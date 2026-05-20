import cv2

from area_selector import crop_rois, draw_rois
from card_reader import CardReader
from chip_counter import ChipCounter, optimize_chips
from config import CHIP_VALUES
from hand_sign_reader import HandSignReader


def main():
    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("Nao foi possivel abrir a camera.")
        return

    card_reader = CardReader()
    chip_counter = ChipCounter()
    hand_reader = HandSignReader()

    # Aposta original: neste exemplo didatico, guardamos a primeira aposta
    # detectada maior que zero. Em um sistema real, ela pode vir do fluxo do jogo.
    original_bet = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Falha ao ler frame da camera.")
            break

        rois = crop_rois(frame)
        debug_frame = draw_rois(frame)

        player_cards, player_cards_debug, player_cards_threshold = card_reader.read_cards(
            rois["player_cards"], debug=True
        )
        dealer_cards, dealer_cards_debug, dealer_cards_threshold = card_reader.read_cards(
            rois["dealer_cards"], debug=True
        )

        detected_chips, current_bet, chips_debug, _ = chip_counter.count_chips(
            rois["player_chips"], debug=True
        )

        if original_bet == 0 and current_bet > 0:
            original_bet = current_bet

        handsign, split, hand_debug, hand_mask = hand_reader.read_hand_sign(
            rois["hand_sign"],
            original_bet=original_bet,
            current_bet=current_bet,
            debug=True,
        )

        optimized_chips = optimize_chips(current_bet, CHIP_VALUES)

        game_state = {
            "Handsign": handsign,
            "Split": split,
            "PlayerCards": player_cards,
            "DealerCards": dealer_cards,
            "BetTotal": current_bet,
            "OptimizedChips": optimized_chips,
            "DetectedChips": detected_chips,
        }

        # Estado textual no terminal para integracao futura com o robo UR.
        print(game_state)

        cv2.imshow("Mesa - ROIs", debug_frame)
        cv2.imshow("Player Cards", player_cards_debug)
        cv2.imshow("Dealer Cards", dealer_cards_debug)
        cv2.imshow("Player Cards Threshold", player_cards_threshold)
        cv2.imshow("Dealer Cards Threshold", dealer_cards_threshold)
        cv2.imshow("Chips", chips_debug)
        cv2.imshow("Hand Sign", hand_debug)

        if hand_mask is not None:
            cv2.imshow("Hand Skin Mask", hand_mask)

        key = cv2.waitKey(1) & 0xFF

        # Teclas simples para debug:
        # q: sair
        # r: recalibrar aposta original usando a aposta atual
        if key == ord("q"):
            break
        if key == ord("r"):
            original_bet = current_bet
            print(f"Aposta original recalibrada para: {original_bet}")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
