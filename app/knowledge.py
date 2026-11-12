"""Recuperação simples de contexto (RAG leve, sem dependências pagas).

A base de conhecimento é um Markdown dividido em seções `## [id] Título`.
Para cada pergunta, pontuamos as seções por sobreposição de termos (com peso
TF-IDF simplificado e normalização de acentos) e injetamos as top-k no prompt.
É suficiente para uma base pequena e não exige banco vetorial nem embeddings pagos.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

DEFAULT_KB = Path(__file__).resolve().parent.parent / "knowledge_base" / "cidadeviva_faq.md"

_SECTION = re.compile(r"^##\s*\[(?P<id>[^\]]+)\]\s*(?P<title>.+)$", re.MULTILINE)
_TOKEN = re.compile(r"[a-z0-9]+")

STOPWORDS = set(
    """a o e de da do das dos em no na nos nas um uma para por com sem que se ou
    eu voce meu minha como qual quais quando onde porque pra pro ao aos as os
    nao sim ja tem ter esta estou isso esse essa este esta foi ser sao mais muito""".split()
)


@dataclass
class Section:
    id: str
    title: str
    body: str

    def render(self) -> str:
        return f"[{self.id}] {self.title}\n{self.body.strip()}"


def _normalize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    tokens = [t for t in _TOKEN.findall(text) if t not in STOPWORDS and len(t) > 1]
    # "stemming" por prefixo: reporto/reportar/reportes -> "report".
    # Simples, sem dependências, e funciona bem para conjugações do português.
    return [t[:6] for t in tokens]


class KnowledgeBase:
    def __init__(self, path: Path | str = DEFAULT_KB) -> None:
        raw = Path(path).read_text(encoding="utf-8")
        self.sections = self._parse(raw)
        self._tokens = [_normalize(s.title + " " + s.body) for s in self.sections]
        n = len(self.sections)
        df: dict[str, int] = {}
        for toks in self._tokens:
            for t in set(toks):
                df[t] = df.get(t, 0) + 1
        self._idf = {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()}

    @staticmethod
    def _parse(raw: str) -> list[Section]:
        matches = list(_SECTION.finditer(raw))
        sections = []
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
            sections.append(Section(m["id"].strip(), m["title"].strip(), raw[m.end() : end]))
        return sections

    def search(self, query: str, k: int = 3) -> list[Section]:
        q = set(_normalize(query))
        if not q:
            return []
        scored = []
        for sec, toks in zip(self.sections, self._tokens):
            tokset = set(toks)
            title_toks = set(_normalize(sec.title))
            score = sum(self._idf.get(t, 0) for t in q & tokset)
            score += 0.5 * sum(self._idf.get(t, 0) for t in q & title_toks)
            if score > 0:
                scored.append((score, sec))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:k]]

    def ids(self) -> set[str]:
        return {s.id for s in self.sections}
