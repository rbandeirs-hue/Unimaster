"""Escolher a foto do computador ou da galeria.

O que motivou
-------------
Os campos de foto tinham `capture="environment"`. No celular, esse atributo faz
o navegador abrir a câmera direto e sumir com a opção de escolher da galeria —
mesmo nas telas cujo botão dizia "Tirar foto OU escolher arquivo". A promessa
estava no rótulo e o atributo a desfazia.

E a validação recusava em silêncio: foto do iPhone (HEIC) ou grande demais
simplesmente não era salva, sem mensagem nenhuma.

Uso:  PYTHONPATH=. .venv/bin/python tests/test_upload_foto.py
"""
import io as _io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from werkzeug.datastructures import FileStorage          # noqa: E402
from utils.upload_seguro import (validar_upload,         # noqa: E402
                                 UploadInvalido, TAMANHO_MAX_MB)

_falhas = []

# Telas em que o usuário escolhe uma imagem. A lista é explícita de propósito:
# se alguém acrescentar `capture` de novo em qualquer uma, o teste acusa.
TELAS_COM_FOTO = [
    "templates/registro_presenca.html",
    "templates/alunos/editar_aluno.html",
    "templates/alunos/cadastro_aluno.html",
    "templates/precadastro/editar.html",
    "templates/precadastro/aula_experimental_publica.html",
    "templates/usuarios/meu_perfil.html",
    "templates/usuarios/editar_usuario.html",
    "templates/zempo/publico_form.html",
    "templates/academias/cadastro_academia.html",
    "templates/academias/editar_academia.html",
    "templates/associacoes/cadastro_associacao.html",
    "templates/associacoes/editar_associacao.html",
    "templates/federacoes/cadastro_federacao.html",
    "templates/federacoes/editar_federacao.html",
    "templates/estoque/produto_form.html",
    "templates/estoque/produto.html",
]


def checar(nome, condicao, detalhe=""):
    print(("  PASSOU  " if condicao else "  FALHOU  ") + nome
          + (f"  [{detalhe}]" if detalhe and not condicao else ""))
    if not condicao:
        _falhas.append(nome)


def _arquivo(nome, dados):
    return FileStorage(stream=_io.BytesIO(dados), filename=nome)


def _valida(nome, dados):
    """(ok, mensagem)"""
    try:
        return True, validar_upload(_arquivo(nome, dados), categorias=["imagem"])
    except UploadInvalido as e:
        return False, str(e)


JPEG = b"\xff\xd8\xff" + b"0" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 200
WEBP = b"RIFF0000WEBP" + b"0" * 200
HEIC = b"\x00\x00\x00\x18ftypheic" + b"0" * 200
EXE = b"MZ\x90\x00" + b"0" * 200


def main():
    print("\nO seletor de arquivos não é mais sequestrado pela câmera\n")

    com_capture = []
    for caminho in TELAS_COM_FOTO:
        p = ROOT / caminho
        if not p.exists():
            continue
        texto = p.read_text(encoding="utf-8")
        if re.search(r'capture\s*=', texto):
            com_capture.append(caminho)
    checar("1. nenhuma tela força a câmera", not com_capture, str(com_capture))

    inputs = 0
    for caminho in TELAS_COM_FOTO:
        p = ROOT / caminho
        if p.exists() and 'accept="image/*"' in p.read_text(encoding="utf-8"):
            inputs += 1
    checar("2. as telas seguem oferecendo campo de imagem", inputs >= 14, str(inputs))

    print("\nFormatos que o navegador exibe\n")

    for dados, nome, rot in ((JPEG, "foto.jpg", "JPEG"), (PNG, "foto.png", "PNG"),
                             (WEBP, "foto.webp", "WebP")):
        ok, r = _valida(nome, dados)
        checar(f"3/{rot}. {rot} é aceito", ok, str(r))

    print("\nFoto do iPhone\n")

    ok, msg = _valida("IMG_0001.heic", HEIC)
    checar("4. HEIC é recusado", not ok)
    checar("5. e a mensagem diz o que fazer no aparelho",
           "iPhone" in msg and "Compatível" in msg, msg[:80])
    ok, msg = _valida("IMG_0002.jpg", HEIC)
    checar("6. HEIC renomeado para .jpg recebe a mesma explicação",
           not ok and "iPhone" in msg, msg[:80])

    print("\nTamanho\n")

    grande = b"\xff\xd8\xff" + b"0" * int((TAMANHO_MAX_MB + 1) * 1024 * 1024)
    ok, msg = _valida("grande.jpg", grande)
    checar("7. acima do limite é recusado", not ok)
    checar("8. e a mensagem diz o tamanho e o limite",
           "MB" in msg and str(int(TAMANHO_MAX_MB)) in msg, msg[:80])

    no_limite = b"\xff\xd8\xff" + b"0" * int(TAMANHO_MAX_MB * 1024 * 1024 // 2)
    ok, _ = _valida("ok.jpg", no_limite)
    checar("9. abaixo do limite passa", ok)

    print("\nO limite de foto não pode derrubar PDF e planilha\n")

    def _valida_cat(nome, dados, cats):
        try:
            validar_upload(_arquivo(nome, dados), categorias=cats)
            return True, ""
        except UploadInvalido as e:
            return False, str(e)

    MB = 1024 * 1024
    ok, msg = _valida_cat("calendario.pdf", b"%PDF" + b"0" * (12 * MB), ["pdf"])
    checar("9b. PDF de 12 MB continua passando", ok, msg[:70])
    ok, msg = _valida_cat("inscricoes.xlsx", b"PK\x03\x04" + b"0" * (12 * MB),
                          ["planilha"])
    checar("9c. planilha de 12 MB também", ok, msg[:70])
    ok, msg = _valida_cat("comprovante.pdf", b"%PDF" + b"0" * (8 * MB),
                          ["comprovante"])
    checar("9d. comprovante em PDF de 8 MB também", ok, msg[:70])
    ok, msg = _valida_cat("enorme.pdf", b"%PDF" + b"0" * (30 * MB), ["pdf"])
    checar("9e. mas 30 MB é recusado em qualquer categoria", not ok, msg[:70])

    print("\nSegurança não afrouxou\n")

    ok, msg = _valida("virus.jpg", EXE)
    checar("10. executável com nome de foto continua barrado", not ok, msg[:60])
    ok, msg = _valida("script.php", JPEG)
    checar("11. extensão fora da lista continua barrada", not ok, msg[:60])
    ok, msg = _valida("vazio.jpg", b"")
    checar("12. arquivo vazio é recusado", not ok, msg[:60])

    print()
    if _falhas:
        print(f"{len(_falhas)} falha(s): " + ", ".join(_falhas))
        sys.exit(1)
    print("Todos os cenários passaram.")


if __name__ == "__main__":
    main()
