import socket
import json
import time
import os
import sys
import threading
import uuid

# Configurações do broker e identificação do atuador
BROKER_HOST   = os.getenv("BROKER_HOST", "localhost")
TCP_REG_PORT  = 5001
ACTUATOR_TYPE = "limitador"
ACTUATOR_ID   = os.getenv("ACTUATOR_ID", f"{ACTUATOR_TYPE}-{uuid.uuid4().hex[:6]}")

# Estado compartilhado do atuador
state = {"active": False, "limit": 320.0}
state_lock = threading.Lock()


def register(tcp_sock: socket.socket) -> bool:
    # Envia pedido de registro
    tcp_sock.sendall((json.dumps({
        "register": "atuador",
        "type": ACTUATOR_TYPE,
        "id":   ACTUATOR_ID,
    }) + "\n").encode())

    # Aguarda resposta do broker
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
    # Envia estado atual
    with state_lock:
        status = {"active": state["active"], "limit": state["limit"]}
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

                # Processa mensagens completas (terminadas em \n)
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue

                    # Keepalive
                    if line in (b"ping", b"pong"):
                        tcp_sock.sendall(b"ping\n")
                        continue

                    # Parse JSON
                    try:
                        msg = json.loads(line.decode())
                    except json.JSONDecodeError:
                        continue

                    # Atualiza estado
                    cmd    = msg.get("command", {})
                    active = cmd.get("active", True)
                    limit  = float(cmd.get("limit", 320))

                    with state_lock:
                        state["active"] = active
                        state["limit"]  = limit if active else 320.0

                    # Log visual
                    status = "ATIVADO" if active else "DESATIVADO"
                    lim_val = state["limit"]
                    print(f"\n  \033[93m[{ACTUATOR_ID}] {status}"
                          f" — limite: {lim_val:.0f} km/h\033[0m", flush=True)

                    send_status(tcp_sock)

            except socket.timeout:
                # Mantém conexão viva
                tcp_sock.sendall(b"ping\n")

    except OSError:
        pass
    finally:
        stop.set()


def main() -> None:
    print(f"Atuador \033[95m{ACTUATOR_ID}\033[0m iniciando → broker {BROKER_HOST}")

    while True:
        try:
            # Conexão TCP
            tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            tcp_sock.connect((BROKER_HOST, TCP_REG_PORT))

            # Registro no broker
            if not register(tcp_sock):
                print("Falha no registro. Tentando novamente...")
                tcp_sock.close()
                time.sleep(3)
                continue

            print(f"  \033[92m✔ Registrado no broker\033[0m  (ID: {ACTUATOR_ID})\n")

            send_status(tcp_sock)

            # Thread de leitura de comandos
            stop = threading.Event()
            threading.Thread(
                target=command_loop,
                args=(tcp_sock, stop),
                daemon=True
            ).start()

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
