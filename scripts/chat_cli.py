"""Chat no terminal com o assistente.

Uso:
    python -m scripts.chat_cli            # modo helper (dúvidas)
    python -m scripts.chat_cli --triagem  # modo triagem (reportes)

Digite 'sair' para encerrar, '/modo' para alternar entre helper e triagem.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from app.llm_client import LLMConfigError
from app.services import Assistente, InputError


def main() -> int:
    parser = argparse.ArgumentParser(description="Chat CidadeViva")
    parser.add_argument("--triagem", action="store_true", help="inicia no modo triagem")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

    assistente = Assistente()
    modo = "triagem" if args.triagem else "helper"
    print(f"CidadeViva Assistente | modelo: {assistente.settings.model} | modo: {modo}")
    print("Digite 'sair' para encerrar e '/modo' para alternar.\n")

    while True:
        try:
            texto = input("você> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if texto.lower() in {"sair", "exit", "quit"}:
            break
        if texto == "/modo":
            modo = "helper" if modo == "triagem" else "triagem"
            print(f"(modo agora: {modo})")
            continue
        try:
            out = assistente.triar(texto) if modo == "triagem" else assistente.responder(texto)
        except InputError as exc:
            print(f"! {exc}")
            continue
        except LLMConfigError as exc:
            print(f"! Configuração: {exc}")
            return 1

        if modo == "helper":
            r = out.resultado
            print(f"\nassistente> {r.resposta}")
            for i, p in enumerate(r.passos, 1):
                print(f"   {i}. {p}")
            if r.encaminhar_atendente:
                print("   (sugestão: falar com um atendente)")
        print("\n--- JSON ---")
        print(json.dumps(out.model_dump(mode="json"), ensure_ascii=False, indent=2))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
