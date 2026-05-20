import os

import cv2

from config import (
    CARD_ASPECT_RATIO_RANGE,
    CARD_CORNER_RATIO,
    CARD_MIN_AREA,
    RANK_TEMPLATE_DIR,
    SUIT_TEMPLATE_DIR,
    TEMPLATE_MATCH_THRESHOLD,
)


def load_templates(folder):
    """
    Carrega templates em escala de cinza.

    O nome do arquivo vira o rotulo. Exemplo:
        templates/ranks/A.png -> "A"
        templates/suits/spades.png -> "spades"
    """
    templates = {}

    if not os.path.isdir(folder):
        return templates

    for filename in os.listdir(folder):
        path = os.path.join(folder, filename)
        label, ext = os.path.splitext(filename)

        if ext.lower() not in [".png", ".jpg", ".jpeg", ".bmp"]:
            continue

        image = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if image is not None:
            templates[label] = image

    return templates


def rank_to_blackjack_value(rank):
    """Converte rank da carta para valor basico de blackjack."""
    if rank in ["J", "Q", "K"]:
        return 10
    if rank == "A":
        return 11

    try:
        return int(rank)
    except (TypeError, ValueError):
        return 0


def detect_card_rectangles(cards_roi):
    """
    Detecta cartas como regioes claras, grandes e aproximadamente retangulares.
    """
    gray = cv2.cvtColor(cards_roi, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # Cartas costumam ser claras contra a mesa. Otsu ajuda quando a iluminacao muda.
    _, threshold = cv2.threshold(
        blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )

    contours, _ = cv2.findContours(
        threshold, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    rectangles = []
    min_ratio, max_ratio = CARD_ASPECT_RATIO_RANGE

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < CARD_MIN_AREA:
            continue

        x, y, w, h = cv2.boundingRect(contour)
        if h == 0:
            continue

        aspect_ratio = w / float(h)
        if min_ratio <= aspect_ratio <= max_ratio:
            rectangles.append((x, y, w, h))

    rectangles.sort(key=lambda rect: rect[0])
    return rectangles, threshold


def crop_card_corner(card_image):
    """Recorta o canto superior esquerdo, onde ficam rank e naipe."""
    height, width = card_image.shape[:2]
    corner_w = max(1, int(width * CARD_CORNER_RATIO[0]))
    corner_h = max(1, int(height * CARD_CORNER_RATIO[1]))
    return card_image[0:corner_h, 0:corner_w]


def match_template(image, templates):
    """
    Compara a imagem com todos os templates e retorna melhor rotulo e score.
    """
    if image is None or image.size == 0:
        return None, 0.0

    if not templates:
        return None, 0.0

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    best_label = None
    best_score = -1.0

    for label, template in templates.items():
        if gray.shape[0] < template.shape[0] or gray.shape[1] < template.shape[1]:
            resized = cv2.resize(template, (gray.shape[1], gray.shape[0]))
        else:
            resized = template

        result = cv2.matchTemplate(gray, resized, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)

        if max_val > best_score:
            best_score = max_val
            best_label = label

    if best_score < TEMPLATE_MATCH_THRESHOLD:
        return None, float(best_score)

    return best_label, float(best_score)


class CardReader:
    """
    Leitor simples de cartas baseado em contornos e template matching.
    """

    def __init__(self, rank_template_dir=RANK_TEMPLATE_DIR, suit_template_dir=SUIT_TEMPLATE_DIR):
        self.rank_templates = load_templates(rank_template_dir)
        self.suit_templates = load_templates(suit_template_dir)

    def read_cards(self, cards_roi, debug=False):
        rectangles, threshold = detect_card_rectangles(cards_roi)
        cards = []
        debug_image = cards_roi.copy()

        for x, y, w, h in rectangles:
            card_image = cards_roi[y:y + h, x:x + w]
            corner = crop_card_corner(card_image)

            # Divide o canto em duas partes simples: rank em cima, naipe embaixo.
            corner_h = corner.shape[0]
            rank_roi = corner[: max(1, corner_h // 2), :]
            suit_roi = corner[max(1, corner_h // 2):, :]

            rank, rank_score = match_template(rank_roi, self.rank_templates)
            suit, suit_score = match_template(suit_roi, self.suit_templates)

            cards.append(
                {
                    "rank": rank,
                    "suit": suit,
                    "rank_score": round(rank_score, 3),
                    "suit_score": round(suit_score, 3),
                    "value": rank_to_blackjack_value(rank),
                }
            )

            if debug:
                cv2.rectangle(debug_image, (x, y), (x + w, y + h), (0, 255, 0), 2)
                label = f"{rank or '?'} {suit or '?'}"
                cv2.putText(
                    debug_image,
                    label,
                    (x, max(18, y - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (0, 255, 0),
                    2,
                    cv2.LINE_AA,
                )

        if debug:
            return cards, debug_image, threshold

        return cards
