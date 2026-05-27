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
    assert bj.dealer_action([card("A"), card("6")]) == "stand"


def test_double_draws_one_card_and_closes_hand():
    round_state = bj.start_round([card("5"), card("5")], card("6"), card("10"))

    accepted = bj.apply_player_action(round_state, "double", lambda: card("9"))

    assert accepted is True
    assert round_state.player_hands[0].cards[-1]["rank"] == "9"
    assert round_state.player_hands[0].doubled is True
    assert round_state.player_hands[0].status == bj.STATUS_DOUBLED
    assert round_state.current_hand() is None


def test_illegal_action_is_rejected_without_mutating_hand():
    round_state = bj.start_round([card("10"), card("9")], card("6"), card("10"))
    before = bj.round_summary(round_state)["player_hands"]

    accepted = bj.apply_player_action(round_state, "split", lambda: card("2"))

    assert accepted is False
    assert bj.round_summary(round_state)["player_hands"] == before
    assert round_state.events[-1]["accepted"] is False


def test_split_creates_independent_hands_and_respects_max_two_splits():
    draw_cards = iter([card("8"), card("8"), card("8"), card("8")])
    round_state = bj.start_round([card("8"), card("8")], card("6"), card("10"))

    assert bj.apply_player_action(round_state, "split", lambda: next(draw_cards)) is True
    assert len(round_state.player_hands) == 2
    assert round_state.split_count == 1

    assert bj.apply_player_action(round_state, "split", lambda: next(draw_cards)) is True
    assert len(round_state.player_hands) == 3
    assert round_state.split_count == bj.MAX_SPLITS_PER_ROUND
    assert "split" not in bj.legal_player_actions(round_state)


def test_complete_round_resolves_each_player_hand_against_dealer():
    round_state = bj.run_blackjack_round(
        [card("Q"), card("5")],
        card("2"),
        card("3"),
        player_actions=["stand"],
        dealer_draw_cards=[card("K"), card("6")],
    )
    summary = bj.round_summary(round_state)

    assert summary["dealer_total"] == 21
    assert summary["dealer_status"] == bj.STATUS_STOOD
    assert summary["player_hands"] == [
        {
            "cards": ["Q", "5"],
            "total": 15,
            "status": bj.STATUS_STOOD,
            "doubled": False,
            "from_split": False,
            "result": bj.RESULT_LOSE,
        }
    ]
