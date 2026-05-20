from pathlib import Path

import cv2

from card_vision import (
    extract_card_corner,
    find_card_contours,
    preprocess_symbol_image,
    resolve_project_path,
)
from config import RANK_TEMPLATE_DIR, ROIS, SUIT_TEMPLATE_DIR
from vision_areas import crop_area


IMAGE_DIRS = ["test_images", "images"]
VALID_RANKS = {"A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"}
VALID_SUITS = {"spades", "hearts", "clubs", "diamonds", ""}


def find_input_images():
    """Busca imagens primeiro em test_images/ e depois em images/."""
    images = []

    for folder in IMAGE_DIRS:
        folder_path = resolve_project_path(folder)
        if not folder_path.exists():
            continue

        for extension in ("*.png", "*.jpg", "*.jpeg"):
            images.extend(sorted(folder_path.glob(extension)))

    return images


def ask_value(prompt, valid_values):
    """Pergunta um valor no terminal aceitando skip ou q."""
    while True:
        value = input(prompt).strip()

        if value.lower() in {"q", "skip"}:
            return value.lower()

        normalized = value.upper() if prompt.startswith("Rank") else value.lower()
        if normalized in valid_values:
            return normalized

        print(f"Valor invalido. Opcoes: {sorted(v for v in valid_values if v)}")
        print("Use skip para pular ou q para sair.")


def save_template(folder, label, image):
    """Salva template binario em templates/ranks ou templates/suits."""
    if not label:
        return

    folder_path = resolve_project_path(folder)
    folder_path.mkdir(parents=True, exist_ok=True)
    output_path = folder_path / f"{label}.png"

    if output_path.exists():
        answer = input(f"{output_path.name} ja existe. Sobrescrever? [s/N] ").strip().lower()
        if answer not in {"s", "sim", "y", "yes"}:
            print("Mantendo template existente.")
            return

    binary = preprocess_symbol_image(image)
    if binary is None:
        print("Nao foi possivel salvar: imagem vazia.")
        return

    cv2.imwrite(str(output_path), binary)
    print(f"Template salvo: {output_path}")


def split_corner(corner):
    """Separa rank e naipe do canto superior esquerdo."""
    h = corner.shape[0]
    rank_img = corner[: max(1, h // 2), :]
    suit_img = corner[max(1, h // 2):, :]
    return rank_img, suit_img


def process_card(card_img, image_name, area_name, card_number):
    corner = extract_card_corner(card_img)
    rank_img, suit_img = split_corner(corner)

    cv2.imshow("Carta detectada", card_img)
    cv2.imshow("Canto superior esquerdo", corner)
    cv2.imshow("Template rank candidato", rank_img)
    cv2.imshow("Template naipe candidato", suit_img)
    cv2.waitKey(1)

    print("-" * 80)
    print(f"Imagem: {image_name}")
    print(f"Area: {area_name}")
    print(f"Carta detectada: {card_number}")

    rank = ask_value("Rank [A,2,3,4,5,6,7,8,9,10,J,Q,K | skip | q]: ", VALID_RANKS)
    if rank == "q":
        return False
    if rank == "skip":
        print("Carta pulada.")
        return True

    suit = ask_value("Naipe opcional [spades, hearts, clubs, diamonds, vazio, skip, q]: ", VALID_SUITS)
    if suit == "q":
        return False
    if suit == "skip":
        suit = ""

    save_template(RANK_TEMPLATE_DIR, rank, rank_img)
    if suit:
        save_template(SUIT_TEMPLATE_DIR, suit, suit_img)

    return True


def main():
    rank_dir = resolve_project_path(RANK_TEMPLATE_DIR)
    suit_dir = resolve_project_path(SUIT_TEMPLATE_DIR)
    rank_dir.mkdir(parents=True, exist_ok=True)
    suit_dir.mkdir(parents=True, exist_ok=True)

    print(f"Raiz do projeto: {resolve_project_path('.')}")
    print(f"Templates ranks: {rank_dir}")
    print(f"Templates suits: {suit_dir}")
    print()

    images = find_input_images()
    if not images:
        print("Nenhuma imagem encontrada em test_images/ ou images/.")
        return

    for image_path in images:
        frame = cv2.imread(str(image_path))
        if frame is None:
            print(f"Erro ao abrir: {image_path}")
            continue

        for area_name in ("player_cards", "dealer_cards"):
            area = crop_area(frame, ROIS[area_name])
            boxes, _ = find_card_contours(area)

            for index, (x, y, w, h) in enumerate(boxes, start=1):
                card_img = area[y:y + h, x:x + w]
                keep_going = process_card(card_img, image_path.name, area_name, index)
                if not keep_going:
                    cv2.destroyAllWindows()
                    return

    cv2.destroyAllWindows()
    print("Finalizado.")


if __name__ == "__main__":
    main()
