#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Envio diário de lembretes de mensalidade via WhatsApp.

Roda 1x/dia (systemd timer). Para cada academia com a automação ligada
(whatsapp_lembrete_mensalidade=1) e com WhatsApp conectado, envia lembrete
das mensalidades pendentes/atrasadas com vencimento até hoje + DIAS_ANTES.

Uso: .venv/bin/python scripts/enviar_lembretes_whatsapp.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from config import get_db_connection
from utils import whatsapp as wpp
from utils import whatsapp_lembretes as lem

DIAS_ANTES = int(os.environ.get("WPP_DIAS_ANTES", "3"))


def main():
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

            if ac.get("lembretes"):
                resumo = lem.enviar_lote(aid, dias_antes=DIAS_ANTES, somente_ativadas=True)
                total_geral += resumo.get("enviados", 0)
                print(f"[lembretes] academia {aid} ({ac['nome']}): "
                      f"{resumo.get('enviados',0)} enviados, {resumo.get('falhas',0)} falhas, "
                      f"{resumo.get('sem_telefone',0)} sem telefone (de {resumo.get('total',0)}).")

            if ac.get("aniversario"):
                ra = lem.enviar_aniversariantes(aid, somente_ativadas=True)
                total_aniv += ra.get("enviados", 0)
                if ra.get("total"):
                    print(f"[aniversário] academia {aid} ({ac['nome']}): "
                          f"{ra.get('enviados',0)} parabéns enviados, "
                          f"{ra.get('sem_telefone',0)} sem telefone, "
                          f"{ra.get('repetidos',0)} já enviados hoje (de {ra.get('total',0)}).")

        print(f"[lembretes] concluído. Mensalidades: {total_geral} · Aniversários: {total_aniv}.")


if __name__ == "__main__":
    main()
