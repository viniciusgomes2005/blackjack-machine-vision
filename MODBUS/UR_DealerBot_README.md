# DealerBot — Universal Robots (PolyScope) + Visão de Máquina via Modbus/TCP

Este documento descreve, em texto, o programa carregado no controlador UR
(`DealerBot`) — um dealer de Blackjack — para que um assistente de código
(Codex) consiga escrever o lado de **visão de máquina + Modbus/TCP** que
dialoga com o robô. O programa real é construído em PolyScope (árvore de
nós) e foi reconstruído a partir de fotos da tela; veja o arquivo
`ur_dealerbot_pseudocode.py` para o "código-fonte" linha-a-linha.

---

## 1. Visão geral do sistema

```
+---------------------+           Modbus/TCP            +---------------------+
|  PC (visão de       |  <----------------------------> |  UR Controller      |
|  máquina + servidor |   - PC escreve sinais p/ robô   |  (PolyScope)        |
|  Modbus)            |   - PC lê sinais do robô        |                     |
+---------------------+                                  +---------------------+
       |                                                          |
       | câmera USB / IP                                           | gripper com
       v                                                          v ventosa
   imagens das cartas / mesa                              robô movimenta cartas
```

- O **PC** roda dois papéis: detecta cartas/jogadas pela câmera **e** expõe
  um servidor Modbus/TCP que o robô lê (igual ao exemplo
  `Polygon_Params_Final.py`).
- O **robô** é o cliente Modbus, configurado em PolyScope:
  `Installation → MODBUS client → adicionar IP do PC, porta 502 →
  registrar inputs/outputs mapeados a nomes de sinal` (`hit`, `splitAB`, …).
- Os sinais que aparecem no programa UR como `Set busyIO=On`,
  `Wait startprog=HI`, `If hit ≡ True`, etc. **são bools nomeados** ligados a
  endereços Modbus/registradores físicos através dessa tela de Installation.

---

## 2. Mapa de I/O

### 2.1 PC → Robô (entradas digitais do robô)

| Nome no programa | DI  | Significado                                                 |
|------------------|-----|-------------------------------------------------------------|
| `hit`            | DI1 | Jogador pediu mais uma carta (na mão atual)                 |
| `splitAB`        | DI2 | Split entre as posições A e B                               |
| `double`         | DI3 | Jogador dobrou a aposta (recebe 1 carta e avança de mão)   |
| `startprog`      | DI4 | Visão libera o início da partida (deal inicial)             |
| `stand`          | DI5 | Jogador parou (na mão atual)                                |
| `splitBC`        | DI6 | Split entre as posições B e C                               |
| `splitAC`        | DI7 | Split entre as posições A e C                               |

Todos são tratados como `True` quando o sinal está em `HI` e `False` quando
`LO`. A visão deve segurar o sinal em `HI` somente enquanto o robô precisa
enxergá-lo (mais detalhes em §4 — handshake).

### 2.2 Robô → PC (saídas digitais do robô)

| Nome no programa | DO  | Significado                                                     |
|------------------|-----|-----------------------------------------------------------------|
| `foto`           | DO1 | **Pulso de 1.0 s em `HI`** — pedido para a visão tirar a foto da carta virada |
| `busyIO`         | DO2 | `HI` enquanto o robô se move / executa uma sub-rotina; `LO` quando está parado esperando entrada |

> ⚠️ Existe ainda um sinal interno `DI[0]` (`Until DI[0]=HI`) usado em
> `pegarCarta` e em `virarDealerFechada`. Esse é o **sensor da ventosa**
> (vácuo / proximidade na garra) — **não é controlado pela visão**, é um
> sensor físico no end-effector. Ignorar do lado do PC.

### 2.3 Saídas controladas internamente pelo robô (não são I/O)

| Nome      | Tipo               | Significado                                  |
|-----------|--------------------|----------------------------------------------|
| `ventosa` | DO interno         | Liga/desliga a sucção da ventosa             |
| `splitcont`, `standcont` | variáveis int | Contadores internos de splits e stands       |

---

## 3. Estrutura do programa do robô (alto nível)

```
INIT
  ├── abre socket TCP para 10.102.28.161:31415  (var_1)
  ├── splitcont := 0
  ├── standcont := 0
  ├── busyIO := On      ; robô ocupado durante setup
  ├── ventosa := Off
  ├── chama standby     ; vai para posição neutra
  └── espera startprog == HI

DEAL INICIAL  (5 cartas em ordem, alternando jogador / dealer)
  pegarCarta → virarCarta → entregaPlayer            ; 1a carta do jogador
  pegarCarta → virarCarta → entregaDealerAberta      ; 1a carta do dealer (aberta)
  pegarCarta → virarCarta → entregaPlayer            ; 2a carta do jogador
  pegarCarta              → entregaDealerFechada     ; 2a carta do dealer (fechada, NÃO vira)
  standby

FASE DO JOGADOR  (loop enquanto standcont < splitcont + 1)
  if hit:                                       ; pedir carta para a mão atual
      pegarCarta → virarCarta
      if standcont == 0: entregaPlayer
      if standcont == 1: split1
      if standcont == 2: split2
      standby
  if double:                                    ; dobrar — recebe carta e avança de mão
      pegarCarta → virarCarta
      (mesmo despacho pelo standcont)
      standcont += 1
      standby
  if splitAB:                                   ; split entre posições A e B
      splitcont += 1
      pegarCarta → virarCarta → entregaPlayer
      pegarCarta → virarCarta → split1
      standby
  if splitAC:                                   ; split entre posições A e C
      splitcont += 1
      pegarCarta → virarCarta → entregaPlayer
      pegarCarta → virarCarta → split2
      standby
  if splitBC:                                   ; split entre posições B e C
      splitcont += 1
      pegarCarta → virarCarta → split1
      pegarCarta → virarCarta → split2
      standby
  if stand:                                     ; parar na mão atual
      standcont += 1

FASE DO DEALER
  espera stand == LO                            ; visão confirma fim da fase do jogador
  virarDealerFechada                            ; vira a carta fechada do dealer
  loop enquanto stand == False:
      if hit:                                   ; dealer bate
          pegarCarta → virarCarta → entregaDealerAberta → standby

FIM
  socket_close()
```

### Sub-rotinas (descritas em prosa, ver pseudocódigo para waypoints)

| Sub-rotina             | O que faz                                                                                                          |
|------------------------|--------------------------------------------------------------------------------------------------------------------|
| `standby`              | Move para waypoints neutros (`14`, `20`) e zera `busyIO`. É a única posição em que o robô espera entrada da visão. |
| `pegarCarta`           | Liga `busyIO`, vai até o baralho, liga ventosa, desce até `Until DI[0]=HI` (sensor da ventosa), recua.              |
| `virarCarta`           | Movimenta para a área de virada, solta a ventosa, dá **`Set foto=HI:Pulse 1.0`** (visão tira a foto), aguarda 1 s, repega a carta. |
| `entregaPlayer`        | Coloca a carta na posição do jogador (waypoints 9, 23).                                                            |
| `entregaDealerAberta`  | Coloca a carta aberta na posição do dealer.                                                                        |
| `entregaDealerFechada` | Coloca a carta fechada na posição do dealer (sem passar por `virarCarta`).                                         |
| `virarDealerFechada`   | Pega a carta fechada do dealer, vira-a, recoloca aberta. Usa `Until DI[0]=HI` na pegada.                            |
| `split1`               | Coloca a carta na posição de split #1 (waypoint 24).                                                               |
| `split2`               | Coloca a carta na posição de split #2 (waypoint 15).                                                               |

Toda sub-rotina **começa com `Set busyIO=On`** e termina implicitamente em
`busyIO=Off` ao voltar para `standby` (que é o único nó que zera `busyIO`).

---

## 4. Handshake — como a visão deve dialogar

> Regra geral: **só mude um sinal de entrada (`hit`, `double`, `stand`,
> `splitAB`, `splitAC`, `splitBC`) quando `busyIO == LO`**. Esse é o
> momento em que o robô está parado em `standby` consultando as condições
> dentro de um `Loop` do PolyScope.

Fluxo recomendado para o lado do PC:

1. Aguardar `busyIO == LO` (robô em `standby`).
2. Decidir a próxima ação a partir da câmera.
3. Setar **exatamente um** sinal em `HI` (mutuamente exclusivos por desenho:
   `hit`, `double`, `stand`, `splitAB`, `splitAC`, `splitBC`).
4. Aguardar `busyIO == HI` (robô aceitou e começou a executar).
5. Voltar o sinal para `LO` (importante: o `If` do PolyScope é por nível,
   não por borda — manter `HI` faria o robô re-disparar a mesma ação na
   próxima iteração do loop).
6. Voltar para o passo 1.

Sub-protocolo da foto (`foto` / `DO1`):

- Em `virarCarta`, o robô executa `Set foto=HI:Pulse 1.0`, ou seja, mantém
  `foto` em `HI` por **1.0 s** e volta para `LO` automaticamente.
- Logo depois há `Wait: 1.0`, então a visão tem ~1 s para capturar e
  classificar a carta antes de o robô continuar.
- A visão deve capturar **na borda de subida** de `foto`.

Início e fim de partida:

- O ciclo começa quando a visão põe `startprog = HI` (a visão pode baixar
  `startprog` logo após observar `busyIO == HI`).
- O ciclo termina quando a visão põe `stand = HI`, **mantém em `HI`** até
  o robô consumir (incrementa `standcont`), e em seguida **põe `stand =
  LO`** — o robô tem um `Wait stand=LO` antes de virar a carta fechada do
  dealer.
- Durante a fase do dealer, a visão pulsa `hit` para forçar o robô a bater
  e finalmente põe `stand = HI` para sair do loop final.

---

## 5. Como mapear os bools sobre Modbus

O exemplo `Polygon_Params_Final.py` mostra o padrão básico (PC = servidor
Modbus/TCP, robô = cliente, robô lê *Register Inputs*). Para este projeto
há duas formas razoáveis:

**A. Um registrador por sinal (mais simples para começar)**
- Use endereços 0..6 para os 7 inputs do robô (1 = HI, 0 = LO).
- O PC chama `server.data_bank.set_input_registers(addr, [0|1])`.
- Em PolyScope, *Installation → MODBUS client* adiciona 7 *Register Inputs*
  e cada um é mapeado a um nome (`hit`, `splitAB`, …) via *I/O Setup → Modbus*.
- Para as saídas (`foto`, `busyIO`) o PC se conecta como **cliente** ao
  Modbus server do próprio robô (porta 502 do controlador UR) e lê os
  *coils*/*registers* mapeados às DOs.

**B. Um único registrador de 16 bits empacotando todos os 7 sinais**
- bit 0 = `hit`, bit 1 = `splitAB`, …, bit 6 = `splitAC`.
- PC escreve um inteiro só; o robô usa expressões em PolyScope para
  extrair cada bit. Mais econômico, mais sujeito a erros — recomenda-se A.

Mapeamento sugerido (forma A):

| Tipo                | Endereço | Sinal       | Direção            |
|---------------------|----------|-------------|--------------------|
| Input Register PC   | 0        | `hit`       | PC → robô          |
| Input Register PC   | 1        | `splitAB`   | PC → robô          |
| Input Register PC   | 2        | `double`    | PC → robô          |
| Input Register PC   | 3        | `startprog` | PC → robô          |
| Input Register PC   | 4        | `stand`     | PC → robô          |
| Input Register PC   | 5        | `splitBC`   | PC → robô          |
| Input Register PC   | 6        | `splitAC`   | PC → robô          |
| DO do robô          | DO1      | `foto`      | robô → PC (ler)    |
| DO do robô          | DO2      | `busyIO`    | robô → PC (ler)    |

O esqueleto Python (`modbus_vision_skeleton.py`) já implementa A.

---

## 6. Arquivos deste pacote

- `UR_DealerBot_README.md` — este documento (contexto para o Codex).
- `ur_dealerbot_pseudocode.py` — reconstrução fiel da árvore PolyScope em
  pseudo-Python; sub-rotinas em ordem, com waypoints e I/O comentados.
- `modbus_vision_skeleton.py` — esqueleto do programa do PC (servidor
  Modbus + ganchos para visão de máquina + leitura das DOs do robô).
  Construído sobre o estilo do `Polygon_Params_Final.py`.
