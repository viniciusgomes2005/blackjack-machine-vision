import argparse
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_IMAGE_BANK = PROJECT_ROOT / "Base_de_dado_renomeada"
DEFAULT_DEBUG_DIR = PROJECT_ROOT / "debug_reconhecimento_otimizado"
DEFAULT_REPORT_FILE = PROJECT_ROOT / "relatorio_reconhecimento_otimizado.txt"

WEBCAM_INDEX = 0

# ROI calibrated for 2560 x 1440 images. The card is expected in the yellow ramp
# region used during the validated camera tests.
BASE_RESOLUTION = (2560, 1440)  # width, height
BASE_CARD_ROI = (1280, 135, 385, 195)  # x, y, width, height
ANALYSIS_SIZE = (385, 195)  # width, height

SYMBOL_REGION = {
    "x0": 0.35,
    "x1": 0.88,
    "y0": 0.02,
    "y1": 0.86,
}

MIN_SYMBOL_AREA = 60
MAX_SYMBOL_AREA = 4000
MIN_SYMBOL_WIDTH = 5
MIN_SYMBOL_HEIGHT = 5
MAX_SYMBOL_WIDTH = 90
MAX_SYMBOL_HEIGHT = 125

MIN_SYMBOL_RATIO = 0.45
MAX_SYMBOL_RATIO = 1.80
MAX_ELONGATION_RATIO = 2.50
SYMBOL_BORDER_MARGIN = 8
MIN_SYMBOL_FILL = 0.15

BLACK_THRESHOLD = 130
MAX_FACE_CARD_AREA = 700

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp"}


def list_bank_images(image_bank: Path = DEFAULT_IMAGE_BANK) -> list[Path]:
    if not image_bank.exists():
        raise FileNotFoundError(f"Pasta do banco nao encontrada: {image_bank}")

    images = sorted(
        path
        for path in image_bank.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )

    if not images:
        raise FileNotFoundError(f"Nenhuma imagem encontrada em: {image_bank}")

    return images


def expected_value_from_filename(filename: str):
    value = Path(filename).stem.split("_", 1)[0].upper()

    if value == "A":
        return "A"

    if value in {"J", "Q", "K"}:
        return 10

    if value.isdigit():
        number = int(value)
        if 2 <= number <= 10:
            return number

    return "x"


def scale_roi_to_image(image: np.ndarray) -> tuple[int, int, int, int]:
    height, width = image.shape[:2]
    base_width, base_height = BASE_RESOLUTION
    scale_x = width / base_width
    scale_y = height / base_height

    x, y, w, h = BASE_CARD_ROI
    x = int(round(x * scale_x))
    y = int(round(y * scale_y))
    w = int(round(w * scale_x))
    h = int(round(h * scale_y))

    x = max(0, min(width - 1, x))
    y = max(0, min(height - 1, y))
    w = max(1, min(width - x, w))
    h = max(1, min(height - y, h))

    return x, y, w, h


def crop_card_by_roi(image: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    x, y, w, h = scale_roi_to_image(image)
    card = image[y : y + h, x : x + w].copy()
    card = cv2.resize(card, ANALYSIS_SIZE, interpolation=cv2.INTER_AREA)
    return card, (x, y, w, h)


def create_symbol_mask(region: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)

    red_1 = cv2.inRange(
        hsv,
        np.array([0, 50, 40], dtype=np.uint8),
        np.array([18, 255, 255], dtype=np.uint8),
    )
    red_2 = cv2.inRange(
        hsv,
        np.array([160, 50, 40], dtype=np.uint8),
        np.array([180, 255, 255], dtype=np.uint8),
    )
    black = (gray < BLACK_THRESHOLD).astype(np.uint8) * 255

    mask = cv2.bitwise_or(cv2.bitwise_or(red_1, red_2), black)
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8), iterations=1)


def analyze_symbols(card: np.ndarray) -> dict[str, object]:
    height, width = card.shape[:2]
    x0 = int(round(width * SYMBOL_REGION["x0"]))
    x1 = int(round(width * SYMBOL_REGION["x1"]))
    y0 = int(round(height * SYMBOL_REGION["y0"]))
    y1 = int(round(height * SYMBOL_REGION["y1"]))

    region = card[y0:y1, x0:x1].copy()
    mask = create_symbol_mask(region)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    symbols = []
    rejected = []
    total_area = 0.0
    largest_area = 0.0
    roi_height, roi_width = region.shape[:2]

    for contour_index, contour in enumerate(contours, start=1):
        area = float(cv2.contourArea(contour))
        x, y, w, h = cv2.boundingRect(contour)
        ratio = w / max(1, h)
        fill = area / max(1.0, float(w * h))
        rejection_reason = ""

        if area < MIN_SYMBOL_AREA:
            rejection_reason = "area pequena"
        elif area > MAX_SYMBOL_AREA:
            rejection_reason = "area grande"
        elif w < MIN_SYMBOL_WIDTH or h < MIN_SYMBOL_HEIGHT:
            rejection_reason = "fino"
        elif w > MAX_SYMBOL_WIDTH:
            rejection_reason = "largura max"
        elif h > MAX_SYMBOL_HEIGHT:
            rejection_reason = "altura max"
        elif ratio < MIN_SYMBOL_RATIO or ratio > MAX_SYMBOL_RATIO:
            rejection_reason = "proporcao"
        elif w > MAX_ELONGATION_RATIO * h or h > MAX_ELONGATION_RATIO * w:
            rejection_reason = "linha alongada"
        elif (
            x <= SYMBOL_BORDER_MARGIN
            or y <= SYMBOL_BORDER_MARGIN
            or x + w >= roi_width - SYMBOL_BORDER_MARGIN
            or y + h >= roi_height - SYMBOL_BORDER_MARGIN
        ):
            rejection_reason = "borda"
        elif fill < MIN_SYMBOL_FILL:
            rejection_reason = "preenchimento"

        item = {
            "indice": contour_index,
            "contorno": contour,
            "area": area,
            "proporcao": ratio,
            "preenchimento": fill,
            "bbox_local": (x, y, w, h),
            "bbox_global": (x0 + x, y0 + y, w, h),
        }

        if rejection_reason:
            item["motivo"] = rejection_reason
            rejected.append(item)
            continue

        symbols.append(item)
        total_area += area
        largest_area = max(largest_area, area)

    coverage = cv2.countNonZero(mask) / max(1, mask.shape[0] * mask.shape[1])

    return {
        "quantidade": len(symbols),
        "simbolos": symbols,
        "rejeitados": rejected,
        "maior_area": largest_area,
        "area_total": total_area,
        "cobertura": coverage,
        "mascara": mask,
        "regiao": region,
        "roi_simbolos": (x0, y0, x1 - x0, y1 - y0),
    }


def recognize_value_by_symbols(card: np.ndarray) -> tuple[object, dict[str, object]]:
    analysis = analyze_symbols(card)
    symbol_count = int(analysis["quantidade"])
    largest_area = float(analysis["maior_area"])
    rejected_count = len(analysis.get("rejeitados", []))

    if symbol_count == 1:
        value = "A"
        reason = "apenas 1 simbolo principal foi detectado, padrao de As"
    elif symbol_count >= 3 and largest_area > MAX_FACE_CARD_AREA:
        value = 10
        reason = "foi detectado um componente grande/complexo, padrao de face card"
    elif 3 <= symbol_count <= 6 and rejected_count >= 45:
        value = 10
        reason = "muitos contornos internos foram rejeitados, padrao de face card"
    elif 2 <= symbol_count <= 10:
        value = symbol_count
        reason = f"foram detectados {symbol_count} simbolos principais no centro da carta"
    elif symbol_count > 10:
        value = 10
        reason = "mais de 10 componentes relevantes foram detectados, interpretado como valor 10"
    else:
        value = "x"
        reason = "nao foram encontrados simbolos suficientes para reconhecer a carta"

    analysis["valor_reconhecido"] = value
    analysis["motivo"] = reason
    return value, analysis


def write_symbol_debug(
    original_image: np.ndarray,
    card: np.ndarray,
    card_roi: tuple[int, int, int, int],
    analysis: dict[str, object],
    output_path: Path,
) -> None:
    debug = card.copy()
    x0, y0, roi_w, roi_h = analysis["roi_simbolos"]
    cv2.rectangle(debug, (x0, y0), (x0 + roi_w, y0 + roi_h), (255, 0, 0), 2)

    for rejected in analysis.get("rejeitados", []):
        x, y, w, h = rejected["bbox_global"]
        reason = str(rejected.get("motivo", "rejeitado"))
        cv2.rectangle(debug, (x, y), (x + w, y + h), (0, 0, 255), 1)
        cv2.putText(
            debug,
            reason,
            (x, min(debug.shape[0] - 4, y + h + 12)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.33,
            (0, 0, 255),
            1,
            cv2.LINE_AA,
        )

    for index, symbol in enumerate(analysis["simbolos"], start=1):
        x, y, w, h = symbol["bbox_global"]
        cv2.rectangle(debug, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.putText(
            debug,
            str(index),
            (x, max(14, y - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 255, 0),
            1,
            cv2.LINE_AA,
        )

    text = f"Valor: {analysis['valor_reconhecido']} | Simbolos aceitos: {analysis['quantidade']}"
    cv2.rectangle(debug, (0, 0), (debug.shape[1], 30), (0, 0, 0), -1)
    cv2.putText(debug, text, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

    debug_original = original_image.copy()
    x, y, w, h = card_roi
    cv2.rectangle(debug_original, (x, y), (x + w, y + h), (0, 255, 255), 4)
    cv2.putText(
        debug_original,
        "ROI carta",
        (x, max(30, y - 10)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (0, 255, 255),
        2,
        cv2.LINE_AA,
    )

    output_path.parent.mkdir(exist_ok=True)
    cv2.imwrite(str(output_path), debug)
    cv2.imwrite(str(output_path.with_name(output_path.stem + "_mascara.png")), analysis["mascara"])


def process_image(
    image: np.ndarray,
    debug_name: str | None = None,
    debug_dir: Path = DEFAULT_DEBUG_DIR,
) -> tuple[object, dict[str, object]]:
    card, roi = crop_card_by_roi(image)
    value, analysis = recognize_value_by_symbols(card)

    if debug_name:
        debug_path = debug_dir / f"{debug_name}_debug.png"
        write_symbol_debug(image, card, roi, analysis, debug_path)

    result = {
        "valor": value,
        "roi_carta": roi,
        "carta": card,
        "analise": analysis,
    }
    return value, result


def rank_to_blackjack_value(rank: str) -> int:
    if rank == "A":
        return 11
    if rank in {"10", "J", "Q", "K"}:
        return 10
    try:
        return int(rank)
    except (TypeError, ValueError):
        return 0


def recognized_value_to_rank(value: object) -> str:
    if value == "A":
        return "A"
    if isinstance(value, int) and 2 <= value <= 10:
        return str(value)
    return "unknown"


def recognized_value_to_card(value: object, debug: dict[str, object] | None = None) -> dict[str, object]:
    rank = recognized_value_to_rank(value)
    card = {
        "rank": rank,
        "suit": "unknown",
        "card_id": None,
        "blackjack_value": rank_to_blackjack_value(rank),
        "rank_score": 1.0 if rank != "unknown" else 0.0,
        "suit_score": 0.0,
        "status": "ok" if rank != "unknown" else "unknown",
    }
    if debug is not None:
        card["debug"] = debug
    return card


def process_image_as_card(
    image: np.ndarray,
    debug_name: str | None = None,
    debug_dir: Path = DEFAULT_DEBUG_DIR,
) -> tuple[dict[str, object], dict[str, object]]:
    value, result = process_image(image, debug_name=debug_name, debug_dir=debug_dir)
    return recognized_value_to_card(value, result["analise"]), result


def capture_image_webcam(camera_index: int = WEBCAM_INDEX) -> np.ndarray | None:
    cap = cv2.VideoCapture(camera_index)

    if not cap.isOpened():
        print("Erro: webcam nao abriu.")
        return None

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, BASE_RESOLUTION[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, BASE_RESOLUTION[1])

    for _ in range(10):
        cap.read()

    window = "Webcam - ESPACO captura | ESC sai"

    while True:
        ok, frame = cap.read()

        if not ok or frame is None:
            cap.release()
            cv2.destroyWindow(window)
            print("Erro: nao foi possivel capturar imagem da webcam.")
            return None

        preview = frame.copy()
        x, y, w, h = scale_roi_to_image(preview)
        cv2.rectangle(preview, (x, y), (x + w, y + h), (0, 255, 255), 3)
        cv2.putText(
            preview,
            "Posicione a carta na ROI | ESPACO = capturar | ESC = sair",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )

        max_width = 1280
        scale = min(1.0, max_width / max(1, preview.shape[1]))
        if scale < 1.0:
            preview_show = cv2.resize(preview, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        else:
            preview_show = preview

        cv2.imshow(window, preview_show)
        key = cv2.waitKey(1) & 0xFF

        if key == 27:
            cap.release()
            cv2.destroyWindow(window)
            return None

        if key == 32:
            cap.release()
            cv2.destroyWindow(window)
            return frame.copy()


def read_single_card_from_camera(camera_index: int = WEBCAM_INDEX):
    image = capture_image_webcam(camera_index)
    if image is None:
        return "x"

    value, result = process_image(image, "webcam")
    analysis = result["analise"]

    print("Carta analisada:")
    print(f"- Valor final reconhecido: {value}")
    print(f"- Simbolos aceitos: {analysis['quantidade']}")
    print(f"- Contornos rejeitados: {len(analysis.get('rejeitados', []))}")
    print(f"- Maior area de simbolo: {analysis['maior_area']:.1f}")
    print(f"- Cobertura da mascara: {analysis['cobertura']:.3f}")
    print(f"- Motivo: {analysis['motivo']}")

    return value


def read_single_card_dict_from_camera(camera_index: int = WEBCAM_INDEX) -> dict[str, object]:
    value = read_single_card_from_camera(camera_index)
    return recognized_value_to_card(value)


def analyze_webcam(camera_index: int = WEBCAM_INDEX):
    value = read_single_card_from_camera(camera_index)
    print(value)
    return value


def evaluate_bank(
    image_bank: Path = DEFAULT_IMAGE_BANK,
    debug_dir: Path = DEFAULT_DEBUG_DIR,
    report_file: Path = DEFAULT_REPORT_FILE,
) -> dict[str, object]:
    images = list_bank_images(image_bank)
    debug_dir.mkdir(exist_ok=True)

    results = []
    hits = 0

    for path in images:
        image = cv2.imread(str(path))
        if image is None:
            continue

        expected = expected_value_from_filename(path.name)
        value, result = process_image(image, path.stem, debug_dir=debug_dir)
        hit = value == expected
        hits += int(hit)

        analysis = result["analise"]
        results.append(
            {
                "arquivo": path.name,
                "esperado": expected,
                "reconhecido": value,
                "acertou": hit,
                "quantidade_simbolos": analysis["quantidade"],
                "maior_area": analysis["maior_area"],
                "cobertura": analysis["cobertura"],
                "motivo": analysis["motivo"],
                "rejeitados": len(analysis.get("rejeitados", [])),
            }
        )

    total = len(results)
    rate = hits / total if total else 0

    lines = [
        "Arquivo | Esperado | Reconhecido | Acertou | Simbolos | Rejeitados | Maior area | Motivo"
    ]
    for item in results:
        status = "OK" if item["acertou"] else "ERRO"
        line = (
            f"{item['arquivo']} | {item['esperado']} | {item['reconhecido']} | "
            f"{status} | {item['quantidade_simbolos']} | {item['rejeitados']} | "
            f"{item['maior_area']:.1f} | {item['motivo']}"
        )
        lines.append(line)
        print(line)

    lines.append("")
    lines.append(f"Resultado final: {hits}/{total}")
    lines.append(f"Taxa de acerto: {rate * 100:.1f}%")
    report_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("Resultado final:")
    print(f"Acertos: {hits}/{total}")
    print(f"Taxa de acerto: {rate * 100:.1f}%")
    print(f"Relatorio salvo em: {report_file.name}")
    print(f"Debug salvo em: {debug_dir.name}/")

    return {"acertos": hits, "total": total, "taxa": rate, "resultados": results}


# Backwards-compatible Portuguese aliases for earlier scripts.
listar_imagens_banco = list_bank_images
extrair_valor_esperado = expected_value_from_filename
capturar_imagem_webcam = capture_image_webcam
escalar_roi_para_imagem = scale_roi_to_image
recortar_carta_por_roi = crop_card_by_roi
criar_mascara_simbolos = create_symbol_mask
analisar_simbolos = analyze_symbols
reconhecer_valor_por_simbolos = recognize_value_by_symbols
gerar_debug_simbolos = write_symbol_debug
processar_imagem = process_image
avaliar_banco = evaluate_bank
analisar_webcam = analyze_webcam
Ler_Carta_Camera = read_single_card_from_camera


def main():
    parser = argparse.ArgumentParser(description="Reconhece uma carta isolada pela camera ou por imagem.")
    parser.add_argument("--camera", type=int, default=WEBCAM_INDEX, help="Indice da camera OpenCV.")
    parser.add_argument("--image", type=Path, help="Imagem estatica para reconhecer.")
    parser.add_argument("--bank", type=Path, help="Pasta de imagens para avaliar.")
    parser.add_argument("--debug-name", default="imagem", help="Nome base dos arquivos de debug.")
    args = parser.parse_args()

    if args.bank:
        evaluate_bank(args.bank)
        return

    if args.image:
        image = cv2.imread(str(args.image))
        if image is None:
            raise FileNotFoundError(f"Nao foi possivel abrir a imagem: {args.image}")
        value, result = process_image(image, args.debug_name)
        print(value)
        print(result["analise"]["motivo"])
        return

    analyze_webcam(args.camera)


if __name__ == "__main__":
    main()
