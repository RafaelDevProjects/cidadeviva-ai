import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.llm_client import LLMError, LLMResponse  # noqa: E402


@pytest.fixture
def settings():
    return Settings(
        api_key="sk-test",
        model="modelo/principal:free",
        fallback_models=["modelo/reserva:free"],
        reasoning_effort="low",
        max_retries=2,
        timeout_s=1,
    )


class FakeClient:
    """Simula o OpenRouterClient devolvendo respostas pré-definidas em sequência."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    def chat(self, messages, *, temperature, json_mode=None, models=None):
        self.chamadas.append(messages)
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        if isinstance(r, dict):
            r = json.dumps(r, ensure_ascii=False)
        return LLMResponse(content=r, model="modelo/principal:free", latency_ms=42, usage={}, attempts=1)


@pytest.fixture
def fake_client_factory():
    return FakeClient


TRIAGEM_OK = {
    "categoria": "buraco_via",
    "prioridade": "alta",
    "orgao_responsavel": "Secretaria de Infraestrutura / Obras",
    "resumo": "Buraco grande na Av. Brasil próximo ao posto de saúde.",
    "localizacao": {
        "texto_original": "Av. Brasil perto do posto de saúde",
        "logradouro": "Av. Brasil",
        "referencia": "perto do posto de saúde",
        "bairro_ou_comunidade": None,
    },
    "risco_imediato": False,
    "justificativa_prioridade": "Via de acesso a serviço de saúde.",
    "dados_faltantes": ["numero", "bairro"],
    "confianca": 0.85,
    "revisao_humana": False,
}

HELPER_OK = {
    "resposta": "Toque em Reportar problema na tela inicial.",
    "passos": ["Abra o app", "Toque em Reportar problema", "Descreva e envie"],
    "fontes": ["faq-03"],
    "dentro_do_escopo": True,
    "encaminhar_atendente": False,
    "confianca": 0.9,
}

__all__ = ["TRIAGEM_OK", "HELPER_OK", "LLMError"]