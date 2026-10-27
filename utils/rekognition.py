# -*- coding: utf-8 -*-
"""Reconhecimento facial da chamada por foto, pelo Amazon Rekognition (região em AWS_REGION; hoje us-east-2, Ohio).

A conta foi criada pelo cadastro novo da AWS, que prende cada projeto na região
do país do endereço — Brasil cai em Ohio, e as outras regiões (inclusive São
Paulo) são negadas por SCP. Usar São Paulo exige ativar os recursos avançados
da conta.

Por que no servidor
-------------------
A primeira versão rodava no navegador (face-api) e dependia de cada celular:
aparelho fraco levava minutos, e navegador com proteção contra rastreamento
entregava a imagem alterada e não achava ninguém. Aqui o celular só manda a
foto; o servidor pergunta ao Rekognition e devolve os rostos.

O que fica onde
---------------
* Uma COLEÇÃO por academia (`<prefixo>-academia-<id>`), com os rostos de
  referência de cada aluno que autorizou: o da foto do cadastro e até
  `MAX_CHAMADA` rostos identificados na chamada. `ExternalImageId` = id do aluno.
* A foto da turma NÃO é guardada: vai para o Rekognition só para análise
  (DetectFaces / SearchFacesByImage não armazenam a imagem) e é descartada.
* A tabela `chamada_foto_rosto` liga FaceId ↔ aluno, para apagar tudo quando
  o consentimento é retirado.

Credenciais em .env: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION.
"""
import io
import os
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageOps

MAX_CHAMADA = 5          # rostos aprendidos na chamada, por aluno
LIMIAR_BUSCA = 70        # similaridade mínima que o Rekognition devolve
MARGEM_RECORTE = 0.45    # folga em volta do rosto ao recortar para a busca
LADO_MINIMO = 200        # rosto pequeno é ampliado até isto antes da busca
PARALELO = 4             # buscas simultâneas (cota da região: 5 por segundo)

_cliente = None
_colecoes_ok = set()


class ErroReconhecimento(Exception):
    """Falha falando com o Rekognition, com mensagem para mostrar na tela."""


def configurado():
    return bool(os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"))


def cliente():
    global _cliente
    if _cliente is None:
        import boto3
        from botocore.config import Config
        _cliente = boto3.client(
            "rekognition",
            region_name=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-2",
            # "adaptive" segura o ritmo sozinho quando a cota por segundo estoura.
            config=Config(retries={"mode": "adaptive", "max_attempts": 8},
                          connect_timeout=5, read_timeout=30),
        )
    return _cliente


def _erro(e):
    """Traduz o erro da AWS para algo que o professor entenda."""
    codigo = getattr(e, "response", {}).get("Error", {}).get("Code", "") if hasattr(e, "response") else ""
    if codigo in ("AccessDeniedException", "UnrecognizedClientException", "InvalidSignatureException"):
        return ErroReconhecimento("O reconhecimento não está autorizado na AWS (chave ou permissão). Avise o suporte.")
    if codigo in ("ProvisionedThroughputExceededException", "ThrottlingException"):
        return ErroReconhecimento("O reconhecimento está ocupado agora. Tente de novo em alguns segundos.")
    return ErroReconhecimento("Não foi possível falar com o reconhecimento agora. Tente de novo.")


def colecao(academia_id):
    prefixo = os.environ.get("REKOGNITION_PREFIXO", "unimaster")
    return f"{prefixo}-academia-{academia_id}"


def garantir_colecao(academia_id):
    nome = colecao(academia_id)
    if nome in _colecoes_ok:
        return nome
    from botocore.exceptions import ClientError
    try:
        cliente().create_collection(CollectionId=nome)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceAlreadyExistsException":
            raise _erro(e)
    _colecoes_ok.add(nome)
    return nome


# ------------------------------------------------------------------ imagem
def abrir(dados):
    """bytes ou caminho → imagem RGB já na orientação certa (EXIF do celular)."""
    img = Image.open(io.BytesIO(dados) if isinstance(dados, (bytes, bytearray)) else dados)
    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        fundo = Image.new("RGB", img.size, (128, 128, 128))
        fundo.paste(img.convert("RGBA"), mask=img.convert("RGBA").getchannel("A"))
        img = fundo
    return img


def jpeg(img, max_lado=None, qualidade=90):
    if max_lado and max(img.size) > max_lado:
        img = img.copy()
        img.thumbnail((max_lado, max_lado))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=qualidade)
    return buf.getvalue()


def recortar_rosto(img, box):
    """Rosto com folga, ampliado se for pequeno (rosto do fundo da foto)."""
    x, y, w, h = box
    m = max(w, h) * MARGEM_RECORTE
    x0, y0 = max(0, int(x - m)), max(0, int(y - m))
    x1, y1 = min(img.width, int(x + w + m)), min(img.height, int(y + h + m))
    r = img.crop((x0, y0, x1, y1))
    menor = min(r.size)
    if menor < LADO_MINIMO:
        f = LADO_MINIMO / float(menor)
        r = r.resize((int(r.width * f), int(r.height * f)), Image.LANCZOS)
    return r


# ---------------------------------------------------------------- operações
def indexar(academia_id, aluno_id, img):
    """Guarda o rosto principal da imagem como referência do aluno. → FaceId ou None."""
    from botocore.exceptions import ClientError
    nome = garantir_colecao(academia_id)
    try:
        r = cliente().index_faces(
            CollectionId=nome, Image={"Bytes": jpeg(img, 1600)}, ExternalImageId=str(aluno_id),
            MaxFaces=1, QualityFilter="NONE", DetectionAttributes=[],
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "InvalidParameterException":
            return None      # imagem sem rosto
        raise _erro(e)
    recs = r.get("FaceRecords") or []
    return recs[0]["Face"]["FaceId"] if recs else None


def apagar(academia_id, face_ids):
    ids = [f for f in face_ids if f]
    if not ids:
        return
    from botocore.exceptions import ClientError
    try:
        for i in range(0, len(ids), 1000):
            cliente().delete_faces(CollectionId=colecao(academia_id), FaceIds=ids[i:i + 1000])
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise _erro(e)


def _detectar_em(img):
    from botocore.exceptions import ClientError
    try:
        r = cliente().detect_faces(Image={"Bytes": jpeg(img, 4096, 88)}, Attributes=["DEFAULT"])
    except ClientError as e:
        raise _erro(e)
    out = []
    for f in r.get("FaceDetails") or []:
        b = f["BoundingBox"]
        out.append({"x": b["Left"] * img.width, "y": b["Top"] * img.height,
                    "w": b["Width"] * img.width, "h": b["Height"] * img.height,
                    "conf": f.get("Confidence", 0)})
    return out


def _sobreposicao(a, b):
    x1, y1 = max(a["x"], b["x"]), max(a["y"], b["y"])
    x2, y2 = min(a["x"] + a["w"], b["x"] + b["w"]), min(a["y"] + a["h"], b["y"] + b["h"])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    menor = min(a["w"] * a["h"], b["w"] * b["h"]) or 1
    return inter / menor


def detectar(img):
    """Rostos da foto da turma, em pixels da imagem recebida.

    O DetectFaces devolve até 100 rostos. Em turma grande ou com rosto pequeno,
    passa também por 4 quadrantes sobrepostos (cada um "ampliado" para o
    serviço) e junta sem repetir.
    """
    rostos = _detectar_em(img)
    larguras = sorted(r["w"] for r in rostos)
    mediana = larguras[len(larguras) // 2] if larguras else 0
    if not rostos or len(rostos) >= 12 or mediana < img.width * 0.05:
        W, H = img.size
        tw, th = int(W * 0.6), int(H * 0.6)
        for (x, y) in [(0, 0), (W - tw, 0), (0, H - th), (W - tw, H - th)]:
            for r in _detectar_em(img.crop((x, y, x + tw, y + th))):
                # Rosto cortado na borda interna do quadrante: o vizinho o pega inteiro.
                if (r["x"] < 2 and x > 0) or (r["y"] < 2 and y > 0) or \
                   (r["x"] + r["w"] > tw - 2 and x + tw < W) or (r["y"] + r["h"] > th - 2 and y + th < H):
                    continue
                r["x"] += x
                r["y"] += y
                rostos.append(r)
    rostos.sort(key=lambda r: -r["conf"])
    ficam = []
    for r in rostos:
        if not any(_sobreposicao(r, f) > 0.5 for f in ficam):
            ficam.append(r)
    return ficam


def _buscar_um(nome, img):
    from botocore.exceptions import ClientError
    try:
        r = cliente().search_faces_by_image(
            CollectionId=nome, Image={"Bytes": jpeg(img, 800)}, MaxFaces=10,
            FaceMatchThreshold=LIMIAR_BUSCA, QualityFilter="NONE",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "InvalidParameterException":
            return []        # o recorte não tem rosto que o serviço aceite
        raise _erro(e)
    melhor = {}
    for m in r.get("FaceMatches") or []:
        aid = m["Face"].get("ExternalImageId")
        if aid and (aid not in melhor or m["Similarity"] > melhor[aid]):
            melhor[aid] = m["Similarity"]
    return sorted(({"id": k, "sim": round(v, 1)} for k, v in melhor.items()), key=lambda m: -m["sim"])


def buscar(academia_id, img, rostos):
    """Para cada rosto, os alunos parecidos da coleção da academia."""
    nome = garantir_colecao(academia_id)
    recortes = [recortar_rosto(img, (r["x"], r["y"], r["w"], r["h"])) for r in rostos]
    with ThreadPoolExecutor(max_workers=PARALELO) as ex:
        return list(ex.map(lambda rc: _buscar_um(nome, rc), recortes))
