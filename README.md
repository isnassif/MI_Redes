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
  <img src="docs/banner.png">
  <br>
  <strong>Sistema distribuído de telemetria veicular em execução</strong>
  <br><br>
</div>

Este projeto implementa um sistema distribuído de telemetria veicular baseado em um broker central e comunicação assíncrona no modelo publish-subscribe. Sensores simulam o comportamento de um veículo em tempo real, enviando dados contínuos de velocidade, temperatura, combustível e óleo, enquanto atuadores permitem interferência remota no sistema.

A arquitetura foi escolhida para eliminar o acoplamento entre componentes: sensores não conhecem clientes, clientes não conhecem atuadores, e toda a coordenação ocorre exclusivamente pelo broker. Isso permite que dispositivos entrem e saiam dinamicamente sem impacto no restante do sistema, garantindo flexibilidade e escalabilidade.

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

O sistema é composto por quatro tipos de processos independentes: broker, sensores, atuadores e cliente. O broker atua como núcleo central, responsável por receber telemetria, gerenciar conexões e distribuir dados.

Sensores geram dados continuamente e os enviam via UDP, priorizando desempenho. Atuadores mantêm conexão TCP persistente e aguardam comandos, enquanto o cliente se conecta para monitoramento e controle em tempo real. Essa separação garante que cada componente possa evoluir ou escalar de forma independente.

</section>

---

<section id="comunicacao">
<h2>Comunicação</h2>

A comunicação foi projetada com base em dois perfis distintos: telemetria de alta frequência e mensagens críticas de controle. Sensores utilizam UDP para envio contínuo de dados, reduzindo overhead e latência, enquanto TCP é utilizado para registro, comandos e sincronização de estado, onde confiabilidade é essencial.

O broker recebe dados dos sensores, mantém apenas o valor mais recente e distribui as informações para clientes assinantes. Atuadores recebem comandos via TCP e retornam seu estado, permitindo ao broker recalcular o comportamento global do sistema em tempo real.

</section>

---

<section id="protocolo">
<h2>Protocolo</h2>

A comunicação utiliza mensagens JSON, com encapsulamento em formato NDJSON nas conexões TCP. Cada dispositivo realiza um handshake inicial ao conectar, sendo registrado pelo broker e recebendo o estado atual do sistema.

O broker também envia atualizações de estado para sensores sempre que atuadores mudam, garantindo consistência global. Esse modelo permite comunicação simples, robusta e facilmente extensível.

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

O broker utiliza múltiplas threads para lidar simultaneamente com sensores, atuadores e clientes. Cada conexão é tratada de forma independente, enquanto estruturas compartilhadas são protegidas por locks específicos para evitar condições de corrida.

Uma lógica central importante é o cálculo da mediana dos sensores de mesmo tipo, utilizada como valor de referência global. Essa abordagem reduz o impacto de leituras anômalas e mantém o sistema estável.

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

O cliente é uma aplicação de terminal interativa que permite monitorar sensores em tempo real e enviar comandos para atuadores. A interface apresenta valores atualizados, gráficos ASCII e indicadores de alerta, oferecendo uma visão clara do estado do sistema.

Além do monitoramento, o cliente também permite controlar remotamente os atuadores, tornando possível alterar o comportamento do sistema diretamente pela interface.

</section>

---

<section id="confiabilidade">
<h2>Confiabilidade</h2>

O sistema foi projetado para tolerar falhas parciais sem interrupção global. Sensores, atuadores e clientes implementam reconexão automática, garantindo recuperação após falhas de rede ou reinicialização do broker.

Caso um atuador desconecte, o broker recalcula imediatamente o estado global e notifica os sensores afetados, evitando inconsistências. Mecanismos de keepalive são utilizados para detectar conexões inativas e manter o sistema consistente.

</section>

---

<section id="docker">
<h2>Docker</h2>

Todos os componentes foram containerizados, permitindo execução reproduzível em diferentes ambientes. O uso de Docker Compose simplifica a inicialização do sistema completo e possibilita a execução distribuída em múltiplas máquinas.

A configuração é mínima, sendo necessário apenas definir o endereço do broker por variável de ambiente.

</section>

---

<section id="execucao">
<h2>Execução</h2>

O sistema pode ser executado localmente com Python ou via Docker. No modo local, cada componente deve ser iniciado em um terminal separado, enquanto o uso de Docker permite subir toda a infraestrutura com um único comando.

Essa flexibilidade facilita tanto o desenvolvimento quanto a validação do sistema em cenários distribuídos reais.

</section>

---

<div align="center">
<sub>Feito com 🏎 e muitos <code>threading.Lock</code></sub>
</div>
