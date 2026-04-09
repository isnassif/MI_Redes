"""
sensor_oleo.py — Sensor de nível de óleo
=========================================
Publica nível de óleo (%) via UDP a cada 1ms.
O desgaste aumenta com a temperatura simulada internamente.
Não recebe push de atuador — apenas sincroniza o valor canônico.
"""

import socket, json, time, random, os, sys, threading, uuid

BROKER_HOST  = os.getenv("BROKER_HOST", "localhost")
UDP_PORT     = 5000
TCP_REG_PORT = 5001
SENSOR_TYPE  = "oleo"
SENSOR_ID    = os.getenv("SENSOR_ID", f"{SENSOR_TYPE}-{uuid.uuid4().hex[:6]}")
INTERVALO_S  = 0.001

state      = {"oleo": 100.0, "temperatura_ref": 90.0}
state_lock = threading.Lock()
init_received = threading.Event()


def apply_broker_msg(msg: dict) -> None:
    """Aplica o valor canônico recebido do broker com convergência suave (0.5)."""
    sv = msg.get("shared_value")
    with state_lock:
        if sv is not None:
            if not init_received.is_set():
                state["oleo"] = float(sv)
            else:
                state["oleo"] += (float(sv) - state["oleo"]) * 0.5
    init_received.set()


def simular() -> float:
    """
    Drena óleo com taxa base + fator extra proporcional à temperatura acima de 100°C.
    Nunca sobe.
    """
    with state_lock:
        state["temperatura_ref"] += random.uniform(-0.5, 0.8)
        state["temperatura_ref"]  = max(60.0, min(state["temperatura_ref"], 145.0))
        fator_temp = max(0.0, (state["temperatura_ref"] - 100) / 100)
        drain = 0.0001 + fator_temp * 0.0001
        state["oleo"] = max(0.0, state["oleo"] - drain)
        return round(state["oleo"], 4)


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
    """Mantém TCP vivo e aplica mensagens do broker."""
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
                        apply_broker_msg(json.loads(line.decode()))
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
                "data": {"valor": valor, "unidade": "%"}, "ts": time.time(),
            }).encode(), (BROKER_HOST, UDP_PORT))
        except OSError:
            pass


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
