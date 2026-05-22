from main import choose_robot_orders


def test_hand_signs_map_to_blackjack_actions():
    assert choose_robot_orders(1, "stand", 0) == {
        "Pegar_Carta": True,
        "Soltar_Player": True,
    }
    assert choose_robot_orders(2, "stand", 0) == {"Split": True}
    assert choose_robot_orders(3, "stand", 0) == {
        "Gambler_Amarelo": False,
        "Gambler_Amarelo_Qtd": 0,
        "Gambler_Verde": False,
        "Gambler_Verde_Qtd": 0,
        "Gambler_Azul": False,
        "Gambler_Azul_Qtd": 0,
    }
    assert choose_robot_orders(4, "hit", 0) == {"Stand": True}
