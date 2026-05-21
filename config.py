"""
Configuracao central do projeto.

Tudo que depende da camera, mesa, cores e valores de fichas fica aqui para
facilitar a calibracao durante testes em bancada.
"""

# ROIs fixas no formato (x, y, largura, altura).
# Ajuste esses valores conforme a resolucao da camera e a posicao da mesa.
ROIS = {
    "dealer_cards": (900, 285, 330, 270),
    "player_cards": (320, 355, 300, 215),
    "player_split_1": (320, 355, 100, 215),
    "player_split_2": (420, 355, 100, 215),
    "player_split_3": (520, 355, 100, 215),
    "player_chips": (320, 565, 380, 285),
    "dealer_area": (900, 285, 330, 270),
    "hand_sign_area": (315, 565, 385, 285),
}

ROI_COLORS = {
    "dealer_cards": (255, 0, 0),
    "player_cards": (0, 255, 0),
    "player_split_1": (0, 180, 0),
    "player_split_2": (0, 200, 120),
    "player_split_3": (0, 220, 220),
    "player_chips": (0, 255, 255),
    "dealer_area": (255, 120, 0),
    "hand_sign_area": (255, 0, 255),
}

RANK_TEMPLATE_DIR = "templates/ranks"
SUIT_TEMPLATE_DIR = "templates/suits"

# Deteccao de cartas brancas.
CARD_MIN_AREA = 1200
CARD_ASPECT_RATIO_MIN = 0.45
# Aceita cartas em pe e deitadas. Nas imagens de referencia, varias cartas
# aparecem em orientacao horizontal.
CARD_ASPECT_RATIO_MAX = 2.40
CARD_CORNER_WIDTH_RATIO = 0.32
CARD_CORNER_HEIGHT_RATIO = 0.30
TEMPLATE_MATCH_THRESHOLD = 0.55
CARD_W = 200
CARD_H = 300
DEBUG_CARD_VISION = False

# Valores atuais das fichas usadas na mesa.
CHIP_VALUES = {
    "yellow": 25,
    "green": 50,
    "blue": 100,
}

# Faixas HSV. OpenCV usa H de 0 a 179.
HSV_RANGES = {
    "red_tape": [((0, 90, 70), (10, 255, 255)), ((170, 90, 70), (179, 255, 255))],
    "blue_tape": [((90, 70, 60), (130, 255, 255))],
    "yellow_tape": [((18, 80, 80), (35, 255, 255))],
    "yellow_chip": [((18, 80, 80), (35, 255, 255))],
    "green_chip": [((40, 60, 60), (85, 255, 255))],
    "blue_chip": [((90, 70, 60), (130, 255, 255))],
}

CHIP_HSV_RANGES = {
    "yellow": HSV_RANGES["yellow_chip"],
    "green": HSV_RANGES["green_chip"],
    "blue": HSV_RANGES["blue_chip"],
}

CHIP_MIN_AREA = 250
CHIP_MAX_AREA = 8000
CHIP_MIN_CIRCULARITY = 0.45

# Segmentacao simples de pele para sinais de mao.
SKIN_HSV_LOWER = (0, 30, 60)
SKIN_HSV_UPPER = (25, 180, 255)
HAND_MIN_AREA = 2500
DOUBLE_DOWN_SECONDS = 3.0

# A mao so conta quando estiver dentro da area azul. A mascara azul e
# reconstruida a partir dos pedacos visiveis, porque mao/braco podem esconder
# parte da marcacao.
BLUE_HAND_ZONE_MIN_AREA = 700
BLUE_HAND_ZONE_DILATE_PX = 28

# Controles de debug.
SHOW_DEBUG_WINDOWS = True
PRINT_EVERY_FRAME = True
