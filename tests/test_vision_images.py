from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")

from card_vision import find_card_contours
from config import ROIS
from vision_areas import crop_area


IMAGE_DIR = Path("images")


RENAMED_IMAGES = [
    "table_round_01_player_QS_5S_dealer_2H_3S.jpeg",
    "table_round_02_player_KC_8C_dealer_JC_8H_hand.jpeg",
    "table_round_03_player_AH_10H_dealer_4S_6C.jpeg",
    "table_round_04_player_3C_JD_dealer_2H_8D.jpeg",
    "table_round_05_player_2D_2H_dealer_4D_JC.jpeg",
]


def test_reference_images_were_renamed():
    for filename in RENAMED_IMAGES:
        assert (IMAGE_DIR / filename).exists()


@pytest.mark.parametrize("filename", RENAMED_IMAGES)
def test_card_contours_are_found_in_reference_images(filename):
    frame = cv2.imread(str(IMAGE_DIR / filename))
    assert frame is not None

    player_area = crop_area(frame, ROIS["player_cards"])
    dealer_area = crop_area(frame, ROIS["dealer_cards"])

    player_boxes, _ = find_card_contours(player_area)
    dealer_boxes, _ = find_card_contours(dealer_area)

    assert len(player_boxes) >= 1
    assert len(dealer_boxes) >= 1


def test_print_detected_cards_for_reference_images():
    from card_vision import load_templates, read_cards_from_area
    from config import RANK_TEMPLATE_DIR, SUIT_TEMPLATE_DIR

    rank_templates = load_templates(RANK_TEMPLATE_DIR)
    suit_templates = load_templates(SUIT_TEMPLATE_DIR)

    print()
    print("Resumo das imagens de teste:")
    print(f"Templates ranks: {list(rank_templates.keys())}")
    print(f"Templates suits: {list(suit_templates.keys())}")

    for filename in RENAMED_IMAGES:
        frame = cv2.imread(str(IMAGE_DIR / filename))
        player_area = crop_area(frame, ROIS["player_cards"])
        dealer_area = crop_area(frame, ROIS["dealer_cards"])

        player_cards = read_cards_from_area(player_area, rank_templates, suit_templates)
        dealer_cards = read_cards_from_area(dealer_area, rank_templates, suit_templates)

        print("-" * 80)
        print(f"Imagem: {filename}")
        print(f"PlayerCards quantidade: {len(player_cards)}")
        for card in player_cards:
            print(f"  Player: {card}")

        print(f"DealerCards quantidade: {len(dealer_cards)}")
        for card in dealer_cards:
            print(f"  Dealer: {card}")

        assert len(player_cards) >= 1
        assert len(dealer_cards) >= 1


def test_expected_ranks_for_first_reference_images():
    from card_vision import load_templates, read_cards_from_area
    from config import RANK_TEMPLATE_DIR, SUIT_TEMPLATE_DIR

    rank_templates = load_templates(RANK_TEMPLATE_DIR)
    suit_templates = load_templates(SUIT_TEMPLATE_DIR)

    expectations = {
        "table_round_01_player_QS_5S_dealer_2H_3S.jpeg": {
            "player_cards": {"Q", "5"},
            "dealer_cards": {"2"},
        },
        "table_round_02_player_KC_8C_dealer_JC_8H_hand.jpeg": {
            "player_cards": {"K", "8"},
            "dealer_cards": {"J", "8"},
        },
    }

    for filename, expected in expectations.items():
        frame = cv2.imread(str(IMAGE_DIR / filename))

        player_area = crop_area(frame, ROIS["player_cards"])
        dealer_area = crop_area(frame, ROIS["dealer_cards"])

        player_cards = read_cards_from_area(player_area, rank_templates, suit_templates)
        dealer_cards = read_cards_from_area(dealer_area, rank_templates, suit_templates)

        player_ranks = {card["rank"] for card in player_cards if card["status"] == "ok"}
        dealer_ranks = {card["rank"] for card in dealer_cards if card["status"] == "ok"}

        assert expected["player_cards"].issubset(player_ranks)
        assert dealer_ranks.intersection(expected["dealer_cards"])


def test_one_round_simulation_uses_card_and_hand_image_recognition():
    from blackjack_engine import RESULT_LOSE
    from main import simulate_round_from_files

    summary = simulate_round_from_files(
        IMAGE_DIR / "table_round_01_player_QS_5S_dealer_2H_3S.jpeg",
        [Path("Sinais") / "4Dedo1.jpg"],
        dealer_hole="3S",
        player_draws=[],
        dealer_draws=["KH", "6C"],
    )

    player_ranks = {card["rank"] for card in summary["vision"]["table"]["player_cards"]}
    dealer_ranks = {card["rank"] for card in summary["vision"]["table"]["dealer_cards"]}

    assert {"Q", "5"}.issubset(player_ranks)
    assert "2" in dealer_ranks
    assert summary["vision"]["hand_decisions"][0]["fingers"] == 4
    assert summary["vision"]["player_actions"] == ["stand"]
    assert summary["dealer_total"] == 21
    assert summary["player_hands"][0]["result"] == RESULT_LOSE


def test_manual_card_arguments_can_drive_split_round_with_hand_images():
    from main import simulate_round_from_files

    summary = simulate_round_from_files(
        round_image=None,
        hand_images=[
            Path("Sinais") / "2Dedo1.jpg",
            Path("Sinais") / "4Dedo1.jpg",
            Path("Sinais") / "4Dedo2.jpg",
        ],
        dealer_hole="10H",
        player_draws=["3H", "2C"],
        dealer_draws=["5C"],
        player_card_codes=["8H", "8D"],
        dealer_upcard="6S",
    )

    assert summary["vision"]["table"]["source"] == "manual"
    assert summary["vision"]["player_actions"] == ["split", "stand", "stand"]
    assert summary["split_count"] == 1
    assert [hand["cards"] for hand in summary["player_hands"]] == [
        ["8 of hearts", "3 of hearts"],
        ["8 of diamonds", "2 of clubs"],
    ]
    assert summary["dealer_total"] == 21
