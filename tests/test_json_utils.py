import pytest

from app.json_utils import JSONExtractionError, extract_json


def test_json_puro():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_json_em_bloco_de_codigo():
    assert extract_json('Claro! Aqui está:\n```json\n{"a": 1}\n```\nQualquer dúvida...') == {"a": 1}


def test_texto_antes_e_depois_sem_fence():
    assert extract_json('Segue a resposta: {"x": "y"} espero ter ajudado') == {"x": "y"}


def test_virgula_sobrando():
    assert extract_json('{"a": [1, 2,], "b": 3,}') == {"a": [1, 2], "b": 3}


def test_chaves_dentro_de_string():
    assert extract_json('{"resumo": "texto com { e } dentro"}') == {"resumo": "texto com { e } dentro"}


def test_objeto_aninhado():
    assert extract_json('{"loc": {"rua": "X"}, "ok": true}') == {"loc": {"rua": "X"}, "ok": True}


@pytest.mark.parametrize("texto", ["", "   ", "sem json aqui", "{quebrado: sim", "[1, 2, 3]"])
def test_falhas(texto):
    with pytest.raises(JSONExtractionError):
        extract_json(texto)
