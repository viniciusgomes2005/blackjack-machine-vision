def _rank(card):
    return card.get("rank", "unknown")


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
    return 11 if _rank(dealer_upcard) == "A" else dealer_upcard.get("blackjack_value", 0)


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
