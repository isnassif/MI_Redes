<nav>
  <h2>Sumário</h2>
  <ul>
    <li><a href="#overview">Visão Geral</a></li>
    <li><a href="#arquitetura">Arquitetura</a></li>
    <li><a href="#comunicacao">Comunicação</a></li>
    <li><a href="#protocolo">Protocolo</a></li>
    <li><a href="#concorrencia">Concorrência</a></li>
    <li><a href="#estrutura">Estrutura do Projeto</a></li>
    <li><a href="#execucao">Execução</a></li>
    <li><a href="#docker">Docker</a></li>
  </ul>
</nav>

---

<section id="overview">
<h2>Visão Geral</h2>

<div align="center">
  <img src="docs/banner.png">
  <br>
  <strong>Sistema distribuído de telemetria veicular</strong>
  <br><br>
</div>

Sistema distribuído baseado em um broker central que integra sensores, atuadores e clientes através do modelo publish-subscribe. Sensores enviam telemetria contínua, atuadores recebem comandos e o cliente permite monitoramento e controle em tempo real.

A implementação é feita em Python puro (sem dependências externas), com comunicação híbrida (UDP + TCP) e suporte a execução distribuída via Docker.

</section>

---

<section id="arquitetura">
<h2>Arquitetura</h2>

<div align="center">
  <img src="docs/arquitetura_geral.png">
  <br>
  <strong>Broker como ponto central de integração</strong>
  <br><br>
</div>

O sistema é composto por quatro processos independentes:

- **Broker (`broker.py`)**  
  Mantém conexões, recebe telemetria, distribui dados e gerencia estado global.

- **Sensores (`sensor_*.py`)**  
  Publicam dados via UDP e mantêm canal TCP para sincronização.

- **Atuadores (`atuador_*.py`)**  
  Recebem comandos via TCP e reportam estado ao broker.

- **Cliente (`cliente.py`)**  
  Interface interativa para monitoramento e envio de comandos.

Toda comunicação ocorre exclusivamente via broker, eliminando dependências diretas entre componentes.

</section>

---

<section id="comunicacao">
<h2>Comunicação</h2>

O sistema utiliza dois protocolos com papéis bem definidos:

- **UDP (porta 5000)**  
  Usado por sensores para envio contínuo de telemetria (~1ms). Não há garantia de entrega, priorizando baixa latência.

- **TCP (portas 5001 e 5002)**  
  Usado para registro, controle, comandos e distribuição confiável de mensagens.

O broker mantém apenas o último valor de cada sensor, evitando acúmulo de mensagens em cenários de alta frequência.

</section>

---

<section id="protocolo">
<h2>Protocolo</h2>

Mensagens são codificadas em JSON. Em TCP, é utilizado **NDJSON** (uma mensagem por linha).

### Registro de sensor
```json
{ "register": "sensor", "type": "velocidade" }
