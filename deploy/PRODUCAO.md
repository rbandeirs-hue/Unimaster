# Unimaster — produção (Ubuntu/Debian)

Arquitetura: **Nginx** → **Gunicorn `127.0.0.1:8000`** → **Flask** (`wsgi:app`).

Ambiente virtual obrigatório: **`.venv`** (a pasta `venv` é removida pelo script de preparação).

## 1. Um comando (prepara `.venv`, dependências e remove `venv` antigo)

```bash
cd /var/www/Unimaster
chmod +x deploy/subir.sh
./deploy/subir.sh
# ou, para já ajustar dono de logs/uploads: sudo ./deploy/subir.sh
```

Alternativa só para renomear `venv`→`.venv` quando **não** existe `.venv`: `deploy/migrar_venv_para_dotvenv.sh`.

**Antes do primeiro `systemctl start`**, o Gunicorn (utilizador `www-data`) tem de poder escrever em `logs/`:

```bash
sudo mkdir -p /var/www/Unimaster/logs
sudo chown -R www-data:www-data /var/www/Unimaster/logs /var/www/Unimaster/static/uploads
```

## 2. Systemd (Gunicorn)

```bash
sudo cp /var/www/Unimaster/deploy/unimaster.service /etc/systemd/system/unimaster.service
sudo systemctl daemon-reload
sudo systemctl enable unimaster
sudo systemctl restart unimaster
sudo systemctl status unimaster
```

Logs da app: `logs/access.log` e `logs/error.log` (relativos a `WorkingDirectory`).

## 3. Nginx

**Domínio com HTTPS (ex.: rmservicosnet.com.br)** — use o ficheiro com SSL e proxy na **8000**:

```bash
sudo cp /var/www/Unimaster/deploy/nginx-unimaster-letsencrypt.conf /etc/nginx/sites-available/unimaster
sudo ln -sf /etc/nginx/sites-available/unimaster /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

**Só HTTP / teste local** (sem TLS): `deploy/nginx-unimaster.conf`.  
Obter certificado pela primeira vez: `deploy/nginx-http-acme.conf` e `COMO_ACEITAR_CERTIFICADO.md` / `CONFIGURAR_SSL.md`.

## 4. Desenvolvimento local (opcional)

```bash
export UNIMASTER_USE_DEV_SERVER=1
.venv/bin/python app.py
```

## Comandos úteis

```bash
sudo systemctl restart unimaster
sudo journalctl -u unimaster -f
tail -f /var/www/Unimaster/logs/error.log
```
