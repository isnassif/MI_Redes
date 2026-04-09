"""
atuador_limitador.py — Atuador de limitador de velocidade
==========================================================
Aguarda comandos do broker e notifica seu estado via {"status": {...}}.
Não publica telemetria — apenas reage a comandos.

Comandos aceitos:
  { "command": { "active": true,  "limit": 150 } }
  { "command": { "active": false } }
"""

import socket, json, time, os, sys, threading, uuid

BROKER_HOST   = os.getenv("BROKER_HOST", "localhost")
TCP_REG_PORT  = 5001
ACTUATOR_TYPE = "limitador"
ACTUATOR_ID   = os.getenv("ACTUATOR_ID", f"{ACTUATOR_TYPE}-{uuid.uuid4().hex[:6]}")

state      = {"active": False, "limit": 320.0}
state_lock = threading.Lock()


def register(tcp_sock: socket.socket) -> bool:
    tcp_sock.sendall((json.dumps({
        "register": "atuador", "type": ACTUATOR_TYPE, "id": ACTUATOR_ID,
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
    """Notifica o broker do estado atual para propagar aos sensores afetados."""
    with state_lock:
        status = {"active": state["active"], "limit": state["limit"]}
    try:
        tcp_sock.sendall((json.dumps({"status": status}) + "\n").encode())
    except OSError:
        pass


def command_loop(tcp_sock: socket.socket, stop: threading.Event) -> None:
    """Processa comandos recebidos do broker e notifica estado após cada mudança."""
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

                    cmd    = msg.get("command", {})
                    active = cmd.get("active", True)
                    limit  = float(cmd.get("limit", 320))

                    with state_lock:
                        state["active"] = active
                        state["limit"]  = limit if active else 320.0

                    status = "ATIVADO" if active else "DESATIVADO"
                    print(f"\n  \033[93m[{ACTUATOR_ID}] {status}"
                          f" — limite: {state['limit']:.0f} km/h\033[0m", flush=True)

                    # Notifica o broker imediatamente para propagar aos sensores
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
                tcp_sock.close(); time.sleep(3); continue

            print(f"  \033[92m✔ Registrado no broker\033[0m  (ID: {ACTUATOR_ID})\n")

            # Envia estado inicial para o broker conhecer a condição de partida
            send_status(tcp_sock)

            stop = threading.Event()
            threading.Thread(target=command_loop, args=(tcp_sock, stop), daemon=True).start()
            stop.wait()

        except ConnectionRefusedError:
            print("  Broker indisponível. Tentando em 3s...", flush=True)
            time.sleep(3); continue
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
