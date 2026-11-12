"""Mascaramento de dados pessoais ANTES de enviar texto ao modelo (LGPD).

O modelo não precisa saber CPF, telefone ou e-mail do cidadão para classificar
um buraco. Mascaramos esses padrões e registramos quantos foram removidos.
"""
from __future__ import annotations

import re

_PATTERNS = [
    ("CPF", re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("TELEFONE", re.compile(r"(?:\(?\b\d{2}\)?\s?)?\b9?\d{4}[-\s]?\d{4}\b")),
]


def mask_pii(text: str) -> tuple[str, int]:
    count = 0
    for label, pat in _PATTERNS:
        text, n = pat.subn(f"[{label} REMOVIDO]", text)
        count += n
    return text, count
