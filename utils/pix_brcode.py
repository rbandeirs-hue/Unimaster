# -*- coding: utf-8 -*-
"""BR Code do PIX (copia-e-cola) a partir da chave da academia.

O PIX que o aluno vê hoje vem do gateway, junto com a cobrança. Quando o
gateway está fora — ou a academia não usa nenhum — não sobra forma de pagar.
Aqui montamos um código a partir da chave própria da academia, que funciona
independentemente de qualquer integração.

O formato é o EMV-QRCPS do Banco Central: campos `ID + tamanho(2) + valor`,
encadeados, com o CRC16 no fim. A especificação está em
"Manual de Padrões para Iniciação do Pix", BCB.

Uso:
    from utils.pix_brcode import montar_brcode
    codigo = montar_brcode("11999999999", "ACADEMIA JUDO", "RECIFE", 150.0)
"""
import re
import unicodedata

# Limites do padrão: nome do recebedor 25, cidade 15.
MAX_BENEFICIARIO = 25
MAX_CIDADE = 15


def _campo(identificador, valor):
    """Um campo EMV: id + tamanho em 2 dígitos + valor."""
    valor = str(valor)
    return f"{identificador}{len(valor):02d}{valor}"


def _ascii_maiusculo(texto, limite):
    """Sem acento, em maiúsculas e dentro do limite.

    O padrão aceita só um subconjunto ASCII nesses campos; acento faz parte dos
    aparelhos recusarem o código na leitura.
    """
    txt = unicodedata.normalize("NFD", str(texto or ""))
    txt = "".join(c for c in txt if unicodedata.category(c) != "Mn")
    txt = re.sub(r"[^A-Za-z0-9 .\-]", "", txt).strip().upper()
    return txt[:limite] or "NAO INFORMADO"[:limite]


def crc16(payload):
    """CRC-16/CCITT-FALSE — o que o padrão exige (poli 0x1021, inicial 0xFFFF)."""
    crc = 0xFFFF
    for byte in payload.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return f"{crc:04X}"


TIPOS_CHAVE = ("cpf", "cnpj", "telefone", "email", "aleatoria")


def limpar_chave(chave, tipo=None):
    """Formata a chave como o BR Code exige, conforme o tipo declarado.

    O tipo não é firula: CPF e celular brasileiro têm 11 dígitos, e adivinhar
    pelo formato errava metade das vezes. Um celular digitado sem pontuação
    virava CPF, e o banco respondia que a chave não existe. Com o tipo vindo do
    cadastro não há palpite.

    `tipo=None` mantém a detecção antiga, só para cadastros anteriores à coluna.
    """
    bruta = str(chave or "").strip()
    if not bruta:
        return ""
    digitos = re.sub(r"\D", "", bruta)
    tipo = (tipo or "").strip().lower()

    if tipo in ("cpf", "cnpj"):
        return digitos
    if tipo == "telefone":
        # Formato E.164, que é o que o padrão exige para chave de celular.
        if bruta.startswith("+"):
            return "+" + digitos
        if digitos.startswith("55") and len(digitos) >= 12:
            return "+" + digitos
        return "+55" + digitos
    if tipo == "email":
        return bruta.lower().replace(" ", "")
    if tipo == "aleatoria":
        return bruta.replace(" ", "").lower()

    # --- sem tipo declarado: heurística de compatibilidade ------------------
    if "@" in bruta:
        return bruta.lower()
    if bruta.startswith("+"):
        return "+" + digitos
    if len(digitos) in (10, 11) and re.fullmatch(r"[\d()\-\s+]+", bruta) and not bruta.isdigit():
        # Pontuação de telefone: "(81) 99587-8180". Sem pontuação é ambíguo com
        # CPF, e aí preferimos CPF — por isso o tipo declarado existe.
        return "+55" + digitos
    if len(digitos) in (11, 14) and re.fullmatch(r"[\d.\-/\s]+", bruta):
        return digitos
    return bruta.replace(" ", "")


def validar_chave(chave, tipo):
    """Mensagem de erro quando a chave não combina com o tipo, ou None."""
    bruta = str(chave or "").strip()
    if not bruta:
        return None
    digitos = re.sub(r"\D", "", bruta)
    tipo = (tipo or "").strip().lower()
    if tipo == "cpf" and len(digitos) != 11:
        return "CPF deve ter 11 dígitos."
    if tipo == "cnpj" and len(digitos) != 14:
        return "CNPJ deve ter 14 dígitos."
    if tipo == "telefone" and len(digitos) not in (10, 11, 12, 13):
        return "Telefone deve ter DDD + número (ex.: 81 99587-8180)."
    if tipo == "email" and "@" not in bruta:
        return "E-mail inválido."
    if tipo == "aleatoria" and len(bruta.replace("-", "")) != 32:
        return "Chave aleatória tem 32 caracteres (formato UUID)."
    if tipo not in TIPOS_CHAVE:
        return "Escolha o tipo da chave PIX."
    return None


def montar_brcode(chave, beneficiario, cidade, valor=None, txid="***", tipo=None):
    """Devolve o copia-e-cola, ou None quando não há chave para usar.

    `valor` entra no código quando informado — assim o aluno não digita o
    valor à mão e não paga a menos por engano. `txid` fica em "***" porque a
    baixa desse pagamento é manual, pelo comprovante: não há o que conciliar
    automaticamente e "***" é o que todo banco aceita num código estático.
    """
    chave = limpar_chave(chave, tipo)
    if not chave:
        return None

    # O identificador vai em MINÚSCULAS, como está no manual do BCB e como
    # geram os PSPs de verdade (conferido contra um código emitido pelo Cora).
    # Em maiúsculas, banco que compara a string sem normalizar recusa o código
    # com um "pagamento falhou" genérico.
    conta = _campo("00", "br.gov.bcb.pix") + _campo("01", chave)

    partes = [
        _campo("00", "01"),                                  # formato do payload
        _campo("26", conta),                                 # dados do recebedor
        _campo("52", "0000"),                                # categoria do comerciante
        _campo("53", "986"),                                 # moeda: BRL
    ]
    if valor is not None:
        try:
            v = float(valor)
        except (TypeError, ValueError):
            v = 0.0
        if v > 0:
            partes.append(_campo("54", f"{v:.2f}"))
    partes += [
        _campo("58", "BR"),                                  # país
        _campo("59", _ascii_maiusculo(beneficiario, MAX_BENEFICIARIO)),
        _campo("60", _ascii_maiusculo(cidade, MAX_CIDADE)),
        _campo("62", _campo("05", txid or "***")),           # dados adicionais
    ]

    payload = "".join(partes) + "6304"                       # o CRC entra depois de "6304"
    return payload + crc16(payload)


def qrcode_base64(texto):
    """PNG do BR Code em base64, para embutir na página. None se não der."""
    if not texto:
        return None
    try:
        import base64
        import io

        import qrcode

        img = qrcode.make(texto)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        # Sem a biblioteca ou com erro de geração, a página mostra só o
        # copia-e-cola — que já resolve o pagamento.
        return None
