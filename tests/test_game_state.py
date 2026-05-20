from game_state import GameState


def test_update_cards_replaces_current_hand_and_tracks_seen_cards_once():
    state = GameState()
    cards = [
        {"rank": "A", "suit": "spades", "card_id": 1},
        {"rank": "K", "suit": "diamonds", "card_id": 52},
    ]

    state.update_player_cards(cards)
    state.update_player_cards(cards)

    assert state.player_hands[0] == cards
    assert [card["card_id"] for card in state.seen_cards] == [1, 52]


def test_reset_round_keeps_seen_cards_memory():
    state = GameState()
    state.update_dealer_cards([{"rank": "5", "suit": "clubs", "card_id": 19}])

    state.reset_round()

    assert state.player_hands == [[]]
    assert state.dealer_hand == []
    assert [card["card_id"] for card in state.seen_cards] == [19]
