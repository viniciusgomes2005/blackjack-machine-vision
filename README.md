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

Para testar o reconhecedor de sinais de mao no quadrado azul:

```bash
python hand_sign_vision.py --camera 0
```

A janela da camera abre em tela cheia. `Espaco` captura, salva a foto em
`Sinais/` e o terminal imprime `1`, `2`, `3`, `4`, `5` ou `vazio`. Voce pode
apertar `Espaco` varias vezes; `Esc` sai.

As imagens com nomes `1Dedo...`, `2Dedo...`, `3Dedo...`, `4Dedo...`,
`5Dedo...` e `Vazio...` em `Sinais/` tambem funcionam como base de calibracao
visual. O classificador usa a aparencia da mao dentro do quadrado azul e nao o
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

## Script principal do DealerBot

O script principal preparado para a logica do jogo e:

```bash
python DealerBotMain.py --camera 0 --hand-interval 5
```

Ele abre a camera, analisa o quadrado azul a cada 5 segundos e imprime no
terminal a decisao detectada:

| Dedos | Acao |
| --- | --- |
| 1 | hit |
| 2 | split |
| 3 | double |
| 4 | stand |
| 5 ou vazio | sem acao |

Para ver as janelas de debug da area azul e da mascara de pele:

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

Para liberar o inicio da partida pelo `startprog` (DI4 / register 128):

```bash
python ur_robot_bridge.py --no-ur-read --startprog
```

Por padrao, o script escuta em `10.102.28.161:31415`. No PolyScope, configure
o cliente Modbus para esse mesmo IP e essa mesma porta.
O IP do controlador UR usado para leitura futura de `foto`/`busyIO` e
`10.103.18.245`.

Se a configuracao do robo espera que o PC conecte diretamente no IP do UR,
use o modo cliente direto:

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

No modo interativo, use:

```text
ur> start
ur> hit
ur> stand
ur> status
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
