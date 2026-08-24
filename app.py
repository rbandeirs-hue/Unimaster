# ============================================================
# 🔥 JUDO ACADEMY — APP PRINCIPAL (100% RBAC por Roles)
# ============================================================

import os
import sys

# Carrega variáveis do arquivo .env (ignorado silenciosamente se não existir)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv não instalado; use variáveis de ambiente do sistema

from flask import Flask, redirect, url_for, send_from_directory, request
from flask_login import LoginManager, current_user
from flask_socketio import SocketIO
from extensions import csrf
from config import get_db_connection

# ============================
# 🔹 Blueprints
# ============================
from blueprints.auth.routes import auth_bp
from blueprints.painel.routes import painel_bp
from blueprints.federacao.routes import federacao_bp
from blueprints.associacao.routes import associacao_bp
from blueprints.academia.routes import academia_bp
from blueprints.aluno import bp_alunos, bp_painel_aluno
from blueprints.painel_responsavel import bp_painel_responsavel
from blueprints.cadastros import cadastros_bp
from blueprints.usuarios.routes import bp_usuarios
from blueprints.turmas.routes import bp_turmas
from blueprints.presencas.presencas import bp_presencas
from blueprints.professores.routes import bp_professores
from blueprints.professor.routes import bp_professor
from blueprints.configuracoes import bp_configuracoes
from blueprints.financeiro.routes import bp_financeiro
from blueprints.financeiro.painel import bp_financeiro_painel, bp_link_pagamento
from blueprints.precadastro import bp_precadastro
from blueprints.solicitacoes import bp_solicitacoes
from blueprints.calendario import bp_calendario
from blueprints.formularios import bp_formularios
from blueprints.eventos_competicoes import bp_eventos_competicoes
from blueprints.competicoes import bp_competicoes
from blueprints.visitante import bp_visitante
from blueprints.externo import bp_externo
from blueprints.notificacoes import bp_notificacoes
from blueprints.aniversario_mensagens import aniversario_mensagens_bp
from blueprints.aniversariante_live import bp_aniversariante_live
from blueprints.zempo import bp_zempo, bp_zempo_publico

# 🔹 Modelo de Usuário (flask-login)
from blueprints.auth.user_model import Usuario


# ============================================================
# 🔹 Inicialização da aplicação
# ============================================================
import secrets as _secrets

app = Flask(__name__)

# SECRET_KEY: lê do ambiente; em dev gera uma temporária (invalida sessions ao reiniciar).
# Em produção, defina SECRET_KEY como variável de ambiente com valor forte (64+ chars hex).
_secret_key = os.environ.get("SECRET_KEY")
if not _secret_key:
    import sys as _sys
    if os.environ.get("FLASK_ENV") == "production":
        raise RuntimeError(
            "SECRET_KEY não definida. Configure a variável de ambiente em produção."
        )
    _secret_key = _secrets.token_hex(32)
    print("⚠️  SECRET_KEY não definida — usando chave temporária (apenas desenvolvimento).", file=_sys.stderr)

app.secret_key = _secret_key


@app.route("/favicon.ico")
def favicon():
    """Navegadores pedem /favicon.ico por padrão; reutiliza o ícone do login (PNG)."""
    return send_from_directory(
        os.path.join(app.static_folder, "img", "login"),
        "judo-icon.png",
        mimetype="image/png",
        max_age=86400,
    )


@app.route("/sw.js")
def service_worker_script():
    """Serve `static/sw.js` em `/sw.js` com escopo ampliado para `/` (Web Push + getRegistration em qualquer rota)."""
    resp = send_from_directory(app.static_folder, "sw.js")
    resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


# Cookies de sessão seguros
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Ativa Secure apenas em produção (requer HTTPS)
if os.environ.get("FLASK_ENV") == "production":
    app.config["SESSION_COOKIE_SECURE"] = True
    app.config["WTF_CSRF_SSL_STRICT"] = True

# CORS: restrinja aos domínios autorizados via variável de ambiente.
# Exemplo: CORS_ORIGINS=http://localhost:5000,https://meudominio.com.br
_cors_env = os.environ.get("CORS_ORIGINS", "")
_cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()] or ["http://localhost:5000"]

# Configuração do SocketIO para WebSocket (placar de judô)
socketio = SocketIO(
    app,
    cors_allowed_origins=_cors_origins,
    async_mode='threading',
    logger=False,
    engineio_logger=False,
    ping_timeout=60,
    ping_interval=25
)


# ============================================================
# 🔹 CSRF Protection global
# ============================================================
csrf.init_app(app)
# Blueprint 100% público (sem autenticação) — isento de CSRF
csrf.exempt(bp_externo)


# ============================================================
# 🔹 Headers de segurança HTTP
# ============================================================
@app.after_request
def aplicar_headers_seguranca(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Liberar câmera/microfone para a própria origem (necessário para captura de
    # foto no cadastro de aluno/usuário/pré-cadastro). Geolocalização permanece bloqueada.
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(self), camera=(self)"
    # Strict-Transport-Security: ativar quando o servidor usar HTTPS
    # response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    # Página autenticada não vai para o cache do navegador. Sem isto o "voltar"
    # depois do logout reexibe a tela do usuário anterior, e a troca de conta no
    # mesmo navegador mostrava a academia antiga vinda do cache. Estáticos
    # continuam cacheáveis — é o que mantém a navegação rápida.
    endpoint = request.endpoint or ""
    if response.mimetype == "text/html" and not endpoint.endswith("static"):
        try:
            autenticado = current_user.is_authenticated
        except Exception:
            autenticado = False
        if autenticado or endpoint.startswith("auth."):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
    return response


# ============================================================
# 🔹 Bloqueio: força cadastro de CPF antes de qualquer navegação
# ============================================================
_CPF_BLOQUEIO_PERMITIDOS = {
    "auth.login",
    "auth.logout",
    "auth.cadastrar_cpf",
    "auth.esqueci_senha",
    "auth.redefinir_senha",
    "static",
}


@app.before_request
def _exigir_cpf_cadastrado():
    if not current_user.is_authenticated:
        return None
    if getattr(current_user, "cpf", None):
        return None
    endpoint = request.endpoint or ""
    if endpoint in _CPF_BLOQUEIO_PERMITIDOS:
        return None
    # Não interferir em arquivos estáticos de qualquer blueprint
    if endpoint.endswith(".static"):
        return None
    return redirect(url_for("auth.cadastrar_cpf"))


# ============================================================
# 🔹 Cadastro do aluno incompleto: completa no primeiro acesso
# ============================================================
# Promover um pré-cadastro deixava o gestor na ficha do aluno para digitar o
# que faltava. Os dados são da família, então quem preenche é ela, na primeira
# vez que entra. Vale nos modos aluno e responsável — em criança o login sai no
# CPF do responsável financeiro, e só olhar o modo aluno deixaria esse caso de
# fora. Um gestor que também é aluno continua gerenciando normalmente, porque
# no modo academia a verificação nem roda.
_CADASTRO_ALUNO_PERMITIDOS = {
    "auth.login",
    "auth.logout",
    "auth.cadastrar_cpf",
    "auth.esqueci_senha",
    "auth.redefinir_senha",
    "painel.home",
    "painel.escolher_modo",
    "painel_aluno.completar_cadastro",
    "static",
}


@app.before_request
def _exigir_cadastro_aluno_completo():
    from flask import session

    if not current_user.is_authenticated:
        return None
    if session.get("modo_painel") not in ("aluno", "responsavel"):
        return None
    endpoint = request.endpoint or ""
    if endpoint in _CADASTRO_ALUNO_PERMITIDOS or endpoint.endswith(".static"):
        return None
    # Chamadas de dados não podem virar redirecionamento de tela.
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return None
    try:
        from blueprints.aluno.painel import alunos_com_cadastro_pendente

        if alunos_com_cadastro_pendente(current_user.id):
            return redirect(url_for("painel_aluno.completar_cadastro"))
    except Exception:
        # Nunca derrubar a navegação por causa da checagem.
        return None
    return None


# ============================================================
# 🔹 Escolha da academia na entrada (quem administra mais de uma)
# ============================================================
# Sem esta etapa, a academia ativa era decidida por `?academia_id=` na URL e
# podia trocar no meio do caminho — com risco de lançar dados na academia
# errada. Agora escolhe-se uma vez, na entrada, e ela vale a sessão toda.
_ESCOLHA_ACADEMIA_PERMITIDOS = {
    "auth.login",
    "auth.logout",
    "auth.cadastrar_cpf",
    "auth.esqueci_senha",
    "auth.redefinir_senha",
    "academia.escolher_academia",
    "painel.escolher_modo",
    "static",
}


@app.before_request
def _exigir_academia_escolhida():
    if not current_user.is_authenticated:
        return None
    endpoint = request.endpoint or ""
    if endpoint in _ESCOLHA_ACADEMIA_PERMITIDOS or endpoint.endswith(".static"):
        return None
    # Requisições de dados (JSON/fetch) não devem virar redirecionamento de tela.
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return None
    try:
        from blueprints.academia.routes import academia_travada, precisa_escolher_academia

        if precisa_escolher_academia():
            return redirect(url_for("academia.escolher_academia", next=request.full_path))

        # Já escolheu: um `academia_id` divergente na URL é reescrito para a
        # academia da sessão. Cada tela grava a academia a partir do próprio
        # parâmetro, então travar só no resolvedor central não bastava — um
        # link antigo continuava trocando o contexto.
        travada = academia_travada()
        pedido = request.args.get("academia_id", type=int)
        if travada and pedido and pedido != travada and request.method == "GET":
            args = request.args.to_dict(flat=True)
            args["academia_id"] = travada
            return redirect(url_for(request.endpoint, **{**(request.view_args or {}), **args}))
    except Exception:
        # Se a checagem falhar por qualquer motivo, o sistema segue aberto:
        # esta é uma etapa de organização, não de segurança.
        return None
    return None


# ============================================================
# 🔹 Configuração do Login
# ============================================================
login_manager = LoginManager(app)
login_manager.login_view = "auth.login"


# ============================================================
# 🔹 CARREGAR USUÁRIO LOGADO (RBAC)
# ============================================================
@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    # 1️⃣ Busca o usuário
    cur.execute("""
        SELECT *
        FROM usuarios
        WHERE id = %s
    """, (user_id,))
    user_row = cur.fetchone()

    if not user_row:
        cur.close()
        conn.close()
        return None

    # 2️⃣ Carrega roles do usuário (tabela roles_usuario)
    roles = Usuario.carregar_roles(user_row["id"])

    # 3️⃣ Carrega permissões derivadas das roles
    permissoes = Usuario.carregar_permissoes(user_row["id"])

    # 4️⃣ Carrega menus liberados (se a tabela existir)
    try:
        menus = Usuario.carregar_menus(user_row["id"])
    except Exception:
        menus = []

    cur.close()
    conn.close()

    # 5️⃣ Retorna objeto completo para flask-login
    return Usuario(
    id=user_row["id"],
    nome=user_row["nome"],
    email=user_row["email"],
    senha=user_row["senha"],
    id_federacao=user_row.get("id_federacao"),
    id_associacao=user_row.get("id_associacao"),
    id_academia=user_row.get("id_academia"),
    roles=roles,
    permissoes=permissoes,
    menus=menus,
    foto=user_row.get("foto"),
    cpf=user_row.get("cpf")
)
    


# ============================================================
# 🔹 asset(): link de estático com versão, para o cache não servir CSS velho
# ============================================================
_ASSET_VERSAO = {}


@app.template_global()
def asset(filename):
    """`url_for('static', ...)` com `?v=<mtime>` no fim.

    Em produção rodam 3 workers gunicorn com template em cache: sem isto, o
    navegador segue servindo o CSS/JS anterior depois do deploy e a tela
    aparece meio nova, meio velha. O mtime é lido uma vez por processo — em
    DEBUG relê sempre, senão o desenvolvedor edita e não vê.
    """
    versao = _ASSET_VERSAO.get(filename)
    if versao is None or app.debug:
        try:
            versao = str(int(os.path.getmtime(os.path.join(app.static_folder, filename))))
        except OSError:
            versao = "0"
        _ASSET_VERSAO[filename] = versao
    return url_for("static", filename=filename) + "?v=" + versao


# ============================================================
# 🔹 Context processor: múltiplos modos (para botão Trocar modo)
# ============================================================
@app.context_processor
def injetar_modos_e_contexto():
    from datetime import datetime
    from flask_login import current_user
    from flask import has_request_context, request, session
    from utils.contexto_logo import get_contexto_logo_e_nome

    layout_embed = False
    if has_request_context():
        layout_embed = (request.args.get("embed") or "").strip().lower() in ("1", "true", "yes")

    def tem_multiplos_modos():
        if not hasattr(current_user, 'is_authenticated') or not current_user.is_authenticated:
            return False
        from blueprints.painel.routes import _modos_disponiveis
        modos = _modos_disponiveis()
        return len(modos) > 1

    def modos_disponiveis():
        """Lista de (modo_id, modo_nome) para dropdown."""
        if not hasattr(current_user, 'is_authenticated') or not current_user.is_authenticated:
            return []
        from blueprints.painel.routes import _modos_disponiveis
        return _modos_disponiveis()

    def modo_atual_nome():
        """Retorna o nome amigável do modo atual (ex: Academia, Aluno)."""
        if not hasattr(current_user, 'is_authenticated') or not current_user.is_authenticated:
            return ""
        from utils.contexto_logo import _modo_efetivo
        modo = session.get("modo_painel") or _modo_efetivo(current_user)
        mapeamento = {
            "admin": "Administrador",
            "federacao": "Federação",
            "associacao": "Associação",
            "academia": "Academia",
            "professor": "Professor",
            "aluno": "Aluno",
            "responsavel": "Responsável",
            "visitante": "Visitante"
        }
        return mapeamento.get(modo, "")

    def get_back_url_default():
        """Home do modo atual. Mantido pelo nome, que os templates já usam."""
        return _home_do_modo()

    logo_url, contexto_nome, _ = get_contexto_logo_e_nome(current_user, session)
    from utils.push_notifications import VAPID_PUBLIC_KEY
    return dict(
        tem_multiplos_modos=tem_multiplos_modos,
        modos_disponiveis=modos_disponiveis,
        modo_atual_nome=modo_atual_nome,
        get_back_url_default=get_back_url_default,
        contexto_logo_url=logo_url,
        contexto_nome=contexto_nome,
        current_year=datetime.now().year,
        layout_embed=layout_embed,
        vapid_public_key=VAPID_PUBLIC_KEY,
    )


# ============================================================
# 🔹 Context processor: shell (lateral, escopo e item ativo do menu)
# ============================================================

# Mapa blueprint → chave do menu. Existe para não precisar escrever
# `{% set menu_ativo = '...' %}` nas ~180 telas: na esmagadora maioria o
# blueprint já identifica sozinho onde o usuário está. A tela sobrescreve
# quando o blueprint atende mais de um item da lateral.
MENU_POR_BLUEPRINT = {
    "academia": "gerenciamento",
    "alunos": "alunos",
    "aniversariante_live": "aniversariantes",
    "associacao": "gerenciamento",
    "cadastros": "cadastros",
    "calendario": "calendario",
    "competicoes": "competicoes",
    "configuracoes": "configuracoes",
    "eventos_competicoes": "eventos",
    "federacao": "gerenciamento",
    "financeiro": "financeiro",
    "formularios": "formularios",
    "painel": "gerenciamento",
    "painel_aluno": "gerenciamento",
    "painel_responsavel": "gerenciamento",
    "precadastro": "precadastro",
    "presencas": "presencas",
    "professor": "gerenciamento",
    "professores": "professores",
    "solicitacoes": "solicitacoes",
    "turmas": "turmas",
    "usuarios": "usuarios",
    "visitante": "gerenciamento",
    "zempo": "zempo",
}


def _home_do_modo():
    """Tela inicial do modo de acesso corrente.

    Estava aninhada dentro do context processor e por isso não dava para
    reaproveitar em `url_voltar`. Mesmo conteúdo, agora no nível do módulo.
    """
    from flask_login import current_user
    from flask import session

    if not getattr(current_user, "is_authenticated", False):
        return url_for("auth.login")
    destinos = {
        "admin": "painel.gerenciamento_admin",
        "federacao": "federacao.gerenciamento_federacao",
        "associacao": "associacao.gerenciamento_associacao",
        "academia": "academia.painel_academia",
        "professor": "professor.painel_professor",
        "aluno": "painel_aluno.meu_perfil",
        "responsavel": "painel_responsavel.meu_perfil",
        "visitante": "visitante.painel",
    }
    return url_for(destinos.get(session.get("modo_painel") or "", "painel.home"))


@app.template_global()
def url_voltar(explicito=None):
    """Para onde o botão "Voltar" deve levar, na ordem que faz sentido.

    Antes o padrão era sempre a home do modo: sair de "cadastrar turma" caía
    no painel da academia em vez de devolver para a lista de turmas. Com a
    lateral fixa isso fica pior — o botão parece navegar para trás e na
    verdade chuta o usuário para o começo.

    A ordem:
      1. `?next=` da URL — intenção declarada por quem trouxe o usuário até
         aqui (aceito só se for caminho interno, para não virar redirecionador
         aberto);
      2. o destino que a tela passou, SE ele for mais específico que a home do
         modo. Muitas views montam `back_url` como
         "?next= ou referrer ou painel", e o terceiro braço é justamente o
         destino errado que queremos evitar;
      3. o item da barra lateral a que esta tela pertence — o "pai" natural
         dela (cadastrar turma -> Turmas, editar usuário -> Usuários);
      4. a home do modo, como último recurso.
    """
    from flask import has_request_context, request, g
    from flask_login import current_user

    if not has_request_context():
        return explicito or "/"

    def _caminho(u):
        return (u or "").split("?")[0].rstrip("/") or "/"

    # 1. ?next= interno
    proximo = (request.args.get("next") or "").strip()
    if proximo.startswith("/") and not proximo.startswith("//"):
        return proximo

    home = _home_do_modo()

    # 2. destino explícito, se disser algo além da home do modo
    if explicito and _caminho(explicito) != _caminho(home):
        return explicito

    # 3. o item da lateral correspondente a esta tela
    try:
        if getattr(current_user, "is_authenticated", False):
            chave = MENU_POR_BLUEPRINT.get(request.blueprint or "")
            ctx = getattr(g, "_shell_ctx", None) or {}
            aqui = _caminho(request.path)
            for _rotulo, itens in (ctx.get("menu_grupos") or []):
                for item in itens:
                    # Não devolve a própria tela como destino de "voltar":
                    # numa tela de lista o pai é a home do modo, não ela mesma.
                    if item.chave == chave and _caminho(item.href) != aqui:
                        return item.href
    except Exception:
        pass

    return explicito or home


@app.context_processor
def injetar_shell():
    """Monta o que a barra lateral precisa, em qualquer modo de acesso.

    Substitui o antigo `injetar_contexto_academia`, que devolvia {} fora do
    modo academia — motivo pelo qual o shell só servia a um modo. Agora:

      * `modo_shell`   — modo de acesso corrente;
      * `menu_grupos`  — a lateral já resolvida por utils.menu;
      * `menu_ativo`   — deduzido do blueprint (a tela pode sobrescrever);
      * `academia`, `academias`, `academia_id` — escopo, para os modos que
        trabalham dentro de uma academia.

    O que a view passa no render_template continua tendo prioridade sobre o
    que sai daqui.
    """
    from flask import has_request_context, session, g, request
    from flask_login import current_user

    if not has_request_context():
        return {}
    if not getattr(current_user, "is_authenticated", False):
        return {}

    cache = getattr(g, "_shell_ctx", None)
    if cache is not None:
        return dict(cache)

    from utils.contexto_logo import _modo_efetivo
    modo = session.get("modo_painel") or _modo_efetivo(current_user) or "academia"

    ctx = {"academia": None, "academias": [], "academia_id": None}

    # O escopo de academia só é consultado por quem trabalha dentro de uma —
    # para aluno, responsável e visitante seria consulta jogada fora.
    if modo in ("academia", "professor"):
        try:
            from blueprints.academia.routes import _get_academia_gerenciamento
            academia_id, academias = _get_academia_gerenciamento()
            ctx["academia_id"] = academia_id
            ctx["academias"] = academias
            ctx["academia"] = next(
                (a for a in academias if a.get("id") == academia_id), None)
        except Exception as e:
            app.logger.info("Escopo de academia indisponível (%s)", e)

    try:
        from utils.menu import menu_do_modo
        menu_grupos = menu_do_modo(modo, ctx)
    except Exception as e:
        # Lateral vazia é ruim; página em erro 500 é pior.
        app.logger.warning("Menu lateral indisponível (%s)", e)
        menu_grupos = []

    ctx["modo_shell"] = modo
    ctx["menu_grupos"] = menu_grupos
    ctx["menu_ativo"] = MENU_POR_BLUEPRINT.get(request.blueprint or "", "")

    g._shell_ctx = ctx
    return dict(ctx)


# ============================================================
# 🔹 Filtro Jinja: data em formato BR (dd/mm/yyyy)
# ============================================================
def _formatar_data_br(valor):
    """Converte date/datetime/string para dd/mm/yyyy. Retorna '' se inválido."""
    if valor is None:
        return ""
    from datetime import datetime, date
    if isinstance(valor, (date, datetime)):
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, str):
        valor = (valor or "").strip()[:10]
        if not valor:
            return ""
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                d = datetime.strptime(valor, fmt)
                return d.strftime("%d/%m/%Y")
            except ValueError:
                continue
    return str(valor) if valor else ""


@app.template_filter("data_br")
def filtro_data_br(valor):
    return _formatar_data_br(valor)


@app.template_filter("status_aula_exp")
def filtro_status_aula_exp(aula):
    """Status de uma aula experimental:
    - 'presente': presença foi registrada;
    - 'agendada': o dia da aula ainda não passou (não pode ser falta antes);
    - 'falta': o dia da aula já passou e não houve presença.
    """
    from datetime import date as _date, datetime as _dt
    if not aula or not hasattr(aula, "get"):
        return "agendada"
    if aula.get("presente"):
        return "presente"
    da = aula.get("data_aula")
    if da is None:
        return "agendada"
    if isinstance(da, str):
        try:
            da = _dt.strptime(da[:10], "%Y-%m-%d").date()
        except Exception:
            return "agendada"
    elif isinstance(da, _dt):
        da = da.date()
    try:
        # Só é falta DEPOIS do dia da aula (no dia ou antes = ainda agendada)
        if da >= _date.today():
            return "agendada"
    except Exception:
        return "agendada"
    return "falta"


@app.template_filter("nl2br")
def filtro_nl2br(valor):
    """Converte quebras de linha em <br> — escapa HTML antes para evitar XSS."""
    from markupsafe import escape, Markup
    if not valor:
        return Markup("")
    return Markup(escape(str(valor)).replace("\n", Markup("<br>")))


@app.template_filter("hora_fmt")
def filtro_hora_fmt(valor):
    """Formata hora para HH:MM (aceita time, datetime, timedelta, string)."""
    if valor is None:
        return ""
    if hasattr(valor, "strftime"):
        return valor.strftime("%H:%M")
    if hasattr(valor, "total_seconds"):  # timedelta
        s = int(valor.total_seconds())
        h, m = divmod(s // 60, 60)
        return f"{h:02d}:{m:02d}"
    s = str(valor)
    if len(s) >= 5 and s[2] in (":", "."):
        return s[:5].replace(".", ":")
    return s


@app.template_filter("moeda_br")
def filtro_moeda_br(valor):
    """Formata valor no padrão brasileiro: 1234.5 -> '1.234,50'.

    Sem o 'R$' — quem chama decide se o símbolo entra, para não duplicar em
    telas que já têm a coluna marcada como monetária.
    """
    try:
        n = float(valor or 0)
    except (TypeError, ValueError):
        return "0,00"
    return f"{n:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


@app.template_filter("telefone_br")
def filtro_telefone_br(valor):
    """Formata telefone: (11) 99999-9999 ou (11) 3333-3333."""
    if not valor:
        return "-"
    dig = "".join(filter(str.isdigit, str(valor)))
    if len(dig) == 11 and dig[2] == "9":
        return f"({dig[:2]}) {dig[2:7]}-{dig[7:]}"
    if len(dig) == 10:
        return f"({dig[:2]}) {dig[2:6]}-{dig[6:]}"
    return valor


# ============================================================
# 🔹 Rota padrão
# ============================================================
@app.route("/")
def index():
    return redirect(url_for("auth.login"))


# ============================================================
# 🔹 Registro dos Blueprints
# ============================================================
app.register_blueprint(auth_bp)         # Login / Logout
app.register_blueprint(painel_bp)       # Painel principal
app.register_blueprint(federacao_bp)    # Gestão da Federação
app.register_blueprint(associacao_bp)   # Gestão da Associação
app.register_blueprint(academia_bp)     # Gestão da Academia
app.register_blueprint(aniversario_mensagens_bp)
app.register_blueprint(bp_aniversariante_live)  # Modo aniversariante estilo live (SPA + JSON)

app.register_blueprint(bp_alunos)       # CRUD alunos
app.register_blueprint(bp_painel_aluno) # Painel do aluno
app.register_blueprint(bp_painel_responsavel) # Painel do responsável

app.register_blueprint(cadastros_bp)    # Hub de Cadastros
app.register_blueprint(bp_usuarios)     # Usuários (lista/cadastro/editar/excluir)
app.register_blueprint(bp_turmas)       # Turmas (CRUD)
app.register_blueprint(bp_presencas)    # Presenças (registro, ata, histórico)
app.register_blueprint(bp_professores)  # Professores (CRUD por academia)
app.register_blueprint(bp_professor)    # Painel Professor (presença, relatório, histórico)
app.register_blueprint(bp_configuracoes)  # Configurações (admin: modalidades)
app.register_blueprint(bp_financeiro)   # Financeiro (dashboard, descontos, mensalidades, receitas, despesas)
app.register_blueprint(bp_financeiro_painel)  # Painel Financeiro (layout próprio, 7 telas)
app.register_blueprint(bp_link_pagamento)     # /p/<token> — link curto de pagamento
app.register_blueprint(bp_precadastro)   # Pré-cadastro (por academia)
app.register_blueprint(bp_solicitacoes)  # Aprovar solicitações (visita em academia)
app.register_blueprint(bp_calendario)    # Calendário hierárquico (eventos, feriados, turmas)
app.register_blueprint(bp_formularios)   # Formulários (federação/associação — campos do aluno)
app.register_blueprint(bp_eventos_competicoes)  # Eventos e Competições (inscrições com formulário)
app.register_blueprint(bp_competicoes)  # Competições — inscrições, categorias, súmulas, placar, resultados
app.register_blueprint(bp_externo)  # Acesso externo — sem login (inscrições, categorias, súmulas, placar)
app.register_blueprint(bp_visitante)     # Visitante (aulas experimentais)
app.register_blueprint(bp_notificacoes)  # Web Push Notifications
app.register_blueprint(bp_zempo)        # Zempo/CBJ — solicitar, migrar e sincronizar atletas
app.register_blueprint(bp_zempo_publico)  # Zempo/CBJ — formulário público do aluno (sem login)

try:
    import pywebpush  # noqa: F401 — dependência opcional em runtime antigo; requirements.txt inclui.
except ImportError:
    app.logger.warning(
        "Web Push: pywebpush não importa neste processo. Interpretador: %s. "
        "Instale no MESMO Python: %s -m pip install pywebpush (em Debian/PEP 668 acrescente --break-system-packages) "
        "ou use o ambiente virtual: %s/.venv/bin/python -m pip install -r requirements.txt",
        sys.executable,
        sys.executable,
        os.path.dirname(os.path.abspath(__file__)),
    )


# ============================================================
# 🔹 WebSocket Handlers (Placar de Judô)
# ============================================================
@socketio.on("join_luta")
def on_join_luta(data):
    """Cliente entra na sala da luta para receber atualizações."""
    from flask_socketio import join_room, emit
    luta_id = data.get("luta_id")
    if luta_id:
        join_room(f"luta_{luta_id}")
        emit("joined", {"luta_id": luta_id})


@socketio.on("leave_luta")
def on_leave_luta(data):
    """Cliente sai da sala da luta."""
    from flask_socketio import leave_room
    luta_id = data.get("luta_id")
    if luta_id:
        leave_room(f"luta_{luta_id}")


@socketio.on("join_evento_placar")
def on_join_evento_placar(data):
    """Monitor por competição: recebe troca de luta ativa na área."""
    from flask_socketio import join_room, emit

    evento_id = data.get("evento_id")
    if evento_id is not None:
        join_room(f"evento_{evento_id}")
        emit("joined_evento_placar", {"evento_id": evento_id})


@socketio.on("join_placar_area")
def on_join_placar_area(data):
    """Monitor por área: mesma TV para todas as lutas daquela área."""
    from flask_socketio import join_room, emit

    evento_id = data.get("evento_id")
    area_num = data.get("area_num")
    if evento_id is None or area_num is None:
        return
    try:
        eid = int(evento_id)
        an = int(area_num)
    except (TypeError, ValueError):
        return
    if an < 1:
        return
    room = f"placar_area_{eid}_{an}"
    join_room(room)
    emit("joined_placar_area", {"evento_id": eid, "area_num": an})


# ============================================================
# 🔹 Sistema de Broadcast Periódico (Placar de Judô)
# ============================================================
import threading
import time

_lutas_ativas = {}  # {luta_id: True/False} - controla quais lutas estão ativas
_broadcast_thread = None
_broadcast_lock = threading.Lock()

def broadcast_periodico_lutas():
    """
    Thread que faz broadcast periódico do ESTADO COMPLETO de todas as lutas ativas.
    Backend é a ÚNICA fonte de verdade - envia estado completo calculado a cada segundo.
    """
    from blueprints.eventos_competicoes.routes import (
        obter_estado_luta_completo,
        get_socketio,
        aplicar_fim_de_tempo,
        aplicar_osaekomi_yuko,
        aplicar_osaekomi_wazaari,
        aplicar_osaekomi_ippon,
    )

    while True:
        try:
            time.sleep(0.5)  # 500ms - atualização mais suave, evita travamento visual

            # Buscar lutas ativas do registry do blueprint
            from blueprints.eventos_competicoes.routes import _lutas_ativas_registry
            with _broadcast_lock:
                lutas_ativas = list(_lutas_ativas_registry.keys())

            # Log apenas a cada 10 segundos para não poluir
            if not hasattr(broadcast_periodico_lutas, '_last_log'):
                broadcast_periodico_lutas._last_log = 0
            agora_log = time.time()
            if agora_log - broadcast_periodico_lutas._last_log > 10:
                if lutas_ativas:
                    print(f"📡 Broadcast ativo: {len(lutas_ativas)} luta(s): {lutas_ativas}")
                broadcast_periodico_lutas._last_log = agora_log

            for luta_id in lutas_ativas:
                try:
                    with app.app_context():
                        luta = obter_estado_luta_completo(luta_id)
                        if luta:
                            status = luta.get("status", "aguardando")
                            tempo_restante = luta.get("tempo_restante_segundos", 0)

                            if luta.get("osaekomi_ativo") and (status == "em_andamento" or (status == "pausada" and luta.get("golden_score_ativado"))):
                                elapsed = luta.get("osaekomi_elapsed_seconds", 0)
                                if elapsed >= 20:
                                    aplicar_osaekomi_ippon(luta_id)
                                    luta = obter_estado_luta_completo(luta_id) or luta
                                    status = luta.get("status", status)
                                elif elapsed >= 15 and not luta.get("osaekomi_wazaari_concedido"):
                                    aplicar_osaekomi_wazaari(luta_id)
                                    luta = obter_estado_luta_completo(luta_id) or luta
                                elif elapsed >= 10 and not luta.get("osaekomi_yuko_concedido"):
                                    aplicar_osaekomi_yuko(luta_id)
                                    luta = obter_estado_luta_completo(luta_id) or luta

                            tempo_restante_int = int(tempo_restante) if tempo_restante is not None else 300
                            if status == "em_andamento" and tempo_restante_int <= 0 and not luta.get("golden_score_ativado"):
                                luta = aplicar_fim_de_tempo(luta_id) or luta
                                status = luta.get("status", status)
                                tempo_restante = luta.get("tempo_restante_segundos", 0)
                                if luta.get("golden_score_ativado"):
                                    luta = obter_estado_luta_completo(luta_id) or luta

                            golden_score_ativado = luta.get("golden_score_ativado", False)
                            if status in ["em_andamento", "finalizada"] or (status == "pausada" and golden_score_ativado):
                                socketio_instance = get_socketio()
                                if socketio_instance:
                                    try:
                                        from datetime import datetime
                                        luta_serializada = dict(luta)
                                        for key, value in luta_serializada.items():
                                            if isinstance(value, datetime):
                                                luta_serializada[key] = value.isoformat() if value else None
                                        socketio_instance.emit("placar_atualizado", luta_serializada, room=f"luta_{luta_id}", namespace="/")
                                        agora_log = time.time()
                                        if not hasattr(broadcast_periodico_lutas, '_last_emit_log'):
                                            broadcast_periodico_lutas._last_emit_log = {}
                                        if luta_id not in broadcast_periodico_lutas._last_emit_log:
                                            broadcast_periodico_lutas._last_emit_log[luta_id] = 0
                                        if agora_log - broadcast_periodico_lutas._last_emit_log[luta_id] > 5:
                                            print(f"✅ Broadcast luta {luta_id}: tempo={tempo_restante}s, status={status}")
                                            broadcast_periodico_lutas._last_emit_log[luta_id] = agora_log
                                    except Exception as emit_error:
                                        print(f"❌ Erro ao emitir para luta {luta_id}: {emit_error}")
                            else:
                                from blueprints.eventos_competicoes.routes import _lutas_ativas_registry
                                with _broadcast_lock:
                                    _lutas_ativas_registry.pop(luta_id, None)
                                print(f"⚠️ Luta {luta_id} removida do broadcast (status={status})")
                except Exception as e:
                    print(f"❌ Erro ao fazer broadcast da luta {luta_id}: {e}")
        except Exception as e:
            print(f"Erro no broadcast periódico: {e}")

def iniciar_broadcast_periodico():
    """Inicia thread de broadcast periódico."""
    global _broadcast_thread
    if _broadcast_thread is None or not _broadcast_thread.is_alive():
        _broadcast_thread = threading.Thread(target=broadcast_periodico_lutas, daemon=True)
        _broadcast_thread.start()
        print("✅ Sistema de broadcast periódico iniciado (thread ativa)")
    else:
        print("ℹ️ Broadcast periódico já está rodando")


# ============================================================
# 🔹 Execução (apenas desenvolvimento local)
# ============================================================
# Em produção use: .venv/bin/gunicorn -c gunicorn.conf.py wsgi:app
# (systemd: deploy/unimaster.service). Não exponha Flask diretamente na Internet.
if __name__ == "__main__":
    _dev = os.environ.get("UNIMASTER_USE_DEV_SERVER", "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    if not _dev:
        print(
            "Este modo (python app.py) é só para desenvolvimento local.\n"
            "Para ativar: export UNIMASTER_USE_DEV_SERVER=1\n\n"
            "Produção: .venv/bin/gunicorn -c gunicorn.conf.py wsgi:app\n"
            "           (ver deploy/unimaster.service e deploy/PRODUCAO.md)",
            file=sys.stderr,
        )
        sys.exit(2)

    port = int(os.environ.get("PORT", 5000))
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"⚠️  Porta inválida: {sys.argv[1]}. Usando porta padrão: {port}")

    host = os.environ.get("HOST", "0.0.0.0")
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "localhost"

    print("=" * 60)
    print("🚀 Servidor de desenvolvimento (UNIMASTER_USE_DEV_SERVER=1)")
    print(f"📡 Porta: {port} | Host: {host}")
    print("-" * 60)
    print(f"🔗 http://localhost:{port}")
    if host == "0.0.0.0":
        print(f"🔗 http://{local_ip}:{port}")
    print("=" * 60)

    iniciar_broadcast_periodico()
    socketio.run(app, host=host, port=port, debug=debug)
