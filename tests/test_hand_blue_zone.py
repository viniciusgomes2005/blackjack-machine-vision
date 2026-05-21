import numpy as np
import pytest

import hand_sign_vision

cv2 = pytest.importorskip("cv2")


def _skin_bgr():
    hsv = np.uint8([[[10, 100, 210]]])
    return tuple(int(channel) for channel in cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0])


def _frame_with_irregular_blue_zone():
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    blue_polygon = np.array(
        [
            [35, 55],
            [170, 35],
            [205, 120],
            [165, 195],
            [45, 180],
            [20, 105],
        ],
        dtype=np.int32,
    )
    cv2.fillPoly(frame, [blue_polygon], (255, 0, 0))
    return frame


def test_blue_hand_zone_is_inferred_from_irregular_area():
    frame = _frame_with_irregular_blue_zone()

    hand_zone = hand_sign_vision.infer_blue_hand_zone(frame)

    assert hand_zone.found is True
    assert hand_zone.mask[120, 110] == 255
    assert hand_zone.mask[20, 300] == 0


def test_hand_sign_only_counts_skin_inside_blue_zone(monkeypatch):
    monkeypatch.setattr(hand_sign_vision, "_estimate_fingers", lambda contour: 4)

    inside = _frame_with_irregular_blue_zone()
    cv2.rectangle(inside, (85, 85), (150, 170), _skin_bgr(), -1)

    outside = _frame_with_irregular_blue_zone()
    cv2.rectangle(outside, (240, 85), (300, 170), _skin_bgr(), -1)

    assert hand_sign_vision.read_hand_sign(
        inside,
        double_detector=None,
        original_bet=0,
        current_bet=0,
    ) == (4, 0)
    assert hand_sign_vision.read_hand_sign(
        outside,
        double_detector=None,
        original_bet=0,
        current_bet=0,
    ) == (0, 0)
