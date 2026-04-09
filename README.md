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
        <li><a href="#tcp-dispositivos">Registro e Controle via TCP (porta 5001)</a></li>
        <li><a href="#tcp-clientes">Assinatura e Comandos via TCP (porta 5002)</a></li>
      </ul>
    </li>
    <li><a href="#protocolo">Protocolo de Comunicação (API Remota)</a>
      <ul>
        <li><a href="#handshake">Handshake de Registro</a></li>
        <li><a href="#push-estado">Push de Estado — Broker para Sensores</a></li>
        <li><a href="#mensagens">Catálogo de Mensagens</a></li>
      </ul>
    </li>
    <li><a href="#encapsulamento">Encapsulamento e Formato dos Dados</a></li>
    <li><a href="#concorrencia">Concorrência e Qualidade de Serviço</a>
      <ul>
        <li><a href="#threading">Threading no Broker</a></li>
        <li><a href="#locks">Locks e Seções Críticas</a></li>
        <li><a href="#mediana">Mediana Canônica e Convergência</a></li>
        <li><a href="#qos">Separação de Perfis de Tráfego</a></li>
      </ul>
    </li>
    <li><a href="#interacao">Interação — Cliente Terminal</a></li>
    <li><a href="#confiabilidade">Confiabilidade e Tratamento de Falhas</a></li>
    <li><a href="#testes">Testes</a></li>
    <li><a href="#docker">Emulação com Docker</a></li>
    <li><a href="#execucao">Como Executar</a></li>
    <li><a href="#equipe">Equipe</a></li>
  </ul>
</nav>

---

<section id="descricao-geral">
<h2>Descrição Geral do Projeto</h2>

<div align="center">
  <img src="docs/banner.png" alt="[SUGESTÃO DE IMAGEM] Print de múltiplos terminais lado a lado (use tmux ou split de janelas) mostrando: broker logando registros à esquerda, dois sensores publicando no centro, e o cliente com gráficos ASCII ao vivo à direita — evidencia o sistema distribuído em funcionamento real">
  <br>
  <strong>Sistema distribuído de telemetria veicular em execução</strong>
  <br><br>
</div>

Este projeto implementa um **sistema distribuído de telemetria veicular** baseado em arquitetura de broker central e comunicação assíncrona por publish-subscribe. O sistema simula o monitoramento em tempo real de um veículo de alta performance, com sensores publicando leituras contínuas de velocidade, temperatura do motor, nível de combustível e nível de óleo, e atuadores capazes de intervir no comportamento do veículo remotamente — tudo coordenado por um serviço central de integração.

O problema central que motivou o projeto é o **alto acoplamento** que ocorre em arquiteturas ponto-a-ponto tradicionais: cada cliente precisaria conhecer o endereço de cada sensor, cada sensor precisaria saber quem está ouvindo, e qualquer mudança na topologia exigiria reconfiguração de todos os participantes. Com um broker intermediário, sensores simplesmente publicam dados, atuadores simplesmente aguardam comandos, e clientes simplesmente assinam tópicos — nenhum componente precisa conhecer os demais diretamente.

O sistema lida com um perfil de tráfego muito intenso: sensores publicam a cada **1 milissegundo**, o que equivale a 1.000 mensagens por segundo por sensor. Com quatro tipos de sensores — cada tipo podendo ter múltiplas instâncias simultâneas —, o broker pode receber e processar dezenas de milhares de mensagens por segundo, mantendo a telemetria fluindo para os clientes sem latência perceptível. Para isso, o broker usa threading, locks granulares e uma estratégia deliberada de descarte de dados antigos em vez de enfileiramento.

Além da alta taxa de publicação, o sistema implementa **sincronização entre instâncias do mesmo tipo de sensor**: quando dois sensores de velocidade estão conectados simultaneamente, o broker calcula a mediana dos valores e empurra esse valor canônico de volta para ambos, forçando convergência gradual sem que os sensores precisem se comunicar diretamente entre si.

O projeto foi desenvolvido inteiramente em Python 3, sem dependências externas além da biblioteca padrão, e containerizado com Docker para permitir execução e testes em múltiplas máquinas distintas de forma reproduzível.

</section>

---

<section id="arquitetura">
<h2>Arquitetura do Sistema</h2>

O sistema é composto por quatro tipos de processos independentes que se comunicam exclusivamente através do broker. Essa separação rigorosa de responsabilidades é o que permite escalar qualquer parte do sistema de forma independente — é possível adicionar dez sensores de velocidade sem alterar nenhuma linha do broker, do cliente ou dos atuadores.

<div align="center">
  <img src="docs/arquitetura_geral.png" alt="[SUGESTÃO DE IMAGEM] Diagrama criado no draw.io ou Excalidraw mostrando o broker no centro com três grupos ao redor: à esquerda os quatro tipos de sensores com setas laranja (UDP) e azul (TCP) apontando para o broker; à direita os dois atuadores com setas azuis bidirecionais; abaixo o cliente com setas azuis bidirecionais. Inclua as portas (UDP 5000, TCP 5001, TCP 5002) nas setas correspondentes">
  <br>
  <strong>Arquitetura geral — broker central com sensores, atuadores e clientes</strong>
  <br><br>
</div>

```
┌─────────────────────────────────────────────────────────────────────┐
│                            BROKER                                   │
│                                                                     │
│   UDP  :5000  ◄──── telemetria contínua dos sensores (~1ms)        │
│   TCP  :5001  ◄──►  registro + heartbeat + push de estado          │
│   TCP  :5002  ◄──►  clientes: subscribe + telemetria + comandos    │
│                                                                     │
│   • Agrega valores por tipo usando mediana canônica                 │
│   • Recalcula estado global dos atuadores a cada mudança            │
│   • Faz push imediato de estado para sensores afetados              │
│   • Distribui telemetria apenas para clientes assinantes            │
└─────────────────────────────────────────────────────────────────────┘
         ▲  UDP 5000        ▲  TCP 5001        ▲  TCP 5002
         │                  │                   │
   [Sensores]          [Atuadores]          [Clientes]
   velocidade          limitador            dashboard
   temperatura         resfriamento         terminal
   combustivel
   oleo
```

<section id="broker">
<h3>Broker — Serviço Central de Integração</h3>

O `broker.py` é o coração do sistema. Ele é o único componente que conhece todos os outros e é responsável por três funções distintas e simultâneas: receber telemetria dos sensores via UDP, gerenciar as conexões persistentes de sensores e atuadores via TCP na porta 5001, e servir os clientes assinantes via TCP na porta 5002.

Internamente, o broker mantém dois dicionários principais — `sensors` e `actuators` — que mapeiam o ID de cada dispositivo para sua entrada completa, incluindo o socket TCP ativo, o tipo, e o estado atual. Esses dicionários são protegidos por `threading.Lock` e atualizados atomicamente sempre que um dispositivo conecta ou desconecta.

Uma das responsabilidades mais importantes do broker é o **recálculo do estado agregado dos atuadores**. Quando múltiplos limitadores estão conectados simultaneamente, o broker seleciona o **limite mais restritivo** entre os ativos. Quando múltiplos atuadores de resfriamento estão presentes, a lógica é OR — basta um estar ativo para o resfriamento global ser considerado ativo. Esse recálculo é disparado em qualquer mudança: conexão, desconexão, ou atualização de estado de qualquer atuador.

</section>

<section id="sensores">
<h3>Sensores Virtuais</h3>

Cada sensor é um processo Python independente que simula a física de um componente real do veículo. A simulação não é trivial: cada sensor mantém um estado interno que evolui com ruído estocástico, influência de outros parâmetros do veículo, e restrições físicas. O sensor de temperatura, por exemplo, aquece proporcionalmente à velocidade simulada e resfria quando o atuador de resfriamento está ativo. O sensor de óleo desgasta mais rapidamente quando a temperatura está alta.

| Arquivo | Tipo | Unidade | Faixa | Influências |
|---|---|---|---|---|
| `sensor_velocidade.py` | `velocidade` | km/h | 0 – 320 | Atuador limitador |
| `sensor_temperatura.py` | `temperatura` | °C | 60 – 145 | Velocidade, atuador de resfriamento |
| `sensor_combustivel.py` | `combustivel` | % | 0 – 100 | Velocidade (consumo proporcional) |
| `sensor_oleo.py` | `oleo` | % | 0 – 100 | Temperatura (desgaste maior com calor) |

Cada sensor opera com duas threads internas: `keepalive_loop`, que mantém a conexão TCP com o broker e processa mensagens de push de estado recebidas, e `publish_loop`, que gera e envia telemetria UDP em loop contínuo. Essa separação garante que uma lentidão na rede TCP nunca atrase a publicação de dados, e vice-versa.

</section>

<section id="atuadores">
<h3>Atuadores</h3>

Os atuadores são processos que não publicam telemetria — eles apenas aguardam comandos do broker e notificam seu estado atual. Ao receber um comando, o atuador atualiza seu estado interno, imprime uma mensagem no terminal e envia `{"status": {...}}` de volta ao broker, que usa essa informação para recalcular o estado global e propagar imediatamente para os sensores afetados.

| Arquivo | Tipo | Efeito nos Sensores |
|---|---|---|
| `atuador_limitador.py` | `limitador` | Restringe a velocidade máxima dos sensores de velocidade |
| `atuador_resfriamento.py` | `resfriamento` | Ativa efeito de resfriamento nos sensores de temperatura |

</section>

<section id="cliente">
<h3>Cliente Terminal</h3>

O `cliente.py` é uma aplicação de terminal completa com interface visual em modo texto, construída inteiramente com ANSI escape codes sem dependências externas. Ao conectar, ele recebe imediatamente a lista de dispositivos conectados no broker e pode assinar tópicos de sensores para receber telemetria ao vivo. O monitoramento exibe gráficos de série temporal em ASCII com atualização a 10 Hz, barras de progresso coloridas por nível de alerta, e indicação de latência em milissegundos em tempo real.

</section>
</section>

---

<section id="comunicacao">
<h2>Comunicação entre Componentes</h2>

A escolha de protocolos de transporte foi deliberada e baseada no perfil de cada tipo de dado. O sistema não usa um único protocolo para tudo — ele usa UDP onde a velocidade e o volume são críticos, e TCP onde a confiabilidade e a ordem das mensagens são essenciais.

<section id="udp">
<h3>Telemetria via UDP (porta 5000)</h3>

Sensores publicam leituras a cada 1 milissegundo via UDP. O protocolo foi escolhido especificamente por suas características: sem handshake, sem confirmação de entrega, sem controle de fluxo. Para telemetria contínua de alta frequência, essas são vantagens, não limitações. Se um pacote UDP for perdido, o próximo chega em 1ms — dado que o valor está permanentemente se atualizando, um pacote perdido não representa perda de informação relevante. Usar TCP para telemetria nessa frequência geraria overhead de confirmação completamente desnecessário.

Cada datagrama UDP carrega um payload JSON completo e autocontido, suficiente para identificar o sensor, o tipo de dado, o valor e o instante de geração:

```json
{
  "id":   "velocidade-a3f9c1",
  "type": "velocidade",
  "data": { "valor": 143.7, "unidade": "km/h" },
  "ts":   1716500123.441
}
```

O broker só processa telemetria de sensores **previamente registrados** via TCP. Pacotes UDP de IDs desconhecidos — que podem vir de conexões antigas antes de uma reinicialização do broker — são ignorados silenciosamente.

</section>

<section id="tcp-dispositivos">
<h3>Registro e Controle via TCP (porta 5001)</h3>

A conexão TCP na porta 5001 tem três propósitos simultâneos durante toda a vida de um dispositivo conectado. Primeiro, é por ela que acontece o **handshake de registro** inicial — sem registro confirmado, nenhuma telemetria UDP do sensor é processada. Segundo, ela serve de canal para o **heartbeat bidirecional** (ping/pong a cada 30 segundos), que permite ao broker detectar conexões zumbi que não enviaram FIN TCP. Terceiro, e mais importante, ela é o canal pelo qual o broker faz **push ativo de estado** para os sensores — quando um atuador muda de estado, o broker não espera o próximo ping do sensor para notificá-lo, ele empurra a mudança imediatamente.

A escolha de manter a conexão TCP persistente — em vez de conectar e desconectar a cada mensagem — foi intencional: reduz latência, elimina o overhead de handshake repetido, e permite que o broker saiba exatamente quais dispositivos estão ativos a qualquer momento.

</section>

<section id="tcp-clientes">
<h3>Assinatura e Comandos via TCP (porta 5002)</h3>

Clientes se conectam na porta 5002 e recebem automaticamente a lista de dispositivos ativos. A partir daí, podem assinar tópicos de sensores individuais (ex: `sensor/velocidade-a3f9c1`) ou por tipo (ex: `sensor/type/velocidade`). Tópicos assinados passam a receber telemetria em streaming contínuo enquanto a conexão durar.

O mesmo canal é usado para enviar comandos para atuadores. O cliente especifica o `target_id` (ID de um atuador específico) ou `target_type` (todos os atuadores de um tipo) junto com o payload do comando. O broker valida os alvos, atualiza o estado interno imediatamente (sem esperar confirmação do atuador), propaga para os sensores afetados, e repassa o comando ao(s) atuador(es).

</section>
</section>

---

<section id="protocolo">
<h2>Protocolo de Comunicação (API Remota)</h2>

<section id="handshake">
<h3>Handshake de Registro</h3>

Todo dispositivo, ao conectar na porta 5001, deve enviar imediatamente uma mensagem de registro. O broker tem timeout de 10 segundos para receber esse registro — se não chegar, a conexão é encerrada. O campo `id` é opcional: se ausente, o broker gera um ID único com `uuid4` automaticamente e o inclui na resposta.

**Sensor enviando registro:**
```json
{ "register": "sensor", "type": "velocidade", "id": "velocidade-a3f9c1" }
```

**Atuador enviando registro:**
```json
{ "register": "atuador", "type": "limitador", "id": "limitador-b2e4f7" }
```

**Broker respondendo para sensor (inclui estado atual e valor canônico):**
```json
{
  "registered": true,
  "id": "velocidade-a3f9c1",
  "state": { "limitador_ativo": false, "limit_speed": 320.0 },
  "shared_value": 157.3
}
```

O campo `shared_value` na resposta inicial garante que um novo sensor não comece divergente dos demais — ele imediatamente adota o valor canônico calculado pela mediana dos sensores já conectados, e a partir daí converge gradualmente.

</section>

<section id="push-estado">
<h3>Push de Estado — Broker para Sensores</h3>

Sempre que o estado de um atuador muda, o broker identifica quais tipos de sensor são afetados e empurra o novo estado via TCP para todos eles, sem esperar qualquer solicitação:

```json
{
  "state": { "limitador_ativo": true, "limit_speed": 120.0 },
  "shared_value": 98.3
}
```

O mapeamento de dependência entre atuadores e sensores é fixo no broker:
- `limitador` → afeta sensores do tipo `velocidade`
- `resfriamento` → afeta sensores do tipo `temperatura`

Sensores de combustível e óleo não recebem push de estado de atuadores porque nenhum atuador atual os influencia diretamente — eles dependem apenas de seus próprios valores simulados internamente.

</section>

<section id="mensagens">
<h3>Catálogo Completo de Mensagens</h3>

| Direção | Contexto | Mensagem | Campos Obrigatórios |
|---|---|---|---|
| Sensor → Broker | TCP 5001 | Registro | `register`, `type`, `id` |
| Atuador → Broker | TCP 5001 | Registro | `register`, `type`, `id` |
| Broker → Dispositivo | TCP 5001 | Confirmação | `registered`, `id`, `state?`, `shared_value?` |
| Sensor → Broker | UDP 5000 | Telemetria | `id`, `type`, `data`, `ts` |
| Broker → Sensor | TCP 5001 | Push de estado | `state`, `shared_value?` |
| Broker → Dispositivo | TCP 5001 | Keepalive | `ping` (texto puro) |
| Dispositivo → Broker | TCP 5001 | Resposta keepalive | `ping` (texto puro — ecoa) |
| Atuador → Broker | TCP 5001 | Atualização de estado | `status: {active, limit?}` |
| Cliente → Broker | TCP 5002 | Assinatura | `subscribe: [tópicos]` |
| Broker → Cliente | TCP 5002 | Telemetria | `id`, `type`, `data`, `ts` |
| Broker → Cliente | TCP 5002 | Lista de dispositivos | `event: device_list`, `sensors[]`, `actuators[]` |
| Broker → Cliente | TCP 5002 | Desconexão de atuador | `event: actuator_disconnected`, `id`, `type`, `actuator_state` |
| Cliente → Broker | TCP 5002 | Comando | `command: {target_id\|target_type, data}` |
| Broker → Atuador | TCP 5001 | Comando repassado | `command: {active, limit?}` |

**Exemplo completo — ativando o limitador via cliente:**

O cliente envia ao broker:
```json
{
  "command": {
    "target_id": "limitador-b2e4f7",
    "data": { "active": true, "limit": 120 }
  }
}
```

O broker repassa ao atuador:
```json
{ "command": { "active": true, "limit": 120 } }
```

O atuador confirma ao broker:
```json
{ "status": { "active": true, "limit": 120.0 } }
```

O broker empurra para os sensores de velocidade:
```json
{ "state": { "limitador_ativo": true, "limit_speed": 120.0 }, "shared_value": 87.4 }
```

</section>
</section>

---

<section id="encapsulamento">
<h2>Encapsulamento e Formato dos Dados</h2>

Todas as mensagens trocadas via TCP usam **JSON delimitado por newline** (`\n`). Cada mensagem é uma única linha JSON terminada por `\n`, o que permite parsing incremental com um buffer simples e sem precisar conhecer o tamanho da mensagem antecipadamente. Esse padrão — conhecido como NDJSON (Newline-Delimited JSON) — é amplamente adotado em protocolos de streaming por ser ao mesmo tempo simples, legível por humanos e eficiente para máquinas.

O parsing em todos os componentes segue o mesmo padrão de buffer acumulativo:

```python
buffer = b""
while True:
    chunk = sock.recv(512)
    buffer += chunk
    while b"\n" in buffer:
        line, buffer = buffer.split(b"\n", 1)
        msg = json.loads(line.strip().decode())
        # processa msg...
```

Essa abordagem lida corretamente com dois fenômenos comuns em TCP: **fragmentação** (quando uma mensagem chega em múltiplos pacotes) e **coalescing** (quando múltiplas mensagens chegam no mesmo pacote). Sem o buffer acumulativo, qualquer um desses casos causaria erros de parsing.

**Validação e tolerância a erros:** todo parsing JSON é encapsulado em `try/except json.JSONDecodeError`. Mensagens malformadas são silenciosamente descartadas sem encerrar a conexão — um byte corrompido ou uma mensagem truncada não derruba o sistema. Campos ausentes são sempre acessados com `.get()` e valores padrão explícitos, nunca com acesso direto por chave.

**Telemetria UDP** segue o mesmo formato JSON, mas sem delimitador — cada datagrama é exatamente uma mensagem completa. O campo `ts` carrega o timestamp Unix de geração do dado no sensor, e o cliente usa esse campo para calcular e exibir a **latência de entrega** em milissegundos em tempo real durante o monitoramento.

</section>

---

<section id="concorrencia">
<h2>Concorrência e Qualidade de Serviço</h2>

<section id="threading">
<h3>Threading no Broker</h3>

O broker opera com um modelo de threading que combina threads de longa duração para os servidores principais com threads efêmeras por conexão para cada dispositivo e cliente.

<div align="center">
  <img src="docs/threading.png" alt="[SUGESTÃO DE IMAGEM] Diagrama mostrando o processo principal do broker no topo, com 4 setas descendo para as threads permanentes (handle_udp, handle_tcp_devices, handle_tcp_clients, status_reporter). De handle_tcp_devices saem N setas menores para threads de conexão individuais (sensor-001, sensor-002, atuador-001). De handle_tcp_clients saem M setas para threads de clientes (cliente-001, cliente-002). Use caixas coloridas por categoria">
  <br>
  <strong>Modelo de threading do broker — threads daemon por conexão</strong>
  <br><br>
</div>

As quatro threads de longa duração inicializadas na startup do broker são:

| Thread | Função |
|---|---|
| `handle_udp` | Loop bloqueante de recepção de telemetria UDP na porta 5000 |
| `handle_tcp_devices` | Loop de `accept()` de sensores e atuadores na porta 5001 |
| `handle_tcp_clients` | Loop de `accept()` de clientes na porta 5002 |
| `status_reporter` | Log periódico do estado completo do sistema a cada 15 segundos |

Cada `accept()` bem-sucedido gera uma nova thread daemon independente que gerencia o ciclo de vida completo daquela conexão — do handshake inicial até a limpeza no `finally` da desconexão. O uso de `daemon=True` em todas as threads garante que nenhuma thread filha impeça o encerramento do processo principal quando o operador pressionar `Ctrl+C`.

</section>

<section id="locks">
<h3>Locks e Seções Críticas</h3>

O broker usa cinco locks distintos, cada um protegendo um conjunto específico de dados compartilhados. A granularidade dos locks é intencional — um único lock global seria mais simples, mas causaria contenção desnecessária entre threads que operam em dados não relacionados.

```
devices_lock        → sensors{},  actuators{}
shared_values_lock  → shared_values_per_sensor{},  shared_values{}
actuator_state_lock → actuator_state{}
subscribers_lock    → subscribers{}
last_values_lock    → last_values{}
```

Um cuidado especial foi necessário para evitar **deadlock**: `threading.Lock` em Python não é reentrante, então uma função que já está dentro de `with devices_lock` não pode chamar outra função que tente adquirir o mesmo lock. A solução adotada é passar os dados necessários como parâmetro quando já se está dentro do lock, movendo a operação para fora:

```python
# Correto: calcula registered_ids dentro do lock, passa para fora
with devices_lock:
    remaining_ids = {sid for sid, e in sensors.items() if e["type"] == dtype}
recalc_shared_value(dtype, registered_ids=remaining_ids)  # fora do lock

# Incorreto: recalc_shared_value tentaria adquirir devices_lock novamente
with devices_lock:
    recalc_shared_value(dtype)  # deadlock
```

</section>

<section id="mediana">
<h3>Mediana Canônica e Convergência entre Sensores</h3>

Quando múltiplas instâncias do mesmo tipo de sensor estão conectadas simultaneamente, o broker precisa de um único valor de referência para sincronizá-las. Esse valor — o **valor canônico** — é calculado como a mediana dos valores mais recentes recebidos de cada instância:

```python
vals = [shared_values_per_sensor[sid] for sid in registered_ids]
shared_values[stype] = sorted(vals)[len(vals) // 2]
```

A **mediana** foi escolhida em vez da média por ser resistente a outliers. Se três sensores de velocidade estão conectados com valores 100, 150 e 0 km/h (o último com algum estado anômalo), a mediana é 100 — enquanto a média seria 83,3 km/h, distorcida pelo valor extremo.

Esse valor canônico é empurrado para todos os sensores do tipo a cada resposta de ping e a cada mudança de estado de atuador. Os sensores aplicam convergência gradual com um fator de interpolação linear:

```python
# Convergência forte (0.8) — velocidade e temperatura, push frequente do broker
state["velocidade"] += (float(sv) - state["velocidade"]) * 0.8

# Convergência suave (0.5) — combustível e óleo, mudanças mais lentas
state["combustivel"] += (float(sv) - state["combustivel"]) * 0.5
```

</section>

<section id="qos">
<h3>Separação de Perfis de Tráfego</h3>

O sistema distingue claramente dois perfis de tráfego com características e requisitos opostos, tratados com estratégias diferentes:

| Característica | Telemetria (UDP) | Controle (TCP) |
|---|---|---|
| Frequência | ~1.000 msg/s por sensor | Esporádico |
| Volume por mensagem | ~100 bytes | ~50–300 bytes |
| Tolerância a perdas | Alta — próxima em 1ms | Zero |
| Garantia de ordem | Não necessária | Necessária |
| Protocolo | UDP | TCP |

O broker **não enfileira telemetria** para os clientes — ele mantém apenas o `last_value` de cada tópico e faz broadcast do valor mais recente. Isso evita que um cliente lento ou com conexão mais lenta acumule uma fila crescente de mensagens antigas e cause aumento de uso de memória indefinido no broker.

</section>
</section>

---

<section id="interacao">
<h2>Interação — Cliente Terminal</h2>

O `cliente.py` implementa uma interface de terminal interativa completa, sem dependências externas. O cliente opera em duas fases alternadas: menus de seleção em modo normal de terminal, e monitoramento ao vivo em modo de tela cheia com atualização contínua via ANSI escape codes.

<div align="center">
  <img src="docs/cliente_monitoramento.gif" alt="[SUGESTÃO DE IMAGEM] GIF gravado com asciinema (instale com: pip install asciinema; grave com: asciinema rec demo.cast; converta com: svg-term --in demo.cast --out demo.svg) mostrando a sequência: 1) menu principal com lista de sensores e atuadores, 2) seleção de dois sensores para monitorar, 3) tela de monitoramento ao vivo com gráficos ASCII subindo e descendo por 10 segundos, 4) pressionar q para voltar ao menu">
  <br>
  <strong>Monitoramento ao vivo com gráfico ASCII de série temporal</strong>
  <br><br>
</div>

### Menu Principal

O menu principal é reconstruído a cada interação com a lista atual de dispositivos viva, recebida do broker. Nomes amigáveis como "Velocidade 1" e "Velocidade 2" são atribuídos dinamicamente com base na posição de cada dispositivo na lista — sem cache estático, sempre refletindo o estado real do broker no momento da exibição.

### Monitoramento ao Vivo

O modo de monitoramento ao vivo atualiza a tela a **10 Hz** (a cada 100ms), agregando as leituras que chegam a 1ms dos sensores. Para cada sensor monitorado são exibidos:

- **Valor atual** com unidade, colorido por nível de alerta (verde / amarelo / vermelho)
- **Barra de progresso** proporcional ao valor máximo do tipo
- **Indicador de alerta** com fundo vermelho quando o valor cruza o limiar crítico
- **Latência de entrega** em milissegundos — diferença entre o `ts` do sensor e o instante de recebimento
- **Gráfico ASCII de série temporal** com os últimos 60 valores, usando blocos Unicode de 8 níveis verticais de resolução

```
  Velocidade 1  (velocidade)
    143.7 km/h  ████████████░░░░░░░░░░  lag: 12ms
  ┌────────────────────────────────────────────────────────────┐
  │                                          ▅▆█▇▅▄           │
  │                              ▂▃▄▅▆▇█▆▄▂        ▃▄▅▆▄▂▁   │
  └────────────────────────────────────────────────────────────┘

  Temperatura 1  (temperatura)  ⚠ ALERTA
    128.4 °C    ████████████████████░░  lag: 8ms
```

Sensores que se desconectam durante o monitoramento são imediatamente identificados com `⚠ ERRO NO SENSOR` em vermelho — o cliente detecta a ausência do ID na `device_list` atualizada que recebe do broker automaticamente.

<div align="center">
  <img src="docs/cliente_comando.png" alt="[SUGESTÃO DE IMAGEM] Print do terminal mostrando a tela de comando do limitador de velocidade: lista os atuadores conectados com números de seleção, mostra o prompt pedindo a velocidade máxima em km/h, e abaixo a mensagem 'Limitador 1: ✔ enviado' em verde">
  <br>
  <strong>Envio de comando de limitador de velocidade via cliente terminal</strong>
  <br><br>
</div>

### Envio de Comandos

O cliente permite controlar atuadores individualmente ou em grupo. Para o limitador de velocidade, o usuário informa a velocidade máxima em km/h e pode selecionar um atuador específico ou todos os do tipo simultaneamente. Para o resfriamento, escolhe entre ativar ou desativar. A confirmação de envio é imediata — o cliente não espera o efeito nos sensores, apenas confirma que o comando chegou ao broker.

</section>

---

<section id="confiabilidade">
<h2>Confiabilidade e Tratamento de Falhas</h2>

O sistema foi projetado para se manter estável diante de qualquer falha parcial. Nenhuma falha de um componente individual derruba o sistema como um todo, e qualquer componente pode reconectar sem intervenção manual.

### Desconexão de Sensor

Quando um sensor perde conexão — por queda de rede, encerramento do processo, ou timeout de keepalive —, o broker executa uma sequência de limpeza no bloco `finally` do handler da conexão. O sensor é removido de `sensors{}`, seu valor individual é removido de `shared_values_per_sensor{}`, o valor canônico do tipo é recalculado sem ele, e todos os clientes recebem a `device_list` atualizada. O cliente exibe `⚠ ERRO NO SENSOR` imediatamente ao detectar que o ID sumiu da lista.

### Desconexão de Atuador

A desconexão de um atuador tem implicações mais abrangentes e foi um ponto crítico de cuidado no projeto. Se o único limitador ativo desconectar inesperadamente, os sensores de velocidade continuariam limitados para sempre sem nenhum push notificando a mudança. O broker trata isso explicitamente: ao detectar a desconexão de um atuador, ele recalcula o estado agregado **sem aquele atuador** e empurra o novo estado para os sensores afetados. No caso do exemplo, os sensores receberiam `{"limitador_ativo": false, "limit_speed": 320.0}` e voltariam a funcionar livremente. Todos os clientes recebem adicionalmente um evento `actuator_disconnected` com o novo estado dos atuadores.

### Reconexão Automática

Todos os componentes implementam reconexão automática com retry a cada 3 segundos. Sensores e atuadores detectam a desconexão quando o `recv()` retorna vazio ou quando o `send()` lança `OSError`, encerram a thread filha via `threading.Event`, e o loop principal da `main()` reinicia a conexão. O estado local é preservado entre reconexões — um sensor em 120°C não volta a 90°C só porque reconectou.

### Timeout e Keepalive

Dispositivos e clientes usam timeout de 35 segundos no `recv()` TCP. Em operação normal isso nunca dispara, pois a telemetria UDP flui constantemente e o broker envia pings a cada 30 segundos. Se o timeout disparar, o componente envia `ping\n` — se a resposta não chegar ou o envio falhar, a conexão é encerrada e o processo reconecta.

### Comando para Atuador Desconectado

Se o cliente tentar enviar um comando para um atuador cujo ID não existe mais em `actuators{}`, o broker loga um aviso e descarta o comando silenciosamente. O cliente não recebe confirmação de erro — mas já terá recebido a `device_list` atualizada e não deveria mais listar aquele atuador como disponível na interface.

</section>

---

<section id="testes">
<h2>Testes</h2>

Os testes foram conduzidos manualmente em ambiente Docker, simulando cenários reais de operação distribuída. Cada cenário foi desenhado para cobrir um aspecto específico do barema do projeto — desde a verificação básica de comunicação até situações de falha e recuperação. Os passos são reproduzíveis por qualquer pessoa com Python 3 e os arquivos do projeto.

<div align="center">
  <img src="docs/testes_overview.png" alt="[SUGESTÃO DE IMAGEM] Print de tela dividida com tmux (4 painéis): painel superior esquerdo com o broker logando registros, painel superior direito com dois sensores de velocidade imprimindo seus valores, painel inferior esquerdo com o atuador limitador aguardando comandos, painel inferior direito com o cliente no monitoramento ao vivo">
  <br>
  <strong>Ambiente de teste com múltiplos componentes em terminais simultâneos</strong>
  <br><br>
</div>

### Teste 1 — Conexão simultânea de múltiplos sensores do mesmo tipo

**Objetivo:** verificar que o broker mantém instâncias separadas, calcula a mediana corretamente e exibe ambos no cliente com nomes amigáveis distintos.

**Como executar:**
```bash
# Terminal 1
python broker.py

# Terminal 2
SENSOR_ID=velocidade-001 python sensor_velocidade.py

# Terminal 3
SENSOR_ID=velocidade-002 python sensor_velocidade.py

# Terminal 4
python cliente.py
# No cliente: selecionar ambos os sensores de velocidade para monitoramento
```

**Resultado esperado:** o cliente lista "Velocidade 1" e "Velocidade 2" com gráficos independentes. O log do broker (status_reporter a cada 15s) mostra dois sensores do tipo `velocidade` registrados. Ao longo do tempo, os valores dos dois sensores convergem gradualmente — evidência de que o push da mediana canônica está funcionando.

---

### Teste 2 — Ativação e desativação do limitador de velocidade

**Objetivo:** verificar o fluxo completo de comando (cliente → broker → atuador → broker → sensores) e o efeito observável no comportamento do sensor.

**Como executar:**
```bash
python broker.py
python sensor_velocidade.py   # terminal separado
python atuador_limitador.py   # terminal separado
python cliente.py             # terminal separado
# No cliente: monitorar o sensor de velocidade ao vivo
# Em outro menu do cliente: ativar limitador com 120 km/h
```

**Resultado esperado:** no terminal do sensor de velocidade, a mensagem `LIMITADOR ATIVADO ≤120 km/h` aparece em amarelo em até 1 segundo após o comando. O gráfico de velocidade no cliente passa a flutuar abaixo de 120 km/h, sem picos acima. Ao desativar, `Limitador DESATIVADO — livre` aparece no sensor e os valores voltam a atingir picos maiores.

<div align="center">
  <img src="docs/teste_limitador.png" alt="[SUGESTÃO DE IMAGEM] Print do terminal do sensor de velocidade mostrando a mensagem amarela 'LIMITADOR ATIVADO ≤120 km/h' logo após o comando ser enviado pelo cliente, com os valores subsequentes todos abaixo de 120">
  <br>
  <strong>Sensor de velocidade recebendo push do limitador em tempo real</strong>
  <br><br>
</div>

---

### Teste 3 — Queda e reconexão do broker

**Objetivo:** verificar que todos os componentes detectam a queda do broker e reconectam automaticamente sem intervenção manual.

**Como executar:**
```bash
# Suba todos os componentes normalmente, depois:
# No terminal do broker, pressione Ctrl+C
# Aguarde 5 segundos observando os outros terminais
# Reinicie o broker: python broker.py
# Aguarde mais 5 segundos
```

**Resultado esperado:** sensores e atuadores imprimem `Broker indisponível. Tentando em 3s...` e tentam reconectar a cada 3 segundos. O cliente exibe `⚠ Broker desconectado. Aguardando reinicialização...`. Ao reiniciar o broker, todos os componentes reconectam automaticamente e retomam operação normal — os sensores voltam a publicar, o cliente volta a receber telemetria.

---

### Teste 4 — Desconexão de atuador ativo e propagação de estado

**Objetivo:** verificar que a desconexão de um atuador ativo não deixa os sensores em estado restrito permanentemente.

**Como executar:**
```bash
python broker.py
python sensor_velocidade.py
python atuador_limitador.py
python cliente.py
# Via cliente: ativar limitador em 80 km/h
# Confirmar que o sensor está limitado (mensagem no terminal)
# Encerrar apenas o atuador: Ctrl+C no terminal do atuador
# Observar o terminal do sensor de velocidade
```

**Resultado esperado:** ao encerrar o atuador, o sensor de velocidade recebe push do broker com `limitador_ativo: false` e imprime `Limitador DESATIVADO — livre`. O cliente recebe evento `actuator_disconnected` e remove o atuador da lista de dispositivos. Os valores de velocidade voltam a ultrapassar 80 km/h.

---

### Teste 5 — Emulação em duas máquinas distintas via Docker

**Objetivo:** verificar que o sistema funciona em rede real com componentes em máquinas físicas distintas.

**Como executar:**

Na Máquina A (hospeda o broker):
```bash
docker build -t broker -f Dockerfile.broker .
docker run -p 5000:5000/udp -p 5001:5001 -p 5002:5002 broker
# Descubra o IP: hostname -I
```

Na Máquina B (sensores e cliente apontando para Máquina A):
```bash
docker run -e BROKER_HOST=<IP_MAQUINA_A> -e SENSOR_ID=velocidade-ext sensor_velocidade
BROKER_HOST=<IP_MAQUINA_A> python cliente.py
```

**Resultado esperado:** o sensor da Máquina B conecta no broker da Máquina A. O cliente vê o sensor na lista com o ID `velocidade-ext` e recebe telemetria normalmente. O comportamento é idêntico ao de execução local, confirmando que não há dependência de localhost.

<div align="center">
  <img src="docs/teste_docker.png" alt="[SUGESTÃO DE IMAGEM] Print do comando 'docker ps' mostrando os contêineres em execução: ao menos broker, sensor_velocidade (duas instâncias com nomes diferentes), sensor_temperatura, atuador_limitador, atuador_resfriamento — evidencia múltiplos processos independentes rodando simultaneamente">
  <br>
  <strong>Múltiplos contêineres rodando simultaneamente via Docker</strong>
  <br><br>
</div>

</section>

---

<section id="docker">
<h2>Emulação com Docker</h2>

Todos os componentes são containerizados individualmente com Dockerfiles baseados em `python:3.11-slim`, mantendo as imagens leves e sem dependências além da biblioteca padrão do Python. A variável de ambiente `BROKER_HOST` é o único ponto de configuração necessário para apontar qualquer componente para um broker em qualquer endereço de rede.

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY atuador_limitador.py .
ENV BROKER_HOST=localhost
CMD ["python", "-u", "atuador_limitador.py"]
```

A flag `-u` no `CMD` desativa o buffering de saída do Python, garantindo que os logs apareçam em tempo real no `docker logs` sem atraso de buffer.

### docker-compose

O `docker-compose.yml` permite subir o ambiente completo com um único comando, com cada componente em seu próprio contêiner isolado:

```yaml
version: "3.9"
services:
  broker:
    build:
      context: .
      dockerfile: Dockerfile.broker
    ports:
      - "5000:5000/udp"
      - "5001:5001"
      - "5002:5002"

  sensor_velocidade_1:
    build:
      context: .
      dockerfile: Dockerfile.sensor_velocidade
    environment:
      - BROKER_HOST=broker
      - SENSOR_ID=velocidade-001
    depends_on: [broker]

  sensor_velocidade_2:
    build:
      context: .
      dockerfile: Dockerfile.sensor_velocidade
    environment:
      - BROKER_HOST=broker
      - SENSOR_ID=velocidade-002
    depends_on: [broker]

  sensor_temperatura:
    build:
      context: .
      dockerfile: Dockerfile.sensor_temperatura
    environment:
      - BROKER_HOST=broker
    depends_on: [broker]

  sensor_combustivel:
    build:
      context: .
      dockerfile: Dockerfile.sensor_combustivel
    environment:
      - BROKER_HOST=broker
    depends_on: [broker]

  sensor_oleo:
    build:
      context: .
      dockerfile: Dockerfile.sensor_oleo
    environment:
      - BROKER_HOST=broker
    depends_on: [broker]

  atuador_limitador:
    build:
      context: .
      dockerfile: Dockerfile.atuador_limitador
    environment:
      - BROKER_HOST=broker
    depends_on: [broker]

  atuador_resfriamento:
    build:
      context: .
      dockerfile: Dockerfile.atuador_resfriamento
    environment:
      - BROKER_HOST=broker
    depends_on: [broker]
```

Para escalar horizontalmente qualquer sensor e testar convergência entre múltiplas instâncias:
```bash
docker compose up --scale sensor_velocidade_1=3
```

### Comunicação entre Máquinas Distintas

O broker escuta em `0.0.0.0` em todas as interfaces de rede. Para conectar componentes de outra máquina na mesma rede local, basta definir `BROKER_HOST` com o IP da máquina hospedeira — nenhuma outra configuração é necessária:

```bash
docker run -e BROKER_HOST=192.168.1.100 -e SENSOR_ID=velocidade-ext sensor_velocidade
```

</section>

---

<section id="execucao">
<h2>Como Executar</h2>

### Sem Docker (desenvolvimento local)

Requisito: Python 3.9 ou superior. Sem dependências externas.

```bash
# Terminal 1 — inicie sempre o broker primeiro
python broker.py

# Terminais 2–5 — sensores (abra quantos quiser de cada tipo)
python sensor_velocidade.py
python sensor_temperatura.py
python sensor_combustivel.py
python sensor_oleo.py

# Terminais 6–7 — atuadores
python atuador_limitador.py
python atuador_resfriamento.py

# Terminal 8 — cliente interativo
python cliente.py
```

### Com Docker Compose

```bash
# Sobe todos os serviços
docker compose up --build

# Em outro terminal, rode o cliente localmente
python cliente.py   # BROKER_HOST=localhost por padrão
```

### Variáveis de Ambiente

| Variável | Componente | Padrão | Descrição |
|---|---|---|---|
| `BROKER_HOST` | Todos | `localhost` | IP ou hostname do broker |
| `SENSOR_ID` | Sensores | `<tipo>-<uuid>` | ID único do sensor — gerado automaticamente se ausente |
| `ACTUATOR_ID` | Atuadores | `<tipo>-<uuid>` | ID único do atuador — gerado automaticamente se ausente |

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
