import argparse
import time
from dataclasses import dataclass

import numpy as np

try:
    import cv2
except ModuleNotFoundError:
    cv2 = None

from config import (
    BLUE_HAND_ZONE_DILATE_PX,
    BLUE_HAND_ZONE_MIN_AREA,
    DOUBLE_DOWN_SECONDS,
    HAND_MIN_AREA,
    HSV_RANGES,
    SKIN_HSV_LOWER,
    SKIN_HSV_UPPER,
)
from camera_utils import open_camera
from vision_areas import mask_from_hsv_ranges


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


@dataclass(frozen=True)
class HandZone:
    """Mascara inferida da area azul onde sinais de mao sao validos."""

    mask: np.ndarray
    blue_mask: np.ndarray
    found: bool


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


def infer_blue_hand_zone(hand_area):
    """
    Reconstroi a area azul mesmo quando uma parte esta escondida pela mao.

    O objetivo nao e criar um retangulo perfeito. A mascara usa os contornos
    azuis visiveis, fecha pequenas falhas e expande um pouco o hull para cobrir
    a area ocluida pela propria mao sem aceitar o frame inteiro.
    """
    _require_cv2()
    hsv = cv2.cvtColor(hand_area, cv2.COLOR_BGR2HSV)
    blue_mask = mask_from_hsv_ranges(hsv, HSV_RANGES["blue_tape"], kernel_size=7)
    contours, _ = cv2.findContours(
        blue_mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    significant = [
        contour
        for contour in contours
        if cv2.contourArea(contour) >= BLUE_HAND_ZONE_MIN_AREA
    ]
    zone_mask = np.zeros(blue_mask.shape, dtype=np.uint8)

    if not significant:
        return HandZone(mask=zone_mask, blue_mask=blue_mask, found=False)

    points = np.vstack(significant)
    hull = cv2.convexHull(points)
    cv2.fillConvexPoly(zone_mask, hull, 255)

    dilate_px = max(1, int(BLUE_HAND_ZONE_DILATE_PX))
    kernel_size = 2 * dilate_px + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    zone_mask = cv2.dilate(zone_mask, kernel, iterations=1)

    close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21))
    zone_mask = cv2.morphologyEx(zone_mask, cv2.MORPH_CLOSE, close_kernel)
    return HandZone(mask=zone_mask, blue_mask=blue_mask, found=True)


def _apply_allowed_zone(mask, allowed_mask):
    if allowed_mask is None:
        return mask

    if allowed_mask.shape != mask.shape:
        raise ValueError("allowed_mask precisa ter o mesmo tamanho da area da mao.")

    clean_allowed = allowed_mask.astype(np.uint8)
    return cv2.bitwise_and(mask, mask, mask=clean_allowed)


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


def read_finger_count(hand_area, debug=False, allowed_mask=None):
    """Retorna a quantidade de dedos levantados detectada na imagem."""
    mask = _skin_mask(hand_area)
    mask = _apply_allowed_zone(mask, allowed_mask)
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


def read_hand_sign(
    hand_area,
    double_detector,
    original_bet,
    current_bet,
    debug=False,
    require_blue_area=True,
):
    """
    Retorna (Handsign, Split), onde Handsign agora e a quantidade de dedos.

    Split fica ativo quando 2 dedos sao detectados, para manter compatibilidade
    com o restante do projeto.
    """
    _ = double_detector, original_bet, current_bet
    hand_zone = infer_blue_hand_zone(hand_area) if require_blue_area else None
    allowed_mask = hand_zone.mask if hand_zone is not None and hand_zone.found else None

    if require_blue_area and allowed_mask is None:
        if debug:
            empty_mask = np.zeros(hand_area.shape[:2], dtype=np.uint8)
            debug_img = hand_area.copy()
            cv2.putText(
                debug_img,
                "area azul nao encontrada",
                (10, 35),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 0, 255),
                2,
                cv2.LINE_AA,
            )
            return 0, 0, debug_img, empty_mask
        return 0, 0

    if debug:
        fingers, debug_img, mask = read_finger_count(
            hand_area,
            debug=True,
            allowed_mask=allowed_mask,
        )
    else:
        fingers = read_finger_count(
            hand_area,
            debug=False,
            allowed_mask=allowed_mask,
        )

    handsign = fingers
    split = 1 if fingers == 2 else 0

    if debug:
        if hand_zone is not None and hand_zone.found:
            overlay = debug_img.copy()
            overlay[hand_zone.mask > 0] = (255, 0, 0)
            debug_img = cv2.addWeighted(overlay, 0.25, debug_img, 0.75, 0)
            blue_contours, _ = cv2.findContours(
                hand_zone.blue_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            cv2.drawContours(debug_img, blue_contours, -1, (255, 0, 0), 2)
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

        hand_zone = infer_blue_hand_zone(frame)
        allowed_mask = hand_zone.mask if hand_zone.found else np.zeros(
            frame.shape[:2], dtype=np.uint8
        )
        fingers, debug_img, mask = read_finger_count(
            frame,
            debug=True,
            allowed_mask=allowed_mask,
        )
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
