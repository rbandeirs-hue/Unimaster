#!/usr/bin/env python3
"""
Backup automático do Unimaster — banco todo dia, arquivos enviados no domingo.

Antes deste script o banco só tinha cópia quando alguém lembrava de fazer à
mão antes de uma migração (a última era de 10/09/2026). Roda pelo
unimaster-backup.timer às 03:30.

  /var/backups/unimaster/auto/banco_AAAAMMDD_HHMM.sql.gz     guarda 30 dias
  /var/backups/unimaster/auto/uploads_AAAAMMDD.tar.gz        domingo; guarda 2

As credenciais vêm do .env do projeto (as mesmas do sistema). Um dump que sai
vazio ou com erro não apaga os antigos — a limpeza só roda depois de um
backup bom.

Uso:  python3 scripts/backup_banco.py [--uploads]   (--uploads força o dos arquivos)
"""
import gzip
import os
import subprocess
import sys
import tarfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINO = Path("/var/backups/unimaster/auto")
LOG = ROOT / "logs" / "backup.log"
DIAS_BANCO = 30
COPIAS_UPLOADS = 2
TAMANHO_MINIMO = 50_000   # um dump do banco real tem centenas de KB


def registrar(msg):
    linha = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(linha)
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except OSError:
        pass


def credenciais():
    try:
        from dotenv import dotenv_values
        env = dotenv_values(ROOT / ".env")
    except Exception:
        env = {}
    pega = lambda k, padrao: os.environ.get(k) or env.get(k) or padrao  # noqa: E731
    return (pega("DB_HOST", "localhost"), pega("DB_USER", "unimaster"),
            pega("DB_PASSWORD", ""), pega("DB_NAME", "unimaster"))


def backup_banco():
    host, user, senha, banco = credenciais()
    arq = DESTINO / f"banco_{datetime.now():%Y%m%d_%H%M}.sql.gz"
    tmp = arq.with_suffix(".tmp")
    cmd = ["mysqldump", "-h", host, "-u", user, "--single-transaction", "--no-tablespaces",
           "--routines", "--triggers", "--default-character-set=utf8mb4", banco]
    with gzip.open(tmp, "wb") as saida:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           env=dict(os.environ, MYSQL_PWD=senha), timeout=1800)
        saida.write(p.stdout)
    if p.returncode != 0 or tmp.stat().st_size < TAMANHO_MINIMO:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"mysqldump falhou ({p.returncode}): {p.stderr.decode(errors='ignore')[:300]}")
    tmp.rename(arq)
    os.chmod(arq, 0o600)   # dados pessoais de alunos: só root lê
    registrar(f"banco ok: {arq.name} ({arq.stat().st_size // 1024} KB)")
    return arq


def backup_uploads():
    origem = ROOT / "static" / "uploads"
    arq = DESTINO / f"uploads_{datetime.now():%Y%m%d}.tar.gz"
    with tarfile.open(arq, "w:gz") as tar:
        tar.add(origem, arcname="uploads")
    os.chmod(arq, 0o600)
    registrar(f"uploads ok: {arq.name} ({arq.stat().st_size // (1024 * 1024)} MB)")


def limpar():
    limite = time.time() - DIAS_BANCO * 86400
    for f in DESTINO.glob("banco_*.sql.gz"):
        if f.stat().st_mtime < limite:
            f.unlink()
            registrar(f"removido (mais de {DIAS_BANCO} dias): {f.name}")
    ups = sorted(DESTINO.glob("uploads_*.tar.gz"))
    for f in ups[:-COPIAS_UPLOADS]:
        f.unlink()
        registrar(f"removido (guarda {COPIAS_UPLOADS}): {f.name}")


def main():
    DESTINO.mkdir(parents=True, exist_ok=True)
    os.chmod(DESTINO, 0o700)
    try:
        backup_banco()
        if "--uploads" in sys.argv or datetime.now().weekday() == 6:
            backup_uploads()
        limpar()
    except Exception as e:
        registrar(f"ERRO no backup: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
