from ur_robot_bridge import (
    DEFAULT_SIGNAL_ADDRESSES,
    LEGACY_SIGNAL_ADDRESSES,
    RobotDirectClient,
    RobotInputs,
    _should_use_direct_mode,
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
