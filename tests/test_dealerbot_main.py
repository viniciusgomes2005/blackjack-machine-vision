from DealerBotMain import (
    action_from_hand_count,
    decision_from_hand_count,
    robot_signal_from_action,
    split_signal_for_round,
)


def test_hand_count_to_action_mapping():
    assert action_from_hand_count(1) == "hit"
    assert action_from_hand_count(2) == "split"
    assert action_from_hand_count(3) == "double"
    assert action_from_hand_count(4) is None
    assert action_from_hand_count(5) == "stand"
    assert action_from_hand_count(None) is None


def test_start_phase_uses_four_fingers_for_startprog():
    assert action_from_hand_count(4, phase="waiting_start") == "startprog"
    assert action_from_hand_count(5, phase="waiting_start") is None


def test_action_to_robot_signal_mapping():
    assert robot_signal_from_action("startprog") == "startprog"
    assert robot_signal_from_action("hit") == "hit"
    assert robot_signal_from_action("split") == "splitAB"
    assert robot_signal_from_action("double") == "double"
    assert robot_signal_from_action("stand") == "stand"
    assert robot_signal_from_action(None) is None


def test_decision_carries_terminal_and_robot_values():
    decision = decision_from_hand_count(2)

    assert decision.fingers == 2
    assert decision.action == "split"
    assert decision.robot_signal == "splitAB"


def test_split_signal_uses_ab_for_first_split():
    import blackjack_engine as bj

    round_state = bj.start_round(
        [bj.card_from_code("8H"), bj.card_from_code("8D")],
        bj.card_from_code("6S"),
    )

    assert split_signal_for_round(round_state) == "splitAB"


def test_split_signal_uses_active_hand_for_second_split():
    import blackjack_engine as bj

    draw_cards = iter([bj.card_from_code("8C"), bj.card_from_code("9D")])
    round_state = bj.start_round(
        [bj.card_from_code("8H"), bj.card_from_code("8D")],
        bj.card_from_code("6S"),
    )
    assert bj.apply_player_action(round_state, "split", lambda: next(draw_cards))

    assert split_signal_for_round(round_state) == "splitAC"

    bj.apply_player_action(round_state, "stand")
    assert split_signal_for_round(round_state) is None

    round_state.player_hands[1].cards = [
        bj.card_from_code("8D"),
        bj.card_from_code("8S"),
    ]
    assert split_signal_for_round(round_state) == "splitBC"


def test_split_signal_returns_none_when_split_is_illegal():
    import blackjack_engine as bj

    round_state = bj.start_round(
        [bj.card_from_code("10H"), bj.card_from_code("8D")],
        bj.card_from_code("6S"),
    )

    assert split_signal_for_round(round_state) is None
