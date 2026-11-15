"""Log de auditoria (JSONL) e relatório do dia (CSV). Só id e protocolo, nunca e-mail ou nome."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

COLUNAS_RELATORIO = ["run_id", "horario", "id", "protocolo", "categoria", "origem", "decisao", "prioridade",
                     "pontos", "duplicada_de", "resultado", "motivo"]


@dataclass
class Resumo:
    run_id: str
    inicio: str
    fim: str | None = None
    situacao: str = "em_andamento"  # sucesso | sucesso_com_falhas | erro_config | api_indisponivel
    codigo_saida: int = 0
    lidos: int = 0
    triados: int = 0
    duplicados: int = 0
    precisa_info: int = 0
    prioridade_alta: int = 0
    ignorados: int = 0
    falhas: int = 0
    chuva_prevista_mm: float | None = None
    chuva_simulada: bool = False
    painel: str = "nao_verificado"  # publicado | ausente | rejeitado | falhou
    emails_enviados: int = 0
    erros: list[str] = field(default_factory=list)


class Auditoria:
    def __init__(self, pasta_logs: Path, pasta_relatorios: Path, run_id: str):
        self.run_id = run_id
        pasta_logs.mkdir(parents=True, exist_ok=True)
        pasta_relatorios.mkdir(parents=True, exist_ok=True)
        hoje = datetime.now().strftime("%Y-%m-%d")
        self.arquivo_log = pasta_logs / f"execucoes_{hoje}.jsonl"
        self.arquivo_relatorio = pasta_relatorios / f"relatorio_{hoje}.csv"

    def evento(self, nome: str, /, **dados) -> None:
        linha = {"run_id": self.run_id, "horario": datetime.now().isoformat(timespec="seconds"), "evento": nome,
                 **dados}
        with self.arquivo_log.open("a", encoding="utf-8") as arquivo:
            arquivo.write(json.dumps(linha, ensure_ascii=False) + "\n")

    def item(self, ocorrencia: dict, decisao, resultado: str) -> None:
        linha = {
            "run_id": self.run_id,
            "horario": datetime.now().isoformat(timespec="seconds"),
            "id": ocorrencia.get("id"),
            "protocolo": ocorrencia.get("protocolo"),
            "categoria": ocorrencia.get("categoria"),
            "origem": ocorrencia.get("origem"),
            "decisao": getattr(decisao, "status", None),
            "prioridade": getattr(decisao, "prioridade", None),
            "pontos": getattr(decisao, "pontos", None),
            "duplicada_de": getattr(decisao, "duplicada_de", None),
            "resultado": resultado,
            "motivo": getattr(decisao, "motivo", None),
        }
        novo = not self.arquivo_relatorio.exists()
        with self.arquivo_relatorio.open("a", encoding="utf-8-sig", newline="") as arquivo:
            escritor = csv.DictWriter(arquivo, fieldnames=COLUNAS_RELATORIO, delimiter=";")
            if novo:
                escritor.writeheader()
            escritor.writerow(linha)
        self.evento("item", **{k: v for k, v in linha.items() if k not in ("run_id", "horario")})

    def fechar(self, resumo: Resumo) -> None:
        self.evento("resumo", **{k: v for k, v in asdict(resumo).items() if k != "run_id"})
