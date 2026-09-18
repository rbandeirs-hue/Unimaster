"""Testes da cobrança familiar — o grupo como UMA cobrança.

Rodam contra o banco real, numa academia de teste com id negativo que é criada e
removida a cada execução. Nenhum dado de produção é tocado.

Uso:  PYTHONPATH=. .venv/bin/python tests/test_cobranca_familia.py
"""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app                                   # noqa: E402
from config import get_db_connection                  # noqa: E402
from utils import cobranca_familia as cf              # noqa: E402

ACADEMIA = -9996
PREFIXO = "ZZ Teste Fam "
HOJE = date.today()
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
    cur.execute("SELECT id FROM alunos WHERE id_academia = %s", (ACADEMIA,))
    alunos = [r["id"] for r in cur.fetchall() or []]
    cur.execute("SELECT id FROM cobranca_grupo WHERE id_academia = %s", (ACADEMIA,))
    grupos = [r["id"] for r in cur.fetchall() or []]
    if grupos:
        ph = ",".join(["%s"] * len(grupos))
        cur.execute(f"DELETE FROM cobranca_grupo_item WHERE grupo_id IN ({ph})", tuple(grupos))
    cur.execute("DELETE FROM cobranca_grupo WHERE id_academia = %s", (ACADEMIA,))
    cur.execute("DELETE FROM familia_cobranca WHERE id_academia = %s", (ACADEMIA,))
    cur.execute("DELETE FROM receitas WHERE id_academia = %s", (ACADEMIA,))
    if alunos:
        ph = ",".join(["%s"] * len(alunos))
        cur.execute(f"DELETE FROM cobranca_avulsa WHERE aluno_id IN ({ph})", tuple(alunos))
        cur.execute(f"DELETE FROM mensalidade_aluno WHERE aluno_id IN ({ph})", tuple(alunos))
    cur.execute("DELETE FROM alunos WHERE id_academia = %s", (ACADEMIA,))
    cur.execute("DELETE FROM academias WHERE id = %s", (ACADEMIA,))
    c.commit(); cur.close(); c.close()


def montar():
    """Dois irmãos, uma taxa avulsa cada, num grupo familiar aberto."""
    c, cur = _conn()
    cur.execute("INSERT INTO academias (id, nome) VALUES (%s, %s)",
                (ACADEMIA, "Academia teste familia"))
    for chave, nome in (("irmao1", "Irmao um"), ("irmao2", "Irmao dois")):
        cur.execute(
            """INSERT INTO alunos (nome, id_academia, status, responsavel_financeiro_cpf,
                                   responsavel_financeiro_nome)
               VALUES (%s,%s,'ativo','11122233344','Responsavel teste')""",
            (PREFIXO + nome, ACADEMIA))
        ids[chave] = cur.lastrowid

    cur.execute(
        """INSERT INTO familia_cobranca (id_academia, responsavel_cpf, responsavel_nome, ativo)
           VALUES (%s,'11122233344','Responsavel teste',1)""", (ACADEMIA,))
    ids["familia"] = cur.lastrowid

    cur.execute(
        """INSERT INTO cobranca_grupo (familia_id, id_academia, competencia,
                                       data_vencimento, valor_total, status)
           VALUES (%s,%s,%s,%s,60.00,'pendente')""",
        (ids["familia"], ACADEMIA, date(HOJE.year, HOJE.month, 1), HOJE))
    ids["grupo"] = cur.lastrowid

    for chave in ("irmao1", "irmao2"):
        cur.execute(
            """INSERT INTO cobranca_avulsa (aluno_id, id_academia, descricao, valor,
                                            data_vencimento, status)
               VALUES (%s,%s,'Taxa de teste',30.00,%s,'pendente')""",
            (ids[chave], ACADEMIA, HOJE))
        ids["avulsa_" + chave] = cur.lastrowid
        cur.execute(
            """INSERT INTO cobranca_grupo_item (grupo_id, aluno_id, valor, origem, registro_id)
               VALUES (%s,%s,30.00,'avulsa',%s)""",
            (ids["grupo"], ids[chave], ids["avulsa_" + chave]))
    c.commit(); cur.close(); c.close()


def um(sql, params=()):
    c, cur = _conn()
    try:
        cur.execute(sql, params)
        r = cur.fetchone()
        return list(r.values())[0] if r else None
    finally:
        cur.close(); c.close()


def main():
    limpar()
    montar()
    grupo = ids["grupo"]
    av1, av2 = ids["avulsa_irmao1"], ids["avulsa_irmao2"]

    # O furo que deixou o grupo aberto em produção: a busca só enxergava
    # mensalidade, e grupo formado por avulsas não era reconhecido.
    checar("1. o grupo é encontrado a partir de uma avulsa",
           (cf.grupo_da_mensalidade(av1, "avulsa") or {}).get("id") == grupo)
    checar("2. sem informar a origem, a busca continua sendo de mensalidade",
           cf.grupo_da_mensalidade(av1) is None)
    checar("3. os itens do grupo contam as duas origens",
           len(cf.itens_do_grupo(grupo)) == 2)

    # Baixa normal: quita as duas e lança uma receita por aluno.
    checar("4. a baixa do grupo quita as duas cobranças",
           cf.baixar_grupo(grupo, 60.00, "manual") is True)
    checar("5. as duas avulsas ficam pagas",
           um("SELECT COUNT(*) FROM cobranca_avulsa WHERE id IN (%s,%s) AND status='pago'",
              (av1, av2)) == 2)
    checar("6. o grupo fica pago pelo total",
           float(um("SELECT valor_pago FROM cobranca_grupo WHERE id=%s", (grupo,)) or 0) == 60.0)
    checar("7. uma receita por aluno, somando o total",
           float(um("SELECT COALESCE(SUM(valor),0) FROM receitas WHERE id_academia=%s",
                    (ACADEMIA,)) or 0) == 60.0)
    checar("8. baixar de novo não duplica receita (webhook reenviado)",
           cf.baixar_grupo(grupo, 60.00, "manual") is True
           and float(um("SELECT COALESCE(SUM(valor),0) FROM receitas WHERE id_academia=%s",
                        (ACADEMIA,)) or 0) == 60.0)

    # O caso que aconteceu de verdade: o gestor baixou cada irmão na mão e o
    # grupo ficou aberto. Fechar o grupo NÃO pode lançar receita de novo.
    limpar()
    montar()
    grupo = ids["grupo"]
    c, cur = _conn()
    cur.execute(
        """UPDATE cobranca_avulsa SET status='pago', data_pagamento=%s, valor_pago=30.00
            WHERE id IN (%s,%s)""",
        (HOJE, ids["avulsa_irmao1"], ids["avulsa_irmao2"]))
    for chave in ("irmao1", "irmao2"):
        cur.execute(
            """INSERT INTO receitas (descricao, valor, data, categoria, id_academia,
                                     id_cobranca_avulsa, id_aluno)
               VALUES ('Baixa individual', 30.00, %s, 'Cobrança avulsa', %s, %s, %s)""",
            (HOJE, ACADEMIA, ids["avulsa_" + chave], ids[chave]))
    c.commit(); cur.close(); c.close()

    checar("9. grupo com itens já baixados um a um é fechado",
           cf.baixar_grupo(grupo, None, "manual") is True)
    checar("10. e passa a constar como pago",
           um("SELECT status FROM cobranca_grupo WHERE id=%s", (grupo,)) == "pago")
    checar("11. fechar o grupo não lança receita de novo",
           float(um("SELECT COALESCE(SUM(valor),0) FROM receitas WHERE id_academia=%s",
                    (ACADEMIA,)) or 0) == 60.0,
           str(um("SELECT COALESCE(SUM(valor),0) FROM receitas WHERE id_academia=%s", (ACADEMIA,))))
    checar("12. o total do grupo bate com o que foi pago",
           float(um("SELECT valor_pago FROM cobranca_grupo WHERE id=%s", (grupo,)) or 0) == 60.0)

    limpar()
    print()
    if _falhas:
        print(f"{len(_falhas)} falha(s): " + ", ".join(_falhas))
        sys.exit(1)
    print("Todos os cenários passaram.")


if __name__ == "__main__":
    with app.app_context():
        main()
