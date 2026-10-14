#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ADM-01 — Administrador de Sistema separado do gestor da academia.

Hoje quem administra o sistema é a conta pessoal do Rodrigo (id 3): ela acumula
admin, gestor de associação e gestor de três academias. Existe uma conta
"Administrador" (id 9) com o papel admin, mas **sem CPF** — e como o login é
por CPF, ela nunca pôde entrar.

Esta migração separa os dois papéis:

  id 9  "Administrador de Sistema", CPF 99999999999, só o papel admin.
        Admin não é limitado por vínculo em `usuarios_academias`: o próprio
        `_academias_ids_brutas` devolve todas as academias para ele. Por isso a
        conta fica SEM vínculo nenhum — ela enxerga as 14 sem marcar nada.

  id 3  Rodrigo, gestor da academia dele e mais nada. A academia é a 14
        (Projeto Esportivo Semeando Vidas): é a única em que ele é
        `gestor_principal`, e é a dona do handle InfinitePay $rodrigo-bandeirs.
        Mantém `professor@14` porque ele tem ficha de professor lá (id 17) e
        tirar o papel esconderia as turmas dele.

Ordem importa: a conta nova é criada e conferida ANTES de o Rodrigo perder o
admin. Se a ordem se invertesse e algo falhasse, ninguém administraria o
sistema.

A senha nova sai impressa uma vez, na aplicação. Troque no primeiro acesso.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_adm_01_administrador_sistema.py            # simulação
  .venv/bin/python migrations/executar_adm_01_administrador_sistema.py --aplicar
  .venv/bin/python migrations/executar_adm_01_administrador_sistema.py --reverter
"""

import json
import secrets
import string
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

DIR_BACKUP = Path("/var/backups/unimaster")
ADMIN_ID = 9
RODRIGO_ID = 3
ACADEMIA_DO_RODRIGO = 14
CPF_ADMIN = "99999999999"
NOME_ADMIN = "Administrador de Sistema"
# (chave do papel, academia_id). 0 = vale em todas.
PAPEIS_ADMIN = [("admin", 0)]
PAPEIS_RODRIGO = [("gestor_academia", ACADEMIA_DO_RODRIGO), ("professor", ACADEMIA_DO_RODRIGO)]


def _senha_forte():
    alfabeto = string.ascii_letters + string.digits
    return "".join(secrets.choice(alfabeto) for _ in range(14))


def _estado(cur):
    """Foto do que esta migração toca — serve de backup e de base do reverter."""
    ids = (ADMIN_ID, RODRIGO_ID)
    cur.execute("SELECT * FROM usuarios WHERE id IN (%s, %s)", ids)
    usuarios = {r["id"]: r for r in cur.fetchall()}
    cur.execute("""SELECT ru.usuario_id, ru.role_id, ru.academia_id, r.chave
                   FROM roles_usuario ru JOIN roles r ON r.id = ru.role_id
                   WHERE ru.usuario_id IN (%s, %s)""", ids)
    papeis = cur.fetchall()
    cur.execute("SELECT * FROM usuarios_academias WHERE usuario_id IN (%s, %s)", ids)
    vinculos = cur.fetchall()
    return {"usuarios": usuarios, "papeis": papeis, "vinculos": vinculos}


def _salvar_backup(estado):
    DIR_BACKUP.mkdir(parents=True, exist_ok=True)
    destino = DIR_BACKUP / f"adm01_estado_{datetime.now():%Y%m%d_%H%M%S}.json"
    destino.write_text(json.dumps(estado, ensure_ascii=False, indent=1, default=str),
                       encoding="utf-8")
    print(f"✓ Backup: {destino}")
    return destino


def _id_do_papel(cur, chave):
    cur.execute("SELECT id FROM roles WHERE chave = %s", (chave,))
    linha = cur.fetchone()
    return (linha or {}).get("id")


def _trocar_papeis(cur, usuario_id, desejados):
    """Deixa o usuário exatamente com estes papéis. Devolve (removidos, criados)."""
    cur.execute("""SELECT r.chave, ru.academia_id FROM roles_usuario ru
                   JOIN roles r ON r.id = ru.role_id WHERE ru.usuario_id = %s""", (usuario_id,))
    atuais = {(r["chave"], r["academia_id"]) for r in cur.fetchall()}
    alvo = set(desejados)
    for chave, academia_id in sorted(atuais - alvo):
        rid = _id_do_papel(cur, chave)
        cur.execute("DELETE FROM roles_usuario WHERE usuario_id=%s AND role_id=%s AND academia_id=%s",
                    (usuario_id, rid, academia_id))
    for chave, academia_id in sorted(alvo - atuais):
        rid = _id_do_papel(cur, chave)
        if rid:
            cur.execute("""INSERT IGNORE INTO roles_usuario (usuario_id, role_id, academia_id)
                           VALUES (%s, %s, %s)""", (usuario_id, rid, academia_id))
    return sorted(atuais - alvo), sorted(alvo - atuais)


def _plano(cur):
    est = _estado(cur)
    u9 = est["usuarios"].get(ADMIN_ID)
    u3 = est["usuarios"].get(RODRIGO_ID)
    if not u9 or not u3:
        print("✗ Usuário 9 ou 3 não encontrado — nada a fazer.")
        return False
    papeis = {}
    for r in est["papeis"]:
        papeis.setdefault(r["usuario_id"], []).append(f'{r["chave"]}@{r["academia_id"]}')
    print(f'\n  id {ADMIN_ID}  "{u9["nome"]}"  cpf={u9["cpf"]!r}')
    print(f'       papéis hoje: {", ".join(sorted(papeis.get(ADMIN_ID, []))) or "nenhum"}')
    print(f'       → nome "{NOME_ADMIN}", cpf {CPF_ADMIN}, senha nova, papéis: '
          f'{", ".join(f"{c}@{a}" for c, a in PAPEIS_ADMIN)}')
    print(f'\n  id {RODRIGO_ID}  "{u3["nome"]}"  cpf={u3["cpf"]!r}')
    print(f'       papéis hoje: {", ".join(sorted(papeis.get(RODRIGO_ID, []))) or "nenhum"}')
    print(f'       vínculos hoje: {sorted(v["academia_id"] for v in est["vinculos"] if v["usuario_id"] == RODRIGO_ID)}')
    print(f'       → papéis: {", ".join(f"{c}@{a}" for c, a in PAPEIS_RODRIGO)}; '
          f'vínculo só na academia {ACADEMIA_DO_RODRIGO}')
    return True


def _aplicar(conn, cur):
    from werkzeug.security import generate_password_hash
    est = _estado(cur)
    _salvar_backup(est)

    # 1) Administrador de Sistema — primeiro, e conferido, antes de mexer no Rodrigo.
    senha = _senha_forte()
    cur.execute("""UPDATE usuarios SET nome=%s, cpf=%s, senha=%s, perfil='Admin', ativo=1
                   WHERE id=%s""",
                (NOME_ADMIN, CPF_ADMIN, generate_password_hash(senha), ADMIN_ID))
    tirados, postos = _trocar_papeis(cur, ADMIN_ID, PAPEIS_ADMIN)
    # Admin não precisa (nem deve) de vínculo: o vínculo só limitaria a lista.
    cur.execute("DELETE FROM usuarios_academias WHERE usuario_id=%s", (ADMIN_ID,))
    conn.commit()
    print(f'✓ id {ADMIN_ID}: "{NOME_ADMIN}", cpf {CPF_ADMIN}; '
          f'papéis removidos {tirados or "—"}, mantidos/criados {PAPEIS_ADMIN}')

    cur.execute("""SELECT COUNT(*) n FROM roles_usuario ru JOIN roles r ON r.id=ru.role_id
                   WHERE ru.usuario_id=%s AND r.chave='admin' AND ru.academia_id=0""", (ADMIN_ID,))
    if not cur.fetchone()["n"]:
        conn.rollback()
        print("✗ A conta nova não ficou com o papel admin — nada foi mudado no Rodrigo.")
        return 1
    cur.execute("SELECT COUNT(*) n FROM academias")
    print(f'  confere: admin sem vínculo enxerga as {cur.fetchone()["n"]} academias')

    # 2) Rodrigo: gestor só da academia dele.
    tirados3, postos3 = _trocar_papeis(cur, RODRIGO_ID, PAPEIS_RODRIGO)
    cur.execute("DELETE FROM usuarios_academias WHERE usuario_id=%s AND academia_id<>%s",
                (RODRIGO_ID, ACADEMIA_DO_RODRIGO))
    cur.execute("""INSERT IGNORE INTO usuarios_academias
                   (usuario_id, academia_id, gestor_principal, acesso_financeiro, acesso_academico)
                   VALUES (%s, %s, 1, 1, 1)""", (RODRIGO_ID, ACADEMIA_DO_RODRIGO))
    conn.commit()
    print(f'✓ id {RODRIGO_ID}: papéis removidos {tirados3 or "—"}, criados {postos3 or "—"}; '
          f'vínculo só na academia {ACADEMIA_DO_RODRIGO}')

    print("\n" + "=" * 66)
    print(f"  Entre como:  CPF {CPF_ADMIN}")
    print(f"               senha {senha}")
    print("  Troque a senha no primeiro acesso.")
    print("=" * 66)
    return 0


def _reverter(conn, cur):
    arquivos = sorted(DIR_BACKUP.glob("adm01_estado_*.json"))
    if not arquivos:
        print("✗ Sem backup de ADM-01 em", DIR_BACKUP, "— nada a reverter com segurança.")
        return 1
    est = json.loads(arquivos[-1].read_text(encoding="utf-8"))
    print("Restaurando de", arquivos[-1])
    for uid, u in est["usuarios"].items():
        cur.execute("""UPDATE usuarios SET nome=%s, cpf=%s, senha=%s, perfil=%s, ativo=%s
                       WHERE id=%s""",
                    (u["nome"], u["cpf"], u["senha"], u["perfil"], u["ativo"], int(uid)))
    ids = (ADMIN_ID, RODRIGO_ID)
    cur.execute("DELETE FROM roles_usuario WHERE usuario_id IN (%s, %s)", ids)
    for r in est["papeis"]:
        cur.execute("""INSERT IGNORE INTO roles_usuario (usuario_id, role_id, academia_id)
                       VALUES (%s, %s, %s)""", (r["usuario_id"], r["role_id"], r["academia_id"]))
    cur.execute("DELETE FROM usuarios_academias WHERE usuario_id IN (%s, %s)", ids)
    for v in est["vinculos"]:
        cur.execute("""INSERT IGNORE INTO usuarios_academias
                       (usuario_id, academia_id, gestor_principal, acesso_financeiro, acesso_academico)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (v["usuario_id"], v["academia_id"], v["gestor_principal"],
                     v["acesso_financeiro"], v["acesso_academico"]))
    conn.commit()
    print("✓ ADM-01 revertida (inclusive a senha anterior do id 9).")
    return 0


def main():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        print("\nADM-01 — Administrador de Sistema")
        if "--reverter" in sys.argv:
            return _reverter(conn, cur)
        if not _plano(cur):
            return 1
        if "--aplicar" not in sys.argv:
            print("\nSimulação. Rode com --aplicar para gravar.")
            return 0
        return _aplicar(conn, cur)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
