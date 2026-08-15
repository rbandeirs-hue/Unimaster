"""
Integração com o Zempo (sistema de cadastro da CBJ — https://zempo.com.br).

A configuração é POR ASSOCIAÇÃO: um código de clube (CLxxxxx) cobre todas as
academias vinculadas. As credenciais ficam na tabela `associacoes`:
  - zempo_codigo       : código de acesso do clube (ex.: CL00947)
  - zempo_senha        : senha do acesso
  - zempo_clube_id     : id numérico do clube no Zempo (ex.: 947)
  - zempo_federacao_id : id da federação no Zempo (ex.: 25 = PE)

O Zempo não expõe API: é um site PHP em ISO-8859-1. Este cliente reproduz os
mesmos POSTs que o navegador faz.

Uso:
    from utils.zempo import ZempoClient
    cli = ZempoClient(codigo, senha, clube_id, federacao_id)
    if cli.configurado:
        cli.login()
        zid = cli.buscar_por_cpf("141.114.104-05")
        dados = cli.ler_pessoa(zid)

Endpoints (descobertos por inspeção do formulário oficial):
    POST /?acao=logando                              {codigo, senha}
    POST /index.php?secao=pessoas_cadastro&acao=cadastrar   (multipart)
    POST /index.php?secao=pessoas_editar&acao=atualizar&id=N (multipart)
    GET  /index.php?secao=pessoas_editar&id=N        (lê os 96 campos)
    POST /index.php?secao=atletas&acao=buscar        {cpf}
    POST /retorno_classes.php        {nascimento, sexo, federacao, graduacao}
    POST /retorno_categorias.php     {peso, sexo, federacao, graduacao, classe..classe15}
    POST /retorno_cidades_geral.php  {estado, tamanho, tipo}
    POST /retorno_bairros_geral.php  {cidade, tamanho, tipo}
    POST /retorno_clubes_pessoas.php {federacao}
"""
import re
import unicodedata

import requests
from bs4 import BeautifulSoup

BASE = "https://zempo.com.br"
TIMEOUT = 30
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# Campos de controle do formulário que nunca devem ser reenviados como dado.
_CAMPOS_IGNORADOS = {"palavra", "imageField", "senha", "senha2", "foto",
                     "cref_frente", "cref_verso", "graduacao_solicitada_anexo"}


class ZempoError(RuntimeError):
    """Falha de comunicação ou de validação no lado do Zempo."""


def _sem_acento(texto):
    nfd = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _latin1(valor):
    """O Zempo é ISO-8859-1; acentos fora dessa tabela viram equivalente sem acento."""
    s = "" if valor is None else str(valor)
    try:
        return s.encode("iso-8859-1")
    except UnicodeEncodeError:
        return _sem_acento(s).encode("iso-8859-1", "ignore")


class ZempoClient:
    """Cliente Zempo vinculado às credenciais de uma associação."""

    def __init__(self, codigo, senha, clube_id=None, federacao_id=None):
        self.codigo = (codigo or "").strip()
        self.senha = (senha or "").strip()
        self.clube_id = str(clube_id or "").strip()
        self.federacao_id = str(federacao_id or "").strip()
        self._sessao = None
        # O Zempo é lento (~1,5 s por página). Numa mesma operação o mesmo cadastro
        # e as mesmas listas de cidade/bairro são pedidos várias vezes; guardar as
        # respostas aqui corta o tempo pela metade sem mudar o comportamento.
        self._cache_pessoas = {}
        self._cache_cidades = {}
        self._cache_bairros = {}

    @property
    def configurado(self):
        """True se a associação tem código e senha do Zempo definidos."""
        return bool(self.codigo and self.senha)

    # ---------------------------------------------------------------- sessão

    def login(self):
        """Autentica e guarda a sessão (PHPSESSID). Idempotente."""
        if self._sessao is not None:
            return self._sessao
        if not self.configurado:
            raise ZempoError("Credenciais do Zempo não configuradas para esta associação.")

        s = requests.Session()
        s.headers.update({
            "User-Agent": UA,
            "Accept-Language": "pt-BR,pt;q=0.9",
        })
        try:
            s.get(BASE + "/portal/", timeout=TIMEOUT)
            r = s.post(BASE + "/?acao=logando",
                       data={"redireciona_teste": "?secao=main",
                             "codigo": self.codigo, "senha": self.senha},
                       timeout=TIMEOUT)
        except requests.RequestException as e:
            raise ZempoError(f"Não foi possível conectar ao Zempo: {e}")

        if not s.cookies.get("PHPSESSID"):
            raise ZempoError("O Zempo não iniciou sessão. Verifique código e senha.")

        # Confirma que a sessão está autenticada: a área logada tem o menu de pessoas.
        teste = self._texto(s.get(BASE + "/index.php?secao=main", timeout=TIMEOUT))
        if "SAIR" not in teste.upper():
            raise ZempoError("Login recusado pelo Zempo. Verifique código e senha.")

        self._sessao = s
        return s

    @staticmethod
    def _texto(resposta):
        resposta.encoding = "iso-8859-1"
        return resposta.text

    def _get(self, url):
        return self._texto(self.login().get(url, timeout=TIMEOUT))

    def _post(self, url, dados):
        return self._texto(self.login().post(url, data=dados, timeout=TIMEOUT))

    def _post_multipart(self, url, dados, arquivos=None):
        """POST multipart com os valores codificados em ISO-8859-1, como o navegador faz."""
        campos = {}
        for chave, valor in dados.items():
            campos[chave] = (None, _latin1(valor))
        for chave, (nome, conteudo, mime) in (arquivos or {}).items():
            campos[chave] = (nome, conteudo, mime)
        return self._texto(self.login().post(url, files=campos, timeout=TIMEOUT))

    # ------------------------------------------------------------ auxiliares

    def classes_de(self, nascimento, sexo, graduacao):
        """
        Resolve as classes etárias (classe, classe2..classe15) — campos obrigatórios
        e calculados pelo próprio Zempo a partir de nascimento/sexo/federação/graduação.
        `nascimento` em dd/mm/aaaa, `sexo` 1|2, `graduacao` id do Zempo.
        """
        bruto = self._post(BASE + "/retorno_classes.php", {
            "nascimento": nascimento, "sexo": sexo,
            "federacao": self.federacao_id, "graduacao": graduacao,
        }).strip()
        if not bruto:
            raise ZempoError("O Zempo não retornou classe etária para os dados informados.")
        classes = {}
        for i, parte in enumerate(bruto.split("//")):
            chave = "classe" if i == 0 else f"classe{i + 1}"
            if i >= 15:
                break
            classes[chave] = parte.split("&")[0]
        for i in range(2, 16):  # completa o que o Zempo não devolveu
            classes.setdefault(f"classe{i}", "")
        if not classes.get("classe"):
            raise ZempoError("O Zempo não encontrou classe etária para esta data de nascimento.")
        return classes

    def categoria_de(self, peso, sexo, graduacao, classes):
        """Resolve a categoria de peso (campo obrigatório calculado pelo Zempo)."""
        dados = {"peso": peso, "sexo": sexo, "federacao": self.federacao_id,
                 "graduacao": graduacao}
        dados.update(classes)
        bruto = self._post(BASE + "/retorno_categorias.php", dados).strip()
        if not bruto or "&" not in bruto:
            raise ZempoError(f"O Zempo não encontrou categoria para o peso {peso} kg.")
        codigo, nome = bruto.split("&", 1)
        if not codigo.strip():
            raise ZempoError(f"O Zempo não encontrou categoria para o peso {peso} kg.")
        return codigo.strip(), nome.strip()

    def _opcoes(self, html, nome_select):
        soup = BeautifulSoup(html, "html.parser")
        sel = soup.find("select", {"name": nome_select}) or soup.find("select")
        if not sel:
            return []
        return [(o.get("value") or "", o.get_text(strip=True))
                for o in sel.find_all("option") if (o.get("value") or "").strip()]

    def cidades(self, estado_id):
        """[(id, nome)] das cidades de um estado (id do Zempo)."""
        chave = str(estado_id)
        if chave not in self._cache_cidades:
            html = self._post(BASE + "/retorno_cidades_geral.php",
                              {"estado": estado_id, "tamanho": "260", "tipo": "1"})
            self._cache_cidades[chave] = self._opcoes(html, "cidade")
        return self._cache_cidades[chave]

    def bairros(self, cidade_id):
        """[(id, nome)] dos bairros de uma cidade (id do Zempo)."""
        chave = str(cidade_id)
        if chave not in self._cache_bairros:
            html = self._post(BASE + "/retorno_bairros_geral.php",
                              {"cidade": cidade_id, "tamanho": "260", "tipo": "1"})
            self._cache_bairros[chave] = self._opcoes(html, "bairro")
        return self._cache_bairros[chave]

    def resolver_cidade(self, estado_id, nome_cidade):
        """Encontra o id da cidade pelo nome (ignora acento/caixa). None se não achar."""
        return self._casar(self.cidades(estado_id), nome_cidade)

    def resolver_bairro(self, cidade_id, nome_bairro):
        """Encontra o id do bairro pelo nome. None se não achar."""
        return self._casar(self.bairros(cidade_id), nome_bairro)

    @staticmethod
    def _casar(opcoes, alvo):
        alvo_n = _sem_acento((alvo or "").strip()).upper()
        if not alvo_n:
            return None
        for valor, rotulo in opcoes:
            if _sem_acento(rotulo).upper() == alvo_n:
                return valor
        for valor, rotulo in opcoes:  # tolera "Boa Viagem" vs "BOA VIAGEM (RECIFE)"
            if alvo_n in _sem_acento(rotulo).upper():
                return valor
        return None

    def clubes(self):
        """[(id, nome)] dos clubes da federação — usado para confirmar o zempo_clube_id."""
        html = self._post(BASE + "/retorno_clubes_pessoas.php",
                          {"federacao": self.federacao_id})
        return self._opcoes(html, "clube")

    # ------------------------------------------------------------- consultas

    def buscar_por_cpf(self, cpf):
        """
        Retorna o id da pessoa no Zempo com este CPF, ou None.

        A busca é por GET e o CPF precisa ir pontuado: enviado só com dígitos, ou
        por POST, o Zempo ignora o filtro e devolve a listagem inteira.
        """
        digitos = re.sub(r"\D", "", cpf or "")
        if len(digitos) != 11:
            return None
        formatado = f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"
        html = self._get(f"{BASE}/index.php?secao=atletas&acao=buscar&cpf={formatado}")
        achados = re.findall(r"secao=pessoas_editar[^\"']*?id=(\d+)", html)
        # Um CPF só pode ter um cadastro; mais de um id significa filtro ignorado.
        unicos = list(dict.fromkeys(achados))
        if len(unicos) != 1:
            return None
        # Sem correspondência o Zempo devolve um registro qualquer em vez de lista
        # vazia, então o CPF do candidato precisa ser conferido antes de aceitar.
        candidato = unicos[0]
        try:
            if re.sub(r"\D", "", self.ler_pessoa(candidato).get("cpf", "")) != digitos:
                return None
        except ZempoError:
            return None
        return candidato

    def ler_pessoa(self, zempo_id):
        """
        Lê o cadastro completo da pessoa a partir do formulário de edição.
        Retorna dict {campo: valor} com os ~96 campos do Zempo.
        """
        chave = str(zempo_id)
        if chave in self._cache_pessoas:
            return self._cache_pessoas[chave]

        html = self._get(f"{BASE}/index.php?secao=pessoas_editar&id={zempo_id}")
        if "pessoas_editar&acao=atualizar" not in html:
            raise ZempoError(f"Cadastro {zempo_id} não encontrado ou sem permissão de edição.")
        campos = self._colher_campos(html)
        # Para um id inexistente o Zempo devolve o formulário em branco em vez de
        # erro. Um cadastro real sempre traz CPF ou RG; sem nenhum dos dois, não existe.
        if not (campos.get("cpf") or "").strip() and not (campos.get("rg") or "").strip():
            raise ZempoError(f"Cadastro {zempo_id} não existe no Zempo.")
        self._cache_pessoas[chave] = campos
        return campos

    @staticmethod
    def _colher_campos(html, incluir_ignorados=False):
        """
        Extrai todos os inputs/selects/textareas do documento.

        Varre o documento inteiro, e não apenas o elemento <form>: o HTML do Zempo
        aninha o formulário dentro de tabelas de forma inválida, o que faz qualquer
        parser fechar o <form> cedo e perder a maior parte dos campos.

        `incluir_ignorados=True` mantém senha e os campos de arquivo, mesmo vazios.
        É obrigatório ao montar um POST: o navegador envia esses campos sempre, e
        sem eles o Zempo descarta o formulário inteiro com "Preencha os campos
        corretamente!". Para apenas LER um cadastro, o padrão (False) é o certo.
        """
        soup = BeautifulSoup(html, "html.parser")
        campos = {}
        for tag in soup.find_all(["input", "select", "textarea"]):
            nome = tag.get("name")
            if not nome or nome.startswith("auto_"):
                continue
            if not incluir_ignorados and nome in _CAMPOS_IGNORADOS:
                continue
            if nome in ("palavra", "imageField"):
                continue
            if tag.name == "select":
                escolhida = tag.find("option", selected=True)
                valor = (escolhida.get("value") or "") if escolhida else ""
            elif tag.name == "textarea":
                valor = (tag.get_text() or "").strip()
            else:
                if tag.get("type") in ("checkbox", "radio") and not tag.has_attr("checked"):
                    continue
                valor = tag.get("value") or ""
            # O documento repete campos (formulário de busca no topo): fica o preenchido.
            if nome not in campos or (valor and not campos[nome]):
                campos[nome] = valor
        return campos

    def ficha_texto(self, zempo_id):
        """Texto da ficha impressa — usado para ler rótulos que o form não expõe."""
        return self._get(f"{BASE}/pessoas_imprimir.php?detalhes=1&imprimir=1&id={zempo_id}")

    def dados_da_ficha(self, zempo_id):
        """
        Campos que só existem na ficha impressa, porque o formulário de edição
        não os expõe: data de registro na federação e data de nascimento.
        """
        texto = BeautifulSoup(self.ficha_texto(zempo_id), "html.parser").get_text(" ", strip=True)
        texto = re.sub(r"\s+", " ", texto)
        achados = {}
        for chave, padrao in (("registro_data", r"Registro em:?\s*(\d{2}/\d{2}/\d{4})"),
                              ("nascimento", r"Data de Nascimento\s*(\d{2}/\d{2}/\d{4})")):
            encontrado = re.search(padrao, texto, re.I)
            if encontrado:
                achados[chave] = encontrado.group(1)
        return achados

    def nome_da_cidade(self, estado_id, cidade_id):
        """Nome da cidade a partir do id do Zempo (para comparar com o sistema)."""
        return dict(self.cidades(estado_id)).get(str(cidade_id or "")) or ""

    def nome_do_bairro(self, cidade_id, bairro_id):
        """Nome do bairro a partir do id do Zempo."""
        return dict(self.bairros(cidade_id)).get(str(bairro_id or "")) or ""

    # --------------------------------------------------------------- escrita

    def criar_atleta(self, campos, foto=None):
        """
        Cria o cadastro de ATLETA. `campos` é o payload já montado pelo mapper.
        `foto` é (nome_arquivo, bytes, mimetype) — opcional (o Zempo só a exige no
        navegador; o servidor aceita sem).
        Retorna (zempo_id, zempo_numero).
        """
        # O Zempo descarta o POST inteiro e responde "Preencha os campos
        # corretamente!" se o formulário não vier completo. Por isso a base é a
        # própria página de cadastro, com todos os campos e seus defaults, e o
        # payload entra por cima.
        formulario = self._colher_campos(
            self._get(BASE + "/index.php?secao=pessoas_cadastro"), incluir_ignorados=True)
        payload = {chave: "" for chave in formulario}
        payload.update(formulario)
        payload.update(campos)
        payload["tipo_cadastro_atleta"] = "1"
        payload.setdefault("federacao", self.federacao_id)
        payload.setdefault("clube", self.clube_id)
        # O submit é <input type="image">: o navegador envia as coordenadas junto.
        payload["imageField.x"] = "50"
        payload["imageField.y"] = "10"

        arquivos = {"foto": foto} if foto else None
        html = self._post_multipart(
            BASE + "/index.php?secao=pessoas_cadastro&acao=cadastrar", payload, arquivos)

        erro = self._erro_do_html(html)
        if erro:
            raise ZempoError(erro)

        # A confirmação mais confiável é reconsultar pelo CPF.
        zempo_id = self.buscar_por_cpf(payload.get("cpf", ""))
        if not zempo_id:
            raise ZempoError(
                "O Zempo aceitou o envio mas o cadastro não foi localizado pelo CPF. "
                "Confira manualmente antes de tentar de novo, para não duplicar.")
        return zempo_id, f"JU{zempo_id}"

    def atualizar_pessoa(self, zempo_id, alteracoes, foto=None):
        """
        Atualiza o cadastro no Zempo preservando o que não foi alterado.

        Relê o formulário, aplica só as chaves de `alteracoes` e reenvia o conjunto
        completo — o Zempo trata o POST como substituição total, então enviar apenas
        os campos alterados apagaria todo o resto.
        """
        # Ler direto da origem: o cache pode ter uma versão anterior deste cadastro.
        self._cache_pessoas.pop(str(zempo_id), None)
        html = self._get(f"{BASE}/index.php?secao=pessoas_editar&id={zempo_id}")
        if "pessoas_editar&acao=atualizar" not in html:
            raise ZempoError(f"Cadastro {zempo_id} não encontrado ou sem permissão de edição.")
        atuais = self._colher_campos(html, incluir_ignorados=True)
        atuais.update(alteracoes)
        atuais["tipo_cadastro_atleta"] = "1"
        atuais["imageField.x"] = "50"
        atuais["imageField.y"] = "10"

        arquivos = {"foto": foto} if foto else None
        html = self._post_multipart(
            f"{BASE}/index.php?secao=pessoas_editar&acao=atualizar&id={zempo_id}",
            atuais, arquivos)
        erro = self._erro_do_html(html)
        if erro:
            raise ZempoError(erro)
        # Depois de gravar, o que estiver em cache está desatualizado.
        self._cache_pessoas.pop(str(zempo_id), None)
        return True

    @staticmethod
    def _erro_do_html(html):
        """
        Extrai a mensagem de erro que o Zempo devolve na própria página.

        Os <script> são descartados antes da leitura: o formulário embute strings
        como "Erro ao encontrar categoria." no JavaScript, que casariam com os
        padrões abaixo e transformariam todo sucesso em falha.
        """
        soup = BeautifulSoup(html, "html.parser")
        for bloco in soup(["script", "style"]):
            bloco.decompose()
        texto = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        for padrao in (r"(Preencha os campos corretamente[^<]{0,40})",
                       r"(J[áa] existe[^.!<]{0,160})",
                       r"(CPF[^.!<]{0,80}(?:j[áa] cadastrado|inv[áa]lido)[^.!<]{0,80})"):
            achado = re.search(padrao, texto, re.I)
            if achado:
                return achado.group(1).strip()
        return None
