"""Mensagens enviadas da ficha do aluno.

O que a ficha passou a ter: ocorrência, aviso de faltas, texto livre e qualquer
modelo já cadastrado na academia — um aluno por vez, com prévia antes de enviar.

Dois pontos que os testes protegem:

* a prévia e o envio usam o MESMO código. Se a tela montasse o texto por conta
  própria, o que a secretaria lê e o que o responsável recebe poderiam divergir;
* o id do aluno vem da URL e é editável. Sem a checagem de escopo, um gestor
  mandaria mensagem para o aluno de outra academia.

Uso:  PYTHONPATH=. .venv/bin/python tests/test_mensagem_aluno.py
"""
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app                                    # noqa: E402
from config import get_db_connection                   # noqa: E402
from utils import whatsapp_aluno as wa                 # noqa: E402
from utils import whatsapp_templates as tpl            # noqa: E402
from tests.test_shell_smoke import USUARIO_POR_MODO    # noqa: E402

ACADEMIA = -9910
OUTRA = -9909
EMAIL_GESTOR = "zz.gestor.msg@teste.local"
_falhas = []
ids = {}
enviados = []


def checar(nome, condicao, detalhe=""):
    print(("  PASSOU  " if condicao else "  FALHOU  ") + nome
          + (f"  [{detalhe}]" if detalhe and not condicao else ""))
    if not condicao:
        _falhas.append(nome)


def _conn():
    c = get_db_connection()
    return c, c.cursor(dictionary=True)


def limpar():
    c, cur = _conn()
    for aid in (ACADEMIA, OUTRA):
        cur.execute("""DELETE p FROM presencas p JOIN alunos a ON a.id = p.aluno_id
                       WHERE a.id_academia = %s""", (aid,))
        cur.execute("DELETE FROM whatsapp_log WHERE id_academia = %s", (aid,))
        cur.execute("DELETE FROM whatsapp_templates WHERE id_academia = %s", (aid,))
        cur.execute("DELETE FROM alunos WHERE id_academia = %s", (aid,))
        cur.execute("DELETE FROM usuarios_academias WHERE academia_id = %s", (aid,))
        cur.execute("DELETE FROM academias WHERE id = %s", (aid,))
    cur.execute("""DELETE ru FROM roles_usuario ru JOIN usuarios u
                   ON u.id = ru.usuario_id WHERE u.email = %s""", (EMAIL_GESTOR,))
    cur.execute("DELETE FROM usuarios WHERE email = %s", (EMAIL_GESTOR,))
    c.commit(); cur.close(); c.close()


def montar():
    c, cur = _conn()
    cur.execute("INSERT INTO academias (id, nome) VALUES (%s,'ZZ Msg Academia')", (ACADEMIA,))
    cur.execute("INSERT INTO academias (id, nome) VALUES (%s,'ZZ Msg Vizinha')", (OUTRA,))
    cur.execute("""INSERT INTO alunos (id_academia, nome, ativo, tel_celular,
                                       responsavel_financeiro_nome,
                                       responsavel_financeiro_telefone)
                   VALUES (%s,'ZZ Pedro Aluno',1,'81977770001',
                           'ZZ Mãe do Pedro','81966660002')""", (ACADEMIA,))
    ids["aluno"] = cur.lastrowid
    cur.execute("""INSERT INTO alunos (id_academia, nome, ativo, tel_celular)
                   VALUES (%s,'ZZ Sem Telefone',1,'')""", (ACADEMIA,))
    ids["sem_tel"] = cur.lastrowid
    cur.execute("""INSERT INTO alunos (id_academia, nome, ativo, tel_celular)
                   VALUES (%s,'ZZ Aluno Vizinho',1,'81955550003')""", (OUTRA,))
    ids["vizinho"] = cur.lastrowid
    # Três faltas neste mês.
    hoje = date.today()
    for dia in (3, 10, 17):
        try:
            cur.execute("""INSERT INTO presencas (aluno_id, data_presenca, presente)
                           VALUES (%s, %s, 0)""",
                        (ids["aluno"], date(hoje.year, hoje.month, dia)))
        except Exception:
            pass
    cur.execute("INSERT IGNORE INTO usuarios_academias (usuario_id, academia_id) "
                "VALUES (%s,%s)", (USUARIO_POR_MODO["admin"], ACADEMIA))
    # O isolamento só dá para medir com um gestor de UMA academia: o admin vê
    # todas por definição, e testar com ele provaria o contrário do que se quer.
    cur.execute("""INSERT INTO usuarios (nome, email, senha, perfil, ativo, cpf)
                   VALUES ('ZZ Gestor Msg', %s, 'x', 'Supervisor', 1,
                           '00000000191')""", (EMAIL_GESTOR,))
    ids["gestor"] = cur.lastrowid
    cur.execute("INSERT INTO roles_usuario (usuario_id, role_id) "
                "SELECT %s, id FROM roles WHERE chave = 'gestor_academia'",
                (ids["gestor"],))
    cur.execute("INSERT IGNORE INTO usuarios_academias (usuario_id, academia_id) "
                "VALUES (%s,%s)", (ids["gestor"], ACADEMIA))
    c.commit(); cur.close(); c.close()


def _cliente():
    cli = app.test_client()
    with cli.session_transaction() as s:
        s["_user_id"] = str(USUARIO_POR_MODO["admin"])
        s["_fresh"] = True
        s["modo_painel"] = "academia"
        s["academia_gerenciamento_id"] = ACADEMIA
    return cli


def main():
    limpar()
    montar()
    from utils import whatsapp as wpp
    original = wpp.enviar
    wpp.enviar = lambda academia_id, telefone, texto, **kw: (
        enviados.append((telefone, texto)) or (True, {}))
    try:
        print("\nDestinatário e dados\n")

        aluno = wa.dados_do_aluno(ids["aluno"])
        tel, quem = wa.destinatario(aluno)
        checar("1. fala com o responsável financeiro quando há um",
               tel == "81966660002" and "Mãe" in quem, f"{tel} {quem}")
        faltas, periodo = wa.contar_faltas(ids["aluno"])
        checar("2. conta as faltas do mês", faltas == 3, str(faltas))
        checar("3. e nomeia o período", "de " in periodo, periodo)

        print("\nPrévia\n")

        texto, erro = wa.previa(ids["aluno"], "faltas", ACADEMIA,
                                extra={"faltas": faltas, "periodo": periodo})
        checar("4. o aviso de faltas traz o número e o período",
               not erro and "3 falta" in texto and periodo in texto, erro or texto[:80])
        checar("5. e trata quem recebe pelo primeiro nome",
               texto.startswith("Olá ZZ!"), texto[:30])

        texto, erro = wa.previa(ids["aluno"], "ocorrencia", ACADEMIA,
                                extra={"ocorrencia": "Chegou sem kimono."})
        checar("6. a ocorrência entra no corpo da mensagem",
               not erro and "Chegou sem kimono." in texto
               and "ZZ Pedro Aluno" in texto, erro or texto[:80])

        texto, erro = wa.previa(ids["aluno"], "livre", ACADEMIA,
                                texto_livre="Oi {nome}, o {aluno} esqueceu a garrafa.")
        checar("7. o texto livre resolve as variáveis",
               not erro and "Oi ZZ," in texto and "ZZ Pedro Aluno" in texto, texto)

        _t, erro = wa.previa(ids["sem_tel"], "livre", ACADEMIA, texto_livre="oi")
        checar("8. sem telefone, a prévia já recusa",
               "telefone" in (erro or "").lower(), erro)

        tpl.salvar(ACADEMIA, "boas_vindas", tpl.padrao("boas_vindas"), False)
        _t, erro = wa.previa(ids["aluno"], "boas_vindas", ACADEMIA)
        checar("9. modelo desativado não é oferecido nem na prévia",
               "desativado" in (erro or "").lower(), erro)

        print("\nEnvio\n")

        enviados.clear()
        ok, msg = wa.enviar(ids["aluno"], "ocorrencia", ACADEMIA,
                            extra={"ocorrencia": "Conversamos sobre o horário."})
        checar("10. envia para o telefone do responsável",
               ok and len(enviados) == 1 and enviados[0][0] == "81966660002",
               f"{ok} {msg} {enviados}")
        checar("11. e o texto enviado é o da prévia",
               "Conversamos sobre o horário." in enviados[0][1])

        c, cur = _conn()
        cur.execute("""SELECT tipo, status, aluno_id FROM whatsapp_log
                       WHERE id_academia = %s ORDER BY id DESC LIMIT 1""", (ACADEMIA,))
        log = cur.fetchone()
        cur.close(); c.close()
        checar("12. o envio fica no histórico com o tipo",
               log and log["tipo"] == "ocorrencia" and log["aluno_id"] == ids["aluno"],
               str(log))

        enviados.clear()
        ok, msg = wa.enviar(ids["sem_tel"], "livre", ACADEMIA, texto_livre="oi")
        checar("13. aluno sem telefone não dispara nada",
               not ok and not enviados, f"{ok} {msg}")

        print("\nEscopo: aluno de outra academia\n")

        cli = _cliente()
        h = cli.get(f"/alunos/ficha/{ids['aluno']}",
                    follow_redirects=True).get_data(as_text=True)
        tok = re.search(r'name="csrf_token" value="([^"]+)"', h)
        tok = tok.group(1) if tok else ""
        checar("14. a ficha abre com a aba Mensagens",
               'data-painel="mensagens"' in h)
        checar("15. e mostra o destinatário",
               "ZZ Mãe do Pedro" in h)

        gestor = app.test_client()
        with gestor.session_transaction() as sess:
            sess["_user_id"] = str(ids["gestor"])
            sess["_fresh"] = True
            sess["modo_painel"] = "academia"
            sess["academia_gerenciamento_id"] = ACADEMIA
        hg = gestor.get(f"/alunos/ficha/{ids['aluno']}",
                        follow_redirects=True).get_data(as_text=True)
        tok_g = re.search(r'name="csrf_token" value="([^"]+)"', hg)
        tok_g = tok_g.group(1) if tok_g else ""

        enviados.clear()
        r = gestor.post(f"/alunos/{ids['vizinho']}/mensagem",
                        data={"tipo": "livre", "texto": "invadindo",
                              "csrf_token": tok_g})
        checar("16. gestor de uma academia não fala com aluno de outra",
               r.status_code == 403 and not enviados, f"{r.status_code} {enviados}")

        enviados.clear()
        r = gestor.post(f"/alunos/{ids['aluno']}/mensagem",
                        data={"tipo": "livre", "texto": "ok", "csrf_token": tok_g})
        checar("16b. mas fala com o da própria academia",
               r.status_code == 200 and len(enviados) == 1,
               f"{r.status_code} {enviados}")

        enviados.clear()
        r = cli.post(f"/alunos/{ids['aluno']}/mensagem",
                     data={"tipo": "livre", "texto": "tudo certo {nome}",
                           "csrf_token": tok})
        checar("17. e para o aluno da própria academia passa",
               r.status_code == 200 and len(enviados) == 1,
               f"{r.status_code} {enviados}")
    finally:
        wpp.enviar = original
        limpar()

    print()
    if _falhas:
        print(f"{len(_falhas)} falha(s): " + ", ".join(_falhas))
        sys.exit(1)
    print("Todos os cenários passaram.")


if __name__ == "__main__":
    main()
