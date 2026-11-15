"""Regras de decisão: validação, duplicidade e prioridade por pontos."""

from conftest import AREA, ocorrencia

from triagem.regras import classificar, decidir, distancia_m, encontrar_duplicada, pontuar, validar


def test_distancia_de_30_metros():
    # 0,00027° de latitude ≈ 30 m
    assert 29 < distancia_m(-23.5, -46.625, -23.50027, -46.625) < 31


def test_cidadao_fora_da_area_precisa_de_informacao():
    decisao = validar(ocorrencia(1, lat=-23.60, lon=-46.70), AREA)
    assert decisao.status == "precisa_info"
    assert "fora da área piloto" in decisao.motivo and "Santana" in decisao.motivo


def test_teste_de_bancada_do_robo_fica_fora_da_regra_de_area():
    robo = ocorrencia(1, categoria="obstaculo", lat=-23.574, lon=-46.623, origem="robo",
                      test_location="Bancada Maker Lab - FIAP")
    decisao = decidir(robo, AREA, [], _regras(), None)
    assert decisao.status == "triada"
    assert decisao.motivo.startswith("Registro de teste de bancada do robô Maker (Bancada Maker Lab - FIAP)")


def test_categoria_invalida_e_sem_local():
    assert validar(ocorrencia(1, categoria="disco_voador"), AREA).status == "precisa_info"
    assert "sem localização" in validar(ocorrencia(1, lat=None), AREA).motivo


def test_duplicada_mesma_categoria_perto_e_recente(regras):
    original = ocorrencia(10, lat=-23.50000, criado="2026-11-10T12:00:00Z", status="triada")
    nova = ocorrencia(11, lat=-23.50015)  # ~17 m
    assert encontrar_duplicada(nova, [original], regras)["id"] == 10


def test_nao_e_duplicada_longe_antiga_outra_categoria_ou_simulada(regras):
    nova = ocorrencia(11)
    longe = ocorrencia(1, lat=-23.5010)  # ~110 m
    antiga = ocorrencia(2, criado="2026-10-20T12:00:00Z")
    outra_categoria = ocorrencia(3, categoria="iluminacao")
    simulada = ocorrencia(4, origem="simulado")
    assert encontrar_duplicada(nova, [longe, antiga, outra_categoria, simulada], regras) is None


def test_pontos_e_motivo_explicavel(regras):
    caso = ocorrencia(1, confirmacoes=4, categoria_ia="buraco", confianca_ia=0.87)
    pontos, partes = pontuar(caso, regras, chuva_mm=15.0)
    assert pontos == 3 + 2 + 1 + 2
    assert partes == ["buraco na via (+3)", "4 confirmações (+2)", "IA confirmou com 87% (+1)",
                      "chuva prevista de 15 mm em 24 h (+2)"]


def test_ia_so_pontua_quando_concorda_com_a_categoria(regras):
    caso = ocorrencia(1, categoria="obstaculo", categoria_ia="buraco", confianca_ia=0.95)
    assert pontuar(caso, regras, None)[0] == 3


def test_chuva_so_pontua_buraco(regras):
    assert pontuar(ocorrencia(1, categoria="iluminacao"), regras, 30.0)[0] == 2


def test_faixas_de_prioridade(regras):
    assert [classificar(p, regras) for p in (1, 2, 3, 4, 5, 8)] == ["baixa", "baixa", "media", "media", "alta", "alta"]


def test_decisao_alta_avisa_gestor(regras):
    decisao = decidir(ocorrencia(1, confirmacoes=4), AREA, [], regras, 12.0)
    assert (decisao.status, decisao.prioridade, decisao.pontos) == ("triada", "alta", 7)
    assert decisao.alertas == ["gestor"]
    assert decisao.payload() == {"status": "triada", "motivo": decisao.motivo, "prioridade": "alta"}


def _regras():
    from triagem.config import REGRAS_PADRAO, carregar_regras
    return carregar_regras(REGRAS_PADRAO)
