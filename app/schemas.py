"""Contratos de saída (JSON) do assistente.

Toda resposta do modelo é validada contra estes schemas antes de chegar ao
usuário ou ao robô de RPA. Se não passar, o serviço tenta reparar e, em último
caso, devolve uma resposta segura marcada para revisão humana.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class Categoria(str, Enum):
    buraco_via = "buraco_via"
    iluminacao_publica = "iluminacao_publica"
    lixo_entulho = "lixo_entulho"
    arvore_poda = "arvore_poda"
    calcada_acessibilidade = "calcada_acessibilidade"
    agua_esgoto = "agua_esgoto"
    sinalizacao_transito = "sinalizacao_transito"
    area_rural_estrada = "area_rural_estrada"
    outro = "outro"


class Prioridade(str, Enum):
    baixa = "baixa"
    media = "media"
    alta = "alta"
    urgente = "urgente"


class Localizacao(BaseModel):
    texto_original: str | None = Field(None, description="Trecho do relato que indica o local")
    logradouro: str | None = None
    referencia: str | None = None
    bairro_ou_comunidade: str | None = None


class TriagemResult(BaseModel):
    categoria: Categoria
    prioridade: Prioridade
    orgao_responsavel: str = Field(..., min_length=2, max_length=120)
    resumo: str = Field(..., min_length=5, max_length=280)
    localizacao: Localizacao
    risco_imediato: bool = Field(..., description="Há risco à vida ou integridade física agora?")
    justificativa_prioridade: str = Field(..., min_length=5, max_length=400)
    dados_faltantes: list[str] = Field(default_factory=list)
    confianca: float = Field(..., ge=0, le=1)
    revisao_humana: bool = False

    @field_validator("dados_faltantes")
    @classmethod
    def _limita_lista(cls, v: list[str]) -> list[str]:
        return v[:5]


class HelperResult(BaseModel):
    resposta: str = Field(..., min_length=1, max_length=1500)
    passos: list[str] = Field(default_factory=list)
    fontes: list[str] = Field(default_factory=list, description="IDs das seções da base usadas")
    dentro_do_escopo: bool
    encaminhar_atendente: bool = False
    confianca: float = Field(..., ge=0, le=1)


class Meta(BaseModel):
    """Metadados devolvidos junto com cada resposta, para auditoria."""

    modelo: str | None = None
    latencia_ms: int | None = None
    tentativas: int = 0
    reparos_json: int = 0
    fallback_seguro: bool = False
    erro: str | None = None


class TriagemResponse(BaseModel):
    resultado: TriagemResult
    meta: Meta


class HelperResponse(BaseModel):
    resultado: HelperResult
    meta: Meta
