# ======================================================
# 🔥 User Model com RBAC Real — Versão Final
# ======================================================
from flask_login import UserMixin
from config import get_db_connection


class Usuario(UserMixin):
    # Níveis de acesso derivados de roles
    ACCESS_LEVELS = [
        ("Federação", ["gestor_federacao"]),
        ("Associação", ["gestor_associacao"]),
        ("Academia", ["gestor_academia", "professor"]),
        ("Aluno", ["aluno"]),
        ("Responsável", ["responsavel"]),
    ]

    # ======================================================
    # 🔹 Construtor
    # ======================================================
    def __init__(
        self,
        id,
        nome,
        email,
        senha,
        id_federacao=None,
        id_associacao=None,
        id_academia=None,
        roles=None,
        permissoes=None,
        menus=None,
        foto=None
    ):
        # Dados básicos
        self.id = id
        self.nome = nome
        self.email = email
        self.senha = senha
        self.foto = foto

        # Hierarquia (para federacao, associação e academia)
        self.id_federacao = id_federacao
        self.id_associacao = id_associacao
        self.id_academia = id_academia

        # RBAC
        self.roles = roles or []
        self.permissoes = permissoes or []
        self.menus = menus or []

    # Mapeamento: nomes no código -> equivalentes na tabela roles (DB usa "Administrador", "Gestor Federação", etc.)
    ROLE_ALIASES = {
        "admin": ["admin", "administrador"],
        "gestor_federacao": ["gestor_federacao", "gestor federação", "gestor federacao"],
        "gestor_associacao": ["gestor_associacao", "gestor associação", "gestor associacao"],
        "gestor_academia": ["gestor_academia", "gestor academia"],
        "professor": ["professor"],
        "aluno": ["aluno"],
        "responsavel": ["responsavel", "responsável"],
        "visitante": ["visitante"],
    }

    # ======================================================
    # 🔹 ROLE: Verifica se o usuário possui uma role
    # ======================================================
    def has_role(self, role_name):
        r_lower = role_name.lower().strip()
        roles_lower = [str(r).lower().strip() for r in (self.roles or [])]
        if r_lower in roles_lower:
            return True
        aliases = self.ROLE_ALIASES.get(r_lower, [r_lower])
        for alias in aliases:
            if alias in roles_lower:
                return True
        for role in roles_lower:
            if role.replace(" ", "_") == r_lower:
                return True
            if r_lower.replace("_", " ") == role:
                return True
        return False

    # ======================================================
    # 🔹 PERMISSÃO: Verifica permissões herdadas via role
    # Admin tem acesso total a todas as permissões
    # ======================================================
    def has_permission(self, perm_name):
        if self.has_role("admin"):
            return True
        return perm_name.lower() in [p.lower() for p in self.permissoes]

    # ======================================================
    # 🔹 NÍVEIS DE ACESSO
    # ======================================================
    def has_access_level(self, level_name):
        level = (level_name or "").strip().lower()
        role_set = {r.lower() for r in self.roles}

        if "admin" in role_set or "administrador" in role_set:
            return level in {label.lower() for label, _ in self.ACCESS_LEVELS}

        for label, roles in self.ACCESS_LEVELS:
            if label.lower() == level and role_set.intersection({r.lower() for r in roles}):
                return True

        return False

    @property
    def niveis_acesso(self):
        return self.niveis_acesso_por_roles(self.roles)

    @staticmethod
    def niveis_acesso_por_roles(roles):
        role_set = {r.lower() for r in (roles or [])}

        if "admin" in role_set or "administrador" in role_set:
            return [label for label, _ in Usuario.ACCESS_LEVELS]

        levels = []
        for label, role_names in Usuario.ACCESS_LEVELS:
            if role_set.intersection({r.lower() for r in role_names}):
                levels.append(label)

        return levels

    # ======================================================
    # 🔹 PERFIL (compatibilidade antiga)
    # Retorna uma string baseada nas roles
    # ======================================================
    @property
    def perfil(self):

        # Ordem lógica de privilégio
        if self.has_role("admin"):
            return "admin"

        if self.has_role("gestor_federacao"):
            return "gestor_federacao"

        if self.has_role("gestor_associacao"):
            return "gestor_associacao"

        if self.has_role("gestor_academia"):
            return "gestor_academia"

        if self.has_role("professor"):
            return "professor"

        if self.has_role("aluno"):
            return "aluno"

        if self.has_role("responsavel"):
            return "responsavel"

        if self.has_role("visitante"):
            return "visitante"

        return "desconhecido"

    # ======================================================
    # 🔥 Carregar Roles do usuário
    # ======================================================
    @staticmethod
    def carregar_roles(usuario_id):
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute("""
            SELECT r.nome
            FROM roles r
            JOIN roles_usuario ru ON ru.role_id = r.id
            WHERE ru.usuario_id = %s
        """, (usuario_id,))

        roles = [row["nome"] for row in cur.fetchall()]

        cur.close()
        conn.close()
        return roles

    # ======================================================
    # 🔥 Carregar Permissões baseadas nas roles
    # ======================================================
    @staticmethod
    def carregar_permissoes(usuario_id):
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute("""
            SELECT DISTINCT p.nome
            FROM permissoes p
            JOIN role_permissoes rp ON rp.permissao_id = p.id
            WHERE rp.role_id IN (
                SELECT role_id FROM roles_usuario WHERE usuario_id = %s
            )
        """, (usuario_id,))

        permissoes = [row["nome"] for row in cur.fetchall()]

        cur.close()
        conn.close()
        return permissoes

    # ======================================================
    # 🔥 Carregar Menus liberados via RBAC
    # ======================================================
    @staticmethod
    def carregar_menus(usuario_id):
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        cur.execute("""
            SELECT DISTINCT m.nome, m.rota, m.icone
            FROM menus m
            JOIN menu_roles mr ON mr.menu_id = m.id
            WHERE mr.role_id IN (
                SELECT role_id FROM roles_usuario WHERE usuario_id = %s
            )
            AND m.ativo = 1
            ORDER BY m.ordem
        """, (usuario_id,))

        menus = cur.fetchall()

        cur.close()
        conn.close()
        return menus
