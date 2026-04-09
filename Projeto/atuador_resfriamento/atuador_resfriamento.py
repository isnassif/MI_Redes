import socket
import json
import time
import os
import sys
import threading
import uuid

BROKER_HOST   = os.getenv("BROKER_HOST", "localhost")
TCP_REG_PORT  = 5001
ACTUATOR_TYPE = "resfriamento"
ACTUATOR_ID   = os.getenv("ACTUATOR_ID", f"{ACTUATOR_TYPE}-{uuid.uuid4().hex[:6]}")

state = {"active": False}
state_lock = threading.Lock()


def register(tcp_sock: socket.socket) -> bool:
    tcp_sock.sendall((json.dumps({
        "register": "atuador",
        "type": ACTUATOR_TYPE,
        "id":   ACTUATOR_ID,
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


def send_status(tcp_sock: socket.socket) -> None:
    """Notifica o broker do estado atual para que ele atualize o estado agregado."""
    with state_lock:
        status = {"active": state["active"]}
    try:
        tcp_sock.sendall((json.dumps({"status": status}) + "\n").encode())
    except OSError:
        pass


def command_loop(tcp_sock: socket.socket, stop: threading.Event) -> None:
    buffer = b""
    tcp_sock.settimeout(35)
    try:
        while not stop.is_set():
            try:
                chunk = tcp_sock.recv(1024)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue

                    if line in (b"ping", b"pong"):
                        tcp_sock.sendall(b"ping\n")
                        continue

                    try:
                        msg = json.loads(line.decode())
                    except json.JSONDecodeError:
                        continue

                    active = msg.get("command", {}).get("active", True)
                    with state_lock:
                        state["active"] = active

                    status = "ATIVADO" if active else "DESATIVADO"
                    print(f"\n  \033[96m[{ACTUATOR_ID}] Resfriamento {status}\033[0m",
                          flush=True)

                    send_status(tcp_sock)

            except socket.timeout:
                tcp_sock.sendall(b"ping\n")
    except OSError:
        pass
    finally:
        stop.set()



def main() -> None:
    print(f"Atuador \033[95m{ACTUATOR_ID}\033[0m iniciando → broker {BROKER_HOST}")

    while True:
        try:
            tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            tcp_sock.connect((BROKER_HOST, TCP_REG_PORT))

            if not register(tcp_sock):
                print("Falha no registro. Tentando novamente...")
                tcp_sock.close()
                time.sleep(3)
                continue

            print(f"  \033[92m✔ Registrado no broker\033[0m  (ID: {ACTUATOR_ID})\n")

            send_status(tcp_sock)

            stop = threading.Event()
            for fn, args in [
                (command_loop, (tcp_sock, stop)),
            ]:
                threading.Thread(target=fn, args=args, daemon=True).start()
            stop.wait()

        except ConnectionRefusedError:
            print("  Broker indisponível. Tentando em 3s...", flush=True)
            time.sleep(3)
            continue
        except KeyboardInterrupt:
            print(f"\n\033[90mAtuador {ACTUATOR_ID} encerrado.\033[0m")
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
