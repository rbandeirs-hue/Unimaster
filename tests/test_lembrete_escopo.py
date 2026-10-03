"""O lembrete de mensalidade fala com quem a tela está mostrando.

O defeito
---------
A tela de mensalidades pode estar filtrada num aluno. O botão do cabeçalho,
rotulado só "Lembretes", disparava `enviar_lote` para a academia INTEIRA — quem
abria a mensalidade de um aluno e clicava ali cobrava todo mundo. E a pergunta
de confirmação dizia "todos os alunos" mesmo nesse caso, então nem o texto
denunciava.

Estes testes travam o comportamento nos dois sentidos: com filtro, um só; sem
filtro, a academia toda.

Uso:  PYTHONPATH=. .venv/bin/python tests/test_lembrete_escopo.py
"""
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection              # noqa: E402
from utils import whatsapp_lembretes as lem       # noqa: E402

ACADEMIA = -9930
_falhas = []
ids = {}


def checar(nome, condicao, detalhe=""):
    print(("  PASSOU  " if condicao else "  FALHOU  ") + nome
          + (f"  [{detalhe}]" if detalhe and not condicao else ""))
    if not condicao:
        _falhas.append(nome)


def _conn():
    c = get_db_connection()
    return c, c.cursor(dictionary=True)


def limpar():
    c, cur = _conn()
    cur.execute("""DELETE ma FROM mensalidade_aluno ma JOIN alunos a
                   ON a.id = ma.aluno_id WHERE a.id_academia = %s""", (ACADEMIA,))
    cur.execute("DELETE FROM alunos WHERE id_academia = %s", (ACADEMIA,))
    cur.execute("DELETE FROM mensalidades WHERE id_academia = %s", (ACADEMIA,))
    cur.execute("DELETE FROM academias WHERE id = %s", (ACADEMIA,))
    c.commit(); cur.close(); c.close()


def montar():
    c, cur = _conn()
    cur.execute("INSERT INTO academias (id, nome) VALUES (%s,'ZZ Lembrete')", (ACADEMIA,))
    # `mensalidade_aluno.mensalidade_id` aponta o plano e é obrigatório.
    cur.execute("""INSERT INTO mensalidades (nome, valor, id_academia, ativo)
                   VALUES ('ZZ Plano', 100, %s, 1)""", (ACADEMIA,))
    ids["plano"] = cur.lastrowid
    ontem = date.today() - timedelta(days=5)
    for n in range(1, 4):
        cur.execute("""INSERT INTO alunos (id_academia, nome, ativo, tel_celular)
                       VALUES (%s, %s, 1, %s)""",
                    (ACADEMIA, f"ZZ Devedor {n}", f"8199999000{n}"))
        aluno_id = cur.lastrowid
        ids[f"aluno{n}"] = aluno_id
        cur.execute("""INSERT INTO mensalidade_aluno
                       (aluno_id, mensalidade_id, data_vencimento, valor, status)
                       VALUES (%s, %s, %s, 100, 'atrasado')""",
                    (aluno_id, ids["plano"], ontem))
        ids[f"ma{n}"] = cur.lastrowid
    c.commit(); cur.close(); c.close()


def main():
    limpar()
    montar()
    try:
        print("\nA consulta que alimenta o envio\n")

        c, cur = _conn()
        todos = lem.buscar_pendentes(cur, ACADEMIA, dias_antes=3)
        um = lem.buscar_pendentes(cur, ACADEMIA, dias_antes=3,
                                  aluno_id=ids["aluno2"])
        atrasados_todos = lem.buscar_pendentes(cur, ACADEMIA, somente_atrasadas=True)
        atrasados_um = lem.buscar_pendentes(cur, ACADEMIA, somente_atrasadas=True,
                                            aluno_id=ids["aluno2"])
        cur.close(); c.close()

        checar("1. sem filtro, os três devedores entram", len(todos) == 3, str(len(todos)))
        checar("2. com o filtro, só um", len(um) == 1, str(len(um)))
        checar("3. e é o aluno certo",
               um and um[0]["aluno_id"] == ids["aluno2"],
               str(um and um[0]["aluno_id"]))
        checar("4. o recorte também vale para 'só atrasadas'",
               len(atrasados_todos) == 3 and len(atrasados_um) == 1,
               f"{len(atrasados_todos)} / {len(atrasados_um)}")

        print("\nO envio em lote respeita o recorte\n")

        # Não manda WhatsApp de verdade: troca o transporte por um espião.
        enviados = []
        original = lem.wpp.enviar
        lem.wpp.enviar = lambda academia_id, telefone, texto, **kw: (
            enviados.append(telefone) or (True, {}))
        try:
            resumo = lem.enviar_lote(ACADEMIA, somente_ativadas=False,
                                     aluno_id=ids["aluno2"])
            checar("5. filtrado, o lote manda UMA mensagem",
                   len(enviados) == 1, str(len(enviados)))
            checar("6. para o telefone daquele aluno",
                   enviados and enviados[0].endswith("0002"), str(enviados))
            checar("7. e o resumo conta um só",
                   resumo["total"] == 1 and resumo["enviados"] == 1, str(resumo))

            enviados.clear()
            resumo = lem.enviar_lote(ACADEMIA, somente_ativadas=False)
            checar("8. sem filtro, manda para os três",
                   len(enviados) == 3, str(len(enviados)))
        finally:
            lem.wpp.enviar = original

        print("\nA tela\n")

        tela = (ROOT / "templates/financeiro/mensalidades/mensalidades_alunos.html"
                ).read_text(encoding="utf-8")
        checar("9. o botão manda o aluno quando a tela está filtrada",
               'data-aluno="{{ aluno_filtro }}"' in tela)
        checar("10. e o rótulo diz o alcance",
               "Lembrete deste aluno" in tela and "Lembretes de todos" in tela)
        checar("11. a pergunta de confirmação também muda",
               "para ' + nome + '?" in tela)

        rota = (ROOT / "blueprints/financeiro/routes.py").read_text(encoding="utf-8")
        checar("12. a rota valida que o aluno é da academia",
               'aluno não é desta academia' in rota)
    finally:
        limpar()

    print()
    if _falhas:
        print(f"{len(_falhas)} falha(s): " + ", ".join(_falhas))
        sys.exit(1)
    print("Todos os cenários passaram.")


if __name__ == "__main__":
    main()
