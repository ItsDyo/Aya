from __future__ import annotations

import html
import json
import threading
from dataclasses import dataclass

from aya.core.assistant import Assistant
from aya.core.aya_dev import EngineeringProposal
from aya.core.permissions import AccessChannel, Capability


FILTERS = {
    "todas": None,
    "aguardando aprovacao": {"AGUARDANDO_APROVACAO", "AGUARDANDO_APROVACAO_REVERSAO"},
    "commit pronto": {"COMMIT_PRONTO"},
    "integrada": {"INTEGRADA"},
    "falhou": {"FALHOU", "REVERSAO_FALHOU"},
    "reversao solicitada": {"REVERSAO_SOLICITADA"},
    "previsao pronta": {"PREVISAO_REVERSAO_PRONTA", "AGUARDANDO_APROVACAO_REVERSAO"},
    "revertida": {"REVERTIDA"},
    "bloqueada": {"INTEGRACAO_BLOQUEADA", "REVERSAO_BLOQUEADA", "PREVISAO_REVERSAO_BLOQUEADA", "REVERSAO_PARCIAL"},
}

DIFF_LIMIT = 9000


@dataclass(frozen=True)
class AyaDevViewModel:
    proposal_id: str
    state: str
    title: str
    summary: str
    overview: str
    plan: str
    diff: str
    tests: str
    approval: str
    integration: str
    reversal: str
    actions: dict[str, bool]
    expected_approval: str
    expected_integration: str
    expected_reversal_approval: str
    expected_revert: str


class AyaDevPanel:
    """View model e callbacks seguros para o painel Aya Dev."""

    def __init__(self, assistant: Assistant, channel: AccessChannel = AccessChannel.LOCAL_GRADIO):
        self.aya = assistant
        self.channel = channel
        self._locks: set[str] = set()
        self._guard = threading.Lock()

    def list_choices(self, state_filter: str = "todas") -> list[str]:
        states = FILTERS.get(state_filter or "todas")
        proposals = sorted(self.aya.aya_dev.proposals.values(), key=lambda item: item.created_at, reverse=True)
        choices = []
        for proposal in proposals:
            if states and proposal.state not in states:
                continue
            choices.append(self._choice(proposal))
        return choices

    def refresh(self, state_filter: str = "todas") -> tuple[list[str], str]:
        choices = self.list_choices(state_filter)
        return choices, choices[0] if choices else ""

    def autonomy_overview(self) -> tuple[str, str, str, str]:
        return (
            self.aya.aya_dev.autonomy_status(),
            self.aya.aya_dev.evaluate_autonomy(),
            self.aya.aya_dev.list_candidates("atuais"),
            self.aya.aya_dev.observe_cycle(),
        )

    def autonomy_capability(self, filter_text: str = "") -> str:
        return self.aya.aya_dev.capability_report(filter_text)

    def autonomy_candidates(self, scope: str = "") -> str:
        return self.aya.aya_dev.list_candidates(scope)

    def autonomy_route(self, candidate_id: str) -> tuple[str, str]:
        candidate_id = (candidate_id or "").strip()
        if not candidate_id:
            return "Informe um candidato.", "Informe um candidato."
        return self.aya.aya_dev.route_candidate(candidate_id), self.aya.aya_dev.explain_route(candidate_id)

    def calibration_overview(self) -> tuple[str, str]:
        return self.aya.aya_dev.list_experiments(), self.aya.aya_dev.experiment_results()

    def create_calibration_experiment(self, candidate_id: str) -> str:
        if not self._can_execute():
            return self.aya.permissions.denial_message(self.channel, Capability.SYSTEM_ADMIN)
        candidate_id = (candidate_id or "").strip()
        if not candidate_id:
            return "Informe um candidato."
        return self.aya.aya_dev.create_calibration_experiment(candidate_id)

    def run_calibration_experiment(self, experiment_id: str, confirmation: str) -> str:
        if not self._can_execute():
            return self.aya.permissions.denial_message(self.channel, Capability.SYSTEM_ADMIN)
        experiment_id = (experiment_id or "").strip()
        if not experiment_id:
            return "Informe um experimento."
        return self.aya.aya_dev.execute_calibration_experiment(f"{experiment_id} | {confirmation or ''}")

    def run_safe_autonomy_cycle(self, confirmation: str) -> str:
        if not self._can_execute():
            return self.aya.permissions.denial_message(self.channel, Capability.SYSTEM_ADMIN)
        if (confirmation or "").strip() != "EXECUTAR CICLO SEGURO":
            return "Confirmacao incorreta. Digite exatamente: EXECUTAR CICLO SEGURO"
        return self.aya.aya_dev.execute_safe_autonomous_cycle()

    def details(self, selected: str, expand_diff: bool = False) -> tuple[str, str, str, str, str, str, str, str]:
        proposal = self._selected_proposal(selected)
        if not proposal:
            empty = "Informacao nao registrada."
            return empty, empty, empty, empty, empty, empty, empty, empty
        vm = self.view_model(proposal.id, expand_diff)
        return vm.overview, vm.plan, vm.diff, vm.tests, vm.approval, vm.integration, vm.reversal, vm.summary

    def view_model(self, proposal_id: str, expand_diff: bool = False) -> AyaDevViewModel:
        proposal = self.aya.aya_dev._get(proposal_id)
        diff_text = proposal.patch or ""
        if not diff_text:
            diff_text = "Informacao nao registrada."
        rendered_diff = render_diff(diff_text, expand=expand_diff)
        expected_reversal = ""
        if proposal.reversal_preview_sha256:
            expected_reversal = f"REV-{proposal.reversal_preview_sha256[:8]}"
        return AyaDevViewModel(
            proposal_id=proposal.id,
            state=proposal.state,
            title=proposal.title,
            summary=f"{proposal.id} [{proposal.state}] risco={proposal.risk}: {proposal.title}",
            overview=self._overview(proposal),
            plan=self._plan(proposal),
            diff=rendered_diff,
            tests=self._tests(proposal),
            approval=self._approval(proposal),
            integration=self.aya.aya_dev.integracao(proposal.id),
            reversal=self.aya.aya_dev.reversao(proposal.id),
            actions=self.available_actions(proposal),
            expected_approval=f"APROVAR {proposal.id}",
            expected_integration=f"INTEGRAR {proposal.id}",
            expected_reversal_approval=expected_reversal,
            expected_revert=f"REVERTER {proposal.id}",
        )

    def available_actions(self, proposal: EngineeringProposal) -> dict[str, bool]:
        return {
            "planejar": proposal.state == "PROPOSTA",
            "preparar": proposal.state in {"PLANEJADA", "FALHOU"},
            "revisar": proposal.state == "EM_TESTE",
            "testar": proposal.state == "EM_TESTE",
            "aprovar": proposal.state == "AGUARDANDO_APROVACAO",
            "rejeitar": proposal.state not in {"INTEGRADA", "REVERTIDA"},
            "aplicar": proposal.state == "APROVADA",
            "integrar": proposal.state == "COMMIT_PRONTO",
            "solicitar_reversao": proposal.state == "INTEGRADA",
            "prever_reversao": proposal.state in {"REVERSAO_SOLICITADA", "PREVISAO_REVERSAO_BLOQUEADA"},
            "aprovar_reversao": proposal.state == "AGUARDANDO_APROVACAO_REVERSAO",
            "reverter": proposal.state == "REVERSAO_APROVADA",
            "descartar": bool(proposal.workspace),
        }

    def run_action(
        self,
        selected: str,
        action: str,
        confirmation: str = "",
        reversal_reason: str = "",
    ) -> tuple[str, str, str, str, str, str, str, str, str]:
        proposal = self._selected_proposal(selected)
        if not proposal:
            empty = "Selecione uma proposta."
            return empty, empty, empty, empty, empty, empty, empty, empty, empty
        if not self._can_execute():
            denial = self.aya.permissions.denial_message(self.channel, Capability.SYSTEM_ADMIN)
            return (denial, *self.details(selected))
        if not self._acquire(proposal.id):
            return ("Acao bloqueada: ja existe uma operacao em andamento para esta proposta.", *self.details(selected))
        try:
            response = self._dispatch_action(proposal, action, confirmation, reversal_reason)
        except Exception as exc:
            response = f"Falha na acao visual: {exc}"
        finally:
            self._release(proposal.id)
        selected_after = self._choice(self.aya.aya_dev._get(proposal.id))
        return (response, *self.details(selected_after))

    def _dispatch_action(self, proposal: EngineeringProposal, action: str, confirmation: str, reversal_reason: str) -> str:
        service = self.aya.aya_dev
        if action == "planejar":
            return service.planejar(proposal.id)
        if action == "preparar":
            return service.preparar(proposal.id)
        if action == "revisar":
            return service.revisar(proposal.id)
        if action == "testar":
            return service.testar(proposal.id)
        if action == "aprovar":
            expected = f"APROVAR {proposal.id}"
            if (confirmation or "").strip() != expected:
                return f"Confirmacao incorreta. Digite exatamente: {expected}"
            return service.aprovar(proposal.id)
        if action == "rejeitar":
            return service.rejeitar(f"{proposal.id} | rejeitada pela interface")
        if action == "aplicar":
            return service.aplicar(proposal.id)
        if action == "integrar":
            expected = f"INTEGRAR {proposal.id}"
            if (confirmation or "").strip() != expected:
                return f"Confirmacao incorreta. Digite exatamente: {expected}"
            return service.integrar(proposal.id)
        if action == "solicitar_reversao":
            if not (reversal_reason or "").strip():
                return "Informe um motivo para solicitar reversao."
            return service.solicitar_reversao(f"{proposal.id} {reversal_reason.strip()}")
        if action == "prever_reversao":
            return service.prever_reversao(proposal.id)
        if action == "aprovar_reversao":
            expected = f"REV-{proposal.reversal_preview_sha256[:8]}" if proposal.reversal_preview_sha256 else ""
            if not expected or (confirmation or "").strip() != expected:
                return f"Codigo de reversao incorreto. Digite exatamente: {expected or 'gere uma previsao valida primeiro'}"
            return service.aprovar_reversao(proposal.id)
        if action == "reverter":
            expected = f"REVERTER {proposal.id}"
            if (confirmation or "").strip() != expected:
                return f"Confirmacao incorreta. Digite exatamente: {expected}"
            return service.reverter(proposal.id)
        if action == "descartar":
            return service.descartar(proposal.id)
        return "Acao desconhecida."

    def _overview(self, proposal: EngineeringProposal) -> str:
        return "\n".join([
            f"ID: {proposal.id}",
            f"Estado: {proposal.state}",
            f"Titulo: {proposal.title}",
            f"Problema: {proposal.problem}",
            f"Evidencias: {' | '.join(proposal.evidence) or 'Informacao nao registrada.'}",
            f"Risco: {proposal.risk}",
            f"Arquivos: {', '.join(proposal.related_files) or 'Informacao nao registrada.'}",
            f"Simbolos: {', '.join(proposal.related_symbols) or 'Informacao nao registrada.'}",
            f"Tentativas: {proposal.attempts}",
            f"Worktree: {proposal.workspace or proposal.workspace_path or 'Informacao nao registrada.'}",
        ])

    def _plan(self, proposal: EngineeringProposal) -> str:
        manifest = json.dumps(proposal.patch_manifest, ensure_ascii=True, indent=2) if proposal.patch_manifest else "Informacao nao registrada."
        return "\n".join([
            "Plano sugerido - nao comprova execucao:",
            proposal.suggested_change or "Informacao nao registrada.",
            "",
            f"Base commit: {proposal.base_commit or 'Informacao nao registrada.'}",
            f"Hash do manifesto: {proposal.approved_manifest_sha256 or self.aya.aya_dev._sha_json(proposal.patch_manifest) if proposal.patch_manifest else 'Informacao nao registrada.'}",
            f"Arquivos autorizados: {', '.join(self.aya.aya_dev._approved_files(proposal)) or 'Informacao nao registrada.'}",
            "",
            "Manifesto estruturado:",
            manifest,
        ])

    def _tests(self, proposal: EngineeringProposal) -> str:
        review_status = "bloqueadora" if self.aya.aya_dev._review_blocks(proposal.review_result) else "consultiva"
        return "\n".join([
            "Validacoes:",
            self.aya.aya_dev._validation_summary(proposal),
            "",
            "Revisao local:",
            proposal.review_result or "Informacao nao registrada.",
            f"Tipo da revisao: {review_status}",
        ])

    def _approval(self, proposal: EngineeringProposal) -> str:
        return "\n".join([
            "Aprovacao e commit:",
            self.aya.aya_dev._approval_summary(proposal),
            "",
            self.aya.aya_dev.commit(proposal.id),
        ])

    def _selected_proposal(self, selected: str) -> EngineeringProposal | None:
        proposal_id = parse_choice_id(selected)
        if not proposal_id:
            return None
        try:
            return self.aya.aya_dev._get(proposal_id)
        except ValueError:
            return None

    def _choice(self, proposal: EngineeringProposal) -> str:
        return f"{proposal.id} | {proposal.state} | risco={proposal.risk} | tentativas={proposal.attempts} | {proposal.created_at} | {proposal.title}"

    def _can_execute(self) -> bool:
        return self.aya.permissions.allows(self.channel, Capability.SYSTEM_ADMIN)

    def _acquire(self, proposal_id: str) -> bool:
        with self._guard:
            if proposal_id in self._locks:
                return False
            self._locks.add(proposal_id)
            return True

    def _release(self, proposal_id: str) -> None:
        with self._guard:
            self._locks.discard(proposal_id)


def parse_choice_id(value: str) -> str:
    text = (value or "").strip()
    return text.split("|", 1)[0].strip() if text else ""


def render_diff(diff: str, *, expand: bool = False) -> str:
    escaped = html.escape(diff or "Informacao nao registrada.")
    if expand or len(escaped) <= DIFF_LIMIT:
        return escaped
    return (
        escaped[:DIFF_LIMIT]
        + "\n\n[Diff truncado visualmente. Use a opcao de expandir para ver o conteudo completo.]"
    )
