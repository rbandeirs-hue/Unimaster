#!/usr/bin/env python3
"""
Verifica no MySQL atual se objetos das migrações recentes do projeto existem.

O projeto não mantém tabela schema_migrations — esta checagem é heurística
(baseada nos artefatos esperados dos .sql em migrations/).

Uso (na raiz do projeto):
  .venv/bin/python migrations/verificar_migracoes_pendentes.py

Usa config.get_db_connection() (variáveis DB_* ou fallback em config.py).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_connection  # noqa: E402

CHECKS = [
    ("Tabela formas_pagamento_catalogo", """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = DATABASE() AND table_name = 'formas_pagamento_catalogo'
    """),
    ("Coluna formas_pagamento.id_catalogo", """
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = 'formas_pagamento'
          AND column_name = 'id_catalogo'
    """),
    ("Coluna mensalidade_aluno.id_forma_pagamento", """
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = 'mensalidade_aluno'
          AND column_name = 'id_forma_pagamento'
    """),
    ("Coluna receitas.id_forma_pagamento", """
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = 'receitas'
          AND column_name = 'id_forma_pagamento'
    """),
    ("Tabela registros_aula_presenca", """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = DATABASE() AND table_name = 'registros_aula_presenca'
    """),
    ("Tabela presencas_avulsas", """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = DATABASE() AND table_name = 'presencas_avulsas'
    """),
    ("Coluna presencas.horario_aula", """
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = 'presencas'
          AND column_name = 'horario_aula'
    """),
    ("Índice uk_presenca_aluno_turma_data_hora", """
        SELECT 1 FROM information_schema.statistics
        WHERE table_schema = DATABASE() AND table_name = 'presencas'
          AND index_name = 'uk_presenca_aluno_turma_data_hora'
    """),
    ("Coluna presencas.observacao_aluno", """
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = 'presencas'
          AND column_name = 'observacao_aluno'
    """),
    ("Tabela aniversario_mensagens", """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = DATABASE() AND table_name = 'aniversario_mensagens'
    """),
    ("Tabela push_subscriptions", """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = DATABASE() AND table_name = 'push_subscriptions'
    """),
]


def main():
    try:
        conn = get_db_connection()
    except Exception as e:
        print("Erro de conexão:", e)
        return 1

    cur = conn.cursor(buffered=True)
    print("Servidor:", getattr(conn, "server_host", "?"), "| Base:", conn.database)
    print("-" * 60)

    pending = []
    for label, sql in CHECKS:
        cur.execute(sql.strip())
        ok = cur.fetchone() is not None
        line = "OK       " if ok else "PENDENTE"
        print(f"[{line}] {label}")
        if not ok:
            pending.append(label)

    cur.execute(
        """
        SELECT table_name, index_name
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND column_name = 'responsavel_financeiro_cpf'
          AND non_unique = 0
        ORDER BY table_name, index_name
        """
    )
    rf = cur.fetchall()
    print("-" * 60)
    print("UNIQUE em responsavel_financeiro_cpf:")
    if not rf:
        print("  (nenhum — esperado após drop_unique)")
    else:
        for t, i in rf:
            print(f"  {t}.{i}")
        pending.append("Executar: migrations/executar_drop_unique_responsavel_financeiro_cpf.py")

    cur.close()
    conn.close()

    print("-" * 60)
    if pending:
        print("Itens pendentes ou a revisar:")
        for p in pending:
            print(" -", p)
        print("\nScripts úteis:")
        print("  .venv/bin/python migrations/executar_formas_pagamento_completo.py")
        print("  .venv/bin/python migrations/executar_add_registros_aula_presenca.py")
        print("  mysql ... < migrations/add_presencas_avulsas.sql")
        print("  .venv/bin/python migrations/executar_alter_presencas_unique_turma.py")
        print("  .venv/bin/python migrations/executar_aniversario_mensagens.py")
        print("  .venv/bin/python migrations/executar_push_subscriptions.py")
        return 2

    print("Nenhuma pendência nas checagens acima.")
    print("(Outras migrações antigas não são auditadas automaticamente.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
