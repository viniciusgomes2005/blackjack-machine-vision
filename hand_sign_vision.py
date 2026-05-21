import argparse
import time

import numpy as np

try:
    import cv2
except ModuleNotFoundError:
    cv2 = None

from config import DOUBLE_DOWN_SECONDS, HAND_MIN_AREA, SKIN_HSV_LOWER, SKIN_HSV_UPPER
from camera_utils import open_camera


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
    x, y, w, h = cv2.boundingRect(contour)
    if w == 0 or h == 0:
        return 0

    hull = cv2.convexHull(contour, returnPoints=False)
    if hull is None or len(hull) < 4:
        return 0

    defects = cv2.convexityDefects(contour, hull)
    if defects is None:
        # Uma mao com apenas um dedo levantado normalmente nao gera "buracos"
        # entre dedos. Usa o formato alto/estreito do contorno como fallback.
        return 1 if h > 1.45 * w else 0

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
        return 1 if h > 1.45 * w else 0

    return min(gaps + 1, 5)


def read_finger_count(hand_area, debug=False):
    """Retorna a quantidade de dedos levantados detectada na imagem."""
    mask = _skin_mask(hand_area)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    debug_img = hand_area.copy()

    if not contours:
        if debug:
            return 0, debug_img, mask
        return 0

    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) < HAND_MIN_AREA:
        if debug:
            return 0, debug_img, mask
        return 0

    fingers = _estimate_fingers(contour)

    if debug:
        cv2.drawContours(debug_img, [contour], -1, (0, 255, 0), 2)
        cv2.putText(
            debug_img,
            f"dedos={fingers}",
            (10, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
        return fingers, debug_img, mask

    return fingers


def read_hand_sign(hand_area, double_detector, original_bet, current_bet, debug=False):
    """
    Retorna (Handsign, Split), onde Handsign agora e a quantidade de dedos.

    Split fica ativo quando 2 dedos sao detectados, para manter compatibilidade
    com o restante do projeto.
    """
    _ = double_detector, original_bet, current_bet

    if debug:
        fingers, debug_img, mask = read_finger_count(hand_area, debug=True)
    else:
        fingers = read_finger_count(hand_area, debug=False)

    handsign = fingers
    split = 1 if fingers == 2 else 0

    if debug:
        return handsign, split, debug_img, mask

    return handsign, split


def run_camera(camera_index=0):
    _require_cv2()

    cap = open_camera(camera_index)
    if cap is None:
        return

    print("Pressione q para sair.")
    while True:
        ok, frame = cap.read()
        if not ok:
            print("Falha ao capturar frame.")
            break

        fingers, debug_img, mask = read_finger_count(frame, debug=True)
        cv2.putText(
            debug_img,
            f"Dedos levantados: {fingers}",
            (20, 70),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.4,
            (0, 255, 255),
            3,
            cv2.LINE_AA,
        )

        cv2.imshow("Contagem de dedos", debug_img)
        cv2.imshow("Mascara pele", mask)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(
        description="Conta dedos levantados usando a camera."
    )
    parser.add_argument(
        "--camera",
        type=int,
        default=0,
        help="Indice da camera usada pelo OpenCV. Padrao: 0.",
    )
    args = parser.parse_args()
    run_camera(camera_index=args.camera)


if __name__ == "__main__":
    main()
