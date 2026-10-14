"""O programa de exame passa a trazer o material de estudo, não só a lista.

A tela do programa dizia "Ukemi-waza: um tipo" e parava aí. Quem treina sabe
de que tipos se fala; quem estuda em casa, não — e o mesmo valia para cada
técnica, que aparecia como um nome japonês sem tradução nem descrição.

Estes testes fixam as duas regras novas:
  * ukemi e kumi-kata viram bloco de material — catálogo inteiro em cima, o
    recorte que a banca cobra embaixo;
  * cada técnica do programa carrega ficha (tradução, família, resumo).

E, principalmente, fixam o que NÃO pode mudar: o conteúdo cobrado, o sorteio
e a contagem de itens novos continuam exatamente como estavam. A camada de
material é consulta, não entra no banco e não entra na prova.

Uso:  PYTHONPATH=. .venv/bin/python tests/test_exame_material.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app                                      # noqa: E402
from config import get_db_connection                     # noqa: E402
from utils import exame_faixa as exf                     # noqa: E402
from utils import exame_faixa_material as mat            # noqa: E402
from tests.test_shell_smoke import USUARIO_POR_MODO, ACADEMIA_TESTE  # noqa: E402

_falhas = []


def checar(nome, condicao, detalhe=""):
    print(("  PASSOU  " if condicao else "  FALHOU  ") + nome
          + (f"  [{detalhe}]" if detalhe and not condicao else ""))
    if not condicao:
        _falhas.append(nome)


def _cliente(modo="academia"):
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["_user_id"] = str(USUARIO_POR_MODO[modo])
        sess["_fresh"] = True
        sess["modo_painel"] = modo
        if modo in ("academia", "professor"):
            sess["academia_gerenciamento_id"] = ACADEMIA_TESTE
    return c


def _programa_do_banco():
    """O programa como está em produção — é dele que a tela monta a página."""
    c = get_db_connection()
    cur = c.cursor(dictionary=True)
    cur.execute("SELECT id_associacao FROM exame_faixa_programa ORDER BY id LIMIT 1")
    linha = cur.fetchone()
    prog = exf.programa(cur, (linha or {}).get("id_associacao")) if linha else []
    cur.close(); c.close()
    return prog


def _nomes_de_tecnica(prog):
    nomes = set()
    for p in prog:
        c = p.get("conteudo") or {}
        for k in ("nage", "katame"):
            nomes.update(c.get(k) or [])
        for k in ("kaeshi", "renraku"):
            for par in c.get(k) or []:
                nomes.add(par.get("a")); nomes.add(par.get("b"))
    return {n for n in nomes if n}


def main():
    print("\nMaterial de estudo do programa de exame\n")
    prog = _programa_do_banco()
    if not prog:
        print("  Sem programa cadastrado — nada a verificar.")
        return 1

    # ------------------------------------------------ cobertura do material
    print("Cobertura: toda técnica do programa tem ficha")
    nomes = _nomes_de_tecnica(prog)
    sem_ficha = sorted(n for n in nomes if not mat.ficha(n))
    checar(f"1. as {len(nomes)} técnicas do programa têm ficha de estudo",
           not sem_ficha, ", ".join(sem_ficha[:6]))
    sem_resumo = sorted(n for n in nomes if not (mat.ficha(n) or {}).get("resumo"))
    checar("2. nenhuma ficha é só o nome — todas descrevem a técnica",
           not sem_resumo, ", ".join(sem_resumo[:6]))
    sem_familia = sorted(n for n in nomes
                         if not mat.familia((mat.ficha(n) or {}).get("familia")))
    checar("3. toda ficha diz a que família a técnica pertence",
           not sem_familia, ", ".join(sem_familia[:6]))
    checar("4. a busca ignora hífen, acento e caixa (academia que escreva diferente)",
           mat.ficha("osoto gari") is mat.ficha("O-soto-gari")
           and mat.ficha("O-soto-gari") is not None)
    checar("5. nome que não existe não quebra: devolve nada",
           mat.ficha("Tecnica-inventada-xyz") is None)

    print("\nToda técnica ensina como se faz, não só o nome")
    sem_passos = sorted(n for n in nomes
                        if not (mat.ficha(n) or {}).get("passos")
                        and (mat.ficha(n) or {}).get("familia") != "grupo")
    checar("5b. todas as técnicas do programa têm passo a passo",
           not sem_passos, ", ".join(sem_passos[:8]))
    curtos = sorted(n for n in nomes
                    if 0 < len((mat.ficha(n) or {}).get("passos") or []) < 3)
    checar("5c. nenhum passo a passo é um passo solto",
           not curtos, ", ".join(curtos[:8]))

    # ------------------------------------------------- ukemi e kumi-kata
    print("\nUkemi e kumi-kata: catálogo em cima, o que se pede embaixo")
    primeira = prog[0]
    conhecimento, tecnicas = exf.blocos_estudo(primeira)
    materiais = {b["titulo"]: b for b in conhecimento if b.get("tipo") == "material"}
    checar("6. a promoção de branca gera os dois blocos de material",
           set(materiais) == {"Ukemi-waza", "Kumi-kata"}, str(sorted(materiais)))
    uk = materiais.get("Ukemi-waza") or {}
    checar("7. o bloco de ukemi traz as quatro quedas, e não só a quantidade",
           len(uk.get("itens") or []) == len(mat.UKEMI) == 4)
    checar("8. o que a banca pede continua aparecendo, à parte do catálogo",
           uk.get("pedido") == "Um tipo", repr(uk.get("pedido")))
    checar("9. cada queda do catálogo tem tradução, resumo e passo a passo",
           all(i.get("traducao") and i.get("resumo") and i.get("passos")
               for i in uk.get("itens") or []))
    km = materiais.get("Kumi-kata") or {}
    checar("10. o bloco de kumi-kata traz as formas de pegada nomeadas",
           len(km.get("itens") or []) >= 8 and any(
               i["nome"] == "Ushiro-obi" for i in km.get("itens") or []))

    # A promoção para a amarela nomeia as quatro quedas uma a uma.
    nomeia = next((p for p in prog if isinstance((p.get("conteudo") or {}).get("ukemi"), list)), None)
    checar("11. existe promoção que nomeia as quedas uma a uma", nomeia is not None)
    if nomeia:
        blocos_n, _ = exf.blocos_estudo(nomeia)
        uk_n = next(b for b in blocos_n if b["titulo"] == "Ukemi-waza")
        exigidos = [i["nome"] for i in uk_n["itens"] if i["exigido"]]
        checar("12. quando o programa nomeia, o catálogo marca quais são",
               sorted(exigidos) == sorted((nomeia["conteudo"] or {})["ukemi"]),
               str(exigidos))
        checar("13. o catálogo continua inteiro mesmo marcando só algumas",
               len(uk_n["itens"]) == len(mat.UKEMI))

    # ------------------------------------------- contagem de "itens novos"
    print("\nA contagem de itens novos não inflou com o catálogo")
    checar("14. 'um tipo' é escolha dentro do catálogo, não item novo a decorar",
           uk.get("n") == 0 and km.get("n") == 0)
    if nomeia:
        checar("15. quando as quedas são nomeadas, elas contam como itens novos",
               uk_n.get("n") == len((nomeia["conteudo"] or {})["ukemi"]))

    # ---------------------------------------------------- pares com ficha
    print("\nKaeshi e renraku: as duas metades são técnicas, e cada uma tem ficha")
    com_par = next((p for p in prog if (p.get("conteudo") or {}).get("kaeshi")), None)
    checar("16. existe promoção com kaeshi-waza", com_par is not None)
    if com_par:
        _, tec_par = exf.blocos_estudo(com_par)
        grupo = next(g for g in tec_par if g["chave"] == "kaeshi")
        linha = grupo["itens"][0]
        checar("17. o par guarda as duas técnicas separadas, não um texto só",
               len(linha["partes"]) == 2 and linha["sep"] == "×")
        checar("18. golpe e contragolpe trazem ficha cada um",
               all(p["ficha"] for p in linha["partes"]),
               str([p["nome"] for p in linha["partes"]]))
        checar("19. o rótulo antigo continua existindo, para quem imprime",
               " × " in linha["rotulo"])

    # ------------------------------------------- o que NÃO pode ter mudado
    print("\nO que a banca cobra e sorteia continua igual")
    p0 = prog[0]
    checar("20. os itens cobrados de nage-waza não mudaram",
           exf.itens(p0, "nage") == (p0["conteudo"] or {}).get("nage"))
    checar("21. o acumulado para o sorteio não mudou de tamanho",
           len(exf.itens_acumulados(prog, len(prog) - 1, "nage")) ==
           len({str(x).lower() for p in prog for x in exf.itens(p, "nage")}))
    sorteio_ok = True
    try:
        exf.blocos_estudo({"conteudo": {}})
    except Exception as e:                                     # noqa: BLE001
        sorteio_ok = False
        print("   ", e)
    checar("22. promoção sem conteúdo nenhum não quebra a tela", sorteio_ok)

    # ------------------------------------------------------------- telas
    print("\nAs telas abrem e mostram o material")
    cli = _cliente("academia")
    r = cli.get("/exame-faixa/programa", follow_redirects=True)
    html = r.get_data(as_text=True)
    checar("23. /exame-faixa/programa responde 200", r.status_code == 200, str(r.status_code))
    checar("24. a seção de fundamentos aparece na página", "Fundamentos" in html)
    checar("25. o catálogo de quedas aparece com os nomes",
           "Ushiro-ukemi" in html and "Zempo-kaiten-ukemi" in html)
    checar("26. as formas de pegada aparecem", "Ushiro-obi" in html and "Naka-sode" in html)
    # A tela do programa virou "apostila" e passa sem_pede=true de propósito:
    # ali o quadro do que cai sai de cena. O bloco em si é checado logo abaixo,
    # direto no trecho que o monta, para o teste não depender de qual tela o usa.
    checar("27. a apostila esconde o quadro do que cai, como foi desenhada",
           "O que a banca pede nesta promoção" not in html)
    checar("28. a ficha da técnica aparece junto do nome",
           "grande ceifada externa" in html)
    checar("29. o passo a passo está na página, recolhido",
           "Como se faz" in html)
    checar("30. nada de Undefined/None vazando no HTML",
           "None" not in html.replace("None</", "") and "Undefined" not in html)

    for p_idx in range(len(prog)):
        rr = cli.get(f"/exame-faixa/programa?p={p_idx}")
        if rr.status_code != 200:
            checar(f"31. promoção {p_idx} abre", False, str(rr.status_code))
            break
    else:
        checar(f"31. todas as {len(prog)} promoções abrem sem erro", True)

    print("\nToda técnica mostra o que o nome quer dizer")
    # Golpe e contragolpe (kaeshi/renraku) eram a única linha que saía só com o
    # nome japonês: a ficha inteira não cabe no par, e no papel ela é escondida.
    # A tradução passa a sair ali, na tela e no papel.
    from flask import render_template
    com_par = next((p for p in prog if (p.get("conteudo") or {}).get("kaeshi")), None)
    if com_par:
        con_p, tec_p = exf.blocos_estudo(com_par)
        with app.app_context():
            html_p = render_template("exame_faixa/_conteudo.html", conhecimento=con_p,
                                     tecnicas=tec_p, quiz=False, atual=com_par)
        pares = [t for g in tec_p for t in g["itens"] if t.get("sep")]
        checar("47. os pares ganham a linha de tradução",
               html_p.count("exf-parl__trad") == len(pares),
               f'{html_p.count("exf-parl__trad")} x {len(pares)}')
        metades = {pt["nome"] for t in pares for pt in t["partes"]}
        faltam = sorted(n for n in metades
                        if (mat.ficha(n) or {}).get("traducao")
                        and (mat.ficha(n) or {})["traducao"] not in html_p)
        checar("48. cada metade do par traz o próprio significado",
               not faltam, ", ".join(faltam[:5]))
        checar("49. a tradução do par não é escondida da impressão",
               "exf-parl__trad" in html_p
               and "exf-nao-imprime" not in html_p.split('exf-parl__trad')[1][:120])

    # E as técnicas soltas (nage/katame) seguem com a ficha completa no papel.
    nomes_cartao = {t["partes"][0]["nome"] for g in tecnicas for t in g["itens"]
                    if not t.get("sep")}
    faltam_c = sorted(n for n in nomes_cartao
                      if (mat.ficha(n) or {}).get("traducao")
                      and (mat.ficha(n) or {})["traducao"] not in html)
    checar("50. técnica solta mostra a tradução no material",
           not faltam_c, ", ".join(faltam_c[:5]))

    print("\nO nome do grupo vem com o que ele quer dizer")
    sem_sig = [g["chave"] for g in exf.GRUPOS if not g.get("significado")]
    checar("42. todo grupo do programa tem significado cadastrado",
           not sem_sig, str(sem_sig))
    checar("43. blocos_estudo leva o significado para a tela",
           all(g.get("significado") for g in tecnicas))
    checar("44. o significado sai ao lado do nome japonês, na tela",
           "Nage-waza<small>técnicas de arremesso" in html
           and "Katame-waza<small>técnicas de controle no solo" in html)
    r_rev = cli.get("/exame-faixa/programa?p=5")
    html_rev = r_rev.get_data(as_text=True)
    checar("45. a revisão das faixas anteriores também traz o significado",
           html_rev.count("exf-grupo__tit") >= 2, str(html_rev.count("exf-grupo__tit")))
    checar("46. a pastilha de contagem não virou parte do título",
           'class="exf-grupo__tit">Nage-waza' in html)

    # ------------------------- material e cobrança deixaram de se misturar
    # O bloco é montado em exame_faixa/_conteudo.html, que hoje serve três
    # telas. Renderizamos o trecho direto: assim o teste cobre a regra (material
    # em cima, lista do que cai embaixo) sem travar em qual tela o mostra.
    print("\nO quadro do que cai: material primeiro, lista limpa por último")
    from flask import render_template
    with app.app_context():
        parcial = render_template("exame_faixa/_conteudo.html",
                                  conhecimento=conhecimento, tecnicas=tecnicas, quiz=False)
        escondido = render_template("exame_faixa/_conteudo.html",
                                    conhecimento=conhecimento, tecnicas=tecnicas,
                                    quiz=False, sem_pede=True)
    pos = {t: parcial.find(t) for t in ("Conhecimento teórico", "Fundamentos",
                                        "Técnicas novas desta faixa",
                                        "O que a banca pede nesta promoção")}
    checar("33. existe o quadro único do que a banca pede",
           pos["O que a banca pede nesta promoção"] > 0, str(pos))
    checar("34. a ordem é conhecimento teórico, fundamentos e depois o que cai",
           pos["Conhecimento teórico"] < pos["Fundamentos"]
           < pos["Técnicas novas desta faixa"] < pos["O que a banca pede nesta promoção"],
           str(pos))
    quadro = parcial[pos["O que a banca pede nesta promoção"]:]
    quadro = quadro[:quadro.find("</section>")]
    checar("35. o quadro é só lista: não repete resumo nem passo a passo",
           "Como se faz" not in quadro and "<details" not in quadro)
    checar("36. o recorte saiu de dentro do bloco de fundamentos",
           'class="exf-pedido"' not in parcial)
    checar("36b. quem pede sem_pede não recebe o quadro",
           "O que a banca pede nesta promoção" not in escondido)
    checar("36c. esconder o quadro não esconde o material de estudo",
           "Ushiro-ukemi" in escondido and "Fundamentos" in escondido)

    print("\nA lista do que cai é a mesma que alimenta o sorteio")
    bloco_pedido = next((b for b in conhecimento if b.get("tipo") == "pedido"), None)
    checar("37. a promoção gera o bloco da lista cobrada", bloco_pedido is not None)
    if bloco_pedido:
        checar("38. a lista é exatamente o banco de teoria do sorteio",
               bloco_pedido["itens"] == exf.itens(primeira, "teoria"),
               str(bloco_pedido["itens"]))
        # O cabeçalho conta os itens de estudo; a lista do fim é a mesma coisa
        # dita de outro jeito e não pode ser somada de novo.
        n_estudo = sum(len(b["itens"]) for b in conhecimento
                       if b.get("tipo") not in ("texto", "material", "pedido"))
        checar("39. a lista do fim não é somada na contagem de itens novos",
               re.search(r">%d iten?s? novo" % n_estudo, parcial) is not None,
               f"esperado {n_estudo}")
    checar("40. o quadro cobre também ukemi, kumi-kata e os grupos de técnica",
           all(t in quadro for t in ("Ukemi-waza", "Kumi-kata", "Nage-waza", "Katame-waza")))
    checar("41. o quadro diz quantos itens de teoria a prova sorteia",
           "sorteados na prova" in quadro)

    r_est = _cliente("aluno").get("/exame-faixa/estudo", follow_redirects=True)
    checar("32. o modo estudo do aluno também abre", r_est.status_code == 200,
           str(r_est.status_code))

    print("\n" + ("TUDO PASSOU" if not _falhas else f"FALHARAM {len(_falhas)}: " + "; ".join(_falhas)))
    return 1 if _falhas else 0


if __name__ == "__main__":
    sys.exit(main())
