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

    def seed_successful_docstring_history(self, total: int = 3):
        for index in range(total):
            proposal = self.service.create_proposal(
                title=f"Historico docstring {index}",
                problem="Documentar simbolo simples.",
                evidence=["teste"],
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
        self.seed_successful_docstring_history()
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
        self.seed_successful_docstring_history()
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
        self.seed_successful_docstring_history()
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
