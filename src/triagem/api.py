"""Cliente da API do MVP com a RPA_API_KEY, com novas tentativas quando a API está fora."""

from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger("triagem.api")


class ApiIndisponivel(Exception):
    """A API não respondeu depois de todas as tentativas."""


class ErroDeItem(Exception):
    """A API recusou um item (o robô registra e segue com os próximos)."""

    def __init__(self, mensagem: str, status_http: int | None = None):
        super().__init__(mensagem)
        self.status_http = status_http


class ZelaAPI:
    def __init__(self, url: str, chave: str, esperas_s: list[float], sessao=None, dormir=time.sleep):
        self.url = url.rstrip("/")
        self.chave = chave
        self.esperas_s = list(esperas_s)
        self.sessao = sessao or requests.Session()
        self.dormir = dormir
        self.tentativas_feitas = 0

    def _com_tentativas(self, metodo: str, caminho: str, **kwargs):
        """Tenta uma vez e mais uma para cada espera configurada (padrão: 5, 15 e 45 s)."""
        kwargs.setdefault("timeout", 60)  # o App Service F1 pode estar dormindo
        headers = {"X-API-Key": self.chave, **kwargs.pop("headers", {})}
        ultimo_erro = ""
        for tentativa, espera in enumerate([0, *self.esperas_s], start=1):
            if espera:
                log.warning("API indisponível (%s). Nova tentativa em %ss.", ultimo_erro, espera)
                self.dormir(espera)
            self.tentativas_feitas += 1
            try:
                resposta = self.sessao.request(metodo, f"{self.url}{caminho}", headers=headers, **kwargs)
            except requests.RequestException as exc:
                ultimo_erro = type(exc).__name__
                continue
            if resposta.status_code >= 500:
                ultimo_erro = f"HTTP {resposta.status_code}"
                continue
            return resposta
        raise ApiIndisponivel(f"{self.url} sem resposta após {tentativa} tentativas ({ultimo_erro})")

    @staticmethod
    def _checar(resposta, contexto: str):
        if resposta.status_code in (401, 403):
            raise ApiIndisponivel(f"{contexto}: a RPA_API_KEY foi recusada (HTTP {resposta.status_code})")
        if resposta.status_code == 503:
            raise ApiIndisponivel(f"{contexto}: integração RPA desligada no servidor (HTTP 503)")
        if resposta.status_code >= 400:
            try:
                detalhe = resposta.json().get("detail")
            except ValueError:
                detalhe = resposta.text[:200]
            raise ErroDeItem(f"{contexto}: HTTP {resposta.status_code} {detalhe}", resposta.status_code)
        return resposta

    def area(self) -> dict:
        resposta = self._checar(self._com_tentativas("GET", "/api/v1/config"), "config")
        return resposta.json()["area"]

    def listar(self, status: str, dias: int | None = None) -> list[dict]:
        params = {"status": status}
        if dias:
            params["dias"] = dias
        resposta = self._com_tentativas("GET", "/api/v1/integracao/ocorrencias", params=params)
        return self._checar(resposta, "listar ocorrências").json()

    def triar(self, ocorrencia_id: int, payload: dict) -> dict:
        resposta = self._com_tentativas(
            "PATCH", f"/api/v1/integracao/ocorrencias/{ocorrencia_id}/triagem", json=payload
        )
        return self._checar(resposta, f"triagem da ocorrência {ocorrencia_id}").json()

    def publicar_painel(self, painel: dict) -> dict:
        resposta = self._com_tentativas("POST", "/api/v1/integracao/painel", json=painel)
        return self._checar(resposta, "publicar painel").json()
