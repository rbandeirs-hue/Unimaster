"""Administrar o sistema e gerir uma academia são papéis diferentes.

Até a ADM-01 eram a mesma conta: a pessoal do Rodrigo acumulava admin, gestor
de associação e gestor de três academias. A conta "Administrador" existia, com
o papel admin, mas sem CPF — e como o login é por CPF, ela nunca entrou.

Agora:
  * "Administrador de Sistema" (CPF 99999999999) é só admin, sem vínculo com
    academia nenhuma, e por isso enxerga todas — é a regra do próprio escopo:
    admin não é limitado por `usuarios_academias`;
  * o Rodrigo é gestor da academia dele e nada além disso.

Uso:  PYTHONPATH=. .venv/bin/python tests/test_admin_sistema.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection                     # noqa: E402

CPF_ADMIN = "99999999999"
CPF_RODRIGO = "08159948425"
ACADEMIA_DO_RODRIGO = 14
_falhas = []


def checar(nome, condicao, detalhe=""):
    print(("  PASSOU  " if condicao else "  FALHOU  ") + nome
          + (f"  [{detalhe}]" if detalhe and not condicao else ""))
    if not condicao:
        _falhas.append(nome)


def _papeis(cur, usuario_id):
    cur.execute("""SELECT r.chave, ru.academia_id FROM roles_usuario ru
                   JOIN roles r ON r.id = ru.role_id WHERE ru.usuario_id = %s""", (usuario_id,))
    return {(r["chave"], r["academia_id"]) for r in cur.fetchall()}


def main():
    print("\nAdministrador de sistema e gestor de academia são contas diferentes\n")
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, nome, cpf, ativo FROM usuarios WHERE cpf = %s", (CPF_ADMIN,))
        adm = cur.fetchone()
        checar("1. existe a conta do CPF 99999999999", adm is not None)
        if not adm:
            return 1
        checar("2. o nome é 'Administrador de Sistema'",
               adm["nome"] == "Administrador de Sistema", adm["nome"])
        checar("3. a conta está ativa (sem isso o login recusa)", bool(adm["ativo"]))

        p_adm = _papeis(cur, adm["id"])
        checar("4. tem o papel admin valendo em todas (academia_id 0)",
               ("admin", 0) in p_adm, str(sorted(p_adm)))
        checar("5. não acumula outro papel — é só administrador",
               p_adm == {("admin", 0)}, str(sorted(p_adm)))

        cur.execute("SELECT COUNT(*) n FROM usuarios_academias WHERE usuario_id = %s", (adm["id"],))
        checar("6. não precisa de academia marcada: nenhum vínculo",
               cur.fetchone()["n"] == 0)

        # A regra que faz isso valer está em _academias_ids_brutas: para admin,
        # o vínculo não limita. Se alguém inverter a ordem da checagem, a conta
        # sem vínculo passaria a não ver academia nenhuma — por isso o teste.
        from app import app
        from blueprints.academia.routes import _academias_ids_brutas
        cur.execute("SELECT COUNT(*) n FROM academias")
        total = cur.fetchone()["n"]
        cli = app.test_client()
        with cli.session_transaction() as sess:
            sess["_user_id"] = str(adm["id"])
            sess["_fresh"] = True
            sess["modo_painel"] = "admin"
        from app import load_user
        with app.test_request_context("/"):
            from flask_login import login_user
            u = load_user(str(adm["id"]))
            checar("7. a conta carrega para o login", u is not None)
            if u:
                login_user(u)
                vistas = _academias_ids_brutas()
                checar(f"8. o admin alcança as {total} academias sem marcar nenhuma",
                       len(vistas) == total, f"{len(vistas)} de {total}")

        print()
        cur.execute("SELECT id, nome FROM usuarios WHERE cpf = %s", (CPF_RODRIGO,))
        rod = cur.fetchone()
        checar("9. o Rodrigo continua com a conta dele", rod is not None)
        if rod:
            p_rod = _papeis(cur, rod["id"])
            checar("10. não é mais administrador do sistema",
                   ("admin", 0) not in p_rod, str(sorted(p_rod)))
            checar("11. não é mais gestor da associação",
                   not any(c == "gestor_associacao" for c, _ in p_rod), str(sorted(p_rod)))
            checar("12. é gestor da academia dele",
                   ("gestor_academia", ACADEMIA_DO_RODRIGO) in p_rod, str(sorted(p_rod)))
            fora = sorted((c, a) for c, a in p_rod if a not in (ACADEMIA_DO_RODRIGO,))
            checar("13. nenhum papel dele vale fora da academia dele", not fora, str(fora))
            cur.execute("SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s",
                        (rod["id"],))
            vinc = sorted(r["academia_id"] for r in cur.fetchall())
            checar("14. o vínculo também é só com a academia dele",
                   vinc == [ACADEMIA_DO_RODRIGO], str(vinc))

        print()
        # "Administrador pode ter acesso a qualquer parte do sistema."
        # Boa parte das telas é fechada por MODO, não por papel — e o admin,
        # depois da ADM-01, só tinha o modo "admin". A correção foi dar a ele
        # os modos de gestão; este teste varre as rotas para garantir que não
        # sobrou tela de gestão fora do alcance dele.
        MODOS = ("admin", "federacao", "associacao", "academia")
        # Telas pessoais: dependem de um cadastro da própria pessoa (ficha de
        # professor, de visitante). Não são parte a administrar — sem cadastro
        # não há o que mostrar.
        PESSOAIS = ("/professor/", "/visitante/", "/eventos-competicoes/disponiveis")
        rotas = [str(r) for r in app.url_map.iter_rules()
                 if "GET" in r.methods and "<" not in str(r)
                 and not str(r).startswith(("/static", "/auth/logout", "/painel/sair"))]
        cli2 = app.test_client()
        with cli2.session_transaction() as sess:
            sess["_user_id"] = str(adm["id"])
            sess["_fresh"] = True
        sem_saida = []
        for url in rotas:
            if url.startswith(PESSOAIS):
                continue
            for modo in MODOS:
                with cli2.session_transaction() as sess:
                    sess["modo_painel"] = modo
                    sess["academia_gerenciamento_id"] = ACADEMIA_DO_RODRIGO
                try:
                    txt = cli2.get(url, follow_redirects=True).get_data(as_text=True)
                except Exception:
                    break
                if "Disponível apenas em modo" not in txt and "Acesso negado" not in txt:
                    break
            else:
                sem_saida.append(url)
        checar(f"15. o admin alcança as {len(rotas)} telas de gestão em algum modo",
               not sem_saida, ", ".join(sem_saida[:6]))

        from blueprints.painel.routes import _modos_disponiveis
        from app import load_user as _load
        with app.test_request_context("/"):
            from flask_login import login_user as _login
            _login(_load(str(adm["id"])))
            modos_adm = [m[0] for m in _modos_disponiveis()]
        checar("16. o admin pode entrar nos modos de gestão",
               {"admin", "federacao", "associacao", "academia"} <= set(modos_adm),
               str(modos_adm))
        checar("17. não recebe o modo professor sem ficha de professor",
               "professor" not in modos_adm, str(modos_adm))

        print()
        cur.execute("""SELECT u.id, u.nome FROM usuarios u
                       JOIN roles_usuario ru ON ru.usuario_id = u.id
                       JOIN roles r ON r.id = ru.role_id AND r.chave = 'admin'
                       WHERE COALESCE(u.ativo, 1) = 1""")
        admins = cur.fetchall()
        checar("18. existe exatamente um administrador de sistema ativo",
               len(admins) == 1, str([(a["id"], a["nome"]) for a in admins]))
        checar("19. e é a conta de CPF 99999999999",
               admins and admins[0]["id"] == adm["id"],
               str([(a["id"], a["nome"]) for a in admins]))
    finally:
        cur.close()
        conn.close()

    print("\n" + ("TUDO PASSOU" if not _falhas else f"FALHARAM {len(_falhas)}: " + "; ".join(_falhas)))
    return 1 if _falhas else 0


if __name__ == "__main__":
    sys.exit(main())
