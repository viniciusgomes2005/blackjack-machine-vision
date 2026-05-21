import argparse
import time
from collections import Counter, deque
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
    HAND_SIGN_HISTORY_SIZE,
    HAND_SIGN_MIN_STABLE_FRAMES,
    HAND_MIN_AREA,
    HSV_RANGES,
    SKIN_HSV_LOWER,
    SKIN_HSV_UPPER,
    SKIN_YCRCB_LOWER,
    SKIN_YCRCB_UPPER,
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


class HandSignStabilizer:
    """Suaviza leituras quadro a quadro antes de publicar o sinal."""

    def __init__(
        self,
        history_size=HAND_SIGN_HISTORY_SIZE,
        min_stable_frames=HAND_SIGN_MIN_STABLE_FRAMES,
    ):
        self.history_size = history_size
        self.min_stable_frames = min_stable_frames
        self.values = deque(maxlen=history_size)
        self.last_stable = 0

    def reset(self):
        self.values.clear()
        self.last_stable = 0

    def update(self, raw_value):
        self.values.append(int(raw_value))
        value, count = Counter(self.values).most_common(1)[0]

        if count >= self.min_stable_frames:
            self.last_stable = value

        if raw_value == 0 and count >= max(2, self.min_stable_frames - 1):
            self.last_stable = 0

        return self.last_stable


@dataclass(frozen=True)
class HandZone:
    """Mascara inferida da area azul onde sinais de mao sao validos."""

    mask: np.ndarray
    blue_mask: np.ndarray
    found: bool


@dataclass(frozen=True)
class FingerDetection:
    count: int
    contour: np.ndarray | None
    palm_center: tuple[int, int] | None
    palm_radius: float
    fingertips: tuple[tuple[int, int], ...]


def _skin_mask(hand_area):
    _require_cv2()
    hsv = cv2.cvtColor(hand_area, cv2.COLOR_BGR2HSV)
    hsv_mask = cv2.inRange(
        hsv,
        np.array(SKIN_HSV_LOWER, dtype=np.uint8),
        np.array(SKIN_HSV_UPPER, dtype=np.uint8),
    )
    ycrcb = cv2.cvtColor(hand_area, cv2.COLOR_BGR2YCrCb)
    ycrcb_mask = cv2.inRange(
        ycrcb,
        np.array(SKIN_YCRCB_LOWER, dtype=np.uint8),
        np.array(SKIN_YCRCB_UPPER, dtype=np.uint8),
    )
    mask = cv2.bitwise_and(hsv_mask, ycrcb_mask)

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


def _main_hand_contour(mask):
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) < HAND_MIN_AREA:
        return None

    return contour


def _estimate_palm(mask, contour):
    contour_mask = np.zeros(mask.shape, dtype=np.uint8)
    cv2.drawContours(contour_mask, [contour], -1, 255, -1)
    distance = cv2.distanceTransform(contour_mask, cv2.DIST_L2, 5)
    _, radius, _, center = cv2.minMaxLoc(distance)
    return center, float(radius)


def _cluster_fingertips(candidates, min_distance):
    if not candidates:
        return ()

    ordered = sorted(candidates, key=lambda item: item[0][0])
    clusters = []

    for point, score in ordered:
        if not clusters:
            clusters.append([(point, score)])
            continue

        previous_point = clusters[-1][-1][0]
        if abs(point[0] - previous_point[0]) <= min_distance:
            clusters[-1].append((point, score))
        else:
            clusters.append([(point, score)])

    fingertips = []
    for cluster in clusters:
        point, _ = max(cluster, key=lambda item: item[1])
        fingertips.append(point)

    return tuple(fingertips)


def _fingertips_from_hull(contour, palm_center, palm_radius):
    hull = cv2.convexHull(contour, returnPoints=True)
    if hull is None or len(hull) < 4 or palm_radius <= 0:
        return ()

    center = np.array(palm_center, dtype=np.float32)
    candidates = []

    for point in hull[:, 0, :]:
        point_f = point.astype(np.float32)
        vector = point_f - center
        distance = float(np.linalg.norm(vector))
        if distance < palm_radius * 1.35:
            continue
        if point[1] > palm_center[1] - palm_radius * 0.25:
            continue

        # Pontas reais ficam longe da palma e relativamente altas no contorno.
        height_score = max(0.0, palm_center[1] - float(point[1]))
        candidates.append(((int(point[0]), int(point[1])), distance + height_score))

    return _cluster_fingertips(candidates, min_distance=max(12.0, palm_radius * 0.7))


def _defect_gap_count(contour, palm_radius):
    x, y, w, h = cv2.boundingRect(contour)
    if w == 0 or h == 0:
        return 0

    hull = cv2.convexHull(contour, returnPoints=False)
    if hull is None or len(hull) < 4:
        return 0

    defects = cv2.convexityDefects(contour, hull)
    if defects is None:
        return 0

    gaps = 0
    min_depth = max(8000, int(palm_radius * 120))
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

        if angle < 85 and depth > min_depth:
            gaps += 1

    return gaps


def _single_finger_fallback(contour, palm_center, palm_radius):
    x, y, w, h = cv2.boundingRect(contour)
    if w == 0 or h == 0 or palm_radius <= 0:
        return 0

    top_distance = palm_center[1] - y
    narrow_shape = h > 1.45 * w
    high_tip = top_distance > palm_radius * 1.8
    return 1 if narrow_shape or high_tip else 0


def _detect_fingers(mask):
    contour = _main_hand_contour(mask)
    if contour is None:
        return FingerDetection(0, None, None, 0.0, ())

    palm_center, palm_radius = _estimate_palm(mask, contour)
    fingertips = _fingertips_from_hull(contour, palm_center, palm_radius)
    gap_count = _defect_gap_count(contour, palm_radius)

    if fingertips:
        count = len(fingertips)
        if gap_count >= 2:
            count = max(count, min(gap_count + 1, 5))
    else:
        count = _single_finger_fallback(contour, palm_center, palm_radius)

    return FingerDetection(
        count=min(count, 5),
        contour=contour,
        palm_center=(int(palm_center[0]), int(palm_center[1])),
        palm_radius=palm_radius,
        fingertips=fingertips,
    )


def read_finger_count(hand_area, debug=False, allowed_mask=None):
    """Retorna a quantidade de dedos levantados detectada na imagem."""
    mask = _skin_mask(hand_area)
    mask = _apply_allowed_zone(mask, allowed_mask)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    detection = _detect_fingers(mask)
    debug_img = hand_area.copy()

    if debug:
        if detection.contour is not None:
            cv2.drawContours(debug_img, [detection.contour], -1, (0, 255, 0), 2)

        if detection.palm_center is not None:
            cv2.circle(
                debug_img,
                detection.palm_center,
                max(2, int(detection.palm_radius)),
                (0, 180, 255),
                2,
            )

        for fingertip in detection.fingertips:
            cv2.circle(debug_img, fingertip, 8, (0, 0, 255), -1)

        cv2.putText(
            debug_img,
            f"dedos={detection.count}",
            (10, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
        return detection.count, debug_img, mask

    return detection.count


def read_hand_sign(
    hand_area,
    double_detector,
    original_bet,
    current_bet,
    debug=False,
    require_blue_area=True,
    stabilizer=None,
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

    handsign = stabilizer.update(fingers) if stabilizer is not None else fingers
    split = 1 if handsign == 2 else 0

    if debug:
        if hand_zone is not None and hand_zone.found:
            overlay = debug_img.copy()
            overlay[hand_zone.mask > 0] = (255, 0, 0)
            debug_img = cv2.addWeighted(overlay, 0.25, debug_img, 0.75, 0)
            blue_contours, _ = cv2.findContours(
                hand_zone.blue_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            cv2.drawContours(debug_img, blue_contours, -1, (255, 0, 0), 2)
        if stabilizer is not None:
            cv2.putText(
                debug_img,
                f"estavel={handsign}",
                (10, 70),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 255),
                2,
                cv2.LINE_AA,
            )
        return handsign, split, debug_img, mask

    return handsign, split


def run_camera(camera_index=0):
    _require_cv2()

    cap = open_camera(camera_index)
    if cap is None:
        return

    print("Pressione q para sair.")
    stabilizer = HandSignStabilizer()
    while True:
        ok, frame = cap.read()
        if not ok:
            print("Falha ao capturar frame.")
            break

        hand_zone = infer_blue_hand_zone(frame)
        allowed_mask = hand_zone.mask if hand_zone.found else np.zeros(
            frame.shape[:2], dtype=np.uint8
        )
        raw_fingers, debug_img, mask = read_finger_count(
            frame,
            debug=True,
            allowed_mask=allowed_mask,
        )
        fingers = stabilizer.update(raw_fingers)
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
