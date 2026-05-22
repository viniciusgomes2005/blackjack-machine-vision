try:
    import cv2
except ModuleNotFoundError:
    cv2 = None


REQUESTED_RESOLUTIONS = ((1920, 1080), (1280, 720), (640, 480), (320, 240))


def _require_cv2():
    if cv2 is None:
        raise ModuleNotFoundError(
            "OpenCV nao esta instalado. Rode: pip install -r requirements.txt"
        )


def _backend_name(cap):
    try:
        return cap.getBackendName()
    except cv2.error:
        return "desconhecido"


def _effective_resolution(cap):
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    return width, height


def open_camera(camera_index=0, requested_resolutions=REQUESTED_RESOLUTIONS):
    """
    Abre a camera tentando resolucoes altas primeiro.

    Retorna um cv2.VideoCapture pronto para uso. A funcao imprime a camera,
    backend, resolucao solicitada e resolucao real aplicada para facilitar
    diagnostico de crop/zoom em cameras USB no Linux.
    """
    _require_cv2()

    print(f"Camera index: {camera_index}")
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        print(f"Aviso: nao foi possivel abrir a camera no indice {camera_index}.")
        return None

    print(f"OpenCV backend: {_backend_name(cap)}")

    last_success = None
    for requested_width, requested_height in requested_resolutions:
        print(f"Requested camera resolution: {requested_width}x{requested_height}")

        if hasattr(cv2, "CAP_PROP_FOURCC"):
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, requested_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, requested_height)

        ok, frame = cap.read()
        effective_width, effective_height = _effective_resolution(cap)
        print(f"Effective camera resolution: {effective_width}x{effective_height}")

        if ok and frame is not None:
            last_success = (requested_width, requested_height)
            if (
                effective_width >= int(requested_width * 0.9)
                and effective_height >= int(requested_height * 0.9)
            ):
                return cap

            print("Aviso: resolucao solicitada nao foi aplicada integralmente.")
        else:
            print("Aviso: camera abriu, mas nao retornou frame nessa resolucao.")

    if last_success is None:
        print("Erro: camera abriu, mas nao retornou frame em nenhuma resolucao testada.")
        print("Verifique se a camera esta ocupada por outro app, permissoes do Windows,")
        print("ou se o indice escolhido realmente corresponde a uma camera com imagem.")
        cap.release()
        return None

    width, height = last_success
    print(f"Usando a melhor resolucao disponivel apos solicitar {width}x{height}.")

    return cap
