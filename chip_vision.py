import numpy as np

try:
    import cv2
except ModuleNotFoundError:
    cv2 = None

from config import (
    CHIP_HSV_RANGES,
    CHIP_MAX_AREA,
    CHIP_MIN_AREA,
    CHIP_MIN_CIRCULARITY,
    CHIP_VALUES,
)


def _require_cv2():
    if cv2 is None:
        raise ModuleNotFoundError(
            "OpenCV nao esta instalado. Rode: pip install -r requirements.txt"
        )


def _mask_from_ranges(hsv, ranges):
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)

    for lower, upper in ranges:
        mask = cv2.bitwise_or(
            mask,
            cv2.inRange(hsv, np.array(lower, dtype=np.uint8), np.array(upper, dtype=np.uint8)),
        )

    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask


def _contour_circularity(contour):
    area = cv2.contourArea(contour)
    perimeter = cv2.arcLength(contour, True)

    if perimeter == 0:
        return 0.0

    return 4.0 * np.pi * area / (perimeter * perimeter)


def count_chips_by_color(chip_area, debug=False):
    """Conta fichas amarelas, verdes e azuis usando HSV e contornos."""
    _require_cv2()
    hsv = cv2.cvtColor(chip_area, cv2.COLOR_BGR2HSV)
    chip_counts = {color: 0 for color in CHIP_VALUES.keys()}
    debug_img = chip_area.copy()
    debug_masks = {}

    for color, ranges in CHIP_HSV_RANGES.items():
        mask = _mask_from_ranges(hsv, ranges)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        valid_contours = []
        for contour in contours:
            area = cv2.contourArea(contour)
            circularity = _contour_circularity(contour)

            if CHIP_MIN_AREA <= area <= CHIP_MAX_AREA and circularity >= CHIP_MIN_CIRCULARITY:
                valid_contours.append(contour)

        chip_counts[color] = len(valid_contours)
        debug_masks[color] = mask

        if debug:
            cv2.drawContours(debug_img, valid_contours, -1, (0, 255, 0), 2)

    if debug:
        return chip_counts, debug_img, debug_masks

    return chip_counts


def calculate_bet(chip_counts, chip_values=CHIP_VALUES):
    """Calcula o valor total da aposta a partir das quantidades por cor."""
    total = 0
    for color, count in chip_counts.items():
        total += count * chip_values.get(color, 0)
    return total


def optimize_chips(value, chip_values=CHIP_VALUES):
    """Retorna a menor quantidade de fichas usando estrategia gulosa."""
    remaining = int(value)
    result = {color: 0 for color in chip_values.keys()}

    for color, chip_value in sorted(chip_values.items(), key=lambda item: item[1], reverse=True):
        if chip_value <= 0:
            continue

        amount = remaining // chip_value
        result[color] = amount
        remaining -= amount * chip_value

    return result


def create_chip_robot_orders(target, optimized_chips):
    """Transforma fichas otimizadas em comandos simples para o robo."""
    prefix = "Gambler" if target == "gambler" else "Dealer"
    labels = {
        "yellow": "Amarelo",
        "green": "Verde",
        "blue": "Azul",
    }

    orders = {}
    for color, label in labels.items():
        amount = optimized_chips.get(color, 0)
        orders[f"{prefix}_{label}"] = amount > 0
        orders[f"{prefix}_{label}_Qtd"] = amount

    return orders
