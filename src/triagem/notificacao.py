"""E-mails do robô (SMTP com TLS). Sem SMTP no .env, o e-mail fica desligado e só aparece no log."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

log = logging.getLogger("triagem.email")


class Notificador:
    def __init__(self, config, smtp_factory=smtplib.SMTP):
        self.config = config
        self.smtp_factory = smtp_factory
        self.enviados = 0
        self.falhas = 0

    def enviar(self, para: str, assunto: str, corpo: str) -> bool:
        """Nunca derruba a execução: falha de e-mail vira aviso no log."""
        if not para:
            return False
        if not self.config.email_ligado:
            log.info("E-mail desligado (SMTP não configurado): %s", assunto)
            return False
        mensagem = EmailMessage()
        mensagem["From"] = self.config.email_remetente
        mensagem["To"] = para
        mensagem["Subject"] = assunto
        mensagem.set_content(corpo)
        try:
            with self.smtp_factory(self.config.smtp_host, self.config.smtp_porta, timeout=30) as smtp:
                smtp.starttls()
                smtp.login(self.config.smtp_usuario, self.config.smtp_senha)
                smtp.send_message(mensagem)
        except (OSError, smtplib.SMTPException) as exc:
            self.falhas += 1
            log.warning("Falha ao enviar e-mail '%s': %s", assunto, type(exc).__name__)
            return False
        self.enviados += 1
        return True

    # mensagens do processo -------------------------------------------------

    def alerta_responsavel(self, titulo: str, detalhe: str) -> bool:
        return self.enviar(
            self.config.email_responsavel,
            f"[ZelaCidade · Robô de triagem] {titulo}",
            f"{detalhe}\n\nVeja o log da execução na pasta logs/ do robô.",
        )

    def prioridade_alta(self, ocorrencia: dict, motivo: str) -> bool:
        return self.enviar(
            self.config.email_gestor,
            f"[ZelaCidade] Prioridade alta: {ocorrencia['protocolo']}",
            f"O robô de triagem marcou {ocorrencia['protocolo']} como prioridade alta.\n\n"
            f"Bairro: {ocorrencia.get('bairro') or 'não informado'}\nMotivo: {motivo}\n\n"
            f"Abrir a ocorrência: {self.config.link_ocorrencia(ocorrencia['id'])}",
        )

    def aviso_morador(self, ocorrencia: dict, texto: str) -> bool:
        """Só com e-mail E consentimento (a API só devolve o e-mail de quem consentiu)."""
        if not (ocorrencia.get("consentimento") and ocorrencia.get("autor_email")):
            return False
        return self.enviar(
            ocorrencia["autor_email"],
            f"[ZelaCidade] Atualização do seu registro {ocorrencia['protocolo']}",
            f"Olá! {texto}\n\nAcompanhe: {self.config.link_ocorrencia(ocorrencia['id'])}\n\n"
            "Você recebe este aviso porque autorizou o contato ao registrar. "
            "A ZelaCidade não substitui os canais oficiais da Prefeitura (SP156).",
        )
