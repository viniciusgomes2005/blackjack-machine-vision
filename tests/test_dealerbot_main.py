from DealerBotMain import (
    action_from_hand_count,
    decision_from_hand_count,
    robot_signal_from_action,
)


def test_hand_count_to_action_mapping():
    assert action_from_hand_count(1) == "hit"
    assert action_from_hand_count(2) == "split"
    assert action_from_hand_count(3) == "double"
    assert action_from_hand_count(4) == "stand"
    assert action_from_hand_count(5) is None
    assert action_from_hand_count(None) is None


def test_action_to_robot_signal_mapping():
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
