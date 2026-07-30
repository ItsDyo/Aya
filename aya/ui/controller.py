from __future__ import annotations

import logging

from aya.core.assistant import Assistant
from aya.core.permissions import AccessChannel
from aya.core.voice import VoiceIO

logger = logging.getLogger("aya.ui.controller")


class UIController:
    """Callbacks usados pela interface Gradio."""

    def __init__(
        self,
        assistant: Assistant,
        voice: VoiceIO | None = None,
        channel: AccessChannel = AccessChannel.LOCAL_GRADIO,
    ):
        self.aya = assistant
        self.voice = voice or VoiceIO()
        self.channel = channel

    def responder(self, mensagem: str) -> str:
        return self.aya.responder(mensagem, channel=self.channel)

    def conversar(self, mensagem, historico):
        if not mensagem or not mensagem.strip():
            return self._normalizar_historico(historico), ""
        resposta = self.responder(mensagem)
        historico = self._normalizar_historico(historico)
        historico.extend([
            {"role": "user", "content": mensagem},
            {"role": "assistant", "content": resposta},
        ])
        return historico, ""

    def salvar_conhecimento(self, topico, conteudo, tags):
        return self.responder(f"/salvar {topico or ''} | {conteudo or ''} | {tags or ''}")

    def iniciar_sessao(self, materia, minutos):
        try:
            minutos = int(minutos)
        except (TypeError, ValueError):
            return "Informe os minutos como número."
        return self.responder(f"/estudar {materia or ''} | {minutos}")

    def encerrar_sessao(self, notas):
        return self.responder(f"/encerrar {notas or ''}")

    def criar_meta(self, tipo, descricao):
        return self.responder(f"/meta {tipo or 'geral'} | {descricao or ''}")

    def registrar_dificuldade(self, materia, topico, descricao):
        return self.responder(f"/dificuldade {materia or ''} | {topico or ''} | {descricao or ''}")

    def lembrar(self, tipo, chave, valor):
        return self.responder(f"/lembrar {tipo or ''} | {chave or ''} | {valor or ''}")

    def consultar_rag(self, consulta):
        return self.responder(f"/rag {consulta or ''}")

    def status_rag(self):
        return self.responder("/ragstatus")

    def reindexar_rag(self):
        return self.responder("/reindexar rag")

    def ingerir(self, caminho):
        return self.responder(f"/ingerir {caminho or '.'}")

    def consultar_fontes(self, consulta):
        return self.responder(f"/fontes {consulta or ''}")

    def aprovar_aprendizado(self, aprendizado_id):
        return self.responder(f"/aprovar {aprendizado_id or ''}")

    def rejeitar_aprendizado(self, aprendizado_id):
        return self.responder(f"/rejeitar {aprendizado_id or ''}")

    def listar_curadoria(self):
        return self.responder("/curadoria")

    def listar_conflitos(self):
        return self.responder("/conflitos")

    def resolver_conflito(self, conflito_id, decisao):
        return self.responder(f"/resolver conflito {conflito_id or ''} {decisao or ''}")

    def fundir_memorias(self, memoria_principal_id, memoria_duplicada_id):
        return self.responder(
            f"/fundir memoria {memoria_principal_id or ''} {memoria_duplicada_id or ''}"
        )

    def historico_memoria(self, memoria_id):
        return self.responder(f"/historico memoria {memoria_id or ''}")

    def criar_backup(self):
        return self.responder("/backup criar")

    def listar_backups(self):
        return self.responder("/backup listar")

    def verificar_backup(self, caminho):
        return self.responder(f"/backup verificar {caminho or ''}")

    def extrair_backup(self, caminho):
        return self.responder(f"/backup extrair {caminho or ''}")

    def confirmar_memoria(self, memoria_id):
        return self.responder(f"/confirmar memoria {memoria_id or ''}")

    def esquecer_memoria(self, memoria_id):
        return self.responder(f"/esquecer memoria {memoria_id or ''}")

    def criar_exercicio(self, topico, nivel):
        return self.responder(f"/exercicio {topico or ''} | {nivel or 'medio'}")

    def responder_exercicio(self, exercicio_id, resposta):
        return self.responder(f"/responder {exercicio_id or ''} | {resposta or ''}")

    def conversar_companhia(self, mensagem, historico):
        if not mensagem or not mensagem.strip():
            return self._normalizar_historico(historico), ""
        resposta = self.responder(f"/companhia {mensagem}")
        historico = self._normalizar_historico(historico)
        historico.extend([
            {"role": "user", "content": mensagem},
            {"role": "assistant", "content": resposta},
        ])
        return historico, ""

    def _normalizar_historico(self, historico):
        mensagens = []
        for item in historico or []:
            if isinstance(item, dict) and "role" in item and "content" in item:
                mensagens.append(item)
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                user, assistant = item
                mensagens.append({"role": "user", "content": user or ""})
                mensagens.append({"role": "assistant", "content": assistant or ""})
        return mensagens

    def conversar_voz(self, audio_path, texto_manual, modo):
        texto = (texto_manual or "").strip()
        aviso = ""
        if not texto:
            texto, aviso = self.voice.transcribe(audio_path)
        if not texto:
            return "", aviso or "Nao recebi texto nem audio.", None

        if modo == "Companhia":
            resposta = self.responder(f"/companhia {texto}")
        else:
            resposta = self.responder(texto)
        audio_resposta, aviso_audio = self.voice.synthesize(resposta)
        status = aviso_audio or aviso or "Resposta gerada."
        return texto, f"{resposta}\n\n[{status}]", audio_resposta

    def painel(self):
        return self.responder("/painel")

    def alertas_painel(self):
        try:
            alerts = self.aya.alert_service.collect()
        except Exception:
            logger.exception("Erro ao carregar painel de alertas")
            return "### Alertas da Aya\n\nNao foi possivel carregar os alertas agora."

        if not alerts:
            return "### Alertas da Aya\n\nTudo em ordem no momento."

        lines = ["### Alertas da Aya", ""]
        for alert in alerts:
            lines.append(f"- **{alert.title}**: {alert.detail}")
            lines.append(f"  Acao sugerida: `{alert.action}`")
        return "\n".join(lines)

    def continuidade(self):
        return self.responder("/continuidade")

    def status(self):
        return self.responder("/status")

    def diagnostico(self):
        return self.responder("/diagnostico")

    def modelos(self):
        return self.responder("/modelos")

    def exportar_fine_tuning(self):
        return self.responder("/finetune")

    def refletir(self):
        return self.responder("/refletir")

    def autonomia(self, acao: str = ""):
        return self.responder(f"/autonomia {acao}".strip())

    def listar_aprendizados(self):
        return self.responder("/aprendizados")

    def revisoes(self):
        return self.responder("/revisoes")

    def incentivo(self):
        return self.responder("/incentivo")

    def conselho(self):
        return self.responder("/companhia me da um conselho")

    def diario(self):
        return self.responder("/diario")
