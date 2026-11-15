"""Configuração do robô: segredos no .env (fora do Git) e regras de negócio no regras.json."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

SRC = Path(__file__).resolve().parents[1]
RAIZ = SRC.parent
REGRAS_PADRAO = SRC / "regras.json"

CHAVES_REGRAS = {
    "duplicidade": ("raio_m", "janela_dias", "status_abertos"),
    "prioridade": ("pontos_categoria", "confirmacoes_por_ponto", "confianca_ia_min", "chuva_mm_min",
                   "pontos_chuva", "categorias_chuva", "alta_min", "media_min"),
    "painel": ("padrao", "max_idade_dias"),
}


class ConfigInvalida(Exception):
    """Configuração ausente ou inválida: o robô registra, avisa o responsável e encerra."""


@dataclass
class Config:
    api_url: str
    api_key: str
    regras: dict
    smtp_host: str = ""
    smtp_porta: int = 587
    smtp_usuario: str = ""
    smtp_senha: str = ""
    email_remetente: str = ""
    email_gestor: str = ""
    email_responsavel: str = ""
    chuva_simulada_mm: float | None = None
    pasta_ouro: Path = RAIZ / "entrada" / "ouro"
    pasta_rejeitados: Path = RAIZ / "entrada" / "rejeitados"
    pasta_logs: Path = RAIZ / "logs"
    pasta_relatorios: Path = RAIZ / "saida" / "relatorios"

    @property
    def email_ligado(self) -> bool:
        return bool(self.smtp_host and self.smtp_usuario and self.smtp_senha)

    def link_ocorrencia(self, ocorrencia_id: int) -> str:
        return f"{self.api_url}/ocorrencias/{ocorrencia_id}"


def _texto(nome: str) -> str:
    valor = (os.environ.get(nome) or "").strip()
    return "" if valor.upper() == "CHANGE_ME" else valor


def carregar_regras(caminho: Path) -> dict:
    if not caminho.is_file():
        raise ConfigInvalida(f"Arquivo de regras ausente: {caminho.name}")
    try:
        regras = json.loads(caminho.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ConfigInvalida(f"{caminho.name} não é um JSON válido: {exc}") from exc
    for secao, chaves in CHAVES_REGRAS.items():
        faltando = [c for c in chaves if c not in regras.get(secao, {})]
        if faltando:
            raise ConfigInvalida(f"{caminho.name}: faltam {faltando} em '{secao}'")
    tentativas = regras.get("espera_tentativas_s")
    if not isinstance(tentativas, list) or not tentativas:
        raise ConfigInvalida(f"{caminho.name}: 'espera_tentativas_s' precisa ser uma lista de segundos")
    return regras


def carregar(arquivo_env: Path | None = None, arquivo_regras: Path | None = None) -> Config:
    load_dotenv(arquivo_env or RAIZ / ".env", override=False)
    regras = carregar_regras(arquivo_regras or REGRAS_PADRAO)
    api_url, api_key = _texto("ZELA_API_URL").rstrip("/"), _texto("RPA_API_KEY")
    if not api_url.startswith(("https://", "http://")):
        raise ConfigInvalida("ZELA_API_URL ausente ou inválida no .env")
    if not api_key:
        raise ConfigInvalida("RPA_API_KEY ausente no .env")
    chuva = _texto("ZELA_CHUVA_SIMULADA_MM")
    try:
        porta = int(_texto("SMTP_PORTA") or 587)
        chuva_simulada = float(chuva.replace(",", ".")) if chuva else None
    except ValueError as exc:
        raise ConfigInvalida(f"Número inválido no .env: {exc}") from exc
    usuario = _texto("SMTP_USUARIO")
    return Config(
        api_url=api_url,
        api_key=api_key,
        regras=regras,
        smtp_host=_texto("SMTP_HOST"),
        smtp_porta=porta,
        smtp_usuario=usuario,
        smtp_senha=_texto("SMTP_SENHA"),
        email_remetente=_texto("EMAIL_REMETENTE") or usuario,
        email_gestor=_texto("EMAIL_GESTOR"),
        email_responsavel=_texto("EMAIL_RESPONSAVEL"),
        chuva_simulada_mm=chuva_simulada,
    )


def config_para_alerta() -> Config | None:
    """Quando a configuração principal falha, ainda tenta montar o SMTP para avisar o responsável."""
    load_dotenv(RAIZ / ".env", override=False)
    if not (_texto("SMTP_HOST") and _texto("SMTP_USUARIO") and _texto("SMTP_SENHA")):
        return None
    try:
        porta = int(_texto("SMTP_PORTA") or 587)
    except ValueError:
        porta = 587
    return Config(api_url=_texto("ZELA_API_URL"), api_key="", regras={}, smtp_host=_texto("SMTP_HOST"),
                  smtp_porta=porta, smtp_usuario=_texto("SMTP_USUARIO"), smtp_senha=_texto("SMTP_SENHA"),
                  email_remetente=_texto("EMAIL_REMETENTE") or _texto("SMTP_USUARIO"),
                  email_responsavel=_texto("EMAIL_RESPONSAVEL"))
