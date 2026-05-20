from chip_vision import create_chip_robot_orders


def command_hit_player():
    return {
        "Pegar_Carta": True,
        "Soltar_Player": True,
    }


def command_hit_dealer():
    return {
        "Pegar_Carta": True,
        "Soltar_Dealer": True,
    }


def command_double_for_gambler(optimized_chips):
    return create_chip_robot_orders("gambler", optimized_chips)


def command_stand():
    return {
        "Stand": True,
    }


def command_split():
    return {
        "Split": True,
    }


def orders_from_action(action, double_chips=None):
    """Converte uma acao textual em comandos simples para o robo UR."""
    if action == "hit":
        return command_hit_player()
    if action == "stand":
        return command_stand()
    if action == "split":
        return command_split()
    if action == "double":
        return command_double_for_gambler(double_chips or {})
    return {}
