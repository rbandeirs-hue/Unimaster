"""Campos obrigatórios do cadastro interno do aluno, escolhidos por academia.

O cadastro e a edição do aluno pela secretaria tinham a lista de obrigatórios
fixa no código — `required` no HTML e uma tupla em blueprints/aluno/alunos.py.
Cada academia trabalha de um jeito (uma não pesa ninguém, outra não pede o nome
do pai, outra exige RG para filiar na federação), então a escolha passa a ser
dela, na tela de Configurações, e fica gravada em `academia_campos_obrigatorios`
(migrations/executar_cad_01_obrigatorios_academia.py).

Sem linha gravada vale o `padrao` do catálogo abaixo, que reproduz o que o
sistema exigia antes desta mudança: nenhuma academia muda de comportamento até
alguém salvar a configuração.

SEMPRE OBRIGATÓRIOS (não aparecem na tela, não dá para desligar)
  nome                  coluna NOT NULL em `alunos`, e é como o aluno aparece em
                        toda lista, chamada, cobrança e mensagem.
  data_nascimento       metade da chave única `unq_nome_nascimento (nome,
                        data_nascimento)`: sem ela o MySQL aceita o mesmo aluno
                        duas vezes (NULL não colide), e é a única trava contra
                        duplicado quando não há CPF. A idade sai dela — menor de
                        idade, faixa etária do exame de faixa e categoria de
                        competição dependem disso.
  id_academia           define de quem é o aluno: escopo de todas as telas, e é
                        da academia que vem esta própria configuração.
  aluno_modalidade_ids  aluno sem modalidade some das listas da associação e da
                        federação (o filtro delas é por `aluno_modalidades`) e
                        fica sem graduação possível, porque a faixa é filtrada
                        pela modalidade.

CADASTRO x EDIÇÃO
  No cadastro novo vale a lista inteira da academia. Na edição o sistema não
  trava ficha antiga por campo que nunca foi preenchido — a tela só avisa, para
  que corrigir um telefone não dependa de completar a ficha toda. O que a edição
  exige é: (1) não APAGAR um campo obrigatório que já tinha valor; (2) os campos
  que a edição já exigia antes desta mudança (EXIGIDOS_NA_EDICAO: nome,
  nascimento e telefone do responsável financeiro), enquanto a academia os
  mantiver obrigatórios.

FAIXA BRANCA
  `ultimo_exame_faixa` nunca é exigido quando a faixa escolhida é a branca —
  branca não tem data de graduação (utils/faixa_branca.py).
"""

from config import get_db_connection

TABELA = "academia_campos_obrigatorios"

# (chave do formulário, rótulo, grupo, padrão de hoje)
# O padrão é o que o cadastro exigia antes desta configuração existir.
CATALOGO = (
    ("sexo", "Sexo", "Dados pessoais", True),
    ("nacionalidade", "Nacionalidade", "Dados pessoais", True),
    ("peso", "Peso", "Dados pessoais", True),
    ("cpf", "CPF", "Documentos", True),
    ("rg", "RG", "Documentos", False),
    ("orgao_emissor", "Órgão emissor do RG", "Documentos", False),
    ("rg_data_emissao", "Data de emissão do RG", "Documentos", False),
    ("nome_pai", "Nome do pai", "Filiação", True),
    ("nome_mae", "Nome da mãe", "Filiação", True),
    ("email", "E-mail", "Contato", True),
    ("telefone_celular", "Telefone celular", "Contato", True),
    ("cep", "CEP", "Endereço", True),
    ("endereco", "Rua / logradouro", "Endereço", True),
    ("numero", "Número", "Endereço", True),
    ("complemento", "Complemento", "Endereço", False),
    ("bairro", "Bairro", "Endereço", True),
    ("cidade", "Cidade", "Endereço", True),
    ("estado", "Estado", "Endereço", True),
    ("TurmaID", "Turma", "Turma e graduação", True),
    ("graduacao_id", "Faixa / graduação", "Turma e graduação", True),
    ("ultimo_exame_faixa", "Data da última graduação", "Turma e graduação", False),
    ("responsavel_financeiro_nome", "Nome do responsável financeiro", "Responsável financeiro", True),
    ("responsavel_financeiro_cpf", "CPF do responsável financeiro", "Responsável financeiro", True),
    ("responsavel_financeiro_telefone", "Telefone do responsável financeiro", "Responsável financeiro", True),
)

SEMPRE_OBRIGATORIOS = (
    ("nome", "Nome completo"),
    ("data_nascimento", "Data de nascimento"),
    ("id_academia", "Academia"),
    ("aluno_modalidade_ids", "Modalidade"),
)

CHAVES_CONFIGURAVEIS = tuple(c[0] for c in CATALOGO)
ROTULOS = dict([(c[0], c[1]) for c in CATALOGO] + list(SEMPRE_OBRIGATORIOS))
PADRAO = frozenset(c[0] for c in CATALOGO if c[3])

# O que a tela de edição já exigia de fato antes: nome e nascimento (HTML
# `required`) e o telefone do responsável financeiro (checado no servidor — é o
# número da cobrança online e do lembrete de WhatsApp). Fica exigido na edição
# mesmo em ficha antiga sem o dado, enquanto a academia mantiver o campo
# obrigatório. O e-mail tinha `required` no HTML, mas a ficha sem e-mail
# chegava com o texto "None" no campo e passava — então não entra aqui, para a
# edição de quem não tem e-mail continuar funcionando.
EXIGIDOS_NA_EDICAO = frozenset({"nome", "data_nascimento", "responsavel_financeiro_telefone"})

# Campos cujo nome no formulário difere do registro do aluno carregado na edição.
_CHAVES_DO_ALUNO = {
    "endereco": ("endereco", "rua"),
    "telefone_celular": ("tel_celular", "telefone"),
    "TurmaID": ("turmas_ids", "TurmaID"),
    "aluno_modalidade_ids": ("modalidades_ids",),
}


def catalogo_por_grupo():
    """[(grupo, [{chave, rotulo, padrao}, ...]), ...] na ordem do catálogo."""
    grupos = []
    for chave, rotulo, grupo, padrao in CATALOGO:
        if not grupos or grupos[-1][0] != grupo:
            grupos.append((grupo, []))
        grupos[-1][1].append({"chave": chave, "rotulo": rotulo, "padrao": padrao})
    return grupos


def configuracao(academia_id):
    """{chave: True/False} do que a academia gravou (só o que tem linha)."""
    if not academia_id:
        return {}
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(f"SELECT campo, obrigatorio FROM {TABELA} WHERE academia_id = %s",
                    (int(academia_id),))
        return {r["campo"]: bool(r["obrigatorio"]) for r in cur.fetchall()
                if r["campo"] in CHAVES_CONFIGURAVEIS}
    except Exception:
        # Tabela ausente (migração não aplicada) ou banco fora: vale o padrão,
        # que é o comportamento de antes.
        return {}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def obrigatorios(academia_id):
    """Conjunto de chaves de formulário obrigatórias no cadastro desta academia.

    Inclui os SEMPRE_OBRIGATORIOS. Sem academia (ou sem configuração), devolve
    o padrão — o mesmo conjunto que o sistema exigia antes.
    """
    conf = configuracao(academia_id)
    ativos = {c for c in CHAVES_CONFIGURAVEIS if conf.get(c, c in PADRAO)}
    return ativos | {c for c, _r in SEMPRE_OBRIGATORIOS}


def _vazio(valor):
    """Vazio como o servidor grava: "", só espaços, "None"/"null" viram NULL.

    O "None" aparece porque partes do formulário de edição imprimem a coluna
    nula crua no `value` — o `_clean_str` de alunos.py já trata isso como vazio.
    """
    if valor is None:
        return True
    if isinstance(valor, (list, tuple, set)):
        return all(_vazio(v) for v in valor)
    s = str(valor).strip()
    return not s or s.lower() in ("none", "null", "undefined")


def _valor_no_form(form, chave):
    if chave == "aluno_modalidade_ids":
        return form.getlist("aluno_modalidade_ids")
    if chave == "TurmaID":
        # Cadastro manda um select `TurmaID`; edição manda a lista `turmas_ids`.
        return [form.get("TurmaID")] + list(form.getlist("turmas_ids"))
    return form.get(chave)


def _valor_anterior(aluno, chave):
    for k in _CHAVES_DO_ALUNO.get(chave, (chave,)):
        v = aluno.get(k) if isinstance(aluno, dict) else getattr(aluno, k, None)
        if not _vazio(v):
            return v
    return None


def exigidos(academia_id, anterior=None, faixa_branca=False, obrig=None):
    """Chaves que o formulário PRECISA trazer preenchidas.

    `anterior` é o aluno como está no banco (edição); None = cadastro novo.
    `faixa_branca` dispensa a data da última graduação.
    `obrig` permite reaproveitar um `obrigatorios()` já consultado.
    """
    obrig = set(obrig if obrig is not None else obrigatorios(academia_id))
    if faixa_branca:
        obrig.discard("ultimo_exame_faixa")
    if anterior is None:
        return obrig
    return {c for c in obrig
            if c in EXIGIDOS_NA_EDICAO or not _vazio(_valor_anterior(anterior, c))}


def validar(form, academia_id, anterior=None, faixa_branca=False, obrig=None):
    """Rótulos dos campos obrigatórios que vieram vazios (lista vazia = ok).

    É a checagem do servidor — o `required` do HTML é contornável. Na edição,
    passe o aluno atual em `anterior` (ver docstring do módulo).
    """
    faltando = []
    exig = exigidos(academia_id, anterior, faixa_branca, obrig)
    ordem = [c for c, _r in SEMPRE_OBRIGATORIOS] + list(CHAVES_CONFIGURAVEIS)
    for chave in ordem:
        if chave in exig and _vazio(_valor_no_form(form, chave)):
            # Na edição a academia não vem no formulário: é a do aluno.
            if chave == "id_academia" and anterior is not None:
                continue
            faltando.append(ROTULOS.get(chave, chave))
    return faltando


def salvar(academia_id, marcados, usuario_id=None):
    """Grava a escolha da academia: uma linha por campo configurável.

    Grava TODOS os campos do catálogo (marcados = 1, os demais = 0), e não só a
    diferença do padrão: o que a academia salvou na tela é a escolha dela, e
    não deve mudar sozinho se o padrão do código mudar um dia.
    """
    marcados = set(marcados or [])
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        for chave in CHAVES_CONFIGURAVEIS:
            cur.execute(
                f"""INSERT INTO {TABELA} (academia_id, campo, obrigatorio, atualizado_por)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE obrigatorio = VALUES(obrigatorio),
                                            atualizado_por = VALUES(atualizado_por)""",
                (int(academia_id), chave, 1 if chave in marcados else 0, usuario_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
