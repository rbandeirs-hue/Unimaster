# -*- coding: utf-8 -*-
"""Mensagens enviadas da ficha do aluno, uma a uma.

O que isto NÃO é
----------------
Não é automação nem envio em massa. É a secretaria olhando a ficha de uma
pessoa e decidindo falar com ela: uma ocorrência, um aviso de faltas, um recado
livre, ou qualquer um dos modelos que a academia já tem cadastrados.

Por isso não passa pelo interruptor de "Avisos gerais", que governa o disparo
para turmas inteiras. Segue o mesmo critério do lembrete individual e do
parabéns manual, que já existiam: quem clicou na ficha de alguém já decidiu.

O que continua valendo
----------------------
* o telefone vem do cadastro — o destinatário é o responsável financeiro
  quando há um, senão o próprio aluno;
* o modelo desativado na tela de Mensagens não sai, exceto no texto livre,
  que não é modelo nenhum;
* todo envio é registrado em `whatsapp_log`, com o tipo, para aparecer no
  histórico da academia.
"""
from datetime import date

from config import get_db_connection
from utils import whatsapp as wpp
from utils import whatsapp_templates as tpl

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _primeiro_nome(texto):
    return (texto or "").strip().split(" ")[0]


def dados_do_aluno(aluno_id, academia_id=None):
    """Aluno, contato e turma. None quando não existe ou é de outra academia."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        sql = """SELECT a.id, a.nome, a.id_academia, a.telefone, a.tel_celular,
                        a.responsavel_financeiro_nome, a.responsavel_financeiro_telefone,
                        ac.nome AS academia_nome,
                        (SELECT t.Nome FROM aluno_turmas at
                          JOIN turmas t ON t.TurmaID = at.TurmaID
                         WHERE at.aluno_id = a.id LIMIT 1) AS turma
                 FROM alunos a
                 LEFT JOIN academias ac ON ac.id = a.id_academia
                 WHERE a.id = %s"""
        par = [aluno_id]
        if academia_id:
            sql += " AND a.id_academia = %s"
            par.append(academia_id)
        cur.execute(sql, tuple(par))
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


def destinatario(aluno):
    """(telefone, nome de quem recebe). O responsável financeiro tem prioridade.

    É ele quem costuma ter o número que a academia usa, e é a mesma regra dos
    lembretes — falar com dois contatos diferentes sobre o mesmo aluno confunde.
    """
    if not aluno:
        return "", ""
    tel = (aluno.get("responsavel_financeiro_telefone") or "").strip()
    if tel:
        return tel, (aluno.get("responsavel_financeiro_nome")
                     or aluno.get("nome") or "")
    tel = (aluno.get("tel_celular") or aluno.get("telefone") or "").strip()
    return tel, (aluno.get("nome") or "")


def contar_faltas(aluno_id, mes=None, ano=None):
    """Faltas do aluno no mês, e o rótulo do período para a mensagem."""
    hoje = date.today()
    mes = int(mes or hoje.month)
    ano = int(ano or hoje.year)
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT COUNT(*) FROM presencas
               WHERE aluno_id = %s AND presente = 0
                 AND MONTH(data_presenca) = %s AND YEAR(data_presenca) = %s""",
            (aluno_id, mes, ano))
        r = cur.fetchone()
        total = int(r[0]) if r else 0
    except Exception:
        total = 0
    finally:
        cur.close()
        conn.close()
    return total, f"{MESES[mes - 1]} de {ano}"


def contexto(aluno, extra=None):
    """Os placeholders disponíveis para qualquer modelo, a partir do aluno."""
    _tel, quem = destinatario(aluno)
    ctx = {
        "nome": _primeiro_nome(quem),
        "responsavel": quem,
        "aluno": aluno.get("nome") or "",
        "academia": aluno.get("academia_nome") or "",
        "turma": aluno.get("turma") or "",
        "mes": date.today().strftime("%m/%Y"),
        "competencia": date.today().strftime("%m/%Y"),
        "valor": "", "vencimento": "", "link": "", "pix": "",
        "ocorrencia": "", "faltas": "", "periodo": "",
    }
    ctx.update(extra or {})
    return ctx


def previa(aluno_id, tipo, academia_id=None, texto_livre=None, extra=None):
    """O texto exatamente como sairá, para a tela mostrar antes de enviar.

    Devolve (texto, erro). Erro preenchido significa que não dá para enviar —
    e a razão é a mesma que o envio usaria, para a prévia nunca prometer algo
    que o envio recusaria.
    """
    aluno = dados_do_aluno(aluno_id, academia_id)
    if not aluno:
        return "", "Aluno não encontrado nesta academia."
    tel, _quem = destinatario(aluno)
    if not tel:
        return "", "Este aluno não tem telefone cadastrado."

    if tipo == "livre":
        texto = (texto_livre or "").strip()
        if not texto:
            return "", "Escreva a mensagem."
        return tpl.render(texto, contexto(aluno, extra)), ""

    if tipo not in tpl.TIPOS:
        return "", "Tipo de mensagem desconhecido."
    modelo, ativo = tpl.obter(aluno["id_academia"], tipo)
    if not ativo:
        return "", ("O modelo “%s” está desativado em Mensagens do WhatsApp."
                    % tpl.TIPOS[tipo]["label"])
    # Texto livre por cima de um modelo: a secretaria ajustou a prévia antes de
    # enviar. Vale o que ela escreveu.
    base = (texto_livre or "").strip() or modelo
    return tpl.render(base, contexto(aluno, extra)), ""


def enviar(aluno_id, tipo, academia_id=None, texto_livre=None, extra=None,
           usuario_id=None):
    """Envia e registra. Devolve (ok, mensagem)."""
    aluno = dados_do_aluno(aluno_id, academia_id)
    if not aluno:
        return False, "Aluno não encontrado nesta academia."
    texto, erro = previa(aluno_id, tipo, academia_id, texto_livre, extra)
    if erro:
        return False, erro
    tel, _quem = destinatario(aluno)

    ok, info = wpp.enviar(aluno["id_academia"], tel, texto)
    try:
        from utils import whatsapp_log as wlog
        wlog.registrar(aluno["id_academia"],
                       tipo if tipo != "livre" else "mensagem_livre",
                       "entregue" if ok else "falha",
                       aluno_id=aluno_id, telefone=tel,
                       erro=(info or {}).get("erro") if isinstance(info, dict) else None)
    except Exception:
        pass
    if ok:
        return True, "Mensagem enviada."
    return False, ((info.get("erro") if isinstance(info, dict) else None)
                   or "Falha no envio. A academia está com o WhatsApp conectado?")
