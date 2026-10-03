"""Academia independente: cria, entra como o gestor dela e percorre as telas."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import app                        # noqa
from config import get_db_connection       # noqa

PREF = "ZZ Indep "
falhas, criados = [], {}


def checar(nome, cond, det=""):
    print(("  PASSOU  " if cond else "  FALHOU  ") + nome + (f"  [{det}]" if det and not cond else ""))
    if not cond:
        falhas.append(nome)


def conn():
    c = get_db_connection(); return c, c.cursor(dictionary=True)


def limpar():
    c, cur = conn()
    cur.execute("SELECT id FROM academias WHERE nome LIKE %s", (PREF + "%",))
    ids = [r["id"] for r in cur.fetchall() or []]
    if ids:
        ph = ",".join(["%s"] * len(ids))
        cur.execute(f"DELETE FROM academia_modalidades WHERE academia_id IN ({ph})", tuple(ids))
        cur.execute(f"DELETE FROM usuarios_academias WHERE academia_id IN ({ph})", tuple(ids))
        cur.execute(f"DELETE FROM academias WHERE id IN ({ph})", tuple(ids))
    # O cadastro cria tambem um perfil de aluno para o gestor; sem apagar, o CPF
    # unico derruba a proxima execucao.
    cur.execute("DELETE FROM alunos WHERE nome LIKE %s OR cpf = '39053344705'", (PREF + "%",))
    cur.execute("DELETE FROM professores WHERE nome LIKE %s OR cpf = '39053344705'", (PREF + "%",))
    cur.execute("SELECT id FROM usuarios WHERE nome LIKE %s OR cpf = '39053344705'", (PREF + "%",))
    uids = [r["id"] for r in cur.fetchall() or []]
    if uids:
        ph = ",".join(["%s"] * len(uids))
        cur.execute(f"DELETE FROM roles_usuario WHERE usuario_id IN ({ph})", tuple(uids))
        cur.execute(f"DELETE FROM usuarios_academias WHERE usuario_id IN ({ph})", tuple(uids))
        cur.execute(f"DELETE FROM usuarios WHERE id IN ({ph})", tuple(uids))
    c.commit(); cur.close(); c.close()


with app.app_context():
    limpar()
    app.config["WTF_CSRF_ENABLED"] = False
    cli = app.test_client()
    with cli.session_transaction() as sess:
        sess["_user_id"] = "3"; sess["_fresh"] = True   # admin do sistema
        sess["modo_painel"] = "admin"
        sess["academia_gerenciamento_id"] = 2

    c, cur = conn()
    cur.execute("SELECT id FROM modalidade WHERE nome = 'Jiu-Jitsu'")
    jiu = cur.fetchone()["id"]
    cur.close(); c.close()

    r = cli.post("/associacao/academias/cadastro", data={
        "nome": PREF + "Jiu-Jitsu Academy",
        "id_associacao": "",                      # INDEPENDENTE
        "cidade": "Recife", "uf": "PE",
        "modalidade_ids": [str(jiu)],
        "gestor_nome": PREF + "Gestor",
        "gestor_email": "zz.indep.gestor@example.com",
        "gestor_cpf": "39053344705",
        "gestor_telefone": "(81) 90000-0000",
        "gestor_senha": "Teste@12345",
    }, follow_redirects=False)
    print("   cadastro:", r.status_code, r.headers.get("Location", ""))
    if r.status_code == 200:
        import re
        corpo = r.get_data(as_text=True)
        for m in re.findall(r'alert[^>]*>\s*([^<]{10,140})', corpo)[:4]:
            print("   erro na tela:", " ".join(m.split()))

    c, cur = conn()
    cur.execute("SELECT id, nome, id_associacao FROM academias WHERE nome LIKE %s", (PREF + "%",))
    acad = cur.fetchone()
    checar("1. academia independente foi criada", acad is not None)
    if acad:
        criados["academia"] = acad["id"]
        checar("2. e ficou SEM associação", acad["id_associacao"] is None, str(acad["id_associacao"]))
        cur.execute("SELECT modalidade_id FROM academia_modalidades WHERE academia_id=%s", (acad["id"],))
        mods = [r["modalidade_id"] for r in cur.fetchall() or []]
        checar("3. com a modalidade jiu-jitsu vinculada", jiu in mods, str(mods))
        cur.execute("""SELECT u.id, u.nome FROM usuarios u
                       JOIN usuarios_academias ua ON ua.usuario_id = u.id
                       WHERE ua.academia_id = %s""", (acad["id"],))
        gestor = cur.fetchone()
        checar("4. o gestor foi criado e vinculado", gestor is not None)
        if gestor:
            criados["gestor"] = gestor["id"]
    cur.close(); c.close()

    if criados.get("gestor"):
        gcli = app.test_client()
        with gcli.session_transaction() as sess:
            sess["_user_id"] = str(criados["gestor"]); sess["_fresh"] = True
            sess["modo_painel"] = "academia"
            sess["academia_gerenciamento_id"] = criados["academia"]
            sess["finance_academia_id"] = criados["academia"]

        # Diagnóstico direto: o que o banco diz sobre este gestor.
        c, cur = conn()
        cur.execute("""SELECT r.nome FROM roles_usuario ru JOIN roles r ON r.id = ru.role_id
                       WHERE ru.usuario_id = %s""", (criados["gestor"],))
        papeis = [r["nome"] for r in cur.fetchall() or []]
        cur.execute("SELECT academia_id FROM usuarios_academias WHERE usuario_id = %s",
                    (criados["gestor"],))
        vinculos = [r["academia_id"] for r in cur.fetchall() or []]
        cur.execute("SELECT id_academia, id_associacao FROM usuarios WHERE id = %s",
                    (criados["gestor"],))
        u = cur.fetchone()
        cur.close(); c.close()
        print(f"\n   papeis do gestor: {papeis}")
        print(f"   usuarios_academias: {vinculos}")
        print(f"   usuarios.id_academia={u['id_academia']} id_associacao={u['id_associacao']}")
        # O banco guarda o rótulo ("Gestor Academia"), não o slug.
        checar("5. o gestor recebeu o papel de gestor da academia",
               any("gestor" in p.lower() and "academia" in p.lower() for p in papeis),
               str(papeis))
        checar("5b. e está vinculado à academia", criados["academia"] in vinculos, str(vinculos))

        telas = [("/academia/", "painel"), ("/alunos/lista_alunos", "alunos"),
                 ("/turmas", "turmas"), ("/financeiro/painel/dashboard", "financeiro"),
                 ("/academia/whatsapp", "whatsapp")]
        # Primeiro acesso: o sistema pede para escolher a academia. Com uma só,
        # a tela deve resolver sozinha. Passar por ela é o fluxo real do gestor.
        pre = gcli.get("/academia/escolher", follow_redirects=True)
        print(f"\n   passagem por /academia/escolher: {pre.status_code}")

        print("\n   telas como gestor independente:")
        for url, rot in telas:
            resp = gcli.get(url, follow_redirects=True)
            ok = resp.status_code in (200, 302)
            destino = resp.headers.get("Location", "") if resp.status_code == 302 else ""
            erro = "500" if resp.status_code >= 500 else ""
            corpo = resp.get_data(as_text=True)
            # Marcador exclusivo da tela de escolha, em vez de adivinhar por palavra solta.
            escolher = "Em qual academia voce vai trabalhar" in corpo or \
                       "Em qual academia você vai trabalhar" in corpo
            marca = "PAROU na escolha de academia" if escolher else "abriu"
            print(f"     {rot:12} {resp.status_code}  {marca}")
            checar(f"6.{rot} abre sem erro de servidor", not erro, str(resp.status_code))

        cur_mod = None
        c, cur = conn()
        from utils.modalidades import filtro_visibilidade_sql
        extra, params = filtro_visibilidade_sql(id_academia=criados["academia"])
        cur.execute("SELECT m.nome FROM modalidade m WHERE m.ativo=1" + extra + " ORDER BY m.nome", params)
        vis = [r["nome"] for r in cur.fetchall() or []]
        checar("7. ela enxerga o jiu-jitsu nas modalidades", "Jiu-Jitsu" in vis, str(vis))
        cur.execute("""SELECT COUNT(*) n FROM graduacao g WHERE g.modalidade_id=%s
                       AND COALESCE(g.ativo,1)=1""", (jiu,))
        checar("8. e as 14 faixas de jiu-jitsu estão disponíveis",
               cur.fetchone()["n"] == 14)
        cur.close(); c.close()

    limpar()
    print()
    if falhas:
        print(f"{len(falhas)} falha(s): " + ", ".join(falhas)); sys.exit(1)
    print("Todos os cenários passaram.")
