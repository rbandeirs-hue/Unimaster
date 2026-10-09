"""Promover pré-cadastro parava com erro de banco quando um campo era longo.

    Erro ao promover: 1406 (22001): Data too long for column 'numero' at row 1

O formulário público grava em `pre_cadastro`, com campos largos; a promoção
copia para `alunos`, com campos estreitos. Quem escreveu "138 Apto 301" no
número da casa passou pelo formulário e travou na promoção — e a tela devolvia
o erro cru do MySQL, sem dizer qual campo encurtar.

Estes testes fixam as duas correções:
  * nenhuma coluna de `alunos` (ou de `usuarios`) pode ser mais estreita que a
    de onde o dado vem — é a regressão que importa, porque fecha a armadilha
    inteira e não só o campo `numero`;
  * se ainda assim estourar, a mensagem diz o campo em português.

O ensaio de gravação roda dentro de uma transação com ROLLBACK: nada é criado
em produção.

Uso:  PYTHONPATH=. .venv/bin/python tests/test_precadastro_promover.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app                                             # noqa: E402
from config import get_db_connection                            # noqa: E402
from blueprints.precadastro.routes import _erro_legivel         # noqa: E402
from tests.test_shell_smoke import USUARIO_POR_MODO             # noqa: E402

_falhas = []


def checar(nome, condicao, detalhe=""):
    print(("  PASSOU  " if condicao else "  FALHOU  ") + nome
          + (f"  [{detalhe}]" if detalhe and not condicao else ""))
    if not condicao:
        _falhas.append(nome)


def _larguras(cur, tabela):
    """Colunas de texto livre e quanto cabe em cada uma.

    ENUM e SET ficam de fora de propósito: ali o limite é a lista de valores
    permitidos, uma restrição desejada, e não um campo apertado por descuido.
    """
    cur.execute("""SELECT COLUMN_NAME c, CHARACTER_MAXIMUM_LENGTH n
                   FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                     AND DATA_TYPE IN ('varchar', 'char', 'text', 'tinytext',
                                       'mediumtext', 'longtext')""", (tabela,))
    return {r["c"]: r["n"] for r in cur.fetchall()}


def main():
    print("\nPromover pré-cadastro: o que vem do formulário cabe no aluno\n")
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        pre = _larguras(cur, "pre_cadastro")
        alu = _larguras(cur, "alunos")
        usu = _larguras(cur, "usuarios")

        # ------------------------------------------------- a regressão central
        print("Largura das colunas: o destino não pode ser mais estreito que a origem")
        apertadas = sorted((c, pre[c], alu[c]) for c in pre if c in alu and alu[c] < pre[c])
        checar("1. nenhuma coluna de alunos é mais estreita que a de pre_cadastro",
               not apertadas,
               "; ".join(f"{c}: pre {a} > aluno {b}" for c, a, b in apertadas))
        checar("2. 'numero' cabe o que o formulário aceita — o campo que quebrou",
               alu.get("numero", 0) >= pre.get("numero", 0),
               f"aluno {alu.get('numero')} < pre {pre.get('numero')}")
        # O login é criado com o nome e o e-mail que vieram do pré-cadastro.
        for campo, origem in (("nome", "responsavel_financeiro_nome"), ("email", "email")):
            checar(f"3.{campo}. usuarios.{campo} cabe o {origem} do pré-cadastro",
                   usu.get(campo, 0) >= pre.get(origem, 0),
                   f"usuario {usu.get(campo)} < pre {pre.get(origem)}")

        # `tipo_aluno` é enum nos alunos e varchar no pré-cadastro. Isso só não é
        # problema porque a promoção não copia essa coluna e ninguém a preenche
        # — se um dia passar a usar, este teste avisa antes de quebrar em
        # produção com "Data truncated for column 'tipo_aluno'".
        cur.execute("SELECT COUNT(*) n FROM pre_cadastro WHERE tipo_aluno IS NOT NULL")
        usados = cur.fetchone()["n"]
        checar("4. tipo_aluno segue sem uso (é enum no aluno e texto no pré-cadastro)",
               usados == 0, f"{usados} pré-cadastro(s) preenchem tipo_aluno")

        # --------------------------------------- ensaio de gravação, com rollback
        print("\nEnsaio: gravar um aluno com cada campo no limite do formulário")
        campos = [c for c in pre if c in alu and c not in ("id", "foto")]
        dados = {}
        for c in campos:
            cur.execute("""SELECT DATA_TYPE d FROM information_schema.COLUMNS
                           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME='alunos'
                             AND COLUMN_NAME = %s""", (c,))
            if (cur.fetchone() or {}).get("d") in ("varchar", "char"):
                dados[c] = "x" * pre[c]
        # nome é único junto com a data de nascimento: um nome que ninguém tem.
        dados["nome"] = ("ENSAIO PC-01 " + "x" * (pre["nome"] - 13))[: pre["nome"]]
        dados.pop("cpf", None)          # cpf é único; fora do ensaio
        dados.pop("estado", None)       # char(2) nos dois lados, nada a provar
        colunas = ", ".join(f"`{c}`" for c in dados)
        marcas = ", ".join(["%s"] * len(dados))
        erro = None
        try:
            cur.execute(f"INSERT INTO alunos ({colunas}) VALUES ({marcas})",
                        list(dados.values()))
        except Exception as e:                                        # noqa: BLE001
            erro = e
        finally:
            conn.rollback()
        checar(f"5. aluno com os {len(dados)} campos no limite do formulário grava",
               erro is None, str(erro))
        cur.execute("SELECT COUNT(*) n FROM alunos WHERE nome LIKE 'ENSAIO PC-01%'")
        checar("6. o ensaio não deixou nada em produção", cur.fetchone()["n"] == 0)

        # ------------------------------------------------- mensagem de erro
        print("\nO erro fala português e aponta o campo")
        m = _erro_legivel(Exception("1406 (22001): Data too long for column 'numero' at row 1"))
        checar("7. 'Data too long' vira o nome do campo na tela",
               "Número" in m and "longo demais" in m, m)
        checar("8. a mensagem não despeja o erro do MySQL",
               "1406" not in m and "Data too long" not in m, m)
        m2 = _erro_legivel(Exception("1406 (22001): Data too long for column 'responsavel_financeiro_nome' at row 1"))
        checar("9. campo de nome composto também tem rótulo",
               "Nome do responsável financeiro" in m2, m2)
        m3 = _erro_legivel(Exception("1062 (23000): Duplicate entry '05825969470' for key 'cpf'"))
        checar("10. CPF duplicado vira explicação, não código de erro",
               "CPF 05825969470 já está cadastrado" in m3, m3)
        m4 = _erro_legivel(Exception("algo totalmente inesperado"))
        checar("11. erro sem padrão conhecido continua aparecendo inteiro",
               "algo totalmente inesperado" in m4, m4)

        # --------------------------------------------- o caso que foi relatado
        print("\nO pré-cadastro que estava travado")
        cur.execute("""SELECT id, nome, numero FROM pre_cadastro
                       WHERE numero IS NOT NULL AND CHAR_LENGTH(numero) > %s""",
                    (alu.get("numero", 0),))
        travados = cur.fetchall()
        checar("12. nenhum pré-cadastro continua grande demais para virar aluno",
               not travados, str([(r["id"], r["numero"]) for r in travados]))
    finally:
        cur.close()
        conn.close()

    print("\nO formulário público tem onde pôr o complemento")
    # Era a origem do caso: sem campo de complemento, o apartamento ia para o
    # número da casa ("138 Apto 301") e estourava a coluna na promoção.
    import re as _re
    fonte = (ROOT / "blueprints" / "precadastro" / "routes.py").read_text(encoding="utf-8")
    bloco = _re.search(r'"""INSERT INTO pre_cadastro\s*\((.*?)\)\s*VALUES \((.*?)\)"""',
                       fonte, _re.S)
    checar("14. a matrícula pública grava o complemento", bool(bloco) and
           "complemento" in _re.sub(r"\s+", " ", bloco.group(1)))
    if bloco:
        colunas = [c.strip() for c in _re.sub(r"\s+", " ", bloco.group(1)).split(",") if c.strip()]
        # 'origem' entra como literal no VALUES, por isso um placeholder a menos.
        checar("15. o INSERT tem placeholder para cada coluna",
               len(colunas) == bloco.group(2).count("%s") + 1,
               f"{len(colunas)} colunas x {bloco.group(2).count('%s')} placeholders")
    tpl = (ROOT / "templates" / "precadastro" / "matricula_publica.html").read_text(encoding="utf-8")
    checar("16. o formulário tem o campo Complemento", 'name="complemento"' in tpl)
    checar("17. o campo Número avisa que é só o número", "Só o número" in tpl)
    checar("18. o campo Número tem limite, para não virar endereço inteiro",
           _re.search(r'id="numero"[^>]*maxlength="\d+"', tpl) is not None)

    print("\nA tela de promover abre")
    cli = app.test_client()
    with cli.session_transaction() as sess:
        sess["_user_id"] = str(USUARIO_POR_MODO["admin"])
        sess["_fresh"] = True
        sess["modo_painel"] = "admin"
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id FROM pre_cadastro ORDER BY id DESC LIMIT 1")
    pid = (cur.fetchone() or {}).get("id")
    cur.close(); conn.close()
    if pid:
        r = cli.get(f"/precadastro/{pid}/promover", follow_redirects=True)
        checar("19. /precadastro/<id>/promover responde 200", r.status_code == 200,
               str(r.status_code))

    print("\n" + ("TUDO PASSOU" if not _falhas else f"FALHARAM {len(_falhas)}: " + "; ".join(_falhas)))
    return 1 if _falhas else 0


if __name__ == "__main__":
    sys.exit(main())
