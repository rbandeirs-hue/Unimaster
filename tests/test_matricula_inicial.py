"""Prova que a matrícula inicial grava o desconto na cobrança gerada."""
import sys
from datetime import date
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import app                       # noqa
from config import get_db_connection      # noqa

ACAD, PREFIXO = 14, "ZZ Teste Matr "   # academia real; tudo criado aqui é apagado no fim
falhas = []


def checar(nome, cond, det=""):
    print(("  PASSOU  " if cond else "  FALHOU  ") + nome + (f"  [{det}]" if det and not cond else ""))
    if not cond:
        falhas.append(nome)


def conn():
    c = get_db_connection()
    return c, c.cursor(dictionary=True)


def limpar():
    c, cur = conn()
    cur.execute("SELECT id FROM alunos WHERE id_academia = %s AND nome LIKE %s",
                (ACAD, PREFIXO + "%"))
    ids = [r["id"] for r in cur.fetchall() or []]
    if ids:
        ph = ",".join(["%s"] * len(ids))
        cur.execute(f"DELETE FROM mensalidade_aluno WHERE aluno_id IN ({ph})", tuple(ids))
        cur.execute(f"DELETE FROM aluno_desconto WHERE aluno_id IN ({ph})", tuple(ids))
    cur.execute("DELETE FROM alunos WHERE id_academia = %s AND nome LIKE %s",
                (ACAD, PREFIXO + "%"))
    cur.execute("DELETE FROM descontos WHERE id_academia = %s AND nome LIKE %s",
                (ACAD, PREFIXO + "%"))
    cur.execute("DELETE FROM mensalidades WHERE id_academia = %s AND nome LIKE %s",
                (ACAD, PREFIXO + "%"))
    c.commit(); cur.close(); c.close()


with app.app_context():
    limpar()
    c, cur = conn()
    cur.execute("INSERT INTO alunos (nome, id_academia, status) VALUES (%s,%s,'ativo')",
                (PREFIXO + "Bolsista", ACAD))
    aluno = cur.lastrowid
    cur.execute("""INSERT INTO mensalidades (nome, valor, id_academia, ativo)
                   VALUES (%s, 100.00, %s, 1)""", (PREFIXO + "Plano", ACAD))
    plano = cur.lastrowid
    cur.execute("""INSERT INTO descontos (nome, tipo, valor, id_academia, ativo)
                   VALUES (%s,'percentual',100.00,%s,1)""", (PREFIXO + "Bolsa integral", ACAD))
    bolsa_100 = cur.lastrowid
    cur.execute("""INSERT INTO descontos (nome, tipo, valor, id_academia, ativo)
                   VALUES (%s,'percentual',50.00,%s,1)""", (PREFIXO + "Meia bolsa", ACAD))
    bolsa_50 = cur.lastrowid
    c.commit(); cur.close(); c.close()

    from blueprints.aluno import alunos as mod  # noqa

    # A tela é de gestão; o teste não valida RBAC, valida a geração da cobrança.
    mod._pode_gerenciar_aluno_academia = lambda *a, **k: True
    app.config["WTF_CSRF_ENABLED"] = False
    cliente = app.test_client()
    with cliente.session_transaction() as sess:
        sess["_user_id"] = "3"          # gestor real da base
        sess["_fresh"] = True
        sess["modo_painel"] = "academia"
        sess["academia_gerenciamento_id"] = ACAD
        sess["finance_academia_id"] = ACAD

    def matricular(desconto_id, mes):
        dados = {"gerar_mensalidade": "1", "mensalidade_id": str(plano),
                 "escopo_mensalidade": "mes", "mes_inicial": str(mes),
                 "ano_ref": str(date.today().year), "dia_vencimento": "10"}
        if desconto_id:
            dados["desconto_id"] = str(desconto_id)
        r = cliente.post(f"/alunos/matricula/{aluno}", data=dados, follow_redirects=False)
        print("   resposta", r.status_code, "->", r.headers.get("Location", "(sem redirect)"))

    matricular(bolsa_50, 10)
    c, cur = conn()
    cur.execute("""SELECT valor, valor_original, desconto_aplicado, id_desconto,
                          desconto_descricao, status
                   FROM mensalidade_aluno WHERE aluno_id = %s AND MONTH(data_vencimento)=10""",
                (aluno,))
    r = cur.fetchone() or {}
    print("   meia bolsa ->", dict(r) if r else "(nada gerado)")
    checar("1. cobrança nasce com o valor JÁ descontado",
           r and float(r["valor"]) == 50.0, str(r.get("valor")))
    checar("2. o valor de tabela fica registrado",
           r and float(r["valor_original"] or 0) == 100.0)
    checar("3. o desconto concedido fica registrado",
           r and float(r["desconto_aplicado"] or 0) == 50.0)
    checar("4. a cobrança aponta para o desconto usado",
           r and r["id_desconto"] == bolsa_50)
    checar("5. com valor a pagar, segue pendente", r and r["status"] == "pendente")
    checar("6. o vínculo de desconto do aluno foi criado",
           (cur.execute("SELECT COUNT(*) n FROM aluno_desconto WHERE aluno_id=%s AND desconto_id=%s AND ativo=1",
                        (aluno, bolsa_50)) or cur.fetchone())["n"] == 1)
    cur.close(); c.close()

    # Bolsa integral: a parcela tem de nascer zerada E quitada.
    c, cur = conn()
    cur.execute("UPDATE aluno_desconto SET ativo = 0 WHERE aluno_id = %s", (aluno,))
    c.commit(); cur.close(); c.close()
    matricular(bolsa_100, 11)
    c, cur = conn()
    cur.execute("""SELECT valor, valor_original, desconto_aplicado, status, status_pagamento
                   FROM mensalidade_aluno WHERE aluno_id = %s AND MONTH(data_vencimento)=11""",
                (aluno,))
    r2 = cur.fetchone() or {}
    print("   bolsa integral ->", dict(r2) if r2 else "(nada gerado)")
    checar("7. bolsa de 100% zera a cobrança",
           r2 and float(r2["valor"]) == 0.0, str(r2.get("valor")))
    checar("8. e ela nasce quitada, sem virar inadimplência",
           r2 and r2["status"] == "pago" and r2["status_pagamento"] == "pago")
    checar("9. o desconto concedido continua registrado",
           r2 and float(r2["desconto_aplicado"] or 0) == 100.0)
    cur.close(); c.close()

    # Sem desconto: comportamento de antes, intacto. O aluno precisa estar SEM
    # vínculo, senão o desconto anterior continua valendo — e deve mesmo.
    c, cur = conn()
    cur.execute("UPDATE aluno_desconto SET ativo = 0 WHERE aluno_id = %s", (aluno,))
    c.commit(); cur.close(); c.close()
    matricular(None, 12)
    c, cur = conn()
    cur.execute("""SELECT valor, valor_original, desconto_aplicado, status
                   FROM mensalidade_aluno WHERE aluno_id = %s AND MONTH(data_vencimento)=12""",
                (aluno,))
    r3 = cur.fetchone() or {}
    print("   sem desconto ->", dict(r3) if r3 else "(nada gerado)")
    checar("10. sem desconto escolhido, nada muda em relação a antes",
           r3 and float(r3["valor"]) == 100.0 and r3["status"] == "pendente")
    cur.close(); c.close()

    limpar()
    print()
    if falhas:
        print(f"{len(falhas)} falha(s): " + ", ".join(falhas)); sys.exit(1)
    print("Todos os cenários passaram.")
