"""Testa o pipeline completo (prompt -> LLM -> JSON -> validação -> guardrails) com LLM simulado."""
import copy
import json

import pytest

from app.llm_client import LLMConfigError, LLMError
from app.privacy import mask_pii
from app.services import Assistente, InputError
from tests.conftest import HELPER_OK, TRIAGEM_OK


def make(fake_client_factory, settings, respostas):
    client = fake_client_factory(respostas)
    return Assistente(client=client, settings=settings), client


# ---------------------------------------------------------------- triagem
def test_triagem_feliz(fake_client_factory, settings):
    a, _ = make(fake_client_factory, settings, [TRIAGEM_OK])
    out = a.triar("Tem um buraco enorme na Av. Brasil perto do posto de saúde")
    assert out.resultado.categoria.value == "buraco_via"
    assert out.resultado.revisao_humana is False
    assert out.meta.reparos_json == 0
    assert out.meta.fallback_seguro is False


def test_prompt_tem_system_fewshot_e_delimitadores(fake_client_factory, settings):
    a, c = make(fake_client_factory, settings, [TRIAGEM_OK])
    a.triar("buraco na rua")
    msgs = c.chamadas[0]
    assert msgs[0]["role"] == "system" and "Responda APENAS com um objeto JSON" in msgs[0]["content"]
    assert [m["role"] for m in msgs[1:5]] == ["user", "assistant", "user", "assistant"]
    assert msgs[-1]["content"].endswith("<<<buraco na rua>>>")


def test_reparo_quando_json_invalido(fake_client_factory, settings):
    a, c = make(fake_client_factory, settings, ["Desculpe, não entendi", TRIAGEM_OK])
    out = a.triar("buraco")
    assert out.meta.reparos_json == 1
    assert out.resultado.categoria.value == "buraco_via"
    # a mensagem de reparo devolve o erro ao modelo
    assert "não é válida para o schema" in c.chamadas[1][-1]["content"]


def test_reparo_quando_enum_invalido(fake_client_factory, settings):
    ruim = {**TRIAGEM_OK, "categoria": "buracos"}
    a, c = make(fake_client_factory, settings, [ruim, TRIAGEM_OK])
    out = a.triar("buraco")
    assert out.meta.reparos_json == 1
    assert "categoria" in c.chamadas[1][-1]["content"]


def test_fallback_seguro_apos_reparos_esgotados(fake_client_factory, settings):
    a, _ = make(fake_client_factory, settings, ["lixo", "lixo", "lixo"])
    out = a.triar("tem lixo na esquina da rua")
    assert out.meta.fallback_seguro is True
    assert out.resultado.revisao_humana is True
    assert out.resultado.categoria.value == "outro"
    assert "tem lixo na esquina" in out.resultado.resumo


def test_fallback_seguro_quando_llm_indisponivel(fake_client_factory, settings):
    a, _ = make(fake_client_factory, settings, [LLMError("Todos os modelos falharam")])
    out = a.triar("buraco na rua")
    assert out.meta.fallback_seguro is True
    assert out.resultado.revisao_humana is True


def test_erro_de_configuracao_sobe(fake_client_factory, settings):
    a, _ = make(fake_client_factory, settings, [LLMConfigError("sem chave")])
    with pytest.raises(LLMConfigError):
        a.triar("buraco")


def test_guardrail_risco_imediato_vira_urgente(fake_client_factory, settings):
    r = {**TRIAGEM_OK, "risco_imediato": True, "prioridade": "media"}
    a, _ = make(fake_client_factory, settings, [r])
    out = a.triar("fio caído soltando faísca")
    assert out.resultado.prioridade.value == "urgente"
    assert "Ajustado para urgente" in out.resultado.justificativa_prioridade


def test_guardrail_baixa_confianca_pede_revisao(fake_client_factory, settings):
    r = {**TRIAGEM_OK, "confianca": 0.3}
    a, _ = make(fake_client_factory, settings, [r])
    assert a.triar("algo estranho").resultado.revisao_humana is True


def test_pii_mascarada_antes_de_ir_ao_modelo(fake_client_factory, settings):
    a, c = make(fake_client_factory, settings, [TRIAGEM_OK])
    a.triar("Buraco na rua. Meu CPF 123.456.789-00, tel (11) 98765-4321, email ana@x.com")
    enviado = c.chamadas[0][-1]["content"]
    assert "123.456.789-00" not in enviado
    assert "98765-4321" not in enviado
    assert "ana@x.com" not in enviado
    assert "[CPF REMOVIDO]" in enviado


@pytest.mark.parametrize("entrada", ["", "   ", None])
def test_entrada_vazia(fake_client_factory, settings, entrada):
    a, _ = make(fake_client_factory, settings, [])
    with pytest.raises(InputError):
        a.triar(entrada)


def test_entrada_longa_truncada(fake_client_factory, settings):
    a, c = make(fake_client_factory, settings, [TRIAGEM_OK])
    a.triar("buraco " * 1000)
    assert len(c.chamadas[0][-1]["content"]) < 2100


# ---------------------------------------------------------------- helper
def test_helper_injeta_contexto_recuperado(fake_client_factory, settings):
    a, c = make(fake_client_factory, settings, [HELPER_OK])
    out = a.responder("Como faço pra reportar um problema?")
    system = c.chamadas[0][0]["content"]
    assert "[faq-03]" in system
    assert "{{CONTEXTO}}" not in system
    assert out.resultado.fontes == ["faq-03"]


def test_helper_remove_fontes_inventadas(fake_client_factory, settings):
    r = copy.deepcopy(HELPER_OK)
    r["fontes"] = ["faq-03", "faq-99"]
    a, _ = make(fake_client_factory, settings, [r])
    out = a.responder("Como faço pra reportar um problema?")
    assert out.resultado.fontes == ["faq-03"]


def test_helper_sem_fonte_vira_baixa_confianca(fake_client_factory, settings):
    r = {**HELPER_OK, "fontes": []}
    a, _ = make(fake_client_factory, settings, [r])
    out = a.responder("Como faço pra reportar um problema?")
    assert out.resultado.confianca <= 0.4
    assert out.resultado.encaminhar_atendente is True


def test_helper_fallback_seguro(fake_client_factory, settings):
    a, _ = make(fake_client_factory, settings, [LLMError("fora do ar")])
    out = a.responder("como acompanho meu reporte")
    assert out.resultado.encaminhar_atendente is True
    assert out.meta.fallback_seguro is True


def test_helper_aceita_json_em_markdown(fake_client_factory, settings):
    texto = "Aqui está:\n```json\n" + json.dumps(HELPER_OK) + "\n```"
    a, _ = make(fake_client_factory, settings, [texto])
    out = a.responder("Como faço pra reportar um problema?")
    assert out.meta.reparos_json == 0


# ---------------------------------------------------------------- utilitários
def test_mask_pii_conta():
    texto, n = mask_pii("cpf 12345678900 e fone 11 912345678")
    assert n == 2 and "12345678900" not in texto
