from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

from aya.config import RUNTIME_CONFIG
from aya.data.database import Database


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContextDecision:
    action: str
    key: str = ""
    value: str = ""
    confidence: float = 0.0
    reason: str = ""
    category: str = ""
    domain: str = "geral"
    sensitive: bool = False


class LearningAutonomy:
    """Regras leves de autoaprendizado e manutencao autonoma."""

    def __init__(
        self,
        db: Database,
        reflect_callback: Callable[[], str],
        auto_reflection_interval: int,
        privacy_mode: str = "leve",
    ):
        self.db = db
        self.reflect_callback = reflect_callback
        self.enabled = True
        self.auto_reflection_interval = auto_reflection_interval
        self.privacy_mode = self.normalize_privacy_mode(privacy_mode)
        self.messages_since_reflection = 0
        self._reflection_running = False
        self.last_context_decision = ContextDecision("conversa", reason="sem mensagens analisadas")

    def decide_and_save_context(self, mensagem: str):
        decisao = self.decide_context_details(mensagem)
        self.last_context_decision = decisao

        if decisao.action == "memoria":
            self._save_memory_decision(decisao)
            return

        if decisao.action == "conhecimento":
            self._save_knowledge_decision(decisao)

    def _save_memory_decision(self, decisao: ContextDecision):
        chave = decisao.key or self.short_key(decisao.value)
        tipo = decisao.category or "assunto_atual"
        confianca = decisao.confidence or 0.65
        resultado = self.db.salvar_memoria_avancada(
            tipo,
            chave,
            decisao.value,
            origem="auto_decisao",
            confianca=confianca,
            dominio=decisao.domain,
        )
        pendente_id = self.db.salvar_aprendizado_pendente(
            "memoria",
            chave,
            decisao.value,
            tipo=tipo,
            origem="auto_decisao",
            confianca=confianca,
            status="aplicado",
            metadata=(
                f"memoria_id={resultado.memory_id};dominio={decisao.domain};motivo={decisao.reason};"
                f"acao={resultado.action};conflito_id={resultado.conflict_id or 0}"
            ),
        )
        self.db.registrar_evento_aprendizado(
            "auto_memoria_conflito" if resultado.action == "conflict" else "auto_memoria",
            f"{tipo}:{chave} = {decisao.value}",
            metadata=(
                f"memoria_id={resultado.memory_id};aprendizado_id={pendente_id};"
                f"dominio={decisao.domain};motivo={decisao.reason};acao={resultado.action};"
                f"conflito_id={resultado.conflict_id or 0}"
            ),
        )

    def _save_knowledge_decision(self, decisao: ContextDecision):
        topico = (decisao.key or self.short_key(decisao.value)).replace("_", " ")
        confianca = decisao.confidence or 0.7
        item_id = self.db.salvar_conhecimento(topico, decisao.value, tags="auto")
        pendente_id = self.db.salvar_aprendizado_pendente(
            "conhecimento",
            topico,
            decisao.value,
            tipo="auto",
            origem="auto_decisao",
            confianca=confianca,
            status="aplicado",
            metadata=f"conhecimento_id={item_id};dominio={decisao.domain};motivo={decisao.reason}",
        )
        self.db.registrar_evento_aprendizado(
            "auto_conhecimento",
            f"{topico}: {decisao.value}",
            metadata=f"conhecimento_id={item_id};aprendizado_id={pendente_id};dominio={decisao.domain};motivo={decisao.reason}",
        )

    def decide_context(self, mensagem: str) -> str:
        return self.decide_context_details(mensagem).action

    def decide_context_details(self, mensagem: str) -> ContextDecision:
        texto = (mensagem or "").strip()
        lower = self.normalize_text(texto)
        domain = self.classify_domain(texto)
        sensitive = self.privacy_blocks(texto)
        if not texto or "?" in texto:
            return ContextDecision("conversa", reason="vazio ou pergunta direta", domain=domain, sensitive=sensitive)
        if "\n" in texto or "```" in texto:
            return ContextDecision("conversa", reason="texto longo ou codigo", domain=domain, sensitive=sensitive)
        if sensitive:
            return ContextDecision(
                "conversa",
                value=texto,
                reason="conteudo sensivel nao deve ser salvo automaticamente",
                domain=domain,
                sensitive=True,
            )
        if self.looks_like_casual_ack(texto):
            return ContextDecision("conversa", reason="mensagem casual curta", domain=domain)
        if self._starts_with_conversation_request(lower):
            return ContextDecision("conversa", reason="pedido de resposta", domain=domain)

        extracted = self.extract_simple_memories(texto)
        if extracted:
            tipo, chave, valor, confianca, extracted_domain, extracted_sensitive = max(extracted, key=lambda item: item[3])
            if extracted_sensitive and self.privacy_mode != "livre":
                return ContextDecision(
                    "conversa",
                    chave,
                    valor,
                    confianca,
                    "memoria extraida parece sensivel",
                    tipo,
                    extracted_domain,
                    True,
                )
            if confianca >= 0.85:
                return ContextDecision("memoria", chave, valor, confianca, "fato direto", tipo, extracted_domain)
            return ContextDecision(
                "conversa",
                chave,
                valor,
                confianca,
                "memoria extraida requer confirmacao",
                tipo,
                extracted_domain,
                extracted_sensitive,
            )

        if self.looks_like_definition_or_note(texto):
            return ContextDecision(
                "conhecimento",
                self.short_key(texto),
                texto,
                0.72,
                "parece nota ou definicao reaproveitavel",
                "auto",
                domain,
            )

        if self.looks_like_study_subject(texto):
            return ContextDecision(
                "memoria",
                self.short_key(texto),
                texto,
                0.65,
                "parece assunto atual de estudo",
                "assunto_atual",
                domain if domain != "geral" else "estudo",
            )

        return ContextDecision("conversa", reason="nao parece memoria nem conhecimento estavel", domain=domain)

    def learn_from_user_message(self, mensagem: str):
        if self.privacy_blocks(mensagem):
            self.db.registrar_evento_aprendizado(
                "privacidade",
                "Mensagem nao salva automaticamente por parecer sensivel.",
                metadata=f"dominio={self.classify_domain(mensagem)}",
            )
            return
        aprendizados = self.extract_simple_memories(mensagem)
        for tipo, chave, valor, confianca, dominio, sensivel in aprendizados:
            if sensivel and self.privacy_mode != "livre":
                self.db.registrar_evento_aprendizado(
                    "privacidade",
                    f"{tipo}:{chave} nao salvo automaticamente por parecer sensivel.",
                    metadata=f"dominio={dominio}",
                )
                continue
            if confianca < 0.85:
                aprendizado_id = self.db.salvar_aprendizado_pendente(
                    "memoria",
                    chave,
                    valor,
                    tipo=tipo,
                    origem="auto",
                    confianca=confianca,
                    metadata=f"extraido_da_mensagem_usuario;dominio={dominio}",
                )
                self.db.registrar_evento_aprendizado(
                    "memoria_pendente",
                    f"{tipo}:{chave} = {valor}",
                    metadata=f"aprendizado_id={aprendizado_id};dominio={dominio}",
                )
                continue
            resultado = self.db.salvar_memoria_avancada(
                tipo,
                chave,
                valor,
                origem="auto",
                confianca=confianca,
                dominio=dominio,
            )
            if resultado.memory_id:
                self.db.registrar_evento_aprendizado(
                    "memoria_auto_conflito" if resultado.action == "conflict" else "memoria_auto",
                    f"{tipo}:{chave} = {valor}",
                    metadata=(
                        f"memoria_id={resultado.memory_id};dominio={dominio};acao={resultado.action};"
                        f"conflito_id={resultado.conflict_id or 0}"
                    ),
                )

    def autonomous_maintenance(self):
        if not self.enabled or self._reflection_running:
            return

        arquivadas = self.db.arquivar_memorias_temporarias_antigas(
            RUNTIME_CONFIG.memory_temporary_ttl_days
        )
        if arquivadas:
            self.db.registrar_evento_aprendizado(
                "memorias_temporarias_arquivadas",
                f"Memorias arquivadas por inatividade: {', '.join(map(str, arquivadas))}",
                metadata=f"ttl_dias={RUNTIME_CONFIG.memory_temporary_ttl_days}",
            )

        self.messages_since_reflection += 1
        if self.messages_since_reflection < self.auto_reflection_interval:
            return
        if self.db.contar_mensagens_totais() < 4:
            return

        self._reflection_running = True
        try:
            resultado = self.reflect_callback()
            self.db.registrar_evento_aprendizado(
                "auto_reflexao",
                resultado.replace("\n", " ")[:500],
                metadata=f"intervalo={self.auto_reflection_interval}",
            )
            self.messages_since_reflection = 0
        except Exception:
            logger.exception("Falha na manutencao autonoma")
        finally:
            self._reflection_running = False

    @staticmethod
    def _starts_with_conversation_request(lower: str) -> bool:
        iniciadores_conversa = (
            "explique",
            "me explique",
            "o que",
            "como",
            "por que",
            "porque",
            "qual",
            "quando",
            "onde",
            "me ajude",
            "ajude",
            "faca",
            "crie",
            "analise",
            "resuma",
            "corrija",
            "compare",
        )
        return lower.startswith(iniciadores_conversa)

    @staticmethod
    def looks_like_study_subject(texto: str) -> bool:
        lower = LearningAutonomy.normalize_text(texto)
        palavras = re.findall(r"[\w#.+-]+", texto, flags=re.UNICODE)
        if len(palavras) < 2 or len(palavras) > 6:
            return False
        if re.search(r"\b(ok|sim|nao|obrigado|obrigada|valeu|beleza|legal|certo|continue|salvar)\b", lower):
            return False
        if re.search(r"\b(e|sao|foi|quero|preciso|tenho|estou|vou|devo|pode|fazer|usar|aprender)\b", lower):
            return False
        return True

    @staticmethod
    def looks_like_definition_or_note(texto: str) -> bool:
        lower = LearningAutonomy.normalize_text(texto)
        if len(texto) < 20:
            return False
        indicadores = (
            r"\b(?:e|sao|significa|serve para|consiste em|define|representa)\b",
            r"\b(?:formula|conceito|definicao|regra)\b",
        )
        return any(re.search(pattern, lower) for pattern in indicadores)

    @staticmethod
    def looks_like_casual_ack(texto: str) -> bool:
        lower = LearningAutonomy.normalize_text(texto)
        return bool(re.fullmatch(r"(ok|sim|nao|beleza|blz|certo|entendi|valeu|obrigado|obrigada|legal)[.! ]*", lower))

    @staticmethod
    def short_key(texto: str) -> str:
        palavras = re.findall(r"[\w]{3,}", LearningAutonomy.normalize_text(texto))
        return "_".join(palavras[:4]) or "assunto"

    @staticmethod
    def extract_simple_memories(mensagem: str) -> list[tuple[str, str, str, float, str, bool]]:
        lower = LearningAutonomy.normalize_text(mensagem.strip())
        dominio_padrao = LearningAutonomy.classify_domain(mensagem)
        memorias: list[tuple[str, str, str, float, str, bool]] = []

        padroes = [
            (
                r"\bme chamo\s+(.+?)(?=\s+e\s+(?:quero|tenho|prefiro|estou|gosto|preciso)\b|[,.;\n]|$)",
                "perfil",
                "nome",
                0.95,
                "pessoal",
            ),
            (
                r"\bmeu nome e\s+(.+?)(?=\s+e\s+(?:quero|tenho|prefiro|estou|gosto|preciso)\b|[,.;\n]|$)",
                "perfil",
                "nome",
                0.95,
                "pessoal",
            ),
            (r"\bestou estudando\s+([^.,;\n]{2,80})", "estudo", "estudando_agora", 0.8, "estudo"),
            (r"\bquero aprender\s+([^.,;\n]{2,80})", "objetivo", "quer_aprender", 0.8, "estudo"),
            (r"\btenho dificuldade (?:em|com)\s+([^.,;\n]{2,80})", "dificuldade", "dificuldade_reportada", 0.85, dominio_padrao),
            (r"\bprefiro\s+([^.,;\n]{2,80})", "preferencia", "preferencia_reportada", 0.75, "pessoal"),
            (r"\bno trabalho (?:preciso|quero|devo)\s+([^.,;\n]{2,80})", "trabalho", "foco_profissional", 0.8, "trabalho"),
            (r"\bno estagio (?:preciso|quero|devo)\s+([^.,;\n]{2,80})", "trabalho", "foco_profissional", 0.8, "trabalho"),
            (r"\baprendi no trabalho\s+([^.,;\n]{2,120})", "trabalho", "aprendizado_profissional", 0.8, "trabalho"),
        ]
        for pattern, tipo, chave, confianca, dominio in padroes:
            match = re.search(pattern, lower, flags=re.IGNORECASE)
            if match:
                valor = match.group(1).strip(" .")
                sensivel = LearningAutonomy.is_sensitive(valor) or LearningAutonomy.is_sensitive(mensagem)
                memorias.append((tipo, chave, valor, confianca, dominio, sensivel))
        return memorias

    @staticmethod
    def extract_search_terms(texto: str) -> list[str]:
        palavras = re.findall(r"[\w#.+-]{4,}", LearningAutonomy.normalize_text(texto), flags=re.UNICODE)
        termos = list(dict.fromkeys(palavras[:8]))
        if texto.strip():
            termos.insert(0, texto.strip()[:80])
        return termos

    @staticmethod
    def normalize_text(texto: str) -> str:
        normalized = unicodedata.normalize("NFKD", texto or "")
        without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        return without_accents.lower().strip()

    @staticmethod
    def classify_domain(texto: str) -> str:
        lower = LearningAutonomy.normalize_text(texto)
        if re.search(r"\b(aya|assistente|meu projeto|projeto aya)\b", lower):
            return "aya"
        if re.search(r"\b(trabalho|estagio|empresa|chefe|cliente|sprint|reuniao|profissional)\b", lower):
            return "trabalho"
        if re.search(r"\b(python|javascript|java|sql|git|github|api|codigo|programacao|bug|erro|classe|funcao)\b", lower):
            return "programacao"
        if re.search(r"\b(estudar|estudo|materia|prova|exercicio|revisar|aprender|aula)\b", lower):
            return "estudo"
        if re.search(r"\b(me chamo|meu nome|prefiro|estou triste|estou frustrado|familia|amigo|rotina)\b", lower):
            return "pessoal"
        return "geral"

    @staticmethod
    def is_sensitive(texto: str) -> bool:
        lower = LearningAutonomy.normalize_text(texto)
        patterns = (
            r"\b(senha|password|token|api key|apikey|chave secreta|segredo|credential|credencial)\b",
            r"\b(cpf|rg|cnpj|cartao|pix|endereco completo|telefone de cliente)\b",
            r"\b(confidencial|sigiloso|privado da empresa|cliente interno|dados do cliente)\b",
            r"\b(producao|banco de dados da empresa|sistema interno)\b",
        )
        return any(re.search(pattern, lower) for pattern in patterns)

    def privacy_blocks(self, texto: str) -> bool:
        mode = self.normalize_privacy_mode(self.privacy_mode)
        if mode == "livre":
            return False
        if self.is_sensitive(texto):
            return True
        if mode == "estrita" and self.classify_domain(texto) == "trabalho":
            return True
        return False

    def set_privacy_mode(self, mode: str) -> str:
        self.privacy_mode = self.normalize_privacy_mode(mode)
        return self.privacy_mode

    @staticmethod
    def normalize_privacy_mode(mode: str) -> str:
        normalized = LearningAutonomy.normalize_text(mode or "leve")
        aliases = {
            "normal": "leve",
            "padrao": "leve",
            "default": "leve",
            "rigida": "estrita",
            "restrita": "estrita",
            "strict": "estrita",
            "free": "livre",
            "desligada": "livre",
            "off": "livre",
        }
        normalized = aliases.get(normalized, normalized)
        if normalized not in {"leve", "estrita", "livre"}:
            return "leve"
        return normalized
