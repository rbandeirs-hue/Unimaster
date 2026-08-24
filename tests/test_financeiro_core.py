"""Testes das regras do núcleo financeiro.

Rodam contra o banco real, mas dentro de uma academia de teste criada e
removida a cada execução — nenhum dado de produção é tocado.
"""
import threading
from datetime import date
from decimal import Decimal

from app import app
from config import get_db_connection
from utils import financeiro_core as fin


ACADEMIA_TESTE = -9999          # id negativo: não colide com academia real
HOJE = date.today()
_falhas = []


def _conn():
    c = get_db_connection()
    return c, c.cursor(dictionary=True)


def checar(nome, condicao, detalhe=""):
    print(("  PASSOU  " if condicao else "  FALHOU  ") + nome + (f"  [{detalhe}]" if detalhe and not condicao else ""))
    if not condicao:
        _falhas.append(nome)


def limpar():
    c, cur = _conn()
    for t in ("fin_conciliacoes", "fin_fechamentos", "fin_transferencias",
              "fin_lancamentos", "fin_contas", "fin_auditoria", "fin_config"):
        col = "id_academia"
        cur.execute(f"DELETE FROM {t} WHERE {col} = %s", (ACADEMIA_TESTE,))
    c.commit(); cur.close(); c.close()


def criar_conta(nome, saldo_inicial=0):
    c, cur = _conn()
    cur.execute(
        """INSERT INTO fin_contas (id_academia, nome, tipo, saldo_inicial, data_saldo_inicial)
           VALUES (%s, %s, 'caixa', %s, %s)""",
        (ACADEMIA_TESTE, nome, saldo_inicial, HOJE))
    c.commit(); cid = cur.lastrowid
    cur.close(); c.close()
    return cid


def set_modo(modo):
    c, cur = _conn()
    fin.definir_modo(c, cur, ACADEMIA_TESTE, modo, usuario_id=1)
    c.commit(); cur.close(); c.close()


def saldo(id_conta):
    c, cur = _conn()
    s = fin.saldo_conta(cur, id_conta)["saldo"]
    cur.close(); c.close()
    return s


# =====================================================================
with app.app_context():
    limpar()
    print("\n--- saldo e lançamentos ---")
    set_modo(fin.MODO_PARCIAL)
    caixa = criar_conta("Caixa teste", 1000)
    checar("1. saldo inicial da conta é respeitado", saldo(caixa) == Decimal("1000.00"), saldo(caixa))

    c, cur = _conn()
    l_pend = fin.lancar(c, cur, id_academia=ACADEMIA_TESTE, id_conta=caixa, sentido="entrada",
                        valor=300, descricao="Receita pendente", data_competencia=HOJE,
                        status="pendente", usuario_id=1)
    c.commit(); cur.close(); c.close()
    checar("2. receita pendente NÃO altera o saldo", saldo(caixa) == Decimal("1000.00"), saldo(caixa))

    c, cur = _conn()
    fin.efetivar(c, cur, l_pend, usuario_id=1)
    c.commit(); cur.close(); c.close()
    checar("3. confirmar a receita altera o saldo", saldo(caixa) == Decimal("1300.00"), saldo(caixa))

    c, cur = _conn()
    d_pend = fin.lancar(c, cur, id_academia=ACADEMIA_TESTE, id_conta=caixa, sentido="saida",
                        valor=100, descricao="Despesa pendente", data_competencia=HOJE,
                        status="pendente", usuario_id=1)
    c.commit(); cur.close(); c.close()
    checar("4. despesa pendente NÃO altera o saldo", saldo(caixa) == Decimal("1300.00"), saldo(caixa))

    c, cur = _conn()
    fin.efetivar(c, cur, d_pend, usuario_id=1)
    c.commit(); cur.close(); c.close()
    checar("5. efetivar a despesa altera o saldo", saldo(caixa) == Decimal("1200.00"), saldo(caixa))

    print("\n--- modo parcial x total ---")
    c, cur = _conn()
    try:
        fin.lancar(c, cur, id_academia=ACADEMIA_TESTE, id_conta=caixa, sentido="saida",
                   valor=5000, descricao="Saída maior que o saldo", data_competencia=HOJE,
                   status="efetivado", usuario_id=1)
        c.commit(); permitiu = True
    except fin.SaldoInsuficiente:
        c.rollback(); permitiu = False
    cur.close(); c.close()
    checar("6. modo PARCIAL permite saldo negativo", permitiu and saldo(caixa) == Decimal("-3800.00"),
           f"permitiu={permitiu} saldo={saldo(caixa)}")

    limpar(); set_modo(fin.MODO_TOTAL)
    cofre = criar_conta("Cofre teste", 500)
    c, cur = _conn()
    msg = ""
    try:
        fin.lancar(c, cur, id_academia=ACADEMIA_TESTE, id_conta=cofre, sentido="saida",
                   valor=700, descricao="Saída acima do saldo", data_competencia=HOJE,
                   status="efetivado", usuario_id=1)
        c.commit(); bloqueou = False
    except fin.SaldoInsuficiente as e:
        c.rollback(); bloqueou = True; msg = str(e)
    cur.close(); c.close()
    checar("7. modo TOTAL bloqueia saldo insuficiente", bloqueou and saldo(cofre) == Decimal("500.00"))
    checar("8. a mensagem informa saldo, valor e diferença",
           "500,00" in msg and "700,00" in msg and "200,00" in msg, msg)

    print("\n--- transferência ---")
    conta_a = criar_conta("Pix teste", 1000)
    conta_b = criar_conta("Banco teste", 200)
    c, cur = _conn()
    patrimonio_antes = fin.saldo_total(cur, ACADEMIA_TESTE)
    t = fin.transferir(c, cur, id_academia=ACADEMIA_TESTE, id_conta_origem=conta_a,
                       id_conta_destino=conta_b, valor=300, data=HOJE, usuario_id=1)
    c.commit()
    patrimonio_depois = fin.saldo_total(cur, ACADEMIA_TESTE)
    cur.close(); c.close()
    checar("9. transferência move o dinheiro entre as contas",
           saldo(conta_a) == Decimal("700.00") and saldo(conta_b) == Decimal("500.00"),
           f"{saldo(conta_a)} / {saldo(conta_b)}")
    checar("10. transferência NÃO altera o patrimônio total",
           patrimonio_antes == patrimonio_depois, f"{patrimonio_antes} -> {patrimonio_depois}")
    checar("11. transferência gera os dois lançamentos ligados",
           t["lancamento_saida"] and t["lancamento_entrada"])

    print("\n--- estorno e cancelamento ---")
    c, cur = _conn()
    receita = fin.lancar(c, cur, id_academia=ACADEMIA_TESTE, id_conta=conta_b, sentido="entrada",
                         valor=200, descricao="Receita a estornar", data_competencia=HOJE,
                         status="efetivado", usuario_id=1)
    c.commit(); cur.close(); c.close()
    antes = saldo(conta_b)
    c, cur = _conn()
    estorno = fin.estornar(c, cur, receita, motivo="teste", usuario_id=1)
    c.commit()
    cur.execute("SELECT status, id_estorno FROM fin_lancamentos WHERE id = %s", (receita,))
    orig = cur.fetchone()
    cur.execute("SELECT id_lancamento_origem FROM fin_lancamentos WHERE id = %s", (estorno,))
    vinculo = cur.fetchone()["id_lancamento_origem"]
    cur.close(); c.close()
    checar("12. estorno desfaz o valor no saldo", saldo(conta_b) == antes - Decimal("200.00"))
    checar("13. estorno preserva o original e o marca como estornado",
           orig["status"] == "efetivado" and orig["id_estorno"] == estorno,
           f"status={orig['status']} id_estorno={orig['id_estorno']}")
    checar("14. estorno fica vinculado ao lançamento original", vinculo == receita)

    c, cur = _conn()
    pend = fin.lancar(c, cur, id_academia=ACADEMIA_TESTE, id_conta=conta_b, sentido="entrada",
                      valor=50, descricao="Pendente a cancelar", data_competencia=HOJE,
                      status="pendente", usuario_id=1)
    fin.cancelar(c, cur, pend, motivo="teste", usuario_id=1)
    c.commit()
    cur.execute("SELECT status FROM fin_lancamentos WHERE id = %s", (pend,))
    checar("15. cancelamento preserva o registro (não apaga)", cur.fetchone()["status"] == "cancelado")
    cur.close(); c.close()

    print("\n--- auditoria ---")
    # `efetivar` acontece no trecho do modo parcial, que é apagado pelo limpar();
    # por isso o teste gera um par novo aqui antes de conferir.
    c, cur = _conn()
    _p = fin.lancar(c, cur, id_academia=ACADEMIA_TESTE, id_conta=conta_b, sentido="entrada",
                    valor=1, descricao="Para auditar efetivacao", data_competencia=HOJE,
                    status="pendente", usuario_id=1)
    fin.efetivar(c, cur, _p, usuario_id=1)
    c.commit(); cur.close(); c.close()
    c, cur = _conn()
    cur.execute("""SELECT acao, COUNT(*) n FROM fin_auditoria
                   WHERE id_academia = %s GROUP BY acao""", (ACADEMIA_TESTE,))
    acoes = {r["acao"]: r["n"] for r in cur.fetchall()}
    cur.close(); c.close()
    checar("16. auditoria registra criar/efetivar/estornar/cancelar",
           all(a in acoes for a in ("criar", "efetivar", "estornar", "cancelar")), str(acoes))

    print("\n--- fechamento mensal ---")
    c, cur = _conn()
    cur.execute("""INSERT INTO fin_fechamentos (id_academia, ano, mes, fechado_por)
                   VALUES (%s,%s,%s,1)""", (ACADEMIA_TESTE, HOJE.year, HOJE.month))
    c.commit()
    try:
        fin.lancar(c, cur, id_academia=ACADEMIA_TESTE, id_conta=conta_b, sentido="entrada",
                   valor=10, descricao="Lançamento em mês fechado", data_competencia=HOJE,
                   status="efetivado", usuario_id=1)
        c.commit(); barrou = False
    except fin.PeriodoFechado:
        c.rollback(); barrou = True
    cur.execute("DELETE FROM fin_fechamentos WHERE id_academia = %s", (ACADEMIA_TESTE,))
    c.commit(); cur.close(); c.close()
    checar("17. mês fechado impede novo lançamento", barrou)

    print("\n--- concorrência (modo TOTAL) ---")
    # Saldo 1000, duas saídas simultâneas de 800: só uma pode passar.
    disputada = criar_conta("Conta disputada", 1000)
    resultados = []

    def gastar():
        c, cur = _conn()
        try:
            fin.lancar(c, cur, id_academia=ACADEMIA_TESTE, id_conta=disputada, sentido="saida",
                       valor=800, descricao="Saída concorrente", data_competencia=HOJE,
                       status="efetivado", usuario_id=1)
            c.commit(); resultados.append("ok")
        except fin.SaldoInsuficiente:
            c.rollback(); resultados.append("bloqueado")
        except Exception as e:
            c.rollback(); resultados.append("erro:" + type(e).__name__)
        finally:
            cur.close(); c.close()

    t1, t2 = threading.Thread(target=gastar), threading.Thread(target=gastar)
    t1.start(); t2.start(); t1.join(); t2.join()
    checar("18. duas saídas simultâneas não gastam o mesmo saldo",
           resultados.count("ok") == 1 and saldo(disputada) == Decimal("200.00"),
           f"{resultados} saldo={saldo(disputada)}")

    print("\n--- extrato ---")
    c, cur = _conn()
    ext = fin.extrato(cur, ACADEMIA_TESTE, id_conta=conta_b)
    cur.close(); c.close()
    checar("19. extrato fecha com o saldo da conta", ext["saldo_final"] == saldo(conta_b),
           f"{ext['saldo_final']} vs {saldo(conta_b)}")
    checar("20. extrato separa entradas e saídas",
           ext["entradas"] > 0 and ext["saidas"] >= 0)

    limpar()
    print("\n" + "=" * 58)
    print(f"RESULTADO: {20 - len(_falhas)}/20 passaram")
    if _falhas:
        print("falhas:", _falhas)
