from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from aya.core.aya_dev import AyaDevService
from aya.core.dev_workspace import CheckResult
from aya.core.llm import StaticClient
from aya.core.project_tools import ProjectTools
from aya.core.permissions import AccessChannel
from aya.ui.aya_dev import AyaDevPanel


class AyaDevAutonomyTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "projeto"
        (self.root / "aya" / "core").mkdir(parents=True)
        (self.root / "tests").mkdir()
        (self.root / "scripts").mkdir()
        (self.root / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n*.pyc\n", encoding="utf-8")
        (self.root / "aya" / "core" / "sample.py").write_text(
            "class Sample:\n"
            "    def run(self, value):\n"
            "        return value\n",
            encoding="utf-8",
        )
        (self.root / "tests" / "test_sample.py").write_text(
            "from aya.core.sample import Sample\n\n"
            "def test_sample():\n"
            "    assert Sample().run('x') == 'x'\n",
            encoding="utf-8",
        )
        (self.root / "scripts" / "smoke_test.py").write_text("print('ok')\n", encoding="utf-8")
        state = self.root.parent / "state"
        self.service = AyaDevService(
            self.root,
            StaticClient("review ok"),
            ProjectTools(self.root),
            storage_path=state / "history.json",
            index_path=state / "index.json",
            workspace_root=self.root.parent / "workspaces",
        )
        self.service.workspace.validate = Mock(side_effect=self._fast_validation)
        self.service.workspace.baseline = Mock(side_effect=self._fast_validation)

    def tearDown(self):
        self.tmp.cleanup()

    def init_git(self, dirty: bool = False):
        for command in (
            ("git", "init"),
            ("git", "config", "user.email", "aya@example.local"),
            ("git", "config", "user.name", "Aya Tests"),
            ("git", "add", "."),
            ("git", "commit", "-m", "baseline"),
        ):
            subprocess.run(command, cwd=self.root, capture_output=True, check=True)
        if dirty:
            (self.root / "aya" / "core" / "sample.py").write_text("# dirty\n", encoding="utf-8")

    def seed_successful_docstring_history(self, total: int = 3, *, production_real: bool = False):
        for index in range(total):
            proposal = self.service.create_proposal(
                title=f"Registro operacional docstring {index}" if production_real else f"Historico docstring {index}",
                problem="Documentar simbolo simples.",
                evidence=["Indice AST confirmou aya/core/sample.py." if production_real else "teste"],
                related_files=["aya/core/sample.py"],
                related_symbols=["Sample.run"],
                probable_cause="sem docstring",
                suggested_change="docstring",
                preserve=["comportamento"],
                impact="baixo",
                urgency="baixa",
                difficulty="baixa",
                required_tests=["tests/test_sample.py"],
                done_criteria=["ok"],
            )
            proposal.state = "AGUARDANDO_APROVACAO"
            proposal.attempts = 1
            proposal.workspace_created = production_real
            proposal.tests_executed = production_real
            proposal.patch_manifest = {
                "version": 1,
                "proposal_id": proposal.id,
                "base_commit": "base",
                "operations": [{"type": "insert_docstring", "file": "aya/core/sample.py"}],
            }
        self.service._save()

    def test_modo_padrao_desligado_e_observar_nao_cria_proposta(self):
        self.assertIn("Modo: DESLIGADA", self.service.autonomy_status())
        before = len(self.service.proposals)
        self.assertIn("DESLIGADA -> OBSERVAR", self.service.set_autonomy_mode("observar"))
        self.assertIn("Candidatos autonomos", self.service.list_candidates())
        self.assertEqual(before, len(self.service.proposals))

    def test_amostra_insuficiente_bloqueia_candidato(self):
        candidates = self.service._autonomous_candidates()
        self.assertTrue(candidates)
        self.assertTrue(any(candidate.eligibility == "DADOS_INSUFICIENTES" for candidate in candidates))

    def test_evidencia_suficiente_deixa_docstring_elegivel_com_score_deterministico(self):
        self.seed_successful_docstring_history(production_real=True)
        first = self.service._autonomous_candidates()
        second = self.service._autonomous_candidates()
        eligible = [candidate for candidate in first if candidate.eligibility == "ELEGIVEL"]
        self.assertTrue(eligible)
        self.assertEqual(
            [(item.candidate_id, item.score) for item in first],
            [(item.candidate_id, item.score) for item in second],
        )

    def test_candidato_sensivel_banco_seguranca_risco_medio_e_arquivos_demais_bloqueiam(self):
        blocked_secret = self.service._candidate_blocked_reasons([".env"], "documentacao", "insert_docstring", "baixo", 1)
        blocked_db = self.service._candidate_blocked_reasons(["aya/data/database.py"], "documentacao", "insert_docstring", "baixo", 1)
        blocked_security = self.service._candidate_blocked_reasons(["aya/core/security.py"], "documentacao", "insert_docstring", "baixo", 1)
        blocked_risk = self.service._candidate_blocked_reasons(["aya/core/sample.py"], "documentacao", "insert_docstring", "medio", 1)
        blocked_files = self.service._candidate_blocked_reasons(["a.py", "b.py", "c.py"], "documentacao", "insert_docstring", "baixo", 1)
        self.assertTrue(blocked_secret)
        self.assertTrue(blocked_db)
        self.assertTrue(blocked_security)
        self.assertIn("RISCO_MEDIO", blocked_risk)
        self.assertIn("MAIS_DE_DOIS_ARQUIVOS", blocked_files)

    def test_preparar_supervisionado_cria_proposta_e_para_aguardando_aprovacao(self):
        self.init_git()
        self.seed_successful_docstring_history(production_real=True)
        self.service.set_autonomy_mode("preparar-supervisionado")
        response = self.service.execute_safe_autonomous_cycle()
        proposals = [proposal for proposal in self.service.proposals.values() if proposal.title.startswith("[AUTO]")]
        self.assertEqual(1, len(proposals))
        self.assertEqual("AGUARDANDO_APROVACAO", proposals[0].state)
        self.assertIn("Aprovacao automatica: nao executada", response)
        self.assertEqual("", subprocess.run(("git", "status", "--porcelain"), cwd=self.root, capture_output=True, text=True, check=True).stdout)

    def test_working_tree_suja_e_worktree_inesperado_bloqueiam(self):
        self.init_git(dirty=True)
        self.service.set_autonomy_mode("preparar-supervisionado")
        self.assertIn("alteracao", self.service.execute_safe_autonomous_cycle())

    def test_modelo_nao_altera_score_e_memoria_nao_reduz_risco(self):
        self.seed_successful_docstring_history(production_real=True)
        self.service.llm = StaticClient(json.dumps({"type": "insert_docstring", "symbol": "Outro", "content": "Outro"}))
        candidate = self.service._select_best_candidate()
        self.assertIsNotNone(candidate)
        before = candidate.score
        self.service.llm.chat(model="x", messages=[], temperature=1, max_tokens=1)
        after = self.service._find_candidate(candidate.candidate_id).score
        self.assertEqual(before, after)
        blocked = self.service._candidate_blocked_reasons(["aya/data/database.py"], "documentacao", "insert_docstring", "baixo", 1)
        self.assertTrue(blocked)

    def test_ui_exige_confirmacao_e_remoto_bloqueia(self):
        assistant = Mock()
        assistant.aya_dev = self.service
        assistant.permissions.allows.return_value = True
        assistant.permissions.denial_message.return_value = "negado"
        panel = AyaDevPanel(assistant)
        self.assertIn("Confirmacao incorreta", panel.run_safe_autonomy_cycle(""))
        assistant.permissions.allows.return_value = False
        remote_panel = AyaDevPanel(assistant, channel=AccessChannel.REMOTE_GRADIO)
        self.assertEqual("negado", remote_panel.run_safe_autonomy_cycle("EXECUTAR CICLO SEGURO"))

    def test_import_nao_usado_gera_candidato_bloqueavel(self):
        (self.root / "aya" / "core" / "sample.py").write_text(
            "import json\n\n"
            "class Sample:\n"
            "    def run(self, value):\n"
            "        return value\n",
            encoding="utf-8",
        )
        candidates = self.service._autonomous_candidates()
        self.assertTrue(any(candidate.operation_type == "replace_exact" for candidate in candidates))

    def test_ast_sem_ruff_f401_nao_cria_candidato_de_import(self):
        (self.root / "aya" / "core" / "sample.py").write_text(
            "import json\n\nclass Sample:\n    def run(self, value):\n        return value\n",
            encoding="utf-8",
        )
        self.service._ruff_f401_diagnostics = Mock(return_value={})
        candidates = self.service._autonomous_candidates(force=True)
        self.assertFalse(any(candidate.operation_type == "replace_exact" for candidate in candidates))

    def test_noqa_type_checking_e_reexport_bloqueiam_f401(self):
        entry = self.service.index.build()[0]
        diagnostic = {"line": 1, "diagnostic_sha256": "abc", "message": "unused import"}
        noqa = self.service._qualify_ruff_f401_candidate(entry, "import json  # noqa: F401\n", "import json  # noqa: F401", diagnostic, "ruff")
        type_checking = self.service._qualify_ruff_f401_candidate(entry, "from typing import TYPE_CHECKING\nimport json\n", "import json", diagnostic, "ruff")
        reexport = self.service._qualify_ruff_f401_candidate(entry, "__all__ = ['json']\nimport json\n", "import json", diagnostic, "ruff")
        self.assertEqual("BLOQUEADO", noqa["qualification_status"])
        self.assertIn("NOQA_IMPORT", noqa["reason_codes"])
        self.assertIn("TYPE_CHECKING_IMPORT", type_checking["reason_codes"])
        self.assertIn("POSSIBLE_REEXPORT", reexport["reason_codes"])

    def test_qualificacao_docstring_filtra_privado_dunder_init_getter_e_trivial(self):
        (self.root / "aya" / "core" / "sample.py").write_text(
            "class Sample:\n"
            "    def __init__(self):\n"
            "        self.value = 1\n"
            "    def __str__(self):\n"
            "        return 'x'\n"
            "    def _private(self):\n"
            "        return 1\n"
            "    def value_getter(self):\n"
            "        return self.value\n"
            "    def one(self):\n"
            "        return 1\n",
            encoding="utf-8",
        )
        candidates = self.service._autonomous_candidates(force=True)
        operational = {candidate.symbol for candidate in candidates if candidate.qualification_status == "ACAO_RECOMENDADA"}
        self.assertNotIn("Sample.__init__", operational)
        self.assertNotIn("Sample.__str__", operational)
        self.assertNotIn("Sample._private", operational)
        self.assertTrue(all("PRIVATE_SYMBOL" in candidate.reason_codes or candidate.symbol != "Sample._private" for candidate in candidates))

    def test_contadores_de_exclusao_conservam_total_bruto(self):
        (self.root / "aya" / "core" / "sample.py").write_text(
            "class Sample:\n"
            "    def __str__(self):\n"
            "        return 'x'\n"
            "    def _private(self):\n"
            "        return 1\n"
            "    def run(self, value):\n"
            "        if value:\n"
            "            return value\n"
            "        return 'x'\n",
            encoding="utf-8",
        )
        candidates = self.service._autonomous_candidates(force=True)
        report = self.service._candidate_scan_report
        exclusions = sum(report["hard_exclusions"].values())
        self.assertEqual(report["raw_detected"], len(candidates) + exclusions)
        self.assertGreaterEqual(report["hard_exclusions"].get("PRIVATE_SYMBOL", 0), 1)
        self.assertIn("Contadores de exclusao", self.service.renew_candidates())

    def test_reason_codes_pontuacao_e_funil_sao_deterministicos(self):
        self.seed_successful_docstring_history(production_real=True)
        first = self.service._autonomous_candidates(force=True)
        second = self.service._autonomous_candidates()
        self.assertEqual(
            [(item.candidate_id, item.priority_score, item.reason_codes) for item in first],
            [(item.candidate_id, item.priority_score, item.reason_codes) for item in second],
        )
        metrics = self.service._candidate_queue_metrics(first)
        self.assertEqual(metrics["detected"], metrics["classified_total"])
        self.assertTrue(any("PUBLIC_SYMBOL" in candidate.reason_codes for candidate in first))

    def test_fila_padrao_resume_e_top_ordena_sem_despejar_tudo(self):
        response = self.service.list_candidates()
        self.assertIn("Resumo dos Candidatos autonomos", response)
        self.assertIn("Top candidatos priorizados", response)
        self.assertLessEqual(response.count("- AUTO-"), 20)

    def test_cache_reutiliza_arquivo_sem_mudanca_e_reanalisa_alterado(self):
        self.service._autonomous_candidates(force=True)
        first_report = self.service._candidate_scan_report
        self.assertGreaterEqual(first_report["cache_misses"], 1)
        self.service._candidate_cache = None
        self.service._autonomous_candidates(force=True)
        second_report = self.service._candidate_scan_report
        self.assertGreaterEqual(second_report["cache_hits"], 1)
        (self.root / "aya" / "core" / "sample.py").write_text(
            "class Sample:\n    def run(self, value):\n        if value:\n            return value\n        return 'x'\n",
            encoding="utf-8",
        )
        self.service._candidate_cache = None
        self.service._autonomous_candidates(force=True)
        third_report = self.service._candidate_scan_report
        self.assertGreaterEqual(third_report["cache_misses"], 1)
        self.assertEqual(1, third_report["ruff_calls"])
        self.assertEqual(1, third_report["index_builds"])

    def test_arquivo_removido_contabiliza_cache_removido(self):
        self.service._autonomous_candidates(force=True)
        (self.root / "aya" / "core" / "sample.py").unlink()
        self.service._candidate_cache = None
        self.service._autonomous_candidates(force=True)
        self.assertGreaterEqual(self.service._candidate_scan_report["files_removed"], 1)

    def test_origem_separa_producao_fixture_legacy_e_unknown(self):
        self.seed_successful_docstring_history(total=1, production_real=True)
        self.seed_successful_docstring_history(total=1)
        legacy = self.service.create_proposal(
            title="Legado sem manifesto",
            problem="Sem manifesto",
            evidence=["manual"],
            related_files=["aya/core/sample.py"],
            related_symbols=["Sample.run"],
            probable_cause="antigo",
            suggested_change="n/a",
            preserve=["n/a"],
            impact="baixo",
            urgency="baixa",
            difficulty="baixa",
            required_tests=["tests/test_sample.py"],
            done_criteria=["n/a"],
        )
        legacy.patch_manifest = {}
        self.assertEqual("production_real", self.service._proposal_origin(next(p for p in self.service.proposals.values() if p.title.startswith("Registro operacional"))))
        self.assertEqual("test_fixture", self.service._proposal_origin(next(p for p in self.service.proposals.values() if p.title.startswith("Historico docstring"))))
        self.assertEqual("legacy_import", self.service._proposal_origin(legacy))

    def test_contabilidade_conserva_total_e_exibe_inconclusivo(self):
        self.seed_successful_docstring_history(total=1, production_real=True)
        pending = self.service.create_proposal(
            title="Registro operacional pendente",
            problem="Documentar",
            evidence=["Indice AST confirmou aya/core/sample.py."],
            related_files=["aya/core/sample.py"],
            related_symbols=["Sample.run"],
            probable_cause="sem docstring",
            suggested_change="docstring",
            preserve=["comportamento"],
            impact="baixo",
            urgency="baixa",
            difficulty="baixa",
            required_tests=["tests/test_sample.py"],
            done_criteria=["ok"],
        )
        pending.workspace_created = True
        pending.tests_executed = True
        pending.patch_manifest = {"operations": [{"type": "insert_docstring", "file": "aya/core/sample.py"}]}
        stats = self.service._operation_stats()["insert_docstring"]
        buckets = stats["success"] + stats["fail"] + stats["inconclusive"] + stats["rejected"] + stats["cancelled"]
        self.assertEqual(stats["total"], buckets)
        self.assertEqual(1, stats["inconclusive"])
        self.assertIn("inconclusivos=1", self.service.capability_report("operacao insert_docstring"))

    def test_capacidade_filtra_categoria_e_modelo(self):
        self.seed_successful_docstring_history(total=1, production_real=True)
        model = next(iter(self.service.proposals.values())).model
        by_category = self.service.capability_report("categoria documentacao")
        by_model = self.service.capability_report(f"modelo {model}")
        self.assertIn("Filtro: categoria=documentacao", by_category)
        self.assertIn("Operacao insert_docstring", by_category)
        self.assertIn(f"Filtro: modelo={model}", by_model)
        self.assertIn("production_real=1", by_model)

    def test_capacidade_versionada_separa_pipeline_atual_e_legado(self):
        self.seed_successful_docstring_history(total=1, production_real=True)
        legacy = self.service.create_proposal(
            title="Historico legado importado",
            problem="Documentar simbolo simples.",
            evidence=["manual"],
            related_files=["aya/core/sample.py"],
            related_symbols=["Sample.run"],
            probable_cause="sem docstring",
            suggested_change="docstring",
            preserve=["comportamento"],
            impact="baixo",
            urgency="baixa",
            difficulty="baixa",
            required_tests=["tests/test_sample.py"],
            done_criteria=["ok"],
        )
        legacy.patch_pipeline_version = "legacy_unknown"
        legacy.schema_version = "legacy_unknown"
        legacy.state = "AGUARDANDO_APROVACAO"
        legacy.patch_manifest = {"operations": [{"type": "insert_docstring", "file": "aya/core/sample.py"}]}
        self.service._save()
        report = self.service.capability_report("operacao insert_docstring")
        self.assertIn("pipeline_atual: casos=1", report)
        self.assertIn("pipeline_desconhecido: casos=1", report)

    def test_falha_do_pipeline_atual_bloqueia_calibracao(self):
        failed = self.service.create_proposal(
            title="Falha operacional atual",
            problem="Documentar simbolo simples.",
            evidence=["Indice AST confirmou aya/core/sample.py."],
            related_files=["aya/core/sample.py"],
            related_symbols=["Sample.run"],
            probable_cause="sem docstring",
            suggested_change="docstring",
            preserve=["comportamento"],
            impact="baixo",
            urgency="baixa",
            difficulty="baixa",
            required_tests=["tests/test_sample.py"],
            done_criteria=["ok"],
        )
        failed.state = "FALHOU"
        failed.workspace_created = True
        failed.tests_executed = True
        failed.patch_manifest = {"operations": [{"type": "insert_docstring", "file": "aya/core/sample.py"}]}
        self.service._save()
        candidate = next(item for item in self.service._autonomous_candidates(force=True) if item.operation_type == "insert_docstring")
        self.assertIn("CURRENT_PIPELINE_FAILURE", candidate.reason_codes)
        response = self.service.create_calibration_experiment(candidate.candidate_id)
        self.assertIn("falha registrada no pipeline atual", response)

    def test_criar_experimento_de_calibracao_nao_chama_modelo_nem_worktree(self):
        candidates = self.service._autonomous_candidates(force=True)
        candidate = next(item for item in candidates if item.qualification_status == "ACAO_RECOMENDADA")
        response = self.service.create_calibration_experiment(candidate.candidate_id)
        self.assertIn("Experimento de calibracao criado", response)
        self.assertIn("Modelo chamado: nao", response)
        self.assertIn("Worktree criado: nao", response)
        self.assertEqual([], self.service.llm.calls)
        self.assertEqual([], list((self.root.parent / "workspaces").glob("*")) if (self.root.parent / "workspaces").exists() else [])
        self.assertIn("AGUARDANDO_CONFIRMACAO", {item.state for item in self.service.experiments.values()})

    def test_experimento_exige_confirmacao_explicitamente(self):
        candidate = next(item for item in self.service._autonomous_candidates(force=True) if item.qualification_status == "ACAO_RECOMENDADA")
        self.service.create_calibration_experiment(candidate.candidate_id)
        experiment = next(iter(self.service.experiments.values()))
        response = self.service.execute_calibration_experiment(f"{experiment.experiment_id} | confirmar")
        self.assertIn("Confirmacao incorreta", response)
        self.assertEqual("AGUARDANDO_CONFIRMACAO", self.service.experiments[experiment.experiment_id].state)

    def test_executar_experimento_para_em_aguardando_aprovacao_sem_commit(self):
        self.init_git()
        candidate = next(item for item in self.service._autonomous_candidates(force=True) if item.qualification_status == "ACAO_RECOMENDADA")
        self.service.create_calibration_experiment(candidate.candidate_id)
        experiment = next(iter(self.service.experiments.values()))
        response = self.service.execute_calibration_experiment(
            f"{experiment.experiment_id} | EXECUTAR EXPERIMENTO {experiment.experiment_id}"
        )
        updated = self.service.experiments[experiment.experiment_id]
        proposal = self.service._get(updated.proposal_id)
        self.assertIn("Commit criado: nao", response)
        self.assertEqual("AGUARDANDO_APROVACAO", updated.state)
        self.assertEqual("AGUARDANDO_APROVACAO", proposal.state)
        self.assertEqual("PATCH_VALIDADO_SEM_COMMIT", updated.result)
        self.assertEqual(
            "",
            subprocess.run(("git", "status", "--porcelain"), cwd=self.root, capture_output=True, text=True, check=True).stdout,
        )

    def test_resultado_de_experimento_validado_alimenta_capacidade_atual(self):
        candidate = next(item for item in self.service._autonomous_candidates(force=True) if item.qualification_status == "ACAO_RECOMENDADA")
        self.service.create_calibration_experiment(candidate.candidate_id)
        experiment = next(iter(self.service.experiments.values()))
        experiment.state = "AGUARDANDO_APROVACAO"
        experiment.result = "PATCH_VALIDADO_SEM_COMMIT"
        experiment.evidence_strength = "CALIBRACAO_VALIDADA"
        experiment.record_sha256 = self.service._experiment_record_sha(experiment)
        self.service._save_experiments()
        report = self.service.capability_report("operacao insert_docstring")
        self.assertIn("pipeline_atual: casos=1", report)
        self.assertIn("sucessos=1", report)

    def test_semantica_classifica_auth_launch_app_memoria_e_control_plane(self):
        (self.root / "app.py").write_text(
            "def create_app():\n"
            "    return 'app'\n\n"
            "def make_auth_checker(password):\n"
            "    return password == 'ok'\n\n"
            "def build_launch_kwargs(host):\n"
            "    return {'server_name': host, 'auth': ('u', 'p')}\n",
            encoding="utf-8",
        )
        (self.root / "aya" / "core" / "aya_dev.py").write_text(
            "class AyaDevService:\n"
            "    def status(self):\n"
            "        return 'ok'\n"
            "    def register_engineering_memory(self, entry):\n"
            "        self.engineering_memory_path.write_text(entry)\n",
            encoding="utf-8",
        )
        auth = self.service._semantic_safety("app.py", "make_auth_checker")
        launch = self.service._semantic_safety("app.py", "build_launch_kwargs")
        create_app = self.service._semantic_safety("app.py", "create_app")
        memory = self.service._semantic_safety("aya/core/aya_dev.py", "AyaDevService.register_engineering_memory")
        status = self.service._semantic_safety("aya/core/aya_dev.py", "AyaDevService.status")
        self.assertEqual("AUTHENTICATION", auth.responsibility)
        self.assertIn("AUTHENTICATION_SYMBOL", auth.reason_codes)
        self.assertIn(launch.responsibility, {"REMOTE_ACCESS", "APPLICATION_BOOTSTRAP"})
        self.assertIn("SERVER_LAUNCH_CONFIGURATION", launch.reason_codes)
        self.assertEqual("APPLICATION_BOOTSTRAP", create_app.responsibility)
        self.assertIn("CENTRAL_APPLICATION_FILE", create_app.reason_codes)
        self.assertEqual("TECHNICAL_MEMORY", memory.responsibility)
        self.assertIn("TECHNICAL_MEMORY_PERSISTENCE", memory.reason_codes)
        self.assertEqual("AUTONOMY_CONTROL", status.responsibility)
        self.assertIn("CALIBRATION_MODULE_BLOCKED", status.reason_codes)

    def test_semantica_permite_utilitario_e_read_only_e_bloqueia_efeitos(self):
        (self.root / "aya" / "core" / "safe_tools.py").write_text(
            "def normalize_name(value):\n"
            "    return value.strip().lower()\n\n"
            "def describe_value(value):\n"
            "    return f'value={value}'\n\n"
            "def save_value(path, value):\n"
            "    path.write_text(value)\n\n"
            "def run_command():\n"
            "    import subprocess\n"
            "    return subprocess.run(['git', 'status'])\n\n"
            "def query_database(db):\n"
            "    return db.execute('select 1')\n",
            encoding="utf-8",
        )
        pure = self.service._semantic_safety("aya/core/safe_tools.py", "normalize_name")
        read_only = self.service._semantic_safety("aya/core/safe_tools.py", "describe_value")
        write = self.service._semantic_safety("aya/core/safe_tools.py", "save_value")
        command = self.service._semantic_safety("aya/core/safe_tools.py", "run_command")
        database = self.service._semantic_safety("aya/core/safe_tools.py", "query_database")
        self.assertEqual("LOW", pure.sensitivity)
        self.assertIn(pure.responsibility, {"PURE_UTILITY", "READ_ONLY_QUERY", "DOCUMENTATION_ONLY"})
        self.assertEqual("LOW", read_only.sensitivity)
        self.assertNotEqual("LOW", write.sensitivity)
        self.assertIn("UNKNOWN_SIDE_EFFECTS", write.reason_codes)
        self.assertEqual("COMMAND_EXECUTION", command.responsibility)
        self.assertIn("COMMAND_EXECUTION_PATH", command.reason_codes)
        self.assertEqual("DATABASE", database.responsibility)
        self.assertIn("TECHNICAL_MEMORY_PERSISTENCE", database.reason_codes)

    def test_shortlist_calibracao_mostra_apenas_candidatos_low_e_limita_cinco(self):
        response = self.service.calibration_candidates()
        if "Nenhum candidato" not in response:
            self.assertLessEqual(response.count("- AUTO-"), 5)
            self.assertIn("sensibilidade=LOW", response)
        self.assertEqual([], self.service.llm.calls)

    def test_explicar_calibracao_e_somente_leitura_e_sem_modelo(self):
        candidate = next(item for item in self.service._autonomous_candidates(force=True) if item.qualification_status == "ACAO_RECOMENDADA")
        response = self.service.explain_calibration_candidate(candidate.candidate_id)
        self.assertIn("Execucao automatica: nao", response)
        self.assertIn("Responsabilidade:", response)
        self.assertIn("Sensibilidade:", response)
        self.assertEqual([], self.service.llm.calls)

    def test_criacao_de_experimento_bloqueia_arquivo_central(self):
        (self.root / "app.py").write_text(
            "def create_app(value):\n"
            "    if value:\n"
            "        return {'server_name': '127.0.0.1'}\n"
            "    return {}\n",
            encoding="utf-8",
        )
        candidate = self.service._build_candidate(
            source="ast:missing_docstring",
            title="Adicionar docstring em create_app",
            problem="Sem docstring.",
            evidence=["app.py:1 sem docstring"],
            category="documentacao",
            operation_type="insert_docstring",
            files=["app.py"],
            symbols=["create_app"],
            estimated_changed_lines=1,
            required_tests=[],
            reason="docstring ausente",
            expected_change="inserir docstring em create_app",
            symbol_signature="create_app(value)",
            stats=self.service._operation_stats(),
            qualification={
                "detection_valid": True,
                "relevance_valid": True,
                "actionable": True,
                "qualification_status": "ACAO_RECOMENDADA",
                "qualification_reasons": ["PUBLIC_SYMBOL", "PUBLIC_NONTRIVIAL_SYMBOL"],
                "documentation_value_score": 70,
                "documentation_value_reasons": ["teste"],
                "reason_codes": ["PUBLIC_SYMBOL", "PUBLIC_NONTRIVIAL_SYMBOL"],
            },
            ruff_diagnostic={},
            file_sha256=self.service._file_sha256("app.py"),
        )
        allowed, reasons = self.service._calibration_candidate_allowed(candidate)
        self.assertFalse(allowed)
        self.assertIn("modulo central bloqueado para primeira calibracao", reasons)

    def test_hash_alterado_e_docstring_adicionada_tornam_candidato_obsoleto(self):
        self.seed_successful_docstring_history(production_real=True)
        candidate = self.service._select_best_candidate()
        self.assertIsNotNone(candidate)
        (self.root / candidate.file).write_text(
            "class Sample:\n"
            "    def run(self, value):\n"
            "        \"\"\"Return value.\"\"\"\n"
            "        return value\n",
            encoding="utf-8",
        )
        stale = self.service._validate_current_candidate(candidate)
        self.assertTrue(stale.stale)
        self.assertIn("hash", stale.stale_reason)

    def test_replace_exact_sem_texto_torna_obsoleto(self):
        (self.root / "aya" / "core" / "sample.py").write_text(
            "import json\n\nclass Sample:\n    def run(self, value):\n        return value\n",
            encoding="utf-8",
        )
        candidate = next(item for item in self.service._autonomous_candidates() if item.operation_type == "replace_exact")
        (self.root / candidate.file).write_text("class Sample:\n    pass\n", encoding="utf-8")
        stale = self.service._validate_current_candidate(candidate)
        self.assertTrue(stale.stale)

    def test_observar_nao_chama_modelo_nao_cria_worktree_nem_altera_git(self):
        self.init_git()
        before = subprocess.run(("git", "status", "--porcelain"), cwd=self.root, capture_output=True, text=True, check=True).stdout
        response = self.service.observe_cycle()
        after = subprocess.run(("git", "status", "--porcelain"), cwd=self.root, capture_output=True, text=True, check=True).stdout
        self.assertIn("Modelo chamado: nao", response)
        self.assertIn("Worktree criado: nao", response)
        self.assertEqual(before, after)
        self.assertEqual([], list((self.root.parent / "workspaces").glob("*")) if (self.root.parent / "workspaces").exists() else [])
        self.assertEqual([], self.service.llm.calls)

    def test_rota_deterministica_e_nao_chama_modelo(self):
        self.seed_successful_docstring_history(production_real=True)
        candidate = self.service._select_best_candidate()
        first = self.service.explain_route(candidate.candidate_id)
        second = self.service.explain_route(candidate.candidate_id)
        self.assertEqual(first, second)
        self.assertIn("nao executa patch", first)
        self.assertEqual([], self.service.llm.calls)

    def test_candidato_obsoleto_nao_executa(self):
        self.init_git()
        self.seed_successful_docstring_history(production_real=True)
        candidate = self.service._select_best_candidate()
        (self.root / candidate.file).write_text("# mudou\n", encoding="utf-8")
        self.service.set_autonomy_mode("preparar-supervisionado")
        self.assertIn("alteracao", self.service.execute_candidate(candidate.candidate_id))

    def _fast_validation(self, workspace, related_tests=None):
        return [
            CheckResult("pytest", "python -m pytest", 0, 1, "ok"),
            CheckResult("ruff", "python -m ruff check .", 0, 1, "ok"),
            CheckResult("compileall", "python -m compileall .", 0, 1, "ok"),
            CheckResult("pip check", "python -m pip check", 0, 1, "ok"),
            CheckResult("smoke", "python scripts/smoke_test.py", 0, 1, "ok"),
        ]


if __name__ == "__main__":
    unittest.main()
