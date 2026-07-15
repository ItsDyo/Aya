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
AUTONOMY_MODES = {"DESLIGADA", "OBSERVAR", "PREPARAR_SUPERVISIONADO"}
AUTONOMY_MIN_CASES = 3
AUTONOMY_MIN_SUCCESSES = 2
AUTONOMY_ALLOWED_OPERATIONS = {"insert_docstring", "replace_exact"}
AUTONOMY_BLOCKED_TERMS = {
    ".env", "credencial", "autenticacao", "permissao", "seguranca", "security", "tailscale", "remoto",
    "banco", "database", "aya/data", "sqlite", "schema", "migracao", "memoria", "rag", "backup", "voz", "subprocess",
    "git", "release", "dependencia",
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
    approved_reversal_base_head: str = ""
    approved_reversal_target_commit: str = ""
    approved_reversal_validation_sha256: str = ""


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
        self._candidate_cache: list[AutonomousCandidate] | None = None
        self._candidate_cache_head = ""
        self._candidate_cache_proposals = -1

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
            proposal.review_result = "Validacao do patch reprovada."
            self._record_failure(proposal, "testes", "validacao reprovada", self._format_checks(results, proposal.state))
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
            f"- Candidatos atuais: {metrics['current']}",
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
            f"- Candidatos atuais: {metrics['current']}",
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
        scope = (scope or "atuais").lower().strip()
        if "obsoleto" in scope:
            candidates = [candidate for candidate in candidates if candidate.stale]
        elif "historico" in scope:
            return self.capability_report("")
        else:
            candidates = [candidate for candidate in candidates if not candidate.stale]
        if not candidates:
            return "Candidatos autonomos: nenhum candidato real detectado."
        lines = ["Candidatos autonomos do Aya Dev:"]
        for item in candidates[:20]:
            lines.append(
                f"- {item.candidate_id} [{item.status}/{item.eligibility}] rota={item.route} score={item.score} "
                f"risco={item.risk} {item.operation_type}: {item.title}"
            )
            lines.append(f"  head={item.project_head[:12]} arquivo={item.file} simbolo={item.symbol or 'n/a'}")
            if item.blocked_reasons:
                lines.append(f"  bloqueios: {'; '.join(item.blocked_reasons)}")
            if item.stale:
                lines.append(f"  obsoleto: {item.stale_reason}")
        return "\n".join(lines)

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

    def observe_cycle(self) -> str:
        before = self.workspace.git_state()
        candidates = self._autonomous_candidates()
        after = self.workspace.git_state()
        metrics = self._candidate_queue_metrics(candidates)
        return "\n".join([
            "Observacao autonoma somente leitura:",
            f"- Git antes: {before.message}",
            f"- Git depois: {after.message}",
            "- Modelo chamado: nao",
            "- Worktree criado: nao",
            "- Codigo alterado: nao",
            f"- Candidatos atuais: {metrics['current']}",
            f"- Duplicados bloqueados: {metrics['duplicates']}",
            f"- Obsoletos: {metrics['stale']}",
            f"- Elegiveis: {metrics['eligible']}",
            f"- Bloqueados: {metrics['blocked']}",
        ])

    def renew_candidates(self) -> str:
        candidates = self._autonomous_candidates(force=True)
        metrics = self._candidate_queue_metrics(candidates)
        return "\n".join([
            "Renovacao de candidatos concluida sem preparar patch:",
            f"- HEAD: {self._safe_head()}",
            f"- Candidatos atuais reais: {metrics['current']}",
            f"- Duplicados bloqueados: {metrics['duplicates']}",
            f"- Obsoletos: {metrics['stale']}",
            f"- Elegiveis: {metrics['eligible']}",
            f"- Bloqueados: {metrics['blocked']}",
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
        for operation in sorted(stats):
            if filter_kind == "operacao" and operation != filter_value_normalized:
                continue
            item = self._empty_operation_stats() | stats[operation]
            level = self._capability_level(operation, item)
            lines.append(
                f"- Operacao {operation}: nivel={level}; total={item['total']}; production_real={item['production_real']}; "
                f"test_fixture={item['test_fixture']}; legacy_import={item['legacy_import']}; unknown={item['unknown']}; "
                f"sucessos={item['success']}; falhas={item['fail']}; inconclusivos={item['inconclusive']}; "
                f"rejeitados={item['rejected']}; cancelados={item['cancelled']}; escalados={item['escalated']}; "
                f"integrados={item['integrated']}; revertidos={item['reverted']}; primeira_tentativa={item['first_attempt_success']}"
            )
        return "\n".join(lines)

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
            lines.append(f"- {result.name}: {'APROVADO' if result.passed else 'REPROVADO'} (codigo={result.exit_code}, {result.duration_ms}ms)")
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
        if item["production_real"] < AUTONOMY_MIN_CASES or item["success"] < AUTONOMY_MIN_SUCCESSES:
            return "DADOS_INSUFICIENTES"
        if item["fail"] or item["escalated"]:
            return "BLOQUEADO_POR_FALHAS"
        return "ELEGIVEL"

    def _capability_level(self, operation: str, item: dict[str, int]) -> str:
        if item["total"] == 0:
            return "SEM_DADOS"
        status = self._operation_policy_status(operation, item)
        if status == "DADOS_INSUFICIENTES":
            return "DADOS_INSUFICIENTES"
        if item["fail"] or item["reverted"] or item["escalated"]:
            return "ESCALONAMENTO_RECOMENDADO"
        if item["production_real"] >= AUTONOMY_MIN_CASES and item["success"] >= AUTONOMY_MIN_SUCCESSES:
            return "SUPORTADA_LOCALMENTE"
        return "EXPERIMENTAL"

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

    def _autonomous_candidates(self, *, force: bool = False) -> list[AutonomousCandidate]:
        head = self._safe_head()
        proposal_count = len(self.proposals)
        if (
            not force
            and self._candidate_cache is not None
            and self._candidate_cache_head == head
            and self._candidate_cache_proposals == proposal_count
        ):
            return self._validate_candidate_list(self._candidate_cache)
        candidates: list[AutonomousCandidate] = []
        stats = self._operation_stats()
        for entry in self.index.build():
            if entry.path.startswith("tests/") or self._candidate_path_blocked(entry.path):
                continue
            candidates.extend(self._docstring_candidates(entry, stats))
            candidates.extend(self._unused_import_candidates(entry, stats))
        self._candidate_cache = candidates
        self._candidate_cache_head = head
        self._candidate_cache_proposals = proposal_count
        return self._validate_candidate_list(candidates)

    def _validate_candidate_list(self, candidates: list[AutonomousCandidate]) -> list[AutonomousCandidate]:
        seen: dict[str, AutonomousCandidate] = {}
        deduplicated: list[AutonomousCandidate] = []
        for candidate in candidates:
            candidate = self._validate_current_candidate(candidate)
            if candidate.deduplication_key in seen:
                duplicate = self._replace_candidate_status(candidate, "BLOQUEADO", ["DUPLICADO"], route="CODEX_REVIEW_RECOMMENDED")
                deduplicated.append(duplicate)
                continue
            seen[candidate.deduplication_key] = candidate
            deduplicated.append(candidate)
        deduplicated.sort(key=lambda item: (-item.score, item.risk, len(item.files), item.estimated_changed_lines, item.candidate_id))
        return deduplicated

    def _docstring_candidates(self, entry: TechnicalFile, stats: dict[str, dict[str, int]]) -> list[AutonomousCandidate]:
        path = self.root / entry.path
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
        except (OSError, SyntaxError):
            return []
        parents = self._ast_parents(tree)
        candidates: list[AutonomousCandidate] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if node.name.startswith("_") or ast.get_docstring(node):
                continue
            symbol = self._qualified_symbol(tree, node, parents)
            if not symbol:
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
            ))
        return candidates

    def _unused_import_candidates(self, entry: TechnicalFile, stats: dict[str, dict[str, int]]) -> list[AutonomousCandidate]:
        path = self.root / entry.path
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            tree = ast.parse(text)
        except (OSError, SyntaxError):
            return []
        used_names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        candidates: list[AutonomousCandidate] = []
        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, ast.Import) or len(node.names) != 1:
                continue
            alias = node.names[0]
            local_name = alias.asname or alias.name.split(".", 1)[0]
            if local_name in used_names:
                continue
            line = text.splitlines()[node.lineno - 1]
            candidates.append(self._build_candidate(
                source="ast:unused_import",
                title=f"Remover import nao usado {alias.name}",
                problem=f"O import {alias.name} nao e referenciado no arquivo.",
                evidence=[f"{entry.path}:{node.lineno} import nao usado por varredura AST local"],
                category="import_nao_usado",
                operation_type="replace_exact",
                files=[entry.path],
                symbols=[],
                estimated_changed_lines=1,
                required_tests=entry.related_tests[:2],
                reason="import nao referenciado por varredura AST local",
                expected_change=f"remover linha exata: {line.strip()}",
                symbol_signature="",
                stats=stats,
            ))
        return candidates

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
    ) -> AutonomousCandidate:
        head = self._safe_head()
        file_sha256 = self._file_sha256(files[0]) if files else ""
        symbol = symbols[0] if symbols else ""
        risk = self.classify_risk(problem, files, title)
        lessons = self._candidate_lessons(files, operation_type)
        similar = self._similar_proposals(files, symbols)
        blocked = self._candidate_blocked_reasons(files, category, operation_type, risk, estimated_changed_lines)
        operation_stats = self._empty_operation_stats() | stats.get(operation_type, {})
        policy = self._operation_policy_status(operation_type, operation_stats)
        if policy != "ELEGIVEL" and not blocked:
            blocked.append(policy)
        eligibility = "ELEGIVEL" if not blocked else ("DADOS_INSUFICIENTES" if blocked == ["DADOS_INSUFICIENTES"] else "BLOQUEADO")
        score, score_explanation = self._candidate_score(
            evidence=evidence,
            required_tests=required_tests,
            stats=operation_stats,
            files=files,
            changed_lines=estimated_changed_lines,
            blocked=blocked,
        )
        deduplication_key = self._candidate_dedup_key(head, operation_type, files[0], symbol, expected_change)
        route = self._route_from_candidate_state(eligibility, blocked, risk, operation_type, operation_stats, stale=False)
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
            status="ELEGIVEL" if eligibility == "ELEGIVEL" else "BLOQUEADO",
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

    def _candidate_path_blocked(self, file: str) -> bool:
        lowered = file.lower()
        return any(term in lowered for term in AUTONOMY_BLOCKED_TERMS) or self.workspace._path_error(file) != ""

    def _candidate_dedup_key(self, head: str, operation: str, file: str, symbol: str, goal: str) -> str:
        normalized = re.sub(r"\s+", " ", goal.lower()).strip()
        return self._sha_text("\n".join([head, operation, file, symbol, normalized]))

    def _signature_for_symbol(self, entry: TechnicalFile, symbol: str) -> str:
        name = symbol.split(".")[-1]
        return next((signature for signature in entry.signatures if signature.startswith(f"{name}(")), "")

    def _validate_current_candidate(self, candidate: AutonomousCandidate) -> AutonomousCandidate:
        if candidate.project_head != self._safe_head():
            return self._stale_candidate(candidate, "HEAD mudou desde a deteccao.")
        path = self.root / candidate.file
        if not path.exists():
            return self._stale_candidate(candidate, "arquivo nao existe mais.")
        try:
            current_hash = self._file_sha256(candidate.file)
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
        return self._replace_candidate_status(candidate, "OBSOLETO", ["OBSOLETO"], stale=True, stale_reason=reason, route="CODEX_REVIEW_RECOMMENDED")

    def _replace_candidate_status(
        self,
        candidate: AutonomousCandidate,
        status: str,
        blocked_reasons: list[str],
        *,
        stale: bool | None = None,
        stale_reason: str | None = None,
        route: str | None = None,
    ) -> AutonomousCandidate:
        data = asdict(candidate)
        data["status"] = status
        data["eligibility"] = "ELEGIVEL" if status == "ELEGIVEL" and not blocked_reasons else "BLOQUEADO"
        data["blocked_reasons"] = [*candidate.blocked_reasons, *blocked_reasons]
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
        if eligibility == "DADOS_INSUFICIENTES" or self._capability_level(operation_type, stats) in {"SEM_DADOS", "DADOS_INSUFICIENTES"}:
            return "INSUFFICIENT_DATA"
        if blocked:
            return "CODEX_REVIEW_RECOMMENDED"
        return "LOCAL_SUPERVISED"

    def _candidate_queue_metrics(self, candidates: list[AutonomousCandidate]) -> dict[str, int]:
        historical = sum(item["total"] for item in self._operation_stats().values())
        return {
            "historical": historical,
            "current": sum(1 for item in candidates if not item.stale),
            "duplicates": sum(1 for item in candidates if "DUPLICADO" in item.blocked_reasons),
            "stale": sum(1 for item in candidates if item.stale),
            "eligible": sum(1 for item in candidates if item.eligibility == "ELEGIVEL" and not item.stale),
            "blocked": sum(1 for item in candidates if item.eligibility != "ELEGIVEL"),
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
        candidates = [candidate for candidate in self._autonomous_candidates() if candidate.eligibility == "ELEGIVEL"]
        if not candidates:
            return None
        candidates.sort(key=lambda item: (-item.score, item.risk, len(item.files), item.estimated_changed_lines, item.candidate_id))
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
                "content": f"Document {candidate.symbols[0]}.",
            }
        if candidate.operation_type == "replace_exact":
            entry = self._unused_import_payload(candidate)
            return {"type": "replace_exact", **entry}
        raise StructuredPatchError("Operacao autonoma nao suportada.")

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
            status = "APROVADO" if item.get("passed") else "REPROVADO"
            lines.append(f"- {item.get('phase', '?')} {item.get('name', '?')}: {status}")
        return "\n".join(lines)

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
