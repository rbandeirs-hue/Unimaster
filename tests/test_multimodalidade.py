"""Testes da multimodalidade: contexto, recortes e contratos.

Rodam contra o banco real, dentro de uma academia de teste com id negativo que
é criada e removida a cada execução — nenhum dado de produção é tocado.

Uso:  PYTHONPATH=. .venv/bin/python tests/test_multimodalidade.py
"""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app                                    # noqa: E402
from config import get_db_connection                   # noqa: E402
from utils import multimodalidade as mm                 # noqa: E402

ACADEMIA = -9998            # id negativo: não colide com academia real
OUTRA = -9997               # segunda academia, para provar que nada vaza
PREFIXO = "ZZ Teste MM "    # `modalidade.nome` é único; o prefixo evita colisão
HOJE = date.today()
_falhas = []
ids = {}


def _conn():
    c = get_db_connection()
    return c, c.cursor(dictionary=True)


def checar(nome, condicao, detalhe=""):
    print(("  PASSOU  " if condicao else "  FALHOU  ") + nome
          + (f"  [{detalhe}]" if detalhe and not condicao else ""))
    if not condicao:
        _falhas.append(nome)


# ------------------------------------------------------------------
# Cenário
# ------------------------------------------------------------------
def limpar():
    c, cur = _conn()
    cur.execute("SELECT id FROM alunos WHERE id_academia IN (%s, %s)", (ACADEMIA, OUTRA))
    alunos = [r["id"] for r in cur.fetchall() or []]
    if alunos:
        ph = ",".join(["%s"] * len(alunos))
        for t in ("matricula_modalidade", "aluno_modalidades", "mensalidade_aluno"):
            cur.execute(f"DELETE FROM {t} WHERE aluno_id IN ({ph})", tuple(alunos))
    cur.execute("SELECT TurmaID FROM turmas WHERE id_academia IN (%s, %s)", (ACADEMIA, OUTRA))
    turmas = [r["TurmaID"] for r in cur.fetchall() or []]
    if turmas:
        ph = ",".join(["%s"] * len(turmas))
        cur.execute(f"DELETE FROM turma_modalidades WHERE turma_id IN ({ph})", tuple(turmas))
    cur.execute("DELETE FROM contrato WHERE id_academia IN (%s, %s)", (ACADEMIA, OUTRA))
    # O serviço de contratos audita cada alteração: a trilha do teste não pode
    # ficar misturada com a das academias de verdade.
    cur.execute("DELETE FROM fin_auditoria WHERE id_academia IN (%s, %s)", (ACADEMIA, OUTRA))
    cur.execute("DELETE FROM turmas WHERE id_academia IN (%s, %s)", (ACADEMIA, OUTRA))
    cur.execute("DELETE FROM alunos WHERE id_academia IN (%s, %s)", (ACADEMIA, OUTRA))
    cur.execute("SELECT id FROM mensalidades WHERE nome LIKE %s", (PREFIXO + "%",))
    planos = [r["id"] for r in cur.fetchall() or []]
    if planos:
        ph = ",".join(["%s"] * len(planos))
        cur.execute(f"DELETE FROM mensalidade_modalidade WHERE mensalidade_id IN ({ph})", tuple(planos))
        cur.execute(f"DELETE FROM mensalidades WHERE id IN ({ph})", tuple(planos))
    cur.execute("DELETE FROM academia_modalidades WHERE academia_id IN (%s, %s)", (ACADEMIA, OUTRA))
    cur.execute("DELETE FROM modalidade WHERE nome LIKE %s", (PREFIXO + "%",))
    cur.execute("DELETE FROM academias WHERE id IN (%s, %s)", (ACADEMIA, OUTRA))
    c.commit(); cur.close(); c.close()
    mm.invalidar()


def montar():
    """Duas modalidades numa academia, uma na outra; alunos, turmas e planos."""
    c, cur = _conn()

    # As academias precisam existir de verdade: `academia_modalidades` tem
    # chave estrangeira. Id negativo continua garantindo que não é academia real.
    for aid, nome in ((ACADEMIA, "Academia teste MM"), (OUTRA, "Academia teste MM 2")):
        cur.execute("INSERT INTO academias (id, nome) VALUES (%s, %s)", (aid, nome))

    for nome in ("Judo", "Ginastica"):
        cur.execute("INSERT INTO modalidade (nome, ativo) VALUES (%s, 1)", (PREFIXO + nome,))
        ids[nome] = cur.lastrowid
    cur.execute("INSERT INTO academia_modalidades (academia_id, modalidade_id) VALUES (%s,%s)",
                (ACADEMIA, ids["Judo"]))
    cur.execute("INSERT INTO academia_modalidades (academia_id, modalidade_id) VALUES (%s,%s)",
                (ACADEMIA, ids["Ginastica"]))
    # A outra academia só dá judô: é ela que prova que o contexto não vaza.
    cur.execute("INSERT INTO academia_modalidades (academia_id, modalidade_id) VALUES (%s,%s)",
                (OUTRA, ids["Judo"]))

    def aluno(nome, academia=ACADEMIA):
        cur.execute("INSERT INTO alunos (nome, id_academia, status) VALUES (%s,%s,'ativo')",
                    (PREFIXO + nome, academia))
        return cur.lastrowid

    ids["a_judo"] = aluno("Judoca")
    ids["a_gin"] = aluno("Ginasta")
    ids["a_ambos"] = aluno("Faz os dois")
    ids["a_trancou"] = aluno("Trancou a ginastica")
    ids["a_sem"] = aluno("Sem modalidade")
    ids["irmao1"] = aluno("Irmao um")
    ids["irmao2"] = aluno("Irmao dois")

    def matricular(aluno_id, modalidade, status="ativa"):
        cur.execute(
            """INSERT INTO matricula_modalidade (aluno_id, modalidade_id, status, origem)
               VALUES (%s,%s,%s,'teste')""", (aluno_id, ids[modalidade], status))

    matricular(ids["a_judo"], "Judo")
    matricular(ids["a_gin"], "Ginastica")
    matricular(ids["a_ambos"], "Judo")
    matricular(ids["a_ambos"], "Ginastica")
    matricular(ids["a_trancou"], "Judo")
    matricular(ids["a_trancou"], "Ginastica", status="encerrada")
    matricular(ids["irmao1"], "Judo")
    matricular(ids["irmao2"], "Judo")

    def turma(nome, modalidade=None):
        cur.execute(
            """INSERT INTO turmas (Nome, DiasHorario, IdadeMin, IdadeMax, Professor,
                                   Classificacao, Capacidade, id_academia)
               VALUES (%s,'Seg 19h',5,99,'Teste','Geral',30,%s)""",
            (PREFIXO + nome, ACADEMIA))
        tid = cur.lastrowid
        if modalidade:
            cur.execute("INSERT INTO turma_modalidades (turma_id, modalidade_id) VALUES (%s,%s)",
                        (tid, ids[modalidade]))
        return tid

    ids["t_judo"] = turma("Turma judo", "Judo")
    ids["t_gin"] = turma("Turma ginastica", "Ginastica")
    ids["t_sem"] = turma("Turma sem modalidade")

    def plano(nome, valor, modalidades):
        cur.execute(
            """INSERT INTO mensalidades (nome, valor, id_academia, ativo, tipo, qtd_min, qtd_max)
               VALUES (%s,%s,%s,1,%s,%s,%s)""",
            (PREFIXO + nome, valor, ACADEMIA,
             "pacote" if len(modalidades) > 1 else "simples",
             len(modalidades), len(modalidades)))
        pid = cur.lastrowid
        for pos, m in enumerate(modalidades):
            cur.execute(
                """INSERT INTO mensalidade_modalidade (mensalidade_id, modalidade_id, principal)
                   VALUES (%s,%s,%s)""", (pid, ids[m], 1 if pos == 0 else 0))
        return pid

    ids["p_judo"] = plano("Plano judo", 100, ["Judo"])
    ids["p_gin"] = plano("Plano ginastica", 120, ["Ginastica"])
    ids["p_combo"] = plano("Plano combo", 180, ["Judo", "Ginastica"])

    def cobranca(aluno_id, plano_id, dia, status="pendente"):
        cur.execute(
            """INSERT INTO mensalidade_aluno
                 (aluno_id, mensalidade_id, data_vencimento, valor, status)
               VALUES (%s,%s,%s,100,%s)""",
            (aluno_id, plano_id, date(HOJE.year, 6, dia), status))
        return cur.lastrowid

    ids["c_judo"] = cobranca(ids["a_judo"], ids["p_judo"], 10)
    ids["c_gin"] = cobranca(ids["a_gin"], ids["p_gin"], 10)
    ids["c_combo"] = cobranca(ids["a_ambos"], ids["p_combo"], 10)
    ids["c_paga"] = cobranca(ids["a_judo"], ids["p_judo"], 10, status="pago")

    c.commit(); cur.close(); c.close()
    mm.invalidar()


def um(sql, params=()):
    c, cur = _conn()
    try:
        cur.execute(sql, params)
        r = cur.fetchone()
        return list(r.values())[0] if r else None
    finally:
        cur.close(); c.close()


def contar_alunos(modalidade_id=None):
    trecho, ps = mm.filtro_alunos_sql("a", ACADEMIA, modalidade_id)
    return um(f"SELECT COUNT(*) FROM alunos a WHERE a.id_academia = %s{trecho}",
              (ACADEMIA,) + tuple(ps))


def contar_turmas(modalidade_id=None):
    trecho, ps = mm.filtro_turmas_sql("t", ACADEMIA, modalidade_id)
    return um(f"SELECT COUNT(*) FROM turmas t WHERE t.id_academia = %s{trecho}",
              (ACADEMIA,) + tuple(ps))


def contar_cobrancas(modalidade_id=None):
    trecho, ps = mm.filtro_cobrancas_sql("ma", ACADEMIA, modalidade_id)
    return um(f"""SELECT COUNT(*) FROM mensalidade_aluno ma
                  JOIN alunos a ON a.id = ma.aluno_id
                  WHERE a.id_academia = %s{trecho}""", (ACADEMIA,) + tuple(ps))


# ------------------------------------------------------------------
# Cenários
# ------------------------------------------------------------------
def main():
    limpar()
    montar()
    judo, gin = ids["Judo"], ids["Ginastica"]

    # --- o contexto em si ---------------------------------------------
    checar("1. academia com duas modalidades oferece contexto",
           mm.multimodal(ACADEMIA))
    checar("2. academia com uma modalidade não oferece contexto",
           not mm.multimodal(OUTRA))
    checar("3. as modalidades vêm da academia, não do sistema todo",
           {m["id"] for m in mm.modalidades_da_academia(ACADEMIA)} == {judo, gin})

    with app.test_request_context("/"):
        from flask import session
        session["academia_gerenciamento_id"] = ACADEMIA
        checar("4. sem escolha, o contexto é Todas", mm.contexto_id() is None)
        mm.definir_contexto(judo)
        checar("5. escolha válida é guardada", mm.contexto_id() == judo)
        checar("6. o nome do contexto acompanha a escolha",
               mm.nome_contexto() == PREFIXO + "Judo")
        mm.definir_contexto("")
        checar("7. escolha vazia volta para Todas", mm.contexto_id() is None)
        mm.definir_contexto(999999)
        checar("8. modalidade inexistente não vira contexto", mm.contexto_id() is None)
        # O vazamento entre academias: o contexto de ginástica não pode
        # sobreviver a uma troca para a academia que só dá judô.
        mm.definir_contexto(gin)
        session["academia_gerenciamento_id"] = OUTRA
        checar("9. contexto não vaza para academia que não tem a modalidade",
               mm.contexto_id() is None)

    # --- recorte de alunos --------------------------------------------
    checar("10. sem contexto, a lista de alunos é a de sempre",
           contar_alunos() == 7, str(contar_alunos()))
    checar("11. contexto de judô traz só quem faz judô",
           contar_alunos(judo) == 5, str(contar_alunos(judo)))
    checar("12. contexto de ginástica traz só quem faz ginástica",
           contar_alunos(gin) == 2, str(contar_alunos(gin)))
    checar("13. aluno de duas modalidades aparece nos dois contextos",
           um("""SELECT COUNT(*) FROM matricula_modalidade
                 WHERE aluno_id = %s AND status = 'ativa'""", (ids["a_ambos"],)) == 2)
    checar("14. matrícula encerrada sai do recorte",
           um("""SELECT COUNT(*) FROM alunos a WHERE a.id = %s AND EXISTS(
                   SELECT 1 FROM matricula_modalidade mm WHERE mm.aluno_id = a.id
                   AND mm.modalidade_id = %s AND mm.status = 'ativa')""",
              (ids["a_trancou"], gin)) == 0)
    checar("15. aluno sem modalidade não é atribuído a nenhuma",
           um("""SELECT COUNT(*) FROM matricula_modalidade WHERE aluno_id = %s""",
              (ids["a_sem"],)) == 0)

    # --- turmas e pendências ------------------------------------------
    checar("16. contexto recorta as turmas",
           contar_turmas(judo) == 1 and contar_turmas(gin) == 1 and contar_turmas() == 3,
           f"{contar_turmas(judo)}/{contar_turmas(gin)}/{contar_turmas()}")
    pend = mm.pendencias(ACADEMIA)
    checar("17. o que não tem modalidade é contado, não escondido",
           pend["alunos"] == 1 and pend["turmas"] == 1, str(pend))

    # --- financeiro ----------------------------------------------------
    checar("18. cobrança de plano simples só entra na sua modalidade",
           contar_cobrancas(judo) == 3 and contar_cobrancas(gin) == 2,
           f"judo={contar_cobrancas(judo)} gin={contar_cobrancas(gin)}")
    checar("19. pacote multimodalidade aparece nas duas, sem virar duas cobranças",
           um("""SELECT COUNT(*) FROM mensalidade_aluno WHERE aluno_id = %s""",
              (ids["a_ambos"],)) == 1)

    # --- contratos e a trava de duplicidade ----------------------------
    c, cur = _conn()
    cur.execute(
        """INSERT INTO contrato (id_academia, mensalidade_id, titular_aluno_id,
                                 valor, status, origem)
           VALUES (%s,%s,%s,100,'ativo','teste')""",
        (ACADEMIA, ids["p_judo"], ids["a_judo"]))
    contrato_ind = cur.lastrowid
    # O item é o que liga aluno e contrato; sem ele o contrato existe mas não
    # cobre ninguém, e a geração não teria como encontrá-lo.
    cur.execute(
        """INSERT INTO contrato_item (contrato_id, aluno_id, modalidade_id,
                                      mensalidade_id, valor)
           VALUES (%s,%s,%s,%s,100)""",
        (contrato_ind, ids["a_judo"], ids["Judo"], ids["p_judo"]))
    cur.execute("UPDATE mensalidade_aluno SET contrato_id = %s, competencia = %s WHERE id = %s",
                (contrato_ind, "2026-06", ids["c_judo"]))
    c.commit()

    duplicou = True
    try:
        cur.execute(
            """INSERT INTO mensalidade_aluno
                 (aluno_id, mensalidade_id, data_vencimento, valor, contrato_id, competencia)
               VALUES (%s,%s,%s,100,%s,'2026-06')""",
            (ids["a_judo"], ids["p_judo"], date(HOJE.year, 6, 20), contrato_ind))
        c.commit()
    except Exception:
        c.rollback()
        duplicou = False
    checar("20. banco recusa duas cobranças do mesmo contrato na mesma competência",
           not duplicou)

    # Família: um contrato, dois irmãos, mesma competência — tem de passar.
    cur.execute(
        """INSERT INTO contrato (id_academia, mensalidade_id, titular_aluno_id,
                                 responsavel_cpf, valor, status, origem)
           VALUES (%s,%s,NULL,'00000000000',200,'ativo','teste')""",
        (ACADEMIA, ids["p_judo"]))
    contrato_fam = cur.lastrowid
    for irmao in ("irmao1", "irmao2"):
        cur.execute(
            """INSERT INTO contrato_item (contrato_id, aluno_id, modalidade_id,
                                          mensalidade_id, valor)
               VALUES (%s,%s,%s,%s,100)""",
            (contrato_fam, ids[irmao], ids["Judo"], ids["p_judo"]))
    familia_ok = True
    try:
        for irmao in ("irmao1", "irmao2"):
            cur.execute(
                """INSERT INTO mensalidade_aluno
                     (aluno_id, mensalidade_id, data_vencimento, valor,
                      contrato_id, competencia)
                   VALUES (%s,%s,%s,100,%s,'2026-06')""",
                (ids[irmao], ids["p_judo"], date(HOJE.year, 6, 10), contrato_fam))
        c.commit()
    except Exception as e:
        c.rollback()
        familia_ok = False
        print("      erro:", e)
    checar("21. contrato de família aceita um irmão por vez na mesma competência",
           familia_ok)

    cur.execute("""SELECT COUNT(*) AS n FROM mensalidade_aluno
                   WHERE contrato_id = %s""", (contrato_fam,))
    checar("22. os dois irmãos ficam no mesmo contrato",
           (cur.fetchone() or {}).get("n") == 2)

    cur.close(); c.close()

    # --- histórico intocado --------------------------------------------
    checar("23. cobrança paga continua sem contrato",
           um("SELECT contrato_id FROM mensalidade_aluno WHERE id = %s",
              (ids["c_paga"],)) is None)

    # --- geração mensal amarrada ao contrato ---------------------------
    from blueprints.financeiro.routes import _gerar_mensalidades_mes

    with app.test_request_context("/"):
        geradas, _pulados = _gerar_mensalidades_mes(ACADEMIA, HOJE.year, 7)
    checar("24. a geração do mês continua gerando", geradas > 0, str(geradas))

    novas = um("""SELECT COUNT(*) FROM mensalidade_aluno ma
                  JOIN alunos a ON a.id = ma.aluno_id
                  WHERE a.id_academia = %s AND MONTH(ma.data_vencimento) = 7
                    AND ma.contrato_id IS NOT NULL""", (ACADEMIA,))
    checar("25. cobrança gerada nasce ligada ao contrato do aluno", novas > 0, str(novas))

    checar("26. a competência é gravada de verdade, não como texto de formato",
           um("""SELECT COUNT(*) FROM mensalidade_aluno ma
                 JOIN alunos a ON a.id = ma.aluno_id
                 WHERE a.id_academia = %s AND ma.competencia IS NOT NULL
                   AND ma.competencia NOT REGEXP '^[0-9]{4}-[0-9]{2}$'""",
              (ACADEMIA,)) == 0)

    checar("27. o retrato do pacote é gravado junto",
           um("""SELECT COUNT(*) FROM mensalidade_aluno ma
                 JOIN alunos a ON a.id = ma.aluno_id
                 WHERE a.id_academia = %s AND MONTH(ma.data_vencimento) = 7
                   AND ma.contrato_id IS NOT NULL
                   AND ma.snapshot_pacote_nome IS NULL""", (ACADEMIA,)) == 0)

    # Rodar de novo não pode gerar a segunda cobrança do mesmo mês.
    antes = um("""SELECT COUNT(*) FROM mensalidade_aluno ma
                  JOIN alunos a ON a.id = ma.aluno_id
                  WHERE a.id_academia = %s AND MONTH(ma.data_vencimento) = 7""",
               (ACADEMIA,))
    with app.test_request_context("/"):
        _gerar_mensalidades_mes(ACADEMIA, HOJE.year, 7)
    depois = um("""SELECT COUNT(*) FROM mensalidade_aluno ma
                   JOIN alunos a ON a.id = ma.aluno_id
                   WHERE a.id_academia = %s AND MONTH(ma.data_vencimento) = 7""",
                (ACADEMIA,))
    checar("28. gerar duas vezes não duplica a cobrança do mês",
           antes == depois, f"{antes} -> {depois}")

    # --- contratos pelo serviço (o que a tela usa) ----------------------
    from utils import contratos as ct

    cid, erro = ct.salvar(ACADEMIA, {
        "mensalidade_id": ids["p_gin"],
        "alunos": [{"aluno_id": ids["a_gin"], "valor": "120,00"}],
        "dia_vencimento": 10, "status": "ativo",
    })
    checar("29. contrato individual é criado pelo serviço", cid and not erro, str(erro))

    _, erro = ct.salvar(ACADEMIA, {
        "mensalidade_id": ids["p_gin"],
        "alunos": [{"aluno_id": ids["a_gin"], "valor": "120"}],
    })
    checar("30. mesmo aluno no mesmo plano em dois contratos é recusado",
           erro is not None and "dobrada" in (erro or ""), str(erro))

    # Aluno da outra academia não entra: é a trava contra misturar academias.
    c, cur = _conn()
    cur.execute("INSERT INTO alunos (nome, id_academia, status) VALUES (%s,%s,'ativo')",
                (PREFIXO + "De outra academia", OUTRA))
    forasteiro = cur.lastrowid
    c.commit(); cur.close(); c.close()
    _, erro = ct.salvar(ACADEMIA, {
        "mensalidade_id": ids["p_judo"],
        "alunos": [{"aluno_id": forasteiro, "valor": "100"}],
    })
    checar("31. aluno de outra academia não entra no contrato",
           erro is not None and "desta academia" in (erro or ""), str(erro))

    _, erro = ct.salvar(ACADEMIA, {"mensalidade_id": ids["p_judo"], "alunos": []})
    checar("32. contrato sem aluno é recusado", erro is not None)

    _, erro = ct.salvar(ACADEMIA, {
        "mensalidade_id": ids["p_judo"], "dia_vencimento": 45,
        "alunos": [{"aluno_id": ids["a_sem"], "valor": "100"}],
    })
    checar("33. dia de vencimento fora de 1 a 31 é recusado", erro is not None)

    # Família: dois alunos, um contrato, valor somado e rateio conferindo.
    fam_id, erro = ct.salvar(ACADEMIA, {
        "mensalidade_id": ids["p_combo"], "familia": True,
        "responsavel_nome": "Responsavel teste", "responsavel_cpf": "123.456.789-00",
        "alunos": [{"aluno_id": ids["a_ambos"], "valor": "180,00"},
                   {"aluno_id": ids["a_sem"], "valor": "150,00"}],
        "dia_vencimento": 5,
    })
    checar("34. contrato de família com dois alunos é criado", fam_id and not erro, str(erro))
    checar("35. o valor do contrato é a soma dos alunos",
           float(um("SELECT valor FROM contrato WHERE id=%s", (fam_id,)) or 0) == 330.0,
           str(um("SELECT valor FROM contrato WHERE id=%s", (fam_id,))))
    checar("36. o rateio fecha com o valor do contrato",
           float(um("SELECT COALESCE(SUM(valor),0) FROM contrato_rateio WHERE contrato_id=%s",
                    (fam_id,)) or 0) == 330.0)
    checar("37. o CPF do responsável é guardado só com dígitos",
           um("SELECT responsavel_cpf FROM contrato WHERE id=%s", (fam_id,)) == "12345678900")
    checar("38. pacote de duas modalidades gera um item por modalidade",
           um("SELECT COUNT(*) FROM contrato_item WHERE contrato_id=%s AND aluno_id=%s",
              (fam_id, ids["a_ambos"])) == 2)

    # Encerrar não pode mexer em cobrança nenhuma.
    cobrancas_antes = um("SELECT COUNT(*) FROM mensalidade_aluno WHERE contrato_id=%s", (cid,))
    ok, erro = ct.alterar_status(cid, ACADEMIA, "encerrado")
    checar("39. encerrar contrato funciona", ok and not erro, str(erro))
    checar("40. encerrar não mexe nas cobranças já emitidas",
           um("SELECT COUNT(*) FROM mensalidade_aluno WHERE contrato_id=%s", (cid,))
           == cobrancas_antes)
    checar("41. encerrar o contrato encerra os itens",
           um("""SELECT COUNT(*) FROM contrato_item
                 WHERE contrato_id=%s AND status <> 'encerrado'""", (cid,)) == 0)

    checar("42. cada alteração deixa rastro em fin_auditoria",
           um("""SELECT COUNT(*) FROM fin_auditoria
                 WHERE entidade='contrato' AND entidade_id=%s""", (cid,)) >= 2)

    # Contrato encerrado libera o aluno para um contrato novo do mesmo plano.
    novo_id, erro = ct.salvar(ACADEMIA, {
        "mensalidade_id": ids["p_gin"],
        "alunos": [{"aluno_id": ids["a_gin"], "valor": "130"}],
    })
    checar("43. com o anterior encerrado, o aluno pode ter contrato novo",
           novo_id and not erro, str(erro))

    c, cur = _conn()
    cur.execute("DELETE FROM alunos WHERE id = %s", (forasteiro,))
    c.commit(); cur.close(); c.close()

    limpar()
    print()
    if _falhas:
        print(f"{len(_falhas)} falha(s): " + ", ".join(_falhas))
        sys.exit(1)
    print("Todos os cenários passaram.")


if __name__ == "__main__":
    main()
