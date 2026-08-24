# -*- coding: utf-8 -*-
"""Troca a base das telas: base.html -> base_app.html (menu lateral).

A parte mecânica da migração é uma linha por tela. Ela é segura porque o
`base_app.html` só desenha o cabeçalho do shell quando a tela declara
`pagina_titulo`/`pagina_subtitulo`/`pagina_acoes` — então a tela que ainda
tem o próprio <h1> dentro de `content` não fica com título duplicado nem com
um cabeçalho vazio abrindo buraco no topo.

O que este script NÃO faz, de propósito: subir o <h1> da tela para
`pagina_titulo`. Isso é decisão de layout, varia caso a caso (o título vive
embrulhado em divs, ao lado de botões) e erraria mais do que acertaria. Fica
para a passada de refino, tela a tela.

Uso:
    python scripts/migrar_shell.py --listar
    python scripts/migrar_shell.py --onda 1 [--aplicar]
    python scripts/migrar_shell.py --arquivo templates/x.html --aplicar
"""

import argparse
import io
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(RAIZ, "templates")

VELHO = '{% extends "base.html" %}'
NOVO = '{% extends "base_app.html" %}'

# Telas públicas ou de impressão: continuam SEM menu lateral. Quem abre estas
# páginas não está navegando no sistema — é um atleta, um responsável, um
# interessado, ou é papel saindo na impressora.
FORA = {
    "index.html",
    "login.html",
    "primeiro_usuario.html",
    "ata_presenca.html",
    "historico_parcial.html",
}
PREFIXOS_FORA = ("externo/", "precadastro/form_publico", "precadastro/matricula_publica",
                 "precadastro/aula_experimental_publica", "auth/")

# Ondas, por área. A ordem sai do plano: academia primeiro (o menu já está
# validado), depois os modos de uma pessoa só, depois os de gestão.
ONDAS = {
    1: ("Modo academia", ("financeiro/", "eventos_competicoes/", "competicoes/", "academia/",
                          "presencas/", "turmas/", "alunos/", "calendario/", "solicitacoes/",
                          "professores/", "academias/", "configuracoes/", "precadastro/")),
    2: ("Aluno, responsável e visitante", ("painel_aluno/", "painel_responsavel/", "visitante/")),
    3: ("Admin, federação e associação", ("painel/", "federacoes/", "associacoes/", "associacao/",
                                          "usuarios/", "formularios/", "cadastros/", "categorias/",
                                          "graduacoes/")),
    4: ("Zempo e avulsas", ("zempo/", "dashboard.html", "turma.html", "registro_presenca.html")),
}


def _rel(caminho):
    return os.path.relpath(caminho, TEMPLATES).replace(os.sep, "/")


def candidatos():
    """Telas que ainda estendem base.html e podem receber o menu lateral."""
    fora = []
    dentro = []
    for raiz, _, arqs in os.walk(TEMPLATES):
        for a in sorted(arqs):
            if not a.endswith(".html"):
                continue
            caminho = os.path.join(raiz, a)
            rel = _rel(caminho)
            if VELHO not in io.open(caminho, encoding="utf-8").read():
                continue
            if rel in FORA or rel.startswith(PREFIXOS_FORA):
                fora.append(rel)
            else:
                dentro.append(rel)
    return dentro, fora


def da_onda(rels, onda):
    _, prefixos = ONDAS[onda]
    return [r for r in rels if r.startswith(prefixos)]


def migrar(rel, aplicar):
    caminho = os.path.join(TEMPLATES, rel)
    s = io.open(caminho, encoding="utf-8").read()
    if s.count(VELHO) != 1:
        return "PULADO (extends não é único)"
    if aplicar:
        io.open(caminho, "w", encoding="utf-8").write(s.replace(VELHO, NOVO))
    return "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--onda", type=int, choices=sorted(ONDAS))
    ap.add_argument("--arquivo")
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--aplicar", action="store_true")
    args = ap.parse_args()

    dentro, fora = candidatos()

    if args.listar:
        print("Telas em base.html que recebem o menu: %d" % len(dentro))
        for o in sorted(ONDAS):
            nome, _ = ONDAS[o]
            itens = da_onda(dentro, o)
            print("  onda %d — %-34s %3d telas" % (o, nome, len(itens)))
        resto = [r for r in dentro if not any(r in da_onda(dentro, o) for o in ONDAS)]
        if resto:
            print("  sem onda atribuída: %d" % len(resto))
            for r in resto:
                print("     ", r)
        print("Ficam sem menu (públicas/impressão): %d" % len(fora))
        for r in fora:
            print("     ", r)
        return 0

    alvos = [args.arquivo.replace("templates/", "")] if args.arquivo else da_onda(dentro, args.onda)
    if not alvos:
        print("nada a fazer")
        return 0
    for rel in alvos:
        print("%-60s %s" % (rel, migrar(rel, args.aplicar)))
    print("\n%d tela(s) %s" % (len(alvos), "migradas" if args.aplicar else "seriam migradas (use --aplicar)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
