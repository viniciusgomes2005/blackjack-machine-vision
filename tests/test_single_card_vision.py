import numpy as np

from single_card_vision import (
    BASE_CARD_ROI,
    BASE_RESOLUTION,
    recognized_value_to_card,
    scale_roi_to_image,
)


def test_recognized_value_to_card_uses_project_card_shape():
    assert recognized_value_to_card("A") == {
        "rank": "A",
        "suit": "unknown",
        "card_id": None,
        "blackjack_value": 11,
        "rank_score": 1.0,
        "suit_score": 0.0,
        "status": "ok",
    }
    assert recognized_value_to_card(10)["rank"] == "10"
    assert recognized_value_to_card("x")["status"] == "unknown"


def test_scale_roi_keeps_validated_base_roi_at_base_resolution():
    width, height = BASE_RESOLUTION
    image = np.zeros((height, width, 3), dtype=np.uint8)

    assert scale_roi_to_image(image) == BASE_CARD_ROI
