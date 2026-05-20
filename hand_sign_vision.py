import time

import numpy as np

try:
    import cv2
except ModuleNotFoundError:
    cv2 = None

from config import DOUBLE_DOWN_SECONDS, HAND_MIN_AREA, SKIN_HSV_LOWER, SKIN_HSV_UPPER


def _require_cv2():
    if cv2 is None:
        raise ModuleNotFoundError(
            "OpenCV nao esta instalado. Rode: pip install -r requirements.txt"
        )


class DoubleDownDetector:
    """Confirma double quando a aposta fica dobrada por alguns segundos."""

    def __init__(self, required_seconds=DOUBLE_DOWN_SECONDS):
        self.required_seconds = required_seconds
        self.start_time = None

    def update(self, original_bet, current_bet):
        if original_bet <= 0:
            self.start_time = None
            return False

        if current_bet < 2 * original_bet:
            self.start_time = None
            return False

        if self.start_time is None:
            self.start_time = time.time()
            return False

        return (time.time() - self.start_time) >= self.required_seconds


def _skin_mask(hand_area):
    _require_cv2()
    hsv = cv2.cvtColor(hand_area, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(
        hsv,
        np.array(SKIN_HSV_LOWER, dtype=np.uint8),
        np.array(SKIN_HSV_UPPER, dtype=np.uint8),
    )

    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask


def _estimate_fingers(contour):
    """Estima dedos por convexity defects. E uma heuristica simples."""
    hull = cv2.convexHull(contour, returnPoints=False)
    if hull is None or len(hull) < 4:
        return 0

    defects = cv2.convexityDefects(contour, hull)
    if defects is None:
        return 0

    gaps = 0
    for i in range(defects.shape[0]):
        start_i, end_i, far_i, depth = defects[i, 0]
        start = contour[start_i][0]
        end = contour[end_i][0]
        far = contour[far_i][0]

        a = np.linalg.norm(end - start)
        b = np.linalg.norm(far - start)
        c = np.linalg.norm(end - far)

        if b == 0 or c == 0:
            continue

        cosine = (b * b + c * c - a * a) / (2 * b * c)
        cosine = np.clip(cosine, -1.0, 1.0)
        angle = np.degrees(np.arccos(cosine))

        if angle < 90 and depth > 10000:
            gaps += 1

    if gaps == 0:
        return 0

    return min(gaps + 1, 5)


def read_hand_sign(hand_area, double_detector, original_bet, current_bet, debug=False):
    """
    Retorna (Handsign, Split).

    0 = nenhum, 1 = hit, 2 = stand, 3 = double, 4 = split.
    """
    if double_detector.update(original_bet, current_bet):
        if debug:
            return 3, 0, hand_area.copy(), None
        return 3, 0

    mask = _skin_mask(hand_area)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    debug_img = hand_area.copy()

    if not contours:
        if debug:
            return 0, 0, debug_img, mask
        return 0, 0

    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) < HAND_MIN_AREA:
        if debug:
            return 0, 0, debug_img, mask
        return 0, 0

    fingers = _estimate_fingers(contour)

    # Mapeamento didatico. Pode ser trocado conforme os gestos definidos em sala.
    if fingers == 1:
        handsign = 1
        split = 0
    elif fingers == 0:
        handsign = 2
        split = 0
    elif fingers == 2:
        handsign = 4
        split = 1
    else:
        handsign = 0
        split = 0

    if debug:
        cv2.drawContours(debug_img, [contour], -1, (0, 255, 0), 2)
        cv2.putText(
            debug_img,
            f"fingers={fingers} sign={handsign}",
            (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
        return handsign, split, debug_img, mask

    return handsign, split
