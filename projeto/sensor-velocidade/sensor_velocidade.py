"""
sensor_velocidade.py — Sensor de velocidade
============================================
Publica leituras de velocidade (km/h) via UDP a cada 1ms.
Recebe push de estado do broker (limitador) via TCP.
"""

import socket, json, time, random, os, sys, threading, uuid

BROKER_HOST  = os.getenv("BROKER_HOST", "localhost")
UDP_PORT     = 5000
TCP_REG_PORT = 5001
SENSOR_TYPE  = "velocidade"
SENSOR_ID    = os.getenv("SENSOR_ID", f"{SENSOR_TYPE}-{uuid.uuid4().hex[:6]}")
INTERVALO_S  = 0.001

state = {
    "velocidade":      80.0,
    "limit_speed":     320.0,
    "limitador_ativo": False,
}
state_lock    = threading.Lock()
init_received = threading.Event()  # aguarda o primeiro push do broker antes de publicar


def apply_broker_msg(msg: dict) -> None:
    """Aplica o estado recebido do broker (limitador, valor canônico)."""
    broker_state = msg.get("state", {})
    sv           = msg.get("shared_value")
    with state_lock:
        if "limitador_ativo" in broker_state:
            state["limitador_ativo"] = bool(broker_state["limitador_ativo"])
        if "limit_speed" in broker_state:
            state["limit_speed"] = float(broker_state["limit_speed"])
        if sv is not None:
            if not init_received.is_set():
                state["velocidade"] = float(sv)      # adoção imediata na primeira sync
            else:
                state["velocidade"] += (float(sv) - state["velocidade"]) * 0.8  # convergência gradual
    init_received.set()


def simular() -> float:
    """Avança a simulação de velocidade com ruído e aplica o limitador se ativo."""
    with state_lock:
        target = random.uniform(0, 320)
        if state["limitador_ativo"]:
            target = min(target, state["limit_speed"])
        state["velocidade"] += (target - state["velocidade"]) * 0.4
        state["velocidade"] += random.uniform(-20, 20)
        teto = state["limit_speed"] if state["limitador_ativo"] else 320.0
        state["velocidade"] = max(0.0, min(state["velocidade"], teto))
        return round(state["velocidade"], 2)


def register(tcp_sock: socket.socket) -> bool:
    """Envia registro ao broker e aguarda confirmação."""
    tcp_sock.sendall((json.dumps({
        "register": "sensor", "type": SENSOR_TYPE, "id": SENSOR_ID,
    }) + "\n").encode())
    raw = b""
    tcp_sock.settimeout(10)
    while b"\n" not in raw:
        chunk = tcp_sock.recv(256)
        if not chunk:
            return False
        raw += chunk
    tcp_sock.settimeout(None)
    return json.loads(raw.split(b"\n")[0]).get("registered", False)


def keepalive_loop(tcp_sock: socket.socket, stop: threading.Event) -> None:
    """
    Mantém a conexão TCP viva e processa mensagens do broker.
    Responde pings com ping e aplica pushes de estado.
    """
    buffer = b""
    tcp_sock.settimeout(35)
    try:
        while not stop.is_set():
            try:
                chunk = tcp_sock.recv(512)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    if line == b"ping":
                        tcp_sock.sendall(b"ping\n")
                        continue
                    try:
                        apply_broker_msg_and_print(json.loads(line.decode()))
                    except json.JSONDecodeError:
                        pass
            except socket.timeout:
                try:
                    tcp_sock.sendall(b"ping\n")
                except OSError:
                    break
    except OSError:
        pass
    finally:
        stop.set()


def publish_loop(udp_sock: socket.socket, stop: threading.Event) -> None:
    """Publica telemetria UDP a cada 1ms após receber o primeiro sync do broker."""
    init_received.wait(timeout=5.0)
    while not stop.is_set():
        time.sleep(INTERVALO_S)
        valor = simular()
        try:
            udp_sock.sendto(json.dumps({
                "id": SENSOR_ID, "type": SENSOR_TYPE,
                "data": {"valor": valor, "unidade": "km/h"}, "ts": time.time(),
            }).encode(), (BROKER_HOST, UDP_PORT))
        except OSError:
            pass


_last_lim_state: dict = {"ativo": None, "speed": None}

def apply_broker_msg_and_print(msg: dict) -> None:
    """Aplica mensagem do broker e imprime no terminal quando o estado do limitador muda."""
    old_lim = _last_lim_state["ativo"]
    old_spd = _last_lim_state["speed"]
    apply_broker_msg(msg)
    with state_lock:
        new_lim = state["limitador_ativo"]
        new_spd = state["limit_speed"]
    if new_lim != old_lim or new_spd != old_spd:
        _last_lim_state["ativo"] = new_lim
        _last_lim_state["speed"] = new_spd
        txt = (f"\033[93mLIMITADOR ATIVADO ≤{new_spd:.0f} km/h\033[0m"
               if new_lim else "\033[90mLimitador DESATIVADO — livre\033[0m")
        print(f"\n  [{SENSOR_ID}] {txt}", flush=True)


def main() -> None:
    print(f"Sensor \033[96m{SENSOR_ID}\033[0m iniciando → broker {BROKER_HOST}")
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    while True:
        try:
            tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            tcp_sock.connect((BROKER_HOST, TCP_REG_PORT))
            init_received.clear()

            if not register(tcp_sock):
                print("Falha no registro. Tentando novamente...")
                tcp_sock.close(); time.sleep(3); continue

            print(f"  \033[92m✔ Registrado no broker\033[0m  (ID: {SENSOR_ID})\n")
            init_received.clear()
            stop = threading.Event()
            for fn, args in [
                (keepalive_loop, (tcp_sock, stop)),
                (publish_loop,   (udp_sock, stop)),
            ]:
                threading.Thread(target=fn, args=args, daemon=True).start()
            stop.wait()

        except ConnectionRefusedError:
            print("  Broker indisponível. Tentando em 3s...", flush=True)
            time.sleep(3); continue
        except KeyboardInterrupt:
            print(f"\n\033[90mSensor {SENSOR_ID} encerrado.\033[0m")
            sys.exit(0)
        finally:
            try:
                tcp_sock.close()
            except Exception:
                pass

        print("  Desconectado. Reconectando em 3s...", flush=True)
        time.sleep(3)


if __name__ == "__main__":
    main()
