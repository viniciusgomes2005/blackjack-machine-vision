from ur_robot_bridge import DEFAULT_SIGNAL_ADDRESSES, RobotInputs


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
