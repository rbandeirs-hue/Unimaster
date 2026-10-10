"""
Domínio próprio e marca da academia (MM-15).

A academia aponta o domínio dela (registro A) para este servidor; o script
scripts/dominios_academias.py emite o certificado e cria o site no nginx. A
partir daí toda requisição chega aqui com o Host da academia, e:

  - a tela de entrada e o shell mostram o nome, a logo e a cor dela;
  - só entra quem é da academia (equipe, aluno, responsável, professor,
    visitante) ou o admin — os demais são mandados para o endereço principal.

Tudo aqui tolera o banco sem a MM-15: sem as colunas, nenhum host é de
academia e o sistema segue como Unimaster.
"""
import os
import re
import time

from config import get_db_connection

# Hosts do próprio sistema: nunca podem ser cadastrados como domínio de academia.
HOSTS_DO_SISTEMA = {
    h.strip().lower()
    for h in os.environ.get("UNIMASTER_HOSTS", "rmservicosnet.com.br,localhost,127.0.0.1").split(",")
    if h.strip()
}
IP_DO_SERVIDOR = os.environ.get("UNIMASTER_IP", "177.153.51.151")

COR_PADRAO = "#e4001b"
_COR = re.compile(r"^#[0-9a-fA-F]{6}$")
_ROTULO = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")

# host -> (expira_em, academia|None). Curto: trocar o domínio na tela vale em
# até um minuto nos três workers sem precisar avisar ninguém.
_CACHE = {}
_TTL = 60


class DominioInvalido(ValueError):
    pass


def normalizar(valor):
    """'https://www.JudoClube.com.br/' -> 'judoclube.com.br'. Vazio -> None.
    Levanta DominioInvalido com a mensagem para o gestor."""
    v = (valor or "").strip().lower()
    if not v:
        return None
    v = re.sub(r"^[a-z]+://", "", v).split("/")[0].split("?")[0].split(":")[0].strip(".")
    if v.startswith("www."):
        v = v[4:]
    try:
        v = v.encode("idna").decode("ascii")
    except UnicodeError:
        raise DominioInvalido("domínio com caracteres inválidos.")
    partes = v.split(".")
    if len(v) > 190 or len(partes) < 2 or not all(_ROTULO.match(p) for p in partes) \
            or partes[-1].isdigit():
        raise DominioInvalido("informe só o domínio, por exemplo: minhaacademia.com.br")
    if v in HOSTS_DO_SISTEMA or any(v.endswith("." + h) for h in HOSTS_DO_SISTEMA):
        raise DominioInvalido("esse é o endereço do próprio sistema.")
    return v


def host_da_requisicao(host):
    """Host do pedido sem porta e sem www."""
    h = (host or "").split(":")[0].strip().lower().rstrip(".")
    return h[4:] if h.startswith("www.") else h


def cor_valida(valor):
    v = (valor or "").strip()
    return v.lower() if _COR.match(v) else None


def academia_do_host(host):
    """{id, nome, titulo, texto, cor} da academia dona do host, ou None."""
    h = host_da_requisicao(host)
    if not h or h in HOSTS_DO_SISTEMA:
        return None
    agora = time.time()
    em_cache = _CACHE.get(h)
    if em_cache and em_cache[0] > agora:
        return em_cache[1]
    academia = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("""SELECT id, nome, marca_titulo, marca_texto, marca_cor
                           FROM academias WHERE dominio = %s LIMIT 1""", (h,))
            r = cur.fetchone()
        finally:
            cur.close()
            conn.close()
        if r:
            academia = {
                "id": int(r["id"]),
                "nome": r["nome"],
                "titulo": (r.get("marca_titulo") or "").strip() or r["nome"],
                "texto": (r.get("marca_texto") or "").strip(),
                "cor": cor_valida(r.get("marca_cor")) or COR_PADRAO,
            }
    except Exception:
        # Sem a MM-15 ou banco fora: o host é tratado como o do sistema.
        academia = None
    _CACHE[h] = (agora + _TTL, academia)
    return academia


PASTA_NGINX = "/etc/nginx/sites-enabled"
PREFIXO_SITE = "academia-"  # sites gerados por scripts/dominios_academias.py


def dominios_do_servidor():
    """Hosts que outros sites do nginx já atendem (sem www). Os sites gerados
    para academias ficam de fora: quem decide sobre eles é o banco."""
    hosts = set()
    try:
        nomes = os.listdir(PASTA_NGINX)
    except OSError:
        return hosts
    for nome in nomes:
        if nome.startswith(PREFIXO_SITE):
            continue
        try:
            with open(os.path.join(PASTA_NGINX, nome), encoding="utf-8", errors="ignore") as f:
                texto = f.read()
        except OSError:
            continue
        for bloco in re.findall(r"^\s*server_name\s+([^;]+);", texto, re.M):
            for h in bloco.split():
                h = host_da_requisicao(h)
                if h and h != "_" and "*" not in h:
                    hosts.add(h)
    return hosts | HOSTS_DO_SISTEMA


def esquecer_cache():
    _CACHE.clear()


def usuario_e_da_academia(usuario_id, academia_id):
    """O usuário tem algum vínculo com a academia: equipe, aluno, responsável
    por aluno dela, professor ou visitante."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT 1 FROM usuarios_academias WHERE usuario_id = %s AND academia_id = %s
               UNION ALL
               SELECT 1 FROM alunos a
               WHERE a.usuario_id = %s AND (a.id_academia = %s OR EXISTS (
                     SELECT 1 FROM alunos_academias aa WHERE aa.aluno_id = a.id AND aa.academia_id = %s))
               UNION ALL
               SELECT 1 FROM responsavel_alunos ra JOIN alunos a ON a.id = ra.aluno_id
               WHERE ra.usuario_id = %s AND (a.id_academia = %s OR EXISTS (
                     SELECT 1 FROM alunos_academias aa WHERE aa.aluno_id = a.id AND aa.academia_id = %s))
               UNION ALL
               SELECT 1 FROM professores WHERE usuario_id = %s AND id_academia = %s
               UNION ALL
               SELECT 1 FROM visitantes WHERE usuario_id = %s AND id_academia = %s
               LIMIT 1""",
            (usuario_id, academia_id,
             usuario_id, academia_id, academia_id,
             usuario_id, academia_id, academia_id,
             usuario_id, academia_id,
             usuario_id, academia_id))
        return cur.fetchone() is not None
    finally:
        cur.close()
        conn.close()


def pode_entrar(usuario, academia_id):
    """Admin entra por qualquer domínio (suporte); os demais, só se forem da academia."""
    try:
        if usuario.has_role("admin"):
            return True
    except Exception:
        pass
    return usuario_e_da_academia(int(usuario.id), int(academia_id))
