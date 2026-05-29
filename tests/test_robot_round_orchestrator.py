from robot_round_orchestrator import RobotRoundOrchestrator, build_parser
import blackjack_engine as bj


def test_dry_run_robot_argument_is_available():
    args = build_parser().parse_args(["--dry-run-robot", "--gesture-test"])

    assert args.dry_run_robot is True
    assert args.gesture_test is True


def test_dry_run_robot_does_not_create_modbus_client():
    orchestrator = RobotRoundOrchestrator(dry_run_robot=True)

    assert orchestrator._robot is None
    orchestrator._pulse("startprog", hold=0.01)
    orchestrator.close()


def test_gesture_test_maps_one_finger_to_hit_before_initial_cards():
    orchestrator = RobotRoundOrchestrator(dry_run_robot=True, gesture_test=True)

    assert orchestrator._action_from_fingers(1) == "hit"


def test_gesture_test_maps_split_to_first_physical_split_signal():
    orchestrator = RobotRoundOrchestrator(dry_run_robot=True, gesture_test=True)

    assert orchestrator._robot_signal_for_gesture_test("split") == "splitAB"


def test_gesture_test_can_resend_same_action_after_interval(monkeypatch):
    orchestrator = RobotRoundOrchestrator(
        dry_run_robot=True,
        gesture_test=True,
        gesture_resend_interval=1.0,
    )
    orchestrator._last_action = "hit"
    orchestrator._last_action_at = 10.0

    monkeypatch.setattr("robot_round_orchestrator.time.monotonic", lambda: 11.1)

    assert orchestrator._should_resend_gesture_action() is True


def test_hit_keeps_main_loop_alive_until_card_capture():
    orchestrator = RobotRoundOrchestrator(dry_run_robot=True)
    orchestrator.round_state = bj.start_round(
        [bj.card_from_code("9H"), bj.card_from_code("2D")],
        bj.card_from_code("6S"),
    )
    orchestrator.phase = "player_turn"

    orchestrator.handle_player_action("hit")

    assert orchestrator._pending_player_action == "hit"
    assert len(orchestrator.round_state.player_hands[0].cards) == 2

    orchestrator._add_player_action_card(bj.card_from_code("5C"))

    assert orchestrator._pending_player_action is None
    assert [card["rank"] for card in orchestrator.round_state.player_hands[0].cards] == [
        "9",
        "2",
        "5",
    ]
