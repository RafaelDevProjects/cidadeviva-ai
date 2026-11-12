"""Configuração centralizada, lida de variáveis de ambiente (.env).

A escolha do modelo fica 100% em configuração: troque OPENROUTER_MODEL no .env
sem mexer em código. OPENROUTER_FALLBACK_MODELS define a ordem de modelos
reserva usados quando o principal falha (rate limit, indisponível, JSON inválido).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

try:  # python-dotenv é opcional em tempo de teste
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _list(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [m.strip() for m in raw.split(",") if m.strip()]


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY", ""))
    base_url: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    )
    # Modelos gratuitos (sufixo :free). A lista do OpenRouter muda com frequência;
    # confira https://openrouter.ai/collections/free-models e ajuste no .env.
    model: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_MODEL", "google/gemma-4-26b-a4b-it:free")
    )
    fallback_models: list[str] = field(
        default_factory=lambda: _list(
            "OPENROUTER_FALLBACK_MODELS",
            "nvidia/nemotron-3.5-lightning:free,baidu/ernie-5.5-flash-preview:free,"
            "nvidia/nemotron-3-ultra-550b-a55b:free",
        )
    )
    # Esforço de raciocínio para modelos que "pensam" (minimal|low|medium|high).
    # Vazio ou "off" = não envia o parâmetro.
    reasoning_effort: str = field(
        default_factory=lambda: (
            ""
            if os.getenv("REASONING_EFFORT", "low").strip().lower() in {"", "off"}
            else os.getenv("REASONING_EFFORT", "low").strip().lower()
        )
    )
    # Temperatura baixa para triagem: queremos respostas consistentes, não criativas.
    temperature_triagem: float = field(default_factory=lambda: _float("TEMPERATURE_TRIAGEM", 0.1))
    temperature_helper: float = field(default_factory=lambda: _float("TEMPERATURE_HELPER", 0.3))
    max_tokens: int = field(default_factory=lambda: _int("MAX_TOKENS", 2000))
    timeout_s: float = field(default_factory=lambda: _float("REQUEST_TIMEOUT_S", 30))
    max_retries: int = field(default_factory=lambda: _int("MAX_RETRIES", 2))
    # Pede JSON mode ao provedor (response_format). Nem todo modelo suporta;
    # se o provedor recusar, o cliente refaz a chamada sem esse parâmetro.
    use_json_mode: bool = field(
        default_factory=lambda: os.getenv("USE_JSON_MODE", "true").lower() == "true"
    )
    app_name: str = "CidadeViva Assistente"
    app_url: str = field(
        default_factory=lambda: os.getenv("APP_URL", "https://github.com/cidadeviva")
    )

    @property
    def models_in_order(self) -> list[str]:
        seen: list[str] = []
        for m in [self.model, *self.fallback_models]:
            if m not in seen:
                seen.append(m)
        return seen


def get_settings() -> Settings:
    return Settings()