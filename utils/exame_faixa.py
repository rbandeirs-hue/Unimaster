# -*- coding: utf-8 -*-
"""Exame de faixa: programa por promoção, situação do aluno, sorteio e notas.

O programa de cada associação vive em `exame_faixa_programa`, uma linha por
promoção (de → para), casada com a tabela `graduacao` pelo id. É por isso que
"qual é o exame deste aluno" é só olhar a faixa atual dele: a promoção é a
linha cujo `graduacao_de_id` é o `alunos.graduacao_id`.

O método de avaliação é o do CFPGs (kyu.js):
  * a banca sorteia técnicas por grupo — metade da faixa em exame, metade do
    acumulado das faixas anteriores, sem repetir;
  * cada técnica recebe nota de 0 a 10;
  * média por grupo → média geral ponderada pelos pesos dos grupos;
  * aprovado com média geral >= NOTA_CORTE.
Só entram na média os grupos que receberam nota: a faixa branca, que não tem
kaeshi nem renraku, não é punida por grupo vazio.
"""

import json
import random
import unicodedata
from datetime import date, datetime

from dateutil.relativedelta import relativedelta

from utils import exame_faixa_material as mat
from utils.exame_faixa_dados import GLOSSARIO

NOTA_CORTE = 6.0

# Grupos avaliados na prova. `tipo` diz como o item vira rótulo: lista é o
# nome da técnica; par é "golpe × contragolpe" ou "1ª + 2ª".
# `significado` é o que o nome japonês quer dizer, para a tela não cobrar do
# aluno que ele já saiba o rótulo do grupo antes de estudar o conteúdo dele.
# As traduções são as do glossário da FPJU (Tadao Nagai, 9º Dan).
GRUPOS = [
    {"chave": "nage",    "nome": "Nage-waza",          "tipo": "lista", "simbolo": "",
     "significado": "técnicas de arremesso — projetar o oponente de pé"},
    {"chave": "katame",  "nome": "Katame-waza",        "tipo": "lista", "simbolo": "",
     "significado": "técnicas de controle no solo — imobilizar, estrangular, chavear"},
    {"chave": "kaeshi",  "nome": "Kaeshi-waza",        "tipo": "par",   "simbolo": "×",
     "significado": "contragolpes — devolver o ataque do oponente"},
    {"chave": "renraku", "nome": "Renraku-henka-waza", "tipo": "par",   "simbolo": "+",
     "significado": "técnicas combinadas — uma puxa a seguinte, em sequência"},
    {"chave": "teoria",  "nome": "Conhecimento teórico", "tipo": "lista", "simbolo": "",
     "significado": "história, terminologia, saudações e arbitragem"},
]
QTD_PADRAO = {"nage": 4, "katame": 3, "kaeshi": 2, "renraku": 2, "teoria": 3}

# A prova tem três partes, cada uma com nota própria: a teórica e a prática,
# esta dividida em nage-waza e katame-waza. Kaeshi e renraku são projeções
# (contragolpe e combinação), então contam dentro da parte de nage-waza.
PARTES = [
    {"chave": "teorica", "nome": "Teórica", "sub": "Histórico, terminologia e saudações",
     "grupos": ["teoria"]},
    {"chave": "nage", "nome": "Prática — Nage-waza", "sub": "Projeções, kaeshi e renraku",
     "grupos": ["nage", "kaeshi", "renraku"]},
    {"chave": "katame", "nome": "Prática — Katame-waza", "sub": "Imobilizações, estrangulamentos e chaves",
     "grupos": ["katame"]},
]
# Pesos das partes na média geral. Iguais por padrão; a banca ajusta na ficha.
PESOS_PADRAO = {"teorica": 1, "nage": 1, "katame": 1}

RESULTADOS = {
    "pendente":  ("Aguardando prova", "warning"),
    "aprovado":  ("Aprovado", "success"),
    "reprovado": ("Não aprovado", "danger"),
    "ausente":   ("Ausente", "info"),
}

# Cor de cada faixa, para o selo. Faixa dupla ("Azul/Amarela") vira duas.
_CORES = {
    "branca": "#f4f4f2", "cinza": "#8a8f96", "azul": "#1f5fbf", "amarela": "#f2c200",
    "laranja": "#ee7a1f", "verde": "#2e8b47", "roxa": "#6a4c93", "marrom": "#6b4a2b",
    "preta": "#1b1b1b", "vermelha": "#c8102e",
}


# ------------------------------------------------------------------ formato
def _norm(txt):
    s = unicodedata.normalize("NFD", str(txt or "")).encode("ascii", "ignore").decode()
    return "".join(ch for ch in s.lower() if ch.isalnum())


def nome_faixa(txt):
    """'AZUL/AMARELA' -> 'Azul/Amarela' (a tabela graduacao guarda em caixa alta)."""
    partes = [p.strip() for p in str(txt or "").replace(" / ", "/").split("/")]
    return "/".join(p[:1].upper() + p[1:].lower() for p in partes if p)


def cores_faixa(txt):
    partes = [_norm(p) for p in str(txt or "").replace(" e ", "/").split("/")]
    return [_CORES[p] for p in partes if p in _CORES] or ["#cccccc"]


def rotulo_item(grupo, item):
    if grupo["tipo"] == "par" and isinstance(item, dict):
        return f'{item.get("a", "")} {grupo["simbolo"]} {item.get("b", "")}'
    return str(item)


def moeda(v):
    if v is None:
        return "—"
    return ("R$ " + f"{float(v):,.2f}").replace(",", "X").replace(".", ",").replace("X", ".")


def _json(txt, padrao):
    if not txt:
        return padrao
    if isinstance(txt, (dict, list)):
        return txt
    try:
        return json.loads(txt)
    except (TypeError, ValueError):
        return padrao


# ---------------------------------------------------------------- programa
def associacao_da_academia(cur, academia_id):
    if not academia_id:
        return None
    cur.execute("SELECT id_associacao FROM academias WHERE id = %s", (academia_id,))
    r = cur.fetchone()
    return (r or {}).get("id_associacao")


def programa(cur, id_associacao, so_ativos=True):
    """Promoções da associação, na ordem, já com o conteúdo decodificado.

    Cada item traz `de`/`para` (nome e id da graduação), `cores_de`/`cores_para`
    e `conteudo` (dict). Lista vazia quando a associação não tem programa ou a
    migração EXF-01 ainda não rodou — as telas mostram isso como estado vazio.
    """
    if not id_associacao:
        return []
    try:
        cur.execute(
            """SELECT p.*, gd.faixa AS de_faixa, gd.graduacao AS de_grau,
                      gp.faixa AS para_faixa, gp.graduacao AS para_grau
               FROM exame_faixa_programa p
               JOIN graduacao gd ON gd.id = p.graduacao_de_id
               JOIN graduacao gp ON gp.id = p.graduacao_para_id
               WHERE p.id_associacao = %s""" + (" AND p.ativo = 1" if so_ativos else "") + """
               ORDER BY p.ordem, p.id""",
            (id_associacao,))
        linhas = cur.fetchall() or []
    except Exception:
        return []
    for i, p in enumerate(linhas):
        p["indice"] = i
        p["conteudo"] = _json(p.get("conteudo"), {})
        p["de"] = nome_faixa(p["de_faixa"])
        p["para"] = nome_faixa(p["para_faixa"])
        p["cores_de"] = cores_faixa(p["de_faixa"])
        p["cores_para"] = cores_faixa(p["para_faixa"])
        p["valor_fmt"] = moeda(p.get("valor"))
        p["idade_txt"] = texto_idade(p)
        p["carencia_txt"] = (f'{p["carencia_meses"]} meses' if p.get("carencia_meses") else "—")
    return linhas


def texto_idade(p):
    mi, ma = p.get("idade_minima"), p.get("idade_maxima")
    if mi and ma:
        return f"{mi} a {ma} anos"
    if mi:
        return f"mínimo {mi} anos"
    return "—"


def itens(p, chave):
    """Itens de um grupo numa promoção. `teoria` junta histórico e terminologia."""
    c = p.get("conteudo") or {}
    if chave == "teoria":
        out = [h.get("q") for h in (c.get("historico") or []) if isinstance(h, dict) and h.get("q")]
        for k in ("terminologia", "reiho", "gestos"):
            out += [t for t in (c.get(k) or []) if isinstance(t, str)]
        return out
    return list(c.get(chave) or [])


def _dedup(grupo, lista):
    vistos, out = set(), []
    for it in lista:
        k = rotulo_item(grupo, it).lower()
        if k not in vistos:
            vistos.add(k)
            out.append(it)
    return out


def itens_acumulados(prog, indice, chave):
    grupo = grupo_por_chave(chave)
    out = []
    for p in prog[: indice + 1]:
        out += itens(p, chave)
    return _dedup(grupo, out)


def grupo_por_chave(chave):
    return next((g for g in GRUPOS if g["chave"] == chave), GRUPOS[0])


def glossario(termo):
    alvo = _norm(termo)
    for k, v in GLOSSARIO.items():
        if _norm(k) == alvo:
            return v
    return None


def blocos_estudo(p):
    """Conteúdo de uma promoção organizado para a tela de estudo.

    Devolve (conhecimento, tecnicas): o primeiro é uma lista de blocos teóricos
    com o significado dos termos; o segundo, os grupos de técnica com rótulos.
    """
    c = p.get("conteudo") or {}
    conhecimento = []
    if c.get("historico"):
        conhecimento.append({"titulo": "Conhecimento histórico", "tipo": "qa",
                             "itens": [{"q": h.get("q"), "a": h.get("a")} for h in c["historico"]]})
    for chave, titulo in (("terminologia", "Terminologia"), ("reiho", "Rei-ho (saudações)"),
                          ("gestos", "Gestos de arbitragem")):
        if c.get(chave):
            conhecimento.append({"titulo": titulo, "tipo": "termos",
                                 "itens": [{"q": t, "a": glossario(t)} for t in c[chave]]})
    if c.get("arbitragem"):
        conhecimento.append({"titulo": "Arbitragem", "tipo": "lista", "itens": c["arbitragem"]})
    conhecimento += _blocos_material(c)
    conhecimento += _bloco_pedido_teoria(p)

    tecnicas = []
    for g in GRUPOS:
        if g["chave"] == "teoria":
            continue
        lista = [_item_tecnica(g, it) for it in itens(p, g["chave"])]
        if lista:
            tecnicas.append({"nome": g["nome"], "chave": g["chave"],
                             "significado": g.get("significado"), "itens": lista})
    return conhecimento, tecnicas


def _bloco_pedido_teoria(p):
    """A lista do que a banca cobra de teoria, separada do material.

    Os blocos de cima misturam as duas coisas por necessidade: para estudar a
    terminologia é preciso ver o termo *e* o significado. Mas quem quer saber
    só o que cai precisa da lista limpa — e é esta, a mesma que alimenta o
    sorteio (`itens(p, "teoria")`), para a tela não prometer uma coisa e a
    prova cobrar outra.
    """
    lista = itens(p, "teoria")
    if not lista:
        return []
    return [{"titulo": "O que a banca pede", "tipo": "pedido", "itens": lista,
             "sorteio": QTD_PADRAO.get("teoria")}]


def _bloco_material(titulo, subtitulo, pedido, catalogo, nota):
    """Bloco de estudo com catálogo fixo: o material em cima, o que a banca
    pede embaixo.

    O programa diz "Ukemi-waza: um tipo" e para por aí — quem treina sabe de
    que tipos se fala, quem estuda em casa não. Então o bloco sempre mostra o
    catálogo inteiro (`catalogo`) e deixa claro, à parte, o recorte cobrado
    nesta promoção (`pedido`).

    `pedido` vem como texto ("Dois tipos") ou como lista de nomes; quando é
    lista, os itens nomeados ficam marcados dentro do catálogo.
    """
    exigidos = pedido if isinstance(pedido, list) else []
    chaves = {_norm(x) for x in exigidos}
    itens_cat = [dict(it, exigido=_norm(it["nome"]) in chaves) for it in catalogo]
    return {
        "titulo": titulo, "subtitulo": subtitulo, "tipo": "material",
        "itens": itens_cat, "nota": nota,
        "pedido": ", ".join(exigidos) if exigidos else (pedido or ""),
        # Só conta como "item novo" o que a promoção nomeia: "um tipo" é uma
        # escolha dentro do catálogo, não um item a mais para decorar.
        "n": len(exigidos),
    }


def _blocos_material(c):
    """Ukemi e kumi-kata viram blocos de material; os dois são catálogo fixo."""
    out = []
    if c.get("ukemi"):
        out.append(_bloco_material(
            "Ukemi-waza", "as quedas", c["ukemi"], mat.UKEMI, mat.UKEMI_NOTA))
    if c.get("kumikata"):
        out.append(_bloco_material(
            "Kumi-kata", "as pegadas", c["kumikata"], mat.KUMI_KATA, mat.KUMI_KATA_NOTA))
    return out


def _parte_tecnica(nome):
    f = mat.ficha(nome)
    return {"nome": nome, "ficha": f, "familia": mat.familia((f or {}).get("familia"))}


def _item_tecnica(grupo, item):
    """Uma linha da lista de técnicas, já com a ficha de estudo de cada nome.

    Kaeshi e renraku são pares ("golpe × contragolpe"), e as duas metades são
    técnicas com ficha própria — por isso a linha guarda `partes`, e não um
    texto só.
    """
    rotulo = rotulo_item(grupo, item)
    if grupo["tipo"] == "par" and isinstance(item, dict):
        partes = [_parte_tecnica(item.get("a", "")), _parte_tecnica(item.get("b", ""))]
        return {"rotulo": rotulo, "sep": grupo["simbolo"], "partes": partes}
    return {"rotulo": rotulo, "sep": None, "partes": [_parte_tecnica(rotulo)]}


# ------------------------------------------------------- edição do conteúdo
# Campos do editor, na ordem da tela. tipo:
#   linhas  um item por linha
#   qa      "Pergunta | Resposta" por linha
#   par     "Golpe × Contragolpe" (kaeshi) ou "1ª + 2ª" (renraku) por linha
#   texto   uma frase ("Dois tipos")
#   ukemi   texto de uma linha, ou vários nomes (um por linha)
CAMPOS_CONTEUDO = [
    {"chave": "historico",    "rotulo": "Conhecimento histórico", "tipo": "qa",
     "ajuda": "Uma pergunta por linha. Depois de “|”, a resposta que aparece no modo estudo."},
    {"chave": "terminologia", "rotulo": "Terminologia", "tipo": "linhas", "ajuda": "Um termo por linha."},
    {"chave": "reiho",        "rotulo": "Rei-ho (saudações)", "tipo": "linhas", "ajuda": "Um termo por linha."},
    {"chave": "gestos",       "rotulo": "Gestos de arbitragem", "tipo": "linhas", "ajuda": "Um gesto por linha."},
    {"chave": "arbitragem",   "rotulo": "Arbitragem", "tipo": "linhas", "ajuda": "Um tópico por linha."},
    {"chave": "ukemi",        "rotulo": "Ukemi-waza", "tipo": "ukemi",
     "ajuda": "Uma linha só (ex.: “Dois tipos”) ou o nome de cada queda, um por linha."},
    {"chave": "kumikata",     "rotulo": "Kumi-kata", "tipo": "texto", "ajuda": "Ex.: “Dois tipos”."},
    {"chave": "nage",         "rotulo": "Nage-waza", "tipo": "linhas", "ajuda": "Uma técnica por linha."},
    {"chave": "katame",       "rotulo": "Katame-waza", "tipo": "linhas", "ajuda": "Uma técnica por linha."},
    {"chave": "kaeshi",       "rotulo": "Kaeshi-waza", "tipo": "par", "simbolo": "×",
     "ajuda": "Golpe × contragolpe, um por linha. Ex.: Seoi-nage × Ko-soto-gari"},
    {"chave": "renraku",      "rotulo": "Renraku-henka-waza", "tipo": "par", "simbolo": "+",
     "ajuda": "1ª técnica + 2ª técnica, uma combinação por linha. Ex.: De-ashi-harai + Seoi-nage"},
    {"chave": "katas",        "rotulo": "Katas cobrados", "tipo": "linhas",
     "ajuda": "Nage-no-kata e/ou Katame-no-kata, um por linha. Em branco: os katas aparecem como material complementar."},
]

_SEPARADORES_PAR = (" × ", "×", " x ", " X ", " + ", "+", " | ", "|", " -> ", " → ")


def conteudo_para_form(c):
    """Conteúdo (dict do banco) -> texto de cada campo do editor."""
    out = {}
    for campo in CAMPOS_CONTEUDO:
        v = (c or {}).get(campo["chave"])
        if campo["tipo"] == "qa":
            out[campo["chave"]] = "\n".join(
                f'{h.get("q", "")} | {h.get("a", "")}'.rstrip(" |") for h in (v or []) if isinstance(h, dict))
        elif campo["tipo"] == "par":
            out[campo["chave"]] = "\n".join(
                f'{p.get("a", "")} {campo["simbolo"]} {p.get("b", "")}' for p in (v or []) if isinstance(p, dict))
        elif isinstance(v, list):
            out[campo["chave"]] = "\n".join(str(x) for x in v)
        else:
            out[campo["chave"]] = v or ""
    return out


def _linhas(texto):
    return [ln.strip() for ln in str(texto or "").splitlines() if ln.strip()]


def form_para_conteudo(form):
    """Texto dos campos do editor -> conteúdo; devolve (conteudo, erros)."""
    c, erros = {}, []
    for campo in CAMPOS_CONTEUDO:
        chave, bruto = campo["chave"], form.get(campo["chave"], "")
        linhas = _linhas(bruto)
        if not linhas:
            continue
        if campo["tipo"] == "qa":
            itens = []
            for ln in linhas:
                q, _, a = ln.partition("|")
                itens.append({"q": q.strip(), "a": a.strip()})
            c[chave] = itens
        elif campo["tipo"] == "par":
            itens = []
            for n, ln in enumerate(linhas, 1):
                sep = next((s for s in _SEPARADORES_PAR if s in ln), None)
                a, b = (ln.split(sep, 1) if sep else (ln, ""))
                if not a.strip() or not b.strip():
                    erros.append(f'{campo["rotulo"]}, linha {n}: use “técnica {campo["simbolo"]} técnica”.')
                    continue
                itens.append({"a": a.strip(), "b": b.strip()})
            c[chave] = itens
        elif campo["tipo"] == "texto":
            c[chave] = " ".join(linhas)
        elif campo["tipo"] == "ukemi":
            c[chave] = linhas[0] if len(linhas) == 1 else linhas
        else:
            c[chave] = linhas
    return c, erros


# ---------------------------------------------------------- situação do aluno
def _anos(nasc, ref):
    if not nasc:
        return None
    return ref.year - nasc.year - ((ref.month, ref.day) < (nasc.month, nasc.day))


def _como_data(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return None


def ultima_graduacao(cur, aluno):
    """Data da última graduação: o cadastro ou, na falta, o histórico.

    Listas grandes pré-carregam o histórico em `aluno["_ultima_hist"]` (uma
    consulta para todos) — aí esta função não vai ao banco.
    """
    d = _como_data(aluno.get("ultimo_exame_faixa"))
    if d:
        return d
    if "_ultima_hist" in aluno:
        return _como_data(aluno["_ultima_hist"])
    try:
        cur.execute("SELECT MAX(data) AS d FROM aluno_graduacao WHERE aluno_id = %s", (aluno["id"],))
        return _como_data((cur.fetchone() or {}).get("d"))
    except Exception:
        return None


def ultimas_do_historico(cur, aluno_ids):
    """{aluno_id: data da graduação mais recente em aluno_graduacao}."""
    ids = [int(i) for i in aluno_ids if i]
    if not ids:
        return {}
    ph = ",".join(["%s"] * len(ids))
    try:
        cur.execute(f"SELECT aluno_id, MAX(data) AS d FROM aluno_graduacao "
                    f"WHERE aluno_id IN ({ph}) GROUP BY aluno_id", tuple(ids))
        return {r["aluno_id"]: r["d"] for r in cur.fetchall()}
    except Exception:
        return {}


def mensalidades_em_atraso(cur, aluno_ids, hoje=None):
    """{aluno_id: quantidade de cobranças vencidas e não pagas}.

    Atraso é sempre contado até HOJE. As listas passam a data da prova (que
    vale para idade e carência), mas mensalidade que vence entre hoje e a
    prova ainda não está atrasada — contá-la marcava aluno em dia como devedor.
    """
    ids = [int(i) for i in aluno_ids if i]
    if not ids:
        return {}
    hoje = min(_como_data(hoje) or date.today(), date.today())
    ph = ",".join(["%s"] * len(ids))
    try:
        cur.execute(
            f"""SELECT aluno_id, COUNT(*) AS n FROM mensalidade_aluno
                WHERE aluno_id IN ({ph}) AND data_vencimento < %s
                  AND status IN ('pendente','atrasado')
                  AND status_pagamento NOT IN ('pago','cancelado','pendente_aprovacao')
                GROUP BY aluno_id""",
            tuple(ids) + (hoje,))
        return {r["aluno_id"]: int(r["n"]) for r in cur.fetchall()}
    except Exception:
        return {}


# Salto de faixa por idade (regra da associação). O exame não é sempre para
# a faixa seguinte: a idade pode levar o aluno direto a uma faixa acima.
#   conta "no_dia"  idade completa no dia da prova
#   conta "no_ano"  idade que o aluno completa no ano da prova
# No exame de DEZEMBRO (o último do ano) vale um ano a menos, contado no dia
# da prova: Cinza com 5, Azul com 10, Amarela com 14 anos completos.
REGRAS_SALTO = [
    {"para": "cinza", "idade": 6, "conta": "no_dia", "so_da_branca": True,
     "texto": "Com 6 anos, o primeiro exame é para Cinza",
     "texto_dezembro": "Com 5 anos no exame de dezembro, o primeiro exame é para Cinza"},
    {"para": "azul", "idade": 11, "conta": "no_ano",
     "texto": "Azul no ano em que completa 11 anos",
     "texto_dezembro": "Azul com 10 anos no exame de dezembro"},
    {"para": "amarela", "idade": 15, "conta": "no_ano",
     "texto": "Amarela no ano em que completa 15 anos",
     "texto_dezembro": "Amarela com 14 anos no exame de dezembro"},
]
MOTIVOS_LARANJA = ["Faixa preta de jiu-jitsu", "Formado em Educação Física"]


def inicio_laranja(cur, aluno):
    """Motivo pelo qual o professor liberou o primeiro exame para Laranja, ou None.

    Listas pré-carregam em `aluno["_inicio_laranja"]` (ver marcas_inicio_laranja).
    """
    if "_inicio_laranja" in aluno:
        return aluno["_inicio_laranja"]
    return marcas_inicio_laranja(cur, [aluno.get("id")]).get(aluno.get("id"))


def marcas_inicio_laranja(cur, aluno_ids):
    ids = [int(i) for i in aluno_ids if i]
    if not ids:
        return {}
    ph = ",".join(["%s"] * len(ids))
    try:
        cur.execute(f"SELECT aluno_id, motivo FROM exame_faixa_aluno "
                    f"WHERE inicio_laranja = 1 AND aluno_id IN ({ph})", tuple(ids))
        return {r["aluno_id"]: (r["motivo"] or "Liberado pelo professor") for r in cur.fetchall()}
    except Exception:
        return {}


def destinos_escolhidos(cur, aluno_ids):
    """{aluno_id: {programa_id, de_id, motivo}} — faixa de destino que o professor escolheu."""
    ids = [int(i) for i in aluno_ids if i]
    if not ids:
        return {}
    ph = ",".join(["%s"] * len(ids))
    try:
        cur.execute(f"""SELECT aluno_id, destino_programa_id, destino_de_id, destino_motivo
                        FROM exame_faixa_aluno
                        WHERE destino_programa_id IS NOT NULL AND aluno_id IN ({ph})""", tuple(ids))
        return {r["aluno_id"]: {"programa_id": r["destino_programa_id"], "de_id": r["destino_de_id"],
                                "motivo": r["destino_motivo"]} for r in cur.fetchall()}
    except Exception:
        return {}


def liberacoes(cur, aluno_ids):
    """{aluno_id: {de_id, motivo, por, em}} — alunos que a academia liberou para o exame."""
    ids = [int(i) for i in aluno_ids if i]
    if not ids:
        return {}
    ph = ",".join(["%s"] * len(ids))
    try:
        cur.execute(f"""SELECT aluno_id, liberado_de_id, liberado_motivo, liberado_por, liberado_em
                        FROM exame_faixa_aluno
                        WHERE liberado_de_id IS NOT NULL AND aluno_id IN ({ph})""", tuple(ids))
        return {r["aluno_id"]: {"de_id": r["liberado_de_id"], "motivo": r["liberado_motivo"],
                                "por": r["liberado_por"], "em": r["liberado_em"]} for r in cur.fetchall()}
    except Exception:
        return {}


def liberacao(cur, aluno):
    """Liberação vigente do aluno, ou None. Vale só enquanto ele estiver na faixa
    em que foi liberado. Listas pré-carregam em `aluno["_liberacao"]`."""
    lib = aluno["_liberacao"] if "_liberacao" in aluno else liberacoes(cur, [aluno.get("id")]).get(aluno.get("id"))
    return lib if lib and lib.get("de_id") == aluno.get("graduacao_id") else None


def destino_escolhido(cur, aluno):
    """Escolha do professor para o aluno, ou None. Listas pré-carregam em `aluno["_destino"]`."""
    if "_destino" in aluno:
        return aluno["_destino"]
    return destinos_escolhidos(cur, [aluno.get("id")]).get(aluno.get("id"))


def _indice_para(prog, faixa):
    alvo = _norm(faixa)
    return next((i for i, p in enumerate(prog) if _norm(p["para_faixa"]) == alvo), None)


def regra_de_salto(prog, nat, nasc, ref, laranja=None):
    """(índice da promoção de destino, motivo) quando a regra leva além da
    próxima faixa; None quando o exame é o normal (faixa seguinte)."""
    melhor = None
    dezembro = ref.month == 12
    for r in REGRAS_SALTO:
        if not nasc:
            break
        if r.get("so_da_branca") and _norm(nat["de_faixa"]) != "branca":
            continue
        idade = _anos(nasc, ref) if r["conta"] == "no_dia" else ref.year - nasc.year
        if idade >= r["idade"]:
            motivo = r["texto"]
        elif dezembro and _anos(nasc, ref) >= r["idade"] - 1:
            # Último exame do ano: basta ter um ano a menos no dia da prova —
            # o que conta é a idade civil que ele completa no ano seguinte.
            motivo = (f"Idade civil em {ref.year + 1}: {ref.year + 1 - nasc.year} anos — "
                      f"{nome_faixa(r['para'])} liberada no exame de dezembro (final do ano)")
        else:
            continue
        cand = _indice_para(prog, r["para"])
        if cand is None or cand <= nat["indice"]:
            continue
        if melhor is None or cand > melhor[0]:
            melhor = (cand, motivo)
    if laranja:
        cand = _indice_para(prog, "laranja")
        if cand is not None and cand > nat["indice"] and (melhor is None or cand > melhor[0]):
            melhor = (cand, f"Primeiro exame para Laranja — {laranja}")
    return melhor


# Como cada grupo do conteúdo se junta quando um aluno pula faixas.
_CHAVE_DO_ITEM = {
    "historico": lambda it: _norm(it.get("q") if isinstance(it, dict) else it),
    "kaeshi": lambda it: (_norm(it.get("a")), _norm(it.get("b"))) if isinstance(it, dict) else _norm(it),
    "renraku": lambda it: (_norm(it.get("a")), _norm(it.get("b"))) if isinstance(it, dict) else _norm(it),
}
# Texto de quantidade ("Um tipo", "Dois tipos"): vale o da faixa mais alta,
# que é a mais exigente. Se alguma promoção nomeia os tipos, a lista vence.
_CHAVES_DE_QUANTIDADE = ("ukemi", "kumikata")


def conteudo_composto(prog, i_de, i_ate):
    """Conteúdo somado das promoções de `i_de` até `i_ate`, inclusive.

    Quem pula da branca direto para a azul faz um exame só, mas a prova é de
    tudo que ficou pelo caminho — as três promoções que ele não prestou. O
    conteúdo de uma linha do programa traz só o que é NOVO naquela faixa, então
    mostrar a linha de destino sozinha esconderia justamente o que ele precisa
    estudar.

    A ordem é a do programa: o que se aprende primeiro aparece primeiro.
    """
    if not prog:
        return {}
    i_de = max(0, i_de)
    i_ate = min(len(prog) - 1, i_ate)
    if i_ate < i_de:
        return dict((prog[i_ate].get("conteudo") or {}))
    fora = {}
    vistos = {}
    for p in prog[i_de:i_ate + 1]:
        for chave, valor in (p.get("conteudo") or {}).items():
            if chave in _CHAVES_DE_QUANTIDADE:
                # Lista de nomes vence texto; entre textos, vale o mais recente.
                atual = fora.get(chave)
                if isinstance(valor, list) or not isinstance(atual, list):
                    fora[chave] = valor
                continue
            if not isinstance(valor, list):
                fora[chave] = valor
                continue
            chave_de = _CHAVE_DO_ITEM.get(chave, lambda it: _norm(
                it if not isinstance(it, dict) else it.get("q") or it.get("a")))
            destino = fora.setdefault(chave, [])
            marcados = vistos.setdefault(chave, set())
            for item in valor:
                k = chave_de(item)
                if k in marcados:
                    continue
                marcados.add(k)
                destino.append(item)
    return fora


def promocao_com_salto(prog, nat, salto):
    """Promoção de destino vista a partir da faixa atual do aluno.

    Conteúdo, valor e banco de sorteio são os da faixa de destino (acumulados);
    a faixa de origem e a carência são as da faixa atual.
    """
    p = dict(prog[salto[0]])
    # O conteúdo é o das faixas puladas somado ao da faixa de destino: ele vai
    # prestar um exame só, mas sobre tudo que ficou pelo caminho.
    p["conteudo"] = conteudo_composto(prog, nat["indice"], salto[0])
    p.update(de=nat["de"], de_faixa=nat["de_faixa"], cores_de=nat["cores_de"],
             graduacao_de_id=nat["graduacao_de_id"], carencia_meses=nat.get("carencia_meses"),
             carencia_txt=nat["carencia_txt"], idade_txt=salto[1],
             salto=True, salto_motivo=salto[1], promocao_normal=nat["para"],
             indice_de=nat["indice"],
             faixas_no_salto=[x["para"] for x in prog[nat["indice"]:salto[0] + 1]])
    return p


def promocao_da_inscricao(prog, dados, graduacao_id=None):
    """(promoção, índice) de uma inscrição, respeitando salto de faixa.

    A inscrição guarda `programa_id` (a promoção de DESTINO) e a faixa de
    origem. Inscrições sem programa_id caem na faixa de origem.
    """
    dados = dados or {}
    idx = next((i for i, p in enumerate(prog) if p["id"] == dados.get("programa_id")), None)
    de_id = dados.get("graduacao_de_id") or graduacao_id
    if idx is None:
        idx = next((i for i, p in enumerate(prog) if p["graduacao_de_id"] == de_id), None)
    if idx is None:
        return None, None
    p = prog[idx]
    if de_id and de_id != p["graduacao_de_id"]:
        nat = next((x for x in prog if x["graduacao_de_id"] == de_id), None)
        if nat:
            p = promocao_com_salto(prog, nat, (idx, dados.get("salto") or "Salto de faixa"))
    return p, idx


_MOD_PROGRAMA = {}


def modalidade_do_programa(cur, prog):
    """Modalidade das faixas do programa (hoje, judô — o exame é só de judô)."""
    if not prog:
        return None
    chave = prog[0]["graduacao_de_id"]
    if chave not in _MOD_PROGRAMA:
        cur.execute("SELECT modalidade_id FROM graduacao WHERE id = %s", (chave,))
        _MOD_PROGRAMA[chave] = (cur.fetchone() or {}).get("modalidade_id")
    return _MOD_PROGRAMA[chave]


def usar_faixa_do_programa(cur, aluno, prog):
    """Troca a faixa do aluno pela dele NA modalidade do programa (judô).

    Quem treina judô e jiu-jitsu pode ter a faixa principal de jiu-jitsu; o
    exame não pode usá-la. Aluno sem a modalidade do programa segue como está.
    Listas pré-carregam em `aluno["_faixa_prog"]` (dict da modalidade ou None).
    """
    if aluno.get("_faixa_prog_aplicada"):
        return
    aluno["_faixa_prog_aplicada"] = True
    from utils import graduacao_modalidade as grad_mod
    if "_faixa_prog" in aluno:
        f = aluno["_faixa_prog"]
    else:
        mod = modalidade_do_programa(cur, prog)
        f = grad_mod.faixa_na_modalidade(cur, aluno["id"], mod) if mod and aluno.get("id") else None
    if f is None:
        return   # aluno não tem a modalidade do programa: nada a trocar
    if f.get("graduacao_id") != aluno.get("graduacao_id"):
        aluno["graduacao_id"] = f.get("graduacao_id")
        aluno["faixa"] = f.get("faixa")
        aluno["grau"] = f.get("graduacao")
    # A carência conta da graduação de JUDÔ: a data única do cadastro é a da
    # faixa principal (pode ser a de jiu-jitsu) e o histórico mistura as duas.
    aluno["ultimo_exame_faixa"] = f.get("data_graduacao")
    if not aluno["ultimo_exame_faixa"] and f.get("graduacao_id") and aluno.get("id"):
        cur.execute(
            """SELECT MAX(ag.data) AS d FROM aluno_graduacao ag
               JOIN graduacao g ON g.id = ag.graduacao_id
               WHERE ag.aluno_id = %s AND g.modalidade_id = %s""",
            (aluno["id"], f.get("modalidade_id")))
        aluno["_ultima_hist"] = (cur.fetchone() or {}).get("d")


def situacao(cur, aluno, prog, data_ref=None, atrasos=None):
    """Onde o aluno está em relação ao próximo exame.

    `data_ref` é a data do exame quando há um evento (a idade e a carência são
    conferidas no dia da prova); sem evento, hoje.

    status:
      apto         cumpre idade e carência
      aguardando   falta idade ou carência — `data_elegivel` diz quando
      fora_idade   passou da idade máxima da promoção (só a primeira tem)
      verificar    falta dado no cadastro (nascimento, data da última faixa)
      sem_faixa    aluno sem graduação cadastrada
      sem_programa a faixa atual não tem promoção no programa (preta, outra modalidade)
    """
    usar_faixa_do_programa(cur, aluno, prog)
    ref = _como_data(data_ref) or date.today()
    s = {"promocao": None, "status": "sem_programa", "pendencias": [], "avisos": [],
         "idade": _anos(_como_data(aluno.get("data_nascimento")), ref),
         "data_ref": ref, "data_elegivel": None, "atrasos": 0}
    if atrasos is None:
        atrasos = mensalidades_em_atraso(cur, [aluno.get("id")], ref)
    s["atrasos"] = atrasos.get(aluno.get("id"), 0)
    if s["atrasos"]:
        s["avisos"].append(
            f'{s["atrasos"]} mensalidade{"s" if s["atrasos"] > 1 else ""} em atraso — '
            "o judoca deve estar em dia para o exame")

    if not aluno.get("graduacao_id"):
        s["status"] = "sem_faixa"
        s["pendencias"].append("Faixa atual não cadastrada")
        return s
    nat = next((x for x in prog if x["graduacao_de_id"] == aluno["graduacao_id"]), None)
    if not nat:
        return s
    nasc = _como_data(aluno.get("data_nascimento"))
    salto = regra_de_salto(prog, nat, nasc, ref, inicio_laranja(cur, aluno))
    s["indice_natural"] = nat["indice"]
    s["pela_regra"] = prog[salto[0]]["para"] if salto else nat["para"]
    # Escolha do professor: vale enquanto o aluno estiver na faixa em que foi
    # feita; promovido, a regra volta a decidir o exame seguinte.
    escolha = None
    d = destino_escolhido(cur, aluno)
    if d and d.get("de_id") == aluno["graduacao_id"]:
        idx_e = next((i for i, x in enumerate(prog) if x["id"] == d["programa_id"]), None)
        if idx_e is not None and idx_e >= nat["indice"]:
            escolha = (idx_e, "Escolha do professor" + (f" — {d['motivo']}" if d.get("motivo") else ""))
    if escolha:
        p = dict(nat) if escolha[0] == nat["indice"] else promocao_com_salto(prog, nat, escolha)
        p.update(escolha=True, escolha_motivo=escolha[1])
        salto = escolha
    else:
        p = promocao_com_salto(prog, nat, salto) if salto else nat
    s["promocao"] = p
    s["salto_dezembro"] = bool(salto and not p.get("escolha") and "exame de dezembro" in salto[1])

    datas = []
    acima = False
    if salto:
        # A regra de salto já é uma regra de idade, e a escolha do professor
        # passa por cima dela: não se cobra a idade mínima nem a máxima.
        pass
    else:
        if p.get("idade_minima"):
            if not nasc:
                s["pendencias"].append("Data de nascimento não informada")
            else:
                minima = int(p["idade_minima"])
                d_idade = nasc + relativedelta(years=minima)
                if s["idade"] >= minima:
                    datas.append(d_idade)
                elif ref.month == 12 and d_idade.year <= ref.year + 1:
                    # Exame de dezembro (o último do ano): quem completa a idade
                    # mínima em qualquer dia do ano seguinte já pode fazer.
                    s["idade_dezembro"] = d_idade
                    s["idade_civil_seguinte"] = (ref.year + 1, ref.year + 1 - nasc.year)
                    s["avisos"].append(f"Idade civil em {ref.year + 1}: {ref.year + 1 - nasc.year} anos — "
                                       "liberado no exame de dezembro (final do ano)")
                else:
                    datas.append(d_idade)
                    s["pendencias"].append(f'Idade mínima: {p["idade_minima"]} anos')
        acima = bool(p.get("idade_maxima") and s["idade"] is not None
                     and s["idade"] > int(p["idade_maxima"]))
        if acima:
            s["pendencias"].append(
                f'Acima da faixa etária desta promoção ({p["idade_txt"]}) — a academia define a faixa de destino')

    s["ultima_graduacao"] = ultima_graduacao(cur, aluno)
    if p.get("carencia_meses"):
        if not s["ultima_graduacao"]:
            s["pendencias"].append("Data da última graduação não informada")
        else:
            d_car = s["ultima_graduacao"] + relativedelta(months=int(p["carencia_meses"]))
            s["data_carencia"] = d_car
            datas.append(d_car)
            if ref < d_car:
                s["pendencias"].append(
                    f'Carência de {p["carencia_meses"]} meses na faixa — completa em {d_car:%d/%m/%Y}')

    s["data_elegivel"] = max(datas) if datas else None
    faltou_dado = any("não informada" in x for x in s["pendencias"])
    if acima:
        s["status"] = "fora_idade"
    elif faltou_dado:
        s["status"] = "verificar"
    elif s["pendencias"]:
        s["status"] = "aguardando"
    else:
        s["status"] = "apto"

    # Liberação do responsável da academia: passa por cima de idade e carência
    # (não de cadastro incompleto). A pendência continua visível como aviso.
    lib = liberacao(cur, aluno) if s["status"] in ("aguardando", "fora_idade") else None
    if lib:
        s["liberado"] = lib
        s["avisos"] = [f"Liberado pela academia sem cumprir: {x}" for x in s["pendencias"]] + s["avisos"]
        s["pendencias"] = []
        s["status"] = "apto"
    return s


STATUS_ROTULO = {
    "apto":         ("Apto", "success"),
    "aguardando":   ("Aguardando", "warning"),
    "verificar":    ("Verificar cadastro", "info"),
    "fora_idade":   ("Fora da faixa etária", "danger"),
    "sem_faixa":    ("Sem faixa", "info"),
    "sem_programa": ("Sem exame no programa", "info"),
}


# ------------------------------------------------------------- banca / notas
def sortear(prog, indice, qtds, escopo="cumulativo", rnd=None):
    """Técnicas da banca por grupo.

    cumulativo: metade da faixa em exame + o resto do acumulado, sem repetir
    faixa:      só as técnicas desta promoção
    """
    rnd = rnd or random.Random()
    out = {}
    for g in GRUPOS:
        n = max(0, int(qtds.get(g["chave"]) or 0))
        if not n:
            continue
        atual = itens(prog[indice], g["chave"])
        if escopo == "faixa":
            escolhidos = rnd.sample(atual, min(n, len(atual)))
        else:
            meta = min(len(atual), (n + 1) // 2)
            escolhidos = rnd.sample(atual, meta)
            usados = {rotulo_item(g, x).lower() for x in escolhidos}
            pool = [x for x in itens_acumulados(prog, indice, g["chave"])
                    if rotulo_item(g, x).lower() not in usados]
            rnd.shuffle(pool)
            while len(escolhidos) < n and pool:
                x = pool.pop()
                k = rotulo_item(g, x).lower()
                if k in usados:
                    continue
                usados.add(k)
                escolhidos.append(x)
        if escolhidos:
            out[g["chave"]] = [rotulo_item(g, x) for x in escolhidos]
    return out


def disponiveis(prog, indice, escopo="cumulativo"):
    """Quantas técnicas cada grupo tem para sortear (o máximo do campo)."""
    out = {}
    for g in GRUPOS:
        if escopo == "faixa":
            out[g["chave"]] = len(itens(prog[indice], g["chave"]))
        else:
            out[g["chave"]] = len(itens_acumulados(prog, indice, g["chave"]))
    return out


def _valores(notas, chave):
    out = []
    for v in (notas.get(chave) or {}).values():
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            pass
    return out


def calcular_medias(notas, pesos):
    """Média de cada grupo, de cada parte e a geral ponderada pelas partes.

    A nota da parte é a média de todas as técnicas dela (nage-waza junta
    projeções, kaeshi e renraku). Só entram na geral as partes com nota.
    """
    med, soma_p, soma_mp = {}, 0.0, 0.0
    for g in GRUPOS:
        vals = _valores(notas, g["chave"])
        med[g["chave"]] = round(sum(vals) / len(vals), 2) if vals else None
    partes = {}
    for pt in PARTES:
        vals = [v for gc in pt["grupos"] for v in _valores(notas, gc)]
        if not vals:
            partes[pt["chave"]] = None
            continue
        m = sum(vals) / len(vals)
        partes[pt["chave"]] = round(m, 2)
        p = float(pesos.get(pt["chave"]) or 0)
        soma_p += p
        soma_mp += m * p
    med["partes"] = partes
    med["geral"] = round(soma_mp / soma_p, 2) if soma_p else None
    return med


def linhas_ficha(av):
    """Ficha organizada por parte → grupo → técnica com a nota lançada."""
    out = []
    tecnicas, notas = av.get("tecnicas") or {}, av.get("notas") or {}
    medias = (av.get("medias") or {}).get("partes") or {}
    for pt in PARTES:
        grupos = []
        for gc in pt["grupos"]:
            tec = tecnicas.get(gc) or []
            if tec:
                ng = notas.get(gc) or {}
                grupos.append({"grupo": grupo_por_chave(gc), "itens": [
                    {"i": i, "rotulo": r, "nota": ng.get(r)} for i, r in enumerate(tec)]})
        if grupos:
            out.append({"parte": pt, "grupos": grupos, "media": medias.get(pt["chave"])})
    return out


def carregar_avaliacao(linha):
    """Decodifica os campos JSON de uma linha de exame_faixa_avaliacao."""
    if not linha:
        return None
    for k, padrao in (("pesos", {}), ("tecnicas", {}), ("notas", {}), ("medias", {})):
        linha[k] = _json(linha.get(k), padrao)
    rot, cor = RESULTADOS.get(linha.get("resultado") or "pendente", RESULTADOS["pendente"])
    linha["resultado_rotulo"], linha["resultado_cor"] = rot, cor
    return linha


def nota_fmt(v):
    if v is None:
        return "—"
    return f"{float(v):.1f}".replace(".", ",")


# ================================================== katas, vídeos e documentos
# Sequência oficial do Kodokan. O programa diz em que promoção cada kata é
# cobrado (campo "katas" do conteúdo); a sequência é sempre esta.
KATAS = [
    {"chave": "nage-no-kata", "nome": "Nage-no-kata", "traducao": "formas de projeção",
     "grupos": [
         ("Te-waza", ["Uki-otoshi", "Seoi-nage", "Kata-guruma"]),
         ("Koshi-waza", ["Uki-goshi", "Harai-goshi", "Tsuri-komi-goshi"]),
         ("Ashi-waza", ["Okuri-ashi-harai", "Sasae-tsuri-komi-ashi", "Uchi-mata"]),
         ("Ma-sutemi-waza", ["Tomoe-nage", "Ura-nage", "Sumi-gaeshi"]),
         ("Yoko-sutemi-waza", ["Yoko-gake", "Yoko-guruma", "Uki-waza"]),
     ]},
    {"chave": "katame-no-kata", "nome": "Katame-no-kata", "traducao": "formas de controle no solo",
     "grupos": [
         ("Osaekomi-waza", ["Kesa-gatame", "Kata-gatame", "Kami-shiho-gatame", "Yoko-shiho-gatame",
                            "Kuzure-kami-shiho-gatame"]),
         ("Shime-waza", ["Kata-juji-jime", "Hadaka-jime", "Okuri-eri-jime", "Kata-ha-jime", "Gyaku-juji-jime"]),
         ("Kansetsu-waza", ["Ude-garami", "Ude-hishigi-juji-gatame", "Ude-hishigi-ude-gatame",
                            "Ude-hishigi-hiza-gatame", "Ashi-garami"]),
     ]},
]
GRUPOS_VIDEO = [("nage", "Nage-waza"), ("katame", "Katame-waza"), ("kaeshi", "Kaeshi-waza"),
                ("renraku", "Renraku-henka-waza"), ("kata", "Katas")]
GRUPOS_PAR = {"kaeshi": "×", "renraku": "+"}


def chave_video(nome):
    """Chave do vídeo: o nome normalizado ("O-soto-gari" == "o soto gari")."""
    return _norm(nome)[:120]


def chave_item(grupo, nome):
    """Chave do vídeo de um item: o par de kaeshi/renraku é uma técnica só,
    com vídeo próprio — não herda o vídeo das técnicas que o formam."""
    if grupo in GRUPOS_PAR:
        return chave_video(f"{grupo} {nome}")
    return chave_video(nome)


def nome_par(grupo, a, b):
    return f"{a} {GRUPOS_PAR.get(grupo, '×')} {b}" if b else str(a or "")


def katas_da_promocao(p):
    """(cobrados, complementares): os katas que a promoção cobra e os demais."""
    pedidos = {_norm(x) for x in ((p or {}).get("conteudo") or {}).get("katas") or []}
    cobrados = [k for k in KATAS if _norm(k["nome"]) in pedidos or _norm(k["chave"]) in pedidos]
    return cobrados, [k for k in KATAS if k not in cobrados]


def embed_video(url):
    """Endereço de player embutido para YouTube, Vimeo e Google Drive; None
    para outro site (aí a tela só abre o link numa aba nova)."""
    import re
    u = (url or "").strip()
    m = re.search(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|embed/|live/)|youtu\.be/)([\w-]{6,})", u)
    if m:
        return f"https://www.youtube.com/embed/{m.group(1)}?rel=0"
    m = re.search(r"vimeo\.com/(?:video/)?(\d+)", u)
    if m:
        return f"https://player.vimeo.com/video/{m.group(1)}"
    m = re.search(r"drive\.google\.com/file/d/([\w-]+)", u)
    if m:
        return f"https://drive.google.com/file/d/{m.group(1)}/preview"
    return None


def videos_da_associacao(cur, id_associacao):
    """{chave: {grupo, nome, url, embed, observacao}} — vazio sem a EXF-06."""
    if not id_associacao:
        return {}
    try:
        cur.execute("""SELECT grupo, chave, nome, url, observacao FROM exame_faixa_video
                       WHERE id_associacao = %s""", (id_associacao,))
        return {r["chave"]: dict(r, embed=embed_video(r["url"])) for r in cur.fetchall()}
    except Exception:
        return {}


def documentos_da_associacao(cur, id_associacao, programa_id=None, todos=False):
    """Documentos do programa todo e, se `programa_id`, os daquela promoção."""
    if not id_associacao:
        return []
    try:
        if todos:
            cur.execute("""SELECT * FROM exame_faixa_documento WHERE id_associacao = %s
                           ORDER BY programa_id IS NOT NULL, titulo""", (id_associacao,))
        else:
            cur.execute("""SELECT * FROM exame_faixa_documento
                           WHERE id_associacao = %s AND (programa_id IS NULL OR programa_id = %s)
                           ORDER BY programa_id IS NOT NULL, titulo""", (id_associacao, programa_id))
        return cur.fetchall()
    except Exception:
        return []


def qr_svg(url):
    """QR Code em SVG (data URI) para a apostila impressa abrir o vídeo no celular."""
    if not url:
        return None
    try:
        import base64
        import io
        import qrcode
        import qrcode.image.svg
        img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=1)
        buf = io.BytesIO()
        img.save(buf)
        return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def anotar_videos(tecnicas, videos, com_qr=False):
    """Põe `video` (e, para a apostila, `qr`) em cada parte de técnica."""
    for g in tecnicas:
        for t in g.get("itens", []):
            partes = t.get("partes", [])
            if t.get("sep"):
                # par: um vídeo só, do par inteiro
                grupo = "kaeshi" if t["sep"] == "×" else "renraku"
                nomes = [p.get("nome") for p in partes]
                v = videos.get(chave_item(grupo, nome_par(grupo, nomes[0] if nomes else "", nomes[1] if len(nomes) > 1 else "")))
                t["video"] = v
                t["qr"] = qr_svg(v["url"]) if (com_qr and v) else None
                for parte in partes:
                    parte["video"] = None
                    parte["qr"] = None
                continue
            for parte in partes:
                v = videos.get(chave_video(parte.get("nome")))
                parte["video"] = v
                if com_qr and v:
                    parte["qr"] = qr_svg(v["url"])
            t["video"] = partes[0]["video"] if partes else None
    return tecnicas


def tecnicas_do_programa(prog, grupo):
    """Técnicas de um grupo (nage/katame) em todo o programa, na ordem em que
    aparecem, com as faixas em que entram — inclui as metades dos pares.
    Para kaeshi/renraku, cada par é um item (um vídeo por par)."""
    vistos, out = {}, []
    if grupo in GRUPOS_PAR:
        for p in prog:
            for par in itens(p, grupo):
                if not isinstance(par, dict) or not par.get("a"):
                    continue
                nome = nome_par(grupo, par.get("a"), par.get("b"))
                k = chave_item(grupo, nome)
                if k not in vistos:
                    vistos[k] = {"nome": nome, "chave": k, "faixas": []}
                    out.append(vistos[k])
                if p["para"] not in vistos[k]["faixas"]:
                    vistos[k]["faixas"].append(p["para"])
        return out
    for p in prog:
        nomes = list(itens(p, grupo))
        for par in itens(p, "kaeshi") + itens(p, "renraku"):
            if isinstance(par, dict):
                for nome in (par.get("a"), par.get("b")):
                    if nome and mat.ficha(nome) and (mat.ficha(nome) or {}).get("familia") in (
                            ("te", "koshi", "ashi", "ma", "yoko") if grupo == "nage" else ("osaekomi", "shime", "kansetsu")):
                        nomes.append(nome)
        for nome in nomes:
            if not isinstance(nome, str) or nome.strip().lower() in ("katame-waza", "nage-waza"):
                continue
            k = chave_video(nome)
            if k not in vistos:
                vistos[k] = {"nome": nome, "chave": k, "faixas": []}
                out.append(vistos[k])
            if p["para"] not in vistos[k]["faixas"]:
                vistos[k]["faixas"].append(p["para"])
    return out
