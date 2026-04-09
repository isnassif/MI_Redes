"""
broker.py — Serviço de integração central
==========================================
Portas:
  UDP 5000 — sensores publicam telemetria
  TCP 5001 — sensores e atuadores se registram e mantêm conexão viva
  TCP 5002 — clientes assinam tópicos e enviam comandos
"""

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

UDP_PORT     = 5000
TCP_REG_PORT = 5001
TCP_SUB_PORT = 5002

# Locks separados por responsabilidade para evitar contenção desnecessária
devices_lock = threading.Lock()
sensors:   dict[str, dict] = {}
actuators: dict[str, dict] = {}

shared_values_lock = threading.Lock()
shared_values_per_sensor: dict[str, float] = {}  # último valor de cada sensor
shared_values: dict[str, float] = {}             # mediana canônica por tipo

actuator_state_lock = threading.Lock()
actuator_state: dict = {
    "limitador_ativo":    False,
    "limit_speed":        320.0,
    "resfriamento_ativo": False,
}

subscribers_lock = threading.Lock()
subscribers: dict[str, list[socket.socket]] = defaultdict(list)

last_values_lock = threading.Lock()
last_values: dict[str, dict] = {}


def recalc_shared_value(stype: str, registered_ids: set = None) -> None:
    """
    Recalcula a mediana canônica para um tipo de sensor.
    Passa registered_ids quando já estiver dentro de devices_lock
    para evitar re-aquisição (threading.Lock não é reentrante).
    """
    if registered_ids is None:
        with devices_lock:
            registered_ids = {sid for sid, e in sensors.items() if e["type"] == stype}

    with shared_values_lock:
        vals = [v for sid, v in shared_values_per_sensor.items() if sid in registered_ids]
        if vals:
            shared_values[stype] = sorted(vals)[len(vals) // 2]
        else:
            shared_values.pop(stype, None)


def recalc_actuator_state(acts: list = None) -> None:
    """
    Recalcula o estado global dos atuadores.
    - limitador: vence o limite mais restritivo entre os ativos
    - resfriamento: ativo se qualquer um estiver ativo (lógica OR)
    Passa acts quando já estiver dentro de devices_lock.
    """
    if acts is None:
        with devices_lock:
            acts = list(actuators.values())

    lim_active  = False
    lim_speed   = 320.0
    resf_active = False

    for a in acts:
        astate = a.get("state", {})
        if a["type"] == "limitador" and astate.get("active", False):
            lim_active = True
            lim_speed  = min(lim_speed, float(astate.get("limit", 320.0)))
        elif a["type"] == "resfriamento" and astate.get("active", False):
            resf_active = True

    with actuator_state_lock:
        actuator_state["limitador_ativo"]    = lim_active
        actuator_state["limit_speed"]        = lim_speed if lim_active else 320.0
        actuator_state["resfriamento_ativo"] = resf_active


def get_state_for_sensor(stype: str) -> dict:
    """Retorna apenas as chaves de estado relevantes para o tipo de sensor."""
    with actuator_state_lock:
        if stype == "velocidade":
            return {
                "limitador_ativo": actuator_state["limitador_ativo"],
                "limit_speed":     actuator_state["limit_speed"],
            }
        elif stype == "temperatura":
            return {"resfriamento_ativo": actuator_state["resfriamento_ativo"]}
    return {}


def send_to_all_clients(payload: dict) -> None:
    """Envia um evento para todos os clientes conectados (ex: device_list, actuator_disconnected)."""
    msg  = (json.dumps(payload) + "\n").encode()
    dead = []

    with subscribers_lock:
        # Deduplica sockets — um cliente pode estar em vários tópicos
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
    """Notifica todos os clientes da lista atualizada de dispositivos."""
    with devices_lock:
        payload = {
            "event":     "device_list",
            "sensors":   [{"id": e["id"], "type": e["type"]} for e in sensors.values()],
            "actuators": [{"id": e["id"], "type": e["type"]} for e in actuators.values()],
        }
    send_to_all_clients(payload)


def broadcast(topic: str, payload: dict) -> None:
    """Envia telemetria apenas para os clientes assinantes do tópico."""
    msg  = (json.dumps(payload) + "\n").encode()
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
    """Remove sockets com falha de todas as listas de assinantes."""
    if not dead:
        return
    with subscribers_lock:
        for sock in dead:
            for lst in subscribers.values():
                if sock in lst:
                    lst.remove(sock)


def _push_state_to_sensors(actuator_type: str) -> None:
    """
    Empurra o estado atual dos atuadores para os sensores afetados via TCP.
    Chamado sempre que um atuador muda de estado ou desconecta.
    """
    sensor_map         = {"limitador": "velocidade", "resfriamento": "temperatura"}
    target_sensor_type = sensor_map.get(actuator_type, "")

    if not target_sensor_type:
        return

    with devices_lock:
        affected = [e for e in sensors.values() if e["type"] == target_sensor_type]

    sstate = get_state_for_sensor(target_sensor_type)
    msg    = (json.dumps({"state": sstate}) + "\n").encode()

    for sensor_entry in affected:
        try:
            sensor_entry["sock"].sendall(msg)
        except OSError:
            pass  # falhas silenciosas; o heartbeat identifica a conexão morta


def handle_udp() -> None:
    """
    Recebe telemetria UDP dos sensores em loop contínuo.
    Atualiza o valor canônico apenas para sensores registrados via TCP.
    O broadcast para clientes acontece independente do registro — bug conhecido (T10).
    """
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

            if stype and valor is not None and sid:
                with devices_lock:
                    is_registered = sid in sensors
                if is_registered:
                    with shared_values_lock:
                        shared_values_per_sensor[sid] = float(valor)
                    recalc_shared_value(stype)

            # Salva e repassa para clientes assinantes
            topic = f"sensor/{sid}"
            with last_values_lock:
                last_values[topic] = payload
            broadcast(topic, payload)

            if stype:
                broadcast(f"sensor/type/{stype}", payload)

        except (json.JSONDecodeError, OSError):
            pass


def handle_device_connection(conn: socket.socket, addr: tuple) -> None:
    """
    Gerencia o ciclo de vida de um sensor ou atuador conectado:
    registro → estado inicial → heartbeat loop → limpeza no finally.
    O bloco finally garante remoção do dispositivo em qualquer cenário de saída.
    """
    entry = None
    kind  = None
    dtype = None

    try:
        # Lê mensagem de registro com timeout de 10s
        raw = b""
        conn.settimeout(10)
        while b"\n" not in raw:
            chunk = conn.recv(512)
            if not chunk:
                return
            raw += chunk
        conn.settimeout(None)

        msg   = json.loads(raw.split(b"\n")[0])
        kind  = msg.get("register")
        dtype = msg.get("type", "unknown")
        did   = msg.get("id") or f"{dtype}-{uuid.uuid4().hex[:6]}"

        entry = {"id": did, "type": dtype, "kind": kind, "sock": conn, "addr": addr, "state": {}}

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

        # Confirma registro
        conn.sendall((json.dumps({"registered": True, "id": did}) + "\n").encode())

        # Envia estado inicial ao sensor para evitar divergência na entrada
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

        # Heartbeat loop — timeout de 30s; envia ping ao detectar inatividade
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
                            # Aproveita o ping para enviar estado e canônico atualizados
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
                        # Atuadores enviam {"status": ...} após executar um comando
                        try:
                            upd = json.loads(line.decode())
                            if kind == "atuador" and "status" in upd:
                                entry["state"] = upd["status"]
                                recalc_actuator_state()
                                logging.info("Estado atuador %s atualizado: %s", did, upd["status"])
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
        # Limpeza garantida — único ponto de remoção de dispositivos
        if entry is not None:
            did = entry["id"]

            # Remoção dentro do lock; operações que adquirem devices_lock
            # ficam fora para evitar deadlock
            with devices_lock:
                if kind == "sensor":
                    sensors.pop(did, None)
                    logging.info("Sensor desconectado: id=%s type=%s", did, dtype)
                    with shared_values_lock:
                        shared_values_per_sensor.pop(did, None)
                    remaining_ids = {sid for sid, e in sensors.items() if e["type"] == dtype}

                elif kind == "atuador":
                    actuators.pop(did, None)
                    logging.info("Atuador desconectado: id=%s type=%s", did, dtype)
                    remaining_ids = None

            if kind == "sensor":
                recalc_shared_value(dtype, registered_ids=remaining_ids)

            elif kind == "atuador":
                recalc_actuator_state()
                _push_state_to_sensors(dtype)  # libera sensores do estado restrito

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
    """Servidor TCP 5001 — aceita conexões de sensores e atuadores."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", TCP_REG_PORT))
    srv.listen(50)
    logging.info("TCP dispositivos :%d", TCP_REG_PORT)

    while True:
        conn, addr = srv.accept()
        threading.Thread(target=handle_device_connection, args=(conn, addr), daemon=True).start()


def handle_client_connection(conn: socket.socket, addr: tuple) -> None:
    """
    Gerencia a conexão de um cliente.
    Ao conectar, envia device_list automaticamente.
    Aceita: subscribe, list_devices, command.
    """
    subscribed = []
    logging.info("Cliente conectado %s:%d", *addr)

    try:
        # Envia lista de dispositivos imediatamente ao conectar
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

                    # Envia último valor conhecido de cada tópico assinado imediatamente
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
                            targets = [e for e in actuators.values() if e["type"] == target_type]

                    if not targets:
                        logging.warning("Comando sem destino: target_id=%s target_type=%s", target_id, target_type)
                        continue

                    # Atualiza estado otimisticamente antes da confirmação do atuador
                    for e in targets:
                        e["state"] = data
                    recalc_actuator_state()

                    for e in targets:
                        _push_state_to_sensors(e["type"])

                    payload_bytes = (json.dumps({"command": data}) + "\n").encode()
                    for e in targets:
                        try:
                            e["sock"].sendall(payload_bytes)
                            logging.info("Cmd → atuador id=%s type=%s data=%s", e["id"], e["type"], data)
                        except OSError:
                            logging.warning("Atuador %s inacessível no envio do comando", e["id"])

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
    """Servidor TCP 5002 — aceita conexões de clientes."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", TCP_SUB_PORT))
    srv.listen(50)
    logging.info("TCP clientes :%d", TCP_SUB_PORT)

    while True:
        conn, addr = srv.accept()
        threading.Thread(target=handle_client_connection, args=(conn, addr), daemon=True).start()


def status_reporter() -> None:
    """Loga o estado completo do sistema a cada 15 segundos para diagnóstico."""
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
    logging.info("=== BROKER INICIANDO ===")

    for fn in (handle_udp, handle_tcp_devices, handle_tcp_clients, status_reporter):
        threading.Thread(target=fn, daemon=True, name=fn.__name__).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Broker encerrado pelo usuário.")
