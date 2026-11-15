"""Regras de negócio da triagem, sem rede e sem arquivo (cobertas por pytest).

Para cada ocorrência recebida, nesta ordem:
1. Validar: campos obrigatórios e, para registros de cidadãos, coordenada dentro da área piloto.
   Testes de bancada do robô Maker ficam fora da regra de área e seguem marcados como teste.
2. Duplicada: mesma categoria, aberta, a até 30 m e registrada há até 14 dias (simulado só casa com simulado).
3. Prioridade por pontos, com o motivo escrito para a decisão ser explicável.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

CATEGORIAS = {
    "buraco": "Buraco na via",
    "calcada_danificada": "Calçada danificada",
    "iluminacao": "Iluminação",
    "obstaculo": "Obstáculo",
    "equipamento_danificado": "Equipamento danificado",
    "lixo_entulho": "Lixo ou entulho",
    "outro": "Outro",
}


@dataclass
class Decisao:
    """O que o robô devolve ao MVP para uma ocorrência (PATCH /integracao/ocorrencias/{id}/triagem)."""

    status: str  # triada | duplicada | precisa_info
    motivo: str
    prioridade: str | None = None
    duplicada_de: int | None = None
    pontos: int | None = None
    alertas: list[str] = field(default_factory=list)

    def payload(self) -> dict:
        corpo = {"status": self.status, "motivo": self.motivo[:500]}
        if self.prioridade:
            corpo["prioridade"] = self.prioridade
        if self.duplicada_de:
            corpo["duplicada_de"] = self.duplicada_de
        return corpo


def ler_data(valor: str | None) -> datetime | None:
    if not valor:
        return None
    return datetime.fromisoformat(str(valor).replace("Z", "+00:00"))


def distancia_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância em metros (fórmula de haversine)."""
    raio = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat, dlon = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * raio * math.asin(math.sqrt(a))


def dentro_da_area(lat: float, lon: float, area: dict) -> bool:
    limites = area["limites"]
    return limites["sul"] <= lat <= limites["norte"] and limites["oeste"] <= lon <= limites["leste"]


def eh_teste_de_bancada(ocorrencia: dict) -> bool:
    return ocorrencia.get("origem") == "robo"


def validar(ocorrencia: dict, area: dict) -> Decisao | None:
    """None quando está tudo certo; senão, a decisão 'precisa_info' com o motivo."""
    if ocorrencia.get("categoria") not in CATEGORIAS:
        return Decisao("precisa_info", f"Categoria inválida ou ausente ({ocorrencia.get('categoria')!r}).")
    lat, lon = ocorrencia.get("latitude"), ocorrencia.get("longitude")
    if lat is None or lon is None:
        return Decisao("precisa_info", "Registro sem localização. Informe o endereço ou marque o ponto no mapa.")
    if ocorrencia.get("origem") == "cidadao" and not dentro_da_area(float(lat), float(lon), area):
        bairros = ", ".join(area.get("bairros") or []) or area.get("nome", "área piloto")
        return Decisao(
            "precisa_info",
            f"Local fora da área piloto ({bairros}). Confirme o endereço ou registre no bairro atendido.",
        )
    return None


def encontrar_duplicada(ocorrencia: dict, abertas: list[dict], regras: dict) -> dict | None:
    """A ocorrência aberta mais antiga e mais próxima que já cobre o mesmo problema."""
    raio = regras["duplicidade"]["raio_m"]
    janela = timedelta(days=regras["duplicidade"]["janela_dias"])
    criada = ler_data(ocorrencia.get("criado_em"))
    candidatas = []
    for outra in abertas:
        if outra["id"] == ocorrencia["id"] or outra.get("categoria") != ocorrencia.get("categoria"):
            continue
        if eh_teste_de_bancada(outra):
            continue  # teste de bancada nunca é original de outro registro
        if bool(outra.get("simulado")) != bool(ocorrencia.get("simulado")):
            continue  # registro simulado nunca vira original de um real (e vice-versa)
        if outra.get("latitude") is None or outra.get("longitude") is None:
            continue
        criada_outra = ler_data(outra.get("criado_em"))
        if criada and criada_outra and not (timedelta(0) <= criada - criada_outra <= janela):
            continue  # a original é anterior e está dentro da janela
        metros = distancia_m(ocorrencia["latitude"], ocorrencia["longitude"], outra["latitude"], outra["longitude"])
        if metros <= raio:
            candidatas.append((metros, criada_outra or criada, outra))
    if not candidatas:
        return None
    candidatas.sort(key=lambda c: (c[0], c[1]))
    return candidatas[0][2]


def pontuar(ocorrencia: dict, regras: dict, chuva_mm: float | None) -> tuple[int, list[str]]:
    """Pontos e a explicação de cada parcela."""
    cfg = regras["prioridade"]
    categoria = ocorrencia["categoria"]
    pontos_categoria = cfg["pontos_categoria"].get(categoria, cfg["pontos_categoria"]["padrao"])
    partes = [f"{CATEGORIAS[categoria].lower()} (+{pontos_categoria})"]
    total = pontos_categoria

    confirmacoes = int(ocorrencia.get("confirmacoes") or 0)
    extra = confirmacoes // cfg["confirmacoes_por_ponto"]
    if extra:
        partes.append(f"{confirmacoes} confirmações (+{extra})")
        total += extra

    confianca = ocorrencia.get("confianca_ia")
    if confianca is not None and ocorrencia.get("categoria_ia") == categoria and confianca >= cfg["confianca_ia_min"]:
        partes.append(f"IA confirmou com {round(confianca * 100)}% (+1)")
        total += 1

    if chuva_mm is not None and categoria in cfg["categorias_chuva"] and chuva_mm >= cfg["chuva_mm_min"]:
        partes.append(f"chuva prevista de {chuva_mm:.0f} mm em 24 h (+{cfg['pontos_chuva']})")
        total += cfg["pontos_chuva"]
    return total, partes


def classificar(pontos: int, regras: dict) -> str:
    cfg = regras["prioridade"]
    if pontos >= cfg["alta_min"]:
        return "alta"
    if pontos >= cfg["media_min"]:
        return "media"
    return "baixa"


ROTULO_PRIORIDADE = {"alta": "alta", "media": "média", "baixa": "baixa"}


def decidir(ocorrencia: dict, area: dict, abertas: list[dict], regras: dict, chuva_mm: float | None) -> Decisao:
    """Aplica as três etapas e devolve a decisão final."""
    invalida = validar(ocorrencia, area)
    if invalida:
        return invalida

    # cada teste de bancada do robô Maker é um registro próprio: fica fora da regra de duplicidade
    original = None if eh_teste_de_bancada(ocorrencia) else encontrar_duplicada(ocorrencia, abertas, regras)
    if original:
        metros = distancia_m(ocorrencia["latitude"], ocorrencia["longitude"], original["latitude"], original["longitude"])
        return Decisao(
            "duplicada",
            f"Mesmo problema de {original['protocolo']}: mesma categoria, a {metros:.0f} m, ainda aberto. "
            "O registro conta como mais uma confirmação.",
            duplicada_de=original["id"],
        )

    pontos, partes = pontuar(ocorrencia, regras, chuva_mm)
    prioridade = classificar(pontos, regras)
    motivo = f"{' + '.join(partes)} = {pontos} pontos, prioridade {ROTULO_PRIORIDADE[prioridade]}."
    if eh_teste_de_bancada(ocorrencia):
        motivo = f"Registro de teste de bancada do robô Maker ({ocorrencia.get('test_location') or 'bancada'}). {motivo}"
    decisao = Decisao("triada", motivo, prioridade=prioridade, pontos=pontos)
    if prioridade == "alta":
        decisao.alertas.append("gestor")
    return decisao
