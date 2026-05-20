from pathlib import Path

import cv2

from card_vision import (
    extract_card_corner,
    find_card_candidates,
    preprocess_symbol_image,
    resolve_project_path,
    warp_card_from_contour,
)
from config import RANK_TEMPLATE_DIR, ROIS, SUIT_TEMPLATE_DIR
from vision_areas import crop_area


IMAGE_DIR = resolve_project_path("images")
SUIT_CODES = {
    "S": "spades",
    "H": "hearts",
    "C": "clubs",
    "D": "diamonds",
}
VALID_RANKS = {"A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"}


def parse_card_code(code):
    """Converte QS, 10H, 2D etc. para (rank, suit)."""
    if len(code) < 2:
        return None

    suit_code = code[-1]
    rank = code[:-1]
    if rank not in VALID_RANKS or suit_code not in SUIT_CODES:
        return None

    return rank, SUIT_CODES[suit_code]


def labels_from_filename(path):
    """
    Extrai labels do padrao:
    table_round_01_player_QS_5S_dealer_2H_3S.jpeg
    """
    parts = path.stem.split("_")
    player_index = parts.index("player")
    dealer_index = parts.index("dealer")

    player_codes = parts[player_index + 1:dealer_index]
    dealer_codes = parts[dealer_index + 1:]

    return {
        "player_cards": [card for code in player_codes if (card := parse_card_code(code))],
        "dealer_cards": [card for code in dealer_codes if (card := parse_card_code(code))],
    }


def split_corner(corner):
    h = corner.shape[0]
    return corner[: max(1, h // 2), :], corner[max(1, h // 2):, :]


def clear_generated_templates():
    """Limpa templates antigos para uma geracao reprodutivel."""
    for folder in (RANK_TEMPLATE_DIR, SUIT_TEMPLATE_DIR):
        folder_path = resolve_project_path(folder)
        folder_path.mkdir(parents=True, exist_ok=True)
        for path in folder_path.glob("*.png"):
            path.unlink()


def save_template_once(folder, label, image):
    folder_path = resolve_project_path(folder)
    folder_path.mkdir(parents=True, exist_ok=True)
    output_path = folder_path / f"{label}.png"

    if output_path.exists():
        print(f"mantendo primeiro template: {output_path}")
        return False

    binary = preprocess_symbol_image(image)
    if binary is None:
        print(f"falha ao gerar template: {output_path}")
        return False

    cv2.imwrite(str(output_path), binary)
    print(f"template salvo: {output_path}")
    return True


def make_templates_for_area(frame, image_name, area_name, expected_cards):
    area = crop_area(frame, ROIS[area_name])
    candidates, _ = find_card_candidates(area)

    print(f"{image_name} | {area_name}: detectadas={len(candidates)} esperadas={len(expected_cards)}")

    saved = 0
    for index, candidate in enumerate(candidates):
        if index >= len(expected_cards):
            break

        rank, suit = expected_cards[index]
        card_img = warp_card_from_contour(area, candidate["contour"])
        corner = extract_card_corner(card_img)
        rank_img, suit_img = split_corner(corner)

        if save_template_once(RANK_TEMPLATE_DIR, rank, rank_img):
            saved += 1
        if save_template_once(SUIT_TEMPLATE_DIR, suit, suit_img):
            saved += 1

    return saved


def main():
    clear_generated_templates()

    image_paths = sorted(IMAGE_DIR.glob("*.jpeg"))
    if not image_paths:
        print(f"Nenhuma imagem encontrada em {IMAGE_DIR}")
        return

    total_saved = 0

    for image_path in image_paths:
        labels = labels_from_filename(image_path)
        frame = cv2.imread(str(image_path))

        if frame is None:
            print(f"erro ao abrir: {image_path}")
            continue

        total_saved += make_templates_for_area(
            frame,
            image_path.name,
            "player_cards",
            labels["player_cards"],
        )
        total_saved += make_templates_for_area(
            frame,
            image_path.name,
            "dealer_cards",
            labels["dealer_cards"],
        )

    print(f"Finalizado. Novos templates salvos: {total_saved}")


if __name__ == "__main__":
    main()
