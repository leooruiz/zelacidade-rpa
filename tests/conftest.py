import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from triagem.api import ApiIndisponivel, ErroDeItem  # noqa: E402
from triagem.config import Config, carregar_regras  # noqa: E402

AREA = {
    "nome": "Área piloto · Zona Norte",
    "centro": {"latitude": -23.4990, "longitude": -46.6250},
    "limites": {"sul": -23.5150, "norte": -23.4830, "oeste": -46.6420, "leste": -46.6080},
    "bairros": ["Santana", "Jardim São Paulo", "Mandaqui", "Tucuruvi"],
}


def ocorrencia(id_, categoria="buraco", lat=-23.5000, lon=-46.6250, origem="cidadao", criado="2026-11-15T12:00:00Z",
               **extra):
    return {"id": id_, "protocolo": f"ZC-{id_:06d}", "categoria": categoria, "latitude": lat, "longitude": lon,
            "origem": origem, "simulado": origem == "simulado", "confirmacoes": 0, "categoria_ia": None,
            "confianca_ia": None, "criado_em": criado, "bairro": "Santana", "status": "recebida",
            "consentimento": False, "autor_email": None, **extra}


class FakeAPI:
    """API em memória: guarda as triagens e o painel publicados."""

    def __init__(self, recebidas=(), abertas=(), fora_do_ar=False, falhar_ids=()):
        self.recebidas, self.abertas = list(recebidas), list(abertas)
        self.fora_do_ar, self.falhar_ids = fora_do_ar, set(falhar_ids)
        self.triagens, self.paineis = {}, []
        self.tentativas_feitas = 0

    def _checar(self):
        self.tentativas_feitas += 1
        if self.fora_do_ar:
            self.tentativas_feitas += 3
            raise ApiIndisponivel("http://mvp sem resposta após 4 tentativas (ConnectionError)")

    def area(self):
        self._checar()
        return AREA

    def listar(self, status, dias=None):
        self._checar()
        return self.recebidas if status == "recebida" else self.abertas

    def triar(self, ocorrencia_id, payload):
        if ocorrencia_id in self.falhar_ids:
            raise ErroDeItem("HTTP 422 dados inválidos", 422)
        if ocorrencia_id in self.triagens:
            raise ErroDeItem("HTTP 409 já triada", 409)
        self.triagens[ocorrencia_id] = payload
        return {"id": ocorrencia_id, **payload}

    def publicar_painel(self, painel):
        self.paineis.append(painel)
        return {"id": len(self.paineis), "linhas": len(painel["linhas"])}


class FakeNotificador:
    def __init__(self):
        self.mensagens = []
        self.enviados = 0

    def _guardar(self, tipo, *args):
        self.mensagens.append((tipo, *args))
        self.enviados += 1
        return True

    def alerta_responsavel(self, titulo, detalhe):
        return self._guardar("responsavel", titulo, detalhe)

    def prioridade_alta(self, ocorrencia, motivo):
        return self._guardar("gestor", ocorrencia["protocolo"], motivo)

    def aviso_morador(self, ocorrencia, texto):
        if ocorrencia.get("consentimento") and ocorrencia.get("autor_email"):
            return self._guardar("morador", ocorrencia["protocolo"], texto)
        return False


@pytest.fixture
def regras():
    return carregar_regras(SRC / "regras.json")


@pytest.fixture
def config(tmp_path, regras):
    return Config(
        api_url="http://mvp", api_key="chave", regras=regras,
        pasta_ouro=tmp_path / "entrada" / "ouro", pasta_rejeitados=tmp_path / "entrada" / "rejeitados",
        pasta_logs=tmp_path / "logs", pasta_relatorios=tmp_path / "saida",
    )


def painel_valido(gerado_em="2026-11-15T10:00:00-03:00"):
    return {"fonte": "databricks:zelacidade.ouro.ouro_painel", "gerado_em": gerado_em,
            "linhas": [{"bairro": "Santana", "categoria": "buraco", "total": 12, "abertas": 5, "resolvidas": 4}],
            "kpis": {"total": 200, "pct_resolvidas_com_evidencia": 0.35}}


def gravar_json(caminho: Path, dados) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados), encoding="utf-8")
    return caminho
