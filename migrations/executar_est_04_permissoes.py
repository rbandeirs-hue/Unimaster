#!/usr/bin/env python3
"""
EST-04 — Permissões do estoque e as chaves que ligam o módulo.

O RBAC do projeto existe e estava ocioso
----------------------------------------
`permissoes`, `role_permissoes`, `has_permission()` e `@permission_required`
já estavam no sistema, com 7 permissões cadastradas e ZERO rotas usando o
decorador — tudo roda por papel. O estoque é o primeiro módulo a usar permissão
por operação, como o dono do sistema pediu, e reusa a infraestrutura em vez de
criar um segundo modelo de autorização.

Quatro colunas novas, todas aditivas e com padrão que preserva o
comportamento atual:

  academias.modulo_estoque            0 — o administrador liga na academia que vai usar
  academias.estoque_permite_negativo  0 — saída acima do saldo é bloqueada
  associacoes.modulo_estoque          0 — a associação também pode ter estoque
  associacoes.estoque_revenda         0 — e, ligando, abastecer as academias

Nascendo em 0, nenhuma academia ganha um módulo que não pediu.

Esta é a única migração do estoque que toca tabelas existentes. São ALTER TABLE
ADD COLUMN: nenhuma linha muda de valor, e a reversão derruba as colunas.

Uso (na raiz do projeto):
  .venv/bin/python migrations/executar_est_04_permissoes.py            # simulação
  .venv/bin/python migrations/executar_est_04_permissoes.py --aplicar
  .venv/bin/python migrations/executar_est_04_permissoes.py --reverter
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

PERMISSOES = [
    ("estoque_ver",                "Consultar estoque, saldos e histórico"),
    ("estoque_produto_cadastrar",  "Cadastrar produtos, variações e categorias"),
    ("estoque_produto_editar",     "Alterar produtos, variações e preços"),
    ("estoque_entrada",            "Registrar entrada de estoque"),
    ("estoque_saida",              "Registrar saída, venda e entrega ao aluno"),
    ("estoque_ajustar",            "Ajustar saldo, estornar e autorizar saldo negativo"),
    ("estoque_inventario",         "Abrir, contar e fechar inventário"),
    ("estoque_relatorio",          "Ver relatórios de estoque"),
    ("estoque_config",             "Configurar locais, tabelas de preço e o módulo"),
]

# Admin não entra: `has_permission` devolve True para ele em qualquer permissão.
# Professor fica só com a consulta — quem precisar de mais, o administrador
# concede. Ampliar depois é um INSERT; tirar acesso já dado é conversa difícil.
POR_PAPEL = {
    "gestor_academia":   [p for p, _ in PERMISSOES],
    "gestor_associacao": [p for p, _ in PERMISSOES],
    "gestor_federacao":  ["estoque_ver", "estoque_relatorio"],
    "professor":         ["estoque_ver"],
}

COLUNAS = [
    ("academias", "modulo_estoque",
     "TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Academia usa o módulo de estoque'"),
    ("academias", "estoque_permite_negativo",
     "TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Permite saída acima do saldo disponível'"),
    ("associacoes", "modulo_estoque",
     "TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Associação mantém estoque próprio'"),
    ("associacoes", "estoque_revenda",
     "TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Academias podem revender o estoque da associação'"),
]


def _tem_coluna(cur, tabela, coluna):
    cur.execute(
        """SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s""",
        (tabela, coluna))
    return cur.fetchone() is not None


def _perm_id(cur, nome):
    cur.execute("SELECT id FROM permissoes WHERE nome = %s", (nome,))
    r = cur.fetchone()
    return r["id"] if r else None


def _role_id(cur, chave):
    cur.execute("SELECT id FROM roles WHERE chave = %s", (chave,))
    r = cur.fetchone()
    return r["id"] if r else None


def simular():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        print("EST-04 — simulação (nada foi gravado)\n")
        print("  Colunas:")
        for tab, col, _tipo in COLUNAS:
            existe = _tem_coluna(cur, tab, col)
            print(f"    {'já existe' if existe else 'criar   '}  {tab}.{col}")
        print("\n  Permissões:")
        for nome, desc in PERMISSOES:
            existe = _perm_id(cur, nome) is not None
            print(f"    {'já existe' if existe else 'criar   '}  {nome:<28} {desc}")
        print("\n  Concessões por papel:")
        for papel, perms in POR_PAPEL.items():
            print(f"    {papel:<20} {len(perms)} permissão(ões)")
        print("\n  Admin não recebe linhas: has_permission() já devolve True para ele.")
        print("\nPara aplicar:  --aplicar")
    finally:
        cur.close()
        conn.close()


def executar_migracao():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        for tab, col, tipo in COLUNAS:
            if _tem_coluna(cur, tab, col):
                print(f"• {tab}.{col} já existia.")
                continue
            cur.execute(f"ALTER TABLE {tab} ADD COLUMN {col} {tipo}")
            conn.commit()
            print(f"✓ {tab}.{col} criada.")

        for nome, desc in PERMISSOES:
            if _perm_id(cur, nome):
                print(f"• permissão {nome} já existia.")
                continue
            cur.execute("INSERT INTO permissoes (nome, descricao) VALUES (%s, %s)",
                        (nome, desc))
            print(f"✓ permissão {nome} criada.")
        conn.commit()

        concedidas = 0
        for papel, perms in POR_PAPEL.items():
            rid = _role_id(cur, papel)
            if not rid:
                print(f"! papel {papel} não encontrado — pulando.")
                continue
            for p in perms:
                pid = _perm_id(cur, p)
                if not pid:
                    continue
                cur.execute(
                    "INSERT IGNORE INTO role_permissoes (role_id, permissao_id) "
                    "VALUES (%s, %s)", (rid, pid))
                concedidas += cur.rowcount
        conn.commit()
        print(f"✓ {concedidas} concessão(ões) gravada(s).")
        print("\nMigração concluída.")
    except Exception as e:
        conn.rollback()
        print("Erro na migração:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


def reverter():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        nomes = [p for p, _ in PERMISSOES]
        marcas = ", ".join(["%s"] * len(nomes))
        cur.execute(
            f"""DELETE rp FROM role_permissoes rp
                JOIN permissoes p ON p.id = rp.permissao_id
                WHERE p.nome IN ({marcas})""", tuple(nomes))
        print(f"✓ {cur.rowcount} concessão(ões) removida(s).")
        cur.execute(f"DELETE FROM permissoes WHERE nome IN ({marcas})", tuple(nomes))
        print(f"✓ {cur.rowcount} permissão(ões) removida(s).")
        conn.commit()
        for tab, col, _tipo in COLUNAS:
            if _tem_coluna(cur, tab, col):
                cur.execute(f"ALTER TABLE {tab} DROP COLUMN {col}")
                conn.commit()
                print(f"✓ {tab}.{col} removida.")
            else:
                print(f"• {tab}.{col} já não existia.")
    except Exception as e:
        conn.rollback()
        print("Erro na reversão:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    if "--reverter" in sys.argv:
        reverter()
    elif "--aplicar" in sys.argv:
        executar_migracao()
    else:
        simular()
