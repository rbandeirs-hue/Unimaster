# ======================================================
# 🔹 models/user.py
# ======================================================

from flask_login import UserMixin

class User(UserMixin):
    """
    Modelo principal de Usuário utilizado pelo Flask-Login.
    Inclui identificação hierárquica para controle de acesso.
    """

    def __init__(self, data):
        # Campos principais
        self.id = data.get('id')
        self.nome = data.get('nome')
        self.email = data.get('email')
        self.senha = data.get('senha')

        # Perfil e nível de acesso
        self.perfil = data.get('perfil')               # ex: admin_federacao, admin_associacao, admin_academia, aluno
        self.nivel = data.get('nivel', '')             # opcional (para lógica extra de controle)

        # Hierarquia (IDs relacionados)
        self.id_federacao = data.get('id_federacao')
        self.id_associacao = data.get('id_associacao')
        self.id_academia = data.get('id_academia')
        self.id_aluno = data.get('id_aluno')

        # Permissões adicionais
        self.is_admin = data.get('is_admin', False)

    def get_id(self):
        """Obrigatório para o Flask-Login"""
        return str(self.id)

    # ======================================================
    # 🔹 Métodos auxiliares para checar permissões
    # ======================================================
    def is_federacao_admin(self):
        return self.perfil in ["admin_federacao"]

    def is_federacao_visualizador(self):
        return self.perfil in ["visualizador_federacao"]

    def is_associacao_admin(self):
        return self.perfil in ["admin_associacao"]

    def is_academia_admin(self):
        return self.perfil in ["admin_academia"]

    def is_instrutor(self):
        return self.perfil in ["instrutor_associacao", "professor"]

    def is_aluno(self):
        return self.perfil == "aluno"

    # ======================================================
    # 🔹 Exemplo útil para logs e debug
    # ======================================================
    def __repr__(self):
        return f"<User {self.id} - {self.nome} ({self.perfil})>"
