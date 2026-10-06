#!/usr/bin/env python3
"""
Saúde das sessões de criptografia do WhatsApp — checagem diária.

O sintoma: mensagem enviada pelo sistema aparece como "Aguardando mensagem" no
celular / WhatsApp Web da PRÓPRIA academia. A causa: a sessão de criptografia
entre o serviço (um aparelho conectado da conta) e os outros aparelhos da mesma
conta corrompe, e cada mensagem trocada com eles vira "Bad MAC" no log. Reiniciar
não conserta — a sessão corrompida está gravada em arquivo e volta igual.

O conserto é descartar só essas sessões (session-<lid da academia>.*.json): o
serviço refaz na próxima mensagem. O login (creds.json) e as sessões com alunos
e responsáveis não são tocados, e não é preciso ler QR Code de novo.

Este script conta, nas últimas 24h do journal, os erros de decifrar ligados aos
aparelhos de cada academia e, acima do limite, faz o descarte — com cópia em
whatsapp-service/backup_sessoes_<data>/. Roda dentro do reinício das 02:00
(unimaster-whatsapp-restart.service), com o serviço PARADO.

Uso:
  python3 scripts/whatsapp_saude_sessoes.py            # só mostra (não mexe em nada)
  python3 scripts/whatsapp_saude_sessoes.py --limpar   # descarta o que passou do limite
"""
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1] / "whatsapp-service"
AUTH = RAIZ / "auth"
LOG = Path(__file__).resolve().parents[1] / "logs" / "whatsapp_saude.log"
SERVICO = "unimaster-whatsapp"

# Erros de decifrar com os aparelhos da própria academia, em 24h, a partir dos
# quais a sessão é dada como corrompida. Em operação normal o número é zero;
# o caso que motivou o script tinha centenas por dia.
LIMITE = 30
GUARDAR_BACKUPS_DIAS = 30

# A pilha de cada "Bad MAC" traz o aparelho que mandou: "<lid>.<aparelho>".
_PILHA = re.compile(r"at (?:async )?(\d{6,})\.(\d+) \[as awaitable\]")


def registrar(msg):
    linha = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(linha)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except OSError:
        pass


def lid_da_academia(pasta):
    """Identificador (lid) da conta da academia, sem o aparelho: '110621899153519'."""
    try:
        creds = json.loads((pasta / "creds.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    lid = ((creds.get("me") or {}).get("lid") or "")
    return lid.split(":")[0].split("@")[0] or None


def ultima_limpeza(academia):
    """Momento (epoch) da última limpeza das sessões desta academia, ou 0."""
    momentos = [p.stat().st_mtime for p in RAIZ.glob(f"backup_sessoes_*/{academia}") if p.is_dir()]
    return max(momentos) if momentos else 0


def erros_por_lid(desde):
    """{lid: n} de erros de decifrar no journal do serviço, nas últimas 24h e
    só DEPOIS da última limpeza de cada lid (`desde` = {lid: epoch}) — senão
    os erros de antes da limpeza fariam descartar as sessões novas e boas."""
    try:
        saida = subprocess.run(
            ["journalctl", "-u", SERVICO, "--since", "24 hours ago", "--no-pager", "-o", "short-unix"],
            capture_output=True, text=True, timeout=120).stdout
    except (OSError, subprocess.SubprocessError) as e:
        registrar(f"não foi possível ler o journal: {e}")
        return {}
    contagem = {}
    for linha in saida.splitlines():
        m = _PILHA.search(linha)
        if not m:
            continue
        try:
            quando = float(linha.split(" ", 1)[0])
        except ValueError:
            continue
        if quando <= desde.get(m.group(1), 0):
            continue
        contagem[m.group(1)] = contagem.get(m.group(1), 0) + 1
    return contagem


def servico_ativo():
    return subprocess.run(["systemctl", "is-active", "--quiet", SERVICO]).returncode == 0


def limpar_backups_antigos():
    limite = time.time() - GUARDAR_BACKUPS_DIAS * 86400
    for pasta in RAIZ.glob("backup_sessoes_*"):
        try:
            if pasta.is_dir() and pasta.stat().st_mtime < limite:
                shutil.rmtree(pasta)
                registrar(f"backup antigo removido: {pasta.name}")
        except OSError:
            pass


def main():
    limpar = "--limpar" in sys.argv
    pastas = sorted(p for p in AUTH.iterdir() if p.is_dir()) if AUTH.is_dir() else []
    lids = {p.name: lid_da_academia(p) for p in pastas}
    erros = erros_por_lid({lid: ultima_limpeza(nome) for nome, lid in lids.items() if lid})
    a_limpar = []
    for pasta in pastas:
        lid = lids.get(pasta.name)
        if not lid:
            continue
        n = erros.get(lid, 0)
        arquivos = sorted(pasta.glob(f"session-{lid}.*.json"))
        estado = "CORROMPIDA" if n >= LIMITE else "ok"
        registrar(f"academia {pasta.name}: {n} erro(s) com os aparelhos da academia em 24h "
                  f"({len(arquivos)} sessão(ões)) → {estado}")
        if n >= LIMITE and arquivos:
            a_limpar.append((pasta, arquivos))

    if not a_limpar:
        registrar("nada a limpar.")
    elif not limpar:
        registrar("simulação: rode com --limpar para descartar as sessões acima.")
    elif servico_ativo():
        # Com o serviço no ar ele regravaria as sessões em cima da limpeza.
        registrar(f"o serviço {SERVICO} está ativo: pare-o antes de limpar. Nada foi feito.")
    else:
        destino = RAIZ / f"backup_sessoes_{datetime.now():%Y%m%d_%H%M}"
        for pasta, arquivos in a_limpar:
            alvo = destino / pasta.name
            alvo.mkdir(parents=True, exist_ok=True)
            for arq in arquivos:
                shutil.move(str(arq), str(alvo / arq.name))
            shutil.chown(destino, "www-data", "www-data")
            shutil.chown(alvo, "www-data", "www-data")
            registrar(f"academia {pasta.name}: {len(arquivos)} sessão(ões) com os aparelhos da "
                      f"academia descartada(s); cópia em {alvo}")
    if limpar:
        limpar_backups_antigos()


if __name__ == "__main__":
    main()
