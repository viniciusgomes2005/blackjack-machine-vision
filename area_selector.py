import cv2

from config import ROI_COLORS, ROIS


def crop_rois(frame, rois=None):
    """
    Recorta as ROIs fixas do frame.

    Retorna um dicionario:
        {"player_cards": imagem_roi, "dealer_cards": imagem_roi, ...}
    """
    if rois is None:
        rois = ROIS

    crops = {}
    height, width = frame.shape[:2]

    for name, (x, y, w, h) in rois.items():
        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(width, x + w)
        y2 = min(height, y + h)
        crops[name] = frame[y1:y2, x1:x2].copy()

    return crops


def draw_rois(frame, rois=None):
    """
    Desenha as ROIs no frame para debug visual.

    A funcao devolve uma copia do frame para evitar alterar o frame original.
    """
    if rois is None:
        rois = ROIS

    debug_frame = frame.copy()

    for name, (x, y, w, h) in rois.items():
        color = ROI_COLORS.get(name, (255, 255, 255))
        cv2.rectangle(debug_frame, (x, y), (x + w, y + h), color, 2)
        cv2.putText(
            debug_frame,
            name,
            (x, max(20, y - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
            cv2.LINE_AA,
        )

    return debug_frame
