# Blackjack Machine Vision

## Testando camera USB no Linux

O projeto permite escolher o indice da camera pelo terminal. Para a contagem de
dedos:

```bash
source .venv/bin/activate
python hand_sign_vision.py --camera 2
```

Para a aplicacao principal:

```bash
source .venv/bin/activate
python main.py --camera 2
```

Para usar o reconhecedor validado de uma carta isolada na rampa/ROI da camera:

```bash
source .venv/bin/activate
python main.py --camera 2 --single-card-camera
```

O mesmo reconhecedor tambem pode ser chamado diretamente:

```bash
python single_card_vision.py --camera 2
python single_card_vision.py --image caminho/para/foto.jpg
python single_card_vision.py --bank Base_de_dado_renomeada
```

Para testar o reconhecedor de sinais de mao no quadrado vermelho:

```bash
python hand_sign_vision.py --camera 0
```

O reconhecedor usado por padrao no robo e um pipeline hibrido com
skeleton/landmarks do MediaPipe ligado. Quando o skeleton detecta uma mao valida
fora dos exemplos conhecidos, ele melhora a generalizacao entre pessoas. Quando
o MediaPipe nao detecta a mao alvo ou a imagem esta muito proxima da base
rotulada em `Sinais/`, o classificador calibrado pela base vence para preservar
os casos ja validados.

A janela da camera abre em tela cheia. `Espaco` captura, salva a foto em
`Sinais/` e o terminal imprime `1`, `2`, `3`, `4`, `5` ou `vazio`. Voce pode
apertar `Espaco` varias vezes; `Esc` sai.

As imagens com nomes `1Dedo...`, `2Dedo...`, `3Dedo...`, `4Dedo...`,
`5Dedo...` e `Vazio...` em `Sinais/` tambem funcionam como base de calibracao
visual. O classificador usa a aparencia da mao dentro do quadrado vermelho e nao o
nome do arquivo no momento da inferencia.

Se voce ja souber o rotulo real do teste, salve direto como parte da base
rotulada:

```bash
python hand_sign_vision.py --camera 0 --label 1
```

Para testar uma imagem estatica:

```bash
python hand_sign_vision.py --image Sinais/3dedo1.jpg
```

Para salvar debug da captura:

```bash
python hand_sign_vision.py --camera 0 --save-debug
```

## Simular uma rodada local

Para testar a logica completa do Blackjack sem Modbus e sem braco robotico:

```bash
python main.py --simulate-round
```

Esse modo usa uma imagem da mesa para reconhecer as cartas, uma imagem em
`Sinais/` para reconhecer o gesto de mao, executa o loop da rodada e imprime o
resultado. Voce pode trocar os insumos:

```bash
python main.py --simulate-round \
  --round-image images/table_round_01_player_QS_5S_dealer_2H_3S.jpeg \
  --hand-image Sinais/4Dedo1.jpg \
  --dealer-hole 3S \
  --dealer-draw KH \
  --dealer-draw 6C
```

Para simular cartas por argumento, sem depender da imagem da mesa, informe as
duas cartas iniciais do jogador e a carta aberta do dealer:

```bash
python main.py --simulate-round \
  --player-card 8H \
  --player-card 8D \
  --dealer-upcard 6S \
  --dealer-hole 10H \
  --hand-image Sinais/2Dedo1.jpg \
  --hand-image Sinais/4Dedo1.jpg \
  --hand-image Sinais/4Dedo2.jpg \
  --player-draw 3H \
  --player-draw 2C \
  --dealer-draw 5C
```

Nesse exemplo, as imagens de mao simulam `split`, depois `stand`, depois
`stand`. As cartas em `--player-draw` entram na ordem em que a rodada precisar
comprar cartas para jogador/splits, e `--dealer-draw` entra na vez do dealer.

Se quiser testar apenas a regra e o loop do Blackjack, sem imagens, use o
simulador manual:

```bash
python blackjack_manual_simulator.py \
  --player-card 8H \
  --player-card 8D \
  --dealer-upcard 6S \
  --dealer-hole 10H \
  --action split \
  --action stand \
  --action stand \
  --player-draw 3H \
  --player-draw 2C \
  --dealer-draw 5C
```

Para digitar acoes e cartas futuras passo a passo durante a rodada:

```bash
python blackjack_manual_simulator.py \
  --player-card 8H \
  --player-card 8D \
  --dealer-upcard 6S \
  --dealer-hole 10H \
  --interactive
```

## Script principal do DealerBot

O script principal preparado para a logica do jogo e:

```bash
python DealerBotMain.py --camera 0 --hand-interval 5
```

Ele abre a camera, analisa o quadrado vermelho a cada 5 segundos e imprime no
terminal a decisao detectada:

| Dedos | Acao |
| --- | --- |
| 1 | hit |
| 2 | split |
| 3 | double |
| 4 antes da rodada | startprog |
| 5 durante a rodada | stand |
| vazio | sem acao |

Para ver as janelas de debug da area vermelha e da mascara de pele:

```bash
python DealerBotMain.py --camera 0 --hand-interval 5 --show
```

Por padrao, `DealerBotMain.py` nao salva fotos e nao envia nada ao robo. Para
habilitar envio direto ao UR pelo `ur_robot_bridge.py`, use:

```bash
python DealerBotMain.py --camera 0 --hand-interval 5 --send-robot
```

Nesse modo, `split` e enviado como `splitAB` ate a logica do jogo decidir entre
`splitAB`, `splitBC` e `splitAC`.

## Testar gestos no orquestrador de rodada

Para validar primeiro o gesto de 4 dedos sem enviar nada ao robo:

```bash
python robot_round_orchestrator.py --camera 0 --show --dry-run-robot --hand-interval 1 --stable-samples 2
```

Resultado esperado no terminal, apos manter 4 dedos no quadrado vermelho por
duas leituras:

```text
[hand] estado=waiting_start dedos=4 acao=startprog
[robot] pulso startprog hold=0.50s
[round] startprog enviado; capture as cartas iniciais com tecla c
```

Nesse modo o pulso e apenas impresso. Quando quiser acionar o UR, remova
`--dry-run-robot`.

Para testar fisicamente os gestos no robo sem depender da rodada ou das cartas,
use `--gesture-test`. Nesse modo 1 dedo pulsa `hit`, 2 dedos pulsa `splitAB`, 3
dedos pulsa `double`, 4 dedos pulsa `startprog` e 5 dedos pulsa `stand`:

```bash
python robot_round_orchestrator.py --camera 0 --show --gesture-test --hand-interval 1 --stable-samples 2
```

No modo normal de rodada, depois do `startprog`, capture as cartas iniciais com
`c` na ordem: primeira carta do jogador, carta aberta do dealer, segunda carta
do jogador. So depois disso o estado vira `player_turn` e gestos como `hit`
sao enviados ao robo.

Depois de `hit`, `double` ou `split`, o orquestrador envia o pulso ao robo e
fica aguardando a proxima carta. Quando a carta estiver na rampa, pressione
`c`. O loop principal continua vivo e a janela de debug da mao continua
atualizando.

Com `--show`, o orquestrador tambem abre as janelas `Robot Round Orchestrator -
mao` e `Robot Round Orchestrator - mascara mao`. Use essas janelas para validar
se o quadrado vermelho esta sendo encontrado e se a mascara de pele corresponde
de fato aos dedos.

## Comunicacao com o Universal Robots

O script principal de Modbus/TCP do PC e:

```bash
python ur_robot_bridge.py --no-ur-read
```

Ele expoe os Input Registers que o programa PolyScope le como entradas:

| Register | Sinal |
| --- | --- |
| 128 | startprog |
| 129 | hit |
| 130 | double |
| 131 | stand |
| 132 | splitAB |
| 133 | splitBC |
| 134 | splitAC |

Para liberar o inicio da partida pelo `startprog` (DI4 / register 128), o
script conecta diretamente no controlador UR em `10.103.18.245:502`:

```bash
python ur_robot_bridge.py --no-ur-read --startprog
```

`--no-ur-read` pode ficar no comando por compatibilidade; no modo direto ele
apenas evita subir o servidor Modbus do PC.

O modo cliente direto tambem pode ser chamado explicitamente:

```bash
python ur_robot_bridge.py --direct-to-robot --startprog --hold 5 --no-interactive
```

Nesse modo, o PC conecta em `10.103.18.245:502` e escreve os sinais no bloco
`128..134` como holding registers e coils.

Para definir qualquer sinal explicitamente:

```bash
python ur_robot_bridge.py --direct-to-robot --set startprog=true
python ur_robot_bridge.py --direct-to-robot --set startprog=false
python ur_robot_bridge.py --direct-to-robot --set hit=true
python ur_robot_bridge.py --direct-to-robot --set stand=false
```

Para abrir o prompt interativo direto no robo:

```bash
python ur_robot_bridge.py --direct-to-robot
```

Comandos no prompt:

```text
ur-direct> start
ur-direct> hit
ur-direct> stand
ur-direct> set startprog true
ur-direct> set startprog false
ur-direct> status
```

Se a configuracao antiga do robo espera conectar no PC como servidor Modbus,
force esse modo com:

```bash
python ur_robot_bridge.py --server-mode --pc-host 0.0.0.0 --no-ur-read
```

Se a leitura das saidas `foto`/`busyIO` do robo ainda nao estiver configurada,
rode com `--no-ur-read`. Nesse modo o script segura cada sinal em HI por um
tempo fixo (`--hold`, padrao 0.5 s) e depois baixa.

Para diagnosticar no PolyScope, mantenha `startprog` ligado ate Ctrl+C:

```bash
python ur_robot_bridge.py --no-ur-read --diagnose-start
```

O bridge publica os mesmos valores em input registers, holding registers,
coils e discrete inputs para facilitar a configuracao inicial no UR.

Ao iniciar, o sistema imprime o indice da camera, o backend usado pelo OpenCV, a
resolucao solicitada e a resolucao real aplicada. Ele tenta primeiro
`1920x1080` e depois `1280x720`.

Comandos uteis para descobrir e ajustar cameras no Linux:

```bash
v4l2-ctl --list-devices
v4l2-ctl -d /dev/video0 --list-ctrls
v4l2-ctl -d /dev/video0 --list-formats-ext
guvcview
```

Se a camera expuser controle de zoom via v4l2, teste zerar o zoom manualmente:

```bash
v4l2-ctl -d /dev/video0 --set-ctrl=zoom_absolute=0
```

A janela principal deve mostrar o frame completo da camera. Os recortes de ROI
sao usados apenas para processamento interno e janelas auxiliares de debug.

---

## Sessao posterior a implementacao da logica correta do Blackjack

Esta secao foi adicionada depois da implementacao do motor correto de
Blackjack local. A partir deste ponto, o projeto passa a ter uma separacao mais
clara entre:

- logica do jogo;
- visao computacional;
- simulacao manual;
- simulacao com imagens;
- comunicacao futura com o robo.

O objetivo atual e permitir testar uma rodada completa sem depender ainda do
braco robotico. A comunicacao com o robo deve ser ligada depois, usando os
eventos e as acoes aceitas pelo motor de Blackjack.

### Arquivos principais apos a implementacao

`blackjack_engine.py`

Motor central da regra do Blackjack. Ele nao depende de camera, OpenCV, Modbus
ou robo. Este arquivo calcula valores, controla o loop da rodada e resolve o
resultado final.

Ele contem:

- `BlackjackHand`: representa uma mao do jogador.
- `BlackjackRound`: representa uma rodada completa.
- `start_round`: inicia a rodada com duas cartas do jogador, uma carta aberta
  do dealer e uma carta fechada do dealer.
- `legal_player_actions`: retorna quais acoes sao validas no estado atual.
- `apply_player_action`: aplica `hit`, `stand`, `split` ou `double`.
- `play_player_turn`: executa o loop das maos do jogador.
- `play_dealer_turn`: executa o loop do dealer.
- `resolve_round`: calcula `win`, `lose` ou `push` para cada mao.
- `run_blackjack_round`: executa a rodada inteira.
- `round_summary`: gera um resumo estruturado para debug, testes e integracao.

`main.py`

Aplicacao principal de visao e simulacao. Continua tendo o modo com camera ao
vivo, mas agora tambem possui `--simulate-round`, que permite testar a rodada
usando imagens salvas ou cartas informadas por argumento.

`blackjack_manual_simulator.py`

Arquivo especifico para simulacoes manuais, sem imagem e sem robo. Ele existe
para testar apenas regra e loop do Blackjack. Serve para validar cenarios como
split, double, bust, dealer comprando, dealer parando em 17 e resolucao final.

`card_vision.py`

Reconhece cartas em regioes da imagem. Ele detecta cartas, corrige perspectiva,
extrai o canto da carta e compara rank/naipe com templates.

`single_card_vision.py`

Reconhecedor alternativo para uma carta isolada em uma ROI calibrada. Ele e
util para testes especificos de uma carta fora do pipeline completo da mesa.

`hand_sign_vision.py`

Reconhece sinais de mao. Ele detecta a area vermelha, segmenta a mao, conta
dedos e retorna o numero reconhecido.

`chip_vision.py`

Detecta fichas por cor, calcula aposta e otimiza fichas. A regra atual do
Blackjack nao usa aposta real para resolver a rodada, mas esse modulo continua
disponivel para a parte visual/economica do projeto.

`ur_robot_bridge.py`

Camada de comunicacao Modbus/TCP com o Universal Robots. Neste momento ela nao
esta conectada ao loop completo da rodada, mas ja define os sinais que serao
usados na integracao.

### Regras implementadas no motor de Blackjack

As regras implementadas seguem o documento de regras do projeto:

- O objetivo e chegar o mais perto possivel de 21 sem ultrapassar.
- Cartas `2` a `10` valem o proprio numero.
- `J`, `Q` e `K` valem 10.
- `A` vale 11, mas vira 1 quando necessario para evitar estouro.
- Blackjack natural e apenas mao inicial de duas cartas com `A` + carta de
  valor 10.
- Acoes validas do jogador: `hit`, `stand`, `split`, `double`.
- `hit`: compra uma carta para a mao ativa.
- `stand`: encerra a mao ativa.
- `double`: so e permitido com exatamente duas cartas, compra uma unica carta e
  encerra a mao automaticamente.
- `split`: so e permitido com duas cartas de mesmo rank.
- O maximo e de 2 splits por rodada, gerando no maximo 3 maos finais.
- Maos splitadas sao jogadas da esquerda para a direita.
- Nao existe regra especial para split de Ases.
- Bust encerra a mao e aquela mao perde automaticamente.
- O dealer joga depois que todas as maos do jogador encerram.
- O dealer compra em 16 ou menos.
- O dealer para em qualquer 17 ou mais, incluindo soft 17.
- Cada mao do jogador e resolvida separadamente contra a mao final do dealer.

### Loop da rodada

O loop logico da rodada esta em `blackjack_engine.py`.

O fluxo e:

1. Inicia a rodada com:
   - duas cartas do jogador;
   - uma carta aberta do dealer;
   - uma carta fechada do dealer.
2. Define a primeira mao do jogador como mao ativa.
3. Enquanto existir mao ativa:
   - calcula as acoes legais;
   - recebe uma acao externa;
   - rejeita a acao se ela for ilegal;
   - aplica a acao se ela for legal;
   - se a mao encerrou, avanca para a proxima mao.
4. Quando todas as maos do jogador encerram:
   - revela a carta fechada do dealer;
   - dealer compra enquanto total < 17;
   - dealer para em total >= 17.
5. Resolve cada mao:
   - jogador bustado: `lose`;
   - dealer bustado e jogador nao bustado: `win`;
   - total do jogador maior: `win`;
   - total do jogador menor: `lose`;
   - total igual: `push`.

### Variaveis principais do motor

`BlackjackHand.cards`

Lista de cartas da mao. Cada carta segue o formato usado pela visao:

```python
{
    "rank": "8",
    "suit": "hearts",
    "blackjack_value": 8,
    "card_id": None,
    "status": "ok",
}
```

`BlackjackHand.status`

Estado da mao:

- `active`: mao ainda esta sendo jogada;
- `stood`: jogador parou;
- `busted`: mao estourou;
- `doubled`: jogador fez double e a mao foi encerrada;
- `blackjack`: blackjack natural.

`BlackjackHand.doubled`

Indica se aquela mao fez double.

`BlackjackHand.from_split`

Indica se aquela mao foi criada a partir de split.

`BlackjackHand.result`

Resultado final da mao:

- `win`;
- `lose`;
- `push`.

`BlackjackRound.player_hands`

Lista ordenada de maos do jogador. Comeca com uma mao e pode crescer ate tres
maos quando ha splits.

`BlackjackRound.active_hand_index`

Indice da mao ativa dentro de `player_hands`.

`BlackjackRound.split_count`

Quantidade de splits ja executados na rodada.

`BlackjackRound.dealer_cards`

Cartas do dealer, incluindo carta aberta e carta fechada quando conhecida.

`BlackjackRound.dealer_status`

Estado final do dealer:

- `waiting`;
- `stood`;
- `busted`.

`BlackjackRound.events`

Lista de eventos da rodada. Esta lista e importante para debug e futura
integracao com o robo, pois registra distribuicao inicial, acoes do jogador,
revelacao do dealer, compras do dealer e resolucao.

### Argumentos de simulacao em `main.py`

`--simulate-round`

Ativa o modo de simulacao local.

`--round-image`

Imagem da mesa usada para reconhecer cartas via `card_vision.py`.

Exemplo:

```bash
--round-image images/table_round_01_player_QS_5S_dealer_2H_3S.jpeg
```

`--hand-image`

Imagem de sinal de mao usada para simular uma acao do jogador via
`hand_sign_vision.py`. Pode ser repetida varias vezes.

Exemplo:

```bash
--hand-image Sinais/2Dedo1.jpg
--hand-image Sinais/4Dedo1.jpg
```

`--player-card`

Carta inicial do jogador, usada quando voce quer simular cartas manualmente sem
depender da imagem da mesa. Deve ser usada exatamente duas vezes.

Exemplo:

```bash
--player-card 8H --player-card 8D
```

`--dealer-upcard`

Carta aberta inicial do dealer, usada na simulacao manual.

`--dealer-hole`

Carta fechada inicial do dealer.

`--player-draw`

Cartas futuras compradas pelo jogador. Elas entram em ordem conforme o loop
precisa de cartas para `hit`, `double` ou `split`.

`--dealer-draw`

Cartas futuras compradas pelo dealer no turno dele.

### Argumentos do simulador manual

O arquivo `blackjack_manual_simulator.py` aceita:

- `--player-card`;
- `--dealer-upcard`;
- `--dealer-hole`;
- `--action`;
- `--player-draw`;
- `--dealer-draw`;
- `--interactive`.

Exemplo sem modo interativo:

```bash
python blackjack_manual_simulator.py \
  --player-card 8H \
  --player-card 8D \
  --dealer-upcard 6S \
  --dealer-hole 10H \
  --action split \
  --action stand \
  --action stand \
  --player-draw 3H \
  --player-draw 2C \
  --dealer-draw 5C
```

Exemplo interativo:

```bash
python blackjack_manual_simulator.py \
  --player-card 8H \
  --player-card 8D \
  --dealer-upcard 6S \
  --dealer-hole 10H \
  --interactive
```

### O que vem da imagem da camera

No fluxo completo com visao, a camera deve fornecer:

- cartas visiveis do jogador;
- carta aberta do dealer;
- cartas adicionais viradas pelo robo;
- carta fechada do dealer apos ser revelada;
- sinal de mao do jogador;
- opcionalmente fichas/aposta.

Atualmente:

- `card_vision.py` reconhece cartas em ROIs da mesa;
- `hand_sign_vision.py` reconhece dedos dentro da area vermelha;
- `chip_vision.py` reconhece fichas, mas a aposta ainda nao altera a resolucao
  da rodada;
- `main.py --simulate-round` consegue usar imagem da mesa e imagens de sinais
  salvas para validar a integracao sem camera ao vivo.

### Sinais de mao atuais

A convencao atual de sinais de mao e:

| Dedos | Acao |
| --- | --- |
| 1 | `hit` |
| 2 | `split` |
| 3 | `double` |
| 4 antes da rodada | `startprog` |
| 5 durante a rodada | `stand` |
| vazio | sem acao |

Antes da rodada comecar, o sinal de 4 dedos substitui o ato de jogar ficha na
mesa e dispara `startprog`. Ou seja:

- antes da rodada: 4 dedos = iniciar programa/rodada;
- durante a vez do jogador: 5 dedos = `stand`.

Essa distincao deve ser feita pelo estado do jogo.

### O que sera enviado ao robo

O robo deve receber sinais booleanos de acao. O mapeamento atual em
`ur_robot_bridge.py` usa:

| Register | Sinal | Uso |
| --- | --- | --- |
| 128 | `startprog` | iniciar rodada/programa |
| 129 | `hit` | comprar carta |
| 130 | `double` | double |
| 131 | `stand` | parar mao ou encerrar fase |
| 132 | `splitAB` | split entre posicoes A/B |
| 133 | `splitBC` | split entre posicoes B/C |
| 134 | `splitAC` | split entre posicoes A/C |

No motor de Blackjack, a acao logica e simples:

- `hit`;
- `stand`;
- `double`;
- `split`.

Na integracao, `split` devera ser traduzido para o sinal fisico correto
(`splitAB`, `splitAC` ou `splitBC`) de acordo com qual mao esta ativa e quais
posicoes da mesa estao sendo usadas.

### O que o robo devera devolver

O robo deve devolver sinais de sincronizacao:

| Sinal | Direcao | Significado |
| --- | --- | --- |
| `busyIO` | robo -> PC | robo esta executando movimento |
| `foto` | robo -> PC | carta esta pronta para captura pela camera |

Uso esperado:

1. PC envia um comando aceito pelo motor (`hit`, `stand`, `double`, `split`,
   `startprog`).
2. Robo sobe `busyIO`.
3. PC aguarda o robo terminar.
4. Quando uma carta precisa ser reconhecida, robo pulsa `foto`.
5. PC captura frame, reconhece carta e atualiza o motor.
6. PC baixa ou pulsa o sinal enviado para evitar repeticao indesejada.

### Testes e validacao

Os testes automatizados ficam em `tests/`.

Principais validacoes apos a implementacao:

- `tests/test_blackjack_engine.py`: regras do Blackjack, split, double, dealer,
  acao ilegal e resolucao.
- `tests/test_vision_images.py`: reconhecimento de cartas em imagens da pasta
  `images/` e rodada integrada com imagem de mesa + imagem de sinal de mao.
- `tests/test_hand_sign_dataset.py`: reconhecimento de imagens principais em
  `Sinais/`.
- `tests/test_ur_robot_bridge.py`: mapeamento de sinais Modbus.
- `tests/test_dealerbot_main.py`: mapeamento de dedos para acoes.

Comando de validacao:

```bash
pytest -q
```

Resultado esperado apos esta etapa:

```text
47 passed
```
