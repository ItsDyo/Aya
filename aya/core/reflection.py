from __future__ import annotations

import json
import logging

from aya.core.llm import ChatClient
from aya.data.database import Database


logger = logging.getLogger(__name__)


class ReflectionService:
    """Gera reflexoes curtas para fortalecer a memoria persistente."""

    def __init__(self, db: Database, llm: ChatClient, model: str, system_prompt: str):
        self.db = db
        self.llm = llm
        self.model = model
        self.system_prompt = system_prompt

    def refletir(self) -> str:
        historico = self.db.exportar_conversas(limite=30)
        if len(historico) < 2:
            return "Ainda há pouco histórico para gerar uma reflexão útil."

        prompt = (
            "Analise o histórico abaixo e gere uma memória curta e útil sobre o usuário, "
            "seus objetivos, preferências ou dificuldades. Não invente. Responda em uma frase.\n\n"
            f"{json.dumps(historico, ensure_ascii=False)}"
        )
        try:
            reflexao = self.llm.chat(
                self.model,
                [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=180,
            )
        except Exception:
            logger.exception("Falha ao gerar reflexão")
            return "Não consegui gerar a reflexão agora."

        memoria_id = self.db.salvar_memoria("reflexao", "ultima_reflexao", reflexao, origem="refletir", confianca=0.75)
        self.db.registrar_evento_aprendizado("reflexao", reflexao, metadata=f"memoria_id={memoria_id}")
        return f"Reflexão salva: {reflexao}"
