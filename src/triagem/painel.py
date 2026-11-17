"""Publicação dos indicadores da camada Ouro (Databricks) no MVP.

O Databricks Free Edition não chama a internet, então o notebook 05_export grava ouro_painel_AAAA-MM-DD.json
e a pessoa coloca o arquivo em entrada/ouro/. O robô pega o mais recente, valida e publica.
Inválido vai para entrada/rejeitados/; ausente só gera aviso e o painel atual continua.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path


class PainelInvalido(ValueError):
    pass


def mais_recente(pasta: Path, padrao: str) -> Path | None:
    arquivos = sorted(Path(pasta).glob(padrao), key=lambda p: (p.stat().st_mtime, p.name))
    return arquivos[-1] if arquivos else None


def _numeros(valor):
    if isinstance(valor, bool):
        return
    if isinstance(valor, (int, float)):
        yield valor
    elif isinstance(valor, dict):
        for item in valor.values():
            yield from _numeros(item)
    elif isinstance(valor, list):
        for item in valor:
            yield from _numeros(item)


def validar(dados: dict, max_idade_dias: int, agora: datetime | None = None) -> dict:
    """Esquema, totais não negativos e data recente. Devolve o corpo do POST /integracao/painel."""
    agora = agora or datetime.now(UTC)
    if not isinstance(dados, dict):
        raise PainelInvalido("o arquivo não é um objeto JSON")
    for campo in ("fonte", "gerado_em", "linhas", "kpis"):
        if campo not in dados:
            raise PainelInvalido(f"campo obrigatório ausente: {campo}")
    linhas, kpis = dados["linhas"], dados["kpis"]
    if not isinstance(linhas, list) or not linhas or not all(isinstance(linha, dict) for linha in linhas):
        raise PainelInvalido("'linhas' precisa ser uma lista não vazia de objetos")
    if not isinstance(kpis, dict):
        raise PainelInvalido("'kpis' precisa ser um objeto")
    if any(numero < 0 for numero in _numeros([linhas, kpis])):
        raise PainelInvalido("há totais negativos")
    try:
        gerado = datetime.fromisoformat(str(dados["gerado_em"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise PainelInvalido(f"gerado_em inválido: {dados['gerado_em']!r}") from exc
    if gerado.tzinfo is None:
        gerado = gerado.replace(tzinfo=UTC)
    if gerado > agora + timedelta(hours=1):
        raise PainelInvalido("gerado_em está no futuro")
    if agora - gerado > timedelta(days=max_idade_dias):
        raise PainelInvalido(f"arquivo velho: gerado há mais de {max_idade_dias} dias")
    return {"fonte": str(dados["fonte"]), "gerado_em": gerado.isoformat(), "linhas": linhas, "kpis": kpis}


def ler(caminho: Path, max_idade_dias: int, agora: datetime | None = None) -> dict:
    try:
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except ValueError as exc:
        raise PainelInvalido(f"JSON inválido: {exc}") from exc
    return validar(dados, max_idade_dias, agora)


def rejeitar(caminho: Path, pasta_rejeitados: Path) -> Path:
    pasta_rejeitados.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
    destino = pasta_rejeitados / f"{caminho.stem}_{carimbo}{caminho.suffix}"
    shutil.move(str(caminho), destino)
    return destino


def arquivar(caminho: Path) -> Path:
    """Depois de publicado, o arquivo vai para entrada/ouro/publicados/ para não ser publicado de novo."""
    pasta = caminho.parent / "publicados"
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / caminho.name
    if destino.exists():  # mesmo nome já publicado antes (novo export no mesmo dia): guarda os dois
        destino = pasta / f"{caminho.stem}_{datetime.now().strftime('%Y%m%d-%H%M%S')}{caminho.suffix}"
    shutil.move(str(caminho), destino)
    return destino
