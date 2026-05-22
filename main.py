import argparse

import cv2

import blackjack_engine
from camera_utils import open_camera
from card_vision import load_templates, read_cards_from_area
from chip_vision import calculate_bet, count_chips_by_color, optimize_chips
from config import (
    CHIP_VALUES,
    PRINT_EVERY_FRAME,
    RANK_TEMPLATE_DIR,
    ROIS,
    SHOW_DEBUG_WINDOWS,
    SUIT_TEMPLATE_DIR,
)
from game_state import GameState
from hand_sign_vision import DoubleDownDetector, HandSignStabilizer, read_hand_sign
from robot_commands import orders_from_action
from vision_areas import crop_area, detect_colored_tape_areas, draw_rois


def choose_robot_orders(handsign, recommended_action, current_bet):
    """
    Sinal do jogador tem prioridade. Se nao houver sinal, usa a recomendacao
    matematica apenas como demonstracao.
    """
    if handsign == 1:
        return orders_from_action("hit")
    if handsign == 2:
        return orders_from_action("split")
    if handsign == 3:
        return orders_from_action("double", optimize_chips(current_bet, CHIP_VALUES))
    if handsign == 4:
        return orders_from_action("stand")

    return orders_from_action(recommended_action, optimize_chips(current_bet, CHIP_VALUES))


def main():
    parser = argparse.ArgumentParser(description="Blackjack machine vision.")
    parser.add_argument(
        "--camera",
        type=int,
        default=0,
        help="Indice da camera usada pelo OpenCV. Padrao: 0.",
    )
    parser.add_argument(
        "--single-card-camera",
        action="store_true",
        help="Usa o reconhecedor validado de uma carta isolada e encerra.",
    )
    args = parser.parse_args()

    if args.single_card_camera:
        from single_card_vision import analyze_webcam

        analyze_webcam(camera_index=args.camera)
        return

    cap = open_camera(args.camera)
    if cap is None:
        return

    rank_templates = load_templates(RANK_TEMPLATE_DIR)
    suit_templates = load_templates(SUIT_TEMPLATE_DIR)

    game_state = GameState()
    double_detector = DoubleDownDetector(required_seconds=3)
    hand_sign_stabilizer = HandSignStabilizer()

    print("Templates de ranks carregados:", list(rank_templates.keys()))
    print("Templates de naipes carregados:", list(suit_templates.keys()))
    print("Pressione q para sair. Pressione r para resetar a rodada.")

    while True:
        ok, frame = cap.read()
        if not ok:
            print("Falha ao capturar frame.")
            break

        debug_rois = draw_rois(frame, ROIS)

        player_area = crop_area(frame, ROIS["player_cards"])
        dealer_area = crop_area(frame, ROIS["dealer_cards"])
        chip_area = crop_area(frame, ROIS["player_chips"])
        hand_area = crop_area(frame, ROIS["hand_sign_area"])

        player_cards, player_debug, player_thresh = read_cards_from_area(
            player_area, rank_templates, suit_templates, debug=True
        )
        dealer_cards, dealer_debug, dealer_thresh = read_cards_from_area(
            dealer_area, rank_templates, suit_templates, debug=True
        )

        game_state.update_player_cards(player_cards, hand_index=0)
        game_state.update_dealer_cards(dealer_cards)

        chip_counts, chip_debug, chip_masks = count_chips_by_color(chip_area, debug=True)
        current_bet = calculate_bet(chip_counts, CHIP_VALUES)

        if game_state.original_bet == 0 and current_bet > 0:
            game_state.original_bet = current_bet

        game_state.current_bet = current_bet
        game_state.optimized_chips = optimize_chips(current_bet, CHIP_VALUES)

        handsign, split, hand_debug, hand_mask = read_hand_sign(
            hand_area,
            double_detector,
            original_bet=game_state.original_bet,
            current_bet=current_bet,
            debug=True,
            stabilizer=hand_sign_stabilizer,
        )
        game_state.Handsign = handsign
        game_state.Split = split

        player_value = blackjack_engine.hand_value(player_cards)
        dealer_value = blackjack_engine.hand_value(dealer_cards)
        dealer_upcard = dealer_cards[0] if dealer_cards else None

        recommended_action = blackjack_engine.basic_strategy(
            player_cards,
            dealer_upcard,
            can_double=True,
            can_split=blackjack_engine.can_split(player_cards),
        )

        robot_orders = choose_robot_orders(handsign, recommended_action, current_bet)
        game_state.robot_orders = robot_orders

        state_output = {
            "Handsign": game_state.Handsign,
            "Split": game_state.Split,
            "PlayerCards": player_cards,
            "DealerCards": dealer_cards,
            "SeenCards": game_state.seen_cards,
            "PlayerValue": player_value,
            "DealerValue": dealer_value,
            "CurrentBet": game_state.current_bet,
            "OriginalBet": game_state.original_bet,
            "ChipCounts": chip_counts,
            "OptimizedChips": game_state.optimized_chips,
            "RecommendedAction": recommended_action,
            "RobotOrders": robot_orders,
        }

        if PRINT_EVERY_FRAME:
            print(state_output)

        if SHOW_DEBUG_WINDOWS:
            tape_boxes = detect_colored_tape_areas(frame)
            for boxes in tape_boxes.values():
                for x, y, w, h in boxes:
                    cv2.rectangle(debug_rois, (x, y), (x + w, y + h), (255, 255, 255), 1)

            cv2.putText(
                debug_rois,
                f"Dedos levantados: {handsign}",
                (20, 70),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.2,
                (0, 255, 255),
                3,
                cv2.LINE_AA,
            )
            cv2.imshow("Mesa - ROIs", debug_rois)
            cv2.imshow("Cartas Jogador", player_debug)
            cv2.imshow("Cartas Dealer", dealer_debug)
            cv2.imshow("Threshold Jogador", player_thresh)
            cv2.imshow("Threshold Dealer", dealer_thresh)
            cv2.imshow("Fichas", chip_debug)
            cv2.imshow("Sinal de Mao", hand_debug)

            if hand_mask is not None:
                cv2.imshow("Mascara Pele na Area Vermelha", hand_mask)

            for color, mask in chip_masks.items():
                cv2.imshow(f"Mascara Ficha {color}", mask)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("r"):
            game_state.reset_round()
            double_detector = DoubleDownDetector(required_seconds=3)
            hand_sign_stabilizer.reset()
            print("Rodada resetada.")

        game_state.start_new_round_if_needed()

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
