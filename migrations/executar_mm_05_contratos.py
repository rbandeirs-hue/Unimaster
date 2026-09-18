#!/usr/bin/env python3
"""
MM-05 — Cria os contratos dos alunos ativos e liga as cobranças em aberto.

Passo 5 da evolução. Até aqui a cobrança nascia solta: o sistema olhava o aluno,
o plano e o mês. O contrato é o que amarra os três e permite que um aluno tenha
duas coisas ao mesmo tempo — judô e ginástica, por exemplo — sem que a segunda
vire uma cobrança fantasma da primeira.

Quem ganha contrato:
  • aluno ativo que tenha ao menos uma cobrança registrada (é dela que saem
    plano, valor e dia de vencimento — `alunos.plano_mensalidade_id` está
    praticamente vazio no banco e não serve de fonte);
  • família ativa em `familia_cobranca` vira UM contrato só, cobrindo os alunos
    daquele responsável, porque quem paga é ele. Os demais viram contrato
    individual.

O que é ligado ao contrato:
  SOMENTE cobranças em aberto ou futuras (pendente/atrasado, não pagas).
  Cobrança paga, cancelada ou aguardando aprovação NÃO é tocada — histórico
  financeiro fechado não se reescreve.

Nas cobranças ligadas também são gravados `competencia` e os `snapshot_*`, que
congelam o nome do pacote e as modalidades vigentes naquele momento. Se o pacote
mudar de composição amanhã, a cobrança de hoje continua contando a verdade dela.

Reversível: `--reverter` desfaz as ligações, limpa os contratos criados por este
passo e devolve `matricula_modalidade.contrato_id` a NULL. Cobrança paga nunca
entrou, então nada de histórico é mexido nem na ida nem na volta.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_mm_05_contratos.py            # simula
  .venv/bin/python migrations/executar_mm_05_contratos.py --aplicar
  .venv/bin/python migrations/executar_mm_05_contratos.py --reverter
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

ORIGEM = "mm05"

# `familia_cobranca` está em utf8mb4_unicode_ci e `alunos` em uca1400: comparar
# as duas colunas sem forçar a collation estoura "Illegal mix of collations".
COL = "COLLATE utf8mb4_unicode_ci"
CPF_ALUNO = (f"REPLACE(REPLACE(REPLACE(COALESCE(a.responsavel_financeiro_cpf,''),"
             f"'.',''),'-',''),' ','') {COL}")

# Situações que contam como cobrança em aberto. Tudo que não estiver aqui fica
# intocado.
ABERTAS = ("status IN ('pendente','atrasado') "
           "AND status_pagamento IN ('pendente','rejeitado')")

SQL_ALUNOS = f"""
SELECT a.id, a.nome, a.id_academia, a.data_matricula,
       a.responsavel_financeiro_nome, {CPF_ALUNO} AS cpf_resp,
       (SELECT ma.mensalidade_id FROM mensalidade_aluno ma
         WHERE ma.aluno_id = a.id AND ma.status <> 'cancelado'
         ORDER BY ma.data_vencimento DESC, ma.id DESC LIMIT 1) AS plano_id,
       (SELECT ma.valor FROM mensalidade_aluno ma
         WHERE ma.aluno_id = a.id AND ma.status <> 'cancelado'
         ORDER BY ma.data_vencimento DESC, ma.id DESC LIMIT 1) AS valor,
       (SELECT DAY(ma.data_vencimento) FROM mensalidade_aluno ma
         WHERE ma.aluno_id = a.id AND ma.status <> 'cancelado'
         ORDER BY ma.data_vencimento DESC, ma.id DESC LIMIT 1) AS dia_venc,
       (SELECT MIN(ma.data_vencimento) FROM mensalidade_aluno ma
         WHERE ma.aluno_id = a.id AND ma.status <> 'cancelado') AS primeira_venc
FROM alunos a
WHERE a.status = 'ativo'
ORDER BY a.id_academia, a.id
"""

SQL_FAMILIAS = f"""
SELECT id, id_academia, responsavel_cpf {COL} AS cpf, responsavel_nome
FROM familia_cobranca WHERE ativo = 1
"""


def _modalidades_do_plano(cur, plano_id):
    cur.execute(
        """SELECT mm.modalidade_id, md.nome, mm.principal
           FROM mensalidade_modalidade mm JOIN modalidade md ON md.id = mm.modalidade_id
           WHERE mm.mensalidade_id = %s ORDER BY mm.principal DESC, md.id""",
        (plano_id,))
    return cur.fetchall() or []


def _ja_tem_contrato(cur, tipo, dados):
    """Este passo pode ser rodado de novo conforme o cadastro dos alunos avança;
    quem já ganhou contrato fica de fora para não duplicar."""
    if tipo == "familia":
        cur.execute(
            f"""SELECT id FROM contrato
                 WHERE origem = %s AND status <> 'cancelado'
                   AND id_academia = %s
                   AND responsavel_cpf {COL} = %s""",
            (ORIGEM, dados["id_academia"], dados["cpf"]))
    else:
        cur.execute(
            """SELECT id FROM contrato
                WHERE origem = %s AND status <> 'cancelado'
                  AND titular_aluno_id = %s""",
            (ORIGEM, dados["titular"]))
    return cur.fetchone() is not None


def _criar_contrato(cur, dados):
    cur.execute(
        """INSERT INTO contrato
             (id_academia, mensalidade_id, titular_aluno_id, responsavel_cpf,
              responsavel_nome, valor, dia_vencimento, periodicidade,
              data_inicio, status, origem)
           VALUES (%s,%s,%s,%s,%s,%s,%s,'mensal',%s,'ativo',%s)""",
        (dados["id_academia"], dados["plano_id"], dados["titular"],
         dados["cpf"], dados["nome_resp"], dados["valor"], dados["dia_venc"],
         dados["data_inicio"], ORIGEM))
    return cur.lastrowid


def _criar_itens(cur, contrato_id, aluno, plano_id, valor, modalidades):
    """Um item por modalidade do pacote. O preço fica no item principal: o
    pacote tem um preço só, e dividir por modalidade seria inventar número."""
    if not modalidades:
        cur.execute(
            """INSERT IGNORE INTO contrato_item
                 (contrato_id, aluno_id, modalidade_id, mensalidade_id, valor)
               VALUES (%s,%s,NULL,%s,%s)""",
            (contrato_id, aluno, plano_id, valor))
        return
    for pos, m in enumerate(modalidades):
        cur.execute(
            """INSERT IGNORE INTO contrato_item
                 (contrato_id, aluno_id, modalidade_id, mensalidade_id, valor)
               VALUES (%s,%s,%s,%s,%s)""",
            (contrato_id, aluno, m["modalidade_id"], plano_id,
             valor if pos == 0 else 0))


def _criar_rateio(cur, contrato_id, aluno, valor, total, modalidades):
    """Quanto do contrato é de cada aluno. A modalidade só é apontada quando o
    plano cobre uma; em pacote fica NULL, porque o valor não se separa."""
    mod_id = modalidades[0]["modalidade_id"] if len(modalidades) == 1 else None
    percentual = (float(valor) / float(total) * 100) if total else None
    cur.execute(
        """INSERT INTO contrato_rateio
             (contrato_id, contrato_item_id, aluno_id, modalidade_id,
              percentual, valor)
           VALUES (%s, NULL, %s, %s, %s, %s)""",
        (contrato_id, aluno, mod_id, percentual, valor))


def _ligar_cobrancas(cur, contrato_id, aluno, plano_id, modalidades):
    nomes = ", ".join(m["nome"] for m in modalidades) or None
    cur.execute("SELECT nome FROM mensalidades WHERE id = %s", (plano_id,))
    linha = cur.fetchone()
    pacote = linha["nome"] if linha else None
    cur.execute(
        f"""UPDATE mensalidade_aluno
               SET contrato_id = %s,
                   -- CONCAT no lugar de DATE_FORMAT: o '%%' do formato chega
                   -- ao MySQL como '%%' literal e gravaria a string '%Y-%m'.
                   competencia = CONCAT(YEAR(data_vencimento), '-',
                                        LPAD(MONTH(data_vencimento), 2, '0')),
                   snapshot_pacote_nome = COALESCE(snapshot_pacote_nome, %s),
                   snapshot_modalidades = COALESCE(snapshot_modalidades, %s)
             WHERE aluno_id = %s AND mensalidade_id = %s
               AND contrato_id IS NULL AND {ABERTAS}""",
        (contrato_id, pacote, nomes, aluno, plano_id))
    return cur.rowcount


def aplicar(simular=True):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(SQL_FAMILIAS)
        familias = {(f["id_academia"], f["cpf"]): f for f in cur.fetchall() or []}

        cur.execute(SQL_ALUNOS)
        alunos = cur.fetchall() or []

        elegiveis = [a for a in alunos if a["plano_id"]]
        sem_plano = [a for a in alunos if not a["plano_id"]]

        # Agrupa por família; quem não está em família ativa fica sozinho.
        grupos = {}
        for a in elegiveis:
            chave = (a["id_academia"], a["cpf_resp"])
            fam = familias.get(chave) if a["cpf_resp"] else None
            grupos.setdefault(("familia", fam["id"]) if fam else ("aluno", a["id"]),
                              []).append(a)

        contratos = itens = ligadas = repetidos = 0
        for (tipo, ref), membros in sorted(grupos.items()):
            total = sum(float(m["valor"] or 0) for m in membros)
            primeiro = membros[0]
            if tipo == "familia":
                fam = next(f for f in familias.values() if f["id"] == ref)
                rotulo = f"família {fam['responsavel_nome'] or fam['cpf']}"
                dados = {"id_academia": fam["id_academia"], "titular": None,
                         "cpf": fam["cpf"], "nome_resp": fam["responsavel_nome"]}
            else:
                rotulo = primeiro["nome"][:32]
                dados = {"id_academia": primeiro["id_academia"],
                         "titular": primeiro["id"], "cpf": primeiro["cpf_resp"],
                         "nome_resp": primeiro["responsavel_financeiro_nome"]}
            dados.update({
                "plano_id": primeiro["plano_id"], "valor": total,
                "dia_venc": primeiro["dia_venc"],
                "data_inicio": primeiro["primeira_venc"] or primeiro["data_matricula"],
            })

            if tipo == "familia" or len(membros) > 1:
                print(f"  ▣ {rotulo}  R$ {total:.2f}  "
                      f"{len(membros)} aluno(s): "
                      + ", ".join(m["nome"].split()[0] for m in membros))

            if _ja_tem_contrato(cur, tipo, dados):
                repetidos += 1
                continue

            contratos += 1
            if simular:
                for m in membros:
                    itens += max(1, len(_modalidades_do_plano(cur, m["plano_id"])))
                continue

            contrato_id = _criar_contrato(cur, dados)
            for m in membros:
                modalidades = _modalidades_do_plano(cur, m["plano_id"])
                _criar_itens(cur, contrato_id, m["id"], m["plano_id"],
                             m["valor"] or 0, modalidades)
                itens += cur.rowcount
                _criar_rateio(cur, contrato_id, m["id"], m["valor"] or 0,
                              total, modalidades)
                ligadas += _ligar_cobrancas(cur, contrato_id, m["id"],
                                            m["plano_id"], modalidades)
                # A matrícula de modalidade passa a apontar para o contrato.
                for mod in modalidades:
                    cur.execute(
                        """UPDATE matricula_modalidade SET contrato_id = %s
                            WHERE aluno_id = %s AND modalidade_id = %s
                              AND contrato_id IS NULL""",
                        (contrato_id, m["id"], mod["modalidade_id"]))

        if simular:
            conn.rollback()
            print(f"\nSIMULAÇÃO — {contratos} contrato(s) para "
                  f"{len(elegiveis)} aluno(s) ativo(s). "
                  "Rode com --aplicar para valer.")
        else:
            conn.commit()
            print(f"\n✓ {contratos} contrato(s), {itens} item(ns) e "
                  f"{ligadas} cobrança(s) em aberto ligadas.")
        if repetidos:
            print(f"• {repetidos} grupo(s) já tinham contrato e foram mantidos "
                  "como estavam.")

        # Divergência que só aparece agora que plano e modalidade se olham:
        # o aluno está matriculado numa modalidade e cobrado por outra.
        cur.execute(
            """SELECT a.id, a.nome, a.id_academia,
                      (SELECT GROUP_CONCAT(md.nome) FROM matricula_modalidade mm
                        JOIN modalidade md ON md.id = mm.modalidade_id
                       WHERE mm.aluno_id = a.id) AS matriculado,
                      (SELECT GROUP_CONCAT(DISTINCT m.nome) FROM contrato_item ci
                        JOIN mensalidades m ON m.id = ci.mensalidade_id
                       WHERE ci.aluno_id = a.id) AS plano
               FROM alunos a
               WHERE EXISTS (SELECT 1 FROM contrato_item ci WHERE ci.aluno_id = a.id)
                 AND NOT EXISTS (SELECT 1 FROM matricula_modalidade mm
                                  WHERE mm.aluno_id = a.id AND mm.contrato_id IS NOT NULL)""")
        divergentes = cur.fetchall() or []
        if divergentes:
            print(f"\n⚠ {len(divergentes)} aluno(s) matriculados numa modalidade e "
                  "cobrados por plano de outra — conferir com a academia:")
            for d in divergentes:
                print(f"    id={d['id']:4} {d['nome'][:30]:30} matriculado em "
                      f"{d['matriculado']} · plano {d['plano']}")

        if sem_plano:
            print(f"\n⚠ {len(sem_plano)} aluno(s) ativo(s) sem nenhuma cobrança "
                  "registrada ficaram sem contrato (nada em que se basear):")
            for a in sem_plano[:20]:
                print(f"    id={a['id']:4} {a['nome'][:32]:32} academia {a['id_academia']}")
            if len(sem_plano) > 20:
                print(f"    ... e mais {len(sem_plano) - 20}")
        return contratos
    except Exception as e:
        conn.rollback()
        print("Erro:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


def reverter():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """UPDATE mensalidade_aluno ma
               JOIN contrato c ON c.id = ma.contrato_id
                  SET ma.contrato_id = NULL, ma.competencia = NULL,
                      ma.snapshot_pacote_nome = NULL, ma.snapshot_modalidades = NULL
                WHERE c.origem = %s""", (ORIGEM,))
        print(f"✓ {cur.rowcount} cobrança(s) desligadas do contrato.")
        cur.execute(
            """UPDATE matricula_modalidade mm
               JOIN contrato c ON c.id = mm.contrato_id
                  SET mm.contrato_id = NULL
                WHERE c.origem = %s""", (ORIGEM,))
        print(f"✓ {cur.rowcount} matrícula(s) de modalidade desligadas.")
        # itens e rateios saem em cascata com o contrato.
        cur.execute("DELETE FROM contrato WHERE origem = %s", (ORIGEM,))
        n = cur.rowcount
        conn.commit()
        print(f"✓ {n} contrato(s) removidos.")
        return n
    except Exception as e:
        conn.rollback()
        print("Erro na reversão:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    if "--reverter" in sys.argv:
        reverter()
    else:
        aplicar(simular="--aplicar" not in sys.argv)
