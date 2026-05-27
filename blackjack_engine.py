from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Iterable


ACTION_HIT = "hit"
ACTION_STAND = "stand"
ACTION_SPLIT = "split"
ACTION_DOUBLE = "double"
VALID_PLAYER_ACTIONS = {ACTION_HIT, ACTION_STAND, ACTION_SPLIT, ACTION_DOUBLE}

STATUS_ACTIVE = "active"
STATUS_STOOD = "stood"
STATUS_BUSTED = "busted"
STATUS_DOUBLED = "doubled"
STATUS_BLACKJACK = "blackjack"
STATUS_WAITING = "waiting"

RESULT_WIN = "win"
RESULT_LOSE = "lose"
RESULT_PUSH = "push"

MAX_SPLITS_PER_ROUND = 2


def _rank(card):
    if isinstance(card, str):
        return card.strip().upper()
    return card.get("rank", "unknown")


def rank_to_blackjack_value(rank):
    if rank == "A":
        return 11
    if rank in ["J", "Q", "K"]:
        return 10
    try:
        return int(rank)
    except (TypeError, ValueError):
        return 0


def make_card(rank, suit="unknown"):
    """Cria uma carta no mesmo formato usado pelos modulos de visao."""
    rank = str(rank).strip().upper()
    return {
        "rank": rank,
        "suit": suit,
        "blackjack_value": rank_to_blackjack_value(rank),
        "card_id": None,
        "status": "ok" if rank_to_blackjack_value(rank) else "unknown",
    }


def card_from_code(code):
    """Converte codigos como QS, 10H ou A em dicionario de carta."""
    suit_map = {
        "S": "spades",
        "H": "hearts",
        "C": "clubs",
        "D": "diamonds",
    }
    code = str(code).strip().upper()
    if not code:
        return make_card("unknown")

    suit = "unknown"
    if code[-1] in suit_map and len(code) > 1:
        suit = suit_map[code[-1]]
        rank = code[:-1]
    else:
        rank = code

    return make_card(rank, suit)


def card_label(card):
    rank = _rank(card)
    suit = card.get("suit", "unknown") if isinstance(card, dict) else "unknown"
    if suit and suit != "unknown":
        return f"{rank} of {suit}"
    return rank


def _copy_card(card):
    if isinstance(card, dict):
        copied = dict(card)
        copied.pop("debug", None)
        return copied
    return card_from_code(card)


def hand_value(cards):
    """Calcula valor da mao com As valendo 11 ou 1."""
    total = 0
    aces = 0

    for card in cards:
        rank = _rank(card)
        if rank == "A":
            total += 11
            aces += 1
        elif rank in ["J", "Q", "K"]:
            total += 10
        else:
            try:
                total += int(rank)
            except (TypeError, ValueError):
                total += 0

    while total > 21 and aces > 0:
        total -= 10
        aces -= 1

    return total


def is_bust(cards):
    return hand_value(cards) > 21


def is_blackjack(cards):
    return len(cards) == 2 and hand_value(cards) == 21


def can_split(cards):
    if len(cards) != 2:
        return False
    return _rank(cards[0]) == _rank(cards[1]) and _rank(cards[0]) != "unknown"


def _dealer_visible_value(dealer_upcard):
    if dealer_upcard is None:
        return 0
    return rank_to_blackjack_value(_rank(dealer_upcard))


def basic_strategy(player_cards, dealer_upcard, can_double=True, can_split=True):
    """Estrategia basica simplificada para demonstracao."""
    value = hand_value(player_cards)
    dealer_value = _dealer_visible_value(dealer_upcard)

    pair_can_split = len(player_cards) == 2 and _rank(player_cards[0]) == _rank(player_cards[1])

    if can_split and pair_can_split:
        rank = _rank(player_cards[0])
        if rank in ["A", "8"]:
            return "split"
        if rank == "10":
            return "stand"
        if rank in ["2", "3", "7"] and 2 <= dealer_value <= 6:
            return "split"

    if value <= 11:
        if can_double and 9 <= value <= 11:
            return "double"
        return "hit"

    if value >= 17:
        return "stand"

    if 12 <= value <= 16:
        if 2 <= dealer_value <= 6:
            return "stand"
        return "hit"

    return "hit"


def count_cards_hi_lo(seen_cards):
    """Contagem Hi-Lo: 2-6 +1, 7-9 0, 10-A -1."""
    count = 0
    for card in seen_cards:
        rank = _rank(card)
        if rank in ["2", "3", "4", "5", "6"]:
            count += 1
        elif rank in ["10", "J", "Q", "K", "A"]:
            count -= 1
    return count


def dealer_action(dealer_cards):
    if hand_value(dealer_cards) < 17:
        return "hit"
    return "stand"


@dataclass
class BlackjackHand:
    cards: list[dict]
    status: str = STATUS_ACTIVE
    doubled: bool = False
    from_split: bool = False
    result: str | None = None

    @property
    def total(self):
        return hand_value(self.cards)

    @property
    def is_active(self):
        return self.status == STATUS_ACTIVE

    @property
    def is_closed(self):
        return self.status != STATUS_ACTIVE

    @property
    def is_busted(self):
        return self.status == STATUS_BUSTED

    @property
    def is_natural_blackjack(self):
        return self.status == STATUS_BLACKJACK


@dataclass
class BlackjackRound:
    player_hands: list[BlackjackHand]
    dealer_cards: list[dict]
    dealer_hole_revealed: bool = False
    active_hand_index: int = 0
    split_count: int = 0
    dealer_status: str = STATUS_WAITING
    events: list[dict] = field(default_factory=list)

    @property
    def dealer_total(self):
        return hand_value(self.dealer_cards)

    @property
    def dealer_busted(self):
        return self.dealer_status == STATUS_BUSTED

    def current_hand(self):
        _advance_active_hand(self)
        if self.active_hand_index >= len(self.player_hands):
            return None
        return self.player_hands[self.active_hand_index]

    def all_player_hands_closed(self):
        return all(hand.is_closed for hand in self.player_hands)


def start_round(player_cards, dealer_upcard, dealer_hole_card=None):
    """
    Inicia a rodada na ordem exigida pelo documento:
    jogador, dealer aberto, jogador, dealer fechado.
    """
    if len(player_cards) != 2:
        raise ValueError("a rodada deve iniciar com exatamente 2 cartas do jogador")
    if dealer_upcard is None:
        raise ValueError("a rodada precisa da carta aberta do dealer")

    player_hand = BlackjackHand(cards=[_copy_card(card) for card in player_cards])
    if is_blackjack(player_hand.cards):
        player_hand.status = STATUS_BLACKJACK

    dealer_cards = [_copy_card(dealer_upcard)]
    dealer_hole_revealed = dealer_hole_card is None
    if dealer_hole_card is not None:
        dealer_cards.append(_copy_card(dealer_hole_card))

    round_state = BlackjackRound(
        player_hands=[player_hand],
        dealer_cards=dealer_cards,
        dealer_hole_revealed=dealer_hole_revealed,
    )
    round_state.events.append(
        {
            "stage": "initial_deal",
            "player_hands": [_hand_snapshot(player_hand)],
            "dealer_upcard": card_label(dealer_cards[0]),
            "dealer_hole_known": dealer_hole_card is not None,
        }
    )
    _advance_active_hand(round_state)
    return round_state


def _hand_snapshot(hand):
    return {
        "cards": [card_label(card) for card in hand.cards],
        "total": hand.total,
        "status": hand.status,
        "doubled": hand.doubled,
        "from_split": hand.from_split,
        "result": hand.result,
    }


def _advance_active_hand(round_state):
    while (
        round_state.active_hand_index < len(round_state.player_hands)
        and round_state.player_hands[round_state.active_hand_index].is_closed
    ):
        round_state.active_hand_index += 1


def _draw(draw_card: Callable[[], dict] | None):
    if draw_card is None:
        raise ValueError("esta acao precisa de uma carta de compra")
    card = draw_card()
    if card is None:
        raise ValueError("draw_card retornou None")
    return _copy_card(card)


def _mark_bust_if_needed(hand):
    if is_bust(hand.cards):
        hand.status = STATUS_BUSTED


def legal_player_actions(round_state):
    hand = round_state.current_hand()
    if hand is None or not hand.is_active:
        return []

    actions = [ACTION_HIT, ACTION_STAND]
    if len(hand.cards) == 2:
        actions.append(ACTION_DOUBLE)
    if (
        len(hand.cards) == 2
        and can_split(hand.cards)
        and round_state.split_count < MAX_SPLITS_PER_ROUND
    ):
        actions.append(ACTION_SPLIT)
    return actions


def apply_player_action(round_state, action, draw_card: Callable[[], dict] | None = None):
    """
    Aplica uma acao externa. Acoes ilegais sao rejeitadas sem alterar a mao.
    Retorna True quando a acao foi aceita e False quando foi rejeitada.
    """
    action = str(action).strip().lower()
    hand = round_state.current_hand()
    legal_actions = legal_player_actions(round_state)

    if hand is None or action not in legal_actions:
        round_state.events.append(
            {
                "stage": "player_action",
                "action": action,
                "accepted": False,
                "hand_index": round_state.active_hand_index,
                "legal_actions": legal_actions,
            }
        )
        return False

    hand_index = round_state.active_hand_index

    if action == ACTION_HIT:
        hand.cards.append(_draw(draw_card))
        _mark_bust_if_needed(hand)
    elif action == ACTION_STAND:
        hand.status = STATUS_STOOD
    elif action == ACTION_DOUBLE:
        hand.cards.append(_draw(draw_card))
        hand.doubled = True
        hand.status = STATUS_BUSTED if is_bust(hand.cards) else STATUS_DOUBLED
    elif action == ACTION_SPLIT:
        first_card, second_card = hand.cards
        left_hand = BlackjackHand(
            cards=[_copy_card(first_card), _draw(draw_card)],
            from_split=True,
        )
        right_hand = BlackjackHand(
            cards=[_copy_card(second_card), _draw(draw_card)],
            from_split=True,
        )
        _mark_bust_if_needed(left_hand)
        _mark_bust_if_needed(right_hand)
        round_state.player_hands[hand_index:hand_index + 1] = [left_hand, right_hand]
        round_state.split_count += 1
    else:
        raise ValueError(f"acao desconhecida: {action}")

    round_state.events.append(
        {
            "stage": "player_action",
            "action": action,
            "accepted": True,
            "hand_index": hand_index,
            "player_hands": [_hand_snapshot(hand) for hand in round_state.player_hands],
        }
    )
    _advance_active_hand(round_state)
    return True


def play_player_turn(round_state, actions: Iterable[str], draw_cards=()):
    actions_iter = iter(actions)
    draw_queue = deque(_copy_card(card) for card in draw_cards)

    def draw_from_queue():
        if not draw_queue:
            raise RuntimeError("faltaram cartas para concluir o turno do jogador")
        return draw_queue.popleft()

    while round_state.current_hand() is not None:
        try:
            action = next(actions_iter)
        except StopIteration as exc:
            raise RuntimeError("faltaram acoes para concluir o turno do jogador") from exc
        apply_player_action(round_state, action, draw_from_queue)

    return round_state


def reveal_dealer_hole(round_state):
    if not round_state.dealer_hole_revealed:
        round_state.dealer_hole_revealed = True
        round_state.events.append(
            {
                "stage": "dealer_reveal",
                "dealer_cards": [card_label(card) for card in round_state.dealer_cards],
                "dealer_total": round_state.dealer_total,
            }
        )


def play_dealer_turn(round_state, draw_cards=()):
    draw_queue = deque(_copy_card(card) for card in draw_cards)
    reveal_dealer_hole(round_state)

    while dealer_action(round_state.dealer_cards) == ACTION_HIT:
        if not draw_queue:
            raise RuntimeError("faltaram cartas para concluir o turno do dealer")
        card = draw_queue.popleft()
        round_state.dealer_cards.append(card)
        round_state.events.append(
            {
                "stage": "dealer_action",
                "action": ACTION_HIT,
                "card": card_label(card),
                "dealer_total": round_state.dealer_total,
            }
        )

    round_state.dealer_status = (
        STATUS_BUSTED if is_bust(round_state.dealer_cards) else STATUS_STOOD
    )
    round_state.events.append(
        {
            "stage": "dealer_action",
            "action": ACTION_STAND,
            "dealer_total": round_state.dealer_total,
            "dealer_status": round_state.dealer_status,
        }
    )
    return round_state


def resolve_round(round_state):
    dealer_total = round_state.dealer_total
    dealer_busted = round_state.dealer_busted

    for hand in round_state.player_hands:
        if hand.is_busted:
            hand.result = RESULT_LOSE
        elif dealer_busted:
            hand.result = RESULT_WIN
        elif hand.total > dealer_total:
            hand.result = RESULT_WIN
        elif hand.total < dealer_total:
            hand.result = RESULT_LOSE
        else:
            hand.result = RESULT_PUSH

    round_state.events.append(
        {
            "stage": "resolution",
            "dealer_total": dealer_total,
            "dealer_status": round_state.dealer_status,
            "player_hands": [_hand_snapshot(hand) for hand in round_state.player_hands],
        }
    )
    return round_state


def run_blackjack_round(
    player_cards,
    dealer_upcard,
    dealer_hole_card,
    player_actions,
    player_draw_cards=(),
    dealer_draw_cards=(),
):
    round_state = start_round(player_cards, dealer_upcard, dealer_hole_card)
    play_player_turn(round_state, player_actions, player_draw_cards)
    play_dealer_turn(round_state, dealer_draw_cards)
    resolve_round(round_state)
    return round_state


def round_summary(round_state):
    return {
        "player_hands": [_hand_snapshot(hand) for hand in round_state.player_hands],
        "dealer_cards": [card_label(card) for card in round_state.dealer_cards],
        "dealer_total": round_state.dealer_total,
        "dealer_status": round_state.dealer_status,
        "dealer_hole_revealed": round_state.dealer_hole_revealed,
        "split_count": round_state.split_count,
        "events": list(round_state.events),
    }
