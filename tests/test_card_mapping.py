from card_vision import rank_suit_to_card_id, rank_to_blackjack_value


def test_rank_suit_to_card_id_uses_expected_order():
    assert rank_suit_to_card_id("A", "spades") == 1
    assert rank_suit_to_card_id("A", "hearts") == 2
    assert rank_suit_to_card_id("A", "clubs") == 3
    assert rank_suit_to_card_id("A", "diamonds") == 4
    assert rank_suit_to_card_id("2", "spades") == 5
    assert rank_suit_to_card_id("K", "diamonds") == 52


def test_rank_suit_to_card_id_unknown_returns_none():
    assert rank_suit_to_card_id("joker", "spades") is None
    assert rank_suit_to_card_id("A", "unknown") is None


def test_rank_to_blackjack_value():
    assert rank_to_blackjack_value("A") == 11
    assert rank_to_blackjack_value("10") == 10
    assert rank_to_blackjack_value("Q") == 10
    assert rank_to_blackjack_value("unknown") == 0
