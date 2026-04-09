<nav id="sumario-completo">
  <h2>Sumário</h2>
  <ul>
    <li><a href="#arquitetura">Arquitetura do Sistema</a>
      <ul>
        <li><a href="#broker">Broker — Serviço Central de Integração</a></li>
        <li><a href="#sensores">Sensores Virtuais</a></li>
        <li><a href="#atuadores">Atuadores</a></li>
        <li><a href="#cliente">Cliente Terminal</a></li>
      </ul>
    </li>
    <li><a href="#estrutura">Estrutura de Diretórios</a></li>
    <li><a href="#pacotes">Pacotes e Dependências</a></li>
    <li><a href="#variaveis">Variáveis de Ambiente</a></li>
    <li><a href="#execucao">Como Executar</a>
      <ul>
        <li><a href="#sem-docker">Sem Docker</a></li>
        <li><a href="#local">Teste local com Docker Compose</a></li>
        <li><a href="#distribuido">Ambiente distribuído — múltiplas máquinas</a></li>
      </ul>
    </li>
    <li><a href="#uso">Como Usar o Cliente</a></li>
    <li><a href="#protocolo">Protocolo de Comunicação</a>
      <ul>
        <li><a href="#catalogo">Catálogo de Mensagens</a></li>
        <li><a href="#fluxo">Fluxo Completo — Ativação do Limitador</a></li>
      </ul>
    </li>
  </ul>
</nav>

---

<section id="arquitetura">
<h2>Arquitetura do Sistema</h2>

<div align="center">
  <br>
  <strong>Arquitetura geral — broker central com sensores, atuadores e clientes</strong>
  <br><br>
</div>

```
┌──────────────────────────────────────────────────────┐
│                      BROKER                          │
│  UDP  :5000  ◄── telemetria dos sensores (~1ms)      │
│  TCP  :5001  ◄►  registro + heartbeat + push estado  │
│  TCP  :5002  ◄►  clientes: subscribe + comandos      │
└──────────────────────────────────────────────────────┘
        ▲  UDP            ▲  TCP            ▲  TCP
   [Sensores]        [Atuadores]        [Clientes]
   velocidade        limitador          terminal
   temperatura       resfriamento
   combustivel
   oleo
```

A arquitetura de broker resolve o problema de **alto acoplamento** ponto-a-ponto: nenhum componente precisa conhecer os outros diretamente. Sensores publicam, atuadores aguardam comandos, e clientes assinam tópicos — toda a coordenação passa pelo broker. Qualquer componente pode entrar ou sair da rede sem derrubar os demais, e todos reconectam automaticamente.

<section id="broker">
<h3>Broker — Serviço Central de Integração</h3>

O `broker.py` é o único componente que conhece todos os outros. Ele recebe telemetria UDP dos sensores, mantém conexões TCP persistentes com sensores e atuadores, e serve clientes assinantes — tudo em threads paralelas. Internamente, mantém dicionários `sensors` e `actuators` protegidos por `threading.Lock`, recalcula o estado agregado dos atuadores a cada mudança (limite mais restritivo entre limitadores; OR entre resfriamentos) e empurra esse estado imediatamente para os sensores afetados.

</section>

<section id="sensores">
<h3>Sensores Virtuais</h3>

Cada sensor simula a física de um componente real: temperatura aquece com a velocidade e resfria com o atuador; óleo desgasta mais em temperaturas altas; combustível consome proporcionalmente à velocidade. Cada processo opera com duas threads — `keepalive_loop` (TCP com o broker) e `publish_loop` (telemetria UDP a cada 1ms) — para que a rede TCP nunca bloqueie a publicação.

| Arquivo | Tipo | Unidade | Faixa |
|---|---|---|---|
| `sensor_velocidade.py` | `velocidade` | km/h | 0 – 320 |
| `sensor_temperatura.py` | `temperatura` | °C | 60 – 145 |
| `sensor_combustivel.py` | `combustivel` | % | 0 – 100 |
| `sensor_oleo.py` | `oleo` | % | 0 – 100 |

</section>

<section id="atuadores">
<h3>Atuadores</h3>

Atuadores não publicam telemetria — apenas aguardam comandos do broker e notificam seu estado após cada mudança via `{"status": {...}}`. O broker usa essa notificação para recalcular o estado global e propagá-lo para os sensores afetados.

| Arquivo | Tipo | Efeito |
|---|---|---|
| `atuador_limitador.py` | `limitador` | Restringe velocidade máxima dos sensores de velocidade |
| `atuador_resfriamento.py` | `resfriamento` | Ativa resfriamento nos sensores de temperatura |

</section>

<section id="cliente">
<h3>Cliente Terminal</h3>

O `cliente.py` é uma aplicação interativa construída com ANSI escape codes. Ao conectar, recebe a lista de dispositivos ativos e permite selecionar sensores para monitoramento ao vivo (gráficos ASCII, barras coloridas por alerta, latência em ms) e enviar comandos para atuadores pelo mesmo terminal.

</section>
</section>

---

<section id="estrutura">
<h2>Estrutura de Diretórios</h2>

```
pbl/
├── broker/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── broker.py
│
├── sensor-velocidade/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── sensor_velocidade.py
│
├── sensor-temperatura/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── sensor_temperatura.py
│
├── sensor-combustivel/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── sensor_combustivel.py
│
├── sensor-oleo/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── sensor_oleo.py
│
├── atuador-limitador/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── atuador_limitador.py
│
├── atuador-resfriamento/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── atuador_resfriamento.py
│
├── cliente/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── cliente.py
│
├── docker-compose.local.yml
├── docker-compose.broker.yml
└── docker-compose.dispositivos.yml
```

</section>

---

<section id="pacotes">
<h2>Pacotes e Dependências</h2>

O projeto **não possui dependências externas**. Utiliza apenas a biblioteca padrão do Python 3 — nenhum `pip install` de terceiros é necessário.

| Módulo | Uso |
|---|---|
| `socket` | Comunicação UDP (telemetria) e TCP (controle e assinatura) |
| `threading` | Threads paralelas por conexão e loops de keepalive |
| `json` | Serialização de todas as mensagens do protocolo |
| `uuid` | Geração de IDs únicos para sensores e atuadores |
| `time` | Timestamps de telemetria e intervalos de reconexão |
| `statistics` | Cálculo da mediana para o valor canônico por tipo de sensor |
| `os` / `sys` | Leitura de variáveis de ambiente e saída padrão |

**Requisitos de ambiente:** Python 3.9 ou superior (execução direta) · Docker 24+ (execução em container).

</section>

---

<section id="variaveis">
<h2>Variáveis de Ambiente</h2>

| Variável | Padrão | Componente | Descrição |
|---|---|---|---|
| `BROKER_HOST` | `localhost` | Todos (exceto broker) | IP ou hostname da máquina onde o broker está rodando |
| `SENSOR_ID` | `<tipo>-<uuid>` | Sensores | ID único do sensor — gerado automaticamente se ausente |
| `ACTUATOR_ID` | `<tipo>-<uuid>` | Atuadores | ID único do atuador — gerado automaticamente se ausente |

</section>

---

<section id="execucao">
<h2>Como Executar</h2>

<section id="sem-docker">
<h3>Sem Docker</h3>

<div align="center">
  <br>
  <strong>Execução direta — um terminal por processo, broker sempre primeiro</strong>
  <br><br>
</div>

Requisito: Python 3.9+. Abra um terminal por processo, na ordem abaixo:

```bash
# 1. Broker (sempre primeiro)
python broker/broker.py

# 2. Sensores (terminais separados)
python sensor-velocidade/sensor_velocidade.py
python sensor-temperatura/sensor_temperatura.py
python sensor-combustivel/sensor_combustivel.py
python sensor-oleo/sensor_oleo.py

# 3. Atuadores (terminais separados)
python atuador-limitador/atuador_limitador.py
python atuador-resfriamento/atuador_resfriamento.py

# 4. Cliente
python cliente/cliente.py
```

Para apontar um componente para um broker em outro endereço:

```bash
BROKER_HOST=192.168.0.10 python sensor-velocidade/sensor_velocidade.py
```

</section>

<section id="local">
<h3>Teste local com Docker Compose</h3>

<div align="center">
  <br>
  <strong>Ambiente completo em uma única máquina — sem nenhum arquivo .py local</strong>
  <br><br>
</div>

O Docker baixa todas as imagens do Docker Hub automaticamente. Nenhum arquivo `.py` precisa estar na máquina.

```bash
# Subir tudo
docker compose -f docker-compose.local.yml up

# Em segundo plano
docker compose -f docker-compose.local.yml up -d

# Ver logs de um serviço específico
docker compose -f docker-compose.local.yml logs -f velocidade-1

# Escalar horizontalmente (ex: 3 sensores de velocidade)
docker compose -f docker-compose.local.yml up --scale velocidade-1=3

# Parar tudo
docker compose -f docker-compose.local.yml down
```

Para o cliente interativo (o `-it` é obrigatório):

```bash
docker run -it --rm \
  --network pbl_pbl-net \
  -e BROKER_HOST=broker \
  SEU_USUARIO/pbl-cliente:latest
```

> O nome da rede `pbl_pbl-net` é gerado automaticamente com base no nome da pasta do projeto. Confirme com `docker network ls` se necessário.

</section>

<section id="distribuido">
<h3>Ambiente distribuído — múltiplas máquinas</h3>

<div align="center">
  <br>
  <strong>Execução distribuída — broker em uma máquina, dispositivos em outras</strong>
  <br><br>
</div>

**Passo 1 — Descobrir o IP da máquina que vai rodar o broker:**

| Sistema | Comando |
|---|---|
| Linux / Mac | `ip a` ou `ifconfig` |
| Windows | `ipconfig` |

**Passo 2 — Na máquina do broker:**

```bash
docker compose -f docker-compose.broker.yml up
```

**Passo 3 — Nas máquinas dos dispositivos**, passando o IP do broker:

```bash
# Linux / Mac
BROKER_HOST=192.168.0.10 docker compose -f docker-compose.dispositivos.yml up

# Windows PowerShell
$env:BROKER_HOST="192.168.0.10"; docker compose -f docker-compose.dispositivos.yml up

# Windows CMD
set BROKER_HOST=192.168.0.10 && docker compose -f docker-compose.dispositivos.yml up
```

**Passo 4 — Cliente** (qualquer máquina com Docker):

```bash
docker run -it --rm \
  -e BROKER_HOST=192.168.0.10 \
  SEU_USUARIO/pbl-cliente:latest
```

</section>
</section>

---

<section id="uso">
<h2>Como Usar o Cliente</h2>

<div align="center">
  <br>
  <strong>Monitoramento ao vivo com gráfico ASCII de série temporal</strong>
  <br><br>
</div>

Ao iniciar, o cliente conecta ao broker e exibe a lista de dispositivos ativos:

```
Dispositivos conectados:
  [1] velocidade-a3f9c1   (velocidade)
  [2] temperatura-b2e4f7  (temperatura)
  [3] limitador-c9d1e2    (limitador)
  [4] resfriamento-f3a8b1 (resfriamento)

Selecione um sensor para monitorar ou um atuador para comandar:
```

**Monitorando um sensor**, o terminal exibe em tempo real (10 Hz):

```
  Velocidade 1  (velocidade)
    143.7 km/h  ████████████░░░░░░░░░░  lag: 12ms
  ┌────────────────────────────────────────────────────────────┐
  │                              ▂▃▄▅▆▇█▆▄▂        ▃▄▅▆▄▂▁   │
  └────────────────────────────────────────────────────────────┘
```

A barra muda de cor conforme o nível de alerta. Sensores desconectados durante o monitoramento são marcados com `⚠ ERRO NO SENSOR` imediatamente.

**Comandando um atuador:**

```
Atuador: limitador-c9d1e2
  [1] Ativar limitador   → define velocidade máxima em km/h
  [2] Desativar limitador
  [3] Aplicar a todos os limitadores conectados

Atuador: resfriamento-f3a8b1
  [1] Ligar resfriamento
  [2] Desligar resfriamento
  [3] Aplicar a todos os resfriamentos conectados
```

</section>

---

<section id="protocolo">
<h2>Protocolo de Comunicação</h2>

Todas as mensagens TCP usam **JSON delimitado por newline** (`\n`) — cada mensagem é uma linha JSON terminada por `\n`. Isso permite parsing incremental sem conhecer o tamanho da mensagem de antemão, lidando corretamente com fragmentação TCP e coalescing:

```python
buffer = b""
while True:
    chunk = sock.recv(512)
    buffer += chunk
    while b"\n" in buffer:
        line, buffer = buffer.split(b"\n", 1)
        msg = json.loads(line.strip().decode())
```

Todo parsing é encapsulado em `try/except json.JSONDecodeError` — mensagens malformadas são descartadas sem encerrar a conexão.

<section id="catalogo">
<h3>Catálogo de Mensagens</h3>

| Direção | Mensagem | Campos principais |
|---|---|---|
| Sensor/Atuador → Broker (TCP 5001) | Registro | `register`, `type`, `id` |
| Broker → Dispositivo (TCP 5001) | Confirmação | `registered`, `id`, `state?`, `shared_value?` |
| Sensor → Broker (UDP 5000) | Telemetria | `id`, `type`, `data`, `ts` |
| Broker → Sensor (TCP 5001) | Push de estado | `state`, `shared_value?` |
| Dispositivo ↔ Broker | Keepalive | `ping` (texto puro) |
| Atuador → Broker (TCP 5001) | Notificação de estado | `status: {active, limit?}` |
| Cliente → Broker (TCP 5002) | Assinatura | `subscribe: [tópicos]` |
| Broker → Cliente (TCP 5002) | Telemetria / eventos | `id/type/data/ts`, `event: device_list`, `event: actuator_disconnected` |
| Cliente → Broker (TCP 5002) | Comando | `command: {target_id\|target_type, data}` |

</section>

<section id="fluxo">
<h3>Fluxo Completo — Ativação do Limitador</h3>

```
Cliente → Broker:   {"command": {"target_id": "limitador-b2e4f7", "data": {"active": true, "limit": 120}}}
Broker  → Atuador:  {"command": {"active": true, "limit": 120}}
Atuador → Broker:   {"status": {"active": true, "limit": 120.0}}
Broker  → Sensores: {"state": {"limitador_ativo": true, "limit_speed": 120.0}, "shared_value": 87.4}
```

</section>
</section>
