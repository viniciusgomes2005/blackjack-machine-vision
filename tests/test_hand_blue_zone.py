import numpy as np
import pytest

import hand_sign_vision

cv2 = pytest.importorskip("cv2")


def _skin_bgr():
    hsv = np.uint8([[[12, 100, 210]]])
    return tuple(int(channel) for channel in cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0])


def _frame_with_irregular_red_zone():
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    red_polygon = np.array(
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
    cv2.fillPoly(frame, [red_polygon], (0, 0, 255))
    return frame


def test_red_hand_zone_is_inferred_from_irregular_area():
    frame = _frame_with_irregular_red_zone()

    hand_zone = hand_sign_vision.infer_blue_hand_zone(frame)

    assert hand_zone.found is True
    assert hand_zone.mask[120, 110] == 255
    assert hand_zone.mask[20, 300] == 0


def test_red_hand_zone_ignores_smaller_red_objects_nearby():
    frame = _frame_with_irregular_red_zone()
    cv2.rectangle(frame, (255, 25), (305, 75), (0, 0, 255), -1)

    hand_zone = hand_sign_vision.infer_blue_hand_zone(frame)

    assert hand_zone.found is True
    assert hand_zone.mask[120, 110] == 255
    assert hand_zone.mask[50, 280] == 0
    assert hand_zone.blue_mask[50, 280] == 0


def test_hand_sign_only_counts_skin_inside_red_zone(monkeypatch):
    def fake_detect_fingers(mask):
        count = 4 if cv2.countNonZero(mask) > 0 else 0
        return hand_sign_vision.FingerDetection(count, None, None, 0.0, ())

    monkeypatch.setattr(hand_sign_vision, "_detect_fingers", fake_detect_fingers)
    monkeypatch.setattr(hand_sign_vision, "_dataset_classifier", lambda: None)

    inside = _frame_with_irregular_red_zone()
    cv2.rectangle(inside, (85, 85), (150, 170), _skin_bgr(), -1)

    outside = _frame_with_irregular_red_zone()
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


def test_hand_sign_stabilizer_requires_repeated_values():
    stabilizer = hand_sign_vision.HandSignStabilizer(
        history_size=5,
        min_stable_frames=3,
    )

    assert stabilizer.update(2) == 0
    assert stabilizer.update(3) == 0
    assert stabilizer.update(2) == 0
    assert stabilizer.update(2) == 2
    assert stabilizer.update(4) == 2


def test_finger_detector_counts_raised_fingertips_from_palm_shape():
    one_finger = np.zeros((220, 220), dtype=np.uint8)
    cv2.circle(one_finger, (100, 150), 38, 255, -1)
    cv2.rectangle(one_finger, (92, 55), (108, 145), 255, -1)

    two_fingers = np.zeros((220, 220), dtype=np.uint8)
    cv2.circle(two_fingers, (100, 150), 38, 255, -1)
    cv2.rectangle(two_fingers, (76, 55), (92, 145), 255, -1)
    cv2.rectangle(two_fingers, (108, 55), (124, 145), 255, -1)

    assert hand_sign_vision._detect_fingers(one_finger).count == 1
    assert hand_sign_vision._detect_fingers(two_fingers).count == 2
