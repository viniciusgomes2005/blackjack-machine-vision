from robot_round_orchestrator import RobotRoundOrchestrator, build_parser
import blackjack_engine as bj


def test_dry_run_robot_argument_is_available():
    args = build_parser().parse_args(["--dry-run-robot", "--gesture-test"])

    assert args.dry_run_robot is True
    assert args.gesture_test is True


def test_robot_output_defaults_match_confirmed_ur_coil_mapping():
    args = build_parser().parse_args([])

    assert args.pc_output_server is False
    assert args.output_source == "coils"
    assert args.foto_coil == 17


def test_pc_output_server_is_explicit_opt_in():
    args = build_parser().parse_args(["--pc-output-server"])

    assert args.pc_output_server is True


def test_foto_delay_argument_is_available():
    args = build_parser().parse_args(["--foto-delay", "0.35"])

    assert args.foto_delay == 0.35


def test_foto_delay_defaults_to_confirmed_robot_timing():
    args = build_parser().parse_args([])

    assert args.foto_delay == 0.8


def test_natural_stand_hold_argument_defaults_to_long_pulse():
    args = build_parser().parse_args([])

    assert args.natural_stand_hold == 1.0


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


def test_split_waits_two_cards_and_creates_physical_hands():
    orchestrator = RobotRoundOrchestrator(dry_run_robot=True)
    orchestrator.round_state = bj.start_round(
        [bj.card_from_code("8H"), bj.card_from_code("8D")],
        bj.card_from_code("6S"),
    )
    orchestrator.phase = "player_turn"

    orchestrator.handle_player_action("split")
    assert orchestrator._pending_player_action == "split"
    assert orchestrator._pending_player_draws_needed == 2

    orchestrator._add_player_action_card(bj.card_from_code("3C"))
    assert len(orchestrator.round_state.player_hands) == 1

    orchestrator._add_player_action_card(bj.card_from_code("4C"))

    assert orchestrator.physical_hands_snapshot()["A"] == ["8 of hearts", "3 of clubs"]
    assert orchestrator.physical_hands_snapshot()["B"] == ["8 of diamonds", "4 of clubs"]


def test_dealer_turn_forces_hit_below_17_then_resolves():
    orchestrator = RobotRoundOrchestrator(dry_run_robot=True)
    orchestrator.round_state = bj.start_round(
        [bj.card_from_code("10H"), bj.card_from_code("7D")],
        bj.card_from_code("6S"),
    )

    orchestrator._enter_dealer_turn()

    assert orchestrator.phase == "dealer_turn"
    assert orchestrator._pending_dealer_card is True

    orchestrator._add_dealer_card(bj.card_from_code("AC"))

    assert orchestrator.phase == "finished"
    assert orchestrator.round_state.dealer_status == bj.STATUS_STOOD
    assert orchestrator.physical_hands_snapshot()["dealer"] == ["6 of spades", "A of clubs"]


def test_initial_blackjack_waits_for_dealer_reveal_before_resolution():
    orchestrator = RobotRoundOrchestrator(dry_run_robot=True, natural_stand_hold=1.2)
    pulses = []
    orchestrator._pulse = lambda signal, hold: pulses.append((signal, hold))

    orchestrator._add_initial_card(bj.card_from_code("AH"))
    orchestrator._add_initial_card(bj.card_from_code("6S"))
    orchestrator._add_initial_card(bj.card_from_code("KH"))

    assert orchestrator.phase == "dealer_turn"
    assert orchestrator._pending_dealer_card is True
    assert orchestrator._natural_blackjack_reveal_pending is True
    assert orchestrator.round_state.player_hands[0].status == bj.STATUS_BLACKJACK
    assert pulses == [("stand", 1.2)]

    orchestrator._add_dealer_card(bj.card_from_code("10C"))

    assert orchestrator.phase == "finished"
    assert orchestrator.round_state.dealer_hole_revealed is True
    assert orchestrator.round_state.dealer_status == bj.STATUS_STOOD
    assert orchestrator.round_state.player_hands[0].result == bj.RESULT_WIN
