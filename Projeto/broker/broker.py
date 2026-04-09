import socket
import threading
import json
import time
import logging
import uuid
from collections import defaultdict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [BROKER] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

UDP_PORT     = 5000   # Telemetria UDP (sensores → broker)
TCP_REG_PORT = 5001   # Registro e heartbeat de dispositivos (TCP)
TCP_SUB_PORT = 5002   # Clientes assinantes (TCP)

devices_lock = threading.Lock()
sensors:   dict[str, dict] = {}
actuators: dict[str, dict] = {}

shared_values_lock = threading.Lock()
shared_values_per_sensor: dict[str, float] = {}  # sensor_id   → último valor recebido
shared_values: dict[str, float] = {}             # sensor_type → mediana canônica


def recalc_shared_value(stype: str, registered_ids: set = None) -> None:
   if registered_ids is None:
        # Sem lock externo: buscamos os IDs registrados agora
        with devices_lock:
            registered_ids = {sid for sid, e in sensors.items() if e["type"] == stype}

    with shared_values_lock:
        # Filtra apenas os valores de sensores atualmente conectados
        vals = [v for sid, v in shared_values_per_sensor.items() if sid in registered_ids]
        if vals:
            # Mediana: ordena e pega o elemento do meio
            shared_values[stype] = sorted(vals)[len(vals) // 2]
        else:
            # Sem sensores do tipo, remove o valor canônico
            shared_values.pop(stype, None)


actuator_state_lock = threading.Lock()
actuator_state: dict = {
    "limitador_ativo":    False,   # algum limitador ativo?
    "limit_speed":        320.0,   # velocidade máxima efetiva (km/h)
    "resfriamento_ativo": False,   # algum resfriamento ativo?
}


def recalc_actuator_state(acts: list = None) -> None:
    if acts is None:
        with devices_lock:
            acts = list(actuators.values())

    lim_active  = False
    lim_speed   = 320.0   # começa no máximo; diminui se houver limitador ativo
    resf_active = False

    for a in acts:
        astate = a.get("state", {})
        if a["type"] == "limitador":
            if astate.get("active", False):
                lim_active = True
                # Limite mais restritivo entre todos os limitadores ativos
                lim_speed = min(lim_speed, float(astate.get("limit", 320.0)))
        elif a["type"] == "resfriamento":
            # OR: basta um ativo para ativar o resfriamento global
            if astate.get("active", False):
                resf_active = True

    with actuator_state_lock:
        actuator_state["limitador_ativo"]    = lim_active
        actuator_state["limit_speed"]        = lim_speed if lim_active else 320.0
        actuator_state["resfriamento_ativo"] = resf_active


def get_state_for_sensor(stype: str) -> dict:
    with actuator_state_lock:
        if stype == "velocidade":
            return {
                "limitador_ativo": actuator_state["limitador_ativo"],
                "limit_speed":     actuator_state["limit_speed"],
            }
        elif stype == "temperatura":
            return {
                "resfriamento_ativo": actuator_state["resfriamento_ativo"],
            }
    return {}

subscribers_lock = threading.Lock()
subscribers: dict[str, list[socket.socket]] = defaultdict(list)

last_values_lock = threading.Lock()
last_values: dict[str, dict] = {}


def send_to_all_clients(payload: dict) -> None:
    msg = (json.dumps(payload) + "\n").encode()
    dead = []

    with subscribers_lock:
        # Deduplica: um cliente pode estar em vários tópicos
        all_socks = set()
        for lst in subscribers.values():
            all_socks.update(lst)

    for sock in all_socks:
        try:
            sock.sendall(msg)
        except OSError:
            dead.append(sock)

    _remove_dead(dead)


def send_device_list_to_all() -> None:
    with devices_lock:
        payload = {
            "event":     "device_list",
            "sensors":   [{"id": e["id"], "type": e["type"]} for e in sensors.values()],
            "actuators": [{"id": e["id"], "type": e["type"]} for e in actuators.values()],
        }
    send_to_all_clients(payload)


def broadcast(topic: str, payload: dict) -> None:
    msg = (json.dumps(payload) + "\n").encode()
    dead = []

    with subscribers_lock:
        socks = list(subscribers.get(topic, []))

    for sock in socks:
        try:
            sock.sendall(msg)
        except OSError:
            dead.append(sock)

    _remove_dead(dead)


def _remove_dead(dead: list) -> None:
    """Remove sockets mortos de todas as listas de assinantes."""
    if not dead:
        return
    with subscribers_lock:
        for sock in dead:
            for lst in subscribers.values():
                if sock in lst:
                    lst.remove(sock)


# ──────────────────────────────────────────────────────────
# Handler UDP — telemetria dos sensores
# ──────────────────────────────────────────────────────────

def handle_udp() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", UDP_PORT))
    logging.info("UDP telemetria :%d", UDP_PORT)

    while True:
        try:
            data, _ = sock.recvfrom(4096)
            payload = json.loads(data.decode())

            sid   = payload.get("id", "")
            stype = payload.get("type", "")
            valor = payload.get("data", {}).get("valor")

            # Só processa sensores registrados via TCP
            # (ignora pacotes UDP de conexões antigas ou IDs desconhecidos)
            if stype and valor is not None and sid:
                with devices_lock:
                    is_registered = sid in sensors
                if is_registered:
                    with shared_values_lock:
                        shared_values_per_sensor[sid] = float(valor)
                    recalc_shared_value(stype)

            # Salva último valor e faz broadcast para clientes interessados
            topic = f"sensor/{sid}"
            with last_values_lock:
                last_values[topic] = payload
            broadcast(topic, payload)

            # Broadcast também por tipo (ex: "sensor/type/velocidade")
            if stype:
                broadcast(f"sensor/type/{stype}", payload)

        except (json.JSONDecodeError, OSError):
            pass


# ──────────────────────────────────────────────────────────
# Handler TCP — registro e heartbeat de dispositivos
# ──────────────────────────────────────────────────────────

def _push_state_to_sensors(actuator_type: str) -> None:
    sensor_map = {"limitador": "velocidade", "resfriamento": "temperatura"}
    target_sensor_type = sensor_map.get(actuator_type, "")

    if not target_sensor_type:
        return   # tipo de atuador desconhecido

    with devices_lock:
        affected = [e for e in sensors.values() if e["type"] == target_sensor_type]

    sstate = get_state_for_sensor(target_sensor_type)
    msg = (json.dumps({"state": sstate}) + "\n").encode()

    for sensor_entry in affected:
        try:
            sensor_entry["sock"].sendall(msg)
        except OSError:
            pass   # falhas silenciosas; heartbeat corrige na próxima iteração


def handle_device_connection(conn: socket.socket, addr: tuple) -> None:
    entry = None   # entrada no dicionário; None até o registro ser concluído
    kind  = None   # "sensor" ou "atuador"
    dtype = None   # tipo específico: "velocidade", "limitador", etc.

    try:
        raw = b""
        conn.settimeout(10)   # timeout para o handshake inicial
        while b"\n" not in raw:
            chunk = conn.recv(512)
            if not chunk:
                return   # conexão fechada antes de completar o registro
            raw += chunk
        conn.settimeout(None)

        msg   = json.loads(raw.split(b"\n")[0])
        kind  = msg.get("register")                                  # "sensor" ou "atuador"
        dtype = msg.get("type", "unknown")                           # tipo do dispositivo
        did   = msg.get("id") or f"{dtype}-{uuid.uuid4().hex[:6]}"  # ID; gera se não enviado

        entry = {
            "id":    did,
            "type":  dtype,
            "kind":  kind,
            "sock":  conn,
            "addr":  addr,
            "state": {},   # estado interno; preenchido por atuadores
        }

        with devices_lock:
            if kind == "sensor":
                sensors[did] = entry
                logging.info("Sensor  registrado: id=%s type=%s addr=%s:%d", did, dtype, *addr)
            elif kind == "atuador":
                actuators[did] = entry
                logging.info("Atuador registrado: id=%s type=%s addr=%s:%d", did, dtype, *addr)
            else:
                logging.warning("Registro inválido '%s' de %s:%d", kind, *addr)
                return

        send_device_list_to_all()

        conn.sendall((json.dumps({"registered": True, "id": did}) + "\n").encode())

        if kind == "sensor":
            init_state = get_state_for_sensor(dtype)
            with shared_values_lock:
                canon = shared_values.get(dtype)
            init_msg: dict = {"state": init_state}
            if canon is not None:
                init_msg["shared_value"] = canon
            try:
                conn.sendall((json.dumps(init_msg) + "\n").encode())
            except OSError:
                pass

        conn.settimeout(30)
        buffer = b""

        while True:
            try:
                chunk = conn.recv(256)
                if not chunk:
                    break
                buffer += chunk

                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue

                    if line == b"ping":
                        if kind == "sensor":
                            sstate = get_state_for_sensor(dtype)
                            with shared_values_lock:
                                canon = shared_values.get(dtype)
                            resp: dict = {"pong": True, "state": sstate}
                            if canon is not None:
                                resp["shared_value"] = canon
                            conn.sendall((json.dumps(resp) + "\n").encode())
                        else:
                            conn.sendall(b"pong\n")

                    else:
                        try:
                            upd = json.loads(line.decode())
                            if kind == "atuador" and "status" in upd:
                                entry["state"] = upd["status"]

                                recalc_actuator_state()
                                logging.info(
                                    "Estado atuador %s atualizado: %s", did, upd["status"]
                                )

                                _push_state_to_sensors(dtype)

                        except json.JSONDecodeError:
                            pass

            except socket.timeout:
                try:
                    conn.sendall(b"ping\n")
                except OSError:
                    break 

    except (ConnectionResetError, BrokenPipeError, OSError, json.JSONDecodeError):
        pass

    finally:

        if entry is not None:
            did = entry["id"]

            with devices_lock:
                if kind == "sensor":
                    sensors.pop(did, None)
                    logging.info("Sensor desconectado: id=%s type=%s", did, dtype)

                    with shared_values_lock:
                        shared_values_per_sensor.pop(did, None)
                    remaining_ids = {
                        sid for sid, e in sensors.items() if e["type"] == dtype
                    }

                elif kind == "atuador":
                    actuators.pop(did, None)
                    logging.info("Atuador desconectado: id=%s type=%s", did, dtype)
                    remaining_ids = None

            if kind == "sensor":
                recalc_shared_value(dtype, registered_ids=remaining_ids)

            elif kind == "atuador":
                recalc_actuator_state()

                _push_state_to_sensors(dtype)

                with actuator_state_lock:
                    new_state = dict(actuator_state)

                send_to_all_clients({
                    "event":          "actuator_disconnected",
                    "id":             did,
                    "type":           dtype,
                    "actuator_state": new_state,
                })

            send_device_list_to_all()

        conn.close()


def handle_tcp_devices() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", TCP_REG_PORT))
    srv.listen(50)
    logging.info("TCP dispositivos :%d", TCP_REG_PORT)

    while True:
        conn, addr = srv.accept()
        threading.Thread(
            target=handle_device_connection,
            args=(conn, addr),
            daemon=True
        ).start()

def handle_client_connection(conn: socket.socket, addr: tuple) -> None:

    subscribed = []
    logging.info("Cliente conectado %s:%d", *addr)

    try:
        with devices_lock:
            device_list = {
                "event":     "device_list",
                "sensors":   [{"id": e["id"], "type": e["type"]} for e in sensors.values()],
                "actuators": [{"id": e["id"], "type": e["type"]} for e in actuators.values()],
            }
        conn.sendall((json.dumps(device_list) + "\n").encode())

        buffer = b""
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buffer += chunk

            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if not line.strip():
                    continue

                try:
                    msg = json.loads(line.decode())
                except json.JSONDecodeError:
                    continue

                if "subscribe" in msg:
                    topics = msg["subscribe"]
                    if isinstance(topics, str):
                        topics = [topics]

                    with subscribers_lock:
                        for t in topics:
                            if conn not in subscribers[t]:
                                subscribers[t].append(conn)
                                subscribed.append(t)

                    logging.info("Cliente %s:%d inscrito em: %s", *addr, topics)

                    for t in topics:
                        with last_values_lock:
                            val = last_values.get(t)
                        if val:
                            try:
                                conn.sendall((json.dumps(val) + "\n").encode())
                            except OSError:
                                pass

                elif msg.get("list_devices"):
                    with devices_lock:
                        resp = {
                            "event":     "device_list",
                            "sensors":   [{"id": e["id"], "type": e["type"]} for e in sensors.values()],
                            "actuators": [{"id": e["id"], "type": e["type"]} for e in actuators.values()],
                        }
                    conn.sendall((json.dumps(resp) + "\n").encode())

                elif "command" in msg:
                    cmd         = msg["command"]
                    data        = cmd.get("data", {})
                    target_id   = cmd.get("target_id")
                    target_type = cmd.get("target_type")

                    targets = []
                    with devices_lock:
                        if target_id:
                            e = actuators.get(target_id)
                            if e:
                                targets = [e]
                        elif target_type:
                            targets = [
                                e for e in actuators.values()
                                if e["type"] == target_type
                            ]

                    if not targets:
                        logging.warning(
                            "Comando sem destino: target_id=%s target_type=%s",
                            target_id, target_type
                        )
                        continue

                    for e in targets:
                        e["state"] = data
                    recalc_actuator_state()

                    for e in targets:
                        _push_state_to_sensors(e["type"])

                    payload_bytes = (json.dumps({"command": data}) + "\n").encode()
                    for e in targets:
                        try:
                            e["sock"].sendall(payload_bytes)
                            logging.info(
                                "Cmd → atuador id=%s type=%s data=%s",
                                e["id"], e["type"], data
                            )
                        except OSError:
                            logging.warning(
                                "Atuador %s inacessível no envio do comando", e["id"]
                            )

    except (ConnectionResetError, BrokenPipeError, OSError):
        pass

    finally:
        with subscribers_lock:
            for t in subscribed:
                if conn in subscribers.get(t, []):
                    subscribers[t].remove(conn)
        conn.close()
        logging.info("Cliente desconectado %s:%d", *addr)


def handle_tcp_clients() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", TCP_SUB_PORT))
    srv.listen(50)
    logging.info("TCP clientes :%d", TCP_SUB_PORT)

    while True:
        conn, addr = srv.accept()
        threading.Thread(
            target=handle_client_connection,
            args=(conn, addr),
            daemon=True
        ).start()


def status_reporter() -> None:
    while True:
        time.sleep(15)

        with devices_lock:
            s = [(e["id"], e["type"]) for e in sensors.values()]
            a = [(e["id"], e["type"]) for e in actuators.values()]

        with subscribers_lock:
            nsub = sum(len(v) for v in subscribers.values())

        with actuator_state_lock:
            astate = dict(actuator_state)

        logging.info(
            "Sensores: %s | Atuadores: %s | Clientes: %d | Estado atuadores: %s",
            s, a, nsub, astate
        )



if __name__ == "__main__":
    logging.info("=== BROKER INICIANDO (v3) ===")

    for fn in (handle_udp, handle_tcp_devices, handle_tcp_clients, status_reporter):
        threading.Thread(target=fn, daemon=True, name=fn.__name__).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Broker encerrado pelo usuário.")
