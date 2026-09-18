# -*- coding: utf-8 -*-
"""Cobrança familiar: uma cobrança única para as mensalidades de irmãos.

Uma família de três alunos recebia três links e pagava três vezes. Aqui ela vira
um grupo: as mensalidades continuam individuais no financeiro (cada aluno com o
seu valor e o seu desconto), mas o gateway emite **uma** cobrança com a soma, e o
pagamento dá baixa em todas de uma vez.

A família é identificada pelo CPF do responsável financeiro. Os membros não são
gravados em lugar nenhum: são sempre os alunos ativos daquela academia com aquele
CPF — assim irmão que entra passa a ser cobrado junto, e irmão que sai deixa de
ser, sem ninguém mexer no cadastro.

O valor de cada item sai de `_valor_com_desconto`, o mesmo cálculo da cobrança
individual, então o desconto família de `aluno_desconto` já vem embutido e o
relatório por aluno continua fechando.

Referência no gateway: `grupo-<id>` (o `external_reference` / `order_nsu`), lida
pelos webhooks para achar o grupo de volta.
"""
import re
from datetime import date

from config import get_db_connection

# Uma cobrança de família com um item só é uma cobrança individual com nome
# pomposo — e ainda esconderia a mensalidade da tela normal. Não monta.
MIN_ITENS = 2

# `alunos` está em utf8mb4_uca1400_ai_ci (MariaDB 11) e as tabelas novas em
# utf8mb4_unicode_ci, o padrão do schema. Comparar coluna com coluna entre as
# duas dá "Illegal mix of collations", então o lado do aluno é convertido para a
# collation fixada no CREATE TABLE da migração. CPF é só dígito: a conversão não
# muda comparação nenhuma, só destrava o JOIN.
COLLATE_CPF = "COLLATE utf8mb4_unicode_ci"

# CPF do responsável na ficha do aluno, sem pontuação e já na collation certa.
CPF_ALUNO_SQL = (
    "REPLACE(REPLACE(REPLACE(a.responsavel_financeiro_cpf,'.',''),'-',''),' ','') " + COLLATE_CPF
)


def so_digitos(v):
    return re.sub(r"\D", "", str(v or ""))


# ---------------------------------------------------------------------------
# Famílias
# ---------------------------------------------------------------------------
def familias_candidatas(academia_id):
    """Responsáveis financeiros com 2+ alunos ativos na academia.

    Devolve uma linha por família, já com o id de `familia_cobranca` quando ela
    foi marcada para cobrar junto (`familia_id` None = ainda não ativada).

    O alias é `cpf_resp`, e não `cpf`, de propósito: existe uma coluna `alunos.cpf`
    e o MySQL resolve o GROUP BY para a coluna em vez do alias. Com o nome `cpf`,
    o agrupamento saía pelo CPF do ALUNO — os 17 alunos que compartilham um CPF
    placeholder viravam uma família só.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            f"""
            SELECT {CPF_ALUNO_SQL} AS cpf_resp,
                   MAX(a.responsavel_financeiro_nome) AS responsavel,
                   COUNT(*) AS qtd,
                   GROUP_CONCAT(a.nome ORDER BY a.nome SEPARATOR ', ') AS alunos,
                   f.id AS familia_id, COALESCE(f.ativo, 0) AS ativo
            FROM alunos a
            LEFT JOIN familia_cobranca f
                   ON f.id_academia = a.id_academia
                  AND f.responsavel_cpf = {CPF_ALUNO_SQL}
            WHERE a.id_academia = %s AND COALESCE(a.ativo,1) = 1 AND a.status = 'ativo'
              AND COALESCE(a.responsavel_financeiro_cpf,'') <> ''
            GROUP BY cpf_resp, f.id, f.ativo
            HAVING COUNT(*) >= %s
            ORDER BY qtd DESC, responsavel
            """,
            (academia_id, MIN_ITENS),
        )
        return cur.fetchall() or []
    finally:
        cur.close()
        conn.close()


def membros(academia_id, cpf):
    """Alunos ativos da academia sob aquele CPF de responsável financeiro."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            f"""SELECT a.* FROM alunos a
               WHERE a.id_academia = %s AND COALESCE(a.ativo,1) = 1 AND a.status = 'ativo'
                 AND {CPF_ALUNO_SQL} = %s
               ORDER BY a.nome""",
            (academia_id, so_digitos(cpf)),
        )
        return cur.fetchall() or []
    finally:
        cur.close()
        conn.close()


def ativar_familia(academia_id, cpf):
    """Marca a família para cobrar junto. Idempotente; devolve o familia_id."""
    cpf_d = so_digitos(cpf)
    if not cpf_d:
        return None
    ms = membros(academia_id, cpf_d)
    if len(ms) < MIN_ITENS:
        return None
    ref = ms[0]
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """INSERT INTO familia_cobranca
                   (id_academia, responsavel_cpf, responsavel_nome, responsavel_email,
                    responsavel_telefone, ativo)
               VALUES (%s,%s,%s,%s,%s,1)
               ON DUPLICATE KEY UPDATE ativo=1, responsavel_nome=VALUES(responsavel_nome),
                    responsavel_email=VALUES(responsavel_email),
                    responsavel_telefone=VALUES(responsavel_telefone)""",
            (academia_id, cpf_d,
             ref.get("responsavel_financeiro_nome") or ref.get("nome"),
             ref.get("email"),
             ref.get("responsavel_financeiro_telefone") or ref.get("tel_celular") or ref.get("telefone")),
        )
        conn.commit()
        cur.execute(
            "SELECT id FROM familia_cobranca WHERE id_academia=%s AND responsavel_cpf=%s",
            (academia_id, cpf_d),
        )
        r = cur.fetchone()
        return r["id"] if r else None
    finally:
        cur.close()
        conn.close()


def desativar_familia(familia_id):
    """Desliga a cobrança conjunta e solta as mensalidades dos grupos ainda abertos.

    Sem soltar os itens, as mensalidades ficariam invisíveis para o lembrete
    individual e ninguém cobraria mais aquela família.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE familia_cobranca SET ativo=0 WHERE id=%s", (familia_id,))
        cur.execute(
            """DELETE i FROM cobranca_grupo_item i
               JOIN cobranca_grupo g ON g.id = i.grupo_id
               WHERE g.familia_id=%s AND g.status IN ('pendente','atrasado')""",
            (familia_id,),
        )
        cur.execute(
            "UPDATE cobranca_grupo SET status='cancelado' "
            "WHERE familia_id=%s AND status IN ('pendente','atrasado')",
            (familia_id,),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Montagem do grupo do mês
# ---------------------------------------------------------------------------
def montar_grupo(familia_id, ano, mes):
    """Monta (ou remonta) a cobrança do mês de uma família.

    Junta as mensalidades em aberto dos membros com vencimento no mês, soma os
    valores já com desconto e grava o grupo. Remonta sem medo: enquanto o grupo
    está pendente, os itens são refeitos e o link é descartado se o total mudou —
    um link com valor velho é pior do que link nenhum.

    Devolve {"grupo_id", "valor_total", "itens", "motivo"}. `motivo` preenchido
    quando não deu para montar.
    """
    from blueprints.financeiro.routes import _valor_com_desconto

    competencia = date(ano, mes, 1)
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM familia_cobranca WHERE id=%s", (familia_id,))
        fam = cur.fetchone()
        if not fam or not fam.get("ativo"):
            return {"grupo_id": None, "valor_total": 0, "itens": [], "motivo": "familia_inativa"}
        academia_id = fam["id_academia"]

        cur.execute(
            "SELECT id, status FROM cobranca_grupo WHERE familia_id=%s AND competencia=%s",
            (familia_id, competencia),
        )
        grupo = cur.fetchone()
        if grupo and grupo["status"] in ("pago", "cancelado"):
            return {"grupo_id": grupo["id"], "valor_total": 0, "itens": [],
                    "motivo": "grupo_" + grupo["status"]}
        grupo_id = grupo["id"] if grupo else None

        # Mensalidades em aberto do mês, dos alunos daquele responsável. O escopo
        # é o plano (mensalidades.id_academia): aluno em duas academias não pode
        # ter a cobrança de uma entrando no grupo da outra.
        cur.execute(
            f"""SELECT ma.*, a.id AS a_id, a.nome AS aluno_nome, a.id_academia
               FROM mensalidade_aluno ma
               JOIN alunos a ON a.id = ma.aluno_id
               JOIN mensalidades m ON m.id = ma.mensalidade_id
               LEFT JOIN cobranca_grupo_item gi
                      ON gi.origem = 'mensalidade' AND gi.registro_id = ma.id
               LEFT JOIN cobranca_grupo g2 ON g2.id = gi.grupo_id
               WHERE a.id_academia = %s AND m.id_academia = %s
                 AND COALESCE(a.ativo,1)=1 AND a.status='ativo'
                 AND {CPF_ALUNO_SQL} = %s
                 AND ma.status IN ('pendente','atrasado')
                 AND YEAR(ma.data_vencimento)=%s AND MONTH(ma.data_vencimento)=%s
                 AND (gi.id IS NULL OR g2.id = %s)
               ORDER BY a.nome""",
            (academia_id, academia_id, fam["responsavel_cpf"], ano, mes, grupo_id or 0),
        )
        candidatas = [dict(c, origem="mensalidade") for c in (cur.fetchall() or [])]

        # Cobranças avulsas dos mesmos irmãos, no mesmo mês. Taxa de exame,
        # uniforme, qualquer valor lançado para o aluno entra na soma da família —
        # senão cada irmão recebia a sua, que é o que o grupo veio evitar.
        cur.execute(
            f"""SELECT ca.id, ca.aluno_id, ca.valor, ca.data_vencimento, ca.status,
                       a.id AS a_id, a.nome AS aluno_nome, a.id_academia
                FROM cobranca_avulsa ca
                JOIN alunos a ON a.id = ca.aluno_id
                LEFT JOIN cobranca_grupo_item gi
                       ON gi.origem = 'avulsa' AND gi.registro_id = ca.id
                LEFT JOIN cobranca_grupo g2 ON g2.id = gi.grupo_id
                WHERE a.id_academia = %s AND ca.id_academia = %s
                  AND COALESCE(a.ativo,1)=1 AND a.status='ativo'
                  AND {CPF_ALUNO_SQL} = %s
                  AND ca.status IN ('pendente','atrasado')
                  AND YEAR(ca.data_vencimento)=%s AND MONTH(ca.data_vencimento)=%s
                  AND (gi.id IS NULL OR g2.id = %s)
                ORDER BY a.nome""",
            (academia_id, academia_id, fam["responsavel_cpf"], ano, mes, grupo_id or 0),
        )
        candidatas += [dict(c, origem="avulsa") for c in (cur.fetchall() or [])]

        itens = []
        total = 0.0
        for ma in candidatas:
            if ma.get("origem") == "avulsa":
                # Avulsa já vem com o valor final: desconto de mensalidade não
                # se aplica a taxa de exame nem a uniforme.
                valor_final = round(float(ma.get("valor") or 0), 2)
            else:
                _vi, _vd, valor_final, _nome = _valor_com_desconto(ma, ma["a_id"], academia_id)
            valor_final = round(float(valor_final or 0), 2)
            # Desconto integral zera a cobrança: não entra na soma nem ocupa
            # vaga no grupo — essas mensalidades já nascem quitadas.
            if valor_final <= 0:
                continue
            itens.append({"origem": ma.get("origem") or "mensalidade",
                          "registro_id": ma["id"],
                          "mensalidade_aluno_id": ma["id"] if ma.get("origem") != "avulsa" else None,
                          "aluno_id": ma["a_id"],
                          "aluno_nome": ma["aluno_nome"], "valor": valor_final,
                          "vencimento": ma["data_vencimento"]})
            total += valor_final
        total = round(total, 2)

        if len(itens) < MIN_ITENS:
            # Sobrou um irmão só (o outro pagou, saiu, ou é bolsista integral):
            # desmonta o grupo para a mensalidade voltar à cobrança normal.
            if grupo_id:
                cur.execute("DELETE FROM cobranca_grupo_item WHERE grupo_id=%s", (grupo_id,))
                cur.execute("UPDATE cobranca_grupo SET status='cancelado' WHERE id=%s", (grupo_id,))
                conn.commit()
            return {"grupo_id": None, "valor_total": 0, "itens": itens, "motivo": "itens_insuficientes"}

        vencimento = min(i["vencimento"] for i in itens)
        if grupo_id:
            cur.execute("SELECT valor_total FROM cobranca_grupo WHERE id=%s", (grupo_id,))
            antes = float((cur.fetchone() or {}).get("valor_total") or 0)
            # Total mudou: o link emitido cobra o valor errado e precisa cair.
            zera_link = abs(antes - total) >= 0.01
            cur.execute(
                """UPDATE cobranca_grupo SET valor_total=%s, data_vencimento=%s, status='pendente'
                   WHERE id=%s""",
                (total, vencimento, grupo_id),
            )
            if zera_link:
                cur.execute(
                    """UPDATE cobranca_grupo SET gateway=NULL, payment_id=NULL, link=NULL,
                           qrcode=NULL, copia_cola=NULL WHERE id=%s""",
                    (grupo_id,),
                )
            cur.execute("DELETE FROM cobranca_grupo_item WHERE grupo_id=%s", (grupo_id,))
        else:
            cur.execute(
                """INSERT INTO cobranca_grupo
                       (familia_id, id_academia, competencia, data_vencimento, valor_total, status)
                   VALUES (%s,%s,%s,%s,%s,'pendente')""",
                (familia_id, academia_id, competencia, vencimento, total),
            )
            grupo_id = cur.lastrowid

        for i in itens:
            cur.execute(
                """INSERT INTO cobranca_grupo_item
                       (grupo_id, origem, registro_id, mensalidade_aluno_id, aluno_id, valor)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (grupo_id, i["origem"], i["registro_id"],
                 i["mensalidade_aluno_id"], i["aluno_id"], i["valor"]),
            )
        conn.commit()
        return {"grupo_id": grupo_id, "valor_total": total, "itens": itens, "motivo": ""}
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def montar_grupos_do_mes(academia_id, ano, mes):
    """Monta o grupo do mês de todas as famílias ativas da academia."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id FROM familia_cobranca WHERE id_academia=%s AND ativo=1",
            (academia_id,),
        )
        ids = [r["id"] for r in cur.fetchall() or []]
    finally:
        cur.close()
        conn.close()
    montados = 0
    for fid in ids:
        try:
            if montar_grupo(fid, ano, mes).get("grupo_id"):
                montados += 1
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Falha ao montar grupo da família %s", fid)
    return montados


# ---------------------------------------------------------------------------
# Cobrança no gateway
# ---------------------------------------------------------------------------
def carregar_grupo(grupo_id):
    """Grupo + família + itens (com nome do aluno), ou None."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT g.*, f.responsavel_cpf, f.responsavel_nome,
                      f.responsavel_email, f.responsavel_telefone
               FROM cobranca_grupo g JOIN familia_cobranca f ON f.id = g.familia_id
               WHERE g.id=%s""",
            (grupo_id,),
        )
        g = cur.fetchone()
        if not g:
            return None
        cur.execute(
            """SELECT i.*, a.nome AS aluno_nome,
                      COALESCE(ma.data_vencimento, ca.data_vencimento) AS data_vencimento,
                      COALESCE(ma.status, ca.status) AS ma_status
               FROM cobranca_grupo_item i
               JOIN alunos a ON a.id = i.aluno_id
               LEFT JOIN mensalidade_aluno ma
                      ON i.origem = 'mensalidade' AND ma.id = i.registro_id
               LEFT JOIN cobranca_avulsa ca
                      ON i.origem = 'avulsa' AND ca.id = i.registro_id
               WHERE i.grupo_id=%s ORDER BY a.nome""",
            (grupo_id,),
        )
        g["itens"] = cur.fetchall() or []
        return g
    finally:
        cur.close()
        conn.close()


def gerar_link(grupo_id, forcar=False):
    """Emite a cobrança única do grupo no gateway ativo da academia.

    Devolve (ok, mensagem). Reaproveita o link já emitido, salvo com `forcar`.
    """
    from blueprints.financeiro.routes import (
        _gateway_config_academia, _gateway_ativo, _emitir_cobranca_online, _endereco_aluno,
    )

    g = carregar_grupo(grupo_id)
    if not g:
        return False, "Grupo não encontrado."
    if g["status"] == "pago":
        return False, "Esta cobrança já foi paga."
    if g.get("link") and not forcar:
        return True, "Link já emitido."
    if float(g.get("valor_total") or 0) <= 0:
        return False, "Grupo sem valor a cobrar."

    cfg = _gateway_config_academia(g["id_academia"])
    if not _gateway_ativo(cfg):
        return False, "A academia não tem gateway de cobrança online configurado."

    # Gateway recusa vencimento no passado; o vencimento do grupo não muda,
    # quem manda no atraso continua sendo a data das mensalidades.
    venc = g["data_vencimento"]
    if venc and venc < date.today():
        venc = date.today()

    nomes = ", ".join(i["aluno_nome"].split(" ")[0] for i in g["itens"])
    descricao = f"Mensalidades {g['competencia'].strftime('%m/%Y')} - {nomes}"

    # Endereço do primeiro irmão: o Cora exige endereço completo no boleto e a
    # família mora junta, então qualquer um dos membros serve.
    endereco = None
    try:
        _cn = get_db_connection(); _cc = _cn.cursor(dictionary=True)
        _cc.execute(
            "SELECT cep, rua, numero, complemento, bairro, cidade, estado FROM alunos WHERE id=%s",
            (g["itens"][0]["aluno_id"],),
        )
        _row = _cc.fetchone()
        _cc.close(); _cn.close()
        if _row:
            endereco = _endereco_aluno(_row)
    except Exception:
        endereco = None

    try:
        r = _emitir_cobranca_online(
            cfg, "PIX",
            nome=g.get("responsavel_nome") or nomes,
            cpf=so_digitos(g.get("responsavel_cpf")),
            email=g.get("responsavel_email"),
            telefone=g.get("responsavel_telefone"),
            valor=float(g["valor_total"]),
            vencimento=venc,
            descricao=descricao,
            origem="grupo", registro_id=grupo_id,
            endereco=endereco,
        )
    except Exception as e:
        return False, f"O gateway recusou a cobrança: {e}"
    if not r:
        return False, "O gateway não devolveu a cobrança."

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """UPDATE cobranca_grupo SET gateway=%s, payment_id=%s, link=%s,
                   qrcode=%s, copia_cola=%s WHERE id=%s""",
            (r.get("gateway"), r.get("payment_id"), r.get("boleto_url"),
             r.get("pix_qrcode"), r.get("pix_copia_cola"), grupo_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()
    return True, "Cobrança única emitida."


# ---------------------------------------------------------------------------
# Baixa
# ---------------------------------------------------------------------------
def baixar_grupo(grupo_id, valor_pago=None, gateway_nome="gateway", data_pagamento=None):
    """Dá baixa em TODAS as mensalidades do grupo e lança as receitas.

    O valor pago é rateado na proporção do valor de cada item, com a sobra do
    arredondamento indo para o último — assim a soma das receitas bate no centavo
    com o que entrou, e o relatório por aluno continua correto.

    Idempotente: grupo já pago não faz nada (os gateways reenviam o webhook).
    """
    import logging
    log = logging.getLogger(__name__)

    g = carregar_grupo(grupo_id)
    if not g:
        return False
    if g["status"] == "pago":
        return True
    itens = [i for i in g["itens"] if i["ma_status"] not in ("pago", "cancelado")]
    if not itens:
        # Todas as cobranças já foram baixadas uma a uma, mas o grupo continuou
        # aberto — era o que acontecia antes de a baixa individual reconhecer
        # grupo formado por avulsas. Aqui ele só é fechado para bater com a
        # realidade: nenhuma receita é lançada, porque cada baixa já lançou a
        # sua, e repetir contaria o dinheiro duas vezes.
        if g.get("status") == "pago":
            return True
        pagos = [i for i in g["itens"] if i["ma_status"] == "pago"]
        if not pagos:
            return False
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                """UPDATE cobranca_grupo
                      SET status='pago', valor_pago=COALESCE(valor_pago, %s),
                          data_pagamento=COALESCE(data_pagamento, %s)
                    WHERE id=%s""",
                (sum(float(i["valor"] or 0) for i in pagos),
                 data_pagamento or date.today(), grupo_id))
            conn.commit()
            log.info("Grupo %s fechado: os %d itens já estavam pagos individualmente",
                     grupo_id, len(pagos))
            return True
        except Exception:
            conn.rollback()
            log.exception("Fechamento do grupo %s falhou", grupo_id)
            return False
        finally:
            cur.close()
            conn.close()

    dia = data_pagamento or date.today()
    total = float(g.get("valor_total") or 0)
    recebido = float(valor_pago or total or 0)
    fator = (recebido / total) if total > 0 else 1.0

    rateio = []
    acumulado = 0.0
    for idx, i in enumerate(itens):
        if idx == len(itens) - 1:
            v = round(recebido - acumulado, 2)
        else:
            v = round(float(i["valor"]) * fator, 2)
            acumulado += v
        rateio.append((i, v))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        for i, v in rateio:
            # A baixa cai na tabela da origem do item: o grupo pode misturar
            # mensalidade e cobrança avulsa dos irmãos.
            if (i.get("origem") or "mensalidade") == "avulsa":
                cur.execute(
                    """UPDATE cobranca_avulsa
                       SET status='pago', data_pagamento=%s, valor_pago=%s
                       WHERE id=%s AND status <> 'pago'""",
                    (dia, v, i["registro_id"]),
                )
            else:
                cur.execute(
                    """UPDATE mensalidade_aluno
                       SET status='pago', status_pagamento='pago', data_pagamento=%s, valor_pago=%s
                       WHERE id=%s AND status <> 'pago'""",
                    (dia, v, i["registro_id"]),
                )
        cur.execute(
            "UPDATE cobranca_grupo SET status='pago', valor_pago=%s, data_pagamento=%s WHERE id=%s",
            (recebido, dia, grupo_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        cur.close()
        conn.close()
        log.exception("Baixa do grupo %s falhou", grupo_id)
        return False

    # Receitas em transação separada: falha aqui não desfaz a baixa.
    try:
        for i, v in rateio:
            # A receita aponta para o registro certo e entra na categoria dele:
            # avulsa somada em "Mensalidades" desmontaria o relatório por categoria.
            if (i.get("origem") or "mensalidade") == "avulsa":
                cur.execute(
                    """INSERT INTO receitas (descricao, valor, data, categoria,
                                             id_academia, id_cobranca_avulsa)
                       VALUES (%s, %s, %s, 'Cobrança avulsa', %s, %s)""",
                    (f"Cobrança avulsa - {i['aluno_nome']} (cobrança familiar {gateway_nome})",
                     v, dia, g["id_academia"], i["registro_id"]),
                )
            else:
                cur.execute(
                    """INSERT INTO receitas (descricao, valor, data, categoria,
                                             id_academia, id_mensalidade_aluno)
                       VALUES (%s, %s, %s, 'Mensalidades', %s, %s)""",
                    (f"Mensalidade - {i['aluno_nome']} (cobrança familiar {gateway_nome})",
                     v, dia, g["id_academia"], i["registro_id"]),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        log.exception("Grupo %s: baixa OK, receita falhou", grupo_id)
    finally:
        cur.close()
        conn.close()

    # Uma confirmação para o responsável, não uma por filho.
    try:
        from utils.whatsapp_lembretes import enviar_evento
        tel = g.get("responsavel_telefone")
        if tel:
            conn2 = get_db_connection(); cur2 = conn2.cursor()
            cur2.execute("SELECT nome FROM academias WHERE id=%s", (g["id_academia"],))
            row = cur2.fetchone()
            cur2.close(); conn2.close()
            enviar_evento(g["id_academia"], "confirmacao_pagamento", tel, {
                "nome": (g.get("responsavel_nome") or "").split(" ")[0],
                "aluno": ", ".join(i["aluno_nome"] for i in itens),
                "valor": f"R$ {recebido:.2f}".replace(".", ","),
                "academia": row[0] if row else "",
            })
    except Exception:
        log.exception("Grupo %s: confirmação no WhatsApp falhou", grupo_id)
    return True


# ---------------------------------------------------------------------------
# Integração com a cobrança individual
# ---------------------------------------------------------------------------
def ids_em_grupo_aberto(academia_id=None):
    """IDs de mensalidade_aluno cobertos por um grupo ainda em aberto.

    O lembrete individual usa isto para não cobrar de novo o que já está na
    cobrança da família — senão a mãe recebe três links e paga um.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        sql = ("""SELECT i.registro_id AS mensalidade_aluno_id FROM cobranca_grupo_item i
                  JOIN cobranca_grupo g ON g.id = i.grupo_id
                  WHERE g.status IN ('pendente','atrasado')""")
        params = ()
        if academia_id:
            sql += " AND g.id_academia = %s"
            params = (academia_id,)
        cur.execute(sql, params)
        return {r[0] for r in cur.fetchall() or []}
    except Exception:
        # Tabela ainda não migrada: sem grupo, tudo é cobrança individual.
        return set()
    finally:
        cur.close()
        conn.close()


def grupo_da_mensalidade(mensalidade_aluno_id, origem="mensalidade"):
    """Grupo aberto que cobre esta cobrança, ou None.

    A origem é parâmetro desde que o grupo passou a juntar também taxas avulsas:
    fixá-la em 'mensalidade' fazia a baixa de uma avulsa não encontrar o grupo,
    e os irmãos ficavam em aberto depois de o responsável já ter pago tudo.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT g.* FROM cobranca_grupo_item i
               JOIN cobranca_grupo g ON g.id = i.grupo_id
               WHERE i.origem = %s AND i.registro_id = %s
                 AND g.status IN ('pendente','atrasado')
               LIMIT 1""",
            (origem, mensalidade_aluno_id),
        )
        return cur.fetchone()
    except Exception:
        return None
    finally:
        cur.close()
        conn.close()


def grupo_com_itens_da_mensalidade(mensalidade_aluno_id, origem="mensalidade"):
    """Grupo (aberto ou pago) que cobre esta mensalidade, com os irmãos dentro.

    É o que o painel do aluno/responsável precisa para mostrar UMA cobrança com
    o total da família em vez de três mensalidades soltas — e para dizer de quem
    são. Devolve None quando a mensalidade é cobrada individualmente.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT g.* FROM cobranca_grupo_item i
               JOIN cobranca_grupo g ON g.id = i.grupo_id
               WHERE i.origem = %s AND i.registro_id = %s AND g.status <> 'cancelado'
               LIMIT 1""",
            (origem, mensalidade_aluno_id),
        )
        g = cur.fetchone()
        if not g:
            return None
        cur.execute(
            """SELECT i.registro_id AS mensalidade_aluno_id, i.aluno_id, i.valor, a.nome AS aluno_nome,
                      ma.status AS ma_status
               FROM cobranca_grupo_item i
               JOIN alunos a ON a.id = i.aluno_id
               JOIN mensalidade_aluno ma ON i.origem = 'mensalidade' AND ma.id = i.registro_id
               WHERE i.grupo_id = %s ORDER BY a.nome""",
            (g["id"],),
        )
        g["itens"] = cur.fetchall() or []
        return g
    except Exception:
        return None
    finally:
        cur.close()
        conn.close()


def grupos_das_mensalidades(mensalidade_ids):
    """{mensalidade_aluno_id: grupo com itens} para uma lista de mensalidades.

    Uma consulta para o grupo e outra para os membros — o painel do aluno lista
    até 200 linhas e não pode fazer duas idas ao banco por linha.
    """
    ids = [int(i) for i in (mensalidade_ids or []) if i]
    if not ids:
        return {}
    ph = ",".join(["%s"] * len(ids))
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            f"""SELECT i.registro_id AS mensalidade_aluno_id, g.*
                FROM cobranca_grupo_item i
                JOIN cobranca_grupo g ON g.id = i.grupo_id
                WHERE i.origem = 'mensalidade' AND i.registro_id IN ({ph})
                  AND g.status <> 'cancelado'""",
            tuple(ids),
        )
        linhas = cur.fetchall() or []
        if not linhas:
            return {}
        grupos = {}
        for l in linhas:
            grupos.setdefault(l["id"], {k: v for k, v in l.items()
                                        if k != "mensalidade_aluno_id"})["itens"] = []
        gph = ",".join(["%s"] * len(grupos))
        cur.execute(
            f"""SELECT i.grupo_id, i.registro_id AS mensalidade_aluno_id, i.aluno_id, i.valor,
                       a.nome AS aluno_nome, ma.status AS ma_status
                FROM cobranca_grupo_item i
                JOIN alunos a ON a.id = i.aluno_id
                JOIN mensalidade_aluno ma ON i.origem = 'mensalidade' AND ma.id = i.registro_id
                WHERE i.grupo_id IN ({gph}) ORDER BY a.nome""",
            tuple(grupos.keys()),
        )
        for item in cur.fetchall() or []:
            grupos[item["grupo_id"]]["itens"].append(item)
        return {l["mensalidade_aluno_id"]: grupos[l["id"]] for l in linhas}
    except Exception:
        return {}
    finally:
        cur.close()
        conn.close()


def mensalidades_do_grupo(grupo_id, apenas_abertas=True):
    """Ids das MENSALIDADES cobertas pelo grupo (não inclui avulsas).

    Mantida como estava: quem chama espera ids de `mensalidade_aluno`. Para
    contar tudo que o grupo cobre, use `itens_do_grupo`.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        sql = """SELECT i.registro_id AS id FROM cobranca_grupo_item i
                 JOIN mensalidade_aluno ma ON i.origem = 'mensalidade' AND ma.id = i.registro_id
                 WHERE i.grupo_id = %s"""
        if apenas_abertas:
            sql += " AND ma.status IN ('pendente','atrasado')"
        cur.execute(sql, (grupo_id,))
        return [r["id"] for r in (cur.fetchall() or [])]
    except Exception:
        return []
    finally:
        cur.close()
        conn.close()


def itens_do_grupo(grupo_id):
    """Tudo que o grupo cobre: (origem, registro_id, aluno_id, valor, nome).

    `mensalidades_do_grupo` só enxerga mensalidade; uma família cobrada por duas
    taxas avulsas voltava lista vazia, e a mensagem de baixa dizia "1 baixada"
    quando eram duas.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT i.origem, i.registro_id, i.aluno_id, i.valor, a.nome
               FROM cobranca_grupo_item i
               LEFT JOIN alunos a ON a.id = i.aluno_id
               WHERE i.grupo_id = %s
               ORDER BY a.nome""", (grupo_id,))
        return cur.fetchall() or []
    except Exception:
        return []
    finally:
        cur.close()
        conn.close()
