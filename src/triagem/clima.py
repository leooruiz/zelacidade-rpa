"""Chuva prevista para as próximas 24 h no bairro piloto (Open-Meteo, público e sem chave)."""

from __future__ import annotations

import logging

import requests

log = logging.getLogger("triagem.clima")

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"


def chuva_prevista_mm(latitude: float, longitude: float, sessao=requests) -> float | None:
    """Soma da precipitação prevista para hoje. Sem resposta, devolve None e a regra de chuva não pontua."""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "precipitation_sum",
        "forecast_days": 1,
        "timezone": "America/Sao_Paulo",
    }
    try:
        resposta = sessao.get(OPEN_METEO, params=params, timeout=20)
        resposta.raise_for_status()
        valor = resposta.json()["daily"]["precipitation_sum"][0]
        return float(valor) if valor is not None else None
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
        log.warning("Previsão de chuva indisponível (%s); a regra de chuva não pontua nesta execução.",
                    type(exc).__name__)
        return None
