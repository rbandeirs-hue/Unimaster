from app.models.base import db
from app.models.luta import Luta
from app.models.resultado import Resultado

# Progressão principal da chave
_PROXIMA_FASE = {
    "oitavas":   "quartas",
    "quartas":   "semifinal",
    "semifinal": "final",
}


def listar(categoria_id=None):
    q = Luta.query
    if categoria_id:
        q = q.filter_by(categoria_id=categoria_id)
    return q.all()


def buscar(id):
    return Luta.query.get_or_404(id)


def criar(dados):
    luta = Luta(**dados)
    db.session.add(luta)
    db.session.commit()
    return luta


def _vantagem_por_contagem_resultado(resultado):
    """1 = azul na frente, -1 = branco, 0 = empate nas regras usuais."""
    ai, aw, ay = resultado.ippon_azul or 0, resultado.wazari_azul or 0, resultado.yuko_azul or 0
    bi, bw, by = resultado.ippon_branco or 0, resultado.wazari_branco or 0, resultado.yuko_branco or 0
    if ai != bi:
        return 1 if ai > bi else -1
    if aw != bw:
        return 1 if aw > bw else -1
    if ay != by:
        return 1 if ay > by else -1
    sa, sb = resultado.shido_azul or 0, resultado.shido_branco or 0
    if sa >= 3 and sb < 3:
        return -1
    if sb >= 3 and sa < 3:
        return 1
    return 0


def _resolver_vencedor_id(luta, resultado, venc_lado):
    if venc_lado == "azul" and luta.atleta_azul_id:
        return luta.atleta_azul_id
    if venc_lado == "branco" and luta.atleta_branco_id:
        return luta.atleta_branco_id
    v = _vantagem_por_contagem_resultado(resultado)
    if v > 0:
        return luta.atleta_azul_id
    if v < 0:
        return luta.atleta_branco_id
    return None


_RESULTADO_KEYS = (
    "ippon_azul",
    "wazari_azul",
    "yuko_azul",
    "shido_azul",
    "ippon_branco",
    "wazari_branco",
    "yuko_branco",
    "shido_branco",
    "tempo_luta",
)


def registrar_resultado(luta_id, dados):
    luta = buscar(luta_id)

    if luta.resultado:
        raise ValueError("Resultado já registrado para esta luta.")

    payload = dict(dados)
    venc_lado = payload.pop("vencedor_lado", None)
    if venc_lado not in (None, "azul", "branco"):
        venc_lado = None

    resultado = Resultado(luta_id=luta_id, **payload)
    db.session.add(resultado)

    luta.vencedor_id = _resolver_vencedor_id(luta, resultado, venc_lado)

    db.session.flush()  # garante vencedor_id antes de avançar

    if luta.vencedor_id:
        if luta.fase == "final_bo3":
            _final_bo3_avancar(luta)
        else:
            _avancar_chave(luta)
            _cbj_pos_resultado(luta)

    db.session.commit()
    return luta


def atualizar_resultado(luta_id, dados):
    """Atualiza placar/vencedor após a luta já ter sido finalizada (mesa em modo correção)."""
    luta = buscar(luta_id)
    if not luta.resultado:
        raise ValueError("Esta luta ainda não possui resultado registrado.")
    if luta.fase == "final_bo3":
        raise ValueError(
            "Correção de melhor-de-3 não é suportada nesta tela; use suporte técnico se precisar alterar."
        )

    payload = dict(dados or {})
    venc_lado = payload.pop("vencedor_lado", None)
    if venc_lado not in (None, "azul", "branco"):
        venc_lado = None

    prox = _proxima_luta_fase_principal(luta)
    if prox and prox.resultado:
        raise ValueError(
            "A próxima luta na chave principal já foi finalizada. Corrija primeiro as lutas seguintes, na ordem inversa."
        )

    res = luta.resultado
    for k in _RESULTADO_KEYS:
        if k in payload:
            setattr(res, k, payload[k])

    db.session.flush()
    luta.vencedor_id = _resolver_vencedor_id(luta, res, venc_lado)
    db.session.flush()

    if luta.vencedor_id:
        _avancar_chave(luta)
        _cbj_pos_resultado(luta)

    db.session.commit()
    return luta


# ── Progressão automática ─────────────────────────────────────

def _avancar_chave(luta):
    """Preenche o próximo slot da chave com o vencedor (eliminatória principal)."""
    _preencher_proximo_slot(luta, _PROXIMA_FASE.get(luta.fase), luta.vencedor_id)


def _final_bo3_avancar(luta_concluida):
    """Melhor de 3: no máximo 3 lutas; 3ª só se empate 1–1 após as duas primeiras."""
    cat_id = luta_concluida.categoria_id
    todas = (
        Luta.query.filter_by(categoria_id=cat_id, fase="final_bo3")
        .order_by(Luta.numero_luta)
        .all()
    )
    base = next((x for x in todas if x.atleta_azul_id and x.atleta_branco_id), None)
    if not base:
        return
    aid, bid = base.atleta_azul_id, base.atleta_branco_id
    wins = {aid: 0, bid: 0}
    for lt in todas:
        if lt.resultado and lt.vencedor_id:
            wins[lt.vencedor_id] = wins.get(lt.vencedor_id, 0) + 1
    if wins.get(aid, 0) >= 2 or wins.get(bid, 0) >= 2:
        return

    encerradas = [lt for lt in todas if lt.resultado]
    if len(encerradas) == 1 and len(todas) >= 2:
        l2 = todas[1]
        l2.atleta_azul_id = aid
        l2.atleta_branco_id = bid
    elif len(encerradas) == 2:
        if wins.get(aid, 0) == 1 and wins.get(bid, 0) == 1:
            mx = max(lt.numero_luta for lt in todas)
            db.session.add(
                Luta(
                    categoria_id=cat_id,
                    atleta_azul_id=aid,
                    atleta_branco_id=bid,
                    fase="final_bo3",
                    numero_luta=mx + 1,
                )
            )


def _cbj_modo(categoria_id):
    """Identifica o desenho da repescagem / bronzes a partir das lutas criadas na categoria."""
    n_rep1 = Luta.query.filter_by(categoria_id=categoria_id, fase="repescagem_1").count()
    n_rep2 = Luta.query.filter_by(categoria_id=categoria_id, fase="repescagem_2").count()
    n_qf = Luta.query.filter_by(categoria_id=categoria_id, fase="quartas").count()
    tem_da = Luta.query.filter_by(categoria_id=categoria_id, fase="disputa_3lugar_a").first()

    if tem_da:
        if n_rep1 == 4 and n_rep2 == 2:
            return "rep_dezesseis"
        if n_rep1 == 2 and n_rep2 == 0:
            return "rep_oito"
        if n_rep1 == 1 and n_qf == 3:
            return "sete_com_rep"
        if n_rep1 == 1 and n_qf == 2:
            return "dois_lados_seis"

    if Luta.query.filter_by(categoria_id=categoria_id, fase="repescagem_2").first() and n_rep1 == 2:
        return "rep_oito_legacy"
    return "unico_legacy"


def _lutas_fase(categoria_id, fase):
    return (
        Luta.query.filter_by(categoria_id=categoria_id, fase=fase)
        .order_by(Luta.numero_luta)
        .all()
    )


def _cbj_pos_resultado(luta):
    """Repescagem e disputas de 3º lugar (CBJ), após registrar vencedor na luta."""
    cat_id = luta.categoria_id
    modo = _cbj_modo(cat_id)
    fase = luta.fase

    if fase in ("oitavas", "quartas"):
        perdedor = _get_perdedor(luta)
        if not perdedor:
            return
        lutas_r1 = _lutas_fase(cat_id, fase)
        try:
            idx = next(i for i, lt in enumerate(lutas_r1) if lt.id == luta.id)
        except StopIteration:
            return

        if modo == "rep_dezesseis" and len(lutas_r1) == 8:
            rep1 = _lutas_fase(cat_id, "repescagem_1")
            if len(rep1) < 4:
                return
            alvo = rep1[idx // 2]
            if idx % 2 == 0:
                alvo.atleta_azul_id = perdedor
            else:
                alvo.atleta_branco_id = perdedor

        elif modo == "rep_oito" and len(lutas_r1) == 4:
            rep1 = _lutas_fase(cat_id, "repescagem_1")
            if len(rep1) < 2:
                return
            alvo = rep1[0] if idx < 2 else rep1[1]
            if idx % 2 == 0:
                alvo.atleta_azul_id = perdedor
            else:
                alvo.atleta_branco_id = perdedor

        elif modo == "dois_lados_seis" and len(lutas_r1) == 2 and fase == "quartas":
            r1 = _lutas_fase(cat_id, "repescagem_1")
            if not r1:
                return
            if idx == 0:
                r1[0].atleta_azul_id = perdedor
            else:
                r1[0].atleta_branco_id = perdedor

        elif modo == "sete_com_rep" and len(lutas_r1) == 3:
            da = _lutas_fase(cat_id, "disputa_3lugar_a")
            rep1 = _lutas_fase(cat_id, "repescagem_1")
            if not da or not rep1:
                return
            if idx == 0:
                da[0].atleta_branco_id = perdedor
            elif idx == 1:
                rep1[0].atleta_azul_id = perdedor
            else:
                rep1[0].atleta_branco_id = perdedor

    elif fase == "semifinal":
        perdedor = _get_perdedor(luta)
        if not perdedor:
            return
        lutas_sf = _lutas_fase(cat_id, "semifinal")
        try:
            idx = next(i for i, lt in enumerate(lutas_sf) if lt.id == luta.id)
        except StopIteration:
            return

        if modo in ("rep_oito", "rep_dezesseis"):
            da = _lutas_fase(cat_id, "disputa_3lugar_a")
            db_ = _lutas_fase(cat_id, "disputa_3lugar_b")
            if not da or not db_:
                return
            if idx == 0:
                da[0].atleta_branco_id = perdedor
            else:
                db_[0].atleta_branco_id = perdedor
        elif modo == "rep_oito_legacy":
            rep2 = _lutas_fase(cat_id, "repescagem_2")
            if idx < len(rep2):
                rep2[idx].atleta_branco_id = perdedor
        elif modo == "sete_com_rep":
            da = _lutas_fase(cat_id, "disputa_3lugar_a")
            db_ = _lutas_fase(cat_id, "disputa_3lugar_b")
            if not da or not db_:
                return
            if idx == 0:
                da[0].atleta_azul_id = perdedor
            else:
                db_[0].atleta_azul_id = perdedor
        elif modo == "dois_lados_seis":
            da = _lutas_fase(cat_id, "disputa_3lugar_a")
            db_ = _lutas_fase(cat_id, "disputa_3lugar_b")
            if not da or not db_:
                return
            if idx == 0:
                da[0].atleta_branco_id = perdedor
            else:
                db_[0].atleta_branco_id = perdedor
        else:
            _preencher_proximo_slot(luta, "disputa_3lugar", perdedor)

    elif fase == "repescagem_1" and luta.vencedor_id:
        if modo == "rep_oito":
            rep1 = _lutas_fase(cat_id, "repescagem_1")
            da = _lutas_fase(cat_id, "disputa_3lugar_a")
            db_ = _lutas_fase(cat_id, "disputa_3lugar_b")
            try:
                idx = next(i for i, lt in enumerate(rep1) if lt.id == luta.id)
            except StopIteration:
                return
            if idx == 0 and da:
                da[0].atleta_azul_id = luta.vencedor_id
            elif idx == 1 and db_:
                db_[0].atleta_azul_id = luta.vencedor_id

        elif modo == "rep_dezesseis":
            rep1 = _lutas_fase(cat_id, "repescagem_1")
            rep2 = _lutas_fase(cat_id, "repescagem_2")
            try:
                idx = next(i for i, lt in enumerate(rep1) if lt.id == luta.id)
            except StopIteration:
                return
            if len(rep2) <= idx // 2:
                return
            dest = rep2[idx // 2]
            if idx % 2 == 0:
                dest.atleta_azul_id = luta.vencedor_id
            else:
                dest.atleta_branco_id = luta.vencedor_id

        elif modo == "dois_lados_seis":
            da = _lutas_fase(cat_id, "disputa_3lugar_a")
            db_ = _lutas_fase(cat_id, "disputa_3lugar_b")
            perdedor = _get_perdedor(luta)
            if da:
                da[0].atleta_azul_id = luta.vencedor_id
            if db_ and perdedor:
                db_[0].atleta_azul_id = perdedor

        elif modo == "sete_com_rep":
            db_ = _lutas_fase(cat_id, "disputa_3lugar_b")
            if db_:
                db_[0].atleta_branco_id = luta.vencedor_id

        elif modo == "rep_oito_legacy":
            rep1 = _lutas_fase(cat_id, "repescagem_1")
            rep2 = _lutas_fase(cat_id, "repescagem_2")
            try:
                idx = next(i for i, lt in enumerate(rep1) if lt.id == luta.id)
            except StopIteration:
                return
            if idx < len(rep2):
                rep2[idx].atleta_azul_id = luta.vencedor_id

    elif fase == "repescagem_2" and luta.vencedor_id:
        if modo == "rep_dezesseis":
            rep2 = _lutas_fase(cat_id, "repescagem_2")
            da = _lutas_fase(cat_id, "disputa_3lugar_a")
            db_ = _lutas_fase(cat_id, "disputa_3lugar_b")
            try:
                idx = next(i for i, lt in enumerate(rep2) if lt.id == luta.id)
            except StopIteration:
                return
            if idx == 0 and da:
                da[0].atleta_azul_id = luta.vencedor_id
            elif idx == 1 and db_:
                db_[0].atleta_azul_id = luta.vencedor_id


def _template_slots_byes_primeira_segunda(n_byes, n_lutas_r1):
    """Espelha _montar_slots_apos_r1: posições dos vencedores de R1 na rodada seguinte."""
    slots = []
    for i in range(n_lutas_r1):
        if i < n_byes:
            slots.append("bye")
        slots.append(None)
    for j in range(n_lutas_r1, n_byes):
        slots.append("bye")
    return slots


def _slot_destino_por_byes(lutas_r1, lutas_r2, idx_r1):
    """
    1ª rodada com byes → slot na fase seguinte (luta, 'azul'|'branco') ou (None, None).
    """
    q = len(lutas_r1)
    s = len(lutas_r2)
    b = 2 * s - q
    if b < 0 or q == 0 or s == 0:
        return None, None
    tpl = _template_slots_byes_primeira_segunda(b, q)
    none_pos = [i for i, x in enumerate(tpl) if x is None]
    if idx_r1 < 0 or idx_r1 >= len(none_pos):
        return None, None
    pos = none_pos[idx_r1]
    dest_i = pos // 2
    if dest_i >= s:
        return None, None
    lado = "azul" if pos % 2 == 0 else "branco"
    return lutas_r2[dest_i], lado


def _preencher_primeira_rodada_com_byes(lutas_r1, lutas_r2, idx_r1, atleta_id):
    """
    1ª rodada (oitavas/quartas) com byes → 2ª rodada: cada vencedor cai no slot certo
    (evita idx//2, que juntava dois byes na mesma luta quando havia 2+ byes).
    """
    luta_dest, lado = _slot_destino_por_byes(lutas_r1, lutas_r2, idx_r1)
    if not luta_dest:
        return False
    if lado == "azul":
        luta_dest.atleta_azul_id = atleta_id
    else:
        luta_dest.atleta_branco_id = atleta_id
    return True


def _proxima_luta_fase_principal(luta_origem):
    """Próxima luta da eliminatória principal que recebe o vencedor desta (para validar correção)."""
    fase_destino = _PROXIMA_FASE.get(luta_origem.fase)
    if not fase_destino:
        return None

    lutas_atual = (
        Luta.query.filter_by(categoria_id=luta_origem.categoria_id, fase=luta_origem.fase)
        .order_by(Luta.numero_luta)
        .all()
    )
    try:
        idx = next(i for i, l in enumerate(lutas_atual) if l.id == luta_origem.id)
    except StopIteration:
        return None

    lutas_destino = (
        Luta.query.filter_by(categoria_id=luta_origem.categoria_id, fase=fase_destino)
        .order_by(Luta.numero_luta)
        .all()
    )

    if (luta_origem.fase, fase_destino) in (
        ("oitavas", "quartas"),
        ("quartas", "semifinal"),
    ):
        dest, _ = _slot_destino_por_byes(lutas_atual, lutas_destino, idx)
        if dest is not None:
            return dest

    idx_destino = idx // 2
    if idx_destino >= len(lutas_destino):
        return None
    return lutas_destino[idx_destino]


def _preencher_proximo_slot(luta_origem, fase_destino, atleta_id):
    """
    Calcula qual luta/slot da fase_destino pertence a esta luta e preenche azul ou branco.

    Regra de indexação (chave simples):
      - Ordena as lutas da fase atual por numero_luta → índice = posição da luta
      - Luta destino = lutas_destino[ índice // 2 ]
      - Slot azul   se índice é par
      - Slot branco se índice é ímpar

    Exceção: primeira rodada com byes → segunda usa template (alinhado a chaveamento_service).
    """
    if not fase_destino or not atleta_id:
        return

    lutas_atual = (
        Luta.query.filter_by(categoria_id=luta_origem.categoria_id, fase=luta_origem.fase)
        .order_by(Luta.numero_luta)
        .all()
    )

    try:
        idx = next(i for i, l in enumerate(lutas_atual) if l.id == luta_origem.id)
    except StopIteration:
        return

    lutas_destino = (
        Luta.query.filter_by(categoria_id=luta_origem.categoria_id, fase=fase_destino)
        .order_by(Luta.numero_luta)
        .all()
    )

    if (luta_origem.fase, fase_destino) in (
        ("oitavas", "quartas"),
        ("quartas", "semifinal"),
    ):
        if _preencher_primeira_rodada_com_byes(lutas_atual, lutas_destino, idx, atleta_id):
            return

    idx_destino = idx // 2
    if idx_destino >= len(lutas_destino):
        return

    luta_dest = lutas_destino[idx_destino]

    if idx % 2 == 0:
        luta_dest.atleta_azul_id = atleta_id
    else:
        luta_dest.atleta_branco_id = atleta_id


def _get_perdedor(luta):
    if luta.vencedor_id == luta.atleta_azul_id:
        return luta.atleta_branco_id
    if luta.vencedor_id == luta.atleta_branco_id:
        return luta.atleta_azul_id
    return None
