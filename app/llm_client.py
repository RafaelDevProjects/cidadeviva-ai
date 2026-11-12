"""Cliente mínimo e robusto para a API do OpenRouter (compatível com OpenAI).

Responsabilidades:
- montar a requisição (modelo, temperatura, max_tokens, JSON mode e raciocínio opcionais);
- aplicar timeout;
- repetir com backoff exponencial em erros transitórios (timeout, 5xx, resposta malformada);
- trocar para o próximo modelo da lista quando um modelo não vai conseguir responder
  (rate limit, raciocínio que esgota o limite de tokens, erro definitivo);
- devolver texto + metadados (modelo usado, tokens, latência) para auditoria.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests

from .config import Settings, get_settings

log = logging.getLogger("cidadeviva.llm")

TRANSIENT_STATUS = {408, 500, 502, 503, 504}
RATE_LIMIT_STATUS = 429


class LLMError(Exception):
    """Falha definitiva ao falar com o modelo (após retries e fallbacks)."""


class LLMConfigError(LLMError):
    """Configuração inválida (ex.: falta de API key)."""


@dataclass
class LLMResponse:
    content: str
    model: str
    latency_ms: int
    usage: dict[str, Any]
    attempts: int


class OpenRouterClient:
    def __init__(
        self,
        settings: Settings | None = None,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings or get_settings()
        self.session = session or requests.Session()
        self._sleep = sleep

    # ------------------------------------------------------------------ público
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        json_mode: bool | None = None,
        models: list[str] | None = None,
    ) -> LLMResponse:
        if not self.settings.api_key:
            raise LLMConfigError(
                "OPENROUTER_API_KEY não configurada. Copie .env.example para .env e preencha."
            )

        json_mode = self.settings.use_json_mode if json_mode is None else json_mode
        errors: list[str] = []
        total_attempts = 0

        for model in models or self.settings.models_in_order:
            try:
                resp, attempts = self._call_with_retry(model, messages, temperature, json_mode)
                total_attempts += attempts
                resp.attempts = total_attempts
                return resp
            except LLMConfigError:
                raise  # chave errada não melhora trocando de modelo
            except _ModelFailed as exc:
                total_attempts += exc.attempts
                log.warning("Modelo %s falhou: %s. Tentando próximo.", model, exc)
                errors.append(f"{model}: {_short(str(exc))}")

        raise LLMError("Todos os modelos falharam -> " + " | ".join(errors))

    # ----------------------------------------------------------------- interno
    def _call_with_retry(
        self, model: str, messages: list[dict[str, str]], temperature: float, json_mode: bool
    ) -> tuple[LLMResponse, int]:
        opts = {"json_mode": json_mode, "reasoning": bool(self.settings.reasoning_effort)}
        last_err = "erro desconhecido"
        attempt = 0
        while attempt <= self.settings.max_retries:
            attempt += 1
            try:
                return self._call_once(model, messages, temperature, **opts), attempt
            except _TransientError as exc:
                last_err = str(exc)
                wait = min(2 ** (attempt - 1), 8)
                log.info("Erro transitório em %s (%s). Nova tentativa em %ss.", model, _short(last_err), wait)
                self._sleep(wait)
            except _ParamUnsupported as exc:
                # Modelo recusou um parâmetro opcional: desliga e refaz (não conta como tentativa).
                log.info("%s não aceita '%s'; repetindo sem esse parâmetro.", model, exc.param)
                opts[exc.param] = False
                attempt -= 1
            except _SkipModel as exc:
                # Não adianta insistir neste modelo agora: vai direto para o próximo.
                raise _ModelFailed(str(exc), attempt) from exc
            except LLMConfigError:
                raise
            except LLMError as exc:
                raise _ModelFailed(str(exc), attempt) from exc
        raise _ModelFailed(last_err, attempt)

    def _call_once(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        *,
        json_mode: bool,
        reasoning: bool,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": self.settings.max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if reasoning:
            # Modelos que "pensam" antes de responder gastam tokens de raciocínio do mesmo
            # limite max_tokens. Esforço baixo + exclude deixa espaço para o JSON final.
            payload["reasoning"] = {"effort": self.settings.reasoning_effort, "exclude": True}

        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
            # Cabeçalhos opcionais recomendados pelo OpenRouter para identificar o app.
            "HTTP-Referer": self.settings.app_url,
            "X-Title": self.settings.app_name,
        }

        start = time.perf_counter()
        try:
            r = self.session.post(
                f"{self.settings.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.settings.timeout_s,
            )
        except requests.Timeout as exc:
            raise _TransientError(f"timeout após {self.settings.timeout_s}s") from exc
        except requests.ConnectionError as exc:
            raise _TransientError(f"falha de conexão: {exc}") from exc
        latency = int((time.perf_counter() - start) * 1000)

        if r.status_code == RATE_LIMIT_STATUS:
            # Modelos gratuitos ficam em rate limit por minutos; esperar segundos raramente
            # resolve. Melhor tentar o próximo modelo da lista imediatamente.
            raise _SkipModel(f"rate limit (HTTP 429): {r.text[:160]}")
        if r.status_code in TRANSIENT_STATUS:
            raise _TransientError(f"HTTP {r.status_code}: {r.text[:200]}")
        if r.status_code == 400:
            body = r.text.lower()
            if json_mode and "response_format" in body:
                raise _ParamUnsupported("json_mode")
            if reasoning and "reasoning" in body:
                raise _ParamUnsupported("reasoning")
        if r.status_code in (401, 403):
            raise LLMConfigError(f"HTTP {r.status_code}: chave inválida ou sem permissão")
        if r.status_code >= 400:
            raise LLMError(f"HTTP {r.status_code}: {r.text[:200]}")

        try:
            data = r.json()
        except ValueError as exc:
            raise _TransientError("resposta não é JSON") from exc

        # O OpenRouter pode devolver 200 com um objeto "error" dentro.
        if "error" in data:
            msg = data["error"].get("message", str(data["error"]))
            code = data["error"].get("code")
            if code == RATE_LIMIT_STATUS:
                raise _SkipModel(f"rate limit: {msg}")
            if code in TRANSIENT_STATUS:
                raise _TransientError(msg)
            raise LLMError(msg)

        try:
            choice = data["choices"][0]
            content = choice["message"].get("content") or ""
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise _TransientError("resposta sem choices/message") from exc

        if not content.strip():
            if choice.get("finish_reason") == "length":
                # O raciocínio interno consumiu todo o max_tokens: repetir dá o mesmo resultado.
                raise _SkipModel(
                    "raciocínio do modelo esgotou max_tokens antes da resposta "
                    "(aumente MAX_TOKENS ou use outro modelo)"
                )
            raise _TransientError("modelo devolveu conteúdo vazio")

        return LLMResponse(
            content=content,
            model=data.get("model", model),
            latency_ms=latency,
            usage=data.get("usage", {}),
            attempts=1,
        )


def _short(text: str, n: int = 140) -> str:
    return text if len(text) <= n else text[:n] + "…"


class _TransientError(Exception):
    """Vale tentar de novo o mesmo modelo depois de esperar."""


class _SkipModel(Exception):
    """Não vale insistir neste modelo agora; passar para o próximo."""


class _ParamUnsupported(Exception):
    def __init__(self, param: str) -> None:
        super().__init__(param)
        self.param = param


class _ModelFailed(LLMError):
    def __init__(self, msg: str, attempts: int) -> None:
        super().__init__(msg)
        self.attempts = attempts