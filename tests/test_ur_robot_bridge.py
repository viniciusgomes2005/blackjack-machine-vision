from ur_robot_bridge import (
    DEFAULT_SIGNAL_ADDRESSES,
    LEGACY_SIGNAL_ADDRESSES,
    RobotDirectClient,
    RobotInputs,
    _format_modbus_snapshot,
    _should_use_direct_mode,
    build_parser,
)


def test_robot_inputs_follow_dealerbot_register_order():
    inputs = RobotInputs(
        hit=True,
        splitAB=False,
        double=True,
        startprog=True,
        stand=False,
        splitBC=True,
        splitAC=False,
    )

    assert inputs.as_registers() == [1, 0, 1, 1, 0, 1, 0]


def test_signals_follow_ur_address_block_128_to_134():
    assert DEFAULT_SIGNAL_ADDRESSES == {
        "startprog": 128,
        "hit": 129,
        "double": 130,
        "stand": 131,
        "splitAB": 132,
        "splitBC": 133,
        "splitAC": 134,
    }


def test_legacy_signals_follow_ur_input_register_order_0_to_6():
    assert LEGACY_SIGNAL_ADDRESSES == {
        "hit": 0,
        "splitAB": 1,
        "double": 2,
        "startprog": 3,
        "stand": 4,
        "splitBC": 5,
        "splitAC": 6,
    }


def test_direct_client_writes_standard_address_map_by_default():
    client = RobotDirectClient.__new__(RobotDirectClient)
    client.address_mode = "standard"

    assert client._addresses_for_signal("stand") == [("standard", 131)]


def test_direct_client_can_write_both_address_maps_when_requested():
    client = RobotDirectClient.__new__(RobotDirectClient)
    client.address_mode = "both"

    assert client._addresses_for_signal("stand") == [
        ("standard", 131),
        ("legacy", 4),
    ]


def test_direct_client_read_outputs_falls_back_to_single_address_reads():
    class FakeClient:
        def read_coils(self, address, count):
            if count > 1:
                return None
            return [address == 17]

    client = RobotDirectClient.__new__(RobotDirectClient)
    client._client = FakeClient()

    outputs = client.read_outputs(foto_coil=17, busyio_coil=18, source="coils")

    assert outputs.foto is True
    assert outputs.busyIO is False
    assert outputs.source == "coils:single"


def test_one_shot_commands_default_to_direct_mode():
    class Args:
        direct_to_robot = False
        server_mode = False
        startprog = True
        command = None
        set = []
        diagnose_start = False

    assert _should_use_direct_mode(Args()) is True


def test_server_mode_keeps_legacy_pc_server_mode():
    class Args:
        direct_to_robot = False
        server_mode = True
        startprog = True
        command = None
        set = []
        diagnose_start = False

    assert _should_use_direct_mode(Args()) is False


def test_keep_high_argument_is_available_for_one_shot_commands():
    args = build_parser().parse_args(["--command", "stand", "--keep-high"])

    assert args.command == "stand"
    assert args.keep_high is True


def test_pc_output_diagnose_arguments_are_available():
    args = build_parser().parse_args(
        [
            "--diagnose-pc-outputs",
            "--pc-host",
            "0.0.0.0",
            "--pc-port",
            "31415",
            "--scan-start",
            "0",
            "--scan-count",
            "32",
            "--scan-poll",
            "0.1",
            "--scan-print-idle",
            "0",
        ]
    )

    assert args.diagnose_pc_outputs is True
    assert args.pc_host == "0.0.0.0"
    assert args.pc_port == 31415
    assert args.scan_start == 0
    assert args.scan_count == 32
    assert args.scan_poll == 0.1
    assert args.scan_print_idle == 0


def test_ur_output_diagnose_argument_is_available():
    args = build_parser().parse_args(["--diagnose-ur-outputs", "--scan-count", "64"])

    assert args.diagnose_ur_outputs is True
    assert args.scan_count == 64


def test_format_modbus_snapshot_shows_active_addresses_by_table():
    snapshot = {
        "coils": [False, True, False],
        "discrete_inputs": [False, False, False],
        "holding_registers": [0, 0, 1],
        "input_registers": None,
    }

    text = _format_modbus_snapshot(snapshot, start=16)

    assert "coils[17=1]" in text
    assert "discrete_inputs[all LO]" in text
    assert "holding_registers[18=1]" in text
    assert "input_registers[unavailable]" in text


def test_format_modbus_snapshot_accepts_sparse_address_map():
    snapshot = {
        "coils": {0: False, 17: True},
        "discrete_inputs": {},
        "holding_registers": {128: 1, 129: 0},
        "input_registers": None,
    }

    text = _format_modbus_snapshot(snapshot, start=0)

    assert "coils[17=1]" in text
    assert "discrete_inputs[all LO]" in text
    assert "holding_registers[128=1]" in text
