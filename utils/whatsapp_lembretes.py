# -*- coding: utf-8 -*-
"""Lembretes de mensalidade via WhatsApp (Baileys).

Usado pelo botão manual (financeiro) e pelo script diário (cron).
Tolerante a falhas: nunca levanta exceção para o chamador.
"""
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


def montar_mensagem(row, academia_nome, academia_id=None):
    """Monta a mensagem usando o template configurável da academia.
    Retorna o texto, ou None se o template daquele tipo estiver desativado."""
    from utils import whatsapp_templates as tpl
    tipo = "lembrete_atraso" if (row.get("data_vencimento")
                                 and row["data_vencimento"] < date.today()) else "lembrete_vencimento"
    texto, ativo = tpl.obter(academia_id, tipo)
    if not ativo:
        return None

    # Emite a cobrança agora se ainda não houver link — é o que garante que a
    # mensagem automática saia com um link de pagamento válido.
    if academia_id:
        row = garantir_cobranca_online(row, academia_id)

    venc = row.get("data_vencimento")
    valor = float(row.get("valor") or 0)
    ctx = {
        "nome": _PRIMEIRO_NOME(_destinatario(row)),
        "aluno": row.get("nome") or "",
        "valor": f"R$ {valor:.2f}".replace(".", ","),
        "vencimento": venc.strftime("%d/%m/%Y") if venc else "",
        "link": _link(row, academia_id) or "",
        "pix": _pix(row) or "",
        "academia": academia_nome or "",
        "mes": venc.strftime("%m/%Y") if venc else "",
    }
    return _limpar_placeholders_vazios(tpl.render(texto, ctx))


def _nome_academia(cur, academia_id):
    cur.execute("SELECT nome, whatsapp_lembrete_mensalidade FROM academias WHERE id=%s", (academia_id,))
    r = cur.fetchone()
    return (r or {})


def buscar_pendentes(cur, academia_id, dias_antes=3, somente_atrasadas=False):
    """Mensalidades pendentes/atrasadas com vencimento até hoje+dias_antes.

    Com `somente_atrasadas`, traz só o que já venceu — é o que alimenta o botão
    "Notificar atrasados" do painel.
    """
    if somente_atrasadas:
        cur.execute(
            """
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
              AND ma.valor > 0
            ORDER BY ma.data_vencimento
            """,
            (academia_id,),
        )
        return cur.fetchall()
    cur.execute(
        """
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
          AND ma.valor > 0
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
