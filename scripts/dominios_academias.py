#!/usr/bin/env python3
"""
Ativa (e desativa) os domínios próprios das academias — MM-15.

O gestor grava o domínio em Configurações › Domínio e marca e ele fica
'pendente'. A cada 5 minutos (unimaster-dominios.timer, como root) este
script, para cada domínio:

  1. recusa o que outro site do nginx já atende;
  2. confere se o DNS aponta para o servidor (sem isso o Let's Encrypt
     recusaria, e falhas repetidas contam no limite deles);
  3. emite o certificado pelo webroot /var/www/html — a porta 80 do nginx
     já responde o desafio para qualquer host;
  4. grava /etc/nginx/sites-available/academia-<domínio>.conf (proxy para o
     gunicorn), testa com `nginx -t` (desfaz se falhar) e recarrega;
  5. marca 'ativo' — ou 'erro' com o motivo, que o gestor lê na tela.

Domínio removido ou trocado na tela: o site gerado é apagado. O certificado
fica (renovar um que não está em uso não faz mal, e evita reemitir se voltar).

Uso:
  python3 scripts/dominios_academias.py            # só mostra o que faria
  python3 scripts/dominios_academias.py --aplicar
"""
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

from config import get_db_connection  # noqa: E402
from utils import dominio_academia as dom  # noqa: E402

CERTBOT = "/opt/certbot-venv/bin/certbot"  # o /usr/bin/certbot do sistema está quebrado (pyOpenSSL do pip)
WEBROOT = "/var/www/html"
DISPONIVEIS = Path("/etc/nginx/sites-available")
HABILITADOS = Path(dom.PASTA_NGINX)
LOG = ROOT / "logs" / "dominios_academias.log"
ESTADO = ROOT / "logs" / "dominios_academias.json"
# Entre duas tentativas de certificado para o mesmo domínio. O Let's Encrypt
# bloqueia o host depois de 5 falhas em uma hora.
ESPERA_CERTIFICADO = 30 * 60

SITE = """# Gerado por scripts/dominios_academias.py para a academia {academia_id} ({nome}).
# Não edite: é refeito a partir do banco (academias.dominio).
server {{
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name {nomes};

    ssl_certificate /etc/letsencrypt/live/{dominio}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{dominio}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    client_max_body_size 50M;

    # Um endereço só: www vai para o domínio sem www (o cookie de sessão é por host).
    if ($host != {dominio}) {{
        return 301 https://{dominio}$request_uri;
    }}

    location /static/ {{
        alias {raiz}/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }}

    location / {{
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
        proxy_buffering off;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_connect_timeout 120s;
        proxy_send_timeout 120s;
        proxy_read_timeout 120s;
    }}
}}
"""


def registrar(msg):
    linha = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(linha)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except OSError:
        pass


def ler_estado():
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def gravar_estado(estado):
    try:
        ESTADO.write_text(json.dumps(estado, indent=1), encoding="utf-8")
    except OSError:
        pass


def aponta_para_servidor(host):
    try:
        ips = {i[4][0] for i in socket.getaddrinfo(host, 443, socket.AF_INET)}
    except socket.gaierror:
        return False, "não encontrado no DNS"
    if dom.IP_DO_SERVIDOR in ips:
        return True, ""
    return False, "aponta para " + ", ".join(sorted(ips))


def nomes_do_certificado(dominio):
    pem = Path(f"/etc/letsencrypt/live/{dominio}/cert.pem")
    if not pem.exists():
        return set()
    saida = subprocess.run(["openssl", "x509", "-noout", "-ext", "subjectAltName", "-in", str(pem)],
                           capture_output=True, text=True).stdout
    return {p.strip()[4:] for p in saida.replace("\n", ",").split(",") if p.strip().startswith("DNS:")}


def emitir_certificado(nomes):
    cmd = [CERTBOT, "certonly", "--webroot", "-w", WEBROOT, "--non-interactive", "--agree-tos",
           "--keep-until-expiring", "--expand", "--cert-name", nomes[0],
           "--deploy-hook", "systemctl reload nginx"]
    for n in nomes:
        cmd += ["-d", n]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode == 0:
        return ""
    texto = (r.stderr or r.stdout or "").strip().splitlines()
    detalhe = next((l for l in texto if "Detail:" in l or "Error" in l), texto[-1] if texto else "")
    return detalhe.strip()[:200]


def nginx_ok():
    r = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
    return r.returncode == 0, (r.stderr or "").strip().splitlines()[-1:] or [""]


def recarregar_nginx():
    subprocess.run(["systemctl", "reload", "nginx"], check=False)


def arquivo_site(dominio):
    return f"{dom.PREFIXO_SITE}{dominio}.conf"


def remover_site(nome_arquivo):
    for p in (HABILITADOS / nome_arquivo, DISPONIVEIS / nome_arquivo):
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def instalar_site(academia, dominio, nomes):
    """Grava e habilita o site; desfaz se o nginx recusar. Devolve erro ou ''."""
    nome = arquivo_site(dominio)
    conteudo = SITE.format(academia_id=academia["id"], nome=(academia["nome"] or "").replace("\n", " "),
                           nomes=" ".join(nomes), dominio=dominio, raiz=ROOT)
    destino = DISPONIVEIS / nome
    anterior = destino.read_text(encoding="utf-8") if destino.exists() else None
    if anterior == conteudo and (HABILITADOS / nome).exists():
        return ""
    destino.write_text(conteudo, encoding="utf-8")
    link = HABILITADOS / nome
    if not link.exists():
        link.symlink_to(destino)
    ok, msg = nginx_ok()
    if ok:
        recarregar_nginx()
        return ""
    if anterior is not None:
        destino.write_text(anterior, encoding="utf-8")
    else:
        remover_site(nome)
    return "configuração recusada pelo nginx: " + msg[0][:150]


def gravar_status(cur, conn, academia_id, status, erro=None):
    if status == "ativo":
        cur.execute("""UPDATE academias SET dominio_status = 'ativo', dominio_erro = NULL,
                              dominio_ativado_em = COALESCE(dominio_ativado_em, NOW())
                       WHERE id = %s""", (academia_id,))
    else:
        cur.execute("UPDATE academias SET dominio_status = %s, dominio_erro = %s WHERE id = %s",
                    (status, (erro or "")[:255] or None, academia_id))
    conn.commit()


def main():
    aplicar = "--aplicar" in sys.argv
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SHOW COLUMNS FROM academias LIKE 'dominio'")
        if not cur.fetchall():
            print("MM-15 não aplicada: nada a fazer.")
            return
        cur.execute("""SELECT id, nome, dominio, dominio_status FROM academias
                       WHERE dominio IS NOT NULL AND dominio <> ''""")
        academias = cur.fetchall()
        desejados = {arquivo_site(a["dominio"]) for a in academias}

        # Sites de domínios que saíram do banco.
        for p in sorted(DISPONIVEIS.glob(f"{dom.PREFIXO_SITE}*.conf")):
            if p.name not in desejados:
                registrar(f"{p.name}: domínio não está mais cadastrado → remover site")
                if aplicar:
                    remover_site(p.name)
                    recarregar_nginx()

        outros = dom.dominios_do_servidor()
        estado = ler_estado()
        for a in academias:
            dominio = a["dominio"]
            site_no_ar = (HABILITADOS / arquivo_site(dominio)).exists()
            if a["dominio_status"] == "ativo" and site_no_ar:
                continue
            if dominio in outros:
                registrar(f"{dominio} (academia {a['id']}): já atendido por outro site → erro")
                if aplicar:
                    gravar_status(cur, conn, a["id"], "erro", "Esse domínio já é usado por outro site neste servidor.")
                continue
            ok, motivo = aponta_para_servidor(dominio)
            if not ok:
                registrar(f"{dominio} (academia {a['id']}): DNS {motivo}")
                if aplicar:
                    gravar_status(cur, conn, a["id"], "erro",
                                  f"O DNS de {dominio} ainda não aponta para o servidor ({motivo}).")
                continue
            www_ok, _ = aponta_para_servidor("www." + dominio)
            nomes = [dominio] + (["www." + dominio] if www_ok else [])

            if not set(nomes) <= nomes_do_certificado(dominio):
                ultima = estado.get(dominio, 0)
                if time.time() - ultima < ESPERA_CERTIFICADO:
                    registrar(f"{dominio}: aguardando para tentar o certificado de novo")
                    continue
                registrar(f"{dominio} (academia {a['id']}): emitir certificado para {', '.join(nomes)}")
                if not aplicar:
                    continue
                estado[dominio] = time.time()
                gravar_estado(estado)
                erro = emitir_certificado(nomes)
                if erro:
                    registrar(f"{dominio}: certificado falhou — {erro}")
                    gravar_status(cur, conn, a["id"], "erro", f"Não foi possível emitir o certificado: {erro}")
                    continue
                estado.pop(dominio, None)
                gravar_estado(estado)

            registrar(f"{dominio} (academia {a['id']}): instalar site no nginx")
            if not aplicar:
                continue
            erro = instalar_site(a, dominio, nomes)
            if erro:
                registrar(f"{dominio}: {erro}")
                gravar_status(cur, conn, a["id"], "erro", erro)
            else:
                registrar(f"{dominio}: no ar")
                gravar_status(cur, conn, a["id"], "ativo")
        if not academias:
            print("nenhum domínio cadastrado.")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    os.umask(0o022)
    main()
