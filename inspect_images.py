from pathlib import Path
import os

import cv2

from card_vision import PROJECT_ROOT, load_templates, read_cards_from_area, resolve_project_path
from config import RANK_TEMPLATE_DIR, ROIS, SUIT_TEMPLATE_DIR
from vision_areas import crop_area, draw_rois


IMAGE_DIR = Path("images")


def print_cards(area_name, cards):
    print(f"  {area_name}: {len(cards)} carta(s) detectada(s)")

    for index, card in enumerate(cards, start=1):
        print(
            "    "
            f"{index}. rank={card['rank']} "
            f"suit={card['suit']} "
            f"card_id={card['card_id']} "
            f"blackjack_value={card['blackjack_value']} "
            f"rank_score={card['rank_score']} "
            f"suit_score={card['suit_score']} "
            f"status={card['status']}"
        )


def main():
    rank_template_path = resolve_project_path(RANK_TEMPLATE_DIR)
    suit_template_path = resolve_project_path(SUIT_TEMPLATE_DIR)

    print(f"Diretorio atual: {Path(os.getcwd())}")
    print(f"Raiz do projeto: {PROJECT_ROOT}")
    print(f"Templates ranks: {rank_template_path}")
    print(f"Templates suits: {suit_template_path}")
    print()

    rank_templates = load_templates(RANK_TEMPLATE_DIR)
    suit_templates = load_templates(SUIT_TEMPLATE_DIR)

    print("Templates carregados:")
    print(f"  ranks: {list(rank_templates.keys())}")
    print(f"  suits: {list(suit_templates.keys())}")
    print()

    if not rank_templates or not suit_templates:
        print(
            "Nenhum template encontrado. Rode python make_templates.py primeiro."
        )
        print(
            "Enquanto os templates estiverem vazios, o script mostra a quantidade "
            "de cartas detectadas, mas rank/naipe aparecem como unknown."
        )
        print()

    image_paths = sorted(IMAGE_DIR.glob("*.jpeg"))

    for image_path in image_paths:
        frame = cv2.imread(str(image_path))
        if frame is None:
            print(f"{image_path.name}: erro ao abrir imagem")
            continue

        player_area = crop_area(frame, ROIS["player_cards"])
        dealer_area = crop_area(frame, ROIS["dealer_cards"])

        player_cards, player_debug, _ = read_cards_from_area(
            player_area, rank_templates, suit_templates, debug=True
        )
        dealer_cards, dealer_debug, _ = read_cards_from_area(
            dealer_area, rank_templates, suit_templates, debug=True
        )

        print("=" * 80)
        print(f"Imagem: {image_path.name}")
        print_cards("player_cards", player_cards)
        print_cards("dealer_cards", dealer_cards)

        debug_frame = draw_rois(frame, ROIS)
        cv2.imshow("Mesa com ROIs", debug_frame)
        cv2.imshow("Player cards detectadas", player_debug)
        cv2.imshow("Dealer cards detectadas", dealer_debug)

        print("Pressione qualquer tecla na janela do OpenCV para ir para a proxima imagem.")
        print("Pressione q para sair.")

        key = cv2.waitKey(0) & 0xFF
        if key == ord("q"):
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
