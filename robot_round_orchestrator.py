import argparse
import time
from dataclasses import dataclass, field
from pathlib import Path

import blackjack_engine as bj
from DealerBotMain import (
    action_from_hand_count,
    split_signal_for_round,
)
from camera_utils import open_camera
from hand_sign_vision import HandSignStabilizer, analyze_hand_image
from single_card_vision import process_image_as_card
from ur_robot_bridge import RobotDirectClient


PHASE_WAITING_START = "waiting_start"
PHASE_INITIAL_DEAL = "initial_deal"
PHASE_PLAYER_TURN = "player_turn"
PHASE_DEALER_TURN = "dealer_turn"
PHASE_FINISHED = "finished"

INITIAL_CARD_STEPS = (
    "player_first",
    "dealer_upcard",
    "player_second",
)


@dataclass
class PendingInitialCards:
    player_cards: list[dict] = field(default_factory=list)
    dealer_upcard: dict | None = None

    def ready(self) -> bool:
        return len(self.player_cards) == 2 and self.dealer_upcard is not None


class RobotRoundOrchestrator:
    """
    Orquestrador inicial para uma rodada real.

    Esta versao ainda usa captura manual por tecla para confirmar cada carta da
    rampa. O contrato central ja fica correto: cartas alimentam o
    blackjack_engine, gestos sao validados pelo motor, e split vira
    splitAB/splitAC/splitBC conforme a mao ativa.
    """

    def __init__(
        self,
        camera_index: int = 0,
        ur_host: str = "10.103.18.245",
        ur_port: int = 502,
        address_mode: str = "standard",
        write_target: str = "holding",
        hand_interval: float = 1.0,
        action_hold: float = 0.3,
        start_hold: float = 0.5,
        stand_hold: float = 0.2,
        stable_samples: int = 2,
        show: bool = False,
        dry_run_robot: bool = False,
        gesture_test: bool = False,
        gesture_resend_interval: float = 0.0,
    ) -> None:
        self.camera_index = camera_index
        self.hand_interval = hand_interval
        self.action_hold = action_hold
        self.start_hold = start_hold
        self.stand_hold = stand_hold
        self.show = show
        self.dry_run_robot = dry_run_robot
        self.gesture_test = gesture_test
        self.gesture_resend_interval = gesture_resend_interval
        self.phase = PHASE_WAITING_START
        self.initial_cards = PendingInitialCards()
        self.round_state: bj.BlackjackRound | None = None
        self._pending_player_action: str | None = None
        self._last_action: str | None = None
        self._last_action_at: float = 0.0
        self._latest_hand_debug_img = None
        self._latest_hand_mask = None
        self._stabilizer = HandSignStabilizer(min_stable_frames=stable_samples)
        self._robot = None
        if not dry_run_robot:
            self._robot = RobotDirectClient(
                ur_host=ur_host,
                ur_port=ur_port,
                address_mode=address_mode,
                write_target=write_target,
            )

    def close(self) -> None:
        if self._robot is not None:
            self._robot.close()

    def run(self) -> None:
        import cv2

        cap = open_camera(self.camera_index)
        if cap is None:
            print(f"Erro: nao foi possivel usar a camera {self.camera_index}.")
            return

        print("robot_round_orchestrator rodando. Ctrl+C para sair.")
        print("Gestos: 4=start, 1=hit, 2=split, 3=double, 5=stand.")
        print("Teclas: c=capturar carta da rampa, s=salvar debug mao, r=reset, q/ESC=sair.")
        if self.dry_run_robot:
            print("Robo: dry-run ligado; pulsos serao apenas impressos.")
        if self.gesture_test:
            print("Modo teste de gestos: sinais fisicos serao enviados sem validar a rodada.")

        next_hand_at = 0.0

        try:
            while True:
                ok, frame = cap.read()
                if not ok or frame is None:
                    print("Falha ao capturar frame da camera.")
                    time.sleep(0.2)
                    continue

                now = time.monotonic()
                if now >= next_hand_at:
                    self._handle_hand_frame(frame)
                    next_hand_at = now + self.hand_interval

                key = self._show_and_read_key(frame)
                if key in {27, ord("q")}:
                    break
                if key == ord("r"):
                    self.reset_round()
                if key == ord("c"):
                    self.capture_card_from_frame(frame)
                if key == ord("s"):
                    self.save_hand_debug_frame(frame)
        except KeyboardInterrupt:
            print("Encerrando orquestrador.")
        finally:
            cap.release()
            if self.show:
                cv2.destroyAllWindows()
            self.close()

    def reset_round(self) -> None:
        self.phase = PHASE_WAITING_START
        self.initial_cards = PendingInitialCards()
        self.round_state = None
        self._pending_player_action = None
        self._last_action = None
        self._last_action_at = 0.0
        self._stabilizer.reset()
        print("[round] reset; aguardando 4 dedos para startprog")

    def _show_and_read_key(self, frame) -> int:
        import cv2

        if not self.show:
            return cv2.waitKey(1) & 0xFF

        preview = frame.copy()
        status = self.phase
        if self._pending_player_action is not None:
            status = f"{status} aguardando_carta={self._pending_player_action}"
        cv2.putText(
            preview,
            f"estado={status}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.imshow("Robot Round Orchestrator", preview)
        if self._latest_hand_debug_img is not None:
            cv2.imshow("Robot Round Orchestrator - mao", self._latest_hand_debug_img)
        if self._latest_hand_mask is not None:
            cv2.imshow("Robot Round Orchestrator - mascara mao", self._latest_hand_mask)
        return cv2.waitKey(1) & 0xFF

    def save_hand_debug_frame(self, frame) -> None:
        import cv2

        output_dir = Path(__file__).resolve().parent / "debug_hand_sign" / "orchestrator_live"
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        frame_path = output_dir / f"{timestamp}_frame.jpg"
        cv2.imwrite(str(frame_path), frame)

        if self._latest_hand_debug_img is not None:
            cv2.imwrite(str(output_dir / f"{timestamp}_debug.png"), self._latest_hand_debug_img)
        if self._latest_hand_mask is not None:
            cv2.imwrite(str(output_dir / f"{timestamp}_mask.png"), self._latest_hand_mask)

        print(f"[debug] amostra de mao salva: {frame_path}")

    def _handle_hand_frame(self, frame) -> None:
        if self.show:
            fingers, debug_img, mask = analyze_hand_image(frame, debug=True)
            self._latest_hand_debug_img = debug_img
            self._latest_hand_mask = mask
        else:
            fingers = analyze_hand_image(frame)
        raw = 0 if fingers is None else fingers
        stable = self._stabilizer.update(raw)
        fingers = None if stable == 0 else stable

        action = self._action_from_fingers(fingers)
        print(
            f"[hand] estado={self.phase} leitura={raw if raw else 'vazio'} "
            f"estavel={fingers if fingers is not None else 'vazio'} "
            f"acao={action or 'vazio'}"
        )

        if action is None:
            self._last_action = None
            return
        if self._last_action == action:
            if self._should_resend_gesture_action():
                self._handle_gesture_test_action(action)
                self._last_action_at = time.monotonic()
                return
            print(f"[hand] acao repetida suprimida: {action}; mostre vazio para rearme")
            return

        if self.gesture_test:
            self._handle_gesture_test_action(action)
            self._last_action = action
            self._last_action_at = time.monotonic()
            return

        if self.phase == PHASE_WAITING_START and action == "startprog":
            self._pulse("startprog", self.start_hold)
            self.phase = PHASE_INITIAL_DEAL
            self._last_action = action
            self._last_action_at = time.monotonic()
            print("[round] startprog enviado; capture as cartas iniciais com tecla c")
            return

        if self.phase == PHASE_PLAYER_TURN:
            self.handle_player_action(action)
            self._last_action = action
            self._last_action_at = time.monotonic()
            return

        if self.phase == PHASE_INITIAL_DEAL:
            print("[round] acao reconhecida mas ignorada; capture as cartas iniciais com tecla c")
        else:
            print(f"[round] acao reconhecida mas ignorada no estado {self.phase}")
        self._last_action = action
        self._last_action_at = time.monotonic()

    def _should_resend_gesture_action(self) -> bool:
        return (
            self.gesture_test
            and self.gesture_resend_interval > 0
            and time.monotonic() - self._last_action_at >= self.gesture_resend_interval
        )

    def _action_from_fingers(self, fingers: int | None) -> str | None:
        if self.gesture_test and fingers != 4:
            return action_from_hand_count(fingers, phase=PHASE_PLAYER_TURN)
        return action_from_hand_count(fingers, phase=self.phase)

    def _handle_gesture_test_action(self, action: str) -> None:
        robot_signal = self._robot_signal_for_gesture_test(action)
        if robot_signal is None:
            print(f"[gesture-test] sem sinal fisico para {action}")
            return

        self._pulse(robot_signal, self._hold_for_action(action))
        if action == "startprog":
            self.phase = PHASE_INITIAL_DEAL
        print(f"[gesture-test] sinal enviado: {robot_signal}")

    def _robot_signal_for_gesture_test(self, action: str) -> str | None:
        if action == "split":
            return "splitAB"
        return action

    def capture_card_from_frame(self, frame) -> dict | None:
        card, _debug = process_image_as_card(frame)
        if card.get("status") != "ok":
            print("[card] carta nao reconhecida; ignorei a captura")
            return None

        print(f"[card] reconhecida: {bj.card_label(card)}")

        if self.phase == PHASE_INITIAL_DEAL:
            self._add_initial_card(card)
        elif self.phase == PHASE_PLAYER_TURN:
            self._add_player_action_card(card)
        elif self.phase == PHASE_DEALER_TURN:
            self._add_dealer_card(card)
        else:
            print(f"[card] captura ignorada no estado {self.phase}")

        return card

    def _add_initial_card(self, card: dict) -> None:
        step = INITIAL_CARD_STEPS[
            len(self.initial_cards.player_cards)
            + (1 if self.initial_cards.dealer_upcard is not None else 0)
        ]

        if step == "player_first":
            self.initial_cards.player_cards.append(card)
        elif step == "dealer_upcard":
            self.initial_cards.dealer_upcard = card
        elif step == "player_second":
            self.initial_cards.player_cards.append(card)

        print(f"[round] carta inicial registrada em {step}")

        if self.initial_cards.ready():
            self.round_state = bj.start_round(
                self.initial_cards.player_cards,
                self.initial_cards.dealer_upcard,
                dealer_hole_card=None,
            )
            self.phase = PHASE_PLAYER_TURN
            self._pending_player_action = None
            self._last_action = None
            print("[round] cartas iniciais completas; aguardando acao do jogador")
            self._print_round_state()

    def handle_player_action(self, action: str) -> None:
        if self._pending_player_action is not None:
            print(
                "[round] acao ignorada; aguardando carta para "
                f"{self._pending_player_action}. Pressione c quando a carta estiver na rampa"
            )
            return

        if self.round_state is None:
            print("[round] acao ignorada; round_state ainda nao existe")
            return

        legal = bj.legal_player_actions(self.round_state)
        if action not in legal:
            print(f"[round] acao ilegal ignorada: {action}; legais={legal}")
            return

        robot_signal = self._robot_signal_for_action(action)
        if robot_signal is None:
            print(f"[round] sem sinal fisico valido para {action}; nada enviado")
            return

        self._pulse(robot_signal, self._hold_for_action(action))

        if action in {"hit", "double", "split"}:
            self._pending_player_action = action
            print("[round] acao enviada; pressione c quando a carta estiver na rampa")
            return
        else:
            accepted = bj.apply_player_action(self.round_state, action)

        print(f"[round] acao aplicada={accepted}: {action}")
        self._print_round_state()

        if self.round_state.current_hand() is None:
            self.phase = PHASE_DEALER_TURN
            print("[round] maos do jogador encerradas; dealer_turn iniciado")

    def _add_player_action_card(self, card: dict) -> None:
        if self.round_state is None:
            print("[round] carta ignorada; round_state ainda nao existe")
            return
        if self._pending_player_action is None:
            print("[card] carta capturada durante player_turn, mas nenhuma acao aguardava carta")
            return

        action = self._pending_player_action
        self._pending_player_action = None
        accepted = bj.apply_player_action(self.round_state, action, lambda: card)
        print(f"[round] acao aplicada={accepted}: {action}")
        self._print_round_state()

        if self.round_state.current_hand() is None:
            self.phase = PHASE_DEALER_TURN
            print("[round] maos do jogador encerradas; dealer_turn iniciado")

    def _add_dealer_card(self, card: dict) -> None:
        if self.round_state is None:
            print("[dealer] round_state ausente")
            return
        self.round_state.dealer_cards.append(card)
        print(f"[dealer] carta adicionada: {bj.card_label(card)}")
        self._print_round_state()

    def _robot_signal_for_action(self, action: str) -> str | None:
        if action == "split":
            return split_signal_for_round(self.round_state)
        return action

    def _hold_for_action(self, action: str) -> float:
        if action == "startprog":
            return self.start_hold
        if action == "stand":
            return self.stand_hold
        return self.action_hold

    def _pulse(self, signal: str, hold: float) -> None:
        print(f"[robot] pulso {signal} hold={hold:.2f}s")
        if self._robot is None:
            return
        self._robot.pulse_signal(signal, hold=hold)

    def _print_round_state(self) -> None:
        if self.round_state is None:
            return
        summary = bj.round_summary(self.round_state)
        print(
            f"[round] ativa={self.round_state.active_hand_index} "
            f"splits={summary['split_count']} maos={summary['player_hands']} "
            f"dealer={summary['dealer_cards']}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Orquestrador inicial da rodada real DealerBot.")
    parser.add_argument("--camera", type=int, default=0, help="Indice da camera OpenCV.")
    parser.add_argument("--ur-host", default="10.103.18.245", help="IP do controlador UR.")
    parser.add_argument("--ur-port", type=int, default=502, help="Porta Modbus do UR.")
    parser.add_argument("--hand-interval", type=float, default=1.0, help="Intervalo de leitura da mao.")
    parser.add_argument("--action-hold", type=float, default=0.3, help="Hold de hit/split/double.")
    parser.add_argument("--start-hold", type=float, default=0.5, help="Hold de startprog.")
    parser.add_argument("--stand-hold", type=float, default=0.2, help="Hold de stand.")
    parser.add_argument("--stable-samples", type=int, default=2, help="Leituras iguais exigidas.")
    parser.add_argument(
        "--address-mode",
        choices=["standard", "legacy", "both"],
        default="standard",
        help="Mapa de enderecos Modbus.",
    )
    parser.add_argument(
        "--write-target",
        choices=["holding", "coil", "both"],
        default="holding",
        help="Tipo de escrita Modbus.",
    )
    parser.add_argument("--show", action="store_true", help="Mostra preview da camera.")
    parser.add_argument(
        "--dry-run-robot",
        action="store_true",
        help="Nao conecta no UR; apenas imprime os pulsos que seriam enviados.",
    )
    parser.add_argument(
        "--gesture-test",
        action="store_true",
        help="Pulsa sinais fisicos direto pelos gestos, sem validar estado da rodada.",
    )
    parser.add_argument(
        "--gesture-resend-interval",
        type=float,
        default=0.0,
        help="No modo --gesture-test, reenvia a mesma acao apos N segundos. 0 desliga.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    orchestrator = RobotRoundOrchestrator(
        camera_index=args.camera,
        ur_host=args.ur_host,
        ur_port=args.ur_port,
        address_mode=args.address_mode,
        write_target=args.write_target,
        hand_interval=args.hand_interval,
        action_hold=args.action_hold,
        start_hold=args.start_hold,
        stand_hold=args.stand_hold,
        stable_samples=args.stable_samples,
        show=args.show,
        dry_run_robot=args.dry_run_robot,
        gesture_test=args.gesture_test,
        gesture_resend_interval=args.gesture_resend_interval,
    )
    orchestrator.run()


if __name__ == "__main__":
    main()
