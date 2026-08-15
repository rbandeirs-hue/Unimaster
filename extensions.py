"""
Extensões Flask inicializadas sem o app (padrão Application Factory).
Importar daqui para evitar dependência circular entre app.py e blueprints.
"""
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect()
