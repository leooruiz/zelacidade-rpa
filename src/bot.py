"""
Robô "Triagem ZelaCidade" (BotCity, template Custom).

Busca as ocorrências novas na API do MVP, valida, detecta duplicadas, calcula a prioridade com o motivo,
devolve a triagem ao MVP, avisa por e-mail, publica os indicadores da camada Ouro e grava log e relatório.

Instale as dependências com `pip install --upgrade -r requirements.txt` e rode com `python bot.py`.
No Windows, o Agendador de Tarefas roda o robô a cada 30 minutos (veja o README).

Documentação do template: https://documentation.botcity.dev/tutorials/custom-automations/python-custom/
"""

import logging
import sys

# Import for integration with BotCity Maestro SDK
from botcity.maestro import *

from triagem import config as cfg
from triagem import execucao

# Disable errors if we are not connected to Maestro
BotMaestroSDK.RAISE_NOT_CONNECTED = False

STATUS_MAESTRO = {
    execucao.SUCESSO: AutomationTaskFinishStatus.SUCCESS,
    execucao.SUCESSO_COM_FALHAS: AutomationTaskFinishStatus.PARTIALLY_COMPLETED,
}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")

    # Runner passes the server url, the id of the task being executed,
    # the access token and the parameters that this task receives (when applicable).
    maestro = BotMaestroSDK.from_sys_args()
    ## Fetch the BotExecution with details from the task, including parameters
    execution = maestro.get_execution()

    try:
        configuracao = cfg.carregar()
    except cfg.ConfigInvalida as exc:
        codigo = execucao.falha_de_configuracao(str(exc), cfg.config_para_alerta())
        maestro.finish_task(task_id=execution.task_id, status=AutomationTaskFinishStatus.FAILED,
                            message=f"Configuração inválida: {exc}")
        return codigo

    resumo = execucao.executar(configuracao)
    maestro.finish_task(
        task_id=execution.task_id,
        status=STATUS_MAESTRO.get(resumo.codigo_saida, AutomationTaskFinishStatus.FAILED),
        message=f"{resumo.situacao}: {resumo.triados} triadas, {resumo.duplicados} duplicadas, "
                f"{resumo.precisa_info} sem informação, {resumo.falhas} falhas",
        total_items=resumo.lidos,
        processed_items=resumo.lidos - resumo.falhas,
        failed_items=resumo.falhas,
    )
    return resumo.codigo_saida


if __name__ == '__main__':
    sys.exit(main())
