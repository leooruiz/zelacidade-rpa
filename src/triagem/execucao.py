"""O processo do robô "Triagem ZelaCidade", do início ao fechamento (é o fluxo do BPMN em docs/).

Códigos de saída: 0 sucesso · 1 sucesso com falhas em itens · 2 configuração inválida · 3 API indisponível.
"""

from __future__ import annotations

import logging
from datetime import datetime

from . import painel as painel_ouro
from .api import ApiIndisponivel, ErroDeItem, ZelaAPI
from .clima import chuva_prevista_mm
from .config import RAIZ, Config
from .notificacao import Notificador
from .regras import ROTULO_PRIORIDADE, decidir
from .registro import Auditoria, Resumo

log = logging.getLogger("triagem")

SUCESSO, SUCESSO_COM_FALHAS, ERRO_CONFIG, API_INDISPONIVEL = 0, 1, 2, 3


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _texto_morador(ocorrencia: dict, decisao) -> str:
    protocolo = ocorrencia["protocolo"]
    if decisao.status == "triada":
        return (f"Seu registro {protocolo} foi triado com prioridade {ROTULO_PRIORIDADE[decisao.prioridade]} "
                "e já está na fila da organização responsável.")
    if decisao.status == "duplicada":
        return f"Seu registro {protocolo} trata de um problema já registrado e foi somado como mais uma confirmação."
    return f"Seu registro {protocolo} precisa de mais informação: {decisao.motivo}"


def falha_de_configuracao(mensagem: str, config_alerta: Config | None = None) -> int:
    """Configuração ausente ou inválida: log de ERRO, e-mail ao responsável (se der) e encerramento."""
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    auditoria = Auditoria(RAIZ / "logs", RAIZ / "saida" / "relatorios", run_id)
    log.error("Configuração inválida: %s", mensagem)
    resumo = Resumo(run_id=run_id, inicio=_agora(), fim=_agora(), situacao="erro_config",
                    codigo_saida=ERRO_CONFIG, erros=[mensagem])
    if config_alerta is not None:
        notificador = Notificador(config_alerta)
        notificador.alerta_responsavel("Configuração inválida", f"O robô não iniciou: {mensagem}")
        resumo.emails_enviados = notificador.enviados
    auditoria.fechar(resumo)
    return ERRO_CONFIG


def executar(config: Config, api: ZelaAPI | None = None, chuva_fn=chuva_prevista_mm,
             notificador: Notificador | None = None, run_id: str | None = None) -> Resumo:
    run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    regras = config.regras
    api = api or ZelaAPI(config.api_url, config.api_key, regras["espera_tentativas_s"])
    notificador = notificador or Notificador(config)
    auditoria = Auditoria(config.pasta_logs, config.pasta_relatorios, run_id)
    resumo = Resumo(run_id=run_id, inicio=_agora())
    auditoria.evento("inicio", api=config.api_url, email_ligado=config.email_ligado)
    log.info("Execução %s iniciada contra %s", run_id, config.api_url)

    # 1. Buscar: área piloto, ocorrências novas e as abertas que podem ser originais de duplicadas
    try:
        area = api.area()
        recebidas = api.listar("recebida")
        abertas = api.listar(",".join(regras["duplicidade"]["status_abertos"]),
                             dias=regras["duplicidade"]["janela_dias"])
    except (ApiIndisponivel, ErroDeItem) as exc:
        resumo.situacao, resumo.codigo_saida = "api_indisponivel", API_INDISPONIVEL
        resumo.erros.append(str(exc))
        log.error("API indisponível: %s", exc)
        auditoria.evento("erro", tipo="api_indisponivel", mensagem=str(exc), tentativas=api.tentativas_feitas)
        notificador.alerta_responsavel(
            "API indisponível",
            f"A API do MVP não respondeu após {api.tentativas_feitas} tentativas.\nErro: {exc}\n"
            "Nenhuma ocorrência foi triada nesta execução; a próxima execução agendada tenta de novo.",
        )
        return _fechar(resumo, auditoria, notificador)
    auditoria.evento("busca", recebidas=len(recebidas), abertas=len(abertas), area=area.get("nome"))
    log.info("%s ocorrências recebidas para triar", len(recebidas))

    # chuva prevista (ou simulada, só para teste e demonstração, sempre registrada no log)
    if config.chuva_simulada_mm is not None:
        chuva, resumo.chuva_simulada = config.chuva_simulada_mm, True
        auditoria.evento("chuva", mm=chuva, simulada=True)
        log.warning("Usando chuva SIMULADA de %s mm (ZELA_CHUVA_SIMULADA_MM)", chuva)
    elif recebidas:
        chuva = chuva_fn(area["centro"]["latitude"], area["centro"]["longitude"])
        auditoria.evento("chuva", mm=chuva, simulada=False)
    else:
        chuva = None
    resumo.chuva_prevista_mm = chuva

    # 2. Para cada ocorrência: validar, checar duplicada, pontuar e devolver a triagem ao MVP
    candidatas = list(abertas)
    for ocorrencia in recebidas:
        resumo.lidos += 1
        try:
            if not isinstance(ocorrencia.get("id"), int) or not ocorrencia.get("protocolo"):
                raise ValueError("id ou protocolo ausente")
            decisao = decidir(ocorrencia, area, candidatas, regras, chuva)
        except (KeyError, TypeError, ValueError) as exc:  # item inconsistente: registra e segue
            resumo.falhas += 1
            resumo.erros.append(f"{ocorrencia.get('protocolo')}: dados inconsistentes ({type(exc).__name__})")
            auditoria.item(ocorrencia, None, f"falha: dados inconsistentes ({type(exc).__name__})")
            continue
        try:
            api.triar(ocorrencia["id"], decisao.payload())
        except ErroDeItem as exc:
            if exc.status_http == 409:
                resumo.ignorados += 1
                auditoria.item(ocorrencia, decisao, "ignorada: já triada por outra execução")
            else:
                resumo.falhas += 1
                resumo.erros.append(str(exc))
                auditoria.item(ocorrencia, decisao, f"falha: {exc}")
            continue
        except ApiIndisponivel as exc:
            restantes = len(recebidas) - resumo.lidos + 1
            resumo.falhas += restantes
            resumo.erros.append(f"API caiu no meio do lote: {exc}")
            auditoria.item(ocorrencia, decisao, "falha: API indisponível; lote interrompido")
            notificador.alerta_responsavel("API caiu no meio do lote",
                                           f"{restantes} ocorrências ficaram para a próxima execução.\n{exc}")
            break

        auditoria.item(ocorrencia, decisao, "ok")
        log.info("%s → %s %s", ocorrencia["protocolo"], decisao.status, decisao.prioridade or "")
        if decisao.status == "triada":
            resumo.triados += 1
            candidatas.append({**ocorrencia, "status": "triada"})
            if decisao.prioridade == "alta":
                resumo.prioridade_alta += 1
                notificador.prioridade_alta(ocorrencia, decisao.motivo)
        elif decisao.status == "duplicada":
            resumo.duplicados += 1
        else:
            resumo.precisa_info += 1
        notificador.aviso_morador(ocorrencia, _texto_morador(ocorrencia, decisao))

    # 3. Publicar os indicadores da Ouro, se houver arquivo novo
    _publicar_painel(config, api, auditoria, resumo, notificador)
    return _fechar(resumo, auditoria, notificador)


def _publicar_painel(config: Config, api: ZelaAPI, auditoria: Auditoria, resumo: Resumo,
                     notificador: Notificador) -> None:
    regras = config.regras["painel"]
    arquivo = painel_ouro.mais_recente(config.pasta_ouro, regras["padrao"])
    if arquivo is None:
        resumo.painel = "ausente"
        auditoria.evento("painel", situacao="ausente",
                         mensagem="Nenhum ouro_painel_*.json em entrada/ouro; o painel atual foi mantido.")
        log.info("Nenhum ouro_painel_*.json em entrada/ouro: o painel atual do MVP foi mantido")
        return
    try:
        corpo = painel_ouro.ler(arquivo, regras["max_idade_dias"])
    except painel_ouro.PainelInvalido as exc:
        destino = painel_ouro.rejeitar(arquivo, config.pasta_rejeitados)
        resumo.painel = "rejeitado"
        resumo.erros.append(f"{arquivo.name} rejeitado: {exc}")
        auditoria.evento("painel", situacao="rejeitado", arquivo=arquivo.name, motivo=str(exc),
                         movido_para=str(destino.relative_to(RAIZ)) if destino.is_relative_to(RAIZ) else destino.name)
        notificador.alerta_responsavel("Arquivo do painel rejeitado", f"{arquivo.name}: {exc}")
        log.warning("Arquivo do painel rejeitado: %s (%s). Movido para entrada/rejeitados; painel atual mantido",
                    arquivo.name, exc)
        return
    try:
        api.publicar_painel(corpo)
    except (ApiIndisponivel, ErroDeItem) as exc:
        resumo.painel = "falhou"
        resumo.falhas += 1
        resumo.erros.append(f"publicar painel: {exc}")
        auditoria.evento("painel", situacao="falhou", arquivo=arquivo.name, motivo=str(exc))
        log.error("Falha ao publicar o painel de %s: %s", arquivo.name, exc)
        return
    painel_ouro.arquivar(arquivo)
    resumo.painel = "publicado"
    auditoria.evento("painel", situacao="publicado", arquivo=arquivo.name, linhas=len(corpo["linhas"]))
    log.info("Painel publicado a partir de %s", arquivo.name)


def _fechar(resumo: Resumo, auditoria: Auditoria, notificador: Notificador) -> Resumo:
    if resumo.situacao == "em_andamento":
        resumo.situacao = "sucesso" if resumo.falhas == 0 else "sucesso_com_falhas"
        resumo.codigo_saida = SUCESSO if resumo.falhas == 0 else SUCESSO_COM_FALHAS
    resumo.fim = _agora()
    houve_algo = resumo.lidos or resumo.painel in ("publicado", "rejeitado", "falhou") or resumo.erros
    if houve_algo and resumo.situacao != "api_indisponivel":
        notificador.alerta_responsavel(
            f"Resumo da execução {resumo.run_id}",
            f"Lidas: {resumo.lidos} · triadas: {resumo.triados} (alta: {resumo.prioridade_alta}) · "
            f"duplicadas: {resumo.duplicados} · precisam de informação: {resumo.precisa_info} · "
            f"ignoradas: {resumo.ignorados} · falhas: {resumo.falhas}\nPainel: {resumo.painel}\n"
            + ("Erros:\n- " + "\n- ".join(resumo.erros) if resumo.erros else "Sem erros."),
        )
    resumo.emails_enviados = notificador.enviados
    auditoria.fechar(resumo)
    log.info("Execução %s terminou: %s (código %s)", resumo.run_id, resumo.situacao, resumo.codigo_saida)
    return resumo
