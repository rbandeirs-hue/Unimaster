# 📦 Guia de Instalação de Dependências - Unimaster

**Produção (Linux):** `deploy/subir.sh` + `deploy/PRODUCAO.md` (Gunicorn, systemd, Nginx, `.venv`).

## 🚀 Instalação Rápida

### 1. Criar ambiente virtual (obrigatório: nome `.venv`)
```bash
# Linux/Mac (produção e desenvolvimento)
python3 -m venv .venv
source .venv/bin/activate

# Windows
python -m venv .venv
.venv\Scripts\activate
```

### 2. Instalar dependências
```bash
pip install -r requirements.txt
```

---

## 📋 Dependências Principais

### Flask (3.0.0)
- **Uso**: Framework web principal
- **Import**: `from flask import Flask, render_template, request, ...`
- **Descrição**: Framework web leve e flexível para Python

### Flask-Login (0.6.3)
- **Uso**: Gerenciamento de sessões e autenticação
- **Import**: `from flask_login import login_required, current_user, login_user`
- **Descrição**: Extensão do Flask para gerenciar usuários logados

### mysql-connector-python (8.2.0)
- **Uso**: Conexão com banco de dados MySQL
- **Import**: `import mysql.connector`
- **Descrição**: Driver oficial MySQL para Python
- **Arquivo**: `config.py`

### python-dateutil (2.8.2)
- **Uso**: Manipulação avançada de datas
- **Import**: `from dateutil.relativedelta import relativedelta`
- **Descrição**: Extensões para trabalhar com datas e intervalos
- **Arquivo**: `blueprints/aluno/alunos.py`

### Werkzeug (3.0.1)
- **Uso**: Utilitários de segurança (hash de senhas)
- **Import**: `from werkzeug.security import check_password_hash, generate_password_hash`
- **Descrição**: Biblioteca de utilitários WSGI (vem com Flask, mas usado explicitamente)
- **Arquivos**: `blueprints/auth/routes.py`, `blueprints/usuarios/routes.py`

---

## 🔍 Verificação de Instalação

### Verificar se todas as dependências estão instaladas:
```bash
pip list
```

Você deve ver:
```
Flask                   3.0.0
Flask-Login             0.6.3
mysql-connector-python  8.2.0
python-dateutil         2.8.2
Werkzeug                3.0.1
```

### Testar importações:
```python
python -c "import flask; import flask_login; import mysql.connector; import dateutil; import werkzeug; print('Todas as dependências OK!')"
```

---

## 🛠️ Instalação Manual (sem requirements.txt)

Se preferir instalar manualmente:

```bash
pip install Flask==3.0.0
pip install Flask-Login==0.6.3
pip install mysql-connector-python==8.2.0
pip install python-dateutil==2.8.2
```

---

## ⚠️ Solução de Problemas

### Erro ao instalar mysql-connector-python
```bash
# Windows - pode precisar de Visual C++ Build Tools
# Ou usar versão alternativa:
pip install mysql-connector-python --no-cache-dir

# Alternativa: usar PyMySQL
pip install PyMySQL
# E alterar config.py para usar PyMySQL
```

### Erro de versão do Python
- **Requisito**: Python 3.8 ou superior
- **Verificar versão**: `python --version`
- **Atualizar**: Baixar de https://www.python.org/

### Erro de permissões
```bash
# Linux/Mac - usar sudo (não recomendado)
sudo pip install -r requirements.txt

# Melhor: usar --user
pip install --user -r requirements.txt
```

---

## 📝 Bibliotecas Padrão (não precisam instalação)

Estas bibliotecas já vêm com Python:
- `datetime` - Manipulação de datas básica
- `os` - Operações do sistema operacional
- `base64` - Codificação base64
- `unicodedata` - Normalização de caracteres Unicode
- `json` - Manipulação de JSON
- `hashlib` - Funções de hash

---

## 🔄 Atualização de Dependências

### Verificar versões desatualizadas:
```bash
pip list --outdated
```

### Atualizar todas:
```bash
pip install --upgrade -r requirements.txt
```

### Atualizar uma específica:
```bash
pip install --upgrade Flask
```

---

## 📦 Estrutura de Arquivos

```
Judo/
├── requirements.txt          # Dependências de produção
├── requirements-dev.txt     # Dependências de desenvolvimento (opcional)
├── INSTALACAO_DEPENDENCIAS.md  # Este arquivo
└── ...
```

---

## ✅ Checklist de Instalação

- [ ] Python 3.8+ instalado
- [ ] Ambiente virtual criado e ativado
- [ ] `requirements.txt` instalado com sucesso
- [ ] Todas as importações funcionando
- [ ] Banco de dados MySQL configurado
- [ ] Aplicação rodando sem erros

---

## 🎯 Próximos Passos

Após instalar as dependências:

1. Configurar banco de dados em `config.py`
2. Executar migrações SQL (se necessário)
3. Desenvolvimento local: `export UNIMASTER_USE_DEV_SERVER=1 && .venv/bin/python app.py` (ou ver `deploy/PRODUCAO.md`)
4. Produção: Gunicorn + systemd + Nginx — `deploy/unimaster.service`, `gunicorn.conf.py`, `wsgi:app`
