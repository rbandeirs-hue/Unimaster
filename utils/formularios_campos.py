# -*- coding: utf-8 -*-
"""
Campos padrão baseados no cadastro do aluno.
Usado para definir quais campos um formulário pode incluir.
"""
from collections import OrderedDict

# (chave, label, grupo)
CAMPOS_ALUNO_PADRAO = OrderedDict([
    # Dados do Atleta
    ("nome", ("Nome completo", "Dados do Atleta")),
    ("sexo", ("Sexo", "Dados do Atleta")),
    # Vínculos
    ("id_academia", ("Academia", "Vínculos")),
    # Filiação
    ("nome_pai", ("Nome do Pai", "Filiação")),
    ("nome_mae", ("Nome da Mãe", "Filiação")),
    # Responsável / Parentesco
    ("responsavel_grau_parentesco", ("Grau de Parentesco", "Responsável")),
    ("responsavel_nome", ("Responsável (menor)", "Responsável")),
    ("responsavel_parentesco", ("Tipo de parentesco", "Responsável")),
    # Registro Esportivo
    ("graduacao_id", ("Faixa / Grau", "Registro Esportivo")),
    ("peso", ("Peso (kg)", "Registro Esportivo")),
    ("categoria", ("Categoria", "Registro Esportivo")),
    ("zempo", ("Registro Zempo nº", "Registro Esportivo")),
    ("data_cadastro_zempo", ("Data de Cadastro Zempo", "Registro Esportivo")),
    # Identificação
    ("data_nascimento", ("Data de nascimento", "Identificação")),
    ("ultimo_exame_faixa", ("Data da Última Graduação", "Identificação")),
    ("nacionalidade", ("Nacionalidade", "Identificação")),
    ("cpf", ("CPF", "Identificação")),
    ("rg", ("RG", "Identificação")),
    ("orgao_emissor", ("Órgão Emissor / UF", "Identificação")),
    ("rg_data_emissao", ("Data de Emissão RG", "Identificação")),
    # Endereço
    ("cep", ("CEP", "Endereço")),
    ("endereco", ("Rua / Logradouro", "Endereço")),
    ("numero", ("Nº", "Endereço")),
    ("bairro", ("Bairro", "Endereço")),
    ("cidade", ("Cidade", "Endereço")),
    ("estado", ("Estado/UF", "Endereço")),
    ("complemento", ("Complemento", "Endereço")),
    # Contato
    ("email", ("E-mail", "Contato")),
    ("telefone_celular", ("Telefone Celular", "Contato")),
    ("telefone_residencial", ("Telefone Residencial", "Contato")),
    ("telefone_comercial", ("Telefone Comercial", "Contato")),
    ("telefone_outro", ("Outro Telefone", "Contato")),
    # Turma e Modalidades
    ("TurmaID", ("Turma", "Turma e Modalidades")),
    ("professor_id", ("Professor", "Turma e Modalidades")),
    ("aluno_modalidade_ids", ("Modalidades", "Turma e Modalidades")),
    # Responsável Financeiro
    ("responsavel_financeiro_nome", ("Nome do Responsável Financeiro", "Responsável Financeiro")),
    ("responsavel_financeiro_cpf", ("CPF do Responsável Financeiro", "Responsável Financeiro")),
    # Outros
    ("observacoes", ("Observações", "Outros")),
    ("foto", ("Foto", "Outros")),
])


def listar_campos_por_grupo():
    """Retorna dict grupo -> [(chave, label), ...]"""
    grupos = {}
    for chave, (label, grupo) in CAMPOS_ALUNO_PADRAO.items():
        grupos.setdefault(grupo, []).append((chave, label))
    return grupos


def get_label(chave):
    """Retorna o label de um campo."""
    v = CAMPOS_ALUNO_PADRAO.get(chave)
    return v[0] if v else chave
