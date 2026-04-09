<nav id="sumario-completo">
  <h2>Sumário</h2>
  <ul>
    <li><a href="#descricao-geral">Descrição Geral</a></li>
    <li><a href="#arquitetura">Arquitetura</a></li>
    <li><a href="#comunicacao">Comunicação</a></li>
    <li><a href="#protocolo">Protocolo</a></li>
    <li><a href="#concorrencia">Concorrência</a></li>
    <li><a href="#cliente">Cliente</a></li>
    <li><a href="#confiabilidade">Confiabilidade</a></li>
    <li><a href="#docker">Docker</a></li>
    <li><a href="#execucao">Execução</a></li>
  </ul>
</nav>

---

<section id="descricao-geral">
<h2>Descrição Geral</h2>

<div align="center">
  <img width="726" height="368" alt="image" src="https://github.com/user-attachments/assets/e9daa5e8-f360-4eb4-a8db-eb6ce268ab69" />
  <br>
  <strong>Sistema distribuído de telemetria veicular em execução</strong>
  <br><br>
</div>

Este projeto implementa um sistema distribuído de telemetria veicular baseado em um broker central responsável por orquestrar sensores, atuadores e clientes. Sensores publicam dados continuamente, atuadores recebem comandos e o cliente consome e controla o sistema em tempo real.

A arquitetura segue o modelo publish-subscribe, onde todos os componentes se comunicam exclusivamente com o broker. Isso elimina dependências diretas entre processos e permite que sensores, atuadores e clientes sejam adicionados ou removidos dinamicamente sem necessidade de reconfiguração.

A implementação é feita em Python puro utilizando sockets TCP e UDP, sem bibliotecas externas, com foco em controle explícito de rede e concorrência.

</section>

---

<section id="arquitetura">
<h2>Arquitetura</h2>

<div align="center">
  <img src="docs/arquitetura_geral.png">
  <br>
  <strong>Arquitetura geral do sistema</strong>
  <br><br>
</div>

O sistema é composto por quatro processos independentes executados separadamente:

O broker (`broker.py`) mantém todas as conexões TCP ativas, recebe telemetria via UDP e distribui dados para clientes inscritos. Ele também centraliza o estado global dos atuadores e calcula valores agregados dos sensores.

Sensores (`sensor_*.py`) possuem duas responsabilidades principais: envio contínuo de telemetria via UDP e manutenção de uma conexão TCP persistente para sincronização de estado com o broker.

Atuadores (`atuador_*.py`) mantêm conexão TCP com o broker e ficam em loop aguardando comandos. Ao receber um comando, atualizam seu estado interno e notificam o broker.

O cliente (`cliente.py`) conecta via TCP, assina sensores e envia comandos para atuadores, funcionando como interface de interação com o sistema.

</section>

---

<section id="comunicacao">
<h2>Comunicação</h2>

A comunicação é dividida entre dois canais distintos:

Sensores utilizam UDP (porta 5000) para envio de telemetria em alta frequência. Esse canal não possui garantia de entrega nem controle de fluxo, reduzindo overhead e evitando bloqueios.

TCP é utilizado para controle (portas 5001 e 5002), incluindo registro de dispositivos, comandos, sincronização de estado e comunicação com clientes. Todas as mensagens críticas passam por esse canal.

O broker mantém apenas o último valor recebido de cada sensor, evitando filas e crescimento de memória em cenários de alta taxa de envio.

</section>

---

<section id="protocolo">
<h2>Protocolo</h2>

Todas as mensagens utilizam JSON. Em TCP, o protocolo é baseado em NDJSON (uma mensagem por linha delimitada por `\n`), permitindo parsing incremental com buffer.

Cada dispositivo inicia com um handshake de registro, informando tipo e identificador. Após o registro, o broker associa o socket ao dispositivo e passa a tratá-lo como ativo.

Sensores enviam telemetria via UDP contendo `id`, `type`, `data` e `ts`. Atuadores recebem comandos via TCP e respondem com seu estado atualizado.

O broker também envia mensagens de push para sensores sempre que o estado de um atuador muda, garantindo sincronização imediata sem polling.

</section>

---

<section id="concorrencia">
<h2>Concorrência</h2>

<div align="center">
  <img src="docs/threading.png">
  <br>
  <strong>Modelo de concorrência do broker</strong>
  <br><br>
</div>

O broker é multi-threaded e opera com três loops principais: recepção UDP, aceitação de conexões TCP de dispositivos e aceitação de clientes. Cada conexão aceita gera uma thread dedicada responsável por todo o ciclo de vida do socket.

Estruturas compartilhadas como listas de sensores, atuadores e valores agregados são protegidas com `threading.Lock`, garantindo acesso consistente entre threads.

Para agregação de dados, o broker calcula a mediana dos sensores de mesmo tipo e armazena como valor canônico. Esse valor é utilizado para sincronização e correção de divergência entre múltiplas instâncias.

</section>

---

<section id="cliente">
<h2>Cliente Terminal</h2>

<div align="center">
  <img src="docs/cliente_monitoramento.gif">
  <br>
  <strong>Monitoramento em tempo real</strong>
  <br><br>
</div>

O cliente é uma aplicação de terminal que mantém conexão TCP com o broker e recebe telemetria em tempo real apenas dos sensores assinados.

A renderização é feita diretamente no terminal utilizando escape codes ANSI, exibindo valores, gráficos ASCII e indicadores de estado. O cliente também envia comandos para atuadores através do mesmo canal TCP, utilizando mensagens JSON.

Toda a lógica de interface é local — o broker apenas encaminha dados e comandos.

</section>

---

<section id="confiabilidade">
<h2>Confiabilidade</h2>

O sistema trata falhas de forma explícita. Conexões TCP utilizam timeout e mensagens de keepalive (`ping`) para detectar desconexões.

Todos os componentes implementam reconexão automática, tentando restabelecer a conexão com o broker em intervalos fixos.

Quando um atuador desconecta, o broker remove seu estado, recalcula o estado global e envia atualizações para sensores afetados. Clientes recebem eventos refletindo a mudança de topologia.

Mensagens inválidas são descartadas silenciosamente, evitando interrupção do fluxo principal.

</section>

---

<section id="docker">
<h2>Docker</h2>

Os componentes são containerizados individualmente, permitindo execução isolada e reproduzível.

O `docker-compose.yml` define todos os serviços e a rede interna. A comunicação ocorre utilizando o nome do serviço `broker` como hostname.

A configuração depende apenas da variável `BROKER_HOST`, permitindo execução distribuída em diferentes máquinas sem alteração de código.

</section>

---

<section id="execucao">
<h2>Execução</h2>

O sistema pode ser executado diretamente com Python, iniciando cada componente em um terminal separado, ou via Docker Compose.

```bash
python broker.py
python sensor_velocidade.py
python atuador_limitador.py
python cliente.py
