import argparse
import socket
import time
from dataclasses import dataclass


DEFAULT_SIGNAL_ADDRESSES = {
    "startprog": 128,
    "hit": 129,
    "double": 130,
    "stand": 131,
    "splitAB": 132,
    "splitBC": 133,
    "splitAC": 134,
}
LEGACY_SIGNAL_ADDRESSES = {
    "hit": 0,
    "splitAB": 1,
    "double": 2,
    "startprog": 3,
    "stand": 4,
    "splitBC": 5,
    "splitAC": 6,
}

ACTION_SIGNALS = {"hit", "splitAB", "double", "stand", "splitBC", "splitAC"}

DEFAULT_PC_HOST = "10.102.28.161"
DEFAULT_PC_PORT = 31415
DEFAULT_UR_HOST = "10.103.18.245"
DEFAULT_UR_PORT = 502
DEFAULT_FOTO_COIL = 1
DEFAULT_BUSYIO_COIL = 2


def _load_modbus():
    try:
        from pyModbusTCP.client import ModbusClient
        from pyModbusTCP.server import ModbusServer
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "pyModbusTCP nao esta instalado. Rode: pip install -r requirements.txt"
        ) from exc

    return ModbusClient, ModbusServer


def _assert_port_available(host: str, port: int) -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, port))
    except OSError as exc:
        raise RuntimeError(
            f"nao foi possivel abrir {host}:{port}; a porta ja esta em uso "
            "ou o IP nao pertence a este PC"
        ) from exc
    finally:
        probe.close()


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "t", "yes", "y", "on", "hi"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off", "lo"}:
        return False
    raise ValueError(f"valor booleano invalido: {value}")


def parse_signal_assignment(raw: str) -> tuple[str, bool]:
    if "=" not in raw:
        raise ValueError("use o formato sinal=true ou sinal=false")

    name, value = raw.split("=", 1)
    name = name.strip()
    if name not in DEFAULT_SIGNAL_ADDRESSES:
        valid = ", ".join(DEFAULT_SIGNAL_ADDRESSES)
        raise ValueError(f"sinal desconhecido: {name}. Validos: {valid}")

    return name, parse_bool(value)


def _should_use_direct_mode(args) -> bool:
    if args.direct_to_robot:
        return True
    if args.server_mode:
        return False
    return bool(args.startprog or args.command or args.set or args.diagnose_start)


@dataclass
class RobotInputs:
    hit: bool = False
    splitAB: bool = False
    double: bool = False
    startprog: bool = False
    stand: bool = False
    splitBC: bool = False
    splitAC: bool = False

    def as_registers(self) -> list[int]:
        return [
            int(self.hit),
            int(self.splitAB),
            int(self.double),
            int(self.startprog),
            int(self.stand),
            int(self.splitBC),
            int(self.splitAC),
        ]

    def as_dict(self) -> dict[str, int]:
        return {
            "hit": int(self.hit),
            "splitAB": int(self.splitAB),
            "double": int(self.double),
            "startprog": int(self.startprog),
            "stand": int(self.stand),
            "splitBC": int(self.splitBC),
            "splitAC": int(self.splitAC),
        }


@dataclass
class RobotOutputs:
    foto: bool = False
    busyIO: bool = False


class DealerBotBridge:
    """
    Bridge Modbus do PC para o DealerBot no Universal Robots.

    O PC sobe um servidor Modbus/TCP. O programa PolyScope do UR le os Input
    Registers 0..6 desse servidor como os sinais digitais nomeados:
    hit, splitAB, double, startprog, stand, splitBC, splitAC.
    """

    def __init__(
        self,
        pc_host: str = DEFAULT_PC_HOST,
        pc_port: int = DEFAULT_PC_PORT,
        ur_host: str = DEFAULT_UR_HOST,
        ur_port: int = DEFAULT_UR_PORT,
        foto_coil: int = DEFAULT_FOTO_COIL,
        busyio_coil: int = DEFAULT_BUSYIO_COIL,
        read_ur_outputs: bool = True,
        timeout: float = 1.0,
    ) -> None:
        ModbusClient, ModbusServer = _load_modbus()
        self.pc_host = pc_host
        self.pc_port = pc_port
        self.ur_host = ur_host
        self.ur_port = ur_port
        self.foto_coil = foto_coil
        self.busyio_coil = busyio_coil
        self.read_ur_outputs = read_ur_outputs
        self.signal_addresses = DEFAULT_SIGNAL_ADDRESSES.copy()
        self.inputs = RobotInputs()
        self.outputs = RobotOutputs()
        self._server = ModbusServer(pc_host, pc_port, no_block=True)
        self._ur = None
        self._started = False
        if read_ur_outputs:
            self._ur = ModbusClient(
                host=ur_host,
                port=ur_port,
                auto_open=True,
                auto_close=False,
                timeout=timeout,
            )

    def start(self) -> None:
        print(f"[ur] iniciando servidor Modbus do PC em {self.pc_host}:{self.pc_port}")
        _assert_port_available(self.pc_host, self.pc_port)
        self._server.start()
        self._started = True
        self.push_inputs()
        print("[ur] servidor Modbus online")

    def stop(self) -> None:
        print("[ur] encerrando bridge")
        if self._started:
            self.clear_all()
            self._server.stop()
            self._started = False
        if self._ur is not None:
            self._ur.close()

    def push_inputs(self) -> None:
        values = self.inputs.as_dict()
        max_address = max(self.signal_addresses.values())
        registers = [0] * (max_address + 1)

        for name, value in values.items():
            registers[self.signal_addresses[name]] = value

        bits = [bool(value) for value in registers]
        self._server.data_bank.set_input_registers(0, registers)
        self._server.data_bank.set_holding_registers(0, registers)
        self._server.data_bank.set_coils(0, bits)
        self._server.data_bank.set_discrete_inputs(0, bits)

    def set_signal(self, name: str, value: bool) -> None:
        if name not in self.signal_addresses:
            raise ValueError(f"sinal desconhecido: {name}")
        setattr(self.inputs, name, bool(value))
        self.push_inputs()
        print(f"[ur] {name}={'HI' if value else 'LO'}")

    def clear_all(self) -> None:
        self.inputs = RobotInputs()
        self.push_inputs()

    def clear_actions(self) -> None:
        for name in ACTION_SIGNALS:
            setattr(self.inputs, name, False)
        self.push_inputs()

    def refresh_outputs(self) -> RobotOutputs:
        if self._ur is None:
            return self.outputs

        start = min(self.foto_coil, self.busyio_coil)
        count = max(self.foto_coil, self.busyio_coil) - start + 1
        bits = self._ur.read_coils(start, count)
        if bits is None:
            print("[ur] aviso: nao foi possivel ler coils do UR")
            return self.outputs

        self.outputs.foto = bool(bits[self.foto_coil - start])
        self.outputs.busyIO = bool(bits[self.busyio_coil - start])
        return self.outputs

    def wait_busy(self, expected: bool, timeout: float | None = None, poll: float = 0.05) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if self.refresh_outputs().busyIO is expected:
                return True
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(poll)

    def wait_foto_rising(self, timeout: float | None = None, poll: float = 0.02) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        previous = self.refresh_outputs().foto
        while True:
            current = self.refresh_outputs().foto
            if current and not previous:
                return True
            if deadline is not None and time.monotonic() >= deadline:
                return False
            previous = current
            time.sleep(poll)

    def send_action(self, name: str, hold: float = 0.2, accept_timeout: float = 5.0) -> None:
        if name not in ACTION_SIGNALS:
            raise ValueError(f"{name} nao e uma acao valida")

        self.clear_actions()
        self.set_signal(name, True)

        accepted = False
        if self.read_ur_outputs:
            accepted = self.wait_busy(True, timeout=accept_timeout)

        if not accepted:
            time.sleep(hold)

        self.set_signal(name, False)

    def start_program(self, hold: float = 0.5, accept_timeout: float = 10.0) -> None:
        """
        Sobe startprog (DI4 / register 128).

        Se a leitura de busyIO estiver habilitada, baixa startprog assim que o
        robo ficar ocupado. Sem leitura do UR, segura por `hold` segundos.
        """
        self.set_signal("startprog", True)

        accepted = False
        if self.read_ur_outputs:
            accepted = self.wait_busy(True, timeout=accept_timeout)

        if accepted:
            print("[ur] robo aceitou startprog: busyIO=HI")
        else:
            print(f"[ur] mantendo startprog por {hold:.2f}s antes de baixar")
            time.sleep(hold)

        self.set_signal("startprog", False)

    def print_status(self) -> None:
        outputs = self.refresh_outputs()
        inputs = self.inputs.as_dict()
        mapped = {
            name: {"address": self.signal_addresses[name], "value": value}
            for name, value in inputs.items()
        }
        print(f"[ur] sinais publicados = {mapped}")
        print("[ur] espelhado em input registers, holding registers, coils e discrete inputs")
        if self.read_ur_outputs:
            print(
                "[ur] outputs "
                f"foto={'HI' if outputs.foto else 'LO'} "
                f"busyIO={'HI' if outputs.busyIO else 'LO'}"
            )


class RobotDirectClient:
    """
    Cliente Modbus para escrever diretamente no servidor Modbus do robo.

    Use este modo quando a configuracao do UR espera que o PC conecte no IP do
    controlador e escreva coils/holding registers do proprio robo.
    """

    def __init__(
        self,
        ur_host: str = DEFAULT_UR_HOST,
        ur_port: int = DEFAULT_UR_PORT,
        address_mode: str = "standard",
        timeout: float = 1.0,
    ) -> None:
        ModbusClient, _ = _load_modbus()
        self.ur_host = ur_host
        self.ur_port = ur_port
        self.address_mode = address_mode
        self._client = ModbusClient(
            host=ur_host,
            port=ur_port,
            auto_open=True,
            auto_close=False,
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def set_signal(self, name: str, value: bool) -> None:
        if name not in DEFAULT_SIGNAL_ADDRESSES:
            raise ValueError(f"sinal desconhecido: {name}")

        addresses = self._addresses_for_signal(name)
        int_value = int(bool(value))
        bool_value = bool(value)
        results = []

        for label, address in addresses:
            holding_ok = self._client.write_single_register(address, int_value)
            coil_ok = self._client.write_single_coil(address, bool_value)
            results.append((label, address, holding_ok, coil_ok))

            print(
                f"[ur-direct] {name}={'HI' if value else 'LO'} "
                f"{label}_addr={address} holding_ok={holding_ok} coil_ok={coil_ok}"
            )

        if not any(holding_ok or coil_ok for _, _, holding_ok, coil_ok in results):
            raise RuntimeError(
                f"o robo nao aceitou escrita Modbus em {self.ur_host}:{self.ur_port} "
                f"para o sinal {name}"
            )

    def _addresses_for_signal(self, name: str) -> list[tuple[str, int]]:
        if self.address_mode == "standard":
            return [("standard", DEFAULT_SIGNAL_ADDRESSES[name])]
        if self.address_mode == "legacy":
            return [("legacy", LEGACY_SIGNAL_ADDRESSES[name])]
        return [
            ("standard", DEFAULT_SIGNAL_ADDRESSES[name]),
            ("legacy", LEGACY_SIGNAL_ADDRESSES[name]),
        ]

    def start_program(self, hold: float = 0.5) -> None:
        self.set_signal("startprog", True)
        time.sleep(hold)
        self.set_signal("startprog", False)

    def pulse_signal(self, name: str, hold: float = 0.5) -> None:
        self.set_signal(name, True)
        time.sleep(hold)
        self.set_signal(name, False)

    def read_signal(self, name: str) -> None:
        if name not in DEFAULT_SIGNAL_ADDRESSES:
            raise ValueError(f"sinal desconhecido: {name}")

        for label, address in self._addresses_for_signal(name):
            holding = self._client.read_holding_registers(address, 1)
            coil = self._client.read_coils(address, 1)
            print(
                f"[ur-direct] {name} {label}_addr={address} "
                f"holding={holding} coil={coil}"
            )


def _interactive_loop(bridge: DealerBotBridge) -> None:
    print("Comandos: start, hit, double, stand, splitAB, splitBC, splitAC, status, clear, quit")
    while True:
        command = input("ur> ").strip()
        if not command:
            continue
        if command in {"quit", "exit", "q"}:
            return
        if command == "status":
            bridge.print_status()
            continue
        if command == "clear":
            bridge.clear_all()
            print("[ur] todos os sinais em LO")
            continue
        if command == "start":
            bridge.start_program()
            continue
        if command in ACTION_SIGNALS:
            bridge.send_action(command)
            continue
        print(f"Comando desconhecido: {command}")


def _direct_interactive_loop(client: RobotDirectClient, hold: float) -> None:
    print("Comandos: start, hit, double, stand, splitAB, splitBC, splitAC, status, set <sinal> <true|false>, quit")
    while True:
        command = input("ur-direct> ").strip()
        if not command:
            continue
        if command in {"quit", "exit", "q"}:
            return
        if command == "status":
            for name in DEFAULT_SIGNAL_ADDRESSES:
                client.read_signal(name)
            continue
        if command == "start":
            client.start_program(hold=hold)
            continue
        if command in ACTION_SIGNALS:
            client.pulse_signal(command, hold=hold)
            continue
        if command.startswith("set "):
            parts = command.split()
            if len(parts) != 3:
                print("Uso: set <sinal> <true|false>")
                continue
            try:
                client.set_signal(parts[1], parse_bool(parts[2]))
            except ValueError as exc:
                print(f"Erro: {exc}")
            continue
        print(f"Comando desconhecido: {command}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bridge Modbus/TCP para o DealerBot UR.")
    parser.add_argument("--pc-host", default=DEFAULT_PC_HOST, help="IP do PC visto pelo UR.")
    parser.add_argument("--pc-port", type=int, default=DEFAULT_PC_PORT, help="Porta Modbus do PC.")
    parser.add_argument("--ur-host", default=DEFAULT_UR_HOST, help="IP do controlador UR.")
    parser.add_argument("--ur-port", type=int, default=DEFAULT_UR_PORT, help="Porta Modbus do UR.")
    parser.add_argument("--foto-coil", type=int, default=DEFAULT_FOTO_COIL, help="Coil DO1/foto no UR.")
    parser.add_argument("--busyio-coil", type=int, default=DEFAULT_BUSYIO_COIL, help="Coil DO2/busyIO no UR.")
    parser.add_argument("--no-ur-read", action="store_true", help="Nao tenta ler foto/busyIO do UR.")
    parser.add_argument(
        "--startprog",
        action="store_true",
        help="Ao iniciar, envia startprog (DI4 / register 128).",
    )
    parser.add_argument("--command", choices=["hit", "double", "stand", "splitAB", "splitBC", "splitAC"])
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="SINAL=BOOL",
        help="Define um sinal explicitamente, ex: --set startprog=true --set hit=false.",
    )
    parser.add_argument("--hold", type=float, default=0.5, help="Tempo de HI quando nao houver leitura do UR.")
    parser.add_argument("--accept-timeout", type=float, default=10.0, help="Timeout esperando busyIO=HI.")
    parser.add_argument("--no-interactive", action="store_true", help="Sai apos executar --startprog/--command.")
    parser.add_argument(
        "--diagnose-start",
        action="store_true",
        help="Mantem startprog em HI ate Ctrl+C para diagnosticar a tela Modbus do UR.",
    )
    parser.add_argument(
        "--direct-to-robot",
        action="store_true",
        help="Conecta no IP do robo e escreve diretamente em coils/holding registers.",
    )
    parser.add_argument(
        "--server-mode",
        action="store_true",
        help="Forca o modo antigo: PC sobe servidor Modbus e o robo conecta no PC.",
    )
    parser.add_argument(
        "--address-mode",
        choices=["both", "standard", "legacy"],
        default="standard",
        help="No modo direto, escreve em 128..134, 0..6 ou ambos. Padrao: standard.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if _should_use_direct_mode(args):
        if args.no_ur_read:
            print("[ur-direct] --no-ur-read recebido; no modo direto ele apenas evita o servidor do PC.")
        client = RobotDirectClient(
            ur_host=args.ur_host,
            ur_port=args.ur_port,
            address_mode=args.address_mode,
        )
        try:
            for raw_set in args.set:
                name, value = parse_signal_assignment(raw_set)
                client.set_signal(name, value)
            if args.set and not (args.diagnose_start or args.startprog or args.command):
                return
            elif args.diagnose_start:
                client.set_signal("startprog", True)
                print("[ur-direct] startprog mantido em HI. Pressione Ctrl+C para baixar e sair.")
                while True:
                    time.sleep(1.0)
            elif args.startprog:
                client.start_program(hold=args.hold)
            elif args.command:
                client.set_signal(args.command, True)
                time.sleep(args.hold)
                client.set_signal(args.command, False)
            else:
                _direct_interactive_loop(client, hold=args.hold)
        except KeyboardInterrupt:
            client.set_signal("startprog", False)
        finally:
            client.close()
        return

    bridge = DealerBotBridge(
        pc_host=args.pc_host,
        pc_port=args.pc_port,
        ur_host=args.ur_host,
        ur_port=args.ur_port,
        foto_coil=args.foto_coil,
        busyio_coil=args.busyio_coil,
        read_ur_outputs=not args.no_ur_read,
    )

    try:
        bridge.start()
        for raw_set in args.set:
            name, value = parse_signal_assignment(raw_set)
            bridge.set_signal(name, value)
        if args.set and args.no_interactive and not (args.diagnose_start or args.startprog or args.command):
            time.sleep(args.hold)
            return
        if args.diagnose_start:
            bridge.set_signal("startprog", True)
            bridge.print_status()
            print("[ur] startprog mantido em HI. Pressione Ctrl+C para baixar e sair.")
            while True:
                time.sleep(1.0)
        if args.startprog:
            bridge.start_program(hold=args.hold, accept_timeout=args.accept_timeout)
        if args.command:
            bridge.send_action(args.command, hold=args.hold, accept_timeout=args.accept_timeout)
        if not args.no_interactive:
            _interactive_loop(bridge)
    except KeyboardInterrupt:
        pass
    except RuntimeError as exc:
        print(f"[ur] erro: {exc}")
    finally:
        bridge.stop()


if __name__ == "__main__":
    main()
