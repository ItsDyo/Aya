from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from aya.config import MODEL_CONFIG
from aya.core.dev_index import TechnicalFile, TechnicalIndex
from aya.core.dev_workspace import CheckResult, DevWorkspace
from aya.core.llm import ChatClient
from aya.core.project_tools import ProjectTools
from aya.core.structured_patch import PATCH_DECISION_SCHEMA, StructuredPatchApplier, StructuredPatchError


PROPOSAL_STATES = {
    "DETECTADA", "PROPOSTA", "PLANEJADA", "PREPARANDO", "EM_TESTE",
    "AGUARDANDO_APROVACAO", "APROVADA", "REJEITADA", "FALHOU",
    "PREPARANDO_COMMIT", "COMMIT_PRONTO", "VALIDANDO_INTEGRACAO",
    "INTEGRANDO", "INTEGRADA", "INTEGRACAO_BLOQUEADA",
    "REVERSAO_SOLICITADA", "GERANDO_PREVISAO_REVERSAO", "PREVISAO_REVERSAO_PRONTA",
    "PREVISAO_REVERSAO_BLOQUEADA", "VALIDANDO_REVERSAO", "AGUARDANDO_APROVACAO_REVERSAO",
    "REVERSAO_APROVADA", "REVERTENDO", "REVERTIDA", "REVERSAO_BLOQUEADA",
    "REVERSAO_FALHOU", "REVERSAO_PARCIAL", "APLICADA",
}
RISK_ORDER = {"baixo": 0, "medio": 1, "alto": 2}
HIGH_RISK_TERMS = {
    ".env", "credencial", "autenticacao", "tailscale", "remoto", "banco", "database", "sqlite", "schema",
    "migracao", "memoria", "excluir", "comando", "privacidade", "seguranca", "backup", "rag",
}
ENGINEERING_MEMORY_KINDS = {"decisao", "aprendizado", "risco", "teste", "incidente", "tecnica"}
ENGINEERING_MEMORY_EVENT_STATES = {
    "COMMIT_PRONTO",
    "FALHOU",
    "INTEGRACAO_BLOQUEADA",
    "INTEGRADA",
    "PREVISAO_REVERSAO_BLOQUEADA",
    "REVERSAO_BLOQUEADA",
    "REVERSAO_FALHOU",
    "REVERSAO_PARCIAL",
    "REVERTIDA",
}
AUTONOMY_POLICY_VERSION = 1
AYA_DEV_CAPABILITY_POLICY_VERSION = 1
PATCH_PIPELINE_VERSION = "structured_patch_discriminated_v1"
STRUCTURED_PATCH_SCHEMA_VERSION = "operation_schema_v1"
PATCH_PROMPT_VERSION = "patch_prompt_v1"
CANDIDATE_ANALYZER_VERSION = AUTONOMY_ANALYZER_VERSION = "aya-dev-candidate-analyzer-v5"
RISK_POLICY_VERSION = "risk_policy_v1"
AUTONOMY_QUALIFICATION_VERSION = 1
AUTONOMY_CANDIDATE_SCHEMA_VERSION = 2
AUTONOMY_MODES = {"DESLIGADA", "OBSERVAR", "PREPARAR_SUPERVISIONADO"}
AUTONOMY_MIN_CASES = 3
AUTONOMY_MIN_SUCCESSES = 2
AUTONOMY_MIN_DOCSTRING_LINES = 4
AUTONOMY_ALLOWED_OPERATIONS = {"insert_docstring", "replace_exact"}
CALIBRATION_ALLOWED_RESPONSIBILITIES = {"PURE_FORMATTING", "PURE_UTILITY", "READ_ONLY_QUERY", "DOCUMENTATION_ONLY"}
CALIBRATION_BLOCKED_FILES = {
    "main.py",
    "app.py",
    "aya/core/dev_index.py",
    "aya/core/aya_dev.py",
    "aya/core/assistant.py",
    "aya/core/permissions.py",
    "aya/core/llm.py",
    "aya/core/dev_workspace.py",
    "aya/core/structured_patch.py",
    "aya/core/release.py",
    "aya/core/backup.py",
    "aya/core/rag.py",
}
AUTONOMY_BLOCKED_TERMS = {
    ".env", "credencial", "autenticacao", "permissao", "seguranca", "security", "tailscale", "remoto",
    "banco", "database", "aya/data", "sqlite", "schema", "migracao", "memoria", "rag", "backup", "voz", "subprocess",
    "git", "release", "dependencia",
}
AUTONOMY_REASON_EXPLANATIONS = {
    "PUBLIC_NONTRIVIAL_SYMBOL": "Simbolo publico com corpo nao trivial.",
    "PUBLIC_SYMBOL": "Simbolo publico detectado no HEAD atual.",
    "EXTERNALLY_REFERENCED": "Simbolo referenciado por outro modulo local.",
    "HAS_RELATED_TESTS": "Existem testes relacionados ao arquivo.",
    "MULTI_BRANCH_BODY": "Corpo possui multiplos caminhos de execucao.",
    "PARAMETERS_NONTRIVIAL": "Assinatura possui parametros relevantes.",
    "RETURNS_VALUE": "Funcao ou metodo retorna valor explicitamente.",
    "RAISES_EXCEPTION": "Corpo pode levantar excecao explicitamente.",
    "CENTRAL_MODULE": "Arquivo pertence a modulo central da Aya.",
    "TECHNICAL_RESPONSIBILITY": "Nome ou arquivo indica responsabilidade tecnica sensivel.",
    "LOW_TECHNICAL_VALUE": "Valor tecnico insuficiente para acao recomendada.",
    "TRIVIAL_BODY": "Corpo pequeno ou simples demais para acao operacional.",
    "PRIVATE_SYMBOL": "Simbolo privado ou protegido.",
    "DUNDER_SYMBOL": "Metodo especial dunder.",
    "INIT_TRIVIAL": "__init__ trivial nao e candidato operacional.",
    "GETTER_SETTER_TRIVIAL": "Getter, setter ou propriedade trivial.",
    "NESTED_SYMBOL": "Funcao aninhada nao entra na fila operacional.",
    "TEST_FILE": "Arquivo de teste nao entra na fila operacional.",
    "DOCSTRING_EXISTS": "Docstring ja existe.",
    "RUFF_F401_CONFIRMED": "Ruff confirmou import nao utilizado F401.",
    "RUFF_F401_UNAVAILABLE": "Diagnostico Ruff F401 indisponivel.",
    "POSSIBLE_REEXPORT": "Possivel reexportacao publica.",
    "TYPE_CHECKING_IMPORT": "Import protegido por TYPE_CHECKING.",
    "SIDE_EFFECT_IMPORT": "Import pode ter efeito colateral.",
    "NOQA_IMPORT": "Linha possui noqa.",
    "DUPLICATE_ACTIVE_PROPOSAL": "Existe proposta ativa equivalente.",
    "DUPLICATE_CURRENT_CANDIDATE": "Existe candidato equivalente na mesma renovacao.",
    "CAPABILITY_INSUFFICIENT": "Capacidade historica insuficiente.",
    "HISTORICAL_FAILURES": "Historico possui falhas para esta operacao.",
    "HIGH_RISK_MODULE": "Modulo classificado como risco medio ou alto.",
    "FILE_BLOCKED": "Arquivo protegido pela politica.",
    "STALE_HEAD": "HEAD mudou desde a deteccao.",
    "STALE_FILE_HASH": "Hash do arquivo mudou.",
    "STALE_FILE_REMOVED": "Arquivo nao existe mais.",
    "STALE_RELATED_TEST": "Teste relacionado nao existe mais.",
    "LEGACY_PIPELINE_FAILURE": "Falha pertence a pipeline antigo ou desconhecido.",
    "CURRENT_PIPELINE_FAILURE": "Falha pertence ao pipeline atual.",
    "CALIBRATION_REQUIRED": "Amostra atual ainda exige calibracao supervisionada.",
    "CALIBRATION_ALLOWED": "Candidato pode ser usado em experimento supervisionado.",
    "ABSOLUTE_POLICY_BLOCK": "Bloqueio absoluto de politica de seguranca.",
    "CURRENT_VERSION_SAMPLE_SMALL": "Amostra da versao atual e pequena.",
    "CURRENT_VERSION_SUCCESS": "Ha sucesso registrado na versao atual.",
    "CURRENT_VERSION_REGRESSION": "Ha regressao ou falha critica na versao atual.",
    "CANDIDATE_NOT_ACTION_RECOMMENDED": "Candidato nao e acao recomendada.",
    "CANDIDATE_TOO_LARGE": "Candidato excede limite do experimento.",
    "CANDIDATE_STALE": "Candidato esta obsoleto.",
    "HUMAN_CONFIRMATION_REQUIRED": "Execucao exige confirmacao textual humana.",
    "CENTRAL_APPLICATION_FILE": "Arquivo central bloqueado para a primeira calibracao real.",
    "AUTHENTICATION_SYMBOL": "Simbolo participa de autenticacao.",
    "AUTHORIZATION_SYMBOL": "Simbolo participa de autorizacao ou permissoes.",
    "REMOTE_ACCESS_SYMBOL": "Simbolo participa de acesso remoto ou rede.",
    "SERVER_LAUNCH_CONFIGURATION": "Simbolo configura inicializacao ou exposicao do servidor.",
    "TECHNICAL_MEMORY_PERSISTENCE": "Simbolo participa de memoria tecnica ou persistencia.",
    "PERSONAL_MEMORY_PERSISTENCE": "Simbolo participa de memoria pessoal.",
    "AUTONOMY_CONTROL_PLANE": "Simbolo participa do plano de controle da autonomia.",
    "GIT_CONTROL_PLANE": "Simbolo controla Git, worktree, commit, integracao ou reversao.",
    "PATCH_PIPELINE_CONTROL": "Simbolo participa do pipeline de patch estruturado.",
    "RELEASE_CONTROL_PLANE": "Simbolo participa de validacao ou release.",
    "COMMAND_EXECUTION_PATH": "Simbolo pode executar comandos, shell ou subprocessos.",
    "UNKNOWN_SIDE_EFFECTS": "Efeitos colaterais nao puderam ser classificados com seguranca.",
    "SAFE_PURE_UTILITY": "Simbolo parece utilitario puro e de baixo risco.",
    "SAFE_READ_ONLY_QUERY": "Simbolo parece consulta somente leitura.",
    "SAFE_DOCUMENTATION_TARGET": "Alvo seguro para documentacao.",
    "CALIBRATION_MODULE_BLOCKED": "Modulo bloqueado para a primeira geracao de calibracao real.",
}


@dataclass
class EngineeringProposal:
    id: str
    title: str
    problem: str
    evidence: list[str]
    related_files: list[str]
    related_symbols: list[str]
    probable_cause: str
    suggested_change: str
    preserve: list[str]
    impact: str
    urgency: str
    risk: str
    difficulty: str
    required_tests: list[str]
    done_criteria: list[str]
    rollback_plan: str
    state: str
    created_at: str
    model: str
    review_result: str = ""
    workspace: str = ""
    patch: str = ""
    attempts: int = 0
    validation: list[dict] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    failure_stage: str = ""
    failure_reason: str = ""
    failure_message: str = ""
    failure_at: str = ""
    workspace_created: bool = False
    workspace_path: str = ""
    workspace_cleaned: bool = False
    cleanup_result: str = ""
    raw_response_saved: bool = False
    raw_response: str = ""
    diff_created: bool = False
    diff_preserved: bool = False
    tests_executed: bool = False
    project_unchanged: bool = True
    base_commit: str = ""
    patch_manifest: dict = field(default_factory=dict)
    approved_at: str = ""
    approved_by: str = ""
    approved_diff_sha256: str = ""
    approved_manifest_sha256: str = ""
    approved_base_commit: str = ""
    approved_validation_sha256: str = ""
    approved_review_sha256: str = ""
    approval_valid: bool = False
    approval_invalid_reason: str = ""
    proposal_branch: str = ""
    proposal_commit: str = ""
    commit_parent: str = ""
    committed_at: str = ""
    committed_files: list[str] = field(default_factory=list)
    committed_diff_sha256: str = ""
    commit_message: str = ""
    main_head_at_commit: str = ""
    main_unchanged: bool = False
    ready_for_integration: bool = False
    integration_started_at: str = ""
    integrated_at: str = ""
    integration_method: str = ""
    integrated_commit: str = ""
    previous_main_head: str = ""
    resulting_main_head: str = ""
    main_branch: str = ""
    integration_validation: list[dict] = field(default_factory=list)
    post_integration_validation: list[dict] = field(default_factory=list)
    merge_commit_created: bool = False
    pushed: bool = False
    remote_used: bool = False
    worktree_cleanup_pending: bool = False
    integration_success: bool = False
    integration_block_reason: str = ""
    integration_partial: bool = False
    integration_cleanup_result: str = ""
    reversal_requested_at: str = ""
    reversal_reason: str = ""
    reversal_requested_by: str = ""
    reversal_approved_at: str = ""
    reversal_approved_by: str = ""
    reversal_approval_valid: bool = False
    reversal_approval_invalid_reason: str = ""
    reversal_target_commit: str = ""
    reversal_base_commit: str = ""
    reversal_main_before: str = ""
    reversal_commit: str = ""
    reversal_main_after: str = ""
    reversal_validation: list[dict] = field(default_factory=list)
    reversal_post_validation: list[dict] = field(default_factory=list)
    reversal_validation_sha256: str = ""
    reversal_review_sha256: str = ""
    reversal_manifest_sha256: str = ""
    reversal_approved_validation_sha256: str = ""
    reversal_approved_review_sha256: str = ""
    reversal_approved_manifest_sha256: str = ""
    reversal_approved_base_commit: str = ""
    reversal_started_at: str = ""
    reversal_completed_at: str = ""
    reversal_error: str = ""
    reversal_partial: bool = False
    reversal_preview_created_at: str = ""
    reversal_preview_base_head: str = ""
    reversal_preview_target_commit: str = ""
    reversal_preview_diff: str = ""
    reversal_preview_diff_sha256: str = ""
    reversal_preview_files: list[str] = field(default_factory=list)
    reversal_preview_added_lines: int = 0
    reversal_preview_removed_lines: int = 0
    reversal_preview_validation: list[dict] = field(default_factory=list)
    reversal_preview_validation_sha256: str = ""
    reversal_preview_conflicts: str = ""
    reversal_preview_clean: bool = False
    reversal_preview_workspace_cleaned: bool = False
    reversal_preview_main_unchanged: bool = False
    reversal_preview_valid: bool = False
    reversal_preview_invalidated_reason: str = ""
    reversal_preview_sha256: str = ""
    approved_reversal_preview_sha256: str = ""
    patch_pipeline_version: str = "legacy_unknown"
    schema_version: str = "legacy_unknown"
    prompt_version: str = "legacy_unknown"
    analyzer_version: str = "legacy_unknown"
    risk_policy_version: str = "legacy_unknown"
    project_head: str = ""
    approved_reversal_base_head: str = ""
    approved_reversal_target_commit: str = ""
    approved_reversal_validation_sha256: str = ""


@dataclass
class CalibrationExperiment:
    experiment_id: str
    candidate_id: str
    proposal_id: str
    created_at: str
    selected_by: str
    project_head: str
    file: str
    file_sha256: str
    symbol: str
    operation_type: str
    category: str
    pipeline_version: str
    schema_version: str
    prompt_version: str
    model: str
    reviewer_model: str
    reason: str
    expected_change: str
    allowed_files: list[str]
    related_tests: list[str]
    risk: str
    estimated_changed_lines: int
    state: str
    attempt: int = 0
    manifest_result: str = ""
    patch_result: str = ""
    validation_result: str = ""
    review_result: str = ""
    human_decision: str = ""
    evidence_strength: str = ""
    result: str = ""
    record_sha256: str = ""


@dataclass(frozen=True)
class SemanticSafety:
    responsibility: str
    sensitivity: str
    relevant_calls: list[str]
    reason_codes: list[str]
    block_reasons: list[str]


@dataclass
class EngineeringMemoryEntry:
    id: str
    kind: str
    title: str
    content: str
    source: str
    created_at: str


@dataclass
class AutonomousCandidate:
    candidate_id: str
    detected_at: str
    generated_at: str
    project_head: str
    source: str
    source_origin: str
    title: str
    problem: str
    evidence: list[str]
    category: str
    operation_type: str
    file: str
    file_sha256: str
    symbol: str
    symbol_signature: str
    reason: str
    expected_change: str
    allowed_files: list[str]
    files: list[str]
    symbols: list[str]
    estimated_changed_lines: int
    risk: str
    required_tests: list[str]
    confidence: str
    detection_valid: bool
    relevance_valid: bool
    actionable: bool
    qualification_status: str
    qualification_reasons: list[str]
    documentation_value_score: int
    documentation_value_reasons: list[str]
    priority_score: int
    priority_reasons: list[str]
    reason_codes: list[str]
    ruff_diagnostic: dict
    status: str
    eligibility: str
    blocked_reasons: list[str]
    related_lessons: list[str]
    similar_proposals: list[str]
    policy_version: int
    score: int
    score_explanation: list[str]
    deduplication_key: str
    stale: bool
    stale_reason: str
    route: str
    record_sha256: str


class AyaDevService:
    """Modo de engenharia local supervisionado e sem aplicacao no projeto principal."""

    def __init__(
        self,
        root: str | Path,
        llm: ChatClient,
        project_tools: ProjectTools,
        primary_model: str = MODEL_CONFIG.primary,
        reviewer_model: str = MODEL_CONFIG.reviewer,
        storage_path: str | Path | None = None,
        index_path: str | Path | None = None,
        engineering_memory_path: str | Path | None = None,
        workspace_root: str | Path | None = None,
        max_files: int = 4,
        max_changed_lines: int = 250,
        max_attempts: int = 2,
    ):
        self.root = Path(root).resolve()
        data_dir = self.root / "data_local"
        self.storage_path = Path(storage_path or data_dir / "aya_dev_history.json")
        memory_dir = self.storage_path.parent if storage_path is not None else data_dir
        self.engineering_memory_path = Path(engineering_memory_path or memory_dir / "aya_dev_engineering_memory.jsonl")
        self.autonomy_path = memory_dir / "aya_dev_autonomy.json"
        self.candidate_cache_path = memory_dir / "aya_dev_candidate_cache.json"
        self.calibration_path = memory_dir / "aya_dev_calibration_experiments.json"
        self.index = TechnicalIndex(self.root, index_path or data_dir / "aya_dev_index.json")
        self.workspace = DevWorkspace(self.root, workspace_root)
        self.structured_patch = StructuredPatchApplier(
            self.root,
            self.workspace,
            max_files=max_files,
            max_changed_lines=max_changed_lines,
        )
        self.llm = llm
        self.project_tools = project_tools
        self.primary_model = primary_model
        self.reviewer_model = reviewer_model
        self.max_files = max_files
        self.max_changed_lines = max_changed_lines
        self.max_attempts = max_attempts
        self.proposals = self._load()
        self.experiments = self._load_experiments()
        self._experiment_locks: set[str] = set()
        self._candidate_cache: list[AutonomousCandidate] | None = None
        self._candidate_cache_head = ""
        self._candidate_cache_proposals = -1
        self._candidate_scan_report = self._empty_candidate_scan_report()
        self._candidate_exclusion_counts: dict[str, int] = {}

    def execute(self, payload: str) -> str:
        action, _, argument = (payload or "status").strip().partition(" ")
        action = action.lower() or "status"
        handlers = {
            "status": self.status,
            "mapear": self.map_project,
            "auditar": self.audit,
            "propostas": self.list_proposals,
            "historico": self.history,
            "metricas": self.metrics,
            "metrics": self.metrics,
            "eventos-tecnicos": self.engineering_events,
            "memoria-tecnica": self.engineering_memory,
            "memoria-tecnica-listar": self.engineering_memory,
            "memoria": self.engineering_memory,
            "autonomia-status": self.autonomy_status,
            "avaliar-autonomia": self.evaluate_autonomy,
            "fila-autonoma": self.autonomous_queue,
            "observar-ciclo": self.observe_cycle,
            "renovar-candidatos": self.renew_candidates,
            "experimentos": self.list_experiments,
            "resultados-experimentos": self.experiment_results,
            "candidatos-calibracao": self.calibration_candidates,
        }
        if action in handlers:
            return handlers[action]()
        if action == "candidatos":
            return self.list_candidates(argument.strip())
        if action in {"capacidade", "confiabilidade"}:
            return self.capability_report(argument.strip())
        if action == "candidato":
            return self.show_candidate(argument.strip())
        if action == "rota":
            return self.route_candidate(argument.strip())
        if action == "explicar-rota":
            return self.explain_route(argument.strip())
        if action == "experimento-candidato":
            return self.create_calibration_experiment(argument.strip())
        if action == "experimento":
            return self.show_experiment(argument.strip())
        if action == "executar-experimento":
            return self.execute_calibration_experiment(argument.strip())
        if action == "cancelar-experimento":
            return self.cancel_calibration_experiment(argument.strip())
        if action == "explicar-calibracao":
            return self.explain_calibration_candidate(argument.strip())
        if action == "autonomia":
            return self.set_autonomy_mode(argument.strip())
        if action == "selecionar-candidato":
            return self.select_candidate(argument.strip())
        if action == "executar-candidato":
            return self.execute_candidate(argument.strip())
        if action == "executar-ciclo-seguro":
            return self.execute_safe_autonomous_cycle()
        if action == "explicar-selecao":
            return self.explain_candidate(argument.strip())
        if action == "cancelar-candidato":
            return self.cancel_candidate(argument.strip())
        if action == "registrar-memoria":
            return self.register_engineering_memory(argument.strip())
        if action in {
            "mostrar", "falha", "commit", "integracao", "planejar", "preparar", "revisar", "testar", "diff",
            "aprovar", "rejeitar", "descartar", "aplicar", "integrar", "solicitar-reversao",
            "prever-reversao", "reversao", "diff-reversao", "aprovar-reversao", "reverter", "pacote-codex",
        }:
            if not argument.strip():
                return f"Informe o ID: /aya-dev {action} id"
            return getattr(self, action.replace("-", "_"))(argument.strip())
        return "Subcomando Aya Dev desconhecido. Use /aya-dev status."

    def status(self) -> str:
        git = self.workspace.git_state()
        counts: dict[str, int] = {}
        for proposal in self.proposals.values():
            counts[proposal.state] = counts.get(proposal.state, 0) + 1
        states = ", ".join(f"{name}={total}" for name, total in sorted(counts.items())) or "nenhuma"
        return "\n".join([
            "Aya Dev - engenharia local supervisionada:",
            f"- Git: {git.message}",
            f"- Preparacao de patches: {'liberada' if git.safe else 'BLOQUEADA'}",
            f"- Propostas: {len(self.proposals)} ({states})",
            f"- Modelo principal: {self.primary_model}",
            f"- Modelo revisor: {self.reviewer_model}",
            f"- Limites: {self.max_files} arquivos, {self.max_changed_lines} linhas, {self.max_attempts} tentativas",
            "- Observabilidade: /aya-dev metricas, /aya-dev eventos-tecnicos, /aya-dev memoria-tecnica",
            "- Aplicacao no projeto principal: exige comando separado e validacao completa",
        ])

    def map_project(self) -> str:
        return self.index.summary(self.index.build())

    def audit(self) -> str:
        entries = self.index.build()
        diagnostics = self.project_tools.diagnosticar_projeto()
        candidates = sorted((item for item in entries if not item.path.startswith("tests/")), key=lambda item: (-item.lines, item.path))
        if not candidates:
            return diagnostics + "\n\nNenhuma proposta tecnica foi criada: nao ha arquivo Python elegivel."
        target = candidates[0]
        title = f"Reduzir responsabilidade de {target.path}"
        problem = f"O arquivo {target.path} possui {target.lines} linhas e concentra muitos simbolos."
        existing = next((item for item in self.proposals.values() if item.title == title and item.state not in {"REJEITADA", "FALHOU"}), None)
        if existing:
            return diagnostics + f"\n\nProposta existente: {existing.id} ({existing.state})."
        proposal = self.create_proposal(
            title=title,
            problem=problem,
            evidence=[f"Indice AST: {target.path} possui {target.lines} linhas.", *target.markers[:3]],
            related_files=[target.path, *target.related_tests[:2]],
            related_symbols=(target.classes + target.functions + target.methods)[:12],
            probable_cause="Responsabilidades acumuladas ao longo da evolucao do projeto.",
            suggested_change="Caracterizar o comportamento e extrair uma responsabilidade pequena.",
            preserve=["comandos existentes", "dados persistentes", "restricoes de seguranca"],
            impact="medio",
            urgency="media",
            difficulty="media",
            required_tests=target.related_tests or ["python -m pytest"],
            done_criteria=["suite completa aprovada", "diff dentro dos limites", "revisao local registrada"],
        )
        return diagnostics + f"\n\nProposta criada com evidencias reais: {proposal.id}."

    def create_proposal(self, **values) -> EngineeringProposal:
        files = list(dict.fromkeys(values["related_files"]))
        indexed = {item.path for item in self.index.build()}
        invented = [path for path in files if path not in indexed]
        if invented:
            raise ValueError(f"Arquivo nao confirmado pelo indice: {invented[0]}")
        proposal_id = f"DEV-{datetime.now():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"
        risk = self.classify_risk(values["problem"], files, values.get("suggested_change", ""))
        proposal = EngineeringProposal(
            id=proposal_id,
            title=values["title"],
            problem=values["problem"],
            evidence=values["evidence"],
            related_files=files,
            related_symbols=values["related_symbols"],
            probable_cause=values["probable_cause"],
            suggested_change=values["suggested_change"],
            preserve=values["preserve"],
            impact=values["impact"],
            urgency=values["urgency"],
            risk=risk,
            difficulty=values["difficulty"],
            required_tests=values["required_tests"],
            done_criteria=values["done_criteria"],
            rollback_plan="Descartar o worktree; nenhuma alteracao e aplicada ao projeto principal.",
            state="PROPOSTA",
            created_at=datetime.now().isoformat(timespec="seconds"),
            model=self.primary_model,
            patch_pipeline_version=PATCH_PIPELINE_VERSION,
            schema_version=STRUCTURED_PATCH_SCHEMA_VERSION,
            prompt_version=PATCH_PROMPT_VERSION,
            analyzer_version=CANDIDATE_ANALYZER_VERSION,
            risk_policy_version=RISK_POLICY_VERSION,
            project_head=self._safe_head(),
        )
        self._event(proposal, "proposta criada", "DETECTADA", "PROPOSTA")
        self.proposals[proposal.id] = proposal
        self._save()
        return proposal

    def classify_risk(self, problem: str, files: list[str], change: str = "", model_risk: str = "baixo") -> str:
        combined = " ".join([problem, change, *files]).lower()
        deterministic = "baixo"
        if any(term in combined for term in HIGH_RISK_TERMS) or len(files) > self.max_files:
            deterministic = "alto"
        elif len(files) > 2 or "assistant.py" in combined:
            deterministic = "medio"
        model_risk = model_risk if model_risk in RISK_ORDER else "baixo"
        return max((deterministic, model_risk), key=RISK_ORDER.get)

    def list_proposals(self) -> str:
        if not self.proposals:
            return "Aya Dev: nenhuma proposta registrada. Use /aya-dev auditar."
        lines = ["Propostas do Aya Dev:"]
        for item in sorted(self.proposals.values(), key=lambda value: value.created_at, reverse=True)[:20]:
            lines.append(f"- {item.id} [{item.state}] risco={item.risk}: {item.title}")
        return "\n".join(lines)

    def mostrar(self, proposal_id: str) -> str:
        proposal = self._get(proposal_id)
        checks = self._validation_summary(proposal)
        lines = [
            f"Proposta {proposal.id}:",
            "",
            "Estado tecnico:",
            f"- Estado: {proposal.state}",
            f"- Risco: {proposal.risk}",
            f"- Tentativas: {proposal.attempts}/{self.max_attempts}",
            "",
            "Proposta original:",
            f"- Titulo: {proposal.title}",
            f"- Problema: {proposal.problem}",
            f"- Evidencias: {' | '.join(proposal.evidence) or 'nenhuma'}",
            f"- Arquivos: {', '.join(proposal.related_files)}",
            f"- Simbolos: {', '.join(proposal.related_symbols) or 'nao identificados'}",
            "",
            "Plano sugerido - ainda nao executado:",
            self._neutralize_success_text(proposal.suggested_change) or "Informacao nao registrada.",
            "",
            "Resultado da preparacao:",
            f"- Diff criado: {'sim' if proposal.diff_created else 'nao'}",
            f"- Workspace: {proposal.workspace or proposal.workspace_path or 'Informacao nao registrada.'}",
            "",
            "Resultado dos testes:",
            checks,
            "",
            "Revisao:",
            proposal.review_result or "Informacao nao registrada.",
            "",
            "Falha:",
            self.falha(proposal.id),
            "",
            "Diff:",
            proposal.patch[:4000] if proposal.patch else "Informacao nao registrada.",
            "",
            "Decisao humana:",
            self._decision_summary(proposal),
            "",
            "Aprovacao:",
            self._approval_summary(proposal),
            "",
            "Commit isolado:",
            self.commit(proposal.id),
            "",
            "Integracao:",
            self.integracao(proposal.id),
            "",
            "Reversao:",
            self.reversao(proposal.id),
        ]
        return "\n".join(lines)

    def falha(self, proposal_id: str) -> str:
        proposal = self._get(proposal_id)
        if not any((proposal.failure_stage, proposal.failure_reason, proposal.failure_message, proposal.failure_at)):
            return f"Falha {proposal.id}: Informacao nao registrada."
        return "\n".join([
            f"Falha {proposal.id}:",
            f"- Etapa: {proposal.failure_stage or 'Informacao nao registrada.'}",
            f"- Motivo: {proposal.failure_reason or 'Informacao nao registrada.'}",
            f"- Mensagem: {proposal.failure_message or 'Informacao nao registrada.'}",
            f"- Quando: {proposal.failure_at or 'Informacao nao registrada.'}",
            f"- Worktree criado: {'sim' if proposal.workspace_created else 'nao'}",
            f"- Worktree: {proposal.workspace_path or 'Informacao nao registrada.'}",
            f"- Worktree limpo: {'sim' if proposal.workspace_cleaned else 'nao'}",
            f"- Resultado da limpeza: {proposal.cleanup_result or 'Informacao nao registrada.'}",
            f"- Resposta bruta salva: {'sim' if proposal.raw_response_saved else 'nao'}",
            f"- Diff criado: {'sim' if proposal.diff_created else 'nao'}",
            f"- Diff preservado: {'sim' if proposal.diff_preserved else 'nao'}",
            f"- Testes executados: {'sim' if proposal.tests_executed else 'nao'}",
            f"- Projeto principal intacto: {'sim' if proposal.project_unchanged else 'nao'}",
        ])

    def planejar(self, proposal_id: str) -> str:
        proposal = self._get(proposal_id)
        context = self._context(proposal, include_content=False)
        try:
            plan = self.llm.chat(
                model=self.primary_model,
                messages=[{"role": "system", "content": "Planeje uma alteracao pequena e local. Nao invente arquivos."}, {"role": "user", "content": context}],
                temperature=0.1,
                max_tokens=700,
            )
        except Exception as exc:
            proposal.state = "FALHOU"
            proposal.review_result = f"Modelo principal indisponivel: {self.workspace.sanitize(str(exc))}"
            self._record_failure(proposal, "planejamento", "modelo indisponivel", proposal.review_result)
            self._event(proposal, "planejamento falhou", "PROPOSTA", "FALHOU")
            self._save()
            return proposal.review_result
        previous = proposal.state
        proposal.suggested_change = self.workspace.sanitize(plan, 4000)
        proposal.state = "PLANEJADA"
        self._event(proposal, "plano local criado", previous, proposal.state)
        self._save()
        return f"Proposta {proposal.id} planejada pelo modelo {self.primary_model}.\n{proposal.suggested_change}"

    def preparar(self, proposal_id: str) -> str:
        proposal = self._get(proposal_id)
        if proposal.risk == "alto":
            return "Preparacao bloqueada: proposta de risco alto deve ser escalonada para revisao humana/Codex."
        if proposal.attempts >= self.max_attempts:
            return f"Limite de {self.max_attempts} tentativas atingido. Gere /aya-dev pacote-codex {proposal.id}."
        git = self.workspace.git_state()
        if not git.safe:
            return f"Preparacao bloqueada: {git.message}"
        if proposal.state not in {"PLANEJADA", "FALHOU"}:
            return "Planeje a proposta antes de preparar o patch."
        previous = proposal.state
        proposal.state = "PREPARANDO"
        proposal.attempts += 1
        self._event(proposal, f"tentativa {proposal.attempts}", previous, proposal.state)
        try:
            proposal.base_commit = git_head = self.workspace.head()
            manifest: dict | None = None
            decision: dict | None = None
            target_file = ""
            if self._use_structured_patch(proposal):
                raw_decision = self._request_patch_decision(proposal, git_head)
                proposal.raw_response = self.workspace.sanitize(
                    json.dumps(raw_decision, ensure_ascii=True) if not isinstance(raw_decision, str) else raw_decision,
                    50000,
                )
                proposal.raw_response_saved = True
                decision = self.structured_patch.parse_decision(raw_decision)
                proposal.raw_response = self.workspace.sanitize(json.dumps(decision, ensure_ascii=True), 50000)
                proposal.raw_response_saved = True
                target_file = self._structured_target_file(proposal)
            worktree = self.workspace.create(proposal.id)
            proposal.workspace = str(worktree)
            proposal.workspace_path = str(worktree)
            proposal.workspace_created = True
            baseline = self.workspace.baseline(worktree, self._related_tests(proposal))
            proposal.validation = [asdict(result) | {"passed": result.passed, "phase": "baseline"} for result in baseline]
            proposal.tests_executed = True
            if not all(result.passed for result in baseline):
                proposal.state = "FALHOU"
                proposal.review_result = "Baseline falhou; nenhum patch foi solicitado ao modelo."
                self._record_failure(proposal, "baseline", "testes baseline reprovaram", proposal.review_result)
                self._cleanup_failed_workspace(proposal)
                self._event(proposal, "baseline reprovado", "PREPARANDO", "FALHOU")
                self._save()
                return proposal.review_result
            if self._use_structured_patch(proposal):
                if decision is None:
                    raise StructuredPatchError("Manifesto estruturado nao foi preparado.")
                manifest = self.structured_patch.build_manifest(
                    decision,
                    proposal.id,
                    git_head,
                    target_file,
                    self._file_sha256(target_file, worktree),
                    self._related_tests(proposal),
                )
                proposal.patch_manifest = manifest
                result = self.structured_patch.apply(
                    worktree,
                    manifest,
                    proposal.id,
                    git_head,
                    proposal.related_files,
                    proposal.related_symbols,
                )
                proposal.diff_created = result.ok
            else:
                response = self.llm.chat(
                    model=self.primary_model,
                    messages=[
                        {"role": "system", "content": self._patch_rules()},
                        {"role": "user", "content": self._context(proposal, include_content=True)},
                    ],
                    temperature=0.0,
                    max_tokens=1800,
                )
                proposal.raw_response = self.workspace.sanitize(response, 50000)
                proposal.raw_response_saved = True
                patch = self._extract_patch(response)
                proposal.diff_created = bool(self.workspace.inspect_patch(patch, self.max_files, self.max_changed_lines, proposal.related_files).diff_created)
                inspection = self.workspace.apply_patch(worktree, patch, self.max_files, self.max_changed_lines, proposal.related_files)
                if not inspection.valid:
                    proposal.state = "FALHOU"
                    proposal.review_result = inspection.message
                    proposal.patch = patch if inspection.diff_created else ""
                    proposal.diff_preserved = bool(proposal.patch)
                    self._record_failure(proposal, "patch", "diff recusado", inspection.message)
                    self._cleanup_failed_workspace(proposal)
                    self._event(proposal, "patch recusado", "PREPARANDO", "FALHOU")
                    self._save()
                    return inspection.message
            proposal.patch = self.workspace.diff(worktree)
            proposal.diff_created = bool(proposal.patch.strip())
            inspection = self.workspace.inspect_patch(proposal.patch, self.max_files, self.max_changed_lines, proposal.related_files)
            if not inspection.valid:
                proposal.state = "FALHOU"
                proposal.review_result = inspection.message
                proposal.diff_preserved = bool(proposal.patch)
                self._record_failure(proposal, "patch", "diff real fora dos limites", inspection.message)
                self._cleanup_failed_workspace(proposal)
                self._event(proposal, "patch recusado", "PREPARANDO", "FALHOU")
                self._save()
                return inspection.message
            diff_check = self.workspace.diff_check(worktree)
            proposal.validation.append(asdict(diff_check) | {"passed": diff_check.passed, "phase": "patch"})
            if not diff_check.passed:
                proposal.state = "FALHOU"
                proposal.review_result = "git diff --check reprovou o diff real."
                self._record_failure(proposal, "patch", "git diff --check reprovou", diff_check.output)
                self._cleanup_failed_workspace(proposal)
                self._event(proposal, "patch recusado", "PREPARANDO", "FALHOU")
                self._save()
                return proposal.review_result
            proposal.state = "EM_TESTE"
            self._event(proposal, "patch preparado somente no worktree", "PREPARANDO", proposal.state)
            self._save()
            return f"Patch preparado no ambiente isolado ({inspection.changed_lines} linhas, {len(inspection.files)} arquivo(s))."
        except StructuredPatchError as exc:
            proposal.state = "FALHOU"
            proposal.review_result = self.workspace.sanitize(str(exc))
            stage = "manifest_generation" if not proposal.workspace else "patch"
            self._record_failure(proposal, stage, "manifesto recusado", proposal.review_result)
            self._cleanup_failed_workspace(proposal)
            self._event(proposal, "manifesto recusado", "PREPARANDO", "FALHOU")
            self._save()
            return f"Preparacao falhou com seguranca: {proposal.review_result}"
        except Exception as exc:
            proposal.state = "FALHOU"
            proposal.review_result = self.workspace.sanitize(str(exc))
            self._record_failure(proposal, "preparacao", "excecao controlada", proposal.review_result)
            self._cleanup_failed_workspace(proposal)
            self._event(proposal, "preparacao falhou", "PREPARANDO", "FALHOU")
            self._save()
            return f"Preparacao falhou com seguranca: {proposal.review_result}"

    def revisar(self, proposal_id: str) -> str:
        proposal = self._get(proposal_id)
        if not proposal.patch:
            return "Nao existe diff preparado para revisar."
        try:
            review = self.llm.chat(
                model=self.reviewer_model,
                messages=[
                    {"role": "system", "content": "Revise criticamente. Nao aplique nem aprove. Aponte escopo, regressao, testes e seguranca."},
                    {"role": "user", "content": self._review_context(proposal)},
                ],
                temperature=0.0,
                max_tokens=900,
            )
        except Exception as exc:
            proposal.review_result = f"Modelo revisor indisponivel: {self.workspace.sanitize(str(exc))}"
            self._save()
            return proposal.review_result
        proposal.review_result = self.workspace.sanitize(review, 5000)
        if any(term in proposal.review_result.lower() for term in ("risco alto", "bloquear", "segredo", "credencial")):
            proposal.risk = self.classify_risk(proposal.problem, proposal.related_files, proposal.suggested_change, "alto")
        self._event(proposal, "revisao independente registrada", proposal.state, proposal.state)
        self._save()
        return f"Revisao por {self.reviewer_model}:\n{proposal.review_result}"

    def testar(self, proposal_id: str) -> str:
        proposal = self._get(proposal_id)
        if not proposal.workspace or not proposal.patch:
            return "Nao existe patch isolado para testar."
        previous = proposal.state
        proposal.state = "EM_TESTE"
        results = self.workspace.validate(proposal.workspace, self._related_tests(proposal))
        proposal.validation.extend(asdict(result) | {"passed": result.passed, "phase": "patch"} for result in results)
        proposal.tests_executed = True
        passed = all(result.passed for result in results)
        proposal.state = "AGUARDANDO_APROVACAO" if passed else "FALHOU"
        if not passed:
            timeout = any(result.exit_code == 124 for result in results)
            proposal.review_result = "Validacao inconclusiva por timeout." if timeout else "Validacao do patch reprovada."
            reason = "VALIDACAO_INCONCLUSIVA_POR_TIMEOUT" if timeout else "validacao reprovada"
            self._record_failure(proposal, "testes", reason, self._format_checks(results, proposal.state))
            self._cleanup_failed_workspace(proposal)
        self._event(proposal, "validacao concluida", previous, proposal.state)
        self._save()
        return self._format_checks(results, proposal.state)

    def diff(self, proposal_id: str) -> str:
        proposal = self._get(proposal_id)
        if not proposal.patch:
            return "Nenhum diff foi preparado para esta proposta."
        return f"Diff somente leitura de {proposal.id}:\n{proposal.patch}"

    def aprovar(self, proposal_id: str) -> str:
        proposal = self._get(proposal_id)
        if proposal.state != "AGUARDANDO_APROVACAO":
            return "Aprovacao recusada: a validacao obrigatoria ainda nao foi aprovada."
        valid, reason = self._approval_snapshot_valid(proposal)
        if not valid:
            proposal.approval_valid = False
            proposal.approval_invalid_reason = reason
            self._save()
            return f"Aprovacao recusada: {reason}"
        previous = proposal.state
        proposal.state = "APROVADA"
        proposal.approved_at = datetime.now().isoformat(timespec="seconds")
        proposal.approved_by = "local_user"
        proposal.approved_diff_sha256 = self._sha_text(proposal.patch)
        proposal.approved_manifest_sha256 = self._sha_json(proposal.patch_manifest)
        proposal.approved_base_commit = proposal.base_commit
        proposal.approved_validation_sha256 = self._sha_json(proposal.validation)
        proposal.approved_review_sha256 = self._sha_text(proposal.review_result)
        proposal.approval_valid = True
        proposal.approval_invalid_reason = ""
        self._event(proposal, "aprovacao humana registrada; patch nao aplicado", previous, proposal.state)
        self._save()
        return "Aprovacao registrada. Nenhum patch foi aplicado ao projeto principal."

    def aplicar(self, proposal_id: str) -> str:
        proposal = self._get(proposal_id)
        if proposal.state != "APROVADA":
            return "Aplicacao bloqueada: aprove explicitamente antes com /aya-dev aprovar ID."
        previous = proposal.state
        proposal.state = "PREPARANDO_COMMIT"
        self._event(proposal, "preparando commit isolado", previous, proposal.state)
        try:
            self._validate_apply_preconditions(proposal)
            branch = self._proposal_branch(proposal.id)
            self._ensure_git_identity()
            if self._branch_exists(branch):
                raise RuntimeError("BRANCH_EXISTENTE")
            self._git(("switch", "-c", branch), cwd=Path(proposal.workspace), timeout=60)
            changed_files = self._approved_files(proposal)
            self._git(("add", "--", *changed_files), cwd=Path(proposal.workspace), timeout=60)
            staged_names = self._git(("diff", "--cached", "--name-only"), cwd=Path(proposal.workspace), timeout=30).stdout.splitlines()
            if sorted(staged_names) != sorted(changed_files):
                raise RuntimeError("STAGING_FORA_DO_ESCOPO")
            cached_check = self._git(("diff", "--cached", "--check"), cwd=Path(proposal.workspace), timeout=30)
            if cached_check.returncode != 0:
                raise RuntimeError(f"STAGED_DIFF_CHECK: {self.workspace.sanitize(cached_check.stderr or cached_check.stdout)}")
            cached_diff = self._git(("diff", "--cached", "--no-ext-diff", "--"), cwd=Path(proposal.workspace), timeout=30).stdout
            if self._sha_text(cached_diff) != proposal.approved_diff_sha256:
                raise RuntimeError("STAGED_DIFF_DIVERGENTE")
            message = f"aya-dev: {self._short_title(proposal.title)} [{proposal.id}]"
            commit = self._git(("commit", "-m", message), cwd=Path(proposal.workspace), timeout=90)
            if commit.returncode != 0:
                raise RuntimeError(f"COMMIT_FALHOU: {self.workspace.sanitize(commit.stderr or commit.stdout)}")
            commit_hash = self._git(("rev-parse", "HEAD"), cwd=Path(proposal.workspace), timeout=30).stdout.strip()
            parent = self._git(("rev-parse", "HEAD^"), cwd=Path(proposal.workspace), timeout=30).stdout.strip()
            proposal.proposal_branch = branch
            proposal.proposal_commit = commit_hash
            proposal.commit_parent = parent
            proposal.committed_at = datetime.now().isoformat(timespec="seconds")
            proposal.committed_files = changed_files
            proposal.committed_diff_sha256 = self._sha_text(cached_diff)
            proposal.commit_message = message
            proposal.main_head_at_commit = self.workspace.head()
            proposal.main_unchanged = proposal.main_head_at_commit == proposal.approved_base_commit
            proposal.ready_for_integration = True
            proposal.state = "COMMIT_PRONTO"
            self._event(proposal, "commit isolado criado no worktree", "PREPARANDO_COMMIT", proposal.state)
            self._save()
            return "\n".join([
                f"Commit isolado criado: {commit_hash}",
                f"- Branch: {branch}",
                "- Main nao foi alterada.",
                "- Integracao ainda nao ocorreu.",
                "- Push nao ocorreu.",
            ])
        except Exception as exc:
            proposal.state = "FALHOU"
            message = self.workspace.sanitize(str(exc))
            self._record_failure(proposal, "commit", "commit isolado falhou", message)
            self._event(proposal, "commit isolado falhou", "PREPARANDO_COMMIT", proposal.state)
            self._save()
            return f"Aplicacao bloqueada: {message}"

    def integrar(self, proposal_id: str) -> str:
        proposal = self._get(proposal_id)
        if proposal.state == "INTEGRADA":
            return self._integrated_idempotent_response(proposal)
        if proposal.state == "COMMIT_PRONTO" and proposal.proposal_commit and self.workspace.head() == proposal.proposal_commit:
            return self._finalize_already_fast_forwarded(proposal)
        previous = proposal.state
        proposal.state = "VALIDANDO_INTEGRACAO"
        proposal.integration_started_at = datetime.now().isoformat(timespec="seconds")
        proposal.integration_method = "fast-forward"
        proposal.pushed = False
        proposal.remote_used = False
        proposal.merge_commit_created = False
        self._event(proposal, "validando integracao explicita", previous, proposal.state)
        try:
            self._validate_integration_preconditions(proposal)
            validation = self._validate_commit_in_clean_worktree(proposal)
            proposal.integration_validation = validation
            if not all(item.get("passed") for item in validation):
                raise RuntimeError("VALIDACAO_LIMPA_REPROVADA")
            proposal.previous_main_head = self.workspace.head()
            proposal.main_branch = self._git(("branch", "--show-current"), cwd=self.root, timeout=30).stdout.strip()
            proposal.state = "INTEGRANDO"
            self._event(proposal, "iniciando fast-forward estrito", "VALIDANDO_INTEGRACAO", proposal.state)
            self._validate_main_ready_for_fast_forward(proposal)
            merge = self._git(("merge", "--ff-only", proposal.proposal_branch), cwd=self.root, timeout=90)
            if merge.returncode != 0:
                raise RuntimeError("FAST_FORWARD_INDISPONIVEL")
            proposal.resulting_main_head = self.workspace.head()
            proposal.integrated_commit = proposal.proposal_commit
            proposal.integrated_at = datetime.now().isoformat(timespec="seconds")
            post = self._post_integration_validation(proposal)
            proposal.post_integration_validation = post
            if not all(item.get("passed") for item in post):
                proposal.integration_partial = True
                proposal.state = "INTEGRACAO_BLOQUEADA"
                proposal.integration_block_reason = "VALIDACAO_POS_INTEGRACAO_REPROVADA"
                self._event(proposal, "validacao pos-integracao reprovada", "INTEGRANDO", proposal.state)
                self._save()
                return "Integracao parcial registrada: a main avancou, mas a validacao posterior falhou. Revisao humana necessaria."
            cleanup = self._cleanup_integrated_worktree(proposal)
            proposal.integration_cleanup_result = cleanup
            proposal.workspace_cleaned = "removido" in cleanup.lower()
            if proposal.workspace_cleaned:
                proposal.workspace = ""
                proposal.worktree_cleanup_pending = False
            else:
                proposal.worktree_cleanup_pending = True
            proposal.integration_success = True
            proposal.state = "INTEGRADA"
            self._event(proposal, "commit integrado por fast-forward", "INTEGRANDO", proposal.state)
            self._save()
            return "\n".join([
                "Integracao concluida por fast-forward estrito.",
                f"- Commit integrado: {proposal.integrated_commit}",
                f"- Main antes: {proposal.previous_main_head}",
                f"- Main depois: {proposal.resulting_main_head}",
                "- Merge commit criado: nao",
                "- Push executado: nao",
                "- Remoto usado: nao",
                f"- Validacao previa: {self._checks_status(proposal.integration_validation)}",
                f"- Validacao posterior: {self._checks_status(proposal.post_integration_validation)}",
                f"- Limpeza do worktree: {proposal.integration_cleanup_result}",
                "- Estado final: INTEGRADA",
            ])
        except Exception as exc:
            if proposal.previous_main_head and self.workspace.head() != proposal.previous_main_head:
                proposal.integration_partial = True
                proposal.state = "INTEGRACAO_BLOQUEADA"
                proposal.resulting_main_head = self.workspace.head()
                proposal.integrated_commit = proposal.proposal_commit if proposal.resulting_main_head == proposal.proposal_commit else ""
                proposal.integration_block_reason = self.workspace.sanitize(str(exc))
                proposal.failure_stage = "integracao"
                proposal.failure_reason = proposal.integration_block_reason
                proposal.failure_message = proposal.integration_block_reason
                proposal.failure_at = datetime.now().isoformat(timespec="seconds")
                self._event(proposal, "integracao parcial bloqueada", previous, "INTEGRACAO_BLOQUEADA")
                self._save()
                return "Integracao parcial registrada: a main avancou, mas a validacao posterior falhou. Revisao humana necessaria."
            proposal.state = "INTEGRACAO_BLOQUEADA"
            proposal.integration_block_reason = self.workspace.sanitize(str(exc))
            proposal.failure_stage = proposal.failure_stage or "integracao"
            proposal.failure_reason = proposal.integration_block_reason
            proposal.failure_message = proposal.integration_block_reason
            proposal.failure_at = datetime.now().isoformat(timespec="seconds")
            self._event(proposal, "integracao bloqueada", previous, proposal.state)
            self._save()
            return f"Integracao bloqueada: {proposal.integration_block_reason}. Main permaneceu intacta."

    def integracao(self, proposal_id: str) -> str:
        proposal = self._get(proposal_id)
        eligible, reason = self._integration_eligibility(proposal)
        return "\n".join([
            f"Integracao {proposal.id}:",
            f"- Elegivel agora: {'sim' if eligible else 'nao'}",
            f"- Motivo do bloqueio: {reason or proposal.integration_block_reason or 'nenhum'}",
            f"- Inicio: {proposal.integration_started_at or 'Informacao nao registrada.'}",
            f"- Metodo: {proposal.integration_method or 'Informacao nao registrada.'}",
            f"- Main antes: {proposal.previous_main_head or 'Informacao nao registrada.'}",
            f"- Main depois: {proposal.resulting_main_head or 'Informacao nao registrada.'}",
            f"- Commit integrado: {proposal.integrated_commit or proposal.proposal_commit or 'Informacao nao registrada.'}",
            f"- Validacao previa: {self._checks_status(proposal.integration_validation)}",
            f"- Validacao posterior: {self._checks_status(proposal.post_integration_validation)}",
            f"- Merge commit criado: {'sim' if proposal.merge_commit_created else 'nao'}",
            f"- Push executado: {'sim' if proposal.pushed else 'nao'}",
            f"- Remoto usado: {'sim' if proposal.remote_used else 'nao'}",
            f"- Limpeza do worktree: {proposal.integration_cleanup_result or 'Informacao nao registrada.'}",
            f"- Estado final: {proposal.state}",
        ])

    def solicitar_reversao(self, payload: str) -> str:
        raw_id, _, reason = payload.partition(" ")
        if not raw_id.strip() or not reason.strip():
            return "Solicitacao recusada: informe /aya-dev solicitar-reversao ID MOTIVO."
        proposal = self._get(raw_id.strip())
        if proposal.state != "INTEGRADA":
            return "Solicitacao recusada: somente propostas INTEGRADAS podem ser revertidas."
        previous = proposal.state
        proposal.state = "REVERSAO_SOLICITADA"
        proposal.reversal_requested_at = datetime.now().isoformat(timespec="seconds")
        proposal.reversal_reason = self.workspace.sanitize(reason.strip(), 1000)
        proposal.reversal_requested_by = "local_user"
        proposal.reversal_target_commit = proposal.integrated_commit or proposal.proposal_commit
        proposal.reversal_base_commit = self.workspace.head()
        proposal.reversal_main_before = proposal.reversal_base_commit
        proposal.reversal_error = ""
        proposal.reversal_partial = False
        self._clear_reversal_preview(proposal)
        proposal.reversal_approval_valid = False
        proposal.reversal_approval_invalid_reason = "previsao de reversao ainda nao aprovada"
        self._event(proposal, "reversao solicitada", previous, proposal.state)
        self._save()
        return "\n".join([
            f"Reversao solicitada para {proposal.id}.",
            f"- Motivo: {proposal.reversal_reason}",
            f"- Commit alvo: {proposal.reversal_target_commit}",
            f"- Main atual: {proposal.reversal_main_before}",
            "- Proximo passo: /aya-dev prever-reversao ID",
        ])

    def prever_reversao(self, proposal_id: str) -> str:
        proposal = self._get(proposal_id)
        previous = proposal.state
        try:
            if proposal.state == "INTEGRADA" and not proposal.reversal_reason:
                raise RuntimeError("MOTIVO_AUSENTE")
            if proposal.state not in {
                "INTEGRADA", "REVERSAO_SOLICITADA", "PREVISAO_REVERSAO_PRONTA",
                "AGUARDANDO_APROVACAO_REVERSAO", "PREVISAO_REVERSAO_BLOQUEADA",
            }:
                raise RuntimeError("ESTADO_NAO_PERMITE_PREVISAO")
            proposal.state = "GERANDO_PREVISAO_REVERSAO"
            self._event(proposal, "gerando previsao deterministica de reversao", previous, proposal.state)
            if not proposal.reversal_target_commit:
                proposal.reversal_target_commit = proposal.integrated_commit or proposal.proposal_commit
            proposal.reversal_base_commit = self.workspace.head()
            proposal.reversal_main_before = proposal.reversal_base_commit
            proposal.state = "VALIDANDO_REVERSAO"
            self._event(proposal, "validando previsao de reversao", "GERANDO_PREVISAO_REVERSAO", proposal.state)
            self._validate_reversal_preconditions(proposal, require_approval=False)
            preview = self._build_reversal_preview(proposal)
            self._store_reversal_preview(proposal, preview)
            proposal.reversal_review_sha256 = self._sha_text(proposal.reversal_reason)
            proposal.reversal_manifest_sha256 = self._sha_json(self._reversal_manifest(proposal))
            if not proposal.reversal_preview_valid:
                raise RuntimeError(proposal.reversal_preview_invalidated_reason or "PREVISAO_REVERSAO_INVALIDA")
            proposal.state = "PREVISAO_REVERSAO_PRONTA"
            self._event(proposal, "previsao de reversao pronta", "VALIDANDO_REVERSAO", proposal.state)
            proposal.state = "AGUARDANDO_APROVACAO_REVERSAO"
            self._event(proposal, "reversao aguardando aprovacao humana", "VALIDANDO_REVERSAO", proposal.state)
            self._save()
            return "\n".join([
                f"Previsao de reversao pronta para {proposal.id}.",
                f"- Identificador: {self._reversal_preview_code(proposal)}",
                f"- Commit alvo: {proposal.reversal_target_commit}",
                f"- Base da main: {proposal.reversal_preview_base_head}",
                f"- Arquivos: {', '.join(proposal.reversal_preview_files) or 'nenhum'}",
                f"- Linhas adicionadas: {proposal.reversal_preview_added_lines}",
                f"- Linhas removidas: {proposal.reversal_preview_removed_lines}",
                f"- Hash da previsao: {proposal.reversal_preview_sha256}",
                f"- Validacao: {self._checks_status(proposal.reversal_preview_validation)}",
                f"- Main intacta: {'sim' if proposal.reversal_preview_main_unchanged else 'nao'}",
                "- Proximo passo: /aya-dev aprovar-reversao ID",
            ])
        except Exception as exc:
            proposal.state = "PREVISAO_REVERSAO_BLOQUEADA"
            proposal.reversal_error = self.workspace.sanitize(str(exc))
            proposal.reversal_preview_valid = False
            proposal.reversal_preview_invalidated_reason = proposal.reversal_error
            self._event(proposal, "previsao de reversao bloqueada", previous, proposal.state)
            self._save()
            return f"Previsao de reversao bloqueada: {proposal.reversal_error}. Main permaneceu intacta."

    def diff_reversao(self, proposal_id: str) -> str:
        proposal = self._get(proposal_id)
        if not proposal.reversal_preview_diff:
            return "Diff de reversao: Informacao nao registrada."
        return f"Diff de reversao {proposal.id}:\n{proposal.reversal_preview_diff}"

    def aprovar_reversao(self, proposal_id: str) -> str:
        proposal = self._get(proposal_id)
        if proposal.state != "AGUARDANDO_APROVACAO_REVERSAO":
            return "Aprovacao de reversao recusada: gere uma previsao valida antes com /aya-dev prever-reversao ID."
        valid, reason = self._reversal_snapshot_valid(proposal)
        if not valid:
            proposal.reversal_approval_valid = False
            proposal.reversal_approval_invalid_reason = reason
            self._save()
            return f"Aprovacao de reversao recusada: {reason}"
        previous = proposal.state
        proposal.state = "REVERSAO_APROVADA"
        proposal.reversal_approved_at = datetime.now().isoformat(timespec="seconds")
        proposal.reversal_approved_by = "local_user"
        proposal.reversal_approved_validation_sha256 = self._sha_json(proposal.reversal_validation)
        proposal.reversal_approved_review_sha256 = self._sha_text(proposal.reversal_reason)
        proposal.reversal_approved_manifest_sha256 = self._sha_json(self._reversal_manifest(proposal))
        proposal.reversal_approved_base_commit = proposal.reversal_base_commit
        proposal.approved_reversal_preview_sha256 = proposal.reversal_preview_sha256
        proposal.approved_reversal_base_head = proposal.reversal_preview_base_head
        proposal.approved_reversal_target_commit = proposal.reversal_preview_target_commit
        proposal.approved_reversal_validation_sha256 = proposal.reversal_preview_validation_sha256
        proposal.reversal_approval_valid = True
        proposal.reversal_approval_invalid_reason = ""
        self._event(proposal, "aprovacao humana de reversao registrada", previous, proposal.state)
        self._save()
        return "Aprovacao de reversao registrada. Nenhum revert foi executado ainda."

    def reversao(self, proposal_id: str) -> str:
        proposal = self._get(proposal_id)
        valid, reason = self._reversal_currently_valid(proposal)
        return "\n".join([
            f"Reversao {proposal.id}:",
            "",
            "Solicitacao:",
            f"- Estado: {proposal.state}",
            f"- Motivo: {proposal.reversal_reason or 'Informacao nao registrada.'}",
            f"- Solicitada em: {proposal.reversal_requested_at or 'Informacao nao registrada.'}",
            f"- Commit alvo: {proposal.reversal_target_commit or 'Informacao nao registrada.'}",
            "",
            "Pre-visualizacao:",
            f"- Estado: {'valida' if proposal.reversal_preview_valid else 'indisponivel/invalida'}",
            f"- Main base: {proposal.reversal_preview_base_head or 'Informacao nao registrada.'}",
            f"- Arquivos afetados: {', '.join(proposal.reversal_preview_files) or 'Informacao nao registrada.'}",
            f"- Linhas adicionadas: {proposal.reversal_preview_added_lines}",
            f"- Linhas removidas: {proposal.reversal_preview_removed_lines}",
            f"- Diff inverso: {'registrado' if proposal.reversal_preview_diff else 'Informacao nao registrada.'}",
            f"- Conflitos: {proposal.reversal_preview_conflicts or 'nenhum'}",
            f"- Testes: {self._checks_status(proposal.reversal_preview_validation)}",
            f"- Hash da previsao: {proposal.reversal_preview_sha256 or 'Informacao nao registrada.'}",
            f"- Validade: {'sim' if proposal.reversal_preview_valid else 'nao'}",
            f"- Motivo de invalidacao: {proposal.reversal_preview_invalidated_reason or 'nenhum'}",
            f"- Worktree temporario limpo: {'sim' if proposal.reversal_preview_workspace_cleaned else 'nao'}",
            f"- Main intacta: {'sim' if proposal.reversal_preview_main_unchanged else 'nao'}",
            "",
            "Aprovacao:",
            f"- Aprovada: {'sim' if proposal.reversal_approval_valid else 'nao'}",
            f"- Data: {proposal.reversal_approved_at or 'Informacao nao registrada.'}",
            f"- Hash aprovado: {proposal.approved_reversal_preview_sha256 or 'Informacao nao registrada.'}",
            f"- Aprovacao valida agora: {'sim' if valid else 'nao'}",
            f"- Motivo de invalidacao: {reason or proposal.reversal_error or 'nenhum'}",
            "",
            "Execucao:",
            f"- Main antes: {proposal.reversal_main_before or 'Informacao nao registrada.'}",
            f"- Commit de reversao: {proposal.reversal_commit or 'Informacao nao registrada.'}",
            f"- Main depois: {proposal.reversal_main_after or 'Informacao nao registrada.'}",
            f"- Validacao previa: {self._checks_status(proposal.reversal_preview_validation or proposal.reversal_validation)}",
            f"- Validacao posterior: {self._checks_status(proposal.reversal_post_validation)}",
            f"- Reversao parcial: {'sim' if proposal.reversal_partial else 'nao'}",
            "- Push executado: nao",
            "- Remoto usado: nao",
        ])

    def reverter(self, proposal_id: str) -> str:
        proposal = self._get(proposal_id)
        if proposal.state == "REVERTIDA":
            return self._reverted_idempotent_response(proposal)
        if proposal.state in {"REVERSAO_PARCIAL", "REVERSAO_FALHOU"} and proposal.reversal_commit and self.workspace.head() == proposal.reversal_commit:
            return self._finalize_already_reverted(proposal)
        if proposal.state != "REVERSAO_APROVADA":
            return "Reversao bloqueada: aprove explicitamente antes com /aya-dev aprovar-reversao ID."
        previous = proposal.state
        proposal.state = "REVERTENDO"
        proposal.reversal_started_at = datetime.now().isoformat(timespec="seconds")
        proposal.reversal_main_before = self.workspace.head()
        self._event(proposal, "reversao iniciada por git revert", previous, proposal.state)
        try:
            self._validate_reversal_preconditions(proposal, require_approval=True)
            self._validate_reversal_approval_for_execution(proposal)
            self._validate_main_ready_for_revert(proposal)
            revert = self.workspace._run(("git", "revert", "--no-edit", proposal.reversal_target_commit), self.root, 120)
            if revert.returncode != 0:
                raise RuntimeError(f"GIT_REVERT_FALHOU: {self.workspace.sanitize(revert.stderr or revert.stdout)}")
            proposal.reversal_commit = self.workspace.head()
            proposal.reversal_main_after = proposal.reversal_commit
            post = self._post_reversal_validation(proposal)
            proposal.reversal_post_validation = post
            if not all(item.get("passed") for item in post):
                proposal.reversal_partial = True
                proposal.state = "REVERSAO_PARCIAL"
                proposal.reversal_error = "VALIDACAO_POS_REVERSAO_REPROVADA"
                self._event(proposal, "validacao pos-reversao reprovada", "REVERTENDO", proposal.state)
                self._save()
                return "Reversao parcial registrada: o commit de revert foi criado, mas a validacao posterior falhou."
            proposal.reversal_completed_at = datetime.now().isoformat(timespec="seconds")
            proposal.reversal_partial = False
            proposal.state = "REVERTIDA"
            self._event(proposal, "reversao concluida por git revert", "REVERTENDO", proposal.state)
            self._save()
            return "\n".join([
                "Reversao concluida por git revert.",
                f"- Commit alvo: {proposal.reversal_target_commit}",
                f"- Commit de reversao: {proposal.reversal_commit}",
                f"- Main antes: {proposal.reversal_main_before}",
                f"- Main depois: {proposal.reversal_main_after}",
                f"- Validacao previa: {self._checks_status(proposal.reversal_validation)}",
                f"- Validacao posterior: {self._checks_status(proposal.reversal_post_validation)}",
                "- Push executado: nao",
                "- Remoto usado: nao",
                "- Estado final: REVERTIDA",
            ])
        except Exception as exc:
            if proposal.reversal_main_before and self.workspace.head() != proposal.reversal_main_before:
                proposal.reversal_partial = True
                proposal.state = "REVERSAO_PARCIAL"
                proposal.reversal_commit = self.workspace.head()
                proposal.reversal_main_after = proposal.reversal_commit
                proposal.reversal_error = self.workspace.sanitize(str(exc))
                self._event(proposal, "reversao parcial registrada", previous, proposal.state)
                self._save()
                return "Reversao parcial registrada: a main avancou, mas a operacao nao foi concluida. Revisao humana necessaria."
            proposal.state = "REVERSAO_FALHOU"
            proposal.reversal_error = self.workspace.sanitize(str(exc))
            self._event(proposal, "reversao falhou antes de mover a main", previous, proposal.state)
            self._save()
            return f"Reversao bloqueada: {proposal.reversal_error}. Main permaneceu intacta."

    def rejeitar(self, proposal_id: str) -> str:
        raw_id, _, reason = proposal_id.partition("|")
        proposal = self._get(raw_id.strip())
        previous = proposal.state
        proposal.state = "REJEITADA"
        proposal.approval_valid = False
        proposal.approval_invalid_reason = reason.strip() or "rejeitada pelo usuario"
        if proposal.workspace:
            try:
                proposal.cleanup_result = self.workspace.discard(proposal.workspace)
                proposal.workspace_cleaned = True
                proposal.workspace = ""
            except (OSError, RuntimeError, ValueError) as exc:
                proposal.cleanup_result = self.workspace.sanitize(str(exc))
        self._event(proposal, "rejeicao humana registrada", previous, proposal.state)
        self._save()
        return f"Proposta {proposal.id} rejeitada."

    def commit(self, proposal_id: str) -> str:
        proposal = self._get(proposal_id)
        if not proposal.proposal_commit:
            return "Commit isolado: Informacao nao registrada."
        return "\n".join([
            "Commit isolado:",
            f"- Branch: {proposal.proposal_branch}",
            f"- Hash: {proposal.proposal_commit}",
            f"- Pai: {proposal.commit_parent}",
            f"- Arquivos: {', '.join(proposal.committed_files)}",
            f"- Mensagem: {proposal.commit_message}",
            f"- Worktree: {proposal.workspace_path or proposal.workspace}",
            f"- Main intacta: {'sim' if proposal.main_unchanged else 'nao'}",
            f"- Pronto para integracao: {'sim' if proposal.ready_for_integration else 'nao'}",
        ])

    def descartar(self, proposal_id: str) -> str:
        proposal = self._get(proposal_id)
        if proposal.workspace:
            try:
                proposal.cleanup_result = self.workspace.discard(proposal.workspace)
                proposal.workspace_cleaned = True
            except (OSError, RuntimeError, ValueError) as exc:
                return f"Nao foi possivel descartar o workspace: {self.workspace.sanitize(str(exc))}"
            proposal.workspace = ""
        self._event(proposal, "workspace isolado descartado", proposal.state, proposal.state)
        self._save()
        return "Workspace isolado descartado; projeto principal permaneceu intacto."

    def pacote_codex(self, proposal_id: str) -> str:
        proposal = self._get(proposal_id)
        checks = [
            f"{item.get('name')}: {'APROVADO' if item.get('passed') else 'REPROVADO'}"
            for item in proposal.validation[-8:]
        ]
        return "\n".join([
            f"Pacote tecnico para Codex - {proposal.id}",
            f"Problema: {proposal.problem}",
            f"Evidencias: {' | '.join(proposal.evidence)}",
            f"Arquivos: {', '.join(proposal.related_files)}",
            f"Simbolos: {', '.join(proposal.related_symbols)}",
            f"Risco: {proposal.risk}",
            f"Tentativas: {proposal.attempts}/{self.max_attempts}",
            f"Testes: {' | '.join(checks) or 'nao executados'}",
            f"Critica do revisor: {proposal.review_result or 'nao disponivel'}",
            f"Diff tentado:\n{proposal.patch[:5000] or 'nenhum diff valido'}",
            f"Comportamento esperado: {'; '.join(proposal.preserve)}",
            "Perguntas abertas: confirmar causa e menor alteracao segura.",
        ])

    def history(self) -> str:
        events = [(proposal.id, event) for proposal in self.proposals.values() for event in proposal.history]
        events.sort(key=lambda item: item[1].get("at", ""), reverse=True)
        if not events:
            return "Historico tecnico do Aya Dev: vazio."
        lines = ["Historico tecnico do Aya Dev:"]
        for proposal_id, event in events[:30]:
            lines.append(f"- {event['at']} {proposal_id}: {event['action']} ({event['before']} -> {event['after']})")
        return "\n".join(lines)

    def engineering_events(self) -> str:
        events = self._technical_events()
        if not events:
            return "Eventos tecnicos do Aya Dev: nenhum evento relevante registrado."
        lines = ["Eventos tecnicos relevantes do Aya Dev:"]
        for proposal_id, event in events[:30]:
            action = self.workspace.sanitize(str(event.get("action", "")), 160)
            before = self.workspace.sanitize(str(event.get("before", "")), 80)
            after = self.workspace.sanitize(str(event.get("after", "")), 80)
            lines.append(f"- {event.get('at', '')} {proposal_id}: {action} ({before} -> {after})")
        return "\n".join(lines)

    def metrics(self) -> str:
        proposals = sorted(self.proposals.values(), key=lambda value: value.id)
        states = self._count_values(proposal.state for proposal in proposals)
        risks = self._count_values(proposal.risk for proposal in proposals)
        failures = self._count_values(
            f"{proposal.failure_stage or 'etapa_indisponivel'}:{proposal.failure_reason or 'motivo_indisponivel'}"
            for proposal in proposals
            if proposal.failure_stage or proposal.failure_reason
        )
        related_files = self._count_values(file for proposal in proposals for file in proposal.related_files)
        validation = [item for proposal in proposals for item in self._all_validation_records(proposal)]
        validation_passed = sum(1 for item in validation if item.get("passed") is True)
        validation_failed = sum(1 for item in validation if item.get("passed") is False)
        partials = sum(
            1
            for proposal in proposals
            if proposal.integration_partial or proposal.reversal_partial or proposal.state in {"REVERSAO_PARCIAL"}
        )
        attention = [
            proposal.id
            for proposal in proposals
            if proposal.state
            in {
                "FALHOU", "INTEGRACAO_BLOQUEADA", "REVERSAO_BLOQUEADA",
                "REVERSAO_FALHOU", "REVERSAO_PARCIAL", "PREVISAO_REVERSAO_BLOQUEADA",
            }
        ]
        memory_entries = self._load_engineering_memory()
        technical_events = self._technical_events()
        lines = [
            "Metricas deterministicas do Aya Dev:",
            f"- Origem das propostas: {self.storage_path}",
            f"- Propostas registradas: {len(proposals)}",
            f"- Estados: {self._format_counts(states)}",
            f"- Riscos: {self._format_counts(risks)}",
            f"- Validacoes registradas: {len(validation)} (aprovadas={validation_passed}, reprovadas={validation_failed})",
            f"- Propostas integradas: {states.get('INTEGRADA', 0)}",
            f"- Propostas revertidas: {states.get('REVERTIDA', 0)}",
            f"- Propostas com falha ou bloqueio: {len(attention)}",
            f"- Estados parciais: {partials}",
            f"- Eventos tecnicos relevantes: {len(technical_events)}",
            f"- Memorias tecnicas registradas: {len(memory_entries)}",
            "- Falhas por etapa: " + self._format_counts(failures),
            "- Arquivos relacionados mais citados: " + self._format_counts(related_files, limit=8),
            "- Observacao: este calculo usa somente dados persistidos; nao executa Git, modelo, testes ou rede.",
        ]
        if attention:
            lines.append("- Propostas que pedem atencao: " + ", ".join(attention[:10]))
        return "\n".join(lines)

    def engineering_memory(self) -> str:
        entries = self._load_engineering_memory()
        lines = ["Memoria tecnica de engenharia do Aya Dev:"]
        if entries:
            for item in entries[-20:]:
                lines.append(f"- {item.id} [{item.kind}] {item.title}: {item.content}")
        else:
            lines.append("- Nenhuma memoria tecnica registrada manualmente.")
        derived = self._derived_engineering_memory()
        if derived:
            lines.extend(["", "Sinais derivados do historico:"])
            lines.extend(f"- {item}" for item in derived)
        else:
            lines.extend(["", "Sinais derivados do historico:", "- Nenhum sinal recorrente encontrado."])
        return "\n".join(lines)

    def register_engineering_memory(self, payload: str) -> str:
        parts = [part.strip() for part in payload.split("|")]
        if len(parts) == 2:
            kind = "tecnica"
            title, content = parts
        elif len(parts) == 3:
            kind, title, content = parts
        else:
            return "Use assim: /aya-dev registrar-memoria tipo | titulo | conteudo"
        kind = self._normalize_memory_kind(kind)
        title = self.workspace.sanitize(title, 160).strip()
        content = self.workspace.sanitize(content, 1200).strip()
        if not title or not content:
            return "Memoria tecnica recusada: informe titulo e conteudo."
        entry_id = self._engineering_memory_id(kind, title, content, "manual")
        existing = {entry.id: entry for entry in self._load_engineering_memory()}
        if entry_id in existing:
            return f"Memoria tecnica ja registrada: {entry_id}."
        entry = EngineeringMemoryEntry(
            id=entry_id,
            kind=kind,
            title=title,
            content=content,
            source="manual",
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        self._append_engineering_memory(entry)
        return f"Memoria tecnica registrada: {entry.id}."

    def autonomy_status(self) -> str:
        state = self._load_autonomy_state()
        candidates = self._autonomous_candidates()
        metrics = self._candidate_queue_metrics(candidates)
        return "\n".join([
            "Autonomia supervisionada do Aya Dev:",
            f"- Modo: {state['mode']}",
            f"- Politica: v{AUTONOMY_POLICY_VERSION}",
            f"- Detectados: {metrics['detected']}",
            f"- Acao recomendada: {metrics['recommended_action']}",
            f"- Manutencao opcional: {metrics['optional_maintenance']}",
            f"- Informativos: {metrics['informative']}",
            f"- Historicos considerados: {metrics['historical']}",
            f"- Duplicados bloqueados: {metrics['duplicates']}",
            f"- Obsoletos: {metrics['stale']}",
            f"- Elegiveis: {metrics['eligible']}",
            f"- Bloqueados: {metrics['blocked']}",
            f"- Candidato selecionado: {state.get('selected_candidate_id') or 'nenhum'}",
            f"- Ciclo em execucao: {state.get('active_proposal_id') or 'nenhum'}",
            "- Limite: uma tarefa por comando; para em AGUARDANDO_APROVACAO.",
        ])

    def set_autonomy_mode(self, payload: str) -> str:
        requested = (payload or "").strip().lower().replace("_", "-")
        mapping = {
            "desligada": "DESLIGADA",
            "desligado": "DESLIGADA",
            "observar": "OBSERVAR",
            "preparar-supervisionado": "PREPARAR_SUPERVISIONADO",
        }
        mode = mapping.get(requested)
        if not mode:
            return "Use: /aya-dev autonomia desligada|observar|preparar-supervisionado"
        state = self._load_autonomy_state()
        before = state["mode"]
        state["mode"] = mode
        state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_autonomy_state(state)
        self._autonomy_event("autonomy_mode_changed", {"before": before, "after": mode})
        return f"Modo de autonomia alterado: {before} -> {mode}."

    def evaluate_autonomy(self) -> str:
        candidates = self._autonomous_candidates()
        stats = self._operation_stats()
        metrics = self._candidate_queue_metrics(candidates)
        lines = [
            "Avaliacao de autonomia do Aya Dev:",
            f"- Politica: v{AUTONOMY_POLICY_VERSION}",
            f"- HEAD: {self._safe_head()}",
            "- Periodo analisado: historico persistido completo do Aya Dev",
            f"- Quantidade minima exigida: {AUTONOMY_MIN_CASES} casos, {AUTONOMY_MIN_SUCCESSES} sucessos locais",
            f"- Amostra disponivel: {sum(item['total'] for item in stats.values())} operacao(oes)",
            "- Categorias elegiveis: documentacao, mensagem_tecnica, teste_caracterizacao, import_nao_usado",
            "- Categorias bloqueadas: seguranca, banco, memoria, rag, remoto, voz, release, git interno, dependencias",
            f"- Operacoes avaliadas: {', '.join(sorted(AUTONOMY_ALLOWED_OPERATIONS))}",
        ]
        for operation in sorted(AUTONOMY_ALLOWED_OPERATIONS):
            item = self._empty_operation_stats() | stats.get(operation, {})
            status = self._operation_policy_status(operation, item)
            lines.append(
                f"- {operation}: total={item['total']}; sucessos={item['success']}; falhas={item['fail']}; "
                f"inconclusivos={item['inconclusive']}; rejeitados={item['rejected']}; cancelados={item['cancelled']}; "
                f"escalados={item['escalated']}; integrados={item['integrated']}; revertidos={item['reverted']}; "
                f"testes={item['test_fixture']}; importados={item['legacy_import']}; desconhecidos={item['unknown']}; "
                f"primeira_tentativa={item['first_attempt_success']}; politica={status}"
            )
        lines.extend([
            f"- Registros historicos considerados: {metrics['historical']}",
            f"- Candidatos detectados: {metrics['detected']}",
            f"- Informativos: {metrics['informative']}",
            f"- Manutencao opcional: {metrics['optional_maintenance']}",
            f"- Acao recomendada: {metrics['recommended_action']}",
            f"- Acionaveis: {metrics['actionable']}",
            f"- Duplicados bloqueados: {metrics['duplicates']}",
            f"- Obsoletos: {metrics['stale']}",
            f"- Elegiveis: {metrics['eligible']}",
            f"- Bloqueados: {metrics['blocked']}",
            f"- Bloqueados por risco: {metrics['blocked_by_risk']}",
            f"- Bloqueados por capacidade: {metrics['blocked_by_capacity']}",
            f"- Bloqueados por dados insuficientes: {metrics['blocked_by_insufficient_data']}",
        ])
        return "\n".join(lines)

    def list_candidates(self, scope: str = "") -> str:
        candidates = self._autonomous_candidates()
        scope = (scope or "resumo").lower().strip()
        metrics = self._candidate_queue_metrics(candidates)
        if scope in {"", "resumo", "atuais"}:
            selected = [candidate for candidate in candidates if not candidate.stale and candidate.qualification_status in {"ACAO_RECOMENDADA", "MANUTENCAO_OPCIONAL"}]
            lines = [
                "Resumo dos Candidatos autonomos do Aya Dev:",
                self._format_candidate_funnel(metrics),
                "",
                "Top candidatos priorizados:",
            ]
            return "\n".join([*lines, *self._format_candidate_items(selected[:20])])
        if scope.startswith("top"):
            candidates = [candidate for candidate in candidates if not candidate.stale and candidate.qualification_status in {"ACAO_RECOMENDADA", "MANUTENCAO_OPCIONAL"}]
        elif "informativo" in scope:
            candidates = [candidate for candidate in candidates if candidate.qualification_status == "INFORMATIVO" and not candidate.stale]
        elif "manutencao" in scope or "manutenção" in scope:
            candidates = [candidate for candidate in candidates if candidate.qualification_status == "MANUTENCAO_OPCIONAL" and not candidate.stale]
        elif "bloqueado" in scope:
            parts = scope.split(maxsplit=1)
            reason = parts[1].strip().upper() if len(parts) > 1 else ""
            candidates = [
                candidate for candidate in candidates
                if candidate.status == "BLOQUEADO" and (not reason or reason in {code.upper() for code in candidate.reason_codes + candidate.blocked_reasons})
            ]
        elif "obsoleto" in scope:
            candidates = [candidate for candidate in candidates if candidate.stale]
        elif "historico" in scope:
            return self.capability_report("")
        else:
            candidates = [candidate for candidate in candidates if not candidate.stale]
        if not candidates:
            return "Candidatos autonomos: nenhum candidato real detectado."
        return "\n".join(["Candidatos autonomos do Aya Dev:", *self._format_candidate_items(candidates[:20])])

    def _format_candidate_items(self, candidates: list[AutonomousCandidate]) -> list[str]:
        if not candidates:
            return ["- nenhum candidato prioritario."]
        lines: list[str] = []
        for item in candidates:
            lines.append(
                f"- {item.candidate_id} [{item.qualification_status}/{item.eligibility}] rota={item.route} "
                f"prioridade={item.priority_score} valor_doc={item.documentation_value_score} risco={item.risk} "
                f"{item.operation_type}: {item.title}"
            )
            lines.append(f"  head={item.project_head[:12]} arquivo={item.file} simbolo={item.symbol or 'n/a'}")
            lines.append(f"  razoes: {self._format_reason_codes(item.reason_codes[:8])}")
            if item.blocked_reasons:
                lines.append(f"  bloqueios: {'; '.join(item.blocked_reasons)}")
            if item.stale:
                lines.append(f"  obsoleto: {item.stale_reason}")
        return lines

    def _format_reason_codes(self, codes: list[str]) -> str:
        if not codes:
            return "nenhuma"
        return "; ".join(f"{code}={AUTONOMY_REASON_EXPLANATIONS.get(code, 'Sem explicacao registrada.')}" for code in codes)

    def _format_candidate_funnel(self, metrics: dict[str, int]) -> str:
        return "\n".join([
            f"- Detectados: {metrics['detected']}",
            f"- Relevantes: {metrics['relevant']}",
            f"- Nao relevantes: {metrics['not_relevant']}",
            f"- Acionaveis: {metrics['actionable']}",
            f"- Informativos: {metrics['informative']}",
            f"- Manutencao opcional: {metrics['optional_maintenance']}",
            f"- Acao recomendada: {metrics['recommended_action']}",
            f"- Qualificados: {metrics['qualified']}",
            f"- Duplicados: {metrics['duplicates']}",
            f"- Obsoletos: {metrics['stale']}",
            f"- Bloqueados por politica: {metrics['blocked_by_policy']}",
            f"- Bloqueados por capacidade: {metrics['blocked_by_capacity']}",
            f"- Bloqueados por risco: {metrics['blocked_by_risk']}",
            f"- Elegiveis: {metrics['eligible']}",
        ])

    def explain_candidate(self, candidate_id: str) -> str:
        return self.show_candidate(candidate_id)

    def show_candidate(self, candidate_id: str) -> str:
        candidate = self._find_candidate(candidate_id)
        if not candidate:
            return f"Candidato autonomo nao encontrado: {candidate_id}"
        return "\n".join([
            f"Candidato {candidate.candidate_id}:",
            f"- Titulo: {candidate.title}",
            f"- Problema: {candidate.problem}",
            f"- Operacao: {candidate.operation_type}",
            f"- Categoria: {candidate.category}",
            f"- HEAD de deteccao: {candidate.project_head}",
            f"- Arquivo: {candidate.file}",
            f"- Hash do arquivo: {candidate.file_sha256}",
            f"- Simbolo: {candidate.symbol or 'nao aplicavel'}",
            f"- Assinatura: {candidate.symbol_signature or 'nao aplicavel'}",
            f"- Motivo: {candidate.reason}",
            f"- Mudanca esperada: {candidate.expected_change}",
            f"- Arquivos: {', '.join(candidate.files)}",
            f"- Simbolos: {', '.join(candidate.symbols)}",
            f"- Evidencias: {' | '.join(candidate.evidence)}",
            f"- Status: {candidate.status}",
            f"- Classe: {candidate.qualification_status}",
            f"- Relevante: {'sim' if candidate.relevance_valid else 'nao'}",
            f"- Acionavel: {'sim' if candidate.actionable else 'nao'}",
            f"- Valor de documentacao: {candidate.documentation_value_score}",
            f"- Razoes de valor: {' | '.join(candidate.documentation_value_reasons) or 'nenhuma'}",
            f"- Prioridade: {candidate.priority_score}",
            f"- Razoes de prioridade: {' | '.join(candidate.priority_reasons) or 'nenhuma'}",
            f"- Reason codes: {self._format_reason_codes(candidate.reason_codes)}",
            f"- Diagnostico Ruff: {candidate.ruff_diagnostic.get('diagnostic_sha256', 'nao aplicavel') if candidate.ruff_diagnostic else 'nao aplicavel'}",
            f"- Atual: {'nao' if candidate.stale else 'sim'}",
            f"- Obsolescencia: {candidate.stale_reason or 'nenhuma'}",
            f"- Fonte: {candidate.source_origin}",
            f"- Elegibilidade: {candidate.eligibility}",
            f"- Rota: {candidate.route}",
            f"- Bloqueios: {' | '.join(candidate.blocked_reasons) or 'nenhum'}",
            f"- Score: {candidate.score}",
            f"- Justificativa: {' | '.join(candidate.score_explanation)}",
            f"- Chave de deduplicacao: {candidate.deduplication_key}",
            f"- Licoes usadas: {' | '.join(candidate.related_lessons) or 'nenhuma'}",
            f"- Propostas similares: {' | '.join(candidate.similar_proposals) or 'nenhuma'}",
            f"- Registro: {candidate.record_sha256}",
        ])

    def calibration_candidates(self) -> str:
        candidates = [candidate for candidate in self._autonomous_candidates() if self._calibration_candidate_allowed(candidate)[0]]
        if not candidates:
            return "Nenhum candidato suficientemente seguro para calibracao real no HEAD atual."
        lines = [
            "Shortlist segura para calibracao real:",
            "- Nenhum candidato sera executado automaticamente.",
            "- A criacao de experimento ainda exige escolha humana explicita.",
        ]
        for candidate in candidates[:5]:
            semantic = self._semantic_safety(candidate.file, candidate.symbol)
            lines.append(
                f"- {candidate.candidate_id}: {candidate.file}::{candidate.symbol or 'n/a'} "
                f"operacao={candidate.operation_type}; responsabilidade={semantic.responsibility}; "
                f"sensibilidade={semantic.sensitivity}; linhas={candidate.estimated_changed_lines}"
            )
            lines.append(f"  reason_codes={', '.join(semantic.reason_codes + candidate.reason_codes[:4])}")
            lines.append(f"  chamadas_relevantes={', '.join(semantic.relevant_calls) or 'nenhuma'}")
        return "\n".join(lines)

    def explain_calibration_candidate(self, candidate_id: str) -> str:
        candidate = self._find_candidate(candidate_id.strip())
        if not candidate:
            return f"Candidato autonomo nao encontrado: {candidate_id}"
        allowed, block_reasons = self._calibration_candidate_allowed(candidate)
        semantic = self._semantic_safety(candidate.file, candidate.symbol)
        operation_stats = self._empty_operation_stats() | self._operation_stats().get(candidate.operation_type, {})
        return "\n".join([
            f"Analise de calibracao {candidate.candidate_id}:",
            f"- Arquivo: {candidate.file}",
            f"- Simbolo: {candidate.symbol or 'nao aplicavel'}",
            f"- Operacao: {candidate.operation_type}",
            f"- Responsabilidade: {semantic.responsibility}",
            f"- Sensibilidade: {semantic.sensitivity}",
            f"- Motivo tecnico: {candidate.reason}",
            f"- Tamanho estimado: {candidate.estimated_changed_lines} linha(s)",
            f"- Testes relacionados: {', '.join(candidate.required_tests) or 'suite completa necessaria'}",
            f"- Chamadas relevantes: {', '.join(semantic.relevant_calls) or 'nenhuma'}",
            f"- Reason codes: {self._format_reason_codes(list(dict.fromkeys([*candidate.reason_codes, *semantic.reason_codes])))}",
            f"- Bloqueios avaliados: {'; '.join(block_reasons) or 'nenhum'}",
            f"- Capacidade atual: {self._capability_level(candidate.operation_type, operation_stats)}",
            f"- Pipeline: {PATCH_PIPELINE_VERSION}",
            f"- Decisao final: {'apto para shortlist' if allowed else 'bloqueado para primeira calibracao real'}",
            "- Execucao automatica: nao. Este comando nao chama modelo, nao cria worktree e nao altera a main.",
        ])

    def observe_cycle(self) -> str:
        before = self.workspace.git_state()
        candidates = self._autonomous_candidates(force=True)
        after = self.workspace.git_state()
        metrics = self._candidate_queue_metrics(candidates)
        report = self._candidate_scan_report
        return "\n".join([
            "Observacao autonoma somente leitura:",
            f"- Git antes: {before.message}",
            f"- Git depois: {after.message}",
            "- Modelo chamado: nao",
            "- Worktree criado: nao",
            "- Codigo alterado: nao",
            f"- Duracao da varredura: {report['scan_duration_ms']}ms",
            f"- Arquivos analisados: {report['files_scanned']}",
            f"- Arquivos reutilizados: {report['files_reused']}",
            f"- Cache hits: {report['cache_hits']}",
            f"- Cache misses: {report['cache_misses']}",
            f"- Chamadas Ruff: {report['ruff_calls']}",
            f"- Construcoes do indice: {report['index_builds']}",
            f"- Total bruto detectado: {report['raw_detected']}",
            f"- Exclusoes duras: {sum(report['hard_exclusions'].values())}",
            "- Contadores de exclusao: " + self._format_counts(report["hard_exclusions"]),
            self._format_candidate_funnel(metrics),
            "Top candidatos:",
            *self._format_candidate_items([candidate for candidate in candidates if not candidate.stale][:5]),
        ])

    def renew_candidates(self) -> str:
        candidates = self._autonomous_candidates(force=True)
        metrics = self._candidate_queue_metrics(candidates)
        report = self._candidate_scan_report
        return "\n".join([
            "Renovacao de candidatos concluida sem preparar patch:",
            f"- HEAD: {self._safe_head()}",
            f"- Duracao: {report['scan_duration_ms']}ms",
            f"- Arquivos analisados: {report['files_scanned']}",
            f"- Arquivos reutilizados: {report['files_reused']}",
            f"- Arquivos removidos: {report['files_removed']}",
            f"- Cache hits: {report['cache_hits']}",
            f"- Cache misses: {report['cache_misses']}",
            f"- Ruff F401: {report['ruff_diagnostics']} diagnostico(s), {report['ruff_calls']} chamada(s)",
            f"- Total bruto detectado: {report['raw_detected']}",
            f"- Exclusoes duras: {sum(report['hard_exclusions'].values())}",
            "- Contadores de exclusao: " + self._format_counts(report["hard_exclusions"]),
            self._format_candidate_funnel(metrics),
        ])

    def capability_report(self, payload: str = "") -> str:
        parts = (payload or "").split(maxsplit=1)
        filter_kind = parts[0].lower() if parts else ""
        filter_value = parts[1].strip() if len(parts) > 1 else ""
        filter_value_normalized = filter_value.lower()
        stats = self._operation_stats(
            category=filter_value_normalized if filter_kind == "categoria" else "",
            model=filter_value_normalized if filter_kind == "modelo" else "",
        )
        lines = [
            "Capacidade historica do Aya Dev:",
            f"- Politica: v{AUTONOMY_POLICY_VERSION}",
            "- Periodo: historico persistido completo",
        ]
        if filter_kind in {"operacao", "categoria", "modelo"}:
            lines.append(f"- Filtro: {filter_kind}={filter_value}")
        versioned = self._versioned_operation_stats()
        for operation in sorted(stats):
            if filter_kind == "operacao" and operation != filter_value_normalized:
                continue
            item = self._empty_operation_stats() | stats[operation]
            level = self._capability_level(operation, item)
            current = versioned.get(operation, {}).get("current", {})
            legacy = versioned.get(operation, {}).get("legacy", {})
            unknown = versioned.get(operation, {}).get("unknown", {})
            lines.append(
                f"- Operacao {operation}: nivel={level}; total={item['total']}; production_real={item['production_real']}; "
                f"test_fixture={item['test_fixture']}; legacy_import={item['legacy_import']}; unknown={item['unknown']}; "
                f"sucessos={item['success']}; falhas={item['fail']}; inconclusivos={item['inconclusive']}; "
                f"rejeitados={item['rejected']}; cancelados={item['cancelled']}; escalados={item['escalated']}; "
                f"integrados={item['integrated']}; revertidos={item['reverted']}; primeira_tentativa={item['first_attempt_success']}"
            )
            lines.append(
                f"  pipeline_atual: casos={current.get('total', 0)}; sucessos={current.get('success', 0)}; "
                f"falhas={current.get('fail', 0)}; inconclusivos={current.get('inconclusive', 0)}; "
                f"integrados={current.get('integrated', 0)}; revertidos={current.get('reverted', 0)}"
            )
            lines.append(
                f"  pipeline_legado: casos={legacy.get('total', 0)}; sucessos={legacy.get('success', 0)}; "
                f"falhas={legacy.get('fail', 0)}; inconclusivos={legacy.get('inconclusive', 0)}"
            )
            lines.append(
                f"  pipeline_desconhecido: casos={unknown.get('total', 0)}; sucessos={unknown.get('success', 0)}; "
                f"falhas={unknown.get('fail', 0)}; inconclusivos={unknown.get('inconclusive', 0)}"
            )
        return "\n".join(lines)

    def list_experiments(self) -> str:
        if not self.experiments:
            return "Experimentos de calibracao do Aya Dev: nenhum registrado."
        lines = [
            "Experimentos de calibracao do Aya Dev:",
            f"- Pipeline atual: {PATCH_PIPELINE_VERSION}",
            f"- Schema: {STRUCTURED_PATCH_SCHEMA_VERSION}",
            f"- Prompt: {PATCH_PROMPT_VERSION}",
            "- Autonomia ampliada: nao",
        ]
        for experiment in sorted(self.experiments.values(), key=lambda item: item.created_at, reverse=True)[:30]:
            lines.append(
                f"- {experiment.experiment_id} [{experiment.state}] candidato={experiment.candidate_id}; "
                f"proposta={experiment.proposal_id or 'nao criada'}; operacao={experiment.operation_type}; "
                f"arquivo={experiment.file}; tentativa={experiment.attempt}; resultado={experiment.result or 'pendente'}"
            )
        return "\n".join(lines)

    def experiment_results(self) -> str:
        if not self.experiments:
            return "Resultados de experimentos: nenhum dado disponivel."
        counts = self._count_values(experiment.result or experiment.state for experiment in self.experiments.values())
        by_operation = self._count_values(experiment.operation_type for experiment in self.experiments.values())
        lines = [
            "Resultados versionados de calibracao:",
            f"- Pipeline atual: {PATCH_PIPELINE_VERSION}",
            "- Resultados: " + self._format_counts(counts),
            "- Operacoes: " + self._format_counts(by_operation),
        ]
        for experiment in sorted(self.experiments.values(), key=lambda item: item.created_at, reverse=True)[:10]:
            lines.append(
                f"- {experiment.experiment_id}: estado={experiment.state}; evidencia={experiment.evidence_strength or 'nao registrada'}; "
                f"patch={experiment.patch_result or 'nao executado'}; validacao={experiment.validation_result or 'nao executada'}; "
                f"revisao={experiment.review_result or 'nao executada'}"
            )
        return "\n".join(lines)

    def create_calibration_experiment(self, candidate_id: str) -> str:
        candidate = self._find_candidate(candidate_id.strip())
        if not candidate:
            return f"Candidato autonomo nao encontrado: {candidate_id}"
        allowed, reasons = self._calibration_candidate_allowed(candidate)
        if not allowed:
            return "\n".join([
                "Experimento de calibracao bloqueado.",
                f"- Candidato: {candidate.candidate_id}",
                "- Motivos: " + "; ".join(reasons),
                "- Patch executado: nao",
                "- Worktree criado: nao",
            ])
        active = [
            item.experiment_id
            for item in self.experiments.values()
            if item.candidate_id == candidate.candidate_id and item.state not in {"CANCELADO", "FALHOU", "BLOQUEADO", "CONCLUIDO"}
        ]
        if active:
            return f"Experimento ja existe para este candidato: {', '.join(active[:3])}"
        active_global = [
            item.experiment_id
            for item in self.experiments.values()
            if item.state not in {"CANCELADO", "FALHOU", "BLOQUEADO", "CONCLUIDO", "AGUARDANDO_APROVACAO"}
        ]
        if len(active_global) >= 3:
            return "Experimento bloqueado: limite global de 3 experimentos ativos atingido."
        proposal = self.create_proposal(
            title=f"[CALIBRATION] {candidate.title}",
            problem=candidate.problem,
            evidence=[*candidate.evidence, f"candidato={candidate.candidate_id}", f"pipeline={PATCH_PIPELINE_VERSION}"],
            related_files=candidate.files,
            related_symbols=candidate.symbols,
            probable_cause=candidate.reason,
            suggested_change=candidate.expected_change,
            preserve=["comportamento existente", "main intacta", "sem commit automatico"],
            impact="baixo",
            urgency="baixa",
            difficulty="baixa",
            required_tests=candidate.required_tests,
            done_criteria=["patch preparado em worktree isolado", "validacao obrigatoria aprovada", "revisao registrada", "sem commit automatico"],
        )
        proposal.patch_pipeline_version = PATCH_PIPELINE_VERSION
        proposal.schema_version = STRUCTURED_PATCH_SCHEMA_VERSION
        proposal.prompt_version = PATCH_PROMPT_VERSION
        proposal.analyzer_version = CANDIDATE_ANALYZER_VERSION
        proposal.risk_policy_version = RISK_POLICY_VERSION
        proposal.project_head = self._safe_head()
        self._save()
        experiment_id = f"EXP-{self._sha_json({'candidate': candidate.candidate_id, 'proposal': proposal.id, 'head': candidate.project_head})[:12].upper()}"
        experiment = CalibrationExperiment(
            experiment_id=experiment_id,
            candidate_id=candidate.candidate_id,
            proposal_id=proposal.id,
            created_at=datetime.now().isoformat(timespec="seconds"),
            selected_by="local_user",
            project_head=candidate.project_head,
            file=candidate.file,
            file_sha256=candidate.file_sha256,
            symbol=candidate.symbol,
            operation_type=candidate.operation_type,
            category=candidate.category,
            pipeline_version=PATCH_PIPELINE_VERSION,
            schema_version=STRUCTURED_PATCH_SCHEMA_VERSION,
            prompt_version=PATCH_PROMPT_VERSION,
            model=self.primary_model,
            reviewer_model=self.reviewer_model,
            reason=candidate.reason,
            expected_change=candidate.expected_change,
            allowed_files=candidate.allowed_files,
            related_tests=candidate.required_tests,
            risk=candidate.risk,
            estimated_changed_lines=candidate.estimated_changed_lines,
            state="AGUARDANDO_CONFIRMACAO",
            evidence_strength="CALIBRACAO_PLANEJADA",
        )
        experiment.record_sha256 = self._experiment_record_sha(experiment)
        self.experiments[experiment.experiment_id] = experiment
        self._save_experiments()
        return "\n".join([
            "Experimento de calibracao criado sem executar patch.",
            f"- Experimento: {experiment.experiment_id}",
            f"- Candidato: {candidate.candidate_id}",
            f"- Proposta supervisionada: {proposal.id}",
            f"- Pipeline: {PATCH_PIPELINE_VERSION}",
            f"- Estado: {experiment.state}",
            "- Modelo chamado: nao",
            "- Worktree criado: nao",
            "- Confirmacao para executar: EXECUTAR EXPERIMENTO " + experiment.experiment_id,
        ])

    def show_experiment(self, experiment_id: str) -> str:
        experiment = self.experiments.get(experiment_id.strip())
        if not experiment:
            return f"Experimento nao encontrado: {experiment_id}"
        return "\n".join([
            f"Experimento {experiment.experiment_id}:",
            f"- Estado: {experiment.state}",
            f"- Candidato: {experiment.candidate_id}",
            f"- Proposta: {experiment.proposal_id or 'nao criada'}",
            f"- HEAD: {experiment.project_head}",
            f"- Arquivo: {experiment.file}",
            f"- Hash do arquivo: {experiment.file_sha256}",
            f"- Simbolo: {experiment.symbol or 'nao aplicavel'}",
            f"- Operacao: {experiment.operation_type}",
            f"- Pipeline: {experiment.pipeline_version}",
            f"- Schema: {experiment.schema_version}",
            f"- Prompt: {experiment.prompt_version}",
            f"- Risco: {experiment.risk}",
            f"- Linhas estimadas: {experiment.estimated_changed_lines}",
            f"- Tentativa: {experiment.attempt}/2",
            f"- Manifesto: {experiment.manifest_result or 'nao executado'}",
            f"- Patch: {experiment.patch_result or 'nao executado'}",
            f"- Validacao: {experiment.validation_result or 'nao executada'}",
            f"- Revisao: {experiment.review_result or 'nao executada'}",
            f"- Decisao humana: {experiment.human_decision or 'pendente'}",
            f"- Resultado: {experiment.result or 'pendente'}",
            f"- Registro: {experiment.record_sha256}",
        ])

    def execute_calibration_experiment(self, payload: str) -> str:
        experiment_id, _, confirmation = (payload or "").partition("|")
        experiment_id = experiment_id.strip()
        confirmation = confirmation.strip() or (payload or "").strip()
        expected = f"EXECUTAR EXPERIMENTO {experiment_id}"
        if not experiment_id:
            return "Informe o ID do experimento."
        experiment = self.experiments.get(experiment_id)
        if not experiment:
            return f"Experimento nao encontrado: {experiment_id}"
        if confirmation != expected:
            return f"Confirmacao incorreta. Digite exatamente: {expected}"
        if experiment.experiment_id in self._experiment_locks:
            return "Experimento bloqueado: ja existe execucao em andamento."
        if experiment.state == "AGUARDANDO_APROVACAO":
            return "Experimento ja preparou patch e aguarda aprovacao humana; nenhum commit foi criado."
        if experiment.state not in {"AGUARDANDO_CONFIRMACAO", "FALHOU"}:
            return f"Experimento nao executavel no estado atual: {experiment.state}"
        if experiment.attempt >= 2:
            experiment.state = "BLOQUEADO"
            experiment.result = "LIMITE_DE_TENTATIVAS"
            experiment.record_sha256 = self._experiment_record_sha(experiment)
            self._save_experiments()
            return "Experimento bloqueado: limite de duas tentativas atingido."
        candidate = self._find_candidate(experiment.candidate_id)
        allowed, reasons = self._calibration_candidate_allowed(candidate) if candidate else (False, ["candidato indisponivel"])
        if not allowed:
            experiment.state = "BLOQUEADO"
            experiment.result = "CANDIDATO_INVALIDO"
            experiment.patch_result = "nao executado"
            experiment.validation_result = "nao executada"
            experiment.review_result = "nao executada"
            experiment.record_sha256 = self._experiment_record_sha(experiment)
            self._save_experiments()
            return "Experimento bloqueado: " + "; ".join(reasons)
        proposal = self._get(experiment.proposal_id)
        self._experiment_locks.add(experiment.experiment_id)
        try:
            experiment.state = "EXECUTANDO"
            experiment.attempt += 1
            experiment.record_sha256 = self._experiment_record_sha(experiment)
            self._save_experiments()
            prepare_result = self._prepare_autonomous_proposal(proposal, candidate)
            experiment.manifest_result = "gerado" if proposal.patch_manifest else "nao gerado"
            experiment.patch_result = "preparado" if proposal.patch else self.workspace.sanitize(prepare_result, 400)
            if proposal.state == "EM_TESTE":
                test_result = self.testar(proposal.id)
                experiment.validation_result = "aprovada" if proposal.state == "AGUARDANDO_APROVACAO" else self.workspace.sanitize(test_result, 400)
            else:
                experiment.validation_result = "nao executada"
            if proposal.state == "AGUARDANDO_APROVACAO":
                review_result = self.revisar(proposal.id)
                experiment.review_result = "registrada" if proposal.review_result else self.workspace.sanitize(review_result, 400)
                experiment.state = "AGUARDANDO_APROVACAO"
                experiment.result = "PATCH_VALIDADO_SEM_COMMIT"
                experiment.evidence_strength = "CALIBRACAO_VALIDADA"
            else:
                experiment.state = "FALHOU"
                experiment.result = "FALHA_CONTROLADA"
                experiment.evidence_strength = "CALIBRACAO_FALHOU"
            experiment.record_sha256 = self._experiment_record_sha(experiment)
            self._save_experiments()
            return "\n".join([
                "Experimento de calibracao executado em fluxo supervisionado.",
                f"- Experimento: {experiment.experiment_id}",
                f"- Proposta: {proposal.id}",
                f"- Estado da proposta: {proposal.state}",
                f"- Estado do experimento: {experiment.state}",
                f"- Manifesto: {experiment.manifest_result}",
                f"- Patch: {experiment.patch_result}",
                f"- Validacao: {experiment.validation_result}",
                f"- Revisao: {experiment.review_result}",
                "- Commit criado: nao",
                "- Integracao executada: nao",
                "- Main alterada: nao",
            ])
        finally:
            self._experiment_locks.discard(experiment.experiment_id)

    def cancel_calibration_experiment(self, experiment_id: str) -> str:
        experiment = self.experiments.get(experiment_id.strip())
        if not experiment:
            return f"Experimento nao encontrado: {experiment_id}"
        if experiment.state in {"AGUARDANDO_APROVACAO", "CONCLUIDO"}:
            return "Experimento nao cancelado: ja produziu artefato supervisionado."
        experiment.state = "CANCELADO"
        experiment.result = "CANCELADO_PELO_USUARIO"
        experiment.human_decision = "cancelado"
        experiment.record_sha256 = self._experiment_record_sha(experiment)
        self._save_experiments()
        return f"Experimento {experiment.experiment_id} cancelado; nenhum commit foi criado."

    def route_candidate(self, candidate_id: str) -> str:
        candidate = self._find_candidate(candidate_id)
        if not candidate:
            return f"Candidato autonomo nao encontrado: {candidate_id}"
        return f"Rota {candidate.candidate_id}: {candidate.route}"

    def explain_route(self, candidate_id: str) -> str:
        candidate = self._find_candidate(candidate_id)
        if not candidate:
            return f"Candidato autonomo nao encontrado: {candidate_id}"
        stats = self._empty_operation_stats() | self._operation_stats().get(candidate.operation_type, {})
        return "\n".join([
            f"Rota para {candidate.candidate_id}: {candidate.route}",
            f"- Elegibilidade: {candidate.eligibility}",
            f"- Status: {candidate.status}",
            f"- Classe: {candidate.qualification_status}",
            f"- Acionavel: {'sim' if candidate.actionable else 'nao'}",
            f"- Obsoleto: {'sim' if candidate.stale else 'nao'} {candidate.stale_reason}",
            f"- Risco: {candidate.risk}",
            f"- Operacao: {candidate.operation_type}",
            f"- Capacidade: {self._capability_level(candidate.operation_type, stats)}",
            f"- Fonte: {candidate.source_origin}",
            f"- Bloqueios: {' | '.join(candidate.blocked_reasons) or 'nenhum'}",
            f"- Score: {candidate.score} ({'; '.join(candidate.score_explanation)})",
            "- Este comando nao executa patch, modelo, worktree, aprovacao, commit ou integracao.",
        ])

    def select_candidate(self, candidate_id: str) -> str:
        candidate = self._find_candidate(candidate_id)
        if not candidate:
            return f"Candidato autonomo nao encontrado: {candidate_id}"
        if candidate.stale:
            return f"Selecao bloqueada: OBSOLETO ({candidate.stale_reason})."
        if candidate.qualification_status != "ACAO_RECOMENDADA" or not candidate.actionable:
            return f"Selecao bloqueada: {candidate.qualification_status} nao e acao recomendada."
        if candidate.eligibility != "ELEGIVEL":
            return f"Selecao bloqueada: {candidate.eligibility} ({'; '.join(candidate.blocked_reasons) or 'sem motivo adicional'})."
        state = self._load_autonomy_state()
        state["selected_candidate_id"] = candidate.candidate_id
        state["selected_score"] = candidate.score
        state["selected_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_autonomy_state(state)
        self._autonomy_event("candidate_selected", asdict(candidate))
        return f"Candidato selecionado: {candidate.candidate_id} score={candidate.score}."

    def cancel_candidate(self, candidate_id: str) -> str:
        state = self._load_autonomy_state()
        if state.get("selected_candidate_id") != candidate_id:
            return f"Nenhum candidato selecionado com ID {candidate_id}."
        state["selected_candidate_id"] = ""
        state["active_proposal_id"] = ""
        state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_autonomy_state(state)
        self._autonomy_event("autonomous_cycle_cancelled", {"candidate_id": candidate_id})
        return f"Candidato cancelado: {candidate_id}."

    def autonomous_queue(self) -> str:
        state = self._load_autonomy_state()
        return "\n".join([
            "Fila autonoma do Aya Dev:",
            f"- Modo: {state['mode']}",
            f"- Selecionado: {state.get('selected_candidate_id') or 'nenhum'}",
            f"- Proposta ativa: {state.get('active_proposal_id') or 'nenhuma'}",
            f"- Ultima atualizacao: {state.get('updated_at') or 'nao registrada'}",
        ])

    def execute_safe_autonomous_cycle(self) -> str:
        state = self._load_autonomy_state()
        if state["mode"] != "PREPARAR_SUPERVISIONADO":
            return "SEM_TAREFA_SEGURA: autonomia precisa estar em PREPARAR_SUPERVISIONADO."
        blocked = self._autonomy_preflight()
        if blocked:
            return f"SEM_TAREFA_SEGURA: {blocked}"
        selected = self._select_best_candidate()
        if not selected:
            self._autonomy_event("candidate_blocked", {"reason": "nenhum candidato elegivel"})
            return "SEM_TAREFA_SEGURA: nenhum candidato elegivel com evidencia suficiente."
        return self.execute_candidate(selected.candidate_id)

    def execute_candidate(self, candidate_id: str) -> str:
        state = self._load_autonomy_state()
        if state["mode"] != "PREPARAR_SUPERVISIONADO":
            return "Execucao bloqueada: modo atual nao permite preparar proposta."
        blocked = self._autonomy_preflight()
        if blocked:
            return f"Execucao bloqueada: {blocked}"
        candidate = self._find_candidate(candidate_id)
        if not candidate:
            return f"Candidato autonomo nao encontrado: {candidate_id}"
        if candidate.stale:
            return f"Execucao bloqueada: OBSOLETO ({candidate.stale_reason})."
        if candidate.qualification_status != "ACAO_RECOMENDADA" or not candidate.actionable:
            return f"Execucao bloqueada: {candidate.qualification_status} nao e acao recomendada."
        if candidate.route not in {"LOCAL_PREPARE_ONLY", "LOCAL_SUPERVISED"}:
            return f"Execucao bloqueada pela rota: {candidate.route}."
        if candidate.eligibility != "ELEGIVEL":
            return f"Execucao bloqueada: {candidate.eligibility} ({'; '.join(candidate.blocked_reasons)})."
        self._autonomy_event("autonomous_cycle_started", asdict(candidate))
        proposal = self.create_proposal(
            title=f"[AUTO] {candidate.title}",
            problem=candidate.problem,
            evidence=candidate.evidence,
            related_files=candidate.files,
            related_symbols=candidate.symbols,
            probable_cause="Melhoria pequena detectada por regra deterministica do Aya Dev.",
            suggested_change=self._candidate_suggested_change(candidate),
            preserve=["main intacta", "sem aprovacao automatica", "sem commit automatico"],
            impact="baixo",
            urgency="baixa",
            difficulty="baixa",
            required_tests=candidate.required_tests or ["python -m pytest"],
            done_criteria=["patch isolado validado", "revisao registrada", "estado AGUARDANDO_APROVACAO"],
        )
        proposal.model = f"autonomy-policy-v{AUTONOMY_POLICY_VERSION}"
        proposal.state = "PLANEJADA"
        self._event(proposal, "autonomous_proposal_created", "PROPOSTA", "PLANEJADA")
        state["selected_candidate_id"] = candidate.candidate_id
        state["active_proposal_id"] = proposal.id
        state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_autonomy_state(state)
        self._save()
        response = self._prepare_autonomous_proposal(proposal, candidate)
        if proposal.state == "EM_TESTE":
            test_response = self.testar(proposal.id)
            review_response = self.revisar(proposal.id)
            self._autonomy_event("autonomous_review_completed", {"proposal_id": proposal.id})
            if proposal.state == "AGUARDANDO_APROVACAO":
                self._autonomy_event("autonomous_waiting_human", {"proposal_id": proposal.id})
                state["active_proposal_id"] = ""
                self._save_autonomy_state(state)
            return "\n".join([
                response,
                test_response,
                review_response,
                f"Estado final: {proposal.state}",
                "Aprovacao automatica: nao executada.",
                "Commit/integracao automatica: nao executados.",
            ])
        if proposal.attempts < 2:
            second = self._prepare_autonomous_proposal(proposal, candidate)
            if proposal.state == "EM_TESTE":
                test_response = self.testar(proposal.id)
                review_response = self.revisar(proposal.id)
                return "\n".join([response, second, test_response, review_response, f"Estado final: {proposal.state}"])
            response = "\n".join([response, second])
        if proposal.state != "AGUARDANDO_APROVACAO":
            proposal.state = "FALHOU" if proposal.state != "FALHOU" else proposal.state
            package = self.pacote_codex(proposal.id)
            self._record_autonomous_escalation(proposal, candidate, package)
            state["active_proposal_id"] = ""
            self._save_autonomy_state(state)
            self._save()
            return response + "\nESCALADA: limite de duas tentativas atingido.\n" + package[:1200]
        return response

    def _context(self, proposal: EngineeringProposal, include_content: bool) -> str:
        entries = {item.path: item for item in self.index.build()}
        sections = [
            f"Problema: {proposal.problem}",
            f"Evidencias: {' | '.join(proposal.evidence)}",
            f"Arquivos confirmados: {', '.join(proposal.related_files)}",
            f"Simbolos: {', '.join(proposal.related_symbols)}",
            f"Mudanca solicitada: {proposal.suggested_change}",
            f"Preservar: {', '.join(proposal.preserve)}",
            f"Testes: {', '.join(proposal.required_tests)}",
        ]
        for rel in proposal.related_files[: self.max_files]:
            entry = entries.get(rel)
            if not entry:
                continue
            sections.append(self._entry_summary(entry))
            if include_content and not rel.startswith("tests/"):
                path = (self.root / rel).resolve()
                try:
                    path.relative_to(self.root)
                except ValueError:
                    continue
                if path.is_file() and not path.is_symlink():
                    sections.append(f"Trecho necessario de {rel}:\n{path.read_text(encoding='utf-8-sig', errors='replace')[:12000]}")
        similar = [item for item in self.proposals.values() if item.id != proposal.id and set(item.related_files) & set(proposal.related_files)]
        if similar:
            sections.append("Casos anteriores: " + " | ".join(f"{item.id}:{item.state}" for item in similar[-3:]))
        return "\n\n".join(sections)

    def _entry_summary(self, entry: TechnicalFile) -> str:
        return (
            f"Indice {entry.path}: hash={entry.sha256[:12]}, linhas={entry.lines}, "
            f"imports={entry.imports[:8]}, simbolos={(entry.classes + entry.functions + entry.methods)[:16]}, "
            f"testes={entry.related_tests[:4]}"
        )

    def _review_context(self, proposal: EngineeringProposal) -> str:
        return (
            f"Proposta: {proposal.title}\nProblema: {proposal.problem}\nRisco minimo: {proposal.risk}\n"
            f"Preservar: {proposal.preserve}\nTestes exigidos: {proposal.required_tests}\nDiff:\n{proposal.patch[:12000]}"
        )

    def _patch_rules(self) -> str:
        return (
            "Produza somente um diff unificado puro aplicavel por git apply. "
            "A primeira linha deve iniciar com 'diff --git ' ou '--- '. "
            "Nao escreva explicacoes, Markdown, cercas ``` ou conclusoes. "
            f"Maximo {self.max_files} arquivos e {self.max_changed_lines} linhas. "
            "Nao altere .env, dados, logs, banco, modelos, backups ou arquivos fora da raiz. "
            "Nao desative testes nem inclua comandos. Preserve o comportamento descrito."
        )

    def _extract_patch(self, response: str) -> str:
        patch = self.workspace.sanitize(response, 50000).strip()
        if "```" in patch:
            raise ValueError("Resposta em Markdown recusada; envie somente diff unificado puro.")
        return patch.rstrip() + "\n"

    def _use_structured_patch(self, proposal: EngineeringProposal) -> bool:
        return proposal.risk == "baixo" and len(proposal.related_files) <= self.max_files

    def _request_patch_decision(self, proposal: EngineeringProposal, base_commit: str) -> dict:
        messages = [
            {
                "role": "system",
                "content": (
                    "Retorne exatamente um objeto JSON compativel com o schema. "
                    "Nao use Markdown, explicacoes, campos extras ou texto de sucesso."
                ),
            },
            {"role": "user", "content": self._manifest_context(proposal, base_commit)},
        ]
        if hasattr(self.llm, "chat_structured"):
            try:
                raw = self.llm.chat_structured(
                    model=self.primary_model,
                    messages=messages,
                    response_schema=PATCH_DECISION_SCHEMA,
                    temperature=0.0,
                    max_tokens=1200,
                )
            except json.JSONDecodeError as exc:
                raise StructuredPatchError(f"JSON invalido: {exc.msg}.") from exc
        else:
            raw = self.llm.chat(
                model=self.primary_model,
                messages=messages,
                temperature=0.0,
                max_tokens=1200,
            )
        return raw

    def _manifest_context(self, proposal: EngineeringProposal, base_commit: str) -> str:
        target_file = self._structured_target_file(proposal)
        symbol = proposal.related_symbols[-1] if proposal.related_symbols else ""
        symbol_context = self._symbol_context(target_file, symbol)
        return "\n".join([
            f"titulo: {proposal.title}",
            f"objetivo: {proposal.suggested_change}",
            f"arquivo_definido_pela_aya: {target_file}",
            f"base_commit_definido_pela_aya: {base_commit}",
            f"simbolos_permitidos: {proposal.related_symbols}",
            f"simbolo_foco: {symbol}",
            f"comportamento_a_preservar: {proposal.preserve}",
            "schema_esperado: insert_docstring => {\"type\":\"insert_docstring\",\"symbol\":\"Classe.metodo\",\"content\":\"texto interno\"}; replace_exact => {\"type\":\"replace_exact\",\"old_text\":\"texto exato\",\"new_text\":\"texto novo\"}",
            "exemplo_valido: {\"type\":\"insert_docstring\",\"symbol\":\"Example.run\",\"content\":\"Return the normalized example value.\"}",
            "regras: sem Markdown; sem explicacoes; sem campos extras; nao diga que a alteracao foi feita; nao inclua file, proposal_id, base_commit, expected_sha256 ou tests.",
            "contexto_do_simbolo:",
            symbol_context,
            "erro_anterior:",
            proposal.failure_message or "nenhum",
            "motivo_anterior:",
            proposal.failure_reason or "nenhum",
        ])

    def _structured_target_file(self, proposal: EngineeringProposal) -> str:
        code_files = [path for path in proposal.related_files if path.endswith(".py") and not path.startswith("tests/")]
        if len(code_files) != 1:
            raise StructuredPatchError("Structured Patch exige exatamente um arquivo de codigo autorizado.")
        return code_files[0]

    def _file_sha256(self, rel: str, base: str | Path | None = None) -> str:
        root = Path(base).resolve() if base is not None else self.root
        path = (root / rel).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise StructuredPatchError("Arquivo fora da raiz.") from exc
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _symbol_context(self, rel: str, symbol: str) -> str:
        path = self.root / rel
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        lines = text.splitlines()
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return "simbolo indisponivel por erro de sintaxe."
        matches = self.structured_patch._find_symbol(tree, symbol)
        if len(matches) != 1:
            return "simbolo indisponivel ou ambiguo."
        node = matches[0]
        start = max(node.lineno - 1, 0)
        end = min(getattr(node, "end_lineno", node.lineno), len(lines))
        body = "\n".join(lines[start:end])
        return f"assinatura_linha={lines[start].strip()}\ncorpo:\n{body[:4000]}"

    def _related_tests(self, proposal: EngineeringProposal) -> list[str]:
        indexed = {item.path: item for item in self.index.build()}
        indexed_paths = set(indexed)
        tests = [path for path in proposal.related_files if self._is_valid_test_path(path, indexed_paths)]
        for path in proposal.related_files:
            entry = indexed.get(path)
            if entry:
                tests.extend(test for test in entry.related_tests if self._is_valid_test_path(test, indexed_paths))
        return list(dict.fromkeys(tests))[:4]

    def _is_valid_test_path(self, path: str, indexed_paths: set[str]) -> bool:
        name = Path(path).name
        return path in indexed_paths and path.startswith("tests/") and name.startswith("test_") and path.endswith(".py")

    def _format_checks(self, results: list[CheckResult], state: str) -> str:
        lines = [f"Validacao Aya Dev: {state}"]
        for result in results:
            if result.passed:
                status = "APROVADO"
            elif result.exit_code == 124:
                status = "VALIDACAO_INCONCLUSIVA_POR_TIMEOUT"
            else:
                status = "REPROVADO"
            lines.append(f"- {result.name}: {status} (codigo={result.exit_code}, {result.duration_ms}ms)")
        return "\n".join(lines)

    def _get(self, proposal_id: str) -> EngineeringProposal:
        proposal = self.proposals.get(proposal_id.upper())
        if not proposal:
            raise ValueError(f"Proposta Aya Dev nao encontrada: {proposal_id}")
        return proposal

    def _event(self, proposal: EngineeringProposal, action: str, before: str, after: str) -> None:
        proposal.history.append({
            "at": datetime.now().isoformat(timespec="seconds"),
            "action": action,
            "before": before,
            "after": after,
        })
        self._record_engineering_event_if_relevant(proposal, action, before, after)

    def _load(self) -> dict[str, EngineeringProposal]:
        try:
            raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        proposals: dict[str, EngineeringProposal] = {}
        for item in raw if isinstance(raw, list) else []:
            try:
                proposal = EngineeringProposal(**item)
            except (TypeError, ValueError):
                try:
                    known = {field.name for field in EngineeringProposal.__dataclass_fields__.values()}
                    proposal = EngineeringProposal(**{key: value for key, value in item.items() if key in known})
                except (AttributeError, TypeError, ValueError):
                    continue
            if proposal.state in PROPOSAL_STATES:
                proposal.risk = self.classify_risk(
                    proposal.problem,
                    proposal.related_files,
                    proposal.suggested_change,
                    proposal.risk,
                )
                proposals[proposal.id] = proposal
        return proposals

    def _save(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.storage_path.with_suffix(self.storage_path.suffix + ".tmp")
        payload = [asdict(item) for item in sorted(self.proposals.values(), key=lambda value: value.created_at)]
        text = json.dumps(payload, ensure_ascii=True, indent=2)
        temporary.write_text(self.workspace.sanitize(text, max(len(text), 5000)), encoding="utf-8")
        for attempt in range(5):
            try:
                temporary.replace(self.storage_path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05)

    def _load_experiments(self) -> dict[str, CalibrationExperiment]:
        try:
            raw = json.loads(self.calibration_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        experiments: dict[str, CalibrationExperiment] = {}
        known = set(CalibrationExperiment.__dataclass_fields__)
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                experiment = CalibrationExperiment(**{key: value for key, value in item.items() if key in known})
            except (TypeError, ValueError):
                continue
            experiments[experiment.experiment_id] = experiment
        return experiments

    def _save_experiments(self) -> None:
        self.calibration_path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps([asdict(item) for item in self.experiments.values()], ensure_ascii=True, indent=2, sort_keys=True)
        self.calibration_path.write_text(self.workspace.sanitize(text, max(len(text), 500000)), encoding="utf-8")

    def _all_validation_records(self, proposal: EngineeringProposal) -> list[dict]:
        records: list[dict] = []
        for field_name in (
            "validation",
            "integration_validation",
            "post_integration_validation",
            "reversal_validation",
            "reversal_post_validation",
            "reversal_preview_validation",
        ):
            value = getattr(proposal, field_name, [])
            if isinstance(value, list):
                records.extend(item for item in value if isinstance(item, dict))
        return records

    def _count_values(self, values) -> dict[str, int]:
        counts: dict[str, int] = {}
        for value in values:
            if value:
                key = self.workspace.sanitize(str(value), 240)
                counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))

    def _format_counts(self, counts: dict[str, int], limit: int | None = None) -> str:
        if not counts:
            return "nenhum"
        items = list(counts.items())
        if limit is not None:
            items = items[:limit]
        return ", ".join(f"{key}={value}" for key, value in items)

    def _normalize_memory_kind(self, kind: str) -> str:
        normalized = re.sub(r"[^a-z0-9_-]+", "_", kind.lower()).strip("_")
        return normalized if normalized in ENGINEERING_MEMORY_KINDS else "tecnica"

    def _engineering_memory_id(self, kind: str, title: str, content: str, source: str) -> str:
        digest = hashlib.sha256(f"{kind}\n{title}\n{content}\n{source}".encode("utf-8")).hexdigest()[:12].upper()
        return f"ENG-{digest}"

    def _load_engineering_memory(self) -> list[EngineeringMemoryEntry]:
        try:
            lines = self.engineering_memory_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        entries: list[EngineeringMemoryEntry] = []
        for line in lines:
            try:
                raw = json.loads(line)
                entry = EngineeringMemoryEntry(**{
                    "id": str(raw.get("id", "")),
                    "kind": self._normalize_memory_kind(str(raw.get("kind", "tecnica"))),
                    "title": self.workspace.sanitize(str(raw.get("title", "")), 160),
                    "content": self.workspace.sanitize(str(raw.get("content", "")), 1200),
                    "source": self.workspace.sanitize(str(raw.get("source", "")), 80),
                    "created_at": str(raw.get("created_at", "")),
                })
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if entry.id and entry.title and entry.content:
                entries.append(entry)
        entries.sort(key=lambda item: (item.created_at, item.id))
        return entries

    def _append_engineering_memory(self, entry: EngineeringMemoryEntry) -> None:
        self.engineering_memory_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(entry), ensure_ascii=True, sort_keys=True)
        with self.engineering_memory_path.open("a", encoding="utf-8") as file:
            file.write(payload + "\n")

    def _record_engineering_event_if_relevant(
        self,
        proposal: EngineeringProposal,
        action: str,
        before: str,
        after: str,
    ) -> None:
        if after not in ENGINEERING_MEMORY_EVENT_STATES:
            return
        kind = "incidente" if after in {"FALHOU", "INTEGRACAO_BLOQUEADA", "REVERSAO_FALHOU", "REVERSAO_PARCIAL"} else "decisao"
        title = f"{proposal.id}: {after}"
        content = self.workspace.sanitize(f"{action} ({before} -> {after})", 400)
        source = f"evento:{proposal.id}:{after}"
        entry_id = self._engineering_memory_id(kind, title, content, source)
        if entry_id in {entry.id for entry in self._load_engineering_memory()}:
            return
        self._append_engineering_memory(EngineeringMemoryEntry(
            id=entry_id,
            kind=kind,
            title=title,
            content=content,
            source=source,
            created_at=datetime.now().isoformat(timespec="seconds"),
        ))

    def _technical_events(self) -> list[tuple[str, dict]]:
        events = [
            (proposal.id, event)
            for proposal in self.proposals.values()
            for event in proposal.history
            if event.get("after") in ENGINEERING_MEMORY_EVENT_STATES
        ]
        events.sort(key=lambda item: (item[1].get("at", ""), item[0], item[1].get("action", "")), reverse=True)
        return events

    def _load_autonomy_state(self) -> dict:
        default = {
            "mode": "DESLIGADA",
            "selected_candidate_id": "",
            "active_proposal_id": "",
            "events": [],
            "updated_at": "",
        }
        try:
            raw = json.loads(self.autonomy_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return default
        if not isinstance(raw, dict):
            return default
        default.update({key: raw.get(key, value) for key, value in default.items()})
        if default["mode"] not in AUTONOMY_MODES:
            default["mode"] = "DESLIGADA"
        if not isinstance(default["events"], list):
            default["events"] = []
        return default

    def _save_autonomy_state(self, state: dict) -> None:
        self.autonomy_path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(state, ensure_ascii=True, indent=2, sort_keys=True)
        self.autonomy_path.write_text(self.workspace.sanitize(text, max(len(text), 5000)), encoding="utf-8")

    def _autonomy_event(self, action: str, data: dict) -> None:
        state = self._load_autonomy_state()
        safe_data = json.loads(self.workspace.sanitize(json.dumps(data, ensure_ascii=True, default=str), 3000))
        state["events"].append({
            "at": datetime.now().isoformat(timespec="seconds"),
            "action": action,
            "policy_version": AUTONOMY_POLICY_VERSION,
            "data": safe_data,
        })
        state["events"] = state["events"][-100:]
        state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_autonomy_state(state)

    def _autonomy_preflight(self) -> str:
        git = self.workspace.git_state()
        if not git.safe:
            return git.message
        worktrees = self._worktree_paths()
        unexpected = [path for path in worktrees if path != self.root]
        if unexpected:
            return "worktree inesperado ativo: " + ", ".join(str(path) for path in unexpected[:3])
        active = [
            proposal.id
            for proposal in self.proposals.values()
            if proposal.title.startswith("[AUTO]") and proposal.state in {"PROPOSTA", "PLANEJADA", "PREPARANDO", "EM_TESTE"}
        ]
        if active:
            return "outra proposta autonoma em execucao: " + ", ".join(active[:3])
        return ""

    def _worktree_paths(self) -> list[Path]:
        result = self._git(("worktree", "list", "--porcelain"), cwd=self.root, timeout=30)
        paths: list[Path] = []
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                paths.append(Path(line.removeprefix("worktree ")).resolve())
        return paths

    def _safe_head(self) -> str:
        try:
            return self.workspace.head()
        except RuntimeError:
            return "HEAD indisponivel"

    def _empty_operation_stats(self) -> dict[str, int]:
        return {
            "total": 0,
            "success": 0,
            "fail": 0,
            "inconclusive": 0,
            "rejected": 0,
            "cancelled": 0,
            "escalated": 0,
            "integrated": 0,
            "reverted": 0,
            "imported": 0,
            "first_attempt_success": 0,
            "production_real": 0,
            "test_fixture": 0,
            "legacy_import": 0,
            "manual_user": 0,
            "automatic_event": 0,
            "unknown": 0,
        }

    def _operation_stats(self, *, category: str = "", model: str = "") -> dict[str, dict[str, int]]:
        stats = {operation: self._empty_operation_stats() for operation in AUTONOMY_ALLOWED_OPERATIONS}
        for proposal in self.proposals.values():
            if model and proposal.model.lower() != model:
                continue
            operations = proposal.patch_manifest.get("operations", []) if isinstance(proposal.patch_manifest, dict) else []
            for operation in operations:
                op_type = str(operation.get("type", ""))
                if op_type not in stats:
                    continue
                if category and self._operation_category(op_type) != category:
                    continue
                item = stats[op_type]
                origin = self._proposal_origin(proposal)
                result = self._proposal_result_bucket(proposal)
                item["total"] += 1
                item[origin] += 1
                item[result] += 1
                if origin == "legacy_import":
                    item["imported"] += 1
                if result == "success":
                    if proposal.attempts <= 1:
                        item["first_attempt_success"] += 1
                if proposal.state == "INTEGRADA":
                    item["integrated"] += 1
                if proposal.state == "REVERTIDA":
                    item["reverted"] += 1
                if proposal.failure_reason.lower().find("codex") >= 0:
                    item["escalated"] += 1
        return stats

    def _operation_policy_status(self, operation: str, item: dict[str, int]) -> str:
        if operation not in AUTONOMY_ALLOWED_OPERATIONS:
            return "OPERACAO_NAO_SUPORTADA"
        versioned = self._versioned_operation_stats().get(operation, {})
        current = versioned.get("current", {})
        if current.get("fail", 0) or current.get("reverted", 0):
            return "BLOQUEADA_POR_FALHA_ATUAL"
        if item["fail"] and current.get("total", 0) < AUTONOMY_MIN_CASES:
            return "CALIBRACAO_NECESSARIA"
        if item["production_real"] < AUTONOMY_MIN_CASES or item["success"] < AUTONOMY_MIN_SUCCESSES:
            return "DADOS_INSUFICIENTES"
        if item["fail"] or item["escalated"]:
            return "BLOQUEADO_POR_FALHAS"
        return "ELEGIVEL"

    def _capability_level(self, operation: str, item: dict[str, int]) -> str:
        if item["total"] == 0:
            return "SEM_DADOS"
        versioned = self._versioned_operation_stats().get(operation, {})
        current = versioned.get("current", {})
        if current.get("fail", 0) or current.get("reverted", 0):
            return "BLOQUEADA_POR_FALHA_ATUAL"
        status = self._operation_policy_status(operation, item)
        if status == "CALIBRACAO_NECESSARIA":
            return "CALIBRACAO_NECESSARIA"
        if status == "DADOS_INSUFICIENTES":
            return "DADOS_INSUFICIENTES"
        if current.get("total", 0) >= 5 and current.get("success", 0) >= 4 and current.get("first_attempt_success", 0) >= 3 and not current.get("fail", 0):
            return "SUPORTADA_LOCALMENTE"
        if current.get("total", 0) >= 2 and current.get("success", 0) >= 1 and not current.get("fail", 0):
            return "EXPERIMENTAL"
        if item["reverted"] or item["escalated"]:
            return "ESCALONAMENTO_RECOMENDADO"
        return "CALIBRACAO_NECESSARIA"

    def _pipeline_generation(self, proposal: EngineeringProposal) -> str:
        pipeline = proposal.patch_pipeline_version or "legacy_unknown"
        schema = proposal.schema_version or "legacy_unknown"
        if pipeline == PATCH_PIPELINE_VERSION and schema == STRUCTURED_PATCH_SCHEMA_VERSION:
            return "CURRENT"
        if pipeline == "legacy_unknown":
            return "LEGACY_UNKNOWN"
        if "structured" in pipeline and schema != "legacy_unknown":
            return "STRUCTURED_PATCH_INITIAL"
        return "LEGACY_DIFF"

    def _versioned_operation_stats(self) -> dict[str, dict[str, dict[str, int]]]:
        def empty() -> dict[str, int]:
            return {
                "total": 0,
                "success": 0,
                "fail": 0,
                "inconclusive": 0,
                "integrated": 0,
                "reverted": 0,
                "first_attempt_success": 0,
            }

        stats = {operation: {"current": empty(), "legacy": empty(), "unknown": empty()} for operation in AUTONOMY_ALLOWED_OPERATIONS}
        for proposal in self.proposals.values():
            operations = proposal.patch_manifest.get("operations", []) if isinstance(proposal.patch_manifest, dict) else []
            generation = self._pipeline_generation(proposal)
            bucket = "current" if generation == "CURRENT" else ("unknown" if generation == "LEGACY_UNKNOWN" else "legacy")
            result = self._proposal_result_bucket(proposal)
            for operation in operations:
                op_type = str(operation.get("type", ""))
                if op_type not in stats:
                    continue
                item = stats[op_type][bucket]
                item["total"] += 1
                if result in item:
                    item[result] += 1
                if proposal.state == "INTEGRADA":
                    item["integrated"] += 1
                if proposal.state == "REVERTIDA":
                    item["reverted"] += 1
                if result == "success" and proposal.attempts <= 1:
                    item["first_attempt_success"] += 1
        for experiment in self.experiments.values():
            if experiment.operation_type not in stats:
                continue
            item = stats[experiment.operation_type]["current"]
            if experiment.evidence_strength in {"CALIBRACAO_VALIDADA", "APROVADA_PELO_USUARIO"}:
                item["total"] += 1
                item["success"] += 1
                if experiment.attempt <= 1:
                    item["first_attempt_success"] += 1
            elif experiment.state in {"FALHOU", "BLOQUEADO"}:
                item["total"] += 1
                item["fail"] += 1
        return stats

    def _experiment_record_sha(self, experiment: CalibrationExperiment) -> str:
        return self._sha_json({
            "experiment_id": experiment.experiment_id,
            "candidate_id": experiment.candidate_id,
            "proposal_id": experiment.proposal_id,
            "project_head": experiment.project_head,
            "file": experiment.file,
            "file_sha256": experiment.file_sha256,
            "operation_type": experiment.operation_type,
            "pipeline_version": experiment.pipeline_version,
            "schema_version": experiment.schema_version,
            "prompt_version": experiment.prompt_version,
            "state": experiment.state,
            "attempt": experiment.attempt,
            "result": experiment.result,
            "evidence_strength": experiment.evidence_strength,
        })

    def _proposal_origin(self, proposal: EngineeringProposal) -> str:
        text = " ".join([proposal.title, proposal.problem, " ".join(proposal.evidence), proposal.model]).lower()
        if "historico docstring" in text or "teste" in text or "aya tests" in text:
            return "test_fixture"
        if not proposal.patch_manifest or not proposal.patch_manifest.get("operations"):
            return "legacy_import"
        if any(event.get("action", "").startswith("autonomous_") for event in proposal.history):
            return "automatic_event"
        if proposal.approved_by == "local_user" or "aprovacao humana" in text:
            return "manual_user"
        if proposal.workspace_created and proposal.tests_executed:
            return "production_real"
        return "unknown"

    def _proposal_result_bucket(self, proposal: EngineeringProposal) -> str:
        if proposal.state in {"AGUARDANDO_APROVACAO", "APROVADA", "COMMIT_PRONTO", "INTEGRADA", "REVERTIDA"}:
            return "success"
        if proposal.state in {"FALHOU", "INTEGRACAO_BLOQUEADA", "REVERSAO_FALHOU", "REVERSAO_PARCIAL"}:
            return "fail"
        if proposal.state == "REJEITADA":
            return "rejected"
        if any(event.get("action") == "workspace isolado descartado" for event in proposal.history):
            return "cancelled"
        return "inconclusive"

    def _operation_category(self, operation_type: str) -> str:
        if operation_type == "insert_docstring":
            return "documentacao"
        if operation_type == "replace_exact":
            return "import_nao_usado"
        return "desconhecida"

    def _empty_candidate_scan_report(self) -> dict:
        return {
            "head": "",
            "files_scanned": 0,
            "files_reused": 0,
            "files_changed": 0,
            "files_removed": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "full_scan": True,
            "scan_duration_ms": 0,
            "ruff_calls": 0,
            "index_builds": 0,
            "capacity_calculations": 0,
            "ruff_version": "",
            "ruff_diagnostics": 0,
            "raw_detected": 0,
            "hard_exclusions": {},
        }

    def _load_candidate_cache(self) -> dict:
        try:
            raw = json.loads(self.candidate_cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save_candidate_cache(self, cache: dict) -> None:
        self.candidate_cache_path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(cache, ensure_ascii=True, indent=2, sort_keys=True)
        self.candidate_cache_path.write_text(self.workspace.sanitize(text, max(len(text), 5000000)), encoding="utf-8")

    def _candidate_from_dict(self, raw: dict, *, head: str) -> AutonomousCandidate | None:
        if not isinstance(raw, dict):
            return None
        allowed = set(AutonomousCandidate.__dataclass_fields__)
        data = {key: raw.get(key) for key in allowed if key in raw}
        missing = [key for key in allowed if key not in data]
        if missing:
            return None
        data["project_head"] = head
        data["deduplication_key"] = self._candidate_dedup_key(
            head,
            str(data.get("operation_type", "")),
            str(data.get("file", "")),
            str(data.get("symbol", "")),
            str(data.get("expected_change", "")),
        )
        data["record_sha256"] = self._sha_json({
            "source": data.get("source", ""),
            "operation_type": data.get("operation_type", ""),
            "file": data.get("file", ""),
            "symbol": data.get("symbol", ""),
            "expected_change": data.get("expected_change", ""),
            "head": head,
            "file_sha256": data.get("file_sha256", ""),
            "deduplication_key": data["deduplication_key"],
            "schema": AUTONOMY_CANDIDATE_SCHEMA_VERSION,
        })
        return AutonomousCandidate(**data)

    def _candidate_cache_compatible(self, cache: dict, *, ruff_version: str) -> bool:
        return (
            cache.get("root") == str(self.root)
            and cache.get("policy_version") == AUTONOMY_POLICY_VERSION
            and cache.get("qualification_version") == AUTONOMY_QUALIFICATION_VERSION
            and cache.get("schema_version") == AUTONOMY_CANDIDATE_SCHEMA_VERSION
            and cache.get("analyzer_version") == AUTONOMY_ANALYZER_VERSION
            and cache.get("ruff_version") == ruff_version
        )

    def _record_candidate_exclusion(self, reason: str) -> None:
        normalized = re.sub(r"[^A-Z0-9_]+", "_", reason.upper()).strip("_") or "UNKNOWN"
        self._candidate_exclusion_counts[normalized] = self._candidate_exclusion_counts.get(normalized, 0) + 1

    def _merge_candidate_exclusions(self, counts: dict) -> None:
        if not isinstance(counts, dict):
            return
        for key, value in counts.items():
            try:
                amount = int(value)
            except (TypeError, ValueError):
                continue
            if amount > 0:
                self._candidate_exclusion_counts[str(key)] = self._candidate_exclusion_counts.get(str(key), 0) + amount

    def _ruff_version(self) -> str:
        result = self.workspace._run(("python", "-m", "ruff", "--version"), self.root, 60)
        if result.returncode != 0:
            return "ruff-indisponivel"
        return result.stdout.strip() or "ruff-versao-desconhecida"

    def _ruff_f401_diagnostics(self, ruff_version: str) -> dict[str, list[dict]]:
        if ruff_version == "ruff-indisponivel":
            return {}
        result = self.workspace._run(
            ("python", "-m", "ruff", "check", ".", "--select", "F401", "--output-format", "json"),
            self.root,
            180,
        )
        if result.returncode not in {0, 1}:
            return {}
        try:
            diagnostics = json.loads(result.stdout or "[]")
        except ValueError:
            return {}
        grouped: dict[str, list[dict]] = {}
        for item in diagnostics if isinstance(diagnostics, list) else []:
            if item.get("code") != "F401":
                continue
            filename = str(item.get("filename", ""))
            path = Path(filename)
            rel = self._relative_to_root(path if path.is_absolute() else self.root / path)
            location = item.get("location") or {}
            diagnostic = {
                "code": "F401",
                "file": rel,
                "line": int(location.get("row") or 0),
                "column": int(location.get("column") or 0),
                "message": str(item.get("message", "")),
                "fix": item.get("fix") or {},
                "ruff_version": ruff_version,
            }
            diagnostic["diagnostic_sha256"] = self._sha_json(diagnostic)
            grouped.setdefault(rel, []).append(diagnostic)
        return grouped

    def _relative_to_root(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    def _autonomous_candidates(self, *, force: bool = False) -> list[AutonomousCandidate]:
        started = time.perf_counter()
        head = self._safe_head()
        proposal_count = len(self.proposals)
        if (
            not force
            and self._candidate_cache is not None
            and self._candidate_cache_head == head
            and self._candidate_cache_proposals == proposal_count
        ):
            self._candidate_scan_report["scan_duration_ms"] = int((time.perf_counter() - started) * 1000)
            return self._validate_candidate_list(self._candidate_cache, head=head)
        report = self._empty_candidate_scan_report()
        report["head"] = head
        ruff_version = self._ruff_version()
        report["ruff_version"] = ruff_version
        persistent_cache = self._load_candidate_cache()
        compatible_cache = self._candidate_cache_compatible(persistent_cache, ruff_version=ruff_version)
        cached_files = persistent_cache.get("files", {}) if compatible_cache else {}
        report["full_scan"] = not compatible_cache
        report["ruff_calls"] = 1
        ruff = self._ruff_f401_diagnostics(ruff_version)
        report["ruff_diagnostics"] = sum(len(items) for items in ruff.values())
        report["index_builds"] = 1
        entries = self.index.build()
        stats = self._operation_stats()
        report["capacity_calculations"] = 1
        entries_by_path = {entry.path: entry for entry in entries}
        current_paths = set(entries_by_path)
        cached_paths = set(cached_files) if isinstance(cached_files, dict) else set()
        report["files_removed"] = len(cached_paths - current_paths)
        file_cache: dict[str, dict] = {}
        candidates: list[AutonomousCandidate] = []
        self._candidate_exclusion_counts = {}
        for entry in entries:
            if entry.path.startswith("tests/") or self._candidate_path_blocked(entry.path):
                self._record_candidate_exclusion("TEST_FILE" if entry.path.startswith("tests/") else "PROTECTED_FILE")
                continue
            before_exclusions = dict(self._candidate_exclusion_counts)
            cached = cached_files.get(entry.path, {}) if isinstance(cached_files, dict) else {}
            ruff_key = self._sha_json(ruff.get(entry.path, []))
            can_reuse = (
                compatible_cache
                and cached.get("sha256") == entry.sha256
                and cached.get("ruff_key") == ruff_key
            )
            if can_reuse:
                reused: list[AutonomousCandidate] = []
                for raw in cached.get("candidates", []):
                    candidate = self._candidate_from_dict(raw, head=head)
                    if candidate:
                        reused.append(candidate)
                candidates.extend(reused)
                file_cache[entry.path] = cached
                self._merge_candidate_exclusions(cached.get("hard_exclusions", {}))
                report["files_reused"] += 1
                report["cache_hits"] += 1
                continue
            report["files_scanned"] += 1
            report["files_changed"] += 1 if cached else 0
            report["cache_misses"] += 1
            file_candidates = [
                *self._docstring_candidates(entry, stats, entries),
                *self._unused_import_candidates(entry, stats, ruff.get(entry.path, []), ruff_version),
            ]
            file_exclusions = {
                key: value - before_exclusions.get(key, 0)
                for key, value in self._candidate_exclusion_counts.items()
                if value - before_exclusions.get(key, 0) > 0
            }
            candidates.extend(file_candidates)
            file_cache[entry.path] = {
                "sha256": entry.sha256,
                "ruff_key": ruff_key,
                "candidates": [asdict(candidate) for candidate in file_candidates],
                "hard_exclusions": dict(sorted(file_exclusions.items())),
            }
        report["hard_exclusions"] = dict(sorted(self._candidate_exclusion_counts.items()))
        report["raw_detected"] = len(candidates) + sum(report["hard_exclusions"].values())
        self._save_candidate_cache({
            "root": str(self.root),
            "head": head,
            "policy_version": AUTONOMY_POLICY_VERSION,
            "qualification_version": AUTONOMY_QUALIFICATION_VERSION,
            "schema_version": AUTONOMY_CANDIDATE_SCHEMA_VERSION,
            "analyzer_version": AUTONOMY_ANALYZER_VERSION,
            "ruff_version": ruff_version,
            "last_scan_report": report,
            "files": file_cache,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        })
        report["scan_duration_ms"] = int((time.perf_counter() - started) * 1000)
        self._candidate_scan_report = report
        self._candidate_cache = candidates
        self._candidate_cache_head = head
        self._candidate_cache_proposals = proposal_count
        return self._validate_candidate_list(candidates, head=head)

    def _validate_candidate_list(self, candidates: list[AutonomousCandidate], *, head: str | None = None) -> list[AutonomousCandidate]:
        seen: dict[str, AutonomousCandidate] = {}
        deduplicated: list[AutonomousCandidate] = []
        current_hashes: dict[str, str] = {}
        head = head or self._safe_head()
        for candidate in candidates:
            candidate = self._validate_current_candidate(candidate, current_hashes=current_hashes, head=head)
            if candidate.deduplication_key in seen:
                duplicate = self._replace_candidate_status(
                    candidate,
                    "BLOQUEADO",
                    ["DUPLICADO"],
                    route="CODEX_REVIEW_RECOMMENDED",
                    reason_codes=["DUPLICATE_CURRENT_CANDIDATE"],
                )
                deduplicated.append(duplicate)
                continue
            seen[candidate.deduplication_key] = candidate
            deduplicated.append(candidate)
        deduplicated.sort(key=lambda item: (-item.priority_score, -item.documentation_value_score, item.risk, len(item.files), item.estimated_changed_lines, item.candidate_id))
        return deduplicated

    def _docstring_candidates(
        self,
        entry: TechnicalFile,
        stats: dict[str, dict[str, int]],
        all_entries: list[TechnicalFile],
    ) -> list[AutonomousCandidate]:
        path = self.root / entry.path
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            tree = ast.parse(text)
        except (OSError, SyntaxError):
            return []
        parents = self._ast_parents(tree)
        lines = text.splitlines()
        candidates: list[AutonomousCandidate] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            symbol = self._qualified_symbol(tree, node, parents)
            if not symbol:
                continue
            qualification = self._qualify_docstring_candidate(entry, node, symbol, parents, lines, all_entries)
            hard_exclusions = {
                "DOCSTRING_EXISTS",
                "TEST_FILE",
                "PRIVATE_SYMBOL",
                "DUNDER_SYMBOL",
                "INIT_TRIVIAL",
                "GETTER_SETTER_TRIVIAL",
                "TRIVIAL_BODY",
                "NESTED_SYMBOL",
            }
            if hard_exclusions & set(qualification["reason_codes"]):
                for reason_code in sorted(hard_exclusions & set(qualification["reason_codes"])):
                    self._record_candidate_exclusion(reason_code)
                continue
            candidates.append(self._build_candidate(
                source="ast:missing_docstring",
                title=f"Adicionar docstring em {symbol}",
                problem=f"O simbolo {symbol} nao possui docstring explicita.",
                evidence=[f"{entry.path}:{node.lineno} sem docstring", f"Indice AST confirmou {entry.path}."],
                category="documentacao",
                operation_type="insert_docstring",
                files=[entry.path],
                symbols=[symbol],
                estimated_changed_lines=1,
                required_tests=entry.related_tests[:2],
                reason="docstring ausente no HEAD atual",
                expected_change=f"inserir docstring em {symbol}",
                symbol_signature=self._signature_for_symbol(entry, symbol),
                stats=stats,
                qualification=qualification,
                ruff_diagnostic={},
                file_sha256=entry.sha256,
            ))
        return candidates

    def _unused_import_candidates(
        self,
        entry: TechnicalFile,
        stats: dict[str, dict[str, int]],
        diagnostics: list[dict],
        ruff_version: str,
    ) -> list[AutonomousCandidate]:
        path = self.root / entry.path
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            return []
        candidates: list[AutonomousCandidate] = []
        text_lines = text.splitlines()
        for diagnostic in diagnostics:
            line_number = int(diagnostic.get("line") or 0)
            if line_number <= 0 or line_number > len(text_lines):
                continue
            line = text_lines[line_number - 1]
            qualification = self._qualify_ruff_f401_candidate(entry, text, line, diagnostic, ruff_version)
            for reason_code in ("NOQA_IMPORT", "TYPE_CHECKING_IMPORT", "POSSIBLE_REEXPORT", "SIDE_EFFECT_IMPORT"):
                if reason_code in qualification["reason_codes"]:
                    self._record_candidate_exclusion(reason_code)
            candidates.append(self._build_candidate(
                source="ruff:F401",
                title=f"Remover import nao usado em {entry.path}:{line_number}",
                problem=diagnostic.get("message", "Ruff F401 confirmou import nao usado."),
                evidence=[f"{entry.path}:{line_number} F401 confirmado por Ruff", diagnostic.get("diagnostic_sha256", "")],
                category="import_nao_usado",
                operation_type="replace_exact",
                files=[entry.path],
                symbols=[],
                estimated_changed_lines=1,
                required_tests=entry.related_tests[:2],
                reason="Ruff F401 confirmou import nao utilizado",
                expected_change=f"remover linha exata: {line.strip()}",
                symbol_signature="",
                stats=stats,
                qualification=qualification,
                ruff_diagnostic=diagnostic,
                file_sha256=entry.sha256,
            ))
        return candidates

    def _qualify_docstring_candidate(
        self,
        entry: TechnicalFile,
        node: ast.AST,
        symbol: str,
        parents: dict[ast.AST, ast.AST],
        lines: list[str],
        all_entries: list[TechnicalFile],
    ) -> dict:
        reason_codes: list[str] = []
        value_reasons: list[str] = []
        if entry.path.startswith("tests/"):
            reason_codes.append("TEST_FILE")
        if ast.get_docstring(node):
            reason_codes.append("DOCSTRING_EXISTS")
        name = getattr(node, "name", "")
        if name == "__init__":
            reason_codes.append("INIT_TRIVIAL")
        elif name.startswith("__") and name.endswith("__"):
            reason_codes.append("DUNDER_SYMBOL")
        elif name.startswith("_"):
            reason_codes.append("PRIVATE_SYMBOL")
        if self._is_nested_symbol(node, parents):
            reason_codes.append("NESTED_SYMBOL")
        body_lines = max((getattr(node, "end_lineno", getattr(node, "lineno", 1)) or 1) - (getattr(node, "lineno", 1) or 1) + 1, 1)
        if body_lines <= 1:
            reason_codes.append("TRIVIAL_BODY")
        if self._is_trivial_getter_setter(node):
            reason_codes.append("GETTER_SETTER_TRIVIAL")
        if not any(code in reason_codes for code in {"PRIVATE_SYMBOL", "DUNDER_SYMBOL", "INIT_TRIVIAL", "GETTER_SETTER_TRIVIAL", "TRIVIAL_BODY", "NESTED_SYMBOL"}):
            reason_codes.append("PUBLIC_SYMBOL")
        if body_lines >= AUTONOMY_MIN_DOCSTRING_LINES:
            reason_codes.append("PUBLIC_NONTRIVIAL_SYMBOL")
            value_reasons.append(f"linhas={body_lines}")
        external_refs = self._external_symbol_references(entry.path, name, all_entries)
        if external_refs:
            reason_codes.append("EXTERNALLY_REFERENCED")
            value_reasons.append(f"referencias_externas={external_refs}")
        branches = sum(isinstance(child, (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.Match, ast.BoolOp)) for child in ast.walk(node))
        if branches:
            reason_codes.append("MULTI_BRANCH_BODY")
            value_reasons.append(f"caminhos={branches}")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            params = [arg.arg for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs] if arg.arg not in {"self", "cls"}]
            if params:
                reason_codes.append("PARAMETERS_NONTRIVIAL")
                value_reasons.append(f"parametros={len(params)}")
            if any(isinstance(child, ast.Return) and child.value is not None for child in ast.walk(node)):
                reason_codes.append("RETURNS_VALUE")
                value_reasons.append("retorno=sim")
        if any(isinstance(child, ast.Raise) for child in ast.walk(node)):
            reason_codes.append("RAISES_EXCEPTION")
            value_reasons.append("excecao=sim")
        if entry.related_tests:
            reason_codes.append("HAS_RELATED_TESTS")
            value_reasons.append("testes=sim")
        if entry.path.startswith("aya/core/"):
            reason_codes.append("CENTRAL_MODULE")
            value_reasons.append("modulo_central=sim")
        if any(term in f"{entry.path} {symbol}".lower() for term in ("security", "permission", "database", "sqlite", "memory", "backup", "rag", "auth", "token")):
            reason_codes.append("TECHNICAL_RESPONSIBILITY")
            value_reasons.append("responsabilidade_tecnica=sim")
        value_score = self._documentation_value_score(reason_codes, body_lines)
        if value_score < 25:
            reason_codes.append("LOW_TECHNICAL_VALUE")
        if any(code in reason_codes for code in {"PRIVATE_SYMBOL", "DUNDER_SYMBOL", "INIT_TRIVIAL", "GETTER_SETTER_TRIVIAL", "TRIVIAL_BODY", "NESTED_SYMBOL", "LOW_TECHNICAL_VALUE"}):
            qualification = "INFORMATIVO"
            relevance_valid = "LOW_TECHNICAL_VALUE" not in reason_codes
            actionable = False
        elif value_score >= 55 and ("EXTERNALLY_REFERENCED" in reason_codes or "TECHNICAL_RESPONSIBILITY" in reason_codes):
            qualification = "ACAO_RECOMENDADA"
            relevance_valid = True
            actionable = True
        else:
            qualification = "MANUTENCAO_OPCIONAL"
            relevance_valid = True
            actionable = False
        return {
            "detection_valid": True,
            "relevance_valid": relevance_valid,
            "actionable": actionable,
            "qualification_status": qualification,
            "qualification_reasons": reason_codes,
            "documentation_value_score": value_score,
            "documentation_value_reasons": value_reasons or ["sem_sinal_forte"],
            "reason_codes": reason_codes,
        }

    def _qualify_ruff_f401_candidate(self, entry: TechnicalFile, text: str, line: str, diagnostic: dict, ruff_version: str) -> dict:
        reason_codes = ["RUFF_F401_CONFIRMED"]
        if "# noqa" in line.lower():
            reason_codes.append("NOQA_IMPORT")
        if "if TYPE_CHECKING" in text or "typing import TYPE_CHECKING" in text:
            reason_codes.append("TYPE_CHECKING_IMPORT")
        if entry.path.endswith("__init__.py") or "__all__" in text:
            reason_codes.append("POSSIBLE_REEXPORT")
        stripped = line.strip()
        if stripped.startswith("import ") and " as " not in stripped and "." not in stripped:
            reason_codes.append("SIDE_EFFECT_IMPORT")
        blocked = any(code in reason_codes for code in {"NOQA_IMPORT", "TYPE_CHECKING_IMPORT", "POSSIBLE_REEXPORT", "SIDE_EFFECT_IMPORT"})
        return {
            "detection_valid": True,
            "relevance_valid": True,
            "actionable": not blocked,
            "qualification_status": "MANUTENCAO_OPCIONAL" if not blocked else "BLOQUEADO",
            "qualification_reasons": reason_codes,
            "documentation_value_score": 0,
            "documentation_value_reasons": [f"ruff={ruff_version}", diagnostic.get("diagnostic_sha256", "")],
            "reason_codes": reason_codes,
        }

    def _documentation_value_score(self, reason_codes: list[str], body_lines: int) -> int:
        weights = {
            "PUBLIC_NONTRIVIAL_SYMBOL": 20,
            "EXTERNALLY_REFERENCED": 30,
            "MULTI_BRANCH_BODY": 15,
            "PARAMETERS_NONTRIVIAL": 10,
            "RETURNS_VALUE": 10,
            "RAISES_EXCEPTION": 12,
            "HAS_RELATED_TESTS": 10,
            "CENTRAL_MODULE": 8,
            "TECHNICAL_RESPONSIBILITY": 20,
        }
        score = min(body_lines, 40)
        return score + sum(weights.get(code, 0) for code in set(reason_codes))

    def _is_nested_symbol(self, node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
        parent = parents.get(node)
        while parent is not None:
            if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return True
            parent = parents.get(parent)
        return False

    def _is_trivial_getter_setter(self, node: ast.AST) -> bool:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return False
        body = [item for item in node.body if not isinstance(item, ast.Expr) or not isinstance(getattr(item, "value", None), ast.Constant)]
        if len(body) != 1:
            return False
        item = body[0]
        if isinstance(item, ast.Return) and isinstance(item.value, ast.Attribute):
            return True
        if isinstance(item, ast.Assign) and len(item.targets) == 1:
            return True
        return False

    def _external_symbol_references(self, current_file: str, name: str, entries: list[TechnicalFile]) -> int:
        if not name:
            return 0
        needle = name.lower()
        return sum(1 for entry in entries if entry.path != current_file and needle in {call.lower() for call in entry.calls})

    def _build_candidate(
        self,
        *,
        source: str,
        title: str,
        problem: str,
        evidence: list[str],
        category: str,
        operation_type: str,
        files: list[str],
        symbols: list[str],
        estimated_changed_lines: int,
        required_tests: list[str],
        reason: str,
        expected_change: str,
        symbol_signature: str,
        stats: dict[str, dict[str, int]],
        qualification: dict,
        ruff_diagnostic: dict,
        file_sha256: str,
    ) -> AutonomousCandidate:
        head = self._safe_head()
        file_sha256 = file_sha256 or (self._file_sha256(files[0]) if files else "")
        symbol = symbols[0] if symbols else ""
        risk = self.classify_risk(problem, files, title)
        lessons = self._candidate_lessons(files, operation_type)
        similar = self._similar_proposals(files, symbols)
        blocked = self._candidate_blocked_reasons(files, category, operation_type, risk, estimated_changed_lines)
        operation_stats = self._empty_operation_stats() | stats.get(operation_type, {})
        policy = self._operation_policy_status(operation_type, operation_stats)
        reason_codes = list(dict.fromkeys(qualification.get("reason_codes", [])))
        semantic = self._semantic_safety(files[0], symbol)
        reason_codes.extend(semantic.reason_codes)
        if policy != "ELEGIVEL" and not blocked:
            blocked.append(policy)
        if policy == "DADOS_INSUFICIENTES":
            reason_codes.append("CAPABILITY_INSUFFICIENT")
        if policy == "CALIBRACAO_NECESSARIA":
            reason_codes.append("CALIBRATION_REQUIRED")
            if self._is_calibration_candidate_shape(qualification, files, risk, estimated_changed_lines):
                reason_codes.append("CALIBRATION_ALLOWED")
        if policy == "BLOQUEADA_POR_FALHA_ATUAL":
            reason_codes.append("CURRENT_PIPELINE_FAILURE")
        if policy == "BLOQUEADO_POR_FALHAS":
            reason_codes.append("LEGACY_PIPELINE_FAILURE")
        if risk != "baixo":
            reason_codes.append("HIGH_RISK_MODULE")
        if any(reason.startswith("ARQUIVO_BLOQUEADO") for reason in blocked):
            reason_codes.append("FILE_BLOCKED")
        if not qualification.get("actionable", False) and qualification.get("qualification_status") != "BLOQUEADO":
            blocked.append("NAO_ACIONAVEL")
        eligibility = "ELEGIVEL" if not blocked else ("DADOS_INSUFICIENTES" if blocked == ["DADOS_INSUFICIENTES"] else "BLOQUEADO")
        score, score_explanation = self._candidate_score(
            evidence=evidence,
            required_tests=required_tests,
            stats=operation_stats,
            files=files,
            changed_lines=estimated_changed_lines,
            blocked=blocked,
        )
        priority_score, priority_reasons = self._candidate_priority_score(
            qualification=qualification,
            stats=operation_stats,
            risk=risk,
            blocked=blocked,
            required_tests=required_tests,
        )
        deduplication_key = self._candidate_dedup_key(head, operation_type, files[0], symbol, expected_change)
        route = self._route_from_candidate_state(eligibility, blocked, risk, operation_type, operation_stats, stale=False)
        final_status = qualification.get("qualification_status", "INFORMATIVO")
        raw = {
            "source": source,
            "title": title,
            "problem": problem,
            "evidence": evidence,
            "category": category,
            "operation_type": operation_type,
            "files": files,
            "symbols": symbols,
            "estimated_changed_lines": estimated_changed_lines,
            "policy_version": AUTONOMY_POLICY_VERSION,
            "head": head,
            "file_sha256": file_sha256,
            "symbol_signature": symbol_signature,
            "deduplication_key": deduplication_key,
            "qualification_status": qualification.get("qualification_status", ""),
            "priority_score": priority_score,
            "schema": AUTONOMY_CANDIDATE_SCHEMA_VERSION,
        }
        digest = self._sha_json(raw)
        return AutonomousCandidate(
            candidate_id=f"AUTO-{digest[:12].upper()}",
            detected_at=datetime.now().isoformat(timespec="seconds"),
            generated_at=datetime.now().isoformat(timespec="seconds"),
            project_head=head,
            source=source,
            source_origin="production_real",
            title=title,
            problem=problem,
            evidence=evidence,
            category=category,
            operation_type=operation_type,
            file=files[0],
            file_sha256=file_sha256,
            symbol=symbol,
            symbol_signature=symbol_signature,
            reason=reason,
            expected_change=expected_change,
            allowed_files=files,
            files=files,
            symbols=symbols,
            estimated_changed_lines=estimated_changed_lines,
            risk=risk,
            required_tests=required_tests,
            confidence="baseada em evidencias locais" if eligibility == "ELEGIVEL" else "limitada",
            detection_valid=bool(qualification.get("detection_valid", True)),
            relevance_valid=bool(qualification.get("relevance_valid", False)),
            actionable=bool(qualification.get("actionable", False)),
            qualification_status=str(qualification.get("qualification_status", "INFORMATIVO")),
            qualification_reasons=list(qualification.get("qualification_reasons", reason_codes)),
            documentation_value_score=int(qualification.get("documentation_value_score", 0)),
            documentation_value_reasons=list(qualification.get("documentation_value_reasons", [])),
            priority_score=priority_score,
            priority_reasons=priority_reasons,
            reason_codes=list(dict.fromkeys(reason_codes)),
            ruff_diagnostic=ruff_diagnostic,
            status=final_status,
            eligibility=eligibility,
            blocked_reasons=blocked,
            related_lessons=lessons,
            similar_proposals=similar,
            policy_version=AUTONOMY_POLICY_VERSION,
            score=score,
            score_explanation=score_explanation,
            deduplication_key=deduplication_key,
            stale=False,
            stale_reason="",
            route=route,
            record_sha256=digest,
        )

    def _candidate_blocked_reasons(
        self,
        files: list[str],
        category: str,
        operation_type: str,
        risk: str,
        estimated_changed_lines: int,
    ) -> list[str]:
        reasons: list[str] = []
        if operation_type not in AUTONOMY_ALLOWED_OPERATIONS:
            reasons.append("OPERACAO_NAO_SUPORTADA")
        if risk != "baixo":
            reasons.append(f"RISCO_{risk.upper()}")
        if len(files) > 2:
            reasons.append("MAIS_DE_DOIS_ARQUIVOS")
        if estimated_changed_lines > 80:
            reasons.append("MAIS_DE_80_LINHAS")
        if category not in {"documentacao", "mensagem_tecnica", "teste_caracterizacao", "import_nao_usado"}:
            reasons.append("CATEGORIA_DESCONHECIDA")
        for file in files:
            if self._candidate_path_blocked(file):
                reasons.append(f"ARQUIVO_BLOQUEADO:{file}")
                break
        return reasons

    def _is_calibration_candidate_shape(
        self,
        qualification: dict,
        files: list[str],
        risk: str,
        estimated_changed_lines: int,
    ) -> bool:
        return (
            qualification.get("qualification_status") == "ACAO_RECOMENDADA"
            and bool(qualification.get("actionable", False))
            and risk == "baixo"
            and len(files) == 1
            and estimated_changed_lines <= 20
        )

    def _calibration_candidate_allowed(self, candidate: AutonomousCandidate) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        semantic = self._semantic_safety(candidate.file, candidate.symbol)
        if candidate.stale:
            reasons.append("candidato obsoleto")
        if candidate.project_head != self._safe_head():
            reasons.append("HEAD mudou desde a deteccao")
        if candidate.qualification_status != "ACAO_RECOMENDADA":
            reasons.append("candidato nao e acao recomendada")
        if not candidate.actionable:
            reasons.append("candidato nao acionavel")
        if candidate.risk != "baixo":
            reasons.append(f"risco {candidate.risk}")
        if len(candidate.files) != 1:
            reasons.append("experimento aceita exatamente um arquivo")
        if candidate.estimated_changed_lines > 20:
            reasons.append("mudanca estimada acima de 20 linhas")
        if candidate.estimated_changed_lines > 10:
            reasons.append("primeira calibracao aceita no maximo 10 linhas")
        if candidate.operation_type not in AUTONOMY_ALLOWED_OPERATIONS:
            reasons.append("operacao nao suportada")
        if self._candidate_path_blocked(candidate.file):
            reasons.append("arquivo protegido ou fora do projeto")
        absolute_blocks = {
            "OPERACAO_NAO_SUPORTADA",
            "MAIS_DE_DOIS_ARQUIVOS",
            "MAIS_DE_80_LINHAS",
            "CATEGORIA_DESCONHECIDA",
            "NAO_ACIONAVEL",
        }
        if any(
            reason.startswith("RISCO_")
            or reason.startswith("ARQUIVO_BLOQUEADO")
            or reason in absolute_blocks
            for reason in candidate.blocked_reasons
        ):
            reasons.append("bloqueio absoluto de politica")
        if "CURRENT_PIPELINE_FAILURE" in candidate.reason_codes or "BLOQUEADA_POR_FALHA_ATUAL" in candidate.blocked_reasons:
            reasons.append("falha registrada no pipeline atual")
        if semantic.sensitivity != "LOW":
            reasons.append(f"sensibilidade {semantic.sensitivity} bloqueada")
        if semantic.responsibility not in CALIBRATION_ALLOWED_RESPONSIBILITIES:
            reasons.append(f"responsabilidade {semantic.responsibility} bloqueada")
        if semantic.block_reasons:
            reasons.extend(semantic.block_reasons)
        if not any(
            code in candidate.reason_codes
            for code in {"CALIBRATION_REQUIRED", "CALIBRATION_ALLOWED", "CAPABILITY_INSUFFICIENT", "LEGACY_PIPELINE_FAILURE"}
        ):
            reasons.append("candidato nao representa lacuna de calibracao")
        try:
            current = self._validate_current_candidate(candidate)
        except (OSError, RuntimeError, ValueError):
            reasons.append("validacao atual indisponivel")
        else:
            if current.stale:
                reasons.append(current.stale_reason or "candidato nao esta atual")
        return not reasons, list(dict.fromkeys(reasons))

    def _semantic_safety(self, file: str, symbol: str) -> SemanticSafety:
        text = self._semantic_text(file, symbol)
        tokens = set(re.findall(r"[a-zA-Z_][\w]*", text.lower()))
        relevant_calls = self._relevant_symbol_calls(file, symbol)
        call_text = " ".join(relevant_calls).lower()
        reason_codes: list[str] = []
        block_reasons: list[str] = []
        responsibility = "UNKNOWN_SENSITIVE"
        sensitivity = "GUARDED"

        if self._calibration_file_blocked(file):
            reason_codes.append("CENTRAL_APPLICATION_FILE")
            reason_codes.append("CALIBRATION_MODULE_BLOCKED")
            block_reasons.append("modulo central bloqueado para primeira calibracao")
            responsibility = "APPLICATION_BOOTSTRAP" if file == "app.py" else "AUTONOMY_CONTROL"
            sensitivity = "CRITICAL"

        if {"auth", "authentication", "login", "password", "token"} & tokens:
            reason_codes.append("AUTHENTICATION_SYMBOL")
            block_reasons.append("autenticacao ou credenciais")
            responsibility = "AUTHENTICATION"
            sensitivity = "CRITICAL"
        if {"authorization", "permission", "permissions", "access", "allows", "capability"} & tokens:
            reason_codes.append("AUTHORIZATION_SYMBOL")
            block_reasons.append("autorizacao ou permissoes")
            responsibility = "AUTHORIZATION"
            sensitivity = "CRITICAL"
        if {"remote", "tailscale", "network", "host", "bind", "server"} & tokens:
            reason_codes.append("REMOTE_ACCESS_SYMBOL")
            block_reasons.append("acesso remoto ou rede")
            responsibility = "REMOTE_ACCESS"
            sensitivity = "CRITICAL"
        if {"launch", "server_name", "server_port", "gradio", "blocks", "create_app"} & tokens and file == "app.py":
            reason_codes.append("SERVER_LAUNCH_CONFIGURATION")
            block_reasons.append("bootstrap ou configuracao de servidor")
            if responsibility not in {"AUTHENTICATION", "AUTHORIZATION", "REMOTE_ACCESS"}:
                responsibility = "APPLICATION_BOOTSTRAP"
            sensitivity = "CRITICAL"
        if {"memory", "memoria", "engineering_memory", "register_engineering_memory", "persistence", "storage"} & tokens:
            code = "TECHNICAL_MEMORY_PERSISTENCE" if "engineering" in text.lower() else "PERSONAL_MEMORY_PERSISTENCE"
            reason_codes.append(code)
            block_reasons.append("memoria ou persistencia")
            responsibility = "TECHNICAL_MEMORY" if code == "TECHNICAL_MEMORY_PERSISTENCE" else "PERSONAL_MEMORY"
            sensitivity = "CRITICAL"
        if {"cache", "index", "read_bytes", "write_text", "read_text", "mkdir", "replace", "stat", "_save"} & tokens:
            reason_codes.append("UNKNOWN_SIDE_EFFECTS")
            block_reasons.append("indice, cache ou efeito de arquivo")
            if responsibility not in {"AUTHENTICATION", "AUTHORIZATION", "REMOTE_ACCESS", "TECHNICAL_MEMORY", "PERSONAL_MEMORY"}:
                responsibility = "PERSISTENCE"
            sensitivity = max(sensitivity, "SENSITIVE", key=self._sensitivity_rank)
        if {"database", "sqlite", "schema", "migration", "db"} & tokens:
            reason_codes.append("TECHNICAL_MEMORY_PERSISTENCE")
            block_reasons.append("banco de dados ou schema")
            responsibility = "DATABASE"
            sensitivity = "CRITICAL"
        if {"autonomy", "autonomous", "candidate", "calibration", "experiment", "approval", "integration"} & tokens:
            reason_codes.append("AUTONOMY_CONTROL_PLANE")
            block_reasons.append("plano de controle da autonomia")
            responsibility = "AUTONOMY_CONTROL"
            sensitivity = "CRITICAL"
        if {"git", "worktree", "commit", "merge", "revert", "branch"} & tokens or re.search(r"\bgit\b", call_text):
            reason_codes.append("GIT_CONTROL_PLANE")
            block_reasons.append("controle Git ou worktree")
            responsibility = "GIT_CONTROL"
            sensitivity = "CRITICAL"
        if {"structured_patch", "patch", "manifest", "risk_policy"} & tokens:
            reason_codes.append("PATCH_PIPELINE_CONTROL")
            block_reasons.append("pipeline de patch")
            responsibility = "PATCH_PIPELINE"
            sensitivity = "CRITICAL"
        if {"release", "validation", "validate", "smoke", "compileall", "ruff"} & tokens:
            reason_codes.append("RELEASE_CONTROL_PLANE")
            block_reasons.append("release ou validacao global")
            responsibility = "RELEASE_CONTROL"
            sensitivity = max(sensitivity, "SENSITIVE", key=self._sensitivity_rank)
        if {"subprocess", "system", "popen", "shell", "command"} & tokens or any(call in call_text for call in ("subprocess", "os.system", "_run", "subprocess.run")):
            reason_codes.append("COMMAND_EXECUTION_PATH")
            block_reasons.append("execucao de comandos")
            responsibility = "COMMAND_EXECUTION"
            sensitivity = "CRITICAL"
        if {"open", "write_text", "read_text", "replace", "unlink", "mkdir", "json", "dump"} & tokens and responsibility == "UNKNOWN_SENSITIVE":
            reason_codes.append("UNKNOWN_SIDE_EFFECTS")
            block_reasons.append("efeito colateral de arquivo ou serializacao")
            responsibility = "PERSISTENCE"
            sensitivity = "SENSITIVE"

        if responsibility == "UNKNOWN_SENSITIVE":
            if self._looks_read_only(file, symbol):
                responsibility = "READ_ONLY_QUERY"
                sensitivity = "LOW"
                reason_codes.append("SAFE_READ_ONLY_QUERY")
            elif self._looks_pure_utility(file, symbol):
                responsibility = "PURE_UTILITY"
                sensitivity = "LOW"
                reason_codes.append("SAFE_PURE_UTILITY")
            elif file.endswith(".py") and symbol:
                responsibility = "DOCUMENTATION_ONLY"
                sensitivity = "LOW"
                reason_codes.append("SAFE_DOCUMENTATION_TARGET")
            else:
                reason_codes.append("UNKNOWN_SIDE_EFFECTS")
                block_reasons.append("efeitos desconhecidos")

        return SemanticSafety(
            responsibility=responsibility,
            sensitivity=sensitivity,
            relevant_calls=relevant_calls,
            reason_codes=list(dict.fromkeys(reason_codes)),
            block_reasons=list(dict.fromkeys(block_reasons)),
        )

    def _sensitivity_rank(self, value: str) -> int:
        return {"LOW": 0, "GUARDED": 1, "SENSITIVE": 2, "CRITICAL": 3}.get(value, 1)

    def _calibration_file_blocked(self, file: str) -> bool:
        normalized = file.replace("\\", "/")
        return (
            normalized in CALIBRATION_BLOCKED_FILES
            or normalized.startswith("aya/data/")
            or normalized.startswith("scripts/")
            or normalized.endswith((".toml", ".yaml", ".yml", ".json", ".ps1", ".bat"))
        )

    def _semantic_text(self, file: str, symbol: str) -> str:
        path = self.root / file
        parts = [file, symbol]
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            tree = ast.parse(text)
        except (OSError, SyntaxError):
            return " ".join(parts)
        node = self._node_for_symbol(tree, symbol)
        if node is None:
            parts.extend(self._imports_for_tree(tree))
            return " ".join(parts + self._relevant_symbol_calls(file, symbol))
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                parts.append(child.id)
            elif isinstance(child, ast.Attribute):
                parts.append(child.attr)
            elif isinstance(child, ast.Constant) and isinstance(child.value, str):
                parts.append(child.value)
            elif isinstance(child, ast.arg):
                parts.append(child.arg)
        decorators = getattr(node, "decorator_list", [])
        parts.extend(self._call_name(item) for item in decorators)
        return " ".join(part for part in parts if part)

    def _imports_for_tree(self, tree: ast.AST) -> list[str]:
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        return imports

    def _node_for_symbol(self, tree: ast.AST, symbol: str) -> ast.AST | None:
        if not symbol:
            return None
        parents = self._ast_parents(tree)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and self._qualified_symbol(tree, node, parents) == symbol:
                return node
        return None

    def _relevant_symbol_calls(self, file: str, symbol: str) -> list[str]:
        path = self.root / file
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
        except (OSError, SyntaxError):
            return []
        node = self._node_for_symbol(tree, symbol)
        if node is None:
            return []
        sensitive_terms = {
            "subprocess", "system", "popen", "run", "_run", "git", "commit", "worktree", "revert",
            "open", "write_text", "read_text", "replace", "unlink", "sqlite", "database", "execute",
            "requests", "serve", "launch", "auth", "allows", "permission", "release", "validate",
        }
        calls = sorted({
            self._call_name(child.func)
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and self._call_name(child.func)
        })
        return [call for call in calls if any(term in call.lower() for term in sensitive_terms)]

    def _call_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            owner = self._call_name(node.value)
            return f"{owner}.{node.attr}" if owner else node.attr
        return ""

    def _looks_read_only(self, file: str, symbol: str) -> bool:
        text = self._semantic_text(file, symbol).lower()
        write_terms = {"write", "save", "append", "delete", "remove", "update", "commit", "execute", "run", "create", "set_"}
        return bool(symbol) and not any(term in text for term in write_terms)

    def _looks_pure_utility(self, file: str, symbol: str) -> bool:
        text = self._semantic_text(file, symbol).lower()
        return bool(symbol) and not any(
            term in text
            for term in ("self.", "write", "open", "subprocess", "git", "database", "sqlite", "auth", "permission", "network", "server")
        )

    def _candidate_score(
        self,
        *,
        evidence: list[str],
        required_tests: list[str],
        stats: dict[str, int],
        files: list[str],
        changed_lines: int,
        blocked: list[str],
    ) -> tuple[int, list[str]]:
        score = 0
        reasons: list[str] = []
        score += len(evidence) * 10
        reasons.append(f"evidencias={len(evidence)}")
        if required_tests:
            score += 15
            reasons.append("testes_relacionados=sim")
        score += stats.get("success", 0) * 8
        reasons.append(f"sucesso_historico={stats.get('success', 0)}")
        score -= len(files) * 2
        score -= changed_lines
        if blocked:
            score -= 1000
            reasons.append("bloqueado=" + ",".join(blocked))
        return score, reasons

    def _candidate_priority_score(
        self,
        *,
        qualification: dict,
        stats: dict[str, int],
        risk: str,
        blocked: list[str],
        required_tests: list[str],
    ) -> tuple[int, list[str]]:
        score = int(qualification.get("documentation_value_score", 0))
        reasons = [f"valor_tecnico={score}"]
        if qualification.get("qualification_status") == "ACAO_RECOMENDADA":
            score += 40
            reasons.append("acao_recomendada=sim")
        elif qualification.get("qualification_status") == "MANUTENCAO_OPCIONAL":
            score += 15
            reasons.append("manutencao_opcional=sim")
        if required_tests:
            score += 10
            reasons.append("testabilidade=sim")
        score += min(stats.get("success", 0), 5) * 4
        if stats.get("fail", 0):
            score -= 40
            reasons.append("falhas_historicas=sim")
        if risk != "baixo":
            score -= 60
            reasons.append(f"risco={risk}")
        if blocked:
            score -= 100
            reasons.append("bloqueado=sim")
        return score, reasons

    def _candidate_path_blocked(self, file: str) -> bool:
        lowered = file.lower()
        return any(term in lowered for term in AUTONOMY_BLOCKED_TERMS) or self.workspace._path_error(file) != ""

    def _candidate_dedup_key(self, head: str, operation: str, file: str, symbol: str, goal: str) -> str:
        normalized = re.sub(r"\s+", " ", goal.lower()).strip()
        return self._sha_text("\n".join([head, operation, file, symbol, normalized]))

    def _signature_for_symbol(self, entry: TechnicalFile, symbol: str) -> str:
        name = symbol.split(".")[-1]
        return next((signature for signature in entry.signatures if signature.startswith(f"{name}(")), "")

    def _validate_current_candidate(
        self,
        candidate: AutonomousCandidate,
        current_hashes: dict[str, str] | None = None,
        head: str | None = None,
    ) -> AutonomousCandidate:
        if candidate.project_head != (head or self._safe_head()):
            return self._stale_candidate(candidate, "HEAD mudou desde a deteccao.")
        path = self.root / candidate.file
        if not path.exists():
            return self._stale_candidate(candidate, "arquivo nao existe mais.")
        try:
            if current_hashes is not None and candidate.file in current_hashes:
                current_hash = current_hashes[candidate.file]
            else:
                current_hash = self._file_sha256(candidate.file)
                if current_hashes is not None:
                    current_hashes[candidate.file] = current_hash
        except (OSError, StructuredPatchError):
            return self._stale_candidate(candidate, "hash atual indisponivel.")
        if current_hash != candidate.file_sha256:
            return self._stale_candidate(candidate, "hash do arquivo mudou.")
        if candidate.operation_type == "insert_docstring" and not candidate.symbol:
            return self._stale_candidate(candidate, "simbolo ausente no candidato.")
        if candidate.operation_type == "replace_exact":
            try:
                payload = self._unused_import_payload(candidate)
            except StructuredPatchError as exc:
                return self._stale_candidate(candidate, str(exc))
            count = path.read_text(encoding="utf-8-sig", errors="replace").count(payload["old_text"])
            if count != 1:
                return self._stale_candidate(candidate, "texto antigo nao existe exatamente uma vez.")
        missing_tests = [test for test in candidate.required_tests if not (self.root / test).exists()]
        if missing_tests:
            return self._stale_candidate(candidate, "teste relacionado ausente: " + ", ".join(missing_tests[:3]))
        return candidate

    def _symbol_missing_docstring(self, file: str, symbol: str, signature: str) -> bool:
        path = self.root / file
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
        except (OSError, SyntaxError):
            return False
        parents = self._ast_parents(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if self._qualified_symbol(tree, node, parents) != symbol:
                continue
            if signature and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = [arg.arg for arg in [*node.args.posonlyargs, *node.args.args]]
                actual = f"{node.name}({', '.join(args)})"
                if actual != signature:
                    return False
            return ast.get_docstring(node) is None
        return False

    def _stale_candidate(self, candidate: AutonomousCandidate, reason: str) -> AutonomousCandidate:
        code = "STALE_FILE_HASH"
        if "HEAD" in reason:
            code = "STALE_HEAD"
        elif "nao existe" in reason:
            code = "STALE_FILE_REMOVED"
        elif "teste" in reason:
            code = "STALE_RELATED_TEST"
        return self._replace_candidate_status(
            candidate,
            "OBSOLETO",
            ["OBSOLETO"],
            stale=True,
            stale_reason=reason,
            route="CODEX_REVIEW_RECOMMENDED",
            reason_codes=[code],
        )

    def _replace_candidate_status(
        self,
        candidate: AutonomousCandidate,
        status: str,
        blocked_reasons: list[str],
        *,
        stale: bool | None = None,
        stale_reason: str | None = None,
        route: str | None = None,
        reason_codes: list[str] | None = None,
    ) -> AutonomousCandidate:
        data = asdict(candidate)
        data["status"] = status
        data["eligibility"] = "ELEGIVEL" if status == "ELEGIVEL" and not blocked_reasons else "BLOQUEADO"
        data["blocked_reasons"] = [*candidate.blocked_reasons, *blocked_reasons]
        data["qualification_status"] = status if status in {"BLOQUEADO", "OBSOLETO"} else candidate.qualification_status
        data["reason_codes"] = list(dict.fromkeys([*candidate.reason_codes, *(reason_codes or [])]))
        data["qualification_reasons"] = list(dict.fromkeys([*candidate.qualification_reasons, *(reason_codes or [])]))
        data["stale"] = candidate.stale if stale is None else stale
        data["stale_reason"] = candidate.stale_reason if stale_reason is None else stale_reason
        data["route"] = candidate.route if route is None else route
        return AutonomousCandidate(**data)

    def _route_from_candidate_state(
        self,
        eligibility: str,
        blocked: list[str],
        risk: str,
        operation_type: str,
        stats: dict[str, int],
        *,
        stale: bool,
    ) -> str:
        if stale:
            return "CODEX_REVIEW_RECOMMENDED"
        if risk != "baixo" or any(reason.startswith("ARQUIVO_BLOQUEADO") for reason in blocked):
            return "CODEX_ESCALATION_REQUIRED"
        if eligibility == "DADOS_INSUFICIENTES" or self._capability_level(operation_type, stats) in {"SEM_DADOS", "DADOS_INSUFICIENTES", "CALIBRACAO_NECESSARIA"}:
            return "INSUFFICIENT_DATA"
        if blocked:
            return "CODEX_REVIEW_RECOMMENDED"
        return "LOCAL_SUPERVISED"

    def _candidate_queue_metrics(self, candidates: list[AutonomousCandidate]) -> dict[str, int]:
        historical = sum(item["total"] for item in self._operation_stats().values())
        detected = len(candidates)
        stale = sum(1 for item in candidates if item.stale or item.qualification_status == "OBSOLETO")
        blocked = sum(1 for item in candidates if not item.stale and item.qualification_status == "BLOQUEADO")
        informative = sum(1 for item in candidates if not item.stale and item.qualification_status == "INFORMATIVO")
        optional = sum(1 for item in candidates if not item.stale and item.qualification_status == "MANUTENCAO_OPCIONAL")
        recommended = sum(1 for item in candidates if not item.stale and item.qualification_status == "ACAO_RECOMENDADA")
        return {
            "historical": historical,
            "detected": detected,
            "current": sum(1 for item in candidates if not item.stale),
            "relevant": sum(1 for item in candidates if item.relevance_valid),
            "not_relevant": sum(1 for item in candidates if not item.relevance_valid),
            "actionable": sum(1 for item in candidates if item.actionable),
            "informative": informative,
            "optional_maintenance": optional,
            "recommended_action": recommended,
            "qualified": informative + optional + recommended + blocked + stale,
            "classified_total": informative + optional + recommended + blocked + stale,
            "blocked_class": blocked,
            "duplicates": sum(1 for item in candidates if "DUPLICADO" in item.blocked_reasons),
            "stale": stale,
            "eligible": sum(1 for item in candidates if item.eligibility == "ELEGIVEL" and not item.stale),
            "blocked": sum(1 for item in candidates if item.eligibility != "ELEGIVEL"),
            "blocked_by_policy": sum(1 for item in candidates if any(reason in item.blocked_reasons for reason in {"NAO_ACIONAVEL", "DUPLICADO"}) or item.qualification_status == "BLOQUEADO"),
            "blocked_by_risk": sum(1 for item in candidates if any(reason.startswith("RISCO_") for reason in item.blocked_reasons)),
            "blocked_by_capacity": sum(1 for item in candidates if "BLOQUEADO_POR_FALHAS" in item.blocked_reasons),
            "blocked_by_insufficient_data": sum(1 for item in candidates if "DADOS_INSUFICIENTES" in item.blocked_reasons),
            "selected": 1 if self._load_autonomy_state().get("selected_candidate_id") else 0,
            "created": sum(1 for proposal in self.proposals.values() if proposal.title.startswith("[AUTO]")),
            "sem_tarefa_segura": sum(
                1
                for event in self._load_autonomy_state().get("events", [])
                if event.get("action") == "candidate_blocked"
            ),
        }

    def _candidate_lessons(self, files: list[str], operation_type: str) -> list[str]:
        entries = self._load_engineering_memory()
        needles = [operation_type, *files]
        lessons = [
            entry.id
            for entry in entries
            if any(needle and needle.lower() in f"{entry.title} {entry.content}".lower() for needle in needles)
        ]
        return lessons[:5]

    def _similar_proposals(self, files: list[str], symbols: list[str]) -> list[str]:
        file_set = set(files)
        symbol_set = set(symbols)
        similar = [
            proposal.id
            for proposal in self.proposals.values()
            if file_set & set(proposal.related_files) or symbol_set & set(proposal.related_symbols)
        ]
        return similar[-5:]

    def _ast_parents(self, tree: ast.AST) -> dict[ast.AST, ast.AST]:
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        return parents

    def _qualified_symbol(self, tree: ast.AST, target: ast.AST, parents: dict[ast.AST, ast.AST] | None = None) -> str:
        if parents is None:
            parents = self._ast_parents(tree)
        if isinstance(target, ast.ClassDef):
            return target.name
        parent = parents.get(target)
        if isinstance(parent, ast.ClassDef) and hasattr(target, "name"):
            return f"{parent.name}.{target.name}"
        return getattr(target, "name", "")

    def _find_candidate(self, candidate_id: str) -> AutonomousCandidate | None:
        wanted = (candidate_id or "").strip().upper()
        return next((candidate for candidate in self._autonomous_candidates() if candidate.candidate_id == wanted), None)

    def _select_best_candidate(self) -> AutonomousCandidate | None:
        candidates = [
            candidate for candidate in self._autonomous_candidates()
            if candidate.eligibility == "ELEGIVEL" and candidate.qualification_status == "ACAO_RECOMENDADA" and candidate.actionable
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: (-item.priority_score, item.risk, len(item.files), item.estimated_changed_lines, item.candidate_id))
        return candidates[0]

    def _candidate_suggested_change(self, candidate: AutonomousCandidate) -> str:
        return "\n".join([
            f"Autonomia supervisionada v{AUTONOMY_POLICY_VERSION}.",
            f"Candidato: {candidate.candidate_id}",
            f"Operacao: {candidate.operation_type}",
            f"Score: {candidate.score} ({'; '.join(candidate.score_explanation)})",
            "Gerar somente manifesto estruturado minimo e parar em AGUARDANDO_APROVACAO.",
        ])

    def _candidate_decision(self, candidate: AutonomousCandidate) -> dict:
        if candidate.operation_type == "insert_docstring":
            return {
                "type": "insert_docstring",
                "symbol": candidate.symbols[0],
                "content": self._candidate_docstring(candidate),
            }
        if candidate.operation_type == "replace_exact":
            entry = self._unused_import_payload(candidate)
            return {"type": "replace_exact", **entry}
        raise StructuredPatchError("Operacao autonoma nao suportada.")

    def _candidate_docstring(self, candidate: AutonomousCandidate) -> str:
        symbol = candidate.symbols[0]
        name = symbol.rsplit(".", 1)[-1]
        subject = name.replace("_", " ")
        body = self._symbol_context(candidate.files[0], symbol).lower()
        if name.startswith("render_"):
            if "html.escape" in body and "diff_limit" in body:
                return f"Render {subject.removeprefix('render ')} as escaped HTML, truncating long content unless expanded."
            return f"Render {subject.removeprefix('render ')} for display without changing stored data."
        if name.startswith("parse_"):
            return f"Parse {subject.removeprefix('parse ')} into the normalized value expected by the caller."
        if "return " in body:
            return f"Return the {subject} result without mutating project state."
        return f"Describe the existing {subject} behavior without changing project state."

    def _unused_import_payload(self, candidate: AutonomousCandidate) -> dict:
        path = self.root / candidate.files[0]
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        evidence = candidate.evidence[0]
        match = re.search(r":(\d+)\s", evidence)
        if not match:
            raise StructuredPatchError("Linha do import nao confirmada.")
        line = text.splitlines()[int(match.group(1)) - 1]
        return {"old_text": line + "\n", "new_text": ""}

    def _prepare_autonomous_proposal(self, proposal: EngineeringProposal, candidate: AutonomousCandidate) -> str:
        if proposal.attempts >= 2:
            return "Tentativa autonoma bloqueada: limite de duas tentativas."
        git = self.workspace.git_state()
        if not git.safe:
            return f"Tentativa autonoma bloqueada: {git.message}"
        previous = proposal.state
        proposal.state = "PREPARANDO"
        proposal.attempts += 1
        self._event(proposal, f"autonomous_attempt_started {proposal.attempts}", previous, proposal.state)
        try:
            proposal.base_commit = self.workspace.head()
            target_file = candidate.files[0]
            decision = self._candidate_decision(candidate)
            worktree = self.workspace.create(proposal.id)
            proposal.workspace = str(worktree)
            proposal.workspace_path = str(worktree)
            proposal.workspace_created = True
            baseline = self.workspace.baseline(worktree, self._related_tests(proposal))
            proposal.validation = [asdict(result) | {"passed": result.passed, "phase": "baseline"} for result in baseline]
            proposal.tests_executed = True
            if not all(result.passed for result in baseline):
                raise RuntimeError("Baseline reprovou antes do patch autonomo.")
            manifest = self.structured_patch.build_manifest(
                decision,
                proposal.id,
                proposal.base_commit,
                target_file,
                self._file_sha256(target_file, worktree),
                self._related_tests(proposal),
            )
            proposal.patch_manifest = manifest
            result = self.structured_patch.apply(
                worktree,
                manifest,
                proposal.id,
                proposal.base_commit,
                proposal.related_files,
                proposal.related_symbols,
            )
            proposal.diff_created = result.ok
            proposal.patch = self.workspace.diff(worktree)
            inspection = self.workspace.inspect_patch(proposal.patch, 2, 80, proposal.related_files)
            if not inspection.valid:
                raise StructuredPatchError(inspection.message)
            diff_check = self.workspace.diff_check(worktree)
            proposal.validation.append(asdict(diff_check) | {"passed": diff_check.passed, "phase": "patch"})
            if not diff_check.passed:
                raise StructuredPatchError(diff_check.output)
            proposal.state = "EM_TESTE"
            self._event(proposal, "autonomous_patch_prepared", "PREPARANDO", proposal.state)
            self._autonomy_event("autonomous_patch_prepared", {"proposal_id": proposal.id, "candidate_id": candidate.candidate_id})
            self._save()
            return f"Patch autonomo preparado em worktree isolado para {proposal.id}."
        except Exception as exc:
            proposal.state = "FALHOU"
            message = self.workspace.sanitize(str(exc), 1200)
            proposal.review_result = message
            proposal.diff_preserved = bool(proposal.patch)
            self._record_failure(proposal, "autonomia", "tentativa autonoma falhou", message)
            self._cleanup_failed_workspace(proposal)
            self._event(proposal, "autonomous_attempt_failed", "PREPARANDO", "FALHOU")
            self._autonomy_event("autonomous_attempt_failed", {"proposal_id": proposal.id, "error": message})
            self._save()
            return f"Tentativa autonoma falhou: {message}"

    def _record_autonomous_escalation(self, proposal: EngineeringProposal, candidate: AutonomousCandidate, package: str) -> None:
        proposal.failure_reason = "ESCALADA"
        proposal.failure_message = self.workspace.sanitize(package, 3000)
        self._autonomy_event("autonomous_cycle_escalated", {
            "proposal_id": proposal.id,
            "candidate_id": candidate.candidate_id,
            "package_sha256": self._sha_text(package),
        })

    def _derived_engineering_memory(self) -> list[str]:
        proposals = sorted(self.proposals.values(), key=lambda value: value.id)
        signals: list[str] = []
        failures = self._count_values(
            f"{proposal.failure_stage or 'etapa_indisponivel'} / {proposal.failure_reason or 'motivo_indisponivel'}"
            for proposal in proposals
            if proposal.failure_stage or proposal.failure_reason
        )
        for key, total in list(failures.items())[:5]:
            signals.append(f"Falha recorrente: {key} em {total} proposta(s).")
        integrated = [proposal for proposal in proposals if proposal.state == "INTEGRADA"]
        if integrated:
            signals.append(f"Integracoes concluidas por fast-forward estrito: {len(integrated)}.")
        reverted = [proposal for proposal in proposals if proposal.state == "REVERTIDA"]
        if reverted:
            signals.append(f"Reversoes concluidas com git revert: {len(reverted)}.")
        blocked = [
            proposal.id
            for proposal in proposals
            if proposal.state in {"INTEGRACAO_BLOQUEADA", "REVERSAO_BLOQUEADA", "PREVISAO_REVERSAO_BLOQUEADA"}
        ]
        if blocked:
            signals.append("Bloqueios atuais: " + ", ".join(blocked[:8]) + ".")
        return signals

    def _record_failure(self, proposal: EngineeringProposal, stage: str, reason: str, message: str) -> None:
        proposal.failure_stage = stage
        proposal.failure_reason = reason
        proposal.failure_message = self.workspace.sanitize(message, 4000)
        proposal.failure_at = datetime.now().isoformat(timespec="seconds")
        proposal.project_unchanged = self.workspace.git_state().safe

    def _cleanup_failed_workspace(self, proposal: EngineeringProposal) -> None:
        workspace = proposal.workspace or proposal.workspace_path
        if not workspace:
            return
        try:
            current_diff = self.workspace.diff(workspace)
            if current_diff.strip() and current_diff != "Diff indisponivel.":
                proposal.patch = current_diff
                proposal.diff_preserved = True
        except (OSError, RuntimeError, ValueError):
            pass
        try:
            proposal.cleanup_result = self.workspace.discard(workspace)
            proposal.workspace_cleaned = True
            proposal.workspace = ""
        except (OSError, RuntimeError, ValueError) as exc:
            proposal.cleanup_result = self.workspace.sanitize(str(exc))
            proposal.workspace_cleaned = False

    def _validation_summary(self, proposal: EngineeringProposal) -> str:
        if not proposal.validation:
            return "Informacao nao registrada."
        lines = []
        for item in proposal.validation[-12:]:
            status = self._validation_item_status(item)
            lines.append(f"- {item.get('phase', '?')} {item.get('name', '?')}: {status}")
        return "\n".join(lines)

    def _validation_item_status(self, item: dict) -> str:
        if item.get("passed"):
            return "APROVADO"
        if item.get("exit_code") == 124:
            return "VALIDACAO_INCONCLUSIVA_POR_TIMEOUT"
        return "REPROVADO"

    def _decision_summary(self, proposal: EngineeringProposal) -> str:
        decisions = {
            "APROVADA": "aprovacao humana registrada; patch nao aplicado automaticamente",
            "REJEITADA": "rejeicao humana registrada",
            "DESCARTADA": "descarte humano registrado",
            "APLICADA": "aplicacao registrada",
        }
        return decisions.get(proposal.state, "Informacao nao registrada.")

    def _neutralize_success_text(self, text: str) -> str:
        cleaned = re.sub(
            r"(?im)^.*(alteracao|mudanca|correcao).*(realizada|concluida|sucesso).*$",
            "[Texto de sucesso do modelo neutralizado: ainda depende de diff e testes reais.]",
            text or "",
        )
        return cleaned.strip()

    def _approval_summary(self, proposal: EngineeringProposal) -> str:
        if not proposal.approved_at:
            return "Aprovacao: Informacao nao registrada."
        valid, reason = self._approval_currently_valid(proposal)
        return "\n".join([
            f"- Aprovada: {'sim' if proposal.approval_valid else 'nao'}",
            f"- Data: {proposal.approved_at}",
            f"- Valida agora: {'sim' if valid else 'nao'}",
            f"- Diff aprovado: {proposal.approved_diff_sha256 or 'Informacao nao registrada.'}",
            f"- Manifesto aprovado: {proposal.approved_manifest_sha256 or 'Informacao nao registrada.'}",
            f"- Motivo de invalidacao: {'' if valid else reason}",
        ])

    def _approval_snapshot_valid(self, proposal: EngineeringProposal) -> tuple[bool, str]:
        if not proposal.patch:
            return False, "diff ausente"
        if not proposal.patch_manifest:
            return False, "manifesto ausente"
        if not proposal.base_commit:
            return False, "base_commit ausente"
        if not proposal.review_result:
            return False, "revisao ausente"
        if not self._required_checks_passed(proposal):
            return False, "checks obrigatorios nao aprovados"
        return True, ""

    def _approval_currently_valid(self, proposal: EngineeringProposal) -> tuple[bool, str]:
        if not proposal.approval_valid:
            return False, proposal.approval_invalid_reason or "aprovacao nao registrada"
        expected = {
            "diff": self._sha_text(proposal.patch),
            "manifest": self._sha_json(proposal.patch_manifest),
            "base": proposal.base_commit,
            "validation": self._sha_json(proposal.validation),
            "review": self._sha_text(proposal.review_result),
        }
        actual = {
            "diff": proposal.approved_diff_sha256,
            "manifest": proposal.approved_manifest_sha256,
            "base": proposal.approved_base_commit,
            "validation": proposal.approved_validation_sha256,
            "review": proposal.approved_review_sha256,
        }
        for key, value in expected.items():
            if value != actual[key]:
                return False, f"aprovacao invalidada por mudanca em {key}"
        return True, ""

    def _validate_apply_preconditions(self, proposal: EngineeringProposal) -> None:
        valid, reason = self._approval_currently_valid(proposal)
        if not valid:
            proposal.approval_valid = False
            proposal.approval_invalid_reason = reason
            raise RuntimeError(reason)
        if proposal.risk not in {"baixo", "medio"}:
            raise RuntimeError("RISCO_NAO_PERMITIDO")
        if not proposal.workspace or not Path(proposal.workspace).exists():
            raise RuntimeError("WORKTREE_AUSENTE")
        if self.workspace.head() != proposal.approved_base_commit:
            raise RuntimeError("BASE_DESATUALIZADA")
        if self._git(("rev-parse", "HEAD"), cwd=Path(proposal.workspace), timeout=30).stdout.strip() != proposal.approved_base_commit:
            raise RuntimeError("WORKTREE_HEAD_DIVERGENTE")
        git_state = self.workspace.git_state()
        if not git_state.safe:
            raise RuntimeError("MAIN_SUJA")
        current_diff = self.workspace.diff(proposal.workspace)
        if self._sha_text(current_diff) != proposal.approved_diff_sha256:
            raise RuntimeError("DIFF_DIVERGENTE")
        if self._sha_json(proposal.patch_manifest) != proposal.approved_manifest_sha256:
            raise RuntimeError("MANIFESTO_DIVERGENTE")
        inspection = self.workspace.inspect_patch(current_diff, self.max_files, self.max_changed_lines, self._approved_files(proposal))
        if not inspection.valid:
            raise RuntimeError(inspection.message)
        status = self._git(("status", "--porcelain"), cwd=Path(proposal.workspace), timeout=30).stdout.splitlines()
        expected = set(self._approved_files(proposal))
        for line in status:
            path = line[3:] if len(line) >= 4 else ""
            if line.startswith("??"):
                raise RuntimeError("ARQUIVO_NAO_RASTREADO")
            if path not in expected:
                raise RuntimeError(f"ARQUIVO_INESPERADO: {path}")
        diff_check = self.workspace.diff_check(proposal.workspace)
        if not diff_check.passed:
            raise RuntimeError("DIFF_CHECK_REPROVADO")
        if not self._required_checks_passed(proposal):
            raise RuntimeError("CHECKS_REPROVADOS")
        if self._review_blocks(proposal.review_result):
            raise RuntimeError("REVISAO_BLOQUEADORA")

    def _integration_eligibility(self, proposal: EngineeringProposal) -> tuple[bool, str]:
        if proposal.state not in {"COMMIT_PRONTO", "VALIDANDO_INTEGRACAO", "INTEGRANDO"}:
            return False, "estado nao elegivel"
        if proposal.state == "COMMIT_PRONTO" and not proposal.ready_for_integration:
            return False, "ready_for_integration falso"
        valid, reason = self._approval_currently_valid(proposal)
        if not valid:
            return False, reason
        if proposal.risk not in {"baixo", "medio"}:
            return False, "risco nao permitido"
        return True, ""

    def _validate_integration_preconditions(self, proposal: EngineeringProposal, allow_integrated_head: bool = False) -> None:
        eligible, reason = self._integration_eligibility(proposal)
        if not eligible:
            raise RuntimeError(reason.upper().replace(" ", "_"))
        if not proposal.proposal_branch or not proposal.proposal_commit or not proposal.commit_parent:
            raise RuntimeError("COMMIT_ISOLADO_INCOMPLETO")
        if not self._branch_exists(proposal.proposal_branch):
            raise RuntimeError("BRANCH_AUSENTE")
        branch_head = self._git(("rev-parse", proposal.proposal_branch), cwd=self.root, timeout=30).stdout.strip()
        if branch_head != proposal.proposal_commit:
            raise RuntimeError("BRANCH_MUDOU")
        commit = self._git(("rev-parse", f"{proposal.proposal_commit}^{{commit}}"), cwd=self.root, timeout=30).stdout.strip()
        if commit != proposal.proposal_commit:
            raise RuntimeError("COMMIT_MUDOU")
        parents = self._git(("show", "-s", "--format=%P", proposal.proposal_commit), cwd=self.root, timeout=30).stdout.split()
        if len(parents) != 1:
            raise RuntimeError("COMMIT_COM_MULTIPLOS_PAIS")
        if parents[0] != proposal.commit_parent:
            raise RuntimeError("PAI_DO_COMMIT_DIVERGENTE")
        ancestor = self.workspace._run(("git", "merge-base", "--is-ancestor", proposal.commit_parent, proposal.proposal_commit), self.root, 30)
        if ancestor.returncode != 0:
            raise RuntimeError("COMMIT_NAO_DESCENDE_DA_BASE")
        changed_files = self._commit_files(proposal.proposal_commit)
        approved_files = self._approved_files(proposal)
        if sorted(changed_files) != sorted(approved_files) or sorted(changed_files) != sorted(proposal.committed_files):
            raise RuntimeError("ARQUIVO_INESPERADO")
        for rel in changed_files:
            error = self.workspace._path_error(rel)
            if error:
                raise RuntimeError(error)
        commit_diff = self._git(("diff", "--no-ext-diff", proposal.commit_parent, proposal.proposal_commit, "--"), cwd=self.root, timeout=30).stdout
        if self._sha_text(commit_diff) != proposal.approved_diff_sha256:
            raise RuntimeError("DIFF_DIVERGENTE")
        if proposal.committed_diff_sha256 and self._sha_text(commit_diff) != proposal.committed_diff_sha256:
            raise RuntimeError("DIFF_COMMIT_DIVERGENTE")
        if self._sha_json(proposal.patch_manifest) != proposal.approved_manifest_sha256:
            raise RuntimeError("MANIFESTO_DIVERGENTE")
        if self._sha_json(proposal.validation) != proposal.approved_validation_sha256:
            raise RuntimeError("VALIDACAO_DIVERGENTE")
        if self._sha_text(proposal.review_result) != proposal.approved_review_sha256:
            raise RuntimeError("REVISAO_DIVERGENTE")
        if not self._required_checks_passed(proposal):
            raise RuntimeError("CHECKS_INCOMPLETOS")
        if not proposal.review_result:
            raise RuntimeError("REVISAO_AUSENTE")
        if self._review_blocks(proposal.review_result):
            raise RuntimeError("REVISAO_BLOQUEADORA")
        if self._git(("branch", "--show-current"), cwd=self.root, timeout=30).stdout.strip() != "main":
            raise RuntimeError("MAIN_BRANCH_DIVERGENTE")
        if self._git(("status", "--porcelain"), cwd=self.root, timeout=30).stdout.strip():
            raise RuntimeError("MAIN_SUJA")
        current_head = self.workspace.head()
        expected_heads = {proposal.commit_parent}
        if allow_integrated_head:
            expected_heads.add(proposal.proposal_commit)
        if current_head not in expected_heads:
            raise RuntimeError("BASE_DIVERGENTE")
        if proposal.workspace_path:
            workspace_path = Path(proposal.workspace_path)
            if not workspace_path.exists():
                raise RuntimeError("WORKTREE_AUSENTE")
            if self._git(("branch", "--show-current"), cwd=workspace_path, timeout=30).stdout.strip() != proposal.proposal_branch:
                raise RuntimeError("WORKTREE_BRANCH_DIVERGENTE")
            if self._git(("rev-parse", "HEAD"), cwd=workspace_path, timeout=30).stdout.strip() != proposal.proposal_commit:
                raise RuntimeError("WORKTREE_COMMIT_DIVERGENTE")
            if self._git(("status", "--porcelain"), cwd=workspace_path, timeout=30).stdout.strip():
                raise RuntimeError("WORKTREE_SUJO")

    def _validate_main_ready_for_fast_forward(self, proposal: EngineeringProposal) -> None:
        if self._git(("branch", "--show-current"), cwd=self.root, timeout=30).stdout.strip() != "main":
            raise RuntimeError("MAIN_BRANCH_DIVERGENTE")
        if self._git(("status", "--porcelain"), cwd=self.root, timeout=30).stdout.strip():
            raise RuntimeError("MAIN_SUJA")
        if self.workspace.head() != proposal.commit_parent:
            raise RuntimeError("BASE_DIVERGENTE")
        branch_head = self._git(("rev-parse", proposal.proposal_branch), cwd=self.root, timeout=30).stdout.strip()
        if branch_head != proposal.proposal_commit:
            raise RuntimeError("BRANCH_MUDOU")

    def _finalize_already_fast_forwarded(self, proposal: EngineeringProposal) -> str:
        previous = proposal.state
        proposal.integration_started_at = proposal.integration_started_at or datetime.now().isoformat(timespec="seconds")
        proposal.integration_method = "fast-forward"
        proposal.previous_main_head = proposal.previous_main_head or proposal.commit_parent
        proposal.resulting_main_head = self.workspace.head()
        proposal.integrated_commit = proposal.proposal_commit
        proposal.main_branch = self._git(("branch", "--show-current"), cwd=self.root, timeout=30).stdout.strip()
        proposal.pushed = False
        proposal.remote_used = False
        proposal.merge_commit_created = False
        try:
            self._validate_integration_preconditions(proposal, allow_integrated_head=True)
            validation = self._validate_commit_in_clean_worktree(proposal)
            proposal.integration_validation = validation
            post = self._post_integration_validation(proposal)
            proposal.post_integration_validation = post
            if not all(item.get("passed") for item in [*validation, *post]):
                raise RuntimeError("VALIDACAO_DE_RECONCILIACAO_REPROVADA")
            cleanup = self._cleanup_integrated_worktree(proposal)
            proposal.integration_cleanup_result = cleanup
            proposal.workspace_cleaned = "removido" in cleanup.lower()
            if proposal.workspace_cleaned:
                proposal.workspace = ""
                proposal.worktree_cleanup_pending = False
            else:
                proposal.worktree_cleanup_pending = True
            proposal.integrated_at = datetime.now().isoformat(timespec="seconds")
            proposal.integration_success = True
            proposal.integration_partial = False
            proposal.state = "INTEGRADA"
            self._event(proposal, "integracao reconciliada sem novo merge", previous, proposal.state)
            self._save()
            return "\n".join([
                "Proposta ja estava fast-forwarded na main; estado reconciliado.",
                f"- Commit integrado: {proposal.integrated_commit}",
                f"- Main antes: {proposal.previous_main_head}",
                f"- Main depois: {proposal.resulting_main_head}",
                "- Novo merge executado: nao",
                "- Push executado: nao",
                f"- Validacao previa: {self._checks_status(proposal.integration_validation)}",
                f"- Validacao posterior: {self._checks_status(proposal.post_integration_validation)}",
                f"- Limpeza do worktree: {proposal.integration_cleanup_result}",
                "- Estado final: INTEGRADA",
            ])
        except Exception as exc:
            proposal.state = "INTEGRACAO_BLOQUEADA"
            proposal.integration_partial = True
            proposal.integration_block_reason = self.workspace.sanitize(str(exc))
            self._event(proposal, "reconciliacao de integracao bloqueada", previous, proposal.state)
            self._save()
            return f"Integracao parcial registrada: {proposal.integration_block_reason}."

    def _validate_commit_in_clean_worktree(self, proposal: EngineeringProposal) -> list[dict]:
        target = self.workspace.workspace_root / f"integration-{proposal.id}-{uuid.uuid4().hex[:8]}"
        results: list[CheckResult] = []
        try:
            self._git(("worktree", "add", "--detach", str(target), proposal.proposal_commit), cwd=self.root, timeout=90)
            results.extend(self.workspace.validate(target))
            for name, command, timeout in (
                ("git diff-tree", ("git", "diff-tree", "--no-commit-id", "--name-only", "-r", proposal.proposal_commit), 30),
                ("git show --check", ("git", "show", "--check", proposal.proposal_commit), 30),
                ("git status --porcelain", ("git", "status", "--porcelain"), 30),
            ):
                results.append(self._check_command(name, command, timeout, target))
        finally:
            if target.exists():
                remove = self.workspace._run(("git", "worktree", "remove", str(target)), self.root, 90)
                prune = self.workspace._run(("git", "worktree", "prune"), self.root, 90)
                if remove.returncode != 0:
                    results.append(CheckResult("limpeza worktree validacao", "git worktree remove", remove.returncode, 0, self.workspace.sanitize(remove.stderr or remove.stdout)))
                if prune.returncode != 0:
                    results.append(CheckResult("git worktree prune", "git worktree prune", prune.returncode, 0, self.workspace.sanitize(prune.stderr or prune.stdout)))
        return [asdict(result) | {"passed": result.passed, "phase": "integration_validation"} for result in results]

    def _post_integration_validation(self, proposal: EngineeringProposal) -> list[dict]:
        results = [
            self._check_command("git diff --check HEAD^ HEAD", ("git", "diff", "--check", "HEAD^", "HEAD"), 30, self.root),
            self._check_command("smoke", ("python", "scripts/smoke_test.py"), 180, self.root),
        ]
        related = self._related_tests(proposal)
        if related:
            results.append(self._check_command("testes relacionados", ("python", "-m", "pytest", *related), 600, self.root))
        current = self.workspace.head()
        parents = self._git(("show", "-s", "--format=%P", "HEAD"), cwd=self.root, timeout=30).stdout.split()
        checks = [
            ("main head integrado", current == proposal.proposal_commit, current),
            ("pai esperado", parents == [proposal.commit_parent], " ".join(parents)),
            ("sem merge commit", len(parents) == 1, "pais=" + str(len(parents))),
            ("status limpo", not self._git(("status", "--porcelain"), cwd=self.root, timeout=30).stdout.strip(), ""),
        ]
        for name, passed, output in checks:
            results.append(CheckResult(name, name, 0 if passed else 1, 0, output))
        return [asdict(result) | {"passed": result.passed, "phase": "post_integration"} for result in results]

    def _cleanup_integrated_worktree(self, proposal: EngineeringProposal) -> str:
        if not proposal.workspace_path:
            return "Worktree nao registrado."
        path = Path(proposal.workspace_path)
        if not path.exists():
            return "Worktree ja estava ausente."
        status = self._git(("status", "--porcelain"), cwd=path, timeout=30).stdout.strip()
        if status:
            return "Worktree nao removido: status nao esta limpo."
        remove = self.workspace._run(("git", "worktree", "remove", str(path)), self.root, 90)
        prune = self.workspace._run(("git", "worktree", "prune"), self.root, 90)
        if remove.returncode != 0:
            return f"Worktree nao removido: {self.workspace.sanitize(remove.stderr or remove.stdout)}"
        return f"Worktree removido; prune codigo={prune.returncode}."

    def _integrated_idempotent_response(self, proposal: EngineeringProposal) -> str:
        head = self.workspace.head()
        ancestor = self.workspace._run(("git", "merge-base", "--is-ancestor", proposal.integrated_commit or proposal.proposal_commit, "main"), self.root, 30)
        still_integrated = ancestor.returncode == 0
        return "\n".join([
            "Proposta ja integrada.",
            f"- Commit: {proposal.integrated_commit or proposal.proposal_commit}",
            f"- Main atual: {head}",
            f"- Commit alcancavel pela main: {'sim' if still_integrated else 'nao'}",
            "- Novo merge executado: nao",
        ])

    def _validate_reversal_preconditions(self, proposal: EngineeringProposal, *, require_approval: bool) -> None:
        if not proposal.reversal_reason:
            raise RuntimeError("MOTIVO_AUSENTE")
        if not proposal.reversal_target_commit:
            raise RuntimeError("COMMIT_ALVO_AUSENTE")
        if self._git(("branch", "--show-current"), cwd=self.root, timeout=30).stdout.strip() != "main":
            raise RuntimeError("MAIN_BRANCH_DIVERGENTE")
        if self._git(("status", "--porcelain"), cwd=self.root, timeout=30).stdout.strip():
            raise RuntimeError("MAIN_SUJA")
        self._git(("rev-parse", f"{proposal.reversal_target_commit}^{{commit}}"), cwd=self.root, timeout=30)
        if not self._commit_is_in_main(proposal.reversal_target_commit):
            raise RuntimeError("COMMIT_FORA_DA_MAIN")
        existing_revert = self._find_revert_commit(proposal.reversal_target_commit)
        if existing_revert and proposal.state not in {"REVERSAO_PARCIAL", "REVERTIDA"}:
            raise RuntimeError("COMMIT_JA_REVERTIDO")
        if require_approval:
            valid, reason = self._reversal_currently_valid(proposal)
            if not valid:
                proposal.reversal_approval_valid = False
                proposal.reversal_approval_invalid_reason = reason
                raise RuntimeError(reason.upper().replace(" ", "_"))
            if self.workspace.head() != proposal.reversal_approved_base_commit:
                raise RuntimeError("BASE_REVERSAO_DIVERGENTE")

    def _build_reversal_preview(self, proposal: EngineeringProposal) -> dict:
        base_head = self.workspace.head()
        target = self.workspace.workspace_root / f"preview-reversal-{proposal.id}-{uuid.uuid4().hex[:8]}"
        results: list[CheckResult] = []
        conflicts = ""
        diff = ""
        files: list[str] = []
        added = 0
        removed = 0
        workspace_cleaned = False
        try:
            self._git(("worktree", "add", "--detach", str(target), base_head), cwd=self.root, timeout=90)
            temp_head = self._git(("rev-parse", "HEAD"), cwd=target, timeout=30).stdout.strip()
            if temp_head != base_head:
                raise RuntimeError("WORKTREE_HEAD_DIVERGENTE")
            revert = self.workspace._run(("git", "revert", "--no-commit", proposal.reversal_target_commit), target, 120)
            if revert.returncode != 0:
                conflicts = self.workspace.sanitize(revert.stderr or revert.stdout)
                self.workspace._run(("git", "revert", "--abort"), target, 60)
                return {
                    "base_head": base_head,
                    "target_commit": proposal.reversal_target_commit,
                    "diff": "",
                    "files": [],
                    "added": 0,
                    "removed": 0,
                    "validation": [asdict(CheckResult("git revert --no-commit", "git revert --no-commit", revert.returncode, 0, conflicts)) | {"passed": False, "phase": "reversal_preview"}],
                    "conflicts": conflicts,
                    "workspace_cleaned": False,
                    "valid": False,
                    "invalidated_reason": "CONFLITO_REVERSAO",
                }
            diff = self._git(("diff", "--no-ext-diff", "HEAD", "--"), cwd=target, timeout=30).stdout
            files, added, removed = self._preview_numstat(target)
            for rel in files:
                error = self.workspace._path_error(rel)
                if error:
                    raise RuntimeError(error)
            results.append(self._check_command("git diff --check", ("git", "diff", "--check", "HEAD"), 30, target))
            results.extend(self.workspace.validate(target, self._related_tests(proposal)))
            abort = self.workspace._run(("git", "revert", "--abort"), target, 60)
            if abort.returncode != 0:
                results.append(CheckResult("git revert --abort", "git revert --abort", abort.returncode, 0, self.workspace.sanitize(abort.stderr or abort.stdout)))
            status = self._git(("status", "--porcelain"), cwd=target, timeout=30).stdout.strip()
            if status:
                results.append(CheckResult("worktree preview limpo", "git status --porcelain", 1, 0, status))
        finally:
            if target.exists():
                remove = self.workspace._run(("git", "worktree", "remove", str(target)), self.root, 90)
                prune = self.workspace._run(("git", "worktree", "prune"), self.root, 90)
                workspace_cleaned = remove.returncode == 0
                if remove.returncode != 0:
                    results.append(CheckResult("limpeza worktree previsao", "git worktree remove", remove.returncode, 0, self.workspace.sanitize(remove.stderr or remove.stdout)))
                if prune.returncode != 0:
                    results.append(CheckResult("git worktree prune", "git worktree prune", prune.returncode, 0, self.workspace.sanitize(prune.stderr or prune.stdout)))
        validation = [asdict(result) | {"passed": result.passed, "phase": "reversal_preview"} for result in results]
        valid = bool(diff.strip()) and all(item.get("passed") for item in validation) and workspace_cleaned
        reason = "" if valid else "PREVISAO_REVERSAO_INVALIDA"
        return {
            "base_head": base_head,
            "target_commit": proposal.reversal_target_commit,
            "diff": diff,
            "files": files,
            "added": added,
            "removed": removed,
            "validation": validation,
            "conflicts": conflicts,
            "workspace_cleaned": workspace_cleaned,
            "valid": valid,
            "invalidated_reason": reason,
        }

    def _store_reversal_preview(self, proposal: EngineeringProposal, preview: dict) -> None:
        proposal.reversal_preview_created_at = datetime.now().isoformat(timespec="seconds")
        proposal.reversal_preview_base_head = preview["base_head"]
        proposal.reversal_preview_target_commit = preview["target_commit"]
        proposal.reversal_preview_diff = preview["diff"]
        proposal.reversal_preview_diff_sha256 = self._sha_text(preview["diff"])
        proposal.reversal_preview_files = list(preview["files"])
        proposal.reversal_preview_added_lines = int(preview["added"])
        proposal.reversal_preview_removed_lines = int(preview["removed"])
        proposal.reversal_preview_validation = list(preview["validation"])
        proposal.reversal_preview_validation_sha256 = self._sha_reversal_validation(proposal.reversal_preview_validation)
        proposal.reversal_preview_conflicts = preview["conflicts"]
        proposal.reversal_preview_clean = not bool(preview["conflicts"]) and bool(preview["diff"].strip())
        proposal.reversal_preview_workspace_cleaned = bool(preview["workspace_cleaned"])
        proposal.reversal_preview_main_unchanged = self.workspace.head() == preview["base_head"]
        proposal.reversal_preview_valid = bool(preview["valid"]) and proposal.reversal_preview_main_unchanged
        proposal.reversal_preview_invalidated_reason = "" if proposal.reversal_preview_valid else preview["invalidated_reason"]
        proposal.reversal_validation = proposal.reversal_preview_validation
        proposal.reversal_validation_sha256 = self._sha_json(proposal.reversal_validation)
        proposal.reversal_preview_sha256 = self._reversal_preview_hash(proposal)

    def _clear_reversal_preview(self, proposal: EngineeringProposal) -> None:
        proposal.reversal_preview_created_at = ""
        proposal.reversal_preview_base_head = ""
        proposal.reversal_preview_target_commit = ""
        proposal.reversal_preview_diff = ""
        proposal.reversal_preview_diff_sha256 = ""
        proposal.reversal_preview_files = []
        proposal.reversal_preview_added_lines = 0
        proposal.reversal_preview_removed_lines = 0
        proposal.reversal_preview_validation = []
        proposal.reversal_preview_validation_sha256 = ""
        proposal.reversal_preview_conflicts = ""
        proposal.reversal_preview_clean = False
        proposal.reversal_preview_workspace_cleaned = False
        proposal.reversal_preview_main_unchanged = False
        proposal.reversal_preview_valid = False
        proposal.reversal_preview_invalidated_reason = ""
        proposal.reversal_preview_sha256 = ""
        proposal.approved_reversal_preview_sha256 = ""
        proposal.approved_reversal_base_head = ""
        proposal.approved_reversal_target_commit = ""
        proposal.approved_reversal_validation_sha256 = ""

    def _preview_numstat(self, cwd: Path) -> tuple[list[str], int, int]:
        result = self._git(("diff", "--numstat", "HEAD"), cwd=cwd, timeout=30)
        files: list[str] = []
        added = 0
        removed = 0
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            add_raw, remove_raw, rel = parts[0], parts[1], parts[2]
            files.append(rel)
            if add_raw.isdigit():
                added += int(add_raw)
            if remove_raw.isdigit():
                removed += int(remove_raw)
        return files, added, removed

    def _reversal_preview_hash(self, proposal: EngineeringProposal) -> str:
        payload = {
            "proposal_id": proposal.id,
            "target_commit": proposal.reversal_preview_target_commit,
            "base_head": proposal.reversal_preview_base_head,
            "diff_sha256": proposal.reversal_preview_diff_sha256,
            "files": proposal.reversal_preview_files,
            "validation": self._normalized_validation_for_hash(proposal.reversal_preview_validation),
            "reason_sha256": self._sha_text(proposal.reversal_reason),
        }
        return self._sha_json(payload)

    def _sha_reversal_validation(self, validation: list[dict]) -> str:
        return self._sha_json(self._normalized_validation_for_hash(validation))

    def _normalized_validation_for_hash(self, validation: list[dict]) -> list[dict]:
        normalized = []
        for item in validation:
            normalized.append({
                "phase": item.get("phase", ""),
                "name": item.get("name", ""),
                "command": item.get("command", ""),
                "exit_code": item.get("exit_code", 0),
                "passed": bool(item.get("passed")),
                "output": item.get("output", ""),
            })
        return normalized

    def _reversal_preview_code(self, proposal: EngineeringProposal) -> str:
        target = (proposal.reversal_preview_target_commit or proposal.reversal_target_commit or "")[:7]
        digest = (proposal.reversal_preview_sha256 or "")[:10]
        return f"REV-{target}-{digest}" if target and digest else "Informacao nao registrada."

    def _validate_reversal_in_clean_worktree(self, proposal: EngineeringProposal) -> list[dict]:
        preview = self._build_reversal_preview(proposal)
        return preview["validation"]

    def _validate_main_ready_for_revert(self, proposal: EngineeringProposal) -> None:
        if self._git(("branch", "--show-current"), cwd=self.root, timeout=30).stdout.strip() != "main":
            raise RuntimeError("MAIN_BRANCH_DIVERGENTE")
        if self._git(("status", "--porcelain"), cwd=self.root, timeout=30).stdout.strip():
            raise RuntimeError("MAIN_SUJA")
        if self.workspace.head() != proposal.reversal_approved_base_commit:
            raise RuntimeError("BASE_REVERSAO_DIVERGENTE")
        if self._find_revert_commit(proposal.reversal_target_commit):
            raise RuntimeError("COMMIT_JA_REVERTIDO")

    def _validate_reversal_approval_for_execution(self, proposal: EngineeringProposal) -> None:
        valid, reason = self._reversal_currently_valid(proposal)
        if not valid:
            proposal.reversal_approval_valid = False
            proposal.reversal_approval_invalid_reason = reason
            raise RuntimeError(reason.upper().replace(" ", "_"))
        if self.workspace.head() != proposal.approved_reversal_base_head:
            raise RuntimeError("BASE_REVERSAO_DIVERGENTE")
        if proposal.reversal_target_commit != proposal.approved_reversal_target_commit:
            raise RuntimeError("COMMIT_ALVO_DIVERGENTE")
        if self._reversal_preview_hash(proposal) != proposal.approved_reversal_preview_sha256:
            raise RuntimeError("PREVISAO_REVERSAO_DIVERGENTE")
        if self._sha_reversal_validation(proposal.reversal_preview_validation) != proposal.approved_reversal_validation_sha256:
            raise RuntimeError("VALIDACAO_PREVISAO_DIVERGENTE")

    def _post_reversal_validation(self, proposal: EngineeringProposal) -> list[dict]:
        results = [
            self._check_command("git diff --check HEAD^ HEAD", ("git", "diff", "--check", "HEAD^", "HEAD"), 30, self.root),
            self._check_command("pytest", ("python", "-m", "pytest"), 600, self.root),
            self._check_command("ruff", ("python", "-m", "ruff", "check", "."), 180, self.root),
            self._check_command("compileall", ("python", "-m", "compileall", "."), 180, self.root),
            self._check_command("pip check", ("python", "-m", "pip", "check"), 180, self.root),
            self._check_command("smoke", ("python", "scripts/smoke_test.py"), 180, self.root),
        ]
        current = self.workspace.head()
        parents = self._git(("show", "-s", "--format=%P", "HEAD"), cwd=self.root, timeout=30).stdout.split()
        checks = [
            ("reversal head registrado", current == proposal.reversal_commit, current),
            ("reversal possui um pai", len(parents) == 1, "pais=" + str(len(parents))),
            ("status limpo", not self._git(("status", "--porcelain"), cwd=self.root, timeout=30).stdout.strip(), ""),
        ]
        for name, passed, output in checks:
            results.append(CheckResult(name, name, 0 if passed else 1, 0, output))
        return [asdict(result) | {"passed": result.passed, "phase": "post_reversal"} for result in results]

    def _reversal_snapshot_valid(self, proposal: EngineeringProposal) -> tuple[bool, str]:
        if not proposal.reversal_preview_valid:
            return False, proposal.reversal_preview_invalidated_reason or "previsao de reversao ausente"
        if proposal.reversal_preview_conflicts:
            return False, "previsao de reversao possui conflito"
        if not proposal.reversal_preview_validation:
            return False, "validacao da previsao ausente"
        if not proposal.reversal_target_commit:
            return False, "commit alvo ausente"
        if not proposal.reversal_base_commit:
            return False, "base de reversao ausente"
        if not proposal.reversal_reason:
            return False, "motivo ausente"
        if self.workspace.head() != proposal.reversal_preview_base_head:
            proposal.reversal_preview_valid = False
            proposal.reversal_preview_invalidated_reason = "main HEAD mudou desde a previsao"
            return False, proposal.reversal_preview_invalidated_reason
        if proposal.reversal_target_commit != proposal.reversal_preview_target_commit:
            return False, "commit alvo mudou desde a previsao"
        if not all(item.get("passed") for item in proposal.reversal_preview_validation):
            return False, "validacao da previsao reprovada"
        expected_validation = self._sha_reversal_validation(proposal.reversal_preview_validation)
        expected_review = self._sha_text(proposal.reversal_reason)
        expected_manifest = self._sha_json(self._reversal_manifest(proposal))
        expected_preview = self._reversal_preview_hash(proposal)
        if proposal.reversal_preview_sha256 != expected_preview:
            return False, "hash da previsao nao corresponde"
        if proposal.reversal_preview_validation_sha256 and proposal.reversal_preview_validation_sha256 != expected_validation:
            return False, "validacao da previsao invalidada"
        if proposal.reversal_review_sha256 and proposal.reversal_review_sha256 != expected_review:
            return False, "motivo de reversao invalidado"
        if proposal.reversal_manifest_sha256 and proposal.reversal_manifest_sha256 != expected_manifest:
            return False, "manifesto de reversao invalidado"
        return True, ""

    def _reversal_currently_valid(self, proposal: EngineeringProposal) -> tuple[bool, str]:
        if not proposal.reversal_approval_valid:
            return False, proposal.reversal_approval_invalid_reason or "aprovacao de reversao nao registrada"
        expected = {
            "validation": self._sha_reversal_validation(proposal.reversal_preview_validation),
            "review": self._sha_text(proposal.reversal_reason),
            "manifest": self._sha_json(self._reversal_manifest(proposal)),
            "base": proposal.reversal_base_commit,
            "preview": self._reversal_preview_hash(proposal),
            "preview_base": proposal.reversal_preview_base_head,
            "preview_target": proposal.reversal_preview_target_commit,
        }
        actual = {
            "validation": proposal.approved_reversal_validation_sha256 or proposal.reversal_approved_validation_sha256,
            "review": proposal.reversal_approved_review_sha256,
            "manifest": proposal.reversal_approved_manifest_sha256,
            "base": proposal.reversal_approved_base_commit,
            "preview": proposal.approved_reversal_preview_sha256,
            "preview_base": proposal.approved_reversal_base_head,
            "preview_target": proposal.approved_reversal_target_commit,
        }
        for key, value in expected.items():
            if value != actual[key]:
                return False, f"aprovacao de reversao invalidada por mudanca em {key}"
        return True, ""

    def _reversal_manifest(self, proposal: EngineeringProposal) -> dict:
        return {
            "proposal_id": proposal.id,
            "target_commit": proposal.reversal_target_commit,
            "base_commit": proposal.reversal_base_commit,
            "reason_sha256": self._sha_text(proposal.reversal_reason),
            "files": self._commit_files(proposal.reversal_target_commit) if proposal.reversal_target_commit else [],
        }

    def _commit_is_in_main(self, commit: str) -> bool:
        return self.workspace._run(("git", "merge-base", "--is-ancestor", commit, "main"), self.root, 30).returncode == 0

    def _find_revert_commit(self, commit: str) -> str:
        result = self._git(("log", "--format=%H", "--grep", f"This reverts commit {commit}"), cwd=self.root, timeout=30)
        return result.stdout.splitlines()[0] if result.stdout.splitlines() else ""

    def _reverted_idempotent_response(self, proposal: EngineeringProposal) -> str:
        return "\n".join([
            "Proposta ja revertida.",
            f"- Commit alvo: {proposal.reversal_target_commit}",
            f"- Commit de reversao: {proposal.reversal_commit}",
            f"- Main atual: {self.workspace.head()}",
            "- Novo revert executado: nao",
        ])

    def _finalize_already_reverted(self, proposal: EngineeringProposal) -> str:
        previous = proposal.state
        try:
            proposal.reversal_post_validation = self._post_reversal_validation(proposal)
            if not all(item.get("passed") for item in proposal.reversal_post_validation):
                raise RuntimeError("VALIDACAO_RECONCILIACAO_REVERSAO_REPROVADA")
            proposal.reversal_completed_at = datetime.now().isoformat(timespec="seconds")
            proposal.reversal_partial = False
            proposal.state = "REVERTIDA"
            self._event(proposal, "reversao reconciliada sem novo revert", previous, proposal.state)
            self._save()
            return "\n".join([
                "Reversao ja estava criada na main; estado reconciliado.",
                f"- Commit de reversao: {proposal.reversal_commit}",
                "- Novo revert executado: nao",
                f"- Validacao posterior: {self._checks_status(proposal.reversal_post_validation)}",
                "- Estado final: REVERTIDA",
            ])
        except Exception as exc:
            proposal.state = "REVERSAO_PARCIAL"
            proposal.reversal_partial = True
            proposal.reversal_error = self.workspace.sanitize(str(exc))
            self._event(proposal, "reconciliacao de reversao bloqueada", previous, proposal.state)
            self._save()
            return f"Reversao parcial registrada: {proposal.reversal_error}."

    def _commit_files(self, commit: str) -> list[str]:
        """Return files changed by a recorded commit."""
        return self._git(("diff-tree", "--no-commit-id", "--name-only", "-r", commit), cwd=self.root, timeout=30).stdout.splitlines()

    def _check_command(self, name: str, command: tuple[str, ...], timeout: int, cwd: Path) -> CheckResult:
        try:
            result = self.workspace._run(command, cwd, timeout)
            output = self.workspace.sanitize("\n".join(value for value in (result.stdout, result.stderr) if value))
            return CheckResult(name, " ".join(command), result.returncode, 0, output)
        except subprocess.TimeoutExpired:
            return CheckResult(name, " ".join(command), 124, 0, "Tempo limite excedido.")

    def _checks_status(self, checks: list[dict]) -> str:
        """Summarize persisted validation checks for display."""
        if not checks:
            return "Informacao nao registrada."
        failed = [item.get("name", "?") for item in checks if not item.get("passed")]
        if failed:
            return "REPROVADO: " + ", ".join(failed[:4])
        return f"APROVADO ({len(checks)} checks)"

    def _required_checks_passed(self, proposal: EngineeringProposal) -> bool:
        required = {"pytest", "ruff", "compileall", "pip check", "smoke"}
        passed = {
            item.get("name")
            for item in proposal.validation
            if item.get("phase") == "patch" and item.get("passed")
        }
        return required.issubset(passed)

    def _review_blocks(self, review: str) -> bool:
        lowered = (review or "").lower()
        return any(term in lowered for term in ("bloquear", "risco alto", "credencial exposta", "segredo exposto"))

    def _approved_files(self, proposal: EngineeringProposal) -> list[str]:
        files: list[str] = []
        for operation in proposal.patch_manifest.get("operations", []):
            rel = operation.get("file", "")
            if rel and rel not in files:
                files.append(rel)
        return files

    def _proposal_branch(self, proposal_id: str) -> str:
        if not re.fullmatch(r"DEV-\d{8}-[A-F0-9]{6}", proposal_id):
            raise RuntimeError("ID_DE_PROPOSTA_INVALIDO")
        return f"aya-dev/{proposal_id}"

    def _branch_exists(self, branch: str) -> bool:
        result = self._git(("branch", "--list", branch), cwd=self.root, timeout=30)
        return bool(result.stdout.strip())

    def _ensure_git_identity(self) -> None:
        name = self._git(("config", "user.name"), cwd=self.root, timeout=15)
        email = self._git(("config", "user.email"), cwd=self.root, timeout=15)
        if name.returncode != 0 or not name.stdout.strip() or email.returncode != 0 or not email.stdout.strip():
            raise RuntimeError("IDENTIDADE_GIT_AUSENTE")

    def _git(self, args: tuple[str, ...], cwd: Path, timeout: int):
        result = self.workspace._run(("git", *args), cwd, timeout)
        if result.returncode != 0 and args[:2] not in {("branch", "--list"), ("config", "user.name"), ("config", "user.email")}:
            raise RuntimeError(self.workspace.sanitize(result.stderr or result.stdout))
        return result

    def _sha_text(self, text: str) -> str:
        return hashlib.sha256((text or "").encode("utf-8")).hexdigest()

    def _sha_json(self, value) -> str:
        payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return self._sha_text(payload)

    def _short_title(self, title: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9 _.-]+", "", title).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned[:72] or "patch supervisionado"
