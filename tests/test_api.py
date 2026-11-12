"""Testes dos endpoints. Exigem fastapi + httpx (pip install -r requirements.txt)."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

import app.api as api  # noqa: E402
from app.services import Assistente  # noqa: E402
from tests.conftest import HELPER_OK, TRIAGEM_OK, FakeClient  # noqa: E402


@pytest.fixture
def client(settings):
    api._assistente = Assistente(client=FakeClient([TRIAGEM_OK, HELPER_OK]), settings=settings)
    yield TestClient(api.app)
    api._assistente = None


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_triagem(client):
    r = client.post("/triagem", json={"relato": "buraco na Av. Brasil"})
    assert r.status_code == 200
    assert r.json()["resultado"]["categoria"] == "buraco_via"


def test_duvida(client):
    client.post("/triagem", json={"relato": "x buraco"})  # consome a 1ª resposta
    r = client.post("/duvida", json={"pergunta": "como reporto um problema?"})
    assert r.status_code == 200
    assert r.json()["resultado"]["fontes"] == ["faq-03"]


def test_entrada_vazia_422(client):
    assert client.post("/triagem", json={"relato": "   "}).status_code == 422
