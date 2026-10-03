"""O botão de cobrar do painel cobra, e diz para quantos.

A queixa
--------
"O botão de enviar msg para cobrar alunos está levando para outra página."
Levava mesmo: era um link para a tela de mensalidades, sem enviar nada. Quem
clicava achava que tinha cobrado.

O número no botão vem da MESMA consulta que o envio usa. A lista de
inadimplentes do painel mostra só os 10 maiores e segue o filtro da tela —
usar aquele número prometeria uma coisa e faria outra, porque o envio é da
academia inteira.

Uso:  PYTHONPATH=. .venv/bin/python tests/test_dash_cobranca.py
"""
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app                                    # noqa: E402
from config import get_db_connection                   # noqa: E402
from tests.test_shell_smoke import USUARIO_POR_MODO    # noqa: E402

ACADEMIA = -9890
_falhas = []
ids = {}
enviados = []
QUANTOS = 12          # mais que os 10 da lista, de propósito


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
    cur.execute("""DELETE ma FROM mensalidade_aluno ma JOIN alunos a
                   ON a.id = ma.aluno_id WHERE a.id_academia = %s""", (ACADEMIA,))
    cur.execute("DELETE FROM whatsapp_log WHERE id_academia = %s", (ACADEMIA,))
    cur.execute("DELETE FROM alunos WHERE id_academia = %s", (ACADEMIA,))
    cur.execute("DELETE FROM mensalidades WHERE id_academia = %s", (ACADEMIA,))
    cur.execute("DELETE FROM usuarios_academias WHERE academia_id = %s", (ACADEMIA,))
    cur.execute("DELETE FROM academias WHERE id = %s", (ACADEMIA,))
    c.commit(); cur.close(); c.close()


def montar():
    c, cur = _conn()
    cur.execute("""INSERT INTO academias (id, nome, whatsapp_numero)
                   VALUES (%s,'ZZ Cobranca','5581999990000')""", (ACADEMIA,))
    cur.execute("""INSERT INTO mensalidades (nome, valor, id_academia, ativo)
                   VALUES ('ZZ Plano', 100, %s, 1)""", (ACADEMIA,))
    ids["plano"] = cur.lastrowid
    venceu = date.today() - timedelta(days=10)
    for n in range(QUANTOS):
        cur.execute("""INSERT INTO alunos (id_academia, nome, ativo, status, tel_celular)
                       VALUES (%s, %s, 1, 'ativo', %s)""",
                    (ACADEMIA, f"ZZ Devedor {n:02d}", f"819{n:08d}"))
        aluno = cur.lastrowid
        cur.execute("""INSERT INTO mensalidade_aluno
                       (aluno_id, mensalidade_id, data_vencimento, valor, status)
                       VALUES (%s,%s,%s,%s,'atrasado')""",
                    (aluno, ids["plano"], venceu, 100 + n))
    cur.execute("INSERT IGNORE INTO usuarios_academias (usuario_id, academia_id) "
                "VALUES (%s,%s)", (USUARIO_POR_MODO["admin"], ACADEMIA))
    c.commit(); cur.close(); c.close()


def _cliente():
    cli = app.test_client()
    with cli.session_transaction() as s:
        s["_user_id"] = str(USUARIO_POR_MODO["admin"])
        s["_fresh"] = True
        s["modo_painel"] = "academia"
        s["academia_gerenciamento_id"] = ACADEMIA
        s["finance_academia_id"] = ACADEMIA
    return cli


def main():
    limpar()
    montar()
    from utils import whatsapp as wpp
    orig_env, orig_disp, orig_con = wpp.enviar, wpp.disponivel, wpp.conectado
    wpp.enviar = lambda academia_id, telefone, texto, **kw: (
        enviados.append((telefone, texto)) or (True, {}))
    wpp.disponivel = lambda: True
    wpp.conectado = lambda academia_id: True
    try:
        cli = _cliente()
        url = f"/academia/dash?academia_id={ACADEMIA}"
        h = cli.get(url, follow_redirects=True).get_data(as_text=True)

        print("\nO botão\n")

        checar("1. é um POST que cobra, não um link para outra tela",
               "mensalidades/notificar-atrasados" in h and '<form method="POST"' in h)
        m = re.search(r"Cobrar (\d+) por WhatsApp", h)
        checar("2. o rótulo diz o número de alunos",
               m and int(m.group(1)) == QUANTOS, m.group(0) if m else "ausente")
        checar("3. e não os 10 da lista abaixo",
               m and int(m.group(1)) != 10, m.group(0) if m else "")
        conf = re.search(r"confirm\('([^']+)", h)
        checar("4. pede confirmação dizendo quantos vão receber",
               conf and f"para {QUANTOS} alunos em atraso" in conf.group(1),
               (conf.group(1)[:90] if conf else "sem confirm"))
        checar("5. e explica de onde sai o texto da mensagem",
               conf and "WhatsApp › Mensagens" in conf.group(1))
        checar("6. tem atalho para personalizar a mensagem",
               "Editar mensagem" in h and "whatsapp/mensagens" in h)

        print("\nO envio\n")

        tok = re.search(r'name="csrf_token" value="([^"]+)"', h).group(1)
        enviados.clear()
        r = cli.post("/financeiro/painel/mensalidades/notificar-atrasados",
                     data={"csrf_token": tok, "academia_id": ACADEMIA,
                           "voltar": url}, follow_redirects=False)
        checar("7. o envio alcança os devedores",
               len(enviados) == QUANTOS, str(len(enviados)))
        checar("8. e volta para o painel, não para outra tela",
               r.status_code == 302 and "/academia/dash" in (r.headers.get("Location") or ""),
               f"{r.status_code} {r.headers.get('Location')}")

        print("\nCom a tela filtrada\n")

        hf = cli.get(url + "&modalidade_id=1", follow_redirects=True).get_data(as_text=True)
        conf = re.search(r"confirm\('([^']+)", hf)
        if conf and "ATENÇÃO" in conf.group(1):
            checar("9. avisa que a cobrança é da academia inteira", True)
        else:
            # Sem modalidade cadastrada nesta academia de teste o filtro é
            # descartado pela rota; então o aviso não deve aparecer mesmo.
            checar("9. sem filtro válido, não inventa aviso",
                   conf and "ATENÇÃO" not in conf.group(1))
    finally:
        wpp.enviar, wpp.disponivel, wpp.conectado = orig_env, orig_disp, orig_con
        limpar()

    print()
    if _falhas:
        print(f"{len(_falhas)} falha(s): " + ", ".join(_falhas))
        sys.exit(1)
    print("Todos os cenários passaram.")


if __name__ == "__main__":
    main()
