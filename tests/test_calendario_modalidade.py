"""Calendário separado por modalidade (MM-08).

A pergunta que estes testes respondem: numa academia que dá judô e jiu-jitsu,
o gestor consegue ver a agenda de uma modalidade sem a outra atrapalhar — e
nada que é de todos (feriado, reunião) some nesse caminho.

Rodam contra o banco real, numa academia de id negativo criada e apagada a
cada execução.

Uso:  PYTHONPATH=. .venv/bin/python tests/test_calendario_modalidade.py
"""
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app                                     # noqa: E402
from config import get_db_connection                    # noqa: E402
from utils import multimodalidade as mm                 # noqa: E402

ACADEMIA = -9990
PREFIXO = "ZZ Cal "
HOJE = date.today()
DIA = date(HOJE.year, HOJE.month, 15)
_falhas = []
ids = {}


def _conn():
    c = get_db_connection()
    return c, c.cursor(dictionary=True)


def checar(nome, condicao, detalhe=""):
    print(("  PASSOU  " if condicao else "  FALHOU  ") + nome
          + (f"  [{detalhe}]" if detalhe and not condicao else ""))
    if not condicao:
        _falhas.append(nome)


def limpar():
    c, cur = _conn()
    cur.execute("DELETE FROM eventos WHERE nivel = 'academia' AND nivel_id = %s", (ACADEMIA,))
    cur.execute("DELETE FROM academia_modalidades WHERE academia_id = %s", (ACADEMIA,))
    cur.execute("DELETE FROM academias WHERE id = %s", (ACADEMIA,))
    cur.execute("DELETE FROM modalidade WHERE nome LIKE %s", (PREFIXO + "%",))
    c.commit(); cur.close(); c.close()
    mm.invalidar()


def montar():
    c, cur = _conn()
    cur.execute("INSERT INTO academias (id, nome) VALUES (%s, %s)",
                (ACADEMIA, "ZZ Academia Calendario"))
    for chave, nome, cor in (("judo", PREFIXO + "Judo", "#e4001b"),
                             ("jiu", PREFIXO + "Jiu", "#1d4ed8")):
        cur.execute("""INSERT INTO modalidade (nome, ativo, visibilidade, cor)
                       VALUES (%s, 1, 'publica', %s)""", (nome, cor))
        ids[chave] = cur.lastrowid
        cur.execute("""INSERT INTO academia_modalidades (academia_id, modalidade_id)
                       VALUES (%s, %s)""", (ACADEMIA, ids[chave]))

    def evento(titulo, modalidade_id):
        cur.execute("""INSERT INTO eventos
                       (titulo, data_inicio, tipo, nivel, nivel_id, status, modalidade_id)
                       VALUES (%s, %s, 'evento', 'academia', %s, 'ativo', %s)""",
                    (titulo, DIA, ACADEMIA, modalidade_id))
        return cur.lastrowid

    ids["ev_judo"] = evento("ZZ Exame de faixa judo", ids["judo"])
    ids["ev_jiu"] = evento("ZZ Open de jiu", ids["jiu"])
    ids["ev_geral"] = evento("ZZ Feriado da cidade", None)
    c.commit(); cur.close(); c.close()
    mm.invalidar()


def _eventos_com_filtro(modalidade_id):
    """Roda a mesma consulta do calendário e devolve os títulos que sobram."""
    trecho, params = mm.filtro_eventos_sql("e", modalidade_id=modalidade_id)
    c, cur = _conn()
    cur.execute("""SELECT e.titulo FROM eventos e
                   WHERE e.nivel = 'academia' AND e.nivel_id = %s
                     AND e.status = 'ativo' """ + trecho,
                (ACADEMIA,) + tuple(params))
    titulos = {r["titulo"] for r in cur.fetchall() or []}
    cur.close(); c.close()
    return titulos


def main():
    limpar()
    montar()
    try:
        print("\nFiltro de eventos\n")

        todos = _eventos_com_filtro(None)
        checar("1. sem modalidade escolhida, o calendário mostra tudo",
               len(todos) == 3, str(todos))

        so_judo = _eventos_com_filtro(ids["judo"])
        checar("2. no judô, o evento de judô aparece",
               "ZZ Exame de faixa judo" in so_judo, str(so_judo))
        checar("3. no judô, o evento de jiu-jitsu some",
               "ZZ Open de jiu" not in so_judo, str(so_judo))
        checar("4. no judô, o feriado continua (lançamento geral)",
               "ZZ Feriado da cidade" in so_judo, str(so_judo))

        so_jiu = _eventos_com_filtro(ids["jiu"])
        checar("5. no jiu-jitsu, o evento de judô some",
               "ZZ Exame de faixa judo" not in so_jiu, str(so_jiu))
        checar("6. no jiu-jitsu, o feriado continua",
               "ZZ Feriado da cidade" in so_jiu, str(so_jiu))

        print("\nFiltro por várias modalidades (aluno e responsável)\n")

        trecho, params = mm.filtro_eventos_por_modalidades("e", [])
        checar("7. aluno sem modalidade conhecida não perde nada",
               trecho == "", trecho)

        trecho, params = mm.filtro_eventos_por_modalidades("e", [ids["jiu"]])
        c, cur = _conn()
        cur.execute("""SELECT e.titulo FROM eventos e
                       WHERE e.nivel_id = %s AND e.status = 'ativo' """ + trecho,
                    (ACADEMIA,) + tuple(params))
        vistos = {r["titulo"] for r in cur.fetchall() or []}
        cur.close(); c.close()
        checar("8. aluno de jiu vê o próprio evento e o geral",
               vistos == {"ZZ Open de jiu", "ZZ Feriado da cidade"}, str(vistos))

        print("\nTela do calendário\n")

        cliente = app.test_client()
        # Reusa o usuário que o smoke test já usa para o modo academia: é o
        # mesmo caminho de sessão do sistema, sem inventar login novo.
        from tests.test_shell_smoke import USUARIO_POR_MODO
        with cliente.session_transaction() as sess:
            sess["_user_id"] = str(USUARIO_POR_MODO["academia"])
            sess["_fresh"] = True
            sess["modo_painel"] = "academia"
            sess["academia_gerenciamento_id"] = ACADEMIA
        base = f"/calendario/visualizar?nivel=academia&nivel_id={ACADEMIA}&visao=lista"
        geral = cliente.get(base, follow_redirects=True).get_data(as_text=True)
        checar("9. a tela abre e lista os três lançamentos",
               all(t in geral for t in ("ZZ Exame de faixa judo", "ZZ Open de jiu",
                                        "ZZ Feriado da cidade")))
        checar("10. o seletor de modalidade aparece na academia multimodal",
               'name="modalidade"' in geral)

        judo = cliente.get(base + f"&modalidade={ids['judo']}",
                           follow_redirects=True).get_data(as_text=True)
        checar("11. filtrando judô, o jiu-jitsu sai da tela",
               "ZZ Open de jiu" not in judo)
        checar("12. filtrando judô, o feriado fica",
               "ZZ Feriado da cidade" in judo)
        checar("13. a navegação de mês preserva o filtro",
               f"modalidade={ids['judo']}" in judo)

        with cliente.session_transaction() as sess:
            sess["modalidade_contexto_id"] = ids["jiu"]
        ctx = cliente.get(base, follow_redirects=True).get_data(as_text=True)
        checar("14. sem filtro na URL, vale o contexto do shell",
               "ZZ Exame de faixa judo" not in ctx and "ZZ Open de jiu" in ctx)
        explicito = cliente.get(base + "&modalidade=",
                                follow_redirects=True).get_data(as_text=True)
        checar("15. escolher 'todas' na tela vence o contexto do shell",
               "ZZ Exame de faixa judo" in explicito)
    finally:
        limpar()

    print()
    if _falhas:
        print(f"{len(_falhas)} falha(s): " + ", ".join(_falhas))
        sys.exit(1)
    print("Todos os cenários passaram.")


if __name__ == "__main__":
    main()
