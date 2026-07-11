from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from aya.core.log_analysis import LogSummary, analyze_logs
from aya.core.project_tools import ProjectTools
from aya.data.database import Database
from aya.paths import LOGS_DIR


@dataclass(frozen=True)
class AdviceState:
    quick_check: str
    conversations: int
    knowledge: int
    memories: int
    conflicts: int
    pending_learning: int
    pending_exercises: int
    rag_status: str
    project_audit: str
    diagnostics: str
    release_history: str
    latest_release: str
    backup_status: str
    hygiene: dict
    log_summary: LogSummary


@dataclass(frozen=True)
class AdviceCandidate:
    title: str
    reason: str
    evidence: list[str]
    affected_modules: list[str]
    risks: list[str]
    tests: list[str]
    done: list[str]
    alternatives: list[str]


class TechnicalAdviceService:
    """Recomenda um unico proximo ciclo usando sinais reais ja disponiveis."""

    def __init__(
        self,
        db: Database,
        project_tools: ProjectTools,
        rag_status_provider: Callable[[], str],
        diagnostics_provider: Callable[[], str],
        release_history_provider: Callable[[], str],
        latest_release_provider: Callable[[], str],
        backup_provider: Callable[[], str],
        hygiene_provider: Callable[[], dict],
        logs_dir: Path = LOGS_DIR,
    ):
        self.db = db
        self.project_tools = project_tools
        self.rag_status_provider = rag_status_provider
        self.diagnostics_provider = diagnostics_provider
        self.release_history_provider = release_history_provider
        self.latest_release_provider = latest_release_provider
        self.backup_provider = backup_provider
        self.hygiene_provider = hygiene_provider
        self.logs_dir = logs_dir

    def build(self) -> str:
        state = self._state()
        candidate = self._choose_candidate(state)
        return self._format(state, candidate)

    def _state(self) -> AdviceState:
        return AdviceState(
            quick_check=self._quick_check(),
            conversations=self._safe_int(self.db.contar_mensagens_totais),
            knowledge=self._safe_int(self.db.contar_conhecimentos),
            memories=self._safe_int(self.db.contar_memorias),
            conflicts=self._safe_int(self.db.contar_conflitos_memoria),
            pending_learning=self._safe_int(self.db.contar_aprendizados_pendentes),
            pending_exercises=self._safe_int(self.db.contar_exercicios_pendentes),
            rag_status=self._safe_text(self.rag_status_provider, "RAG: indisponivel"),
            project_audit=self._safe_text(self.project_tools.diagnosticar_projeto, "Auditoria do projeto: indisponivel"),
            diagnostics=self._safe_text(self.diagnostics_provider, "Diagnostico: indisponivel"),
            release_history=self._safe_text(self.release_history_provider, "Historico de release: indisponivel"),
            latest_release=self._safe_text(self.latest_release_provider, "Ultimo release: indisponivel"),
            backup_status=self._safe_text(self.backup_provider, "Backups: indisponivel"),
            hygiene=self._safe_hygiene(),
            log_summary=analyze_logs(self.logs_dir),
        )

    def _choose_candidate(self, state: AdviceState) -> AdviceCandidate:
        if state.quick_check != "ok":
            return self._database_candidate(state)
        if state.log_summary.sensitive_findings:
            return self._security_candidate(state)
        if state.log_summary.active_errors:
            return self._active_errors_candidate(state)
        if "nenhum backup encontrado" in state.backup_status.lower() or "indisponivel" in state.backup_status.lower():
            return self._backup_candidate(state)
        if self._memory_functional_failure(state):
            return self._memory_candidate(state)
        if "Embeddings locais: ativos" not in state.rag_status:
            return self._rag_candidate(state)
        if self._release_missing_or_incomplete(state):
            return self._release_candidate(state)
        if self._project_has_large_files_or_todos(state.project_audit):
            return self._project_candidate(state)
        return self._interface_candidate(state)

    def _database_candidate(self, state: AdviceState) -> AdviceCandidate:
        return AdviceCandidate(
            title="Corrigir integridade do banco SQLite.",
            reason="O banco e uma dependencia central para memoria, conhecimento, estudos e historico.",
            evidence=[f"SQLite quick_check: {state.quick_check}"],
            affected_modules=["aya/data/database.py", "aya/core/backup.py", "data_local/study_ai.db"],
            risks=["perda ou corrupcao de dados se qualquer migracao for feita sem backup validado"],
            tests=["PRAGMA quick_check", "python -m unittest discover -v", "python scripts\\smoke_test.py"],
            done=["quick_check retorna ok", "backup validado antes de qualquer reparo", "suite automatizada passa"],
            alternatives=["Consolidar validacao de release.", "Revisar curadoria de memoria."],
        )

    def _security_candidate(self, state: AdviceState) -> AdviceCandidate:
        return AdviceCandidate(
            title="Revisar possivel exposicao de dados sensiveis nos logs.",
            reason="Registros sensiveis em log podem expor credenciais ou tokens locais.",
            evidence=[f"Linhas com padrao sensivel nos logs: {state.log_summary.sensitive_findings}"],
            affected_modules=["logs/", "aya/core/diagnostics.py", "aya/core/advice.py"],
            risks=["remover contexto util demais dos logs", "deixar credenciais em historico tecnico"],
            tests=["teste de sanitizacao de logs", "ruff", "compileall", "python -m pytest"],
            done=["nenhuma credencial aparece em saidas tecnicas", "logs continuam uteis sem expor segredo", "testes passam"],
            alternatives=["Investigar erros ativos nos logs.", "Consolidar backup validado."],
        )

    def _active_errors_candidate(self, state: AdviceState) -> AdviceCandidate:
        issue = state.log_summary.issues[0]
        return AdviceCandidate(
            title="Investigar erros ativos e recorrentes registrados nos logs.",
            reason="Erro recente e ainda ativo tem prioridade sobre melhorias de memoria ou interface.",
            evidence=[
                f"Erros ativos: {state.log_summary.active_errors}",
                f"Assinaturas unicas: {state.log_summary.unique_errors}",
                f"Mais recente: {issue.module} / {issue.exception_type} / {issue.count} ocorrencia(s)",
            ],
            affected_modules=[issue.module, "logs/aya.log", "modulo relacionado ao traceback"],
            risks=["tratar erro recuperado como ativo", "ignorar impacto real se o erro estiver interrompendo fluxo do usuario"],
            tests=["teste que reproduz o erro", "pytest", "ruff", "compileall", "smoke_test.py"],
            done=["erro deixa de aparecer apos reproducao", "fluxo afetado funciona", "logs novos nao repetem a mesma assinatura"],
            alternatives=["Consolidar validacao de release.", "Melhorar curadoria de memoria."],
        )

    def _backup_candidate(self, state: AdviceState) -> AdviceCandidate:
        return AdviceCandidate(
            title="Criar e validar um backup atual antes de novos ciclos.",
            reason="Sem backup validado, qualquer mudanca em memoria, RAG ou banco aumenta o risco operacional.",
            evidence=[state.backup_status],
            affected_modules=["aya/core/backup.py", "backups/", "data_local/study_ai.db"],
            risks=["backup incompleto", "ocupar espaco em disco se nao houver rotacao"],
            tests=["/backup criar", "/backup verificar", "PRAGMA quick_check", "python -m pytest"],
            done=["backup recente existe", "backup passa na verificacao", "documentacao continua correta"],
            alternatives=["Consolidar validacao de release.", "Melhorar curadoria de memoria."],
        )

    def _memory_candidate(self, state: AdviceState) -> AdviceCandidate:
        evidence = [
            f"Conflitos pendentes: {state.conflicts}",
            f"Aprendizados pendentes: {state.pending_learning}",
            f"Memorias fracas detectadas: {state.hygiene.get('fracas', 'indisponivel')}",
            f"Duplicatas detectadas: {state.hygiene.get('duplicatas', 'indisponivel')}",
            self._small_memory_sample_note(state),
        ]
        if self._memory_tests_failing(state):
            evidence.append(self._release_check_summary(state.latest_release))
        return AdviceCandidate(
            title="Melhorar curadoria e limpeza da memoria persistente.",
            reason="Memoria ruim ou pendente afeta diretamente a qualidade das respostas da Aya.",
            evidence=evidence,
            affected_modules=["aya/core/curation.py", "aya/data/database.py", "aya/core/panel.py"],
            risks=["arquivar memoria util por engano", "confundir memoria pessoal com conhecimento tecnico"],
            tests=["testes de conflitos", "testes de fusao", "testes de curadoria", "python -m unittest discover -v"],
            done=["conflitos ficam visiveis", "aprendizados pendentes podem ser aprovados ou rejeitados", "nenhuma memoria e apagada sem acao explicita"],
            alternatives=["Consolidar validacao de release.", "Melhorar reindexacao do RAG."],
        )

    def _rag_candidate(self, state: AdviceState) -> AdviceCandidate:
        return AdviceCandidate(
            title="Revisar RAG local e embeddings.",
            reason="O RAG e a base para respostas com contexto local; sem embeddings ativos, a busca fica mais limitada.",
            evidence=[state.rag_status],
            affected_modules=["aya/core/rag.py", "aya/core/embeddings.py", "aya/core/knowledge.py"],
            risks=["reindexacao lenta", "duplicacao de chunks se a ingestao for alterada sem teste"],
            tests=["testes de ingestao", "testes de reingestao", "testes de busca semantica", "python scripts\\smoke_test.py"],
            done=["embeddings ativos aparecem no status", "reingestao nao duplica chunks", "buscas retornam fontes quando houver contexto"],
            alternatives=["Melhorar curadoria de memoria.", "Consolidar validacao de release."],
        )

    def _release_candidate(self, state: AdviceState) -> AdviceCandidate:
        evidence = [self._first_relevant_line(state.release_history), self._release_check_summary(state.latest_release)]
        return AdviceCandidate(
            title="Consolidar validacao de release da Aya 1.0.",
            reason="Antes de evoluir mais funcionalidades, a Aya precisa de um retrato tecnico recente e verificavel.",
            evidence=evidence,
            affected_modules=["aya/core/release.py", "aya/core/diagnostics.py", "scripts/smoke_test.py", "logs/releases/"],
            risks=["um check pode demorar ou falhar por dependencia local indisponivel"],
            tests=["ruff", "compileall", "unittest", "smoke_test.py", "pip check", "PRAGMA quick_check"],
            done=["/release executar gera relatorio salvo", "todos os checks ficam APROVADO ou a falha fica documentada", "nenhuma credencial aparece no relatorio"],
            alternatives=["Reduzir arquivos grandes.", "Melhorar interface mobile."],
        )

    def _project_candidate(self, state: AdviceState) -> AdviceCandidate:
        evidence = self._audit_evidence(state.project_audit)
        return AdviceCandidate(
            title="Reduzir arquivos grandes e pontos simples de manutencao.",
            reason="Arquivos grandes e TODOs tornam cada nova melhoria mais arriscada e mais dificil de revisar.",
            evidence=evidence,
            affected_modules=["aya/core/assistant.py", "tests/test_aya.py", "modulos apontados por /auditar"],
            risks=["refatorar demais e quebrar comandos existentes", "mover codigo sem testes focados"],
            tests=["testes dos comandos afetados", "ruff", "compileall", "python -m unittest discover -v"],
            done=["mudancas pequenas por arquivo", "comandos existentes preservados", "testes focados e suite completa passam"],
            alternatives=["Melhorar interface mobile.", "Consolidar validacao de release."],
        )

    def _interface_candidate(self, state: AdviceState) -> AdviceCandidate:
        return AdviceCandidate(
            title="Melhorar a interface mobile sem redesenho completo.",
            reason="Os principais fundamentos tecnicos verificados nao apontaram bloqueio critico; melhorar o uso diario aumenta o valor da Aya.",
            evidence=[
                f"SQLite quick_check: {state.quick_check}",
                f"Conflitos pendentes: {state.conflicts}",
                state.rag_status,
            ],
            affected_modules=["app.py", "aya/ui/controller.py"],
            risks=["poluir a tela com controles demais", "quebrar compatibilidade mobile do Gradio"],
            tests=["teste manual da interface", "testes do UIController", "smoke_test.py"],
            done=["conversa continua como tela principal", "controles avancados ficam recolhidos", "interface abre localmente"],
            alternatives=["Reduzir arquivos grandes.", "Melhorar curadoria de memoria."],
        )

    def _format(self, state: AdviceState, candidate: AdviceCandidate) -> str:
        operational_pending = self._operational_pending_lines(state)
        lines = [
            "Conselho tecnico da Aya:",
            "",
            "Proximo ciclo tecnico recomendado:",
            candidate.title,
            "",
            "Motivo:",
            candidate.reason,
            "",
            "Evidencias tecnicas:",
            *self._bullets(candidate.evidence),
            *self._bullets(self._curation_evidence_lines(state)),
            "",
            "Pendencias operacionais:",
            *self._bullets(operational_pending),
            "",
            "Acoes manuais sugeridas:",
            *self._bullets(self._manual_action_lines(operational_pending)),
            "",
            "Impacto:",
            self._impact(candidate),
            "",
            "Urgencia:",
            self._urgency(state, candidate),
            "",
            "Risco:",
            self._risk_level(candidate),
            "",
            "Confianca da recomendacao:",
            self._confidence_note(state, candidate),
            "",
            "Estado coletado:",
            f"- SQLite quick_check: {state.quick_check}",
            f"- Conversas salvas: {state.conversations}",
            f"- Conhecimentos: {state.knowledge}",
            f"- Memorias persistentes: {state.memories}",
            f"- Conflitos de memoria: {state.conflicts}",
            f"- Aprendizados pendentes: {state.pending_learning}",
            f"- Exercicios pendentes: {state.pending_exercises}",
            f"- Erros em logs: {state.log_summary.total_error_records} registro(s), {state.log_summary.unique_errors} assinatura(s), {state.log_summary.duplicated_records} duplicado(s)",
            f"- Erros ativos em logs: {state.log_summary.active_errors}",
            f"- Erros recuperados/antigos: {state.log_summary.recovered_errors + state.log_summary.old_errors}",
            f"- Avisos em logs: {state.log_summary.warnings}",
            f"- Possiveis dados sensiveis em logs: {state.log_summary.sensitive_findings}",
            f"- {state.backup_status}",
            "",
            "Resumo de erros relevantes:",
            *self._bullets(self._log_issue_lines(state.log_summary)),
            "",
            "Modulos possivelmente afetados:",
            *self._bullets(candidate.affected_modules),
            "",
            "Riscos:",
            *self._bullets(candidate.risks),
            "",
            "Testes necessarios:",
            *self._bullets(candidate.tests),
            "",
            "Criterios de conclusao:",
            *self._bullets(candidate.done),
            "",
            "Alternativas secundarias:",
            *self._numbered(candidate.alternatives[:2]),
            "",
            "Informacoes indisponiveis:",
            *self._bullets(self._unavailable(state)),
            "",
            "Observacao: este comando apenas recomenda. Ele nao altera arquivos, nao roda correcoes e nao executa o ciclo sugerido.",
        ]
        return "\n".join(lines)

    def _quick_check(self) -> str:
        try:
            row = self.db.connection.execute("PRAGMA quick_check").fetchone()
            return str(row[0] if row else "sem resposta")
        except Exception as exc:
            return f"erro: {exc}"

    def _safe_int(self, provider: Callable[[], int]) -> int:
        try:
            return int(provider())
        except Exception:
            return -1

    def _safe_text(self, provider: Callable[[], str], fallback: str) -> str:
        try:
            return str(provider())
        except Exception as exc:
            return f"{fallback} ({exc})"

    def _safe_hygiene(self) -> dict:
        try:
            return dict(self.hygiene_provider())
        except Exception as exc:
            return {"indisponivel": str(exc)}

    def _release_missing_or_incomplete(self, state: AdviceState) -> bool:
        latest_lower = state.latest_release.lower()
        if "Nenhum relatorio" in state.release_history or "nenhum release completo" in latest_lower or "indisponivel" in latest_lower:
            return True
        return any(marker in state.latest_release for marker in ("REPROVADO", "INDISPONIVEL", "NAO_EXECUTADO", "nao executado"))

    def _hygiene_needs_work(self, hygiene: dict) -> bool:
        keys = ("duplicatas", "conflitos", "fracas", "conflitos_pendentes")
        return any(int(hygiene.get(key, 0) or 0) > 0 for key in keys if str(hygiene.get(key, 0)).isdigit())

    def _memory_functional_failure(self, state: AdviceState) -> bool:
        if self._memory_tests_failing(state):
            return True
        if "indisponivel" in state.hygiene or "erro" in state.hygiene:
            return True
        if not self._curation_review_available(state):
            return state.conflicts > 0 or state.pending_learning > 0 or self._hygiene_needs_work(state.hygiene)
        if self._large_memory_backlog(state):
            return True
        return False

    def _memory_tests_failing(self, state: AdviceState) -> bool:
        text = f"{state.latest_release}\n{state.release_history}"
        memory_terms = ("memoria", "memórias", "curadoria", "higiene", "conflito")
        lines = text.lower().splitlines()
        for index, line in enumerate(lines):
            if "unittest" in line and "reprovado" in line:
                context = "\n".join(lines[index:index + 6])
                if any(term in context for term in memory_terms):
                    return True
            if any(marker in line for marker in ("reprovado", "falha", "failed", "error")) and any(term in line for term in memory_terms):
                return True
        return False

    def _curation_review_available(self, state: AdviceState) -> bool:
        expected_keys = {
            "memorias_fracas",
            "memorias_adiadas",
            "memorias_ignoradas",
            "itens_conflitantes",
            "precisa_revisao",
        }
        return expected_keys.issubset(set(state.hygiene.keys()))

    def _large_memory_backlog(self, state: AdviceState) -> bool:
        limits = {
            "fracas": 25,
            "duplicatas": 10,
            "conflitos": 10,
            "conflitos_pendentes": 10,
        }
        for key, limit in limits.items():
            value = state.hygiene.get(key, 0)
            if str(value).isdigit() and int(value) > limit:
                return True
        return state.pending_learning > 25 or state.conflicts > 10

    def _curation_evidence_lines(self, state: AdviceState) -> list[str]:
        if self._curation_review_available(state):
            return [
                "Curadoria operacional detectada: resumo de memorias fracas, adiadas, ignoradas e conflitos esta disponivel.",
            ]
        return []

    def _operational_pending_lines(self, state: AdviceState) -> list[str]:
        if not self._curation_review_available(state):
            return ["Nenhuma pendencia operacional identificada com as fontes disponiveis."]

        lines: list[str] = []
        for item in state.hygiene.get("memorias_fracas", [])[:8]:
            lines.append(self._memory_pending_line(item))
        if state.conflicts:
            lines.append(f"Conflitos de memoria pendentes: {state.conflicts}.")
        if state.pending_learning:
            lines.append(f"Aprendizados pendentes: {state.pending_learning}.")
        if not lines:
            lines.append("Nenhuma pendencia operacional de memoria identificada.")
        return lines

    def _memory_pending_line(self, item) -> str:
        memoria_id = self._row_value(item, "id", "?")
        dominio = self._row_value(item, "dominio", "geral")
        motivos = self._safe_memory_reasons(item)
        return f"Memoria #{memoria_id} [{dominio}]: {', '.join(motivos)}."

    def _safe_memory_reasons(self, item) -> list[str]:
        motivos: list[str] = []
        try:
            confianca = float(self._row_value(item, "confianca", 0) or 0)
        except (TypeError, ValueError):
            confianca = 0.0
        tipo = str(self._row_value(item, "tipo", "") or "")
        origem = str(self._row_value(item, "origem", "") or "")
        valor = str(self._row_value(item, "valor", "") or "")
        if confianca < 0.7:
            motivos.append("baixa confianca")
        if tipo in {"assunto_atual", "reflexao"} and confianca < 0.9:
            motivos.append("conteudo temporario")
        if len(valor.strip()) < 8:
            motivos.append("conteudo vago ou incompleto")
        if origem.startswith("auto") and confianca < 0.85:
            motivos.append("origem automatica com confianca limitada")
        return motivos or ["revisao manual pendente"]

    def _row_value(self, item, key: str, default=""):
        try:
            if hasattr(item, "keys") and key in item.keys():
                return item[key]
            if isinstance(item, dict):
                return item.get(key, default)
        except (KeyError, TypeError):
            return default
        return default

    def _manual_action_lines(self, operational_pending: list[str]) -> list[str]:
        if operational_pending == ["Nenhuma pendencia operacional de memoria identificada."]:
            return ["Nenhuma acao manual imediata sugerida para memoria."]
        if operational_pending == ["Nenhuma pendencia operacional identificada com as fontes disponiveis."]:
            return ["Execute /curadoria se quiser verificar manualmente memorias pendentes."]
        return [
            "Revise as memorias com /curadoria.",
            "Use /arquivar memoria id, /editar memoria id | novo valor, /adiar memoria id ou /ignorar memoria id conforme o caso.",
        ]

    def _project_has_large_files_or_todos(self, audit: str) -> bool:
        lower = audit.lower()
        return "arquivo grande" in lower or "todo/fixme" in lower or "arquivos maiores:" in lower

    def _audit_evidence(self, audit: str) -> list[str]:
        lines = [line.strip() for line in audit.splitlines() if line.strip()]
        selected = [
            line for line in lines
            if "Arquivos analisados:" in line or "Arquivos maiores:" in line or "arquivo grande" in line or "TODO/FIXME" in line
        ]
        return selected[:5] or ["Auditoria local nao apontou achado especifico."]

    def _first_relevant_line(self, text: str) -> str:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
        return "Historico de release sem linhas relevantes."

    def _release_check_summary(self, text: str) -> str:
        checks = [line.strip() for line in text.splitlines() if line.strip().startswith("- ") and any(name in line for name in ("pytest", "ruff", "compileall", "unittest", "smoke_test.py", "pip check"))]
        if not checks:
            return "Checks de release: nao disponiveis no ultimo relatorio."
        return "Checks de release: " + " | ".join(checks[:5])

    def _unavailable(self, state: AdviceState) -> list[str]:
        unavailable = []
        combined = "\n".join([state.diagnostics, state.release_history, state.latest_release, state.project_audit, state.backup_status])
        if "indisponivel" in combined.lower():
            unavailable.append("Uma ou mais fontes retornaram indisponivel; veja o texto bruto dos comandos relacionados.")
        if "nao executado" in state.latest_release or "NAO_EXECUTADO" in state.latest_release:
            unavailable.append("Alguns checks do ultimo release nao foram executados naquele relatorio.")
        if not unavailable:
            unavailable.append("Nenhuma indisponibilidade detectada nas fontes consultadas.")
        return unavailable

    def _small_memory_sample_note(self, state: AdviceState) -> str:
        total = state.hygiene.get("total", state.memories)
        fracas = state.hygiene.get("fracas", "indisponivel")
        if isinstance(total, int) and total and total <= 5:
            return f"Memorias fracas: {fracas} de {total}. A amostra e pequena; a recomendacao deve ser tratada com confianca limitada."
        return ""

    def _log_issue_lines(self, summary: LogSummary) -> list[str]:
        if not summary.issues:
            return ["Nenhum erro encontrado nos logs analisados."]
        lines = []
        for issue in summary.issues[:3]:
            lines.append(
                f"{issue.module}: {issue.exception_type}, {issue.count} ocorrencia(s), "
                f"status={issue.status}, gravidade={issue.severity}, ultimo={issue.last_seen}"
            )
        return lines

    def _impact(self, candidate: AdviceCandidate) -> str:
        if any(term in candidate.title.lower() for term in ("banco", "seguranca", "erros ativos")):
            return "Alto: afeta estabilidade, seguranca ou persistencia."
        if "rag" in candidate.title.lower() or "memoria" in candidate.title.lower():
            return "Medio/alto: afeta qualidade das respostas e recuperacao de contexto."
        return "Medio: melhora uso e manutencao sem indicar falha critica."

    def _urgency(self, state: AdviceState, candidate: AdviceCandidate) -> str:
        if state.log_summary.active_errors or state.quick_check != "ok" or state.log_summary.sensitive_findings:
            return "Alta: ha evidencia tecnica que pode afetar confiabilidade agora."
        if "nenhum backup encontrado" in state.backup_status.lower():
            return "Media/alta: nao bloqueia uso imediato, mas aumenta risco antes de novos ciclos."
        return "Media: importante, mas sem sinal de falha ativa critica."

    def _risk_level(self, candidate: AdviceCandidate) -> str:
        if len(candidate.affected_modules) >= 3:
            return "Medio: envolve mais de um modulo."
        return "Baixo/medio: escopo aparenta ser contido."

    def _confidence_note(self, state: AdviceState, candidate: AdviceCandidate) -> str:
        if state.log_summary.active_errors:
            return "Boa: baseada em erro recente, assinatura unica e impacto conhecido no log."
        if self._memory_tests_failing(state):
            return "Boa: baseada em teste de memoria reprovado no ultimo registro de release disponivel."
        if state.memories <= 5 and "memoria" in candidate.title.lower():
            return "Limitada: a proporcao de memorias fracas chama atencao, mas a amostra e pequena."
        if self._unavailable(state) != ["Nenhuma indisponibilidade detectada nas fontes consultadas."]:
            return "Limitada: uma ou mais fontes tecnicas nao estavam totalmente disponiveis."
        return "Moderada: baseada em diagnostico local, banco, RAG, release e logs disponiveis."

    def _bullets(self, items: list[str]) -> list[str]:
        return [f"- {item}" for item in items if item]

    def _numbered(self, items: list[str]) -> list[str]:
        return [f"{index}. {item}" for index, item in enumerate(items, start=1)]
