"""Conferência entre o gateway de pagamento e o sistema.

O que falta conferir em academia que cobra por link (hoje InfinitePay): o
gateway avisa o pagamento (webhook / retorno do pagador) e o sistema dá baixa.
Quando uma ponta falha, ninguém percebe — o aviso que não chega é silencioso,
e a baixa que falha no meio só deixa uma linha no log do servidor.

Duas partes:
  1. Registro dos avisos (tabela `gateway_eventos`, criada sob demanda):
     cada aviso de pagamento com gateway, cobrança, valor e o que aconteceu
     ('baixado', 'ja_pago', 'nao_encontrado', 'erro'). A InfinitePay não deixa
     perguntar se um link em aberto foi pago (só confirma quem acabou de
     pagar), então este registro é a única trilha do lado do gateway.
  2. `pendencias(cur, academia)`: as listas da tela Caixa › Conferência.
"""
import json
import logging

from config import get_db_connection

log = logging.getLogger(__name__)
_TABELA_OK = False

DIAS_LINK_VELHO = 30


def garantir_tabela(cur):
    global _TABELA_OK
    if _TABELA_OK:
        return
    cur.execute("""CREATE TABLE IF NOT EXISTS gateway_eventos (
        id INT AUTO_INCREMENT PRIMARY KEY,
        gateway VARCHAR(30) NOT NULL,
        origem VARCHAR(20) NULL,            -- mensalidade | avulsa | grupo | matricula
        registro_id INT NULL,
        id_academia INT NULL,
        valor DECIMAL(10,2) NULL,
        resultado VARCHAR(20) NOT NULL DEFAULT 'recebido',
        detalhe VARCHAR(500) NULL,
        recebido_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        KEY ix_gw_academia (id_academia, recebido_em),
        KEY ix_gw_registro (origem, registro_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    _TABELA_OK = True


def registrar(gateway, origem, registro_id, valor=None, resultado="recebido", detalhe=None,
              id_academia=None):
    """Grava um aviso do gateway. Conexão própria: nunca interfere na baixa e
    nunca levanta. Devolve o id do evento (ou None)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            garantir_tabela(cur)
            consulta = {
                "mensalidade": """SELECT m.id_academia FROM mensalidade_aluno ma
                                  JOIN mensalidades m ON m.id = ma.mensalidade_id WHERE ma.id = %s""",
                "avulsa": "SELECT id_academia FROM cobranca_avulsa WHERE id = %s",
                "grupo": "SELECT id_academia FROM cobranca_grupo WHERE id = %s",
            }.get(origem)
            if id_academia is None and registro_id and consulta:
                cur.execute(consulta, (registro_id,))
                r = cur.fetchone()
                id_academia = r[0] if r else None
            if isinstance(detalhe, (dict, list)):
                detalhe = json.dumps(detalhe, ensure_ascii=False, default=str)
            cur.execute("""INSERT INTO gateway_eventos (gateway, origem, registro_id, id_academia, valor,
                                                        resultado, detalhe)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        (gateway, origem, registro_id, id_academia, valor, resultado,
                         (detalhe or "")[:500] or None))
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()
    except Exception:
        log.warning("Evento do gateway não registrado", exc_info=True)
        return None


def resultado(evento_id, res, detalhe=None):
    if not evento_id:
        return
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("UPDATE gateway_eventos SET resultado = %s, detalhe = COALESCE(%s, detalhe) WHERE id = %s",
                        (res, (detalhe or "")[:500] or None, evento_id))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        log.warning("Resultado do evento %s não registrado", evento_id, exc_info=True)


def pendencias(cur, id_academia):
    """Listas da conferência. Cada item é um dict pronto para a tela."""
    garantir_tabela(cur)
    out = {}

    # 1. O gateway avisou que pagou e a cobrança não está paga aqui.
    cur.execute(
        """SELECT e.id, e.gateway, e.origem, e.registro_id, e.valor, e.resultado, e.detalhe, e.recebido_em,
                  COALESCE(a1.nome, a2.nome) AS aluno,
                  COALESCE(ma.status, ca.status) AS status_atual
           FROM gateway_eventos e
           LEFT JOIN mensalidade_aluno ma ON e.origem = 'mensalidade' AND ma.id = e.registro_id
           LEFT JOIN alunos a1 ON a1.id = ma.aluno_id
           LEFT JOIN cobranca_avulsa ca ON e.origem = 'avulsa' AND ca.id = e.registro_id
           LEFT JOIN alunos a2 ON a2.id = ca.aluno_id
           WHERE e.id_academia = %s AND e.resultado IN ('erro', 'nao_encontrado', 'recebido')
             AND COALESCE(ma.status, ca.status, '') <> 'pago'
           ORDER BY e.recebido_em DESC LIMIT 100""", (id_academia,))
    out["aviso_sem_baixa"] = cur.fetchall()

    # 2. Paga aqui, com valor, e sem receita: o dinheiro não aparece em lugar nenhum.
    cur.execute(
        """SELECT ma.id, a.nome AS aluno, ma.valor_pago AS valor, ma.data_pagamento, ma.gateway,
                  'mensalidade' AS origem
           FROM mensalidade_aluno ma JOIN mensalidades m ON m.id = ma.mensalidade_id
           JOIN alunos a ON a.id = ma.aluno_id
           WHERE m.id_academia = %s AND ma.status = 'pago' AND COALESCE(ma.valor_pago, ma.valor) > 0
             AND NOT EXISTS (SELECT 1 FROM receitas r WHERE r.id_mensalidade_aluno = ma.id
                             AND COALESCE(r.cancelada, 0) = 0)
           UNION ALL
           SELECT ca.id, a.nome, ca.valor_pago, ca.data_pagamento, ca.gateway, 'avulsa'
           FROM cobranca_avulsa ca JOIN alunos a ON a.id = ca.aluno_id
           WHERE ca.id_academia = %s AND ca.status = 'pago' AND COALESCE(ca.valor_pago, ca.valor) > 0
             AND NOT EXISTS (SELECT 1 FROM receitas r WHERE r.id_cobranca_avulsa = ca.id
                             AND COALESCE(r.cancelada, 0) = 0)
           ORDER BY data_pagamento DESC LIMIT 100""", (id_academia, id_academia))
    out["pago_sem_receita"] = cur.fetchall()

    # 3. Receita fora do caixa (academia com controle ligado).
    cur.execute(
        """SELECT r.id, r.descricao, r.valor, r.data FROM receitas r
           JOIN fin_config f ON f.id_academia = r.id_academia AND f.modo IN ('parcial', 'total')
           WHERE r.id_academia = %s AND r.id_lancamento IS NULL AND r.valor > 0
             AND COALESCE(r.cancelada, 0) = 0
           ORDER BY r.data DESC LIMIT 100""", (id_academia,))
    out["receita_fora_caixa"] = cur.fetchall()

    # 4. Link de pagamento ainda ativo em cobrança paga/cancelada — dá para pagar de novo.
    cur.execute(
        """SELECT ma.id, a.nome AS aluno, ma.status, ma.valor, ma.data_vencimento, ma.gateway
           FROM mensalidade_aluno ma JOIN mensalidades m ON m.id = ma.mensalidade_id
           JOIN alunos a ON a.id = ma.aluno_id
           WHERE m.id_academia = %s AND ma.status = 'cancelado'
             AND COALESCE(ma.asaas_boleto_url, ma.cora_boleto_url, '') <> ''
           ORDER BY ma.data_vencimento DESC LIMIT 100""", (id_academia,))
    out["link_em_cancelada"] = cur.fetchall()

    # 5. Mensalidade numa cobrança familiar em aberto que ainda tem link individual.
    cur.execute(
        """SELECT ma.id, a.nome AS aluno, ma.valor, ma.data_vencimento, g.id AS grupo_id,
                  f.responsavel_nome
           FROM cobranca_grupo_item i
           JOIN cobranca_grupo g ON g.id = i.grupo_id AND g.status IN ('pendente', 'atrasado')
           JOIN familia_cobranca f ON f.id = g.familia_id
           JOIN mensalidade_aluno ma ON ma.id = i.registro_id AND COALESCE(i.origem, 'mensalidade') = 'mensalidade'
           JOIN alunos a ON a.id = ma.aluno_id
           WHERE g.id_academia = %s AND ma.status IN ('pendente', 'atrasado')
             AND COALESCE(ma.asaas_boleto_url, ma.cora_boleto_url, '') <> ''
           ORDER BY ma.data_vencimento DESC""", (id_academia,))
    out["familia_com_link_individual"] = cur.fetchall()

    # 6. Em aberto com link do gateway, vencida há mais de 30 dias: conferir no app do gateway.
    cur.execute(
        """SELECT ma.id, a.nome AS aluno, ma.valor, ma.data_vencimento, ma.gateway,
                  DATEDIFF(CURDATE(), ma.data_vencimento) AS dias
           FROM mensalidade_aluno ma JOIN mensalidades m ON m.id = ma.mensalidade_id
           JOIN alunos a ON a.id = ma.aluno_id
           WHERE m.id_academia = %s AND ma.status IN ('pendente', 'atrasado')
             AND COALESCE(ma.asaas_boleto_url, ma.cora_boleto_url, '') <> ''
             AND ma.data_vencimento < CURDATE() - INTERVAL %s DAY
           ORDER BY ma.data_vencimento LIMIT 100""", (id_academia, DIAS_LINK_VELHO))
    out["link_velho_em_aberto"] = cur.fetchall()

    out["total"] = sum(len(v) for v in out.values())
    return out
