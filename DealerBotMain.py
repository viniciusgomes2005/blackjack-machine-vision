import argparse
import time
from dataclasses import dataclass

from camera_utils import open_camera
from hand_sign_vision import HandSignStabilizer, analyze_hand_image


PLAYER_HAND_ACTIONS = {
    1: "hit",
    2: "split",
    3: "double",
    5: "stand",
}
START_FINGERS = 4

ROBOT_SIGNAL_BY_ACTION = {
    "startprog": "startprog",
    "hit": "hit",
    "split": "splitAB",
    "double": "double",
    "stand": "stand",
}


@dataclass(frozen=True)
class HandDecision:
    fingers: int | None
    phase: str
    action: str | None
    robot_signal: str | None


def action_from_hand_count(
    fingers: int | None,
    phase: str = "player_turn",
) -> str | None:
    """Converte dedos detectados na decisao contextual do DealerBot."""
    if phase == "waiting_start":
        return "startprog" if fingers == START_FINGERS else None
    return PLAYER_HAND_ACTIONS.get(fingers)


def robot_signal_from_action(action: str | None) -> str | None:
    """Converte uma acao logica no sinal Modbus atual do robo."""
    return ROBOT_SIGNAL_BY_ACTION.get(action)


def split_signal_for_round(round_state) -> str | None:
    """
    Decide qual sinal fisico de split enviar para o UR.

    A fonte da verdade e o blackjack_engine: se "split" nao estiver entre as
    acoes legais, nao envia nada. Quando ha uma unica mao, o split cria A/B.
    Quando ja ha duas maos, a mao ativa define se a nova mao vai para C.
    """
    import blackjack_engine as bj

    if bj.ACTION_SPLIT not in bj.legal_player_actions(round_state):
        return None

    hand_count = len(round_state.player_hands)
    active_index = round_state.active_hand_index

    if hand_count == 1:
        return "splitAB"
    if hand_count == 2 and active_index == 0:
        return "splitAC"
    if hand_count == 2 and active_index == 1:
        return "splitBC"
    return None


def decision_from_hand_count(
    fingers: int | None,
    phase: str = "player_turn",
) -> HandDecision:
    action = action_from_hand_count(fingers, phase=phase)
    return HandDecision(
        fingers=fingers,
        phase=phase,
        action=action,
        robot_signal=robot_signal_from_action(action),
    )


def format_decision(decision: HandDecision) -> str:
    fingers = decision.fingers if decision.fingers is not None else "vazio"
    action = decision.action if decision.action is not None else "vazio"
    robot_signal = decision.robot_signal if decision.robot_signal is not None else "-"
    return (
        f"estado={decision.phase} dedos={fingers} "
        f"acao={action} sinal_robo={robot_signal}"
    )


class DealerBotController:
    """
    Orquestrador principal do DealerBot.

    Neste primeiro passo, ele observa sinais de mao em intervalos fixos e
    publica a decisao no terminal. Envio ao robo fica desligado por padrao.
    """

    def __init__(
        self,
        camera_index: int = 0,
        hand_interval: float = 5.0,
        show: bool = False,
        send_robot: bool = False,
        robot_hold: float = 0.5,
        start_hold: float = 0.5,
        stand_hold: float = 0.2,
        send_repeats: bool = False,
        ur_host: str | None = None,
        ur_port: int = 502,
        address_mode: str = "standard",
        write_target: str = "holding",
        stable_samples: int = 1,
    ) -> None:
        self.camera_index = camera_index
        self.hand_interval = hand_interval
        self.show = show
        self.send_robot = send_robot
        self.robot_hold = robot_hold
        self.start_hold = start_hold
        self.stand_hold = stand_hold
        self.send_repeats = send_repeats
        self.ur_host = ur_host
        self.ur_port = ur_port
        self.address_mode = address_mode
        self.write_target = write_target
        self.phase = "waiting_start"
        self._stabilizer = HandSignStabilizer(min_stable_frames=stable_samples)
        self._last_sent_signal: str | None = None
        self._robot = None

    def run(self, max_samples: int | None = None) -> None:
        import cv2

        cap = open_camera(self.camera_index)
        if cap is None:
            print(f"Erro: nao foi possivel usar a camera {self.camera_index}.")
            print("Tente outro indice com --camera N ou confira se a camera USB")
            print("esta liberando imagem no aplicativo Camera do Windows.")
            return

        if self.send_robot:
            from ur_robot_bridge import RobotDirectClient

            kwargs = {
                "ur_port": self.ur_port,
                "address_mode": self.address_mode,
                "write_target": self.write_target,
            }
            if self.ur_host is not None:
                kwargs["ur_host"] = self.ur_host
            self._robot = RobotDirectClient(**kwargs)

        print("DealerBotMain rodando. Ctrl+C para sair.")
        print(f"Intervalo de leitura de mao: {self.hand_interval:.2f}s")
        print("Fluxo: 4 dedos inicia; 1=hit, 2=split, 3=double, 5=stand")
        if self.send_robot:
            print("Envio ao robo: ligado")
        else:
            print("Envio ao robo: desligado; apenas imprimindo decisoes")

        samples = 0
        next_sample_at = 0.0

        try:
            while True:
                ok, frame = cap.read()
                if not ok or frame is None:
                    print("Falha ao capturar frame da camera.")
                    time.sleep(0.2)
                    continue

                now = time.monotonic()
                if now >= next_sample_at:
                    decision, debug_img, mask = self._analyze_frame(frame)
                    self._publish_decision(decision)
                    samples += 1
                    next_sample_at = now + self.hand_interval

                    if max_samples is not None and samples >= max_samples:
                        break

                if self.show:
                    if debug_img is not None:
                        cv2.imshow("DealerBotMain - mao", debug_img)
                    if mask is not None:
                        cv2.imshow("DealerBotMain - mascara", mask)
                    if cv2.waitKey(1) & 0xFF in {27, ord("q")}:
                        break
        except KeyboardInterrupt:
            print("Encerrando DealerBotMain.")
        finally:
            if self._robot is not None:
                self._robot.close()
            cap.release()
            if self.show:
                cv2.destroyAllWindows()

    def _analyze_frame(self, frame):
        if self.show:
            fingers, debug_img, mask = analyze_hand_image(frame, debug=True)
            stable_fingers = self._stable_fingers(fingers)
            return decision_from_hand_count(stable_fingers, self.phase), debug_img, mask

        fingers = analyze_hand_image(frame, debug=False)
        stable_fingers = self._stable_fingers(fingers)
        return decision_from_hand_count(stable_fingers, self.phase), None, None

    def _stable_fingers(self, fingers: int | None) -> int | None:
        raw = 0 if fingers is None else fingers
        stable = self._stabilizer.update(raw)
        return None if stable == 0 else stable

    def _publish_decision(self, decision: HandDecision) -> None:
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] {format_decision(decision)}")

        if decision.robot_signal is None:
            self._last_sent_signal = None
            return

        if not self.send_robot or decision.robot_signal is None:
            return

        if (
            not self.send_repeats
            and self._last_sent_signal == decision.robot_signal
        ):
            return

        self._robot.pulse_signal(
            decision.robot_signal,
            hold=self._hold_for_decision(decision),
        )
        self._last_sent_signal = decision.robot_signal

        if decision.action == "startprog":
            self.phase = "player_turn"

    def _hold_for_decision(self, decision: HandDecision) -> float:
        if decision.action == "startprog":
            return self.start_hold
        if decision.action == "stand":
            return self.stand_hold
        return self.robot_hold


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Script principal do DealerBot: camera, sinais de mao e robo."
    )
    parser.add_argument(
        "--camera",
        type=int,
        default=0,
        help="Indice da camera usada pelo OpenCV. Padrao: 0.",
    )
    parser.add_argument(
        "--hand-interval",
        type=float,
        default=5.0,
        help="Intervalo em segundos entre analises de sinal de mao. Padrao: 5.",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Mostra janelas de debug da area vermelha e mascara de pele.",
    )
    parser.add_argument(
        "--send-robot",
        action="store_true",
        help="Envia a acao detectada ao UR via ur_robot_bridge.py.",
    )
    parser.add_argument(
        "--robot-hold",
        type=float,
        default=0.3,
        help="Tempo em segundos segurando hit/split/double em HI.",
    )
    parser.add_argument(
        "--start-hold",
        type=float,
        default=0.5,
        help="Tempo em segundos segurando startprog em HI.",
    )
    parser.add_argument(
        "--stand-hold",
        type=float,
        default=0.2,
        help="Tempo em segundos segurando stand em HI.",
    )
    parser.add_argument(
        "--send-repeats",
        action="store_true",
        help="Envia tambem leituras repetidas da mesma acao.",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=None,
        help="Para automaticamente apos N leituras. Util para teste rapido.",
    )
    parser.add_argument("--ur-host", default=None, help="IP do controlador UR.")
    parser.add_argument("--ur-port", type=int, default=502, help="Porta Modbus do UR.")
    parser.add_argument(
        "--address-mode",
        choices=["standard", "legacy", "both"],
        default="standard",
        help="Mapa de enderecos usado no modo direto.",
    )
    parser.add_argument(
        "--write-target",
        choices=["holding", "coil", "both"],
        default="holding",
        help="Tipo de escrita Modbus usado no modo direto.",
    )
    parser.add_argument(
        "--stable-samples",
        type=int,
        default=1,
        help="Quantidade de leituras iguais exigidas antes de aceitar um gesto.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    controller = DealerBotController(
        camera_index=args.camera,
        hand_interval=args.hand_interval,
        show=args.show,
        send_robot=args.send_robot,
        robot_hold=args.robot_hold,
        start_hold=args.start_hold,
        stand_hold=args.stand_hold,
        send_repeats=args.send_repeats,
        ur_host=args.ur_host,
        ur_port=args.ur_port,
        address_mode=args.address_mode,
        write_target=args.write_target,
        stable_samples=args.stable_samples,
    )
    controller.run(max_samples=args.max_samples)


if __name__ == "__main__":
    main()
