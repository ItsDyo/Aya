from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from aya.config import MODEL_CONFIG
from aya.core.dev_index import TechnicalFile, TechnicalIndex
from aya.core.dev_workspace import CheckResult, DevWorkspace
from aya.core.llm import ChatClient
from aya.core.project_tools import ProjectTools


PROPOSAL_STATES = {
    "DETECTADA", "PROPOSTA", "PLANEJADA", "PREPARANDO", "EM_TESTE",
    "AGUARDANDO_APROVACAO", "APROVADA", "REJEITADA", "FALHOU",
    "APLICADA", "REVERTIDA",
}
RISK_ORDER = {"baixo": 0, "medio": 1, "alto": 2}
HIGH_RISK_TERMS = {
    ".env", "credencial", "autenticacao", "tailscale", "remoto", "banco", "database", "sqlite", "schema",
    "migracao", "memoria", "excluir", "comando", "privacidade", "seguranca", "backup", "rag",
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
        workspace_root: str | Path | None = None,
        max_files: int = 4,
        max_changed_lines: int = 250,
        max_attempts: int = 2,
    ):
        self.root = Path(root).resolve()
        data_dir = self.root / "data_local"
        self.storage_path = Path(storage_path or data_dir / "aya_dev_history.json")
        self.index = TechnicalIndex(self.root, index_path or data_dir / "aya_dev_index.json")
        self.workspace = DevWorkspace(self.root, workspace_root)
        self.llm = llm
        self.project_tools = project_tools
        self.primary_model = primary_model
        self.reviewer_model = reviewer_model
        self.max_files = max_files
        self.max_changed_lines = max_changed_lines
        self.max_attempts = max_attempts
        self.proposals = self._load()

    def execute(self, payload: str) -> str:
        action, _, argument = (payload or "status").strip().partition(" ")
        action = action.lower() or "status"
        handlers = {
            "status": self.status,
            "mapear": self.map_project,
            "auditar": self.audit,
            "propostas": self.list_proposals,
            "historico": self.history,
        }
        if action in handlers:
            return handlers[action]()
        if action in {
            "mostrar", "falha", "planejar", "preparar", "revisar", "testar", "diff",
            "aprovar", "rejeitar", "descartar", "aplicar", "integrar", "reverter", "pacote-codex",
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
            proposal.state = "EM_TESTE"
            self._event(proposal, "patch preparado somente no worktree", "PREPARANDO", proposal.state)
            self._save()
            return f"Patch preparado no ambiente isolado ({inspection.changed_lines} linhas, {len(inspection.files)} arquivo(s))."
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
        previous = proposal.state
        proposal.state = "APROVADA"
        self._event(proposal, "aprovacao humana registrada; patch nao aplicado", previous, proposal.state)
        self._save()
        return "Aprovacao registrada. Nenhum patch foi aplicado ao projeto principal."

    def aplicar(self, proposal_id: str) -> str:
        proposal = self._get(proposal_id)
        if proposal.state != "APROVADA":
            return "Aplicacao bloqueada: aprove explicitamente antes com /aya-dev aprovar ID."
        return "Aplicacao supervisionada ainda nao habilitada neste ciclo."

    def integrar(self, proposal_id: str) -> str:
        self._get(proposal_id)
        return "Integracao bloqueada: ciclo de integracao ainda nao habilitado."

    def reverter(self, proposal_id: str) -> str:
        self._get(proposal_id)
        return "Reversao bloqueada: nenhum commit aplicado por Aya Dev neste ciclo."

    def rejeitar(self, proposal_id: str) -> str:
        proposal = self._get(proposal_id)
        previous = proposal.state
        proposal.state = "REJEITADA"
        self._event(proposal, "rejeicao humana registrada", previous, proposal.state)
        self._save()
        return f"Proposta {proposal.id} rejeitada."

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

    def _related_tests(self, proposal: EngineeringProposal) -> list[str]:
        indexed = {item.path: item for item in self.index.build()}
        tests = [path for path in proposal.related_files if path.startswith("tests/")]
        for path in proposal.related_files:
            entry = indexed.get(path)
            if entry:
                tests.extend(entry.related_tests)
        return list(dict.fromkeys(tests))[:4]

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
        temporary.replace(self.storage_path)

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
