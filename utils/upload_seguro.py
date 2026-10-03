"""
Validação segura de uploads: extensão + magic bytes (conteúdo real do arquivo).
Uso:
    from utils.upload_seguro import validar_upload, UploadInvalido

    try:
        ext = validar_upload(file_storage, categorias=["imagem"])
    except UploadInvalido as e:
        flash(str(e), "danger")
"""
import os
from werkzeug.utils import secure_filename

# ── Magic bytes por tipo ────────────────────────────────────────────────────
_SIGNATURES: list[tuple[bytes, str, str]] = [
    # (prefixo_hex, extensao_normalizada, tipo_legivel)
    (b"\xff\xd8\xff",                   "jpg",  "JPEG"),
    (b"\x89PNG\r\n\x1a\n",              "png",  "PNG"),
    (b"GIF87a",                          "gif",  "GIF"),
    (b"GIF89a",                          "gif",  "GIF"),
    (b"RIFF",                            "webp", "WebP"),   # precisa checar bytes 8-12 = WEBP
    (b"%PDF",                            "pdf",  "PDF"),
    (b"PK\x03\x04",                      "xlsx", "XLSX/ZIP"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1","xls",  "XLS"),
]

# HEIC/HEIF é o formato padrão da câmera do iPhone. Não entra na whitelist —
# o navegador não exibe em <img> fora do Safari, e converter exigiria uma
# dependência nova. Mas é reconhecido aqui para a mensagem dizer o que fazer,
# em vez de um "tipo não permitido" que não ajuda ninguém.
_HEIC_MARCAS = (b"ftypheic", b"ftypheix", b"ftyphevc", b"ftypmif1", b"ftypmsf1")


MENSAGEM_HEIC = (
    "Esta foto está no formato HEIC, do iPhone, que o navegador não exibe. "
    "No iPhone, vá em Ajustes › Câmera › Formatos e escolha "
    "\u201cMais Compatível\u201d, ou compartilhe a foto como JPEG."
)


def _eh_heic(header: bytes) -> bool:
    return any(marca in header[:24] for marca in _HEIC_MARCAS)

# Categorias pré-definidas de tipos permitidos
_CATEGORIAS: dict[str, set[str]] = {
    "imagem":    {"jpg", "jpeg", "png", "gif", "webp"},
    "documento": {"pdf"},
    "planilha":  {"xlsx", "xls"},
    "comprovante": {"jpg", "jpeg", "png", "pdf", "webp"},
    "pdf":       {"pdf"},
}


class UploadInvalido(ValueError):
    pass


def _detectar_extensao_real(header: bytes) -> str | None:
    """Retorna a extensão real do arquivo pelos magic bytes, ou None se desconhecido."""
    for sig, ext, _ in _SIGNATURES:
        if header.startswith(sig):
            if ext == "webp":
                # WebP: bytes 8-12 devem ser b"WEBP"
                if header[8:12] == b"WEBP":
                    return "webp"
                # RIFF mas não WEBP: recusar
                return None
            return ext
    return None


# As telas prometem "até 5 MB". Sem esta checagem a promessa era só texto: não
# havia limite nenhum, nem aqui nem no Flask, e uma foto de 40 MB entrava.
#
# O limite é POR CATEGORIA, e não um número só: foto de cadastro em 5 MB é
# generoso, mas o mesmo teto derrubaria o calendário da federação em PDF e a
# planilha de inscrições, que passam disso com facilidade e sempre passaram.
TAMANHO_MAX_MB = 5

_LIMITE_POR_CATEGORIA: dict[str, float] = {
    "imagem": 5,
    "comprovante": 10,
    "documento": 25,
    "pdf": 25,
    "planilha": 25,
}


def _limite_das_categorias(categorias: list[str] | None) -> float:
    """O maior limite entre as categorias aceitas.

    Maior, e não menor: quem aceita comprovante em JPG ou PDF não deve recusar
    o PDF de 8 MB por causa do teto da foto.
    """
    valores = [_LIMITE_POR_CATEGORIA[c] for c in (categorias or [])
               if c in _LIMITE_POR_CATEGORIA]
    return max(valores) if valores else TAMANHO_MAX_MB


def _tamanho_mb(file_storage) -> float:
    """Tamanho do upload, sem carregar o arquivo na memória."""
    fluxo = file_storage.stream
    posicao = fluxo.tell()
    fluxo.seek(0, os.SEEK_END)
    tamanho = fluxo.tell()
    fluxo.seek(posicao)
    return tamanho / (1024 * 1024)


def validar_upload(
    file_storage,
    categorias: list[str] | None = None,
    extensoes_extras: set[str] | None = None,
    tamanho_max_mb: float | None = None,
) -> str:
    """
    Valida o arquivo enviado pelo usuário.
    - Verifica se há um arquivo real
    - Sanitiza o nome
    - Checa extensão contra whitelist
    - Checa magic bytes (conteúdo real)

    Retorna a extensão normalizada (ex: "jpg").
    Lança UploadInvalido em caso de falha.
    """
    if not file_storage or not file_storage.filename:
        raise UploadInvalido("Nenhum arquivo enviado.")

    safe_name = secure_filename(file_storage.filename)
    if not safe_name:
        raise UploadInvalido("Nome de arquivo inválido.")

    limite = (_limite_das_categorias(categorias) if tamanho_max_mb is None
              else tamanho_max_mb)
    tamanho = _tamanho_mb(file_storage)
    if tamanho > limite:
        raise UploadInvalido(
            f"Arquivo de {tamanho:.1f} MB — o limite é {limite:.0f} MB. "
            "Reduza o arquivo e tente de novo.")

    # Extensão declarada
    _, raw_ext = os.path.splitext(safe_name)
    ext_declarada = raw_ext.lstrip(".").lower()
    if ext_declarada == "jpeg":
        ext_declarada = "jpg"

    # Montar whitelist
    permitidas: set[str] = set()
    for cat in (categorias or []):
        permitidas |= _CATEGORIAS.get(cat, set())
    if extensoes_extras:
        permitidas |= extensoes_extras

    if not permitidas:
        raise UploadInvalido("Nenhuma categoria de arquivo definida.")

    if ext_declarada not in permitidas:
        # HEIC primeiro: é o padrão da câmera do iPhone e responder só
        # "extensão não permitida" deixa a pessoa sem saber o que fazer.
        if ext_declarada in ("heic", "heif"):
            raise UploadInvalido(MENSAGEM_HEIC)
        lista = ", ".join(sorted(permitidas))
        raise UploadInvalido(f"Extensão '.{ext_declarada}' não permitida. Use: {lista}.")

    # Ler os primeiros 16 bytes para magic bytes (sem consumir o stream)
    # 32 bytes: o JPEG se identifica nos 3 primeiros, mas o HEIC guarda o
    # "ftyp" a partir do byte 4 e precisa de mais folga.
    cabecalho = file_storage.stream.read(32)
    file_storage.stream.seek(0)

    if not cabecalho:
        raise UploadInvalido("Arquivo vazio.")

    ext_real = _detectar_extensao_real(cabecalho)

    # Extensões que não têm magic bytes reconhecíveis mas são baixo risco (texto simples, Office antigo)
    _SEM_MAGIC = {"txt", "doc", "docx", "rar", "zip"}

    if ext_real is None:
        # Aceitar se for extensão de texto/formato sem assinatura binária e estiver na whitelist
        if ext_declarada in _SEM_MAGIC and ext_declarada in permitidas:
            return ext_declarada
        if _eh_heic(cabecalho) or ext_declarada in ("heic", "heif"):
            raise UploadInvalido(MENSAGEM_HEIC)
        raise UploadInvalido("Tipo de arquivo não reconhecido ou não permitido.")

    # Normalizar jpeg→jpg para comparação
    ext_real_norm = "jpg" if ext_real == "jpeg" else ext_real

    # Para xlsx/xls, o magic bytes de ZIP cobre ambos — aceitar se a ext declarada for planilha
    if ext_real_norm == "xlsx" and ext_declarada in {"xlsx", "xls"}:
        pass
    elif ext_real_norm not in permitidas:
        raise UploadInvalido(
            f"Conteúdo do arquivo não corresponde à extensão '.{ext_declarada}'. "
            f"O arquivo parece ser do tipo '{ext_real_norm}'."
        )

    return ext_declarada


def nome_seguro(prefixo: str, ext: str, sufixo_uuid: bool = True) -> str:
    """Gera nome de arquivo seguro com prefixo + UUID."""
    import uuid
    parte_uuid = f"_{uuid.uuid4().hex[:12]}" if sufixo_uuid else ""
    return f"{prefixo}{parte_uuid}.{ext}"
