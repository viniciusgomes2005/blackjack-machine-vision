from pathlib import Path

import numpy as np

try:
    import cv2
except ModuleNotFoundError:
    cv2 = None

from config import (
    CARD_ASPECT_RATIO_MAX,
    CARD_ASPECT_RATIO_MIN,
    CARD_CORNER_HEIGHT_RATIO,
    CARD_CORNER_WIDTH_RATIO,
    CARD_H,
    CARD_MIN_AREA,
    CARD_W,
    TEMPLATE_MATCH_THRESHOLD,
)

RANK_ORDER = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SUIT_ORDER = {"spades": 0, "hearts": 1, "clubs": 2, "diamonds": 3}
PROJECT_ROOT = Path(__file__).resolve().parent
VALID_TEMPLATE_EXTENSIONS = {".png", ".jpg", ".jpeg"}


def _require_cv2():
    if cv2 is None:
        raise ModuleNotFoundError(
            "OpenCV nao esta instalado. Rode: pip install -r requirements.txt"
        )


def resolve_project_path(path):
    """Resolve caminhos relativos sempre a partir da raiz do projeto."""
    path = Path(path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def preprocess_symbol_image(image):
    """
    Converte rank/naipe para grayscale binario.

    O mesmo preprocessamento e usado em templates e nas regioes recortadas da
    carta, deixando o template matching mais facil de explicar e reproduzir.
    """
    _require_cv2()

    if image is None or image.size == 0:
        return None

    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()

    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


def find_card_contours(card_area):
    """Encontra cartas como regioes brancas e retangulares dentro da ROI."""
    candidates, thresh = find_card_candidates(card_area)
    boxes = [candidate["bbox"] for candidate in candidates]
    return boxes, thresh


def find_card_candidates(card_area):
    """Encontra cartas e preserva o contorno para correcao de perspectiva."""
    _require_cv2()
    gray = cv2.cvtColor(card_area, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < CARD_MIN_AREA:
            continue

        rect = cv2.minAreaRect(contour)
        rect_w, rect_h = rect[1]
        short_side = min(rect_w, rect_h)
        long_side = max(rect_w, rect_h)

        if short_side == 0:
            continue

        ratio = long_side / float(short_side)
        if CARD_ASPECT_RATIO_MIN <= ratio <= CARD_ASPECT_RATIO_MAX:
            candidates.append(
                {
                    "contour": contour,
                    "bbox": cv2.boundingRect(contour),
                    "area": area,
                }
            )

    candidates.sort(key=lambda candidate: candidate["bbox"][0])
    return candidates, thresh


def order_points(points):
    """
    Ordena pontos como top-left, top-right, bottom-right, bottom-left.

    Esse formato e o que cv2.getPerspectiveTransform espera para fazer o warp.
    """
    points = np.array(points, dtype="float32")
    ordered = np.zeros((4, 2), dtype="float32")

    sums = points.sum(axis=1)
    diffs = np.diff(points, axis=1)

    ordered[0] = points[np.argmin(sums)]
    ordered[2] = points[np.argmax(sums)]
    ordered[1] = points[np.argmin(diffs)]
    ordered[3] = points[np.argmax(diffs)]

    return ordered


def contour_to_card_points(contour):
    """
    Tenta usar 4 pontos reais do contorno.

    Se a carta estiver parcialmente sobreposta e o contorno nao virar um
    quadrilatero bom, usa minAreaRect como fallback.
    """
    perimeter = cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, 0.03 * perimeter, True)

    if len(approx) == 4:
        return approx.reshape(4, 2)

    rect = cv2.minAreaRect(contour)
    return cv2.boxPoints(rect)


def warp_card_from_contour(card_area, contour):
    """Normaliza uma carta detectada para CARD_W x CARD_H."""
    points = order_points(contour_to_card_points(contour))
    destination = np.array(
        [
            [0, 0],
            [CARD_W - 1, 0],
            [CARD_W - 1, CARD_H - 1],
            [0, CARD_H - 1],
        ],
        dtype="float32",
    )

    matrix = cv2.getPerspectiveTransform(points, destination)
    warped = cv2.warpPerspective(card_area, matrix, (CARD_W, CARD_H))

    if warped.shape[1] > warped.shape[0]:
        warped = cv2.rotate(warped, cv2.ROTATE_90_CLOCKWISE)

    return warped


def rotate_card(card_img, rotation_index):
    """Retorna a carta em uma das quatro orientacoes possiveis."""
    if rotation_index == 0:
        return card_img
    if rotation_index == 1:
        return cv2.rotate(card_img, cv2.ROTATE_90_CLOCKWISE)
    if rotation_index == 2:
        return cv2.rotate(card_img, cv2.ROTATE_180)
    return cv2.rotate(card_img, cv2.ROTATE_90_COUNTERCLOCKWISE)


def extract_card_corner(card_img):
    """Recorta o canto superior esquerdo da carta para leitura."""
    h, w = card_img.shape[:2]
    corner_w = max(1, int(w * CARD_CORNER_WIDTH_RATIO))
    corner_h = max(1, int(h * CARD_CORNER_HEIGHT_RATIO))
    return card_img[:corner_h, :corner_w]


def load_templates(folder):
    """
    Carrega templates a partir da raiz do projeto.

    A pasta e criada automaticamente quando nao existe. Cada arquivo .png,
    .jpg ou .jpeg vira um template cujo nome e o stem do arquivo.
    """
    _require_cv2()
    templates = {}
    folder_path = resolve_project_path(folder)

    print(f"[templates] Procurando em: {folder_path}")
    folder_path.mkdir(parents=True, exist_ok=True)

    image_paths = sorted(
        path for path in folder_path.iterdir() if path.suffix.lower() in VALID_TEMPLATE_EXTENSIONS
    )

    for path in image_paths:
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        template = preprocess_symbol_image(image)
        if template is not None:
            templates[path.stem] = template

    print(f"[templates] Encontrados: {len(templates)}")
    print(f"[templates] Carregados: {list(templates.keys())}")

    return templates


def match_template(region, templates):
    """Retorna o melhor template e score por cv2.matchTemplate."""
    _require_cv2()
    if region is None or region.size == 0 or not templates:
        return "unknown", 0.0

    gray = preprocess_symbol_image(region)
    if gray is None:
        return "unknown", 0.0

    best_name = "unknown"
    best_score = -1.0

    for name, template in templates.items():
        current_template = cv2.resize(template, (gray.shape[1], gray.shape[0]))

        result = cv2.matchTemplate(gray, current_template, cv2.TM_CCOEFF_NORMED)
        _, score, _, _ = cv2.minMaxLoc(result)

        if score > best_score:
            best_score = score
            best_name = name

    if best_score < TEMPLATE_MATCH_THRESHOLD:
        return "unknown", float(best_score)

    return best_name, float(best_score)


def rank_to_blackjack_value(rank):
    if rank == "A":
        return 11
    if rank in ["J", "Q", "K"]:
        return 10
    try:
        return int(rank)
    except (TypeError, ValueError):
        return 0


def rank_suit_to_card_id(rank, suit):
    """Converte rank/naipe para ID de 1 a 52."""
    if rank not in RANK_ORDER or suit not in SUIT_ORDER:
        return None

    rank_index = RANK_ORDER.index(rank)
    suit_index = SUIT_ORDER[suit]
    return rank_index * 4 + suit_index + 1


def read_card_corner(card_img, rank_templates, suit_templates):
    """Le o canto superior esquerdo de uma orientacao da carta."""
    corner = extract_card_corner(card_img)
    corner_h = corner.shape[0]

    rank_region = corner[: max(1, corner_h // 2), :]
    suit_region = corner[max(1, corner_h // 2):, :]

    rank, rank_score = match_template(rank_region, rank_templates)
    suit, suit_score = match_template(suit_region, suit_templates)

    return {
        "rank": rank,
        "suit": suit,
        "rank_score": rank_score,
        "suit_score": suit_score,
        "rank_region": rank_region,
        "corner": corner,
    }


def read_card(card_img, rank_templates, suit_templates, debug=False):
    """
    Le uma carta normalizada.

    Testa quatro orientacoes porque o indice da carta pode estar em qualquer
    canto quando a carta foi vista girada na mesa.
    """
    attempts = []
    for rotation_index in range(4):
        rotated = rotate_card(card_img, rotation_index)
        attempt = read_card_corner(rotated, rank_templates, suit_templates)
        attempt["rotation"] = rotation_index
        attempts.append(attempt)

    best = max(attempts, key=lambda item: item["rank_score"])
    rank = best["rank"]
    suit = best["suit"]
    rank_score = best["rank_score"]
    suit_score = best["suit_score"]
    card_id = rank_suit_to_card_id(rank, suit)

    # Para blackjack, rank confiavel ja e suficiente.
    status = "ok" if rank != "unknown" else "unknown"

    card = {
        "rank": rank,
        "suit": suit,
        "card_id": card_id,
        "blackjack_value": rank_to_blackjack_value(rank),
        "rank_score": round(rank_score, 3),
        "suit_score": round(suit_score, 3),
        "status": status,
    }

    if debug:
        card["debug"] = {
            "best_rotation": best["rotation"],
            "attempts": [
                {
                    "rotation": item["rotation"],
                    "rank": item["rank"],
                    "rank_score": round(item["rank_score"], 3),
                    "suit": item["suit"],
                    "suit_score": round(item["suit_score"], 3),
                }
                for item in attempts
            ],
        }

    return card


def read_cards_from_area(card_area, rank_templates, suit_templates, debug=False):
    """Detecta e le todas as cartas em uma ROI."""
    candidates, thresh = find_card_candidates(card_area)
    cards = []
    debug_img = card_area.copy()

    for candidate in candidates:
        x, y, w, h = candidate["bbox"]
        card_img = warp_card_from_contour(card_area, candidate["contour"])
        card = read_card(card_img, rank_templates, suit_templates, debug=debug)
        cards.append(card)

        if debug:
            color = (0, 255, 0) if card["status"] == "ok" else (0, 165, 255)
            cv2.rectangle(debug_img, (x, y), (x + w, y + h), color, 2)
            cv2.putText(
                debug_img,
                f'{card["rank"]}/{card["suit"]}',
                (x, max(18, y - 5)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                2,
                cv2.LINE_AA,
            )

    if debug:
        return cards, debug_img, thresh

    return cards
