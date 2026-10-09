#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reemite as cobranças cujo link nasceu sem endereço de retorno.

As cobranças criadas pela régua de cobrança foram para a InfinitePay sem
`webhook_url` (o `url_for(_external=True)` não funciona fora de request, a
exceção era engolida e o campo ia None). Resultado: o pagamento acontece e o
gateway não tem para onde avisar — nenhuma baixa automática jamais ocorreu.

A correção no código vale para links novos. Os que já foram enviados continuam
cegos até serem reemitidos — é o que este script faz.

Por que é seguro reemitir:
  * o que foi enviado no WhatsApp é o link curto `/p/<token>`, que resolve a
    URL do gateway **na hora do clique**; reemitir troca o destino sem invalidar
    a mensagem que a pessoa já recebeu;
  * para quem ainda não tem link curto, um é criado antes — e o checkout antigo
    continua de pé na InfinitePay, então ninguém fica sem poder pagar.

O que NÃO faz: não mexe em cobrança paga ou cancelada, não altera valor,
vencimento ou desconto, e não dá baixa em nada.

Uso (na raiz do projeto):
  .venv/bin/python scripts/reemitir_links_sem_webhook.py            # simulação
  .venv/bin/python scripts/reemitir_links_sem_webhook.py --aplicar
  .venv/bin/python scripts/reemitir_links_sem_webhook.py --aplicar --academia 14
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app                                        # noqa: E402
from config import get_db_connection                       # noqa: E402

APLICAR = "--aplicar" in sys.argv
_ACAD = None
if "--academia" in sys.argv:
    try:
        _ACAD = int(sys.argv[sys.argv.index("--academia") + 1])
    except (IndexError, ValueError):
        print("--academia precisa de um id. Ex.: --academia 14")
        sys.exit(2)


def _tem_curto(cur, ma_id):
    """Só consulta: a simulação não pode criar token nenhum."""
    cur.execute("SELECT 1 FROM pagamento_links WHERE origem='mensalidade' AND registro_id=%s",
                (ma_id,))
    return cur.fetchone() is not None


def _abertas(cur):
    sql = """SELECT ma.id, ma.valor, ma.valor_original, ma.desconto_aplicado, ma.id_desconto,
                    ma.data_vencimento, ma.asaas_boleto_url,
                    a.id AS aluno_id, a.nome, a.email, a.telefone, a.cpf,
                    a.cep, a.rua, a.bairro, a.numero, a.complemento, a.cidade, a.estado,
                    a.id_academia, ac.nome AS academia
             FROM mensalidade_aluno ma
             JOIN alunos a ON a.id = ma.aluno_id
             JOIN academias ac ON ac.id = a.id_academia
             WHERE ma.gateway = 'infinitepay'
               AND ma.status NOT IN ('pago', 'cancelado')
               AND ma.asaas_boleto_url IS NOT NULL AND ma.asaas_boleto_url <> ''"""
    params = ()
    if _ACAD:
        sql += " AND a.id_academia = %s"
        params = (_ACAD,)
    cur.execute(sql + " ORDER BY a.id_academia, ma.id", params)
    return cur.fetchall()


def main():
    with app.app_context():
        from blueprints.financeiro.routes import (
            _gateway_config_academia, _emitir_cobranca_online, _endereco_aluno,
        )
        from utils.links_curtos import obter_token

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            linhas = _abertas(cur)
            for r in linhas:
                r["_curto"] = _tem_curto(cur, r["id"])
        finally:
            cur.close()
            conn.close()

        print(f"\nCobranças InfinitePay em aberto a reemitir: {len(linhas)}")
        if not linhas:
            return 0
        for r in linhas:
            curto = "sim" if r["_curto"] else "não (será criado)"
            print(f"  #{r['id']:>5}  {r['academia'][:26]:26}  R$ {float(r['valor']):>8.2f}  "
                  f"venc {r['data_vencimento']}  link curto: {curto}  {r['nome'][:24]}")
        if not APLICAR:
            print("\nSimulação. Rode com --aplicar para reemitir de verdade "
                  "(uma chamada à InfinitePay por cobrança).")
            return 0

        ok = falhou = 0
        for r in linhas:
            # Link curto primeiro: é ele que sobrevive à troca do checkout.
            obter_token("mensalidade", r["id"], r["id_academia"])
            cfg = _gateway_config_academia(r["id_academia"])
            conn = get_db_connection()
            cur = conn.cursor(dictionary=True)
            try:
                novo = _emitir_cobranca_online(
                    cfg, "PIX", nome=r["nome"], cpf=r.get("cpf"), email=r.get("email"),
                    telefone=r.get("telefone"), valor=float(r["valor"]),
                    vencimento=r["data_vencimento"],
                    descricao=f"Mensalidade - {r['nome']}",
                    origem="mensalidade", registro_id=r["id"],
                    endereco=_endereco_aluno(r),
                )
                cur.execute(
                    """UPDATE mensalidade_aluno
                       SET asaas_payment_id=%s, asaas_tipo=%s, asaas_boleto_url=%s,
                           asaas_pix_qrcode=%s, asaas_pix_copia_cola=%s, gateway=%s
                       WHERE id=%s""",
                    (novo["payment_id"], novo["tipo"], novo["boleto_url"],
                     novo["pix_qrcode"], novo["pix_copia_cola"], novo["gateway"], r["id"]),
                )
                conn.commit()
                ok += 1
                print(f"  ✓ #{r['id']} reemitida")
            except Exception as e:                                   # noqa: BLE001
                falhou += 1
                print(f"  ✗ #{r['id']} falhou: {e}")
            finally:
                cur.close()
                conn.close()
        print(f"\n✓ Reemitidas: {ok}   ✗ falhas: {falhou}")
        return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main())
