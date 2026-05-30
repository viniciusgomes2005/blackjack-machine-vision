from robot_round_orchestrator import RobotRoundOrchestrator, build_parser
import blackjack_engine as bj
import hand_sign_vision


class FakeOutputReader:
    def __init__(self, busy_values):
        self.busy_values = list(busy_values)
        self.reads = 0

    def read_outputs(self, **_kwargs):
        self.reads += 1
        busy = self.busy_values.pop(0) if self.busy_values else False
        return type("Outputs", (), {"foto": False, "busyIO": busy, "source": "coils"})()


def test_dry_run_robot_argument_is_available():
    args = build_parser().parse_args(["--dry-run-robot", "--gesture-test"])

    assert args.dry_run_robot is True
    assert args.gesture_test is True


def test_robot_output_defaults_match_confirmed_ur_coil_mapping():
    args = build_parser().parse_args([])

    assert args.pc_output_server is False
    assert args.output_source == "coils"
    assert args.foto_coil == 17
    assert args.busyio_coil == 18


def test_pc_output_server_is_explicit_opt_in():
    args = build_parser().parse_args(["--pc-output-server"])

    assert args.pc_output_server is True


def test_foto_delay_argument_is_available():
    args = build_parser().parse_args(["--foto-delay", "0.35"])

    assert args.foto_delay == 0.35


def test_foto_delay_defaults_to_confirmed_robot_timing():
    args = build_parser().parse_args([])

    assert args.foto_delay == 0.8


def test_precise_hand_vision_is_default():
    args = build_parser().parse_args([])

    assert args.fast_hand_vision is False


def test_fast_hand_vision_can_be_enabled_for_quicker_startup():
    args = build_parser().parse_args(["--fast-hand-vision"])

    assert args.fast_hand_vision is True


def test_configure_fast_hand_vision_disables_heavy_detectors(monkeypatch):
    orchestrator = RobotRoundOrchestrator(dry_run_robot=True, fast_hand_vision=True)
    monkeypatch.setattr(hand_sign_vision, "USE_HAND_SKELETON_DETECTOR", True)
    monkeypatch.setattr(hand_sign_vision, "USE_HAND_DATASET_CLASSIFIER", True)

    orchestrator._configure_hand_vision()

    assert hand_sign_vision.USE_HAND_SKELETON_DETECTOR is False
    assert hand_sign_vision.USE_HAND_DATASET_CLASSIFIER is False


def test_natural_stand_hold_argument_defaults_to_long_pulse():
    args = build_parser().parse_args([])

    assert args.natural_stand_hold == 4.0


def test_natural_stand_idle_timeout_defaults_to_wait_for_robot_idle():
    args = build_parser().parse_args([])

    assert args.natural_stand_idle_timeout == 20.0


def test_dealer_action_idle_timeout_defaults_to_short_wait():
    args = build_parser().parse_args([])

    assert args.dealer_action_idle_timeout == 0.0


def test_dry_run_robot_does_not_create_modbus_client():
    orchestrator = RobotRoundOrchestrator(dry_run_robot=True)

    assert orchestrator._robot is None
    orchestrator._pulse("startprog", hold=0.01)
    orchestrator.close()


def test_finished_round_accepts_startprog_without_restarting_orchestrator():
    orchestrator = RobotRoundOrchestrator(dry_run_robot=True)
    pulses = []
    orchestrator._pulse = lambda signal, hold: pulses.append(signal)
    orchestrator.phase = "finished"
    orchestrator.round_state = bj.start_round(
        [bj.card_from_code("10H"), bj.card_from_code("7D")],
        bj.card_from_code("6S"),
    )
    orchestrator.initial_cards.player_cards = [bj.card_from_code("10H")]

    orchestrator._start_round_from_gesture()

    assert pulses == ["startprog"]
    assert orchestrator.phase == "initial_deal"
    assert orchestrator.round_state is None
    assert orchestrator.initial_cards.player_cards == []


def test_startprog_pulses_without_busy_confirmation():
    orchestrator = RobotRoundOrchestrator(dry_run_robot=True)
    pulses = []
    orchestrator._pulse = lambda signal, hold: pulses.append((signal, hold))

    orchestrator._start_round_from_gesture()

    assert pulses == [("startprog", 0.5)]
    assert orchestrator.phase == "initial_deal"


def test_finished_phase_maps_four_fingers_to_startprog():
    orchestrator = RobotRoundOrchestrator(dry_run_robot=True)
    orchestrator.phase = "finished"

    assert orchestrator._action_from_fingers(4) == "startprog"
    assert orchestrator._action_from_fingers(5) is None


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


def test_split_updates_physical_hands_immediately_and_assigns_draws():
    orchestrator = RobotRoundOrchestrator(dry_run_robot=True)
    orchestrator.round_state = bj.start_round(
        [bj.card_from_code("8H"), bj.card_from_code("8D")],
        bj.card_from_code("6S"),
    )
    orchestrator.phase = "player_turn"

    orchestrator.handle_player_action("split")
    assert orchestrator._pending_player_action == "split"
    assert orchestrator._pending_player_draws_needed == 2
    assert orchestrator.round_state.split_count == 1
    assert orchestrator.physical_hands_snapshot()["A"] == ["8 of hearts"]
    assert orchestrator.physical_hands_snapshot()["B"] == ["8 of diamonds"]

    orchestrator._add_player_action_card(bj.card_from_code("3C"))
    assert orchestrator.physical_hands_snapshot()["A"] == ["8 of hearts", "3 of clubs"]
    assert orchestrator.physical_hands_snapshot()["B"] == ["8 of diamonds"]

    orchestrator._add_player_action_card(bj.card_from_code("4C"))

    assert orchestrator.physical_hands_snapshot()["A"] == ["8 of hearts", "3 of clubs"]
    assert orchestrator.physical_hands_snapshot()["B"] == ["8 of diamonds", "4 of clubs"]


def test_second_split_of_hand_a_uses_ac_and_preserves_physical_labels():
    orchestrator = RobotRoundOrchestrator(dry_run_robot=True)
    pulses = []
    orchestrator._pulse = lambda signal, hold: pulses.append(signal)
    orchestrator.round_state = bj.start_round(
        [bj.card_from_code("8H"), bj.card_from_code("8D")],
        bj.card_from_code("6S"),
    )
    orchestrator.phase = "player_turn"

    orchestrator.handle_player_action("split")
    orchestrator._add_player_action_card(bj.card_from_code("8C"))
    orchestrator._add_player_action_card(bj.card_from_code("5C"))

    orchestrator.handle_player_action("split")
    orchestrator._add_player_action_card(bj.card_from_code("2C"))
    orchestrator._add_player_action_card(bj.card_from_code("3C"))

    assert pulses == ["splitAB", "splitAC"]
    assert orchestrator.round_state.split_count == 2
    assert orchestrator.physical_hands_snapshot()["A"] == ["8 of hearts", "2 of clubs"]
    assert orchestrator.physical_hands_snapshot()["B"] == ["8 of diamonds", "5 of clubs"]
    assert orchestrator.physical_hands_snapshot()["C"] == ["8 of clubs", "3 of clubs"]


def test_second_split_of_hand_b_uses_bc_and_third_split_is_ignored():
    orchestrator = RobotRoundOrchestrator(dry_run_robot=True)
    pulses = []
    orchestrator._pulse = lambda signal, hold: pulses.append(signal)
    orchestrator.round_state = bj.start_round(
        [bj.card_from_code("8H"), bj.card_from_code("8D")],
        bj.card_from_code("6S"),
    )
    orchestrator.phase = "player_turn"

    orchestrator.handle_player_action("split")
    orchestrator._add_player_action_card(bj.card_from_code("5C"))
    orchestrator._add_player_action_card(bj.card_from_code("8C"))
    orchestrator.handle_player_action("stand")
    orchestrator.handle_player_action("split")
    orchestrator._add_player_action_card(bj.card_from_code("2C"))
    orchestrator._add_player_action_card(bj.card_from_code("8S"))

    orchestrator.handle_player_action("split")

    assert pulses == ["splitAB", "stand", "splitBC"]
    assert orchestrator.round_state.split_count == 2
    assert orchestrator.physical_hands_snapshot()["A"] == ["8 of hearts", "5 of clubs"]
    assert orchestrator.physical_hands_snapshot()["B"] == ["8 of diamonds", "2 of clubs"]
    assert orchestrator.physical_hands_snapshot()["C"] == ["8 of clubs", "8 of spades"]
    assert orchestrator._pending_player_action is None


def test_player_gesture_waits_until_robot_is_idle_before_pulse(monkeypatch):
    orchestrator = RobotRoundOrchestrator(dry_run_robot=True)
    orchestrator._output_reader = FakeOutputReader([True, True, False])
    pulses = []
    sleeps = []
    orchestrator._pulse = lambda signal, hold: pulses.append(signal)
    orchestrator.round_state = bj.start_round(
        [bj.card_from_code("8H"), bj.card_from_code("8D")],
        bj.card_from_code("6S"),
    )
    orchestrator.phase = "player_turn"

    monkeypatch.setattr("robot_round_orchestrator.time.sleep", lambda value: sleeps.append(value))

    orchestrator.handle_player_action("split")

    assert pulses == ["splitAB"]
    assert orchestrator._output_reader.reads == 3
    assert len(sleeps) == 2


def test_player_bust_sends_auto_stand_after_robot_is_idle(monkeypatch):
    orchestrator = RobotRoundOrchestrator(dry_run_robot=True)
    orchestrator._output_reader = FakeOutputReader([False, True, False, True, False])
    pulses = []
    sleeps = []
    orchestrator._pulse = lambda signal, hold: pulses.append(signal)
    orchestrator.round_state = bj.start_round(
        [bj.card_from_code("10H"), bj.card_from_code("9D")],
        bj.card_from_code("6S"),
    )
    orchestrator.round_state.dealer_hole_revealed = False
    orchestrator.phase = "player_turn"

    monkeypatch.setattr("robot_round_orchestrator.time.sleep", lambda value: sleeps.append(value))

    orchestrator.handle_player_action("hit")
    orchestrator._add_player_action_card(bj.card_from_code("5C"))

    assert pulses == ["hit", "stand"]
    assert orchestrator.round_state.player_hands[0].status == bj.STATUS_BUSTED
    assert orchestrator.phase == "dealer_turn"
    assert orchestrator._pending_dealer_card is True

    orchestrator._add_dealer_card(bj.card_from_code("10C"))

    assert pulses == ["hit", "stand", "stand"]
    assert orchestrator.phase == "finished"
    assert orchestrator.round_state.dealer_hole_revealed is True
    assert orchestrator.physical_hands_snapshot()["dealer"] == ["6 of spades", "10 of clubs"]
    assert orchestrator._output_reader.reads == 5
    assert len(sleeps) == 2


def test_player_21_sends_auto_stand_and_advances_after_robot_is_idle(monkeypatch):
    orchestrator = RobotRoundOrchestrator(dry_run_robot=True)
    orchestrator._output_reader = FakeOutputReader([False, True, False])
    pulses = []
    sleeps = []
    orchestrator._pulse = lambda signal, hold: pulses.append(signal)
    orchestrator.round_state = bj.start_round(
        [bj.card_from_code("10H"), bj.card_from_code("10D")],
        bj.card_from_code("6S"),
    )
    orchestrator.round_state.player_hands.append(
        bj.BlackjackHand(cards=[bj.card_from_code("8C"), bj.card_from_code("2C")])
    )
    orchestrator.phase = "player_turn"

    monkeypatch.setattr("robot_round_orchestrator.time.sleep", lambda value: sleeps.append(value))

    orchestrator.handle_player_action("hit")
    orchestrator._add_player_action_card(bj.card_from_code("AC"))

    assert pulses == ["hit", "stand"]
    assert orchestrator.round_state.player_hands[0].status == bj.STATUS_STOOD
    assert orchestrator.round_state.active_hand_index == 1
    assert orchestrator._output_reader.reads == 3
    assert len(sleeps) == 1


def test_last_player_stand_waits_for_dealer_hole_before_auto_dealer_hit():
    orchestrator = RobotRoundOrchestrator(dry_run_robot=True)
    pulses = []
    orchestrator._pulse = lambda signal, hold: pulses.append(signal)
    orchestrator.round_state = bj.start_round(
        [bj.card_from_code("10H"), bj.card_from_code("7D")],
        bj.card_from_code("5S"),
    )
    orchestrator.round_state.dealer_hole_revealed = False
    orchestrator.phase = "player_turn"

    orchestrator.handle_player_action("stand")

    assert pulses == ["stand"]
    assert orchestrator.phase == "dealer_turn"
    assert orchestrator._pending_dealer_card is True

    orchestrator._add_dealer_card(bj.card_from_code("3C"))

    assert pulses == ["stand", "hit"]
    assert orchestrator.round_state.dealer_hole_revealed is True
    assert orchestrator.physical_hands_snapshot()["dealer"] == ["5 of spades", "3 of clubs"]


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


def test_dealer_turn_keeps_hitting_until_17_when_player_has_no_natural_blackjack():
    orchestrator = RobotRoundOrchestrator(dry_run_robot=True)
    pulses = []
    orchestrator._pulse = lambda signal, hold: pulses.append((signal, hold, orchestrator.phase))
    orchestrator.round_state = bj.start_round(
        [bj.card_from_code("10H"), bj.card_from_code("7D")],
        bj.card_from_code("2S"),
    )

    orchestrator._enter_dealer_turn()

    assert pulses[-1][0] == "hit"
    assert orchestrator._pending_dealer_card is True

    orchestrator._add_dealer_card(bj.card_from_code("4C"))
    assert pulses[-1][0] == "hit"
    assert orchestrator._pending_dealer_card is True

    orchestrator._add_dealer_card(bj.card_from_code("9D"))
    assert pulses[-1][0] == "hit"
    assert orchestrator._pending_dealer_card is True

    orchestrator._add_dealer_card(bj.card_from_code("2D"))
    assert pulses[-1][0] == "stand"
    assert orchestrator.phase == "finished"
    assert orchestrator.round_state.dealer_total == 17
    assert orchestrator.round_state.dealer_status == bj.STATUS_STOOD


def test_dealer_bust_prints_player_won_and_resolves(capsys):
    orchestrator = RobotRoundOrchestrator(dry_run_robot=True)
    pulses = []
    orchestrator._pulse = lambda signal, hold: pulses.append((signal, hold, orchestrator.phase))
    orchestrator.round_state = bj.start_round(
        [bj.card_from_code("10H"), bj.card_from_code("7D")],
        bj.card_from_code("10S"),
    )

    orchestrator._enter_dealer_turn()
    orchestrator._add_dealer_card(bj.card_from_code("6C"))
    orchestrator._add_dealer_card(bj.card_from_code("10D"))

    output = capsys.readouterr().out
    assert "Jogador Venceu" in output
    assert orchestrator.phase == "finished"
    assert orchestrator.round_state.dealer_total == 26
    assert orchestrator.round_state.dealer_status == bj.STATUS_BUSTED
    assert orchestrator.round_state.player_hands[0].result == bj.RESULT_WIN
    assert pulses == [
        ("hit", orchestrator.action_hold, "dealer_turn"),
        ("hit", orchestrator.action_hold, "dealer_turn"),
        ("stand", orchestrator.stand_hold, "dealer_turn"),
    ]


def test_dealer_auto_action_waits_until_robot_is_idle(monkeypatch):
    orchestrator = RobotRoundOrchestrator(
        dry_run_robot=True,
        dealer_action_idle_timeout=5.0,
    )
    orchestrator._output_reader = FakeOutputReader([True, True, False])
    pulses = []
    orchestrator._pulse = lambda signal, hold: pulses.append((signal, hold, orchestrator.phase))
    orchestrator.round_state = bj.start_round(
        [bj.card_from_code("10H"), bj.card_from_code("7D")],
        bj.card_from_code("2S"),
    )
    now = iter(index * 0.2 for index in range(100))
    sleeps = []

    monkeypatch.setattr("robot_round_orchestrator.time.monotonic", lambda: next(now))
    monkeypatch.setattr("robot_round_orchestrator.time.sleep", lambda value: sleeps.append(value))

    orchestrator._enter_dealer_turn()

    assert pulses == [("hit", orchestrator.action_hold, "dealer_turn")]
    assert orchestrator._output_reader.reads == 3
    assert len(sleeps) == 2


def test_initial_blackjack_waits_for_dealer_reveal_before_resolution():
    orchestrator = RobotRoundOrchestrator(
        dry_run_robot=True,
        natural_stand_hold=1.2,
        natural_stand_idle_timeout=0.0,
    )
    pulses = []
    orchestrator._pulse = lambda signal, hold: pulses.append((signal, hold, orchestrator.phase))

    orchestrator._add_initial_card(bj.card_from_code("AH"))
    orchestrator._add_initial_card(bj.card_from_code("6S"))
    orchestrator._add_initial_card(bj.card_from_code("KH"))

    assert orchestrator.phase == "dealer_turn"
    assert orchestrator._pending_dealer_card is True
    assert orchestrator._natural_blackjack_reveal_pending is True
    assert orchestrator.round_state.player_hands[0].status == bj.STATUS_BLACKJACK
    assert pulses == [("stand", 1.2, "player_turn")]

    orchestrator._add_dealer_card(bj.card_from_code("AC"))

    assert pulses == [
        ("stand", 1.2, "player_turn"),
        ("stand", orchestrator.stand_hold, "dealer_turn"),
    ]
    assert orchestrator.phase == "finished"
    assert orchestrator.round_state.dealer_hole_revealed is True
    assert orchestrator.round_state.dealer_status == bj.STATUS_STOOD
    assert orchestrator.round_state.player_hands[0].result == bj.RESULT_WIN


def test_natural_blackjack_waits_for_busy_cycle_before_stand(monkeypatch):
    orchestrator = RobotRoundOrchestrator(
        dry_run_robot=True,
        natural_stand_idle_timeout=5.0,
    )
    orchestrator._output_reader = FakeOutputReader([True, True, False])
    now = iter(index * 0.2 for index in range(100))
    sleeps = []

    monkeypatch.setattr("robot_round_orchestrator.time.monotonic", lambda: next(now))
    monkeypatch.setattr("robot_round_orchestrator.time.sleep", lambda value: sleeps.append(value))

    orchestrator._wait_robot_idle_before_natural_stand()

    assert orchestrator._output_reader.reads == 3
    assert len(sleeps) == orchestrator._output_reader.reads - 1
