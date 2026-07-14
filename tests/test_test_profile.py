import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import pytest

from aya.core.assistant import Assistant
from aya.core.llm import StaticClient
from aya.data.database import Database
from scripts.pytest_profile_plugin import AyaProfile


class TestProfileTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "test.db")
        self.aya = Assistant(db=self.db, llm=StaticClient("ok"))
        self.aya.release.test_profiles_dir = self.root / "profiles"

    def tearDown(self):
        self.aya.encerrar()
        self.tmp.cleanup()

    @pytest.mark.integration
    def test_plugin_registra_duracao_fases_outcome_marcadores_e_head(self):
        sample = self.root / "test_sample_profile.py"
        output = self.root / "profile.json"
        sample.write_text(
            "import pytest\n\n"
            "@pytest.mark.unit\n"
            "def test_ok():\n"
            "    assert True\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                "python",
                "-m",
                "pytest",
                str(sample),
                "-q",
                "-p",
                "scripts.pytest_profile_plugin",
                "--aya-profile-output",
                str(output),
            ],
            cwd=Path.cwd(),
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        data = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(0, result.returncode)
        self.assertEqual(1, data["total_collected"])
        self.assertEqual(1, data["total_passed"])
        self.assertIn("project_head", data)
        self.assertIn("environment_fingerprint", data)
        self.assertNotIn("token", data["environment_fingerprint"].lower())
        test = data["tests"][0]
        self.assertEqual("passed", test["outcome"])
        self.assertIn("setup_ms", test)
        self.assertIn("call_ms", test)
        self.assertIn("teardown_ms", test)
        self.assertIn("unit", test["markers"])

    def test_relatorio_ordena_lentos_e_calcula_arquivo_marcador_limites(self):
        data = self._profile_data(
            tests=[
                self._test("tests/a.py::test_fast", 100, ["unit"]),
                self._test("tests/b.py::test_slow", 61000, ["integration"]),
            ],
            commands=[],
        )

        markdown = self.aya.release._profile_markdown(data)

        self.assertLess(markdown.index("tests/b.py::test_slow"), markdown.index("tests/a.py::test_fast"))
        self.assertIn("tests/b.py", markdown)
        self.assertIn("integration", markdown)
        self.assertIn(">= 60s: 1 teste(s)", markdown)

    def test_subprocessos_sao_normalizados_e_segredos_ocultados(self):
        profile = AyaProfile(str(self.root / "profile.json"))

        normalized = profile._normalize_command(["tool", "--token", "abc123", "api_key=segredo"])

        self.assertIn("--token [segredo ocultado]", normalized)
        self.assertNotIn("abc123", normalized)
        self.assertNotIn("api_key=segredo", normalized)

    def test_comando_perfil_com_runner_fake_nao_executa_pytest_real(self):
        def runner(command, timeout):
            output = Path(command[command.index("--aya-profile-output") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(self._profile_data()), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

        self.aya.release.runner = runner

        resposta = self.aya.responder("/release perfil-testes rapido")

        self.assertIn("Perfil de desempenho dos testes", resposta)
        self.assertIn("A suite rapida nao substitui o release completo", resposta)

    def test_comando_leitura_nao_executa_pytest(self):
        self.aya.release.test_profiles_dir.mkdir(parents=True)
        (self.aya.release.test_profiles_dir / "test_profile_20200101_rapido.json").write_text(
            json.dumps(self._profile_data()),
            encoding="utf-8",
        )

        def runner(command, timeout):
            raise AssertionError("nao deveria executar pytest")

        self.aya.release.runner = runner

        resposta = self.aya.responder("/release perfil-testes ultimo")

        self.assertIn("Perfil de desempenho dos testes", resposta)

    def test_historico_de_perfis(self):
        self.aya.release.test_profiles_dir.mkdir(parents=True)
        (self.aya.release.test_profiles_dir / "baseline_manual.json").write_text(
            json.dumps(self._profile_data()),
            encoding="utf-8",
        )

        resposta = self.aya.responder("/release perfil-testes historico")

        self.assertIn("Historico de perfis de teste", resposta)

    def test_marcadores_estao_configurados(self):
        text = Path("pytest.ini").read_text(encoding="utf-8")

        for marker in ("unit", "integration", "git", "ui", "ollama", "slow", "release_full"):
            self.assertIn(f"{marker}:", text)

    def test_comparacao_respeita_tolerancia(self):
        previous = self._profile_data(profile_id="TP-OLD", duration=10_000)
        current = self._profile_data(profile_id="TP-NEW", duration=10_400)
        self.aya.release.test_profiles_dir.mkdir(parents=True)
        (self.aya.release.test_profiles_dir / "test_profile_old.json").write_text(
            json.dumps(previous),
            encoding="utf-8",
        )

        lines = self.aya.release._profile_comparison_lines(current)

        self.assertIn("dentro da tolerancia", "\n".join(lines))

    def _profile_data(self, profile_id="TP-TEST", duration=1000, tests=None, commands=None):
        tests = tests if tests is not None else [self._test("tests/a.py::test_ok", 10, ["unit"])]
        return {
            "profile_id": profile_id,
            "project_head": "abc",
            "started_at": "2026-07-13T10:00:00",
            "finished_at": "2026-07-13T10:00:01",
            "total_duration_ms": duration,
            "python_version": "3.14.6",
            "pytest_version": "9.1.1",
            "environment_fingerprint": "safehash",
            "total_collected": len(tests),
            "total_passed": len(tests),
            "total_failed": 0,
            "total_skipped": 0,
            "tests": tests,
            "commands": commands if commands is not None else [],
        }

    def _test(self, nodeid, total_ms, markers):
        return {
            "nodeid": nodeid,
            "arquivo": nodeid.split("::", 1)[0],
            "classe": "",
            "funcao": nodeid.split("::")[-1],
            "outcome": "passed",
            "setup_ms": 1,
            "call_ms": total_ms - 2,
            "teardown_ms": 1,
            "total_ms": total_ms,
            "markers": markers,
        }
