from chip_vision import calculate_bet, create_chip_robot_orders, optimize_chips


def test_calculate_bet():
    chip_counts = {"yellow": 1, "green": 1, "blue": 2}
    chip_values = {"yellow": 25, "green": 50, "blue": 100}
    assert calculate_bet(chip_counts, chip_values) == 275


def test_optimize_chips_uses_larger_values_first():
    chip_values = {"yellow": 25, "green": 50, "blue": 100}
    assert optimize_chips(75, chip_values) == {"yellow": 1, "green": 1, "blue": 0}
    assert optimize_chips(150, chip_values) == {"yellow": 0, "green": 1, "blue": 1}


def test_create_chip_robot_orders_for_gambler():
    orders = create_chip_robot_orders(
        "gambler",
        {"yellow": 1, "green": 1, "blue": 0},
    )

    assert orders["Gambler_Amarelo"] is True
    assert orders["Gambler_Verde"] is True
    assert orders["Gambler_Azul"] is False
    assert orders["Gambler_Amarelo_Qtd"] == 1
    assert orders["Gambler_Verde_Qtd"] == 1
    assert orders["Gambler_Azul_Qtd"] == 0
