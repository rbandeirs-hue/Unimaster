# -*- coding: utf-8 -*-
"""Catálogo de relatórios do sistema.

Um relatório aqui é uma função que recebe um cursor e um recorte
(`Recorte`: academia, período, modalidade, turma) e devolve linhas. Quem
sabe desenhar a tabela, montar o Excel, o PDF e a impressão é o blueprint
`relatorios` — nada disso se repete por relatório.

Por que um catálogo e não uma tela por relatório: o sistema tinha UMA tela
de relatório (o financeiro do mês) e o mesmo pedido chegava sempre em outra
forma — "quantos alunos sem CPF", "quem sumiu", "quanto entrou por PIX".
Cada resposta virava uma consulta no banco feita à mão. Aqui a pergunta
entra uma vez, com o nome que o gestor usa, e sai em tela, planilha ou papel.

Para acrescentar um relatório: `@relatorio(...)` e uma função que devolve
lista de dicionários. As colunas declaram tipo (moeda, data, percentual)
porque quem formata é a saída, não a consulta.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
import calendar
from utils.graduacao_modalidade import sql_join_faixa as _join_faixa


# =====================================================================
# Recorte e catálogo
# =====================================================================

@dataclass
class Recorte:
    """O filtro que vale para todos os relatórios da página."""
    academia_id: int
    ini: date
    fim: date
    modalidade_id: int = None
    turma_id: int = None
    academia_nome: str = ""

    @property
    def dias(self):
        return (self.fim - self.ini).days + 1

    def rotulo(self):
        return f"{self.ini.strftime('%d/%m/%Y')} a {self.fim.strftime('%d/%m/%Y')}"


@dataclass
class Coluna:
    chave: str
    rotulo: str
    # texto | numero | moeda | data | percentual | mes | pessoa | acao
    # `pessoa` desenha iniciais + nome + uma linha de apoio (faixa, idade);
    # `acao` é o botão que leva para a ficha.
    tipo: str = "texto"
    # Coluna que só existe na tela (um botão, um link): não vai para o papel.
    so_tela: bool = False


@dataclass
class Definicao:
    id: str
    secao: str
    nome: str
    descricao: str
    colunas: list
    funcao: object
    # Texto curto que explica o que entra na conta. Vai no rodapé da tela e
    # no cabeçalho do Excel e do PDF: relatório sem critério declarado vira
    # discussão na reunião.
    criterio: str = ""
    # Um total por coluna, quando somar faz sentido.
    totaliza: list = field(default_factory=list)
    # False: aparece no catálogo marcado "em construção" e não abre. Mostrar o
    # que falta é melhor do que esconder: o gestor para de procurar o relatório
    # que não existe e sabe o que está por vir.
    pronto: bool = True


CATALOGO = {}
SECOES = [
    ("gestao", "Gestão e decisão", "bi-graph-up-arrow",
     "Os números que respondem 'como estamos indo' e 'onde mexer'."),
    ("financeiro", "Financeiro", "bi-cash-coin",
     "Entradas, saídas e o que está para receber."),
    ("alunos", "Alunos", "bi-people",
     "Quem está na base, quem entrou e quem saiu."),
    ("frequencia", "Frequência", "bi-calendar2-check",
     "Quem treina, quanto treina e quem parou."),
    ("graduacoes", "Graduações", "bi-award",
     "Faixas, exames e quem já cumpriu o tempo."),
    ("turmas", "Turmas e professores", "bi-easel",
     "Ocupação, horários e quem dá aula."),
    ("captacao", "Captação", "bi-person-plus",
     "Do interessado ao aluno matriculado."),
    ("competicoes", "Competições", "bi-trophy",
     "Inscrições e resultados."),
    ("estoque", "Estoque", "bi-box-seam",
     "O que tem, o que saiu e quanto vale."),
    ("cadastro", "Cadastro incompleto", "bi-clipboard-x",
     "Campos em branco que travam cobrança, chamada ou inscrição."),
]


def relatorio(id, secao, nome, descricao, colunas, criterio="",
              totaliza=None, pronto=True):
    def registra(fn):
        CATALOGO[id] = Definicao(
            id=id, secao=secao, nome=nome, descricao=descricao,
            colunas=[Coluna(*c) if isinstance(c, tuple) else c for c in colunas],
            funcao=fn, criterio=criterio, totaliza=totaliza or [], pronto=pronto,
        )
        return fn
    return registra


def por_secao():
    """Catálogo agrupado, na ordem de SECOES.

    Não existe relatório que cruze academias: cada uma vê só os próprios
    números, mesmo quando a mesma pessoa administra várias.
    """
    grupos = []
    for chave, titulo, icone, resumo in SECOES:
        itens = [d for d in CATALOGO.values() if d.secao == chave]
        if itens:
            grupos.append({"chave": chave, "titulo": titulo, "icone": icone,
                           "resumo": resumo, "itens": itens})
    return grupos


# ------------------------------------------------- ajudantes de consulta

def _meses_ate(fim, quantos=12):
    """Lista de (ano, mes) terminando no mês de `fim`."""
    saida = []
    ano, mes = fim.year, fim.month
    for _ in range(quantos):
        saida.append((ano, mes))
        mes -= 1
        if mes == 0:
            ano, mes = ano - 1, 12
    return list(reversed(saida))


def _limites(ano, mes):
    return date(ano, mes, 1), date(ano, mes, calendar.monthrange(ano, mes)[1])


MESES = ['', 'jan', 'fev', 'mar', 'abr', 'mai', 'jun',
         'jul', 'ago', 'set', 'out', 'nov', 'dez']


def _mes_rotulo(ano, mes):
    return f"{MESES[mes]}/{str(ano)[2:]}"


def _filtro_modalidade(rec, alias="a"):
    """Trecho de SQL + parâmetros para recortar por modalidade."""
    if not rec.modalidade_id:
        return "", []
    return (f" AND EXISTS (SELECT 1 FROM aluno_modalidades am "
            f"WHERE am.aluno_id = {alias}.id AND am.modalidade_id = %s)",
            [rec.modalidade_id])


def _filtro_turma(rec, alias="a"):
    if not rec.turma_id:
        return "", []
    return (f" AND ({alias}.TurmaID = %s OR EXISTS (SELECT 1 FROM aluno_turmas at2 "
            f"WHERE at2.aluno_id = {alias}.id AND at2.TurmaID = %s))",
            [rec.turma_id, rec.turma_id])


def _recorte_alunos(rec, alias="a"):
    """Filtro comum da base de alunos: academia + modalidade + turma."""
    sql = f" AND {alias}.id_academia = %s"
    par = [rec.academia_id]
    s, p = _filtro_modalidade(rec, alias); sql += s; par += p
    s, p = _filtro_turma(rec, alias);      sql += s; par += p
    return sql, par


# =====================================================================
# Gestão e decisão
# =====================================================================

@relatorio(
    "panorama", "gestao", "Panorama do período",
    "Os oito números que dizem como o mês está indo, em uma tela.",
    [("indicador", "Indicador"), ("valor", "No período"), ("nota", "Como ler")],
    criterio="Base: alunos com ativo = 1 na academia escolhida. Receita: lançamentos não cancelados com data dentro do período.",
)
def _panorama(cur, rec):
    filtro, par = _recorte_alunos(rec)
    linhas = []

    cur.execute(f"SELECT COUNT(*) n FROM alunos a WHERE COALESCE(a.ativo,1)=1 {filtro}", par)
    ativos = cur.fetchone()["n"]
    linhas.append({"indicador": "Alunos ativos", "valor": ativos,
                   "nota": "base de hoje, não do fim do período"})

    cur.execute(f"""SELECT COUNT(*) n FROM alunos a
                    WHERE a.data_matricula BETWEEN %s AND %s {filtro}""",
                [rec.ini, rec.fim] + par)
    entradas = cur.fetchone()["n"]

    cur.execute(f"""SELECT COUNT(*) n FROM alunos a
                    WHERE a.data_inativacao BETWEEN %s AND %s {filtro}""",
                [rec.ini, rec.fim] + par)
    saidas = cur.fetchone()["n"]

    linhas.append({"indicador": "Entraram no período", "valor": entradas, "nota": "matrículas novas"})
    linhas.append({"indicador": "Saíram no período", "valor": saidas, "nota": "inativados com data"})
    linhas.append({"indicador": "Saldo de alunos", "valor": entradas - saidas,
                   "nota": "entradas menos saídas"})

    cur.execute("""SELECT COALESCE(SUM(valor),0) v FROM receitas
                   WHERE id_academia=%s AND (cancelada=0 OR cancelada IS NULL)
                     AND data BETWEEN %s AND %s""",
                [rec.academia_id, rec.ini, rec.fim])
    receita = float(cur.fetchone()["v"] or 0)
    # Despesa = o que saiu do caixa: paga e não estornada, pela data do
    # pagamento (utils/despesas_pagamento.py). Cadastrada e não paga é conta
    # a pagar, não gasto.
    cur.execute("""SELECT COALESCE(SUM(l.valor),0) v
                   FROM despesas d JOIN fin_lancamentos l ON l.id = d.id_lancamento
                    AND l.status = 'efetivado' AND l.id_estorno IS NULL
                   WHERE d.id_academia=%s AND l.data_efetivacao BETWEEN %s AND %s""",
                [rec.academia_id, rec.ini, rec.fim])
    despesa = float(cur.fetchone()["v"] or 0)
    linhas.append({"indicador": "Receita", "valor": f"R$ {receita:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                   "nota": "lançamentos não cancelados"})
    linhas.append({"indicador": "Despesa", "valor": f"R$ {despesa:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                   "nota": "tudo que saiu no período"})
    linhas.append({"indicador": "Saldo", "valor": f"R$ {receita - despesa:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                   "nota": "receita menos despesa"})

    cur.execute("""SELECT COALESCE(SUM(ma.valor),0) v, COUNT(DISTINCT ma.aluno_id) q
                   FROM mensalidade_aluno ma JOIN alunos a ON a.id = ma.aluno_id
                   WHERE a.id_academia=%s
                     AND (ma.status='atrasado' OR (ma.status='pendente' AND ma.data_vencimento < CURDATE()))""",
                [rec.academia_id])
    r = cur.fetchone()
    atraso = float(r["v"] or 0)
    linhas.append({"indicador": "Em atraso hoje",
                   "valor": f"R$ {atraso:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                   "nota": f"{r['q']} aluno(s), vencidas de qualquer mês"})

    cur.execute(f"""SELECT COUNT(DISTINCT p.aluno_id) n FROM presencas p
                    JOIN alunos a ON a.id = p.aluno_id
                    WHERE p.data_presenca BETWEEN %s AND %s AND COALESCE(p.presente,1)=1 {filtro}""",
                [rec.ini, rec.fim] + par)
    treinaram = cur.fetchone()["n"]
    pct = (treinaram / ativos * 100) if ativos else 0
    linhas.append({"indicador": "Treinaram no período", "valor": f"{treinaram} ({pct:.0f}%)",
                   "nota": "alunos ativos com ao menos uma presença"})
    return linhas


@relatorio(
    "evolucao_alunos", "gestao", "Evolução da base de alunos",
    "Entradas, saídas e saldo mês a mês — o crescimento real da academia.",
    [("mes", "Mês", "mes"), ("entradas", "Entraram", "numero"),
     ("saidas", "Saíram", "numero"), ("saldo", "Saldo", "numero")],
    criterio="Entradas por data_matricula; saídas por data_inativacao. Alunos inativados sem data não entram na conta de saída.",
    totaliza=["entradas", "saidas", "saldo"],
)
def _evolucao_alunos(cur, rec):
    filtro, par = _recorte_alunos(rec)
    linhas = []
    for ano, mes in _meses_ate(rec.fim, 12):
        ini, fim = _limites(ano, mes)
        cur.execute(f"""SELECT COUNT(*) n FROM alunos a
                        WHERE a.data_matricula BETWEEN %s AND %s {filtro}""", [ini, fim] + par)
        e = cur.fetchone()["n"]
        cur.execute(f"""SELECT COUNT(*) n FROM alunos a
                        WHERE a.data_inativacao BETWEEN %s AND %s {filtro}""", [ini, fim] + par)
        s = cur.fetchone()["n"]
        linhas.append({"mes": _mes_rotulo(ano, mes), "entradas": e, "saidas": s, "saldo": e - s})
    return linhas


@relatorio(
    "evasao", "gestao", "Evasão: quem saiu e depois de quanto tempo",
    "Cada saída com o tempo de casa — mostra se a perda é na porta de entrada ou depois.",
    [("nome", "Aluno"), ("matricula", "Matriculou", "data"),
     ("saida", "Saiu", "data"), ("meses", "Meses de casa", "numero"),
     ("turma", "Última turma")],
    criterio="Alunos inativados com data dentro do período. Tempo de casa = da matrícula à inativação.",
)
def _evasao(cur, rec):
    filtro, par = _recorte_alunos(rec)
    cur.execute(f"""SELECT a.nome, a.data_matricula, a.data_inativacao,
                           TIMESTAMPDIFF(MONTH, a.data_matricula, a.data_inativacao) meses,
                           t.Nome turma
                    FROM alunos a
                    LEFT JOIN turmas t ON t.TurmaID = a.TurmaID
                    WHERE a.data_inativacao BETWEEN %s AND %s {filtro}
                    ORDER BY a.data_inativacao DESC""", [rec.ini, rec.fim] + par)
    return [{"nome": r["nome"], "matricula": r["data_matricula"], "saida": r["data_inativacao"],
             "meses": r["meses"], "turma": r["turma"] or "—"} for r in cur.fetchall()]


@relatorio(
    "risco_evasao", "gestao", "Risco de evasão",
    "Quem está matriculado, pagando, e parou de aparecer — a lista para ligar hoje.",
    [("nome", "Aluno"), ("turma", "Turma"), ("ultima", "Última presença", "data"),
     ("dias", "Dias sem treinar", "numero"), ("telefone", "Telefone"),
     ("situacao", "Mensalidade")],
    criterio="Alunos ativos cuja última presença tem 21 dias ou mais (ou que nunca tiveram presença registrada, se matriculados há mais de 21 dias).",
)
def _risco_evasao(cur, rec):
    filtro, par = _recorte_alunos(rec)
    cur.execute(f"""SELECT a.id, a.nome, a.telefone, a.tel_celular, t.Nome turma,
                           MAX(p.data_presenca) ultima,
                           DATEDIFF(CURDATE(), MAX(p.data_presenca)) dias
                    FROM alunos a
                    LEFT JOIN turmas t ON t.TurmaID = a.TurmaID
                    LEFT JOIN presencas p ON p.aluno_id = a.id AND COALESCE(p.presente,1)=1
                    WHERE COALESCE(a.ativo,1)=1
                      AND (a.data_matricula IS NULL OR a.data_matricula <= DATE_SUB(CURDATE(), INTERVAL 21 DAY))
                      {filtro}
                    GROUP BY a.id, a.nome, a.telefone, a.tel_celular, t.Nome
                    HAVING ultima IS NULL OR dias >= 21
                    ORDER BY dias DESC, a.nome""", par)
    brutos = cur.fetchall()
    if not brutos:
        return []
    ids = [r["id"] for r in brutos]
    marcas = ",".join(["%s"] * len(ids))
    cur.execute(f"""SELECT aluno_id, COUNT(*) q FROM mensalidade_aluno
                    WHERE aluno_id IN ({marcas})
                      AND (status='atrasado' OR (status='pendente' AND data_vencimento < CURDATE()))
                    GROUP BY aluno_id""", ids)
    atraso = {r["aluno_id"]: r["q"] for r in cur.fetchall()}
    linhas = []
    for r in brutos:
        q = atraso.get(r["id"], 0)
        linhas.append({
            "nome": r["nome"], "turma": r["turma"] or "—", "ultima": r["ultima"],
            "dias": r["dias"] if r["dias"] is not None else "nunca treinou",
            "telefone": r["telefone"] or r["tel_celular"] or "—",
            "situacao": f"{q} em atraso" if q else "em dia",
        })
    return linhas


@relatorio(
    "ticket_medio", "gestao", "Receita por aluno, mês a mês",
    "Quanto cada aluno ativo rendeu — mostra se o crescimento vem de mais gente ou de preço.",
    [("mes", "Mês", "mes"), ("receita", "Receita", "moeda"),
     ("alunos", "Alunos ativos", "numero"), ("ticket", "Por aluno", "moeda")],
    criterio="Receita = lançamentos não cancelados do mês. Alunos ativos = base de hoje (o sistema não guarda foto da base por mês), então meses antigos saem com o denominador de hoje.",
)
def _ticket_medio(cur, rec):
    filtro, par = _recorte_alunos(rec)
    cur.execute(f"SELECT COUNT(*) n FROM alunos a WHERE COALESCE(a.ativo,1)=1 {filtro}", par)
    ativos = cur.fetchone()["n"] or 0
    linhas = []
    for ano, mes in _meses_ate(rec.fim, 12):
        ini, fim = _limites(ano, mes)
        cur.execute("""SELECT COALESCE(SUM(valor),0) v FROM receitas
                       WHERE id_academia=%s AND (cancelada=0 OR cancelada IS NULL)
                         AND data BETWEEN %s AND %s""", [rec.academia_id, ini, fim])
        v = float(cur.fetchone()["v"] or 0)
        linhas.append({"mes": _mes_rotulo(ano, mes), "receita": v, "alunos": ativos,
                       "ticket": (v / ativos) if ativos else 0})
    return linhas


@relatorio(
    "previsao_receita", "gestao", "Previsão do mês",
    "O que já entrou, o que ainda vem e o que está vencido — antes de o mês fechar.",
    [("situacao", "Situação"), ("qtd", "Cobranças", "numero"), ("valor", "Valor", "moeda")],
    criterio="Mensalidades com vencimento no período, agrupadas pela situação de hoje.",
    totaliza=["qtd", "valor"],
)
def _previsao_receita(cur, rec):
    cur.execute("""SELECT
            CASE
              WHEN ma.status='pago' THEN 'Já recebido'
              WHEN ma.data_vencimento < CURDATE() THEN 'Vencido e não pago'
              ELSE 'A vencer'
            END situacao,
            COUNT(*) qtd, COALESCE(SUM(ma.valor),0) valor
        FROM mensalidade_aluno ma JOIN alunos a ON a.id = ma.aluno_id
        WHERE a.id_academia = %s AND ma.data_vencimento BETWEEN %s AND %s
        GROUP BY situacao ORDER BY FIELD(situacao,'Já recebido','A vencer','Vencido e não pago')""",
        [rec.academia_id, rec.ini, rec.fim])
    return [{"situacao": r["situacao"], "qtd": r["qtd"], "valor": float(r["valor"] or 0)}
            for r in cur.fetchall()]


@relatorio(
    "aging", "gestao", "Atraso por faixa de dias",
    "Dívida de 30, 60, 90 dias — quanto ainda dá para recuperar e quanto já virou perda.",
    [("faixa", "Atraso"), ("alunos", "Alunos", "numero"),
     ("cobrancas", "Cobranças", "numero"), ("valor", "Valor", "moeda")],
    criterio="Mensalidades vencidas e não pagas, de qualquer mês, pela distância até hoje.",
    totaliza=["cobrancas", "valor"],
)
def _aging(cur, rec):
    cur.execute("""SELECT
            CASE
              WHEN DATEDIFF(CURDATE(), ma.data_vencimento) <= 30 THEN '1 a 30 dias'
              WHEN DATEDIFF(CURDATE(), ma.data_vencimento) <= 60 THEN '31 a 60 dias'
              WHEN DATEDIFF(CURDATE(), ma.data_vencimento) <= 90 THEN '61 a 90 dias'
              ELSE 'mais de 90 dias'
            END faixa,
            COUNT(DISTINCT ma.aluno_id) alunos, COUNT(*) cobrancas,
            COALESCE(SUM(ma.valor),0) valor
        FROM mensalidade_aluno ma JOIN alunos a ON a.id = ma.aluno_id
        WHERE a.id_academia = %s AND ma.status <> 'pago' AND ma.data_vencimento < CURDATE()
        GROUP BY faixa
        ORDER BY FIELD(faixa,'1 a 30 dias','31 a 60 dias','61 a 90 dias','mais de 90 dias')""",
        [rec.academia_id])
    return [{"faixa": r["faixa"], "alunos": r["alunos"], "cobrancas": r["cobrancas"],
             "valor": float(r["valor"] or 0)} for r in cur.fetchall()]


@relatorio(
    "ocupacao_horarios", "gestao", "Ocupação por turma e horário",
    "Onde lota e onde sobra vaga — a conta para abrir, fechar ou juntar turma.",
    [("turma", "Turma"), ("horario", "Horário"), ("matriculados", "Matriculados", "numero"),
     ("capacidade", "Capacidade", "numero"), ("ocupacao", "Ocupação", "percentual"),
     ("presenca_media", "Presença média", "numero")],
    criterio="Matriculados = alunos ativos com a turma como principal ou vinculados a ela. Presença média = presenças no período ÷ dias com aula registrada.",
)
def _ocupacao_horarios(cur, rec):
    cur.execute("""SELECT t.TurmaID, t.Nome, t.DiasHorario, t.hora_inicio, t.Capacidade,
                          (SELECT COUNT(*) FROM alunos a
                            WHERE COALESCE(a.ativo,1)=1
                              AND (a.TurmaID = t.TurmaID
                                   OR EXISTS (SELECT 1 FROM aluno_turmas at2
                                              WHERE at2.aluno_id=a.id AND at2.TurmaID=t.TurmaID))) matriculados
                   FROM turmas t WHERE t.id_academia = %s ORDER BY t.Nome""",
                [rec.academia_id])
    turmas = cur.fetchall()
    linhas = []
    for t in turmas:
        cur.execute("""SELECT COUNT(*) presencas, COUNT(DISTINCT data_presenca) dias
                       FROM presencas WHERE turma_id=%s AND COALESCE(presente,1)=1
                         AND data_presenca BETWEEN %s AND %s""",
                    [t["TurmaID"], rec.ini, rec.fim])
        p = cur.fetchone()
        media = (p["presencas"] / p["dias"]) if p["dias"] else 0
        cap = t["Capacidade"] or 0
        linhas.append({
            "turma": t["Nome"],
            "horario": t["DiasHorario"] or (str(t["hora_inicio"])[:5] if t["hora_inicio"] else "—"),
            "matriculados": t["matriculados"],
            "capacidade": cap or "sem limite",
            "ocupacao": (t["matriculados"] / cap * 100) if cap else None,
            "presenca_media": round(media, 1),
        })
    return linhas


@relatorio(
    "funil_captacao", "gestao", "Funil: interessado até matrícula",
    "Quantos pré-cadastros viraram aula experimental e quantos viraram aluno.",
    [("etapa", "Etapa"), ("qtd", "Quantidade", "numero"), ("taxa", "Do topo", "percentual")],
    criterio="Pré-cadastros criados no período; experimentais pela data da aula; matrículas por data_matricula no mesmo período.",
)
def _funil(cur, rec):
    cur.execute("""SELECT COUNT(*) n FROM pre_cadastro
                   WHERE academia_id=%s AND DATE(created_at) BETWEEN %s AND %s""",
                [rec.academia_id, rec.ini, rec.fim])
    pre = cur.fetchone()["n"]
    cur.execute("""SELECT COUNT(*) n FROM aulas_experimentais ae
                   JOIN visitantes v ON v.id = ae.visitante_id
                   WHERE v.id_academia=%s AND ae.data_aula BETWEEN %s AND %s""",
                [rec.academia_id, rec.ini, rec.fim])
    exp = cur.fetchone()["n"]
    cur.execute("""SELECT COUNT(*) n FROM aulas_experimentais ae
                   JOIN visitantes v ON v.id = ae.visitante_id
                   WHERE v.id_academia=%s AND ae.data_aula BETWEEN %s AND %s
                     AND COALESCE(ae.presente,0)=1""",
                [rec.academia_id, rec.ini, rec.fim])
    compareceu = cur.fetchone()["n"]
    cur.execute("""SELECT COUNT(*) n FROM alunos
                   WHERE id_academia=%s AND data_matricula BETWEEN %s AND %s""",
                [rec.academia_id, rec.ini, rec.fim])
    mat = cur.fetchone()["n"]
    topo = pre or 0
    def taxa(n):
        return (n / topo * 100) if topo else None
    return [
        {"etapa": "Pré-cadastros recebidos", "qtd": pre, "taxa": 100.0 if topo else None},
        {"etapa": "Aulas experimentais marcadas", "qtd": exp, "taxa": taxa(exp)},
        {"etapa": "Compareceram à experimental", "qtd": compareceu, "taxa": taxa(compareceu)},
        {"etapa": "Matrículas no período", "qtd": mat, "taxa": taxa(mat)},
    ]


@relatorio(
    "desempenho_professor", "gestao", "Professores: turmas, alunos e aulas",
    "Quanto cada professor carrega e como a frequência anda nas turmas dele.",
    [("professor", "Professor"), ("turmas", "Turmas", "numero"),
     ("alunos", "Alunos", "numero"), ("aulas", "Aulas no período", "numero"),
     ("presencas", "Presenças", "numero"), ("media", "Média por aula", "numero")],
    criterio="Vínculo por turma_professor. Aulas = dias distintos com presença registrada nas turmas do professor.",
)
def _desempenho_professor(cur, rec):
    cur.execute("""SELECT p.id, p.nome FROM professores p
                   WHERE p.id_academia=%s AND COALESCE(p.ativo,1)=1 ORDER BY p.nome""",
                [rec.academia_id])
    profs = cur.fetchall()
    linhas = []
    for pr in profs:
        cur.execute("SELECT TurmaID FROM turma_professor WHERE professor_id=%s", [pr["id"]])
        turmas = [t["TurmaID"] for t in cur.fetchall()]
        if not turmas:
            linhas.append({"professor": pr["nome"], "turmas": 0, "alunos": 0,
                           "aulas": 0, "presencas": 0, "media": 0})
            continue
        marcas = ",".join(["%s"] * len(turmas))
        cur.execute(f"""SELECT COUNT(DISTINCT a.id) n FROM alunos a
                        WHERE COALESCE(a.ativo,1)=1
                          AND (a.TurmaID IN ({marcas})
                               OR EXISTS (SELECT 1 FROM aluno_turmas at2
                                          WHERE at2.aluno_id=a.id AND at2.TurmaID IN ({marcas})))""",
                    turmas + turmas)
        alunos = cur.fetchone()["n"]
        cur.execute(f"""SELECT COUNT(DISTINCT data_presenca) aulas, COUNT(*) presencas
                        FROM presencas WHERE turma_id IN ({marcas})
                          AND COALESCE(presente,1)=1 AND data_presenca BETWEEN %s AND %s""",
                    turmas + [rec.ini, rec.fim])
        p = cur.fetchone()
        linhas.append({
            "professor": pr["nome"], "turmas": len(turmas), "alunos": alunos,
            "aulas": p["aulas"], "presencas": p["presencas"],
            "media": round(p["presencas"] / p["aulas"], 1) if p["aulas"] else 0,
        })
    return linhas


@relatorio(
    "mix_pagamento", "gestao", "Como os alunos pagam",
    "Mix de formas de pagamento — a conta antes de negociar taxa com gateway.",
    [("forma", "Forma de pagamento"), ("qtd", "Pagamentos", "numero"),
     ("valor", "Valor", "moeda"), ("fatia", "Fatia", "percentual")],
    criterio="Mensalidades pagas com data_pagamento no período, pela forma registrada na baixa.",
    totaliza=["qtd", "valor"],
)
def _mix_pagamento(cur, rec):
    cur.execute("""SELECT COALESCE(fp.nome, CONCAT('Gateway ', COALESCE(ma.gateway,'não informado'))) forma,
                          COUNT(*) qtd, COALESCE(SUM(COALESCE(ma.valor_pago, ma.valor)),0) valor
                   FROM mensalidade_aluno ma
                   JOIN alunos a ON a.id = ma.aluno_id
                   LEFT JOIN formas_pagamento fp ON fp.id = ma.id_forma_pagamento
                   WHERE a.id_academia=%s AND ma.status='pago'
                     AND ma.data_pagamento BETWEEN %s AND %s
                   GROUP BY forma ORDER BY valor DESC""",
                [rec.academia_id, rec.ini, rec.fim])
    linhas = [{"forma": r["forma"], "qtd": r["qtd"], "valor": float(r["valor"] or 0)}
              for r in cur.fetchall()]
    total = sum(l["valor"] for l in linhas)
    for l in linhas:
        l["fatia"] = (l["valor"] / total * 100) if total else None
    return linhas


@relatorio(
    "impacto_descontos", "gestao", "Desconto concedido",
    "Quanto foi abatido no período e quanto isso pesa na receita cheia.",
    [("aluno", "Aluno"), ("motivo", "Motivo"), ("cheio", "Valor cheio", "moeda"),
     ("desconto", "Desconto", "moeda"), ("pago", "Ficou em", "moeda")],
    criterio="Mensalidades com desconto_aplicado maior que zero e vencimento no período.",
    totaliza=["cheio", "desconto", "pago"],
)
def _impacto_descontos(cur, rec):
    cur.execute("""SELECT a.nome aluno,
                          COALESCE(NULLIF(ma.desconto_descricao,''), d.nome, 'sem motivo registrado') motivo,
                          COALESCE(ma.valor_original, ma.valor + ma.desconto_aplicado) cheio,
                          ma.desconto_aplicado desconto, ma.valor pago
                   FROM mensalidade_aluno ma
                   JOIN alunos a ON a.id = ma.aluno_id
                   LEFT JOIN descontos d ON d.id = ma.id_desconto
                   WHERE a.id_academia=%s AND COALESCE(ma.desconto_aplicado,0) > 0
                     AND ma.data_vencimento BETWEEN %s AND %s
                   ORDER BY ma.desconto_aplicado DESC""",
                [rec.academia_id, rec.ini, rec.fim])
    return [{"aluno": r["aluno"], "motivo": r["motivo"], "cheio": float(r["cheio"] or 0),
             "desconto": float(r["desconto"] or 0), "pago": float(r["pago"] or 0)}
            for r in cur.fetchall()]


@relatorio(
    "tempo_de_casa", "gestao", "Tempo de casa da base",
    "Há quanto tempo cada faixa da base treina — fidelidade em uma tabela.",
    [("faixa", "Tempo de casa"), ("alunos", "Alunos", "numero"), ("fatia", "Da base", "percentual")],
    criterio="Alunos ativos, pela distância entre data_matricula e hoje. Sem data de matrícula entram em 'não informado'.",
    totaliza=["alunos"],
)
def _tempo_de_casa(cur, rec):
    filtro, par = _recorte_alunos(rec)
    cur.execute(f"""SELECT CASE
              WHEN a.data_matricula IS NULL THEN 'não informado'
              WHEN TIMESTAMPDIFF(MONTH, a.data_matricula, CURDATE()) < 3 THEN 'menos de 3 meses'
              WHEN TIMESTAMPDIFF(MONTH, a.data_matricula, CURDATE()) < 6 THEN '3 a 6 meses'
              WHEN TIMESTAMPDIFF(MONTH, a.data_matricula, CURDATE()) < 12 THEN '6 a 12 meses'
              WHEN TIMESTAMPDIFF(MONTH, a.data_matricula, CURDATE()) < 24 THEN '1 a 2 anos'
              ELSE 'mais de 2 anos' END faixa,
            COUNT(*) alunos
        FROM alunos a WHERE COALESCE(a.ativo,1)=1 {filtro}
        GROUP BY faixa
        ORDER BY FIELD(faixa,'menos de 3 meses','3 a 6 meses','6 a 12 meses','1 a 2 anos','mais de 2 anos','não informado')""",
        par)
    linhas = [{"faixa": r["faixa"], "alunos": r["alunos"]} for r in cur.fetchall()]
    total = sum(l["alunos"] for l in linhas)
    for l in linhas:
        l["fatia"] = (l["alunos"] / total * 100) if total else None
    return linhas


# =====================================================================
# Financeiro
# =====================================================================

@relatorio(
    "receitas_categoria", "financeiro", "Receitas por categoria",
    "De onde veio o dinheiro do período.",
    [("categoria", "Categoria"), ("qtd", "Lançamentos", "numero"), ("total", "Total", "moeda")],
    criterio="Receitas não canceladas com data dentro do período.",
    totaliza=["qtd", "total"],
)
def _receitas_categoria(cur, rec):
    cur.execute("""SELECT COALESCE(NULLIF(categoria,''),'Sem categoria') categoria,
                          COUNT(*) qtd, COALESCE(SUM(valor),0) total
                   FROM receitas
                   WHERE id_academia=%s AND (cancelada=0 OR cancelada IS NULL)
                     AND data BETWEEN %s AND %s
                   GROUP BY categoria ORDER BY total DESC""",
                [rec.academia_id, rec.ini, rec.fim])
    return [{"categoria": r["categoria"], "qtd": r["qtd"], "total": float(r["total"] or 0)}
            for r in cur.fetchall()]


@relatorio(
    "despesas_categoria", "financeiro", "Despesas por categoria",
    "Para onde o dinheiro foi.",
    [("categoria", "Categoria"), ("qtd", "Lançamentos", "numero"), ("total", "Total", "moeda")],
    criterio="Despesas pagas, pela data do pagamento.",
    totaliza=["qtd", "total"],
)
def _despesas_categoria(cur, rec):
    cur.execute("""SELECT COALESCE(NULLIF(d.categoria,''),'Sem categoria') categoria,
                          COUNT(*) qtd, COALESCE(SUM(l.valor),0) total
                   FROM despesas d JOIN fin_lancamentos l ON l.id = d.id_lancamento
                    AND l.status = 'efetivado' AND l.id_estorno IS NULL
                   WHERE d.id_academia=%s AND l.data_efetivacao BETWEEN %s AND %s
                   GROUP BY categoria ORDER BY total DESC""",
                [rec.academia_id, rec.ini, rec.fim])
    return [{"categoria": r["categoria"], "qtd": r["qtd"], "total": float(r["total"] or 0)}
            for r in cur.fetchall()]


@relatorio(
    "inadimplentes", "financeiro", "Inadimplentes",
    "Quem está em atraso, há quanto tempo e quanto soma.",
    [("nome", "Aluno"), ("qtd", "Cobranças", "numero"), ("total", "Em atraso", "moeda"),
     ("venc", "Mais antiga", "data"), ("dias", "Dias de atraso", "numero"),
     ("telefone", "Telefone")],
    criterio="Mensalidades com status atrasado, ou pendentes já vencidas — de qualquer mês, não só do período.",
    totaliza=["qtd", "total"],
)
def _inadimplentes(cur, rec):
    filtro, par = _recorte_alunos(rec)
    cur.execute(f"""SELECT a.nome, a.telefone, a.tel_celular, COUNT(*) qtd,
                           COALESCE(SUM(ma.valor),0) total, MIN(ma.data_vencimento) venc,
                           DATEDIFF(CURDATE(), MIN(ma.data_vencimento)) dias
                    FROM mensalidade_aluno ma JOIN alunos a ON a.id = ma.aluno_id
                    WHERE (ma.status='atrasado'
                           OR (ma.status='pendente' AND ma.data_vencimento < CURDATE()))
                      {filtro}
                    GROUP BY a.id, a.nome, a.telefone, a.tel_celular
                    ORDER BY total DESC""", par)
    return [{"nome": r["nome"], "qtd": r["qtd"], "total": float(r["total"] or 0),
             "venc": r["venc"], "dias": r["dias"],
             "telefone": r["telefone"] or r["tel_celular"] or "—"} for r in cur.fetchall()]


@relatorio(
    "fluxo_caixa", "financeiro", "Fluxo de caixa mês a mês",
    "Entradas, saídas e saldo dos últimos 12 meses.",
    [("mes", "Mês", "mes"), ("receitas", "Receitas", "moeda"),
     ("despesas", "Despesas", "moeda"), ("saldo", "Saldo", "moeda")],
    criterio="Receitas não canceladas, pela data; despesas pagas, pela data do pagamento.",
    totaliza=["receitas", "despesas", "saldo"],
)
def _fluxo_caixa(cur, rec):
    linhas = []
    for ano, mes in _meses_ate(rec.fim, 12):
        ini, fim = _limites(ano, mes)
        cur.execute("""SELECT COALESCE(SUM(valor),0) v FROM receitas
                       WHERE id_academia=%s AND (cancelada=0 OR cancelada IS NULL)
                         AND data BETWEEN %s AND %s""", [rec.academia_id, ini, fim])
        r = float(cur.fetchone()["v"] or 0)
        cur.execute("""SELECT COALESCE(SUM(l.valor),0) v
                       FROM despesas d JOIN fin_lancamentos l ON l.id = d.id_lancamento
                        AND l.status = 'efetivado' AND l.id_estorno IS NULL
                       WHERE d.id_academia=%s AND l.data_efetivacao BETWEEN %s AND %s""",
                    [rec.academia_id, ini, fim])
        d = float(cur.fetchone()["v"] or 0)
        linhas.append({"mes": _mes_rotulo(ano, mes), "receitas": r, "despesas": d, "saldo": r - d})
    return linhas


@relatorio(
    "mensalidades_periodo", "financeiro", "Mensalidades do período",
    "Cada cobrança com vencimento no período e como ela está.",
    [("aluno", "Aluno"), ("venc", "Vencimento", "data"), ("valor", "Valor", "moeda"),
     ("status", "Situação"), ("pagamento", "Pago em", "data"), ("forma", "Forma")],
    criterio="Mensalidades com data_vencimento dentro do período, de alunos da academia.",
    totaliza=["valor"],
)
def _mensalidades_periodo(cur, rec):
    filtro, par = _recorte_alunos(rec)
    cur.execute(f"""SELECT a.nome aluno, ma.data_vencimento venc, ma.valor,
                           ma.status, ma.data_pagamento pagamento, fp.nome forma
                    FROM mensalidade_aluno ma
                    JOIN alunos a ON a.id = ma.aluno_id
                    LEFT JOIN formas_pagamento fp ON fp.id = ma.id_forma_pagamento
                    WHERE ma.data_vencimento BETWEEN %s AND %s {filtro}
                    ORDER BY ma.data_vencimento, a.nome""", [rec.ini, rec.fim] + par)
    return [{"aluno": r["aluno"], "venc": r["venc"], "valor": float(r["valor"] or 0),
             "status": (r["status"] or "").capitalize(), "pagamento": r["pagamento"],
             "forma": r["forma"] or "—"} for r in cur.fetchall()]


# =====================================================================
# Alunos
# =====================================================================

@relatorio(
    "alunos_ativos", "alunos", "Alunos ativos",
    "A lista completa com turma, faixa, contato e situação financeira.",
    [("nome", "Aluno"), ("idade", "Idade", "numero"), ("faixa", "Faixa"),
     ("turma", "Turma"), ("matricula", "Matrícula", "data"),
     ("telefone", "Telefone"), ("situacao", "Financeiro")],
    criterio="Alunos com ativo = 1 na academia escolhida.",
)
def _alunos_ativos(cur, rec):
    filtro, par = _recorte_alunos(rec)
    cur.execute(f"""SELECT a.id, a.nome, a.telefone, a.tel_celular, a.data_matricula,
                           TIMESTAMPDIFF(YEAR, a.data_nascimento, CURDATE()) idade,
                           g.faixa, t.Nome turma,
                           (SELECT COUNT(*) FROM mensalidade_aluno ma
                             WHERE ma.aluno_id = a.id AND ma.status <> 'pago'
                               AND ma.data_vencimento < CURDATE()) atrasadas
                    FROM alunos a
                    {_join_faixa()}
                    LEFT JOIN turmas t ON t.TurmaID = a.TurmaID
                    WHERE COALESCE(a.ativo,1)=1 {filtro}
                    ORDER BY a.nome""", par)
    return [{"nome": r["nome"], "idade": r["idade"], "faixa": r["faixa"] or "—",
             "turma": r["turma"] or "—", "matricula": r["data_matricula"],
             "telefone": r["telefone"] or r["tel_celular"] or "—",
             "situacao": f"{r['atrasadas']} em atraso" if r["atrasadas"] else "em dia"}
            for r in cur.fetchall()]


@relatorio(
    "matriculas_saidas", "alunos", "Matrículas e saídas",
    "Quem entrou e quem saiu no período, lado a lado.",
    [("nome", "Aluno"), ("movimento", "Movimento"), ("data", "Data", "data"),
     ("turma", "Turma"), ("telefone", "Telefone")],
    criterio="Entradas por data_matricula, saídas por data_inativacao, ambas dentro do período.",
)
def _matriculas_saidas(cur, rec):
    filtro, par = _recorte_alunos(rec)
    cur.execute(f"""SELECT a.nome, 'Entrou' movimento, a.data_matricula dt,
                           t.Nome turma, a.telefone, a.tel_celular
                    FROM alunos a LEFT JOIN turmas t ON t.TurmaID = a.TurmaID
                    WHERE a.data_matricula BETWEEN %s AND %s {filtro}
                    UNION ALL
                    SELECT a.nome, 'Saiu', a.data_inativacao, t.Nome, a.telefone, a.tel_celular
                    FROM alunos a LEFT JOIN turmas t ON t.TurmaID = a.TurmaID
                    WHERE a.data_inativacao BETWEEN %s AND %s {filtro}
                    ORDER BY dt DESC""",
                [rec.ini, rec.fim] + par + [rec.ini, rec.fim] + par)
    return [{"nome": r["nome"], "movimento": r["movimento"], "data": r["dt"],
             "turma": r["turma"] or "—",
             "telefone": r["telefone"] or r["tel_celular"] or "—"} for r in cur.fetchall()]


@relatorio(
    "alunos_por_turma", "alunos", "Alunos por modalidade e turma",
    "Quantos em cada turma, com a modalidade e as vagas que sobram.",
    [("turma", "Turma"), ("horario", "Horário"), ("modalidades", "Modalidades"),
     ("alunos", "Alunos", "numero"), ("capacidade", "Capacidade", "numero"),
     ("vagas", "Vagas", "numero")],
    criterio="Alunos ativos vinculados à turma, pela turma principal ou por aluno_turmas.",
    totaliza=["alunos"],
)
def _alunos_por_turma(cur, rec):
    cur.execute("""SELECT t.TurmaID, t.Nome, t.DiasHorario, t.Capacidade,
                          (SELECT GROUP_CONCAT(m.nome SEPARATOR ', ')
                             FROM turma_modalidades tm JOIN modalidade m ON m.id = tm.modalidade_id
                            WHERE tm.turma_id = t.TurmaID) modalidades,
                          (SELECT COUNT(*) FROM alunos a
                            WHERE COALESCE(a.ativo,1)=1
                              AND (a.TurmaID = t.TurmaID
                                   OR EXISTS (SELECT 1 FROM aluno_turmas at2
                                              WHERE at2.aluno_id=a.id AND at2.TurmaID=t.TurmaID))) alunos
                   FROM turmas t WHERE t.id_academia=%s ORDER BY t.Nome""",
                [rec.academia_id])
    linhas = []
    for r in cur.fetchall():
        cap = r["Capacidade"] or 0
        linhas.append({"turma": r["Nome"], "horario": r["DiasHorario"] or "—",
                       "modalidades": r["modalidades"] or "—", "alunos": r["alunos"],
                       "capacidade": cap or "sem limite",
                       "vagas": (cap - r["alunos"]) if cap else "—"})
    return linhas


@relatorio(
    "aniversariantes", "alunos", "Aniversariantes",
    "Do mês do período, com o contato para mandar o parabéns.",
    [("nome", "Aluno"), ("dia", "Dia"), ("idade", "Faz", "numero"),
     ("turma", "Turma"), ("telefone", "Telefone")],
    criterio="Alunos ativos que fazem aniversário no mês do período escolhido.",
)
def _aniversariantes(cur, rec):
    filtro, par = _recorte_alunos(rec)
    cur.execute(f"""SELECT a.nome, a.data_nascimento, a.telefone, a.tel_celular, t.Nome turma,
                           TIMESTAMPDIFF(YEAR, a.data_nascimento, CURDATE()) + 1 idade
                    FROM alunos a LEFT JOIN turmas t ON t.TurmaID = a.TurmaID
                    WHERE COALESCE(a.ativo,1)=1 AND a.data_nascimento IS NOT NULL
                      AND MONTH(a.data_nascimento) = %s {filtro}
                    ORDER BY DAY(a.data_nascimento)""", [rec.fim.month] + par)
    return [{"nome": r["nome"],
             "dia": r["data_nascimento"].strftime("%d/%m") if r["data_nascimento"] else "—",
             "idade": r["idade"], "turma": r["turma"] or "—",
             "telefone": r["telefone"] or r["tel_celular"] or "—"} for r in cur.fetchall()]


# =====================================================================
# Frequência
# =====================================================================

@relatorio(
    "frequencia_turma", "frequencia", "Frequência por turma",
    "Presenças, dias com aula e média por turma no período.",
    [("turma", "Turma"), ("dias", "Dias com aula", "numero"),
     ("presencas", "Presenças", "numero"), ("media", "Média por aula", "numero"),
     ("alunos", "Alunos distintos", "numero")],
    criterio="Presenças marcadas como presente, no período. Dias com aula = datas distintas com registro.",
    totaliza=["presencas"],
)
def _frequencia_turma(cur, rec):
    cur.execute("""SELECT t.Nome turma, COUNT(DISTINCT p.data_presenca) dias,
                          COUNT(*) presencas, COUNT(DISTINCT p.aluno_id) alunos
                   FROM presencas p JOIN turmas t ON t.TurmaID = p.turma_id
                   WHERE t.id_academia=%s AND COALESCE(p.presente,1)=1
                     AND p.data_presenca BETWEEN %s AND %s
                   GROUP BY t.TurmaID, t.Nome ORDER BY presencas DESC""",
                [rec.academia_id, rec.ini, rec.fim])
    return [{"turma": r["turma"], "dias": r["dias"], "presencas": r["presencas"],
             "media": round(r["presencas"] / r["dias"], 1) if r["dias"] else 0,
             "alunos": r["alunos"]} for r in cur.fetchall()]


@relatorio(
    "ranking_frequencia", "frequencia", "Ranking de frequência",
    "Quem mais treinou no período.",
    [("posicao", "#", "numero"), ("nome", "Aluno"), ("turma", "Turma"),
     ("presencas", "Presenças", "numero"), ("ultima", "Última", "data")],
    criterio="Presenças marcadas como presente, no período, por aluno ativo.",
    totaliza=["presencas"],
)
def _ranking_frequencia(cur, rec):
    filtro, par = _recorte_alunos(rec)
    cur.execute(f"""SELECT a.nome, t.Nome turma, COUNT(*) presencas,
                           MAX(p.data_presenca) ultima
                    FROM presencas p
                    JOIN alunos a ON a.id = p.aluno_id
                    LEFT JOIN turmas t ON t.TurmaID = a.TurmaID
                    WHERE COALESCE(p.presente,1)=1 AND p.data_presenca BETWEEN %s AND %s
                      AND COALESCE(a.ativo,1)=1 {filtro}
                    GROUP BY a.id, a.nome, t.Nome
                    ORDER BY presencas DESC, a.nome""", [rec.ini, rec.fim] + par)
    return [{"posicao": i, "nome": r["nome"], "turma": r["turma"] or "—",
             "presencas": r["presencas"], "ultima": r["ultima"]}
            for i, r in enumerate(cur.fetchall(), 1)]


@relatorio(
    "sem_presenca_30", "frequencia", "Sem presença há 30 dias",
    "Alunos ativos que não aparecem há um mês ou mais.",
    [("nome", "Aluno"), ("turma", "Turma"), ("ultima", "Última presença", "data"),
     ("dias", "Dias", "numero"), ("telefone", "Telefone")],
    criterio="Alunos ativos cuja última presença tem 30 dias ou mais, ou que nunca tiveram presença.",
)
def _sem_presenca_30(cur, rec):
    filtro, par = _recorte_alunos(rec)
    cur.execute(f"""SELECT a.nome, a.telefone, a.tel_celular, t.Nome turma,
                           MAX(p.data_presenca) ultima,
                           DATEDIFF(CURDATE(), MAX(p.data_presenca)) dias
                    FROM alunos a
                    LEFT JOIN turmas t ON t.TurmaID = a.TurmaID
                    LEFT JOIN presencas p ON p.aluno_id = a.id AND COALESCE(p.presente,1)=1
                    WHERE COALESCE(a.ativo,1)=1 {filtro}
                    GROUP BY a.id, a.nome, a.telefone, a.tel_celular, t.Nome
                    HAVING ultima IS NULL OR dias >= 30
                    ORDER BY dias DESC, a.nome""", par)
    return [{"nome": r["nome"], "turma": r["turma"] or "—", "ultima": r["ultima"],
             "dias": r["dias"] if r["dias"] is not None else "nunca",
             "telefone": r["telefone"] or r["tel_celular"] or "—"} for r in cur.fetchall()]


# =====================================================================
# Graduações
# =====================================================================

@relatorio(
    "distribuicao_faixa", "graduacoes", "Distribuição por faixa",
    "Quantos alunos em cada graduação.",
    [("faixa", "Faixa"), ("alunos", "Alunos", "numero"), ("fatia", "Da base", "percentual")],
    criterio="Alunos ativos, pela graduação registrada na ficha. Sem graduação entram em 'não informada'.",
    totaliza=["alunos"],
)
def _distribuicao_faixa(cur, rec):
    filtro, par = _recorte_alunos(rec)
    cur.execute(f"""SELECT COALESCE(g.faixa, 'não informada') faixa, COUNT(*) alunos,
                           MIN(COALESCE(g.ordem, 999)) ordem
                    FROM alunos a {_join_faixa()}
                    WHERE COALESCE(a.ativo,1)=1 {filtro}
                    GROUP BY faixa ORDER BY ordem, faixa""", par)
    linhas = [{"faixa": r["faixa"], "alunos": r["alunos"]} for r in cur.fetchall()]
    total = sum(l["alunos"] for l in linhas)
    for l in linhas:
        l["fatia"] = (l["alunos"] / total * 100) if total else None
    return linhas


@relatorio(
    "exames_periodo", "graduacoes", "Exames de faixa do período",
    "Quem foi avaliado, por quem, e o resultado.",
    [("aluno", "Aluno"), ("data", "Data", "data"), ("de", "Saiu de"),
     ("para", "Foi para"), ("resultado", "Resultado"), ("avaliador", "Avaliador")],
    criterio="Registros de examefaixa_judo com Data_Exame dentro do período.",
)
def _exames_periodo(cur, rec):
    cur.execute("""SELECT e.Nome_Aluno aluno, e.Data_Exame data, e.Graduacao_Atual de,
                          e.Graduacao_Pretendida para, e.Resultado resultado,
                          e.Instrutor_Avaliador avaliador
                   FROM examefaixa_judo e
                   LEFT JOIN alunos a ON a.id = e.ID_Aluno
                   WHERE e.Data_Exame BETWEEN %s AND %s
                     AND (a.id_academia = %s OR a.id IS NULL)
                   ORDER BY e.Data_Exame DESC""",
                [rec.ini, rec.fim, rec.academia_id])
    return [{"aluno": r["aluno"], "data": r["data"], "de": r["de"] or "—",
             "para": r["para"] or "—", "resultado": r["resultado"] or "—",
             "avaliador": r["avaliador"] or "—"} for r in cur.fetchall()]


@relatorio(
    "aptos_graduar", "graduacoes", "Aptos a graduar",
    "Quem já cumpriu o tempo de carência da faixa atual.",
    [("nome", "Aluno"), ("faixa", "Faixa atual"), ("desde", "Desde", "data"),
     ("meses", "Meses na faixa", "numero"), ("carencia", "Carência", "numero"),
     ("presencas", "Presenças no período", "numero")],
    criterio="Última graduação registrada em aluno_graduacao comparada à carência (em meses) da graduação. Quem nunca teve graduação registrada não entra.",
)
def _aptos_graduar(cur, rec):
    filtro, par = _recorte_alunos(rec)
    cur.execute(f"""SELECT a.id, a.nome, g.faixa, g.carencia_minima carencia,
                           MAX(ag.data) desde,
                           TIMESTAMPDIFF(MONTH, MAX(ag.data), CURDATE()) meses
                    FROM alunos a
                    JOIN aluno_graduacao ag ON ag.aluno_id = a.id
                    {_join_faixa()}
                    WHERE COALESCE(a.ativo,1)=1 {filtro}
                    GROUP BY a.id, a.nome, g.faixa, g.carencia_minima
                    HAVING carencia IS NOT NULL AND meses >= carencia
                    ORDER BY meses DESC""", par)
    brutos = cur.fetchall()
    linhas = []
    for r in brutos:
        cur.execute("""SELECT COUNT(*) n FROM presencas
                       WHERE aluno_id=%s AND COALESCE(presente,1)=1
                         AND data_presenca BETWEEN %s AND %s""",
                    [r["id"], rec.ini, rec.fim])
        linhas.append({"nome": r["nome"], "faixa": r["faixa"] or "—", "desde": r["desde"],
                       "meses": r["meses"], "carencia": r["carencia"],
                       "presencas": cur.fetchone()["n"]})
    return linhas


# =====================================================================
# Turmas e professores
# =====================================================================

DIAS = {1: "Segunda", 2: "Terça", 3: "Quarta", 4: "Quinta",
        5: "Sexta", 6: "Sábado", 7: "Domingo"}


def _hora(valor):
    """`hora_inicio` vem como intervalo de tempo; aqui vira 18:00."""
    if valor is None:
        return None
    total = int(valor.total_seconds()) if hasattr(valor, "total_seconds") else int(valor)
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}"


@relatorio(
    "grade_semana", "turmas", "Grade de horários da semana",
    "Cada dia com suas turmas, professor, idades e vagas.",
    [("dia", "Dia"), ("horario", "Horário"), ("turma", "Turma"),
     ("professor", "Professor"), ("idades", "Idades"),
     ("alunos", "Alunos", "numero"), ("vagas", "Vagas", "numero")],
    criterio=("Turmas da academia, abertas por dia da semana. A turma aparece em cada dia "
              "em que tem aula, então o total de linhas é maior que o de turmas. Vagas = "
              "capacidade menos alunos ativos vinculados."),
)
def _grade_semana(cur, rec):
    cur.execute("""SELECT t.TurmaID, t.Nome, t.dias_semana, t.DiasHorario,
                          t.hora_inicio, t.hora_fim, t.IdadeMin, t.IdadeMax, t.Capacidade,
                          (SELECT GROUP_CONCAT(DISTINCT p.nome SEPARATOR ', ')
                             FROM turma_professor tp JOIN professores p ON p.id = tp.professor_id
                            WHERE tp.TurmaID = t.TurmaID) professores,
                          (SELECT COUNT(*) FROM alunos a
                            WHERE COALESCE(a.ativo,1)=1
                              AND (a.TurmaID = t.TurmaID
                                   OR EXISTS (SELECT 1 FROM aluno_turmas at2
                                              WHERE at2.aluno_id=a.id AND at2.TurmaID=t.TurmaID))) alunos
                   FROM turmas t WHERE t.id_academia = %s""", [rec.academia_id])
    turmas = cur.fetchall()

    linhas = []
    for t in turmas:
        if rec.turma_id and t["TurmaID"] != rec.turma_id:
            continue
        cap = t["Capacidade"] or 0
        ini, fim = _hora(t["hora_inicio"]), _hora(t["hora_fim"])
        horario = f"{ini} às {fim}" if ini and fim else (t["DiasHorario"] or "—")
        idades = (f"{t['IdadeMin']} a {t['IdadeMax']} anos"
                  if t["IdadeMin"] is not None and t["IdadeMax"] is not None else "todas")
        # `dias_semana` guarda "1,3,5". Sem ele, a turma aparece uma vez só,
        # em "dia não informado" — sumir da grade seria pior.
        dias = [int(d) for d in (t["dias_semana"] or "").split(",") if d.strip().isdigit()]
        for dia in (dias or [0]):
            linhas.append({
                "_ordem": (dia if dia else 99, ini or "99:99"),
                "dia": DIAS.get(dia, "dia não informado"),
                "horario": horario,
                "turma": t["Nome"],
                "professor": t["professores"] or "—",
                "idades": idades,
                "alunos": t["alunos"],
                "vagas": (cap - t["alunos"]) if cap else "sem limite",
            })

    linhas.sort(key=lambda l: l["_ordem"])
    for l in linhas:
        l.pop("_ordem", None)
    return linhas


# =====================================================================
# Captação
# =====================================================================

@relatorio(
    "precadastros", "captacao", "Pré-cadastros do período",
    "Quem se interessou, por onde chegou e se virou aluno.",
    [("nome", "Interessado"), ("data", "Chegou em", "data"), ("origem", "Origem"),
     ("telefone", "Telefone"), ("virou_aluno", "Virou aluno")],
    criterio="Pré-cadastros criados no período. 'Virou aluno' confere se existe aluno com o mesmo CPF ou o mesmo nome na academia.",
)
def _precadastros(cur, rec):
    cur.execute("""SELECT p.nome, DATE(p.created_at) data, p.origem, p.telefone, p.tel_celular, p.cpf,
                          (SELECT COUNT(*) FROM alunos a
                            WHERE a.id_academia = p.academia_id
                              AND ((p.cpf IS NOT NULL AND p.cpf <> ''
                                    AND a.cpf = p.cpf COLLATE utf8mb4_unicode_ci)
                                   OR a.nome = p.nome COLLATE utf8mb4_unicode_ci)) virou
                   FROM pre_cadastro p
                   WHERE p.academia_id=%s AND DATE(p.created_at) BETWEEN %s AND %s
                   ORDER BY p.created_at DESC""",
                [rec.academia_id, rec.ini, rec.fim])
    return [{"nome": r["nome"], "data": r["data"], "origem": r["origem"] or "—",
             "telefone": r["telefone"] or r["tel_celular"] or "—",
             "virou_aluno": "sim" if r["virou"] else "não"} for r in cur.fetchall()]


@relatorio(
    "aulas_experimentais", "captacao", "Aulas experimentais",
    "Marcadas, comparecidas e aprovadas no período.",
    [("visitante", "Visitante"), ("data", "Data", "data"), ("turma", "Turma"),
     ("compareceu", "Compareceu"), ("aprovado", "Aprovado"), ("telefone", "Telefone")],
    criterio="Aulas experimentais com data dentro do período, de visitantes da academia.",
)
def _aulas_experimentais(cur, rec):
    cur.execute("""SELECT v.nome visitante, ae.data_aula data, t.Nome turma,
                          ae.presente, ae.aprovado, v.telefone
                   FROM aulas_experimentais ae
                   JOIN visitantes v ON v.id = ae.visitante_id
                   LEFT JOIN turmas t ON t.TurmaID = ae.turma_id
                   WHERE v.id_academia=%s AND ae.data_aula BETWEEN %s AND %s
                   ORDER BY ae.data_aula DESC""",
                [rec.academia_id, rec.ini, rec.fim])
    return [{"visitante": r["visitante"], "data": r["data"], "turma": r["turma"] or "—",
             "compareceu": "sim" if r["presente"] else "não",
             "aprovado": "sim" if r["aprovado"] else "—",
             "telefone": r["telefone"] or "—"} for r in cur.fetchall()]


@relatorio(
    "visitantes_diarias", "captacao", "Visitantes e diárias",
    "Quem treinou de passagem e quanto pagou.",
    [("visitante", "Visitante"), ("valor", "Valor", "moeda"), ("status", "Situação"),
     ("informado", "Informado em", "data"), ("confirmado", "Confirmado em", "data")],
    criterio="Pagamentos de diária de visitantes da academia, pela data de criação dentro do período.",
    totaliza=["valor"],
)
def _visitantes_diarias(cur, rec):
    cur.execute("""SELECT v.nome visitante, d.valor, d.status,
                          DATE(d.pagamento_informado_em) informado,
                          DATE(d.pagamento_confirmado_em) confirmado
                   FROM visitante_pagamentos_diaria d
                   JOIN visitantes v ON v.id = d.visitante_id
                   WHERE v.id_academia=%s AND DATE(d.criado_em) BETWEEN %s AND %s
                   ORDER BY d.criado_em DESC""",
                [rec.academia_id, rec.ini, rec.fim])
    return [{"visitante": r["visitante"], "valor": float(r["valor"] or 0),
             "status": (r["status"] or "—").capitalize(),
             "informado": r["informado"], "confirmado": r["confirmado"]}
            for r in cur.fetchall()]


# =====================================================================
# Competições
# =====================================================================

@relatorio(
    "inscricoes_evento", "competicoes", "Inscrições por evento",
    "Quantos atletas cada evento levou, e em que situação estão.",
    [("evento", "Evento"), ("data", "Data", "data"), ("inscritos", "Inscritos", "numero"),
     ("enviadas", "Enviadas", "numero"), ("avulsas", "Avulsas", "numero")],
    criterio="Inscrições da academia escolhida em eventos cuja data de início cai no período.",
    totaliza=["inscritos", "enviadas", "avulsas"],
)
def _inscricoes_evento(cur, rec):
    cur.execute("""SELECT e.nome evento, e.data_inicio data,
                          COUNT(*) inscritos,
                          SUM(i.status = 'enviada') enviadas,
                          SUM(COALESCE(i.inclusao_avulsa,0) = 1) avulsas
                   FROM eventos_competicoes_inscricoes i
                   JOIN eventos_competicoes e ON e.id = i.evento_id
                   WHERE i.academia_id=%s AND e.data_inicio BETWEEN %s AND %s
                   GROUP BY e.id, e.nome, e.data_inicio
                   ORDER BY e.data_inicio DESC""",
                [rec.academia_id, rec.ini, rec.fim])
    return [{"evento": r["evento"], "data": r["data"], "inscritos": r["inscritos"],
             "enviadas": int(r["enviadas"] or 0), "avulsas": int(r["avulsas"] or 0)}
            for r in cur.fetchall()]


@relatorio(
    "resultados_medalhas", "competicoes", "Resultados e medalhas",
    "Colocações por atleta no período.",
    [("aluno", "Atleta"), ("competicao", "Competição"), ("data", "Data", "data"),
     ("categoria", "Categoria"), ("colocacao", "Colocação"), ("ambito", "Âmbito")],
    criterio="Registros de aluno_competicoes com data dentro do período, de alunos da academia.",
)
def _resultados_medalhas(cur, rec):
    filtro, par = _recorte_alunos(rec)
    cur.execute(f"""SELECT a.nome aluno, c.competicao, c.data_competicao data,
                           c.categoria, c.colocacao, c.ambito
                    FROM aluno_competicoes c JOIN alunos a ON a.id = c.aluno_id
                    WHERE c.data_competicao BETWEEN %s AND %s {filtro}
                    ORDER BY c.data_competicao DESC""", [rec.ini, rec.fim] + par)
    return [{"aluno": r["aluno"], "competicao": r["competicao"] or "—", "data": r["data"],
             "categoria": r["categoria"] or "—", "colocacao": r["colocacao"] or "—",
             "ambito": r["ambito"] or "—"} for r in cur.fetchall()]


# =====================================================================
# Estoque
# =====================================================================

@relatorio(
    "estoque_saldo", "estoque", "Saldo por produto",
    "O que tem, onde está e quanto vale pelo custo.",
    [("produto", "Produto"), ("variacao", "Variação"), ("local", "Local"),
     ("quantidade", "Quantidade", "numero"), ("custo", "Custo unitário", "moeda"),
     ("total", "Valor parado", "moeda")],
    criterio="Saldos atuais por local da academia. Valor = quantidade × custo da variação (ou do produto).",
    totaliza=["quantidade", "total"],
)
def _estoque_saldo(cur, rec):
    cur.execute("""SELECT pr.nome produto, va.nome variacao, lo.nome local,
                          s.quantidade, COALESCE(va.custo, pr.custo, 0) custo
                   FROM estoque_saldo s
                   JOIN estoque_variacao va ON va.id = s.variacao_id
                   JOIN estoque_produto pr ON pr.id = va.produto_id
                   JOIN estoque_local lo ON lo.id = s.local_id
                   WHERE lo.id_academia=%s AND s.quantidade <> 0
                   ORDER BY pr.nome, va.nome""",
                [rec.academia_id])
    return [{"produto": r["produto"], "variacao": r["variacao"] or "—", "local": r["local"],
             "quantidade": float(r["quantidade"] or 0), "custo": float(r["custo"] or 0),
             "total": float(r["quantidade"] or 0) * float(r["custo"] or 0)}
            for r in cur.fetchall()]


@relatorio(
    "estoque_movimentos", "estoque", "Movimentações do período",
    "Entradas, saídas e ajustes, com quem lançou.",
    [("data", "Data", "data"), ("produto", "Produto"), ("sentido", "Sentido"),
     ("motivo", "Motivo"), ("quantidade", "Quantidade", "numero"), ("local", "Local")],
    criterio="Movimentos de estoque dos locais da academia, pela data de criação.",
    totaliza=["quantidade"],
)
def _estoque_movimentos(cur, rec):
    cur.execute("""SELECT DATE(m.criado_em) data, pr.nome produto, m.sentido, m.motivo,
                          m.quantidade, lo.nome local
                   FROM estoque_movimento m
                   JOIN estoque_variacao va ON va.id = m.variacao_id
                   JOIN estoque_produto pr ON pr.id = va.produto_id
                   LEFT JOIN estoque_local lo ON lo.id = m.local_id
                   WHERE m.id_academia=%s AND DATE(m.criado_em) BETWEEN %s AND %s
                   ORDER BY m.criado_em DESC""",
                [rec.academia_id, rec.ini, rec.fim])
    return [{"data": r["data"], "produto": r["produto"], "sentido": r["sentido"] or "—",
             "motivo": r["motivo"] or "—", "quantidade": float(r["quantidade"] or 0),
             "local": r["local"] or "—"} for r in cur.fetchall()]


# =====================================================================
# Cadastro incompleto — um relatório por campo que falta
# =====================================================================
# Todos olham só alunos ATIVOS: cobrar CPF de quem já saiu não muda nada.

FALTAS = [
    ("falta_endereco", "Sem endereço", "CEP ou rua em branco",
     "(a.cep IS NULL OR a.cep='' OR a.rua IS NULL OR a.rua='')"),
    ("falta_telefone", "Sem telefone", "Nem fixo nem celular",
     "((a.telefone IS NULL OR a.telefone='') AND (a.tel_celular IS NULL OR a.tel_celular=''))"),
    ("falta_faixa", "Sem faixa", "Graduação não lançada na ficha",
     "a.graduacao_id IS NULL"),
    ("falta_cpf", "Sem CPF", "Trava cobrança online e inscrição federada",
     "(a.cpf IS NULL OR a.cpf='')"),
    ("falta_turma", "Sem turma", "Não entra em nenhuma chamada",
     "(a.TurmaID IS NULL AND NOT EXISTS (SELECT 1 FROM aluno_turmas at2 WHERE at2.aluno_id=a.id))"),
    ("falta_foto", "Sem foto", "A chamada fica só com nomes",
     "(a.foto IS NULL OR a.foto='')"),
    ("falta_modalidade", "Sem modalidade", "Fica fora de todo recorte por modalidade",
     "NOT EXISTS (SELECT 1 FROM aluno_modalidades am WHERE am.aluno_id=a.id)"),
    ("falta_responsavel", "Menor sem responsável", "Responsável financeiro em branco",
     "(TIMESTAMPDIFF(YEAR, a.data_nascimento, CURDATE()) < 18 "
     "AND (a.responsavel_financeiro_nome IS NULL OR a.responsavel_financeiro_nome=''))"),
    ("falta_sexo", "Sem sexo", "Trava chave de competição",
     "(a.sexo IS NULL OR a.sexo='')"),
    ("falta_nascimento", "Sem data de nascimento", "Sem categoria de idade",
     "a.data_nascimento IS NULL"),
    ("falta_email", "Sem e-mail", "Não recebe cobrança nem aviso",
     "(a.email IS NULL OR a.email='')"),
]


def _iniciais(nome):
    """Duas letras para o círculo da tabela: 'Marcos Silveira' -> 'MS'."""
    partes = [p for p in (nome or "").split() if p[:1].isalpha()]
    if not partes:
        return "?"
    if len(partes) == 1:
        return partes[0][:2].upper()
    return (partes[0][:1] + partes[-1][:1]).upper()


def _monta_falta(condicao):
    def consulta(cur, rec):
        filtro, par = _recorte_alunos(rec)
        cur.execute(f"""SELECT a.id, a.nome, a.data_matricula, t.Nome turma,
                               a.telefone, a.tel_celular, g.faixa,
                               TIMESTAMPDIFF(YEAR, a.data_nascimento, CURDATE()) idade
                        FROM alunos a
                        LEFT JOIN turmas t ON t.TurmaID = a.TurmaID
                        {_join_faixa()}
                        WHERE COALESCE(a.ativo,1)=1 AND {condicao} {filtro}
                        ORDER BY a.data_matricula, a.nome""", par)
        linhas = []
        for r in cur.fetchall():
            apoio = [x for x in (r["faixa"], f"{r['idade']} anos" if r["idade"] else None) if x]
            linhas.append({
                "_aluno_id": r["id"],
                "_iniciais": _iniciais(r["nome"]),
                "_sub": " · ".join(apoio) or "sem faixa nem idade",
                "nome": r["nome"],
                "matricula": r["data_matricula"],
                "turma": r["turma"] or "—",
                "telefone": r["telefone"] or r["tel_celular"] or "—",
                "acao": "Corrigir",
            })
        return linhas
    return consulta


for _id, _nome, _desc, _cond in FALTAS:
    relatorio(
        _id, "cadastro", _nome, _desc,
        [("nome", "Aluno", "pessoa"), ("matricula", "Matrícula", "data"),
         ("turma", "Turma"), ("telefone", "Contato"),
         Coluna("acao", "Ação", "acao", so_tela=True)],
        criterio=("Somente alunos ATIVOS desta academia. O período não se aplica: o cadastro "
                  "está incompleto hoje. Ordenado por tempo de casa — os mais antigos primeiro."),
    )(_monta_falta(_cond))


def contagem_faltas(cur, rec):
    """Os números dos cartões de cadastro incompleto, em uma consulta só."""
    filtro, par = _recorte_alunos(rec)
    partes = ", ".join(f"SUM({cond}) AS `{rid}`" for rid, _, _, cond in FALTAS)
    cur.execute(f"""SELECT COUNT(*) AS total, {partes}
                    FROM alunos a WHERE COALESCE(a.ativo,1)=1 {filtro}""", par)
    linha = cur.fetchone() or {}
    return {"total": int(linha.get("total") or 0),
            **{rid: int(linha.get(rid) or 0) for rid, _, _, _ in FALTAS}}
