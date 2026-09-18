#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Envio de cobranças de mensalidade via WhatsApp (régua) e aniversários.

Roda de hora em hora (systemd timer) e não envia nada fora da hora configurada
por academia (`cobranca_regua_config.hora_envio`, padrão 9h). Rodar mais vezes
é inofensivo: quem decide se sai mensagem é a régua de cobrança, e a trava em
`whatsapp_envios` impede a mesma etapa de sair duas vezes no mesmo dia.

Para cada academia com a automação ligada (whatsapp_lembrete_mensalidade=1) e
WhatsApp conectado, aplica a régua: só fala nos dias configurados (D-5, D-1,
D0, D+3, D+7, ...) em vez de cobrar todo vencido todo dia.

Uso: .venv/bin/python scripts/enviar_lembretes_whatsapp.py
     .venv/bin/python scripts/enviar_lembretes_whatsapp.py --agora   (ignora a hora)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from config import get_db_connection
from utils import whatsapp as wpp
from utils import whatsapp_lembretes as lem
from utils import regua_cobranca as regua

# Mantida por compatibilidade: só é usada se a régua estiver indisponível.
DIAS_ANTES = int(os.environ.get("WPP_DIAS_ANTES", "3"))
# `--agora` roda a régua independentemente da hora configurada (teste manual).
IGNORAR_HORA = "--agora" in sys.argv


def main():
    from datetime import datetime
    hora_atual = datetime.now().hour
    with app.app_context():
        if not wpp.disponivel():
            print("[lembretes] microserviço WhatsApp offline — abortando.")
            return

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        # Uma academia pode ter só os lembretes ligados, só o aniversário, ou os dois.
        cur.execute(
            """SELECT id, nome,
                      COALESCE(whatsapp_lembrete_mensalidade, 0) AS lembretes,
                      COALESCE(whatsapp_aniversario, 0) AS aniversario
               FROM academias
               WHERE COALESCE(whatsapp_lembrete_mensalidade, 0) = 1
                  OR COALESCE(whatsapp_aniversario, 0) = 1"""
        )
        academias = cur.fetchall()
        cur.close()
        conn.close()

        if not academias:
            print("[lembretes] nenhuma academia com automação ligada.")
            return

        total_geral = 0
        total_aniv = 0
        for ac in academias:
            aid = ac["id"]
            if not wpp.conectado(aid):
                print(f"[lembretes] academia {aid} ({ac['nome']}): WhatsApp não conectado — pulando.")
                continue

            # A academia escolhe a hora do disparo; o timer é de hora em hora.
            # Fora dela, nada sai — nem cobrança nem parabéns.
            cfg = regua.carregar(aid)
            na_hora = IGNORAR_HORA or int(cfg.get("hora_envio", 9)) == hora_atual
            if not na_hora:
                continue

            if ac.get("lembretes"):
                resumo = lem.processar_regua(aid, somente_ativadas=True)
                total_geral += resumo.get("enviados", 0)
                print(f"[régua] academia {aid} ({ac['nome']}): "
                      f"{resumo.get('enviados',0)} enviados "
                      f"({resumo.get('consolidados',0)} consolidados), "
                      f"{resumo.get('falhas',0)} falhas, "
                      f"{resumo.get('sem_telefone',0)} sem telefone, "
                      f"{resumo.get('repetidos',0)} já enviados hoje, "
                      f"{resumo.get('tratativa',0)} para tratativa, "
                      f"{resumo.get('suspensos',0)} suspensos "
                      f"(de {resumo.get('total',0)} em aberto).")

            if ac.get("aniversario"):
                ra = lem.enviar_aniversariantes(aid, somente_ativadas=True)
                total_aniv += ra.get("enviados", 0)
                if ra.get("total"):
                    print(f"[aniversário] academia {aid} ({ac['nome']}): "
                          f"{ra.get('enviados',0)} parabéns enviados, "
                          f"{ra.get('sem_telefone',0)} sem telefone, "
                          f"{ra.get('repetidos',0)} já enviados hoje (de {ra.get('total',0)}).")

        print(f"[lembretes] concluído. Cobranças: {total_geral} · Aniversários: {total_aniv}.")


if __name__ == "__main__":
    main()
