"""
Configuracoes simples do projeto.

A ideia e deixar todos os valores que dependem da mesa/camera neste arquivo,
para que a calibracao seja facil de explicar e alterar.
"""

# ROIs fixas no formato: (x, y, largura, altura)
# Ajuste estes valores conforme a posicao real da camera sobre a mesa.
ROIS = {
    "player_cards": (120, 300, 420, 180),
    "dealer_cards": (120, 60, 420, 160),
    "player_chips": (600, 300, 220, 180),
    "hand_sign": (560, 80, 300, 220),
}

# Cores usadas para desenhar as ROIs no frame de debug (B, G, R).
ROI_COLORS = {
    "player_cards": (0, 255, 0),
    "dealer_cards": (255, 0, 0),
    "player_chips": (0, 255, 255),
    "hand_sign": (255, 0, 255),
}

# Caminhos dos templates de ranks e naipes.
RANK_TEMPLATE_DIR = "templates/ranks"
SUIT_TEMPLATE_DIR = "templates/suits"

# Parametros para detectar cartas como regioes claras e retangulares.
CARD_MIN_AREA = 1200
CARD_ASPECT_RATIO_RANGE = (0.45, 0.85)  # largura / altura
CARD_CORNER_RATIO = (0.32, 0.28)        # canto superior esquerdo da carta
TEMPLATE_MATCH_THRESHOLD = 0.55

# Valores das fichas. Ajuste conforme o padrao usado na mesa.
CHIP_VALUES = {
    "white": 1,
    "red": 5,
    "green": 25,
    "yellow": 50,
    "blue": 100,
}

# Faixas HSV para fichas. Em OpenCV, H vai de 0 a 179.
# Para vermelho existem duas faixas porque o hue passa pelo zero.
CHIP_HSV_RANGES = {
    "white": [((0, 0, 170), (179, 70, 255))],
    "red": [((0, 80, 70), (10, 255, 255)), ((170, 80, 70), (179, 255, 255))],
    "yellow": [((18, 80, 80), (35, 255, 255))],
    "blue": [((90, 70, 60), (130, 255, 255))],
    "green": [((40, 60, 60), (85, 255, 255))],
}

CHIP_MIN_AREA = 250
CHIP_MAX_AREA = 8000

# Segmentacao simples de pele em HSV para leitura de mao.
SKIN_HSV_LOWER = (0, 30, 60)
SKIN_HSV_UPPER = (25, 180, 255)
HAND_MIN_AREA = 2500

# Regras simples de interpretacao dos dedos estimados.
FINGERS_FOR_HIT = 1
FINGERS_FOR_STAND = 0
FINGERS_FOR_SPLIT = 2

# Double down: aposta atual precisa ficar pelo menos 2x a original por 3 s.
DOUBLE_DOWN_MULTIPLIER = 2.0
DOUBLE_DOWN_SECONDS = 3.0
