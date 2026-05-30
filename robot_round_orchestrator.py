import argparse
import importlib.util
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import blackjack_engine as bj
import hand_sign_vision
from DealerBotMain import (
    action_from_hand_count,
    split_signal_for_round,
)
from camera_utils import open_camera
from hand_sign_vision import HandSignStabilizer, analyze_hand_image
from ur_robot_bridge import DEFAULT_BUSYIO_COIL, PcModbusOutputServer, RobotDirectClient


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

CARD_DETECTOR_PATH = Path(__file__).resolve().parent / "Camera_otimizado_CORRETO .py"


def _load_card_detector():
    spec = importlib.util.spec_from_file_location("camera_otimizado_correto", CARD_DETECTOR_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Nao foi possivel carregar detector de cartas: {CARD_DETECTOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CARD_DETECTOR = None


def _card_detector():
    global _CARD_DETECTOR
    if _CARD_DETECTOR is None:
        _CARD_DETECTOR = _load_card_detector()
    return _CARD_DETECTOR


def _rank_to_blackjack_value(rank: str) -> int:
    if rank == "A":
        return 11
    if rank in {"10", "J", "Q", "K"}:
        return 10
    try:
        return int(rank)
    except (TypeError, ValueError):
        return 0


def _recognized_value_to_card(value: object, debug: dict[str, object] | None = None) -> dict[str, object]:
    if value == "A":
        rank = "A"
    elif isinstance(value, int) and 2 <= value <= 10:
        rank = str(value)
    else:
        rank = "unknown"

    card = {
        "rank": rank,
        "suit": "unknown",
        "card_id": None,
        "blackjack_value": _rank_to_blackjack_value(rank),
        "rank_score": 1.0 if rank != "unknown" else 0.0,
        "suit_score": 0.0,
        "status": "ok" if rank != "unknown" else "unknown",
    }
    if debug is not None:
        card["debug"] = debug
    return card


def process_image_as_card(image) -> tuple[dict[str, object], dict[str, object]]:
    value, result = _card_detector().processar_imagem(image)
    return _recognized_value_to_card(value, result["analise"]), result


def _copy_card(card: dict) -> dict:
    copied = dict(card)
    copied.pop("debug", None)
    return copied


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
        pc_host: str = "0.0.0.0",
        pc_port: int = 31415,
        address_mode: str = "standard",
        write_target: str = "holding",
        hand_interval: float = 1.0,
        action_hold: float = 0.3,
        start_hold: float = 0.5,
        stand_hold: float = 0.2,
        natural_stand_hold: float = 4.0,
        natural_stand_idle_timeout: float = 20.0,
        dealer_action_idle_timeout: float = 0.0,
        stable_samples: int = 2,
        show: bool = False,
        dry_run_robot: bool = False,
        gesture_test: bool = False,
        gesture_resend_interval: float = 0.0,
        auto_foto: bool = True,
        foto_coil: int = 17,
        busyio_coil: int = DEFAULT_BUSYIO_COIL,
        output_source: str = "coils",
        pc_output_server: bool = False,
        foto_cooldown: float = 0.4,
        foto_delay: float = 0.8,
        fast_hand_vision: bool = False,
    ) -> None:
        self.camera_index = camera_index
        self.hand_interval = hand_interval
        self.action_hold = action_hold
        self.start_hold = start_hold
        self.stand_hold = stand_hold
        self.natural_stand_hold = natural_stand_hold
        self.natural_stand_idle_timeout = natural_stand_idle_timeout
        self.dealer_action_idle_timeout = dealer_action_idle_timeout
        self.show = show
        self.dry_run_robot = dry_run_robot
        self.gesture_test = gesture_test
        self.gesture_resend_interval = gesture_resend_interval
        self.auto_foto = auto_foto
        self.foto_coil = foto_coil
        self.busyio_coil = busyio_coil
        self.output_source = output_source
        self.pc_output_server = pc_output_server
        self.foto_cooldown = foto_cooldown
        self.foto_delay = foto_delay
        self.fast_hand_vision = fast_hand_vision
        self.phase = PHASE_WAITING_START
        self.initial_cards = PendingInitialCards()
        self.round_state: bj.BlackjackRound | None = None
        self._pending_player_action: str | None = None
        self._pending_player_draws: list[dict] = []
        self._pending_player_draws_needed = 0
        self._pending_split_draw_targets: list[int] = []
        self._pending_dealer_card = False
        self._natural_blackjack_reveal_pending = False
        self._player_bust_reveal_pending = False
        self._last_foto = False
        self._last_outputs_seen: tuple[bool, bool, str] | None = None
        self._last_foto_capture_at = 0.0
        self._last_action: str | None = None
        self._last_action_at: float = 0.0
        self._latest_hand_debug_img = None
        self._latest_hand_mask = None
        self._state_log_dir = Path(__file__).resolve().parent / "debug_hand_sign" / "orchestrator_live"
        self._events_log_path = self._state_log_dir / "orchestrator_events.jsonl"
        self._latest_event_path = self._state_log_dir / "latest_orchestrator_event.json"
        self._event_seq = 0
        self._stabilizer = HandSignStabilizer(min_stable_frames=stable_samples)
        self._robot = None
        self._output_reader = None
        if not dry_run_robot:
            self._robot = RobotDirectClient(
                ur_host=ur_host,
                ur_port=ur_port,
                address_mode=address_mode,
                write_target=write_target,
            )
            if pc_output_server:
                self._output_reader = PcModbusOutputServer(pc_host=pc_host, pc_port=pc_port)
                self._output_reader.start()
                print(
                    "[robot] lendo foto/busyIO do servidor Modbus local do PC "
                    f"em {pc_host}:{pc_port}"
                )
            else:
                self._output_reader = self._robot
                print("[robot] lendo foto/busyIO diretamente do UR")

    def close(self) -> None:
        if self._robot is not None:
            self._robot.close()
        if self._output_reader is not None and self._output_reader is not self._robot:
            self._output_reader.close()

    def run(self) -> None:
        import cv2

        self._configure_hand_vision()
        cap = open_camera(self.camera_index)
        if cap is None:
            print(f"Erro: nao foi possivel usar a camera {self.camera_index}.")
            return

        print("robot_round_orchestrator rodando. Ctrl+C para sair.")
        print("Gestos: 4=start, 1=hit, 2=split, 3=double, 5=stand.")
        print("Teclas: c=capturar carta da rampa, s=salvar debug mao, r=reset, q/ESC=sair.")
        if self.auto_foto:
            print("Automacao foto: ligada; pulso foto do robo captura carta automaticamente.")
        if self.dry_run_robot:
            print("Robo: dry-run ligado; pulsos serao apenas impressos.")
        if self.gesture_test:
            print("Modo teste de gestos: sinais fisicos serao enviados sem validar a rodada.")

        self._log_outputs_snapshot("boot")
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

                if self._foto_rising(now):
                    capture_frame = self._frame_after_foto_delay(cap, fallback=frame)
                    self.capture_card_from_frame(capture_frame, source="foto")

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

    def _configure_hand_vision(self) -> None:
        if not self.fast_hand_vision:
            return
        if hand_sign_vision.USE_HAND_SKELETON_DETECTOR or hand_sign_vision.USE_HAND_DATASET_CLASSIFIER:
            hand_sign_vision.USE_HAND_SKELETON_DETECTOR = False
            hand_sign_vision.USE_HAND_DATASET_CLASSIFIER = False
            print("[hand] visao rapida ligada; MediaPipe/dataset desativados no orquestrador")

    def reset_round(self) -> None:
        self.phase = PHASE_WAITING_START
        self.initial_cards = PendingInitialCards()
        self.round_state = None
        self._pending_player_action = None
        self._pending_player_draws = []
        self._pending_player_draws_needed = 0
        self._pending_split_draw_targets = []
        self._pending_dealer_card = False
        self._natural_blackjack_reveal_pending = False
        self._player_bust_reveal_pending = False
        self._last_foto = False
        self._last_foto_capture_at = 0.0
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

    def _foto_rising(self, now: float) -> bool:
        if not self.auto_foto or self._output_reader is None:
            return False

        outputs = self._output_reader.read_outputs(
            foto_coil=self.foto_coil,
            busyio_coil=self.busyio_coil,
            source=self.output_source,
        )
        outputs_seen = (outputs.foto, outputs.busyIO, outputs.source)
        if outputs_seen != self._last_outputs_seen:
            print(
                "[robot] outputs "
                f"foto={'HI' if outputs.foto else 'LO'} "
                f"busyIO={'HI' if outputs.busyIO else 'LO'} "
                f"source={outputs.source}"
            )
            self._last_outputs_seen = outputs_seen
        rising = outputs.foto and not self._last_foto
        self._last_foto = outputs.foto

        if not rising:
            return False
        if now - self._last_foto_capture_at < self.foto_cooldown:
            return False

        self._last_foto_capture_at = now
        print("[robot] foto=HI; capturando carta")
        return True

    def _frame_after_foto_delay(self, cap, fallback):
        if self.foto_delay <= 0:
            return fallback

        print(f"[robot] aguardando {self.foto_delay:.2f}s antes da captura foto")
        time.sleep(self.foto_delay)
        frame = fallback
        for _ in range(3):
            ok, fresh = cap.read()
            if ok and fresh is not None:
                frame = fresh
        return frame

    def _log_outputs_snapshot(self, reason: str) -> None:
        if not self.auto_foto or self._output_reader is None:
            print(f"[robot] outputs snapshot skipped ({reason}); auto_foto desativado ou leitor ausente")
            self._append_event(
                "outputs_snapshot_skipped",
                reason=reason,
                auto_foto=self.auto_foto,
                reader_present=self._output_reader is not None,
            )
            return

        outputs = self._output_reader.read_outputs(
            foto_coil=self.foto_coil,
            busyio_coil=self.busyio_coil,
            source=self.output_source,
        )
        print(
            f"[robot] outputs snapshot ({reason}) "
            f"foto={'HI' if outputs.foto else 'LO'} "
            f"busyIO={'HI' if outputs.busyIO else 'LO'} "
            f"source={outputs.source}"
        )
        self._last_outputs_seen = (outputs.foto, outputs.busyIO, outputs.source)
        self._last_foto = outputs.foto
        self._append_event(
            "outputs_snapshot",
            reason=reason,
            foto=outputs.foto,
            busyIO=outputs.busyIO,
            source=outputs.source,
            foto_coil=self.foto_coil,
            busyio_coil=self.busyio_coil,
        )

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
        self._append_event(
            "hand_frame",
            state=self.phase,
            reading=raw if raw else None,
            stable=fingers,
            action=action,
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

        if self.phase in {PHASE_WAITING_START, PHASE_FINISHED} and action == "startprog":
            self._start_round_from_gesture()
            return

        if self.phase == PHASE_PLAYER_TURN:
            self.handle_player_action(action)
            self._last_action = action
            self._last_action_at = time.monotonic()
            return

        if self.phase == PHASE_INITIAL_DEAL:
            print("[round] acao reconhecida mas ignorada; aguardando cartas iniciais via foto")
        else:
            print(f"[round] acao reconhecida mas ignorada no estado {self.phase}")
        self._last_action = action
        self._last_action_at = time.monotonic()

    def _start_round_from_gesture(self) -> None:
        if self.phase == PHASE_FINISHED:
            self.initial_cards = PendingInitialCards()
            self.round_state = None
            self._pending_player_action = None
            self._pending_player_draws = []
            self._pending_player_draws_needed = 0
            self._pending_split_draw_targets = []
            self._pending_dealer_card = False
            self._natural_blackjack_reveal_pending = False
            self._player_bust_reveal_pending = False
            self._last_foto = False
            print("[round] nova rodada solicitada apos finished")

        self._pulse("startprog", self.start_hold)
        self.phase = PHASE_INITIAL_DEAL
        self._last_action = "startprog"
        self._last_action_at = time.monotonic()
        print("[round] startprog enviado; aguardando cartas iniciais via foto (c = captura manual)")
        self._append_event("startprog_sent", action="startprog")

    def _should_resend_gesture_action(self) -> bool:
        return (
            self.gesture_test
            and self.gesture_resend_interval > 0
            and time.monotonic() - self._last_action_at >= self.gesture_resend_interval
        )

    def _action_from_fingers(self, fingers: int | None) -> str | None:
        if self.gesture_test and fingers != 4:
            return action_from_hand_count(fingers, phase=PHASE_PLAYER_TURN)
        if self.phase == PHASE_FINISHED:
            return "startprog" if fingers == 4 else None
        return action_from_hand_count(fingers, phase=self.phase)

    def _handle_gesture_test_action(self, action: str) -> None:
        robot_signal = self._robot_signal_for_gesture_test(action)
        if robot_signal is None:
            print(f"[gesture-test] sem sinal fisico para {action}")
            return

        self._wait_robot_idle_before_gesture_signal(action)
        self._pulse(robot_signal, self._hold_for_action(action))
        if action == "startprog":
            self.phase = PHASE_INITIAL_DEAL
        print(f"[gesture-test] sinal enviado: {robot_signal}")
        self._append_event("gesture_test_action", action=action, robot_signal=robot_signal)

    def _robot_signal_for_gesture_test(self, action: str) -> str | None:
        if action == "split":
            return "splitAB"
        return action

    def capture_card_from_frame(self, frame, source: str = "manual") -> dict | None:
        card, _debug = process_image_as_card(frame)
        if card.get("status") != "ok":
            print(f"[card] carta nao reconhecida via {source}; ignorei a captura")
            self._append_event("card_unrecognized", source=source)
            return None

        print(f"[card] reconhecida via {source}: {bj.card_label(card)}")
        self._append_event(
            "card_recognized",
            source=source,
            card=bj.card_label(card),
            rank=card.get("rank"),
            blackjack_value=card.get("blackjack_value"),
        )

        if self.phase == PHASE_INITIAL_DEAL:
            self._add_initial_card(card)
        elif self._pending_player_action is not None:
            self._add_player_action_card(card)
        elif self.phase == PHASE_DEALER_TURN and self._pending_dealer_card:
            self._add_dealer_card(card)
        elif self.phase == PHASE_PLAYER_TURN:
            print("[card] carta ignorada; nenhuma acao do jogador aguardava carta")
        elif self.phase == PHASE_DEALER_TURN:
            print("[card] carta ignorada; dealer nao aguardava compra")
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
        self._append_event(
            "initial_card_registered",
            step=step,
            card=bj.card_label(card),
            initial_player=[bj.card_label(item) for item in self.initial_cards.player_cards],
            initial_dealer_upcard=(
                bj.card_label(self.initial_cards.dealer_upcard)
                if self.initial_cards.dealer_upcard is not None
                else None
            ),
        )

        if self.initial_cards.ready():
            self.round_state = bj.start_round(
                self.initial_cards.player_cards,
                self.initial_cards.dealer_upcard,
                dealer_hole_card=None,
            )
            self.round_state.dealer_hole_revealed = False
            self._pending_player_action = None
            self._pending_player_draws = []
            self._pending_player_draws_needed = 0
            self._last_action = None
            self._after_initial_deal()

    def _after_initial_deal(self) -> None:
        print("[round] cartas iniciais completas")
        self._append_event(
            "initial_deal_complete",
            snapshot=self._build_round_snapshot("initial_deal_complete"),
        )
        self._print_round_state()

        has_natural_blackjack = (
            self.round_state is not None
            and len(self.round_state.player_hands) == 1
            and self.round_state.player_hands[0].is_natural_blackjack
        )
        if has_natural_blackjack:
            self._finish_natural_blackjack()
            return

        self.phase = PHASE_PLAYER_TURN
        print("[round] aguardando acao do jogador")

    def _finish_natural_blackjack(self) -> None:
        if self.round_state is None:
            return

        print("[round] blackjack natural do jogador; enviando stand do jogador para revelar dealer")
        self.phase = PHASE_PLAYER_TURN
        self._pending_player_action = None
        self._pending_player_draws = []
        self._pending_player_draws_needed = 0
        self._pending_split_draw_targets = []
        self._wait_foto_released_before_player_stand()
        self._wait_robot_idle_before_natural_stand()
        self._pulse("stand", self.natural_stand_hold)
        self.phase = PHASE_DEALER_TURN
        self._pending_dealer_card = True
        self._natural_blackjack_reveal_pending = True
        print("[dealer] aguardando carta fechada revelada via foto")

    def _wait_robot_idle_before_natural_stand(self) -> None:
        if self._output_reader is None:
            return
        if self.natural_stand_idle_timeout <= 0:
            return

        print(
            "[robot] aguardando busyIO=LO para enviar stand natural "
            f"(coil {self.busyio_coil}, timeout={self.natural_stand_idle_timeout:.2f}s)"
        )
        deadline = time.monotonic() + self.natural_stand_idle_timeout
        while time.monotonic() < deadline:
            outputs = self._output_reader.read_outputs(
                foto_coil=self.foto_coil,
                busyio_coil=self.busyio_coil,
                source=self.output_source,
            )
            outputs_seen = (outputs.foto, outputs.busyIO, outputs.source)
            if outputs_seen != self._last_outputs_seen:
                print(
                    "[robot] outputs "
                    f"foto={'HI' if outputs.foto else 'LO'} "
                    f"busyIO={'HI' if outputs.busyIO else 'LO'} "
                    f"source={outputs.source}"
                )
                self._last_outputs_seen = outputs_seen

            if not outputs.busyIO:
                self._last_outputs_seen = (outputs.foto, outputs.busyIO, outputs.source)
                print("[robot] busyIO=LO; enviando stand natural")
                return
            time.sleep(0.05)

        print("[robot] aviso: busyIO=LO nao foi confirmado; enviando stand natural mesmo assim")

    def _wait_foto_released_before_player_stand(self, timeout: float = 3.0) -> None:
        if self._output_reader is None:
            return

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            outputs = self._output_reader.read_outputs(
                foto_coil=self.foto_coil,
                busyio_coil=self.busyio_coil,
                source=self.output_source,
            )
            if not outputs.foto:
                self._last_foto = False
                return
            time.sleep(0.05)

        print("[robot] aviso: foto continuou HI antes do stand natural; enviando stand mesmo assim")

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

        self._wait_robot_idle_before_gesture_signal(action)
        self._pulse(robot_signal, self._hold_for_action(action))

        if action == "split":
            accepted = self._start_split_action(robot_signal)
            if not accepted:
                print("[round] split rejeitado; estado das maos nao foi alterado")
                return
            print("[round] split aplicado; aguardando 2 cartas via foto")
            self._print_round_state()
            return

        if action in {"hit", "double", "split"}:
            self._pending_player_action = action
            self._pending_player_draws = []
            self._pending_player_draws_needed = 2 if action == "split" else 1
            print(
                "[round] acao enviada; aguardando "
                f"{self._pending_player_draws_needed} carta(s) via foto"
            )
            return
        else:
            accepted = bj.apply_player_action(self.round_state, action)

        print(f"[round] acao aplicada={accepted}: {action}")
        self._append_event("player_action_applied", action=action, accepted=accepted)
        self._print_round_state()
        self._after_player_state_update()

    def _start_split_action(self, robot_signal: str) -> bool:
        if self.round_state is None:
            return False

        hand_index = self.round_state.active_hand_index
        hand = self.round_state.current_hand()
        if hand is None or len(hand.cards) != 2:
            return False

        first_card, second_card = hand.cards
        first_hand = bj.BlackjackHand(cards=[_copy_card(first_card)], from_split=True)
        second_hand = bj.BlackjackHand(cards=[_copy_card(second_card)], from_split=True)

        if robot_signal == "splitAB":
            self.round_state.player_hands[hand_index:hand_index + 1] = [first_hand, second_hand]
            draw_targets = [0, 1]
        elif robot_signal == "splitAC" and len(self.round_state.player_hands) == 2 and hand_index == 0:
            self.round_state.player_hands[0] = first_hand
            self.round_state.player_hands.append(second_hand)
            draw_targets = [0, 2]
        elif robot_signal == "splitBC" and len(self.round_state.player_hands) == 2 and hand_index == 1:
            self.round_state.player_hands[1] = first_hand
            self.round_state.player_hands.append(second_hand)
            draw_targets = [1, 2]
        else:
            return False

        self.round_state.split_count += 1
        self.round_state.active_hand_index = hand_index
        self.round_state.events.append(
            {
                "stage": "player_action",
                "action": "split",
                "accepted": True,
                "hand_index": hand_index,
                "robot_signal": robot_signal,
                "draw_targets": draw_targets,
            }
        )
        self._pending_player_action = "split"
        self._pending_player_draws = []
        self._pending_player_draws_needed = 2
        self._pending_split_draw_targets = draw_targets
        return True

    def _add_player_action_card(self, card: dict) -> None:
        if self.round_state is None:
            print("[round] carta ignorada; round_state ainda nao existe")
            return
        if self._pending_player_action is None:
            print("[card] carta capturada durante player_turn, mas nenhuma acao aguardava carta")
            return

        if self._pending_player_action == "split":
            self._add_split_draw_card(card)
            return

        self._pending_player_draws.append(card)
        remaining = self._pending_player_draws_needed - len(self._pending_player_draws)
        if remaining > 0:
            print(f"[round] aguardando mais {remaining} carta(s) para {self._pending_player_action}")
            return

        action = self._pending_player_action
        draw_cards = iter(self._pending_player_draws)
        self._pending_player_action = None
        self._pending_player_draws = []
        self._pending_player_draws_needed = 0
        self._pending_split_draw_targets = []
        acted_hand_index = self.round_state.active_hand_index
        accepted = bj.apply_player_action(self.round_state, action, lambda: next(draw_cards))
        print(f"[round] acao aplicada={accepted}: {action}")
        self._print_round_state()
        if accepted:
            self._auto_stand_after_closed_player_total(acted_hand_index)
        self._after_player_state_update()

    def _auto_stand_after_closed_player_total(self, hand_index: int) -> None:
        if self.round_state is None or hand_index >= len(self.round_state.player_hands):
            return
        hand = self.round_state.player_hands[hand_index]
        reason = None
        if hand.is_busted:
            reason = "bustou"
        elif hand.is_active and hand.total == 21:
            hand.status = bj.STATUS_STOOD
            reason = "fez 21"
        if reason is None:
            return

        hand_label = ("A", "B", "C")[hand_index]
        print(f"[round] mao {hand_label} {reason}; enviando stand automatico para trocar de mao")
        self._wait_robot_idle_before_gesture_signal("stand")
        self._pulse("stand", self.stand_hold)
        self._append_event("player_auto_stand", hand=hand_label, reason=reason)

    def _add_split_draw_card(self, card: dict) -> None:
        if self.round_state is None:
            return
        draw_number = len(self._pending_player_draws)
        if draw_number >= len(self._pending_split_draw_targets):
            print("[round] carta de split ignorada; nao ha mao alvo pendente")
            return

        target_index = self._pending_split_draw_targets[draw_number]
        self._pending_player_draws.append(card)
        self.round_state.player_hands[target_index].cards.append(_copy_card(card))
        if bj.is_bust(self.round_state.player_hands[target_index].cards):
            self.round_state.player_hands[target_index].status = bj.STATUS_BUSTED

        hand_label = ("A", "B", "C")[target_index]
        print(f"[round] carta de split adicionada na mao {hand_label}: {bj.card_label(card)}")

        remaining = self._pending_player_draws_needed - len(self._pending_player_draws)
        if remaining > 0:
            print(f"[round] aguardando mais {remaining} carta(s) para split")
            self._print_round_state()
            return

        self._pending_player_action = None
        self._pending_player_draws = []
        self._pending_player_draws_needed = 0
        self._pending_split_draw_targets = []
        self.round_state.current_hand()
        print("[round] split completo")
        self._append_event("split_completed", snapshot=self._build_round_snapshot("split_completed"))
        self._print_round_state()
        self._after_player_state_update()

    def _add_dealer_card(self, card: dict) -> None:
        if self.round_state is None:
            print("[dealer] round_state ausente")
            return
        self._pending_dealer_card = False
        self.round_state.dealer_cards.append(card)
        print(f"[dealer] carta adicionada: {bj.card_label(card)}")
        self._append_event(
            "dealer_card_added",
            card=bj.card_label(card),
            dealer_cards=[bj.card_label(item) for item in self.round_state.dealer_cards],
        )
        if not self.round_state.dealer_hole_revealed:
            bj.reveal_dealer_hole(self.round_state)
        self._print_round_state()
        if self._natural_blackjack_reveal_pending:
            self._natural_blackjack_reveal_pending = False
            self.round_state.dealer_status = bj.STATUS_STOOD
            bj.resolve_round(self.round_state)
            print("[round] blackjack natural revelado; enviando stand final para encerrar no robo")
            self._wait_robot_idle_before_gesture_signal("stand")
            self._pulse("stand", self.stand_hold)
            self.phase = PHASE_FINISHED
            print("[round] blackjack natural resolvido apos revelar dealer")
            self._print_round_state()
            self._print_final_result_summary()
            return
        if self._player_bust_reveal_pending:
            self._finish_after_player_bust_reveal()
            return
        self._drive_dealer_turn()

    def _after_player_state_update(self) -> None:
        if self.round_state is None:
            return

        if all(hand.is_busted for hand in self.round_state.player_hands):
            self._enter_dealer_reveal_after_player_bust()
            return

        if self.round_state.current_hand() is None:
            self._enter_dealer_turn()

    def _enter_dealer_reveal_after_player_bust(self) -> None:
        if self.round_state is None:
            return

        self.phase = PHASE_DEALER_TURN
        self._last_action = None
        self._player_bust_reveal_pending = True
        print("[round] todas as maos do jogador estouraram; revelando dealer antes de encerrar")
        if not self.round_state.dealer_hole_revealed and len(self.round_state.dealer_cards) == 1:
            self._pending_dealer_card = True
            print("[dealer] aguardando carta fechada revelada via foto")
            self._append_event("dealer_waiting_hole_reveal_after_player_bust")
            return
        self._finish_after_player_bust_reveal()

    def _finish_after_player_bust_reveal(self) -> None:
        if self.round_state is None:
            return

        self._player_bust_reveal_pending = False
        self.round_state.dealer_status = bj.STATUS_STOOD
        print("[dealer] cartas reveladas; enviando stand final antes de encerrar")
        self._wait_robot_idle_before_dealer_action()
        self._pulse("stand", self.stand_hold)
        bj.resolve_round(self.round_state)
        self.phase = PHASE_FINISHED
        self._append_event("player_bust_round_finished")
        self._print_round_state()
        self._print_final_result_summary()

    def _enter_dealer_turn(self) -> None:
        self.phase = PHASE_DEALER_TURN
        self._last_action = None
        print("[round] maos do jogador encerradas; dealer_turn iniciado")
        if (
            self.round_state is not None
            and not self.round_state.dealer_hole_revealed
            and len(self.round_state.dealer_cards) == 1
        ):
            self._pending_dealer_card = True
            print("[dealer] aguardando carta fechada revelada via foto")
            self._append_event("dealer_waiting_hole_reveal")
            return
        self._drive_dealer_turn()

    def _drive_dealer_turn(self) -> None:
        if self.round_state is None or self.phase != PHASE_DEALER_TURN:
            return
        if self._pending_dealer_card:
            return

        if bj.is_bust(self.round_state.dealer_cards):
            self.round_state.dealer_status = bj.STATUS_BUSTED
            print("[dealer] bustou; aguardando idle e enviando stand final")
            self._wait_robot_idle_before_dealer_action()
            self._pulse("stand", self.stand_hold)
            bj.resolve_round(self.round_state)
            self.phase = PHASE_FINISHED
            print("Jogador Venceu")
            print("[round] dealer bustou; rodada resolvida")
            self._append_event(
                "dealer_bust_round_resolved",
                dealer_total=self.round_state.dealer_total,
            )
            self._print_round_state()
            self._print_final_result_summary()
            return

        if bj.dealer_action(self.round_state.dealer_cards) == bj.ACTION_HIT:
            print("[dealer] total < 17; hit forcado")
            self._wait_robot_idle_before_dealer_action()
            self._pulse("hit", self.action_hold)
            self._pending_dealer_card = True
            print("[dealer] aguardando carta via foto")
            return

        self.round_state.dealer_status = (
            bj.STATUS_BUSTED
            if bj.is_bust(self.round_state.dealer_cards)
            else bj.STATUS_STOOD
        )
        self._wait_robot_idle_before_dealer_action()
        self._pulse("stand", self.stand_hold)
        bj.resolve_round(self.round_state)
        self.phase = PHASE_FINISHED
        print("[round] dealer encerrou; rodada resolvida")
        self._append_event(
            "dealer_round_resolved",
            dealer_status=self.round_state.dealer_status,
            dealer_total=self.round_state.dealer_total,
        )
        self._print_round_state()
        self._print_final_result_summary()

    def _wait_robot_idle_before_dealer_action(self) -> None:
        if self._output_reader is None:
            return

        print(
            "[robot] aguardando busyIO=LO antes da acao automatica do dealer "
            f"(coil {self.busyio_coil}, "
            f"timeout={self.dealer_action_idle_timeout:.2f}s; 0=sem timeout)"
        )
        deadline = (
            None
            if self.dealer_action_idle_timeout <= 0
            else time.monotonic() + self.dealer_action_idle_timeout
        )
        while True:
            outputs = self._output_reader.read_outputs(
                foto_coil=self.foto_coil,
                busyio_coil=self.busyio_coil,
                source=self.output_source,
            )
            outputs_seen = (outputs.foto, outputs.busyIO, outputs.source)
            if outputs_seen != self._last_outputs_seen:
                print(
                    "[robot] outputs "
                    f"foto={'HI' if outputs.foto else 'LO'} "
                    f"busyIO={'HI' if outputs.busyIO else 'LO'} "
                    f"source={outputs.source}"
                )
                self._last_outputs_seen = outputs_seen

            if not outputs.busyIO:
                self._last_outputs_seen = (outputs.foto, outputs.busyIO, outputs.source)
                print("[robot] busyIO=LO; enviando acao automatica do dealer")
                return
            time.sleep(0.05)

            if deadline is not None and time.monotonic() >= deadline:
                print(
                    "[robot] aviso: busyIO=LO nao foi confirmado; "
                    "continuando espera antes da acao do dealer"
                )
                deadline = time.monotonic() + self.dealer_action_idle_timeout

    def _wait_robot_idle_before_gesture_signal(self, action: str) -> None:
        if self._output_reader is None:
            return

        print(
            "[robot] aguardando busyIO=LO antes do gesto "
            f"{action} (coil {self.busyio_coil})"
        )
        while True:
            outputs = self._output_reader.read_outputs(
                foto_coil=self.foto_coil,
                busyio_coil=self.busyio_coil,
                source=self.output_source,
            )
            outputs_seen = (outputs.foto, outputs.busyIO, outputs.source)
            if outputs_seen != self._last_outputs_seen:
                print(
                    "[robot] outputs "
                    f"foto={'HI' if outputs.foto else 'LO'} "
                    f"busyIO={'HI' if outputs.busyIO else 'LO'} "
                    f"source={outputs.source}"
                )
                self._last_outputs_seen = outputs_seen

            if not outputs.busyIO:
                self._last_outputs_seen = (outputs.foto, outputs.busyIO, outputs.source)
                print(f"[robot] busyIO=LO; enviando gesto {action}")
                return
            time.sleep(0.05)

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
        self._append_event("pulse", signal=signal, hold=hold)
        if self._robot is None:
            return
        try:
            self._robot.pulse_signal(signal, hold=hold)
        except RuntimeError as exc:
            print(f"[robot] ERRO no pulso {signal}: {exc}")
            print("[robot] mantendo orquestrador ativo; verifique IP/rede/Modbus do UR")
            self._append_event("pulse_error", signal=signal, error=str(exc))

    def _print_round_state(self) -> None:
        if self.round_state is None:
            self._write_round_snapshot("no_round_state")
            return
        summary = bj.round_summary(self.round_state)
        print(
            f"[round] ativa={self.round_state.active_hand_index} "
            f"splits={summary['split_count']} maos={summary['player_hands']} "
            f"dealer={summary['dealer_cards']}"
        )
        print(f"[round] listas_fisicas={self.physical_hands_snapshot()}")
        self._write_round_snapshot("round_state")
        self._append_event(
            "round_state",
            snapshot=self._build_round_snapshot("round_state"),
        )

    def _print_final_result_summary(self) -> None:
        if self.round_state is None:
            return
        winners = []
        for index, hand in enumerate(self.round_state.player_hands):
            if hand.result == bj.RESULT_WIN:
                winners.append(("A", "B", "C")[index])
        if winners:
            print(f"Jogador venceu {len(winners)} mao(s): {', '.join(winners)}")
        else:
            print("Dealer venceu!")

    def physical_hands_snapshot(self) -> dict[str, list[str]]:
        player_hands = self.round_state.player_hands if self.round_state is not None else []
        snapshot = {"A": [], "B": [], "C": [], "dealer": []}
        for index, label in enumerate(("A", "B", "C")):
            if index < len(player_hands):
                snapshot[label] = [bj.card_label(card) for card in player_hands[index].cards]
        if self.round_state is not None:
            snapshot["dealer"] = [bj.card_label(card) for card in self.round_state.dealer_cards]
        return snapshot

    def _write_round_snapshot(self, reason: str) -> None:
        self._state_log_dir.mkdir(parents=True, exist_ok=True)
        snapshot = self._build_round_snapshot(reason)
        if self.round_state is not None:
            summary = bj.round_summary(self.round_state)
            snapshot.update(
                {
                    "active_hand_index": self.round_state.active_hand_index,
                    "dealer_total": summary["dealer_total"],
                    "dealer_status": summary["dealer_status"],
                    "dealer_hole_revealed": summary["dealer_hole_revealed"],
                    "player_hands": summary["player_hands"],
                }
            )

        latest_path = self._state_log_dir / "latest_round_state.json"
        history_path = self._state_log_dir / "round_state_history.jsonl"
        payload = json.dumps(snapshot, ensure_ascii=True, sort_keys=True)
        latest_path.write_text(payload + "\n", encoding="utf-8")
        with history_path.open("a", encoding="utf-8") as file:
            file.write(payload + "\n")

    def _build_round_snapshot(self, reason: str) -> dict:
        snapshot = {
            "reason": reason,
            "phase": self.phase,
            "pending_initial": {
                "player": [bj.card_label(card) for card in self.initial_cards.player_cards],
                "dealer_upcard": (
                    bj.card_label(self.initial_cards.dealer_upcard)
                    if self.initial_cards.dealer_upcard is not None
                    else None
                ),
            },
            "physical_hands": self.physical_hands_snapshot(),
            "pending_player_action": self._pending_player_action,
            "pending_player_draws_needed": self._pending_player_draws_needed,
            "pending_dealer_card": self._pending_dealer_card,
            "natural_blackjack_reveal_pending": self._natural_blackjack_reveal_pending,
            "player_bust_reveal_pending": self._player_bust_reveal_pending,
            "foto_coil": self.foto_coil,
            "busyio_coil": self.busyio_coil,
            "output_source": self.output_source,
            "foto_delay": self.foto_delay,
            "natural_stand_hold": self.natural_stand_hold,
            "natural_stand_idle_timeout": self.natural_stand_idle_timeout,
            "dealer_action_idle_timeout": self.dealer_action_idle_timeout,
        }
        if self.round_state is not None:
            summary = bj.round_summary(self.round_state)
            snapshot.update(
                {
                    "active_hand_index": self.round_state.active_hand_index,
                    "dealer_total": summary["dealer_total"],
                    "dealer_status": summary["dealer_status"],
                    "dealer_hole_revealed": summary["dealer_hole_revealed"],
                    "player_hands": summary["player_hands"],
                }
            )
        return snapshot

    def _append_event(self, event: str, **payload) -> None:
        self._state_log_dir.mkdir(parents=True, exist_ok=True)
        self._event_seq += 1
        entry = {
            "seq": self._event_seq,
            "event": event,
            "phase": self.phase,
            "timestamp": time.time(),
            **payload,
        }
        payload_text = json.dumps(entry, ensure_ascii=True, sort_keys=True)
        self._latest_event_path.write_text(payload_text + "\n", encoding="utf-8")
        with self._events_log_path.open("a", encoding="utf-8") as file:
            file.write(payload_text + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Orquestrador inicial da rodada real DealerBot.")
    parser.add_argument("--camera", type=int, default=0, help="Indice da camera OpenCV.")
    parser.add_argument("--ur-host", default="10.103.18.245", help="IP do controlador UR.")
    parser.add_argument("--ur-port", type=int, default=502, help="Porta Modbus do UR.")
    parser.add_argument(
        "--pc-host",
        default="0.0.0.0",
        help="IP local para servidor Modbus do PC quando --pc-output-server estiver ligado.",
    )
    parser.add_argument(
        "--pc-port",
        type=int,
        default=31415,
        help="Porta local para servidor Modbus do PC quando --pc-output-server estiver ligado.",
    )
    parser.add_argument("--hand-interval", type=float, default=1.0, help="Intervalo de leitura da mao.")
    parser.add_argument("--action-hold", type=float, default=0.3, help="Hold de hit/split/double.")
    parser.add_argument("--start-hold", type=float, default=0.5, help="Hold de startprog.")
    parser.add_argument("--stand-hold", type=float, default=0.2, help="Hold de stand.")
    parser.add_argument(
        "--natural-stand-hold",
        type=float,
        default=4.0,
        help="Hold de stand usado para sair da fase do jogador em blackjack natural.",
    )
    parser.add_argument(
        "--natural-stand-idle-timeout",
        type=float,
        default=20.0,
        help="Timeout esperando busyIO=LO antes do stand automatico em blackjack natural.",
    )
    parser.add_argument(
        "--dealer-action-idle-timeout",
        type=float,
        default=0.0,
        help="Timeout esperando busyIO=LO antes de hit/stand automaticos do dealer. 0 espera sem limite.",
    )
    parser.add_argument("--foto-coil", type=int, default=17, help="Coil de saida foto do UR.")
    parser.add_argument(
        "--busyio-coil",
        type=int,
        default=DEFAULT_BUSYIO_COIL,
        help="Coil de saida busyIO do UR.",
    )
    parser.add_argument(
        "--output-source",
        choices=["auto", "coils", "discrete_inputs", "holding_registers", "input_registers"],
        default="coils",
        help="Tipo Modbus usado para ler foto/busyIO. Padrao: coils direto do UR.",
    )
    parser.add_argument("--foto-cooldown", type=float, default=0.4, help="Cooldown entre capturas por foto.")
    parser.add_argument(
        "--foto-delay",
        type=float,
        default=0.8,
        help="Atraso entre a borda foto=HI e a captura da carta.",
    )
    parser.add_argument(
        "--fast-hand-vision",
        action="store_true",
        help="Desativa MediaPipe/dataset na leitura de maos para iniciar mais rapido, com menor precisao.",
    )
    parser.add_argument(
        "--no-auto-foto",
        action="store_true",
        help="Desliga captura automatica por pulso foto; tecla c continua funcionando.",
    )
    parser.add_argument(
        "--pc-output-server",
        action="store_true",
        default=False,
        help="Le foto/busyIO de um servidor Modbus local escrito pelo UR como cliente.",
    )
    parser.add_argument(
        "--no-pc-output-server",
        action="store_false",
        dest="pc_output_server",
        help="Desliga o servidor Modbus local do PC e tenta ler outputs diretamente do UR.",
    )
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
        pc_host=args.pc_host,
        pc_port=args.pc_port,
        address_mode=args.address_mode,
        write_target=args.write_target,
        hand_interval=args.hand_interval,
        action_hold=args.action_hold,
        start_hold=args.start_hold,
        stand_hold=args.stand_hold,
        natural_stand_hold=args.natural_stand_hold,
        natural_stand_idle_timeout=args.natural_stand_idle_timeout,
        dealer_action_idle_timeout=args.dealer_action_idle_timeout,
        auto_foto=not args.no_auto_foto,
        foto_coil=args.foto_coil,
        busyio_coil=args.busyio_coil,
        output_source=args.output_source,
        pc_output_server=args.pc_output_server,
        foto_cooldown=args.foto_cooldown,
        foto_delay=args.foto_delay,
        fast_hand_vision=args.fast_hand_vision,
        stable_samples=args.stable_samples,
        show=args.show,
        dry_run_robot=args.dry_run_robot,
        gesture_test=args.gesture_test,
        gesture_resend_interval=args.gesture_resend_interval,
    )
    orchestrator.run()


if __name__ == "__main__":
    main()
