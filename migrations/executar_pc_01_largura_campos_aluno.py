#!/usr/bin/env python3
"""
PC-01 — O pré-cadastro aceitava texto que o cadastro de aluno não guardava.

Sintoma: promover o pré-cadastro morria com

    Erro ao promover: 1406 (22001): Data too long for column 'numero' at row 1

A causa é só assimetria de largura. O formulário público grava em
`pre_cadastro`, com campos largos; a promoção copia para `alunos`, com campos
estreitos. Quem escreveu "138 Apto 301" no número da casa passou pelo
formulário e travou na promoção — e a secretaria não tinha como saber por quê,
porque a tela devolvia o erro cru do MySQL.

Treze colunas estavam nessa situação:

    coluna                       alunos        pre_cadastro
    bairro                       varchar(80)   varchar(120)
    cep                          varchar(10)   varchar(20)
    cidade                       varchar(80)   varchar(120)
    complemento                  varchar(100)  varchar(255)
    cpf                          varchar(14)   varchar(20)
    email                        varchar(100)  varchar(255)
    nome                         varchar(100)  varchar(255)
    nome_mae                     varchar(100)  varchar(255)
    nome_pai                     varchar(100)  varchar(255)
    numero                       varchar(10)   varchar(20)
    responsavel_financeiro_nome  varchar(100)  varchar(255)
    responsavel_parentesco       varchar(50)   varchar(100)
    telefone                     varchar(20)   varchar(50)

`usuarios.nome` e `usuarios.email` entram na mesma conta: a promoção cria o
login com o nome e o e-mail que vieram do pré-cadastro.

A migração só ALARGA. Nenhum dado é lido, reescrito ou truncado — alargar
varchar em InnoDB é mudança de metadado. O sentido contrário é que seria
destrutivo, e por isso `--reverter` se recusa a estreitar uma coluna que hoje
tenha algum valor mais longo do que caberia.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_pc_01_largura_campos_aluno.py            # simulação
  .venv/bin/python migrations/executar_pc_01_largura_campos_aluno.py --aplicar
  .venv/bin/python migrations/executar_pc_01_largura_campos_aluno.py --reverter
"""

import gzip
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

DIR_BACKUP = Path("/var/backups/unimaster")

# (tabela, coluna, largura antiga, largura nova). A largura nova é a da coluna
# equivalente em pre_cadastro — a origem do dado.
ALARGAR = [
    ("alunos", "bairro", 80, 120),
    ("alunos", "cep", 10, 20),
    ("alunos", "cidade", 80, 120),
    ("alunos", "complemento", 100, 255),
    ("alunos", "cpf", 14, 20),
    ("alunos", "email", 100, 255),
    ("alunos", "nome", 100, 255),
    ("alunos", "nome_mae", 100, 255),
    ("alunos", "nome_pai", 100, 255),
    ("alunos", "numero", 10, 20),
    ("alunos", "responsavel_financeiro_nome", 100, 255),
    ("alunos", "responsavel_parentesco", 50, 100),
    ("alunos", "telefone", 20, 50),
    ("usuarios", "nome", 100, 255),
    ("usuarios", "email", 100, 255),
]

# Dump: alunos inteiro; de usuarios só o que esta migração toca, para não
# espalhar hash de senha por diretório de backup sem necessidade.
DUMP = {"alunos": "*", "usuarios": "id, nome, email, cpf"}


def _literal(valor):
    if valor is None:
        return "NULL"
    if isinstance(valor, (int, float)):
        return str(valor)
    return "'" + str(valor).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _backup():
    DIR_BACKUP.mkdir(parents=True, exist_ok=True)
    destino = DIR_BACKUP / f"alunos_usuarios_pre_pc01_{datetime.now():%Y%m%d_%H%M%S}.sql.gz"
    conn = get_db_connection()
    cur = conn.cursor()
    total = 0
    try:
        with gzip.open(destino, "wt", encoding="utf-8") as f:
            f.write("-- Unimaster / PC-01: alunos e usuarios antes de alargar os campos\n")
            f.write(f"-- {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            f.write("-- De usuarios saem apenas id, nome, email e cpf.\n\n")
            for tabela, campos in DUMP.items():
                cur.execute(f"SHOW CREATE TABLE `{tabela}`")
                f.write(f"-- {tabela}\n{cur.fetchone()[1]};\n\n")
                cur.execute(f"SELECT {campos} FROM `{tabela}` ORDER BY id")
                colunas = [d[0] for d in cur.description]
                linhas = cur.fetchall()
                total += len(linhas)
                nomes = ", ".join(f"`{c}`" for c in colunas)
                for linha in linhas:
                    f.write(f"INSERT INTO `{tabela}` ({nomes}) VALUES "
                            f"({', '.join(_literal(v) for v in linha)});\n")
                f.write("\n")
    finally:
        cur.close()
        conn.close()
    print(f"✓ Backup: {destino} ({destino.stat().st_size} bytes, {total} linhas)")
    return destino


def _definicao(cur, tabela, coluna):
    """Definição atual da coluna, para alterar só a largura e nada mais."""
    cur.execute(
        """SELECT COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, COLLATION_NAME,
                  CHARACTER_MAXIMUM_LENGTH
           FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s""",
        (tabela, coluna))
    linha = cur.fetchone()
    if not linha:
        return None
    tipo, nulo, padrao, colacao, largura = linha
    return {"tipo": tipo, "nulo": nulo == "YES", "padrao": padrao,
            "colacao": colacao, "largura": largura}


def _modify(tabela, coluna, largura, d):
    """MODIFY que muda a largura e preserva colação, nulidade e default."""
    sql = f"ALTER TABLE `{tabela}` MODIFY `{coluna}` VARCHAR({largura})"
    if d["colacao"]:
        sql += f" COLLATE {d['colacao']}"
    sql += " NULL DEFAULT NULL" if d["nulo"] else " NOT NULL"
    return sql


def _plano(cur, alvo_novo=True):
    """O que seria feito, sem escrever nada. Devolve a lista de alterações."""
    fazer, impedem = [], []
    for tabela, coluna, antiga, nova in ALARGAR:
        d = _definicao(cur, tabela, coluna)
        if not d:
            print(f"  ·  {tabela}.{coluna}: não existe — ignorada")
            continue
        destino = nova if alvo_novo else antiga
        if d["largura"] == destino:
            print(f"  =  {tabela}.{coluna}: já em varchar({destino})")
            continue
        if not alvo_novo:
            # Estreitar só pode se nenhum valor de hoje perder caractere.
            cur.execute(f"SELECT COUNT(*) FROM `{tabela}` WHERE CHAR_LENGTH(`{coluna}`) > %s",
                        (destino,))
            maiores = cur.fetchone()[0]
            if maiores:
                impedem.append(f"{tabela}.{coluna} ({maiores} registro(s) acima de {destino})")
                continue
        print(f"  →  {tabela}.{coluna}: varchar({d['largura']}) → varchar({destino})")
        fazer.append((tabela, coluna, destino, d))
    return fazer, impedem


def main():
    reverter = "--reverter" in sys.argv
    aplicar = "--aplicar" in sys.argv
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        print("\nPC-01 — largura dos campos que vêm do pré-cadastro")
        print("Revertendo (estreitar):\n" if reverter else "Alargando:\n")
        fazer, impedem = _plano(cur, alvo_novo=not reverter)

        if impedem:
            print("\n✗ Reversão recusada: estreitar estas colunas apagaria dado gravado —")
            for m in impedem:
                print(f"    {m}")
            print("  Apague ou encurte esses valores antes de reverter.")
            return 1
        if not fazer:
            print("\nNada a fazer.")
            return 0
        if not (aplicar or reverter):
            print(f"\n{len(fazer)} alteração(ões). Simulação — rode com --aplicar para gravar.")
            return 0
        if reverter and not aplicar:
            print(f"\n{len(fazer)} alteração(ões) a reverter. "
                  "Rode com --reverter --aplicar para gravar.")
            return 0

        _backup()
        for tabela, coluna, largura, d in fazer:
            sql = _modify(tabela, coluna, largura, d)
            cur.execute(sql)
            print(f"✓ {sql}")
        conn.commit()
        print(f"\n✓ PC-01 {'revertida' if reverter else 'aplicada'}: "
              f"{len(fazer)} coluna(s).")
        return 0
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
