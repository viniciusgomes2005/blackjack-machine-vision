import re
from pathlib import Path

import pytest

import hand_sign_vision

cv2 = pytest.importorskip("cv2")


SIGNALS_DIR = Path(__file__).resolve().parents[1] / "Sinais"


def _expected_count(path):
    name = path.name.lower()
    if name.startswith("t"):
        return None
    if "vazio" in name:
        return 0

    match = re.search(r"([1-5])dedo", name)
    if match is None:
        return None
    value = int(match.group(1))
    return value if value in hand_sign_vision.VALID_HAND_COUNTS else None


def test_sinais_dataset_reaches_full_accuracy():
    image_paths = sorted(SIGNALS_DIR.glob("*.jpg"))
    assert image_paths, "Dataset Sinais/*.jpg nao encontrado."

    mistakes = []
    for path in image_paths:
        frame = cv2.imread(str(path))
        assert frame is not None, f"Falha ao abrir {path}"

        predicted, _ = hand_sign_vision.read_hand_sign(
            frame,
            double_detector=None,
            original_bet=0,
            current_bet=0,
            require_blue_area=True,
        )
        expected = _expected_count(path)
        if expected is None:
            continue
        if predicted != expected:
            mistakes.append((path.name, expected, predicted))

    assert mistakes == []


def test_blank_image_returns_empty_hand_sign():
    import numpy as np

    blank = np.zeros((300, 400, 3), dtype=np.uint8)

    assert hand_sign_vision.analyze_hand_image(blank) is None
