# -*- coding: utf-8 -*-
"""Contratos: o acordo que liga aluno, pacote e cobrança.

Antes da multimodalidade a cobrança nascia solta — o sistema olhava o aluno, o
plano e o mês e replicava a última. Funcionava enquanto cada aluno fazia uma
coisa só. O contrato é o que permite ao mesmo aluno ter judô e ginástica ao
mesmo tempo sem que a segunda vire uma cobrança duplicada da primeira, e é o que
permite ao responsável ter UM contrato cobrindo dois filhos.

Regras que valem aqui e não no navegador (o formulário pode ser burlado):

  • todo aluno do contrato tem de ser da mesma academia do contrato;
  • o contrato precisa de pelo menos um aluno;
  • o mesmo aluno não entra duas vezes no mesmo plano em contratos ativos —
    seria cobrança dobrada;
  • dia de vencimento entre 1 e 31;
  • dinheiro é Decimal, nunca float: centavo somado em float vira dízima.

Toda alteração fica em `fin_auditoria`, a mesma trilha do resto do financeiro.
"""
from decimal import Decimal, InvalidOperation

from config import get_db_connection

ENTIDADE = "contrato"
STATUS_VALIDOS = ("ativo", "suspenso", "encerrado", "cancelado")


def _dec(valor, padrao="0"):
    """Decimal tolerante ao que vem de formulário: '1.234,56' ou '1234.56'."""
    if isinstance(valor, Decimal):
        return valor
    texto = str(valor if valor is not None else padrao).strip()
    if not texto:
        texto = padrao
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return Decimal(texto)
    except (InvalidOperation, ValueError):
        return Decimal(padrao)


def _so_digitos(texto):
    return "".join(c for c in (texto or "") if c.isdigit())


def _auditar(cur, academia_id, contrato_id, acao, **campos):
    cur.execute(
        """INSERT INTO fin_auditoria
             (id_academia, entidade, entidade_id, acao, valor_anterior, valor_novo,
              status_anterior, status_novo, motivo, detalhes, usuario_id, ip)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (academia_id, ENTIDADE, contrato_id, acao,
         campos.get("valor_anterior"), campos.get("valor_novo"),
         campos.get("status_anterior"), campos.get("status_novo"),
         campos.get("motivo"), campos.get("detalhes"),
         campos.get("usuario_id"), campos.get("ip")))


# ------------------------------------------------------------------
# Leitura
# ------------------------------------------------------------------
def listar(academia_id, status=None, modalidade_id=None, busca=None):
    """Contratos da academia, cada um já com seus alunos e modalidades."""
    if not academia_id:
        return []
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        where = ["c.id_academia = %s"]
        params = [academia_id]
        if status and status != "todos":
            where.append("c.status = %s")
            params.append(status)
        if modalidade_id:
            where.append("""EXISTS (SELECT 1 FROM contrato_item ci2
                                     WHERE ci2.contrato_id = c.id
                                       AND ci2.modalidade_id = %s)""")
            params.append(modalidade_id)
        if busca:
            where.append("""(c.responsavel_nome LIKE %s OR EXISTS (
                              SELECT 1 FROM contrato_item ci3
                              JOIN alunos a3 ON a3.id = ci3.aluno_id
                              WHERE ci3.contrato_id = c.id AND a3.nome LIKE %s))""")
            params.extend([f"%{busca}%", f"%{busca}%"])

        cur.execute(
            f"""SELECT c.*, m.nome AS plano_nome, m.valor AS plano_valor,
                       t.nome AS titular_nome,
                       (SELECT COUNT(*) FROM mensalidade_aluno ma
                         WHERE ma.contrato_id = c.id) AS cobrancas
                FROM contrato c
                LEFT JOIN mensalidades m ON m.id = c.mensalidade_id
                LEFT JOIN alunos t ON t.id = c.titular_aluno_id
                WHERE {' AND '.join(where)}
                ORDER BY c.status, COALESCE(t.nome, c.responsavel_nome), c.id""",
            tuple(params))
        contratos = cur.fetchall() or []
        if not contratos:
            return []

        ph = ",".join(["%s"] * len(contratos))
        cur.execute(
            f"""SELECT ci.*, a.nome AS aluno_nome, md.nome AS modalidade_nome
                FROM contrato_item ci
                JOIN alunos a ON a.id = ci.aluno_id
                LEFT JOIN modalidade md ON md.id = ci.modalidade_id
                WHERE ci.contrato_id IN ({ph})
                ORDER BY a.nome, md.nome""",
            tuple(c["id"] for c in contratos))
        itens = {}
        for r in cur.fetchall() or []:
            itens.setdefault(r["contrato_id"], []).append(r)

        for c in contratos:
            c["itens"] = itens.get(c["id"], [])
            # Um aluno aparece uma vez por modalidade do pacote; para exibir
            # interessa a pessoa, não a repetição.
            vistos, alunos = set(), []
            for i in c["itens"]:
                if i["aluno_id"] not in vistos:
                    vistos.add(i["aluno_id"])
                    alunos.append({"id": i["aluno_id"], "nome": i["aluno_nome"],
                                   "valor": i["valor"]})
            c["alunos"] = alunos
            c["modalidades"] = sorted({i["modalidade_nome"] for i in c["itens"]
                                       if i["modalidade_nome"]})
            c["familia"] = c["titular_aluno_id"] is None
        return contratos
    finally:
        cur.close()
        conn.close()


def carregar(contrato_id, academia_id=None):
    contratos = listar(academia_id) if academia_id else []
    for c in contratos:
        if c["id"] == contrato_id:
            return c
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM contrato WHERE id = %s", (contrato_id,))
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


def alunos_para_contrato(academia_id):
    """Alunos ativos da academia, com as modalidades em que estão matriculados."""
    if not academia_id:
        return []
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT a.id, a.nome,
                      (SELECT GROUP_CONCAT(md.nome ORDER BY md.nome SEPARATOR ', ')
                         FROM matricula_modalidade mm
                         JOIN modalidade md ON md.id = mm.modalidade_id
                        WHERE mm.aluno_id = a.id AND mm.status = 'ativa') AS modalidades
               FROM alunos a
               WHERE a.id_academia = %s AND a.status = 'ativo'
               ORDER BY a.nome""", (academia_id,))
        return cur.fetchall() or []
    finally:
        cur.close()
        conn.close()


def planos_da_academia(academia_id):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT m.id, m.nome, m.valor, m.tipo,
                      (SELECT GROUP_CONCAT(md.nome ORDER BY mm.principal DESC, md.nome
                                           SEPARATOR ' + ')
                         FROM mensalidade_modalidade mm
                         JOIN modalidade md ON md.id = mm.modalidade_id
                        WHERE mm.mensalidade_id = m.id) AS modalidades
               FROM mensalidades m
               WHERE m.id_academia = %s AND COALESCE(m.ativo, 1) = 1
               ORDER BY m.nome""", (academia_id,))
        return cur.fetchall() or []
    finally:
        cur.close()
        conn.close()


# ------------------------------------------------------------------
# Escrita
# ------------------------------------------------------------------
def _modalidades_do_plano(cur, plano_id):
    cur.execute(
        """SELECT mm.modalidade_id FROM mensalidade_modalidade mm
           WHERE mm.mensalidade_id = %s ORDER BY mm.principal DESC, mm.modalidade_id""",
        (plano_id,))
    return [r["modalidade_id"] if isinstance(r, dict) else r[0]
            for r in cur.fetchall() or []]


def _validar(cur, academia_id, contrato_id, plano_id, alunos):
    """(erro, None) ou (None, alunos normalizados). Erro é texto para o gestor."""
    if not plano_id:
        return "Escolha o plano do contrato.", None
    if not alunos:
        return "O contrato precisa de pelo menos um aluno.", None

    ids = [a["aluno_id"] for a in alunos]
    if len(set(ids)) != len(ids):
        return "O mesmo aluno foi incluído duas vezes.", None

    ph = ",".join(["%s"] * len(ids))
    cur.execute(f"SELECT id, nome, id_academia FROM alunos WHERE id IN ({ph})", tuple(ids))
    encontrados = {r["id"]: r for r in cur.fetchall() or []}
    for aluno_id in ids:
        linha = encontrados.get(aluno_id)
        if not linha:
            return "Aluno não encontrado.", None
        if linha["id_academia"] != academia_id:
            # A trava que impede um contrato de misturar academias.
            return (f"{linha['nome']} não é aluno desta academia.", None)

    # Cobrança dobrada: o mesmo aluno no mesmo plano em outro contrato ativo.
    cur.execute(
        f"""SELECT a.nome FROM contrato_item ci
            JOIN contrato c ON c.id = ci.contrato_id
            JOIN alunos a ON a.id = ci.aluno_id
            WHERE ci.aluno_id IN ({ph}) AND c.mensalidade_id = %s
              AND c.status = 'ativo' AND ci.status = 'ativo'
              AND c.id <> %s
            LIMIT 1""",
        tuple(ids) + (plano_id, contrato_id or 0))
    repetido = cur.fetchone()
    if repetido:
        nome = repetido["nome"] if isinstance(repetido, dict) else repetido[0]
        return (f"{nome} já tem um contrato ativo neste mesmo plano. "
                "Dois contratos do mesmo plano gerariam cobrança dobrada.", None)
    return None, alunos


def salvar(academia_id, dados, usuario_id=None, ip=None):
    """Cria ou atualiza um contrato. Devolve (contrato_id, erro)."""
    contrato_id = dados.get("id") or None
    plano_id = dados.get("mensalidade_id") or None
    alunos = dados.get("alunos") or []
    familia = bool(dados.get("familia"))

    dia = dados.get("dia_vencimento")
    try:
        dia = int(dia) if dia else None
    except (TypeError, ValueError):
        dia = None
    if dia is not None and not (1 <= dia <= 31):
        return None, "O dia de vencimento precisa estar entre 1 e 31."

    status = dados.get("status") or "ativo"
    if status not in STATUS_VALIDOS:
        status = "ativo"

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        erro, alunos = _validar(cur, academia_id, contrato_id, plano_id, alunos)
        if erro:
            return None, erro

        for a in alunos:
            a["valor"] = _dec(a.get("valor"))
        total = sum((a["valor"] for a in alunos), Decimal("0"))

        titular = None if (familia or len(alunos) > 1) else alunos[0]["aluno_id"]
        cpf = _so_digitos(dados.get("responsavel_cpf"))
        nome_resp = (dados.get("responsavel_nome") or "").strip() or None

        if contrato_id:
            cur.execute("SELECT * FROM contrato WHERE id = %s AND id_academia = %s",
                        (contrato_id, academia_id))
            antes = cur.fetchone()
            if not antes:
                return None, "Contrato não encontrado nesta academia."
            cur.execute(
                """UPDATE contrato
                      SET mensalidade_id=%s, titular_aluno_id=%s, responsavel_cpf=%s,
                          responsavel_nome=%s, valor=%s, dia_vencimento=%s,
                          data_inicio=%s, data_fim=%s, status=%s, observacoes=%s
                    WHERE id=%s AND id_academia=%s""",
                (plano_id, titular, cpf or None, nome_resp, total, dia,
                 dados.get("data_inicio") or None, dados.get("data_fim") or None,
                 status, (dados.get("observacoes") or "").strip() or None,
                 contrato_id, academia_id))
            _auditar(cur, academia_id, contrato_id, "editar_contrato",
                     valor_anterior=antes["valor"], valor_novo=total,
                     status_anterior=antes["status"], status_novo=status,
                     motivo="Contrato editado no painel",
                     detalhes=f"{len(alunos)} aluno(s), plano {plano_id}",
                     usuario_id=usuario_id, ip=ip)
        else:
            cur.execute(
                """INSERT INTO contrato
                     (id_academia, mensalidade_id, titular_aluno_id, responsavel_cpf,
                      responsavel_nome, valor, dia_vencimento, periodicidade,
                      data_inicio, data_fim, status, observacoes, origem)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,'mensal',%s,%s,%s,%s,'manual')""",
                (academia_id, plano_id, titular, cpf or None, nome_resp, total, dia,
                 dados.get("data_inicio") or None, dados.get("data_fim") or None,
                 status, (dados.get("observacoes") or "").strip() or None))
            contrato_id = cur.lastrowid
            _auditar(cur, academia_id, contrato_id, "criar_contrato",
                     valor_novo=total, status_novo=status,
                     motivo="Contrato criado no painel",
                     detalhes=f"{len(alunos)} aluno(s), plano {plano_id}",
                     usuario_id=usuario_id, ip=ip)

        # Itens e rateio são reescritos: são a composição do contrato, não
        # histórico. As cobranças já emitidas continuam apontando para o
        # contrato e não são tocadas.
        cur.execute("DELETE FROM contrato_rateio WHERE contrato_id = %s", (contrato_id,))
        cur.execute("DELETE FROM contrato_item WHERE contrato_id = %s", (contrato_id,))

        modalidades = _modalidades_do_plano(cur, plano_id)
        for a in alunos:
            if modalidades:
                for pos, mod_id in enumerate(modalidades):
                    cur.execute(
                        """INSERT INTO contrato_item
                             (contrato_id, aluno_id, modalidade_id, mensalidade_id,
                              valor, status, data_inicio)
                           VALUES (%s,%s,%s,%s,%s,'ativo',%s)""",
                        (contrato_id, a["aluno_id"], mod_id, plano_id,
                         a["valor"] if pos == 0 else Decimal("0"),
                         dados.get("data_inicio") or None))
            else:
                cur.execute(
                    """INSERT INTO contrato_item
                         (contrato_id, aluno_id, modalidade_id, mensalidade_id,
                          valor, status, data_inicio)
                       VALUES (%s,%s,NULL,%s,%s,'ativo',%s)""",
                    (contrato_id, a["aluno_id"], plano_id, a["valor"],
                     dados.get("data_inicio") or None))

            # Rateio: quanto do contrato é de cada aluno. Em pacote a modalidade
            # fica NULL — o valor do combo não se separa entre as modalidades.
            mod_rateio = modalidades[0] if len(modalidades) == 1 else None
            percentual = (a["valor"] / total * 100) if total else None
            cur.execute(
                """INSERT INTO contrato_rateio
                     (contrato_id, contrato_item_id, aluno_id, modalidade_id,
                      percentual, valor)
                   VALUES (%s, NULL, %s, %s, %s, %s)""",
                (contrato_id, a["aluno_id"], mod_rateio, percentual, a["valor"]))

            # A matrícula de modalidade passa a apontar para este contrato.
            for mod_id in modalidades:
                cur.execute(
                    """UPDATE matricula_modalidade SET contrato_id = %s
                        WHERE aluno_id = %s AND modalidade_id = %s
                          AND (contrato_id IS NULL OR contrato_id = %s)""",
                    (contrato_id, a["aluno_id"], mod_id, contrato_id))

        conn.commit()
        return contrato_id, None
    except Exception as e:
        conn.rollback()
        return None, f"Não foi possível salvar o contrato: {e}"
    finally:
        cur.close()
        conn.close()


def alterar_status(contrato_id, academia_id, novo, usuario_id=None, ip=None,
                   motivo=None):
    """Encerra, suspende, cancela ou reativa. Devolve (ok, erro).

    Nada é apagado: encerrar um contrato não mexe em cobrança nenhuma já
    emitida — o que fica no passado continua como está.
    """
    if novo not in STATUS_VALIDOS:
        return False, "Situação inválida."
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM contrato WHERE id = %s AND id_academia = %s",
                    (contrato_id, academia_id))
        antes = cur.fetchone()
        if not antes:
            return False, "Contrato não encontrado nesta academia."
        if antes["status"] == novo:
            return True, None
        cur.execute("UPDATE contrato SET status = %s WHERE id = %s", (novo, contrato_id))
        if novo in ("encerrado", "cancelado"):
            cur.execute(
                "UPDATE contrato_item SET status = 'encerrado' WHERE contrato_id = %s",
                (contrato_id,))
        elif novo == "ativo":
            cur.execute(
                "UPDATE contrato_item SET status = 'ativo' WHERE contrato_id = %s",
                (contrato_id,))
        _auditar(cur, academia_id, contrato_id, "status_contrato",
                 status_anterior=antes["status"], status_novo=novo,
                 valor_anterior=antes["valor"], valor_novo=antes["valor"],
                 motivo=motivo or "Situação alterada no painel",
                 usuario_id=usuario_id, ip=ip)
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, f"Não foi possível alterar a situação: {e}"
    finally:
        cur.close()
        conn.close()
