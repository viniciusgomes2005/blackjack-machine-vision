import argparse
import time
from dataclasses import dataclass

from camera_utils import open_camera
from hand_sign_vision import analyze_hand_image


HAND_ACTIONS = {
    1: "hit",
    2: "split",
    3: "double",
    4: "stand",
    5: None,
}

ROBOT_SIGNAL_BY_ACTION = {
    "hit": "hit",
    "split": "splitAB",
    "double": "double",
    "stand": "stand",
}


@dataclass(frozen=True)
class HandDecision:
    fingers: int | None
    action: str | None
    robot_signal: str | None


def action_from_hand_count(fingers: int | None) -> str | None:
    """Converte dedos detectados na decisao de Blackjack."""
    return HAND_ACTIONS.get(fingers)


def robot_signal_from_action(action: str | None) -> str | None:
    """Converte uma acao logica no sinal Modbus atual do robo."""
    return ROBOT_SIGNAL_BY_ACTION.get(action)


def decision_from_hand_count(fingers: int | None) -> HandDecision:
    action = action_from_hand_count(fingers)
    return HandDecision(
        fingers=fingers,
        action=action,
        robot_signal=robot_signal_from_action(action),
    )


def format_decision(decision: HandDecision) -> str:
    fingers = decision.fingers if decision.fingers is not None else "vazio"
    action = decision.action if decision.action is not None else "vazio"
    robot_signal = decision.robot_signal if decision.robot_signal is not None else "-"
    return f"dedos={fingers} acao={action} sinal_robo={robot_signal}"


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
        send_repeats: bool = False,
    ) -> None:
        self.camera_index = camera_index
        self.hand_interval = hand_interval
        self.show = show
        self.send_robot = send_robot
        self.robot_hold = robot_hold
        self.send_repeats = send_repeats
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

            self._robot = RobotDirectClient()

        print("DealerBotMain rodando. Ctrl+C para sair.")
        print(f"Intervalo de leitura de mao: {self.hand_interval:.2f}s")
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
            return decision_from_hand_count(fingers), debug_img, mask

        fingers = analyze_hand_image(frame, debug=False)
        return decision_from_hand_count(fingers), None, None

    def _publish_decision(self, decision: HandDecision) -> None:
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] {format_decision(decision)}")

        if not self.send_robot or decision.robot_signal is None:
            return

        if (
            not self.send_repeats
            and self._last_sent_signal == decision.robot_signal
        ):
            return

        self._robot.pulse_signal(decision.robot_signal, hold=self.robot_hold)
        self._last_sent_signal = decision.robot_signal


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
        default=0.5,
        help="Tempo em segundos segurando cada sinal HI ao enviar ao robo.",
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
    return parser


def main() -> None:
    args = build_parser().parse_args()
    controller = DealerBotController(
        camera_index=args.camera,
        hand_interval=args.hand_interval,
        show=args.show,
        send_robot=args.send_robot,
        robot_hold=args.robot_hold,
        send_repeats=args.send_repeats,
    )
    controller.run(max_samples=args.max_samples)


if __name__ == "__main__":
    main()
