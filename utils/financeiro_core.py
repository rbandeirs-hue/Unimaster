"""Núcleo do módulo financeiro — a fonte central de verdade do saldo.

Por que este arquivo existe
---------------------------
Antes, cada tela somava valores do seu jeito: o dashboard fazia
``receitas - despesas`` do período, o histórico somava ``valor`` das pagas, e
nenhuma delas sabia *onde* o dinheiro estava. Não havia conta financeira: a
forma de pagamento ("Pix", "Dinheiro") era só um rótulo na linha.

Aqui o saldo tem uma definição só::

    saldo da conta = saldo_inicial
                   + entradas efetivadas
                   - saídas efetivadas

Lançamento pendente não entra no saldo. Transferência interna move dinheiro
entre contas sem alterar o patrimônio total, porque gera uma saída e uma
entrada de mesmo valor.

Modos de controle (por academia, em ``fin_config``)
---------------------------------------------------
``desativado``  o financeiro não interfere em nada;
``parcial``     registra tudo e calcula saldo, mas não bloqueia por falta de
                saldo — a conta pode ficar negativa, com alerta. É o modo de
                implantação gradual;
``total``       o saldo precisa ser fiel: saída maior que o disponível é
                recusada, com a diferença explicada.

Concorrência
------------
No modo total, duas saídas simultâneas não podem gastar o mesmo saldo. Por
isso a verificação e a gravação acontecem na mesma transação, com a linha da
conta travada por ``SELECT ... FOR UPDATE``. Sem a trava, as duas leriam o
mesmo saldo antes de qualquer gravação e as duas passariam.
"""

from decimal import Decimal

from flask import request
from flask_login import current_user

from config import get_db_connection


# =====================================================================
# Erros
# =====================================================================
class ErroFinanceiro(Exception):
    """Falha de regra financeira — a mensagem é mostrada ao usuário."""


class SaldoInsuficiente(ErroFinanceiro):
    def __init__(self, conta_nome, disponivel, solicitado):
        self.conta_nome = conta_nome
        self.disponivel = Decimal(str(disponivel))
        self.solicitado = Decimal(str(solicitado))
        self.diferenca = self.solicitado - self.disponivel
        super().__init__(
            f"Saldo insuficiente na conta {conta_nome}. "
            f"Saldo disponível: {_moeda(self.disponivel)} · "
            f"Valor da movimentação: {_moeda(self.solicitado)} · "
            f"Diferença: {_moeda(self.diferenca)}"
        )


class PeriodoFechado(ErroFinanceiro):
    def __init__(self, mes, ano):
        super().__init__(
            f"O mês {mes:02d}/{ano} está fechado. Reabra o período para lançar nele."
        )


def _moeda(v):
    return f"R$ {Decimal(str(v)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# =====================================================================
# Configuração de modo
# =====================================================================
MODO_DESATIVADO = "desativado"
MODO_PARCIAL = "parcial"
MODO_TOTAL = "total"


def modo_controle(cur, id_academia):
    """Modo do controle financeiro da academia. Sem registro, `desativado`."""
    cur.execute("SELECT modo FROM fin_config WHERE id_academia = %s", (id_academia,))
    linha = cur.fetchone()
    if not linha:
        return MODO_DESATIVADO
    return (linha["modo"] if isinstance(linha, dict) else linha[0]) or MODO_DESATIVADO


def definir_modo(conn, cur, id_academia, modo, usuario_id=None):
    """Grava o modo. A validação de quem pode virar para `total` é da rota."""
    if modo not in (MODO_DESATIVADO, MODO_PARCIAL, MODO_TOTAL):
        raise ErroFinanceiro(f"Modo inválido: {modo}")
    anterior = modo_controle(cur, id_academia)
    cur.execute(
        """INSERT INTO fin_config (id_academia, modo, atualizado_por)
           VALUES (%s, %s, %s)
           ON DUPLICATE KEY UPDATE modo = VALUES(modo), atualizado_por = VALUES(atualizado_por)""",
        (id_academia, modo, usuario_id),
    )
    auditar(cur, id_academia, "fin_config", id_academia, "modo",
            status_anterior=anterior, status_novo=modo, usuario_id=usuario_id)
    return anterior


# =====================================================================
# Auditoria
# =====================================================================
def auditar(cur, id_academia, entidade, entidade_id, acao, *,
            valor_anterior=None, valor_novo=None,
            status_anterior=None, status_novo=None,
            motivo=None, detalhes=None, usuario_id=None):
    """Registra a mudança. Nunca levanta: auditoria não pode derrubar a operação."""
    try:
        if usuario_id is None:
            usuario_id = getattr(current_user, "id", None)
        ip = None
        try:
            ip = request.headers.get("X-Forwarded-For", request.remote_addr)
            if ip:
                ip = ip.split(",")[0].strip()[:45]
        except Exception:
            ip = None
        cur.execute(
            """INSERT INTO fin_auditoria
               (id_academia, entidade, entidade_id, acao, valor_anterior, valor_novo,
                status_anterior, status_novo, motivo, detalhes, usuario_id, ip)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (id_academia, entidade, entidade_id, acao, valor_anterior, valor_novo,
             status_anterior, status_novo, motivo, detalhes, usuario_id, ip),
        )
    except Exception:
        pass


# =====================================================================
# Saldo
# =====================================================================
def saldo_conta(cur, id_conta, para_atualizar=False):
    """Saldo atual da conta. `para_atualizar` trava a linha até o commit."""
    cur.execute(
        "SELECT id, id_academia, nome, saldo_inicial FROM fin_contas WHERE id = %s"
        + (" FOR UPDATE" if para_atualizar else ""),
        (id_conta,),
    )
    conta = cur.fetchone()
    if not conta:
        raise ErroFinanceiro("Conta financeira não encontrada.")

    cur.execute(
        """SELECT COALESCE(SUM(CASE WHEN sentido = 'entrada' THEN valor ELSE -valor END), 0) AS mov
           FROM fin_lancamentos
           WHERE id_conta = %s AND status = 'efetivado'"""
        # Leitura travada também na soma: sem isto, sob REPEATABLE READ, a
        # segunda transação enxergaria o snapshot aberto antes do commit da
        # primeira e as duas gastariam o mesmo saldo.
        + (" FOR UPDATE" if para_atualizar else ""),
        (id_conta,),
    )
    linha = cur.fetchone()
    mov = linha["mov"] if isinstance(linha, dict) else linha[0]
    conta["saldo"] = Decimal(str(conta["saldo_inicial"] or 0)) + Decimal(str(mov or 0))
    return conta


def saldos_por_conta(cur, id_academia, so_ativas=True):
    """Saldo de cada conta da academia, em uma consulta. Usado no dashboard."""
    cur.execute(
        """SELECT c.id, c.nome, c.tipo, c.ativo, c.saldo_inicial,
                  COALESCE(SUM(CASE WHEN l.status = 'efetivado'
                                    THEN CASE WHEN l.sentido = 'entrada' THEN l.valor ELSE -l.valor END
                                    ELSE 0 END), 0) AS movimento
           FROM fin_contas c
           LEFT JOIN fin_lancamentos l ON l.id_conta = c.id
           WHERE c.id_academia = %s """ + ("AND c.ativo = 1 " if so_ativas else "") +
        """GROUP BY c.id, c.nome, c.tipo, c.ativo, c.saldo_inicial
           ORDER BY c.nome""",
        (id_academia,),
    )
    contas = cur.fetchall()
    for c in contas:
        c["saldo"] = Decimal(str(c["saldo_inicial"] or 0)) + Decimal(str(c["movimento"] or 0))
    return contas


def saldo_total(cur, id_academia):
    """Patrimônio da academia — a soma das contas. Transferência não altera."""
    return sum((c["saldo"] for c in saldos_por_conta(cur, id_academia)), Decimal("0"))


# =====================================================================
# Guardas
# =====================================================================
def _competencia_fechada(cur, id_academia, data_competencia):
    cur.execute(
        """SELECT status FROM fin_fechamentos
           WHERE id_academia = %s AND ano = %s AND mes = %s""",
        (id_academia, data_competencia.year, data_competencia.month),
    )
    linha = cur.fetchone()
    if not linha:
        return False
    status = linha["status"] if isinstance(linha, dict) else linha[0]
    return status == "fechado"


def conferir_saldo(cur, id_academia, id_conta, valor, modo=None):
    """No modo total, recusa saída maior que o disponível. Trava a conta.

    Chamar SEMPRE dentro da transação que vai gravar o lançamento — é a trava
    que impede duas saídas simultâneas de gastarem o mesmo saldo.
    """
    if modo is None:
        modo = modo_controle(cur, id_academia)
    conta = saldo_conta(cur, id_conta, para_atualizar=True)
    if modo == MODO_TOTAL and conta["saldo"] < Decimal(str(valor)):
        raise SaldoInsuficiente(conta["nome"], conta["saldo"], valor)
    return conta


# =====================================================================
# Lançamentos
# =====================================================================
def lancar(conn, cur, *, id_academia, id_conta, sentido, valor, descricao,
           data_competencia, data_efetivacao=None, status="efetivado",
           origem="manual", origem_id=None, id_categoria=None,
           id_forma_pagamento=None, id_aluno=None, id_responsavel=None,
           observacoes=None, comprovante_url=None, usuario_id=None,
           id_transferencia=None, id_lancamento_origem=None):
    """Grava um lançamento no razão e devolve o id.

    `status='pendente'` registra sem afetar o saldo (contas a pagar/receber).
    `status='efetivado'` afeta o saldo — e por isso passa pela conferência.
    """
    valor = Decimal(str(valor))
    if valor <= 0:
        raise ErroFinanceiro("O valor da movimentação precisa ser maior que zero.")
    if sentido not in ("entrada", "saida"):
        raise ErroFinanceiro(f"Sentido inválido: {sentido}")

    # A trava vem antes de qualquer outra leitura: se o fechamento fosse
    # consultado primeiro, ele abriria o snapshot da transação e a conferência
    # de saldo passaria a enxergar dados velhos.
    if status == "efetivado":
        if sentido == "saida":
            conferir_saldo(cur, id_academia, id_conta, valor)
        else:
            # trava a conta também na entrada: mantém a ordem de bloqueio
            # sempre a mesma e evita impasse entre duas transações
            saldo_conta(cur, id_conta, para_atualizar=True)
        if data_efetivacao is None:
            data_efetivacao = data_competencia

    if _competencia_fechada(cur, id_academia, data_competencia):
        raise PeriodoFechado(data_competencia.month, data_competencia.year)

    cur.execute(
        """INSERT INTO fin_lancamentos
           (id_academia, id_conta, sentido, valor, data_competencia, data_efetivacao,
            status, descricao, id_categoria, id_forma_pagamento, origem, origem_id,
            id_aluno, id_responsavel, id_lancamento_origem, id_transferencia,
            comprovante_url, observacoes, criado_por)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (id_academia, id_conta, sentido, valor, data_competencia, data_efetivacao,
         status, descricao, id_categoria, id_forma_pagamento, origem, origem_id,
         id_aluno, id_responsavel, id_lancamento_origem, id_transferencia,
         comprovante_url, observacoes, usuario_id or getattr(current_user, "id", None)),
    )
    lanc_id = cur.lastrowid
    auditar(cur, id_academia, "fin_lancamentos", lanc_id, "criar",
            valor_novo=valor, status_novo=status, usuario_id=usuario_id,
            detalhes=f"{sentido} · {origem}:{origem_id} · conta {id_conta}")
    return lanc_id


def efetivar(conn, cur, lanc_id, *, data_efetivacao=None, usuario_id=None):
    """Passa um lançamento pendente para efetivado — aí sim ele entra no saldo."""
    cur.execute("SELECT * FROM fin_lancamentos WHERE id = %s FOR UPDATE", (lanc_id,))
    lanc = cur.fetchone()
    if not lanc:
        raise ErroFinanceiro("Lançamento não encontrado.")
    if lanc["status"] == "efetivado":
        return lanc_id
    if lanc["status"] in ("cancelado", "estornado"):
        raise ErroFinanceiro("Lançamento cancelado ou estornado não pode ser efetivado.")

    if lanc["sentido"] == "saida":
        conferir_saldo(cur, lanc["id_academia"], lanc["id_conta"], lanc["valor"])

    cur.execute(
        "UPDATE fin_lancamentos SET status = 'efetivado', data_efetivacao = %s, atualizado_por = %s WHERE id = %s",
        (data_efetivacao or lanc["data_competencia"],
         usuario_id or getattr(current_user, "id", None), lanc_id),
    )
    auditar(cur, lanc["id_academia"], "fin_lancamentos", lanc_id, "efetivar",
            status_anterior=lanc["status"], status_novo="efetivado", usuario_id=usuario_id)
    return lanc_id


def cancelar(conn, cur, lanc_id, *, motivo=None, usuario_id=None):
    """Cancela um lançamento. Não apaga: o histórico continua consultável."""
    cur.execute("SELECT * FROM fin_lancamentos WHERE id = %s FOR UPDATE", (lanc_id,))
    lanc = cur.fetchone()
    if not lanc:
        raise ErroFinanceiro("Lançamento não encontrado.")
    if lanc["status"] == "cancelado":
        return lanc_id
    if lanc["status"] == "efetivado":
        raise ErroFinanceiro(
            "Lançamento já efetivado não pode ser cancelado — use o estorno, "
            "que mantém o original e registra a reversão."
        )
    cur.execute(
        "UPDATE fin_lancamentos SET status = 'cancelado', atualizado_por = %s WHERE id = %s",
        (usuario_id or getattr(current_user, "id", None), lanc_id),
    )
    auditar(cur, lanc["id_academia"], "fin_lancamentos", lanc_id, "cancelar",
            status_anterior=lanc["status"], status_novo="cancelado",
            motivo=motivo, usuario_id=usuario_id)
    return lanc_id


def estornar(conn, cur, lanc_id, *, motivo=None, usuario_id=None):
    """Reverte um lançamento efetivado criando o contrário dele.

    O original continua lá, marcado como estornado, e o novo lançamento aponta
    para ele. Estorno não é apagar: os dois ficam no extrato.
    """
    cur.execute("SELECT * FROM fin_lancamentos WHERE id = %s FOR UPDATE", (lanc_id,))
    lanc = cur.fetchone()
    if not lanc:
        raise ErroFinanceiro("Lançamento não encontrado.")
    if lanc["status"] != "efetivado":
        raise ErroFinanceiro("Só lançamento efetivado pode ser estornado.")

    contrario = "saida" if lanc["sentido"] == "entrada" else "entrada"
    novo = lancar(
        conn, cur,
        id_academia=lanc["id_academia"], id_conta=lanc["id_conta"],
        sentido=contrario, valor=lanc["valor"],
        descricao=f"Estorno — {lanc['descricao']}"[:255],
        data_competencia=lanc["data_competencia"],
        status="efetivado", origem="estorno", origem_id=lanc["id"],
        id_categoria=lanc["id_categoria"], id_forma_pagamento=lanc["id_forma_pagamento"],
        id_aluno=lanc["id_aluno"], id_responsavel=lanc["id_responsavel"],
        observacoes=motivo, usuario_id=usuario_id, id_lancamento_origem=lanc["id"],
    )
    # O original continua 'efetivado' — o dinheiro de fato entrou ou saiu, e o
    # lançamento de estorno é que o neutraliza. Marcá-lo como 'estornado' o
    # tiraria da soma do saldo e o valor seria descontado duas vezes: uma pela
    # exclusão do original, outra pelo lançamento contrário.
    cur.execute(
        "UPDATE fin_lancamentos SET id_estorno = %s, atualizado_por = %s WHERE id = %s",
        (novo, usuario_id or getattr(current_user, "id", None), lanc_id),
    )
    auditar(cur, lanc["id_academia"], "fin_lancamentos", lanc_id, "estornar",
            valor_anterior=lanc["valor"], status_anterior="efetivado",
            status_novo="estornado", motivo=motivo, usuario_id=usuario_id,
            detalhes=f"lancamento de estorno: {novo}")
    return novo


# =====================================================================
# Transferência entre contas
# =====================================================================
def transferir(conn, cur, *, id_academia, id_conta_origem, id_conta_destino,
               valor, data, descricao=None, usuario_id=None):
    """Move dinheiro entre contas da mesma academia.

    Gera dois lançamentos ligados pelo id da transferência. Não é receita nem
    despesa: o patrimônio total continua o mesmo, muda só onde ele está.
    """
    if id_conta_origem == id_conta_destino:
        raise ErroFinanceiro("Escolha contas diferentes para a transferência.")
    valor = Decimal(str(valor))
    if valor <= 0:
        raise ErroFinanceiro("O valor da transferência precisa ser maior que zero.")

    # Trava sempre na mesma ordem (menor id primeiro) para duas transferências
    # cruzadas não ficarem esperando uma pela outra.
    primeira, segunda = sorted((id_conta_origem, id_conta_destino))
    saldo_conta(cur, primeira, para_atualizar=True)
    saldo_conta(cur, segunda, para_atualizar=True)

    modo = modo_controle(cur, id_academia)
    origem = saldo_conta(cur, id_conta_origem)
    if modo == MODO_TOTAL and origem["saldo"] < valor:
        raise SaldoInsuficiente(origem["nome"], origem["saldo"], valor)

    destino = saldo_conta(cur, id_conta_destino)
    texto = descricao or f"Transferência {origem['nome']} → {destino['nome']}"

    cur.execute(
        """INSERT INTO fin_transferencias
           (id_academia, id_conta_origem, id_conta_destino, valor, data, descricao, criado_por)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (id_academia, id_conta_origem, id_conta_destino, valor, data, texto,
         usuario_id or getattr(current_user, "id", None)),
    )
    transf_id = cur.lastrowid

    comum = dict(id_academia=id_academia, valor=valor, data_competencia=data,
                 status="efetivado", origem="transferencia", origem_id=transf_id,
                 id_transferencia=transf_id, usuario_id=usuario_id)
    saida = lancar(conn, cur, id_conta=id_conta_origem, sentido="saida",
                   descricao=f"{texto} (saída)"[:255], **comum)
    entrada = lancar(conn, cur, id_conta=id_conta_destino, sentido="entrada",
                     descricao=f"{texto} (entrada)"[:255], **comum)

    auditar(cur, id_academia, "fin_transferencias", transf_id, "criar",
            valor_novo=valor, usuario_id=usuario_id,
            detalhes=f"saida:{saida} entrada:{entrada}")
    return {"id": transf_id, "lancamento_saida": saida, "lancamento_entrada": entrada}


# =====================================================================
# Extrato
# =====================================================================
def extrato(cur, id_academia, *, id_conta=None, inicio=None, fim=None,
            sentido=None, status="efetivado", id_aluno=None, origem=None):
    """Movimentações em ordem de data, com saldo corrente linha a linha."""
    onde = ["l.id_academia = %s"]
    args = [id_academia]
    if id_conta:
        onde.append("l.id_conta = %s"); args.append(id_conta)
    if inicio:
        onde.append("COALESCE(l.data_efetivacao, l.data_competencia) >= %s"); args.append(inicio)
    if fim:
        onde.append("COALESCE(l.data_efetivacao, l.data_competencia) <= %s"); args.append(fim)
    if sentido:
        onde.append("l.sentido = %s"); args.append(sentido)
    if status:
        onde.append("l.status = %s"); args.append(status)
    if id_aluno:
        onde.append("l.id_aluno = %s"); args.append(id_aluno)
    if origem:
        onde.append("l.origem = %s"); args.append(origem)

    cur.execute(
        """SELECT l.*, c.nome AS conta_nome, c.tipo AS conta_tipo,
                  cat.nome AS categoria_nome, fp.nome AS forma_nome, a.nome AS aluno_nome
           FROM fin_lancamentos l
           JOIN fin_contas c ON c.id = l.id_conta
           LEFT JOIN fin_categorias cat ON cat.id = l.id_categoria
           LEFT JOIN formas_pagamento fp ON fp.id = l.id_forma_pagamento
           LEFT JOIN alunos a ON a.id = l.id_aluno
           WHERE """ + " AND ".join(onde) +
        """ ORDER BY COALESCE(l.data_efetivacao, l.data_competencia), l.id""",
        tuple(args),
    )
    linhas = cur.fetchall()

    # Saldo inicial do recorte: tudo que foi efetivado antes do período.
    saldo = Decimal("0")
    if id_conta:
        cur.execute("SELECT COALESCE(saldo_inicial, 0) AS s FROM fin_contas WHERE id = %s", (id_conta,))
        r = cur.fetchone()
        saldo = Decimal(str((r["s"] if isinstance(r, dict) else r[0]) or 0))
        if inicio:
            cur.execute(
                """SELECT COALESCE(SUM(CASE WHEN sentido='entrada' THEN valor ELSE -valor END), 0) AS m
                   FROM fin_lancamentos
                   WHERE id_conta = %s AND status = 'efetivado'
                     AND COALESCE(data_efetivacao, data_competencia) < %s""",
                (id_conta, inicio),
            )
            r = cur.fetchone()
            saldo += Decimal(str((r["m"] if isinstance(r, dict) else r[0]) or 0))

    saldo_inicial = saldo
    entradas = saidas = Decimal("0")
    for l in linhas:
        v = Decimal(str(l["valor"] or 0))
        if l["sentido"] == "entrada":
            saldo += v; entradas += v
        else:
            saldo -= v; saidas += v
        l["saldo_corrente"] = saldo

    return {
        "linhas": linhas,
        "saldo_inicial": saldo_inicial,
        "entradas": entradas,
        "saidas": saidas,
        "saldo_final": saldo,
    }


# =====================================================================
# Contas: criação assistida e resolução a partir da forma de pagamento
# =====================================================================
# Palpite de tipo pelo nome da forma. Serve só para o cadastro assistido:
# o gestor pode trocar depois, e a conta é o que vale.
_TIPO_POR_NOME = (
    ("pix", "pix"), ("dinheiro", "caixa"), ("especie", "caixa"), ("espécie", "caixa"),
    ("caixa", "caixa"), ("credito", "cartao"), ("crédito", "cartao"),
    ("debito", "cartao"), ("débito", "cartao"), ("cartao", "cartao"), ("cartão", "cartao"),
    ("boleto", "banco"), ("transferencia", "banco"), ("transferência", "banco"),
    ("ted", "banco"), ("doc", "banco"), ("banco", "banco"),
)


def _tipo_sugerido(nome):
    n = (nome or "").strip().lower()
    for chave, tipo in _TIPO_POR_NOME:
        if chave in n:
            return tipo
    return "outra"


def criar_conta(conn, cur, *, id_academia, nome, tipo="outra", saldo_inicial=0,
                data_saldo_inicial=None, observacao=None, usuario_id=None):
    """Cria uma conta financeira e devolve o id."""
    cur.execute(
        """INSERT INTO fin_contas
           (id_academia, nome, tipo, saldo_inicial, data_saldo_inicial, observacao, criado_por)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (id_academia, nome.strip(), tipo, Decimal(str(saldo_inicial or 0)),
         data_saldo_inicial, observacao, usuario_id or getattr(current_user, "id", None)),
    )
    conta_id = cur.lastrowid
    auditar(cur, id_academia, "fin_contas", conta_id, "criar",
            valor_novo=Decimal(str(saldo_inicial or 0)), usuario_id=usuario_id,
            detalhes=f"{nome} ({tipo})")
    return conta_id


def preparar_contas(conn, cur, id_academia, usuario_id=None):
    """Cria uma conta para cada forma de pagamento em uso e as amarra.

    Passo de implantação: a academia já tem formas cadastradas ("Pix",
    "Dinheiro", "Cartão"), e o que falta é dizer onde o dinheiro de cada uma
    fica. Aqui cada forma ganha uma conta de mesmo nome, que o gestor renomeia
    ou reagrupa depois — duas formas podem apontar para a mesma conta.

    Devolve o que foi criado. Rodar de novo não duplica nada.
    """
    cur.execute(
        """SELECT id, nome, id_conta_padrao FROM formas_pagamento
           WHERE id_academia = %s AND COALESCE(ativo,1) = 1 ORDER BY ordem, nome""",
        (id_academia,))
    formas = cur.fetchall()

    cur.execute("SELECT id, nome FROM fin_contas WHERE id_academia = %s", (id_academia,))
    por_nome = {(c["nome"] or "").strip().lower(): c["id"] for c in cur.fetchall()}

    criadas, vinculadas = [], []
    for f in formas:
        if f["id_conta_padrao"]:
            continue
        chave = (f["nome"] or "").strip().lower()
        conta_id = por_nome.get(chave)
        if not conta_id:
            conta_id = criar_conta(
                conn, cur, id_academia=id_academia, nome=f["nome"],
                tipo=_tipo_sugerido(f["nome"]), usuario_id=usuario_id,
                observacao="Criada na implantação do controle financeiro.")
            por_nome[chave] = conta_id
            criadas.append({"id": conta_id, "nome": f["nome"]})
        cur.execute("UPDATE formas_pagamento SET id_conta_padrao = %s WHERE id = %s",
                    (conta_id, f["id"]))
        vinculadas.append({"forma": f["nome"], "conta_id": conta_id})

    # Sem nenhuma forma cadastrada, ao menos o caixa precisa existir.
    if not por_nome:
        conta_id = criar_conta(conn, cur, id_academia=id_academia, nome="Caixa",
                               tipo="caixa", usuario_id=usuario_id,
                               observacao="Conta padrão criada na implantação.")
        criadas.append({"id": conta_id, "nome": "Caixa"})

    return {"criadas": criadas, "vinculadas": vinculadas}


def conta_padrao(cur, id_academia, id_forma_pagamento=None):
    """Conta de destino de um recebimento.

    Ordem: a conta amarrada à forma de pagamento; senão a primeira conta ativa
    da academia. Devolve None quando a academia ainda não tem conta nenhuma —
    é o que mantém o razão opcional enquanto o modo é `desativado`.
    """
    if id_forma_pagamento:
        cur.execute(
            """SELECT c.id FROM formas_pagamento f
               JOIN fin_contas c ON c.id = f.id_conta_padrao AND c.ativo = 1
               WHERE f.id = %s AND c.id_academia = %s""",
            (id_forma_pagamento, id_academia))
        linha = cur.fetchone()
        if linha:
            return linha["id"] if isinstance(linha, dict) else linha[0]

    cur.execute(
        """SELECT id FROM fin_contas
           WHERE id_academia = %s AND ativo = 1 ORDER BY id LIMIT 1""",
        (id_academia,))
    linha = cur.fetchone()
    return (linha["id"] if isinstance(linha, dict) else linha[0]) if linha else None


# =====================================================================
# Integração com o fluxo de pagamento existente
# =====================================================================
def registrar_entrada_de_pagamento(conn, cur, *, id_academia, valor, descricao,
                                   data, id_forma_pagamento=None, id_aluno=None,
                                   origem="mensalidade", origem_id=None,
                                   id_receita=None, usuario_id=None):
    """Espelha no razão um pagamento que o sistema acabou de dar baixa.

    Chamada pelo fluxo que já existe, depois de gravar a receita. Devolve o id
    do lançamento, ou None quando o razão ainda não se aplica — academia sem
    conta cadastrada ou controle desativado. Nunca derruba a baixa: se o razão
    falhar, o pagamento continua registrado como sempre foi.
    """
    try:
        if modo_controle(cur, id_academia) == MODO_DESATIVADO:
            return None
        if not valor or Decimal(str(valor)) <= 0:
            return None
        id_conta = conta_padrao(cur, id_academia, id_forma_pagamento)
        if not id_conta:
            return None

        lanc_id = lancar(
            conn, cur, id_academia=id_academia, id_conta=id_conta, sentido="entrada",
            valor=valor, descricao=descricao[:255], data_competencia=data,
            data_efetivacao=data, status="efetivado", origem=origem,
            origem_id=origem_id, id_forma_pagamento=id_forma_pagamento,
            id_aluno=id_aluno, usuario_id=usuario_id,
        )
        if id_receita:
            cur.execute("UPDATE receitas SET id_lancamento = %s WHERE id = %s",
                        (lanc_id, id_receita))
        return lanc_id
    except ErroFinanceiro:
        # Regra financeira barrou (mês fechado, saldo). A baixa em si já
        # aconteceu; quem chamou decide se desfaz.
        raise
    except Exception:
        # Falha inesperada no razão não pode impedir o registro do pagamento.
        return None


def reatribuir_conta(conn, cur, lanc_id, id_conta_nova, *, motivo=None, usuario_id=None):
    """Move um lançamento para outra conta, mantendo valor, data e origem.

    Existe porque a conta é o único dado do razão que o sistema não conseguia
    inferir do histórico: `despesas` não guarda forma de pagamento, então toda
    despesa antiga caiu na conta padrão. Corrigir isso não é editar dinheiro —
    é dizer de onde ele saiu de fato.

    O saldo das duas contas muda; o patrimônio total, não.
    """
    cur.execute("SELECT * FROM fin_lancamentos WHERE id = %s FOR UPDATE", (lanc_id,))
    lanc = cur.fetchone()
    if not lanc:
        raise ErroFinanceiro("Lançamento não encontrado.")
    if int(lanc["id_conta"]) == int(id_conta_nova):
        return lanc_id
    if lanc["status"] != "efetivado":
        raise ErroFinanceiro("Só lançamento efetivado tem conta a corrigir.")
    if lanc["id_transferencia"]:
        raise ErroFinanceiro(
            "Este lançamento faz parte de uma transferência — cancele a "
            "transferência em vez de trocar a conta de um dos lados."
        )
    if _competencia_fechada(cur, lanc["id_academia"], lanc["data_competencia"]):
        raise PeriodoFechado(lanc["data_competencia"].month, lanc["data_competencia"].year)

    cur.execute("SELECT id, id_academia, nome FROM fin_contas WHERE id = %s", (id_conta_nova,))
    destino = cur.fetchone()
    if not destino or int(destino["id_academia"]) != int(lanc["id_academia"]):
        raise ErroFinanceiro("A conta escolhida não é desta academia.")

    # No modo total, a conta que passa a receber a saída precisa suportá-la.
    if lanc["sentido"] == "saida":
        conferir_saldo(cur, lanc["id_academia"], id_conta_nova, lanc["valor"])
    else:
        saldo_conta(cur, id_conta_nova, para_atualizar=True)

    cur.execute("SELECT nome FROM fin_contas WHERE id = %s", (lanc["id_conta"],))
    linha = cur.fetchone()
    anterior = (linha or {}).get("nome") or lanc["id_conta"]

    cur.execute(
        "UPDATE fin_lancamentos SET id_conta = %s, atualizado_por = %s WHERE id = %s",
        (id_conta_nova, usuario_id or getattr(current_user, "id", None), lanc_id),
    )
    auditar(cur, lanc["id_academia"], "fin_lancamentos", lanc_id, "reatribuir_conta",
            valor_anterior=lanc["valor"], valor_novo=lanc["valor"],
            status_anterior=str(anterior), status_novo=destino["nome"],
            motivo=motivo, usuario_id=usuario_id)
    return lanc_id
