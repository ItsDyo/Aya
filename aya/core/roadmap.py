from __future__ import annotations

from dataclasses import dataclass

from aya.data.database import Database


@dataclass
class RoadmapStatus:
    conversations: int
    knowledge: int
    memories: int
    conflicts: int
    pending_learning: int
    pending_exercises: int
    rag_status: str


class RoadmapService:
    def __init__(self, db: Database, rag_status_provider):
        self.db = db
        self.rag_status_provider = rag_status_provider

    def build(self) -> str:
        status = self._status()
        return "\n".join([
            "Roadmap Aya 1.0:",
            "- Meta: versao local estavel ate 1 de agosto de 2026.",
            "- Direcao: confiabilidade primeiro, poder depois.",
            "",
            "Estado atual:",
            f"- Conversas salvas: {status.conversations}",
            f"- Conhecimentos: {status.knowledge}",
            f"- Memorias persistentes: {status.memories}",
            f"- Conflitos de memoria: {status.conflicts}",
            f"- Aprendizados pendentes: {status.pending_learning}",
            f"- Exercicios pendentes: {status.pending_exercises}",
            f"- {status.rag_status}",
            "",
            "Prioridades para 1.0:",
            "1. Estabilidade de inicializacao e diagnostico.",
            "2. Memoria persistente confiavel e curadoria clara.",
            "3. RAG local com fontes e embeddings ativos.",
            "4. Interface simples no computador e celular.",
            "5. Ajuda de programacao com revisao antes de edicao.",
            "6. Documentacao de uso, backup e recuperacao.",
            "",
            "Fora da 1.0 por enquanto:",
            "- Telegram.",
            "- Fine-tuning real.",
            "- Automacao agressiva sem confirmacao.",
            "- Expor porta no roteador.",
            "",
            "Criterio de pronto:",
            "- ruff, compileall, unittest, smoke_test.py, pip check e banco SQLite integro.",
            "- Gradio local funcionando e acesso remoto via Tailscale seguro.",
            "- Nenhum log com credenciais ou dados sensiveis desnecessarios.",
            "",
            "Documento completo: docs/roadmap_v1.md",
        ])

    def _status(self) -> RoadmapStatus:
        return RoadmapStatus(
            conversations=self.db.contar_mensagens_totais(),
            knowledge=self.db.contar_conhecimentos(),
            memories=self.db.contar_memorias(),
            conflicts=self.db.contar_conflitos_memoria(),
            pending_learning=self.db.contar_aprendizados_pendentes(),
            pending_exercises=self.db.contar_exercicios_pendentes(),
            rag_status=self.rag_status_provider(),
        )
