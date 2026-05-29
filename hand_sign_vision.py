import argparse
import re
import sys
import time
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np

try:
    import cv2
except ModuleNotFoundError:
    cv2 = None

from config import (
    DOUBLE_DOWN_SECONDS,
    HAND_ZONE_COLOR,
    HAND_ZONE_DILATE_PX,
    HAND_ZONE_MIN_AREA,
    HAND_SIGN_HISTORY_SIZE,
    HAND_SIGN_MIN_STABLE_FRAMES,
    HAND_MIN_AREA,
    HAND_DATASET_CONFIDENCE_DISTANCE,
    HAND_SKELETON_MIN_LANDMARKS_IN_ZONE,
    HAND_SKELETON_MIN_SKIN_AREA,
    HSV_RANGES,
    SKIN_HSV_LOWER,
    SKIN_HSV_UPPER,
    SKIN_YCRCB_LOWER,
    SKIN_YCRCB_UPPER,
    USE_HAND_SKELETON_DETECTOR,
    USE_HAND_DATASET_CLASSIFIER,
)
from camera_utils import open_camera
from vision_areas import mask_from_hsv_ranges


WEBCAM_INDEX = 0
VALID_HAND_COUNTS = {1, 2, 3, 4, 5}
DEFAULT_HAND_DEBUG_DIR = Path(__file__).resolve().parent / "debug_hand_sign"
DEFAULT_SIGNALS_DIR = Path(__file__).resolve().parent / "Sinais"
_DATASET_CLASSIFIER = None
_MEDIAPIPE_HANDS = None
_MEDIAPIPE_IMPORT_FAILED = False


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
    """Mascara inferida da area colorida onde sinais de mao sao validos."""

    mask: np.ndarray
    zone_color_mask: np.ndarray
    found: bool

    @property
    def blue_mask(self):
        """Compatibilidade com chamadas antigas."""
        return self.zone_color_mask


@dataclass(frozen=True)
class FingerDetection:
    count: int
    contour: np.ndarray | None
    palm_center: tuple[int, int] | None
    palm_radius: float
    fingertips: tuple[tuple[int, int], ...]
    raw_count: int = 0
    gap_count: int = 0
    shallow_gaps: int = 0
    open_hand_gaps: int = 0
    right_ratio: float = 0.0


@dataclass(frozen=True)
class SkeletonDetection:
    count: int
    landmarks: tuple[tuple[int, int], ...]
    raised_fingers: tuple[str, ...]


def normalize_hand_count(count):
    """Retorna 1..5 ou None quando a leitura nao e um sinal valido."""
    return int(count) if int(count) in VALID_HAND_COUNTS else None


def _label_from_signal_filename(path):
    name = Path(path).name.lower()
    stem = Path(path).stem.lower()
    if "vazio" in name:
        return 0

    foto_match = re.search(r"foto\d+_([1-5])$", stem)
    if foto_match is not None:
        return int(foto_match.group(1))

    dedo_match = re.search(r"([1-5])dedo", name)
    if dedo_match is not None:
        return int(dedo_match.group(1))

    return None


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


def _selected_hand_zone_component(zone_color_mask):
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    clean = cv2.morphologyEx(zone_color_mask, cv2.MORPH_OPEN, kernel)

    join_px = max(8, min(18, int(HAND_ZONE_DILATE_PX * 0.6)))
    join_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (2 * join_px + 1, 2 * join_px + 1),
    )
    grouped = cv2.dilate(clean, join_kernel, iterations=1)
    grouped = cv2.morphologyEx(grouped, cv2.MORPH_CLOSE, join_kernel)

    contours, _ = cv2.findContours(
        grouped,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    height, width = zone_color_mask.shape
    best = None
    best_score = 0.0

    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w == 0 or h == 0:
            continue

        component_mask = np.zeros(zone_color_mask.shape, dtype=np.uint8)
        cv2.drawContours(component_mask, [contour], -1, 255, -1)
        selected_pixels = cv2.bitwise_and(
            zone_color_mask,
            zone_color_mask,
            mask=component_mask,
        )
        zone_color_area = cv2.countNonZero(selected_pixels)
        if zone_color_area < HAND_ZONE_MIN_AREA:
            continue

        aspect = w / h
        if aspect < 0.35 or aspect > 2.80:
            continue

        bbox_area = w * h
        center_x = (x + w / 2) / max(1, width)
        center_y = (y + h / 2) / max(1, height)
        lower_left_prior = 1.0 + 0.20 * center_y + 0.12 * (1.0 - center_x)
        compactness = min(1.0, zone_color_area / max(1, bbox_area * 0.18))
        score = zone_color_area * compactness * lower_left_prior

        if score > best_score:
            best_score = score
            best = selected_pixels

    return best


def _solid_zone_from_color_pixels(selected_pixels):
    points = cv2.findNonZero(selected_pixels)
    zone_mask = np.zeros(selected_pixels.shape, dtype=np.uint8)

    if points is None or len(points) < 4:
        return zone_mask

    rect = cv2.minAreaRect(points)
    (center, size, angle) = rect
    width, height = size
    if width <= 0 or height <= 0:
        return zone_mask

    expand = max(8, int(HAND_ZONE_DILATE_PX * 0.7))
    rect = (center, (width + 2 * expand, height + 2 * expand), angle)
    box = cv2.boxPoints(rect).astype(np.int32)
    cv2.fillConvexPoly(zone_mask, box, 255)

    close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31))
    return cv2.morphologyEx(zone_mask, cv2.MORPH_CLOSE, close_kernel)


def infer_hand_zone(hand_area):
    """
    Reconstroi a area colorida mesmo quando uma parte esta escondida pela mao.

    A cena deve ter um unico quadrado valido. Manchas menores da mesma cor sao
    ignoradas; a mascara final e um preenchimento solido do candidato dominante.
    """
    _require_cv2()
    hsv = cv2.cvtColor(hand_area, cv2.COLOR_BGR2HSV)
    colors = []
    for color in (HAND_ZONE_COLOR, "blue_tape", "red_tape"):
        if color in HSV_RANGES and color not in colors:
            colors.append(color)

    skin = _skin_mask(hand_area)
    candidates = []
    empty_mask = np.zeros(hand_area.shape[:2], dtype=np.uint8)

    for color in colors:
        color_mask = mask_from_hsv_ranges(hsv, HSV_RANGES[color], kernel_size=7)
        selected_pixels = _selected_hand_zone_component(color_mask)
        if selected_pixels is None:
            candidates.append((0.0, HandZone(mask=empty_mask, zone_color_mask=color_mask, found=False)))
            continue

        zone_mask = _solid_zone_from_color_pixels(selected_pixels)
        if cv2.countNonZero(zone_mask) == 0:
            candidates.append((0.0, HandZone(mask=zone_mask, zone_color_mask=selected_pixels, found=False)))
            continue

        skin_inside = cv2.countNonZero(cv2.bitwise_and(skin, skin, mask=zone_mask))
        color_area = cv2.countNonZero(selected_pixels)
        score = skin_inside * 1000.0 + color_area
        candidates.append((score, HandZone(mask=zone_mask, zone_color_mask=selected_pixels, found=True)))

    found_candidates = [item for item in candidates if item[1].found]
    if not found_candidates:
        color_mask = mask_from_hsv_ranges(hsv, HSV_RANGES[HAND_ZONE_COLOR], kernel_size=7)
        return HandZone(mask=empty_mask, zone_color_mask=color_mask, found=False)

    return max(found_candidates, key=lambda item: item[0])[1]


def infer_blue_hand_zone(hand_area):
    """Compatibilidade: a area fisica agora e vermelha."""
    return infer_hand_zone(hand_area)


def _apply_allowed_zone(mask, allowed_mask):
    if allowed_mask is None:
        return mask

    if allowed_mask.shape != mask.shape:
        raise ValueError("allowed_mask precisa ter o mesmo tamanho da area da mao.")

    clean_allowed = allowed_mask.astype(np.uint8)
    return cv2.bitwise_and(mask, mask, mask=clean_allowed)


def _hand_feature_vector(image, hand_zone):
    """
    Assinatura visual normalizada da area colorida.

    Ela combina aparencia da area do quadrado, mascara de pele e medidas
    geometricas. A base Sinais/ usa essa assinatura para calibrar a leitura sem
    depender de nomes de arquivos durante a inferencia.
    """
    zone_mask = hand_zone.mask
    ys, xs = np.where(zone_mask > 0)
    if len(xs) == 0:
        return np.zeros(64 * 64 * 4 + 12, dtype=np.float32)

    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1

    zone_only = image.copy()
    zone_only[zone_mask == 0] = 0
    crop_bgr = zone_only[y0:y1, x0:x1]
    crop_bgr = cv2.resize(crop_bgr, (64, 64), interpolation=cv2.INTER_AREA)
    crop_bgr = crop_bgr.astype(np.float32) / 255.0

    skin = _skin_mask(image)
    skin = _apply_allowed_zone(skin, zone_mask)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    skin = cv2.morphologyEx(skin, cv2.MORPH_CLOSE, kernel)
    crop_skin = skin[y0:y1, x0:x1]
    crop_skin = cv2.resize(crop_skin, (64, 64), interpolation=cv2.INTER_AREA)
    crop_skin = crop_skin.astype(np.float32) / 255.0

    contour = _main_hand_contour(skin)
    zone_area = float(max(1, cv2.countNonZero(zone_mask)))
    skin_area = float(cv2.countNonZero(skin))
    geometry = [skin_area / zone_area]

    if contour is None:
        geometry.extend([0.0] * 11)
    else:
        x, y, w, h = cv2.boundingRect(contour)
        contour_area = float(cv2.contourArea(contour))
        hull = cv2.convexHull(contour)
        hull_area = float(max(1.0, cv2.contourArea(hull)))
        palm_center, palm_radius = _estimate_palm(skin, contour)
        geometry.extend(
            [
                contour_area / zone_area,
                w / max(1, x1 - x0),
                h / max(1, y1 - y0),
                w / max(1, h),
                contour_area / max(1, w * h),
                contour_area / hull_area,
                palm_radius / max(1, max(w, h)),
                _right_contour_ratio(contour, palm_center, palm_radius),
                len(_fingertips_from_hull(contour, palm_center, palm_radius)) / 6.0,
                _convexity_gap_count(contour, palm_radius, angle_limit=90, depth_radius_multiplier=50) / 6.0,
                _convexity_gap_count(contour, palm_radius, angle_limit=60, depth_radius_multiplier=50) / 6.0,
            ]
        )

    return np.concatenate(
        [
            crop_bgr.reshape(-1),
            crop_skin.reshape(-1),
            np.array(geometry, dtype=np.float32),
        ]
    ).astype(np.float32)


class HandDatasetClassifier:
    """Classificador calibrado pelas imagens rotuladas em Sinais/."""

    def __init__(self, features, labels):
        self.features = features
        self.labels = labels
        self.mean = features.mean(axis=0)
        self.std = features.std(axis=0) + 1e-6
        self.normalized = (features - self.mean) / self.std

    @classmethod
    def from_dir(cls, signals_dir=DEFAULT_SIGNALS_DIR):
        features = []
        labels = []
        for path in sorted(Path(signals_dir).glob("*.jpg")):
            label = _label_from_signal_filename(path)
            if label is None:
                continue

            image = cv2.imread(str(path))
            if image is None:
                continue

            hand_zone = infer_blue_hand_zone(image)
            if not hand_zone.found:
                feature = np.zeros(64 * 64 * 4 + 12, dtype=np.float32)
            else:
                feature = _hand_feature_vector(image, hand_zone)
            features.append(feature)
            labels.append(label)

        if not features:
            return None

        return cls(np.stack(features), np.array(labels, dtype=np.int32))

    def predict(self, image, hand_zone):
        label, _distance = self.predict_with_distance(image, hand_zone)
        return label

    def predict_with_distance(self, image, hand_zone):
        feature = _hand_feature_vector(image, hand_zone)
        normalized = (feature - self.mean) / self.std
        distances = np.linalg.norm(self.normalized - normalized, axis=1)
        nearest = int(np.argmin(distances))
        return int(self.labels[nearest]), float(distances[nearest])


def _dataset_classifier():
    global _DATASET_CLASSIFIER
    if _DATASET_CLASSIFIER is None:
        _DATASET_CLASSIFIER = HandDatasetClassifier.from_dir()
    return _DATASET_CLASSIFIER


def _mediapipe_hands():
    global _MEDIAPIPE_HANDS, _MEDIAPIPE_IMPORT_FAILED
    if _MEDIAPIPE_IMPORT_FAILED:
        return None
    if _MEDIAPIPE_HANDS is not None:
        return _MEDIAPIPE_HANDS

    sentinel = object()
    previous_tensorflow = sys.modules.get("tensorflow", sentinel)
    sys.modules["tensorflow"] = None
    try:
        import mediapipe as mp
    except Exception as exc:
        _MEDIAPIPE_IMPORT_FAILED = True
        print(f"[hand] MediaPipe indisponivel; usando fallback: {exc}")
        return None
    finally:
        if previous_tensorflow is sentinel:
            sys.modules.pop("tensorflow", None)
        else:
            sys.modules["tensorflow"] = previous_tensorflow

    try:
        _MEDIAPIPE_HANDS = mp.solutions.hands.Hands(
            static_image_mode=True,
            max_num_hands=1,
            model_complexity=1,
            min_detection_confidence=0.55,
            min_tracking_confidence=0.50,
        )
    except Exception as exc:
        _MEDIAPIPE_IMPORT_FAILED = True
        print(f"[hand] MediaPipe Hands indisponivel; usando fallback: {exc}")
        return None
    return _MEDIAPIPE_HANDS


def _point_distance(a, b):
    return float(np.linalg.norm(np.array(a, dtype=np.float32) - np.array(b, dtype=np.float32)))


def _landmark_points(hand_landmarks):
    return tuple((float(point.x), float(point.y)) for point in hand_landmarks.landmark)


def _landmark_pixel_points(points, image_shape):
    height, width = image_shape[:2]
    pixels = []
    for x, y in points:
        px = int(round(x * (width - 1)))
        py = int(round(y * (height - 1)))
        pixels.append((px, py))
    return tuple(pixels)


def _landmarks_inside_zone(pixel_points, zone_mask):
    if zone_mask is None:
        return True

    height, width = zone_mask.shape[:2]
    inside = 0
    for x, y in pixel_points:
        if 0 <= x < width and 0 <= y < height and zone_mask[y, x] > 0:
            inside += 1
    return inside >= HAND_SKELETON_MIN_LANDMARKS_IN_ZONE


def _zone_has_enough_skin(image, hand_zone):
    if hand_zone is None or not hand_zone.found:
        return True

    skin = _skin_mask(image)
    skin_inside = cv2.countNonZero(cv2.bitwise_and(skin, skin, mask=hand_zone.mask))
    return skin_inside >= HAND_SKELETON_MIN_SKIN_AREA


def count_fingers_from_landmarks(points):
    """
    Conta dedos abertos a partir dos 21 landmarks normalizados do MediaPipe.

    A regra usa distancias relativas ao punho, entao e menos sensivel a rotacao
    da mao do que comparar apenas coordenadas y.
    """
    if points is None or len(points) != 21:
        return 0, ()

    wrist = points[0]
    palm_scale = max(_point_distance(wrist, points[9]), 1e-6)
    palm_width = max(_point_distance(points[5], points[17]), palm_scale * 0.65)

    raised = []
    finger_specs = (
        ("index", 5, 6, 8),
        ("middle", 9, 10, 12),
        ("ring", 13, 14, 16),
        ("pinky", 17, 18, 20),
    )
    for name, mcp_i, pip_i, tip_i in finger_specs:
        mcp = points[mcp_i]
        pip = points[pip_i]
        tip = points[tip_i]
        extended_from_wrist = _point_distance(wrist, tip) > _point_distance(wrist, pip) + palm_scale * 0.08
        extended_from_mcp = _point_distance(mcp, tip) > _point_distance(mcp, pip) * 1.22
        if extended_from_wrist and extended_from_mcp:
            raised.append(name)

    thumb_tip = points[4]
    thumb_ip = points[3]
    thumb_mcp = points[2]
    index_mcp = points[5]
    thumb_tip_index_ratio = _point_distance(thumb_tip, index_mcp) / max(palm_width, 1e-6)
    thumb_wrist_ratio = _point_distance(wrist, thumb_tip) / max(palm_scale, 1e-6)
    non_thumb_count = len(raised)
    thumb_far_from_index = thumb_tip_index_ratio > 0.60 and (
        thumb_wrist_ratio > 1.35
        or (non_thumb_count >= 4 and thumb_wrist_ratio > 1.25)
    )
    thumb_extended = (
        _point_distance(wrist, thumb_tip) > _point_distance(wrist, thumb_mcp) + palm_scale * 0.10
        and _point_distance(thumb_mcp, thumb_tip) > _point_distance(thumb_mcp, thumb_ip) * 1.10
        and thumb_far_from_index
    )
    if thumb_extended:
        raised.append("thumb")

    return normalize_hand_count(len(raised)) or 0, tuple(raised)


def _detect_hand_skeleton(image, hand_zone=None):
    hands = _mediapipe_hands()
    if hands is None:
        return None
    if not _zone_has_enough_skin(image, hand_zone):
        return None

    sources = [(image, 0, 0)]
    if hand_zone is not None and hand_zone.found:
        ys, xs = np.where(hand_zone.mask > 0)
        if len(xs) > 0:
            pad = 48
            x0 = max(0, int(xs.min()) - pad)
            y0 = max(0, int(ys.min()) - pad)
            x1 = min(image.shape[1], int(xs.max()) + pad + 1)
            y1 = min(image.shape[0], int(ys.max()) + pad + 1)
            crop = image[y0:y1, x0:x1]
            if crop.size:
                sources.append((crop, x0, y0))

    best = None
    best_inside = -1
    zone_mask = hand_zone.mask if hand_zone is not None and hand_zone.found else None
    for source, x0, y0 in sources:
        rgb = cv2.cvtColor(source, cv2.COLOR_BGR2RGB)
        result = hands.process(rgb)
        if not result.multi_hand_landmarks:
            continue

        for landmarks in result.multi_hand_landmarks:
            points = _landmark_points(landmarks)
            crop_pixel_points = _landmark_pixel_points(points, source.shape)
            pixel_points = tuple((x + x0, y + y0) for x, y in crop_pixel_points)
            if zone_mask is None:
                inside = len(pixel_points)
            else:
                inside = sum(
                    1
                    for x, y in pixel_points
                    if 0 <= y < zone_mask.shape[0]
                    and 0 <= x < zone_mask.shape[1]
                    and zone_mask[y, x] > 0
                )
            if inside > best_inside:
                best = (points, pixel_points)
                best_inside = inside

    if best is None:
        return None

    points, pixel_points = best
    if not _landmarks_inside_zone(pixel_points, zone_mask):
        return None

    count, raised = count_fingers_from_landmarks(points)
    return SkeletonDetection(count=count, landmarks=pixel_points, raised_fingers=raised)


def _draw_skeleton_debug(debug_img, skeleton):
    if skeleton is None:
        return debug_img

    connections = (
        (0, 1), (1, 2), (2, 3), (3, 4),
        (0, 5), (5, 6), (6, 7), (7, 8),
        (0, 9), (9, 10), (10, 11), (11, 12),
        (0, 13), (13, 14), (14, 15), (15, 16),
        (0, 17), (17, 18), (18, 19), (19, 20),
        (5, 9), (9, 13), (13, 17),
    )
    for start, end in connections:
        cv2.line(debug_img, skeleton.landmarks[start], skeleton.landmarks[end], (255, 180, 0), 2)
    for point in skeleton.landmarks:
        cv2.circle(debug_img, point, 4, (255, 0, 255), -1)
    cv2.putText(
        debug_img,
        f"skeleton={skeleton.count} {','.join(skeleton.raised_fingers)}",
        (20, 120),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255, 180, 0),
        2,
        cv2.LINE_AA,
    )
    return debug_img


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
    return _convexity_gap_count(contour, palm_radius, angle_limit=85, depth_radius_multiplier=120)


def _convexity_gap_count(contour, palm_radius, angle_limit=90, depth_radius_multiplier=50):
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
    min_depth = max(3000, int(palm_radius * depth_radius_multiplier))
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

        if angle < angle_limit and depth > min_depth:
            gaps += 1

    return gaps


def _right_contour_ratio(contour, palm_center, palm_radius):
    points = contour[:, 0, :]
    if len(points) == 0 or palm_radius <= 0:
        return 0.0

    right_limit = palm_center[0] + palm_radius * 0.5
    right_points = sum(1 for point in points if point[0] > right_limit)
    return right_points / len(points)


def _finger_geometry_metrics(contour, palm_center, palm_radius):
    return {
        "right_ratio": _right_contour_ratio(contour, palm_center, palm_radius),
        "shallow_gaps": _convexity_gap_count(
            contour,
            palm_radius,
            angle_limit=60,
            depth_radius_multiplier=50,
        ),
        "open_hand_gaps": _convexity_gap_count(
            contour,
            palm_radius,
            angle_limit=90,
            depth_radius_multiplier=50,
        ),
    }


def _refine_finger_count(contour, palm_center, palm_radius, raw_count, metrics=None):
    """
    Corrige a contagem bruta para o enquadramento real do projeto.

    A primeira estimativa vem das pontas do casco convexo. Em fotos reais, um
    dedo horizontal pode criar pontas falsas e cinco dedos podem aparecer como
    quatro pontas. As concavidades entre dedos e a distribuicao do contorno em
    relacao a palma resolvem esses casos sem depender do nome da imagem.
    """
    if raw_count <= 0:
        return 0

    metrics = metrics or _finger_geometry_metrics(contour, palm_center, palm_radius)
    right_ratio = metrics["right_ratio"]
    shallow_gaps = metrics["shallow_gaps"]
    open_hand_gaps = metrics["open_hand_gaps"]

    if raw_count <= 3:
        if shallow_gaps >= 2:
            return 3
        x, y, w, h = cv2.boundingRect(contour)
        if shallow_gaps == 0 and right_ratio < 0.35 and w > h:
            return 0
        if right_ratio <= 0.646:
            return 1 if shallow_gaps == 0 else 2
        return 2 if raw_count <= 2 else 3

    return 4 if open_hand_gaps <= 3 else 5


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
    metrics = _finger_geometry_metrics(contour, palm_center, palm_radius)

    if fingertips:
        raw_count = len(fingertips)
        if gap_count >= 2:
            raw_count = max(raw_count, min(gap_count + 1, 5))
    else:
        raw_count = _single_finger_fallback(contour, palm_center, palm_radius)

    count = _refine_finger_count(
        contour,
        palm_center,
        palm_radius,
        raw_count,
        metrics=metrics,
    )

    return FingerDetection(
        count=min(count, 5),
        contour=contour,
        palm_center=(int(palm_center[0]), int(palm_center[1])),
        palm_radius=palm_radius,
        fingertips=fingertips,
        raw_count=raw_count,
        gap_count=gap_count,
        shallow_gaps=metrics["shallow_gaps"],
        open_hand_gaps=metrics["open_hand_gaps"],
        right_ratio=metrics["right_ratio"],
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
            f"dedos={detection.count} bruto={detection.raw_count} pontas={len(detection.fingertips)}",
            (10, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.85,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            debug_img,
            (
                f"gaps={detection.gap_count}/{detection.open_hand_gaps} "
                f"rasos={detection.shallow_gaps} direita={detection.right_ratio:.2f}"
            ),
            (10, 68),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.75,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
        return detection.count, debug_img, mask

    return detection.count


def analyze_hand_image(image, debug=False):
    """Detecta o quadrado vermelho e conta dedos apenas dentro dele."""
    hand_zone = infer_blue_hand_zone(image)

    if not hand_zone.found:
        empty_mask = np.zeros(image.shape[:2], dtype=np.uint8)
        if debug:
            debug_img = image.copy()
            cv2.putText(
                debug_img,
                "quadrado vermelho nao detectado",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (0, 0, 255),
                2,
                cv2.LINE_AA,
            )
            return None, debug_img, empty_mask
        return None

    skeleton = (
        _detect_hand_skeleton(image, hand_zone)
        if USE_HAND_SKELETON_DETECTOR
        else None
    )
    classifier = _dataset_classifier() if USE_HAND_DATASET_CLASSIFIER else None
    calibrated_count = None
    calibrated_distance = None
    if classifier is not None:
        calibrated_label, calibrated_distance = classifier.predict_with_distance(image, hand_zone)
        calibrated_count = None if calibrated_label == 0 else calibrated_label

    if debug:
        raw_count, debug_img, mask = read_finger_count(
            image,
            debug=True,
            allowed_mask=hand_zone.mask,
        )
    else:
        raw_count = read_finger_count(image, debug=False, allowed_mask=hand_zone.mask)

    dataset_is_confident = (
        calibrated_distance is not None
        and calibrated_distance <= HAND_DATASET_CONFIDENCE_DISTANCE
    )
    if skeleton is not None and not dataset_is_confident:
        count = normalize_hand_count(skeleton.count)
    elif classifier is not None and dataset_is_confident:
        count = calibrated_count
    else:
        count = normalize_hand_count(raw_count)

    if debug:
        debug_img = _draw_skeleton_debug(debug_img, skeleton)
        overlay = debug_img.copy()
        overlay[hand_zone.mask > 0] = (0, 0, 255)
        debug_img = cv2.addWeighted(overlay, 0.22, debug_img, 0.78, 0)
        zone_contours, _ = cv2.findContours(
            hand_zone.blue_mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        cv2.drawContours(debug_img, zone_contours, -1, (0, 0, 255), 2)

        source = (
            "skeleton"
            if skeleton is not None and not dataset_is_confident
            else ("dataset" if classifier is not None else "contorno")
        )
        label = str(count) if count is not None else "vazio"
        cv2.putText(
            debug_img,
            f"sinal={label} fonte={source}",
            (20, 80),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.95,
            (0, 0, 255),
            3,
            cv2.LINE_AA,
        )
        return count, debug_img, mask

    return count


def write_hand_debug(image, debug_img, mask, output_prefix):
    output_prefix = Path(output_prefix)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_prefix.with_name(output_prefix.name + "_debug.png")), debug_img)
    cv2.imwrite(str(output_prefix.with_name(output_prefix.name + "_mask.png")), mask)


def _next_capture_path(output_dir, label=None):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    prefix = f"{label}dedo" if label in {1, 2, 3, 4, 5} else "captura"
    candidate = output_dir / f"{prefix}_{timestamp}.jpg"

    suffix = 1
    while candidate.exists():
        candidate = output_dir / f"{prefix}_{timestamp}_{suffix:02d}.jpg"
        suffix += 1

    return candidate


def save_hand_capture(image, output_dir=DEFAULT_SIGNALS_DIR, label=None):
    _require_cv2()
    path = _next_capture_path(output_dir, label=label)
    ok = cv2.imwrite(str(path), image)
    if not ok:
        raise RuntimeError(f"Nao foi possivel salvar captura em: {path}")
    return path


def capture_hand_image_webcam(
    camera_index=WEBCAM_INDEX,
    fullscreen=True,
    save_capture=True,
    output_dir=DEFAULT_SIGNALS_DIR,
    label=None,
    continuous=False,
    save_debug=False,
    debug_dir=DEFAULT_HAND_DEBUG_DIR,
):
    _require_cv2()
    cap = open_camera(camera_index)

    if cap is None or not cap.isOpened():
        print("Erro: webcam nao abriu.")
        return None, None

    for _ in range(10):
        cap.read()

    window = "Sinal de mao - ESPACO captura | ESC sai"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    if fullscreen:
        cv2.setWindowProperty(window, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    last_result = "Espaco captura; Esc sai"

    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            cap.release()
            cv2.destroyWindow(window)
            print("Erro: nao foi possivel capturar imagem da webcam.")
            return None, None

        preview = frame.copy()
        hand_zone = infer_blue_hand_zone(preview)
        zone_label = (
            "quadrado vermelho OK"
            if hand_zone.found
            else "quadrado vermelho NAO detectado"
        )
        zone_color = (0, 255, 0) if hand_zone.found else (0, 0, 255)
        if hand_zone.found:
            contours, _ = cv2.findContours(
                hand_zone.blue_mask,
                cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE,
            )
            cv2.drawContours(preview, contours, -1, (0, 0, 255), 2)
            overlay = preview.copy()
            overlay[hand_zone.mask > 0] = (0, 0, 255)
            preview = cv2.addWeighted(overlay, 0.18, preview, 0.82, 0)

        cv2.putText(
            preview,
            "Mao no quadrado vermelho | ESPACO = capturar e salvar | ESC = sair",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            preview,
            zone_label,
            (20, 80),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            zone_color,
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            preview,
            last_result,
            (20, 120),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

        cv2.imshow(window, preview)
        key = cv2.waitKey(1) & 0xFF

        if key == 27:
            cap.release()
            cv2.destroyWindow(window)
            return None, None

        if key == 32:
            image = frame.copy()
            saved_path = None
            if save_capture:
                saved_path = save_hand_capture(
                    image,
                    output_dir=output_dir,
                    label=label,
                )

            if continuous:
                count, debug_img, mask = analyze_hand_image(image, debug=True)
                result = count if count is not None else "vazio"
                print("Sinal de mao analisado:")
                if saved_path is not None:
                    print(f"- Foto salva em: {saved_path}")
                print(f"- Dedos detectados: {result}")
                print(result)

                if save_debug:
                    debug_name = Path(saved_path).stem if saved_path else "webcam"
                    write_hand_debug(image, debug_img, mask, Path(debug_dir) / debug_name)
                    print(f"- Debug salvo em: {Path(debug_dir).name}/")

                last_result = f"ultimo resultado: {result}"
                continue

            cap.release()
            cv2.destroyWindow(window)
            return image, saved_path


def read_hand_sign_from_camera(
    camera_index=WEBCAM_INDEX,
    debug_dir=DEFAULT_HAND_DEBUG_DIR,
    save_debug=False,
    fullscreen=True,
    save_capture=True,
    output_dir=DEFAULT_SIGNALS_DIR,
    label=None,
    continuous=True,
):
    if continuous:
        capture_hand_image_webcam(
            camera_index,
            fullscreen=fullscreen,
            save_capture=save_capture,
            output_dir=output_dir,
            label=label,
            continuous=True,
            save_debug=save_debug,
            debug_dir=debug_dir,
        )
        return None

    image, saved_path = capture_hand_image_webcam(
        camera_index,
        fullscreen=fullscreen,
        save_capture=save_capture,
        output_dir=output_dir,
        label=label,
    )
    if image is None:
        print("vazio")
        return None

    count, debug_img, mask = analyze_hand_image(image, debug=True)

    print("Sinal de mao analisado:")
    if saved_path is not None:
        print(f"- Foto salva em: {saved_path}")
    print(f"- Dedos detectados: {count if count is not None else 'vazio'}")
    if save_debug:
        write_hand_debug(image, debug_img, mask, Path(debug_dir) / "webcam")
        print(f"- Debug salvo em: {Path(debug_dir).name}/")
    print(count if count is not None else "vazio")
    return count


def evaluate_hand_image(path, debug_name=None, debug_dir=DEFAULT_HAND_DEBUG_DIR):
    image = cv2.imread(str(path))
    if image is None:
        raise FileNotFoundError(f"Nao foi possivel abrir a imagem: {path}")

    count, debug_img, mask = analyze_hand_image(image, debug=True)
    if debug_name:
        write_hand_debug(image, debug_img, mask, Path(debug_dir) / debug_name)

    return count


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

    Convencao atual dos sinais:
    1 dedo = hit, 2 dedos = split, 3 dedos = double, 5 dedos = stand.
    Split fica ativo quando 2 dedos sao detectados.
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
                "area vermelha nao encontrada",
                (10, 35),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 0, 255),
                2,
                cv2.LINE_AA,
            )
            return 0, 0, debug_img, empty_mask
        return 0, 0

    skeleton = (
        _detect_hand_skeleton(hand_area, hand_zone)
        if USE_HAND_SKELETON_DETECTOR
        else None
    )
    classifier = (
        _dataset_classifier()
        if USE_HAND_DATASET_CLASSIFIER and require_blue_area and hand_zone is not None
        else None
    )
    calibrated_fingers = None
    calibrated_distance = None
    if classifier is not None:
        calibrated_label, calibrated_distance = classifier.predict_with_distance(hand_area, hand_zone)
        calibrated_fingers = 0 if calibrated_label == 0 else calibrated_label

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

    if calibrated_fingers is not None:
        fingers = calibrated_fingers
    dataset_is_confident = (
        calibrated_distance is not None
        and calibrated_distance <= HAND_DATASET_CONFIDENCE_DISTANCE
    )
    if skeleton is not None and not dataset_is_confident:
        fingers = skeleton.count
    elif calibrated_fingers is not None and not dataset_is_confident:
        fingers = 0

    handsign = stabilizer.update(fingers) if stabilizer is not None else fingers
    split = 1 if handsign == 2 else 0

    if debug:
        debug_img = _draw_skeleton_debug(debug_img, skeleton)
        if hand_zone is not None and hand_zone.found:
            overlay = debug_img.copy()
            overlay[hand_zone.mask > 0] = (0, 0, 255)
            debug_img = cv2.addWeighted(overlay, 0.25, debug_img, 0.75, 0)
            zone_contours, _ = cv2.findContours(
                hand_zone.blue_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            cv2.drawContours(debug_img, zone_contours, -1, (0, 0, 255), 2)
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

        raw_fingers, debug_img, mask = analyze_hand_image(frame, debug=True)
        raw_fingers = raw_fingers or 0
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
    parser.add_argument("--image", type=Path, help="Imagem estatica para reconhecer.")
    parser.add_argument(
        "--debug-name",
        default=None,
        help="Nome base dos arquivos de debug ao usar --image.",
    )
    parser.add_argument(
        "--save-debug",
        action="store_true",
        help="Salva imagens de debug ao capturar pela camera.",
    )
    parser.add_argument(
        "--no-fullscreen",
        action="store_true",
        help="Abre a janela em modo normal em vez de tela cheia.",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Nao salva a foto capturada com Espaco em Sinais/.",
    )
    parser.add_argument(
        "--save-dir",
        type=Path,
        default=DEFAULT_SIGNALS_DIR,
        help="Pasta onde as fotos capturadas serao salvas. Padrao: Sinais/.",
    )
    parser.add_argument(
        "--label",
        type=int,
        choices=sorted(VALID_HAND_COUNTS),
        default=None,
        help="Rotulo real da captura, se voce quiser salvar como 1dedo..5dedo.",
    )
    parser.add_argument(
        "--single-shot",
        action="store_true",
        help="Captura uma vez e fecha, em vez de continuar ate Esc.",
    )
    args = parser.parse_args()

    if args.image:
        count = evaluate_hand_image(args.image, debug_name=args.debug_name)
        print(count if count is not None else "vazio")
        return

    read_hand_sign_from_camera(
        camera_index=args.camera,
        save_debug=args.save_debug,
        fullscreen=not args.no_fullscreen,
        save_capture=not args.no_save,
        output_dir=args.save_dir,
        label=args.label,
        continuous=not args.single_shot,
    )


if __name__ == "__main__":
    main()
