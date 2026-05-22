"""
ur_dealerbot_pseudocode.py
==========================
Reconstrução fiel da árvore do programa PolyScope `DealerBot`
(Universal Robots) em pseudo-Python.

NÃO É CÓDIGO EXECUTÁVEL. É só uma representação textual da estrutura do
programa do robô — para que um assistente de código (Codex / Claude /
etc.) possa raciocinar sobre o que o robô faz a cada passo e em que
ordem ele lê/escreve cada sinal.

Convenções:
  - MoveJ / MoveL / MoveP: comandos de movimento do UR. O argumento é o
    nome do waypoint (Waypoint_N) tal como aparece na árvore.
  - set_io(...) / read_io(...): ações de I/O. Os nomes (`busyIO`,
    `ventosa`, `foto`, `hit`, `stand`, etc.) são exatamente os nomes
    configurados em PolyScope → Installation → I/O Setup.
  - "DI[0]": sensor da ventosa (proximidade / vácuo no end-effector).
    Não é controlado pela visão; é um sensor físico do gripper.
  - "Pulse 1.0" em foto: PolyScope mantém DO1 em HI por 1.0 s.

Ordem de chamada (fluxo do jogo de Blackjack):
  socket_open → standby → wait(startprog=HI)
  → deal inicial (5 chamadas alternadas pegar/virar/entrega)
  → loop fase do jogador (hit / double / split* / stand)
  → wait(stand=LO) → virarDealerFechada
  → loop fase do dealer (hit repetido até stand=True)
  → socket_close()
"""

# ---------------------------------------------------------------------------
# Programa principal: Robot Program
# (corresponde à imagem que começa com `var_1 := socket_open(...)`)
# ---------------------------------------------------------------------------
def DealerBot():
    # Abre socket TCP para o PC. Porta 31415 (lida da foto; conferir).
    var_1 = socket_open("10.102.28.161", 31415)

    splitcont = 0
    standcont = 0
    set_io(busyIO=True)      # On — robô ocupado durante setup
    set_io(ventosa=False)    # Off — ventosa desligada

    standby()
    wait_until(startprog == "HI")

    # ----- DEAL INICIAL: 5 cartas, alternando jogador / dealer ------------
    pegarCarta();  virarCarta();  entregaPlayer()           # 1a do jogador
    pegarCarta();  virarCarta();  entregaDealerAberta()     # 1a do dealer (aberta)
    pegarCarta();  virarCarta();  entregaPlayer()           # 2a do jogador
    pegarCarta();                 entregaDealerFechada()    # 2a do dealer (fechada — NÃO vira)
    standby()

    # ----- FASE DO JOGADOR ------------------------------------------------
    # Loop principal: roda enquanto o jogador ainda tem mãos a jogar.
    # `splitcont` aumenta a cada split (gera mãos extras).
    # `standcont` aumenta cada vez que o jogador "para" em uma das mãos.
    while standcont < splitcont + 1:

        # ---- HIT: pedir mais uma carta para a mão atual ------------------
        if hit == True:
            pegarCarta()
            virarCarta()
            if standcont == 0:
                entregaPlayer()
            if standcont == 1:
                split1()
            if standcont == 2:
                split2()
            standby()

        # ---- DOUBLE: recebe 1 carta e avança automaticamente de mão ------
        if double == True:
            pegarCarta()
            virarCarta()
            if standcont == 0:
                entregaPlayer()
                standcont = standcont + 1
            if standcont == 1:
                split1()
                standcont = standcont + 1
            if standcont == 2:
                split2()
                standcont = standcont + 1
            standby()

        # ---- SPLIT AB: divide a mão entre as posições A e B --------------
        if splitAB == True:
            splitcont = splitcont + 1
            pegarCarta(); virarCarta(); entregaPlayer()
            pegarCarta(); virarCarta(); split1()
            standby()

        # ---- SPLIT AC: divide a mão entre as posições A e C --------------
        if splitAC == True:
            splitcont = splitcont + 1
            pegarCarta(); virarCarta(); entregaPlayer()
            pegarCarta(); virarCarta(); split2()
            standby()

        # ---- SPLIT BC: divide a mão entre as posições B e C --------------
        if splitBC == True:
            splitcont = splitcont + 1
            pegarCarta(); virarCarta(); split1()
            pegarCarta(); virarCarta(); split2()
            standby()

        # ---- STAND: jogador para nessa mão; avança o contador ------------
        if stand == True:
            standcont = standcont + 1

    # ----- TRANSIÇÃO PARA FASE DO DEALER ----------------------------------
    # A visão precisa baixar `stand` para LO antes do robô virar a carta
    # fechada do dealer.
    wait_until(stand == "LO")
    virarDealerFechada()

    # ----- FASE DO DEALER -------------------------------------------------
    # Dealer bate enquanto a visão pedir (hit=True). O loop termina quando
    # a visão põe stand=True novamente.
    while stand == False:
        if hit == True:
            pegarCarta()
            virarCarta()
            entregaDealerAberta()
            standby()

    socket_close()


# ---------------------------------------------------------------------------
# Sub-rotinas (cada `P xxx` no PolyScope vira uma função aqui)
# ---------------------------------------------------------------------------

def pegarCarta():
    """Pega uma carta do baralho usando a ventosa."""
    set_io(busyIO=True)
    MoveJ("Waypoint_2")            # pose neutra acima do baralho
    set_io(ventosa=True)            # liga sucção
    MoveJ("Waypoint_3",
          until="DI[0]==HI")        # desce até o sensor da ventosa ativar
    MoveL("Waypoint_16")            # sobe linearmente com a carta
    wait(0.75)
    MoveJ("Waypoint_2")             # volta à pose neutra


def virarCarta():
    """Vira a carta, pulsa `foto` para a visão capturar, e a repega virada."""
    set_io(busyIO=True)
    MoveJ("Waypoint_2")
    MoveP("Waypoint_8", "Waypoint_5", "Waypoint_4")  # trajetória de virada
    MoveJ("Waypoint_1")
    set_io(ventosa=False)           # solta a carta virada na bancada
    MoveJ("Waypoint_17")
    set_io(foto=True, pulse=1.0)    # DO1: Pulse 1.0 s → visão captura aqui
    wait(1.0)                       # dá tempo para a visão processar
    MoveJ("Waypoint_6")
    MoveJ("Waypoint_9")
    set_io(ventosa=True)            # repega a carta agora virada
    MoveJ("Waypoint_7",
          until="DI[0]==HI")        # desce até sensor da ventosa
    MoveL("Waypoint_10")            # sobe com a carta


def entregaPlayer():
    """Entrega uma carta na posição do jogador."""
    set_io(busyIO=True)
    MoveJ("Waypoint_9")
    MoveJ("Waypoint_23")
    set_io(ventosa=False)           # solta a carta
    MoveJ("Waypoint_2")


def entregaDealerAberta():
    """Entrega uma carta aberta na posição do dealer."""
    set_io(busyIO=True)
    MoveJ("Waypoint_9")
    MoveJ("Waypoint_18")
    set_io(ventosa=False)
    MoveJ("Waypoint_2")


def entregaDealerFechada():
    """Entrega a 2a carta do dealer fechada (sem passar por virarCarta)."""
    set_io(busyIO=True)
    MoveJ("Waypoint_2")
    MoveJ("Waypoint_25", "Waypoint_21")
    set_io(ventosa=False)
    MoveJ("Waypoint_2")


def virarDealerFechada():
    """Pega a carta fechada do dealer, vira e recoloca aberta."""
    set_io(busyIO=True)
    MoveJ("Waypoint_20")
    MoveJ("Waypoint_21")
    set_io(ventosa=True)
    wait(1.0)
    MoveJ("Waypoint_22")
    MoveJ("Waypoint_11")
    MoveJ("Waypoint_12")
    MoveJ("Waypoint_13")
    MoveJ("Waypoint_9")
    set_io(ventosa=True)
    MoveJ("Waypoint_7", until="DI[0]==HI")
    wait(0.5)
    MoveL("Waypoint_19")
    MoveJ("Waypoint_21")
    set_io(ventosa=False)
    MoveJ("Waypoint_20")


def split1():
    """Coloca a carta na posição de split #1."""
    set_io(busyIO=True)
    MoveJ("Waypoint_2")
    MoveJ("Waypoint_24")
    set_io(ventosa=False)
    MoveJ("Waypoint_2")


def split2():
    """Coloca a carta na posição de split #2."""
    set_io(busyIO=True)
    MoveJ("Waypoint_2")
    MoveJ("Waypoint_15")
    set_io(ventosa=False)
    MoveJ("Waypoint_2")


def standby():
    """Pose neutra; única sub-rotina que zera `busyIO`.
    É aqui que o robô fica disponível para ler novos sinais da visão."""
    MoveJ("Waypoint_14", "Waypoint_20")
    set_io(busyIO=False)


# ---------------------------------------------------------------------------
# Resumo dos waypoints citados (apenas para mapeamento mental)
# ---------------------------------------------------------------------------
# Waypoint_1  : virada — pose intermediária
# Waypoint_2  : pose neutra "home" (acima do baralho)
# Waypoint_3  : descer no baralho (até sensor da ventosa)
# Waypoint_4,5,8 : trajetória MoveP de virada
# Waypoint_6  : sobre a área de virada (após pulso foto)
# Waypoint_7  : descida final no flip (até sensor)
# Waypoint_9  : pose acima do jogador / acima da carta fechada do dealer
# Waypoint_10 : recuo após repegar carta virada
# Waypoint_11,12,13 : trajetória de virada do dealer
# Waypoint_14, 20 : pose de standby
# Waypoint_15 : posição de split #2
# Waypoint_16 : recuo linear pós-pegada
# Waypoint_17 : pose antes de pulsar `foto`
# Waypoint_18 : posição do dealer (aberta)
# Waypoint_19 : descida controlada pós virada do dealer
# Waypoint_21 : posição da 2a carta do dealer (fechada)
# Waypoint_22 : trânsito após pegar carta fechada do dealer
# Waypoint_23 : posição do jogador
# Waypoint_24 : posição de split #1
# Waypoint_25 : pose intermediária para entregaDealerFechada
