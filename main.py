import argparse
from pathlib import Path

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
from hand_sign_vision import (
    DoubleDownDetector,
    HandSignStabilizer,
    analyze_hand_image,
    read_hand_sign,
)
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


def recognized_cards(cards):
    """Mantem apenas cartas com rank reconhecido pela visao."""
    return [card for card in cards if card.get("status") == "ok" and card.get("rank") != "unknown"]


def read_table_cards_from_image(image_path):
    """Le cartas do jogador e do dealer a partir de uma imagem da mesa."""
    image_path = Path(image_path)
    frame = cv2.imread(str(image_path))
    if frame is None:
        raise FileNotFoundError(f"nao foi possivel abrir a imagem: {image_path}")

    rank_templates = load_templates(RANK_TEMPLATE_DIR)
    suit_templates = load_templates(SUIT_TEMPLATE_DIR)
    player_area = crop_area(frame, ROIS["player_cards"])
    dealer_area = crop_area(frame, ROIS["dealer_cards"])

    player_cards = read_cards_from_area(player_area, rank_templates, suit_templates)
    dealer_cards = read_cards_from_area(dealer_area, rank_templates, suit_templates)

    return {
        "image": str(image_path),
        "player_cards": recognized_cards(player_cards),
        "dealer_cards": recognized_cards(dealer_cards),
        "raw_player_cards": player_cards,
        "raw_dealer_cards": dealer_cards,
    }


def read_hand_decision_from_image(image_path):
    """Reconhece um sinal de mao salvo em imagem e converte para acao."""
    from DealerBotMain import decision_from_hand_count

    image_path = Path(image_path)
    frame = cv2.imread(str(image_path))
    if frame is None:
        raise FileNotFoundError(f"nao foi possivel abrir a imagem: {image_path}")

    fingers = analyze_hand_image(frame)
    decision = decision_from_hand_count(fingers)
    return {
        "image": str(image_path),
        "fingers": decision.fingers,
        "action": decision.action,
        "robot_signal": decision.robot_signal,
    }


def cards_from_codes(codes):
    return [blackjack_engine.card_from_code(code) for code in codes]


def table_cards_from_codes(player_card_codes, dealer_upcard_code):
    if len(player_card_codes) != 2:
        raise RuntimeError("use --player-card exatamente 2 vezes para simular a mao inicial")
    if dealer_upcard_code is None:
        raise RuntimeError("use --dealer-upcard para simular a carta aberta do dealer")

    return {
        "image": "argumentos manuais",
        "source": "manual",
        "player_cards": cards_from_codes(player_card_codes),
        "dealer_cards": [blackjack_engine.card_from_code(dealer_upcard_code)],
        "raw_player_cards": [],
        "raw_dealer_cards": [],
    }


def simulate_round_from_files(
    round_image,
    hand_images,
    dealer_hole,
    player_draws,
    dealer_draws,
    player_card_codes=None,
    dealer_upcard=None,
):
    """
    Executa uma rodada local sem Modbus:
    imagem da mesa -> cartas, imagens de mao -> acoes, motor -> resultado.
    """
    if player_card_codes or dealer_upcard:
        table = table_cards_from_codes(player_card_codes or [], dealer_upcard)
    else:
        table = read_table_cards_from_image(round_image)

    player_cards = table["player_cards"]
    dealer_cards = table["dealer_cards"]

    if len(player_cards) < 2:
        raise RuntimeError("a imagem precisa reconhecer ao menos 2 cartas do jogador")
    if not dealer_cards:
        raise RuntimeError("a imagem precisa reconhecer a carta aberta do dealer")

    hand_decisions = [read_hand_decision_from_image(path) for path in hand_images]
    player_actions = [
        decision["action"]
        for decision in hand_decisions
        if decision["action"] in blackjack_engine.VALID_PLAYER_ACTIONS
    ]

    if not player_actions:
        player_actions = [
            blackjack_engine.basic_strategy(
                player_cards,
                dealer_cards[0],
                can_double=True,
                can_split=blackjack_engine.can_split(player_cards),
            )
        ]

    round_state = blackjack_engine.run_blackjack_round(
        player_cards[:2],
        dealer_cards[0],
        blackjack_engine.card_from_code(dealer_hole),
        player_actions,
        player_draw_cards=cards_from_codes(player_draws),
        dealer_draw_cards=cards_from_codes(dealer_draws),
    )
    summary = blackjack_engine.round_summary(round_state)
    summary["vision"] = {
        "table": table,
        "hand_decisions": hand_decisions,
        "player_actions": player_actions,
    }
    return summary


def print_round_events(summary):
    print("Etapas da rodada:")
    for index, event in enumerate(summary["events"], start=1):
        stage = event["stage"]
        prefix = f"  {index}. "

        if stage == "initial_deal":
            hands = event["player_hands"]
            print(
                prefix
                + "Distribuicao inicial: "
                + f"jogador={hands[0]['cards']} total={hands[0]['total']} "
                + f"dealer_aberta={event['dealer_upcard']}"
            )
        elif stage == "player_action":
            if not event["accepted"]:
                print(
                    prefix
                    + f"Acao do jogador rejeitada: {event['action']} "
                    + f"legais={event['legal_actions']}"
                )
                continue

            hand_index = event["hand_index"] + 1
            print(prefix + f"Jogador mao {hand_index}: acao={event['action']}")
            for hand_pos, hand in enumerate(event["player_hands"], start=1):
                print(
                    "     "
                    + f"mao {hand_pos}: cartas={hand['cards']} "
                    + f"total={hand['total']} status={hand['status']}"
                )
        elif stage == "dealer_reveal":
            print(
                prefix
                + "Dealer revela carta fechada: "
                + f"cartas={event['dealer_cards']} total={event['dealer_total']}"
            )
        elif stage == "dealer_action":
            if event["action"] == "hit":
                print(
                    prefix
                    + f"Dealer compra {event['card']} "
                    + f"total={event['dealer_total']}"
                )
            else:
                print(
                    prefix
                    + f"Dealer para total={event['dealer_total']} "
                    + f"status={event['dealer_status']}"
                )
        elif stage == "resolution":
            print(prefix + "Resolucao final:")
            for hand_pos, hand in enumerate(event["player_hands"], start=1):
                print(
                    "     "
                    + f"mao {hand_pos}: total={hand['total']} "
                    + f"status={hand['status']} resultado={hand['result']}"
                )


def print_round_summary(summary):
    print("Rodada local de blackjack")
    table = summary["vision"]["table"]
    print(f"Fonte das cartas iniciais: {table['image']}")
    print("Cartas iniciais do jogador:")
    for card in summary["vision"]["table"]["player_cards"]:
        print(f"  - {blackjack_engine.card_label(card)}")
    print("Carta aberta do dealer:")
    for card in summary["vision"]["table"]["dealer_cards"]:
        print(f"  - {blackjack_engine.card_label(card)}")
    print("Sinais de mao reconhecidos:")
    for decision in summary["vision"]["hand_decisions"]:
        print(
            "  - "
            f"{decision['image']}: dedos={decision['fingers']} "
            f"acao={decision['action']} sinal_robo={decision['robot_signal']}"
        )
    print_round_events(summary)
    print("Resultado:")
    print(
        "  Dealer: "
        f"{summary['dealer_cards']} total={summary['dealer_total']} "
        f"status={summary['dealer_status']}"
    )
    for index, hand in enumerate(summary["player_hands"], start=1):
        print(
            "  Mao "
            f"{index}: cartas={hand['cards']} total={hand['total']} "
            f"status={hand['status']} resultado={hand['result']}"
        )


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
    parser.add_argument(
        "--simulate-round",
        action="store_true",
        help="Executa uma rodada local sem robo usando imagem da mesa e sinais de mao.",
    )
    parser.add_argument(
        "--round-image",
        default="images/table_round_01_player_QS_5S_dealer_2H_3S.jpeg",
        help="Imagem da mesa usada em --simulate-round.",
    )
    parser.add_argument(
        "--player-card",
        action="append",
        default=None,
        help="Carta inicial do jogador para simulacao manual. Use exatamente 2 vezes, ex: --player-card 8H --player-card 8D.",
    )
    parser.add_argument(
        "--dealer-upcard",
        default=None,
        help="Carta aberta do dealer para simulacao manual, ex: 6S.",
    )
    parser.add_argument(
        "--hand-image",
        action="append",
        default=None,
        help="Imagem de sinal de mao usada em --simulate-round. Pode repetir.",
    )
    parser.add_argument(
        "--dealer-hole",
        default="3S",
        help="Carta fechada do dealer para simulacao local, ex: 3S.",
    )
    parser.add_argument(
        "--player-draw",
        action="append",
        default=None,
        help="Carta de compra do jogador para hit/double/split na simulacao.",
    )
    parser.add_argument(
        "--dealer-draw",
        action="append",
        default=None,
        help="Carta de compra do dealer na simulacao. Pode repetir.",
    )
    args = parser.parse_args()

    if args.simulate_round:
        hand_images = args.hand_image or ["Sinais/4Dedo1.jpg"]
        player_draws = args.player_draw or []
        dealer_draws = args.dealer_draw or ["KH", "6C"]
        summary = simulate_round_from_files(
            args.round_image,
            hand_images,
            args.dealer_hole,
            player_draws,
            dealer_draws,
            player_card_codes=args.player_card,
            dealer_upcard=args.dealer_upcard,
        )
        print_round_summary(summary)
        return

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
