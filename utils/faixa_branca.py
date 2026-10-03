"""Faixa branca: o ponto de partida, não uma graduação.

O aluno começa na branca — ninguém "se gradua" nela. Por isso a branca não tem
data de graduação: o cadastro grava `ultimo_exame_faixa = NULL`, a ficha mostra
"sem data de graduação" e o histórico (`aluno_graduacao`) não recebe linha de
branca. A data que existia ali era a da matrícula ou um chute, e atrapalhava
quem lia a ficha achando que era um exame.

A identificação é pelo NOME normalizado, não por id: judô e jiu-jitsu têm cada
um a sua branca (ids diferentes) e uma associação nova pode cadastrar outra.
"BRANCA", "Branca" e "branca " casam; "Branca/Cinza" e "Vermelha e Branca" não.

Graus: no Jiu-Jitsu a branca tem 1º a 4º grau (migração GR-01). O ponto de
partida é a branca sem grau ou no 1º grau; do 2º grau em diante o aluno
recebeu um grau — é graduação, tem data.
"""

import unicodedata


def _norm(txt):
    s = unicodedata.normalize("NFD", str(txt or "")).encode("ascii", "ignore").decode()
    return "".join(ch for ch in s.lower() if ch.isalnum())


def _grau_acima_do_primeiro(grau):
    """"2º grau", "3º GRAU"… → True. Sem grau, "1º grau", "INICIANTE", "." → False."""
    digitos = "".join(ch for ch in str(grau or "") if ch.isdigit())
    return bool(digitos) and int(digitos) >= 2


def faixa_eh_branca(nome_faixa, grau=None):
    """True só para a faixa branca pura (não Branca/Cinza, não Vermelha e Branca),
    sem grau ou no 1º grau — a branca de 2º grau em diante já é graduação."""
    return _norm(nome_faixa) == "branca" and not _grau_acima_do_primeiro(grau)


def graduacao_eh_branca(cur, graduacao_id):
    """Consulta `graduacao` e diz se o id é de uma faixa branca.

    Na falha de consulta devolve False: no pior caso o sistema aceita a data
    digitada, que é o comportamento de antes — melhor que travar o cadastro.
    """
    if not graduacao_id:
        return False
    try:
        cur.execute("SELECT faixa, graduacao FROM graduacao WHERE id = %s", (int(graduacao_id),))
        r = cur.fetchone()
    except Exception:
        return False
    if not r:
        return False
    faixa = r.get("faixa") if isinstance(r, dict) else r[0]
    grau = r.get("graduacao") if isinstance(r, dict) else (r[1] if len(r) > 1 else None)
    return faixa_eh_branca(faixa, grau)


def marcar_brancas(graduacoes):
    """Anota `branca=True/False` em cada graduação de uma lista de dicts.

    Os formulários de aluno usam isso para desligar o campo de data quando a
    faixa escolhida é a branca, sem o template precisar normalizar acento.
    """
    for g in graduacoes or []:
        try:
            g["branca"] = faixa_eh_branca(g.get("faixa"), g.get("graduacao"))
        except Exception:
            pass
    return graduacoes
