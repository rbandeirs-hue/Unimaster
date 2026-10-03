"""O interruptor "Avisos gerais" desliga de verdade.

O defeito
---------
`academias.whatsapp_avisos` era gravado pela tela de WhatsApp e NUNCA lido pela
rota de envio. Desmarcado, o sistema continuava disparando o aviso para todos
os alunos da academia. O interruptor existia só na aparência.

A trava tem de ser no servidor: esconder o botão não adianta, o envio é um POST
que pode ser repetido.

Uso:  PYTHONPATH=. .venv/bin/python tests/test_avisos_interruptor.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app                                    # noqa: E402
from config import get_db_connection                   # noqa: E402
from tests.test_shell_smoke import USUARIO_POR_MODO    # noqa: E402

ACADEMIA = -9920
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
    cur.execute("DELETE FROM whatsapp_log WHERE id_academia = %s", (ACADEMIA,))
    cur.execute("DELETE FROM alunos WHERE id_academia = %s", (ACADEMIA,))
    cur.execute("DELETE FROM usuarios_academias WHERE academia_id = %s", (ACADEMIA,))
    cur.execute("DELETE FROM academias WHERE id = %s", (ACADEMIA,))
    c.commit(); cur.close(); c.close()


def montar():
    c, cur = _conn()
    cur.execute("INSERT INTO academias (id, nome) VALUES (%s,'ZZ Avisos')", (ACADEMIA,))
    for n in range(1, 4):
        cur.execute("""INSERT INTO alunos (id_academia, nome, ativo, tel_celular)
                       VALUES (%s, %s, 1, %s)""",
                    (ACADEMIA, f"ZZ Aviso {n}", f"8198888000{n}"))
    cur.execute("INSERT IGNORE INTO usuarios_academias (usuario_id, academia_id) "
                "VALUES (%s, %s)", (USUARIO_POR_MODO["admin"], ACADEMIA))
    c.commit(); cur.close(); c.close()


def _ligar(valor):
    c, cur = _conn()
    cur.execute("UPDATE academias SET whatsapp_avisos = %s WHERE id = %s",
                (1 if valor else 0, ACADEMIA))
    c.commit(); cur.close(); c.close()


def _cliente():
    cli = app.test_client()
    with cli.session_transaction() as s:
        s["_user_id"] = str(USUARIO_POR_MODO["admin"])
        s["_fresh"] = True
        s["modo_painel"] = "academia"
        s["academia_gerenciamento_id"] = ACADEMIA
    return cli


def _token(cli):
    """O CSRF da tela. O POST real também o exige — testar sem ele mediria a
    proteção de CSRF, não o interruptor."""
    h = cli.get(f"/academia/whatsapp/avisos?academia_id={ACADEMIA}",
                follow_redirects=True).get_data(as_text=True)
    m = re.search(r'name="csrf_token" value="([^"]+)"', h) or \
        re.search(r'csrf_token\(\)|"([A-Za-z0-9_.\-]{20,})"', h)
    return m.group(1) if m and m.lastindex else ""


def main():
    limpar()
    montar()

    # Espião no lugar do transporte: nenhuma mensagem real sai daqui.
    from utils import whatsapp as wpp
    original = wpp.enviar
    wpp.enviar = lambda academia_id, telefone, texto, **kw: (
        enviados.append(telefone) or (True, {}))

    try:
        cli = _cliente()
        _ligar(True)          # liga só para colher o token da tela
        tok = _token(cli)

        print("\nCom o interruptor DESLIGADO\n")

        _ligar(False)
        h = cli.get(f"/academia/whatsapp/avisos?academia_id={ACADEMIA}",
                    follow_redirects=True).get_data(as_text=True)
        checar("1. a tela avisa que está desligado",
               "desligados para esta academia" in h)
        checar("2. e o botão não fica pronto para enviar",
               "Avisos desligados" in h)

        enviados.clear()
        r = cli.post("/academia/whatsapp/avisos/enviar",
                     data={"mensagem": "ZZ teste", "destino": "todos",
                           "csrf_token": tok},
                     follow_redirects=True)
        corpo = r.get_data(as_text=True)
        checar("3. o POST é recusado", r.status_code == 409, str(r.status_code))
        checar("4. com mensagem que diz onde ligar",
               "Avisos gerais" in corpo or "avisos gerais" in corpo, corpo[:120])
        checar("5. e NENHUMA mensagem sai", len(enviados) == 0, str(enviados))

        print("\nCom o interruptor LIGADO\n")

        _ligar(True)
        h = cli.get(f"/academia/whatsapp/avisos?academia_id={ACADEMIA}",
                    follow_redirects=True).get_data(as_text=True)
        checar("6. o aviso de desligado some", "desligados para esta academia" not in h)

        enviados.clear()
        r = cli.post("/academia/whatsapp/avisos/enviar",
                     data={"mensagem": "ZZ teste", "destino": "todos",
                           "csrf_token": tok},
                     follow_redirects=True)
        checar("7. o envio é aceito", r.status_code == 200, str(r.status_code))
        checar("8. e alcança os três alunos", len(enviados) == 3, str(len(enviados)))

        print("\nA trava é do servidor, não da tela\n")

        _ligar(False)
        enviados.clear()
        # Chamada direta, sem passar pela tela — é o que um POST repetido faz.
        r = cli.post("/academia/whatsapp/avisos/enviar",
                     data={"mensagem": "ZZ burlar", "destino": "todos",
                           "csrf_token": tok})
        checar("9. POST direto com o interruptor desligado é recusado",
               r.status_code == 409 and not enviados, f"{r.status_code} {enviados}")
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
