"""
sensor_temperatura.py — Sensor de temperatura do motor
=======================================================
Publica leituras de temperatura (°C) via UDP a cada 1ms.
Recebe push de estado do broker (resfriamento) via TCP.
"""

import socket, json, time, random, os, sys, threading, uuid

BROKER_HOST  = os.getenv("BROKER_HOST", "localhost")
UDP_PORT     = 5000
TCP_REG_PORT = 5001
SENSOR_TYPE  = "temperatura"
SENSOR_ID    = os.getenv("SENSOR_ID", f"{SENSOR_TYPE}-{uuid.uuid4().hex[:6]}")
INTERVALO_S  = 0.001

state = {
    "temperatura":        90.0,
    "resfriamento_ativo": False,
    "velocidade_ref":     80.0,   # velocidade interna usada para calcular aquecimento
}
state_lock    = threading.Lock()
init_received = threading.Event()


def apply_broker_msg(msg: dict) -> None:
    """Aplica estado recebido do broker (resfriamento ativo, valor canônico)."""
    broker_state = msg.get("state", {})
    sv           = msg.get("shared_value")
    with state_lock:
        if "resfriamento_ativo" in broker_state:
            state["resfriamento_ativo"] = bool(broker_state["resfriamento_ativo"])
        if sv is not None:
            if not init_received.is_set():
                state["temperatura"] = float(sv)
            else:
                state["temperatura"] += (float(sv) - state["temperatura"]) * 0.8
    init_received.set()


def simular() -> float:
    """
    Simula física de temperatura:
    - aquece proporcionalmente à velocidade interna
    - resfria -10°C/tick quando o atuador está ativo
    - perde -1°C/tick para o ambiente
    - faixa: 60–145°C
    """
    with state_lock:
        state["velocidade_ref"] += random.uniform(-30, 40)
        state["velocidade_ref"]  = max(0.0, min(state["velocidade_ref"], 320.0))
        calor    = (state["velocidade_ref"] / 320) * 5.0
        cooling  = -10.0 if state["resfriamento_ativo"] else 0.0
        ambiente = -1.0
        ruido    = random.uniform(-1.5, 2.5)
        state["temperatura"] += calor + cooling + ambiente + ruido
        state["temperatura"]  = max(60.0, min(state["temperatura"], 145.0))
        return round(state["temperatura"], 2)


def register(tcp_sock: socket.socket) -> bool:
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
    """Mantém TCP vivo e aplica pushes de estado do broker."""
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
    init_received.wait(timeout=5.0)
    while not stop.is_set():
        time.sleep(INTERVALO_S)
        valor = simular()
        try:
            udp_sock.sendto(json.dumps({
                "id": SENSOR_ID, "type": SENSOR_TYPE,
                "data": {"valor": valor, "unidade": "°C"}, "ts": time.time(),
            }).encode(), (BROKER_HOST, UDP_PORT))
        except OSError:
            pass


_last_res_state: dict = {"ativo": None}

def apply_broker_msg_and_print(msg: dict) -> None:
    """Aplica mensagem e imprime quando o estado do resfriamento muda."""
    old_res = _last_res_state["ativo"]
    apply_broker_msg(msg)
    with state_lock:
        new_res = state["resfriamento_ativo"]
    if new_res != old_res:
        _last_res_state["ativo"] = new_res
        txt = ("\033[96mRESFRIAMENTO ATIVADO\033[0m"
               if new_res else "\033[90mResfriamento DESATIVADO\033[0m")
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
