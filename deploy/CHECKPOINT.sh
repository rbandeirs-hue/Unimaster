#!/bin/bash
# ============================================================
# Checkpoint: salva o estado atual do projeto para poder reverter
# Uso: ./deploy/CHECKPOINT.sh
# Para reverter no futuro: git log, depois git reset --hard <hash>
# ============================================================
set -e
cd "$(dirname "$0")/.."

DATA=$(date +%Y%m%d_%H%M%S)
MSG="Checkpoint: sistema OK em $DATA"

echo "Salvando checkpoint..."
git add -A
git status
git commit -m "$MSG" || true
echo ""
echo "Checkpoint salvo. Para reverter no futuro:"
echo "  git log --oneline"
echo "  git reset --hard <hash-do-checkpoint>"
echo ""
