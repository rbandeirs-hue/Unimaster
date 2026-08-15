"""
Tradução entre o cadastro de aluno do sistema e o cadastro de pessoa do Zempo.

Três responsabilidades:
  1. `validar_aluno`  — diz quais campos obrigatórios do Zempo faltam no aluno,
     ANTES de tentar migrar (é o alerta pedido na tela de solicitação);
  2. `montar_payload` — monta o dicionário que vai no POST de cadastro/atualização,
     resolvendo no Zempo o que ele mesmo calcula (classe, categoria, cidade, bairro);
  3. `comparar`       — diff campo a campo Zempo × sistema, para a prévia do sync.

Os ids de select abaixo foram extraídos do formulário oficial (secao=pessoas_cadastro).
"""
import re
import unicodedata
from datetime import date, datetime

# ------------------------------------------------------------------ tabelas

# Mesma numeração para os selects `estado`, `rg_estado`, `cref_estado` e `naturalidade`.
UF_PARA_ID = {
    "AC": "1", "AL": "2", "AP": "3", "AM": "4", "BA": "5", "CE": "6", "DF": "7",
    "ES": "8", "GO": "9", "MA": "10", "MT": "11", "MS": "12", "MG": "13",
    "PA": "14", "PB": "15", "PR": "16", "PE": "17", "PI": "18", "RJ": "19",
    "RN": "20", "RS": "21", "RO": "22", "RR": "23", "SC": "24", "SP": "25",
    "SE": "26", "TO": "27",
}
ID_PARA_UF = {v: k for k, v in UF_PARA_ID.items()}

NOME_ESTADO_PARA_UF = {
    "ACRE": "AC", "ALAGOAS": "AL", "AMAPA": "AP", "AMAZONAS": "AM", "BAHIA": "BA",
    "CEARA": "CE", "DISTRITO FEDERAL": "DF", "ESPIRITO SANTO": "ES", "GOIAS": "GO",
    "MARANHAO": "MA", "MATO GROSSO": "MT", "MATO GROSSO DO SUL": "MS",
    "MINAS GERAIS": "MG", "PARA": "PA", "PARAIBA": "PB", "PARANA": "PR",
    "PERNAMBUCO": "PE", "PIAUI": "PI", "RIO DE JANEIRO": "RJ",
    "RIO GRANDE DO NORTE": "RN", "RIO GRANDE DO SUL": "RS", "RONDONIA": "RO",
    "RORAIMA": "RR", "SANTA CATARINA": "SC", "SAO PAULO": "SP", "SERGIPE": "SE",
    "TOCANTINS": "TO",
}

# Senha com que o atleta é criado no Zempo. Ele troca depois, no próprio site.
SENHA_PADRAO = "123456"

SEXO_PARA_ID = {"M": "1", "F": "2"}
ID_PARA_SEXO = {"1": "M", "2": "F"}

# O Zempo só lista faixas coloridas; faixa preta entra como kodansha, fluxo à parte.
# A ORDEM AQUI É A PROGRESSÃO DA GRADUAÇÃO, na mesma sequência do formulário
# oficial da CBJ — e é ela que as telas exibem. Não ordene alfabeticamente.
FAIXA_PARA_ID = {
    "BRANCA": "1", "BRANCA/CINZA": "22", "CINZA": "2", "CINZA/AZUL": "3",
    "AZUL": "4", "AZUL/AMARELA": "5", "AMARELA": "10", "AMARELA/LARANJA": "11",
    "LARANJA": "6", "VERDE": "7", "ROXA": "8", "MARROM": "9",
}
# [(valor, rótulo)] para os selects. O rótulo sai do .title() do Python, que
# capitaliza depois da barra ("Branca/Cinza") — o filtro `title` do Jinja não faz isso.
FAIXAS_EM_ORDEM = [(chave, chave.title()) for chave in FAIXA_PARA_ID]
ID_PARA_FAIXA = {v: k.title() for k, v in FAIXA_PARA_ID.items()}

# Obrigatórios do formulário quando o tipo de cadastro é ATLETA.
# Derivado das classes validate[required] dentro dos blocos sempre-visíveis e
# .exibe_atleta (civil/escolaridade/pis/pix são exclusivos de ÁRBITRO).
OBRIGATORIOS_ATLETA = [
    "nome", "nome_primeiro", "nome_ultimo", "cpf", "nascimento", "sexo", "peso",
    "graduacao", "graduacao_data", "rg", "rg_orgao", "rg_estado", "rg_data",
    "cep", "endereco", "estado", "cidade", "bairro", "naturalidade",
    "email", "celular", "telefone", "foto",
]

# Rótulo amigável para a tela de pendências.
ROTULOS = {
    "nome": "Nome completo", "nome_primeiro": "Primeiro nome", "nome_ultimo": "Último nome",
    "cpf": "CPF", "nascimento": "Data de nascimento", "sexo": "Sexo", "peso": "Peso",
    "graduacao": "Graduação (faixa)", "graduacao_data": "Data da última graduação",
    "rg": "RG", "rg_orgao": "Órgão emissor do RG", "rg_estado": "Estado emissor do RG",
    "registro_data": "Data de registro na federação",
    "rg_data": "Data de emissão do RG", "cep": "CEP", "endereco": "Endereço (rua)",
    "estado": "Estado", "cidade": "Cidade", "bairro": "Bairro",
    "naturalidade": "Naturalidade (UF)", "email": "E-mail", "celular": "Celular",
    "telefone": "Telefone residencial", "foto": "Foto",
}

# Campo do Zempo -> coluna em `alunos`, para o diff e o sync de volta.
CAMPO_ZEMPO_PARA_COLUNA = {
    "nome": "nome", "cpf": "cpf", "peso": "peso", "rg": "rg",
    "rg_orgao": "orgao_emissor", "email": "email", "endereco": "rua",
    "complemento": "numero", "cep": "cep", "responsavel": "responsavel_nome",
    "responsavel_parentesco": "responsavel_parentesco", "nacionalidade": "nacionalidade",
    "celular": "tel_celular", "telefone": "tel_residencial",
    "pai": "nome_pai", "mae": "nome_mae",
}


# ---------------------------------------------------------------- utilidades

def _texto(valor):
    return ("" if valor is None else str(valor)).strip()


def _sem_acento(valor):
    nfd = unicodedata.normalize("NFD", _texto(valor))
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _digitos(valor):
    return re.sub(r"\D", "", _texto(valor))


def _data_br(valor):
    """date/datetime/str -> dd/mm/aaaa. Vazio se não der para interpretar."""
    if not valor:
        return ""
    if isinstance(valor, (date, datetime)):
        return valor.strftime("%d/%m/%Y")
    bruto = _texto(valor)
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y"):
        try:
            return datetime.strptime(bruto[:19], formato).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return ""


def _cpf_formatado(valor):
    d = _digitos(valor)
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}" if len(d) == 11 else ""


def _telefone_formatado(valor):
    """O Zempo grava no formato (81)99999-9999."""
    d = _digitos(valor)
    if len(d) == 11:
        return f"({d[:2]}){d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"({d[:2]}){d[2:6]}-{d[6:]}"
    return _texto(valor)


def _uf_id(valor):
    """Aceita 'PE', 'pe' ou 'Pernambuco' e devolve o id do Zempo."""
    bruto = _sem_acento(valor).upper().strip()
    if not bruto:
        return ""
    if bruto in UF_PARA_ID:
        return UF_PARA_ID[bruto]
    return UF_PARA_ID.get(NOME_ESTADO_PARA_UF.get(bruto, ""), "")


def _faixa_id(nome_faixa):
    bruto = _sem_acento(nome_faixa).upper().strip()
    bruto = re.sub(r"\s*/\s*", "/", bruto)
    bruto = re.sub(r"^FAIXA\s+", "", bruto)
    return FAIXA_PARA_ID.get(bruto, "")


def _partes_do_nome(nome_completo):
    partes = [p for p in _texto(nome_completo).split() if p]
    if not partes:
        return "", ""
    if len(partes) == 1:
        return partes[0], partes[0]
    return partes[0], partes[-1]


# ---------------------------------------------------------------- validação

def validar_aluno(aluno):
    """
    Confere o aluno contra os obrigatórios do Zempo.

    `aluno` é a linha de `alunos` (dict) já com `faixa` vinda de `graduacao`.
    Retorna [(campo, rótulo)] do que falta — lista vazia significa pronto para migrar.
    """
    valores = _valores_diretos(aluno)
    faltando = []
    for campo in OBRIGATORIOS_ATLETA:
        if not _texto(valores.get(campo)):
            faltando.append((campo, ROTULOS.get(campo, campo)))
    return faltando


def _valores_diretos(aluno):
    """Campos do Zempo que saem do aluno sem precisar consultar o Zempo."""
    nome = _texto(aluno.get("nome"))
    primeiro, ultimo = _partes_do_nome(nome)
    peso = aluno.get("peso")
    return {
        "nome": nome,
        "nome_primeiro": primeiro,
        "nome_ultimo": ultimo,
        "cpf": _cpf_formatado(aluno.get("cpf")),
        "nascimento": _data_br(aluno.get("data_nascimento")),
        "sexo": SEXO_PARA_ID.get(_texto(aluno.get("sexo")).upper(), ""),
        "peso": f"{float(peso):.2f}" if peso not in (None, "", 0) else "",
        "graduacao": _faixa_id(aluno.get("faixa")),
        "graduacao_data": _data_br(aluno.get("ultimo_exame_faixa")),
        "rg": _texto(aluno.get("rg")),
        "rg_orgao": _texto(aluno.get("orgao_emissor")),
        # Cai na UF de residência só quando a emissora não foi informada.
        "rg_estado": _uf_id(aluno.get("rg_uf")) or _uf_id(aluno.get("estado")),
        "rg_data": _data_br(aluno.get("rg_data_emissao")),
        "cep": _digitos(aluno.get("cep")),
        "endereco": _texto(aluno.get("rua")),
        "complemento": " ".join(x for x in [_texto(aluno.get("numero")),
                                            _texto(aluno.get("complemento"))] if x),
        "estado": _uf_id(aluno.get("estado")),
        "naturalidade": _uf_id(aluno.get("naturalidade")) or _uf_id(aluno.get("estado")),
        "nacionalidade": _texto(aluno.get("nacionalidade")) or "Brasil",
        "email": _texto(aluno.get("email")),
        # O Zempo exige celular E telefone residencial. O sistema costuma ter só um
        # deles, então um cobre o outro em vez de barrar a migração por formalidade.
        "celular": _telefone_formatado(aluno.get("tel_celular") or aluno.get("telefone")
                                       or aluno.get("tel_residencial")),
        "telefone": _telefone_formatado(aluno.get("tel_residencial") or aluno.get("telefone")
                                        or aluno.get("tel_celular")),
        "responsavel": _texto(aluno.get("responsavel_nome")),
        "responsavel_parentesco": _texto(aluno.get("responsavel_parentesco")),
        "pai": _texto(aluno.get("nome_pai")),
        "mae": _texto(aluno.get("nome_mae")),
        # `cidade`/`bairro` são ids resolvidos no Zempo; a foto é enviada como arquivo.
        "cidade": _texto(aluno.get("cidade")),
        "bairro": _texto(aluno.get("bairro")),
        "foto": _texto(aluno.get("foto")),
    }


# ----------------------------------------------------------------- montagem

def montar_payload(aluno, cliente, senha=None):
    """
    Monta o payload de cadastro. Consulta o Zempo para os campos que ele calcula
    (classe, categoria) e para os ids de cidade/bairro.

    Levanta ZempoError se o Zempo não resolver classe/categoria, e ValueError se
    a cidade ou o bairro do aluno não existirem na base do Zempo.
    """
    valores = _valores_diretos(aluno)

    estado_id = valores["estado"]
    cidade_id = cliente.resolver_cidade(estado_id, valores["cidade"])
    if not cidade_id:
        raise ValueError(
            f"A cidade '{valores['cidade']}' não existe na lista do Zempo para "
            f"{ID_PARA_UF.get(estado_id, '?')}. Corrija o cadastro do aluno.")
    bairro_id = cliente.resolver_bairro(cidade_id, valores["bairro"])
    if not bairro_id:
        raise ValueError(
            f"O bairro '{valores['bairro']}' não existe na lista do Zempo para "
            f"{valores['cidade']}. Corrija o cadastro do aluno.")

    classes = cliente.classes_de(valores["nascimento"], valores["sexo"], valores["graduacao"])
    categoria_id, _ = cliente.categoria_de(
        valores["peso"], valores["sexo"], valores["graduacao"], classes)

    senha_pessoa = _texto(senha) or SENHA_PADRAO

    payload = {
        "nome": valores["nome"],
        "nome_primeiro": valores["nome_primeiro"],
        "nome_ultimo": valores["nome_ultimo"],
        "cpf": valores["cpf"],
        "nascimento": valores["nascimento"],
        "sexo": valores["sexo"],
        "peso": valores["peso"],
        "graduacao": valores["graduacao"],
        "graduacao_data": valores["graduacao_data"],
        "registro_data": _data_br(aluno.get("data_matricula")) or _data_br(date.today()),
        "rg": valores["rg"],
        "rg_orgao": valores["rg_orgao"],
        "rg_estado": valores["rg_estado"],
        "rg_data": valores["rg_data"],
        "cep": valores["cep"],
        "endereco": valores["endereco"],
        "complemento": valores["complemento"],
        "estado": estado_id,
        "cidade": cidade_id,
        "bairro": bairro_id,
        "naturalidade": valores["naturalidade"],
        "nacionalidade": valores["nacionalidade"],
        "email": valores["email"],
        "email2": valores["email"],          # o Zempo exige a confirmação
        "celular": valores["celular"],
        "telefone": valores["telefone"],
        "responsavel": valores["responsavel"],
        "responsavel_parentesco": valores["responsavel_parentesco"],
        "pai": valores["pai"],
        "mae": valores["mae"],
        "categoria": categoria_id,
        "status": "1",                        # Ativo
        "senha": senha_pessoa,
        "senha2": senha_pessoa,
    }
    payload.update(classes)
    return payload


# --------------------------------------------------------------------- diff

def comparar(dados_zempo, aluno, cliente=None):
    """
    Diff entre o cadastro no Zempo e o aluno no sistema, para a prévia do sync.

    Retorna [{campo, rotulo, valor_zempo, valor_sistema, coluna}] só com o que
    difere — `coluna` é a coluna de `alunos` a atualizar se o usuário aceitar.
    """
    diferencas = []
    for campo, coluna in CAMPO_ZEMPO_PARA_COLUNA.items():
        no_zempo = _texto(dados_zempo.get(campo))
        no_sistema = _texto(aluno.get(coluna))
        if not no_zempo:
            continue
        if _comparavel(campo, no_zempo) == _comparavel(campo, no_sistema):
            continue
        diferencas.append({
            "campo": campo,
            "rotulo": ROTULOS.get(campo, campo.replace("_", " ").capitalize()),
            "valor_zempo": no_zempo,
            "valor_sistema": no_sistema,
            "coluna": coluna,
        })

    # Campos que exigem tradução de id -> texto antes de comparar.
    for campo, coluna, traduz in (
        ("sexo", "sexo", lambda v: ID_PARA_SEXO.get(v, "")),
        ("graduacao", "faixa", lambda v: ID_PARA_FAIXA.get(v, "")),
        ("estado", "estado", lambda v: ID_PARA_UF.get(v, "")),
        ("naturalidade", "naturalidade", lambda v: ID_PARA_UF.get(v, "")),
        ("rg_estado", "rg_uf", lambda v: ID_PARA_UF.get(v, "")),
    ):
        if coluna is None:
            continue
        no_zempo = traduz(_texto(dados_zempo.get(campo)))
        no_sistema = _texto(aluno.get(coluna))
        if no_zempo and no_zempo.upper() != _sem_acento(no_sistema).upper():
            diferencas.append({
                "campo": campo,
                "rotulo": ROTULOS.get(campo, campo),
                "valor_zempo": no_zempo,
                "valor_sistema": no_sistema,
                "coluna": coluna,
            })

    # Cidade e bairro são ids no Zempo: precisam do cliente para virar nome.
    if cliente is not None:
        estado_id = _texto(dados_zempo.get("estado"))
        cidade_id = _texto(dados_zempo.get("cidade"))
        bairro_id = _texto(dados_zempo.get("bairro"))
        try:
            nomes = []
            if estado_id and cidade_id:
                nomes.append(("cidade", "cidade",
                              cliente.nome_da_cidade(estado_id, cidade_id)))
                if bairro_id:
                    nomes.append(("bairro", "bairro",
                                  cliente.nome_do_bairro(cidade_id, bairro_id)))
            for campo, coluna, no_zempo in nomes:
                no_sistema = _texto(aluno.get(coluna))
                if no_zempo and _sem_acento(no_zempo).upper() != _sem_acento(no_sistema).upper():
                    diferencas.append({
                        "campo": campo,
                        "rotulo": ROTULOS.get(campo, campo.capitalize()),
                        "valor_zempo": no_zempo,
                        "valor_sistema": no_sistema or "(vazio)",
                        "coluna": coluna,
                    })
        except Exception:
            pass  # sem rede não dá para traduzir os ids; o resto do diff continua

    # Datas: o Zempo devolve dd/mm/aaaa, o banco guarda date.
    for campo, coluna in (("nascimento", "data_nascimento"),
                          ("graduacao_data", "ultimo_exame_faixa"),
                          ("rg_data", "rg_data_emissao"),
                          ("registro_data", "zempo_registro_data")):
        no_zempo = _texto(dados_zempo.get(campo))
        no_sistema = _data_br(aluno.get(coluna))
        if no_zempo and no_zempo != no_sistema:
            diferencas.append({
                "campo": campo,
                "rotulo": ROTULOS.get(campo, campo),
                "valor_zempo": no_zempo,
                "valor_sistema": no_sistema or "(vazio)",
                "coluna": coluna,
            })
    return diferencas


def _comparavel(campo, valor):
    """Normaliza para comparar sem falso positivo de formatação."""
    if campo in ("cpf", "celular", "telefone", "cep"):
        return _digitos(valor)
    if campo == "peso":
        try:
            return f"{float(str(valor).replace(',', '.')):.2f}"
        except (TypeError, ValueError):
            return _texto(valor)
    return _sem_acento(valor).upper()


def valor_para_banco(campo, valor_zempo):
    """Converte o valor lido do Zempo para o formato da coluna de `alunos`."""
    if campo in ("nascimento", "graduacao_data", "rg_data", "registro_data"):
        try:
            return datetime.strptime(valor_zempo, "%d/%m/%Y").date()
        except ValueError:
            return None
    if campo == "sexo":
        return ID_PARA_SEXO.get(valor_zempo, None)
    if campo in ("estado", "naturalidade", "rg_estado"):
        return ID_PARA_UF.get(valor_zempo, valor_zempo)
    if campo == "peso":
        try:
            return float(str(valor_zempo).replace(",", "."))
        except (TypeError, ValueError):
            return None
    if campo == "cpf":
        return _cpf_formatado(valor_zempo) or valor_zempo
    return valor_zempo
