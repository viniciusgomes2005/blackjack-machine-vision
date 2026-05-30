# Foto - Resumo do problema de captura do robô

## Contexto

Este documento resume o problema atual do fluxo de `foto` no orquestrador do blackjack, o que foi testado, o que funciona, o que falha e quais hipóteses continuam válidas.

O objetivo do sistema é este:

1. O robô executa movimentos do jogo.
2. Quando uma carta precisa ser fotografada, o robô pulsa `foto`.
3. O Python detecta esse pulso.
4. O Python captura a imagem da câmera.
5. A visão reconhece a carta.
6. A carta é inserida na lista correta da rodada.

O problema central é que o `foto` ainda não está chegando de forma confiável ao Python no fluxo real.

---

## Situação atual resumida

- `startprog` funciona.
- O robô aceita comandos Modbus do Python para `startprog`, `hit`, `stand`, `split`, `double`.
- O Python lê a mão corretamente em muitos cenários.
- O Python ainda depende, em vários testes, de `c` manual para capturar cartas.
- O pulso `foto` não aparece de forma confiável no log do Python.
- O `foto` foi configurado no PolyScope como `Modbus Client I/O Setup`, não como saída digital física exposta diretamente no servidor Modbus do UR.

### Veredito provisório

Hoje o diagnóstico mais forte aponta para um problema no lado Python/bridge de Modbus, não para uma falha mecânica do robô:

- o robô responde a `startprog`;
- o Python já fala com o UR em PC -> robô;
- o que falha é a observação de `foto` no lado do PC;
- então o ponto mais suspeito é a leitura do sinal, o tipo de tabela Modbus ou a ligação entre o PolyScope e o servidor Modbus do Python.

---

## O que já foi confirmado

### 1. `startprog` funciona

O terminal mostrou claramente:

```text
[robot] pulso startprog hold=0.50s
[ur-direct] startprog=HI standard_addr=128 holding_ok=True coil_ok=False ...
[ur-direct] startprog=LO standard_addr=128 holding_ok=True coil_ok=False ...
```

Isso prova que:

- o Python consegue escrever no UR;
- o endereço de `startprog` está correto;
- a rede/Modbus para o caminho PC -> UR está funcional.

### 2. O Python consegue ler a mão

O log mostrou:

```text
[hand] estado=waiting_start leitura=4 estavel=4 acao=startprog
```

e depois:

```text
[hand] estado=initial_deal leitura=1 estavel=1 acao=hit
```

Então o reconhecimento dos gestos está ativo.

### 3. O modo de visão de cartas funciona quando a captura é manual

Quando você apertou `c`, o Python reconheceu cartas e alimentou a rodada.

Exemplo de log:

```text
[card] reconhecida via manual: 4
[round] carta inicial registrada em player_first
```

Isso confirma que:

- `process_image_as_card(...)` está funcionando;
- a rota de captura manual está correta;
- o problema não é a câmera em si, mas o gatilho automático.

### 4. Os testes automatizados do repositório passam

A suíte inteira passou várias vezes durante o trabalho:

```text
63 passed
```

Isso significa que as mudanças de código não quebraram os testes formais.

---

## O que falhou na prática

### 1. O `foto` não apareceu no log quando esperado

Mesmo com o orquestrador rodando, o boot mostrou:

```text
[robot] outputs snapshot (boot) foto=LO busyIO=LO source=pc_server:auto:none
```

Ou seja:

- o Python subiu o servidor Modbus local;
- o leitor foi inicializado;
- mas o `foto` não estava ativo naquele momento.

Depois disso, em vários testes, não apareceram mensagens como:

```text
[robot] outputs foto=HI ...
[robot] foto=HI; capturando carta
```

Isso é o sinal mais importante do problema.

### 2. A captura continua dependendo de `c` manual

A rodada só andou quando `c` foi pressionado manualmente.

Isso indica que:

- o fluxo automático de `foto` não está disparando;
- a automação real ainda não está fechada;
- a leitura do pulso no Python não está batendo com o que o PolyScope está emitindo.

### 3. A visão errou cartas em alguns testes

Foram observados erros como:

- `8` lido como `6`
- `J` lido como `A`
- alguns frames com leitura instável

Isso é um problema separado do `foto`, mas importante:

- mesmo que o pulso funcione, a captura pode reconhecer carta errada;
- portanto a automação precisa resolver dois pontos: gatilho e classificação.

---

## Arquitetura que existe hoje no código

### Caminho PC -> UR

Esse caminho funciona.

Responsabilidade:

- Python envia `startprog`, `hit`, `stand`, `split`, `double`.

Implementação:

- `RobotDirectClient` em `ur_robot_bridge.py`
- `pulse_signal(...)`
- `set_signal(...)`

### Caminho UR -> PC

Esse caminho foi o ponto de confusão.

Existem dois modelos possíveis:

#### Modelo A: ler o UR diretamente

O Python conecta no IP do UR e tenta ler `foto/busyIO` do servidor Modbus do robô.

Esse modelo usa:

- `RobotDirectClient.read_outputs(...)`

Esse modelo só funciona se o `foto` estiver exposto no Modbus server do UR.

#### Modelo B: o UR escreve no servidor Modbus do PC

Esse é o modelo que o PolyScope foi configurado para usar agora.

O robô está com:

- `foto` em `Modbus Client I/O Setup`
- `busyIO` em `Modbus Client I/O Setup`

Ou seja:

- o robô escreve o sinal no servidor Modbus do PC;
- o Python deve subir o servidor;
- o Python deve ler esse servidor local.

Esse modelo foi implementado no código com:

- `PcModbusOutputServer`
- `--pc-output-server`

---

## Estado da configuração do PolyScope

Você confirmou o seguinte:

- `foto` está no `Digital Output` do `MODBUS client IO Setup`
- o endereço do `foto` é `17`
- o programa faz `Set foto=HI:Pulse 1.0`
- `busyIO` existe, mas o mapeamento prático dele ainda não estava sendo usado de forma confiável

Isso significa que:

- o Python não deve procurar `foto` apenas no UR;
- ele deve servir como Modbus server local;
- o robô deve conectar nesse servidor e escrever o valor.

---

## O que foi testado

### Testado: leitura direta do UR

Resultado:

- funciona para `startprog`
- não resolveu o `foto`
- o `foto` não apareceu como pulso confiável

### Testado: servidor Modbus local do PC

Resultado:

- o servidor sobe
- o boot imprime o snapshot
- ainda não há evidência consistente de que o `foto` esteja chegando como mudança observável

### Testado: `foto_coil=1`

Resultado:

- estava errado para o seu caso
- foi ajustado para `17`

### Testado: `foto_coil=17`

Resultado:

- é o valor correto para o mapeamento que você descreveu
- ainda depende de o Python estar lendo do servidor certo

### Testado: captura manual com `c`

Resultado:

- funciona
- mas não resolve a automação

---

## Soluções já tentadas

### 1. Ler `foto` do servidor Modbus do UR

Status:

- não resolveu

Motivo provável:

- o `foto` não está exposto lá do jeito que o Python espera;
- ou o sinal foi movido para o caminho Modbus Client I/O Setup do PC.

### 2. Subir servidor Modbus local no PC

Status:

- implementado
- mas ainda faltam logs reais do `foto` chegando

Motivo provável se continuar falhando:

- IP/porta no PolyScope não estão apontando para o PC;
- o endereço 17 não está sendo escrito no tipo Modbus que o Python está lendo;
- o robô está escrevendo em outro tipo de tabela Modbus;
- o Python está lendo a tabela errada.

### 3. Ajustar `foto_coil` para `17`

Status:

- feito

Resultado:

- remove um erro de configuração explícito
- não garante por si só o recebimento

### 4. Adicionar diagnóstico no boot

Status:

- feito

Resultado:

- agora o Python mostra no boot algo como:

```text
[robot] outputs snapshot (boot) foto=LO busyIO=LO source=pc_server:auto:none
```

- isso ajuda a saber se o leitor está ativo

### 5. Persistir logs em arquivo

Status:

- feito

Arquivos gerados:

- `debug_hand_sign/orchestrator_live/latest_round_state.json`
- `debug_hand_sign/orchestrator_live/orchestrator_events.jsonl`
- `debug_hand_sign/orchestrator_live/latest_orchestrator_event.json`

Resultado:

- agora a execução deixa trilha persistente
- não depende só do terminal

---

## O que hoje parece mais provável

### Hipótese 1: o Python está lendo o canal errado, ou lendo do lugar errado

Essa é a hipótese mais provável hoje.

Sinais dessa hipótese:

- o boot mostra `foto=LO`
- não há transição de `foto` para `HI`
- a captura automática não acontece

Possíveis causas:

- IP errado no PolyScope
- porta errada
- endereço errado
- o tipo de dado usado pelo PolyScope não é o que o Python está lendo
- o sinal está indo para uma tabela Modbus diferente da lida pelo código

### Hipótese 2: o robô está configurado corretamente, mas o bridge do Python não está enxergando a tabela certa

Essa hipótese é uma variação da anterior, mas merece ser dita claramente:

- o robô pode estar escrevendo `foto` corretamente;
- o Python pode estar ouvindo o servidor certo;
- mas a implementação pode estar olhando `coils` enquanto o PolyScope escreve `holding_registers`, ou vice-versa.

Mesmo com o servidor do PC ativo, o `foto` pode estar indo para:

- `coils`
- `discrete_inputs`
- `holding_registers`
- `input_registers`

O código atualmente tenta modo `auto`, mas ainda pode haver uma diferença entre o tipo usado pelo PolyScope e o tipo lido pelo Python.

### Hipótese 3: o gatilho existe, mas o frame capturado não é o certo

Mesmo se `foto` chegar, a captura pode estar ocorrendo:

- cedo demais
- tarde demais
- antes da carta estar visível

Isso explicaria reconhecimento errado ou ausência de carta.

---

## Diagnóstico do log mais recente

O terminal mostrou:

```text
[pc-modbus] servidor local ouvindo em 0.0.0.0:31415
[robot] lendo foto/busyIO do servidor Modbus local do PC em 0.0.0.0:31415
[robot] outputs snapshot (boot) foto=LO busyIO=LO source=pc_server:auto:none
```

Interpretação:

- o servidor local abriu com sucesso;
- o leitor está ativo;
- no boot, o `foto` ainda não estava alto;
- isso não prova que o robô escreveu depois, mas prova que o monitor estava funcionando.

O problema é que, depois disso, ainda não apareceu `foto=HI`.

---

## O que funciona hoje

- envio de sinais do PC para o UR
- leitura da mão
- fluxo de rodada
- captura manual de carta
- motor de blackjack
- persistência de estado da rodada
- logs persistentes do orquestrador

---

## O que não funciona ainda

- leitura confiável do pulso `foto`
- automação completa sem `c` manual
- classificação de carta 100% consistente

---

## O que precisa ser resolvido para fechar o problema

### A. Confirmar o caminho físico do `foto`

Precisamos saber com certeza:

- o UR escreve em qual IP
- em qual porta
- em qual endereço
- em qual tipo Modbus

### B. Confirmar a leitura correspondente no Python

O Python precisa ler exatamente a mesma tabela que o PolyScope está escrevendo.

### C. Confirmar a janela temporal da foto

O `foto` só é útil se a captura ocorrer quando a carta já estiver visível.

### D. Melhorar a visão da carta

Mesmo com o gatilho certo, a classificação precisa ser estável o bastante para não confundir ranks.

---

## Próximos caminhos válidos

### Caminho 1: manter o servidor Modbus do PC e validar o tipo de registro

Esse é o caminho que já está mais perto do modelo atual.

Próximo passo:

- descobrir em qual tabela o PolyScope grava `foto`
- fazer o Python ler exatamente essa tabela

### Caminho 2: colocar um log de leitura por tipo de Modbus

Isso ajuda a descobrir:

- se `foto` aparece em `coils`
- ou em `holding_registers`
- ou em `discrete_inputs`
- ou em `input_registers`

### Caminho 3: instrumentar o PolyScope com teste isolado do `foto`

Fazer um teste simples no robô:

- pulsar `foto`
- deixar o PC mostrando se algum valor mudou

### Caminho 4: reforçar a visão da carta depois que o gatilho estiver certo

Depois que o `foto` estiver chegando, o próximo foco é:

- estabilizar o reconhecimento
- reduzir confusão entre valores parecidos
- garantir a mão correta e o índice correto

---

## Estado dos arquivos relevantes

- [robot_round_orchestrator.py](./robot_round_orchestrator.py)
- [ur_robot_bridge.py](./ur_robot_bridge.py)
- [blackjack_engine.py](./blackjack_engine.py)
- [single_card_vision.py](./single_card_vision.py)
- [debug_hand_sign/orchestrator_live/latest_round_state.json](./debug_hand_sign/orchestrator_live/latest_round_state.json)
- [debug_hand_sign/orchestrator_live/orchestrator_events.jsonl](./debug_hand_sign/orchestrator_live/orchestrator_events.jsonl)
- [debug_hand_sign/orchestrator_live/latest_orchestrator_event.json](./debug_hand_sign/orchestrator_live/latest_orchestrator_event.json)

---

## Conclusão curta

Hoje o sistema está assim:

- o jogo e o envio de sinais para o robô funcionam;
- a leitura manual das cartas funciona;
- o `foto` ainda não está entrando de forma confiável no Python;
- o defeito mais provável está no lado Python/Modbus, não no robô;
- o caminho correto agora é validar o tipo de Modbus que o PolyScope está escrevendo no servidor do PC e fechar essa leitura;
- depois disso, a automação de captura deve passar a funcionar sem `c`.
