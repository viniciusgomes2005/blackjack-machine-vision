import blackjack_engine as bj


def card(rank):
    return {"rank": rank, "blackjack_value": 11 if rank == "A" else 10 if rank in ["J", "Q", "K"] else int(rank)}


def test_hand_value_handles_soft_aces():
    assert bj.hand_value([card("A"), card("9")]) == 20
    assert bj.hand_value([card("A"), card("9"), card("5")]) == 15


def test_bust_blackjack_and_split():
    assert bj.is_bust([card("10"), card("9"), card("5")]) is True
    assert bj.is_blackjack([card("A"), card("K")]) is True
    assert bj.can_split([card("8"), card("8")]) is True
    assert bj.can_split([card("8"), card("9")]) is False


def test_basic_strategy_simple_cases():
    assert bj.basic_strategy([card("8"), card("8")], card("6")) == "split"
    assert bj.basic_strategy([card("10"), card("7")], card("A")) == "stand"
    assert bj.basic_strategy([card("10"), card("2")], card("7")) == "hit"
    assert bj.basic_strategy([card("5"), card("5")], card("6")) == "double"


def test_hi_lo_and_dealer_action():
    seen = [card("2"), card("6"), card("7"), card("10"), card("A")]
    assert bj.count_cards_hi_lo(seen) == 0
    assert bj.dealer_action([card("10"), card("6")]) == "hit"
    assert bj.dealer_action([card("10"), card("7")]) == "stand"
