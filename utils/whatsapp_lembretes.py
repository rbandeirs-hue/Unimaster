# -*- coding: utf-8 -*-
"""Lembretes de mensalidade via WhatsApp (Baileys).

Usado pelo botão manual (financeiro) e pelo script diário (cron).
Tolerante a falhas: nunca levanta exceção para o chamador.
"""
import logging
from datetime import date
from config import get_db_connection
from utils import whatsapp as wpp

_PRIMEIRO_NOME = lambda s: (str(s).strip().split()[0] if s and str(s).strip() else "")


def _telefone(row):
    return (row.get("responsavel_financeiro_telefone") or row.get("tel_celular")
            or row.get("telefone") or "").strip() or None


def _link_gateway(row):
    """URL crua devolvida pelo gateway (longa)."""
    return (row.get("asaas_boleto_url") or row.get("cora_boleto_url")
            or row.get("inter_boleto_url") or "").strip() or None


def _link(row, academia_id=None):
    """Link de pagamento para a mensagem — curto quando possível.

    A URL do gateway passa de 180 caracteres (a do Cora vem do Google Storage,
    com parâmetros), o que deixa a mensagem feia e desconfiável. Trocamos por
    /p/<token> no domínio da própria academia. Se o encurtador não estiver
    disponível (tabela ausente, PUBLIC_BASE_URL não configurada), cai na URL
    original — melhor um link longo do que nenhum.
    """
    bruto = _link_gateway(row)
    if not bruto:
        return None
    try:
        from utils.links_curtos import encurtar
        curto = encurtar("mensalidade", row.get("id"), academia_id)
        if curto:
            return curto
    except Exception:
        pass
    return bruto


def _pix(row):
    """Copia e cola do PIX, quando o gateway devolveu (Cora, Asaas, EFÍ)."""
    return (row.get("asaas_pix_copia_cola") or row.get("cora_pix_copia_cola")
            or row.get("inter_pix_copia_cola") or "").strip() or None


def _destinatario(row):
    return row.get("responsavel_financeiro_nome") or row.get("nome") or "aluno"


def garantir_cobranca_online(row, academia_id, forcar=False):
    """Gera a cobrança no gateway da academia quando a mensalidade ainda não tem link.

    Com `forcar`, reemite mesmo já havendo link — é o "Atualizar links" do painel,
    para refazer cobranças antigas que ficaram com valor ou endereço errados.

    É o que faz o lembrete automático sair com um link que realmente abre — antes,
    mensalidades nunca cobradas online iam com o `{link}` vazio.

    A cobrança gerada é gravada no próprio registro, então a próxima mensagem
    reaproveita o mesmo link em vez de emitir outra. Tolerante a falha: se não
    houver gateway ativo ou a emissão der erro, devolve o que já existia.
    """
    # Só mensalidade: a emissão grava o link em `mensalidade_aluno` pelo `id` da
    # linha. Com a régua lendo também avulsa, matrícula e cobrança familiar, um
    # registro de outra tabela com o mesmo id sobrescreveria o link da
    # mensalidade alheia — cobrando o aluno errado pelo valor errado.
    if (row.get("origem") or "mensalidade") != "mensalidade":
        return row
    if _link_gateway(row) and not forcar:
        return row
    ma_id = row.get("id")
    aluno_id = row.get("aluno_id")
    if not ma_id or not aluno_id or float(row.get("valor") or 0) <= 0:
        return row

    try:
        # Import tardio: evita ciclo entre utils e o blueprint financeiro.
        from blueprints.financeiro.routes import (
            _gateway_config_academia, _gateway_ativo, _emitir_cobranca_online,
            _dados_pagador, _endereco_aluno,
        )
        cfg = _gateway_config_academia(academia_id)
        if not _gateway_ativo(cfg):
            return row

        conn = get_db_connection(); cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                """SELECT nome, cpf, email, telefone, tel_celular,
                          responsavel_financeiro_nome, responsavel_financeiro_cpf,
                          responsavel_financeiro_telefone,
                          cep, rua, numero, complemento, bairro, cidade, estado
                   FROM alunos WHERE id=%s""",
                (aluno_id,),
            )
            aluno = cur.fetchone()
            if not aluno:
                return row

            pag_nome, pag_cpf, pag_tel = _dados_pagador(aluno)
            if not pag_cpf:
                # Sem CPF nenhum gateway emite — segue sem link, sem quebrar o envio.
                return row

            # Mensalidade atrasada gera segunda via com vencimento de hoje: os
            # gateways recusam data no passado (o Cora devolve 400 em
            # paymentTerms.dueDate). O vencimento original do registro não muda —
            # quem manda no status de atraso continua sendo a data da mensalidade.
            venc = row.get("data_vencimento") or date.today()
            if venc < date.today():
                venc = date.today()

            # Cobra o valor final: além do desconto gravado na linha, o aluno pode
            # ter desconto por vínculo (aluno_desconto), que só aparece no cálculo.
            valor_cobravel = float(row.get("valor") or 0)
            try:
                from blueprints.financeiro.routes import _valor_com_desconto
                _vi, _vd, vf, _nome = _valor_com_desconto(
                    {"valor": row.get("valor"),
                     "valor_original": row.get("valor_original"),
                     "desconto_aplicado": row.get("desconto_aplicado"),
                     "id_desconto": row.get("id_desconto"),
                     "data_vencimento": row.get("data_vencimento")},
                    aluno_id, academia_id,
                )
                if vf and vf > 0:
                    valor_cobravel = float(vf)
            except Exception:
                pass

            r = _emitir_cobranca_online(
                cfg, "PIX", nome=pag_nome, cpf=pag_cpf, email=aluno.get("email"),
                telefone=pag_tel, valor=valor_cobravel, vencimento=venc,
                descricao=f"Mensalidade - {aluno.get('nome')}",
                origem="mensalidade", registro_id=ma_id,
                endereco=_endereco_aluno(aluno),
            )
            cur.execute(
                """UPDATE mensalidade_aluno
                   SET asaas_payment_id=%s, asaas_tipo=%s, asaas_boleto_url=%s,
                       asaas_pix_qrcode=%s, asaas_pix_copia_cola=%s, gateway=%s
                   WHERE id=%s""",
                (r["payment_id"], r["tipo"], r["boleto_url"], r["pix_qrcode"],
                 r["pix_copia_cola"], r["gateway"], ma_id),
            )
            conn.commit()
            row["asaas_boleto_url"] = r["boleto_url"]
            row["asaas_pix_copia_cola"] = r["pix_copia_cola"]
        finally:
            cur.close(); conn.close()
    except Exception as e:
        # Nunca derruba o lembrete por causa do gateway — mas registra, senão a
        # falha some e a mensagem sai sem link sem ninguém saber por quê.
        try:
            from flask import current_app
            current_app.logger.warning(
                f"Lembrete: falha ao gerar cobrança online da mensalidade {ma_id}: {e}")
        except Exception:
            pass
    return row


def _limpar_placeholders_vazios(texto):
    """Remove a linha do link e o rótulo acima dela quando não houve link.

    Sem isso o template padrão manda 'Pague pelo link:' seguido de nada.
    """
    linhas = texto.split("\n")
    saida = []
    for linha in linhas:
        if linha.strip() == "":
            # Rótulo órfão logo antes de uma linha vazia que era o link.
            if saida and saida[-1].rstrip().endswith(":"):
                saida.pop()
        saida.append(linha)
    # Colapsa as quebras triplas que sobraram da remoção.
    txt = "\n".join(saida)
    while "\n\n\n" in txt:
        txt = txt.replace("\n\n\n", "\n\n")
    return txt.strip()


def _reais(v):
    return f"R$ {float(v or 0):.2f}".replace(".", ",")


def _ctx_mensagem(row, academia_nome, academia_id=None, extra=None):
    """Placeholders de uma cobrança. `extra` acrescenta os da consolidada.

    `responsavel` e `competencia` são apelidos de `nome`/`mes`: os modelos
    antigos continuam válidos e os novos podem usar o nome que faz sentido.
    """
    venc = row.get("data_vencimento")
    ctx = {
        "nome": _PRIMEIRO_NOME(_destinatario(row)),
        "responsavel": _destinatario(row) or "",
        "aluno": row.get("nome") or "",
        "valor": _reais(row.get("valor")),
        "vencimento": venc.strftime("%d/%m/%Y") if venc else "",
        "link": _link(row, academia_id) or "",
        "pix": _pix(row) or "",
        "academia": academia_nome or "",
        "mes": venc.strftime("%m/%Y") if venc else "",
        "competencia": venc.strftime("%m/%Y") if venc else "",
        "quantidade_pendencias": "1",
        "valor_total": _reais(row.get("valor")),
        "lista": "",
    }
    if extra:
        ctx.update(extra)
    return ctx


def montar_mensagem(row, academia_nome, academia_id=None, texto_custom=None):
    """Monta a mensagem usando o template configurável da academia.
    Retorna o texto, ou None se o template daquele tipo estiver desativado.

    `texto_custom` é a mensagem da etapa da régua: quando o gestor escreve um
    texto para o D+7, é ele que vale ali; sem isso, segue o modelo de sempre.
    """
    from utils import whatsapp_templates as tpl
    tipo = "lembrete_atraso" if (row.get("data_vencimento")
                                 and row["data_vencimento"] < date.today()) else "lembrete_vencimento"
    if texto_custom:
        texto = texto_custom
    else:
        texto, ativo = tpl.obter(academia_id, tipo)
        if not ativo:
            return None

    # Emite a cobrança agora se ainda não houver link — é o que garante que a
    # mensagem automática saia com um link de pagamento válido.
    if academia_id:
        if (row.get("origem") or "") == "grupo":
            # A cobrança familiar tem emissão própria: um link só, com a soma
            # dos irmãos. Sem isto a mensagem do grupo saía sem forma de pagar.
            if not _link_gateway(row):
                try:
                    from utils.cobranca_familia import gerar_link, carregar_grupo
                    ok, _msg = gerar_link(row["id"])
                    if ok:
                        g = carregar_grupo(row["id"]) or {}
                        row = dict(row,
                                   asaas_boleto_url=g.get("link"),
                                   asaas_pix_copia_cola=g.get("copia_cola"))
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Régua: falha ao emitir a cobrança do grupo %s", row.get("id"))
        else:
            row = garantir_cobranca_online(row, academia_id)

    return _limpar_placeholders_vazios(tpl.render(texto, _ctx_mensagem(row, academia_nome, academia_id)))


def montar_mensagem_consolidada(rows, academia_nome, academia_id=None, texto_custom=None):
    """Uma mensagem para várias mensalidades vencidas do mesmo responsável.

    O link é o da mais antiga (é por ela que a negociação começa); a lista e o
    total vão nos placeholders novos.
    """
    from utils import whatsapp_templates as tpl
    if texto_custom:
        texto = texto_custom
    else:
        texto, ativo = tpl.obter(academia_id, "cobranca_consolidada")
        if not ativo:
            return None

    ordenadas = sorted(rows, key=lambda r: r.get("data_vencimento") or date.today())
    principal = ordenadas[0]
    if academia_id:
        principal = garantir_cobranca_online(principal, academia_id)
    total = sum(float(r.get("valor") or 0) for r in ordenadas)
    linhas = []
    for r in ordenadas:
        v = r.get("data_vencimento")
        etiqueta = v.strftime("%m/%Y") if v else "—"
        quem = _PRIMEIRO_NOME(r.get("nome"))
        linhas.append(f"• {etiqueta}{' (' + quem + ')' if quem else ''} — {_reais(r.get('valor'))}")
    # Com irmãos no mesmo grupo, citar só o primeiro aluno soa como cobrança
    # errada ("mas o Pedro eu paguei"). Nomeia todos.
    nomes_alunos = []
    for r in ordenadas:
        n = _PRIMEIRO_NOME(r.get("nome"))
        if n and n not in nomes_alunos:
            nomes_alunos.append(n)
    extra = {
        "aluno": " e ".join(nomes_alunos) if len(nomes_alunos) > 1 else (ordenadas[0].get("nome") or ""),
        "quantidade_pendencias": str(len(ordenadas)),
        "valor_total": _reais(total),
        "lista": "\n".join(linhas),
    }
    return _limpar_placeholders_vazios(
        tpl.render(texto, _ctx_mensagem(principal, academia_nome, academia_id, extra)))


def _nome_academia(cur, academia_id):
    cur.execute("SELECT nome, whatsapp_lembrete_mensalidade FROM academias WHERE id=%s", (academia_id,))
    r = cur.fetchone()
    return (r or {})


def _fora_de_grupo_sql(cur, origem="mensalidade", alias="ma"):
    """Fragmento que tira do lembrete o que já está numa cobrança familiar.

    A cobrança de quem paga junto com os irmãos sai uma vez só, no link do grupo;
    mandar o lembrete individual também faria a mãe receber duas cobranças do que
    ela paga numa. Vale para as duas origens que o grupo aceita — mensalidade e
    avulsa —, por isso a origem e o alias são parâmetros. Devolve "" onde a
    migração ainda não rodou.
    """
    try:
        cur.execute("SHOW TABLES LIKE 'cobranca_grupo_item'")
        if not cur.fetchone():
            return ""
        cur.execute("SHOW COLUMNS FROM cobranca_grupo_item LIKE 'registro_id'")
        if not cur.fetchone():
            # Esquema antigo, só com mensalidade_aluno_id.
            if origem != "mensalidade":
                return ""
            return ("""
          AND NOT EXISTS (SELECT 1 FROM cobranca_grupo_item gi
                          JOIN cobranca_grupo g ON g.id = gi.grupo_id
                          WHERE gi.mensalidade_aluno_id = %s.id
                            AND g.status IN ('pendente','atrasado'))""" % alias)
    except Exception:
        return ""
    return ("""
          AND NOT EXISTS (SELECT 1 FROM cobranca_grupo_item gi
                          JOIN cobranca_grupo g ON g.id = gi.grupo_id
                          WHERE gi.origem = '%s' AND gi.registro_id = %s.id
                            AND g.status IN ('pendente','atrasado'))""" % (origem, alias))


def buscar_pendentes(cur, academia_id, dias_antes=3, somente_atrasadas=False):
    """Mensalidades pendentes/atrasadas com vencimento até hoje+dias_antes.

    Com `somente_atrasadas`, traz só o que já venceu — é o que alimenta o botão
    "Notificar atrasados" do painel.
    """
    _sem_grupo = _fora_de_grupo_sql(cur)
    if somente_atrasadas:
        cur.execute(
            f"""
            SELECT ma.id, ma.aluno_id, ma.data_vencimento, ma.valor, ma.status,
                   ma.valor_original, ma.desconto_aplicado, ma.id_desconto,
                   ma.asaas_boleto_url, ma.cora_boleto_url, ma.inter_boleto_url,
                   ma.asaas_pix_copia_cola, ma.cora_pix_copia_cola, ma.inter_pix_copia_cola,
                   a.nome, a.telefone, a.tel_celular,
                   a.responsavel_financeiro_nome, a.responsavel_financeiro_telefone
            FROM mensalidade_aluno ma
            JOIN alunos a ON a.id = ma.aluno_id
            WHERE a.id_academia = %s
              AND ma.status IN ('pendente','atrasado')
              AND ma.data_vencimento IS NOT NULL
              AND ma.data_vencimento < CURDATE()
              AND ma.valor > 0{_sem_grupo}
            ORDER BY ma.data_vencimento
            """,
            (academia_id,),
        )
        return cur.fetchall()
    cur.execute(
        f"""
        SELECT ma.id, ma.aluno_id, ma.data_vencimento, ma.valor, ma.status,
               ma.valor_original, ma.desconto_aplicado, ma.id_desconto,
               ma.asaas_boleto_url, ma.cora_boleto_url, ma.inter_boleto_url,
               ma.asaas_pix_copia_cola, ma.cora_pix_copia_cola, ma.inter_pix_copia_cola,
               a.nome, a.telefone, a.tel_celular,
               a.responsavel_financeiro_nome, a.responsavel_financeiro_telefone
        FROM mensalidade_aluno ma
        JOIN alunos a ON a.id = ma.aluno_id
        WHERE a.id_academia = %s
          AND ma.status IN ('pendente','atrasado')
          AND ma.data_vencimento IS NOT NULL
          AND ma.data_vencimento <= DATE_ADD(CURDATE(), INTERVAL %s DAY)
          AND ma.valor > 0{_sem_grupo}
        ORDER BY ma.data_vencimento
        """,
        (academia_id, dias_antes),
    )
    return cur.fetchall()


def enviar_um(academia_id, ma_id):
    """Envia o lembrete de uma mensalidade específica. Retorna (ok, mensagem)."""
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        acad = _nome_academia(cur, academia_id)
        cur.execute(
            """SELECT ma.id, ma.aluno_id, ma.data_vencimento, ma.valor, ma.status,
                      ma.asaas_boleto_url, ma.cora_boleto_url, ma.inter_boleto_url,
                      ma.asaas_pix_copia_cola, ma.cora_pix_copia_cola, ma.inter_pix_copia_cola,
                      a.nome, a.telefone, a.tel_celular,
                      a.responsavel_financeiro_nome, a.responsavel_financeiro_telefone
               FROM mensalidade_aluno ma JOIN alunos a ON a.id = ma.aluno_id
               WHERE ma.id=%s AND a.id_academia=%s""",
            (ma_id, academia_id),
        )
        row = cur.fetchone()
    finally:
        cur.close(); conn.close()
    if not row:
        return False, "Mensalidade não encontrada."
    if float(row.get("valor") or 0) <= 0:
        return False, "Mensalidade sem valor a cobrar (isenta ou 100% de desconto)."
    try:
        from utils.cobranca_familia import grupo_da_mensalidade
        if grupo_da_mensalidade(row["id"]):
            return False, ("Esta mensalidade está numa cobrança familiar — envie o link "
                           "do grupo em Financeiro › Famílias, senão a família recebe "
                           "duas cobranças do mesmo valor.")
    except ImportError:
        pass
    tel = _telefone(row)
    if not tel:
        return False, "Aluno sem telefone cadastrado."
    texto = montar_mensagem(row, acad.get("nome") or "", academia_id)
    if texto is None:
        return False, "O modelo de mensagem deste tipo está desativado (Mensagens do WhatsApp)."
    ok, info = wpp.enviar(academia_id, tel, texto)
    if ok:
        return True, "Lembrete enviado."
    return False, (info.get("erro") if isinstance(info, dict) else "Falha no envio") or "Falha no envio"


def enviar_evento(academia_id, tipo, telefone, ctx):
    """Envia uma mensagem de evento (matricula, boas_vindas, etc.) usando o template
    configurável da academia. Tolerante a falha. Retorna True se enfileirou."""
    try:
        if not academia_id or not telefone:
            return False
        from utils import whatsapp_templates as tpl
        texto, ativo = tpl.obter(academia_id, tipo)
        if not ativo:
            return False
        ok, _ = wpp.enviar(academia_id, telefone, tpl.render(texto, ctx))
        return ok
    except Exception:
        return False


def _valor_liquido_pago(row, academia_id, tipo="mensalidade_aluno"):
    """Valor que o aluno realmente pagou, para a mensagem de confirmação.

    Prioriza `valor_pago` (o que foi efetivamente recebido, já com desconto e
    eventuais juros). Sem ele, calcula o valor final com o desconto do aluno —
    informar o valor cheio numa confirmação passa a impressão de cobrança errada.
    """
    pago = float(row.get("valor_pago") or 0)
    if pago > 0:
        return pago
    bruto = float(row.get("valor") or 0)
    if tipo == "cobranca_avulsa":
        return bruto
    try:
        from blueprints.financeiro.routes import _valor_com_desconto
        _vi, _vd, vf, _n = _valor_com_desconto(row, row.get("aluno_id"), academia_id)
        if vf is not None and float(vf) > 0:
            return float(vf)
    except Exception:
        pass
    return bruto


def enviar_confirmacao_pagamento(registro_id, tipo="mensalidade_aluno"):
    """Envia a confirmação de pagamento (mensalidade OU cobrança avulsa), se o modelo
    estiver ativo e o WhatsApp conectado. Tolerante a falha — nunca levanta exceção."""
    try:
        from utils import whatsapp_templates as tpl
        conn = get_db_connection(); cur = conn.cursor(dictionary=True)
        if tipo == "cobranca_avulsa":
            cur.execute(
                """SELECT ca.id, ca.valor, ca.valor_pago, ca.data_vencimento,
                          ca.aluno_id, a.id_academia,
                          a.nome, a.telefone, a.tel_celular,
                          a.responsavel_financeiro_nome, a.responsavel_financeiro_telefone,
                          ac.nome AS academia_nome
                   FROM cobranca_avulsa ca
                   JOIN alunos a ON a.id = ca.aluno_id
                   JOIN academias ac ON ac.id = a.id_academia
                   WHERE ca.id = %s""",
                (registro_id,),
            )
        else:
            cur.execute(
                """SELECT ma.id, ma.valor, ma.valor_pago, ma.valor_original,
                          ma.desconto_aplicado, ma.id_desconto, ma.data_vencimento,
                          ma.aluno_id, a.id_academia,
                          a.nome, a.telefone, a.tel_celular,
                          a.responsavel_financeiro_nome, a.responsavel_financeiro_telefone,
                          ac.nome AS academia_nome
                   FROM mensalidade_aluno ma
                   JOIN alunos a ON a.id = ma.aluno_id
                   JOIN academias ac ON ac.id = a.id_academia
                   WHERE ma.id = %s""",
                (registro_id,),
            )
        row = cur.fetchone()
        cur.close(); conn.close()
        if not row:
            return False
        academia_id = row["id_academia"]
        texto, ativo = tpl.obter(academia_id, "confirmacao_pagamento")
        if not ativo:
            return False
        tel = _telefone(row)
        if not tel:
            return False
        venc = row.get("data_vencimento")
        valor = _valor_liquido_pago(row, academia_id, tipo)
        ctx = {
            "nome": _PRIMEIRO_NOME(row.get("responsavel_financeiro_nome") or row.get("nome")),
            "aluno": row.get("nome") or "",
            "valor": f"R$ {valor:.2f}".replace(".", ","),
            "vencimento": venc.strftime("%d/%m/%Y") if venc else "",
            "link": "",
            "academia": row.get("academia_nome") or "",
            "mes": venc.strftime("%m/%Y") if venc else "",
        }
        ok, _ = wpp.enviar(academia_id, tel, tpl.render(texto, ctx))
        try:
            from utils import whatsapp_log as wlog
            wlog.registrar(academia_id, "confirmacao_pagamento", "entregue" if ok else "falha",
                           aluno_id=row.get("aluno_id"), telefone=tel)
        except Exception:
            pass
        return ok
    except Exception:
        return False


def enviar_confirmacao_matricula(precad_id, valor=None):
    """Confirma no WhatsApp o pagamento da matrícula de um pré-cadastro.

    Chamada pela baixa da matrícula — vale tanto para o webhook do gateway
    quanto para a baixa manual da secretaria. Tolerante a falha: o pagamento já
    está registrado, e não pode ser desfeito porque o WhatsApp não respondeu.
    """
    try:
        from utils import whatsapp_templates as tpl
        conn = get_db_connection(); cur = conn.cursor(dictionary=True)
        cur.execute(
            """SELECT p.id, p.nome, p.telefone, p.tel_celular, p.matricula_valor,
                      p.responsavel_financeiro_nome, p.academia_id,
                      ac.nome AS academia_nome
               FROM pre_cadastro p
               LEFT JOIN academias ac ON ac.id = p.academia_id
               WHERE p.id = %s""",
            (precad_id,),
        )
        row = cur.fetchone()
        cur.close(); conn.close()
        if not row:
            return False
        academia_id = row.get("academia_id")
        if not academia_id:
            return False
        texto, ativo = tpl.obter(academia_id, "confirmacao_matricula")
        if not ativo:
            return False
        # O pré-cadastro não tem telefone do responsável financeiro em coluna
        # própria; o celular do cadastro é o contato que a secretaria usa.
        tel = (row.get("tel_celular") or row.get("telefone") or "").strip()
        if not tel:
            return False
        val = valor if valor is not None else row.get("matricula_valor")
        ctx = {
            "nome": _PRIMEIRO_NOME(row.get("responsavel_financeiro_nome") or row.get("nome")),
            "aluno": row.get("nome") or "",
            "valor": (f"R$ {float(val):.2f}".replace(".", ",")) if val else "",
            "vencimento": "",
            "link": "",
            "academia": row.get("academia_nome") or "",
            "mes": "",
        }
        ok, _ = wpp.enviar(academia_id, tel, tpl.render(texto, ctx))
        try:
            from utils import whatsapp_log as wlog
            wlog.registrar(academia_id, "confirmacao_matricula",
                           "entregue" if ok else "falha", telefone=tel)
        except Exception:
            pass
        return ok
    except Exception:
        return False


def _ja_enviado(cur, academia_id, tipo, referencia_id, dia):
    """True se este envio já foi registrado hoje — evita duplicar em retentativa."""
    try:
        cur.execute(
            """SELECT 1 FROM whatsapp_envios
               WHERE id_academia=%s AND tipo=%s AND referencia_id=%s AND data_ref=%s""",
            (academia_id, tipo, referencia_id, dia),
        )
        return cur.fetchone() is not None
    except Exception:
        # Sem a tabela (migration não rodada) seguimos enviando, só sem a trava.
        return False


def _marcar_enviado(conn, cur, academia_id, tipo, referencia_id, dia):
    try:
        cur.execute(
            """INSERT INTO whatsapp_envios (id_academia, tipo, referencia_id, data_ref)
               VALUES (%s, %s, %s, %s)""",
            (academia_id, tipo, referencia_id, dia),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def enviar_aniversariantes(academia_id, somente_ativadas=True, dia=None):
    """Parabeniza no WhatsApp os aniversariantes do dia.

    Roda junto do envio diário de lembretes. A trava em `whatsapp_envios`
    garante um único parabéns por aluno por dia, mesmo se o job rodar de novo.
    Retorna {enviados, falhas, sem_telefone, total}.
    """
    dia = dia or date.today()
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    resumo = {"enviados": 0, "falhas": 0, "sem_telefone": 0, "total": 0, "repetidos": 0}
    try:
        cur.execute(
            """SELECT nome, COALESCE(whatsapp_aniversario, 0) AS ligado
               FROM academias WHERE id=%s""",
            (academia_id,),
        )
        acad = cur.fetchone() or {}
        if somente_ativadas and not acad.get("ligado"):
            resumo["motivo"] = "automacao_desligada"
            return resumo

        from utils import whatsapp_templates as tpl
        texto, ativo = tpl.obter(academia_id, "aniversario")
        if not ativo:
            resumo["motivo"] = "modelo_desativado"
            return resumo

        cur.execute(
            """SELECT id, nome, data_nascimento, telefone, tel_celular,
                      responsavel_financeiro_nome, responsavel_financeiro_telefone
               FROM alunos
               WHERE id_academia=%s AND COALESCE(ativo,1)=1
                 AND data_nascimento IS NOT NULL
                 AND MONTH(data_nascimento)=%s AND DAY(data_nascimento)=%s""",
            (academia_id, dia.month, dia.day),
        )
        alunos = cur.fetchall()
        resumo["total"] = len(alunos)
        nome_acad = acad.get("nome") or ""

        for al in alunos:
            if _ja_enviado(cur, academia_id, "aniversario", al["id"], dia):
                resumo["repetidos"] += 1
                continue
            tel = _telefone(al)
            if not tel:
                resumo["sem_telefone"] += 1
                continue
            ctx = {
                "nome": _PRIMEIRO_NOME(_destinatario(al)),
                "aluno": al.get("nome") or "",
                "academia": nome_acad,
                "valor": "", "vencimento": "", "link": "", "pix": "",
                "mes": dia.strftime("%m/%Y"),
            }
            ok, _ = wpp.enviar(academia_id, tel, _limpar_placeholders_vazios(tpl.render(texto, ctx)))
            if ok:
                resumo["enviados"] += 1
                _marcar_enviado(conn, cur, academia_id, "aniversario", al["id"], dia)
            else:
                resumo["falhas"] += 1
            try:
                from utils import whatsapp_log as wlog
                wlog.registrar(academia_id, "aniversario", "entregue" if ok else "falha",
                               aluno_id=al.get("id"), telefone=tel)
            except Exception:
                pass
    except Exception:
        pass
    finally:
        cur.close(); conn.close()
    return resumo


def mensagem_aniversario(academia_id, aluno_row=None):
    """Texto do parabéns como ele sairá — usado na prévia da tela e no envio.

    Sem `aluno_row` devolve o modelo com os placeholders já resolvidos pelos
    dados da academia, que é o que a tela mostra antes de escolher alguém.
    """
    from utils import whatsapp_templates as tpl
    texto, ativo = tpl.obter(academia_id, "aniversario")
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT nome FROM academias WHERE id=%s", (academia_id,))
        nome_acad = (cur.fetchone() or {}).get("nome") or ""
    finally:
        cur.close(); conn.close()
    row = aluno_row or {}
    ctx = {
        "nome": _PRIMEIRO_NOME(_destinatario(row)) or "{nome}",
        "aluno": row.get("nome") or "{aluno}",
        "academia": nome_acad,
        "valor": "", "vencimento": "", "link": "", "pix": "",
        "mes": date.today().strftime("%m/%Y"),
    }
    return _limpar_placeholders_vazios(tpl.render(texto, ctx)), ativo


def enviar_aniversario_aluno(aluno_id, dia=None, forcar=False):
    """Parabeniza um aluno pelo WhatsApp — o envio manual feito pela secretaria.

    Diferente de `enviar_aniversariantes` (cron), não exige a automação ligada:
    quem clicou no botão já decidiu enviar. A trava de duplicidade do dia
    continua valendo, e `forcar` é o "enviar mesmo assim" de quem já passou.

    Retorna {ok, motivo, telefone} — nunca levanta exceção.
    """
    dia = dia or date.today()
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT id, id_academia, nome, data_nascimento, telefone, tel_celular,
                      responsavel_financeiro_nome, responsavel_financeiro_telefone
               FROM alunos WHERE id=%s AND COALESCE(ativo,1)=1""",
            (aluno_id,),
        )
        al = cur.fetchone()
        if not al:
            return {"ok": False, "motivo": "aluno_nao_encontrado"}
        academia_id = al.get("id_academia")
        if not academia_id:
            return {"ok": False, "motivo": "sem_academia"}

        if not forcar and _ja_enviado(cur, academia_id, "aniversario", al["id"], dia):
            return {"ok": False, "motivo": "ja_enviado_hoje"}

        tel = _telefone(al)
        if not tel:
            return {"ok": False, "motivo": "sem_telefone"}

        texto, ativo = mensagem_aniversario(academia_id, al)
        if not ativo:
            return {"ok": False, "motivo": "modelo_desativado"}

        ok, detalhe = wpp.enviar(academia_id, tel, texto)
        if ok:
            _marcar_enviado(conn, cur, academia_id, "aniversario", al["id"], dia)
            return {"ok": True, "telefone": tel}
        return {"ok": False, "motivo": "falha_envio", "detalhe": str(detalhe or "")}
    except Exception as exc:
        return {"ok": False, "motivo": "erro", "detalhe": str(exc)}
    finally:
        cur.close(); conn.close()


def enviar_boas_vindas_aluno(aluno_id):
    """Boas-vindas ao aluno recém-cadastrado pelo sistema.

    O fluxo público de pré-cadastro já fazia isso; quem cadastra por dentro do
    sistema não disparava nada. Tolerante a falha — nunca atrapalha o cadastro.
    """
    try:
        conn = get_db_connection(); cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                """SELECT a.id, a.nome, a.telefone, a.tel_celular, a.id_academia,
                          a.responsavel_financeiro_nome, a.responsavel_financeiro_telefone,
                          ac.nome AS academia_nome
                   FROM alunos a JOIN academias ac ON ac.id = a.id_academia
                   WHERE a.id = %s""",
                (aluno_id,),
            )
            al = cur.fetchone()
        finally:
            cur.close(); conn.close()
        if not al or not al.get("id_academia"):
            return False
        tel = _telefone(al)
        if not tel:
            return False
        return enviar_evento(al["id_academia"], "boas_vindas", tel, {
            "nome": _PRIMEIRO_NOME(_destinatario(al)),
            "aluno": al.get("nome") or "",
            "academia": al.get("academia_nome") or "",
            "valor": "", "vencimento": "", "link": "", "pix": "", "mes": "",
        })
    except Exception:
        return False


def enviar_lote(academia_id, dias_antes=3, somente_ativadas=True, somente_atrasadas=False):
    """Envia lembretes para todas as mensalidades pendentes/atrasadas da academia.
    Retorna resumo {enviados, falhas, sem_telefone, total}."""
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    resumo = {"enviados": 0, "falhas": 0, "sem_telefone": 0, "total": 0}
    try:
        from utils import whatsapp_log as wlog
    except Exception:
        wlog = None
    import uuid
    lote_id = "lembrete-" + uuid.uuid4().hex[:12]
    tipo_log = "lembrete_atraso" if somente_atrasadas else "lembrete_vencimento"
    try:
        acad = _nome_academia(cur, academia_id)
        if somente_ativadas and not acad.get("whatsapp_lembrete_mensalidade"):
            resumo["motivo"] = "automacao_desligada"
            return resumo
        rows = buscar_pendentes(cur, academia_id, dias_antes, somente_atrasadas)
        resumo["total"] = len(rows)
        nome_acad = acad.get("nome") or ""
        for row in rows:
            tel = _telefone(row)
            if not tel:
                resumo["sem_telefone"] += 1
                if wlog:
                    wlog.registrar(academia_id, tipo_log, "sem_numero", aluno_id=row.get("aluno_id"), lote_id=lote_id)
                continue
            texto = montar_mensagem(row, nome_acad, academia_id)
            if texto is None:
                resumo["desativado"] = resumo.get("desativado", 0) + 1
                continue
            ok, _ = wpp.enviar(academia_id, tel, texto)
            resumo["enviados" if ok else "falhas"] += 1
            if wlog:
                wlog.registrar(academia_id, tipo_log, "entregue" if ok else "falha",
                               aluno_id=row.get("aluno_id"), telefone=tel, lote_id=lote_id)
    finally:
        cur.close(); conn.close()
    return resumo


# =====================================================================
# Régua de cobrança (job diário)
# =====================================================================
# O job roda todo dia; a régua decide se hoje é dia de falar. Antes, todo
# vencido recebia mensagem em toda execução — o cliente que atrasou uma semana
# levava sete cobranças. Ver `utils/regua_cobranca.py`.

def _colunas_suspensao(cur):
    """Trecho do SELECT com as colunas de suspensão, ou constantes quando a
    migração ainda não rodou — assim o job funciona antes e depois dela."""
    try:
        cur.execute("SHOW COLUMNS FROM alunos LIKE 'cobranca_suspensa'")
        if cur.fetchone():
            return (", a.cobranca_suspensa, a.cobranca_suspensa_ate, "
                    "a.cobranca_suspensa_motivo")
    except Exception:
        pass
    return (", 0 AS cobranca_suspensa, NULL AS cobranca_suspensa_ate, "
            "NULL AS cobranca_suspensa_motivo")


def buscar_em_aberto(cur, academia_id):
    """Mensalidades que ainda podem ser cobradas, sem recorte de data.

    Diferente de `buscar_pendentes` (usada pelos botões manuais), aqui não há
    janela: a régua é que escolhe o dia. Ficam de fora as que estão em cobrança
    familiar (o grupo cobra por elas) e as que têm pagamento em conferência —
    cobrar quem acabou de enviar o comprovante é o pior tipo de mensagem.
    """
    _sem_grupo = _fora_de_grupo_sql(cur)
    _susp = _colunas_suspensao(cur)
    cur.execute(
        f"""
        SELECT 'mensalidade' AS origem,
               ma.id, ma.aluno_id, ma.data_vencimento, ma.valor, ma.status,
               ma.status_pagamento, ma.valor_original, ma.desconto_aplicado, ma.id_desconto,
               ma.asaas_boleto_url, ma.cora_boleto_url, ma.inter_boleto_url,
               ma.asaas_pix_copia_cola, ma.cora_pix_copia_cola, ma.inter_pix_copia_cola,
               a.nome, a.telefone, a.tel_celular,
               a.responsavel_financeiro_nome, a.responsavel_financeiro_telefone{_susp}
        FROM mensalidade_aluno ma
        JOIN alunos a ON a.id = ma.aluno_id
        WHERE a.id_academia = %s
          AND ma.status IN ('pendente','atrasado')
          AND COALESCE(ma.status_pagamento, '') <> 'pendente_aprovacao'
          AND ma.data_vencimento IS NOT NULL
          AND ma.valor > 0{_sem_grupo}
        ORDER BY ma.data_vencimento
        """,
        (academia_id,),
    )
    linhas = cur.fetchall() or []

    # Cobrança avulsa: qualquer valor lançado para o aluno (taxa, uniforme,
    # exame de faixa) segue a MESMA régua da mensalidade. Antes só a mensalidade
    # era cobrada e o resto ficava sem aviso nenhum.
    _sem_grupo_av = _fora_de_grupo_sql(cur, "avulsa", "ca")
    try:
        cur.execute(
            f"""
            SELECT 'avulsa' AS origem,
                   ca.id, ca.aluno_id, ca.data_vencimento, ca.valor, ca.status,
                   NULL AS status_pagamento, NULL AS valor_original,
                   0 AS desconto_aplicado, NULL AS id_desconto,
                   ca.asaas_boleto_url, NULL AS cora_boleto_url, NULL AS inter_boleto_url,
                   ca.asaas_pix_copia_cola, NULL AS cora_pix_copia_cola,
                   NULL AS inter_pix_copia_cola,
                   a.nome, a.telefone, a.tel_celular,
                   a.responsavel_financeiro_nome, a.responsavel_financeiro_telefone{_susp}
            FROM cobranca_avulsa ca
            JOIN alunos a ON a.id = ca.aluno_id
            WHERE ca.id_academia = %s
              AND ca.status IN ('pendente','atrasado')
              AND ca.data_vencimento IS NOT NULL
              AND ca.valor > 0{_sem_grupo_av}
            ORDER BY ca.data_vencimento
            """,
            (academia_id,),
        )
        linhas += cur.fetchall() or []
    except Exception:
        logging.getLogger(__name__).exception("Régua: falha ao ler cobranças avulsas")

    # Matrícula em aberto: vive em `pre_cadastro`, ainda sem aluno criado. Não
    # tem `aluno_id`, então entra com id negativo — o suficiente para agrupar
    # por destinatário sem colidir com aluno de verdade.
    try:
        cur.execute(
            """
            SELECT 'matricula' AS origem,
                   p.id, -p.id AS aluno_id, p.matricula_vencimento AS data_vencimento,
                   p.matricula_valor AS valor, COALESCE(p.matricula_status,'pendente') AS status,
                   NULL AS status_pagamento, p.matricula_valor_original AS valor_original,
                   COALESCE(p.matricula_desconto,0) AS desconto_aplicado, NULL AS id_desconto,
                   p.matricula_link AS asaas_boleto_url, NULL AS cora_boleto_url,
                   NULL AS inter_boleto_url,
                   p.matricula_copia_cola AS asaas_pix_copia_cola, NULL AS cora_pix_copia_cola,
                   NULL AS inter_pix_copia_cola,
                   p.nome, p.telefone, p.tel_celular,
                   p.responsavel_financeiro_nome,
                   -- `pre_cadastro` não tem telefone próprio do responsável:
                   -- o contato informado na inscrição já é o de quem paga.
                   NULL AS responsavel_financeiro_telefone,
                   0 AS cobranca_suspensa, NULL AS cobranca_suspensa_ate,
                   NULL AS cobranca_suspensa_motivo
            FROM pre_cadastro p
            WHERE p.academia_id = %s
              AND COALESCE(p.matricula_status,'') NOT IN ('pago','cancelado')
              AND p.matricula_valor > 0
              AND p.matricula_vencimento IS NOT NULL
            ORDER BY p.matricula_vencimento
            """,
            (academia_id,),
        )
        linhas += cur.fetchall() or []
    except Exception:
        logging.getLogger(__name__).exception("Régua: falha ao ler matrículas em aberto")

    # Cobrança familiar: as mensalidades dos irmãos saem da régua individual
    # (o `_fora_de_grupo_sql` acima as remove) e voltam aqui como UMA linha, com
    # a soma e os nomes de quem ela cobre. Sem isto a família ficava em silêncio:
    # a mensalidade some do lembrete individual e nada ocupava o lugar dela.
    try:
        cur.execute(
            """
            SELECT 'grupo' AS origem,
                   g.id, MIN(i.aluno_id) AS aluno_id, g.data_vencimento,
                   g.valor_total AS valor, g.status,
                   NULL AS status_pagamento, NULL AS valor_original,
                   0 AS desconto_aplicado, NULL AS id_desconto,
                   g.link AS asaas_boleto_url, NULL AS cora_boleto_url,
                   NULL AS inter_boleto_url,
                   g.copia_cola AS asaas_pix_copia_cola, NULL AS cora_pix_copia_cola,
                   NULL AS inter_pix_copia_cola,
                   GROUP_CONCAT(a.nome ORDER BY a.nome SEPARATOR ', ') AS nome,
                   f.responsavel_telefone AS telefone, NULL AS tel_celular,
                   f.responsavel_nome AS responsavel_financeiro_nome,
                   f.responsavel_telefone AS responsavel_financeiro_telefone,
                   0 AS cobranca_suspensa, NULL AS cobranca_suspensa_ate,
                   NULL AS cobranca_suspensa_motivo
            FROM cobranca_grupo g
            JOIN familia_cobranca f ON f.id = g.familia_id
            JOIN cobranca_grupo_item i ON i.grupo_id = g.id
            JOIN alunos a ON a.id = i.aluno_id
            WHERE g.id_academia = %s
              AND g.status IN ('pendente','atrasado')
              AND g.data_vencimento IS NOT NULL
              AND g.valor_total > 0
            GROUP BY g.id, g.data_vencimento, g.valor_total, g.status, g.link,
                     g.copia_cola, f.responsavel_telefone, f.responsavel_nome
            ORDER BY g.data_vencimento
            """,
            (academia_id,),
        )
        linhas += cur.fetchall() or []
    except Exception:
        logging.getLogger(__name__).exception("Régua: falha ao ler cobranças familiares")

    return linhas


def _ainda_cobravel(cur, registro_id, origem="mensalidade"):
    """Reconsulta o status agora, imediatamente antes de enviar.

    Entre montar a lista e disparar a mensagem o pagamento pode ter entrado
    (baixa na secretaria, webhook do gateway, comprovante enviado). Confiar na
    consulta do começo do lote é o que faz o sistema cobrar quem já pagou.

    Vale para as três origens da régua — mensalidade, cobrança avulsa e
    matrícula —, cada uma com o seu jeito de dizer "já foi paga".
    """
    try:
        if origem == "grupo":
            cur.execute(
                "SELECT status, NULL AS status_pagamento, valor_total AS valor "
                "FROM cobranca_grupo WHERE id = %s", (registro_id,))
        elif origem == "avulsa":
            cur.execute(
                "SELECT status, NULL AS status_pagamento, valor "
                "FROM cobranca_avulsa WHERE id = %s", (registro_id,))
        elif origem == "matricula":
            cur.execute(
                "SELECT COALESCE(matricula_status,'pendente') AS status, "
                "       NULL AS status_pagamento, matricula_valor AS valor "
                "FROM pre_cadastro WHERE id = %s", (registro_id,))
        else:
            cur.execute(
                "SELECT status, status_pagamento, valor "
                "FROM mensalidade_aluno WHERE id = %s", (registro_id,))
        r = cur.fetchone()
    except Exception:
        return False
    if not r:
        return False
    if (r.get("status") or "") not in ("pendente", "atrasado"):
        return False
    if (r.get("status_pagamento") or "") in ("pago", "pendente_aprovacao"):
        return False
    return float(r.get("valor") or 0) > 0


def _chave_destinatario(row):
    """Agrupa por quem RECEBE, não por aluno.

    A mãe de dois alunos com o mesmo telefone é um destinatário só — senão ela
    recebe duas cobranças seguidas no mesmo minuto. Sem telefone, cada aluno
    fica no seu grupo (o envio vai falhar de qualquer forma, mas a contagem
    fica correta).
    """
    tel = _telefone(row)
    if tel:
        return "tel:" + "".join(ch for ch in tel if ch.isdigit())
    return "aluno:%s" % row.get("aluno_id")


def processar_regua(academia_id, hoje=None, somente_ativadas=True):
    """Aplica a régua do dia na academia. Retorna um resumo do que aconteceu.

    Percorre os destinatários (não as mensalidades) e, para cada um, decide
    entre régua individual, cobrança consolidada e tratativa administrativa a
    partir de quantas mensalidades vencidas ele tem AGORA — é isso que faz o
    pagamento de uma das duas devolver o responsável para a régua simples, sem
    guardar "nível de cobrança" nenhum.
    """
    from utils import regua_cobranca as regua
    try:
        from utils import whatsapp_log as wlog
    except Exception:
        wlog = None
    import uuid

    hoje = hoje or date.today()
    lote_id = "regua-" + uuid.uuid4().hex[:12]
    resumo = {"total": 0, "enviados": 0, "falhas": 0, "sem_telefone": 0,
              "consolidados": 0, "tratativa": 0, "suspensos": 0,
              "repetidos": 0, "sem_etapa": 0, "desativado": 0}

    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        acad = _nome_academia(cur, academia_id)
        if somente_ativadas and not acad.get("whatsapp_lembrete_mensalidade"):
            resumo["motivo"] = "automacao_desligada"
            return resumo
        nome_acad = acad.get("nome") or ""
        cfg = regua.carregar(academia_id, cur)

        linhas = buscar_em_aberto(cur, academia_id)
        resumo["total"] = len(linhas)

        grupos = {}
        for row in linhas:
            grupos.setdefault(_chave_destinatario(row), []).append(row)

        for chave, rows in grupos.items():
            # Suspensão é por aluno: o irmão suspenso sai da conta, o outro
            # continua sendo cobrado normalmente.
            rows = [r for r in rows if not regua.suspenso(r, hoje)]
            if not rows:
                resumo["suspensos"] += 1
                continue

            vencidas = [r for r in rows if regua.dias_ate(r["data_vencimento"], hoje) > 0]

            # Acumulou demais: para de insistir no automático e fica para a
            # secretaria tratar (ligar, negociar, suspender).
            if cfg["tratativa_apos"] and len(vencidas) >= cfg["tratativa_apos"]:
                resumo["tratativa"] += 1
                continue

            if len(vencidas) >= cfg["consolidar_apos"]:
                enviou = _regua_consolidada(conn, cur, academia_id, nome_acad, cfg,
                                            vencidas, hoje, resumo, wlog, lote_id)
            else:
                enviou = _regua_individual(conn, cur, academia_id, nome_acad, cfg,
                                           rows, hoje, resumo, wlog, lote_id)
            del enviou
    finally:
        cur.close(); conn.close()
    return resumo


def _regua_individual(conn, cur, academia_id, nome_acad, cfg, rows, hoje, resumo, wlog, lote_id):
    """Cobra UMA mensalidade do destinatário hoje, se alguma bater etapa.

    Com uma parcela vencida e outra a vencer, as duas poderiam cair no mesmo
    dia da régua; fica a mais atrasada — receber duas cobranças seguidas do
    mesmo remetente é o que o ajuste veio evitar.
    """
    from utils import regua_cobranca as regua
    alvo, etapa, dias_alvo = None, None, None
    limite = getattr(regua, "LIMITE_DIAS", 90)
    for r in rows:
        d = regua.dias_ate(r["data_vencimento"], hoje)
        # Passou de três meses: sai da cobrança automática. Insistir por robô
        # depois disso não recupera e desgasta — o caso é de tratativa humana.
        if d > limite:
            continue
        e = regua.etapa_do_dia(cfg["individual"], d)
        if not e:
            continue
        # Uma mensagem por destinatário por dia: fica a mais atrasada.
        if alvo is None or d > dias_alvo:
            alvo, etapa, dias_alvo = r, e, d
    if alvo is None:
        resumo["sem_etapa"] += 1
        return False

    # A marca separa as origens: `mensalidade_aluno` 100 e `cobranca_avulsa` 100
    # são registros distintos e dividiriam a mesma trava de duplicidade.
    marca = "regua:%s:%d" % (alvo.get("origem") or "mensalidade", dias_alvo)
    if _ja_enviado(cur, academia_id, marca, alvo["id"], hoje):
        resumo["repetidos"] += 1
        return False

    tel = _telefone(alvo)
    if not tel:
        resumo["sem_telefone"] += 1
        if wlog:
            wlog.registrar(academia_id, "lembrete_atraso" if dias_alvo > 0 else "lembrete_vencimento",
                           "sem_numero", aluno_id=alvo.get("aluno_id"), lote_id=lote_id)
        return False

    if not _ainda_cobravel(cur, alvo["id"], alvo.get("origem") or "mensalidade"):
        return False

    texto = montar_mensagem(alvo, nome_acad, academia_id, etapa.get("mensagem"))
    if texto is None:
        resumo["desativado"] += 1
        return False

    ok, _info = wpp.enviar(academia_id, tel, texto)
    resumo["enviados" if ok else "falhas"] += 1
    if ok:
        _marcar_enviado(conn, cur, academia_id, marca, alvo["id"], hoje)
    if wlog:
        wlog.registrar(academia_id, "lembrete_atraso" if dias_alvo > 0 else "lembrete_vencimento",
                       "entregue" if ok else "falha", aluno_id=alvo.get("aluno_id"),
                       telefone=tel, lote_id=lote_id)
    return ok


def _regua_consolidada(conn, cur, academia_id, nome_acad, cfg, vencidas, hoje, resumo, wlog, lote_id):
    """Uma mensagem só, com todas as pendências.

    A âncora é o vencimento da N-ésima mais antiga (N = limiar de consolidação):
    é o dia em que o responsável passou a dever N mensalidades. Fixá-la aí é o
    que impede a mensalidade nova de reiniciar a régua — quem já foi cobrado
    três vezes não volta para a estaca zero porque virou o mês.
    """
    from utils import regua_cobranca as regua
    ordenadas = sorted(vencidas, key=lambda r: r["data_vencimento"])
    ancora = ordenadas[cfg["consolidar_apos"] - 1]["data_vencimento"]
    # A etapa 0 é o primeiro dia em que o responsável REALMENTE deve N
    # mensalidades — o dia seguinte ao vencimento da N-ésima. Sem o -1, a etapa
    # 0 cairia no próprio vencimento, quando ele ainda não está em atraso, e
    # portanto nunca dispararia.
    dias = regua.dias_ate(ancora, hoje) - 1
    etapa = regua.etapa_do_dia(cfg["consolidada"], dias)
    if not etapa:
        resumo["sem_etapa"] += 1
        return False

    ref = min(int(r.get("aluno_id") or 0) for r in ordenadas)
    marca = "regua_cons:%d" % dias
    if _ja_enviado(cur, academia_id, marca, ref, hoje):
        resumo["repetidos"] += 1
        return False

    tel = _telefone(ordenadas[0])
    if not tel:
        resumo["sem_telefone"] += 1
        if wlog:
            wlog.registrar(academia_id, "cobranca_consolidada", "sem_numero",
                           aluno_id=ordenadas[0].get("aluno_id"), lote_id=lote_id)
        return False

    # Revalida uma a uma: quem pagou no meio do caminho sai da lista, e se
    # sobrar menos que o limiar a consolidada perde o sentido e nada é enviado
    # hoje (amanhã o responsável cai na régua individual).
    vivas = [r for r in ordenadas
             if _ainda_cobravel(cur, r["id"], r.get("origem") or "mensalidade")]
    if len(vivas) < cfg["consolidar_apos"]:
        return False

    texto = montar_mensagem_consolidada(vivas, nome_acad, academia_id, etapa.get("mensagem"))
    if texto is None:
        resumo["desativado"] += 1
        return False

    ok, _info = wpp.enviar(academia_id, tel, texto)
    resumo["enviados" if ok else "falhas"] += 1
    if ok:
        resumo["consolidados"] += 1
        _marcar_enviado(conn, cur, academia_id, marca, ref, hoje)
    if wlog:
        wlog.registrar(academia_id, "cobranca_consolidada", "entregue" if ok else "falha",
                       aluno_id=ordenadas[0].get("aluno_id"), telefone=tel, lote_id=lote_id)
    return ok
