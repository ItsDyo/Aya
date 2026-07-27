from __future__ import annotations

from collections.abc import Callable
import json
import logging
import re

from aya.config import MODEL_CONFIG, RUNTIME_CONFIG
from aya.core.advice import TechnicalAdviceService
from aya.core.alerts import AlertService, formatar_alertas
from aya.core.aya_dev import AyaDevService
from aya.core.backup import BackupService
from aya.core.change_plan import ChangePlanService
from aya.core.code_assistant import CodeAssistant
from aya.core.command_router import CommandRouter
from aya.core.companion import CompanionMode, CompanionService
from aya.core.continuity import ContinuityReport
from aya.core.curation import CurationService
from aya.core.diagnostics import DiagnosticsService
from aya.core.exercises import ExerciseCoach
from aya.core.fine_tuning import FineTuningExporter
from aya.core.ingestion import FileIngestor
from aya.core.intent import Intent, IntentRouter
from aya.core.knowledge import KnowledgeService
from aya.core.learning import LearningAutonomy
from aya.core.llm import ChatClient, OllamaClient
from aya.core.panel import PanelBuilder
from aya.core.permissions import AccessChannel, Capability, PermissionManager
from aya.core.project_tools import ProjectTools
from aya.core.prompts import REVIEW_PROMPT as DEFAULT_REVIEW_PROMPT
from aya.core.prompts import SYSTEM_PROMPT as DEFAULT_SYSTEM_PROMPT
from aya.core.rag import RAGEngine
from aya.core.release import ReleaseReportService
from aya.core.reflection import ReflectionService
from aya.core.roadmap import RoadmapService
from aya.core.study import StudyPlanner
from aya.data.database import Database
from aya.data.memory import MemoryManager
from aya.data.session import StudySession
from aya.paths import HISTORY_PATH, PROJECT_ROOT, ensure_runtime_dirs, migrate_legacy_file


logger = logging.getLogger(__name__)


class Assistant:
    MODEL1 = MODEL_CONFIG.primary
    MODEL2 = MODEL_CONFIG.reviewer

    SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT
    REVIEW_PROMPT = DEFAULT_REVIEW_PROMPT

    HISTORICO_JSON = HISTORY_PATH

    COMMAND_NAMES = (
        "/ajuda", "/help", "/salvar", "/buscar", "/estudar", "/encerrar", "/meta", "/metas",
        "/dificuldade", "/painel", "/status", "/roadmap", "/release", "/perfil", "/codigo",
        "/finetune", "/diagnostico", "/modelos", "/backup", "/memoria", "/memorias", "/rag",
        "/ragstatus", "/reindexar", "/ingerir", "/fontes", "/lembrar", "/refletir", "/autonomia",
        "/privacidade", "/aprendizados", "/aprovar", "/rejeitar", "/curadoria", "/higiene",
        "/conflitos", "/resolver", "/fundir", "/historico", "/confirmar", "/esquecer",
        "/arquivar", "/restaurar", "/editar", "/dominio", "/adiar", "/ignorar", "/retomar",
        "/exercicio", "/responder", "/revisoes", "/companhia", "/desabafo", "/conselho",
        "/incentivo", "/diario", "/continuidade", "/resumo", "/ondeparamos", "/projeto",
        "/auditar", "/arquivo", "/revisar", "/plano", "/alertas", "/aya-dev",
    )

    def __init__(
        self,
        db: Database | None = None,
        llm: ChatClient | None = None,
        model_primary: str | None = None,
        model_reviewer: str | None = None,
    ):
        self.db = db or Database()
        ensure_runtime_dirs()
        migrate_legacy_file("historico_aya.json", self.HISTORICO_JSON)
        self.llm = llm or OllamaClient()
        self.memoria = MemoryManager(self.db)
        self.rag = RAGEngine(self.db)
        self.intent_router = IntentRouter()
        self.companion = CompanionMode()
        self.continuity = ContinuityReport()
        self.curation = CurationService(self.db)
        self.backups = BackupService(self.db)
        self.panel = PanelBuilder()
        self.ingestor = FileIngestor()
        self.model_primary = model_primary or self.MODEL1
        self.model_reviewer = model_reviewer or self.MODEL2
        self.diagnostics = DiagnosticsService(
            self.db,
            self.llm,
            self.model_primary,
            self.model_reviewer,
            self.ver_status,
            self.backups.resumo,
        )
        self.companion_service = CompanionService(
            self.db,
            self.llm,
            self.companion,
            self.model_primary,
            lambda: self.memoria.construir_contexto_completo(self.sessao_ativa),
        )
        self.fine_tuning = FineTuningExporter(self.db, self.SYSTEM_PROMPT)
        self.reflection = ReflectionService(self.db, self.llm, self.model_primary, self.SYSTEM_PROMPT)
        self.learning = LearningAutonomy(
            self.db,
            self.refletir,
            RUNTIME_CONFIG.auto_reflection_interval,
            privacy_mode=RUNTIME_CONFIG.privacy_mode,
        )
        self.knowledge = KnowledgeService(self.db, self.rag, self.ingestor, self.learning.extract_search_terms)
        self.exercise_coach = ExerciseCoach(self.db, self.llm, self.rag, self.model_primary, self.SYSTEM_PROMPT)
        self.code_assistant = CodeAssistant()
        self.change_plan = ChangePlanService()
        self.project_tools = ProjectTools()
        self.aya_dev = AyaDevService(
            PROJECT_ROOT,
            self.llm,
            self.project_tools,
            self.model_primary,
            self.model_reviewer,
        )
        self.roadmap = RoadmapService(self.db, self.rag.status)
        self.release = ReleaseReportService(self.db, self.rag.status, self.diagnostico)
        self.advice = TechnicalAdviceService(
            self.db,
            self.project_tools,
            self.rag.status,
            self.diagnostico,
            self.release.listar,
            self.release.ultimo_completo,
            self.backups.resumo,
            self.curation.resumo_higiene,
        )
        self.alert_service = AlertService(self.db, aya_dev=self.aya_dev, curation=self.curation)
        self.permissions = PermissionManager()
        self.command_router = CommandRouter(set(self.COMMAND_NAMES), self.permissions, self._command_capability)
        self.study = StudyPlanner(self.db)
        self.sessao_ativa: StudySession | None = None
        self.autonomia_ativa = True
        self.auto_reflexao_intervalo = RUNTIME_CONFIG.auto_reflection_interval
        self._mensagens_desde_reflexao = 0
        self._auto_reflexao_em_andamento = False
        self._migrar_historico_json()

    def responder(
        self,
        mensagem_usuario: str,
        channel: AccessChannel | str = AccessChannel.LOCAL_TERMINAL,
    ) -> str:
        channel = self.permissions.normalize_channel(channel)
        mensagem_usuario = (mensagem_usuario or "").strip()
        if not mensagem_usuario:
            return "Digite uma mensagem ou um comando para eu te ajudar."

        if mensagem_usuario.startswith("/"):
            return self.executar_comando(mensagem_usuario, channel)

        aya_dev_response = self._responder_aya_dev_natural(mensagem_usuario)
        if aya_dev_response:
            return aya_dev_response

        denial = self._authorize(channel, Capability.CHAT)
        if denial:
            return denial
        conflitos_antes = self.db.contar_conflitos_memoria()

        acao_automatica = self._executar_intencao_natural(mensagem_usuario, channel)
        if acao_automatica:
            return acao_automatica

        if self.companion.is_personal(mensagem_usuario):
            denial = self._authorize(channel, Capability.COMPANION)
            if denial:
                return denial
            return self._responder_companhia(mensagem_usuario)

        if self.permissions.allows(channel, Capability.MEMORY_AUTO_WRITE):
            self._decidir_e_salvar_contexto_automatico(mensagem_usuario)

        return self._responder_com_ia(mensagem_usuario, channel, conflitos_antes)

    def executar_comando(
        self,
        comando: str,
        channel: AccessChannel | str = AccessChannel.LOCAL_TERMINAL,
    ) -> str:
        channel = self.permissions.normalize_channel(channel)
        route = self.command_router.route(comando, channel)
        nome = route.parsed.name
        resto = route.parsed.payload

        comandos = self._command_handlers(resto, channel)

        acao = comandos.get(nome)
        if not acao:
            return f"Não reconheci o comando `{nome}`. Use `/ajuda` para ver o que eu já sei fazer."

        denial = self._authorize(channel, route.capability)
        if denial:
            return denial

        try:
            return acao()
        except Exception:
            logger.exception("Erro ao executar comando %s", nome)
            return "Tive um problema ao executar esse comando. Registrei o erro para análise."

    def _command_handlers(self, resto: str, channel: AccessChannel) -> dict[str, Callable[[], str]]:
        return {
            "/ajuda": lambda: self.ajuda(),
            "/help": lambda: self.ajuda(),
            "/salvar": lambda: self._comando_salvar(resto),
            "/buscar": lambda: self._comando_buscar(resto),
            "/estudar": lambda: self._comando_estudar(resto),
            "/encerrar": lambda: self.encerrar_sessao(resto),
            "/meta": lambda: self._comando_meta(resto),
            "/metas": lambda: self.ver_metas(),
            "/dificuldade": lambda: self._comando_dificuldade(resto),
            "/painel": lambda: self.painel(),
            "/status": lambda: self.ver_status(),
            "/roadmap": lambda: self.roadmap.build(),
            "/release": lambda: self._comando_release(resto),
            "/perfil": lambda: self._comando_perfil(resto),
            "/codigo": lambda: self._comando_codigo(resto, channel),
            "/finetune": lambda: self.exportar_fine_tuning(),
            "/diagnostico": lambda: self.diagnostico(),
            "/modelos": lambda: self.modelos(),
            "/backup": lambda: self._comando_backup(resto),
            "/memoria": lambda: self.memoria.construir_contexto_completo(self.sessao_ativa),
            "/memorias": lambda: self.curation.listar_memorias(resto),
            "/rag": lambda: self._comando_rag(resto),
            "/ragstatus": lambda: self.knowledge.status_rag(),
            "/reindexar": lambda: self.knowledge.reindexar_rag("forcar" in resto.lower()),
            "/ingerir": lambda: self._comando_ingerir(resto),
            "/fontes": lambda: self._comando_fontes(resto),
            "/lembrar": lambda: self._comando_lembrar(resto),
            "/refletir": lambda: self.refletir(),
            "/autonomia": lambda: self._comando_autonomia(resto),
            "/privacidade": lambda: self._comando_privacidade(resto),
            "/aprendizados": lambda: self._comando_aprendizados(resto),
            "/aprovar": lambda: self._comando_aprovar_aprendizado(resto),
            "/rejeitar": lambda: self._comando_rejeitar_aprendizado(resto),
            "/curadoria": lambda: self._comando_curadoria(resto),
            "/higiene": lambda: self._comando_higiene(resto),
            "/conflitos": lambda: self.curation.listar_conflitos(resto),
            "/resolver": lambda: self.curation.resolver_conflito(resto),
            "/fundir": lambda: self.curation.fundir_memorias(resto),
            "/historico": lambda: self.curation.historico_memoria(resto),
            "/confirmar": lambda: self._comando_confirmar_memoria(resto),
            "/esquecer": lambda: self._comando_esquecer_memoria(resto),
            "/arquivar": lambda: self.curation.arquivar_memoria(resto),
            "/restaurar": lambda: self.curation.restaurar_memoria(resto),
            "/editar": lambda: self.curation.editar_memoria(resto),
            "/dominio": lambda: self.curation.alterar_dominio_memoria(resto),
            "/adiar": lambda: self.curation.adiar_memoria(resto),
            "/ignorar": lambda: self.curation.ignorar_memoria(resto),
            "/retomar": lambda: self.curation.retomar_memoria(resto),
            "/exercicio": lambda: self._comando_exercicio(resto),
            "/responder": lambda: self._comando_responder_exercicio(resto),
            "/revisoes": lambda: self._comando_revisoes(),
            "/companhia": lambda: self._comando_companhia(resto),
            "/desabafo": lambda: self._comando_companhia(resto or "preciso desabafar"),
            "/conselho": lambda: self.advice.build(),
            "/incentivo": lambda: self._comando_companhia(resto or "me anima um pouco"),
            "/diario": lambda: self._comando_diario_companhia(resto),
            "/continuidade": lambda: self.continuidade(),
            "/resumo": lambda: self.continuidade(),
            "/ondeparamos": lambda: self.continuidade(),
            "/projeto": lambda: self.project_tools.resumir_projeto(),
            "/auditar": lambda: self.project_tools.diagnosticar_projeto(),
            "/arquivo": lambda: self._comando_arquivo(resto),
            "/revisar": lambda: self._comando_revisar(resto, channel),
            "/plano": lambda: self._comando_plano_alteracao(resto, channel),
            "/alertas": lambda: self._comando_alertas(),
            "/aya-dev": lambda: self.aya_dev.execute(resto),
        }

    def _responder_aya_dev_natural(self, mensagem: str) -> str:
        texto = mensagem.lower()
        match = re.search(r"\bdev-\d{8}-[a-f0-9]{6}\b", mensagem, re.IGNORECASE)
        if not match or not any(term in texto for term in ("aya dev", "aya-dev", "proposta", "patch", "falha")):
            return ""
        proposal_id = match.group(0)
        if any(term in texto for term in ("falha", "erro", "falhou", "motivo")):
            return self.aya_dev.falha(proposal_id)
        if any(term in texto for term in ("diff", "patch")):
            return self.aya_dev.diff(proposal_id)
        return self.aya_dev.mostrar(proposal_id)

    def ajuda(self) -> str:
        return """Voce pode falar naturalmente comigo. Comandos sao atalhos, nao obrigacao.

Exemplos naturais:
- "vou estudar matematica por 25 minutos"
- "quero estudar Python"
- "terminei de estudar, revisei fracoes"
- "crie um exercicio sobre listas em Python"
- "responder exercicio 1 | listas guardam valores"
- "ingira README.md"
- "mostre fontes sobre memoria persistente"
- "estou frustrado hoje"
- "onde paramos"
- "crie um plano para alterar aya/core/assistant.py para separar responsabilidades"
- "me ajude com codigo: ..."

Atalhos manuais por area:

Estudo:
/estudar materia | minutos
/encerrar notas
/exercicio topico | nivel
/responder id | resposta
/revisoes

Memoria e conhecimento:
/salvar topico | conteudo | tags
/buscar termo
/memoria
/memorias dominio|fracas
/rag consulta
/ragstatus
/reindexar rag
/ingerir caminho
/fontes termo
/lembrar tipo | chave | valor
/aprendizados
/aprovar id
/rejeitar id
/curadoria
/higiene
/alertas
/conflitos
/resolver conflito id | aceitar ou rejeitar
/fundir memoria id_principal | id_duplicada
/historico memoria id
/backup criar
/backup listar
/backup verificar nome_do_backup.zip
/confirmar memoria id
/esquecer memoria id
/arquivar memoria id
/restaurar memoria id
/editar memoria id | novo valor
/dominio memoria id | dominio
/adiar memoria id
/ignorar memoria id
/retomar memoria id
/revisar memoria id

Companhia:
/companhia mensagem
/desabafo mensagem
/companhia me da um conselho
/incentivo mensagem
/diario

Continuidade e projeto:
/status
/roadmap
/conselho
/release
/continuidade
/meta tipo | descricao
/metas
/dificuldade materia | topico | descricao
/projeto
/auditar
/arquivo caminho_relativo
/revisar caminho_relativo
/plano caminho_relativo | objetivo
/codigo problema ou codigo
/aya-dev status|mapear|auditar|propostas|mostrar id

Sistema:
/autonomia
/privacidade
/refletir
/modelos
/diagnostico
/finetune"""

    def _executar_intencao_natural(self, mensagem: str, channel: AccessChannel) -> str | None:
        intent = self.intent_router.detect(mensagem)
        if not intent:
            return None
        denial = self._authorize(channel, self._intent_capability(intent))
        if denial:
            return denial
        try:
            return self._aplicar_intencao(intent, channel)
        except Exception:
            logger.exception("Erro ao aplicar intencao natural %s", intent.name)
            return None

    def _aplicar_intencao(self, intent: Intent, channel: AccessChannel) -> str:
        slots = intent.slots
        if intent.name == "painel":
            return self.painel()
        if intent.name == "status":
            return self.ver_status()
        if intent.name == "roadmap":
            return self.roadmap.build()
        if intent.name == "release":
            return self._comando_release(str(slots.get("salvar", "")))
        if intent.name == "continuidade":
            return self.continuidade()
        if intent.name == "diagnostico":
            return self.diagnostico()
        if intent.name == "modelos":
            return self.modelos()
        if intent.name == "backup":
            return self._comando_backup(str(slots.get("acao", "")))
        if intent.name == "autonomia":
            return self._comando_autonomia(str(slots.get("acao", "")))
        if intent.name == "privacidade":
            return self._comando_privacidade(str(slots.get("modo", "")))
        if intent.name == "projeto":
            return self.project_tools.resumir_projeto()
        if intent.name == "auditar_projeto":
            return self.project_tools.diagnosticar_projeto()
        if intent.name == "arquivo":
            return self.project_tools.ler_arquivo(str(slots["path"]))
        if intent.name == "revisar_arquivo":
            return self._comando_revisar_arquivo(str(slots["path"]), channel)
        if intent.name == "plano_alteracao":
            objetivo = str(slots.get("objetivo", ""))
            return self._comando_plano_alteracao(f"{slots['path']} | {objetivo}", channel)
        if intent.name == "codigo":
            return self._comando_codigo(str(slots.get("conteudo", "")), channel)
        if intent.name == "refletir":
            return self.refletir()
        if intent.name == "aprendizados":
            return self._comando_aprendizados("")
        if intent.name == "higiene":
            return self._comando_higiene("")
        if intent.name == "confirmar_rascunho":
            return self.curation.confirmar_ultimo_rascunho(str(slots.get("dominio", "")))
        if intent.name == "rejeitar_rascunho":
            return self.curation.rejeitar_ultimo_rascunho()
        if intent.name == "aprovar_aprendizado":
            return self._comando_aprovar_aprendizado(str(slots["id"]))
        if intent.name == "rejeitar_aprendizado":
            return self._comando_rejeitar_aprendizado(str(slots["id"]))
        if intent.name == "exercicio":
            return self._comando_exercicio(f"{slots['topico']} | {slots.get('nivel', 'medio')}")
        if intent.name == "responder_exercicio":
            return self._comando_responder_exercicio(f"{slots['id']} | {slots['resposta']}")
        if intent.name == "revisoes":
            return self._comando_revisoes()
        if intent.name == "companhia":
            return self._responder_companhia(str(slots.get("mensagem", "")))
        if intent.name == "iniciar_sessao":
            return self.iniciar_sessao(str(slots["materia"]), int(slots["minutos"]))
        if intent.name == "encerrar_sessao":
            return self.encerrar_sessao(str(slots.get("notas", "")))
        if intent.name == "metas":
            return self.ver_metas()
        if intent.name == "meta":
            return self.criar_meta(str(slots["descricao"]), str(slots.get("tipo", "geral")))
        if intent.name == "dificuldade":
            return self.registrar_dificuldade(
                str(slots.get("materia", "geral")),
                str(slots["topico"]),
                str(slots.get("descricao", "")),
            )
        if intent.name == "memoria":
            return self.memoria.construir_contexto_completo(self.sessao_ativa)
        if intent.name == "lembrar":
            resultado = self.db.salvar_memoria_avancada(
                str(slots["tipo"]),
                str(slots["chave"]),
                str(slots["valor"]),
                origem="natural",
                confianca=0.85,
            )
            self.db.registrar_evento_aprendizado(
                "memoria_natural",
                f"{slots['tipo']}:{slots['chave']} = {slots['valor']}",
                metadata=(
                    f"memoria_id={resultado.memory_id};acao={resultado.action};"
                    f"conflito_id={resultado.conflict_id or 0}"
                ),
            )
            if resultado.action == "conflict":
                return self._resposta_salvamento_memoria(resultado, str(slots["valor"]))
            acao = " e reforcei essa lembranca" if resultado.action == "reinforced" else ""
            return f"Guardei isso na memória{acao}: {slots['valor']}"
        if intent.name == "salvar_conhecimento":
            return self.salvar_conhecimento(
                str(slots["topico"]),
                str(slots["conteudo"]),
                str(slots.get("tags", "auto")),
            )
        if intent.name == "ingerir":
            return self._comando_ingerir(str(slots.get("path", ".")))
        if intent.name == "fontes":
            return self._comando_fontes(str(slots.get("termo", "")))
        if intent.name == "rag":
            return self._comando_rag(str(slots.get("termo", "")))
        if intent.name == "buscar":
            contexto = self.rag.formatar_contexto(str(slots["termo"]), limite=10)
            return contexto or self._comando_buscar(str(slots["termo"]))
        return ""

    def _decidir_e_salvar_contexto_automatico(self, mensagem: str):
        self.learning.decide_and_save_context(mensagem)

    def _decidir_contexto_automatico(self, mensagem: str) -> str:
        return self.learning.decide_context(mensagem)

    def _parece_assunto_de_estudo(self, texto: str) -> bool:
        return self.learning.looks_like_study_subject(texto)

    def _parece_definicao_ou_nota(self, texto: str) -> bool:
        return self.learning.looks_like_definition_or_note(texto)

    def _chave_curta(self, texto: str) -> str:
        return self.learning.short_key(texto)

    def salvar_conhecimento(self, topico: str, conteudo: str, tags: str = "") -> str:
        return self.knowledge.salvar_conhecimento(topico, conteudo, tags)

    def iniciar_sessao(self, materia: str, minutos: int) -> str:
        resposta, self.sessao_ativa = self.study.iniciar_sessao(materia, minutos, self.sessao_ativa)
        return resposta

    def encerrar_sessao(self, notas: str = "") -> str:
        resposta, self.sessao_ativa = self.study.encerrar_sessao(notas, self.sessao_ativa)
        return resposta

    def criar_meta(self, descricao: str, tipo: str = "geral") -> str:
        return self.study.criar_meta(descricao, tipo)

    def ver_metas(self) -> str:
        return self.study.ver_metas()

    def registrar_dificuldade(self, materia: str, topico: str, descricao: str = "") -> str:
        return self.study.registrar_dificuldade(materia, topico, descricao)

    def ver_status(self) -> str:
        resumo = self.db.buscar_resumo_semanal()
        hoje = self.db.buscar_sessoes_hoje()
        linhas = [
            "Status da Aya:",
            f"- Modelo principal: {self.model_primary}",
            f"- Modelo revisor: {self.model_reviewer}",
            f"- Conversas salvas: {self.db.contar_mensagens_totais()}",
            f"- Conhecimentos salvos: {self.db.contar_conhecimentos()}",
            f"- Memorias persistentes: {self.db.contar_memorias()}",
            f"- Conflitos de memoria pendentes: {self.db.contar_conflitos_memoria()}",
            f"- {self.rag.status()}",
            f"- Aprendizados pendentes: {self.db.contar_aprendizados_pendentes()}",
            f"- Exercicios pendentes: {self.db.contar_exercicios_pendentes()}",
            f"- Registros de companhia: {self.db.contar_diario_companhia()}",
            f"- Autonomia leve: {'ligada' if self.autonomia_ativa else 'desligada'}",
            f"- Privacidade: {self.learning.privacy_mode}",
            f"- Auto-reflexao: a cada {self.auto_reflexao_intervalo} resposta(s)",
            f"- Sessoes hoje: {len(hoje)}",
            f"- Ultimos 7 dias: {resumo['total_sessoes']} sessao(oes), {resumo['total_minutos']} minuto(s), {resumo['materias_distintas']} materia(s)",
        ]
        if self.sessao_ativa:
            linhas.append(f"- Sessão ativa: {self.sessao_ativa.resumo_para_display()}")
        return "\n".join(linhas)

    def painel(self) -> str:
        resumo = self.db.buscar_resumo_semanal()
        metas = self.db.buscar_metas_ativas()
        panel_limit = RUNTIME_CONFIG.panel_limit
        return self.panel.build(
            resumo=resumo,
            sessao_ativa=self.sessao_ativa,
            total_conversas=self.db.contar_mensagens_totais(),
            total_conhecimentos=self.db.contar_conhecimentos(),
            total_memorias=self.db.contar_memorias(),
            metas=metas[:panel_limit],
            revisoes=self.db.buscar_revisoes_pendentes(limite=panel_limit),
            dificuldades=self.db.buscar_dificuldades_abertas(limite=panel_limit),
            memorias_revisao=self.db.buscar_memorias_para_revisao(limite=panel_limit),
            aprendizados=self.db.listar_aprendizados_pendentes(limite=panel_limit),
            eventos=self.db.buscar_eventos_aprendizado(limite=4),
            higiene=self.curation.resumo_higiene(),
        )

    def continuidade(self) -> str:
        return self.continuity.build(
            status=self.ver_status(),
            metas=self.db.buscar_metas_ativas(),
            dificuldades=self.db.buscar_dificuldades_abertas(limite=6),
            sessoes=self.db.buscar_historico_sessoes(limite=6),
            revisoes=self.db.buscar_revisoes_pendentes(limite=6),
            aprendizados=self.db.listar_aprendizados_pendentes(limite=6),
            diario=self.db.buscar_diario_companhia(limite=6),
            eventos=self.db.buscar_eventos_aprendizado(limite=8),
            memorias=self.db.buscar_memorias(limite=6),
            higiene=self.curation.resumo_higiene(),
        )

    def diagnostico(self) -> str:
        return self.diagnostics.diagnostico()

    def modelos(self) -> str:
        return self.diagnostics.modelos()

    def _comando_release(self, resto: str = "") -> str:
        acao = (resto or "").lower()
        if "perfil-testes" in acao or "perfil testes" in acao:
            return self.release.perfil_testes(acao)
        if "executar" in acao or "validar" in acao or "rodar" in acao:
            mode = "rapido" if "rapido" in acao or "rápido" in acao else "completo"
            reuse = "reutilizar" in acao or "reusar" in acao
            return self.release.validar(mode=mode, reuse=reuse)
        if "status" in acao:
            return self.release.status()
        if "listar" in acao or "historico" in acao or "releases" in acao:
            return self.release.listar()
        if "ultimo" in acao or "ultima" in acao:
            return self.release.ultimo()
        if "comparar" in acao:
            return self.release.comparar()
        salvar = "salvar" in acao or "gerar" in acao
        return self.release.build(salvar=salvar)

    def _comando_backup(self, resto: str) -> str:
        acao, _, detalhe = (resto or "").strip().partition(" ")
        acao = acao.strip().lower()
        detalhe = detalhe.strip()
        if acao in {"", "listar", "lista", "ver", "backups"}:
            return self.backups.listar_backups()
        if acao in {"criar", "novo", "gerar", "fazer"}:
            return self.backups.criar_backup(detalhe)
        if acao in {"verificar", "checar", "validar"}:
            return self.backups.verificar_backup(detalhe)
        if acao in {"extrair", "restaurar", "recuperar"}:
            return self.backups.extrair_backup(detalhe)
        return "Use assim: `/backup criar`, `/backup listar`, `/backup verificar nome_do_backup.zip` ou `/backup extrair nome_do_backup.zip`."

    def _comando_autonomia(self, resto: str) -> str:
        acao = (resto or "").strip().lower()
        if acao in {"on", "ligar", "ativa", "ativar"}:
            self.autonomia_ativa = True
            self.learning.enabled = True
            return "Autonomia leve ligada. Vou refletir periodicamente em silencio e atualizar memorias uteis."
        if acao in {"off", "desligar", "pausar", "desativar"}:
            self.autonomia_ativa = False
            self.learning.enabled = False
            return "Autonomia leve desligada. Continuo respondendo normalmente, sem manutencao automatica."
        if acao in {"refletir", "agora"}:
            return self.refletir()

        estado = "ligada" if self.autonomia_ativa else "desligada"
        self._mensagens_desde_reflexao = self.learning.messages_since_reflection
        ultima_decisao = self.learning.last_context_decision
        return (
            "Autonomia leve da Aya:\n"
            f"- Estado: {estado}\n"
            f"- Auto-reflexao: a cada {self.auto_reflexao_intervalo} resposta(s)\n"
            f"- Privacidade: {self.learning.privacy_mode}\n"
            f"- Respostas desde a ultima reflexao: {self._mensagens_desde_reflexao}\n\n"
            f"- Ultima decisao de contexto: {ultima_decisao.action}"
            f" ({ultima_decisao.reason or 'sem motivo registrado'})\n\n"
            "Use `/autonomia on`, `/autonomia off` ou `/autonomia refletir`."
        )

    def _comando_privacidade(self, resto: str) -> str:
        modo = (resto or "").strip().lower()
        if modo:
            self.learning.set_privacy_mode(modo)
        atual = self.learning.privacy_mode
        explicacao = {
            "leve": "bloqueia salvamento automatico de senhas, tokens, credenciais e dados sensiveis.",
            "estrita": "tambem evita salvar automaticamente qualquer coisa de trabalho.",
            "livre": "nao bloqueia salvamento automatico por privacidade. Use com cuidado.",
        }[atual]
        return (
            "Privacidade da Aya:\n"
            f"- Modo atual: {atual}\n"
            f"- Regra: {explicacao}\n\n"
            "Use `/privacidade leve`, `/privacidade estrita` ou `/privacidade livre`."
        )

    def _comando_companhia(self, resto: str) -> str:
        mensagem = (resto or "").strip()
        if not mensagem:
            return (
                "Estou aqui com voce. Pode me contar como foi seu dia, pedir um conselho "
                "ou so desabafar um pouco."
            )
        return self._responder_companhia(mensagem)

    def _responder_companhia(self, mensagem_usuario: str) -> str:
        return self.companion_service.responder(mensagem_usuario)

    def _comando_diario_companhia(self, resto: str) -> str:
        return self.companion_service.listar_diario(resto)

    def exportar_fine_tuning(self, caminho: str | None = None) -> str:
        return self.fine_tuning.exportar(caminho)

    def refletir(self) -> str:
        return self.reflection.refletir()

    def encerrar(self):
        if self.sessao_ativa:
            self.encerrar_sessao("Encerrada automaticamente.")
        self.db.fechar()

    def _responder_com_ia(
        self,
        mensagem_usuario: str,
        channel: AccessChannel = AccessChannel.LOCAL_TERMINAL,
        conflitos_antes: int | None = None,
    ) -> str:
        if conflitos_antes is None:
            conflitos_antes = self.db.contar_conflitos_memoria()
        self.db.salvar_mensagem("user", mensagem_usuario)
        pendentes_antes = self.db.contar_aprendizados_pendentes()
        can_auto_write = self.permissions.allows(channel, Capability.MEMORY_AUTO_WRITE)
        if can_auto_write:
            self._aprender_com_mensagem_usuario(mensagem_usuario)
        try:
            contexto = self._montar_contexto(mensagem_usuario, channel)
            if channel == AccessChannel.LIMITED_INTEGRATION:
                historico = [{"role": "user", "content": mensagem_usuario}]
            else:
                historico = self.db.carregar_historico(limite=20)
            resposta_base = self.llm.chat(
                self.model_primary,
                [{"role": "system", "content": contexto}, *historico],
                temperature=MODEL_CONFIG.primary_temperature,
                max_tokens=MODEL_CONFIG.primary_max_tokens,
            )
            resposta_final = self._revisar_resposta(mensagem_usuario, resposta_base)
        except Exception:
            logger.exception("Erro ao gerar resposta da Aya")
            resposta_final = (
                "Tive um problema ao falar com o modelo local. "
                "Confere se o Ollama está aberto e se os modelos estão instalados?"
            )

        if can_auto_write:
            resposta_final = self._anexar_aviso_rascunho(resposta_final, pendentes_antes)
            resposta_final = self._anexar_aviso_conflito(resposta_final, conflitos_antes)
        self.db.salvar_mensagem("assistant", resposta_final)
        if can_auto_write:
            self._manutencao_autonoma()
        return resposta_final

    def _anexar_aviso_conflito(self, resposta: str, conflitos_antes: int) -> str:
        conflitos_depois = self.db.contar_conflitos_memoria()
        if conflitos_depois <= conflitos_antes:
            return resposta
        conflito = self.db.listar_conflitos_memoria(limite=1)[0]
        return (
            resposta
            + "\n\nNotei uma mudança que conflita com uma memória anterior e não substituí nada. "
            + f"Deixei o conflito #{conflito['id']} na curadoria para você decidir."
        )

    def _anexar_aviso_rascunho(self, resposta: str, pendentes_antes: int) -> str:
        if self.db.contar_aprendizados_pendentes() <= pendentes_antes:
            return resposta
        pendente = self.db.listar_aprendizados_pendentes(limite=1)[0]
        if pendente["categoria"] != "memoria":
            return resposta
        aviso = (
            "\n\nPosso guardar isso como rascunho de memoria. "
            "Responda `pode guardar`, `nao salva` ou `guarda como trabalho/estudo/pessoal`."
        )
        return resposta + aviso

    def _manutencao_autonoma(self):
        self.learning.enabled = self.autonomia_ativa
        self.learning.auto_reflection_interval = self.auto_reflexao_intervalo
        self.learning.autonomous_maintenance()
        self._mensagens_desde_reflexao = self.learning.messages_since_reflection
        self._auto_reflexao_em_andamento = self.learning._reflection_running

    def _montar_contexto(self, mensagem_usuario: str, channel: AccessChannel) -> str:
        partes = [self.SYSTEM_PROMPT]
        can_read_memory = self.permissions.allows(channel, Capability.MEMORY_READ)
        can_read_knowledge = self.permissions.allows(channel, Capability.KNOWLEDGE_READ)
        can_read_rag = self.permissions.allows(channel, Capability.RAG_READ)
        if can_read_memory:
            partes.append(self.memoria.construir_contexto_completo(self.sessao_ativa))
        if can_read_knowledge and not can_read_rag:
            partes.append(self._buscar_conhecimento_relevante(mensagem_usuario))
        if can_read_rag:
            partes.append(self.rag.formatar_contexto(mensagem_usuario, limite=8))
        return "\n\n".join(parte for parte in partes if parte)

    def _buscar_conhecimento_relevante(self, mensagem_usuario: str) -> str:
        return self.knowledge.contexto_relevante(mensagem_usuario)

    def _aprender_com_mensagem_usuario(self, mensagem: str):
        self.learning.learn_from_user_message(mensagem)

    def _extrair_memorias_simples(self, mensagem: str) -> list[tuple[str, str, str, float, str, bool]]:
        return self.learning.extract_simple_memories(mensagem)

    def _extrair_termos(self, texto: str) -> list[str]:
        return self.learning.extract_search_terms(texto)

    def _revisar_resposta(self, pergunta: str, resposta_base: str) -> str:
        try:
            return self.llm.chat(
                self.model_reviewer,
                [
                    {"role": "system", "content": self.REVIEW_PROMPT},
                    {"role": "user", "content": f"Pergunta:\n{pergunta}\n\nResposta candidata:\n{resposta_base}"},
                ],
                temperature=MODEL_CONFIG.reviewer_temperature,
                max_tokens=MODEL_CONFIG.reviewer_max_tokens,
            )
        except Exception:
            logger.exception("Modelo revisor falhou; usando resposta base")
            return resposta_base

    def _comando_salvar(self, resto: str) -> str:
        partes = [p.strip() for p in resto.split("|")]
        if len(partes) < 2:
            return "Use assim: `/salvar tópico | conteúdo | tags opcionais`."
        tags = partes[2] if len(partes) >= 3 else ""
        return self.salvar_conhecimento(partes[0], partes[1], tags)

    def _comando_buscar(self, termo: str) -> str:
        return self.knowledge.buscar_conhecimento(termo)

    def _comando_estudar(self, resto: str) -> str:
        partes = [p.strip() for p in resto.split("|")]
        if len(partes) != 2:
            return "Use assim: `/estudar Matemática | 25`."
        try:
            minutos = int(partes[1])
        except ValueError:
            return "Os minutos precisam ser um número. Ex: `/estudar Python | 30`."
        return self.iniciar_sessao(partes[0], minutos)

    def _comando_meta(self, resto: str) -> str:
        partes = [p.strip() for p in resto.split("|")]
        if len(partes) < 2:
            return self.criar_meta(resto, "geral")
        return self.criar_meta(partes[1], partes[0])

    def _comando_dificuldade(self, resto: str) -> str:
        partes = [p.strip() for p in resto.split("|")]
        if len(partes) < 2:
            return "Use assim: `/dificuldade matéria | tópico | descrição opcional`."
        descricao = partes[2] if len(partes) >= 3 else ""
        return self.registrar_dificuldade(partes[0], partes[1], descricao)

    def _comando_perfil(self, resto: str) -> str:
        partes = [p.strip() for p in resto.split("|")]
        if len(partes) != 2:
            perfil = self.db.carregar_perfil()
            if not perfil:
                return "Seu perfil ainda está vazio. Use `/perfil chave | valor` para salvar algo."
            return "\n".join([f"{chave}: {valor}" for chave, valor in perfil.items()])
        self.db.salvar_perfil(partes[0], partes[1])
        return f"Guardei no seu perfil: {partes[0]} = {partes[1]}."

    def _comando_rag(self, resto: str) -> str:
        return self.knowledge.consultar_rag(resto)

    def _comando_ingerir(self, resto: str) -> str:
        return self.knowledge.ingerir(resto)

    def _comando_fontes(self, resto: str) -> str:
        return self.knowledge.listar_fontes(resto)

    def _comando_lembrar(self, resto: str) -> str:
        partes = [p.strip() for p in resto.split("|")]
        if len(partes) != 3:
            return "Use assim: `/lembrar tipo | chave | valor`."
        resultado = self.db.salvar_memoria_avancada(
            partes[0], partes[1], partes[2], origem="manual", confianca=0.95
        )
        self.db.registrar_evento_aprendizado(
            "memoria_manual",
            f"{partes[0]}:{partes[1]} = {partes[2]}",
            metadata=(
                f"memoria_id={resultado.memory_id};acao={resultado.action};"
                f"conflito_id={resultado.conflict_id or 0}"
            ),
        )
        return self._resposta_salvamento_memoria(resultado, partes[2], partes[0], partes[1])

    def _comando_aprendizados(self, resto: str) -> str:
        return self.curation.listar_aprendizados(resto)

    def _comando_curadoria(self, resto: str) -> str:
        return self.curation.listar_curadoria(resto)

    def _comando_higiene(self, resto: str) -> str:
        return self.curation.higiene_memoria(resto)

    def _comando_confirmar_memoria(self, resto: str) -> str:
        return self.curation.confirmar_memoria(resto)

    def _comando_esquecer_memoria(self, resto: str) -> str:
        return self.curation.esquecer_memoria(resto)

    def _comando_aprovar_aprendizado(self, resto: str) -> str:
        return self.curation.aprovar_aprendizado(resto)

    def _comando_rejeitar_aprendizado(self, resto: str) -> str:
        return self.curation.rejeitar_aprendizado(resto)

    def _comando_exercicio(self, resto: str) -> str:
        return self.exercise_coach.criar_exercicio(resto)

    def _comando_responder_exercicio(self, resto: str) -> str:
        return self.exercise_coach.responder_exercicio(resto)

    def _comando_revisoes(self) -> str:
        return self.exercise_coach.listar_revisoes()

    def _comando_alertas(self) -> str:
        return formatar_alertas(self.alert_service.collect())

    def _comando_codigo(
        self,
        resto: str,
        channel: AccessChannel = AccessChannel.LOCAL_TERMINAL,
    ) -> str:
        if not resto:
            return "Cole o código ou descreva o erro depois de `/codigo`."
        rag_context = ""
        if self.permissions.allows(channel, Capability.RAG_READ):
            rag_context = self.rag.formatar_contexto(resto, limite=4)
        prompt = self.code_assistant.build_prompt(resto, rag_context)
        return self._responder_com_ia(prompt, channel)

    def _comando_revisar_arquivo(
        self,
        resto: str,
        channel: AccessChannel = AccessChannel.LOCAL_TERMINAL,
    ) -> str:
        if not resto:
            return "Use assim: `/revisar aya/core/assistant.py`."
        revisao = self.project_tools.preparar_revisao_arquivo(resto)
        if isinstance(revisao, str):
            return revisao
        prompt = (
            "Revise este arquivo como um engenheiro senior. "
            "Priorize bugs reais, riscos de manutencao, seguranca, testes faltantes e clareza. "
            "Nao proponha reescrever tudo sem necessidade e nao diga que editou o arquivo.\n\n"
            f"{revisao.summary}\n\n"
            f"Conteudo do arquivo {revisao.path}:\n"
            "```text\n"
            f"{revisao.content}\n"
            "```"
        )
        return self._responder_com_ia(prompt, channel)

    def _comando_revisar(
        self,
        resto: str,
        channel: AccessChannel = AccessChannel.LOCAL_TERMINAL,
    ) -> str:
        if resto.strip().lower().startswith("memoria"):
            return self.curation.revisar_memoria(resto)
        return self._comando_revisar_arquivo(resto, channel)

    def _comando_plano_alteracao(
        self,
        resto: str,
        channel: AccessChannel = AccessChannel.LOCAL_TERMINAL,
    ) -> str:
        if not resto:
            return "Use assim: `/plano aya/core/assistant.py | objetivo da mudanca`."
        caminho, separador, objetivo = resto.partition("|")
        caminho = caminho.strip()
        objetivo = objetivo.strip() if separador else ""
        if not caminho:
            return "Informe o arquivo depois de `/plano`."
        revisao = self.project_tools.preparar_revisao_arquivo(caminho)
        if isinstance(revisao, str):
            return revisao
        prompt = self.change_plan.build_prompt(revisao, objetivo)
        return self._responder_com_ia(prompt, channel)

    @staticmethod
    def _resposta_salvamento_memoria(resultado, valor: str, tipo: str = "", chave: str = "") -> str:
        if resultado.action == "conflict":
            return (
                f"Nao substitui a memoria #{resultado.memory_id}: o novo valor entra em conflito "
                f"com o atual. Criei o conflito #{resultado.conflict_id} para sua decisao. "
                f"Use `/resolver conflito {resultado.conflict_id} aceitar` para trocar ou "
                f"`/resolver conflito {resultado.conflict_id} rejeitar` para manter."
            )
        detalhe = f" [{tipo}] {chave} = {valor}" if tipo and chave else f": {valor}"
        if resultado.action == "reinforced":
            return f"Memoria #{resultado.memory_id} reforcada{detalhe}"
        return f"Memória salva com ID {resultado.memory_id}{detalhe}"

    def _authorize(self, channel: AccessChannel, capability: Capability) -> str | None:
        if self.permissions.allows(channel, capability):
            return None
        return self.permissions.denial_message(channel, capability)

    @staticmethod
    def _command_capability(name: str, payload: str) -> Capability:
        mapping = {
            "/ajuda": Capability.CHAT,
            "/help": Capability.CHAT,
            "/salvar": Capability.KNOWLEDGE_WRITE,
            "/buscar": Capability.KNOWLEDGE_READ,
            "/estudar": Capability.STUDY,
            "/encerrar": Capability.STUDY,
            "/meta": Capability.STUDY,
            "/metas": Capability.STUDY,
            "/dificuldade": Capability.STUDY,
            "/painel": Capability.STATUS,
            "/status": Capability.STATUS,
            "/roadmap": Capability.STATUS,
            "/release": Capability.SYSTEM_DIAGNOSTICS,
            "/perfil": Capability.MEMORY_WRITE if "|" in payload else Capability.MEMORY_READ,
            "/codigo": Capability.CHAT,
            "/finetune": Capability.DATA_EXPORT,
            "/diagnostico": Capability.SYSTEM_DIAGNOSTICS,
            "/modelos": Capability.SYSTEM_DIAGNOSTICS,
            "/backup": Capability.BACKUP_MANAGE,
            "/memoria": Capability.MEMORY_READ,
            "/memorias": Capability.MEMORY_READ,
            "/rag": Capability.RAG_READ,
            "/ragstatus": Capability.RAG_READ,
            "/reindexar": Capability.FILE_INGEST,
            "/ingerir": Capability.FILE_INGEST,
            "/fontes": Capability.KNOWLEDGE_READ,
            "/lembrar": Capability.MEMORY_WRITE,
            "/refletir": Capability.SYSTEM_ADMIN,
            "/autonomia": Capability.SYSTEM_ADMIN,
            "/privacidade": Capability.SYSTEM_ADMIN,
            "/aprendizados": Capability.MEMORY_READ,
            "/aprovar": Capability.MEMORY_CURATE,
            "/rejeitar": Capability.MEMORY_CURATE,
            "/curadoria": Capability.MEMORY_READ,
            "/higiene": Capability.MEMORY_READ,
            "/conflitos": Capability.MEMORY_READ,
            "/resolver": Capability.MEMORY_CURATE,
            "/fundir": Capability.MEMORY_CURATE,
            "/historico": Capability.MEMORY_READ,
            "/confirmar": Capability.MEMORY_CURATE,
            "/esquecer": Capability.MEMORY_CURATE,
            "/arquivar": Capability.MEMORY_CURATE,
            "/restaurar": Capability.MEMORY_CURATE,
            "/editar": Capability.MEMORY_CURATE,
            "/dominio": Capability.MEMORY_CURATE,
            "/adiar": Capability.MEMORY_CURATE,
            "/ignorar": Capability.MEMORY_CURATE,
            "/retomar": Capability.MEMORY_CURATE,
            "/exercicio": Capability.STUDY,
            "/responder": Capability.STUDY,
            "/revisoes": Capability.STUDY,
            "/companhia": Capability.COMPANION,
            "/desabafo": Capability.COMPANION,
            "/conselho": Capability.SYSTEM_DIAGNOSTICS,
            "/incentivo": Capability.COMPANION,
            "/diario": Capability.MEMORY_READ,
            "/continuidade": Capability.STATUS,
            "/resumo": Capability.STATUS,
            "/ondeparamos": Capability.STATUS,
            "/projeto": Capability.PROJECT_ACCESS,
            "/auditar": Capability.PROJECT_ACCESS,
            "/arquivo": Capability.PROJECT_ACCESS,
            "/revisar": Capability.MEMORY_READ if payload.strip().lower().startswith("memoria") else Capability.PROJECT_ACCESS,
            "/plano": Capability.PROJECT_ACCESS,
            "/alertas": Capability.MEMORY_READ,
            "/aya-dev": Capability.SYSTEM_ADMIN,
        }
        return mapping.get(name, Capability.SYSTEM_ADMIN)

    @staticmethod
    def _intent_capability(intent: Intent) -> Capability:
        mapping = {
            "painel": Capability.STATUS,
            "status": Capability.STATUS,
            "roadmap": Capability.STATUS,
            "release": Capability.SYSTEM_DIAGNOSTICS,
            "continuidade": Capability.STATUS,
            "diagnostico": Capability.SYSTEM_DIAGNOSTICS,
            "modelos": Capability.SYSTEM_DIAGNOSTICS,
            "backup": Capability.BACKUP_MANAGE,
            "autonomia": Capability.SYSTEM_ADMIN,
            "privacidade": Capability.SYSTEM_ADMIN,
            "projeto": Capability.PROJECT_ACCESS,
            "auditar_projeto": Capability.PROJECT_ACCESS,
            "arquivo": Capability.PROJECT_ACCESS,
            "revisar_arquivo": Capability.PROJECT_ACCESS,
            "plano_alteracao": Capability.PROJECT_ACCESS,
            "codigo": Capability.CHAT,
            "refletir": Capability.SYSTEM_ADMIN,
            "aprendizados": Capability.MEMORY_READ,
            "higiene": Capability.MEMORY_READ,
            "confirmar_rascunho": Capability.MEMORY_CURATE,
            "rejeitar_rascunho": Capability.MEMORY_CURATE,
            "aprovar_aprendizado": Capability.MEMORY_CURATE,
            "rejeitar_aprendizado": Capability.MEMORY_CURATE,
            "exercicio": Capability.STUDY,
            "responder_exercicio": Capability.STUDY,
            "revisoes": Capability.STUDY,
            "companhia": Capability.COMPANION,
            "iniciar_sessao": Capability.STUDY,
            "encerrar_sessao": Capability.STUDY,
            "metas": Capability.STUDY,
            "meta": Capability.STUDY,
            "dificuldade": Capability.STUDY,
            "memoria": Capability.MEMORY_READ,
            "lembrar": Capability.MEMORY_WRITE,
            "salvar_conhecimento": Capability.KNOWLEDGE_WRITE,
            "ingerir": Capability.FILE_INGEST,
            "fontes": Capability.KNOWLEDGE_READ,
            "rag": Capability.RAG_READ,
            "buscar": Capability.KNOWLEDGE_READ,
        }
        return mapping.get(intent.name, Capability.SYSTEM_ADMIN)

    def _comando_arquivo(self, resto: str) -> str:
        if not resto:
            return "Use assim: `/arquivo core/assistant.py`."
        return self.project_tools.ler_arquivo(resto)

    def _migrar_historico_json(self):
        if not self.HISTORICO_JSON.exists() or self.db.contar_mensagens_totais() > 0:
            return
        try:
            with self.HISTORICO_JSON.open("r", encoding="utf-8") as f:
                mensagens = json.load(f)
        except (OSError, json.JSONDecodeError):
            logger.exception("Nao foi possivel migrar historico JSON")
            return

        for msg in mensagens:
            role = msg.get("role")
            content = msg.get("content")
            if role in {"user", "assistant"} and content:
                self.db.salvar_mensagem(role, content)

