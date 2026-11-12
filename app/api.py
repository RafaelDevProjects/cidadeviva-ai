"""API REST (FastAPI).

Rodar:  uvicorn app.api:app --reload
Docs interativas: http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import __version__
from .config import get_settings
from .llm_client import LLMConfigError
from .schemas import HelperResponse, TriagemResponse
from .services import MAX_INPUT_CHARS, Assistente, InputError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="CidadeViva Assistente",
    version=__version__,
    description="Triagem de reportes urbanos/rurais e helper de dúvidas com IA generativa (OpenRouter).",
)

_assistente: Assistente | None = None


def get_assistente() -> Assistente:
    global _assistente
    if _assistente is None:
        _assistente = Assistente()
    return _assistente


class RelatoIn(BaseModel):
    relato: str = Field(..., min_length=1, max_length=MAX_INPUT_CHARS * 2,
                        examples=["Tem um buraco enorme na Av. Brasil perto do posto de saúde"])


class PerguntaIn(BaseModel):
    pergunta: str = Field(..., min_length=1, max_length=MAX_INPUT_CHARS * 2,
                          examples=["Como acompanho meu reporte?"])


@app.get("/health")
def health() -> dict:
    s = get_settings()
    return {
        "status": "ok",
        "versao": __version__,
        "modelo": s.model,
        "fallbacks": s.fallback_models,
        "api_key_configurada": bool(s.api_key),
    }


@app.post("/triagem", response_model=TriagemResponse)
def triagem(body: RelatoIn) -> TriagemResponse:
    try:
        return get_assistente().triar(body.relato)
    except InputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LLMConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/duvida", response_model=HelperResponse)
def duvida(body: PerguntaIn) -> HelperResponse:
    try:
        return get_assistente().responder(body.pergunta)
    except InputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LLMConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
