"""Testes da régua de cobrança.

Sem banco: as consultas e o envio de WhatsApp são substituídos por dublês, e o
que se testa é a decisão — em que dia a régua fala, com quem, e quando ela se
cala. É essa decisão que mudou; o resto (SQL, gateway, Baileys) já era.

Uso (na raiz do projeto):
  .venv/bin/python tests/test_regua_cobranca.py
"""
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import whatsapp_lembretes as lem  # noqa: E402
from utils import regua_cobranca as rc  # noqa: E402

ACADEMIA = -9999
HOJE = date(2026, 9, 10)
_falhas = []

# Estado dos dublês, zerado a cada cenário.
ENVIOS = []          # mensagens que saíram
MARCADOS = set()     # trava anti-duplicidade (whatsapp_envios)
PAGAS = set()        # mensalidades que "pagaram" antes do envio
LINHAS = []          # o que buscar_em_aberto devolve


def checar(nome, condicao, detalhe=""):
    print(("  PASSOU  " if condicao else "  FALHOU  ") + nome
          + (f"  [{detalhe}]" if detalhe and not condicao else ""))
    if not condicao:
        _falhas.append(nome)


# ---------------------------------------------------------------- dublês
class _Cur:
    def execute(self, *a, **k):
        pass

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def close(self):
        pass


class _Conn:
    def cursor(self, **k):
        return _Cur()

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class _Wpp:
    @staticmethod
    def enviar(academia_id, telefone, texto):
        ENVIOS.append({"telefone": telefone, "texto": texto})
        return True, {}


def instalar_dubles():
    lem.get_db_connection = lambda: _Conn()
    lem.wpp = _Wpp()
    lem._nome_academia = lambda cur, aid: {"nome": "Academia Teste",
                                           "whatsapp_lembrete_mensalidade": 1}
    lem.buscar_em_aberto = lambda cur, aid: list(LINHAS)
    lem._ja_enviado = lambda cur, aid, tipo, ref, dia: (tipo, ref, dia) in MARCADOS
    lem._marcar_enviado = lambda conn, cur, aid, tipo, ref, dia: MARCADOS.add((tipo, ref, dia))
    # A função real recebe a origem desde que a régua passou a cobrar
    # matrícula e avulsa, não só mensalidade.
    lem._ainda_cobravel = lambda cur, ma_id, origem='mensalidade': ma_id not in PAGAS
    lem.montar_mensagem = lambda row, nome, aid=None, custom=None: "[individual] %s" % row["id"]
    lem.montar_mensagem_consolidada = (
        lambda rows, nome, aid=None, custom=None:
        "[consolidada] %d itens" % len(rows))


def mensalidade(ma_id, dias_do_vencimento, aluno_id=1, telefone="11999990000", valor=70.0, **extra):
    """`dias_do_vencimento` positivo = já venceu há tantos dias."""
    row = {
        "id": ma_id, "aluno_id": aluno_id, "valor": valor,
        "data_vencimento": HOJE - timedelta(days=dias_do_vencimento),
        "status": "atrasado" if dias_do_vencimento > 0 else "pendente",
        "status_pagamento": None, "nome": "Aluno %s" % aluno_id,
        "telefone": telefone, "tel_celular": None,
        "responsavel_financeiro_nome": None, "responsavel_financeiro_telefone": None,
        "cobranca_suspensa": 0, "cobranca_suspensa_ate": None,
        "cobranca_suspensa_motivo": None,
    }
    row.update(extra)
    return row


def cenario(linhas, config=None, pagas=(), marcados=()):
    """Prepara o estado e roda a régua uma vez. Devolve (resumo, envios)."""
    global LINHAS
    LINHAS = list(linhas)
    ENVIOS.clear()
    MARCADOS.clear()
    MARCADOS.update(marcados)
    PAGAS.clear()
    PAGAS.update(pagas)

    cfg = {
        "hora_envio": 9, "consolidar_apos": 2, "tratativa_apos": 3,
        "individual": [{"dias": d, "ativo": True, "mensagem": None} for d in rc.PADRAO_INDIVIDUAL],
        "consolidada": [{"dias": d, "ativo": True, "mensagem": None} for d in rc.PADRAO_CONSOLIDADA],
        "personalizada": True,
    }
    if config:
        cfg.update(config)
    rc.carregar = lambda academia_id, cur=None: cfg
    resumo = lem.processar_regua(ACADEMIA, hoje=HOJE)
    return resumo, list(ENVIOS)


# ---------------------------------------------------------------- cenários
def limpar_log():
    """Tira do `whatsapp_log` o que este teste escreveu.

    A régua real é exercitada de ponta a ponta, e ela grava no log de verdade —
    sem esta limpeza, os envios fictícios da academia de teste ficavam
    misturados com os das academias que usam o WhatsApp.
    """
    from config import get_db_connection
    c = get_db_connection()
    cur = c.cursor()
    try:
        cur.execute("DELETE FROM whatsapp_log WHERE id_academia = %s", (ACADEMIA,))
        c.commit()
    except Exception:
        c.rollback()
    finally:
        cur.close()
        c.close()


def main():
    instalar_dubles()
    limpar_log()
    print("\nRégua de cobrança\n")

    # 1-5: dias configurados antes, no dia e depois.
    for rotulo, dias, espera in [
        ("1. D-10 (fora da régua) não envia", -10, 0),
        ("2. D-5 envia", -5, 1),
        ("3. D-4 (não configurado) não envia", -4, 0),
        ("4. D-1 envia", -1, 1),
        ("5. D0 envia", 0, 1),
        ("6. D+1 não envia", 1, 0),
        ("7. D+3 envia", 3, 1),
        ("8. D+4 não envia", 4, 0),
        ("9. D+7 envia", 7, 1),
    ]:
        _r, envios = cenario([mensalidade(100, dias)])
        checar(rotulo, len(envios) == espera, f"{len(envios)} envio(s)")

    # 10-11: pagamento tira a cobrança do caminho.
    _r, envios = cenario([mensalidade(100, 3)], pagas={100})
    checar("10. mensalidade paga antes do envio não é cobrada", not envios)

    _r, envios = cenario([])
    checar("11. sem mensalidade em aberto, nada sai", not envios)

    # 12: o job rodando duas vezes no mesmo dia.
    _r, envios1 = cenario([mensalidade(100, 3)])
    LINHAS_ANTES = list(LINHAS)
    ENVIOS.clear()
    resumo2 = lem.processar_regua(ACADEMIA, hoje=HOJE)   # segunda execução, mesma trava
    checar("12. segunda execução no mesmo dia não repete",
           len(envios1) == 1 and not ENVIOS and resumo2.get("repetidos") == 1,
           f"{len(ENVIOS)} envio(s) na 2ª")
    del LINHAS_ANTES

    # 13: trocar D+3 por D+5 muda o dia sem tocar em código.
    cfg_d5 = {"individual": [{"dias": d, "ativo": True, "mensagem": None}
                             for d in (-5, -1, 0, 5, 7, 15, 25)]}
    _r, envios = cenario([mensalidade(100, 3)], config=cfg_d5)
    checar("13a. com D+5 no lugar de D+3, o terceiro dia cala", not envios)
    _r, envios = cenario([mensalidade(100, 5)], config=cfg_d5)
    checar("13b. e o quinto dia fala", len(envios) == 1)

    # 13c: etapa desativada não envia.
    cfg_off = {"individual": [{"dias": 3, "ativo": False, "mensagem": None}]}
    _r, envios = cenario([mensalidade(100, 3)], config=cfg_off)
    checar("13c. etapa desativada não envia", not envios)

    # 14: duas vencidas viram uma cobrança consolidada. A âncora é o dia
    # seguinte ao vencimento da segunda — é quando ele passa a dever duas.
    duas = [mensalidade(100, 30, aluno_id=1), mensalidade(101, 1, aluno_id=1)]
    resumo, envios = cenario(duas)
    checar("14. duas vencidas: uma mensagem consolidada",
           len(envios) == 1 and envios[0]["texto"].startswith("[consolidada]")
           and resumo.get("consolidados") == 1,
           str(envios))

    # 14b: a consolidada também respeita a régua (D+7 da âncora, não todo dia).
    resumo, envios = cenario([mensalidade(100, 30, aluno_id=1),
                              mensalidade(101, 3, aluno_id=1)])
    checar("14b. consolidada fora da etapa não envia", not envios)
    resumo, envios = cenario([mensalidade(100, 30, aluno_id=1),
                              mensalidade(101, 8, aluno_id=1)])
    checar("14c. consolidada no D+7 da âncora envia", len(envios) == 1)

    # 15: pagando uma das duas, volta para a régua individual — a paga já não
    # volta da consulta, e o responsável passa a ter uma pendência só.
    resumo, envios = cenario([mensalidade(101, 3, aluno_id=1)])
    checar("15a. pagou uma das duas: volta para a régua individual",
           len(envios) == 1 and envios[0]["texto"].startswith("[individual]"), str(envios))
    # Pagou DEPOIS da consulta e antes do envio: a consolidada some do dia.
    resumo, envios = cenario([mensalidade(100, 30, aluno_id=1),
                              mensalidade(101, 1, aluno_id=1)], pagas={100})
    checar("15b. pagou entre a consulta e o envio: nada é enviado", not envios, str(envios))

    # 16: três vencidas param o automático e vão para tratativa.
    tres = [mensalidade(100, 30, aluno_id=1), mensalidade(101, 15, aluno_id=1),
            mensalidade(102, 1, aluno_id=1)]
    resumo, envios = cenario(tres)
    checar("16. três vencidas: nada automático, vai para tratativa",
           not envios and resumo.get("tratativa") == 1, str(resumo))

    # 17: cobrança suspensa.
    resumo, envios = cenario([mensalidade(100, 3, cobranca_suspensa=1)])
    checar("17a. suspensão indeterminada não recebe", not envios and resumo.get("suspensos") == 1)
    resumo, envios = cenario([mensalidade(100, 3, cobranca_suspensa_ate=HOJE + timedelta(days=5))])
    checar("17b. suspensão com prazo em aberto não recebe", not envios)
    resumo, envios = cenario([mensalidade(100, 3, cobranca_suspensa_ate=HOJE - timedelta(days=1))])
    checar("17c. suspensão vencida volta a cobrar", len(envios) == 1)

    # 18: responsável com dois alunos no mesmo telefone.
    dois_alunos = [mensalidade(100, 1, aluno_id=1, telefone="11988887777"),
                   mensalidade(101, 1, aluno_id=2, telefone="11988887777")]
    resumo, envios = cenario(dois_alunos)
    checar("18a. mesmo telefone, dois alunos: uma mensagem só", len(envios) == 1, str(envios))
    checar("18b. e ela é a consolidada", envios and envios[0]["texto"].startswith("[consolidada]"))

    outros_telefones = [mensalidade(100, 3, aluno_id=1, telefone="11988887777"),
                        mensalidade(101, 3, aluno_id=2, telefone="11955554444")]
    resumo, envios = cenario(outros_telefones)
    checar("18c. telefones diferentes: uma mensagem para cada", len(envios) == 2, str(envios))

    # Extra: uma vencida e outra a vencer no mesmo dia de etapa = uma mensagem.
    resumo, envios = cenario([mensalidade(100, 3, aluno_id=1),
                              mensalidade(101, -5, aluno_id=1)])
    checar("19. vencida + a vencer no mesmo dia: uma mensagem (a mais atrasada)",
           len(envios) == 1 and envios[0]["texto"] == "[individual] 100", str(envios))

    # Extra: pagamento em conferência nunca chega à régua (filtro no SELECT) —
    # aqui garante-se a segunda trava, a revalidação imediata antes do envio.
    resumo, envios = cenario([mensalidade(100, 3)], pagas={100})
    checar("20. revalidação imediata antes do envio", not envios)

    # Simulador: as datas batem com a régua.
    datas = [s["data"] for s in rc.simular(
        [{"dias": d, "ativo": True} for d in rc.PADRAO_INDIVIDUAL], date(2026, 9, 10))]
    # A expectativa sai da própria régua: ela já cresceu de 7 para 21 etapas
    # quando a cobrança passou a ir até 6 meses, e uma lista fixa aqui só
    # quebraria de novo no próximo ajuste.
    esperadas = [date(2026, 9, 10) + timedelta(days=d) for d in rc.PADRAO_INDIVIDUAL]
    checar("21. simulador projeta as datas da régua",
           datas == esperadas, str(datas))

    print()
    limpar_log()
    if _falhas:
        print(f"{len(_falhas)} falha(s): " + ", ".join(_falhas))
        sys.exit(1)
    print("Todos os cenários passaram.")


if __name__ == "__main__":
    main()
