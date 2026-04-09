import socket, json, time, os, sys, threading, select, termios, tty, fcntl
from collections import deque

BROKER_HOST  = os.getenv("BROKER_HOST", "localhost")
TCP_SUB_PORT = 5002
GRAPH_W      = 60   # largura do gráfico em colunas
GRAPH_H      = 6    # altura em linhas
HISTORY      = GRAPH_W  # pontos de histórico


class C:
    R     = "\033[0m";  B  = "\033[1m"
    RED   = "\033[91m"; YEL = "\033[93m"; GRN = "\033[92m"
    CYN   = "\033[96m"; BLU = "\033[94m"; MAG = "\033[95m"
    WHT   = "\033[97m"; GRY = "\033[90m"
    BGRED = "\033[41m"; CLR = "\033[H\033[J"


# ── Estado global ────────────────────────────────────────
client_lock = threading.Lock()
live_data:   dict[str, dict]          = {}   # topic → último payload
history:     dict[str, deque]         = {}   # sensor_id → deque de floats
device_list: dict                     = {"sensors": [], "actuators": []}
device_list_updated = threading.Event()
broker_online       = threading.Event()   # sinaliza que há conexão ativa com o broker
running     = True
sock_global = None

# ── Metadados por tipo ───────────────────────────────────
SENSOR_META = {
    "velocidade":  {"unidade": "km/h", "max": 320,  "mid": 200, "high": 280, "invert": False},
    "temperatura": {"unidade": "°C",   "max": 145,  "mid": 105, "high": 120, "invert": False},
    "combustivel": {"unidade": "%",    "max": 100,  "mid": 30,  "high": 15,  "invert": True},
    "oleo":        {"unidade": "%",    "max": 100,  "mid": 25,  "high": 10,  "invert": True},
}

# ── Nomes amigáveis ──────────────────────────────────────
TYPE_LABELS = {
    "velocidade": "Velocidade", "temperatura": "Temperatura",
    "combustivel": "Combustível", "oleo": "Óleo",
    "limitador": "Limitador",   "resfriamento": "Resfriamento",
}

def friendly(did: str, dtype: str, device_kind: str = "sensors") -> str:
    """
    Retorna nome amigável baseado na posição atual do dispositivo na lista viva.
    Sem cache estático: recalcula sempre a partir de device_list.
    - 1 sensor do tipo  → "Velocidade"  (sem número)
    - 2+ sensores       → "Velocidade 1", "Velocidade 2", ...
    - sensor ausente    → usa dtype como fallback
    """
    base = TYPE_LABELS.get(dtype, dtype.capitalize()) if dtype else (did or "?")
    with client_lock:
        devices = [d for d in device_list.get(device_kind, []) if d.get("type") == dtype]
    ids = [d["id"] for d in devices]
    if len(ids) <= 1:
        return base
    try:
        idx = ids.index(did) + 1
        return f"{base} {idx}"
    except ValueError:
        return base


# ── Helpers visuais ──────────────────────────────────────
def cor(meta: dict, value: float) -> str:
    inv = meta.get("invert", False)
    if inv:
        return C.RED if value <= meta["high"] else (C.YEL if value <= meta["mid"] else C.GRN)
    else:
        return C.RED if value >= meta["high"] else (C.YEL if value >= meta["mid"] else C.GRN)

def bar(value: float, max_val: float, width: int = 22) -> str:
    filled = int(max(0.0, min(value / max_val, 1.0)) * width)
    return "█" * filled + "░" * (width - filled)

def hdr(title: str) -> None:
    print(f"\n{C.B}{C.WHT}{'═'*52}{C.R}")
    print(f"{C.B}{C.CYN}  🏎  {title}{C.R}")
    print(f"{C.B}{C.WHT}{'═'*52}{C.R}\n")

def inp(prompt: str) -> str:
    print(f"  {C.CYN}▶  {prompt}{C.R} ", end="", flush=True)
    try:
        return input().strip()
    except (EOFError, KeyboardInterrupt):
        return ""

def send(sock: socket.socket, msg: dict) -> bool:
    try:
        sock.sendall((json.dumps(msg) + "\n").encode())
        return True
    except OSError:
        return False


# ── Gráfico ASCII ────────────────────────────────────────
# Blocos de 8 níveis verticais
BRAILLE_BARS = " ▁▂▃▄▅▆▇█"

def draw_graph(vals: deque, meta: dict, width: int = GRAPH_W, height: int = GRAPH_H) -> list[str]:
    """Retorna lista de strings com o gráfico de série temporal."""
    pts = list(vals)
    if not pts:
        return [" " * width] * height

    lo  = meta.get("min_val", 0.0)
    hi  = float(meta["max"])
    rng = hi - lo or 1.0

    # Normaliza cada ponto para [0, height*8)
    def norm(v):
        return max(0.0, min((v - lo) / rng, 1.0)) * (height * 8 - 1)

    # Preenche até width pontos (mais recentes à direita)
    if len(pts) < width:
        pts = [pts[0]] * (width - len(pts)) + pts
    else:
        pts = pts[-width:]

    normed = [norm(v) for v in pts]

    # Monta matriz [height x width]
    rows = []
    for row in range(height - 1, -1, -1):
        line = ""
        for col_val in normed:
            cell_top    = (row + 1) * 8
            cell_bottom = row * 8
            if col_val >= cell_top:
                line += "█"
            elif col_val <= cell_bottom:
                line += " "
            else:
                frac = col_val - cell_bottom
                idx  = max(0, min(int(frac), 8))
                line += BRAILLE_BARS[idx]
        rows.append(line)
    return rows

def render_graph(sid: str, meta: dict, c_color: str, label: str, valor: float) -> None:
    """Imprime o gráfico de um sensor."""
    with client_lock:
        vals = history.get(sid, deque())

    unidade = meta["unidade"]
    lo      = meta.get("min_val", 0.0)
    hi      = meta["max"]

    # Linha de escala superior
    print(f"  {C.GRY}┌{'─'*GRAPH_W}┐  {C.WHT}{lo:.0f}–{hi:.0f} {unidade}{C.R}")

    rows = draw_graph(vals, meta)
    for i, row in enumerate(rows):
        print(f"  {C.GRY}│{C.R}{c_color}{row}{C.R}{C.GRY}│{C.R}")

    print(f"  {C.GRY}└{'─'*GRAPH_W}┘{C.R}")


# ── Thread receptora ─────────────────────────────────────
def receiver(sock: socket.socket) -> None:
    global running
    buffer = b""
    while running:
        try:
            ready, _, _ = select.select([sock], [], [], 1.0)
            if not ready:
                continue
            chunk = sock.recv(4096)
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line.decode())
                except json.JSONDecodeError:
                    continue

                if payload.get("event") == "device_list":
                    with client_lock:
                        device_list["sensors"]   = payload.get("sensors", [])
                        device_list["actuators"] = payload.get("actuators", [])
                    device_list_updated.set()
                    continue

                sid   = payload.get("id", "")
                stype = payload.get("type", "")
                valor = payload.get("data", {}).get("valor")
                if sid and valor is not None:
                    topic = f"sensor/{sid}"
                    with client_lock:
                        live_data[topic] = payload
                        if sid not in history:
                            history[sid] = deque(maxlen=HISTORY)
                        history[sid].append(float(valor))

        except OSError:
            break   # erro de rede → sai do loop

    # Broker caiu ou conexão perdida: limpa lista de dispositivos e sinaliza
    with client_lock:
        device_list["sensors"]   = []
        device_list["actuators"] = []
    broker_online.clear()   # acorda qualquer tela bloqueada em wait()


# ── Conexão ──────────────────────────────────────────────
def connect(show_waiting: bool = True) -> socket.socket:
    """Tenta conectar ao broker indefinidamente, sem limite de tentativas."""
    attempt = 0
    while True:
        attempt += 1
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5)
            s.connect((BROKER_HOST, TCP_SUB_PORT))
            s.settimeout(None)
            return s
        except (ConnectionRefusedError, OSError):
            if show_waiting:
                print(f"  {C.YEL}⏳ Aguardando broker... (tentativa {attempt}){C.R}", flush=True)
            time.sleep(3)


# ── Telas ────────────────────────────────────────────────
def screen_main(sock: socket.socket) -> str:
    print(C.CLR, end="")
    hdr("PAINEL DE CONTROLE")
    with client_lock:
        sens = list(device_list["sensors"])
        acts = list(device_list["actuators"])

    print(f"  {C.B}Sensores conectados:{C.R}")
    if sens:
        for s in sens:
            print(f"    {C.GRY}•{C.R} {C.CYN}{friendly(s['id'], s['type'])}{C.R}")
    else:
        print(f"    {C.GRY}nenhum{C.R}")

    print(f"\n  {C.B}Atuadores conectados:{C.R}")
    if acts:
        for a in acts:
            print(f"    {C.GRY}•{C.R} {C.MAG}{friendly(a['id'], a['type'], 'actuators')}{C.R}")
    else:
        print(f"    {C.GRY}nenhum{C.R}")

    print(f"\n  {C.B}[1]{C.R}  Monitorar sensores ao vivo")
    print(f"  {C.B}[2]{C.R}  Enviar comando — limitador de velocidade")
    print(f"  {C.B}[3]{C.R}  Enviar comando — resfriamento do motor")
    print(f"  {C.B}[4]{C.R}  Atualizar lista de dispositivos")
    print(f"  {C.B}[0]{C.R}  Sair")
    return inp("Opção")


def screen_select_sensors() -> list[str]:
    print(C.CLR, end="")
    hdr("SELECIONAR SENSORES")
    with client_lock:
        sens = list(device_list["sensors"])
    if not sens:
        print(f"  {C.GRY}Nenhum sensor conectado.{C.R}")
        inp("Enter para voltar")
        return []
    for i, s in enumerate(sens, 1):
        print(f"  {C.B}[{i}]{C.R}  {C.CYN}{friendly(s['id'], s['type'])}{C.R}")
    print(f"  {C.B}[a]{C.R}  Todos")
    print(f"  {C.B}[v]{C.R}  Voltar")
    choice = inp("Sensores (ex: 1 3 ou a)")
    if choice.lower() == "v":
        return []
    if choice.lower() == "a":
        return [s["id"] for s in sens]
    selected = []
    for ch in choice.split():
        try:
            idx = int(ch) - 1
            if 0 <= idx < len(sens):
                selected.append(sens[idx]["id"])
        except ValueError:
            pass
    return selected


def screen_live(sock: socket.socket, sensor_ids: list[str]) -> None:
    if not sensor_ids:
        return
    topics = [f"sensor/{sid}" for sid in sensor_ids]
    send(sock, {"subscribe": topics})

    fd = sys.stdin.fileno()
    try:
        old = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        fl  = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
    except Exception:
        old = fl = None

    try:
        while True:
            try:
                ch = sys.stdin.read(1)
                if ch in ("\n", "\r", "q", "Q"):
                    break
            except (BlockingIOError, IOError):
                pass

            print(C.CLR, end="")
            hdr("MONITORAMENTO AO VIVO")

            with client_lock:
                connected_ids = {s["id"] for s in device_list["sensors"]}
                snapshot      = dict(live_data)

            for sid in sensor_ids:
                topic = f"sensor/{sid}"
                entry = snapshot.get(topic)

                if sid not in connected_ids:
                    label = friendly(sid, "")
                    print(f"  {C.RED}{C.B}⚠ ERRO NO SENSOR  {label}{C.R}\n")
                    continue

                if not entry:
                    print(f"  {C.GRY}[{friendly(sid,'')}] aguardando dados...{C.R}\n")
                    continue

                stype = entry.get("type", "")
                valor = entry["data"]["valor"]
                label = friendly(sid, stype)
                meta  = SENSOR_META.get(stype, {"unidade":"","max":100,"mid":70,"high":90,"invert":False})
                c     = cor(meta, valor)
                b_str = bar(valor, meta["max"])

                invert  = meta.get("invert", False)
                critico = (valor <= meta["high"]) if invert else (valor >= meta["high"])
                alerta  = f"  {C.BGRED}{C.B} ⚠ ALERTA {C.R}" if critico else ""

                lag   = time.time() - entry.get("ts", time.time())
                lag_c = C.RED if lag > 1 else (C.YEL if lag > 0.3 else C.GRN)

                # Cabeçalho do sensor
                print(f"  {C.B}{label}{C.R}  {C.GRY}({stype}){C.R}{alerta}")
                print(f"  {c}{valor:>7.1f} {meta['unidade']:<5}{C.R}  {c}{b_str}{C.R}"
                      f"  {C.GRY}lag:{lag_c}{lag*1000:.0f}ms{C.R}")

                # Gráfico
                render_graph(sid, meta, c, label, valor)
                print()

            print(f"  {C.GRY}[Enter/q] voltar{C.R}")
            time.sleep(0.1)   # atualiza a 10Hz (sensores publicam a 1ms, agregamos aqui)

    finally:
        if old is not None:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        if fl is not None:
            fcntl.fcntl(fd, fcntl.F_SETFL, fl)


def screen_cmd_limitador(sock: socket.socket) -> None:
    print(C.CLR, end="")
    hdr("LIMITADOR DE VELOCIDADE")
    with client_lock:
        acts = [a for a in device_list["actuators"] if a["type"] == "limitador"]
    if not acts:
        print(f"  {C.GRY}Nenhum atuador 'limitador' conectado.{C.R}")
        inp("Enter para voltar"); return

    for i, a in enumerate(acts, 1):
        print(f"    {C.B}[{i}]{C.R}  {C.MAG}{friendly(a['id'], a['type'], 'actuators')}{C.R}")
    print(f"    {C.B}[a]{C.R}  Todos\n    {C.B}[v]{C.R}  Voltar")
    choice = inp("Qual atuador")
    if choice.lower() == "v": return

    targets = []
    if choice.lower() == "a":
        targets = [a["id"] for a in acts]
    else:
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(acts):
                targets = [acts[idx]["id"]]
        except ValueError: pass

    if not targets:
        print(f"  {C.RED}Opção inválida.{C.R}"); time.sleep(1); return

    print(f"\n  {C.B}[1]{C.R}  Ativar\n  {C.B}[2]{C.R}  Desativar")
    action = inp("Ação")
    if action == "1":
        val = inp("Velocidade máxima (km/h)")
        try:
            limit = float(val)
        except ValueError:
            print(f"  {C.RED}Valor inválido.{C.R}"); time.sleep(1); return
        for tid in targets:
            ok = send(sock, {"command": {"target_id": tid, "data": {"active": True, "limit": limit}}})
            print(f"  {friendly(tid,'limitador','actuators')}: {C.GRN+'✔ enviado'+C.R if ok else C.RED+'✘ falha'+C.R}")
    elif action == "2":
        for tid in targets:
            ok = send(sock, {"command": {"target_id": tid, "data": {"active": False}}})
            print(f"  {friendly(tid,'limitador','actuators')}: {C.GRN+'✔ enviado'+C.R if ok else C.RED+'✘ falha'+C.R}")
    time.sleep(1.2)


def screen_cmd_resfriamento(sock: socket.socket) -> None:
    print(C.CLR, end="")
    hdr("RESFRIAMENTO DO MOTOR")
    with client_lock:
        acts = [a for a in device_list["actuators"] if a["type"] == "resfriamento"]
    if not acts:
        print(f"  {C.GRY}Nenhum atuador 'resfriamento' conectado.{C.R}")
        inp("Enter para voltar"); return

    for i, a in enumerate(acts, 1):
        print(f"    {C.B}[{i}]{C.R}  {C.MAG}{friendly(a['id'], a['type'], 'actuators')}{C.R}")
    print(f"    {C.B}[a]{C.R}  Todos\n    {C.B}[v]{C.R}  Voltar")
    choice = inp("Qual atuador")
    if choice.lower() == "v": return

    targets = []
    if choice.lower() == "a":
        targets = [a["id"] for a in acts]
    else:
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(acts):
                targets = [acts[idx]["id"]]
        except ValueError: pass

    if not targets:
        print(f"  {C.RED}Opção inválida.{C.R}"); time.sleep(1); return

    print(f"\n  {C.B}[1]{C.R}  Ativar\n  {C.B}[2]{C.R}  Desativar")
    action = inp("Ação")
    active = {"1": True, "2": False}.get(action)
    if active is None: return

    for tid in targets:
        ok = send(sock, {"command": {"target_id": tid, "data": {"active": active}}})
        print(f"  {friendly(tid,'resfriamento','actuators')}: {C.GRN+'✔ enviado'+C.R if ok else C.RED+'✘ falha'+C.R}")
    time.sleep(1.2)


# ── Main ──────────────────────────────────────────────────
def main() -> None:
    global running, sock_global
    print(C.CLR, end="")
    hdr("CLIENTE — ROTA DAS COISAS")

    first_connect = True

    while running:
        # ── Conecta (ou reconecta) ao broker ────────────────────
        if first_connect:
            print(f"  Conectando ao broker {C.CYN}{BROKER_HOST}:{TCP_SUB_PORT}{C.R}...")
        else:
            print(C.CLR, end="")
            print(f"\n  {C.RED}⚠ Broker desconectado.{C.R} Aguardando reinicialização...", flush=True)

        sock = connect(show_waiting=not first_connect or True)
        sock_global = sock
        broker_online.set()

        print(f"  {C.GRN}✔ {'Reconectado' if not first_connect else 'Conectado'}!{C.R}")
        first_connect = False
        time.sleep(0.5)

        # Reinicia thread receptora para o novo socket
        threading.Thread(target=receiver, args=(sock,), daemon=True).start()
        device_list_updated.wait(timeout=5)

        # ── Loop de menus ────────────────────────────────────────
        while running and broker_online.is_set():
            device_list_updated.clear()
            choice = screen_main(sock)

            if not broker_online.is_set():
                break   # broker caiu durante a navegação no menu

            if choice == "1":
                ids = screen_select_sensors()
                if ids:
                    screen_live(sock, ids)
            elif choice == "2":
                screen_cmd_limitador(sock)
            elif choice == "3":
                screen_cmd_resfriamento(sock)
            elif choice == "4":
                send(sock, {"list_devices": True})
                device_list_updated.wait(timeout=3)
            elif choice == "0":
                running = False
                sock.close()
                print(C.CLR + f"\n  {C.CYN}Até logo! 🏁{C.R}\n")
                sys.exit(0)

        # Sai do loop interno → broker caiu → tenta reconectar
        try:
            sock.close()
        except OSError:
            pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        running = False
        if sock_global:
            sock_global.close()
        print(f"\n  {C.CYN}Encerrado.{C.R}\n")
