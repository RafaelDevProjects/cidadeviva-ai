import pytest

from app.knowledge import KnowledgeBase


@pytest.fixture(scope="module")
def kb():
    return KnowledgeBase()


def test_carrega_secoes(kb):
    assert len(kb.sections) >= 10
    assert "faq-03" in kb.ids()


@pytest.mark.parametrize(
    "pergunta,esperado",
    [
        ("como reporto um buraco?", "faq-03"),
        ("apareceu erro E-102", "faq-07"),
        ("não tenho internet no sítio", "faq-06"),
        ("a foto da conta de luz não é reconhecida", "faq-08"),
        ("quero excluir minha conta, e meus dados?", "faq-09"),
        ("cadastro com conta de luz", "faq-02"),
    ],
)
def test_recupera_secao_certa_no_top3(kb, pergunta, esperado):
    ids = [s.id for s in kb.search(pergunta, k=3)]
    assert esperado in ids, ids


def test_pergunta_fora_do_escopo_traz_pouco(kb):
    assert kb.search("receita de bolo de cenoura") == []
