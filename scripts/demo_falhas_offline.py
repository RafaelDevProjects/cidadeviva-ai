"""Demonstra, sem rede, como o pipeline reage a respostas ruins do modelo.

Uso:  python -m scripts.demo_falhas_offline
Cenários: JSON em markdown, texto sem JSON (reparo), enum inválido (reparo),
risco imediato com prioridade errada (guardrail) e LLM fora do ar (fallback seguro).
"""
from __future__ import annotations

import json
import logging

from app.config import Settings
from app.llm_client import LLMError, LLMResponse
from app.services import Assistente

BASE = {
    "categoria": "iluminacao_publica",
    "prioridade": "media",
    "orgao_responsavel": "Departamento de Iluminação Pública",
    "resumo": "Fio elétrico caído soltando faísca ao lado de ponto de ônibus.",
    "localizacao": {"texto_original": "Rua Ipê, 120", "logradouro": "Rua Ipê", "referencia": "ponto de ônibus", "bairro_ou_comunidade": "Cidade Tiradentes"},
    "risco_imediato": True,
    "justificativa_prioridade": "Fio exposto com faísca.",
    "dados_faltantes": [],
    "confianca": 0.9,
    "revisao_humana": False,
}


class Roteiro:
    def __init__(self, respostas):
        self.respostas = list(respostas)

    def chat(self, messages, *, temperature, json_mode=None, models=None):
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        print(f"   ↳ modelo respondeu: {r[:90]!r}{'…' if len(r) > 90 else ''}")
        return LLMResponse(r, "simulado:free", 10, {}, 1)


CENARIOS = [
    ("JSON dentro de bloco markdown", ["Claro!\n```json\n" + json.dumps(BASE) + "\n```"]),
    ("Texto sem JSON -> pedido de reparo", ["Desculpe, posso ajudar com isso!", json.dumps(BASE)]),
    ("Categoria inexistente -> reparo", [json.dumps({**BASE, "categoria": "eletrica"}), json.dumps(BASE)]),
    ("Três respostas inválidas -> fallback seguro", ["nada", "nada", "nada"]),
    ("Todos os modelos fora do ar -> fallback seguro", [LLMError("Todos os modelos falharam -> HTTP 503")]),
]


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="   [log %(levelname)s] %(message)s")
    relato = "Tem um fio caído soltando faísca na Rua Ipê, 120, Cidade Tiradentes, do lado do ponto de ônibus"
    for nome, respostas in CENARIOS:
        print(f"\n=== {nome} ===")
        a = Assistente(client=Roteiro(respostas), settings=Settings(api_key="offline"))
        out = a.triar(relato).model_dump(mode="json")
        r, m = out["resultado"], out["meta"]
        print(f"   resultado: categoria={r['categoria']} prioridade={r['prioridade']} "
              f"revisao_humana={r['revisao_humana']}")
        print(f"   meta: reparos_json={m['reparos_json']} fallback_seguro={m['fallback_seguro']} erro={m['erro']}")


if __name__ == "__main__":
    main()
