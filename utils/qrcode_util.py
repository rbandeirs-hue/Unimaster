"""Geração de QR Code como PNG em base64 (para exibir via data:image/png;base64,...).

Usado, por exemplo, para gerar o QR Code do link de checkout da InfinitePay,
que não retorna um QR PIX próprio — o QR aponta para a URL de pagamento.
"""
import io
import base64


def gerar_qr_base64(texto):
    """Retorna o PNG do QR Code de `texto` codificado em base64 (str), ou None.

    O retorno NÃO inclui o prefixo 'data:image/png;base64,' — o template já o adiciona.
    """
    if not texto:
        return None
    try:
        import qrcode

        img = qrcode.make(str(texto))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None
