"""
testes.py — Testes de software do sistema de telemetria distribuída
"""

import socket
import json
import time
import threading
import unittest
import statistics
import random

# Configuração
BROKER_HOST  = "localhost"
UDP_PORT     = 5000
TCP_DEV_PORT = 5001   # sensores e atuadores
TCP_CLI_PORT = 5002   # clientes

# ==================== Helpers ====================

def tcp_connect(port: int, timeout: float = 5.0) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect((BROKER_HOST, port))
    return s

def send_line(sock: socket.socket, obj: dict) -> None:
    sock.sendall((json.dumps(obj) + "\n").encode())

def recv_line(sock: socket.socket, timeout: float = 5.0) -> dict:
    sock.settimeout(timeout)
    buf = b""
    while b"\n" not in buf:
        chunk = sock.recv(1024)
        if not chunk:
            raise ConnectionError("Conexão fechada pelo broker")
        buf += chunk
    return json.loads(buf.split(b"\n")[0])

def register_sensor(sock: socket.socket, sensor_type: str, sensor_id: str) -> dict:
    send_line(sock, {"register": "sensor", "type": sensor_type, "id": sensor_id})
    return recv_line(sock)

def register_actuator(sock: socket.socket, act_type: str, act_id: str) -> dict:
    send_line(sock, {"register": "atuador", "type": act_type, "id": act_id})
    return recv_line(sock)

def send_udp(sensor_id: str, sensor_type: str, valor: float, unidade: str = "") -> None:
    payload = {
        "id":   sensor_id,
        "type": sensor_type,
        "data": {"valor": valor, "unidade": unidade},
        "ts":   time.time(),
    }
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(json.dumps(payload).encode(), (BROKER_HOST, UDP_PORT))
    s.close()

def subscribe_client(sock: socket.socket, topics: list) -> dict:
    device_list = recv_line(sock)
    send_line(sock, {"subscribe": topics})
    return device_list

# ==================== BLOCO 1 — Confiabilidade ====================

class TestConfiabilidade(unittest.TestCase):
    
    def test_01_broker_acessivel_nas_tres_portas(self):
        # Testa UDP (fire-and-forget)
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.sendto(b"ping", (BROKER_HOST, UDP_PORT))
        udp.close()

        # Testa TCP porta de dispositivos
        s1 = tcp_connect(TCP_DEV_PORT)
        self.assertIsNotNone(s1)
        s1.close()

        # Testa TCP porta de clientes
        s2 = tcp_connect(TCP_CLI_PORT)
        self.assertIsNotNone(s2)
        s2.close()

    def test_02_registro_sensor_confirmado(self):
        sock = tcp_connect(TCP_DEV_PORT)
        try:
            resp = register_sensor(sock, "velocidade", "test-vel-01")
            self.assertTrue(resp.get("registered"))
            self.assertEqual(resp.get("id"), "test-vel-01")
        finally:
            sock.close()

    def test_03_registro_atuador_confirmado(self):
        sock = tcp_connect(TCP_DEV_PORT)
        try:
            resp = register_actuator(sock, "limitador", "test-lim-01")
            self.assertTrue(resp.get("registered"))
            self.assertEqual(resp.get("id"), "test-lim-01")
        finally:
            sock.close()

    def test_04_sensor_aparece_no_device_list_do_cliente(self):
        sid = f"test-vel-{random.randint(1000,9999)}"

        dev_sock = tcp_connect(TCP_DEV_PORT)
        try:
            register_sensor(dev_sock, "velocidade", sid)
            time.sleep(0.3)  # aguarda propagação

            cli_sock = tcp_connect(TCP_CLI_PORT)
            try:
                device_list = recv_line(cli_sock)
                sensor_ids = [s["id"] for s in device_list.get("sensors", [])]
                self.assertIn(sid, sensor_ids)
            finally:
                cli_sock.close()
        finally:
            dev_sock.close()

    def test_05_desconexao_remove_sensor_da_lista(self):
        sid = f"test-oleo-{random.randint(1000,9999)}"

        dev_sock = tcp_connect(TCP_DEV_PORT)
        register_sensor(dev_sock, "oleo", sid)
        time.sleep(0.3)

        dev_sock.close()  # simula queda
        time.sleep(1.5)   # broker detecta e remove

        cli_sock = tcp_connect(TCP_CLI_PORT)
        try:
            device_list = recv_line(cli_sock)
            sensor_ids = [s["id"] for s in device_list.get("sensors", [])]
            self.assertNotIn(sid, sensor_ids)
        finally:
            cli_sock.close()

    def test_06_reconexao_de_sensor(self):
        sid = f"test-comb-{random.randint(1000,9999)}"

        s1 = tcp_connect(TCP_DEV_PORT)
        r1 = register_sensor(s1, "combustivel", sid)
        self.assertTrue(r1.get("registered"))
        s1.close()
        time.sleep(1.0)

        s2 = tcp_connect(TCP_DEV_PORT)
        try:
            r2 = register_sensor(s2, "combustivel", sid)
            self.assertTrue(r2.get("registered"))
        finally:
            s2.close()

    def test_07_multiplos_sensores_mesmo_tipo_simultaneos(self):
        N = 5
        sockets = []
        ids = [f"test-temp-multi-{i}" for i in range(N)]

        try:
            for sid in ids:
                s = tcp_connect(TCP_DEV_PORT)
                resp = register_sensor(s, "temperatura", sid)
                self.assertTrue(resp.get("registered"))
                sockets.append(s)

            time.sleep(0.3)

            cli_sock = tcp_connect(TCP_CLI_PORT)
            try:
                device_list = recv_line(cli_sock)
                sensor_ids = [s["id"] for s in device_list.get("sensors", [])]
                for sid in ids:
                    self.assertIn(sid, sensor_ids)
            finally:
                cli_sock.close()
        finally:
            for s in sockets:
                s.close()

    def test_08_cliente_reconecta_apos_perda_de_conexao(self):
        c1 = tcp_connect(TCP_CLI_PORT)
        dl1 = recv_line(c1)
        self.assertEqual(dl1.get("event"), "device_list")
        c1.close()

        time.sleep(0.5)

        c2 = tcp_connect(TCP_CLI_PORT)
        try:
            dl2 = recv_line(c2)
            self.assertEqual(dl2.get("event"), "device_list")
        finally:
            c2.close()

# ==================== BLOCO 2 — Validade ====================

class TestValidade(unittest.TestCase):
    
    def test_09_telemetria_udp_entregue_ao_cliente(self):
        sid   = f"test-vel-udp-{random.randint(1000,9999)}"
        topic = f"sensor/{sid}"

        dev_sock = tcp_connect(TCP_DEV_PORT)
        register_sensor(dev_sock, "velocidade", sid)

        cli_sock = tcp_connect(TCP_CLI_PORT)
        subscribe_client(cli_sock, [topic])
        time.sleep(0.2)

        valor_enviado = round(random.uniform(50, 200), 2)
        send_udp(sid, "velocidade", valor_enviado, "km/h")

        try:
            payload = recv_line(cli_sock, timeout=3.0)
            self.assertEqual(payload.get("id"), sid)
            self.assertAlmostEqual(payload["data"]["valor"], valor_enviado, places=2)
        finally:
            cli_sock.close()
            dev_sock.close()

    def test_12_limitador_propaga_estado_ao_sensor_velocidade(self):
        lim_id = f"test-lim-prop-{random.randint(1000,9999)}"
        vel_id = f"test-vel-prop-{random.randint(1000,9999)}"

        lim_sock = tcp_connect(TCP_DEV_PORT)
        vel_sock = tcp_connect(TCP_DEV_PORT)
        cli_sock = tcp_connect(TCP_CLI_PORT)

        received_states = []

        def listen_sensor():
            vel_sock.settimeout(4.0)
            buf = b""
            try:
                while True:
                    chunk = vel_sock.recv(512)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if line.strip():
                            try:
                                received_states.append(json.loads(line.decode()))
                            except json.JSONDecodeError:
                                pass
            except socket.timeout:
                pass

        try:
            register_actuator(lim_sock, "limitador", lim_id)
            send_line(lim_sock, {"status": {"active": False, "limit": 320.0}})

            register_sensor(vel_sock, "velocidade", vel_id)
            recv_line(vel_sock)  # descarta mensagem inicial

            subscribe_client(cli_sock, [])

            t = threading.Thread(target=listen_sensor, daemon=True)
            t.start()
            time.sleep(0.3)

            send_line(cli_sock, {"command": {
                "target_id": lim_id,
                "data": {"active": True, "limit": 120.0}
            }})

            t.join(timeout=5.0)

            estados_limitador = [
                m.get("state", {}) for m in received_states
                if "state" in m and "limitador_ativo" in m.get("state", {})
            ]
            self.assertTrue(len(estados_limitador) > 0)
            lim_ativo = any(e.get("limitador_ativo") for e in estados_limitador)
            self.assertTrue(lim_ativo)

        finally:
            cli_sock.close()
            lim_sock.close()
            vel_sock.close()

    def test_13_resfriamento_logica_OR(self):
        id1 = f"test-resf-or-1-{random.randint(1000,9999)}"
        id2 = f"test-resf-or-2-{random.randint(1000,9999)}"

        s1 = tcp_connect(TCP_DEV_PORT)
        s2 = tcp_connect(TCP_DEV_PORT)

        try:
            register_actuator(s1, "resfriamento", id1)
            register_actuator(s2, "resfriamento", id2)

            # Um ativo, outro inativo → global ativo
            send_line(s1, {"status": {"active": True}})
            send_line(s2, {"status": {"active": False}})
            time.sleep(0.4)

            temp_id = f"test-temp-or-{random.randint(1000,9999)}"
            temp_sock = tcp_connect(TCP_DEV_PORT)
            try:
                register_sensor(temp_sock, "temperatura", temp_id)
                init = recv_line(temp_sock)
                resf_ativo = init.get("state", {}).get("resfriamento_ativo", False)
                self.assertTrue(resf_ativo)
            finally:
                temp_sock.close()

            # Ambos inativos → global inativo
            send_line(s1, {"status": {"active": False}})
            send_line(s2, {"status": {"active": False}})
            time.sleep(0.4)

            temp_id2 = f"test-temp-or2-{random.randint(1000,9999)}"
            temp_sock2 = tcp_connect(TCP_DEV_PORT)
            try:
                register_sensor(temp_sock2, "temperatura", temp_id2)
                init2 = recv_line(temp_sock2)
                resf_ativo2 = init2.get("state", {}).get("resfriamento_ativo", False)
                self.assertFalse(resf_ativo2)
            finally:
                temp_sock2.close()

        finally:
            s1.close()
            s2.close()

    def test_14_limitador_mais_restritivo_entre_multiplos(self):
        id_a = f"test-lim-rest-a-{random.randint(1000,9999)}"
        id_b = f"test-lim-rest-b-{random.randint(1000,9999)}"

        s_a = tcp_connect(TCP_DEV_PORT)
        s_b = tcp_connect(TCP_DEV_PORT)

        try:
            register_actuator(s_a, "limitador", id_a)
            register_actuator(s_b, "limitador", id_b)

            send_line(s_a, {"status": {"active": True,  "limit": 200.0}})
            send_line(s_b, {"status": {"active": True,  "limit": 120.0}})
            time.sleep(0.4)

            vel_id = f"test-vel-rest-{random.randint(1000,9999)}"
            vel_sock = tcp_connect(TCP_DEV_PORT)
            try:
                register_sensor(vel_sock, "velocidade", vel_id)
                init = recv_line(vel_sock)
                limit_speed = init.get("state", {}).get("limit_speed", 320.0)
                self.assertAlmostEqual(limit_speed, 120.0, places=1)  # menor limite vence
            finally:
                vel_sock.close()
        finally:
            s_a.close()
            s_b.close()

    def test_15_desconexao_atuador_libera_estado(self):
        lim_id = f"test-lim-disc-{random.randint(1000,9999)}"
        vel_id = f"test-vel-disc-{random.randint(1000,9999)}"

        lim_sock = tcp_connect(TCP_DEV_PORT)
        vel_sock = tcp_connect(TCP_DEV_PORT)

        received = []

        def listen():
            vel_sock.settimeout(5.0)
            buf = b""
            try:
                while True:
                    chunk = vel_sock.recv(512)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if line.strip() and line.strip() != b"ping":
                            try:
                                received.append(json.loads(line.decode()))
                            except json.JSONDecodeError:
                                pass
            except socket.timeout:
                pass

        try:
            register_actuator(lim_sock, "limitador", lim_id)
            send_line(lim_sock, {"status": {"active": True, "limit": 80.0}})
            time.sleep(0.3)

            register_sensor(vel_sock, "velocidade", vel_id)
            recv_line(vel_sock)

            t = threading.Thread(target=listen, daemon=True)
            t.start()
            time.sleep(0.3)

            lim_sock.close()  # desconecta o atuador

            t.join(timeout=5.0)

            # Deve receber state com limitador_ativo=False
            liberados = [
                m for m in received
                if m.get("state", {}).get("limitador_ativo") == False
            ]
            self.assertTrue(len(liberados) > 0)

        finally:
            try:
                vel_sock.close()
            except Exception:
                pass

    def test_16_sensor_recebe_shared_value_ao_registrar(self):
        sid_base = f"test-temp-base-{random.randint(1000,9999)}"
        sid_novo = f"test-temp-novo-{random.randint(1000,9999)}"

        s_base = tcp_connect(TCP_DEV_PORT)
        try:
            register_sensor(s_base, "temperatura", sid_base)
            send_udp(sid_base, "temperatura", 95.0, "°C")
            time.sleep(0.4)

            s_novo = tcp_connect(TCP_DEV_PORT)
            try:
                register_sensor(s_novo, "temperatura", sid_novo)
                init = recv_line(s_novo)
                self.assertIn("shared_value", init)
            finally:
                s_novo.close()
        finally:
            s_base.close()

# ==================== BLOCO 3 — Desempenho ====================

class TestDesempenho(unittest.TestCase):
    
    def test_17_registro_massivo_simultaneo(self):
        N = 20
        results = [None] * N
        errors = []

        def register_worker(i):
            try:
                s = tcp_connect(TCP_DEV_PORT, timeout=5.0)
                sid = f"test-mass-{i:03d}"
                resp = register_sensor(s, "velocidade", sid)
                results[i] = resp.get("registered", False)
                s.close()
            except Exception as e:
                errors.append(str(e))
                results[i] = False

        threads = [threading.Thread(target=register_worker, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        sucessos = sum(1 for r in results if r is True)
        self.assertEqual(sucessos, N)

    def test_18_taxa_de_entrega_udp_sob_carga(self):
        sid   = f"test-taxa-{random.randint(1000,9999)}"
        topic = f"sensor/{sid}"
        N     = 100

        dev_sock = tcp_connect(TCP_DEV_PORT)
        register_sensor(dev_sock, "velocidade", sid)

        cli_sock = tcp_connect(TCP_CLI_PORT)
        subscribe_client(cli_sock, [topic])
        time.sleep(0.2)

        recebidos = []

        def coletar():
            cli_sock.settimeout(6.0)
            buf = b""
            try:
                while len(recebidos) < N:
                    chunk = cli_sock.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if line.strip():
                            try:
                                recebidos.append(json.loads(line.decode()))
                            except json.JSONDecodeError:
                                pass
            except socket.timeout:
                pass

        t = threading.Thread(target=coletar, daemon=True)
        t.start()

        for i in range(N):
            send_udp(sid, "velocidade", float(i), "km/h")
            time.sleep(0.005)  # ~200 pacotes/s

        t.join(timeout=8.0)

        taxa = len(recebidos) / N
        self.assertGreaterEqual(taxa, 0.95)  # 95% mínimo esperado

        dev_sock.close()
        cli_sock.close()

    def test_19_latencia_broadcast_cliente(self):
        sid   = f"test-lat-{random.randint(1000,9999)}"
        topic = f"sensor/{sid}"

        dev_sock = tcp_connect(TCP_DEV_PORT)
        register_sensor(dev_sock, "velocidade", sid)

        cli_sock = tcp_connect(TCP_CLI_PORT)
        subscribe_client(cli_sock, [topic])
        time.sleep(0.3)

        latencias = []

        for _ in range(20):
            t0 = time.time()
            send_udp(sid, "velocidade", round(random.uniform(0, 320), 2), "km/h")

            cli_sock.settimeout(2.0)
            buf = b""
            try:
                while b"\n" not in buf:
                    buf += cli_sock.recv(1024)
                t1 = time.time()
                latencias.append((t1 - t0) * 1000)
            except socket.timeout:
                pass

            time.sleep(0.05)

        dev_sock.close()
        cli_sock.close()

        self.assertGreater(len(latencias), 15)
        mediana_ms = statistics.median(latencias)
        self.assertLess(mediana_ms, 100.0)  # abaixo de 100ms

    def test_20_multiplos_clientes_recebem_broadcast(self):
        sid   = f"test-multi-cli-{random.randint(1000,9999)}"
        topic = f"sensor/{sid}"
        N_CLI = 5
        valor = round(random.uniform(50, 300), 2)

        dev_sock = tcp_connect(TCP_DEV_PORT)
        register_sensor(dev_sock, "velocidade", sid)

        clientes = []
        for _ in range(N_CLI):
            c = tcp_connect(TCP_CLI_PORT)
            subscribe_client(c, [topic])
            clientes.append(c)

        time.sleep(0.3)
        recebidos = [False] * N_CLI

        def esperar(i, c):
            c.settimeout(3.0)
            buf = b""
            try:
                while b"\n" not in buf:
                    buf += c.recv(1024)
                msg = json.loads(buf.split(b"\n")[0])
                if abs(msg.get("data", {}).get("valor", -1) - valor) < 0.01:
                    recebidos[i] = True
            except (socket.timeout, Exception):
                pass

        threads = [threading.Thread(target=esperar, args=(i, c), daemon=True)
                   for i, c in enumerate(clientes)]
        for t in threads:
            t.start()

        time.sleep(0.1)
        send_udp(sid, "velocidade", valor, "km/h")

        for t in threads:
            t.join(timeout=4.0)

        for c in clientes:
            c.close()
        dev_sock.close()

        self.assertEqual(sum(recebidos), N_CLI)

    def test_21_carga_mista_sensores_e_atuadores(self):
        sockets  = []
        stop_evt = threading.Event()

        try:
            vel_ids  = [f"test-carga-vel-{i}"  for i in range(2)]
            temp_ids = [f"test-carga-temp-{i}" for i in range(2)]
            lim_id   = f"test-carga-lim-0"
            resf_id  = f"test-carga-resf-0"

            for sid in vel_ids:
                s = tcp_connect(TCP_DEV_PORT)
                register_sensor(s, "velocidade", sid)
                sockets.append(s)

            for sid in temp_ids:
                s = tcp_connect(TCP_DEV_PORT)
                register_sensor(s, "temperatura", sid)
                sockets.append(s)

            lim_sock = tcp_connect(TCP_DEV_PORT)
            register_actuator(lim_sock, "limitador", lim_id)
            send_line(lim_sock, {"status": {"active": True, "limit": 160.0}})
            sockets.append(lim_sock)

            resf_sock = tcp_connect(TCP_DEV_PORT)
            register_actuator(resf_sock, "resfriamento", resf_id)
            send_line(resf_sock, {"status": {"active": True}})
            sockets.append(resf_sock)

            def publicar(sid, stype, unidade):
                while not stop_evt.is_set():
                    send_udp(sid, stype, random.uniform(0, 320), unidade)
                    time.sleep(0.01)

            workers = []
            for sid in vel_ids:
                workers.append(threading.Thread(
                    target=publicar, args=(sid, "velocidade", "km/h"), daemon=True))
            for sid in temp_ids:
                workers.append(threading.Thread(
                    target=publicar, args=(sid, "temperatura", "°C"), daemon=True))

            for w in workers:
                w.start()

            time.sleep(3.0)
            stop_evt.set()
            for w in workers:
                w.join(timeout=2.0)

            cli = tcp_connect(TCP_CLI_PORT)
            try:
                dl = recv_line(cli)
                ids_registrados = [s["id"] for s in dl.get("sensors", [])]
                atuadores_registrados = [a["id"] for a in dl.get("actuators", [])]

                for sid in vel_ids + temp_ids:
                    self.assertIn(sid, ids_registrados)

                for aid in [lim_id, resf_id]:
                    self.assertIn(aid, atuadores_registrados)
            finally:
                cli.close()

        finally:
            for s in sockets:
                try:
                    s.close()
                except Exception:
                    pass

if __name__ == "__main__":
    print("=" * 65)
    print("  TESTES DO SISTEMA DE TELEMETRIA DISTRIBUÍDA")
    print("  Certifique-se de que o broker está rodando antes de executar.")
    print("=" * 65)
    unittest.main(verbosity=2)
