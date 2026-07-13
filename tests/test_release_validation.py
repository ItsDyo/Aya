import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aya.core.assistant import Assistant
from aya.core.llm import StaticClient
from aya.core.release import ReleaseTimeoutConfig
from aya.data.database import Database


class ReleaseValidationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "test.db")
        self.aya = Assistant(db=self.db, llm=StaticClient("ok"))
        self.aya.release.releases_dir = self.root / "releases"
        self.aya.release.evidence_dir = self.root / "evidence"

    def tearDown(self):
        self.aya.encerrar()
        self.tmp.cleanup()

    def _runner(self, code: int = 0, stdout: str = "ok"):
        def runner(command, timeout):
            return subprocess.CompletedProcess(command, code, stdout=stdout, stderr="")

        return runner

    def test_exit_code_zero_produz_aprovado(self):
        self.aya.release.runner = self._runner(0)

        resposta = self.aya.responder("/release validar rapido")

        self.assertIn("pytest: APROVADO", resposta)
        self.assertIn("Status geral: APROVADO", resposta)

    def test_exit_code_diferente_de_zero_produz_reprovado(self):
        self.aya.release.runner = self._runner(1, "falha real")

        resposta = self.aya.responder("/release validar rapido")

        self.assertIn("pytest: REPROVADO", resposta)
        self.assertIn("Status geral: REPROVADO", resposta)

    def test_timeout_produz_timeout_e_nao_reprovado(self):
        def runner(command, timeout):
            if "pytest" in command:
                raise subprocess.TimeoutExpired(command, timeout, output="saida parcial")
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

        self.aya.release.runner = runner

        resposta = self.aya.responder("/release validar completo")

        self.assertIn("pytest: TIMEOUT", resposta)
        self.assertIn("Status geral: PARCIAL", resposta)
        self.assertNotIn("pytest: REPROVADO", resposta)
        self.assertIn("saida parcial", resposta)
        self.assertIn("nao comprova reprovacao da suite", resposta)

    def test_comando_ausente_produz_indisponivel(self):
        def runner(command, timeout):
            if "ruff" in command:
                raise FileNotFoundError("ruff nao encontrado")
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

        self.aya.release.runner = runner

        resposta = self.aya.responder("/release validar rapido")

        self.assertIn("ruff: INDISPONIVEL", resposta)
        self.assertIn("Status geral: PARCIAL", resposta)

    def test_check_nao_executado_aparece_no_relatorio_estatico(self):
        resposta = self.aya.responder("/release")

        self.assertIn("pytest: NAO_EXECUTADO", resposta)
        self.assertIn("Status geral: PARCIAL", resposta)

    def test_erro_interno_e_separado(self):
        def runner(command, timeout):
            raise RuntimeError("infra quebrou")

        self.aya.release.runner = runner

        resposta = self.aya.responder("/release validar rapido")

        self.assertIn("ERRO_INTERNO", resposta)
        self.assertIn("Status geral: ERRO", resposta)

    def test_modo_rapido_usa_escopo_curto(self):
        comandos = []

        def runner(command, timeout):
            comandos.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

        self.aya.release.runner = runner

        self.aya.responder("/release validar rapido")

        self.assertIn("tests/test_aya.py", comandos[0])
        self.assertIn("-k", comandos[0])

    def test_modo_completo_e_compatibilidade_validar(self):
        comandos = []

        def runner(command, timeout):
            comandos.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

        self.aya.release.runner = runner

        resposta = self.aya.responder("/release validar")

        self.assertIn("Modo: completo", resposta)
        self.assertEqual([os.sys.executable, "-m", "pytest"], comandos[0])

    def test_timeout_padrao_e_por_ambiente(self):
        with patch.dict(os.environ, {"AYA_RELEASE_PYTEST_TIMEOUT": "1300"}, clear=False):
            config = ReleaseTimeoutConfig.from_env()

        self.assertEqual(1300, config.pytest_complete)

    def test_timeout_invalido_usa_padrao_e_limites(self):
        with patch.dict(os.environ, {"AYA_RELEASE_PYTEST_TIMEOUT": "-5"}, clear=False):
            baixo = ReleaseTimeoutConfig.from_env()
        with patch.dict(os.environ, {"AYA_RELEASE_PYTEST_TIMEOUT": "999999"}, clear=False):
            alto = ReleaseTimeoutConfig.from_env()
        with patch.dict(os.environ, {"AYA_RELEASE_PYTEST_TIMEOUT": "abc"}, clear=False):
            invalido = ReleaseTimeoutConfig.from_env()

        self.assertEqual(60, baixo.pytest_complete)
        self.assertEqual(2400, alto.pytest_complete)
        self.assertEqual(2400, invalido.pytest_complete)

    def test_timeout_adaptativo_minimo_maximo_e_historico_timeout_nao_reduz(self):
        service = self.aya.release
        service.timeout_config = ReleaseTimeoutConfig(adaptive_minimum=900, adaptive_maximum=2400)
        with patch.object(service, "_working_tree_clean", return_value=True), patch.object(
            service, "_project_head", return_value="abc"
        ):
            service._save_evidence(
                name="pytest",
                command=[os.sys.executable, "-m", "pytest"],
                mode="completo",
                scope="suite_completa",
                returncode=0,
                state="APROVADO",
                started_at=service._parse_created_at("2026-07-13 10:00:00"),
                duration_seconds=807,
                output="ok",
                timeout_seconds=1200,
                timeout_source="configuracao",
            )
            service._save_evidence(
                name="pytest",
                command=[os.sys.executable, "-m", "pytest"],
                mode="completo",
                scope="suite_completa",
                returncode=None,
                state="TIMEOUT",
                started_at=service._parse_created_at("2026-07-13 10:10:00"),
                duration_seconds=100,
                output="timeout",
                timeout_seconds=100,
                timeout_source="configuracao",
            )

            self.assertEqual(1210, service._adaptive_pytest_timeout())

    def test_evidencia_armazena_head_duracao_e_fingerprint_sem_credencial(self):
        segredo = "sk-super-secreto"
        self.aya.release.runner = self._runner(0, f"token={segredo}")

        resposta = self.aya.responder("/release validar rapido")
        evidence_files = list(self.aya.release.evidence_dir.glob("VAL-*.json"))
        text = "\n".join(path.read_text(encoding="utf-8") for path in evidence_files)

        self.assertIn("evidencia_id: VAL-", resposta)
        self.assertIn("project_head", text)
        self.assertIn("duration_ms", text)
        self.assertIn("environment_fingerprint", text)
        self.assertNotIn(segredo, resposta)
        self.assertNotIn(segredo, text)

    def test_reutilizacao_com_head_identico_aparece_no_relatorio(self):
        service = self.aya.release
        service.runner = self._runner(0, "ok")
        with patch.object(service, "_working_tree_clean", return_value=True), patch.object(
            service, "_project_head", return_value="abc"
        ):
            service.validar(mode="completo")
            resposta = service.validar(mode="completo", reuse=True)

        self.assertIn("origem_resultado: reutilizado", resposta)
        self.assertIn("Resultado reutilizado de evidencia aprovada", resposta)

    def test_reutilizacao_bloqueada_com_head_diferente(self):
        service = self.aya.release
        chamadas = 0

        def runner(command, timeout):
            nonlocal chamadas
            chamadas += 1
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

        service.runner = runner
        with patch.object(service, "_working_tree_clean", return_value=True), patch.object(
            service, "_project_head", return_value="abc"
        ):
            service.validar(mode="completo")
        with patch.object(service, "_working_tree_clean", return_value=True), patch.object(
            service, "_project_head", return_value="def"
        ):
            service.validar(mode="completo", reuse=True)

        self.assertGreater(chamadas, 5)

    def test_reutilizacao_bloqueada_com_working_tree_sujo(self):
        service = self.aya.release
        chamadas = 0

        def runner(command, timeout):
            nonlocal chamadas
            chamadas += 1
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

        service.runner = runner
        with patch.object(service, "_working_tree_clean", return_value=True), patch.object(
            service, "_project_head", return_value="abc"
        ):
            service.validar(mode="completo")
        with patch.object(service, "_working_tree_clean", return_value=False), patch.object(
            service, "_project_head", return_value="abc"
        ):
            resposta = service.validar(mode="completo", reuse=True)

        self.assertNotIn("origem_resultado: reutilizado", resposta)
        self.assertGreater(chamadas, 5)

    def test_reutilizacao_bloqueada_por_expiracao_comando_e_python(self):
        service = self.aya.release
        service.timeout_config = ReleaseTimeoutConfig(reuse_window_seconds=0)
        old_start = service._parse_created_at("2020-01-01 10:00:00")
        service._save_evidence(
            name="pytest",
            command=[os.sys.executable, "-m", "pytest"],
            mode="completo",
            scope="suite_completa",
            returncode=0,
            state="APROVADO",
            started_at=old_start,
            duration_seconds=1,
            output="ok",
            timeout_seconds=1200,
            timeout_source="configuracao",
        )

        with patch.object(service, "_working_tree_clean", return_value=True), patch.object(
            service, "_project_head", return_value=service._project_head()
        ):
            self.assertIsNone(service._find_reusable_evidence("pytest", [os.sys.executable, "-m", "pytest"], "completo", "suite_completa"))
            self.assertIsNone(service._find_reusable_evidence("pytest", [os.sys.executable, "-m", "pytest", "-q"], "completo", "suite_completa"))
            with patch("platform.python_version", return_value="0.0.0"):
                self.assertIsNone(service._find_reusable_evidence("pytest", [os.sys.executable, "-m", "pytest"], "completo", "suite_completa"))

    def test_release_antigo_continua_legivel(self):
        releases_dir = self.aya.release.releases_dir
        releases_dir.mkdir(parents=True)
        (releases_dir / "release_20200101_100000.md").write_text(
            "Relatorio tecnico de release da Aya\n"
            "Gerado em: 2020-01-01 10:00:00\n"
            "Release completo: sim\n"
            "- pytest: APROVADO\n"
            "- ruff: APROVADO\n"
            "- compileall: APROVADO\n"
            "- pip check: APROVADO\n"
            "- smoke_test.py: APROVADO\n",
            encoding="utf-8",
        )

        status = self.aya.responder("/release status")

        self.assertIn("Status de release", status)
        self.assertIn("Ultimo release completo", status)

    def test_aya_inicializa_normalmente(self):
        self.assertIn("Aya", self.aya.responder("/status"))


if __name__ == "__main__":
    unittest.main()
