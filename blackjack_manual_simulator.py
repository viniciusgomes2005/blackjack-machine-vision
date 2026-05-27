import argparse
from collections import deque

import blackjack_engine as bj


def parse_card(code):
    card = bj.card_from_code(code)
    if card["blackjack_value"] == 0:
        raise ValueError(f"carta invalida: {code}")
    return card


def parse_cards(codes):
    return [parse_card(code) for code in codes]


def card_list_text(cards):
    return ", ".join(bj.card_label(card) for card in cards)


def print_hand(prefix, hand):
    print(
        f"{prefix}: cartas=[{card_list_text(hand.cards)}] "
        f"total={hand.total} status={hand.status}"
    )


def print_round_state(round_state):
    print()
    print("Estado atual")
    for index, hand in enumerate(round_state.player_hands, start=1):
        marker = " <- ativa" if index - 1 == round_state.active_hand_index and hand.is_active else ""
        print_hand(f"  Mao {index}{marker}", hand)

    dealer_cards = card_list_text(round_state.dealer_cards)
    print(
        f"  Dealer: cartas=[{dealer_cards}] "
        f"total={round_state.dealer_total} status={round_state.dealer_status}"
    )
    print(f"  Splits usados: {round_state.split_count}/{bj.MAX_SPLITS_PER_ROUND}")


def print_final_result(round_state):
    print()
    print("Resultado final")
    print(
        f"  Dealer: cartas=[{card_list_text(round_state.dealer_cards)}] "
        f"total={round_state.dealer_total} status={round_state.dealer_status}"
    )
    for index, hand in enumerate(round_state.player_hands, start=1):
        print(
            f"  Mao {index}: cartas=[{card_list_text(hand.cards)}] "
            f"total={hand.total} status={hand.status} resultado={hand.result}"
        )


def prompt_card(label):
    while True:
        raw = input(f"{label}: ").strip()
        try:
            return parse_card(raw)
        except ValueError as exc:
            print(f"Erro: {exc}")


def prompt_action(legal_actions):
    while True:
        raw = input(f"Acao {legal_actions}: ").strip().lower()
        if raw in {"q", "quit", "exit"}:
            raise KeyboardInterrupt
        if raw == "status":
            return "status"
        if raw:
            return raw


def next_scripted_item(queue, label):
    if not queue:
        raise RuntimeError(f"faltou informar {label}")
    return queue.popleft()


def make_player_drawer(player_draws, interactive):
    queue = deque(player_draws)

    def draw():
        if interactive:
            return prompt_card("Carta comprada pelo jogador")
        return next_scripted_item(queue, "--player-draw")

    return draw


def next_dealer_card(dealer_draws, interactive):
    if interactive:
        return prompt_card("Carta comprada pelo dealer")
    return next_scripted_item(dealer_draws, "--dealer-draw")


def play_player_loop(round_state, actions, player_draws, interactive):
    action_queue = deque(actions)
    draw_player_card = make_player_drawer(player_draws, interactive)

    while round_state.current_hand() is not None:
        hand_index = round_state.active_hand_index + 1
        legal_actions = bj.legal_player_actions(round_state)
        print_round_state(round_state)
        print(f"Turno do jogador - mao {hand_index}")
        print(f"Acoes legais: {', '.join(legal_actions)}")

        if interactive:
            action = prompt_action(legal_actions)
            if action == "status":
                continue
        else:
            action = next_scripted_item(action_queue, "--action")
            print(f"Acao recebida por argumento: {action}")

        accepted = bj.apply_player_action(round_state, action, draw_player_card)
        if accepted:
            print(f"Acao aceita: {action}")
        else:
            print(f"Acao rejeitada: {action}. A mao nao foi alterada.")


def play_dealer_loop(round_state, dealer_draws, interactive):
    dealer_draws = deque(dealer_draws)
    bj.reveal_dealer_hole(round_state)

    print()
    print(
        "Dealer revela carta fechada: "
        f"[{card_list_text(round_state.dealer_cards)}] "
        f"total={round_state.dealer_total}"
    )

    while bj.dealer_action(round_state.dealer_cards) == bj.ACTION_HIT:
        card = next_dealer_card(dealer_draws, interactive)
        round_state.dealer_cards.append(card)
        round_state.events.append(
            {
                "stage": "dealer_action",
                "action": bj.ACTION_HIT,
                "card": bj.card_label(card),
                "dealer_total": round_state.dealer_total,
            }
        )
        print(f"Dealer compra {bj.card_label(card)} -> total={round_state.dealer_total}")

    round_state.dealer_status = (
        bj.STATUS_BUSTED if bj.is_bust(round_state.dealer_cards) else bj.STATUS_STOOD
    )
    round_state.events.append(
        {
            "stage": "dealer_action",
            "action": bj.ACTION_STAND,
            "dealer_total": round_state.dealer_total,
            "dealer_status": round_state.dealer_status,
        }
    )
    print(f"Dealer para -> total={round_state.dealer_total} status={round_state.dealer_status}")


def run_manual_round(args):
    player_cards = parse_cards(args.player_card)
    dealer_upcard = parse_card(args.dealer_upcard)
    dealer_hole = parse_card(args.dealer_hole)
    player_draws = parse_cards(args.player_draw)
    dealer_draws = parse_cards(args.dealer_draw)

    round_state = bj.start_round(player_cards, dealer_upcard, dealer_hole)
    print("Simulador manual de Blackjack")
    print("Formato de carta: AH, 10D, QS, 8C. Naipe opcional: H, D, C, S.")

    play_player_loop(
        round_state,
        actions=args.action,
        player_draws=player_draws,
        interactive=args.interactive,
    )
    play_dealer_loop(round_state, dealer_draws, interactive=args.interactive)
    bj.resolve_round(round_state)
    print_final_result(round_state)
    return round_state


def build_parser():
    parser = argparse.ArgumentParser(
        description="Simulador manual de uma rodada de Blackjack sem camera e sem robo.",
        epilog=(
            "Exemplo: python blackjack_manual_simulator.py "
            "--player-card 8H --player-card 8D --dealer-upcard 6S "
            "--dealer-hole 10H --action split --action stand --action stand "
            "--player-draw 3H --player-draw 2C --dealer-draw 5C"
        ),
    )
    parser.add_argument(
        "--player-card",
        action="append",
        required=True,
        help="Carta inicial do jogador. Use exatamente 2 vezes.",
    )
    parser.add_argument(
        "--dealer-upcard",
        required=True,
        help="Carta aberta inicial do dealer.",
    )
    parser.add_argument(
        "--dealer-hole",
        required=True,
        help="Carta fechada inicial do dealer.",
    )
    parser.add_argument(
        "--action",
        action="append",
        default=[],
        choices=sorted(bj.VALID_PLAYER_ACTIONS),
        help="Acao do jogador em ordem. Use varias vezes no modo por argumento.",
    )
    parser.add_argument(
        "--player-draw",
        action="append",
        default=[],
        help="Cartas futuras compradas pelo jogador/splits, em ordem.",
    )
    parser.add_argument(
        "--dealer-draw",
        action="append",
        default=[],
        help="Cartas futuras compradas pelo dealer, em ordem.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Pede acoes e cartas futuras passo a passo pelo input().",
    )
    return parser


def main():
    args = build_parser().parse_args()
    if len(args.player_card) != 2:
        raise SystemExit("Erro: use --player-card exatamente 2 vezes.")
    if not args.interactive and not args.action:
        raise SystemExit("Erro: informe ao menos uma --action ou use --interactive.")

    try:
        run_manual_round(args)
    except KeyboardInterrupt:
        print()
        print("Simulacao interrompida.")
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(f"Erro: {exc}") from exc


if __name__ == "__main__":
    main()
