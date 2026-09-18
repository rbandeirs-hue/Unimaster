#!/usr/bin/env python3
"""
MM-01 — Cancela mensalidades duplicadas na mesma competência.

Passo 1 da evolução multimodalidade. `mensalidade_aluno` nunca teve índice
único de (aluno, plano, competência): a trava contra duplicidade é só
aplicacional, e ela vazou. Enquanto existirem duplicatas, o índice único que a
geração por contrato precisa (MM-06) não pode ser criado.

Regra de escolha, nesta ordem:
  1. fica a PAGA mais antiga (foi ela que o aluno realmente quitou);
  2. sem nenhuma paga, fica a mais antiga;
  3. empate de data, fica o menor id.
As demais viram 'cancelado', com o motivo gravado em `fin_auditoria`.

Nada é apagado. A reversão lê a própria auditoria e devolve o status anterior.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_mm_01_cancelar_duplicadas.py            # simula
  .venv/bin/python migrations/executar_mm_01_cancelar_duplicadas.py --aplicar
  .venv/bin/python migrations/executar_mm_01_cancelar_duplicadas.py --reverter
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

ACAO = "cancelar_duplicada_mm01"
ENTIDADE = "mensalidade_aluno"

SQL_GRUPOS = """
SELECT ma.id, ma.aluno_id, ma.mensalidade_id, ma.data_vencimento, ma.valor,
       ma.status, ma.status_pagamento, ma.criado_em, a.nome AS aluno_nome,
       a.id_academia, p.nome AS plano_nome
FROM mensalidade_aluno ma
JOIN alunos a ON a.id = ma.aluno_id
JOIN mensalidades p ON p.id = ma.mensalidade_id
JOIN (SELECT aluno_id, mensalidade_id,
             YEAR(data_vencimento) AS ano, MONTH(data_vencimento) AS mes
      FROM mensalidade_aluno
      WHERE status <> 'cancelado' AND data_vencimento IS NOT NULL
      GROUP BY 1,2,3,4 HAVING COUNT(*) > 1) d
  ON d.aluno_id = ma.aluno_id AND d.mensalidade_id = ma.mensalidade_id
 AND d.ano = YEAR(ma.data_vencimento) AND d.mes = MONTH(ma.data_vencimento)
WHERE ma.status <> 'cancelado'
ORDER BY ma.aluno_id, ma.mensalidade_id, ma.data_vencimento, ma.id
"""


def _agrupar(linhas):
    grupos = {}
    for r in linhas:
        chave = (r["aluno_id"], r["mensalidade_id"],
                 r["data_vencimento"].year, r["data_vencimento"].month)
        grupos.setdefault(chave, []).append(r)
    return grupos


def _escolher(itens):
    """(mantida, [canceladas]) segundo a regra do cabeçalho."""
    def ordem(r):
        return (0 if r["status"] == "pago" else 1,
                r["criado_em"] or r["data_vencimento"], r["id"])
    ordenadas = sorted(itens, key=ordem)
    return ordenadas[0], ordenadas[1:]


def _auditar(cur, r, motivo):
    cur.execute(
        """INSERT INTO fin_auditoria
             (id_academia, entidade, entidade_id, acao, valor_anterior, valor_novo,
              status_anterior, status_novo, motivo, detalhes, usuario_id, ip)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,NULL)""",
        (r["id_academia"], ENTIDADE, r["id"], ACAO, r["valor"], r["valor"],
         r["status"], "cancelado", motivo,
         "vencimento=%s plano=%s" % (r["data_vencimento"], r["plano_nome"])),
    )


def aplicar(simular=True):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(SQL_GRUPOS)
        grupos = _agrupar(cur.fetchall() or [])
        if not grupos:
            print("Nenhuma duplicata encontrada. Nada a fazer.")
            return 0

        total = 0
        print(f"{len(grupos)} competência(s) com duplicata:\n")
        for (aluno_id, plano_id, ano, mes), itens in sorted(grupos.items()):
            mantida, canceladas = _escolher(itens)
            nome = itens[0]["aluno_nome"][:28]
            print(f"  {nome:28} {mes:02d}/{ano}  plano {plano_id}")
            print(f"     MANTÉM  id={mantida['id']:5} venc={mantida['data_vencimento']} "
                  f"R$ {float(mantida['valor'] or 0):7.2f} {mantida['status']}")
            for r in canceladas:
                print(f"     cancela id={r['id']:5} venc={r['data_vencimento']} "
                      f"R$ {float(r['valor'] or 0):7.2f} {r['status']}")
                total += 1
                if not simular:
                    motivo = ("Duplicada da mensalidade %s na competência %02d/%d "
                              "(MM-01)" % (mantida["id"], mes, ano))
                    _auditar(cur, r, motivo)
                    cur.execute(
                        """UPDATE mensalidade_aluno
                              SET status = 'cancelado',
                                  observacoes = CONCAT(COALESCE(observacoes,''), %s)
                            WHERE id = %s AND status <> 'cancelado'""",
                        (" [MM-01] " + motivo, r["id"]),
                    )
        if simular:
            conn.rollback()
            print(f"\nSIMULAÇÃO — {total} registro(s) seriam cancelados. "
                  "Rode com --aplicar para valer.")
        else:
            conn.commit()
            print(f"\n✓ {total} registro(s) cancelados e auditados.")
        return total
    except Exception as e:
        conn.rollback()
        print("Erro:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


def reverter():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT entidade_id, status_anterior FROM fin_auditoria
               WHERE entidade = %s AND acao = %s ORDER BY id""",
            (ENTIDADE, ACAO),
        )
        linhas = cur.fetchall() or []
        if not linhas:
            print("Nada a reverter: não há auditoria deste passo.")
            return 0
        for r in linhas:
            cur.execute(
                "UPDATE mensalidade_aluno SET status = %s WHERE id = %s AND status = 'cancelado'",
                (r["status_anterior"], r["entidade_id"]),
            )
        cur.execute("DELETE FROM fin_auditoria WHERE entidade = %s AND acao = %s",
                    (ENTIDADE, ACAO))
        conn.commit()
        print(f"✓ {len(linhas)} registro(s) restaurados ao status anterior.")
        return len(linhas)
    except Exception as e:
        conn.rollback()
        print("Erro na reversão:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    if "--reverter" in sys.argv:
        reverter()
    else:
        aplicar(simular="--aplicar" not in sys.argv)
