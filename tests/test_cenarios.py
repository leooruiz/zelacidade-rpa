"""Os 3 cenários pedidos (sucesso, decisão e falha) e as exceções previstas, de ponta a ponta no processo."""

import json
from datetime import UTC, datetime

import pytest
from conftest import FakeAPI, FakeNotificador, gravar_json, ocorrencia, painel_valido

from triagem import execucao
from triagem.api import ApiIndisponivel, ZelaAPI
from triagem.config import ConfigInvalida, carregar_regras
from triagem.painel import PainelInvalido, validar


def _log(config):
    linhas = []
    for arquivo in config.pasta_logs.glob("execucoes_*.jsonl"):
        linhas += [json.loads(linha) for linha in arquivo.read_text(encoding="utf-8").splitlines()]
    return linhas


def test_cenario_sucesso_triagem_relatorio_log_e_painel(config):
    """Lote normal: tudo triado, relatório CSV e log JSONL gravados, painel da Ouro publicado."""
    agora = datetime.now(UTC).isoformat()
    gravar_json(config.pasta_ouro / "ouro_painel_2026-11-16.json", painel_valido(agora))
    api = FakeAPI(recebidas=[ocorrencia(1), ocorrencia(2, categoria="iluminacao", lat=-23.49)])
    resumo = execucao.executar(config, api=api, chuva_fn=lambda *_: 0.0, notificador=FakeNotificador())

    assert (resumo.situacao, resumo.codigo_saida, resumo.lidos, resumo.triados) == ("sucesso", 0, 2, 2)
    assert api.triagens[1]["prioridade"] == "media" and api.triagens[2]["prioridade"] == "baixa"
    assert resumo.painel == "publicado" and len(api.paineis) == 1
    assert (config.pasta_ouro / "publicados" / "ouro_painel_2026-11-16.json").exists()
    relatorio = next(config.pasta_relatorios.glob("relatorio_*.csv")).read_text(encoding="utf-8-sig")
    assert "ZC-000001" in relatorio and "@" not in relatorio  # LGPD: sem e-mail no relatório
    eventos = [linha["evento"] for linha in _log(config)]
    assert eventos[0] == "inicio" and eventos[-1] == "resumo" and eventos.count("item") == 2


def test_cenario_decisao_duplicada_e_alta_por_chuva(config):
    """As duas decisões do vídeo: uma duplicada (soma confirmação) e um buraco que vira alta pela chuva."""
    original = ocorrencia(10, criado="2026-11-14T12:00:00Z", status="triada", confirmacoes=1)
    duplicada = ocorrencia(11, lat=-23.50010)  # ~11 m da original
    chuva = ocorrencia(12, lat=-23.4900, confirmacoes=0, categoria_ia="buraco", confianca_ia=0.9,
                       consentimento=True, autor_email="morador@exemplo.com")
    notificador = FakeNotificador()
    api = FakeAPI(recebidas=[duplicada, chuva], abertas=[original])
    resumo = execucao.executar(config, api=api, chuva_fn=lambda *_: 18.0, notificador=notificador)

    assert api.triagens[11] == {"status": "duplicada", "duplicada_de": 10,
                                "motivo": api.triagens[11]["motivo"]}
    assert "ZC-000010" in api.triagens[11]["motivo"]
    assert api.triagens[12]["prioridade"] == "alta"
    assert "chuva prevista de 18 mm" in api.triagens[12]["motivo"]
    assert (resumo.duplicados, resumo.triados, resumo.prioridade_alta) == (1, 1, 1)
    tipos = [m[0] for m in notificador.mensagens]
    assert "gestor" in tipos and "morador" in tipos  # morador só porque deu e-mail e consentimento
    assert all("@" not in json.dumps(linha) for linha in _log(config))  # LGPD: sem e-mail no log


def test_cenario_falha_api_fora_do_ar(config):
    """API desligada: tentativas, log de erro, e-mail de alerta e código de saída 3, sem falha silenciosa."""
    notificador = FakeNotificador()
    resumo = execucao.executar(config, api=FakeAPI(fora_do_ar=True), notificador=notificador)
    assert (resumo.situacao, resumo.codigo_saida) == ("api_indisponivel", 3)
    assert notificador.mensagens[0][:2] == ("responsavel", "API indisponível")
    erro = next(linha for linha in _log(config) if linha["evento"] == "erro")
    assert erro["tipo"] == "api_indisponivel" and erro["tentativas"] == 4


def test_tentativas_com_espera_5_15_45():
    esperas = []

    class SessaoFora:
        def request(self, *args, **kwargs):
            import requests
            raise requests.ConnectionError("fora")

    api = ZelaAPI("http://mvp", "chave", [5, 15, 45], sessao=SessaoFora(), dormir=esperas.append)
    with pytest.raises(ApiIndisponivel, match="4 tentativas"):
        api.listar("recebida")
    assert esperas == [5, 15, 45]


def test_item_com_erro_nao_para_o_lote(config):
    api = FakeAPI(recebidas=[ocorrencia(1), ocorrencia(2, lat=-23.49)], falhar_ids={1})
    resumo = execucao.executar(config, api=api, chuva_fn=lambda *_: None, notificador=FakeNotificador())
    assert (resumo.falhas, resumo.triados, resumo.codigo_saida) == (1, 1, 1)
    assert 2 in api.triagens


def test_item_inconsistente_e_registrado_e_o_lote_segue(config):
    coordenada_quebrada = ocorrencia(1, lat="abc")
    sem_id = {**ocorrencia(3), "id": None}
    api = FakeAPI(recebidas=[coordenada_quebrada, sem_id, ocorrencia(2, lat=-23.49)])
    resumo = execucao.executar(config, api=api, chuva_fn=lambda *_: None, notificador=FakeNotificador())
    assert resumo.falhas == 2 and resumo.triados == 1 and resumo.codigo_saida == 1


def test_painel_invalido_vai_para_rejeitados(config):
    gravar_json(config.pasta_ouro / "ouro_painel_2026-11-16.json", {**painel_valido(), "kpis": {"total": -3}})
    notificador = FakeNotificador()
    resumo = execucao.executar(config, api=FakeAPI(), notificador=notificador)
    assert resumo.painel == "rejeitado"
    assert list(config.pasta_rejeitados.glob("ouro_painel_2026-11-16_*.json"))
    assert ("responsavel", "Arquivo do painel rejeitado") == notificador.mensagens[0][:2]


def test_painel_ausente_mantem_o_atual(config):
    resumo = execucao.executar(config, api=FakeAPI(), notificador=FakeNotificador())
    assert resumo.painel == "ausente" and resumo.codigo_saida == 0


def test_painel_velho_e_recusado():
    agora = datetime(2026, 11, 16, 12, tzinfo=UTC)
    with pytest.raises(PainelInvalido, match="velho"):
        validar(painel_valido("2026-11-10T10:00:00-03:00"), 3, agora)
    assert validar(painel_valido("2026-11-16T08:00:00-03:00"), 3, agora)["linhas"]


def test_configuracao_invalida(tmp_path):
    with pytest.raises(ConfigInvalida, match="ausente"):
        carregar_regras(tmp_path / "nao_existe.json")
    (tmp_path / "regras.json").write_text('{"prioridade": {}}', encoding="utf-8")
    with pytest.raises(ConfigInvalida, match="faltam"):
        carregar_regras(tmp_path / "regras.json")


def test_aviso_ao_morador_so_para_registro_real_com_consentimento(config):
    """Registro simulado tem e-mail fictício (@exemplo.com): o robô não manda aviso para ele."""
    from triagem.notificacao import Notificador

    enviados = []

    class SMTPFalso:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self):
            pass

        def login(self, *args):
            pass

        def send_message(self, mensagem):
            enviados.append(mensagem["To"])

    config.smtp_host, config.smtp_usuario, config.smtp_senha = "smtp.teste", "robo@teste.com", "senha"
    notificador = Notificador(config, smtp_factory=SMTPFalso)
    simulado = ocorrencia(1, origem="simulado", consentimento=True, autor_email="morador001@exemplo.com")
    real = ocorrencia(2, consentimento=True, autor_email="vizinho@teste.com")
    sem_consentimento = ocorrencia(3, consentimento=False, autor_email="outro@teste.com")
    assert notificador.aviso_morador(simulado, "texto") is False
    assert notificador.aviso_morador(sem_consentimento, "texto") is False
    assert notificador.aviso_morador(real, "texto") is True
    assert enviados == ["vizinho@teste.com"]
