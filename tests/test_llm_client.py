"""Testa retry, fallback de modelo e tratamento de erros HTTP sem rede (sessão simulada)."""
import pytest
import requests

from app.llm_client import LLMConfigError, LLMError, OpenRouterClient


class FakeResp:
    def __init__(self, status, data=None, text=""):
        self.status_code = status
        self._data = data
        self.text = text or (str(data) if data else "")

    def json(self):
        if self._data is None:
            raise ValueError("not json")
        return self._data


def ok(content, model="modelo/principal:free"):
    return FakeResp(200, {"model": model, "choices": [{"message": {"content": content}}], "usage": {"total_tokens": 10}})


class FakeSession:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.payloads = []

    def post(self, url, json, headers, timeout):
        self.payloads.append(json)
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


MSGS = [{"role": "user", "content": "oi"}]


def make(settings, respostas):
    sess = FakeSession(respostas)
    return OpenRouterClient(settings, session=sess, sleep=lambda s: None), sess


def test_sucesso_envia_modelo_e_parametros(settings):
    c, sess = make(settings, [ok('{"a":1}')])
    r = c.chat(MSGS, temperature=0.1)
    assert r.content == '{"a":1}'
    p = sess.payloads[0]
    assert p["model"] == "modelo/principal:free"
    assert p["temperature"] == 0.1
    assert p["response_format"] == {"type": "json_object"}


def test_429_pula_direto_para_proximo_modelo(settings):
    c, sess = make(settings, [FakeResp(429, text="rate-limited upstream"), ok("x", "modelo/reserva:free")])
    r = c.chat(MSGS, temperature=0)
    assert r.content == "x"
    assert [p["model"] for p in sess.payloads] == ["modelo/principal:free", "modelo/reserva:free"]


def test_retry_em_503_depois_sucesso(settings):
    c, _ = make(settings, [FakeResp(503), ok("x")])
    r = c.chat(MSGS, temperature=0)
    assert r.content == "x"
    assert r.attempts == 2


def test_envia_parametro_de_raciocinio(settings):
    c, sess = make(settings, [ok("x")])
    c.chat(MSGS, temperature=0)
    assert sess.payloads[0]["reasoning"] == {"effort": "low", "exclude": True}


def test_raciocinio_esgotou_tokens_pula_modelo_sem_repetir(settings):
    vazio_por_limite = FakeResp(200, {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]})
    c, sess = make(settings, [vazio_por_limite, ok("x", "modelo/reserva:free")])
    r = c.chat(MSGS, temperature=0)
    assert r.model == "modelo/reserva:free"
    assert len(sess.payloads) == 2  # não repetiu o modelo que esgotou tokens


def test_modelo_rejeita_reasoning_refaz_sem(settings):
    c, sess = make(settings, [FakeResp(400, text="reasoning is not supported for this model"), ok("x")])
    assert c.chat(MSGS, temperature=0).content == "x"
    assert "reasoning" in sess.payloads[0]
    assert "reasoning" not in sess.payloads[1]


def test_timeout_e_retry(settings):
    c, _ = make(settings, [requests.Timeout(), ok("x")])
    assert c.chat(MSGS, temperature=0).content == "x"


def test_fallback_para_segundo_modelo(settings):
    # 3 falhas no principal (1 + 2 retries) -> passa para o reserva
    c, sess = make(settings, [FakeResp(503), FakeResp(503), FakeResp(503), ok("ok", "modelo/reserva:free")])
    r = c.chat(MSGS, temperature=0)
    assert r.model == "modelo/reserva:free"
    assert sess.payloads[-1]["model"] == "modelo/reserva:free"


def test_todos_modelos_falham(settings):
    c, _ = make(settings, [FakeResp(500)] * 6)
    with pytest.raises(LLMError, match="Todos os modelos falharam"):
        c.chat(MSGS, temperature=0)


def test_chave_invalida_nao_tenta_fallback(settings):
    c, sess = make(settings, [FakeResp(401, text="unauthorized")])
    with pytest.raises(LLMConfigError):
        c.chat(MSGS, temperature=0)
    assert len(sess.payloads) == 1


def test_sem_api_key():
    from app.config import Settings

    c = OpenRouterClient(Settings(api_key=""), session=FakeSession([]))
    with pytest.raises(LLMConfigError):
        c.chat(MSGS, temperature=0)


def test_json_mode_nao_suportado_refaz_sem(settings):
    c, sess = make(settings, [FakeResp(400, text="response_format is not supported"), ok("x")])
    assert c.chat(MSGS, temperature=0).content == "x"
    assert "response_format" in sess.payloads[0]
    assert "response_format" not in sess.payloads[1]


def test_erro_dentro_de_200(settings):
    corpo = {"error": {"message": "Provider returned error", "code": 502}}
    c, _ = make(settings, [FakeResp(200, corpo), ok("x")])
    assert c.chat(MSGS, temperature=0).content == "x"


def test_conteudo_vazio_conta_como_transitorio(settings):
    c, _ = make(settings, [ok(""), ok("x")])
    assert c.chat(MSGS, temperature=0).content == "x"