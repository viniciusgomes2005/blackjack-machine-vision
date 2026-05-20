import time

import cv2
import numpy as np

from config import (
    DOUBLE_DOWN_MULTIPLIER,
    DOUBLE_DOWN_SECONDS,
    FINGERS_FOR_HIT,
    FINGERS_FOR_SPLIT,
    FINGERS_FOR_STAND,
    HAND_MIN_AREA,
    SKIN_HSV_LOWER,
    SKIN_HSV_UPPER,
)


class DoubleDownDetector:
    """
    Confirma double down quando a aposta atual fica pelo menos 2x a aposta
    original durante um tempo continuo.
    """

    def __init__(self, multiplier=DOUBLE_DOWN_MULTIPLIER, seconds=DOUBLE_DOWN_SECONDS):
        self.multiplier = multiplier
        self.seconds = seconds
        self.start_time = None

    def update(self, original_bet, current_bet):
        if original_bet <= 0:
            self.start_time = None
            return False

        target = original_bet * self.multiplier
        condition_met = current_bet >= target

        if not condition_met:
            self.start_time = None
            return False

        if self.start_time is None:
            self.start_time = time.time()
            return False

        return (time.time() - self.start_time) >= self.seconds


def segment_skin(hand_roi):
    """Segmenta pele de forma simples em HSV."""
    hsv = cv2.cvtColor(hand_roi, cv2.COLOR_BGR2HSV)
    lower = np.array(SKIN_HSV_LOWER, dtype=np.uint8)
    upper = np.array(SKIN_HSV_UPPER, dtype=np.uint8)
    mask = cv2.inRange(hsv, lower, upper)

    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask


def estimate_fingers(contour):
    """
    Estima dedos usando convexity defects.

    E uma heuristica academica simples: conta vales profundos entre dedos e
    soma 1. Nao e uma leitura robusta para todos os gestos, mas e didatica.
    """
    hull_indices = cv2.convexHull(contour, returnPoints=False)

    if hull_indices is None or len(hull_indices) < 4:
        return 0

    defects = cv2.convexityDefects(contour, hull_indices)
    if defects is None:
        return 0

    finger_gaps = 0

    for i in range(defects.shape[0]):
        start_idx, end_idx, far_idx, depth = defects[i, 0]
        start = contour[start_idx][0]
        end = contour[end_idx][0]
        far = contour[far_idx][0]

        a = np.linalg.norm(end - start)
        b = np.linalg.norm(far - start)
        c = np.linalg.norm(end - far)

        if b == 0 or c == 0:
            continue

        angle = np.degrees(np.arccos((b * b + c * c - a * a) / (2 * b * c)))

        # depth vem multiplicado por 256 no OpenCV.
        if angle < 90 and depth > 10000:
            finger_gaps += 1

    if finger_gaps == 0:
        return 0

    return min(finger_gaps + 1, 5)


class HandSignReader:
    """
    Retorna Handsign:
        0 = nenhum sinal
        1 = pedir carta
        2 = parar
        3 = dobrar
        4 = split
    """

    def __init__(self):
        self.double_down_detector = DoubleDownDetector()

    def read_hand_sign(self, hand_roi, original_bet, current_bet, debug=False):
        if self.double_down_detector.update(original_bet, current_bet):
            if debug:
                return 3, False, hand_roi.copy(), None
            return 3, False

        mask = segment_skin(hand_roi)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            if debug:
                return 0, False, hand_roi.copy(), mask
            return 0, False

        largest = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest)

        debug_image = hand_roi.copy()
        if area < HAND_MIN_AREA:
            if debug:
                return 0, False, debug_image, mask
            return 0, False

        fingers = estimate_fingers(largest)
        split = fingers == FINGERS_FOR_SPLIT

        if fingers == FINGERS_FOR_HIT:
            handsign = 1
        elif fingers == FINGERS_FOR_STAND:
            handsign = 2
        elif split:
            handsign = 4
        else:
            handsign = 0

        if debug:
            cv2.drawContours(debug_image, [largest], -1, (0, 255, 0), 2)
            cv2.putText(
                debug_image,
                f"fingers={fingers} sign={handsign}",
                (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )
            return handsign, split, debug_image, mask

        return handsign, split
