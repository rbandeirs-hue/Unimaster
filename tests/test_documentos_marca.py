"""A marca impressa nos documentos segue a modalidade de quem está no papel.

O relatório de presença de um aluno de jiu-jitsu saía com "Unimaster Judô" no
cabeçalho e no rodapé — o nome estava fixo no template. Estes testes fixam a
regra nova: a marca vem do registro (matrícula do aluno, modalidade da turma),
depois da identidade da academia, e quando nada responde sai só "Unimaster".

Uso:  PYTHONPATH=. .venv/bin/python tests/test_documentos_marca.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app                                             # noqa: E402
from config import get_db_connection                            # noqa: E402
from blueprints.presencas.presencas import _marca_documento     # noqa: E402
from tests.test_shell_smoke import USUARIO_POR_MODO             # noqa: E402

_falhas = []


def checar(nome, condicao, detalhe=""):
    print(("  PASSOU  " if condicao else "  FALHOU  ") + nome
          + (f"  [{detalhe}]" if detalhe and not condicao else ""))
    if not condicao:
        _falhas.append(nome)


def _cliente(academia_id):
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["_user_id"] = str(USUARIO_POR_MODO["academia"])
        sess["_fresh"] = True
        sess["modo_painel"] = "academia"
        sess["academia_gerenciamento_id"] = academia_id
    return c


def _aluno_so_de(modalidade_id):
    """Aluno matriculado NESSA modalidade e em nenhuma outra.

    Aluno que faz jiu-jitsu e judô sai com as duas no cabeçalho, e isso está
    certo — só não serve para provar que uma não vazou na outra.
    """
    c = get_db_connection()
    cur = c.cursor(dictionary=True)
    cur.execute("""SELECT a.id, a.nome, a.id_academia
                   FROM alunos a
                   JOIN matricula_modalidade mm
                     ON mm.aluno_id = a.id AND mm.status = 'ativa'
                   WHERE mm.modalidade_id = %s AND a.ativo = 1
                     AND (SELECT COUNT(*) FROM matricula_modalidade m2
                          WHERE m2.aluno_id = a.id AND m2.status = 'ativa') = 1
                   LIMIT 1""", (modalidade_id,))
    linha = cur.fetchone()
    cur.close(); c.close()
    return linha


def main():
    print("\nA regra da marca, isolada\n")

    checar("1. a modalidade do registro vence tudo",
           _marca_documento(["Jiu-Jitsu"], None) == "Jiu-Jitsu")
    checar("2. várias modalidades saem juntas, sem escolher por conta própria",
           _marca_documento(["Ginástica", "Judô"], None) == "Ginástica · Judô")
    checar("3. sem nada que responda, não inventa modalidade",
           _marca_documento([], None) == "",
           _marca_documento([], None))
    checar("4. valor vazio na lista não vira marca",
           _marca_documento([None, ""], None) == "")

    print("\nRelatório de presença do aluno\n")

    import re
    for rotulo, modalidade_id, esperado in (("jiu-jitsu", 7, "Jiu-Jitsu"),
                                            ("judô", 1, "Judô")):
        aluno = _aluno_so_de(modalidade_id)
        if not aluno:
            checar(f"5/{rotulo}. relatório do aluno", False,
                   "nenhum aluno ativo nessa modalidade para testar")
            continue
        cliente = _cliente(aluno["id_academia"])
        html = cliente.get(f"/presencas/relatorio/{aluno['id']}",
                           follow_redirects=True).get_data(as_text=True)
        cabecalho = re.search(r'doc-marca-nome">(.*?)</span>', html, re.S)
        cabecalho = cabecalho.group(1).strip() if cabecalho else ""
        checar(f"5/{rotulo}. o cabeçalho traz a modalidade do aluno",
               esperado in cabecalho, cabecalho)
        checar(f"6/{rotulo}. o rodapé acompanha o cabeçalho",
               f"sistema Unimaster {esperado}." in html)
        if esperado != "Judô":
            # O nome da turma pode conter "Judô" legitimamente; o que não pode
            # é a MARCA do documento trazer judô para um aluno que não faz.
            checar(f"7/{rotulo}. a marca não traz judô para quem não faz",
                   "Judô" not in cabecalho, cabecalho)

    print()
    if _falhas:
        print(f"{len(_falhas)} falha(s): " + ", ".join(_falhas))
        sys.exit(1)
    print("Todos os cenários passaram.")


if __name__ == "__main__":
    main()
