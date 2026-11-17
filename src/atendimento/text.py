"""Utilitarios de texto."""
import re
import unicodedata


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def extract_order_id(text: str) -> str | None:
    """Pega o numero do pedido: 'pedido 12345', '#12345' ou um numero isolado de 5 a 8 digitos."""
    t = normalize(text)
    m = re.search(r"(?:pedido|numero|#)\s*#?\s*(\d{5,8})\b", t) or re.search(r"\b(\d{5,8})\b", t)
    return m.group(1) if m else None


def extract_amount(text: str) -> float | None:
    """Valor em reais citado pelo usuario (ex.: 'R$ 400'). Informativo: quem decide e a politica."""
    m = re.search(r"r\$\s*(\d+(?:[.,]\d{1,2})?)", normalize(text))
    return float(m.group(1).replace(",", ".")) if m else None
