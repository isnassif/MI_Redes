<nav id="sumario-completo">
  <h2>Sumário</h2>
  <ul>
    <li><a href="#descricao-geral">Descrição Geral do Projeto</a></li>
    <li><a href="#arquitetura">Arquitetura do Sistema</a>
      <ul>
        <li><a href="#broker">Broker — Serviço Central de Integração</a></li>
        <li><a href="#sensores">Sensores Virtuais</a></li>
        <li><a href="#atuadores">Atuadores</a></li>
        <li><a href="#cliente">Cliente Terminal</a></li>
      </ul>
    </li>
    <li><a href="#comunicacao">Comunicação entre Componentes</a>
      <ul>
        <li><a href="#udp">Telemetria via UDP</a></li>
        <li><a href="#tcp">Registro, Controle e Assinatura via TCP</a></li>
      </ul>
    </li>
    <li><a href="#protocolo">Protocolo e Formato das Mensagens</a>
      <ul>
        <li><a href="#handshake">Handshake de Registro</a></li>
        <li><a href="#catalogo">Catálogo de Mensagens</a></li>
        <li><a href="#encapsulamento">Encapsulamento e Parsing</a></li>
      </ul>
    </li>
    <li><a href="#concorrencia">Concorrência e Sincronização</a></li>
    <li><a href="#interacao">Interação via Cliente Terminal</a></li>
    <li><a href="#confiabilidade">Confiabilidade e Tratamento de Falhas</a></li>
    <li><a href="#docker">Emulação com Docker</a></li>
    <li><a href="#execucao">Como Executar</a></li>
    <li><a href="#equipe">Equipe</a></li>
  </ul>
</nav>

---

<section id="descricao-geral">
<h2>Descrição Geral do Projeto</h2>

<div align="center">
  <br>
  <strong>Sistema distribuído de telemetria veicular em execução</strong>
  <br><br>
</div>

Este projeto implementa um **sistema distribuído de telemetria veicular** com arquitetura de broker central e comunicação por publish-subscribe. Sensores virtuais publicam leituras contínuas de velocidade, temperatura, combustível e óleo; atuadores intervêm remotamente no comportamento dos sensores; e um cliente terminal monitora tudo em tempo real e envia comandos.

A arquitetura de broker resolve o problema de **alto acoplamento** ponto-a-ponto: nenhum componente precisa conhecer os outros diretamente. Sensores publicam, atuadores aguardam comandos, e clientes assinam tópicos — toda a coordenação passa pelo broker. Qualquer componente pode entrar ou sair da rede sem derrubar os demais, e todos reconectam automaticamente. O projeto foi desenvolvido em Python 3 sem dependências externas e containerizado com Docker para execução em múltiplas máquinas.

</section>

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

<section id="broker">
<h3>Broker — Serviço Central de Integração</h3>

O `broker.py` é o único componente que conhece todos os outros. Ele recebe telemetria UDP dos sensores, mantém conexões TCP persistentes com sensores e atuadores, e serve clientes assinantes — tudo em threads paralelas. Internamente, mantém dicionários `sensors` e `actuators` protegidos por `threading.Lock`, recalcula o estado agregado dos atuadores a cada mudança (limite mais restritivo entre limitadores; OR entre resfriamentos) e empurra esse estado imediatamente para os sensores afetados.

</section>

<section id="sensores">
<h3>Sensores Virtuais</h3>

Cada sensor simula a física de um componente real: temperatura aquece com a velocidade e resfria com o atuador; óleo desgasta mais em temperaturas altas; combustível consome proporcionalmente à velocidade. Cada processo opera com duas threads — `keepalive_loop` (TCP com o broker) e `publish_loop` (telemetria UDP a cada 1 ms) — para que a rede TCP nunca bloqueie a publicação.

| Arquivo | Tipo | Unidade | Faixa |
|---|---|---|---|
| `sensor_velocidade.py` | `velocidade` | km/h | 0 – 320 |
| `sensor_temperatura.py` | `temperatura` | °C | 60 – 145 |
| `sensor_combustivel.py` | `combustivel` | % | 0 – 100 |
| `sensor_oleo.py` | `oleo` | % | 0 – 100 |

</section>

<section id="atuadores">
<h3>Atuadores</h3>

Atuadores não publicam telemetria — apenas aguardam comandos do broker e notificam seu estado após cada mudança via `{"status": {...}}`. O broker usa essa notificação para recalcular o estado global e propagar para os sensores.

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

<section id="comunicacao">
<h2>Comunicação entre Componentes</h2>

<section id="udp">
<h3>Telemetria via UDP (porta 5000)</h3>

Sensores publicam a cada 1 ms via UDP — sem handshake, sem confirmação, sem controle de fluxo. Para telemetria contínua de alta frequência isso é vantagem: um pacote perdido é irrelevante quando o próximo chega em 1 ms. O broker só processa telemetria de sensores previamente registrados via TCP, descartando pacotes de IDs desconhecidos.

```json
{ "id": "velocidade-a3f9c1", "type": "velocidade", "data": { "valor": 143.7, "unidade": "km/h" }, "ts": 1716500123.441 }
```

</section>

<section id="tcp">
<h3>Registro, Controle e Assinatura via TCP (portas 5001 e 5002)</h3>

A porta 5001 serve três propósitos simultâneos durante toda a vida de um dispositivo: o handshake de registro inicial, o heartbeat bidirecional (ping/pong a cada 30s para detectar conexões zumbi), e o canal de push ativo de estado do broker para os sensores. A conexão é mantida aberta permanentemente.

A porta 5002 é exclusiva para clientes: ao conectar, recebem a lista de dispositivos ativos e podem assinar tópicos de sensores para receber telemetria em streaming, ou enviar comandos para atuadores especificando `target_id` ou `target_type`.

O broker não enfileira telemetria para clientes — mantém apenas o `last_value` de cada tópico e faz broadcast do mais recente, evitando crescimento de memória com clientes lentos.

</section>
</section>

---

<section id="protocolo">
<h2>Protocolo e Formato das Mensagens</h2>

<section id="handshake">
<h3>Handshake de Registro</h3>

Todo dispositivo ao conectar na porta 5001 envia imediatamente uma mensagem de registro. O campo `id` é opcional — o broker gera um UUID se ausente. Para sensores, a resposta inclui o estado atual dos atuadores e o valor canônico do tipo, para que o sensor não comece divergente das instâncias já conectadas.

**Sensor → Broker:**
```json
{ "register": "sensor", "type": "velocidade", "id": "velocidade-a3f9c1" }
```

**Broker → Sensor:**
```json
{ "registered": true, "id": "velocidade-a3f9c1", "state": { "limitador_ativo": false, "limit_speed": 320.0 }, "shared_value": 157.3 }
```

Quando um atuador muda de estado, o broker empurra imediatamente o novo estado para os sensores afetados (`limitador` → `velocidade`; `resfriamento` → `temperatura`):

```json
{ "state": { "limitador_ativo": true, "limit_speed": 120.0 }, "shared_value": 98.3 }
```

</section>

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
| Broker → Cliente (TCP 5002) | Telemetria / dispositivos / eventos | `id/type/data/ts`, `event: device_list`, `event: actuator_disconnected` |
| Cliente → Broker (TCP 5002) | Comando | `command: {target_id\|target_type, data}` |

**Fluxo completo — ativação do limitador:**
```
Cliente → Broker:   {"command": {"target_id": "limitador-b2e4f7", "data": {"active": true, "limit": 120}}}
Broker  → Atuador:  {"command": {"active": true, "limit": 120}}
Atuador → Broker:   {"status": {"active": true, "limit": 120.0}}
Broker  → Sensores: {"state": {"limitador_ativo": true, "limit_speed": 120.0}, "shared_value": 87.4}
```

</section>

<section id="encapsulamento">
<h3>Encapsulamento e Parsing</h3>

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

Todo parsing é encapsulado em `try/except json.JSONDecodeError` — mensagens malformadas são descartadas sem encerrar a conexão. Campos ausentes são sempre acessados com `.get()` e valores padrão explícitos.

</section>
</section>

---

<section id="concorrencia">
<h2>Concorrência e Sincronização</h2>

<div align="center">
 <br>
  <strong>Modelo de threading — threads daemon por conexão</strong>
  <br><br>
</div>

O broker roda quatro threads permanentes desde a startup, mais uma thread daemon por conexão aceita:

| Thread permanente | Função |
|---|---|
| `handle_udp` | Recepção de telemetria UDP |
| `handle_tcp_devices` | `accept()` de sensores e atuadores (porta 5001) |
| `handle_tcp_clients` | `accept()` de clientes (porta 5002) |
| `status_reporter` | Log de estado a cada 15s |

Cinco locks protegem conjuntos distintos de dados compartilhados (`devices_lock`, `shared_values_lock`, `actuator_state_lock`, `subscribers_lock`, `last_values_lock`). Como `threading.Lock` não é reentrante, funções que operam dentro de um lock calculam os dados necessários e operam fora para evitar deadlock.

O broker mantém um **valor canônico** por tipo de sensor — a mediana dos valores recebidos de todas as instâncias daquele tipo — e o empurra de volta para os sensores, forçando convergência gradual. A mediana foi escolhida em vez da média por ser resistente a outliers: um sensor com valor anômalo não distorce o canônico. Os sensores aplicam o valor canônico com interpolação suave ao recebê-lo:

```python
state["velocidade"] += (float(sv) - state["velocidade"]) * 0.8
```

</section>

---

<section id="interacao">
<h2>Interação via Cliente Terminal</h2>

<div align="center">
  <br>
  <strong>Monitoramento ao vivo com gráfico ASCII de série temporal</strong>
  <br><br>
</div>

O cliente permite selecionar remotamente qualquer sensor conectado e visualizar seus dados em tempo real, com atualização a 10 Hz. Para cada sensor monitorado são exibidos: valor atual colorido por nível de alerta, barra de progresso, latência de entrega em ms, e gráfico de série temporal em ASCII com os últimos 60 valores.

```
  Velocidade 1  (velocidade)
    143.7 km/h  ████████████░░░░░░░░░░  lag: 12ms
  ┌────────────────────────────────────────────────────────────┐
  │                              ▂▃▄▅▆▇█▆▄▂        ▃▄▅▆▄▂▁   │
  └────────────────────────────────────────────────────────────┘
```

Sensores desconectados durante o monitoramento são marcados com `⚠ ERRO NO SENSOR`. O mesmo terminal permite enviar comandos para atuadores — ativar o limitador com um valor em km/h, ou ligar/desligar o resfriamento — selecionando um atuador específico ou todos do tipo.

</section>

---

<section id="confiabilidade">
<h2>Confiabilidade e Tratamento de Falhas</h2>

**Desconexão de sensor:** o broker remove o sensor, recalcula a mediana sem ele e envia `device_list` atualizada para todos os clientes. O cliente exibe `⚠ ERRO NO SENSOR` imediatamente.

**Desconexão de atuador ativo:** caso crítico — sem tratamento, os sensores ficariam restritos indefinidamente. O broker trata isso no bloco `finally` da conexão: recalcula o estado agregado sem o atuador e empurra imediatamente o novo estado para os sensores afetados. Clientes recebem um evento `actuator_disconnected`.

**Reconexão automática:** todos os componentes detectam desconexão quando `recv()` retorna vazio ou `send()` lança `OSError` e reconectam a cada 3 segundos automaticamente, preservando o estado local.

**Timeout e keepalive:** timeout de 35s no `recv()` TCP dos dispositivos. Ao disparar, enviam `ping\n` — sem resposta, encerram e reconectam. O broker usa timeout de 30s e envia `ping\n` ativamente.

</section>

---

<section id="docker">
<h2>Emulação com Docker</h2>

<div align="center">
  <br>
  <strong>Múltiplos contêineres em execução simultânea</strong>
  <br><br>
</div>

Cada componente tem seu próprio `Dockerfile` baseado em `python:3.11-slim`. A variável `BROKER_HOST` é o único ponto de configuração para apontar qualquer componente para um broker em qualquer endereço de rede.

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY atuador_limitador.py .
ENV BROKER_HOST=localhost
CMD ["python", "-u", "atuador_limitador.py"]
```

O `docker-compose.yml` orquestra o ambiente completo. Para escalar horizontalmente e testar convergência:

```bash
docker compose up --build
docker compose up --scale sensor_velocidade_1=3
```

</section>

---

<section id="execucao">
<h2>Como Executar</h2>

**Sem Docker** (Python 3.9+, sem dependências externas):
```bash
python broker.py
python sensor_velocidade.py
python sensor_temperatura.py
python sensor_combustivel.py
python sensor_oleo.py
python atuador_limitador.py
python atuador_resfriamento.py
python cliente.py
```

**Com Docker Compose:**
```bash
docker compose up --build
python cliente.py  # BROKER_HOST=localhost por padrão
```

| Variável | Padrão | Descrição |
|---|---|---|
| `BROKER_HOST` | `localhost` | IP ou hostname do broker |
| `SENSOR_ID` | `<tipo>-<uuid>` | ID único — gerado automaticamente se ausente |
| `ACTUATOR_ID` | `<tipo>-<uuid>` | ID único — gerado automaticamente se ausente |

</section>

---

<section id="equipe">
<h2>Equipe</h2>

Desenvolvido como projeto da disciplina de **Redes de Computadores / Sistemas Distribuídos — UEFS, 2025**.

| Nome | GitHub |
|---|---|
| — | — |
| — | — |
| — | — |

</section>

---

<div align="center">
<sub>Feito com 🏎 e muitos <code>threading.Lock</code> — UEFS 2025</sub>
</div>
