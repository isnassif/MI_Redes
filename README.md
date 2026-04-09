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
        <li><a href="#tcp-dispositivos">Registro e Controle via TCP</a></li>
        <li><a href="#tcp-clientes">Assinatura e Comandos</a></li>
        <li><a href="#perfis-trafego">Perfis de Tráfego e Mensagens Críticas</a></li>
      </ul>
    </li>
    <li><a href="#protocolo">Protocolo e Formato das Mensagens</a>
      <ul>
        <li><a href="#handshake">Handshake de Registro</a></li>
        <li><a href="#push-estado">Push de Estado</a></li>
        <li><a href="#catalogo">Catálogo de Mensagens</a></li>
        <li><a href="#encapsulamento">Encapsulamento e Parsing</a></li>
      </ul>
    </li>
    <li><a href="#concorrencia">Concorrência e Sincronização</a>
      <ul>
        <li><a href="#threading">Modelo de Threading</a></li>
        <li><a href="#locks">Locks e Seções Críticas</a></li>
        <li><a href="#mediana">Mediana Canônica</a></li>
      </ul>
    </li>
    <li><a href="#interacao">Interação via Cliente Terminal</a></li>
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
  <img src="docs/banner.png" alt="[SUGESTÃO DE IMAGEM] Print de múltiplos terminais lado a lado (use tmux) mostrando: broker logando registros à esquerda, dois sensores publicando no centro, e o cliente com gráficos ASCII ao vivo à direita — evidencia o sistema distribuído em funcionamento real">
  <br>
  <strong>Sistema distribuído de telemetria veicular em execução</strong>
  <br><br>
</div>

Este projeto implementa um **sistema distribuído de telemetria veicular** baseado em arquitetura de broker central e comunicação assíncrona por publish-subscribe. O sistema simula o monitoramento em tempo real de um veículo, com sensores publicando leituras contínuas de velocidade, temperatura do motor, nível de combustível e nível de óleo, e atuadores capazes de intervir no comportamento do veículo remotamente.

O problema central que motivou a escolha dessa arquitetura é o **alto acoplamento** que ocorre em sistemas ponto-a-ponto tradicionais: cada cliente precisaria conhecer o endereço de cada sensor, e qualquer mudança na topologia exigiria reconfiguração de todos os participantes. Com um broker intermediário, sensores simplesmente publicam dados, atuadores simplesmente aguardam comandos, e clientes simplesmente assinam tópicos — nenhum componente precisa conhecer os demais diretamente.

Os componentes do sistema são processos completamente independentes entre si. O broker é o único ponto de integração, e sua ausência não impede que os demais processos continuem tentando reconectar automaticamente. Cada sensor, atuador e cliente pode entrar e sair da rede a qualquer momento sem derrubar os outros. O sistema foi desenvolvido inteiramente em Python 3, sem dependências externas além da biblioteca padrão, e containerizado com Docker para permitir execução em múltiplas máquinas distintas de forma reproduzível.

</section>

---

<section id="arquitetura">
<h2>Arquitetura do Sistema</h2>

<div align="center">
  <img src="docs/arquitetura_geral.png" alt="[SUGESTÃO DE IMAGEM] Diagrama criado no draw.io ou Excalidraw mostrando o broker no centro com três grupos ao redor: à esquerda os quatro tipos de sensores com setas laranja (UDP 5000) e azul (TCP 5001) apontando para o broker; à direita os dois atuadores com setas azuis bidirecionais (TCP 5001); abaixo o cliente com setas azuis bidirecionais (TCP 5002). Inclua os nomes das portas nas setas">
  <br>
  <strong>Arquitetura geral — broker central com sensores, atuadores e clientes</strong>
  <br><br>
</div>

O sistema é composto por quatro tipos de processos independentes que se comunicam exclusivamente por meio do broker. Essa separação rigorosa de responsabilidades é o que permite escalar qualquer parte do sistema de forma independente — é possível adicionar dez sensores de velocidade sem alterar nenhuma linha do broker, do cliente ou dos atuadores.

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
   velocidade          limitador            terminal
   temperatura         resfriamento
   combustivel
   oleo
```

<section id="broker">
<h3>Broker — Serviço Central de Integração</h3>

O `broker.py` é o único componente que conhece todos os outros. Sua função é receber telemetria dos sensores, gerenciar conexões persistentes de dispositivos e servir clientes assinantes — tudo simultaneamente, em threads separadas.

Internamente, o broker mantém dois dicionários principais, `sensors` e `actuators`, que mapeiam o ID de cada dispositivo para sua entrada completa: socket TCP ativo, tipo, endereço remoto e estado atual. Esses dicionários são protegidos por `threading.Lock` e atualizados atomicamente a cada conexão ou desconexão.

O broker também é responsável pelo **recálculo do estado agregado dos atuadores**. Quando múltiplos limitadores estão ativos simultaneamente, ele seleciona o limite mais restritivo entre todos. Quando múltiplos atuadores de resfriamento estão presentes, a lógica é OR — basta um estar ativo. Esse recálculo é disparado em qualquer mudança de estado: nova conexão, desconexão, ou atualização enviada por um atuador.

</section>

<section id="sensores">
<h3>Sensores Virtuais</h3>

Cada sensor é um processo Python independente que simula a física de um componente real do veículo. O estado interno de cada sensor evolui com ruído estocástico, influência de outros parâmetros e restrições físicas. O sensor de temperatura aquece proporcionalmente à velocidade simulada internamente e resfria quando o atuador correspondente está ativo. O sensor de óleo desgasta mais rapidamente em temperaturas altas.

| Arquivo | Tipo | Unidade | Faixa | Influências externas |
|---|---|---|---|---|
| `sensor_velocidade.py` | `velocidade` | km/h | 0 – 320 | Atuador limitador |
| `sensor_temperatura.py` | `temperatura` | °C | 60 – 145 | Atuador de resfriamento |
| `sensor_combustivel.py` | `combustivel` | % | 0 – 100 | — |
| `sensor_oleo.py` | `oleo` | % | 0 – 100 | — |

Cada sensor opera com duas threads internas: `keepalive_loop`, que mantém a conexão TCP com o broker e processa mensagens de push de estado, e `publish_loop`, que gera e envia telemetria UDP em loop contínuo a cada 1 ms. Essa separação garante que uma lentidão na rede TCP nunca atrase a publicação de dados.

</section>

<section id="atuadores">
<h3>Atuadores</h3>

Os atuadores são processos que não publicam telemetria — eles apenas aguardam comandos do broker e notificam seu estado atual após cada mudança. Ao receber um comando, o atuador atualiza seu estado interno e envia `{"status": {...}}` de volta ao broker, que usa essa informação para recalcular o estado global e propagar imediatamente para os sensores afetados.

| Arquivo | Tipo | Efeito nos Sensores |
|---|---|---|
| `atuador_limitador.py` | `limitador` | Restringe a velocidade máxima dos sensores de velocidade |
| `atuador_resfriamento.py` | `resfriamento` | Ativa efeito de resfriamento nos sensores de temperatura |

</section>

<section id="cliente">
<h3>Cliente Terminal</h3>

O `cliente.py` é uma aplicação de terminal interativa construída inteiramente com ANSI escape codes, sem dependências externas. Ao conectar, recebe automaticamente a lista de dispositivos ativos no broker. A partir daí, o operador pode selecionar sensores para monitoramento ao vivo — com gráficos de série temporal em ASCII, barras de progresso coloridas por nível de alerta e latência de entrega em tempo real — e enviar comandos para atuadores pelo mesmo terminal.

</section>
</section>

---

<section id="comunicacao">
<h2>Comunicação entre Componentes</h2>

A escolha dos protocolos de transporte foi deliberada: o sistema usa UDP para telemetria contínua, onde a velocidade importa mais que a garantia de entrega, e TCP para controle e comandos, onde a confiabilidade e a ordem são essenciais.

<section id="udp">
<h3>Telemetria via UDP (porta 5000)</h3>

Sensores publicam leituras a cada 1 milissegundo via UDP. O protocolo foi escolhido por suas características: sem handshake, sem confirmação de entrega, sem controle de fluxo. Para telemetria de alta frequência, isso é vantagem — se um pacote for perdido, o próximo chega em 1 ms. Usar TCP para esse volume geraria overhead completamente desnecessário. O broker só processa telemetria de sensores **previamente registrados** via TCP, descartando pacotes de IDs desconhecidos.

</section>

<section id="tcp-dispositivos">
<h3>Registro e Controle via TCP (porta 5001)</h3>

A conexão TCP na porta 5001 serve a três propósitos simultâneos durante toda a vida de um dispositivo: o **handshake de registro** inicial, o **heartbeat bidirecional** (ping/pong a cada 30 segundos para detectar conexões zumbi), e o canal pelo qual o broker faz **push ativo de estado** para os sensores sempre que um atuador muda. A conexão é mantida aberta permanentemente — não há reconexão a cada mensagem — o que reduz latência e permite ao broker saber exatamente quais dispositivos estão vivos a qualquer momento.

</section>

<section id="tcp-clientes">
<h3>Assinatura e Comandos (porta 5002)</h3>

Clientes conectam na porta 5002 e recebem automaticamente a lista de dispositivos ativos. A partir daí, podem assinar tópicos de sensores individuais (ex: `sensor/velocidade-a3f9c1`) ou por tipo (ex: `sensor/type/velocidade`). O mesmo canal é usado para enviar comandos para atuadores, especificando o `target_id` (um atuador específico) ou `target_type` (todos de um tipo).

</section>

<section id="perfis-trafego">
<h3>Perfis de Tráfego e Mensagens Críticas</h3>

O sistema distingue dois perfis de tráfego com estratégias diferentes de tratamento:

| Característica | Telemetria (UDP) | Controle (TCP) |
|---|---|---|
| Frequência | ~1.000 msg/s por sensor | Esporádico |
| Tolerância a perdas | Alta — próxima em 1 ms | Zero |
| Garantia de ordem | Não necessária | Necessária |
| Tratamento no broker | Descarta antigas, mantém só `last_value` | Processamento garantido |

Mensagens de controle — comandos para atuadores, push de estado, confirmações de registro — são tratadas via TCP com entrega garantida. A telemetria UDP é agregada no broker: apenas o valor mais recente de cada sensor é mantido, evitando enfileiramento e crescimento indefinido de memória quando um cliente está lento.

</section>
</section>

---

<section id="protocolo">
<h2>Protocolo e Formato das Mensagens</h2>

<section id="handshake">
<h3>Handshake de Registro</h3>

Todo dispositivo ao conectar na porta 5001 deve enviar imediatamente uma mensagem de registro. O broker tem timeout de 10 segundos para recebê-la. O campo `id` é opcional — se ausente, o broker gera um ID único com `uuid4` e o inclui na resposta. Após o registro, o broker envia ao sensor o estado atual dos atuadores e o valor canônico do tipo, para que o sensor não comece divergente das demais instâncias já conectadas.

**Sensor:**
```json
{ "register": "sensor", "type": "velocidade", "id": "velocidade-a3f9c1" }
```

**Atuador:**
```json
{ "register": "atuador", "type": "limitador", "id": "limitador-b2e4f7" }
```

**Broker → Sensor (resposta com estado inicial):**
```json
{
  "registered": true,
  "id": "velocidade-a3f9c1",
  "state": { "limitador_ativo": false, "limit_speed": 320.0 },
  "shared_value": 157.3
}
```

</section>

<section id="push-estado">
<h3>Push de Estado — Broker → Sensores</h3>

Sempre que o estado de um atuador muda, o broker empurra o novo estado imediatamente para todos os sensores do tipo afetado, sem esperar qualquer solicitação. O mapeamento de dependência é fixo: `limitador` afeta sensores de `velocidade`; `resfriamento` afeta sensores de `temperatura`.

```json
{
  "state": { "limitador_ativo": true, "limit_speed": 120.0 },
  "shared_value": 98.3
}
```

O campo `shared_value` carrega a mediana canônica do tipo naquele momento, permitindo que o sensor corrija sua convergência junto com o estado do atuador numa única mensagem.

</section>

<section id="catalogo">
<h3>Catálogo de Mensagens</h3>

| Direção | Mensagem | Campos |
|---|---|---|
| Sensor → Broker (TCP 5001) | Registro | `register`, `type`, `id` |
| Atuador → Broker (TCP 5001) | Registro | `register`, `type`, `id` |
| Broker → Dispositivo (TCP 5001) | Confirmação | `registered`, `id`, `state?`, `shared_value?` |
| Sensor → Broker (UDP 5000) | Telemetria | `id`, `type`, `data`, `ts` |
| Broker → Sensor (TCP 5001) | Push de estado | `state`, `shared_value?` |
| Dispositivo ↔ Broker (TCP 5001) | Keepalive | `ping` (texto puro) |
| Atuador → Broker (TCP 5001) | Notificação de estado | `status: {active, limit?}` |
| Cliente → Broker (TCP 5002) | Assinatura | `subscribe: [tópicos]` |
| Broker → Cliente (TCP 5002) | Telemetria | `id`, `type`, `data`, `ts` |
| Broker → Cliente (TCP 5002) | Lista de dispositivos | `event: device_list`, `sensors[]`, `actuators[]` |
| Broker → Cliente (TCP 5002) | Desconexão de atuador | `event: actuator_disconnected`, `id`, `type`, `actuator_state` |
| Cliente → Broker (TCP 5002) | Comando | `command: {target_id\|target_type, data}` |
| Broker → Atuador (TCP 5001) | Comando repassado | `command: {active, limit?}` |

**Exemplo completo — fluxo de ativação do limitador:**

```
Cliente  ──►  Broker:   {"command": {"target_id": "limitador-b2e4f7", "data": {"active": true, "limit": 120}}}
Broker   ──►  Atuador:  {"command": {"active": true, "limit": 120}}
Atuador  ──►  Broker:   {"status": {"active": true, "limit": 120.0}}
Broker   ──►  Sensores: {"state": {"limitador_ativo": true, "limit_speed": 120.0}, "shared_value": 87.4}
```

</section>

<section id="encapsulamento">
<h3>Encapsulamento e Parsing</h3>

Todas as mensagens TCP usam **JSON delimitado por newline** (`\n`) — cada mensagem é uma linha JSON terminada por `\n`. Esse padrão (NDJSON) permite parsing incremental com buffer simples, sem precisar conhecer o tamanho da mensagem de antemão, e lida corretamente com fragmentação TCP (mensagem chegando em múltiplos pacotes) e coalescing (múltiplas mensagens no mesmo pacote):

```python
buffer = b""
while True:
    chunk = sock.recv(512)
    buffer += chunk
    while b"\n" in buffer:
        line, buffer = buffer.split(b"\n", 1)
        msg = json.loads(line.strip().decode())
```

Todo parsing JSON é encapsulado em `try/except json.JSONDecodeError`. Mensagens malformadas são silenciosamente descartadas sem encerrar a conexão. Campos ausentes são sempre acessados com `.get()` e valores padrão explícitos, nunca com acesso direto por chave. A telemetria UDP segue o mesmo formato JSON, mas sem delimitador — cada datagrama é exatamente uma mensagem completa. O campo `ts` (timestamp Unix de geração) é usado pelo cliente para calcular e exibir a latência de entrega em milissegundos.

</section>
</section>

---

<section id="concorrencia">
<h2>Concorrência e Sincronização</h2>

<section id="threading">
<h3>Modelo de Threading</h3>

<div align="center">
  <img src="docs/threading.png" alt="[SUGESTÃO DE IMAGEM] Diagrama mostrando o processo principal do broker no topo, com 4 setas descendo para as threads permanentes (handle_udp, handle_tcp_devices, handle_tcp_clients, status_reporter). De handle_tcp_devices saem N setas menores para threads de conexão individuais de cada sensor e atuador. De handle_tcp_clients saem M setas para threads de clientes. Use caixas coloridas por categoria">
  <br>
  <strong>Modelo de threading do broker — threads daemon por conexão</strong>
  <br><br>
</div>

O broker opera com quatro threads de longa duração inicializadas na startup, mais uma thread efêmera para cada dispositivo ou cliente que conecta:

| Thread permanente | Função |
|---|---|
| `handle_udp` | Loop bloqueante de recepção UDP na porta 5000 |
| `handle_tcp_devices` | Loop de `accept()` de sensores e atuadores na porta 5001 |
| `handle_tcp_clients` | Loop de `accept()` de clientes na porta 5002 |
| `status_reporter` | Log periódico do estado completo a cada 15 segundos |

Cada `accept()` bem-sucedido gera uma thread daemon independente que gerencia o ciclo de vida completo daquela conexão — do handshake inicial até a limpeza garantida no bloco `finally` da desconexão. O uso de `daemon=True` garante que nenhuma thread filha impeça o encerramento do processo principal.

Os sensores também usam threading interno: a thread `keepalive_loop` mantém a conexão TCP e processa mensagens de push, enquanto `publish_loop` envia telemetria UDP de forma independente. Isso garante que a latência de rede no canal TCP nunca bloqueie a publicação de dados.

</section>

<section id="locks">
<h3>Locks e Seções Críticas</h3>

O broker usa cinco locks distintos com granularidade intencional — um único lock global causaria contenção desnecessária entre threads operando em dados não relacionados:

```
devices_lock        → sensors{},  actuators{}
shared_values_lock  → shared_values_per_sensor{},  shared_values{}
actuator_state_lock → actuator_state{}
subscribers_lock    → subscribers{}
last_values_lock    → last_values{}
```

Um cuidado especial foi necessário para evitar **deadlock**: `threading.Lock` em Python não é reentrante. Funções que já estão dentro de um bloco `with devices_lock` não podem chamar outras funções que tentem adquirir o mesmo lock. A solução adotada é calcular os dados necessários dentro do lock e passá-los como parâmetro para fora:

```python
# Correto: calcula registered_ids dentro do lock e opera fora
with devices_lock:
    remaining_ids = {sid for sid, e in sensors.items() if e["type"] == dtype}
recalc_shared_value(dtype, registered_ids=remaining_ids)  # fora do lock

# Incorreto: deadlock — recalc_shared_value tentaria adquirir devices_lock novamente
with devices_lock:
    recalc_shared_value(dtype)
```

As requisições simultâneas de múltiplos sensores publicando a 1 ms são gerenciadas por esse modelo: cada thread de sensor acessa `shared_values_lock` brevemente para atualizar seu valor, e o recálculo da mediana é feito também dentro desse lock, de forma atômica.

</section>

<section id="mediana">
<h3>Mediana Canônica</h3>

Quando múltiplas instâncias do mesmo tipo de sensor estão conectadas, o broker calcula a **mediana** dos valores recebidos como valor canônico de referência:

```python
vals = [shared_values_per_sensor[sid] for sid in registered_ids]
shared_values[stype] = sorted(vals)[len(vals) // 2]
```

A mediana foi escolhida em vez da média por ser resistente a outliers — se um sensor com estado anômalo enviar 0 km/h enquanto os outros marcam ~150 km/h, a mediana não é distorcida. Esse valor é empurrado para todos os sensores do tipo a cada resposta de ping e a cada mudança de estado de atuador. Os sensores aplicam convergência gradual ao receber o valor canônico:

```python
# Velocidade e temperatura: convergência forte (broker empurra com frequência)
state["velocidade"] += (float(sv) - state["velocidade"]) * 0.8

# Combustível e óleo: convergência suave (mudanças mais lentas)
state["combustivel"] += (float(sv) - state["combustivel"]) * 0.5
```

</section>
</section>

---

<section id="interacao">
<h2>Interação via Cliente Terminal</h2>

O `cliente.py` foi construído para permitir a **seleção remota de dispositivos**, a **visualização de dados em tempo real** e o **envio de comandos** a partir de um único terminal interativo, sem dependências externas.

<div align="center">
  <img src="docs/cliente_monitoramento.gif" alt="[SUGESTÃO DE IMAGEM] GIF gravado com asciinema (instale: pip install asciinema; grave: asciinema rec demo.cast; converta: svg-term --in demo.cast --out demo.svg ou use asciinema-gif) mostrando a sequência: 1) menu principal listando sensores e atuadores, 2) seleção de dois sensores, 3) tela de monitoramento com gráficos ASCII atualizando ao vivo por ~10 segundos, 4) pressionar q para voltar">
  <br>
  <strong>Monitoramento ao vivo com gráfico ASCII de série temporal e indicação de alerta</strong>
  <br><br>
</div>

Ao conectar, o cliente recebe automaticamente do broker a lista completa de sensores e atuadores ativos. Nomes amigáveis como "Velocidade 1" e "Velocidade 2" são atribuídos dinamicamente — sem cache estático, sempre refletindo o estado real do broker. O operador seleciona quais sensores deseja monitorar e o cliente entra em modo de tela cheia com atualização a **10 Hz**.

Para cada sensor monitorado são exibidos: o valor atual com unidade colorido por nível de alerta (verde / amarelo / vermelho), uma barra de progresso proporcional ao máximo do tipo, um indicador de alerta em destaque quando o valor cruza o limiar crítico, a latência de entrega em milissegundos, e um gráfico de série temporal em ASCII com os últimos 60 valores usando blocos Unicode de 8 níveis de resolução vertical.

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

Sensores que se desconectam durante o monitoramento são imediatamente identificados com `⚠ ERRO NO SENSOR` — o cliente detecta a ausência do ID na `device_list` atualizada que o broker envia automaticamente. A interface também permite enviar comandos para atuadores: ativar o limitador de velocidade com um valor em km/h, ou ligar/desligar o resfriamento, selecionando um atuador específico ou todos os do tipo simultaneamente.

<div align="center">
  <img src="docs/cliente_comando.png" alt="[SUGESTÃO DE IMAGEM] Print do terminal mostrando a tela de comando do limitador de velocidade: lista os atuadores conectados numerados, prompt pedindo a velocidade máxima em km/h, e confirmação '✔ enviado' em verde logo abaixo">
  <br>
  <strong>Envio de comando de limitador de velocidade via cliente terminal</strong>
  <br><br>
</div>

</section>

---

<section id="confiabilidade">
<h2>Confiabilidade e Tratamento de Falhas</h2>

O sistema foi projetado para se manter estável diante de qualquer falha parcial. Nenhuma falha de um componente individual derruba o sistema como um todo.

**Desconexão de sensor:** o broker remove o sensor de `sensors{}`, recalcula a mediana sem ele e envia `device_list` atualizada para todos os clientes. O cliente exibe `⚠ ERRO NO SENSOR` imediatamente. Se o sensor reconectar, retoma operação normal adotando o valor canônico atual do broker.

**Desconexão de atuador ativo:** este é o caso mais crítico. Se o único limitador ativo desconectar inesperadamente, os sensores de velocidade ficariam limitados indefinidamente sem receber notificação. O broker trata isso no bloco `finally` da conexão: ao detectar a desconexão, recalcula o estado agregado **sem aquele atuador** e empurra imediatamente o novo estado para os sensores afetados. Todos os clientes recebem adicionalmente um evento `actuator_disconnected` com o novo estado global.

**Reconexão automática:** todos os componentes implementam reconexão automática com retry a cada 3 segundos, detectando desconexão quando `recv()` retorna vazio ou `send()` lança `OSError`. O estado local é preservado entre reconexões.

**Timeout e keepalive:** dispositivos e clientes usam timeout de 35 segundos no `recv()` TCP. Ao disparar, o componente envia `ping\n` — se a resposta não chegar ou o envio falhar, a conexão é encerrada e o processo reconecta. O broker usa timeout de 30 segundos e envia `ping\n` ativamente ao detectar inatividade.

**Comando para atuador desconectado:** se o cliente tentar enviar um comando para um ID que não existe mais em `actuators{}`, o broker loga um aviso e descarta o comando. O cliente já terá recebido a `device_list` atualizada e não deveria mais listar aquele atuador.

</section>

---

<section id="testes">
<h2>Testes</h2>

Os testes foram conduzidos manualmente em ambiente local e com Docker, cobrindo os cenários principais de operação, falha e recuperação do sistema. Todos são reproduzíveis abrindo múltiplos terminais com os arquivos do projeto.

<div align="center">
  <img src="docs/testes_overview.png" alt="[SUGESTÃO DE IMAGEM] Print de tela dividida com tmux (4 painéis, crie com: tmux new-session, depois Ctrl+b % para dividir verticalmente e Ctrl+b ' para dividir horizontalmente): painel superior esquerdo com broker logando, superior direito com dois sensores de velocidade, inferior esquerdo com atuador, inferior direito com cliente no monitoramento ao vivo">
  <br>
  <strong>Ambiente de testes com múltiplos componentes em terminais simultâneos</strong>
  <br><br>
</div>

### Teste 1 — Múltiplos sensores do mesmo tipo conectados simultaneamente

**Objetivo:** verificar que o broker mantém instâncias separadas, calcula a mediana corretamente e exibe ambos no cliente com nomes amigáveis distintos.

```bash
python broker.py
SENSOR_ID=velocidade-001 python sensor_velocidade.py  # terminal 2
SENSOR_ID=velocidade-002 python sensor_velocidade.py  # terminal 3
python cliente.py  # selecionar ambos os sensores para monitoramento
```

**Resultado esperado:** o cliente lista "Velocidade 1" e "Velocidade 2" com gráficos independentes. O `status_reporter` do broker (log a cada 15s) mostra dois sensores do tipo `velocidade`. Ao longo do tempo, os valores dos dois sensores convergem gradualmente — evidência do push da mediana canônica funcionando.

---

### Teste 2 — Ativação e desativação do limitador de velocidade

**Objetivo:** verificar o fluxo completo de comando (cliente → broker → atuador → broker → sensores) e o efeito observável no sensor.

```bash
python broker.py
python sensor_velocidade.py   # terminal 2 — observe os logs
python atuador_limitador.py   # terminal 3
python cliente.py             # monitorar velocidade ao vivo; ativar limitador em 120 km/h
```

**Resultado esperado:** no terminal do sensor, a mensagem `LIMITADOR ATIVADO ≤120 km/h` aparece em amarelo em até 1 segundo após o comando. O gráfico de velocidade no cliente passa a flutuar abaixo de 120 km/h. Ao desativar, `Limitador DESATIVADO — livre` aparece no sensor e os picos voltam.

<div align="center">
  <img src="docs/teste_limitador.png" alt="[SUGESTÃO DE IMAGEM] Print do terminal do sensor de velocidade mostrando a mensagem amarela 'LIMITADOR ATIVADO ≤120 km/h' logo após o envio do comando pelo cliente, com os valores impressos logo abaixo todos abaixo de 120">
  <br>
  <strong>Sensor de velocidade recebendo push do limitador em tempo real</strong>
  <br><br>
</div>

---

### Teste 3 — Queda e reconexão do broker

**Objetivo:** verificar que todos os componentes detectam a queda e reconectam automaticamente sem intervenção.

```bash
# Com todos os componentes rodando:
# Pressione Ctrl+C no terminal do broker — aguarde 5s observando os outros terminais
# Reinicie: python broker.py — aguarde mais 5s
```

**Resultado esperado:** sensores e atuadores imprimem `Broker indisponível. Tentando em 3s...` e tentam reconectar a cada 3 segundos. O cliente exibe `⚠ Broker desconectado. Aguardando reinicialização...`. Ao reiniciar o broker, todos os componentes reconectam automaticamente e retomam operação normal.

---

### Teste 4 — Desconexão de atuador ativo e propagação de estado

**Objetivo:** verificar que a desconexão de um atuador ativo não deixa os sensores em estado restrito permanentemente.

```bash
# Com broker, sensor de velocidade, atuador limitador e cliente rodando:
# Via cliente: ativar limitador em 80 km/h
# Confirmar que o sensor está limitado (mensagem no terminal do sensor)
# Ctrl+C apenas no terminal do atuador
# Observar o terminal do sensor de velocidade e o cliente
```

**Resultado esperado:** ao encerrar o atuador, o sensor recebe push do broker com `limitador_ativo: false` e imprime `Limitador DESATIVADO — livre`. O cliente remove o atuador da lista. Os valores de velocidade voltam a ultrapassar 80 km/h.

---

### Teste 5 — Emulação em duas máquinas distintas via Docker

**Objetivo:** verificar que o sistema funciona em rede real com componentes em máquinas físicas distintas.

**Máquina A (broker):**
```bash
docker build -t broker -f Dockerfile.broker .
docker run -p 5000:5000/udp -p 5001:5001 -p 5002:5002 broker
hostname -I  # anote o IP
```

**Máquina B (sensor e cliente):**
```bash
docker run -e BROKER_HOST=<IP_MAQUINA_A> -e SENSOR_ID=velocidade-ext sensor_velocidade
BROKER_HOST=<IP_MAQUINA_A> python cliente.py
```

**Resultado esperado:** o sensor da Máquina B conecta no broker da Máquina A. O cliente vê o sensor na lista com o ID `velocidade-ext` e recebe telemetria normalmente. O comportamento é idêntico ao de execução local.

<div align="center">
  <img src="docs/teste_docker.png" alt="[SUGESTÃO DE IMAGEM] Print do comando 'docker ps' mostrando os contêineres em execução: broker, sensor_velocidade (duas instâncias), sensor_temperatura, atuador_limitador, atuador_resfriamento — ou alternativamente o output colorido do 'docker compose up' com os logs de cada serviço aparecendo em paralelo">
  <br>
  <strong>Múltiplos contêineres em execução simultânea — ambiente distribuído via Docker</strong>
  <br><br>
</div>

</section>

---

<section id="docker">
<h2>Emulação com Docker</h2>

Todos os componentes são containerizados individualmente com Dockerfiles baseados em `python:3.11-slim`. A variável de ambiente `BROKER_HOST` é o único ponto de configuração necessário para apontar qualquer componente para um broker em qualquer endereço de rede — sem recompilar imagens.

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY atuador_limitador.py .
ENV BROKER_HOST=localhost
CMD ["python", "-u", "atuador_limitador.py"]
```

A flag `-u` desativa o buffering de saída do Python, garantindo logs em tempo real no `docker logs`. O `docker-compose.yml` orquestra o ambiente completo:

```yaml
version: "3.9"
services:
  broker:
    build: { context: ., dockerfile: Dockerfile.broker }
    ports: ["5000:5000/udp", "5001:5001", "5002:5002"]

  sensor_velocidade_1:
    build: { context: ., dockerfile: Dockerfile.sensor_velocidade }
    environment: [BROKER_HOST=broker, SENSOR_ID=velocidade-001]
    depends_on: [broker]

  sensor_velocidade_2:
    build: { context: ., dockerfile: Dockerfile.sensor_velocidade }
    environment: [BROKER_HOST=broker, SENSOR_ID=velocidade-002]
    depends_on: [broker]

  sensor_temperatura:
    build: { context: ., dockerfile: Dockerfile.sensor_temperatura }
    environment: [BROKER_HOST=broker]
    depends_on: [broker]

  sensor_combustivel:
    build: { context: ., dockerfile: Dockerfile.sensor_combustivel }
    environment: [BROKER_HOST=broker]
    depends_on: [broker]

  sensor_oleo:
    build: { context: ., dockerfile: Dockerfile.sensor_oleo }
    environment: [BROKER_HOST=broker]
    depends_on: [broker]

  atuador_limitador:
    build: { context: ., dockerfile: Dockerfile.atuador_limitador }
    environment: [BROKER_HOST=broker]
    depends_on: [broker]

  atuador_resfriamento:
    build: { context: ., dockerfile: Dockerfile.atuador_resfriamento }
    environment: [BROKER_HOST=broker]
    depends_on: [broker]
```

Para escalar horizontalmente e testar convergência entre múltiplas instâncias:
```bash
docker compose up --scale sensor_velocidade_1=3
```

O broker escuta em `0.0.0.0` em todas as interfaces. Para conectar componentes de outra máquina na mesma rede local, basta definir `BROKER_HOST` com o IP da máquina hospedeira:
```bash
docker run -e BROKER_HOST=192.168.1.100 -e SENSOR_ID=velocidade-ext sensor_velocidade
```

</section>

---

<section id="execucao">
<h2>Como Executar</h2>

**Sem Docker** (Python 3.9+, sem dependências externas):
```bash
python broker.py                    # terminal 1 — inicie sempre o broker primeiro
python sensor_velocidade.py         # terminais separados para cada componente
python sensor_temperatura.py
python sensor_combustivel.py
python sensor_oleo.py
python atuador_limitador.py
python atuador_resfriamento.py
python cliente.py                   # cliente interativo
```

**Com Docker Compose:**
```bash
docker compose up --build
python cliente.py                   # rode o cliente localmente (BROKER_HOST=localhost)
```

**Variáveis de ambiente:**

| Variável | Componente | Padrão | Descrição |
|---|---|---|---|
| `BROKER_HOST` | Todos | `localhost` | IP ou hostname do broker |
| `SENSOR_ID` | Sensores | `<tipo>-<uuid>` | ID único — gerado automaticamente se ausente |
| `ACTUATOR_ID` | Atuadores | `<tipo>-<uuid>` | ID único — gerado automaticamente se ausente |

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
