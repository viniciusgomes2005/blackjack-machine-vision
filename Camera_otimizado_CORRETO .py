from pathlib import Path
import cv2
import numpy as np

# ============================================================
# CONFIGURACOES PRINCIPAIS
# ============================================================
PASTA_BASE = Path(__file__).resolve().parent
CAMINHO_BANCO = PASTA_BASE / "Base_de_dado_renomeada"
PASTA_DEBUG = PASTA_BASE / "debug_reconhecimento_otimizado"
ARQUIVO_RELATORIO = PASTA_BASE / "relatorio_reconhecimento_otimizado.txt"

# Quando Base_de_dado=True, o codigo avalia todas as imagens do banco.
# Quando Base_de_dado=False, o codigo abre a webcam e espera ESPACO para capturar.
Base_de_dado = False
MODO_AVALIACAO_BANCO = Base_de_dado
MODO_WEBCAM = not Base_de_dado
WEBCAM_INDEX = 0

# ROI calibrada para as imagens 2560 x 1440 do banco.
# A carta fica sempre na rampa amarela, na parte superior da imagem.
# O codigo escala essa ROI automaticamente se a resolucao for diferente.
RESOLUCAO_BASE = (2560, 1440)  # largura, altura
ROI_CARTA_BASE = (1280, 135, 385, 195)  # x, y, largura, altura

# Tamanho padrao usado para analisar simbolos; manter fixo deixa os filtros estaveis.
TAMANHO_ANALISE = (385, 195)  # largura, altura

# Regiao interna da carta onde ficam os simbolos principais.
# Como a carta esta inclinada na rampa, essa regiao pega o lado direito/central,
# onde aparecem os simbolos em todas as cartas do banco.
REGIAO_SIMBOLOS = {
    "x0": 0.35,
    "x1": 0.88,
    "y0": 0.02,
    # Evita pegar a borda inferior da rampa/carta como simbolo.
    "y1": 0.86,
}

# Filtros dos contornos dos simbolos no tamanho TAMANHO_ANALISE.
AREA_MIN_SIMBOLO = 60
AREA_MAX_SIMBOLO = 4000
LARGURA_MIN_SIMBOLO = 5
ALTURA_MIN_SIMBOLO = 5

# Limites maximos do retangulo do simbolo.
# Use esses valores para impedir que bordas grandes da rampa/carta sejam aceitas.
# Se uma linha/borda longa estiver sendo contada como simbolo, reduza LARGURA_MAX_SIMBOLO.
# Se uma linha/borda alta estiver sendo contada como simbolo, reduza ALTURA_MAX_SIMBOLO.
LARGURA_MAX_SIMBOLO = 90
ALTURA_MAX_SIMBOLO = 125

# Filtros para evitar que bordas finas da rampa/carta sejam contadas como simbolos.
# Um simbolo valido deve ser compacto, não uma linha longa e fina.
PROPORCAO_MIN_SIMBOLO = 0.45       # w/h minimo
PROPORCAO_MAX_SIMBOLO = 1.80       # w/h maximo
RELACAO_MAX_ALONGADA = 2.50        # rejeita w > 2.5*h ou h > 2.5*w
MARGEM_BORDA_SIMBOLO = 8           # rejeita contornos grudados na borda da ROI
PREENCHIMENTO_MIN_SIMBOLO = 0.15   # area_contorno/(w*h) minimo

LIMIAR_PRETO = 130
MAX_AREA_FACE_CARD = 700

EXTENSOES_IMAGEM = {".jpg", ".jpeg", ".png", ".bmp"}


# ============================================================
# FUNCOES DE ENTRADA / SAIDA
# ============================================================
def listar_imagens_banco(caminho_banco: Path) -> list[Path]:
    if not caminho_banco.exists():
        raise FileNotFoundError(f"Pasta do banco nao encontrada: {caminho_banco}")

    imagens = sorted(
        arquivo
        for arquivo in caminho_banco.iterdir()
        if arquivo.is_file() and arquivo.suffix.lower() in EXTENSOES_IMAGEM
    )

    if not imagens:
        raise FileNotFoundError(f"Nenhuma imagem encontrada em: {caminho_banco}")

    return imagens


def extrair_valor_esperado(nome_arquivo: str):
    valor = Path(nome_arquivo).stem.split("_", 1)[0].upper()

    if valor == "A":
        return "A"

    if valor in {"J", "Q", "K"}:
        return 10

    if valor.isdigit():
        numero = int(valor)
        if 2 <= numero <= 10:
            return numero

    return "x"


def capturar_imagem_webcam() -> np.ndarray | None:
    cap = cv2.VideoCapture(WEBCAM_INDEX)

    if not cap.isOpened():
        print("Erro: webcam nao abriu.")
        return None

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, RESOLUCAO_BASE[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, RESOLUCAO_BASE[1])

    for _ in range(10):
        cap.read()

    janela = "Webcam - ESPACO captura | ESC sai"

    while True:
        ok, frame = cap.read()

        if not ok or frame is None:
            cap.release()
            cv2.destroyWindow(janela)
            print("Erro: nao foi possivel capturar imagem da webcam.")
            return None

        preview = frame.copy()
        x, y, w, h = escalar_roi_para_imagem(preview)
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

        largura_max = 1280
        escala = min(1.0, largura_max / max(1, preview.shape[1]))
        if escala < 1.0:
            preview_show = cv2.resize(preview, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA)
        else:
            preview_show = preview

        cv2.imshow(janela, preview_show)
        tecla = cv2.waitKey(1) & 0xFF

        if tecla == 27:
            cap.release()
            cv2.destroyWindow(janela)
            return None

        if tecla == 32:
            cap.release()
            cv2.destroyWindow(janela)
            return frame.copy()


# ============================================================
# RECORTE DA CARTA
# ============================================================
def escalar_roi_para_imagem(imagem: np.ndarray) -> tuple[int, int, int, int]:
    altura, largura = imagem.shape[:2]
    largura_base, altura_base = RESOLUCAO_BASE
    escala_x = largura / largura_base
    escala_y = altura / altura_base

    x, y, w, h = ROI_CARTA_BASE
    x = int(round(x * escala_x))
    y = int(round(y * escala_y))
    w = int(round(w * escala_x))
    h = int(round(h * escala_y))

    x = max(0, min(largura - 1, x))
    y = max(0, min(altura - 1, y))
    w = max(1, min(largura - x, w))
    h = max(1, min(altura - y, h))

    return x, y, w, h


def recortar_carta_por_roi(imagem: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    x, y, w, h = escalar_roi_para_imagem(imagem)
    carta = imagem[y : y + h, x : x + w].copy()
    carta = cv2.resize(carta, TAMANHO_ANALISE, interpolation=cv2.INTER_AREA)
    return carta, (x, y, w, h)


# ============================================================
# DETECCAO DE SIMBOLOS
# ============================================================
def criar_mascara_simbolos(regiao: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(regiao, cv2.COLOR_BGR2HSV)
    cinza = cv2.cvtColor(regiao, cv2.COLOR_BGR2GRAY)

    # Vermelho das cartas de copas/ouros.
    vermelho_1 = cv2.inRange(
        hsv,
        np.array([0, 50, 40], dtype=np.uint8),
        np.array([18, 255, 255], dtype=np.uint8),
    )
    vermelho_2 = cv2.inRange(
        hsv,
        np.array([160, 50, 40], dtype=np.uint8),
        np.array([180, 255, 255], dtype=np.uint8),
    )

    # Preto das cartas de espadas/paus.
    preto = (cinza < LIMIAR_PRETO).astype(np.uint8) * 255

    mascara = cv2.bitwise_or(cv2.bitwise_or(vermelho_1, vermelho_2), preto)
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8), iterations=1)
    return mascara


def analisar_simbolos(carta: np.ndarray) -> dict[str, object]:
    altura, largura = carta.shape[:2]
    x0 = int(round(largura * REGIAO_SIMBOLOS["x0"]))
    x1 = int(round(largura * REGIAO_SIMBOLOS["x1"]))
    y0 = int(round(altura * REGIAO_SIMBOLOS["y0"]))
    y1 = int(round(altura * REGIAO_SIMBOLOS["y1"]))

    regiao = carta[y0:y1, x0:x1].copy()
    mascara = criar_mascara_simbolos(regiao)

    contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    simbolos = []
    rejeitados = []
    area_total = 0.0
    maior_area = 0.0
    altura_roi, largura_roi = regiao.shape[:2]

    for indice_contorno, contorno in enumerate(contornos, start=1):
        area = float(cv2.contourArea(contorno))
        x, y, w, h = cv2.boundingRect(contorno)
        proporcao = w / max(1, h)
        preenchimento = area / max(1.0, float(w * h))
        motivo_rejeicao = ""

        # 1) Area coerente de simbolo.
        if area < AREA_MIN_SIMBOLO:
            motivo_rejeicao = "area pequena"
        elif area > AREA_MAX_SIMBOLO:
            motivo_rejeicao = "area grande"

        # 2) Dimensoes minimas e maximas.
        elif w < LARGURA_MIN_SIMBOLO or h < ALTURA_MIN_SIMBOLO:
            motivo_rejeicao = "fino"
        elif w > LARGURA_MAX_SIMBOLO:
            motivo_rejeicao = "largura max"
        elif h > ALTURA_MAX_SIMBOLO:
            motivo_rejeicao = "altura max"

        # 3) Proporcao compacta. Evita linhas horizontais/verticais.
        elif proporcao < PROPORCAO_MIN_SIMBOLO or proporcao > PROPORCAO_MAX_SIMBOLO:
            motivo_rejeicao = "proporcao"
        elif w > RELACAO_MAX_ALONGADA * h or h > RELACAO_MAX_ALONGADA * w:
            motivo_rejeicao = "linha alongada"

        # 4) Evita bordas da ROI/rampa/carta.
        elif (
            x <= MARGEM_BORDA_SIMBOLO
            or y <= MARGEM_BORDA_SIMBOLO
            or x + w >= largura_roi - MARGEM_BORDA_SIMBOLO
            or y + h >= altura_roi - MARGEM_BORDA_SIMBOLO
        ):
            motivo_rejeicao = "borda"

        # 5) Evita contornos vazados/fracos demais.
        elif preenchimento < PREENCHIMENTO_MIN_SIMBOLO:
            motivo_rejeicao = "preenchimento"

        if motivo_rejeicao:
            rejeitados.append(
                {
                    "indice": indice_contorno,
                    "contorno": contorno,
                    "area": area,
                    "proporcao": proporcao,
                    "preenchimento": preenchimento,
                    "bbox_local": (x, y, w, h),
                    "bbox_global": (x0 + x, y0 + y, w, h),
                    "motivo": motivo_rejeicao,
                }
            )
            continue

        simbolos.append(
            {
                "indice": indice_contorno,
                "contorno": contorno,
                "area": area,
                "proporcao": proporcao,
                "preenchimento": preenchimento,
                "bbox_local": (x, y, w, h),
                "bbox_global": (x0 + x, y0 + y, w, h),
            }
        )
        area_total += area
        maior_area = max(maior_area, area)

    cobertura = cv2.countNonZero(mascara) / max(1, mascara.shape[0] * mascara.shape[1])

    return {
        "quantidade": len(simbolos),
        "simbolos": simbolos,
        "rejeitados": rejeitados,
        "maior_area": maior_area,
        "area_total": area_total,
        "cobertura": cobertura,
        "mascara": mascara,
        "regiao": regiao,
        "roi_simbolos": (x0, y0, x1 - x0, y1 - y0),
    }


# ============================================================
# CLASSIFICACAO DA CARTA
# ============================================================
def reconhecer_valor_por_simbolos(carta: np.ndarray) -> tuple[object, dict[str, object]]:
    analise = analisar_simbolos(carta)
    quantidade = int(analise["quantidade"])
    maior_area = float(analise["maior_area"])

    rejeitados = len(analise.get("rejeitados", []))

    if quantidade == 1:
        valor = "A"
        motivo = "apenas 1 simbolo principal foi detectado, padrao de As"
    elif quantidade >= 3 and maior_area > MAX_AREA_FACE_CARD:
        valor = 10
        motivo = "foi detectado um componente grande/complexo, padrao de face card"
    elif 3 <= quantidade <= 6 and rejeitados >= 45:
        valor = 10
        motivo = "muitos contornos internos foram rejeitados, padrao de face card"
    elif 2 <= quantidade <= 10:
        valor = quantidade
        motivo = f"foram detectados {quantidade} simbolos principais no centro da carta"
    elif quantidade > 10:
        valor = 10
        motivo = "mais de 10 componentes relevantes foram detectados, interpretado como valor 10"
    else:
        valor = "x"
        motivo = "nao foram encontrados simbolos suficientes para reconhecer a carta"

    analise["valor_reconhecido"] = valor
    analise["motivo"] = motivo
    return valor, analise


# ============================================================
# DEBUG VISUAL
# ============================================================
def gerar_debug_simbolos(
    imagem_original: np.ndarray,
    carta: np.ndarray,
    roi_carta: tuple[int, int, int, int],
    analise: dict[str, object],
    caminho_saida: Path,
) -> None:
    debug = carta.copy()
    x0, y0, w_roi, h_roi = analise["roi_simbolos"]

    cv2.rectangle(debug, (x0, y0), (x0 + w_roi, y0 + h_roi), (255, 0, 0), 2)

    # Rejeitados em vermelho: normalmente sao bordas, linhas finas ou ruido.
    for rejeitado in analise.get("rejeitados", []):
        x, y, w, h = rejeitado["bbox_global"]
        motivo = str(rejeitado.get("motivo", "rejeitado"))
        cv2.rectangle(debug, (x, y), (x + w, y + h), (0, 0, 255), 1)
        cv2.putText(
            debug,
            motivo,
            (x, min(debug.shape[0] - 4, y + h + 12)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.33,
            (0, 0, 255),
            1,
            cv2.LINE_AA,
        )

    # Aceitos em verde: estes sao os simbolos realmente contados.
    for indice, simbolo in enumerate(analise["simbolos"], start=1):
        x, y, w, h = simbolo["bbox_global"]
        cv2.rectangle(debug, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.putText(
            debug,
            str(indice),
            (x, max(14, y - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 255, 0),
            1,
            cv2.LINE_AA,
        )

    texto = f"Valor: {analise['valor_reconhecido']} | Simbolos aceitos: {analise['quantidade']}"
    cv2.rectangle(debug, (0, 0), (debug.shape[1], 30), (0, 0, 0), -1)
    cv2.putText(debug, texto, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

    # Debug da imagem original mostrando a ROI usada.
    debug_original = imagem_original.copy()
    x, y, w, h = roi_carta
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

    caminho_saida.parent.mkdir(exist_ok=True)
    cv2.imwrite(str(caminho_saida), debug)
    # A imagem original com ROI pode ser pesada; salve apenas quando for necessario depurar a localizacao.
    # cv2.imwrite(str(caminho_saida.with_name(caminho_saida.stem + "_original_roi.png")), debug_original)
    cv2.imwrite(str(caminho_saida.with_name(caminho_saida.stem + "_mascara.png")), analise["mascara"])


# ============================================================
# PROCESSAMENTO
# ============================================================
def processar_imagem(imagem: np.ndarray, nome_debug: str | None = None) -> tuple[object, dict[str, object]]:
    carta, roi = recortar_carta_por_roi(imagem)
    valor, analise = reconhecer_valor_por_simbolos(carta)

    if nome_debug:
        caminho_debug = PASTA_DEBUG / f"{nome_debug}_debug.png"
        gerar_debug_simbolos(imagem, carta, roi, analise, caminho_debug)

    resultado = {
        "valor": valor,
        "roi_carta": roi,
        "carta": carta,
        "analise": analise,
    }
    return valor, resultado


def avaliar_banco() -> dict[str, object]:
    imagens = listar_imagens_banco(CAMINHO_BANCO)
    PASTA_DEBUG.mkdir(exist_ok=True)

    resultados = []
    acertos = 0

    for arquivo in imagens:
        imagem = cv2.imread(str(arquivo))
        if imagem is None:
            continue

        esperado = extrair_valor_esperado(arquivo.name)
        valor, resultado = processar_imagem(imagem, arquivo.stem)
        acertou = valor == esperado
        acertos += int(acertou)

        analise = resultado["analise"]
        resultados.append(
            {
                "arquivo": arquivo.name,
                "esperado": esperado,
                "reconhecido": valor,
                "acertou": acertou,
                "quantidade_simbolos": analise["quantidade"],
                "maior_area": analise["maior_area"],
                "cobertura": analise["cobertura"],
                "motivo": analise["motivo"],
                "rejeitados": len(analise.get("rejeitados", [])),
            }
        )

    total = len(resultados)
    taxa = acertos / total if total else 0

    linhas = []
    linhas.append("Arquivo | Esperado | Reconhecido | Acertou | Simbolos | Rejeitados | Maior area | Motivo")
    for item in resultados:
        status = "OK" if item["acertou"] else "ERRO"
        linha = (
            f"{item['arquivo']} | {item['esperado']} | {item['reconhecido']} | "
            f"{status} | {item['quantidade_simbolos']} | {item['rejeitados']} | {item['maior_area']:.1f} | {item['motivo']}"
        )
        linhas.append(linha)
        print(linha)

    linhas.append("")
    linhas.append(f"Resultado final: {acertos}/{total}")
    linhas.append(f"Taxa de acerto: {taxa * 100:.1f}%")
    ARQUIVO_RELATORIO.write_text("\n".join(linhas) + "\n", encoding="utf-8")

    print("Resultado final:")
    print(f"Acertos: {acertos}/{total}")
    print(f"Taxa de acerto: {taxa * 100:.1f}%")
    print(f"Relatorio salvo em: {ARQUIVO_RELATORIO.name}")
    print(f"Debug salvo em: {PASTA_DEBUG.name}/")

    return {"acertos": acertos, "total": total, "taxa": taxa, "resultados": resultados}


def analisar_webcam() -> object:
    imagem = capturar_imagem_webcam()
    if imagem is None:
        print("x")
        return "x"

    valor, resultado = processar_imagem(imagem, "webcam")
    analise = resultado["analise"]

    print("Carta analisada:")
    print(f"- Valor final reconhecido: {valor}")
    print(f"- Simbolos aceitos: {analise['quantidade']}")
    print(f"- Contornos rejeitados: {len(analise.get('rejeitados', []))}")
    print(f"- Maior area de simbolo: {analise['maior_area']:.1f}")
    print(f"- Cobertura da mascara: {analise['cobertura']:.3f}")
    print(f"- Motivo: {analise['motivo']}")
    print(valor)
    return valor


def main() -> None:
    if Base_de_dado:
        avaliar_banco()
    else:
        analisar_webcam()


if __name__ == "__main__":
    main()
