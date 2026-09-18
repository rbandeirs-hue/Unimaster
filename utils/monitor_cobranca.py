# -*- coding: utf-8 -*-
"""Monitor da cobrança automática: o que a régua vê e o que ela já falou.

A régua funciona, mas era invisível. Quando o gestor recebia "a mãe do Pietro
diz que está sendo cobrada", não havia onde olhar: a decisão do robô vivia no
log do servidor e nas tabelas de controle. Este módulo junta as três pontas —
o que está em aberto, o que já foi enviado e qual é o próximo passo — por
DESTINATÁRIO, que é como a régua raciocina.

A regra não é reimplementada aqui. As funções de decisão são as mesmas que o
envio usa (`buscar_em_aberto`, `_chave_destinatario`, `etapa_do_dia`); se a
régua mudar, a tela muda junto. Uma segunda cópia da regra seria pior do que
não ter tela nenhuma: mostraria com confiança algo que não acontece.
"""
from datetime import date, timedelta

from config import get_db_connection

# Quantos dias de histórico a tela mostra por destinatário.
DIAS_HISTORICO = 90
# Até onde projetar o próximo disparo.
DIAS_PROJECAO = 120


def _situacao(qtd_vencidas, cfg):
    """O que a régua FARIA com este destinatário hoje, pelos mesmos limiares."""
    if qtd_vencidas <= 0:
        return "a_vencer", "Só a vencer"
    if cfg.get("tratativa_apos") and qtd_vencidas >= cfg["tratativa_apos"]:
        return "tratativa", "Parou o automático — tratativa humana"
    if qtd_vencidas >= cfg.get("consolidar_apos", 2):
        return "consolidada", "Cobrança consolidada"
    return "individual", "Cobrança individual"


def _historico(cur, academia_id, alunos_ids, telefone, desde):
    """Mensagens já enviadas a este destinatário.

    Casa por telefone E por aluno: o log guarda os dois, e um responsável que
    trocou de número continua aparecendo pelos filhos.
    """
    if not alunos_ids and not telefone:
        return []
    so_digitos = "".join(c for c in (telefone or "") if c.isdigit())
    condicoes, params = [], [academia_id, desde]
    if alunos_ids:
        condicoes.append("aluno_id IN (%s)" % ",".join(["%s"] * len(alunos_ids)))
        params.extend(alunos_ids)
    if so_digitos:
        # O telefone é gravado com máscara; comparar só os dígitos evita perder
        # o registro por causa de um parêntese.
        condicoes.append(
            "REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(telefone,''),'(',''),')',''),'-',''),' ','') = %s")
        params.append(so_digitos)
    try:
        cur.execute(
            f"""SELECT id, tipo, status, telefone, aluno_id, erro, criado_em
                FROM whatsapp_log
                WHERE id_academia = %s AND criado_em >= %s
                  AND ({' OR '.join(condicoes)})
                ORDER BY criado_em DESC
                LIMIT 40""", tuple(params))
        return cur.fetchall() or []
    except Exception:
        return []


def _etapas_marcadas(cur, academia_id, desde):
    """(referencia_id, tipo) -> data de envio, vindo de `whatsapp_envios`.

    É a trava de duplicidade da régua, e de quebra diz QUAL cobrança e QUAL
    etapa dispararam — informação que o log de mensagem não guarda.
    """
    marcas = {}
    try:
        cur.execute(
            """SELECT tipo, referencia_id, data_ref, enviado_em
               FROM whatsapp_envios
               WHERE id_academia = %s AND enviado_em >= %s
               ORDER BY enviado_em DESC""", (academia_id, desde))
        for r in cur.fetchall() or []:
            marcas.setdefault(r["referencia_id"], []).append(r)
    except Exception:
        pass
    return marcas


def _ja_disparou_hoje(marcas, cobranca_id, hoje):
    """A etapa de hoje daquela cobrança já foi enviada?

    Sem isto a tela anunciava "próximo aviso: hoje" para uma mensagem que saiu
    às 9h — e o gestor ficava esperando algo que já tinha acontecido.
    """
    for m in marcas.get(cobranca_id) or []:
        ref = m.get("data_ref")
        if ref and ref == hoje:
            return True
    return False


def _proximos_disparos(cobrancas, cfg, hoje, marcas=None, limite=3):
    """As próximas datas em que a régua vai falar sobre estas cobranças."""
    from utils import regua_cobranca as regua

    marcas = marcas or {}
    etapas = cfg.get("individual") or []
    futuros = []
    for c in cobrancas:
        venc = c.get("data_vencimento")
        if not venc:
            continue
        for d in range(0, DIAS_PROJECAO):
            dia = hoje + timedelta(days=d)
            atraso = regua.dias_ate(venc, dia)
            if atraso > getattr(regua, "LIMITE_DIAS", 180):
                break
            if not regua.etapa_do_dia(etapas, atraso):
                continue
            if d == 0 and _ja_disparou_hoje(marcas, c.get("id"), hoje):
                continue          # a de hoje já saiu; procura a seguinte
            futuros.append({"data": dia, "dias": atraso,
                            "cobranca_id": c.get("id"),
                            "origem": c.get("origem") or "mensalidade"})
            break
    futuros.sort(key=lambda x: x["data"])
    return futuros[:limite]


def panorama(academia_id, hoje=None, somente_com_aberto=True):
    """Um retrato por destinatário: aberto, histórico e próximo passo."""
    from utils import whatsapp_lembretes as lem
    from utils import regua_cobranca as regua

    hoje = hoje or date.today()
    desde = hoje - timedelta(days=DIAS_HISTORICO)

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cfg = regua.carregar(academia_id, cur)
        linhas = lem.buscar_em_aberto(cur, academia_id)
        marcas = _etapas_marcadas(cur, academia_id, desde)

        grupos = {}
        for row in linhas:
            grupos.setdefault(lem._chave_destinatario(row), []).append(row)

        resultado = []
        for chave, rows in grupos.items():
            suspensas = [r for r in rows if regua.suspenso(r, hoje)]
            ativas = [r for r in rows if not regua.suspenso(r, hoje)]
            vencidas = [r for r in ativas
                        if regua.dias_ate(r["data_vencimento"], hoje) > 0]

            primeiro = rows[0]
            telefone = lem._telefone(primeiro)
            nome_resp = (primeiro.get("responsavel_financeiro_nome")
                         or primeiro.get("nome") or "—")

            alunos, vistos = [], set()
            for r in rows:
                aid = r.get("aluno_id")
                if aid and aid not in vistos:
                    vistos.add(aid)
                    alunos.append({"id": aid, "nome": r.get("nome")})

            cobrancas = []
            for r in sorted(ativas + suspensas,
                            key=lambda x: x.get("data_vencimento") or hoje):
                atraso = regua.dias_ate(r["data_vencimento"], hoje)
                disparos = marcas.get(r.get("id"), [])
                # A marca é por origem: mensalidade 5 e avulsa 5 são registros
                # diferentes e não podem se confundir.
                origem = r.get("origem") or "mensalidade"
                disparos = [d for d in disparos
                            if (d.get("tipo") or "").startswith(f"regua:{origem}:")
                            or (d.get("tipo") or "").startswith("regua_cons")]
                cobrancas.append({
                    "id": r.get("id"),
                    "origem": origem,
                    "aluno": r.get("nome"),
                    "aluno_id": r.get("aluno_id"),
                    "vencimento": r.get("data_vencimento"),
                    "valor": float(r.get("valor") or 0),
                    "status": r.get("status"),
                    "atraso": atraso,
                    "suspensa": regua.suspenso(r, hoje),
                    "avisos": len(disparos),
                })

            if not ativas:
                chave_sit, rotulo = "suspenso", "Cobrança suspensa"
            elif not telefone:
                chave_sit, rotulo = "sem_telefone", "Sem telefone cadastrado"
            else:
                chave_sit, rotulo = _situacao(len(vencidas), cfg)

            historico = _historico(cur, academia_id,
                                   [a["id"] for a in alunos], telefone, desde)

            resultado.append({
                "chave": chave, "responsavel": nome_resp, "telefone": telefone,
                "alunos": alunos, "cobrancas": cobrancas,
                "total": sum(c["valor"] for c in cobrancas),
                "total_vencido": sum(c["valor"] for c in cobrancas if c["atraso"] > 0),
                "qtd_vencidas": len(vencidas),
                "situacao": chave_sit, "situacao_rotulo": rotulo,
                "historico": historico,
                "ultimo_aviso": historico[0]["criado_em"] if historico else None,
                "proximos": _proximos_disparos(ativas, cfg, hoje, marcas),
            })

        # Quem está mais atrasado e deve mais aparece primeiro.
        ordem = {"tratativa": 0, "consolidada": 1, "individual": 2,
                 "sem_telefone": 3, "a_vencer": 4, "suspenso": 5}
        resultado.sort(key=lambda d: (ordem.get(d["situacao"], 9),
                                      -d["total_vencido"], -d["total"]))
        if somente_com_aberto:
            resultado = [d for d in resultado if d["cobrancas"]]
        return {"destinatarios": resultado, "cfg": cfg, "hoje": hoje}
    finally:
        cur.close()
        conn.close()


def resumo(panorama_dict):
    """Os números do topo da tela."""
    ds = panorama_dict.get("destinatarios") or []
    return {
        "destinatarios": len(ds),
        "em_tratativa": sum(1 for d in ds if d["situacao"] == "tratativa"),
        "consolidados": sum(1 for d in ds if d["situacao"] == "consolidada"),
        "sem_telefone": sum(1 for d in ds if d["situacao"] == "sem_telefone"),
        "suspensos": sum(1 for d in ds if d["situacao"] == "suspenso"),
        "total_aberto": sum(d["total"] for d in ds),
        "total_vencido": sum(d["total_vencido"] for d in ds),
        "avisos_hoje": sum(
            1 for d in ds for h in d["historico"]
            if h["criado_em"] and h["criado_em"].date() == panorama_dict["hoje"]),
    }
