from __future__ import annotations

import json
import logging
import re
from typing import Any

from aya.core.llm import ChatClient
from aya.core.rag import RAGEngine
from aya.data.database import Database


logger = logging.getLogger(__name__)


class ExerciseCoach:
    """Gera, corrige e agenda revisoes de exercicios."""

    def __init__(
        self,
        db: Database,
        llm: ChatClient,
        rag: RAGEngine,
        model: str,
        system_prompt: str,
    ):
        self.db = db
        self.llm = llm
        self.rag = rag
        self.model = model
        self.system_prompt = system_prompt

    def criar_exercicio(self, texto: str) -> str:
        partes = [p.strip() for p in texto.split("|")]
        topico = partes[0] if partes else ""
        nivel = partes[1] if len(partes) > 1 else "medio"
        if not topico:
            return "Use assim: `/exercicio Python listas | facil`."

        pergunta, resposta_esperada = self._gerar_exercicio(topico, nivel)
        exercicio_id = self.db.criar_exercicio(topico, pergunta, resposta_esperada, nivel)
        self.db.registrar_evento_aprendizado(
            "exercicio_criado",
            f"{topico}: {pergunta}",
            metadata=f"exercicio_id={exercicio_id}",
        )
        return (
            f"Exercicio #{exercicio_id} sobre {topico} ({nivel}):\n"
            f"{pergunta}\n\n"
            f"Responda com `/responder {exercicio_id} | sua resposta`."
        )

    def responder_exercicio(self, texto: str) -> str:
        partes = [p.strip() for p in texto.split("|", 1)]
        if len(partes) != 2:
            return "Use assim: `/responder 3 | sua resposta`."
        exercicio_id = self._extrair_id(partes[0])
        resposta_usuario = partes[1]
        if exercicio_id is None or not resposta_usuario:
            return "Use assim: `/responder 3 | sua resposta`."

        exercicio = self.db.buscar_exercicio(exercicio_id)
        if not exercicio or exercicio["status"] != "pendente":
            return f"Nao encontrei exercicio pendente com ID {exercicio_id}."

        feedback, nota = self._corrigir_exercicio(exercicio, resposta_usuario)
        dias_revisao = self._dias_para_revisao(nota)
        self.db.registrar_resposta_exercicio(exercicio_id, resposta_usuario, feedback, nota, dias_revisao)
        self.db.registrar_evento_aprendizado(
            "exercicio_corrigido",
            f"#{exercicio_id} nota {nota:.1f}",
            metadata=f"revisar_em={dias_revisao}d",
        )

        reforco = ""
        if nota < 7:
            self.db.registrar_dificuldade(exercicio["topico"], "exercicio", feedback[:240])
            reforco = "\n\nVou considerar esse ponto como dificuldade e trazer revisao mais cedo."

        return (
            f"Correcao do exercicio #{exercicio_id}:\n"
            f"- Nota: {nota:.1f}/10\n"
            f"- Proxima revisao: em {dias_revisao} dia(s)\n\n"
            f"{feedback}{reforco}"
        )

    def listar_revisoes(self) -> str:
        revisoes = self.db.buscar_revisoes_pendentes(limite=10)
        if not revisoes:
            return "Nao ha revisoes vencidas agora."
        linhas = ["Revisoes pendentes:"]
        for item in revisoes:
            linhas.append(f"- #{item['id']} {item['topico']} (nota {item['nota']:.1f}): {item['pergunta']}")
        return "\n".join(linhas)

    def _gerar_exercicio(self, topico: str, nivel: str) -> tuple[str, str]:
        contexto = self.rag.formatar_contexto(topico, limite=5)
        prompt = (
            "Crie um exercicio curto para verificar se o usuario aprendeu o topico. "
            "Responda obrigatoriamente em JSON com as chaves pergunta e resposta_esperada. "
            "A pergunta deve exigir raciocinio, nao so definicao.\n\n"
            f"Topico: {topico}\nNivel: {nivel}\nContexto local:\n{contexto or 'Sem contexto local.'}"
        )
        try:
            conteudo = self.llm.chat(
                self.model,
                [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=350,
            )
            dados = self._extrair_json_objeto(conteudo)
            pergunta = str(dados.get("pergunta", "")).strip()
            resposta = str(dados.get("resposta_esperada", "")).strip()
            if pergunta:
                return pergunta, resposta
        except Exception:
            logger.exception("Falha ao gerar exercicio com IA")

        return (
            f"Explique {topico} com suas palavras e crie um exemplo simples de uso.",
            f"Uma boa resposta deve explicar {topico} corretamente e incluir um exemplo coerente.",
        )

    def _corrigir_exercicio(self, exercicio: Any, resposta_usuario: str) -> tuple[str, float]:
        prompt = (
            "Corrija a resposta do usuario. Responda em JSON com as chaves nota e feedback. "
            "nota deve ser um numero de 0 a 10. feedback deve ser curto, honesto e didatico.\n\n"
            f"Topico: {exercicio['topico']}\n"
            f"Pergunta: {exercicio['pergunta']}\n"
            f"Resposta esperada: {exercicio['resposta_esperada'] or 'Nao informada.'}\n"
            f"Resposta do usuario: {resposta_usuario}"
        )
        try:
            conteudo = self.llm.chat(
                self.model,
                [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=350,
            )
            dados = self._extrair_json_objeto(conteudo)
            nota = float(dados.get("nota", 0))
            feedback = str(dados.get("feedback", "")).strip()
            if feedback:
                return feedback, max(0.0, min(10.0, nota))
        except Exception:
            logger.exception("Falha ao corrigir exercicio com IA")

        palavras_chave = set(re.findall(r"\b\w{4,}\b", (exercicio["resposta_esperada"] or exercicio["topico"]).lower()))
        resposta_tokens = set(re.findall(r"\b\w{4,}\b", resposta_usuario.lower()))
        acertos = len(palavras_chave & resposta_tokens)
        nota = 7.0 if acertos else 5.0
        feedback = "Boa tentativa. Compare sua resposta com o conceito esperado e refine com um exemplo mais claro."
        return feedback, nota

    @staticmethod
    def _dias_para_revisao(nota: float) -> int:
        if nota >= 9:
            return 7
        if nota >= 7:
            return 3
        return 1

    @staticmethod
    def _extrair_id(texto: str) -> int | None:
        match = re.search(r"\d+", texto or "")
        if not match:
            return None
        return int(match.group(0))

    @staticmethod
    def _extrair_json_objeto(texto: str) -> dict:
        texto = (texto or "").strip()
        try:
            return json.loads(texto)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", texto, flags=re.DOTALL)
            if not match:
                return {}
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return {}
