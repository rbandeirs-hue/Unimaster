# -*- coding: utf-8 -*-
"""Plano de mensalidade por modalidade, com o valor dividido entre elas.

Cada plano diz a que modalidade(s) da academia pertence (`mensalidade_modalidade`).
Num combo, cada modalidade tem a sua parte do valor (`mensalidade_modalidade.valor`,
migração PM-01) e as partes somam o valor do plano: "Judô e Jiu-Jitsu R$ 180" =
Judô 90 + Jiu-Jitsu 90. Plano de uma modalidade só leva o valor inteiro nela.

Onde se escolhe plano, a lista respeita a modalidade em foco (seletor do topo do
sistema, `utils.multimodalidade.contexto_id`): só aparecem os planos que cobrem
aquela modalidade. Plano sem modalidade nenhuma continua aparecendo — sumir com
ele esconderia cobrança sem ninguém saber por quê.
"""
from decimal import Decimal, InvalidOperation

TOLERANCIA = Decimal("0.01")


def _dec(v):
    if v is None or v == "":
        return None
    try:
        s = str(v).strip().replace("R$", "").strip()
        if "," in s:
            s = s.replace(".", "").replace(",", ".")
        return Decimal(s).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def modalidades_dos_planos(cur, plano_ids):
    """{plano_id: [{id, nome, cor, valor, principal}]} na ordem (principal primeiro)."""
    ids = [int(i) for i in plano_ids if i]
    if not ids:
        return {}
    ph = ",".join(["%s"] * len(ids))
    try:
        cur.execute(
            f"""SELECT mm.mensalidade_id, md.id, md.nome, md.cor, mm.valor, mm.principal
                FROM mensalidade_modalidade mm JOIN modalidade md ON md.id = mm.modalidade_id
                WHERE mm.mensalidade_id IN ({ph})
                ORDER BY mm.principal DESC, md.nome""", tuple(ids))
    except Exception:
        return {}
    out = {}
    for r in cur.fetchall():
        linha = r if isinstance(r, dict) else dict(zip(
            ("mensalidade_id", "id", "nome", "cor", "valor", "principal"), r))
        out.setdefault(linha["mensalidade_id"], []).append(
            {"id": linha["id"], "nome": linha["nome"], "cor": linha["cor"],
             "valor": linha["valor"], "principal": linha["principal"]})
    return out


def anotar(cur, planos):
    """Acrescenta a cada plano: `modalidades_plano`, `mod_ids` ("1,7") e `rateio_ok`.

    `modalidades` recebe a mesma lista só quando o plano ainda não tem esse
    campo — algumas consultas (contratos) já trazem `modalidades` como texto e
    a tela delas conta com isso.

    rateio_ok é False quando o combo ainda não tem a divisão do valor (ou a
    soma não bate com o total) — a tela de Planos mostra isso como pendência.
    """
    mapa = modalidades_dos_planos(cur, [p["id"] for p in planos])
    for p in planos:
        mods = mapa.get(p["id"], [])
        p["modalidades_plano"] = mods
        p.setdefault("modalidades", mods)
        p["mod_ids"] = ",".join(str(m["id"]) for m in mods)
        if len(mods) <= 1:
            p["rateio_ok"] = True
        else:
            partes = [m["valor"] for m in mods]
            p["rateio_ok"] = (all(v is not None for v in partes)
                              and abs(sum(Decimal(str(v)) for v in partes)
                                      - Decimal(str(p.get("valor") or 0))) <= TOLERANCIA)
    return planos


def filtrar_contexto(cur, planos, academia_id=None, modalidade_id=None):
    """Só os planos da modalidade em foco (os sem modalidade ficam sempre)."""
    if modalidade_id is None:
        try:
            from utils.multimodalidade import contexto_id
            modalidade_id = contexto_id(academia_id)
        except Exception:
            modalidade_id = None
    if planos and "modalidades_plano" not in planos[0]:
        anotar(cur, planos)
    if not modalidade_id:
        return planos
    return [p for p in planos
            if not p["modalidades_plano"] or any(m["id"] == modalidade_id for m in p["modalidades_plano"])]


def ler_form(form, modalidades_academia, valor_total):
    """Modalidades e divisão do valor vindas do formulário de plano.

    Devolve (linhas, erros): linhas = [(modalidade_id, valor, principal)].
    Regras: ao menos uma modalidade; combo exige o valor de cada uma e a soma
    igual ao valor do plano; plano de uma modalidade leva o valor inteiro.
    """
    validas = {m["id"] for m in modalidades_academia}
    escolhidas = []
    for x in form.getlist("modalidade_ids"):
        if str(x).isdigit() and int(x) in validas and int(x) not in escolhidas:
            escolhidas.append(int(x))
    erros = []
    if not escolhidas:
        return [], ["Escolha a modalidade do plano."]
    total = Decimal(str(valor_total or 0)).quantize(Decimal("0.01"))
    if len(escolhidas) == 1:
        return [(escolhidas[0], total, 1)], []
    linhas, soma = [], Decimal("0")
    nomes = {m["id"]: m["nome"] for m in modalidades_academia}
    for i, mid in enumerate(escolhidas):
        v = _dec(form.get(f"valor_modalidade_{mid}"))
        if v is None or v < 0:
            erros.append(f"Informe quanto do valor é de {nomes.get(mid, 'cada modalidade')}.")
            continue
        soma += v
        linhas.append((mid, v, 1 if i == 0 else 0))
    if not erros and abs(soma - total) > TOLERANCIA:
        erros.append(f"A divisão entre as modalidades soma R$ {soma:.2f}".replace(".", ",")
                     + f", mas o plano é de R$ {total:.2f}".replace(".", ",")
                     + " — as partes precisam fechar o valor do plano.")
    return linhas, erros


def gravar(cur, plano_id, linhas):
    """Reescreve as modalidades do plano com a divisão informada."""
    cur.execute("DELETE FROM mensalidade_modalidade WHERE mensalidade_id = %s", (plano_id,))
    for mid, valor, principal in linhas:
        cur.execute("""INSERT INTO mensalidade_modalidade (mensalidade_id, modalidade_id, principal, valor)
                       VALUES (%s,%s,%s,%s)""", (plano_id, mid, principal, valor))
    try:
        cur.execute("UPDATE mensalidades SET tipo = %s WHERE id = %s",
                    ("pacote" if len(linhas) > 1 else "simples", plano_id))
    except Exception:
        pass
