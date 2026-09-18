# -*- coding: utf-8 -*-
"""Contexto operacional de modalidade.

Uma academia que dá judô, jiu-jitsu e ginástica é três operações dentro de uma:
o professor de ginástica não quer a lista de judô, e o relatório de judô não
deve somar a mensalidade da ginástica. O contexto resolve isso sem separar as
academias — o gestor escolhe uma modalidade e o sistema inteiro passa a
enxergar só aquele recorte.

Como funciona:

  • o contexto vive na sessão, em `modalidade_contexto_id`;
  • "Todas" é o padrão e é sempre uma opção: sem escolha, nada muda em relação
    ao que o sistema já fazia;
  • a escolha é validada contra as modalidades DA ACADEMIA corrente. Trocar de
    academia invalida sozinho um contexto que não exista lá — sem isso, o
    gestor levaria o jiu-jitsu da ArteFísica para dentro de uma academia que só
    dá judô;
  • para academia de uma modalidade só, o seletor nem aparece: não há o que
    escolher.

Os filtros devolvem `(trecho_sql, params)` para serem concatenados na consulta
de quem chama, no mesmo formato de `utils/modalidades.py`. Com "Todas", o
trecho é vazio e a consulta segue idêntica à de antes.

Registro sem modalidade nenhuma NÃO é escondido por engano: ele simplesmente
não pertence a nenhum recorte, e `pendencias()` conta quantos são para a tela
avisar. Some silenciosamente é o que não pode acontecer.
"""
import threading
import time

from config import get_db_connection

CHAVE_SESSAO = "modalidade_contexto_id"
# Vermelho histórico do shell: modalidade sem cor definida segue igual.
COR_PADRAO = "#e4001b"

_TTL_SEGUNDOS = 300
_cache = {}
_lock = threading.Lock()


# ------------------------------------------------------------------
# Quais modalidades a academia oferece
# ------------------------------------------------------------------
def _consultar_modalidades(academia_id):
    """`academia_modalidades` é a fonte; quem não tem lá cai no que os alunos
    realmente praticam, para o seletor não nascer vazio numa academia antiga."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT md.id, md.nome, md.cor
               FROM academia_modalidades am
               JOIN modalidade md ON md.id = am.modalidade_id
               WHERE am.academia_id = %s AND md.ativo = 1
               ORDER BY md.nome""", (academia_id,))
        linhas = cur.fetchall() or []
        if linhas:
            return [{"id": r["id"], "nome": r["nome"],
                     "cor": r.get("cor") or COR_PADRAO} for r in linhas]

        cur.execute(
            """SELECT DISTINCT md.id, md.nome, md.cor
               FROM matricula_modalidade mm
               JOIN alunos a ON a.id = mm.aluno_id
               JOIN modalidade md ON md.id = mm.modalidade_id
               WHERE a.id_academia = %s AND md.ativo = 1
               ORDER BY md.nome""", (academia_id,))
        return [{"id": r["id"], "nome": r["nome"],
                 "cor": r.get("cor") or COR_PADRAO} for r in cur.fetchall() or []]
    finally:
        cur.close()
        conn.close()


def modalidades_da_academia(academia_id):
    if not academia_id:
        return []
    agora = time.time()
    with _lock:
        item = _cache.get(academia_id)
        if item and agora - item[0] < _TTL_SEGUNDOS:
            return list(item[1])
    try:
        valor = _consultar_modalidades(academia_id)
    except Exception:
        # Sem a consulta não dá para oferecer contexto nenhum — e oferecer um
        # recorte errado é pior do que não oferecer.
        return []
    with _lock:
        _cache[academia_id] = (agora, valor)
    return list(valor)


def invalidar(academia_id=None):
    """Esquece o cache — chamado ao mexer nas modalidades da academia."""
    with _lock:
        if academia_id is None:
            _cache.clear()
        else:
            _cache.pop(academia_id, None)


def multimodal(academia_id):
    """True quando há mais de uma modalidade, ou seja, quando escolher importa."""
    return len(modalidades_da_academia(academia_id)) > 1


# ------------------------------------------------------------------
# O contexto em si
# ------------------------------------------------------------------
def contexto_id(academia_id=None):
    """Modalidade escolhida, ou None para "Todas".

    A validação contra a academia é o que impede o contexto de vazar de uma
    academia para outra quando o gestor troca de escopo.
    """
    from flask import has_request_context, session
    if not has_request_context():
        return None
    valor = session.get(CHAVE_SESSAO)
    if not valor:
        return None
    if academia_id is None:
        academia_id = (session.get("academia_gerenciamento_id")
                       or session.get("finance_academia_id"))
    if not academia_id:
        return None
    if not any(m["id"] == valor for m in modalidades_da_academia(academia_id)):
        return None
    return valor


def definir_contexto(valor, academia_id=None):
    """Guarda a escolha. Valor falso, 'todas' ou inválido limpa o contexto."""
    from flask import session
    try:
        valor = int(valor)
    except (TypeError, ValueError):
        valor = 0
    if academia_id is None:
        academia_id = (session.get("academia_gerenciamento_id")
                       or session.get("finance_academia_id"))
    if valor and any(m["id"] == valor for m in modalidades_da_academia(academia_id)):
        session[CHAVE_SESSAO] = valor
        return valor
    session.pop(CHAVE_SESSAO, None)
    return None


def nome_contexto(academia_id=None):
    mid = contexto_id(academia_id)
    if not mid:
        return ""
    if academia_id is None:
        from flask import session
        academia_id = (session.get("academia_gerenciamento_id")
                       or session.get("finance_academia_id"))
    for m in modalidades_da_academia(academia_id):
        if m["id"] == mid:
            return m["nome"]
    return ""


def identidade(academia_id=None):
    """Como o sistema se apresenta no recorte atual: (rótulo, cor).

    Com uma modalidade em foco, é ela que dá nome e cor. Sem foco, uma academia
    de modalidade única ainda se identifica por ela — é o caso da maioria. Só
    quem tem várias e não escolheu nenhuma vê o rótulo genérico.
    """
    from flask import session
    if academia_id is None:
        try:
            academia_id = (session.get("academia_gerenciamento_id")
                           or session.get("finance_academia_id"))
        except Exception:
            academia_id = None
    modalidades = modalidades_da_academia(academia_id)
    mid = contexto_id(academia_id)
    if mid:
        for m in modalidades:
            if m["id"] == mid:
                return m["nome"], m.get("cor") or COR_PADRAO
    if len(modalidades) == 1:
        return modalidades[0]["nome"], modalidades[0].get("cor") or COR_PADRAO
    if modalidades:
        return "", COR_PADRAO
    return "Judô", COR_PADRAO


# ------------------------------------------------------------------
# Filtros de consulta
# ------------------------------------------------------------------
def filtro_alunos_sql(alias="a", academia_id=None, modalidade_id=None):
    """Alunos matriculados na modalidade do contexto.

    Lê `matricula_modalidade`, que tem situação: aluno que trancou a ginástica
    sai do recorte da ginástica sem sair do sistema.
    """
    mid = modalidade_id or contexto_id(academia_id)
    if not mid:
        return "", ()
    return (f" AND EXISTS (SELECT 1 FROM matricula_modalidade mm_ctx"
            f" WHERE mm_ctx.aluno_id = {alias}.id AND mm_ctx.modalidade_id = %s"
            f" AND mm_ctx.status = 'ativa')", (mid,))


def filtro_turmas_sql(alias="t", academia_id=None, modalidade_id=None):
    mid = modalidade_id or contexto_id(academia_id)
    if not mid:
        return "", ()
    return (f" AND EXISTS (SELECT 1 FROM turma_modalidades tm_ctx"
            f" WHERE tm_ctx.turma_id = {alias}.TurmaID"
            f" AND tm_ctx.modalidade_id = %s)", (mid,))


def filtro_graduacao_sql(alias="g", academia_id=None, modalidade_id=None):
    mid = modalidade_id or contexto_id(academia_id)
    if not mid:
        return "", ()
    return f" AND {alias}.modalidade_id = %s", (mid,)


def filtro_cobrancas_sql(alias="ma", academia_id=None, modalidade_id=None):
    """Cobranças cujo plano cobre a modalidade.

    Pacote multimodalidade entra no recorte de TODAS as modalidades que ele
    cobre — o dinheiro é um só e não se parte. Quem soma receita por modalidade
    precisa saber disso: veja `receita_por_modalidade`.
    """
    mid = modalidade_id or contexto_id(academia_id)
    if not mid:
        return "", ()
    return (f" AND EXISTS (SELECT 1 FROM mensalidade_modalidade mm_cob"
            f" WHERE mm_cob.mensalidade_id = {alias}.mensalidade_id"
            f" AND mm_cob.modalidade_id = %s)", (mid,))


def filtro_precadastro_sql(alias="pc", academia_id=None, modalidade_id=None):
    """Pré-cadastros da modalidade em foco.

    `pre_cadastro.modalidades_ids` é uma lista em texto e hoje está vazia em
    todos os registros. Quem ainda não declarou modalidade continua aparecendo
    em qualquer recorte: é um interessado por converter, e escondê-lo custaria
    matrícula.
    """
    mid = modalidade_id or contexto_id(academia_id)
    if not mid:
        return "", ()
    return (f" AND (COALESCE({alias}.modalidades_ids,'') = ''"
            f" OR FIND_IN_SET(%s, {alias}.modalidades_ids))", (mid,))


def filtro_professores_sql(alias="p", academia_id=None, modalidade_id=None):
    mid = modalidade_id or contexto_id(academia_id)
    if not mid:
        return "", ()
    return (f" AND EXISTS (SELECT 1 FROM professor_modalidade pm_ctx"
            f" WHERE pm_ctx.professor_id = {alias}.id"
            f" AND pm_ctx.modalidade_id = %s AND pm_ctx.ativo = 1)", (mid,))


# ------------------------------------------------------------------
# O que fica de fora do recorte
# ------------------------------------------------------------------
def pendencias(academia_id):
    """Quantos registros da academia não pertencem a modalidade nenhuma.

    Serve para a tela avisar em vez de deixar o gestor achar que perdeu aluno
    ao ligar um contexto.
    """
    vazio = {"alunos": 0, "turmas": 0}
    if not academia_id:
        return vazio
    chave = ("pend", academia_id)
    agora = time.time()
    with _lock:
        item = _cache.get(chave)
        if item and agora - item[0] < _TTL_SEGUNDOS:
            return dict(item[1])
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT COUNT(*) FROM alunos a
               WHERE a.id_academia = %s AND a.status = 'ativo'
                 AND NOT EXISTS (SELECT 1 FROM matricula_modalidade mm
                                  WHERE mm.aluno_id = a.id)""", (academia_id,))
        alunos = (cur.fetchone() or [0])[0]
        cur.execute(
            """SELECT COUNT(*) FROM turmas t
               WHERE t.id_academia = %s
                 AND NOT EXISTS (SELECT 1 FROM turma_modalidades tm
                                  WHERE tm.turma_id = t.TurmaID)""", (academia_id,))
        turmas = (cur.fetchone() or [0])[0]
        resultado = {"alunos": int(alunos or 0), "turmas": int(turmas or 0)}
        with _lock:
            _cache[chave] = (agora, resultado)
        return dict(resultado)
    except Exception:
        return vazio
    finally:
        cur.close()
        conn.close()


def sql_turmas_da_academia(academia_id, colunas="TurmaID, Nome", modalidade_id=None):
    """Consulta pronta das turmas de uma academia, já pelo contexto.

    As telas de presença montam esse mesmo SELECT em quatro lugares; centralizar
    evita que uma delas fique para trás e mostre a turma de outra modalidade.
    """
    trecho, ps = filtro_turmas_sql("turmas", academia_id, modalidade_id)
    sql = (f"SELECT {colunas} FROM turmas WHERE id_academia = %s{trecho} "
           "ORDER BY Nome")
    return sql, (academia_id,) + tuple(ps)


# ------------------------------------------------------------------
# Contrato e retrato do pacote
# ------------------------------------------------------------------
def contrato_do_aluno(cur, aluno_id, academia_id, plano_id=None):
    """Contrato ativo que cobre o aluno, ou None.

    Procura pelo item, não pelo titular: no contrato de família o titular é
    NULL e quem aparece são os filhos. Havendo mais de um contrato ativo — o
    aluno pode ter dois, judô e ginástica —, o do plano pedido tem preferência.
    """
    cur.execute(
        """SELECT c.id, c.mensalidade_id
           FROM contrato c
           JOIN contrato_item ci ON ci.contrato_id = c.id
           WHERE ci.aluno_id = %s AND c.id_academia = %s
             AND c.status = 'ativo' AND ci.status = 'ativo'
           GROUP BY c.id, c.mensalidade_id
           ORDER BY (c.mensalidade_id = %s) DESC, c.id
           LIMIT 1""",
        (aluno_id, academia_id, plano_id or 0))
    linha = cur.fetchone()
    if not linha:
        return None
    if isinstance(linha, dict):
        return {"id": linha["id"], "mensalidade_id": linha["mensalidade_id"]}
    return {"id": linha[0], "mensalidade_id": linha[1]}


def snapshot_do_plano(cur, plano_id):
    """(nome do pacote, modalidades) como estão AGORA.

    Gravado junto da cobrança para que mudar o pacote amanhã não reescreva o
    que a cobrança de hoje significava.
    """
    if not plano_id:
        return None, None
    cur.execute("SELECT nome FROM mensalidades WHERE id = %s", (plano_id,))
    linha = cur.fetchone()
    nome = (linha["nome"] if isinstance(linha, dict) else linha[0]) if linha else None
    cur.execute(
        """SELECT md.nome FROM mensalidade_modalidade mm
           JOIN modalidade md ON md.id = mm.modalidade_id
           WHERE mm.mensalidade_id = %s
           ORDER BY mm.principal DESC, md.nome""", (plano_id,))
    linhas = cur.fetchall() or []
    nomes = [(r["nome"] if isinstance(r, dict) else r[0]) for r in linhas]
    return nome, (", ".join(nomes) if nomes else None)


def competencia_de(data_vencimento):
    """'AAAA-MM' da cobrança. Existe para não repetir DATE_FORMAT em SQL, onde
    o '%%' do formato já causou gravação de literal."""
    return f"{data_vencimento.year:04d}-{data_vencimento.month:02d}"


def modalidades_do_professor(usuario_id, academia_id):
    """Modalidades que o professor leciona, entre as da academia.

    Sem nenhum vínculo em `professor_modalidade`, devolve todas: a tabela ainda
    está sendo preenchida, e esconder turma de professor não cadastrado seria
    tirar acesso a quem sempre teve — o oposto do que o contexto se propõe.
    """
    todas = modalidades_da_academia(academia_id)
    if not usuario_id or not todas:
        return todas
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT pm.modalidade_id
               FROM professor_modalidade pm
               JOIN professores p ON p.id = pm.professor_id
               WHERE pm.ativo = 1 AND p.id_academia = %s
                 AND (p.usuario_id = %s OR p.id = %s)""",
            (academia_id, usuario_id, usuario_id))
        permitidas = {r[0] for r in cur.fetchall() or []}
    except Exception:
        return todas
    finally:
        cur.close()
        conn.close()
    if not permitidas:
        return todas
    return [m for m in todas if m["id"] in permitidas]


def filtro_eventos_sql(alias="e", academia_id=None, modalidade_id=None):
    """Eventos da modalidade em foco.

    O evento só pertence a uma modalidade quando está preso a uma turma. Feriado,
    competição e aviso geral não têm turma e continuam aparecendo em qualquer
    recorte — esconder feriado do professor de ginástica não ajudaria ninguém.
    """
    mid = modalidade_id or contexto_id(academia_id)
    if not mid:
        return "", ()
    return (f" AND ({alias}.turma_id IS NULL OR EXISTS ("
            f"SELECT 1 FROM turma_modalidades tm_ev"
            f" WHERE tm_ev.turma_id = {alias}.turma_id"
            f" AND tm_ev.modalidade_id = %s))", (mid,))
