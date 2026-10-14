"""Quem salta faixa estuda tudo o que ficou pelo caminho.

O programa guarda, em cada linha, só o que é NOVO naquela promoção. Quem vai
da branca direto para a azul presta um exame só, mas sobre as quatro
promoções do intervalo — e a tela mostrava apenas a linha de destino. O aluno
via "Seoi-nage, Kami-shiho-gatame" e não via o-soto-gari, o-goshi,
hon-kesa-gatame: justamente o que ele nunca prestou.

Agora `promocao_com_salto` compõe o conteúdo do intervalo inteiro. Estes
testes fixam a composição e, principalmente, o que NÃO pode mudar: quem não
salta continua vendo só a faixa dele.

Uso:  PYTHONPATH=. .venv/bin/python tests/test_exame_salto.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app                                      # noqa: E402
from config import get_db_connection                     # noqa: E402
from utils import exame_faixa as exf                     # noqa: E402

_falhas = []


def checar(nome, condicao, detalhe=""):
    print(("  PASSOU  " if condicao else "  FALHOU  ") + nome
          + (f"  [{detalhe}]" if detalhe and not condicao else ""))
    if not condicao:
        _falhas.append(nome)


def _programa():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id_associacao FROM exame_faixa_programa ORDER BY id LIMIT 1")
        linha = cur.fetchone()
        return exf.programa(cur, (linha or {}).get("id_associacao")) if linha else []
    finally:
        cur.close()
        conn.close()


def _tecnicas(conteudo, chave):
    return [str(x) for x in (conteudo or {}).get(chave) or []]


def main():
    print("\nSalto de faixa: o material soma as promoções puladas\n")
    prog = _programa()
    if len(prog) < 4:
        print("  Programa curto demais para testar salto.")
        return 1

    destino = 3                     # branca → azul, no programa 2026.1
    salto = exf.promocao_com_salto(prog, prog[0], (destino, "Azul aos 11 anos"))

    print("A composição")
    checar("1. a promoção sai da faixa do aluno e vai ao destino",
           salto["de"] == prog[0]["de"] and salto["para"] == prog[destino]["para"],
           f'{salto["de"]} → {salto["para"]}')
    checar("2. guarda de onde o salto começou, para a revisão saber onde parar",
           salto.get("indice_de") == 0, str(salto.get("indice_de")))
    checar("3. lista as faixas que o exame cobre",
           salto.get("faixas_no_salto") == [p["para"] for p in prog[0:destino + 1]],
           str(salto.get("faixas_no_salto")))

    print("\nNada do caminho fica de fora")
    for chave in ("nage", "katame", "terminologia", "historico"):
        esperado = []
        for p in prog[0:destino + 1]:
            for it in (p.get("conteudo") or {}).get(chave) or []:
                k = it.get("q") if isinstance(it, dict) else it
                if k not in esperado:
                    esperado.append(k)
        obtido = [it.get("q") if isinstance(it, dict) else it
                  for it in (salto["conteudo"].get(chave) or [])]
        checar(f"4.{chave}. o salto traz todos os itens de {chave} do intervalo",
               obtido == esperado, f"{len(obtido)} x {len(esperado)}")

    checar("5. o material cresceu de verdade em relação só ao destino",
           len(_tecnicas(salto["conteudo"], "nage"))
           > len(_tecnicas(prog[destino]["conteudo"], "nage")),
           f'{len(_tecnicas(salto["conteudo"], "nage"))} x '
           f'{len(_tecnicas(prog[destino]["conteudo"], "nage"))}')
    for chave in ("nage", "katame", "terminologia"):
        itens = _tecnicas(salto["conteudo"], chave)
        checar(f"6.{chave}. nada repetido em {chave}", len(itens) == len(set(itens)),
               str([x for x in itens if itens.count(x) > 1][:4]))

    print("\nUkemi e kumi-kata: vale a exigência da faixa mais alta")
    checar("7. a quantidade é a do destino, não a da faixa de origem",
           salto["conteudo"].get("ukemi") == prog[destino]["conteudo"].get("ukemi"),
           f'{salto["conteudo"].get("ukemi")!r} x {prog[destino]["conteudo"].get("ukemi")!r}')
    # Quando alguma promoção do intervalo NOMEIA as quedas, a lista vence o texto.
    i_lista = next((i for i, p in enumerate(prog)
                    if isinstance((p.get("conteudo") or {}).get("ukemi"), list)), None)
    if i_lista is not None and i_lista > 0:
        composto = exf.conteudo_composto(prog, 0, i_lista)
        checar("8. lista de quedas nomeadas vence o texto de quantidade",
               isinstance(composto.get("ukemi"), list), repr(composto.get("ukemi")))

    print("\nQuem não salta não vê diferença")
    # A composição não pode escrever no programa: as linhas são compartilhadas
    # entre os alunos da mesma tela, e um salto contaminaria os outros.
    import copy
    antes = copy.deepcopy([p.get("conteudo") for p in prog])
    exf.promocao_com_salto(prog, prog[0], (destino, "x"))
    exf.promocao_com_salto(prog, prog[1], (4, "y"))
    depois = [p.get("conteudo") for p in prog]
    checar("9. compor um salto não altera as linhas do programa", antes == depois,
           str([i for i, (a, d) in enumerate(zip(antes, depois)) if a != d]))
    checar("10. composto de uma faixa só é a própria faixa",
           exf.conteudo_composto(prog, 2, 2) == (prog[2].get("conteudo") or {}))
    checar("11. intervalo invertido não quebra",
           isinstance(exf.conteudo_composto(prog, 3, 1), dict))
    checar("12. programa vazio não quebra", exf.conteudo_composto([], 0, 0) == {})

    print("\nO sorteio continua cobrindo o que o material mostra")
    banco = {exf.rotulo_item(exf.grupo_por_chave("nage"), x).lower()
             for x in exf.itens_acumulados(prog, destino, "nage")}
    do_material = {x.lower() for x in _tecnicas(salto["conteudo"], "nage")}
    checar("13. tudo que o material mostra está no banco de sorteio",
           do_material <= banco, str(sorted(do_material - banco)[:5]))

    print("\nA tela avisa que é salto")
    from flask import render_template
    con_s, tec_s = exf.blocos_estudo(salto)
    con_n, tec_n = exf.blocos_estudo(prog[destino])
    with app.app_context():
        html_s = render_template("exame_faixa/_conteudo.html", conhecimento=con_s,
                                 tecnicas=tec_s, quiz=False, atual=salto)
        html_n = render_template("exame_faixa/_conteudo.html", conhecimento=con_n,
                                 tecnicas=tec_n, quiz=False, atual=prog[destino])
    checar("14. com salto, o aviso aparece", "Salto de faixa" in html_s)
    checar("15. o aviso nomeia as faixas cobertas",
           all(f in html_s for f in salto["faixas_no_salto"]))
    checar("16. sem salto, nenhum aviso", "exf-salto" not in html_n)
    checar("17. sem salto o rótulo continua 'nesta faixa'",
           "novos nesta faixa" in html_n or "novo nesta faixa" in html_n)
    checar("18. com salto o rótulo não diz 'nesta faixa'",
           "nesta faixa" not in html_s)
    checar("19. as técnicas das faixas puladas aparecem na tela",
           all(t in html_s for t in _tecnicas(prog[0]["conteudo"], "nage")),
           str(_tecnicas(prog[0]["conteudo"], "nage")))

    print("\nA banca imprime o material dos alunos do exame")
    from tests.test_shell_smoke import USUARIO_POR_MODO
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""SELECT id, exame_academia_id FROM eventos_competicoes
                       WHERE exame_faixa = 1 AND exame_academia_id IS NOT NULL
                       ORDER BY id DESC LIMIT 1""")
        ev = cur.fetchone()
    finally:
        cur.close()
        conn.close()
    checar("20. existe exame de academia para testar", ev is not None)
    if ev:
        cli = app.test_client()
        with cli.session_transaction() as sess:
            sess["_user_id"] = str(USUARIO_POR_MODO["admin"])
            sess["_fresh"] = True
            sess["modo_painel"] = "admin"
            sess["academia_gerenciamento_id"] = ev["exame_academia_id"]
        base = f"?academia_id={ev['exame_academia_id']}"
        r_b = cli.get(f"/exame-faixa/evento/{ev['id']}/banca{base}", follow_redirects=True)
        hb = r_b.get_data(as_text=True)
        checar("21. a banca abre", r_b.status_code == 200, str(r_b.status_code))
        checar("22. a banca tem o botão de imprimir material", "Imprimir material" in hb)
        checar("23. o diálogo lista os alunos do exame",
               'id="exf-apostila"' in hb and hb.count('name="aluno_id"') > 0)
        r_a = cli.get(f"/exame-faixa/evento/{ev['id']}/apostilas{base}")
        ha = r_a.get_data(as_text=True)
        checar("24. a rota de apostilas do exame responde 200",
               r_a.status_code == 200, str(r_a.status_code))
        # Antes, a impressão só considerava inscritos: com a inscrição ainda não
        # feita (ou cancelada), saía uma página em branco.
        n_folhas = ha.count('class="exf-so-papel exf-apostila-folha"')
        checar("25. sai material mesmo sem inscrição confirmada", n_folhas > 0,
               f"{n_folhas} folhas")
        checar("26. quem salta leva o aviso na própria apostila",
               ("Salto de faixa" in ha) == (hb.count('lst-tag">salto<') > 0),
               f'avisos={ha.count("Salto de faixa")} na lista={hb.count(chr(62) + "salto" + chr(60))}')
        # Filtrar por aluno reduz a impressão.
        import re as _re
        ids = _re.findall(r'name="aluno_id" value="(\d+)"', hb)
        if ids:
            r_f = cli.get(f"/exame-faixa/evento/{ev['id']}/apostilas{base}&aluno_id={ids[0]}")
            n_um = r_f.get_data(as_text=True).count('class="exf-so-papel exf-apostila-folha"')
            checar("27. filtrar por aluno imprime só aquele aluno", n_um == 1, f"{n_um} folhas")

    print("\n" + ("TUDO PASSOU" if not _falhas else f"FALHARAM {len(_falhas)}: " + "; ".join(_falhas)))
    return 1 if _falhas else 0


if __name__ == "__main__":
    sys.exit(main())
