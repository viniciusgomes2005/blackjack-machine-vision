import numpy as np

try:
    import cv2
except ModuleNotFoundError:
    cv2 = None

from config import HSV_RANGES, ROI_COLORS


def _require_cv2():
    if cv2 is None:
        raise ModuleNotFoundError(
            "OpenCV nao esta instalado. Rode: pip install -r requirements.txt"
        )


def crop_area(frame, roi):
    """Recorta uma ROI fixa do frame."""
    x, y, w, h = roi
    height, width = frame.shape[:2]

    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(width, x + w)
    y2 = min(height, y + h)

    return frame[y1:y2, x1:x2].copy()


def draw_rois(frame, rois):
    """Desenha todas as ROIs no frame de debug."""
    _require_cv2()
    debug = frame.copy()

    for name, (x, y, w, h) in rois.items():
        color = ROI_COLORS.get(name, (255, 255, 255))
        cv2.rectangle(debug, (x, y), (x + w, y + h), color, 2)
        cv2.putText(
            debug,
            name,
            (x, max(20, y - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            2,
            cv2.LINE_AA,
        )

    return debug


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


def detect_colored_tape_areas(frame):
    """
    Detecta fitas coloridas para calibracao.

    O sistema principal usa ROIs fixas. Esta funcao serve apenas para mostrar
    onde o HSV esta encontrando vermelho, azul e amarelo.
    """
    _require_cv2()
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    result = {}

    for color_name in ["red_tape", "blue_tape", "yellow_tape"]:
        mask = _mask_from_ranges(hsv, HSV_RANGES[color_name])
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        boxes = []
        for contour in contours:
            if cv2.contourArea(contour) < 500:
                continue
            boxes.append(cv2.boundingRect(contour))

        result[color_name] = boxes

    return result
