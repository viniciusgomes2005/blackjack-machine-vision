import cv2
import numpy as np

from config import CHIP_HSV_RANGES, CHIP_MAX_AREA, CHIP_MIN_AREA, CHIP_VALUES


def build_color_mask(hsv_image, ranges):
    """Cria uma mascara binaria combinando uma ou mais faixas HSV."""
    mask = np.zeros(hsv_image.shape[:2], dtype=np.uint8)

    for lower, upper in ranges:
        lower_np = np.array(lower, dtype=np.uint8)
        upper_np = np.array(upper, dtype=np.uint8)
        mask = cv2.bitwise_or(mask, cv2.inRange(hsv_image, lower_np, upper_np))

    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask


def count_mask_objects(mask):
    """Conta objetos filtrando por area para reduzir ruido."""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    count = 0
    valid_contours = []

    for contour in contours:
        area = cv2.contourArea(contour)
        if CHIP_MIN_AREA <= area <= CHIP_MAX_AREA:
            count += 1
            valid_contours.append(contour)

    return count, valid_contours


def optimize_chips(value, chip_values=CHIP_VALUES):
    """
    Retorna uma combinacao gulosa de fichas para o valor informado.

    Para valores classicos de fichas, a estrategia gulosa e simples e facil
    de explicar: sempre usa a maior ficha possivel primeiro.
    """
    remaining = int(value)
    result = {}

    sorted_chips = sorted(chip_values.items(), key=lambda item: item[1], reverse=True)

    for color, chip_value in sorted_chips:
        if chip_value <= 0:
            continue

        amount = remaining // chip_value
        if amount > 0:
            result[color] = amount
            remaining -= amount * chip_value

    return result


class ChipCounter:
    """Detector simples de fichas por segmentacao HSV."""

    def __init__(self, hsv_ranges=CHIP_HSV_RANGES, chip_values=CHIP_VALUES):
        self.hsv_ranges = hsv_ranges
        self.chip_values = chip_values

    def count_chips(self, chips_roi, debug=False):
        hsv = cv2.cvtColor(chips_roi, cv2.COLOR_BGR2HSV)
        detected_chips = {}
        total = 0
        debug_image = chips_roi.copy()
        debug_masks = {}

        for color, ranges in self.hsv_ranges.items():
            mask = build_color_mask(hsv, ranges)
            count, contours = count_mask_objects(mask)
            detected_chips[color] = count
            total += count * self.chip_values.get(color, 0)
            debug_masks[color] = mask

            if debug:
                cv2.drawContours(debug_image, contours, -1, (0, 255, 0), 2)

        if debug:
            return detected_chips, total, debug_image, debug_masks

        return detected_chips, total
