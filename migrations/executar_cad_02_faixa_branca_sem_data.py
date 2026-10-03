#!/usr/bin/env python3
"""
CAD-02 — Faixa branca sem data de graduação.

Faixa branca não é graduação: o aluno começa nela. Mesmo assim o cadastro
pedia "Data da Última Graduação" para a branca e o registro manual aceitava
lançar uma branca no histórico — e o que ficou gravado foi a data da matrícula,
um "Cadastro" genérico ou até 0007-01-01 digitado por engano. A ficha mostrava
isso como "desde dd/mm/aaaa", como se fosse exame.

O código agora grava NULL para a branca (utils/faixa_branca.py). Esta migração
limpa o que já estava no banco:

  alunos.ultimo_exame_faixa   vira NULL nos alunos cuja graduação ATUAL é branca;
  aluno_graduacao             perde as linhas de faixa branca (a tabela exige
                              data NOT NULL, então a branca não tem como ficar
                              lá sem data inventada).

A branca é reconhecida pelo nome normalizado ("BRANCA", "Branca"), não por id:
judô e jiu-jitsu têm cada um a sua. "Branca/Cinza" e "Vermelha e Branca" não
entram.

Efeito no exame de faixa (utils/exame_faixa.py): a data da última graduação só
pesa na carência, e a promoção que sai da branca não tem carência — zerar a
data não muda a situação de ninguém.

Antes de apagar, as linhas afetadas vão para /var/backups/unimaster em SQL
(gzip): os INSERTs do histórico e os UPDATEs que devolvem as datas. É de lá que
o --reverter restaura.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_cad_02_faixa_branca_sem_data.py            # simulação
  .venv/bin/python migrations/executar_cad_02_faixa_branca_sem_data.py --aplicar
  .venv/bin/python migrations/executar_cad_02_faixa_branca_sem_data.py --reverter [arquivo.sql.gz]
"""

import gzip
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402
from utils.faixa_branca import faixa_eh_branca  # noqa: E402

DIR_BACKUP = Path("/var/backups/unimaster")
PREFIXO = "faixa_branca_pre_cad02_"


def _ids_brancas(cur):
    cur.execute("SELECT id, faixa FROM graduacao")
    return [g["id"] for g in cur.fetchall() if faixa_eh_branca(g["faixa"])]


def _plano(cur):
    """O que a migração faria, sem escrever nada."""
    brancas = _ids_brancas(cur)
    alunos, historico = [], []
    if brancas:
        ph = ",".join(["%s"] * len(brancas))
        cur.execute(
            f"""SELECT id, nome, ativo, ultimo_exame_faixa FROM alunos
                WHERE graduacao_id IN ({ph}) AND ultimo_exame_faixa IS NOT NULL
                ORDER BY id""", tuple(brancas))
        alunos = cur.fetchall()
    # No histórico vale também o texto da faixa: linha antiga pode ter
    # graduacao_id nulo e só o nome gravado.
    cur.execute("SELECT * FROM aluno_graduacao ORDER BY id")
    for r in cur.fetchall():
        if (r.get("graduacao_id") in brancas) or faixa_eh_branca(r.get("faixa")):
            historico.append(r)
    return brancas, alunos, historico


def _literal(valor):
    """Valor Python -> literal SQL, para o dump."""
    if valor is None:
        return "NULL"
    if isinstance(valor, (int, float)):
        return str(valor)
    texto = str(valor)
    return "'" + texto.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _backup(alunos, historico):
    """Grava o que vai ser alterado, em SQL pronto para reaplicar.

    Só as linhas afetadas — restaurar a tabela inteira desfaria o que a
    academia lançou depois. O UPDATE só devolve a data se ela ainda estiver
    nula, para não pisar numa data corrigida à mão depois da migração.
    """
    DIR_BACKUP.mkdir(parents=True, exist_ok=True)
    destino = DIR_BACKUP / f"{PREFIXO}{datetime.now():%Y%m%d_%H%M%S}.sql.gz"
    with gzip.open(destino, "wt", encoding="utf-8") as f:
        f.write("-- Unimaster / CAD-02: faixa branca antes de zerar a data de graduação\n")
        f.write(f"-- {datetime.now():%Y-%m-%d %H:%M:%S} — {len(alunos)} aluno(s), "
                f"{len(historico)} linha(s) de aluno_graduacao\n\n")
        for a in alunos:
            f.write(f"UPDATE alunos SET ultimo_exame_faixa = {_literal(a['ultimo_exame_faixa'])} "
                    f"WHERE id = {int(a['id'])} AND ultimo_exame_faixa IS NULL;\n")
        if historico:
            colunas = list(historico[0].keys())
            campos = ", ".join(f"`{c}`" for c in colunas)
            for linha in historico:
                valores = ", ".join(_literal(linha[c]) for c in colunas)
                f.write(f"INSERT IGNORE INTO aluno_graduacao ({campos}) VALUES ({valores});\n")
    print(f"✓ Backup: {destino} ({destino.stat().st_size} bytes)")
    return destino


def simular():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        brancas, alunos, historico = _plano(cur)
        print("CAD-02 — simulação (nada foi gravado)\n")
        print(f"  graduações brancas (ids)                  : {brancas}")
        print(f"  alunos na branca com data a zerar         : {len(alunos)} "
              f"({sum(1 for a in alunos if a['ativo'])} ativo(s))")
        for a in alunos:
            print(f"      {a['id']:>5}  {a['ultimo_exame_faixa']}  {a['nome']}")
        print(f"  linhas de aluno_graduacao a remover       : {len(historico)}")
        for h in historico:
            print(f"      #{h['id']:>4}  aluno {h['aluno_id']:>5}  {h['data']}  {h['origem']}")
        print(f"\n  backup irá para                           : {DIR_BACKUP}/{PREFIXO}*.sql.gz")
        print("\nPara aplicar:  --aplicar")
    finally:
        cur.close()
        conn.close()


def executar_migracao():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        brancas, alunos, historico = _plano(cur)
        if not alunos and not historico:
            print("• Nada a fazer: nenhuma faixa branca com data.")
            return
        _backup(alunos, historico)
        if alunos:
            ids = [a["id"] for a in alunos]
            cur.execute(
                f"UPDATE alunos SET ultimo_exame_faixa = NULL WHERE id IN ({','.join(['%s'] * len(ids))})",
                tuple(ids))
            print(f"✓ Data da última graduação zerada em {cur.rowcount} aluno(s) na faixa branca.")
        if historico:
            ids = [h["id"] for h in historico]
            cur.execute(
                f"DELETE FROM aluno_graduacao WHERE id IN ({','.join(['%s'] * len(ids))})",
                tuple(ids))
            print(f"✓ {cur.rowcount} linha(s) de faixa branca removida(s) do histórico.")
        conn.commit()
        print("\nMigração concluída.")
    except Exception as e:
        conn.rollback()
        print("Erro na migração:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


def reverter(arquivo=None):
    """Reaplica o backup (o mais recente, se nenhum arquivo for indicado)."""
    if arquivo:
        origem = Path(arquivo)
    else:
        candidatos = sorted(DIR_BACKUP.glob(f"{PREFIXO}*.sql.gz"))
        if not candidatos:
            print(f"• Nenhum backup {PREFIXO}*.sql.gz em {DIR_BACKUP}; nada a reverter.")
            return
        origem = candidatos[-1]
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        n = 0
        with gzip.open(origem, "rt", encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if not linha or linha.startswith("--"):
                    continue
                cur.execute(linha.rstrip(";"))
                n += 1
        conn.commit()
        print(f"✓ {n} comando(s) reaplicado(s) de {origem}.")
    except Exception as e:
        conn.rollback()
        print("Erro na reversão:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    if "--reverter" in sys.argv:
        resto = [a for a in sys.argv[1:] if a != "--reverter"]
        reverter(resto[0] if resto else None)
    elif "--aplicar" in sys.argv:
        executar_migracao()
    else:
        simular()
