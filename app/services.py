"""Casos de uso do assistente: triagem de reporte e helper de dúvidas.

Fluxo de cada chamada (os dois casos seguem o mesmo pipeline):

    entrada -> validação/limpeza (PII, tamanho) -> montagem do prompt
           -> LLM (retry + fallback de modelo)
           -> extração de JSON -> validação pydantic
           -> (se falhar) pedido de reparo ao modelo, até N vezes
           -> regras de negócio pós-modelo (guardrails)
           -> (se tudo falhar) resposta segura marcada para revisão humana
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .config import Settings, get_settings
from .json_utils import JSONExtractionError, extract_json
from .knowledge import KnowledgeBase
from .llm_client import LLMConfigError, LLMError, OpenRouterClient
from .privacy import mask_pii
from .schemas import (
    Categoria,
    HelperResponse,
    HelperResult,
    Localizacao,
    Meta,
    Prioridade,
    TriagemResponse,
    TriagemResult,
)

log = logging.getLogger("cidadeviva.services")

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
MAX_INPUT_CHARS = 2000
MAX_REPAIRS = 2
LIMIAR_CONFIANCA = 0.6

T = TypeVar("T", bound=BaseModel)


class InputError(ValueError):
    pass


@lru_cache
def _load(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _clean_input(text: str) -> tuple[str, int]:
    if text is None or not text.strip():
        raise InputError("O texto não pode estar vazio.")
    text = " ".join(text.split())  # normaliza espaços/quebras
    if len(text) > MAX_INPUT_CHARS:
        text = text[:MAX_INPUT_CHARS]
    return mask_pii(text)


class Assistente:
    def __init__(
        self,
        client: OpenRouterClient | None = None,
        kb: KnowledgeBase | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client or OpenRouterClient(self.settings)
        self.kb = kb or KnowledgeBase()

    # ============================================================ TRIAGEM
    def build_triagem_messages(self, relato: str) -> list[dict[str, str]]:
        system = _load("triagem_system.md")
        exemplos = json.loads(_load("triagem_exemplos.json"))
        msgs = [{"role": "system", "content": system}]
        # few-shot: pares usuário/assistente ensinam o formato e o tom esperado
        for ex in exemplos:
            msgs.append({"role": "user", "content": f"RELATO DO CIDADÃO:\n<<<{ex['relato']}>>>"})
            msgs.append({"role": "assistant", "content": json.dumps(ex["saida"], ensure_ascii=False)})
        # delimitadores <<< >>> separam dado de instrução (mitiga prompt injection)
        msgs.append({"role": "user", "content": f"RELATO DO CIDADÃO:\n<<<{relato}>>>"})
        return msgs

    def triar(self, relato: str) -> TriagemResponse:
        texto, pii = _clean_input(relato)
        msgs = self.build_triagem_messages(texto)
        result, meta = self._run(msgs, TriagemResult, self.settings.temperature_triagem)
        if result is None:
            result = self._triagem_segura(texto)
        else:
            result = self._guardrails_triagem(result)
        if pii:
            log.info("%d dado(s) pessoal(is) mascarado(s) antes do envio ao modelo.", pii)
        return TriagemResponse(resultado=result, meta=meta)

    @staticmethod
    def _guardrails_triagem(r: TriagemResult) -> TriagemResult:
        data = r.model_dump()
        # Regra de negócio: risco imediato SEMPRE é urgente (o modelo pode esquecer).
        if r.risco_imediato and r.prioridade != Prioridade.urgente:
            data["prioridade"] = Prioridade.urgente
            data["justificativa_prioridade"] = (
                r.justificativa_prioridade + " [Ajustado para urgente: risco imediato.]"
            )[:400]
        # Baixa confiança ou categoria 'outro' -> um humano confere antes do RPA enviar.
        if r.confianca < LIMIAR_CONFIANCA or r.categoria == Categoria.outro:
            data["revisao_humana"] = True
        return TriagemResult(**data)

    @staticmethod
    def _triagem_segura(texto: str) -> TriagemResult:
        """Resposta de contingência: nunca descarta o relato do cidadão."""
        return TriagemResult(
            categoria=Categoria.outro,
            prioridade=Prioridade.media,
            orgao_responsavel="Ouvidoria Municipal",
            resumo=(texto[:270] + "…") if len(texto) > 270 else (texto if len(texto) >= 5 else "Relato sem detalhes"),
            localizacao=Localizacao(texto_original=None),
            risco_imediato=False,
            justificativa_prioridade="Classificação automática indisponível; encaminhado para triagem manual.",
            dados_faltantes=["classificacao_automatica"],
            confianca=0.0,
            revisao_humana=True,
        )

    # ============================================================ HELPER
    def build_helper_messages(self, pergunta: str, k: int = 3) -> tuple[list[dict[str, str]], list[str]]:
        secoes = self.kb.search(pergunta, k=k)
        contexto = "\n\n".join(s.render() for s in secoes) or "(nenhum trecho relevante encontrado)"
        system = _load("helper_system.md").replace("{{CONTEXTO}}", contexto)
        msgs = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"PERGUNTA DO USUÁRIO:\n<<<{pergunta}>>>"},
        ]
        return msgs, [s.id for s in secoes]

    def responder(self, pergunta: str) -> HelperResponse:
        texto, _ = _clean_input(pergunta)
        msgs, ids_contexto = self.build_helper_messages(texto)
        result, meta = self._run(msgs, HelperResult, self.settings.temperature_helper)
        if result is None:
            result = HelperResult(
                resposta=(
                    "Desculpe, não consegui responder agora. Tente novamente em alguns minutos "
                    "ou fale com o atendimento pelo menu Ajuda > Falar com atendente."
                ),
                passos=[],
                fontes=[],
                dentro_do_escopo=True,
                encaminhar_atendente=True,
                confianca=0.0,
            )
        else:
            result = self._guardrails_helper(result, ids_contexto)
        return HelperResponse(resultado=result, meta=meta)

    def _guardrails_helper(self, r: HelperResult, ids_contexto: list[str]) -> HelperResult:
        data = r.model_dump()
        # Fontes só podem ser seções que realmente foram enviadas no contexto.
        validas = [f for f in r.fontes if f in ids_contexto]
        data["fontes"] = validas
        data["passos"] = r.passos[:6]
        # Resposta "dentro do escopo" sem nenhuma fonte real = possível alucinação.
        if r.dentro_do_escopo and not validas and not r.encaminhar_atendente:
            data["confianca"] = min(r.confianca, 0.4)
            data["encaminhar_atendente"] = True
        return HelperResult(**data)

    # ============================================================ PIPELINE
    def _run(self, msgs: list[dict[str, str]], schema: type[T], temperature: float) -> tuple[T | None, Meta]:
        meta = Meta()
        conversa = list(msgs)
        for tentativa in range(MAX_REPAIRS + 1):
            try:
                resp = self.client.chat(conversa, temperature=temperature)
            except LLMConfigError:
                raise
            except LLMError as exc:
                log.error("Falha no LLM: %s", exc)
                meta.erro = str(exc)[:300]
                meta.fallback_seguro = True
                return None, meta

            meta.modelo = resp.model
            meta.latencia_ms = (meta.latencia_ms or 0) + resp.latency_ms
            meta.tentativas += resp.attempts

            try:
                obj = extract_json(resp.content)
                validado = schema.model_validate(obj)
                meta.erro = None  # reparos bem-sucedidos ficam registrados em reparos_json
                return validado, meta
            except (JSONExtractionError, ValidationError) as exc:
                erro = _resumo_erro(exc)
                log.warning("Saída inválida (tentativa %d): %s", tentativa + 1, erro)
                meta.erro = erro
                if tentativa == MAX_REPAIRS:
                    break
                meta.reparos_json += 1
                # Prompt de reparo: devolve ao modelo o que ele escreveu + o erro exato.
                conversa = conversa + [
                    {"role": "assistant", "content": resp.content[:3000]},
                    {
                        "role": "user",
                        "content": (
                            "Sua resposta anterior não é válida para o schema exigido. "
                            f"Erro: {erro}. Responda novamente APENAS com o objeto JSON "
                            "corrigido, seguindo exatamente o formato e os valores permitidos."
                        ),
                    },
                ]
        meta.fallback_seguro = True
        return None, meta


def _resumo_erro(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        partes = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]]
        return "; ".join(partes)
    return str(exc)
