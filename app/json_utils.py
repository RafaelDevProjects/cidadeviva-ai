"""Extração tolerante de JSON a partir do texto do modelo.

Modelos pequenos e gratuitos às vezes:
- embrulham o JSON em ```json ... ```;
- escrevem uma frase antes ou depois ("Claro! Aqui está:");
- deixam vírgula sobrando antes de } ou ].
Esta função cobre esses casos sem usar eval.
"""
from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


class JSONExtractionError(ValueError):
    pass


def extract_json(text: str) -> dict[str, Any]:
    if not text or not text.strip():
        raise JSONExtractionError("texto vazio")

    candidates: list[str] = []
    for m in _FENCE.finditer(text):
        candidates.append(m.group(1))
    candidates.append(text)

    for cand in candidates:
        obj = _first_object(cand)
        if obj is None:
            continue
        for attempt in (obj, _TRAILING_COMMA.sub(r"\1", obj)):
            try:
                parsed = json.loads(attempt)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    raise JSONExtractionError("nenhum objeto JSON válido encontrado")


def _first_object(text: str) -> str | None:
    """Devolve o primeiro objeto {...} balanceado, respeitando strings."""
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        start = text.find("{", start + 1)
    return None
