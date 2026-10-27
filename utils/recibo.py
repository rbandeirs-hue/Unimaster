"""Recibo de pagamento em PDF (mensalidade ou cobrança avulsa paga).

O aluno pagava e só tinha, quando muito, o comprovante do gateway — sem o nome
da academia, sem dizer a que mês se referia. O recibo traz quem recebeu, quem
pagou, a referência, o valor (também por extenso), a data e a forma, com um
número que identifica a cobrança no sistema (M-<id> mensalidade, A-<id> avulsa).

Só sai de cobrança paga e com valor. Quem pode abrir é decidido na rota.
"""
import io
from datetime import date, datetime
from decimal import Decimal

MESES = ["", "janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]

_UNI = ["zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove",
        "dez", "onze", "doze", "treze", "quatorze", "quinze", "dezesseis", "dezessete",
        "dezoito", "dezenove"]
_DEZ = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta",
        "oitenta", "noventa"]
_CEN = ["", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos",
        "setecentos", "oitocentos", "novecentos"]


def _ate_mil(n):
    if n == 0:
        return ""
    if n == 100:
        return "cem"
    partes = []
    c, r = divmod(n, 100)
    if c:
        partes.append(_CEN[c])
    if r:
        if r < 20:
            partes.append(_UNI[r])
        else:
            d, u = divmod(r, 10)
            partes.append(_DEZ[d] + (f" e {_UNI[u]}" if u else ""))
    return " e ".join(partes)


def _inteiro(n):
    if n == 0:
        return "zero"
    grupos = []
    milhoes, resto = divmod(n, 1_000_000)
    milhares, unidades = divmod(resto, 1000)
    if milhoes:
        grupos.append(("um milhão" if milhoes == 1 else _ate_mil(milhoes) + " milhões"))
    if milhares:
        grupos.append("mil" if milhares == 1 else _ate_mil(milhares) + " mil")
    if unidades:
        grupos.append(_ate_mil(unidades))
    # "mil e cem", "dois mil e trinta": o "e" antes do último grupo quando ele
    # é redondo (centena exata) ou menor que cem.
    if len(grupos) > 1 and unidades and (unidades < 100 or unidades % 100 == 0):
        return ", ".join(grupos[:-1]) + " e " + grupos[-1]
    return " ".join(grupos) if len(grupos) <= 2 else ", ".join(grupos)


def por_extenso(valor):
    """Decimal('1234.56') -> 'mil duzentos e trinta e quatro reais e cinquenta e seis centavos'."""
    v = Decimal(str(valor or 0)).quantize(Decimal("0.01"))
    reais, cent = divmod(int(v * 100), 100)
    partes = []
    if reais:
        sufixo = "real" if reais == 1 else "reais"
        if reais >= 1_000_000 and reais % 1_000_000 == 0:
            sufixo = "de reais"
        partes.append(f"{_inteiro(reais)} {sufixo}")
    if cent:
        partes.append(f"{_inteiro(cent)} {'centavo' if cent == 1 else 'centavos'}")
    return " e ".join(partes) if partes else "zero real"


def _moeda(v):
    return "R$ " + f"{Decimal(str(v or 0)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def dados(cur, tipo, registro_id):
    """Tudo o que vai no recibo, ou None se a cobrança não existe / não está paga."""
    if tipo == "mensalidade":
        cur.execute(
            """SELECT ma.id, ma.aluno_id, ma.valor, ma.valor_pago, ma.data_pagamento,
                      ma.data_vencimento, ma.competencia, ma.id_forma_pagamento,
                      m.nome AS referencia, m.id_academia
               FROM mensalidade_aluno ma JOIN mensalidades m ON m.id = ma.mensalidade_id
               WHERE ma.id = %s AND ma.status = 'pago'""", (registro_id,))
        origem_col, prefixo = "id_mensalidade_aluno", "M"
    elif tipo == "avulsa":
        cur.execute(
            """SELECT ca.id, ca.aluno_id, ca.valor, ca.valor_pago, ca.data_pagamento,
                      ca.data_vencimento, NULL AS competencia, NULL AS id_forma_pagamento,
                      ca.descricao AS referencia, ca.id_academia
               FROM cobranca_avulsa ca WHERE ca.id = %s AND ca.status = 'pago'""", (registro_id,))
        origem_col, prefixo = "id_cobranca_avulsa", "A"
    else:
        return None
    c = cur.fetchone()
    if not c:
        return None
    valor = Decimal(str(c["valor_pago"] if c["valor_pago"] not in (None, 0) else c["valor"] or 0))
    if valor <= 0:
        return None   # isenção não tem recibo de pagamento
    cur.execute(f"""SELECT r.valor, r.data, fp.nome AS forma FROM receitas r
                    LEFT JOIN formas_pagamento fp ON fp.id = r.id_forma_pagamento
                    WHERE r.{origem_col} = %s AND COALESCE(r.cancelada, 0) = 0
                    ORDER BY r.data, r.id""", (registro_id,))
    partes = cur.fetchall()
    formas = sorted({p["forma"] for p in partes if p.get("forma")})
    if not formas and c.get("id_forma_pagamento"):
        cur.execute("SELECT nome FROM formas_pagamento WHERE id = %s", (c["id_forma_pagamento"],))
        f = cur.fetchone()
        formas = [f["nome"]] if f else []
    cur.execute("""SELECT nome, cpf, responsavel_financeiro_nome, responsavel_financeiro_cpf
                   FROM alunos WHERE id = %s""", (c["aluno_id"],))
    aluno = cur.fetchone() or {}
    cur.execute("""SELECT id, nome, rua, numero, bairro, cidade, uf, cep, telefone, email
                   FROM academias WHERE id = %s""", (c["id_academia"],))
    academia = cur.fetchone() or {}

    ref = c["referencia"] or ("Mensalidade" if tipo == "mensalidade" else "Cobrança")
    comp = c.get("competencia")
    venc = c.get("data_vencimento")
    if tipo == "mensalidade":
        if comp and len(str(comp)) == 7:
            a, m = str(comp).split("-")
            ref += f" — {MESES[int(m)]} de {a}"
        elif venc:
            ref += f" — {MESES[venc.month]} de {venc.year}"
    return {
        "numero": f"{prefixo}-{c['id']:06d}",
        "tipo": tipo,
        "registro_id": c["id"],
        "aluno_id": c["aluno_id"],
        "academia": academia,
        "aluno": aluno,
        "referencia": ref,
        "vencimento": venc,
        "valor": valor,
        "extenso": por_extenso(valor),
        "data_pagamento": c["data_pagamento"],
        "formas": formas,
    }


def _cpf(txt):
    d = "".join(ch for ch in str(txt or "") if ch.isdigit())
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}" if len(d) == 11 else (txt or "")


def pdf(d, logo_arquivo=None):
    """Bytes do PDF (A4, metade superior: o recibo cabe numa folha cortável)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"Recibo {d['numero']}", author=d["academia"].get("nome") or "")
    cinza = colors.HexColor("#57575a")
    base = ParagraphStyle("b", fontName="Helvetica", fontSize=10, leading=14)
    pequeno = ParagraphStyle("p", parent=base, fontSize=8.5, leading=11, textColor=cinza)
    titulo = ParagraphStyle("t", parent=base, fontName="Helvetica-Bold", fontSize=18, leading=22)
    forte = ParagraphStyle("f", parent=base, fontName="Helvetica-Bold")
    corpo = ParagraphStyle("c", parent=base, fontSize=11, leading=17)

    ac = d["academia"]
    end = ", ".join(x for x in [
        " ".join(x for x in [ac.get("rua"), ac.get("numero")] if x),
        ac.get("bairro"),
        "/".join(x for x in [ac.get("cidade"), ac.get("uf")] if x)] if x)
    contato = " · ".join(x for x in [ac.get("telefone"), ac.get("email")] if x)
    cab_txt = [Paragraph(ac.get("nome") or "", forte)]
    if end:
        cab_txt.append(Paragraph(end, pequeno))
    if contato:
        cab_txt.append(Paragraph(contato, pequeno))
    logo = None
    if logo_arquivo:
        try:
            logo = Image(logo_arquivo, width=20 * mm, height=20 * mm, kind="proportional")
        except Exception:
            logo = None
    cab = Table([[logo or "", cab_txt,
                  [Paragraph("RECIBO", titulo), Paragraph(f"Nº {d['numero']}", pequeno)]]],
                colWidths=[24 * mm, None, 45 * mm])
    cab.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                             ("ALIGN", (2, 0), (2, 0), "RIGHT"),
                             ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#1c1c1c")),
                             ("BOTTOMPADDING", (0, 0), (-1, 0), 8)]))

    al = d["aluno"]
    pagador = al.get("responsavel_financeiro_nome") or al.get("nome") or ""
    cpf_pag = _cpf(al.get("responsavel_financeiro_cpf") or al.get("cpf"))
    aluno_txt = (f" referente ao(à) aluno(a) <b>{al.get('nome')}</b>"
                 if al.get("responsavel_financeiro_nome") and al.get("responsavel_financeiro_nome") != al.get("nome")
                 else "")
    dp = d["data_pagamento"]
    data_txt = f"{dp.day} de {MESES[dp.month]} de {dp.year}" if dp else "—"
    texto = (f"Recebemos de <b>{pagador}</b>{f' (CPF {cpf_pag})' if cpf_pag else ''}{aluno_txt} "
             f"a importância de <b>{_moeda(d['valor'])}</b> ({d['extenso']}), "
             f"referente a <b>{d['referencia']}</b>.")

    det = [["Valor pago", _moeda(d["valor"])],
           ["Data do pagamento", dp.strftime("%d/%m/%Y") if dp else "—"],
           ["Forma de pagamento", ", ".join(d["formas"]) or "Não informada"]]
    if d.get("vencimento"):
        det.insert(1, ["Vencimento", d["vencimento"].strftime("%d/%m/%Y")])
    tab = Table(det, colWidths=[55 * mm, None], hAlign="LEFT")
    tab.setStyle(TableStyle([("FONT", (0, 0), (0, -1), "Helvetica", 9.5),
                             ("TEXTCOLOR", (0, 0), (0, -1), cinza),
                             ("FONT", (1, 0), (1, -1), "Helvetica-Bold", 10),
                             ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor("#e3e3e0")),
                             ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))

    cidade = ac.get("cidade") or ""
    hoje = date.today()
    assinatura = Table([["", ""], [Paragraph(ac.get("nome") or "", pequeno), ""]],
                       colWidths=[80 * mm, None], rowHeights=[16 * mm, None])
    assinatura.setStyle(TableStyle([("LINEABOVE", (0, 1), (0, 1), 0.6, colors.HexColor("#1c1c1c"))]))

    elementos = [cab, Spacer(1, 10 * mm), Paragraph(texto, corpo), Spacer(1, 6 * mm), tab,
                 Spacer(1, 8 * mm),
                 Paragraph(f"{cidade + ', ' if cidade else ''}{hoje.day} de {MESES[hoje.month]} de {hoje.year}.", base),
                 assinatura, Spacer(1, 6 * mm),
                 Paragraph(f"Pagamento registrado em {data_txt}. Recibo emitido eletronicamente em "
                           f"{datetime.now():%d/%m/%Y às %H:%M} pelo sistema; vale sem assinatura.", pequeno)]
    doc.build(elementos)
    return buf.getvalue()
