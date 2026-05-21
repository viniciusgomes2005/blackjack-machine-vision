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
