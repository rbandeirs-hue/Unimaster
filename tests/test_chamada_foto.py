"""Chamada por foto: consentimento, descritores e a gravação pela chamada de sempre.

O reconhecimento roda no navegador; o que o servidor precisa garantir é:

* só entra no reconhecimento quem tem foto E consentimento — a página entrega
  a cada pessoa o motivo de estar (ou não) na comparação;
* o descritor só é gravado para aluno da academia, com consentimento e para a
  foto que está no cadastro agora; retirar o consentimento apaga tudo;
* menor de idade não se autoriza pelo próprio login: quem decide é o responsável;
* a tela grava pelo MESMO POST da chamada manual, sem apagar observação/plano.

Uso:  PYTHONPATH=. .venv/bin/python tests/test_chamada_foto.py
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
from utils import chamada_foto as cf                   # noqa: E402
from tests.test_shell_smoke import USUARIO_POR_MODO    # noqa: E402

ACADEMIA = -9930
OUTRA = -9929
ADMIN = USUARIO_POR_MODO["admin"]
_falhas = []
ids = {}
HOJE = date.today().isoformat()
DESC = [0.01 * (i % 7) for i in range(128)]


def checar(nome, condicao, detalhe=""):
    print(("  PASSOU  " if condicao else "  FALHOU  ") + nome
          + (f"  [{detalhe}]" if detalhe and not condicao else ""))
    if not condicao:
        _falhas.append(nome)


def _conn():
    c = get_db_connection()
    return c, c.cursor(dictionary=True)


UPLOADS = ROOT / "static" / "uploads"
FOTOS_TESTE = ["zz_adulto.jpg", "zz_recusou.jpg", "zz_viz.jpg"]


def limpar():
    for f in FOTOS_TESTE:
        (UPLOADS / f).unlink(missing_ok=True)
    c, cur = _conn()
    cf.garantir_tabelas(cur)
    for aid in (ACADEMIA, OUTRA):
        cur.execute("DELETE FROM chamada_foto_rosto WHERE academia_id = %s", (aid,))
        cur.execute("""DELETE d FROM chamada_foto_descritor d JOIN alunos a ON a.id = d.aluno_id
                       WHERE a.id_academia = %s""", (aid,))
        cur.execute("""DELETE k FROM chamada_foto_consentimento k JOIN alunos a ON a.id = k.aluno_id
                       WHERE a.id_academia = %s""", (aid,))
        cur.execute("DELETE FROM chamada_foto_academia WHERE academia_id = %s", (aid,))
        cur.execute("DELETE p FROM presencas p JOIN turmas t ON t.TurmaID = p.turma_id WHERE t.id_academia = %s", (aid,))
        cur.execute("DELETE FROM registros_aula_presenca WHERE academia_id = %s", (aid,))
        cur.execute("DELETE at FROM aluno_turmas at JOIN turmas t ON t.TurmaID = at.TurmaID WHERE t.id_academia = %s", (aid,))
        cur.execute("""DELETE ra FROM responsavel_alunos ra JOIN alunos a ON a.id = ra.aluno_id
                       WHERE a.id_academia = %s""", (aid,))
        cur.execute("DELETE FROM turmas WHERE id_academia = %s", (aid,))
        cur.execute("DELETE FROM alunos WHERE id_academia = %s", (aid,))
        cur.execute("DELETE FROM usuarios_academias WHERE academia_id = %s", (aid,))
        cur.execute("DELETE FROM academias WHERE id = %s", (aid,))
    c.commit(); cur.close(); c.close()


def montar():
    from PIL import Image
    for f in FOTOS_TESTE:
        Image.new("RGB", (60, 60), (120, 100, 90)).save(UPLOADS / f)
    c, cur = _conn()
    cur.execute("INSERT INTO academias (id, nome) VALUES (%s,'ZZ Foto Academia')", (ACADEMIA,))
    cur.execute("INSERT INTO academias (id, nome) VALUES (%s,'ZZ Foto Vizinha')", (OUTRA,))
    cur.execute("INSERT IGNORE INTO usuarios_academias (usuario_id, academia_id) VALUES (%s,%s)", (ADMIN, ACADEMIA))
    cur.execute("""INSERT INTO turmas (Nome, DiasHorario, IdadeMin, IdadeMax, Professor, Classificacao,
                                       Capacidade, id_academia)
                   VALUES ('ZZ Turma Foto', '', 0, 99, '', '', 30, %s)""", (ACADEMIA,))
    ids["turma"] = cur.lastrowid

    def aluno(nome, foto, nasc, academia=ACADEMIA, turma=True):
        cur.execute("""INSERT INTO alunos (nome, id_academia, ativo, foto, data_nascimento, TurmaID)
                       VALUES (%s, %s, 1, %s, %s, %s)""",
                    (nome, academia, foto, nasc, ids["turma"] if turma else None))
        i = cur.lastrowid
        if turma:
            cur.execute("INSERT INTO aluno_turmas (aluno_id, TurmaID) VALUES (%s, %s)", (i, ids["turma"]))
        return i

    ids["adulto"] = aluno("ZZ Adulto Autorizou", "zz_adulto.jpg", "1990-01-01")
    ids["menor"] = aluno("ZZ Menor Sem Foto", None, date.today().replace(year=date.today().year - 10))
    ids["recusou"] = aluno("ZZ Recusou", "zz_recusou.jpg", "1992-01-01")
    ids["vizinho"] = aluno("ZZ Vizinho", "zz_viz.jpg", "1990-01-01", academia=OUTRA, turma=False)

    # Usuário de responsável que os outros testes já usam (cadastro completo:
    # um usuário novo cairia em "completar cadastro" antes de chegar à tela).
    ids["resp"] = USUARIO_POR_MODO["responsavel"]
    cur.execute("INSERT INTO responsavel_alunos (usuario_id, aluno_id) VALUES (%s, %s)", (ids["resp"], ids["menor"]))

    cf.definir_consentimento(cur, ids["adulto"], "autorizou", "termo_papel", ADMIN)
    cf.definir_consentimento(cur, ids["recusou"], "recusou", "aluno", ADMIN)
    cf.definir_consentimento(cur, ids["vizinho"], "autorizou", "termo_papel", ADMIN)
    c.commit(); cur.close(); c.close()


def _cliente(usuario=ADMIN, modo="academia"):
    cli = app.test_client()
    with cli.session_transaction() as s:
        s["_user_id"] = str(usuario)
        s["_fresh"] = True
        s["modo_painel"] = modo
        s["academia_gerenciamento_id"] = ACADEMIA
    return cli


def _token(html):
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1) if m else ""


def _contar(sql, params):
    c, cur = _conn()
    cur.execute(sql, params)
    n = list(cur.fetchone().values())[0]
    cur.close(); c.close()
    return n


class AwsFalso:
    """Rekognition de mentira: registra o que foi pedido e responde fixo."""
    def __init__(self):
        self.indexados, self.apagados, self.sem_rosto = [], [], set()
        self.n = 0

    def instalar(self):
        from utils import rekognition as rk
        self.rk, self.orig = rk, {k: getattr(rk, k) for k in ("configurado", "indexar", "apagar", "detectar", "buscar")}
        rk.configurado = lambda: True
        rk.indexar = self.indexar
        rk.apagar = lambda academia_id, faces: self.apagados.extend(f for f in faces if f)
        rk.detectar = lambda img: [{"x": 10, "y": 10, "w": 30, "h": 30, "conf": 99},
                                   {"x": 60, "y": 10, "w": 30, "h": 30, "conf": 98}]
        rk.buscar = lambda academia_id, img, rostos: [
            [{"id": str(ids["adulto"]), "sim": 99.1}, {"id": str(ids["vizinho"]), "sim": 97.0}],
            [{"id": str(ids["recusou"]), "sim": 96.0}]]

    def desinstalar(self):
        for k, v in self.orig.items():
            setattr(self.rk, k, v)

    def indexar(self, academia_id, aluno_id, img):
        if aluno_id in self.sem_rosto:
            return None
        self.n += 1
        self.indexados.append(aluno_id)
        return f"face-{aluno_id}-{self.n}"


def main():
    limpar()
    montar()
    aws = AwsFalso()
    aws.instalar()
    try:
        cli = _cliente()
        q = f"academia_id={ACADEMIA}&turma_id={ids['turma']}&data_presenca={HOJE}&horario_aula=18:30"

        print("\nLiga e desliga\n")
        h = cli.get(f"/registro_presenca?{q}").get_data(as_text=True)
        checar("1. desligada, a chamada não mostra o botão", "modo=foto" not in h)
        r = cli.get(f"/registro_presenca?modo=foto&{q}", follow_redirects=True).get_data(as_text=True)
        checar("2. e o modo foto volta para a chamada manual", "cfDados" not in r and "desligada" in r)

        h = cli.get(f"/chamada-foto/configuracao?academia_id={ACADEMIA}").get_data(as_text=True)
        checar("3. a configuração lista os alunos da academia",
               "ZZ Adulto Autorizou" in h and "ZZ Menor Sem Foto" in h and "ZZ Vizinho" not in h)
        cli.post(f"/chamada-foto/configuracao/ativa?academia_id={ACADEMIA}",
                 data={"csrf_token": _token(h), "ativa": "1"})
        c, cur = _conn()
        checar("4. ligar grava na academia", cf.academia_ativa(cur, ACADEMIA))
        cur.close(); c.close()

        print("\nQuem entra no reconhecimento\n")
        h = cli.get(f"/registro_presenca?{q}").get_data(as_text=True)
        checar("5. ligada, a chamada mostra o botão", "modo=foto" in h)
        h = cli.get(f"/registro_presenca?modo=foto&{q}").get_data(as_text=True)
        import json
        m = re.search(r'id="cfDados">(.*?)</script>', h, re.S)
        dados = json.loads(m.group(1)) if m else {"pessoas": []}
        motivo = {p["nome"]: p.get("motivo") for p in dados["pessoas"]}
        checar("6. com foto e consentimento: entra", motivo.get("ZZ Adulto Autorizou") is None
               and "ZZ Adulto Autorizou" in motivo, str(motivo))
        checar("7. recusou: só à mão", motivo.get("ZZ Recusou") == "sem_consentimento", str(motivo))
        checar("8. sem resposta conta como sem consentimento",
               motivo.get("ZZ Menor Sem Foto") == "sem_consentimento", str(motivo))
        adulto = next((p for p in dados["pessoas"] if p["nome"] == "ZZ Adulto Autorizou"), {})
        checar("9. foto do cadastro ainda não levada ao reconhecimento: a página pede", adulto.get("indexar") is True,
               str(adulto))
        checar("10. a foto da turma não vai no formulário de gravação",
               'id="formGravar"' in h and "multipart" not in h.split('id="formGravar"')[1].split("</form>")[0])
        tok = _token(h)

        print("\nRekognition (simulado)\n")
        todos = [ids["adulto"], ids["recusou"], ids["vizinho"], ids["menor"]]
        r = cli.post(f"/chamada-foto/preparar?academia_id={ACADEMIA}", json={"ids": todos},
                     headers={"X-CSRFToken": tok}).get_json() or {}
        checar("11. só a foto de quem autorizou, desta academia, vai ao reconhecimento",
               r.get("prontos") == [str(ids["adulto"])] and aws.indexados == [ids["adulto"]], str(r))
        cli.post(f"/chamada-foto/preparar?academia_id={ACADEMIA}", json={"ids": todos}, headers={"X-CSRFToken": tok})
        checar("12. e não manda de novo a mesma foto", aws.indexados == [ids["adulto"]], str(aws.indexados))
        h = cli.get(f"/registro_presenca?modo=foto&{q}").get_data(as_text=True)
        dados = json.loads(re.search(r'id="cfDados">(.*?)</script>', h, re.S).group(1))
        adulto = next(p for p in dados["pessoas"] if p["nome"] == "ZZ Adulto Autorizou")
        checar("13. na próxima aula vem pronto", adulto.get("indexar") is False and adulto.get("referencias") == 1,
               str(adulto))
        import io
        from PIL import Image
        buf = io.BytesIO(); Image.new("RGB", (120, 60), (90, 90, 90)).save(buf, format="JPEG"); buf.seek(0)
        r = cli.post(f"/chamada-foto/analisar?academia_id={ACADEMIA}", headers={"X-CSRFToken": tok},
                     data={"foto": (buf, "turma.jpg"), "ids": ",".join(str(i) for i in todos)},
                     content_type="multipart/form-data").get_json() or {}
        rostos = r.get("rostos") or []
        checar("14. analisar devolve os rostos com os parecidos, só os desta chamada que autorizaram",
               len(rostos) == 2 and [m["id"] for m in rostos[0]["matches"]] == [str(ids["adulto"])]
               and rostos[1]["matches"] == [] and r.get("largura") == 120, str(r)[:300])

        print("\nGravação pelo POST da chamada\n")
        c, cur = _conn()
        cur.execute("""INSERT INTO registros_aula_presenca (turma_id, academia_id, data_aula, horario_aula, observacao)
                       VALUES (%s, %s, %s, '18:30:00', 'ZZ obs que não pode sumir')""",
                    (ids["turma"], ACADEMIA, HOJE))
        c.commit(); cur.close(); c.close()
        h = cli.get(f"/registro_presenca?modo=foto&{q}").get_data(as_text=True)
        form = h.split('id="formGravar"')[1].split("</form>")[0]
        campos = dict(re.findall(r'name="([a-z_]+)" value="([^"]*)"', form))
        campos["aluno_id"] = [str(ids["adulto"]), str(ids["menor"])]
        cli.post("/registro_presenca", data=campos)
        n = _contar("""SELECT COUNT(*) FROM presencas WHERE turma_id=%s AND data_presenca=%s
                       AND horario_aula='18:30:00' AND presente=1""", (ids["turma"], HOJE))
        checar("15. os presentes caem em presencas", n == 2, str(n))
        n = _contar("""SELECT COUNT(*) FROM presencas WHERE turma_id=%s AND data_presenca=%s
                       AND horario_aula='18:30:00' AND presente=0""", (ids["turma"], HOJE))
        checar("16. e quem não foi marcado fica ausente", n == 1, str(n))
        n = _contar("""SELECT COUNT(*) FROM registros_aula_presenca WHERE turma_id=%s AND data_aula=%s
                       AND observacao='ZZ obs que não pode sumir'""", (ids["turma"], HOJE))
        checar("17. a observação da aula continua lá", n == 1)

        print("\nConsentimento pela família\n")
        fam = _cliente(ids["resp"], "responsavel")
        h = fam.get("/chamada-foto/autorizar").get_data(as_text=True)
        checar("18. o responsável vê o filho", "ZZ Menor Sem Foto" in h)
        ftok = _token(h)
        fam.post(f"/chamada-foto/autorizar/{ids['menor']}", data={"csrf_token": ftok, "status": "autorizou"})
        c, cur = _conn()
        st = cf.status_dos_alunos(cur, [ids["menor"]]).get(ids["menor"]) or {}
        cur.close(); c.close()
        checar("19. e autoriza", st.get("status") == "autorizou" and st.get("via") == "responsavel", str(st))
        r = fam.post(f"/chamada-foto/autorizar/{ids['vizinho']}", data={"csrf_token": ftok, "status": "autorizou"},
                     follow_redirects=True).get_data(as_text=True)
        checar("20. aluno que não é dele: recusa", "não está no seu acesso" in r)

        # Menor no próprio login (via "aluno"): a rota recusa mesmo que o aluno apareça para ele.
        import blueprints.chamada_foto.routes as rotas
        original_busca = rotas._alunos_que_posso_autorizar
        rotas._alunos_que_posso_autorizar = lambda cur: [{
            "id": ids["recusou"], "nome": "ZZ Recusou", "via": "aluno",
            "data_nascimento": date.today().replace(year=date.today().year - 12),
            "responsavel_financeiro_nome": "", "foto": None, "id_academia": ACADEMIA,
            "academia_nome": "ZZ Foto Academia"}]
        try:
            r = fam.post(f"/chamada-foto/autorizar/{ids['recusou']}", data={"csrf_token": ftok, "status": "autorizou"},
                         follow_redirects=True).get_data(as_text=True)
        finally:
            rotas._alunos_que_posso_autorizar = original_busca
        checar("21. menor no próprio login não se autoriza", "quem autoriza é o responsável" in r)

        print("\nSem foto no cadastro, aprende pela chamada\n")
        # O menor agora tem consentimento (teste 19), mas continua sem foto.
        h = cli.get(f"/registro_presenca?modo=foto&{q}").get_data(as_text=True)
        pes = {p["nome"]: p for p in json.loads(re.search(r'id="cfDados">(.*?)</script>', h, re.S).group(1))["pessoas"]}
        menor = pes.get("ZZ Menor Sem Foto", {})
        checar("21b. consentiu sem foto: ainda não reconhece, mas pode aprender",
               menor.get("motivo") == "sem_foto" and menor.get("pode_aprender") is True, str(menor))
        checar("21c. quem não consentiu não pode aprender",
               pes.get("ZZ Recusou", {}).get("pode_aprender") is False)
        tok = _token(h)

        def aprender(aid):
            b = io.BytesIO(); Image.new("RGB", (80, 80), (100, 90, 80)).save(b, format="JPEG"); b.seek(0)
            return cli.post(f"/chamada-foto/aprender?academia_id={ACADEMIA}", headers={"X-CSRFToken": tok},
                            data={"aluno_id": str(aid), "rosto": (b, "rosto.jpg")}, content_type="multipart/form-data")
        r = aprender(ids["menor"])
        checar("21d. o rosto identificado na chamada é guardado mesmo sem foto",
               r.status_code == 200 and (r.get_json() or {}).get("guardado") is True, r.get_data(as_text=True)[:120])
        checar("21e. quem não autorizou, não", aprender(ids["recusou"]).status_code == 403)
        for _ in range(7):
            aprender(ids["menor"])
        n = _contar("SELECT COUNT(*) FROM chamada_foto_rosto WHERE aluno_id=%s AND origem='chamada'", (ids["menor"],))
        from utils.rekognition import MAX_CHAMADA
        checar("21e2. guarda no máximo os mais recentes, e apaga os velhos na AWS",
               n == MAX_CHAMADA and len(aws.apagados) == 8 - MAX_CHAMADA, f"{n} {aws.apagados}")
        h = cli.get(f"/registro_presenca?modo=foto&{q}").get_data(as_text=True)
        pes = {p["nome"]: p for p in json.loads(re.search(r'id="cfDados">(.*?)</script>', h, re.S).group(1))["pessoas"]}
        menor = pes.get("ZZ Menor Sem Foto", {})
        checar("21f. na próxima chamada ele já entra no reconhecimento",
               menor.get("motivo") is None and menor.get("referencias") == MAX_CHAMADA and not menor.get("indexar"),
               str(menor)[:200])
        h = cli.get(f"/chamada-foto/configuracao?academia_id={ACADEMIA}").get_data(as_text=True)
        checar("21g. e a configuração mostra que foi reconhecido pela chamada", "reconhecido pelos rostos da chamada" in h)

        print("\nRetirar apaga o rosto\n")
        h = cli.get(f"/chamada-foto/configuracao?academia_id={ACADEMIA}").get_data(as_text=True)
        cli.post(f"/chamada-foto/aluno/{ids['adulto']}/termo-papel?academia_id={ACADEMIA}",
                 data={"csrf_token": _token(h), "status": "recusou"})
        n = _contar("SELECT COUNT(*) FROM chamada_foto_rosto WHERE aluno_id=%s", (ids["adulto"],))
        checar("22. ao recusar, o rosto some daqui e da AWS",
               n == 0 and any(f.startswith(f"face-{ids['adulto']}-") for f in aws.apagados), f"{n} {aws.apagados}")
        r = cli.post(f"/chamada-foto/aluno/{ids['vizinho']}/termo-papel?academia_id={ACADEMIA}",
                     data={"csrf_token": _token(h), "status": "recusou"}, follow_redirects=True).get_data(as_text=True)
        checar("23. gestão não lança termo de aluno de outra academia", "não encontrado nesta academia" in r)

        print("\nPedido pelo WhatsApp e termo\n")
        from utils import whatsapp as wpp
        enviados = []
        original = wpp.enviar
        c, cur = _conn()
        cur.execute("UPDATE alunos SET tel_celular='81977770009' WHERE id=%s", (ids["recusou"],))
        c.commit(); cur.close(); c.close()
        wpp.enviar = lambda academia_id, telefone, texto, **kw: (enviados.append(texto) or (True, {}))
        try:
            cli.post(f"/chamada-foto/aluno/{ids['recusou']}/pedir?academia_id={ACADEMIA}",
                     data={"csrf_token": _token(h)})
        finally:
            wpp.enviar = original
        checar("24. o pedido leva o link para autorizar",
               len(enviados) == 1 and "/chamada-foto/autorizar" in enviados[0], str(enviados)[:120])
        c, cur = _conn()
        st = cf.status_dos_alunos(cur, [ids["recusou"]]).get(ids["recusou"]) or {}
        cur.close(); c.close()
        checar("25. e registra a data do pedido sem apagar a resposta",
               st.get("pedido_em") is not None and st.get("status") == "recusou", str(st))
        h = cli.get(f"/chamada-foto/termo?academia_id={ACADEMIA}&aluno_id={ids['menor']}").get_data(as_text=True)
        checar("26. o termo sai com o nome do aluno", "ZZ Menor Sem Foto" in h and "Autorizo" in h)
    finally:
        aws.desinstalar()
        limpar()

    print()
    if _falhas:
        print(f"{len(_falhas)} falha(s): {', '.join(_falhas)}")
        sys.exit(1)
    print("Tudo certo.")


if __name__ == "__main__":
    main()
