# -*- coding: utf-8 -*-
"""Regras do estoque: saldo, movimentação, transferência, estorno e inventário.

Onde ficam as regras
--------------------
Aqui, não na rota e não no template. A rota traduz o formulário, checa a
permissão e chama uma função daqui; quem decide se a operação pode acontecer é
este módulo. Isso é o que permite testar a regra sem HTTP — e é o que impede
que uma segunda tela, amanhã, mexa no saldo por um caminho que não valida nada.

As duas fontes de verdade
-------------------------
`estoque_movimento` é o histórico, imutável. `estoque_saldo` é a quantidade
atual. Guardar as duas é redundância deliberada: somar o histórico a cada
consulta não escala e, principalmente, não dá onde travar.

Concorrência
------------
Toda mudança de saldo abre transação, faz `SELECT ... FOR UPDATE` na linha de
saldo e só então grava. Sem a trava, duas saídas simultâneas do mesmo item
leriam o mesmo saldo e as duas passariam — o estoque furaria em exatamente uma
unidade, sem nada no log explicando. É o mesmo padrão de
`utils/financeiro_core.py` para o saldo das contas.

Saída acima do saldo
--------------------
Bloqueada por padrão. Passa em dois casos, os dois explícitos: a academia
ligou `estoque_permite_negativo`, ou quem tem a permissão `estoque_ajustar`
autorizou aquela saída específica. Nunca em silêncio.
"""
from decimal import Decimal

from config import get_db_connection
from utils.financeiro_core import auditar

# ---------------------------------------------------------------- motivos
MOTIVOS_ENTRADA = {
    "compra": "Compra",
    "doacao": "Doação",
    "devolucao_saida": "Devolução de saída",
    "ajuste_positivo": "Ajuste positivo",
    "transferencia_entrada": "Transferência recebida",
    "estorno": "Estorno",
    "inventario": "Ajuste de inventário",
}

MOTIVOS_SAIDA = {
    "venda": "Venda",
    "entrega_aluno": "Entrega ao aluno",
    "uso_interno": "Uso interno",
    "perda": "Perda",
    "avaria": "Avaria",
    "ajuste_negativo": "Ajuste negativo",
    "devolucao_fornecedor": "Devolução ao fornecedor",
    "transferencia_saida": "Transferência enviada",
    "estorno": "Estorno",
    "inventario": "Ajuste de inventário",
}

# Motivos que o serviço gera sozinho; a tela não os oferece.
MOTIVOS_INTERNOS = {"transferencia_entrada", "transferencia_saida",
                    "estorno", "inventario"}


class EstoqueErro(Exception):
    """Operação recusada por regra de negócio. A rota vira isto em mensagem."""


# ------------------------------------------------------------------- dono
# Todo registro do estoque pertence a EXATAMENTE um dos três. A regra é
# validada aqui, em Python, e não por CHECK no banco: o CHECK recusaria com
# uma mensagem que não diz nada a quem está usando a tela.
DONOS = ("id_academia", "id_associacao", "id_organizacao")


def normalizar_dono(id_academia=None, id_associacao=None, id_organizacao=None):
    """Devolve o dicionário do dono, garantindo que só um veio preenchido."""
    valores = {"id_academia": id_academia or None,
               "id_associacao": id_associacao or None,
               "id_organizacao": id_organizacao or None}
    preenchidos = [k for k, v in valores.items() if v]
    if len(preenchidos) != 1:
        raise EstoqueErro(
            "Informe exatamente um dono: academia, associação ou organização.")
    return valores


def filtro_dono(alias="p", id_academia=None, id_associacao=None, id_organizacao=None):
    """(trecho SQL, params) para recortar por dono numa consulta.

    Sem dono nenhum devolve uma condição falsa, de propósito: consulta sem
    recorte no estoque é vazamento entre clientes, não "ver tudo".
    """
    for coluna, valor in (("id_academia", id_academia),
                          ("id_associacao", id_associacao),
                          ("id_organizacao", id_organizacao)):
        if valor:
            return f" AND {alias}.{coluna} = %s", (valor,)
    return " AND 1 = 0", ()


# ------------------------------------------------------------------ apoio
def _conn():
    return get_db_connection()


def _int_positivo(valor, campo="quantidade"):
    try:
        n = int(valor)
    except (TypeError, ValueError):
        raise EstoqueErro(f"{campo.capitalize()} inválida.")
    if n <= 0:
        raise EstoqueErro(f"{campo.capitalize()} precisa ser maior que zero.")
    return n


def _variacao(cur, variacao_id):
    """Variação com o dono do produto, para validar escopo e custo."""
    cur.execute(
        """SELECT v.id, v.produto_id, v.nome, v.custo AS custo_var, v.ativo,
                  p.nome AS produto, p.custo AS custo_prod,
                  p.id_academia, p.id_associacao, p.id_organizacao,
                  p.ativo AS produto_ativo
           FROM estoque_variacao v
           JOIN estoque_produto p ON p.id = v.produto_id
           WHERE v.id = %s""", (variacao_id,))
    v = cur.fetchone()
    if not v:
        raise EstoqueErro("Produto ou variação não encontrada.")
    return v


def _local(cur, local_id):
    cur.execute("SELECT id, id_academia, id_associacao, id_organizacao, nome, ativo "
                "FROM estoque_local WHERE id = %s", (local_id,))
    l = cur.fetchone()
    if not l:
        raise EstoqueErro("Local de estoque não encontrado.")
    return l


def _mesmo_dono(a, b):
    """Produto e local têm de pertencer à mesma academia ou associação.

    É a trava de isolamento no ponto mais baixo possível: mesmo que uma rota
    esqueça de validar o escopo, não dá para mover o produto de uma academia
    para o depósito de outra.
    """
    return all(a.get(c) == b.get(c) for c in DONOS)


def _saldo_travado(cur, local_id, variacao_id):
    """Saldo atual com a linha travada até o commit. Cria a linha se faltar."""
    cur.execute(
        "SELECT quantidade FROM estoque_saldo "
        "WHERE local_id = %s AND variacao_id = %s FOR UPDATE",
        (local_id, variacao_id))
    linha = cur.fetchone()
    if linha is not None:
        return int(linha["quantidade"] if isinstance(linha, dict) else linha[0])
    # INSERT IGNORE + releitura travada: se outra transação criou a linha no
    # meio do caminho, a releitura pega a dela em vez de estourar.
    cur.execute(
        "INSERT IGNORE INTO estoque_saldo (local_id, variacao_id, quantidade) "
        "VALUES (%s, %s, 0)", (local_id, variacao_id))
    cur.execute(
        "SELECT quantidade FROM estoque_saldo "
        "WHERE local_id = %s AND variacao_id = %s FOR UPDATE",
        (local_id, variacao_id))
    linha = cur.fetchone()
    return int(linha["quantidade"] if isinstance(linha, dict) else linha[0]) if linha else 0


def _permite_negativo(cur, dono):
    """A chave fica na academia ou na organização; a associação não tem."""
    try:
        if dono.get("id_academia"):
            cur.execute("SELECT COALESCE(estoque_permite_negativo, 0) AS v "
                        "FROM academias WHERE id = %s", (dono["id_academia"],))
        elif dono.get("id_organizacao"):
            cur.execute("SELECT COALESCE(permite_negativo, 0) AS v "
                        "FROM estoque_organizacao WHERE id = %s", (dono["id_organizacao"],))
        else:
            return False
        r = cur.fetchone()
        return bool(r["v"]) if r else False
    except Exception:
        return False


# ------------------------------------------------------------ movimentação
def movimentar(*, variacao_id, local_id, sentido, motivo, quantidade,
               usuario_id=None, custo_unitario=None, preco_unitario=None,
               tabela_preco_id=None, aluno_id=None, observacao=None,
               origem=None, origem_id=None, movimento_par_id=None,
               estorna_movimento_id=None, autorizar_negativo=False,
               conn=None, cur=None):
    """Grava UM movimento e ajusta o saldo, atomicamente.

    Com `conn`/`cur`, entra na transação de quem chamou — é assim que a
    transferência grava os dois lados sem deixar meio caminho gravado.
    Devolve o id do movimento.
    """
    quantidade = _int_positivo(quantidade)
    if sentido not in ("E", "S"):
        raise EstoqueErro("Sentido inválido.")
    validos = MOTIVOS_ENTRADA if sentido == "E" else MOTIVOS_SAIDA
    if motivo not in validos:
        raise EstoqueErro("Motivo inválido para este sentido.")

    externo = cur is not None
    if not externo:
        conn = _conn()
        cur = conn.cursor(dictionary=True)
    try:
        v = _variacao(cur, variacao_id)
        l = _local(cur, local_id)
        if not _mesmo_dono(v, l):
            raise EstoqueErro("O local de estoque não pertence ao dono do produto.")

        saldo = _saldo_travado(cur, local_id, variacao_id)
        if sentido == "S":
            novo = saldo - quantidade
            if novo < 0 and not autorizar_negativo and not _permite_negativo(cur, v):
                raise EstoqueErro(
                    f"Saldo insuficiente: há {saldo} em {l['nome']} e a saída é de "
                    f"{quantidade}.")
        else:
            novo = saldo + quantidade

        if custo_unitario is None:
            custo_unitario = v["custo_var"] if v["custo_var"] is not None else v["custo_prod"]

        cur.execute(
            """INSERT INTO estoque_movimento
               (id_academia, id_associacao, id_organizacao, local_id, variacao_id,
                sentido, motivo, quantidade, saldo_depois, custo_unitario,
                preco_unitario, tabela_preco_id, aluno_id, usuario_id, observacao,
                origem, origem_id, movimento_par_id, estorna_movimento_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (v["id_academia"], v["id_associacao"], v["id_organizacao"],
             local_id, variacao_id, sentido,
             motivo, quantidade, novo, custo_unitario, preco_unitario,
             tabela_preco_id, aluno_id, usuario_id, observacao, origem, origem_id,
             movimento_par_id, estorna_movimento_id))
        mov_id = cur.lastrowid

        cur.execute(
            "UPDATE estoque_saldo SET quantidade = %s "
            "WHERE local_id = %s AND variacao_id = %s",
            (novo, local_id, variacao_id))

        # A auditoria do sistema é por academia; no estoque independente não há
        # academia, e a linha vai com id_academia nulo — o detalhe identifica.
        auditar(cur, v["id_academia"], "estoque_movimento", mov_id,
                f"{'entrada' if sentido == 'E' else 'saida'}:{motivo}",
                valor_anterior=Decimal(saldo), valor_novo=Decimal(novo),
                motivo=observacao,
                detalhes=f"{v['produto']} / {v['nome']} em {l['nome']}: "
                         f"{'+' if sentido == 'E' else '-'}{quantidade}",
                usuario_id=usuario_id)

        if not externo:
            conn.commit()
        return mov_id
    except Exception:
        if not externo:
            conn.rollback()
        raise
    finally:
        if not externo:
            cur.close()
            conn.close()


def entrada(**kw):
    """Açúcar para `movimentar` com sentido de entrada."""
    kw.setdefault("motivo", "compra")
    return movimentar(sentido="E", **kw)


def saida(**kw):
    """Açúcar para `movimentar` com sentido de saída."""
    kw.setdefault("motivo", "venda")
    return movimentar(sentido="S", **kw)


def transferir(*, variacao_id, origem_local_id, destino_local_id, quantidade,
               usuario_id=None, observacao=None, autorizar_negativo=False):
    """Move quantidade entre dois locais, numa transação só.

    Grava dois movimentos ligados por `movimento_par_id`. É por aqui que a
    associação abastece a academia para revenda: nada aparece nem some do nada,
    e os dois lados são visíveis no histórico de cada um.
    """
    quantidade = _int_positivo(quantidade)
    if int(origem_local_id) == int(destino_local_id):
        raise EstoqueErro("Origem e destino são o mesmo local.")

    conn = _conn()
    cur = conn.cursor(dictionary=True)
    try:
        # Sempre na mesma ordem de id: duas transferências cruzadas travando
        # em ordens opostas produziriam deadlock.
        for lid in sorted((int(origem_local_id), int(destino_local_id))):
            _saldo_travado(cur, lid, variacao_id)

        saida_id = movimentar(
            variacao_id=variacao_id, local_id=origem_local_id, sentido="S",
            motivo="transferencia_saida", quantidade=quantidade,
            usuario_id=usuario_id, observacao=observacao,
            autorizar_negativo=autorizar_negativo, conn=conn, cur=cur)

        entrada_id = movimentar(
            variacao_id=variacao_id, local_id=destino_local_id, sentido="E",
            motivo="transferencia_entrada", quantidade=quantidade,
            usuario_id=usuario_id, observacao=observacao,
            movimento_par_id=saida_id, conn=conn, cur=cur)

        cur.execute("UPDATE estoque_movimento SET movimento_par_id = %s WHERE id = %s",
                    (entrada_id, saida_id))
        conn.commit()
        return saida_id, entrada_id
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def estornar(movimento_id, usuario_id=None, motivo_texto=None):
    """Anula um movimento com outro em sentido contrário.

    Movimento confirmado nunca é apagado nem editado: o estorno é a única
    correção, e fica visível no histórico ao lado do original.
    """
    conn = _conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM estoque_movimento WHERE id = %s FOR UPDATE",
                    (movimento_id,))
        orig = cur.fetchone()
        if not orig:
            raise EstoqueErro("Movimento não encontrado.")
        if orig["estorna_movimento_id"]:
            raise EstoqueErro("Um estorno não pode ser estornado. Lance o oposto.")
        cur.execute("SELECT id FROM estoque_movimento WHERE estorna_movimento_id = %s",
                    (movimento_id,))
        if cur.fetchone():
            raise EstoqueErro("Este movimento já foi estornado.")

        novo_id = movimentar(
            variacao_id=orig["variacao_id"], local_id=orig["local_id"],
            sentido="E" if orig["sentido"] == "S" else "S",
            motivo="estorno", quantidade=orig["quantidade"],
            usuario_id=usuario_id,
            custo_unitario=orig["custo_unitario"],
            observacao=motivo_texto or f"Estorno do movimento {movimento_id}",
            estorna_movimento_id=movimento_id,
            # O estorno de uma entrada pode deixar o saldo negativo se a
            # mercadoria já saiu. Barrar aqui prenderia o erro no sistema.
            autorizar_negativo=True,
            conn=conn, cur=cur)
        conn.commit()
        return novo_id
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


# ----------------------------------------------------------------- leitura
def saldo_de(variacao_id, local_id=None):
    """Quantidade de uma variação: num local, ou somada em todos."""
    conn = _conn()
    cur = conn.cursor()
    try:
        if local_id:
            cur.execute("SELECT quantidade FROM estoque_saldo "
                        "WHERE local_id = %s AND variacao_id = %s",
                        (local_id, variacao_id))
        else:
            cur.execute("SELECT COALESCE(SUM(quantidade), 0) FROM estoque_saldo "
                        "WHERE variacao_id = %s", (variacao_id,))
        r = cur.fetchone()
        return int(r[0]) if r and r[0] is not None else 0
    finally:
        cur.close()
        conn.close()


def conferir_saldos(academia_id=None):
    """Recalcula o saldo pelo histórico e devolve as divergências.

    Existe porque `estoque_saldo` é uma redundância: se ela puder divergir do
    histórico, quero descobrir por teste, não por reclamação de cliente.
    """
    conn = _conn()
    cur = conn.cursor(dictionary=True)
    try:
        filtro, params = "", ()
        if academia_id:
            filtro = " AND m.id_academia = %s"
            params = (academia_id,)
        cur.execute(f"""
            SELECT s.local_id, s.variacao_id, s.quantidade AS saldo,
                   COALESCE(SUM(CASE WHEN m.sentido = 'E' THEN m.quantidade
                                     ELSE -m.quantidade END), 0) AS historico
            FROM estoque_saldo s
            LEFT JOIN estoque_movimento m
              ON m.local_id = s.local_id AND m.variacao_id = s.variacao_id
            WHERE 1=1 {filtro}
            GROUP BY s.local_id, s.variacao_id, s.quantidade
            HAVING saldo <> historico
        """, params)
        return cur.fetchall() or []
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------- catálogo
def criar_produto(*, nome, id_academia=None, id_associacao=None, id_organizacao=None,
                  categoria_id=None, sku=None, descricao=None, unidade="un", custo=0,
                  estoque_min=0, estoque_max=None, variacoes=None,
                  usuario_id=None):
    """Cria o produto e SEMPRE ao menos uma variação.

    Produto sem variação recebe uma chamada "Único". Isso evita o caminho
    duplo — produto com variação e produto sem — que é onde nascem as
    divergências: saldo e movimento apontam sempre para uma variação real, com
    chave estrangeira de verdade, sem id mágico.
    """
    nome = (nome or "").strip()
    if not nome:
        raise EstoqueErro("O produto precisa de um nome.")
    dono = normalizar_dono(id_academia, id_associacao, id_organizacao)

    conn = _conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """INSERT INTO estoque_produto
               (id_academia, id_associacao, id_organizacao, categoria_id, nome,
                sku, descricao, unidade, custo, estoque_min, estoque_max)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (dono["id_academia"], dono["id_associacao"], dono["id_organizacao"],
             categoria_id, nome, (sku or None),
             descricao, unidade, custo or 0, estoque_min or 0, estoque_max))
        produto_id = cur.lastrowid

        linhas = variacoes or [{"nome": "Único"}]
        for v in linhas:
            cur.execute(
                """INSERT INTO estoque_variacao
                   (produto_id, nome, sku, modalidade_id, graduacao_id,
                    tamanho, cor, custo)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (produto_id, (v.get("nome") or "Único").strip(), v.get("sku") or None,
                 v.get("modalidade_id"), v.get("graduacao_id"),
                 v.get("tamanho"), v.get("cor"), v.get("custo")))

        auditar(cur, dono["id_academia"], "estoque_produto", produto_id, "criar",
                detalhes=f"{nome} ({len(linhas)} variação(ões))", usuario_id=usuario_id)
        conn.commit()
        return produto_id
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def preco_de(variacao_id, tabela_id=None, id_academia=None, id_associacao=None,
             id_organizacao=None):
    """Preço de uma variação na tabela pedida, ou na tabela padrão do dono.

    Devolve None quando não há preço: item sem preço naquela tabela não é
    vendido por ela, e inventar um preço seria pior do que recusar a venda.
    """
    conn = _conn()
    cur = conn.cursor(dictionary=True)
    try:
        if tabela_id:
            cur.execute("SELECT preco FROM estoque_preco "
                        "WHERE tabela_id = %s AND variacao_id = %s",
                        (tabela_id, variacao_id))
            r = cur.fetchone()
            return r["preco"] if r else None

        trecho, par = filtro_dono("t", id_academia, id_associacao, id_organizacao)
        cur.execute(
            f"""SELECT p.preco FROM estoque_preco p
                JOIN estoque_tabela_preco t ON t.id = p.tabela_id
                WHERE p.variacao_id = %s AND t.ativo = 1 AND t.padrao = 1 {trecho}
                LIMIT 1""", (variacao_id,) + par)
        r = cur.fetchone()
        return r["preco"] if r else None
    finally:
        cur.close()
        conn.close()


def tabelas_de_preco(id_academia=None, id_associacao=None, id_organizacao=None,
                     perfil=None):
    conn = _conn()
    cur = conn.cursor(dictionary=True)
    try:
        trecho, par = filtro_dono("t", id_academia, id_associacao, id_organizacao)
        extra, par_extra = "", ()
        if perfil:
            extra, par_extra = " AND t.perfil = %s", (perfil,)
        cur.execute(
            f"""SELECT t.id, t.nome, t.perfil, t.padrao FROM estoque_tabela_preco t
                WHERE t.ativo = 1 {trecho} {extra}
                ORDER BY t.padrao DESC, t.nome""", par + par_extra)
        return cur.fetchall() or []
    finally:
        cur.close()
        conn.close()


# --------------------------------------------------------------- panorama
def panorama(id_academia=None, id_associacao=None, id_organizacao=None, dias=30):
    """Os números do painel, numa consulta por indicador.

    Só conta produto ativo: item desativado continua no histórico, mas não é
    "produto em estoque" para efeito de alerta — senão o gestor persegue um
    aviso sobre algo que ele mesmo tirou de linha.
    """
    conn = _conn()
    cur = conn.cursor(dictionary=True)
    dono, par = filtro_dono("p", id_academia, id_associacao, id_organizacao)
    try:
        dados = {}
        cur.execute(f"""SELECT COUNT(*) AS n FROM estoque_produto p
                        WHERE p.ativo = 1 {dono}""", par)
        dados["produtos"] = cur.fetchone()["n"]

        cur.execute(f"""SELECT COALESCE(SUM(s.quantidade), 0) AS n,
                               COALESCE(SUM(s.quantidade *
                                   COALESCE(v.custo, p.custo)), 0) AS valor
                        FROM estoque_saldo s
                        JOIN estoque_variacao v ON v.id = s.variacao_id
                        JOIN estoque_produto p ON p.id = v.produto_id
                        WHERE p.ativo = 1 {dono}""", par)
        r = cur.fetchone()
        dados["itens"] = int(r["n"] or 0)
        dados["valor"] = r["valor"] or 0

        # O alerta é POR VARIAÇÃO, não por produto. Ter sete kimonos não serve
        # de nada quando os sete são A2 e o aluno veste A3: somando o produto
        # inteiro, o A3 esgotado ficaria invisível justamente para quem precisa
        # comprar. O mínimo cadastrado no produto vale para cada variação dele.
        cur.execute(f"""
            SELECT v.id AS variacao_id, v.nome AS variacao,
                   p.id AS produto_id, p.nome AS produto, p.estoque_min,
                   COALESCE(SUM(s.quantidade), 0) AS saldo
            FROM estoque_produto p
            JOIN estoque_variacao v ON v.produto_id = p.id AND v.ativo = 1
            LEFT JOIN estoque_saldo s ON s.variacao_id = v.id
            WHERE p.ativo = 1 {dono}
            GROUP BY v.id, v.nome, p.id, p.nome, p.estoque_min
            ORDER BY saldo, p.nome, v.nome""", par)
        linhas = cur.fetchall() or []
        dados["sem_estoque"] = [x for x in linhas if int(x["saldo"]) <= 0]
        dados["estoque_baixo"] = [x for x in linhas
                                  if 0 < int(x["saldo"]) <= int(x["estoque_min"] or 0)]

        cur.execute(f"""
            SELECT m.sentido, COALESCE(SUM(m.quantidade), 0) AS n
            FROM estoque_movimento m
            JOIN estoque_variacao v ON v.id = m.variacao_id
            JOIN estoque_produto p ON p.id = v.produto_id
            WHERE m.criado_em >= (NOW() - INTERVAL %s DAY) {dono}
            GROUP BY m.sentido""", (dias,) + par)
        por_sentido = {x["sentido"]: int(x["n"]) for x in cur.fetchall() or []}
        dados["entradas"] = por_sentido.get("E", 0)
        dados["saidas"] = por_sentido.get("S", 0)
        dados["dias"] = dias
        return dados
    finally:
        cur.close()
        conn.close()


def movimentos(id_academia=None, id_associacao=None, id_organizacao=None,
               limite=50, **filtros):
    """Histórico, do mais recente para o mais antigo."""
    conn = _conn()
    cur = conn.cursor(dictionary=True)
    try:
        trecho, par_dono = filtro_dono("p", id_academia, id_associacao, id_organizacao)
        onde = [trecho.replace(" AND ", "", 1)]
        par = list(par_dono)
        for campo, coluna in (("variacao_id", "m.variacao_id"),
                              ("local_id", "m.local_id"),
                              ("aluno_id", "m.aluno_id"),
                              ("sentido", "m.sentido")):
            if filtros.get(campo):
                onde.append(f"{coluna} = %s")
                par.append(filtros[campo])
        if filtros.get("desde"):
            onde.append("m.criado_em >= %s")
            par.append(filtros["desde"])
        par.append(int(limite))
        cur.execute(f"""
            SELECT m.*, p.nome AS produto, v.nome AS variacao,
                   l.nome AS local, u.nome AS usuario, a.nome AS aluno
            FROM estoque_movimento m
            JOIN estoque_variacao v ON v.id = m.variacao_id
            JOIN estoque_produto p ON p.id = v.produto_id
            JOIN estoque_local l ON l.id = m.local_id
            LEFT JOIN usuarios u ON u.id = m.usuario_id
            LEFT JOIN alunos a ON a.id = m.aluno_id
            WHERE {' AND '.join(onde)}
            ORDER BY m.criado_em DESC, m.id DESC
            LIMIT %s""", tuple(par))
        return cur.fetchall() or []
    finally:
        cur.close()
        conn.close()


# -------------------------------------------------------------- inventário
def abrir_inventario(*, local_id, usuario_id=None, observacao=None):
    """Congela o saldo do local numa lista para contar na mão.

    `qtd_sistema` é gravado agora, na abertura: é ele que responde "o que o
    sistema achava" quando a diferença aparecer. Ler esse número só na hora de
    fechar mediria outra coisa — o saldo já teria mudado com as vendas do dia.
    """
    conn = _conn()
    cur = conn.cursor(dictionary=True)
    try:
        local = _local(cur, local_id)
        cur.execute("""SELECT id FROM estoque_inventario
                       WHERE local_id = %s AND status = 'aberto'""", (local_id,))
        if cur.fetchone():
            raise EstoqueErro(
                f"Já existe um inventário aberto em {local['nome']}. "
                "Feche ou cancele antes de abrir outro.")

        cur.execute(
            """INSERT INTO estoque_inventario
               (id_academia, id_associacao, id_organizacao, local_id,
                observacao, iniciado_por)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (local["id_academia"], local["id_associacao"], local["id_organizacao"],
             local_id, observacao, usuario_id))
        inv_id = cur.lastrowid

        # Entram todas as variações ativas do dono, inclusive as de saldo zero:
        # item que sumiu do sistema mas está na prateleira só aparece assim.
        cur.execute(
            """INSERT INTO estoque_inventario_item
                   (inventario_id, variacao_id, qtd_sistema)
               SELECT %s, v.id, COALESCE(s.quantidade, 0)
               FROM estoque_variacao v
               JOIN estoque_produto p ON p.id = v.produto_id
               LEFT JOIN estoque_saldo s ON s.variacao_id = v.id AND s.local_id = %s
               WHERE v.ativo = 1 AND p.ativo = 1
                 AND ((p.id_academia IS NOT NULL AND p.id_academia = %s)
                   OR (p.id_associacao IS NOT NULL AND p.id_associacao = %s)
                   OR (p.id_organizacao IS NOT NULL AND p.id_organizacao = %s))""",
            (inv_id, local_id, local["id_academia"], local["id_associacao"],
             local["id_organizacao"]))
        itens = cur.rowcount
        if not itens:
            raise EstoqueErro("Nenhum produto cadastrado para contar.")

        auditar(cur, local["id_academia"], "estoque_inventario", inv_id, "abrir",
                usuario_id=usuario_id,
                detalhes=f"{local['nome']}: {itens} item(ns) para contar")
        conn.commit()
        return inv_id
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def contar(inventario_id, contagens, usuario_id=None):
    """Guarda o que foi contado. Pode ser chamado quantas vezes for preciso.

    `contagens` é {variacao_id: quantidade}. Valor None limpa a contagem
    daquele item — contar errado e ter que voltar atrás é rotina.
    """
    conn = _conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM estoque_inventario WHERE id = %s", (inventario_id,))
        inv = cur.fetchone()
        if not inv:
            raise EstoqueErro("Inventário não encontrado.")
        if inv["status"] != "aberto":
            raise EstoqueErro("Este inventário já foi fechado.")

        gravados = 0
        for variacao_id, valor in (contagens or {}).items():
            if valor is None or valor == "":
                cur.execute("""UPDATE estoque_inventario_item SET qtd_contada = NULL
                               WHERE inventario_id = %s AND variacao_id = %s""",
                            (inventario_id, variacao_id))
                continue
            try:
                qtd = int(valor)
            except (TypeError, ValueError):
                raise EstoqueErro("Quantidade contada inválida.")
            if qtd < 0:
                raise EstoqueErro("Quantidade contada não pode ser negativa.")
            cur.execute("""UPDATE estoque_inventario_item SET qtd_contada = %s
                           WHERE inventario_id = %s AND variacao_id = %s""",
                        (qtd, inventario_id, variacao_id))
            gravados += 1
        conn.commit()
        return gravados
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def fechar_inventario(inventario_id, usuario_id=None):
    """Transforma cada diferença num movimento de ajuste.

    O saldo NÃO é sobrescrito com a contagem. A diferença entre o que o sistema
    achava e o que existe é a informação que interessa, e sobrescrever a
    apagaria — daqui a um ano ninguém saberia por que o saldo mudou. Item não
    contado é ignorado: em branco quer dizer "não contei", não "tem zero".
    """
    conn = _conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM estoque_inventario WHERE id = %s FOR UPDATE",
                    (inventario_id,))
        inv = cur.fetchone()
        if not inv:
            raise EstoqueErro("Inventário não encontrado.")
        if inv["status"] != "aberto":
            raise EstoqueErro("Este inventário já foi fechado.")

        cur.execute("""SELECT * FROM estoque_inventario_item
                       WHERE inventario_id = %s AND qtd_contada IS NOT NULL""",
                    (inventario_id,))
        itens = cur.fetchall() or []
        if not itens:
            raise EstoqueErro("Nenhum item foi contado.")

        ajustes, sobra, falta = 0, 0, 0
        for item in itens:
            # O saldo de agora, não o da abertura: entre abrir e fechar pode
            # ter havido venda, e o ajuste precisa levar a mercadoria ao que
            # foi contado de verdade.
            atual = _saldo_travado(cur, inv["local_id"], item["variacao_id"])
            diferenca = int(item["qtd_contada"]) - atual
            if diferenca == 0:
                continue
            mov_id = movimentar(
                variacao_id=item["variacao_id"], local_id=inv["local_id"],
                sentido="E" if diferenca > 0 else "S",
                motivo="inventario", quantidade=abs(diferenca),
                usuario_id=usuario_id,
                observacao=f"Inventário {inventario_id}: contado "
                           f"{item['qtd_contada']}, sistema {atual}",
                origem="inventario", origem_id=inventario_id,
                # A contagem é a verdade. Se ela deixa o saldo negativo, é
                # sinal de erro anterior que o ajuste precisa expor, não
                # esconder atrás de uma recusa.
                autorizar_negativo=True,
                conn=conn, cur=cur)
            cur.execute("UPDATE estoque_inventario_item SET movimento_id = %s "
                        "WHERE id = %s", (mov_id, item["id"]))
            ajustes += 1
            if diferenca > 0:
                sobra += diferenca
            else:
                falta += -diferenca

        cur.execute("""UPDATE estoque_inventario SET status = 'fechado',
                              fechado_em = NOW(), fechado_por = %s WHERE id = %s""",
                    (usuario_id, inventario_id))
        auditar(cur, inv["id_academia"], "estoque_inventario", inventario_id,
                "fechar", usuario_id=usuario_id,
                detalhes=f"{ajustes} ajuste(s) · sobra {sobra} · falta {falta}")
        conn.commit()
        return {"ajustes": ajustes, "sobra": sobra, "falta": falta,
                "contados": len(itens)}
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def cancelar_inventario(inventario_id, usuario_id=None):
    """Desiste da contagem. Nada de saldo foi tocado, então não há o que desfazer."""
    conn = _conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM estoque_inventario WHERE id = %s", (inventario_id,))
        inv = cur.fetchone()
        if not inv:
            raise EstoqueErro("Inventário não encontrado.")
        if inv["status"] != "aberto":
            raise EstoqueErro("Só inventário aberto pode ser cancelado.")
        cur.execute("UPDATE estoque_inventario SET status = 'cancelado' WHERE id = %s",
                    (inventario_id,))
        auditar(cur, inv["id_academia"], "estoque_inventario", inventario_id,
                "cancelar", usuario_id=usuario_id)
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def inventario(inventario_id):
    """O inventário com seus itens, para a tela de contagem."""
    conn = _conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""SELECT i.*, l.nome AS local, u.nome AS iniciou
                       FROM estoque_inventario i
                       JOIN estoque_local l ON l.id = i.local_id
                       LEFT JOIN usuarios u ON u.id = i.iniciado_por
                       WHERE i.id = %s""", (inventario_id,))
        inv = cur.fetchone()
        if not inv:
            return None
        cur.execute("""SELECT it.*, v.nome AS variacao, p.nome AS produto, p.unidade
                       FROM estoque_inventario_item it
                       JOIN estoque_variacao v ON v.id = it.variacao_id
                       JOIN estoque_produto p ON p.id = v.produto_id
                       WHERE it.inventario_id = %s
                       ORDER BY p.nome, v.nome""", (inventario_id,))
        inv["itens"] = cur.fetchall() or []
        return inv
    finally:
        cur.close()
        conn.close()


def inventarios(id_academia=None, id_associacao=None, id_organizacao=None, limite=30):
    conn = _conn()
    cur = conn.cursor(dictionary=True)
    try:
        trecho, par = filtro_dono("i", id_academia, id_associacao, id_organizacao)
        cur.execute(f"""SELECT i.*, l.nome AS local,
                               (SELECT COUNT(*) FROM estoque_inventario_item x
                                WHERE x.inventario_id = i.id) AS itens,
                               (SELECT COUNT(*) FROM estoque_inventario_item x
                                WHERE x.inventario_id = i.id
                                  AND x.qtd_contada IS NOT NULL) AS contados
                        FROM estoque_inventario i
                        JOIN estoque_local l ON l.id = i.local_id
                        WHERE 1=1 {trecho}
                        ORDER BY i.iniciado_em DESC LIMIT %s""", par + (int(limite),))
        return cur.fetchall() or []
    finally:
        cur.close()
        conn.close()
