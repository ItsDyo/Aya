from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from aya.core.aya_dev import AyaDevService
from aya.core.dev_workspace import CheckResult, GitState
from aya.core.llm import StaticClient
from aya.core.project_tools import ProjectTools


class FailingClient:
    def chat(self, **kwargs):
        raise RuntimeError("ollama offline token=segredo")


class AyaDevTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "projeto"
        (self.root / "aya" / "core").mkdir(parents=True)
        (self.root / "tests").mkdir()
        (self.root / "scripts").mkdir()
        (self.root / "aya" / "core" / "sample.py").write_text(
            "import json\n\nclass Sample:\n    def run(self, value: str) -> str:\n        return json.dumps(value)\n",
            encoding="utf-8",
        )
        (self.root / "tests" / "test_sample.py").write_text(
            "from aya.core.sample import Sample\n\ndef test_sample():\n    assert Sample().run('x')\n",
            encoding="utf-8",
        )
        (self.root / "scripts" / "smoke_test.py").write_text("print('ok')\n", encoding="utf-8")
        self.storage = self.root / "state" / "history.json"
        self.cache = self.root / "state" / "index.json"
        self.workspaces = self.root.parent / "workspaces"
        self.client = StaticClient("Plano pequeno e verificavel.")
        self.service = AyaDevService(
            self.root,
            self.client,
            ProjectTools(self.root),
            storage_path=self.storage,
            index_path=self.cache,
            workspace_root=self.workspaces,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def proposal(self, **overrides):
        values = {
            "title": "Melhorar Sample",
            "problem": "Metodo run precisa de caracterizacao.",
            "evidence": ["Indice AST confirmou aya/core/sample.py."],
            "related_files": ["aya/core/sample.py", "tests/test_sample.py"],
            "related_symbols": ["Sample", "run"],
            "probable_cause": "Responsabilidade pouco explicita.",
            "suggested_change": "Adicionar teste pequeno.",
            "preserve": ["retorno atual"],
            "impact": "baixo",
            "urgency": "baixa",
            "difficulty": "baixa",
            "required_tests": ["tests/test_sample.py"],
            "done_criteria": ["testes passam"],
        }
        values.update(overrides)
        return self.service.create_proposal(**values)

    def init_git(self, dirty: bool = False):
        commands = [
            ("git", "init"),
            ("git", "config", "user.email", "aya@example.local"),
            ("git", "config", "user.name", "Aya Tests"),
            ("git", "add", "."),
            ("git", "commit", "-m", "baseline"),
        ]
        for command in commands:
            subprocess.run(command, cwd=self.root, capture_output=True, check=True)
        if dirty:
            (self.root / "aya" / "core" / "sample.py").write_text("# alterado\n", encoding="utf-8")

    def test_indice_ast_registra_simbolos_assinaturas_chamadas_e_testes(self):
        entry = next(item for item in self.service.index.build() if item.path == "aya/core/sample.py")
        self.assertIn("Sample", entry.classes)
        self.assertIn("run", entry.methods)
        self.assertIn("run(self, value)", entry.signatures)
        self.assertIn("json.dumps", entry.calls)
        self.assertIn("tests/test_sample.py", entry.related_tests)

    def test_indice_invalida_cache_quando_hash_muda(self):
        before = next(item for item in self.service.index.build() if item.path.endswith("sample.py"))
        path = self.root / "aya" / "core" / "sample.py"
        path.write_text(path.read_text(encoding="utf-8") + "\n# TODO revisar\n", encoding="utf-8")
        after = next(item for item in self.service.index.build() if item.path.endswith("sample.py"))
        self.assertNotEqual(before.sha256, after.sha256)
        self.assertTrue(after.markers)

    def test_selecao_relevante_nao_envia_projeto_inteiro(self):
        selected = self.service.index.select("classe Sample run", limit=1)
        self.assertEqual(["aya/core/sample.py"], [item.path for item in selected])

    def test_proposta_exige_evidencia_e_arquivo_real(self):
        proposal = self.proposal()
        self.assertTrue(proposal.evidence)
        self.assertEqual("PROPOSTA", proposal.state)

    def test_proposta_rejeita_arquivo_inventado(self):
        with self.assertRaisesRegex(ValueError, "nao confirmado"):
            self.proposal(related_files=["aya/core/inventado.py"])

    def test_risco_deterministico(self):
        self.assertEqual("alto", self.service.classify_risk("alterar autenticacao", ["aya/auth.py"]))
        self.assertEqual("alto", self.service.classify_risk("refatorar", ["aya/data/database.py"]))
        self.assertEqual("medio", self.service.classify_risk("organizar", ["aya/core/assistant.py"]))
        self.assertEqual("baixo", self.service.classify_risk("documentar", ["aya/core/sample.py"]))

    def test_modelo_nao_reduz_risco_obrigatorio(self):
        risk = self.service.classify_risk("migracao do banco", ["aya/data/database.py"], model_risk="baixo")
        self.assertEqual("alto", risk)

    def test_patch_bloqueia_caminho_fora_da_raiz(self):
        result = self.service.workspace.inspect_patch("--- a/../fora.py\n+++ b/../fora.py\n@@ -0,0 +1 @@\n+x\n")
        self.assertFalse(result.valid)
        self.assertIn("fora da raiz", result.message)

    def test_patch_bloqueia_link_simbolico_externo(self):
        external = self.root.parent / "outside.py"
        external.write_text("x = 1\n", encoding="utf-8")
        link = self.root / "linked.py"
        try:
            link.symlink_to(external)
        except OSError:
            external_resolved = external.resolve()
            with (
                patch.object(Path, "is_symlink", return_value=True),
                patch.object(Path, "resolve", return_value=external_resolved),
            ):
                result = self.service.workspace.inspect_patch(
                    "--- a/linked.py\n+++ b/linked.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
                )
        else:
            result = self.service.workspace.inspect_patch(
                "--- a/linked.py\n+++ b/linked.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
            )
        self.assertFalse(result.valid)
        self.assertIn("simbolico", result.message)

    def test_git_indisponivel_bloqueia_preparacao(self):
        state = self.service.workspace.git_state()
        self.assertFalse(state.valid)
        self.assertIn("BLOQUEADA", self.service.status())

    def test_git_com_alteracoes_nao_salvas(self):
        self.init_git(dirty=True)
        state = self.service.workspace.git_state()
        self.assertTrue(state.valid)
        self.assertFalse(state.clean)
        self.assertTrue(state.changed_files)

    def test_cria_worktree_isolado_sem_alterar_raiz(self):
        self.init_git()
        original = hashlib.sha256((self.root / "aya/core/sample.py").read_bytes()).hexdigest()
        workspace = self.service.workspace.create("DEV-TESTE")
        self.assertTrue((workspace / "aya/core/sample.py").exists())
        self.assertEqual(original, hashlib.sha256((self.root / "aya/core/sample.py").read_bytes()).hexdigest())
        self.service.workspace.discard(workspace)

    def test_baseline_falhando_impede_chamada_ao_modelo(self):
        proposal = self.proposal()
        proposal.state = "PLANEJADA"
        fake_workspace = self.workspaces / proposal.id
        fake_workspace.mkdir(parents=True)
        self.service.workspace.git_state = Mock(return_value=GitState(True, True, "ok"))
        self.service.workspace.create = Mock(return_value=fake_workspace)
        self.service.workspace.baseline = Mock(return_value=[CheckResult("pytest", "python -m pytest", 1, 1, "falhou")])
        calls_before = len(self.client.calls)
        response = self.service.preparar(proposal.id)
        self.assertIn("Baseline falhou", response)
        self.assertEqual(calls_before, len(self.client.calls))

    def test_patch_excedendo_limite_de_linhas(self):
        body = "\n".join(f"+linha {number}" for number in range(251))
        patch_text = f"--- a/aya/core/sample.py\n+++ b/aya/core/sample.py\n@@ -1 +1,251 @@\n-x\n{body}\n"
        result = self.service.workspace.inspect_patch(patch_text)
        self.assertFalse(result.valid)
        self.assertIn("250 linhas", result.message)

    def test_patch_bloqueia_arquivo_protegido(self):
        result = self.service.workspace.inspect_patch("--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n-A=x\n+A=y\n")
        self.assertFalse(result.valid)
        self.assertIn("protegido", result.message)

    def test_extrator_preserva_quebra_final_exigida_pelo_git(self):
        patch_text = self.service._extract_patch(
            "```diff\n--- a/aya/core/sample.py\n+++ b/aya/core/sample.py\n@@ -1 +1 @@\n-import json\n+import re\n```"
        )

        self.assertTrue(patch_text.endswith("\n"))

    def test_limite_de_duas_tentativas(self):
        proposal = self.proposal()
        proposal.state = "FALHOU"
        proposal.attempts = 2
        self.assertIn("Limite de 2", self.service.preparar(proposal.id))

    def test_revisao_local_usa_modelo_revisor_sem_aprovar(self):
        proposal = self.proposal()
        proposal.patch = "diff --git a/a.py b/a.py\n"
        before = proposal.state
        response = self.service.revisar(proposal.id)
        self.assertIn("reviewer" if self.service.reviewer_model == "reviewer" else self.service.reviewer_model, response)
        self.assertEqual(before, proposal.state)
        self.assertEqual(self.service.reviewer_model, self.client.calls[-1]["model"])

    def test_ollama_indisponivel_falha_de_forma_sanitizada(self):
        service = AyaDevService(
            self.root,
            FailingClient(),
            ProjectTools(self.root),
            storage_path=self.storage,
            index_path=self.cache,
            workspace_root=self.workspaces,
        )
        proposal = service.create_proposal(**self._proposal_values())
        response = service.planejar(proposal.id)
        self.assertIn("indisponivel", response)
        self.assertNotIn("segredo", response)

    def test_validacao_aprovada_aguarda_aprovacao(self):
        proposal = self.proposal()
        proposal.patch = "diff"
        proposal.workspace = str(self.workspaces / proposal.id)
        self.service.workspace.validate = Mock(return_value=[CheckResult("pytest", "python -m pytest", 0, 2, "ok")])
        response = self.service.testar(proposal.id)
        self.assertIn("AGUARDANDO_APROVACAO", response)
        self.assertEqual("AGUARDANDO_APROVACAO", proposal.state)

    def test_validacao_reprovada_bloqueia_aprovacao(self):
        proposal = self.proposal()
        proposal.patch = "diff"
        proposal.workspace = str(self.workspaces / proposal.id)
        self.service.workspace.validate = Mock(return_value=[CheckResult("pytest", "python -m pytest", 1, 2, "erro")])
        self.service.testar(proposal.id)
        self.assertEqual("FALHOU", proposal.state)
        self.assertIn("recusada", self.service.aprovar(proposal.id))

    def test_diff_e_somente_leitura(self):
        proposal = self.proposal()
        proposal.patch = "diff --git a/a.py b/a.py"
        before = self.storage.read_bytes()
        response = self.service.diff(proposal.id)
        self.assertIn("somente leitura", response)
        self.assertEqual(before, self.storage.read_bytes())

    def test_historico_tecnico_persiste_separado(self):
        proposal = self.proposal()
        loaded = AyaDevService(
            self.root,
            self.client,
            ProjectTools(self.root),
            storage_path=self.storage,
            index_path=self.cache,
            workspace_root=self.workspaces,
        )
        self.assertIn(proposal.id, loaded.proposals)
        self.assertIn(proposal.id, loaded.history())

    def test_conteudo_sensivel_e_sanitizado(self):
        output = self.service.workspace.sanitize("token=abc123 password='muito-secreto'")
        self.assertNotIn("abc123", output)
        self.assertNotIn("muito-secreto", output)

    def test_pacote_codex_contem_contexto_minimo(self):
        proposal = self.proposal()
        proposal.attempts = 2
        proposal.review_result = "Falta teste de regressao."
        package = self.service.pacote_codex(proposal.id)
        self.assertIn("Pacote tecnico para Codex", package)
        self.assertIn("Evidencias", package)
        self.assertIn("Tentativas: 2/2", package)

    def test_preparacao_nao_modifica_projeto_principal(self):
        proposal = self.proposal()
        proposal.state = "PLANEJADA"
        original = (self.root / "aya/core/sample.py").read_bytes()
        self.service.workspace.git_state = Mock(return_value=GitState(False, False, "invalido"))
        self.service.preparar(proposal.id)
        self.assertEqual(original, (self.root / "aya/core/sample.py").read_bytes())

    def test_validacao_nao_executa_comando_arbitrario_do_modelo(self):
        workspace = self.workspaces / "safe"
        workspace.mkdir(parents=True)
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, "ok", ""))
        self.service.workspace._run = runner
        self.service.workspace.validate(workspace)
        commands = [call.args[0] for call in runner.call_args_list]
        self.assertEqual(5, len(commands))
        self.assertTrue(all(command[0] == "python" for command in commands))
        self.assertFalse(any("del" in command or "powershell" in command for command in commands))

    def test_comandos_basicos_e_aprovacao_apenas_registram(self):
        proposal = self.proposal()
        proposal.state = "AGUARDANDO_APROVACAO"
        self.assertIn("Aya Dev", self.service.execute("status"))
        self.assertIn("Arquivos Python", self.service.execute("mapear"))
        self.assertIn(proposal.id, self.service.execute("propostas"))
        self.assertIn("Nenhum patch foi aplicado", self.service.execute(f"aprovar {proposal.id}"))

    def _proposal_values(self):
        return {
            "title": "Melhorar Sample",
            "problem": "Metodo run precisa de caracterizacao.",
            "evidence": ["Indice AST confirmou aya/core/sample.py."],
            "related_files": ["aya/core/sample.py"],
            "related_symbols": ["Sample", "run"],
            "probable_cause": "Responsabilidade pouco explicita.",
            "suggested_change": "Adicionar teste pequeno.",
            "preserve": ["retorno atual"],
            "impact": "baixo",
            "urgency": "baixa",
            "difficulty": "baixa",
            "required_tests": ["tests/test_sample.py"],
            "done_criteria": ["testes passam"],
        }


class AssistantAyaDevInitializationTest(unittest.TestCase):
    def test_assistant_normal_continua_inicializando(self):
        from aya.core.assistant import Assistant
        from aya.core.llm import StaticClient
        from aya.data.database import Database

        with tempfile.TemporaryDirectory() as tmp:
            assistant = Assistant(db=Database(Path(tmp) / "test.db"), llm=StaticClient())
            self.assertIn("Aya Dev", assistant.responder("/aya-dev status"))
            assistant.encerrar()


if __name__ == "__main__":
    unittest.main()
