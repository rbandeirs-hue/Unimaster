# -*- coding: utf-8 -*-
"""Chamada por foto: consentimento, liga/desliga por academia e "assinatura" do rosto.

Como funciona
-------------
O reconhecimento roda NO NAVEGADOR do professor (face-api, carregada do CDN):
a foto da turma nunca sobe para o servidor. O que o servidor guarda é só o
descritor de cada aluno — 128 números que resumem o rosto da foto do cadastro —
para o celular não precisar recalcular a turma inteira a cada aula.

Quem entra no reconhecimento
----------------------------
Só aluno com foto no cadastro E consentimento 'autorizou'. Rosto é dado
biométrico (sensível na LGPD): sem consentimento explícito o aluno não é
procurado na foto, aparece na lista para o professor marcar à mão. Menor de
idade: quem autoriza é o responsável.

Retirar o consentimento apaga os descritores do aluno na mesma hora.

Os descritores de origem 'cadastro' valem para a foto em que foram calculados
(`foto`); trocou a foto, o antigo é ignorado e o navegador calcula outro.
Os de origem 'chamada' vêm de um rosto que o professor identificou à mão
("guardar este rosto") e ajudam quando a foto do cadastro é antiga.
"""
import json
import math

STATUS = {
    "autorizou": ("Autorizou", "success"),
    "aguardando": ("Aguardando", "warning"),
    "recusou": ("Recusou", "neutral"),
}
VIAS = {"responsavel": "pelo responsável", "aluno": "pelo próprio aluno",
        "termo_papel": "termo em papel"}
MAX_DESCRITORES_CHAMADA = 5
TAMANHO_DESCRITOR = 128

TERMO = (
    "Autorizo a academia a usar a foto do cadastro de {aluno} para conferir a "
    "presença nas aulas pela chamada por foto. O sistema compara o rosto da foto "
    "da turma com a foto do cadastro; a foto da turma não é guardada, fica só a "
    "lista de presença. A autorização pode ser retirada a qualquer momento, e "
    "então os dados do rosto são apagados e a presença volta a ser marcada à mão."
)

_DDL = [
    """CREATE TABLE IF NOT EXISTS chamada_foto_academia (
        academia_id    INT NOT NULL PRIMARY KEY,
        ativa          TINYINT(1) NOT NULL DEFAULT 0,
        atualizado_por INT NULL,
        atualizado_em  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS chamada_foto_consentimento (
        aluno_id        INT NOT NULL PRIMARY KEY,
        status          VARCHAR(12) NOT NULL DEFAULT 'aguardando',
        via             VARCHAR(16) NULL,
        respondido_por  INT NULL,
        respondido_em   DATETIME NULL,
        pedido_em       DATETIME NULL,
        atualizado_em   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS chamada_foto_descritor (
        id         INT AUTO_INCREMENT PRIMARY KEY,
        aluno_id   INT NOT NULL,
        origem     VARCHAR(10) NOT NULL,
        foto       VARCHAR(255) NULL,
        descritor  TEXT NOT NULL,
        criado_em  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        KEY ix_cfd_aluno (aluno_id, origem)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]


def garantir_tabelas(cur):
    for sql in _DDL:
        cur.execute(sql)


# ------------------------------------------------------------------ academia
def academia_ativa(cur, academia_id):
    if not academia_id:
        return False
    try:
        cur.execute("SELECT ativa FROM chamada_foto_academia WHERE academia_id = %s", (academia_id,))
        r = cur.fetchone()
    except Exception:
        return False   # tabela ainda não criada: recurso desligado
    if not r:
        return False
    return bool(r["ativa"] if isinstance(r, dict) else r[0])


def definir_ativa(cur, academia_id, ativa, usuario_id):
    cur.execute(
        """INSERT INTO chamada_foto_academia (academia_id, ativa, atualizado_por)
           VALUES (%s, %s, %s)
           ON DUPLICATE KEY UPDATE ativa = VALUES(ativa), atualizado_por = VALUES(atualizado_por)""",
        (academia_id, 1 if ativa else 0, usuario_id),
    )


# ------------------------------------------------------------ consentimento
def status_dos_alunos(cur, aluno_ids):
    """{aluno_id: linha de chamada_foto_consentimento} — ausente = nunca pedido."""
    ids = [int(i) for i in aluno_ids if str(i).isdigit()]
    if not ids:
        return {}
    ph = ",".join(["%s"] * len(ids))
    try:
        cur.execute(f"SELECT * FROM chamada_foto_consentimento WHERE aluno_id IN ({ph})", tuple(ids))
        return {r["aluno_id"]: r for r in cur.fetchall()}
    except Exception:
        return {}


def definir_consentimento(cur, aluno_id, status, via, usuario_id):
    if status not in STATUS:
        raise ValueError("status inválido")
    respondido = status != "aguardando"
    cur.execute(
        """INSERT INTO chamada_foto_consentimento (aluno_id, status, via, respondido_por, respondido_em)
           VALUES (%s, %s, %s, %s, IF(%s, NOW(), NULL))
           ON DUPLICATE KEY UPDATE status = VALUES(status), via = VALUES(via),
               respondido_por = VALUES(respondido_por), respondido_em = VALUES(respondido_em)""",
        (aluno_id, status, via, usuario_id, 1 if respondido else 0),
    )
    if status != "autorizou":
        cur.execute("DELETE FROM chamada_foto_descritor WHERE aluno_id = %s", (aluno_id,))


def marcar_pedido(cur, aluno_id):
    """Registra que o pedido saiu. Não rebaixa quem já respondeu."""
    cur.execute(
        """INSERT INTO chamada_foto_consentimento (aluno_id, status, pedido_em)
           VALUES (%s, 'aguardando', NOW())
           ON DUPLICATE KEY UPDATE pedido_em = NOW()""",
        (aluno_id,),
    )


def menor_de_idade(aluno):
    from datetime import date
    nasc = aluno.get("data_nascimento")
    if not nasc:
        return bool((aluno.get("responsavel_financeiro_nome") or "").strip())
    hoje = date.today()
    idade = hoje.year - nasc.year - ((hoje.month, hoje.day) < (nasc.month, nasc.day))
    return idade < 18


# ---------------------------------------------------------------- descritor
def validar_descritor(valor):
    """Lista de 128 floats finitos, arredondada — ou None."""
    if not isinstance(valor, (list, tuple)) or len(valor) != TAMANHO_DESCRITOR:
        return None
    out = []
    for v in valor:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(f) or abs(f) > 10:
            return None
        out.append(round(f, 5))
    return out


def salvar_descritor(cur, aluno_id, origem, foto, descritor):
    texto = json.dumps(descritor, separators=(",", ":"))
    if origem == "cadastro":
        cur.execute("DELETE FROM chamada_foto_descritor WHERE aluno_id = %s AND origem = 'cadastro'",
                    (aluno_id,))
        cur.execute("""INSERT INTO chamada_foto_descritor (aluno_id, origem, foto, descritor)
                       VALUES (%s, 'cadastro', %s, %s)""", (aluno_id, foto, texto))
        return
    cur.execute("""INSERT INTO chamada_foto_descritor (aluno_id, origem, descritor)
                   VALUES (%s, 'chamada', %s)""", (aluno_id, texto))
    # Guarda só os mais recentes: o rosto muda, e a lista não pode crescer sem fim.
    cur.execute("""SELECT id FROM chamada_foto_descritor WHERE aluno_id = %s AND origem = 'chamada'
                   ORDER BY id DESC""", (aluno_id,))
    velhos = [r["id"] if isinstance(r, dict) else r[0] for r in cur.fetchall()][MAX_DESCRITORES_CHAMADA:]
    if velhos:
        ph = ",".join(["%s"] * len(velhos))
        cur.execute(f"DELETE FROM chamada_foto_descritor WHERE id IN ({ph})", tuple(velhos))


def descritores_validos(cur, alunos_foto):
    """{aluno_id: {"cadastro": bool, "lista": [[128 floats], ...]}} para os alunos dados.

    `alunos_foto` = {aluno_id: foto atual}. O descritor de cadastro só vale se
    foi calculado na foto atual.
    """
    ids = list(alunos_foto)
    if not ids:
        return {}
    ph = ",".join(["%s"] * len(ids))
    try:
        cur.execute(f"""SELECT aluno_id, origem, foto, descritor FROM chamada_foto_descritor
                        WHERE aluno_id IN ({ph})""", tuple(ids))
        linhas = cur.fetchall()
    except Exception:
        return {}
    out = {}
    for r in linhas:
        if r["origem"] == "cadastro" and r["foto"] != alunos_foto.get(r["aluno_id"]):
            continue
        try:
            d = json.loads(r["descritor"])
        except Exception:
            continue
        item = out.setdefault(r["aluno_id"], {"cadastro": False, "lista": []})
        item["lista"].append(d)
        if r["origem"] == "cadastro":
            item["cadastro"] = True
    return out
