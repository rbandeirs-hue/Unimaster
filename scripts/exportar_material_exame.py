#!/usr/bin/env python3
"""
Exporta o material do exame de faixa (kyu) do Unimaster para o CFPGs, faixa
por faixa, para revisão e ajuste do conteúdo.

Fonte de cada parte:
  programa (o que a banca cobra)    banco: exame_faixa_programa (edição em uso)
  fichas das técnicas e quedas      utils/exame_faixa_material.py
  glossário da terminologia         utils/exame_faixa_dados.GLOSSARIO
  regras da banca                   utils/exame_faixa.py (sorteio, partes, pesos, corte)
  vídeos                            banco: exame_faixa_video
  versão do CFPGs (comparação)      /var/www/CFPGs/sistema/public/faixas.js

Gera em /var/www/CFPGs/material-exame-kyu/ (só essa pasta; nada mais no CFPGs
é tocado):
  README.md                          como ler e o que ajustar
  00-fundamentos-ukemi-kumikata.md   as quedas e pegadas (o programa pede "N tipos")
  01-...md a 11-...md                uma promoção por arquivo
  conferencia.md                     divergências com o faixas.js e itens sem material
  programa-2026.1.json               tudo em dados, para reimportar depois

Uso (na raiz do Unimaster):
  .venv/bin/python scripts/exportar_material_exame.py [--associacao 1] [--destino DIR]
"""
import argparse
import json
import subprocess
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402
from utils import exame_faixa as ef  # noqa: E402
from utils import exame_faixa_material as mat  # noqa: E402

FAIXAS_JS = Path("/var/www/CFPGs/sistema/public/faixas.js")
DESTINO = Path("/var/www/CFPGs/material-exame-kyu")

ROTULOS_TEORIA = [
    ("historico", "Conhecimento histórico"),
    ("terminologia", "Terminologia"),
    ("reiho", "Reiho — saudações"),
    ("gestos", "Gestos de arbitragem"),
    ("arbitragem", "Arbitragem"),
]


def norm(txt):
    s = unicodedata.normalize("NFD", str(txt or "")).encode("ascii", "ignore").decode()
    return "".join(c for c in s.lower() if c.isalnum())


def slug(txt):
    s = unicodedata.normalize("NFD", str(txt or "")).encode("ascii", "ignore").decode().lower()
    return "".join(c if c.isalnum() else "-" for c in s).strip("-").replace("--", "-")


def moeda(v):
    return "—" if v is None else f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def lista(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def rotulo_par(chave, it):
    simb = "×" if chave == "kaeshi" else "+"
    return f"{it.get('a')} {simb} {it.get('b')}" if isinstance(it, dict) else str(it)


# ------------------------------------------------------------------ fontes
def carregar_programa(id_associacao):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT p.*, gd.faixa AS de_faixa, gp.faixa AS para_faixa
               FROM exame_faixa_programa p
               LEFT JOIN graduacao gd ON gd.id = p.graduacao_de_id
               LEFT JOIN graduacao gp ON gp.id = p.graduacao_para_id
               WHERE p.id_associacao = %s AND p.ativo = 1
               ORDER BY p.ordem, p.id""", (id_associacao,))
        prog = cur.fetchall()
        for p in prog:
            p["conteudo"] = json.loads(p["conteudo"] or "{}")
        cur.execute("""SELECT grupo, chave, nome, url, observacao FROM exame_faixa_video
                       WHERE id_associacao = %s""", (id_associacao,))
        videos = {norm(v["chave"] or v["nome"]): v for v in cur.fetchall()}
        cur.execute("SELECT nome FROM associacoes WHERE id = %s", (id_associacao,))
        r = cur.fetchone()
        return prog, videos, (r or {}).get("nome") or f"associação {id_associacao}"
    finally:
        conn.close()


def carregar_faixas_js():
    """window.FAIXAS do CFPGs, lido pelo próprio node (é JS, não JSON)."""
    if not FAIXAS_JS.exists():
        return []
    js = ("const vm=require('vm');const fs=require('fs');const c={window:{}};"
          f"vm.runInNewContext(fs.readFileSync({json.dumps(str(FAIXAS_JS))},'utf8'),c);"
          "process.stdout.write(JSON.stringify(c.window.FAIXAS||[]));")
    try:
        saida = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
        return json.loads(saida.stdout or "[]")
    except Exception:
        return []


def ficha_tecnica(nome):
    f = mat.ficha(nome)
    if not f:
        return None
    f = dict(f)
    if not f.get("passos"):
        f["passos"] = mat.PASSOS_NAGE.get(f.get("nome")) or mat.PASSOS_NAGE.get(nome) or []
    return f


# ------------------------------------------------------------------ escrita
def bloco_tecnica(nome, videos, pendencias):
    f = ficha_tecnica(nome)
    v = videos.get(norm(nome))
    out = [f"#### {nome}"]
    if not f:
        out.append("> ⚠️ **Sem ficha de estudo** no Unimaster (sem tradução, família e passos).")
        pendencias.append(f"{nome}: sem ficha de estudo")
    else:
        fam = mat.familia(f.get("familia")) or ""
        cab = [x for x in (f.get("traducao") and f"*{f['traducao']}*", fam, f.get("serie")) if x]
        out.append(" · ".join(cab))
        if f.get("resumo"):
            out.append("")
            out.append(f["resumo"])
        if f.get("passos"):
            out.append("")
            out.append("**Execução**")
            out += [f"{i}. {p}" for i, p in enumerate(f["passos"], 1)]
        else:
            pendencias.append(f"{nome}: ficha sem passo a passo")
    out.append("")
    if v and v.get("url"):
        out.append(f"🎥 Vídeo: {v['url']}" + (f" — {v['observacao']}" if v.get("observacao") else ""))
    else:
        out.append("🎥 Vídeo: *não cadastrado*")
        pendencias.append(f"{nome}: sem vídeo")
    out.append("")
    return out


def comparar(p, js):
    """Diferenças entre a promoção no Unimaster e a do faixas.js."""
    if not js:
        return ["Promoção não existe no faixas.js do CFPGs."]
    c = p["conteudo"]
    dif = []
    if float(p.get("valor") or 0) != float(js.get("valor") or 0):
        dif.append(f"Taxa: Unimaster {moeda(p.get('valor'))} · CFPGs {moeda(js.get('valor'))}")
    for chave in ("historico", "terminologia", "reiho", "gestos", "arbitragem",
                  "nage", "katame", "kaeshi", "renraku"):
        a = lista(c.get(chave))
        b = lista(js.get(chave))
        if chave == "historico":
            a, b = [x.get("q") for x in a], [x.get("q") for x in b]
        elif chave in ("kaeshi", "renraku"):
            a, b = [rotulo_par(chave, x) for x in a], [rotulo_par(chave, x) for x in b]
        sa, sb = {norm(x): x for x in a}, {norm(x): x for x in b}
        so_u = [sa[k] for k in sa if k not in sb]
        so_c = [sb[k] for k in sb if k not in sa]
        if so_u or so_c:
            partes = []
            if so_u:
                partes.append("só no Unimaster: " + "; ".join(so_u))
            if so_c:
                partes.append("só no CFPGs: " + "; ".join(so_c))
            dif.append(f"{chave}: " + " — ".join(partes))
    for chave in ("ukemi", "kumikata"):
        a, b = c.get(chave), js.get(chave)
        if norm(json.dumps(a, ensure_ascii=False)) != norm(json.dumps(b, ensure_ascii=False)):
            dif.append(f"{chave}: Unimaster {a!r} · CFPGs {b!r}")
    return dif


def arquivo_promocao(i, p, prog, videos, js, total_disp):
    c = p["conteudo"]
    titulo = f"{p['de_faixa'].title()} → {p['para_faixa'].title()}"
    pend = []
    L = [f"# {i:02d}. {titulo}", "",
         f"Programa de exame de faixa — edição **{p.get('edicao')}** (Unimaster, em uso). "
         "Promoções são cumulativas: a banca sorteia também técnicas das faixas anteriores.", "",
         "## Requisitos", "",
         "| | Unimaster | CFPGs (faixas.js) |", "|---|---|---|",
         f"| Idade mínima | {ef.texto_idade(p)} | {(js or {}).get('idadeMin', '—')} |",
         f"| Carência na faixa atual | {(str(p['carencia_meses']) + ' meses') if p.get('carencia_meses') else '—'} | {(js or {}).get('carencia', '—')} |",
         f"| Taxa do exame | {moeda(p.get('valor'))} | {moeda((js or {}).get('valor')) if js else '—'} |",
         ""]

    # ---- prova teórica
    L += ["## Prova teórica", ""]
    teve = False
    for chave, nome in ROTULOS_TEORIA:
        itens = lista(c.get(chave))
        if not itens:
            continue
        teve = True
        L.append(f"### {nome}")
        for it in itens:
            if chave == "historico":
                L.append(f"- **{it.get('q')}**  ")
                L.append(f"  {it.get('a') or '⚠️ sem resposta de estudo'}")
                if not it.get("a"):
                    pend.append(f"Histórico sem resposta: {it.get('q')}")
            elif chave in ("terminologia", "reiho", "gestos"):
                sig = ef.glossario(it)
                instrucao = len(str(it).split()) > 3   # "Revisar a terminologia…" não é termo
                if sig:
                    L.append(f"- **{it}** — {sig}")
                elif instrucao:
                    L.append(f"- {it}")
                else:
                    L.append(f"- **{it}** — ⚠️ *sem tradução no glossário*")
                    pend.append(f"{it}: sem tradução no glossário")
            else:
                L.append(f"- {it}")
        L.append("")
    if not teve:
        L += ["*Nada pedido nesta promoção.*", ""]

    # ---- prova prática
    L += ["## Prova prática", ""]
    for chave, nome in (("ukemi", "Ukemi — quedas"), ("kumikata", "Kumi-kata — pegadas")):
        if c.get(chave):
            v = c[chave]
            L.append(f"**{nome}:** {', '.join(v) if isinstance(v, list) else v} "
                     "(ver `00-fundamentos-ukemi-kumikata.md`)")
    L.append("")
    for chave, nome in (("nage", "Nage-waza — projeções"), ("katame", "Katame-waza — solo")):
        itens = lista(c.get(chave))
        L.append(f"### {nome} ({len(itens)})")
        L.append("")
        if not itens:
            L += ["*Nenhuma técnica nova nesta promoção.*", ""]
        for t in itens:
            L += bloco_tecnica(t, videos, pend)
    for chave, nome in (("kaeshi", "Kaeshi-waza — golpe × contragolpe"),
                        ("renraku", "Renraku-henka-waza — 1ª + 2ª técnica")):
        itens = lista(c.get(chave))
        if not itens:
            continue
        L.append(f"### {nome} ({len(itens)})")
        L.append("")
        for it in itens:
            faltam = [x for x in (it.get("a"), it.get("b")) if x and not mat.ficha(x)]
            L.append(f"- {rotulo_par(chave, it)}" + (f"  ⚠️ sem ficha: {', '.join(faltam)}" if faltam else ""))
            for x in faltam:
                pend.append(f"{x} (em {chave}): sem ficha de estudo")
        L.append("")

    # ---- acumulado
    idx = prog.index(p)
    L += ["## Acumulado das faixas anteriores (também pode ser sorteado)", ""]
    for chave, nome in (("nage", "Nage-waza"), ("katame", "Katame-waza"),
                        ("kaeshi", "Kaeshi-waza"), ("renraku", "Renraku-henka-waza")):
        ant = []
        for q in prog[:idx]:
            for it in lista(q["conteudo"].get(chave)):
                r = rotulo_par(chave, it) if isinstance(it, dict) else it
                if norm(r) not in {norm(x) for x in ant}:
                    ant.append(r)
        if ant:
            L.append(f"- **{nome}:** " + "; ".join(ant))
    if idx == 0:
        L.append("- *Primeira promoção: não há acumulado.*")
    L.append("")

    # ---- banca
    disp = total_disp[idx]
    L += ["## Como a banca avalia", "",
          "Sorteio padrão (a banca pode mudar na ficha): metade das técnicas da faixa em exame "
          "e o restante do acumulado, sem repetir.", "",
          "| Grupo | Sorteadas (padrão) | Disponíveis no acumulado |", "|---|---|---|"]
    for g in ef.GRUPOS:
        if g["chave"] == "teoria":
            continue
        L.append(f"| {g['nome']} | {ef.QTD_PADRAO.get(g['chave'], 0)} | {disp.get(g['chave'], 0)} |")
    L += ["", "Partes e notas: " + "; ".join(
        f"**{pt['nome']}** ({pt['sub']}, peso {ef.PESOS_PADRAO.get(pt['chave'], 1)})" for pt in ef.PARTES),
        f"Aprovação com média geral mínima **{str(ef.NOTA_CORTE).replace('.', ',')}**.", ""]

    # ---- conferência
    dif = comparar(p, js)
    L += ["## Pontos para revisar", ""]
    if not dif and not pend:
        L += ["Nada a apontar: igual ao faixas.js e com material completo.", ""]
    for d in dif:
        L.append(f"- 🔀 {d}")
    for d in pend:
        L.append(f"- ⚠️ {d}")
    L.append("")
    nome_arq = f"{i:02d}-{slug(p['de_faixa'])}-para-{slug(p['para_faixa'])}.md"
    return nome_arq, "\n".join(L), dif, pend


def fundamentos():
    L = ["# Fundamentos — Ukemi e Kumi-kata", "",
         "O programa pede \"um tipo\", \"dois tipos\"… de queda e de pegada. Estas são as opções "
         "e como cada uma se faz (Unimaster, `utils/exame_faixa_material.py`).", "",
         "## Ukemi — quedas", "", mat.UKEMI_NOTA, ""]
    for u in mat.UKEMI:
        L += [f"### {u['nome']} — *{u.get('traducao', '')}*", "", u.get("resumo", ""), ""]
        L += [f"{i}. {s}" for i, s in enumerate(u.get("passos") or [], 1)] + [""]
    L += ["## Kumi-kata — pegadas", "", mat.KUMI_KATA_NOTA, ""]
    for k in mat.KUMI_KATA:
        L += [f"### {k['nome']} — *{k.get('traducao', '')}*", "", k.get("resumo", ""), ""]
        L += [f"{i}. {s}" for i, s in enumerate(k.get("passos") or [], 1)] + [""]
    L += ["## Termos usados nas fichas", ""]
    L += [f"- **{t['termo']}** — {t['significado']}" for t in mat.TERMOS_DO_TEXTO]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--associacao", type=int, default=1)
    ap.add_argument("--destino", default=str(DESTINO))
    args = ap.parse_args()
    destino = Path(args.destino)
    destino.mkdir(parents=True, exist_ok=True)

    prog, videos, assoc = carregar_programa(args.associacao)
    if not prog:
        sys.exit("Nenhum programa ativo para essa associação.")
    faixas_js = carregar_faixas_js()
    js_por_par = {(norm(f.get("de")), norm(f.get("para"))): f for f in faixas_js}

    total_disp = []
    for idx in range(len(prog)):
        progx = [{"conteudo": q["conteudo"]} for q in prog]
        total_disp.append(ef.disponiveis(progx, idx))

    arquivos, conf = [], []
    for i, p in enumerate(prog, 1):
        js = js_por_par.get((norm(p["de_faixa"]), norm(p["para_faixa"])))
        nome, texto, dif, pend = arquivo_promocao(i, p, prog, videos, js, total_disp)
        (destino / nome).write_text(texto + "\n", encoding="utf-8")
        arquivos.append((nome, p, len(dif), len(pend)))
        conf.append((nome, p, dif, pend))

    (destino / "00-fundamentos-ukemi-kumikata.md").write_text(fundamentos(), encoding="utf-8")

    # ---- conferência geral
    C = ["# Conferência do material — faixa por faixa", "",
         f"Gerado em {datetime.now():%d/%m/%Y %H:%M} a partir do Unimaster ({assoc}, edição "
         f"{prog[0].get('edicao')}) e comparado com `sistema/public/faixas.js` do CFPGs.", "",
         "🔀 = o Unimaster e o CFPGs dizem coisas diferentes (decidir qual vale).  ",
         "⚠️ = falta material no Unimaster (ficha, tradução, vídeo ou resposta).", "",
         "| Promoção | 🔀 Divergências | ⚠️ Faltas |", "|---|---|---|"]
    for nome, p, dif, pend in conf:
        C.append(f"| [{p['de_faixa'].title()} → {p['para_faixa'].title()}]({nome}) | {len(dif)} | {len(pend)} |")
    C.append("")
    for nome, p, dif, pend in conf:
        if not dif and not pend:
            continue
        C += [f"## {p['de_faixa'].title()} → {p['para_faixa'].title()}", ""]
        C += [f"- 🔀 {d}" for d in dif] + [f"- ⚠️ {d}" for d in pend] + [""]
    sem_par = [f for f in faixas_js
               if not any(norm(f.get("de")) == norm(p["de_faixa"]) and norm(f.get("para")) == norm(p["para_faixa"])
                          for p in prog)]
    if sem_par:
        C += ["## Promoções que só existem no faixas.js", ""]
        C += [f"- {f.get('de')} → {f.get('para')}" for f in sem_par] + [""]
    (destino / "conferencia.md").write_text("\n".join(C), encoding="utf-8")

    # ---- dados
    dados = {
        "fonte": "Unimaster — exame_faixa_programa", "associacao": assoc,
        "edicao": prog[0].get("edicao"), "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "regras_banca": {"nota_corte": ef.NOTA_CORTE, "sorteio_padrao": ef.QTD_PADRAO,
                         "partes": ef.PARTES, "pesos": ef.PESOS_PADRAO},
        "promocoes": [{
            "ordem": p["ordem"], "de": p["de_faixa"], "para": p["para_faixa"],
            "idade_minima": p.get("idade_minima"), "idade_maxima": p.get("idade_maxima"),
            "carencia_meses": p.get("carencia_meses"),
            "valor": float(p["valor"]) if p.get("valor") is not None else None,
            "conteudo": p["conteudo"],
        } for p in prog],
        "fichas": {n: ficha_tecnica(n) for n in sorted(mat.TECNICAS)},
        "ukemi": mat.UKEMI, "kumikata": mat.KUMI_KATA,
        "glossario": __import__("utils.exame_faixa_dados", fromlist=["GLOSSARIO"]).GLOSSARIO,
        "videos": {v["nome"]: v["url"] for v in videos.values()},
    }
    (destino / f"programa-{prog[0].get('edicao')}.json").write_text(
        json.dumps(dados, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    # ---- README
    R = ["# Material do exame de faixa (kyu) — para revisão", "",
         f"Exportado do Unimaster em {datetime.now():%d/%m/%Y %H:%M} ({assoc}, edição {prog[0].get('edicao')}). "
         "É uma **cópia para revisar**: editar estes arquivos não muda o sistema. Depois de revisado, "
         "o conteúdo volta ao Unimaster pela tela *Exame de faixa › Programa* (ou reimportando o JSON).", "",
         "## Arquivos", "",
         "- `conferencia.md` — **comece por aqui**: o que diverge do `faixas.js` do CFPGs e o que falta de material.",
         "- `00-fundamentos-ukemi-kumikata.md` — as quedas e pegadas, e os termos usados nas fichas.",
         ""]
    for nome, p, nd, np_ in arquivos:
        R.append(f"- `{nome}` — {p['de_faixa'].title()} → {p['para_faixa'].title()}"
                 + (f" · 🔀 {nd}" if nd else "") + (f" · ⚠️ {np_}" if np_ else ""))
    R += ["", f"- `programa-{prog[0].get('edicao')}.json` — tudo em dados (programa, fichas, glossário, vídeos, regras).", "",
          "## O que cada arquivo de faixa traz", "",
          "1. **Requisitos** — idade, carência e taxa, lado a lado com o CFPGs.",
          "2. **Prova teórica** — perguntas com a resposta de estudo, terminologia com tradução, saudações, arbitragem.",
          "3. **Prova prática** — quedas, pegadas e cada técnica com tradução, família, série do Go-kyo, "
          "resumo, passo a passo e vídeo; kaeshi e renraku.",
          "4. **Acumulado** — o que vem das faixas anteriores e pode ser sorteado.",
          "5. **Como a banca avalia** — sorteio, partes, pesos e nota de corte.",
          "6. **Pontos para revisar** — divergências e faltas daquela faixa.", "",
          "Para gerar de novo (no servidor): "
          "`cd /var/www/Unimaster && .venv/bin/python scripts/exportar_material_exame.py`", ""]
    (destino / "README.md").write_text("\n".join(R), encoding="utf-8")

    print(f"{len(arquivos)} promoções exportadas em {destino}")
    for nome, p, nd, np_ in arquivos:
        print(f"  {nome}: {nd} divergência(s), {np_} falta(s)")


if __name__ == "__main__":
    main()
