from __future__ import annotations

import logging
import re
from collections.abc import Callable

from aya.core.llm import ChatClient
from aya.data.database import Database


logger = logging.getLogger(__name__)


class CompanionMode:
    """Camada de companhia: acolhe, conversa e protege limites saudaveis."""

    CRISIS_PATTERNS = (
        r"\bme matar\b",
        r"\bme machucar\b",
        r"\btirar minha vida\b",
        r"\bnao quero mais viver\b",
        r"\bnão quero mais viver\b",
        r"\bvontade de sumir\b",
        r"\bacabar com tudo\b",
    )

    PERSONAL_PATTERNS = (
        r"\bpreciso conversar\b",
        r"\bme sinto\b",
        r"\bestou triste\b",
        r"\bestou frustrad[oa]\b",
        r"\bestou cansad[oa]\b",
        r"\bestou desanimad[oa]\b",
        r"\bfoi dificil\b",
        r"\bfoi difícil\b",
        r"\bdia ruim\b",
        r"\bme da um conselho\b",
        r"\bme dá um conselho\b",
        r"\bme anima\b",
        r"\bdesabafo\b",
        r"\bcompanhia\b",
    )

    def is_crisis(self, message: str) -> bool:
        lower = (message or "").lower()
        return any(re.search(pattern, lower) for pattern in self.CRISIS_PATTERNS)

    def is_personal(self, message: str) -> bool:
        if self.is_crisis(message):
            return True
        lower = (message or "").lower()
        return any(re.search(pattern, lower) for pattern in self.PERSONAL_PATTERNS)

    def classify_tone(self, message: str) -> str:
        lower = (message or "").lower()
        if self.is_crisis(lower):
            return "crise"
        if any(word in lower for word in ("frustr", "raiva", "irrit", "travado", "travada")):
            return "frustracao"
        if any(word in lower for word in ("triste", "sozinho", "sozinha", "cansado", "cansada", "desanimado", "desanimada")):
            return "acolhimento"
        if "conselho" in lower:
            return "conselho"
        if "anima" in lower or "incentivo" in lower:
            return "incentivo"
        return "companhia"

    def crisis_response(self) -> str:
        return (
            "Eu sinto muito que voce esteja passando por isso. Eu posso ficar aqui com voce agora, "
            "mas isso e serio demais para voce carregar sozinho.\n\n"
            "Por favor, fale agora com alguem de confianca perto de voce. Se houver risco imediato, "
            "ligue para o servico de emergencia da sua regiao. No Brasil, voce tambem pode procurar "
            "o CVV pelo 188.\n\n"
            "Enquanto isso: afaste qualquer coisa que possa te machucar, sente em um lugar mais seguro "
            "e me responda so com uma coisa pequena: voce esta em seguranca neste momento?"
        )

    def system_prompt(self, user_context: str = "") -> str:
        return (
            "Voce e Aya em modo companhia pessoal. Seu papel e conversar com presenca, carinho, "
            "honestidade e respeito. Nao aja como terapeuta profissional. Nao diagnostique. "
            "Nao transforme tudo em aula. Ajude o usuario a nomear o que sente, organizar pensamentos "
            "e escolher um proximo passo pequeno.\n\n"
            "Estilo: portugues brasileiro, tom natural, acolhedor, direto e sem frases vazias. "
            "Quando fizer sentido, termine com uma pergunta simples. Se houver sinal de risco de "
            "autoagressao ou crise, oriente ajuda humana imediata.\n\n"
            f"Contexto local relevante:\n{user_context or 'Sem contexto pessoal adicional.'}"
        )

    def fallback_response(self, message: str) -> str:
        tone = self.classify_tone(message)
        if tone == "conselho":
            return (
                "Meu conselho sincero: nao tenta resolver a vida inteira de uma vez. "
                "Escolhe o menor proximo passo que melhora um pouco a situacao e faz isso primeiro. "
                "Me conta qual parte esta pesando mais agora?"
            )
        if tone == "incentivo":
            return (
                "Voce nao precisa estar no auge para continuar. Um passo pequeno ainda conta, "
                "principalmente nos dias em que a cabeca esta pesada. Estou aqui com voce. "
                "Qual e a menor coisa que da para fazer agora?"
            )
        if tone == "frustracao":
            return (
                "Eu entendo. Frustracao costuma bater mais forte quando voce esta tentando muito "
                "e parece que o resultado nao acompanha. Vamos diminuir o tamanho do problema: "
                "o que exatamente te travou hoje?"
            )
        return (
            "Estou aqui com voce. Pode falar do jeito que vier, sem precisar organizar tudo antes. "
            "O que aconteceu no seu dia?"
        )

    def summarize_for_diary(self, message: str, response: str) -> str:
        message = " ".join((message or "").split())
        response = " ".join((response or "").split())
        if len(message) > 180:
            message = message[:177] + "..."
        if len(response) > 180:
            response = response[:177] + "..."
        return f"Usuario: {message} | Aya: {response}"


class CompanionService:
    """Fluxo de companhia pessoal com diario e limites de seguranca."""

    def __init__(
        self,
        db: Database,
        llm: ChatClient,
        mode: CompanionMode,
        model: str,
        context_provider: Callable[[], str],
    ):
        self.db = db
        self.llm = llm
        self.mode = mode
        self.model = model
        self.context_provider = context_provider

    def responder(self, mensagem_usuario: str) -> str:
        self.db.salvar_mensagem("user", mensagem_usuario)
        tom = self.mode.classify_tone(mensagem_usuario)

        if self.mode.is_crisis(mensagem_usuario):
            resposta = self.mode.crisis_response()
            self.db.salvar_mensagem("assistant", resposta)
            self._registrar_diario(tom, mensagem_usuario, resposta)
            return resposta

        try:
            contexto = self.context_provider()
            prompt = self.mode.system_prompt(contexto)
            historico = self.db.carregar_historico(limite=12)
            resposta = self.llm.chat(
                self.model,
                [{"role": "system", "content": prompt}, *historico],
                temperature=0.6,
                max_tokens=500,
            )
            if not resposta.strip():
                resposta = self.mode.fallback_response(mensagem_usuario)
        except Exception:
            logger.exception("Erro ao gerar resposta de companhia")
            resposta = self.mode.fallback_response(mensagem_usuario)

        self.db.salvar_mensagem("assistant", resposta)
        self._registrar_diario(tom, mensagem_usuario, resposta)
        return resposta

    def listar_diario(self, texto: str) -> str:
        limite = 10
        if texto.strip().isdigit():
            limite = max(1, min(30, int(texto.strip())))
        registros = self.db.buscar_diario_companhia(limite=limite)
        if not registros:
            return "Ainda nao ha registros no diario de companhia."
        linhas = ["Diario de companhia:"]
        for item in registros:
            resumo = item["resumo"].replace("\n", " ").strip()
            if len(resumo) > 180:
                resumo = resumo[:177] + "..."
            linhas.append(f"- #{item['id']} [{item['tom']}] {resumo}")
        return "\n".join(linhas)

    def _registrar_diario(self, tom: str, mensagem: str, resposta: str):
        resumo = self.mode.summarize_for_diary(mensagem, resposta)
        diario_id = self.db.registrar_diario_companhia(tom, resumo, mensagem, resposta)
        if diario_id:
            self.db.registrar_evento_aprendizado("diario_companhia", resumo, metadata=f"diario_id={diario_id};tom={tom}")

        if tom in {"frustracao", "acolhimento", "conselho"}:
            pendente_id = self.db.salvar_aprendizado_pendente(
                "memoria",
                f"companhia_{tom}",
                resumo,
                tipo="companhia",
                origem="diario_companhia",
                confianca=0.55,
                metadata=f"diario_id={diario_id}",
            )
            if pendente_id:
                self.db.registrar_evento_aprendizado("companhia_pendente", resumo, metadata=f"aprendizado_id={pendente_id}")
