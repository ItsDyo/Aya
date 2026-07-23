from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from aya.core.aya_dev import AyaDevService, CalibrationExperiment
from aya.core.dev_workspace import (
    FULL_VALIDATION_PYTEST_TIMEOUT_SECONDS,
    RELATED_TEST_TIMEOUT_FALLBACK_SECONDS,
    RELATED_TEST_TIMEOUT_MAXIMUM_SECONDS,
    RELATED_TEST_TIMEOUT_MINIMUM_SECONDS,
    CheckResult,
    DevWorkspace,
    GitState,
    calculate_related_test_timeout,
)
from aya.core.llm import StaticClient
from aya.core.permissions import AccessChannel, PermissionManager
from aya.core.project_tools import ProjectTools
from aya.core.structured_patch import PATCH_MANIFEST_SCHEMA, StructuredPatchError
from aya.ui import aya_dev as aya_dev_ui
from aya.ui.aya_dev import AyaDevPanel, render_diff


class FailingClient:
    def chat(self, **kwargs):
        raise RuntimeError("ollama offline token=segredo")


class StructuredClient(StaticClient):
    def __init__(self, payload):
        super().__init__(json.dumps(payload) if not isinstance(payload, str) else payload)
        self.payload = payload

    def chat_structured(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.payload, Exception):
            raise self.payload
        if isinstance(self.payload, str):
            return self.payload
        return self.payload


class DynamicStructuredClient(StaticClient):
    def chat_structured(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "type": "insert_docstring",
            "symbol": "Sample.run",
            "content": "Executa sample.",
        }


class AyaDevTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "projeto"
        (self.root / "aya" / "core").mkdir(parents=True)
        (self.root / "tests").mkdir()
        (self.root / "scripts").mkdir()
        (self.root / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n*.pyc\n", encoding="utf-8")
        (self.root / "aya" / "core" / "sample.py").write_text(
            "import json\n\nclass Sample:\n    def run(self, value: str) -> str:\n        return json.dumps(value)\n",
            encoding="utf-8",
        )
        (self.root / "tests" / "test_sample.py").write_text(
            "from aya.core.sample import Sample\n\ndef test_sample():\n    assert Sample().run('x')\n",
            encoding="utf-8",
        )
        (self.root / "scripts" / "smoke_test.py").write_text("print('ok')\n", encoding="utf-8")
        self.storage = self.root.parent / "state" / "history.json"
        self.cache = self.root.parent / "state" / "index.json"
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
        self.service.workspace.validate = Mock(side_effect=self._fast_validation)
        self.service.workspace.baseline = Mock(side_effect=self._fast_validation)

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

    def test_diff_unificado_valido(self):
        result = self.service.workspace.inspect_patch(
            "--- a/aya/core/sample.py\n+++ b/aya/core/sample.py\n@@ -1 +1 @@\n-import json\n+import json\n",
            allowed_files=["aya/core/sample.py"],
        )
        self.assertTrue(result.valid)
        self.assertEqual(("aya/core/sample.py",), result.files)

    def test_patch_manifest_schema_basico(self):
        self.assertEqual(1, PATCH_MANIFEST_SCHEMA["properties"]["version"]["const"])
        operations = PATCH_MANIFEST_SCHEMA["properties"]["operations"]
        self.assertEqual(4, operations["maxItems"])
        self.assertEqual(["insert_docstring", "replace_exact"], operations["items"]["properties"]["type"]["enum"])

    def test_patch_decision_insert_docstring_completo(self):
        decision = self.service.structured_patch.parse_decision({
            "type": "insert_docstring",
            "symbol": "Sample.run",
            "content": "Executa sample.",
        })
        self.assertEqual("insert_docstring", decision["type"])

    def test_patch_decision_recusa_docstring_generica(self):
        with self.assertRaisesRegex(StructuredPatchError, "generica"):
            self.service.structured_patch.parse_decision({
                "type": "insert_docstring",
                "symbol": "render_diff",
                "content": "Document render_diff.",
            })

    def test_patch_decision_insert_docstring_sem_symbol(self):
        with self.assertRaisesRegex(StructuredPatchError, "symbol"):
            self.service.structured_patch.parse_decision({"type": "insert_docstring", "content": "x"})

    def test_patch_decision_insert_docstring_sem_content(self):
        with self.assertRaisesRegex(StructuredPatchError, "content"):
            self.service.structured_patch.parse_decision({"type": "insert_docstring", "symbol": "Sample.run"})

    def test_patch_decision_insert_docstring_campo_extra(self):
        with self.assertRaisesRegex(StructuredPatchError, "Campo extra"):
            self.service.structured_patch.parse_decision({
                "type": "insert_docstring",
                "symbol": "Sample.run",
                "content": "x",
                "file": "aya/core/sample.py",
            })

    def test_patch_decision_replace_exact_completo(self):
        decision = self.service.structured_patch.parse_decision({
            "type": "replace_exact",
            "old_text": "a",
            "new_text": "b",
        })
        self.assertEqual("replace_exact", decision["type"])

    def test_patch_decision_replace_exact_sem_old_text(self):
        with self.assertRaisesRegex(StructuredPatchError, "old_text"):
            self.service.structured_patch.parse_decision({"type": "replace_exact", "new_text": "b"})

    def test_patch_decision_mistura_campos_recusada(self):
        with self.assertRaisesRegex(StructuredPatchError, "Campo extra"):
            self.service.structured_patch.parse_decision({
                "type": "replace_exact",
                "old_text": "a",
                "new_text": "b",
                "symbol": "Sample.run",
            })

    def test_patch_manifest_json_invalido(self):
        with self.assertRaisesRegex(StructuredPatchError, "JSON invalido"):
            self.service.structured_patch.parse("{")

    def test_patch_manifest_markdown_recusado(self):
        with self.assertRaisesRegex(StructuredPatchError, "Markdown"):
            self.service.structured_patch.parse("```json\n{}\n```")

    def test_patch_manifest_operacao_desconhecida(self):
        manifest = self._manifest("desconhecida")
        with self.assertRaisesRegex(StructuredPatchError, "Operacao desconhecida"):
            self.service.structured_patch.parse(manifest)

    def test_patch_manifest_excesso_de_operacoes(self):
        manifest = self._manifest()
        manifest["operations"] = [manifest["operations"][0] for _ in range(5)]
        with self.assertRaisesRegex(StructuredPatchError, "limite"):
            self.service.structured_patch.parse(manifest)

    def test_texto_explicativo_e_recusado(self):
        result = self.service.workspace.inspect_patch(
            "Claro, aqui esta o patch:\n--- a/aya/core/sample.py\n+++ b/aya/core/sample.py\n@@ -1 +1 @@\n-a\n+b\n"
        )
        self.assertFalse(result.valid)
        self.assertIn("diff unificado puro", result.message)

    def test_markdown_e_recusado(self):
        with self.assertRaisesRegex(ValueError, "Markdown recusada"):
            self.service._extract_patch(
                "```diff\n--- a/aya/core/sample.py\n+++ b/aya/core/sample.py\n@@ -1 +1 @@\n-a\n+b\n```"
            )

    def test_diff_sem_hunk_e_recusado(self):
        result = self.service.workspace.inspect_patch("--- a/aya/core/sample.py\n+++ b/aya/core/sample.py\n")
        self.assertFalse(result.valid)
        self.assertIn("sem hunk", result.message)

    def test_arquivo_fora_da_proposta_e_recusado(self):
        result = self.service.workspace.inspect_patch(
            "--- a/aya/core/sample.py\n+++ b/aya/core/sample.py\n@@ -1 +1 @@\n-a\n+b\n",
            allowed_files=["tests/test_sample.py"],
        )
        self.assertFalse(result.valid)
        self.assertIn("fora do escopo", result.message)

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
        proposal.risk = "medio"
        fake_workspace = self.workspaces / proposal.id
        fake_workspace.mkdir(parents=True)
        self.service.workspace.git_state = Mock(return_value=GitState(True, True, "ok"))
        self.service.workspace.head = Mock(return_value="abc1234")
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

    def test_patch_manifest_arquivo_fora_da_proposta(self):
        workspace = self.root
        manifest = self._manifest(file="aya/core/sample.py")
        with self.assertRaisesRegex(StructuredPatchError, "fora da proposta"):
            self.service.structured_patch.apply(workspace, manifest, "DEV-20260713-ABCDEF", "abc1234", ["tests/test_sample.py"], ["Sample.run"])

    def test_patch_manifest_arquivo_protegido(self):
        manifest = self._manifest(file=".env")
        with self.assertRaisesRegex(StructuredPatchError, "protegido"):
            self.service.structured_patch.apply(self.root, manifest, "DEV-20260713-ABCDEF", "abc1234", [".env"], ["Sample.run"])

    def test_patch_manifest_hash_diferente(self):
        manifest = self._manifest(expected_sha256="0" * 64)
        with self.assertRaisesRegex(StructuredPatchError, "Hash diferente"):
            self.service.structured_patch.apply(self.root, manifest, "DEV-20260713-ABCDEF", "abc1234", ["aya/core/sample.py"], ["Sample.run"])

    def test_patch_manifest_simbolo_inexistente(self):
        manifest = self._manifest(symbol="Sample.inexistente")
        with self.assertRaisesRegex(StructuredPatchError, "Simbolo inexistente"):
            self.service.structured_patch.apply(self.root, manifest, "DEV-20260713-ABCDEF", "abc1234", ["aya/core/sample.py"], ["Sample.inexistente"])

    def test_patch_manifest_simbolo_ambiguo(self):
        path = self.root / "aya/core/sample.py"
        path.write_text(path.read_text(encoding="utf-8") + "\ndef run():\n    return 'x'\n", encoding="utf-8")
        manifest = self._manifest(symbol="run", expected_sha256=self._sha("aya/core/sample.py"))
        with self.assertRaisesRegex(StructuredPatchError, "ambiguo"):
            self.service.structured_patch.apply(self.root, manifest, "DEV-20260713-ABCDEF", "abc1234", ["aya/core/sample.py"], ["run"])

    def test_patch_manifest_docstring_ja_existente(self):
        manifest = self._manifest(content="Executa sample.")
        self.service.structured_patch.apply(self.root, manifest, "DEV-20260713-ABCDEF", "abc1234", ["aya/core/sample.py"], ["Sample.run"])
        manifest = self._manifest(expected_sha256=self._sha("aya/core/sample.py"), content="Executa sample.")
        with self.assertRaisesRegex(StructuredPatchError, "equivalente"):
            self.service.structured_patch.apply(self.root, manifest, "DEV-20260713-ABCDEF", "abc1234", ["aya/core/sample.py"], ["Sample.run"])

    def test_patch_manifest_insert_docstring_valido_e_indentado(self):
        manifest = self._manifest(content="Executa sample.")
        result = self.service.structured_patch.apply(self.root, manifest, "DEV-20260713-ABCDEF", "abc1234", ["aya/core/sample.py"], ["Sample.run"])
        text = (self.root / "aya/core/sample.py").read_text(encoding="utf-8")
        self.assertTrue(result.ok)
        self.assertIn('        """Executa sample."""', text)

    def test_patch_manifest_replace_exact_valido(self):
        old = "return json.dumps(value)"
        new = "return json.dumps(value, ensure_ascii=False)"
        manifest = self._manifest("replace_exact", old=old, new=new)
        self.service.structured_patch.apply(self.root, manifest, "DEV-20260713-ABCDEF", "abc1234", ["aya/core/sample.py"], ["Sample.run"])
        self.assertIn(new, (self.root / "aya/core/sample.py").read_text(encoding="utf-8"))

    def test_patch_manifest_replace_exact_ausente(self):
        manifest = self._manifest("replace_exact", old="nao existe", new="x")
        with self.assertRaisesRegex(StructuredPatchError, "nao encontrado"):
            self.service.structured_patch.apply(self.root, manifest, "DEV-20260713-ABCDEF", "abc1234", ["aya/core/sample.py"], ["Sample.run"])

    def test_patch_manifest_replace_exact_duplicado(self):
        path = self.root / "aya/core/sample.py"
        path.write_text(path.read_text(encoding="utf-8") + "\n# dup\n# dup\n", encoding="utf-8")
        manifest = self._manifest("replace_exact", expected_sha256=self._sha("aya/core/sample.py"), old="# dup", new="# novo")
        with self.assertRaisesRegex(StructuredPatchError, "mais de uma vez"):
            self.service.structured_patch.apply(self.root, manifest, "DEV-20260713-ABCDEF", "abc1234", ["aya/core/sample.py"], ["Sample.run"])

    def test_extrator_preserva_quebra_final_exigida_pelo_git(self):
        patch_text = self.service._extract_patch(
            "--- a/aya/core/sample.py\n+++ b/aya/core/sample.py\n@@ -1 +1 @@\n-import json\n+import re\n"
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
        self.assertIn("testes", self.service.falha(proposal.id))

    def test_diff_e_somente_leitura(self):
        proposal = self.proposal()
        proposal.patch = "diff --git a/a.py b/a.py"
        before = self.storage.read_bytes()
        response = self.service.diff(proposal.id)
        self.assertIn("somente leitura", response)
        self.assertEqual(before, self.storage.read_bytes())

    def test_falha_id_mostra_dados_registrados_sem_modelo(self):
        proposal = self.proposal()
        proposal.state = "FALHOU"
        self.service._record_failure(proposal, "patch", "diff recusado", "token=segredo")
        response = self.service.execute(f"falha {proposal.id}")
        self.assertIn("Etapa: patch", response)
        self.assertIn("Motivo: diff recusado", response)
        self.assertNotIn("segredo", response)

    def test_mostrar_neutraliza_falso_sucesso_do_modelo(self):
        proposal = self.proposal(suggested_change="Alteracao realizada com sucesso.")
        response = self.service.mostrar(proposal.id)
        self.assertIn("neutralizado", response)
        self.assertIn("Plano sugerido", response)

    def test_proposta_antiga_compativel_sem_campos_de_falha(self):
        proposal = self.proposal()
        data = self.storage.read_text(encoding="utf-8")
        self.storage.write_text(data.replace(',\n    "failure_stage": ""', ""), encoding="utf-8")
        loaded = AyaDevService(
            self.root,
            self.client,
            ProjectTools(self.root),
            storage_path=self.storage,
            index_path=self.cache,
            workspace_root=self.workspaces,
        )
        self.assertIn(proposal.id, loaded.proposals)
        self.assertIn("Informacao nao registrada", loaded.falha(proposal.id))

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

    def test_git_apply_check_falhando_registra_falha_e_limpa_worktree(self):
        proposal = self.proposal(related_files=["aya/core/sample.py", "tests/test_sample.py"])
        self.init_git()
        proposal.state = "PLANEJADA"
        proposal.risk = "medio"
        self.client.resposta = (
            "--- a/aya/core/sample.py\n"
            "+++ b/aya/core/sample.py\n"
            "@@ -99 +99 @@\n"
            "-linha inexistente\n"
            "+linha nova\n"
        )
        response = self.service.preparar(proposal.id)
        self.assertIn("Patch recusado", response)
        self.assertEqual("FALHOU", proposal.state)
        self.assertEqual("patch", proposal.failure_stage)
        self.assertTrue(proposal.workspace_cleaned)
        self.assertFalse(Path(proposal.workspace_path).exists())

    def test_preparar_structured_patch_gera_diff_real_e_aguarda_teste(self):
        proposal = self.proposal(
            related_files=["aya/core/sample.py"],
            related_symbols=["Sample", "Sample.run"],
            suggested_change="Adicionar docstring curta em Sample.run.",
        )
        self.init_git()
        proposal.state = "PLANEJADA"
        self.service.llm = DynamicStructuredClient("review ok")
        response = self.service.preparar(proposal.id)
        self.assertIn("Patch preparado", response)
        self.assertEqual("EM_TESTE", proposal.state)
        self.assertIn('"""Executa sample."""', proposal.patch)
        self.assertTrue(proposal.patch_manifest)
        self.assertTrue((Path(proposal.workspace) / "aya/core/sample.py").exists())

    def test_preparar_structured_patch_head_alterado_bloqueia_manifesto(self):
        proposal = self.proposal(related_files=["aya/core/sample.py"], related_symbols=["Sample.run"])
        self.init_git()
        proposal.state = "PLANEJADA"
        self.service.llm = StructuredClient({
            "type": "insert_docstring",
            "symbol": "Sample.run",
            "content": "Executa sample.",
            "base_commit": "HEAD-ANTIGO",
        })
        response = self.service.preparar(proposal.id)
        self.assertIn("Campo extra", response)
        self.assertEqual("FALHOU", proposal.state)
        self.assertFalse(proposal.workspace_created)

    def test_modelo_nao_pode_alterar_proposal_id_no_modo_estruturado(self):
        proposal = self.proposal(related_files=["aya/core/sample.py"], related_symbols=["Sample.run"])
        self.init_git()
        proposal.state = "PLANEJADA"
        self.service.llm = StructuredClient({
            "type": "insert_docstring",
            "symbol": "Sample.run",
            "content": "Executa sample.",
            "proposal_id": "DEV-20990101-ABCDEF",
        })
        response = self.service.preparar(proposal.id)
        self.assertIn("Campo extra", response)
        self.assertEqual("manifest_generation", proposal.failure_stage)
        self.assertFalse(proposal.workspace_created)

    def test_testes_relacionados_derivados_do_indice(self):
        proposal = self.proposal(related_files=["aya/core/sample.py"], required_tests=[])
        self.assertEqual(["tests/test_sample.py"], self.service._related_tests(proposal))

    def test_testes_relacionados_priorizam_mencao_direta_ao_simbolo(self):
        (self.root / "aya" / "ui").mkdir()
        (self.root / "aya" / "ui" / "aya_dev.py").write_text(
            "def render_diff(diff, expand=False):\n    return diff\n\n"
            "def render_panel():\n    return render_diff('ok')\n",
            encoding="utf-8",
        )
        (self.root / "tests" / "test_aya_dev_broad.py").write_text(
            "from aya.ui import aya_dev\n\n"
            "def test_panel_module():\n    assert aya_dev\n",
            encoding="utf-8",
        )
        (self.root / "tests" / "test_aya_dev_render_diff.py").write_text(
            "from aya.ui.aya_dev import render_diff\n\n"
            "def test_render_diff():\n    assert render_diff('x') == 'x'\n",
            encoding="utf-8",
        )
        self.service.index = type(self.service.index)(self.root, self.cache)
        proposal = self.proposal(
            related_files=["aya/ui/aya_dev.py"],
            related_symbols=["render_diff"],
            required_tests=[],
        )

        self.assertEqual(["tests/test_aya_dev_render_diff.py"], self.service._related_tests(proposal))

    def test_arquivo_de_codigo_recusado_como_teste_relacionado(self):
        proposal = self.proposal(related_files=["aya/core/sample.py"], required_tests=["aya/core/sample.py"])
        self.assertNotIn("aya/core/sample.py", self.service._related_tests(proposal))

    def test_sem_teste_relacionado_nao_inventa_caminho(self):
        (self.root / "tests" / "test_sample.py").unlink()
        self.service.index = type(self.service.index)(self.root, self.cache)
        proposal = self.proposal(related_files=["aya/core/sample.py"], required_tests=[])
        self.assertEqual([], self.service._related_tests(proposal))

    def test_preparar_structured_patch_validado_chega_a_aguardando_aprovacao(self):
        proposal = self.proposal(
            related_files=["aya/core/sample.py"],
            related_symbols=["Sample", "Sample.run"],
            suggested_change="Adicionar docstring curta em Sample.run.",
        )
        self.init_git()
        proposal.state = "PLANEJADA"
        self.service.llm = DynamicStructuredClient("review ok")
        self.service.preparar(proposal.id)
        review = self.service.revisar(proposal.id)
        result = self.service.testar(proposal.id)
        self.assertIn("review", review.lower())
        self.assertIn("AGUARDANDO_APROVACAO", result)
        self.assertEqual("AGUARDANDO_APROVACAO", proposal.state)
        self.assertTrue(any(call.get("messages") for call in self.service.llm.calls))
        self.assertEqual("", (self.root / "aya/core/sample.py").read_text(encoding="utf-8").splitlines()[0].replace("import json", ""))

    def test_preparar_structured_patch_segunda_tentativa_usa_erros_reais(self):
        proposal = self.proposal(related_files=["aya/core/sample.py"], related_symbols=["Sample.run"])
        self.init_git()
        proposal.state = "PLANEJADA"
        self.service.llm = StructuredClient("```json\n{}\n```")
        self.service.preparar(proposal.id)
        self.assertEqual("FALHOU", proposal.state)
        self.assertEqual("manifesto recusado", proposal.failure_reason)
        self.service.llm = DynamicStructuredClient("review ok")
        response = self.service.preparar(proposal.id)
        self.assertIn("Patch preparado", response)
        context = self.service.llm.calls[-1]["messages"][-1]["content"]
        self.assertIn("manifesto recusado", context)
        self.assertIn("Decisao em Markdown recusada", context)
        self.assertEqual(2, proposal.attempts)

    def test_patch_markdown_falha_com_motivo_persistido_e_worktree_removido(self):
        proposal = self.proposal(related_files=["aya/core/sample.py", "tests/test_sample.py"])
        self.init_git()
        proposal.state = "PLANEJADA"
        proposal.risk = "medio"
        self.client.resposta = (
            "```diff\n--- a/aya/core/sample.py\n+++ b/aya/core/sample.py\n"
            "@@ -1 +1 @@\n-import json\n+import re\n```"
        )
        response = self.service.preparar(proposal.id)
        self.assertIn("Markdown recusada", response)
        self.assertEqual("preparacao", proposal.failure_stage)
        self.assertTrue(proposal.raw_response_saved)
        self.assertTrue(proposal.workspace_cleaned)

    def test_aprovacao_nao_aplica_patch(self):
        proposal = self.proposal()
        self._mark_ready_for_approval(proposal)
        before = (self.root / "aya/core/sample.py").read_text(encoding="utf-8")
        self.service.aprovar(proposal.id)
        after = (self.root / "aya/core/sample.py").read_text(encoding="utf-8")
        self.assertEqual(before, after)
        self.assertEqual("APROVADA", proposal.state)

    def test_aprovacao_guarda_hashes_do_diff_e_manifesto(self):
        proposal = self.proposal()
        self._mark_ready_for_approval(proposal)
        self.service.aprovar(proposal.id)
        self.assertTrue(proposal.approved_diff_sha256)
        self.assertTrue(proposal.approved_manifest_sha256)
        self.assertTrue(proposal.approved_validation_sha256)
        self.assertTrue(proposal.approval_valid)

    def test_aplicar_bloqueia_sem_aprovacao(self):
        proposal = self.proposal()
        self._mark_ready_for_approval(proposal)
        response = self.service.aplicar(proposal.id)
        self.assertIn("aprove explicitamente", response)

    def test_aplicar_bloqueia_aprovacao_invalida_por_diff(self):
        proposal = self.proposal()
        self._mark_ready_for_approval(proposal)
        self.service.aprovar(proposal.id)
        proposal.patch += "\n"
        response = self.service.aplicar(proposal.id)
        self.assertIn("diff", response.lower())

    def test_aplicar_bloqueia_aprovacao_invalida_por_manifesto(self):
        proposal = self.proposal()
        self._mark_ready_for_approval(proposal)
        self.service.aprovar(proposal.id)
        proposal.patch_manifest["tests"] = []
        response = self.service.aplicar(proposal.id)
        self.assertIn("manifest", response.lower())

    def test_aplicar_bloqueia_risco_alto(self):
        proposal = self.proposal()
        self._mark_ready_for_approval(proposal)
        self.service.aprovar(proposal.id)
        proposal.risk = "alto"
        response = self.service.aplicar(proposal.id)
        self.assertIn("RISCO", response)

    def test_aplicar_bloqueia_sem_revisao(self):
        proposal = self.proposal()
        self._mark_ready_for_approval(proposal)
        proposal.review_result = ""
        response = self.service.aprovar(proposal.id)
        self.assertIn("revisao", response)

    def test_aplicar_bloqueia_com_teste_reprovado(self):
        proposal = self.proposal()
        self._mark_ready_for_approval(proposal)
        proposal.validation[0]["passed"] = False
        response = self.service.aprovar(proposal.id)
        self.assertIn("checks", response)

    def test_aplicar_bloqueia_worktree_head_alterado(self):
        proposal = self._prepare_real_patch_for_commit()
        self.service.aprovar(proposal.id)
        subprocess.run(("git", "commit", "--allow-empty", "-m", "diverge"), cwd=proposal.workspace, capture_output=True, check=True)
        response = self.service.aplicar(proposal.id)
        self.assertIn("WORKTREE_HEAD", response)

    def test_aplicar_bloqueia_main_suja(self):
        proposal = self._prepare_real_patch_for_commit()
        self.service.aprovar(proposal.id)
        (self.root / "notes.txt").write_text("sujo\n", encoding="utf-8")
        response = self.service.aplicar(proposal.id)
        self.assertIn("MAIN_SUJA", response)

    def test_aplicar_bloqueia_arquivo_nao_rastreado_no_worktree(self):
        proposal = self._prepare_real_patch_for_commit()
        self.service.aprovar(proposal.id)
        (Path(proposal.workspace) / "novo.txt").write_text("x\n", encoding="utf-8")
        response = self.service.aplicar(proposal.id)
        self.assertIn("ARQUIVO_NAO_RASTREADO", response)

    def test_aplicar_cria_branch_e_commit_isolado(self):
        proposal = self._prepare_real_patch_for_commit()
        main_before = self._git_head(self.root)
        self.service.aprovar(proposal.id)
        response = self.service.aplicar(proposal.id)
        main_after = self._git_head(self.root)
        self.assertIn("Commit isolado criado", response)
        self.assertEqual("COMMIT_PRONTO", proposal.state)
        self.assertEqual(main_before, main_after)
        self.assertEqual(main_before, proposal.commit_parent)
        self.assertTrue(proposal.proposal_branch.startswith("aya-dev/"))
        self.assertEqual(["aya/core/sample.py"], proposal.committed_files)
        self.assertIn(proposal.id, proposal.commit_message)
        self.assertIn("Branch", self.service.commit(proposal.id))

    def test_aplicar_bloqueia_branch_existente(self):
        proposal = self._prepare_real_patch_for_commit()
        self.service.aprovar(proposal.id)
        subprocess.run(("git", "branch", f"aya-dev/{proposal.id}"), cwd=self.root, capture_output=True, check=True)
        response = self.service.aplicar(proposal.id)
        self.assertIn("BRANCH_EXISTENTE", response)

    def test_rejeitar_invalida_aprovacao_e_preserva_proposta(self):
        proposal = self._prepare_real_patch_for_commit()
        self.service.aprovar(proposal.id)
        response = self.service.rejeitar(f"{proposal.id} | nao quero")
        self.assertIn("rejeitada", response)
        self.assertFalse(proposal.approval_valid)
        self.assertEqual("REJEITADA", proposal.state)

    def test_commit_id_nao_chama_modelo(self):
        proposal = self.proposal()
        before = len(self.client.calls)
        self.assertIn("Informacao nao registrada", self.service.execute(f"commit {proposal.id}"))
        self.assertEqual(before, len(self.client.calls))

    def test_integrar_bloqueia_sem_commit_pronto(self):
        proposal = self.proposal()
        self._mark_ready_for_approval(proposal)
        self.service.aprovar(proposal.id)
        response = self.service.integrar(proposal.id)
        self.assertIn("Integracao bloqueada", response)
        self.assertEqual("INTEGRACAO_BLOQUEADA", proposal.state)

    def test_integrar_bloqueia_sem_aprovacao_valida(self):
        proposal = self._prepare_commit_ready_for_integration()
        proposal.approval_valid = False
        response = self.service.integrar(proposal.id)
        self.assertIn("APROVACAO", response.upper())
        self.assertEqual("INTEGRACAO_BLOQUEADA", proposal.state)

    def test_integrar_bloqueia_com_main_suja(self):
        proposal = self._prepare_commit_ready_for_integration()
        (self.root / "notes.txt").write_text("sujo\n", encoding="utf-8")
        response = self.service.integrar(proposal.id)
        self.assertIn("MAIN_SUJA", response)
        self.assertEqual(proposal.commit_parent, self._git_head(self.root))

    def test_integrar_bloqueia_com_untracked(self):
        proposal = self._prepare_commit_ready_for_integration()
        (self.root / "novo.txt").write_text("untracked\n", encoding="utf-8")
        response = self.service.integrar(proposal.id)
        self.assertIn("MAIN_SUJA", response)
        self.assertEqual(proposal.commit_parent, self._git_head(self.root))

    def test_integrar_bloqueia_em_branch_diferente(self):
        proposal = self._prepare_commit_ready_for_integration()
        subprocess.run(("git", "branch", "outra"), cwd=self.root, capture_output=True, check=True)
        subprocess.run(("git", "switch", "outra"), cwd=self.root, capture_output=True, check=True)
        response = self.service.integrar(proposal.id)
        self.assertIn("MAIN_BRANCH", response)
        self.assertEqual(proposal.commit_parent, self._git_head(self.root))

    def test_integrar_bloqueia_quando_main_avancou(self):
        proposal = self._prepare_commit_ready_for_integration()
        subprocess.run(("git", "commit", "--allow-empty", "-m", "avanca main"), cwd=self.root, capture_output=True, check=True)
        response = self.service.integrar(proposal.id)
        self.assertIn("BASE_DIVERGENTE", response)

    def test_integrar_bloqueia_quando_branch_mudou(self):
        proposal = self._prepare_commit_ready_for_integration()
        subprocess.run(("git", "commit", "--allow-empty", "-m", "avanca branch"), cwd=proposal.workspace_path, capture_output=True, check=True)
        response = self.service.integrar(proposal.id)
        self.assertIn("BRANCH_MUDOU", response)
        self.assertEqual(proposal.commit_parent, self._git_head(self.root))

    def test_integrar_bloqueia_quando_manifesto_mudou(self):
        proposal = self._prepare_commit_ready_for_integration()
        proposal.patch_manifest["tests"] = []
        response = self.service.integrar(proposal.id)
        self.assertIn("manifest", response.lower())

    def test_integrar_bloqueia_sem_revisao(self):
        proposal = self._prepare_commit_ready_for_integration()
        proposal.review_result = ""
        response = self.service.integrar(proposal.id)
        self.assertIn("REVIEW", response)

    def test_integrar_bloqueia_com_testes_incompletos(self):
        proposal = self._prepare_commit_ready_for_integration()
        proposal.validation = [item for item in proposal.validation if item.get("name") != "smoke"]
        response = self.service.integrar(proposal.id)
        self.assertIn("validation", response.lower())

    def test_integrar_bloqueia_risco_alto(self):
        proposal = self._prepare_commit_ready_for_integration()
        proposal.risk = "alto"
        response = self.service.integrar(proposal.id)
        self.assertIn("RISCO", response)

    def test_integrar_bloqueia_validacao_limpa_falhando(self):
        proposal = self._prepare_commit_ready_for_integration()
        failed = CheckResult("pytest", "python -m pytest", 1, 0, "falhou")
        with patch.object(self.service, "_validate_commit_in_clean_worktree", return_value=[failed.__dict__ | {"passed": False}]):
            response = self.service.integrar(proposal.id)
        self.assertIn("VALIDACAO_LIMPA", response)
        self.assertEqual(proposal.commit_parent, self._git_head(self.root))

    def test_integrar_fast_forward_bem_sucedido_e_idempotente(self):
        proposal = self._prepare_commit_ready_for_integration()
        main_before = self._git_head(self.root)
        validation = [CheckResult("pytest", "python -m pytest", 0, 0, "ok").__dict__ | {"passed": True}]
        with patch.object(self.service, "_validate_commit_in_clean_worktree", return_value=validation):
            response = self.service.integrar(proposal.id)
        self.assertIn("Integracao concluida", response)
        self.assertEqual("INTEGRADA", proposal.state)
        self.assertEqual(main_before, proposal.previous_main_head)
        self.assertEqual(proposal.proposal_commit, self._git_head(self.root))
        self.assertEqual(proposal.proposal_commit, proposal.resulting_main_head)
        self.assertFalse(proposal.merge_commit_created)
        self.assertFalse(proposal.pushed)
        self.assertFalse(proposal.remote_used)
        self.assertFalse(Path(proposal.workspace_path).exists())
        self.assertIn("ja integrada", self.service.integrar(proposal.id))

    def test_integracao_conclui_experimento_de_calibracao_vinculado(self):
        proposal = self._prepare_commit_ready_for_integration()
        experiment = CalibrationExperiment(
            experiment_id="EXP-TESTE",
            candidate_id="AUTO-TESTE",
            proposal_id=proposal.id,
            created_at="2026-01-01T00:00:00",
            selected_by="local_user",
            project_head=proposal.project_head,
            file="aya/core/sample.py",
            file_sha256="sha",
            symbol="Sample.run",
            operation_type="insert_docstring",
            category="documentacao",
            pipeline_version=proposal.patch_pipeline_version,
            schema_version=proposal.schema_version,
            prompt_version=proposal.prompt_version,
            model=self.service.primary_model,
            reviewer_model=self.service.reviewer_model,
            reason="docstring ausente",
            expected_change="inserir docstring",
            allowed_files=["aya/core/sample.py"],
            related_tests=["tests/test_sample.py"],
            risk="baixo",
            estimated_changed_lines=1,
            state="AGUARDANDO_APROVACAO",
            result="PATCH_VALIDADO_SEM_COMMIT",
        )
        self.service.experiments[experiment.experiment_id] = experiment
        validation = [CheckResult("pytest", "python -m pytest", 0, 0, "ok").__dict__ | {"passed": True}]

        with patch.object(self.service, "_validate_commit_in_clean_worktree", return_value=validation):
            self.service.integrar(proposal.id)

        self.assertEqual("INTEGRADA", proposal.state)
        self.assertEqual("CONCLUIDO", experiment.state)
        self.assertEqual("PROPOSTA_INTEGRADA", experiment.result)
        self.assertEqual("APROVADA_PELO_USUARIO", experiment.evidence_strength)

    def test_integrar_falha_pos_fast_forward_registra_parcial(self):
        proposal = self._prepare_commit_ready_for_integration()
        validation = [CheckResult("pytest", "python -m pytest", 0, 0, "ok").__dict__ | {"passed": True}]
        timeout = subprocess.TimeoutExpired(("python", "-m", "pytest"), 300)
        with (
            patch.object(self.service, "_validate_commit_in_clean_worktree", return_value=validation),
            patch.object(self.service, "_post_integration_validation", side_effect=timeout),
        ):
            response = self.service.integrar(proposal.id)
        self.assertIn("Integracao parcial", response)
        self.assertNotIn("Main permaneceu intacta", response)
        self.assertEqual("INTEGRACAO_BLOQUEADA", proposal.state)
        self.assertTrue(proposal.integration_partial)
        self.assertEqual(proposal.proposal_commit, self._git_head(self.root))

    def test_integrar_reconcilia_commit_ja_na_main_sem_novo_merge(self):
        proposal = self._prepare_commit_ready_for_integration()
        subprocess.run(("git", "merge", "--ff-only", proposal.proposal_branch), cwd=self.root, capture_output=True, check=True)
        validation = [CheckResult("pytest", "python -m pytest", 0, 0, "ok").__dict__ | {"passed": True}]
        with (
            patch.object(self.service, "_validate_commit_in_clean_worktree", return_value=validation),
            patch.object(self.service, "_post_integration_validation", return_value=validation),
        ):
            response = self.service.integrar(proposal.id)
        self.assertIn("reconciliado", response)
        self.assertIn("Novo merge executado: nao", response)
        self.assertEqual("INTEGRADA", proposal.state)
        self.assertEqual(proposal.proposal_commit, self._git_head(self.root))

    def test_integracao_id_nao_chama_modelo(self):
        proposal = self.proposal()
        before = len(self.client.calls)
        self.assertIn("Integracao", self.service.execute(f"integracao {proposal.id}"))
        self.assertEqual(before, len(self.client.calls))

    def test_solicitar_reversao_bloqueia_proposta_nao_integrada(self):
        proposal = self.proposal()
        response = self.service.solicitar_reversao(f"{proposal.id} motivo real")
        self.assertIn("somente propostas INTEGRADAS", response)

    def test_solicitar_reversao_exige_motivo(self):
        proposal = self.proposal()
        response = self.service.solicitar_reversao(proposal.id)
        self.assertIn("MOTIVO", response.upper())

    def test_reverter_bloqueia_sem_aprovacao_de_reversao(self):
        proposal = self._prepare_integrated_for_reversal()
        response = self.service.reverter(proposal.id)
        self.assertIn("aprovar-reversao", response)

    def test_aprovar_reversao_invalida_por_mudanca_no_motivo(self):
        proposal = self._prepare_integrated_for_reversal()
        self._request_reversal_ready_for_approval(proposal)
        proposal.reversal_reason = "motivo alterado"
        response = self.service.aprovar_reversao(proposal.id)
        self.assertIn("previsao", response.lower())

    def test_reverter_bloqueia_main_suja(self):
        proposal = self._prepare_reversal_approved()
        (self.root / "notes.txt").write_text("sujo\n", encoding="utf-8")
        response = self.service.reverter(proposal.id)
        self.assertIn("MAIN_SUJA", response)
        self.assertEqual(proposal.reversal_base_commit, self._git_head(self.root))

    def test_reverter_bloqueia_commit_inexistente(self):
        proposal = self._prepare_integrated_for_reversal()
        self._request_reversal_ready_for_approval(proposal)
        self.service.aprovar_reversao(proposal.id)
        proposal.reversal_target_commit = "0" * 40
        response = self.service.reverter(proposal.id)
        self.assertIn("unknown revision", response.lower())

    def test_reverter_bloqueia_commit_fora_da_main(self):
        proposal = self._prepare_integrated_for_reversal()
        extra = self.workspaces / "fora-main"
        subprocess.run(("git", "worktree", "add", "-b", "fora-main", str(extra), "HEAD"), cwd=self.root, capture_output=True, check=True)
        subprocess.run(("git", "commit", "--allow-empty", "-m", "fora main"), cwd=extra, capture_output=True, check=True)
        outside = self._git_head(extra)
        subprocess.run(("git", "worktree", "remove", str(extra)), cwd=self.root, capture_output=True, check=True)
        self._request_reversal_ready_for_approval(proposal)
        self.service.aprovar_reversao(proposal.id)
        proposal.reversal_target_commit = outside
        response = self.service.reverter(proposal.id)
        self.assertIn("COMMIT_FORA_DA_MAIN", response)

    def test_solicitar_reversao_detecta_revert_existente(self):
        proposal = self._prepare_reversal_approved()
        with (
            patch.object(self.service, "_validate_reversal_in_clean_worktree", return_value=self._passed_validation()),
            patch.object(self.service, "_post_reversal_validation", return_value=self._passed_validation()),
        ):
            self.service.reverter(proposal.id)
        proposal.state = "INTEGRADA"
        self.service.solicitar_reversao(f"{proposal.id} outro motivo")
        response = self.service.prever_reversao(proposal.id)
        self.assertIn("COMMIT_JA_REVERTIDO", response)

    def test_prever_reversao_bloqueia_validacao_previa_falhando(self):
        proposal = self._prepare_integrated_for_reversal()
        self.service.solicitar_reversao(f"{proposal.id} motivo real")
        preview = self._fake_preview(proposal, valid=False, reason="VALIDACAO_REVERSAO_REPROVADA")
        with patch.object(self.service, "_build_reversal_preview", return_value=preview):
            response = self.service.prever_reversao(proposal.id)
        self.assertIn("VALIDACAO_REVERSAO", response)
        self.assertEqual("PREVISAO_REVERSAO_BLOQUEADA", proposal.state)

    def test_prever_reversao_persiste_diff_arquivos_linhas_e_hash(self):
        proposal = self._prepare_integrated_for_reversal()
        main_before = self._git_head(self.root)
        self.service.solicitar_reversao(f"{proposal.id} motivo real")
        with patch.object(self.service, "_build_reversal_preview", return_value=self._fake_preview(proposal)):
            response = self.service.prever_reversao(proposal.id)
        self.assertIn("Previsao de reversao pronta", response)
        self.assertEqual(main_before, self._git_head(self.root))
        self.assertTrue(proposal.reversal_preview_diff)
        self.assertEqual(["aya/core/sample.py"], proposal.reversal_preview_files)
        self.assertEqual(0, proposal.reversal_preview_added_lines)
        self.assertEqual(1, proposal.reversal_preview_removed_lines)
        self.assertTrue(proposal.reversal_preview_sha256)
        self.assertTrue(proposal.reversal_preview_main_unchanged)
        self.assertTrue(proposal.reversal_preview_workspace_cleaned)

    def test_prever_reversao_real_nao_cria_commit_na_main(self):
        proposal = self._prepare_integrated_for_reversal()
        main_before = self._git_head(self.root)
        self.service.solicitar_reversao(f"{proposal.id} motivo real")
        response = self.service.prever_reversao(proposal.id)
        self.assertIn("Previsao de reversao pronta", response)
        self.assertEqual(main_before, self._git_head(self.root))
        self.assertIn('"""Executa sample."""', proposal.reversal_preview_diff)
        self.assertEqual(["aya/core/sample.py"], proposal.reversal_preview_files)
        self.assertEqual("AGUARDANDO_APROVACAO_REVERSAO", proposal.state)
        self.assertTrue(proposal.reversal_preview_workspace_cleaned)
        self.assertFalse(any(path.name.startswith("preview-reversal-") for path in self.workspaces.glob("*")))

    def test_prever_reversao_mesma_previsao_mantem_hash(self):
        proposal = self._prepare_integrated_for_reversal()
        self.service.solicitar_reversao(f"{proposal.id} motivo real")
        preview = self._fake_preview(proposal)
        with patch.object(self.service, "_build_reversal_preview", return_value=preview):
            self.service.prever_reversao(proposal.id)
            first_hash = proposal.reversal_preview_sha256
            self.service.prever_reversao(proposal.id)
        self.assertEqual(first_hash, proposal.reversal_preview_sha256)

    def test_aprovar_reversao_sem_previsao_e_bloqueada(self):
        proposal = self._prepare_integrated_for_reversal()
        self.service.solicitar_reversao(f"{proposal.id} motivo real")
        response = self.service.aprovar_reversao(proposal.id)
        self.assertIn("previsao", response.lower())

    def test_prever_reversao_head_diferente_invalida_previsao_anterior(self):
        proposal = self._prepare_integrated_for_reversal()
        self.service.solicitar_reversao(f"{proposal.id} motivo real")
        with patch.object(self.service, "_build_reversal_preview", return_value=self._fake_preview(proposal)):
            self.service.prever_reversao(proposal.id)
        subprocess.run(("git", "commit", "--allow-empty", "-m", "avanca main"), cwd=self.root, capture_output=True, check=True)
        response = self.service.aprovar_reversao(proposal.id)
        self.assertIn("HEAD", response)

    def test_diff_reversao_nao_chama_modelo(self):
        proposal = self._prepare_integrated_for_reversal()
        self._request_reversal_ready_for_approval(proposal)
        before = len(self.client.calls)
        response = self.service.execute(f"diff-reversao {proposal.id}")
        self.assertIn("diff --git", response)
        self.assertEqual(before, len(self.client.calls))

    def test_reverter_trata_conflito_do_git_revert(self):
        proposal = self._prepare_reversal_approved()
        original_run = self.service.workspace._run

        def fake_run(command, cwd, timeout, input_text=None):
            if command[:3] == ("git", "revert", "--no-edit"):
                return subprocess.CompletedProcess(command, 1, "", "CONFLICT")
            return original_run(command, cwd, timeout, input_text)

        self.service.workspace._run = fake_run
        response = self.service.reverter(proposal.id)
        self.assertIn("GIT_REVERT_FALHOU", response)
        self.assertEqual("REVERSAO_FALHOU", proposal.state)

    def test_reverter_bem_sucedido_e_idempotente(self):
        proposal = self._prepare_reversal_approved()
        with (
            patch.object(self.service, "_validate_reversal_in_clean_worktree", return_value=self._passed_validation()),
            patch.object(self.service, "_post_reversal_validation", return_value=self._passed_validation()),
        ):
            response = self.service.reverter(proposal.id)
        self.assertIn("Reversao concluida", response)
        self.assertEqual("REVERTIDA", proposal.state)
        self.assertTrue(proposal.reversal_commit)
        self.assertEqual(proposal.reversal_commit, self._git_head(self.root))
        self.assertFalse(proposal.pushed)
        self.assertFalse(proposal.remote_used)
        self.assertIn("ja revertida", self.service.reverter(proposal.id))

    def test_reverter_validacao_posterior_falhando_registra_parcial(self):
        proposal = self._prepare_reversal_approved()
        failed = CheckResult("pytest", "python -m pytest", 1, 0, "falhou").__dict__ | {"passed": False}
        with (
            patch.object(self.service, "_validate_reversal_in_clean_worktree", return_value=self._passed_validation()),
            patch.object(self.service, "_post_reversal_validation", return_value=[failed]),
        ):
            response = self.service.reverter(proposal.id)
        self.assertIn("Reversao parcial", response)
        self.assertEqual("REVERSAO_PARCIAL", proposal.state)
        self.assertEqual(proposal.reversal_commit, self._git_head(self.root))

    def test_reverter_interrupcao_pos_revert_nao_diz_main_intacta(self):
        proposal = self._prepare_reversal_approved()
        with (
            patch.object(self.service, "_validate_reversal_in_clean_worktree", return_value=self._passed_validation()),
            patch.object(self.service, "_post_reversal_validation", side_effect=subprocess.TimeoutExpired(("python", "-m", "pytest"), 600)),
        ):
            response = self.service.reverter(proposal.id)
        self.assertIn("Reversao parcial", response)
        self.assertNotIn("Main permaneceu intacta", response)
        self.assertEqual("REVERSAO_PARCIAL", proposal.state)

    def test_reverter_reconcilia_reversao_parcial(self):
        proposal = self._prepare_reversal_approved()
        with (
            patch.object(self.service, "_validate_reversal_in_clean_worktree", return_value=self._passed_validation()),
            patch.object(self.service, "_post_reversal_validation", return_value=[CheckResult("pytest", "python -m pytest", 1, 0, "falhou").__dict__ | {"passed": False}]),
        ):
            self.service.reverter(proposal.id)
        with patch.object(self.service, "_post_reversal_validation", return_value=self._passed_validation()):
            response = self.service.reverter(proposal.id)
        self.assertIn("reconciliado", response)
        self.assertEqual("REVERTIDA", proposal.state)

    def test_reversao_id_nao_chama_modelo(self):
        proposal = self.proposal()
        before = len(self.client.calls)
        self.assertIn("Reversao", self.service.execute(f"reversao {proposal.id}"))
        self.assertEqual(before, len(self.client.calls))

    def test_painel_aya_dev_inicializa_sem_proposta(self):
        self.service.proposals.clear()
        panel = self._panel()
        choices, selected = panel.refresh("todas")
        self.assertEqual([], choices)
        self.assertEqual("", selected)

    def test_painel_lista_e_filtra_propostas(self):
        proposal = self.proposal()
        proposal.state = "COMMIT_PRONTO"
        panel = self._panel()
        all_choices, _ = panel.refresh("todas")
        filtered, _ = panel.refresh("commit pronto")
        failed, _ = panel.refresh("falhou")
        self.assertTrue(any(proposal.id in item for item in all_choices))
        self.assertTrue(any(proposal.id in item for item in filtered))
        self.assertFalse(any(proposal.id in item for item in failed))

    def test_painel_selecao_mostra_dados_reais(self):
        proposal = self.proposal()
        panel = self._panel()
        overview, plan, *_ = panel.details(panel._choice(proposal))
        self.assertIn(proposal.id, overview)
        self.assertIn(proposal.problem, overview)
        self.assertIn("nao comprova execucao", plan)

    def test_painel_diff_escapa_html_e_trunca_visualmente(self):
        dangerous = "diff --git a/x b/x\n+<script>alert(1)</script>\n" + ("+x\n" * 10000)
        rendered = render_diff(dangerous, expand=False)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("Diff truncado visualmente", rendered)
        self.assertNotIn("<script>", rendered)

    def test_painel_falha_nao_aparece_como_sucesso(self):
        proposal = self.proposal()
        proposal.state = "FALHOU"
        proposal.failure_reason = "erro real"
        panel = self._panel()
        overview, *_ = panel.details(panel._choice(proposal))
        self.assertIn("FALHOU", overview)
        self.assertNotIn("concluida", overview.lower())

    def test_painel_botoes_dependem_do_estado(self):
        proposal = self.proposal()
        panel = self._panel()
        actions = panel.available_actions(proposal)
        self.assertTrue(actions["planejar"])
        self.assertFalse(actions["integrar"])
        proposal.state = "COMMIT_PRONTO"
        actions = panel.available_actions(proposal)
        self.assertTrue(actions["integrar"])

    def test_painel_aprovacao_exige_texto_exato_e_nao_cria_commit(self):
        proposal = self.proposal()
        self._mark_ready_for_approval(proposal)
        self.init_git()
        before = self._git_head(self.root)
        panel = self._panel()
        selected = panel._choice(proposal)
        response, *_ = panel.run_action(selected, "aprovar", "APROVAR ERRADO", "")
        self.assertIn("Confirmacao incorreta", response)
        self.assertEqual(before, self._git_head(self.root))
        response, *_ = panel.run_action(selected, "aprovar", f"APROVAR {proposal.id}", "")
        self.assertIn("Aprovacao registrada", response)
        self.assertEqual(before, self._git_head(self.root))

    def test_painel_integracao_exige_texto_exato_e_chama_backend(self):
        proposal = self.proposal()
        proposal.state = "COMMIT_PRONTO"
        panel = self._panel()
        with patch.object(self.service, "integrar", return_value="integrado") as integrar:
            response, *_ = panel.run_action(panel._choice(proposal), "integrar", "INTEGRAR ERRADO", "")
            self.assertIn("Confirmacao incorreta", response)
            integrar.assert_not_called()
            response, *_ = panel.run_action(panel._choice(proposal), "integrar", f"INTEGRAR {proposal.id}", "")
            self.assertEqual("integrado", response)
            integrar.assert_called_once_with(proposal.id)

    def test_painel_motivo_reversao_obrigatorio(self):
        proposal = self.proposal()
        proposal.state = "INTEGRADA"
        panel = self._panel()
        response, *_ = panel.run_action(panel._choice(proposal), "solicitar_reversao", "", "")
        self.assertIn("motivo", response.lower())

    def test_painel_previsao_reversao_mostra_diff_arquivos_linhas_e_hash(self):
        proposal = self.proposal()
        proposal.state = "AGUARDANDO_APROVACAO_REVERSAO"
        proposal.reversal_preview_diff = "diff --git a/x b/x\n-old\n+new\n"
        proposal.reversal_preview_files = ["x"]
        proposal.reversal_preview_added_lines = 1
        proposal.reversal_preview_removed_lines = 1
        proposal.reversal_preview_sha256 = "abcdef123456"
        panel = self._panel()
        *_, reversal, _summary = panel.details(panel._choice(proposal))
        self.assertIn("x", reversal)
        self.assertIn("abcdef123456", reversal)
        self.assertIn("Linhas adicionadas: 1", reversal)

    def test_painel_aprovacao_reversao_exige_codigo_e_nao_reverte(self):
        proposal = self.proposal()
        proposal.state = "AGUARDANDO_APROVACAO_REVERSAO"
        proposal.reversal_preview_sha256 = "abcdef123456"
        panel = self._panel()
        with patch.object(self.service, "aprovar_reversao", return_value="aprovada") as approve:
            response, *_ = panel.run_action(panel._choice(proposal), "aprovar_reversao", "REV-errado", "")
            self.assertIn("Codigo", response)
            approve.assert_not_called()
            response, *_ = panel.run_action(panel._choice(proposal), "aprovar_reversao", "REV-abcdef12", "")
            self.assertEqual("aprovada", response)
            approve.assert_called_once_with(proposal.id)

    def test_painel_execucao_reversao_exige_confirmacao_e_chama_backend(self):
        proposal = self.proposal()
        proposal.state = "REVERSAO_APROVADA"
        panel = self._panel()
        with patch.object(self.service, "reverter", return_value="revertida") as revert:
            response, *_ = panel.run_action(panel._choice(proposal), "reverter", "REVERTER ERRADO", "")
            self.assertIn("Confirmacao incorreta", response)
            revert.assert_not_called()
            response, *_ = panel.run_action(panel._choice(proposal), "reverter", f"REVERTER {proposal.id}", "")
            self.assertEqual("revertida", response)
            revert.assert_called_once_with(proposal.id)

    def test_painel_recarrega_estado_e_mostra_erro_persistido(self):
        proposal = self.proposal()
        panel = self._panel()

        def fail_action(proposal_id):
            proposal.state = "FALHOU"
            proposal.failure_reason = "erro persistido"
            return "falhou"

        with patch.object(self.service, "planejar", side_effect=fail_action):
            response, overview, *_ = panel.run_action(panel._choice(proposal), "planejar", "", "")
        self.assertEqual("falhou", response)
        self.assertIn("FALHOU", overview)

    def test_painel_acao_concorrente_e_bloqueada_e_lock_libera(self):
        proposal = self.proposal()
        panel = self._panel()
        self.assertTrue(panel._acquire(proposal.id))
        response, *_ = panel.run_action(panel._choice(proposal), "planejar", "", "")
        self.assertIn("em andamento", response)
        panel._release(proposal.id)
        with patch.object(self.service, "planejar", side_effect=RuntimeError("falha")):
            response, *_ = panel.run_action(panel._choice(proposal), "planejar", "", "")
        self.assertIn("Falha", response)
        self.assertTrue(panel._acquire(proposal.id))
        panel._release(proposal.id)

    def test_painel_canal_remoto_bloqueia_execucao_mas_visualiza(self):
        proposal = self.proposal()
        panel = self._panel(channel=AccessChannel.REMOTE_GRADIO)
        overview, *_ = panel.details(panel._choice(proposal))
        self.assertIn(proposal.id, overview)
        response, *_ = panel.run_action(panel._choice(proposal), "planejar", "", "")
        self.assertIn("bloqueada", response)

    def test_painel_visualizacao_nao_chama_modelo_e_sem_subprocess(self):
        proposal = self.proposal()
        panel = self._panel()
        before = len(self.client.calls)
        panel.details(panel._choice(proposal))
        self.assertEqual(before, len(self.client.calls))
        source = inspect.getsource(aya_dev_ui)
        self.assertNotIn("subprocess", source)

    def test_validacao_nao_executa_comando_arbitrario_do_modelo(self):
        workspace = self.workspaces / "safe"
        workspace.mkdir(parents=True)
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, "ok", ""))
        self.service.workspace._run = runner
        self.service.workspace.validate = type(self.service.workspace).validate.__get__(self.service.workspace)
        self.service.workspace.validate(workspace)
        commands = [call.args[0] for call in runner.call_args_list]
        self.assertEqual(5, len(commands))
        self.assertTrue(all(command[0] == "python" for command in commands))
        self.assertFalse(any("del" in command or "powershell" in command for command in commands))
        self.assertEqual(FULL_VALIDATION_PYTEST_TIMEOUT_SECONDS, runner.call_args_list[0].args[2])

    def test_testes_relacionados_usam_timeout_maior_de_calibracao(self):
        workspace = self.workspaces / "safe-timeout"
        workspace.mkdir(parents=True)
        (workspace / "tests").mkdir()
        (workspace / "tests" / "test_sample.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        dev_workspace = DevWorkspace(self.root, self.workspaces)
        captured = []

        def fake_check(name, command, timeout, cwd):
            captured.append((name, command, timeout, cwd))
            return CheckResult(name, " ".join(command), 0, 1, "ok")

        dev_workspace._check = fake_check
        dev_workspace.validate(workspace, ["tests/test_sample.py"])

        self.assertEqual("testes relacionados", captured[0][0])
        self.assertEqual(RELATED_TEST_TIMEOUT_FALLBACK_SECONDS, captured[0][2])

    def test_timeout_adaptativo_usa_minimo_para_baseline_curta(self):
        self.assertEqual(RELATED_TEST_TIMEOUT_MINIMUM_SECONDS, calculate_related_test_timeout(100))

    def test_timeout_adaptativo_calcula_margem_para_baseline_real(self):
        self.assertEqual(1411, calculate_related_test_timeout(900.27))

    def test_timeout_adaptativo_respeita_maximo(self):
        self.assertEqual(RELATED_TEST_TIMEOUT_MAXIMUM_SECONDS, calculate_related_test_timeout(2000))

    def test_timeout_adaptativo_usa_fallback_sem_baseline(self):
        self.assertEqual(RELATED_TEST_TIMEOUT_FALLBACK_SECONDS, calculate_related_test_timeout(None))

    def test_timeout_adaptativo_e_deterministico(self):
        first = calculate_related_test_timeout(900.27)
        second = calculate_related_test_timeout(900.27)
        self.assertEqual(first, second)

    def test_timeout_nao_reutiliza_baseline_incompativel(self):
        proposal = self.proposal()
        proposal.validation = [{
            "phase": "baseline",
            "name": "testes relacionados",
            "command": "python -m pytest tests/outro.py",
            "duration_ms": 900270,
            "passed": True,
        }]

        metadata = self.service._related_test_timeout_metadata(proposal, ["tests/test_sample.py"])

        self.assertIsNone(metadata["baseline_duration_seconds"])
        self.assertEqual(RELATED_TEST_TIMEOUT_FALLBACK_SECONDS, metadata["calculated_timeout_seconds"])
        self.assertEqual("fallback_sem_baseline_compativel", metadata["timeout_calculation_source"])

    def test_timeout_usa_baseline_compativel_da_propria_proposta(self):
        proposal = self.proposal()
        proposal.validation = [{
            "phase": "baseline",
            "name": "testes relacionados",
            "command": "python -m pytest tests/test_sample.py",
            "duration_ms": 900270,
            "passed": True,
        }]

        metadata = self.service._related_test_timeout_metadata(proposal, ["tests/test_sample.py"])

        self.assertEqual(900.27, metadata["baseline_duration_seconds"])
        self.assertEqual(1411, metadata["calculated_timeout_seconds"])
        self.assertEqual("baseline_relacionada_da_proposta", metadata["timeout_calculation_source"])

    def test_timeout_em_validacao_e_inconclusivo_nao_falha_funcional(self):
        proposal = self.proposal()
        workspace = self.workspaces / proposal.id
        workspace.mkdir(parents=True)
        proposal.workspace = str(workspace)
        proposal.workspace_path = str(workspace)
        proposal.patch = "diff --git a/aya/core/sample.py b/aya/core/sample.py\n"
        self.service.workspace.validate = Mock(return_value=[
            CheckResult("testes relacionados", "python -m pytest tests/test_sample.py", 124, 900001, "Tempo limite excedido.")
        ])
        self.service.workspace.git_state = Mock(return_value=GitState(True, True, "ok"))

        response = self.service.testar(proposal.id)

        self.assertIn("VALIDACAO_INCONCLUSIVA_POR_TIMEOUT", response)
        self.assertEqual("VALIDACAO_INCONCLUSIVA_POR_TIMEOUT", proposal.failure_reason)
        self.assertEqual("Validacao inconclusiva por timeout.", proposal.review_result)
        self.assertIn("VALIDACAO_INCONCLUSIVA_POR_TIMEOUT", self.service._validation_summary(proposal))

    def test_comandos_basicos_e_aprovacao_apenas_registram(self):
        proposal = self.proposal()
        self._mark_ready_for_approval(proposal)
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

    def _sha(self, rel: str) -> str:
        return hashlib.sha256((self.root / rel).read_bytes()).hexdigest()

    def _manifest(
        self,
        operation_type: str = "insert_docstring",
        *,
        file: str = "aya/core/sample.py",
        symbol: str = "Sample.run",
        expected_sha256: str | None = None,
        content: str = "Executa sample.",
        old: str = "return json.dumps(value)",
        new: str = "return json.dumps(value, ensure_ascii=False)",
    ) -> dict:
        operation = {
            "type": operation_type,
            "file": file,
            "expected_sha256": expected_sha256 or self._sha(file) if (self.root / file).exists() else "0" * 64,
        }
        if operation_type == "insert_docstring":
            operation.update({"symbol": symbol, "content": content})
        elif operation_type == "replace_exact":
            operation.update({"old_text": old, "new_text": new})
        return {
            "version": 1,
            "proposal_id": "DEV-20260713-ABCDEF",
            "base_commit": "abc1234",
            "operations": [operation],
            "tests": ["tests/test_sample.py"],
        }

    def _mark_ready_for_approval(self, proposal):
        proposal.state = "AGUARDANDO_APROVACAO"
        proposal.base_commit = "abc1234"
        proposal.patch = (
            "diff --git a/aya/core/sample.py b/aya/core/sample.py\n"
            "--- a/aya/core/sample.py\n"
            "+++ b/aya/core/sample.py\n"
            "@@ -1 +1 @@\n"
            "-import json\n"
            "+import json\n"
        )
        proposal.patch_manifest = self._manifest(expected_sha256=self._sha("aya/core/sample.py"))
        proposal.review_result = "review ok"
        proposal.validation = [
            {"phase": "patch", "name": "pytest", "passed": True},
            {"phase": "patch", "name": "ruff", "passed": True},
            {"phase": "patch", "name": "compileall", "passed": True},
            {"phase": "patch", "name": "pip check", "passed": True},
            {"phase": "patch", "name": "smoke", "passed": True},
        ]

    def _prepare_real_patch_for_commit(self):
        proposal = self.proposal(
            related_files=["aya/core/sample.py"],
            related_symbols=["Sample", "Sample.run"],
            suggested_change="Adicionar docstring curta em Sample.run.",
        )
        self.init_git()
        proposal.state = "PLANEJADA"
        self.service.llm = DynamicStructuredClient("review ok")
        self.service.preparar(proposal.id)
        self.service.revisar(proposal.id)
        self.service.testar(proposal.id)
        self.assertEqual("AGUARDANDO_APROVACAO", proposal.state)
        return proposal

    def _prepare_commit_ready_for_integration(self):
        proposal = self._prepare_real_patch_for_commit()
        subprocess.run(("git", "branch", "-M", "main"), cwd=self.root, capture_output=True, check=True)
        self.service.aprovar(proposal.id)
        response = self.service.aplicar(proposal.id)
        self.assertIn("Commit isolado criado", response)
        self.assertEqual("COMMIT_PRONTO", proposal.state)
        self.assertEqual(proposal.commit_parent, self._git_head(self.root))
        return proposal

    def _passed_validation(self):
        return [CheckResult("pytest", "python -m pytest", 0, 0, "ok").__dict__ | {"passed": True}]

    def _fast_validation(self, workspace, related_tests=None, *, related_test_timeout=None):
        results = []
        if related_tests:
            results.append(CheckResult("testes relacionados", "python -m pytest " + " ".join(related_tests), 0, 1, "ok"))
        results.extend([
            CheckResult("pytest", "python -m pytest", 0, 1, "ok"),
            CheckResult("ruff", "python -m ruff check .", 0, 1, "ok"),
            CheckResult("compileall", "python -m compileall .", 0, 1, "ok"),
            CheckResult("pip check", "python -m pip check", 0, 1, "ok"),
            CheckResult("smoke", "python scripts/smoke_test.py", 0, 1, "ok"),
        ])
        return results

    def _prepare_integrated_for_reversal(self):
        proposal = self._prepare_commit_ready_for_integration()
        with patch.object(self.service, "_validate_commit_in_clean_worktree", return_value=self._passed_validation()):
            response = self.service.integrar(proposal.id)
        self.assertIn("Integracao concluida", response)
        self.assertEqual("INTEGRADA", proposal.state)
        return proposal

    def _request_reversal_ready_for_approval(self, proposal):
        response = self.service.solicitar_reversao(f"{proposal.id} motivo real")
        self.assertIn("Reversao solicitada", response)
        with patch.object(self.service, "_build_reversal_preview", return_value=self._fake_preview(proposal)):
            response = self.service.prever_reversao(proposal.id)
        self.assertIn("Previsao de reversao pronta", response)
        self.assertEqual("AGUARDANDO_APROVACAO_REVERSAO", proposal.state)
        return response

    def _prepare_reversal_approved(self):
        proposal = self._prepare_integrated_for_reversal()
        self._request_reversal_ready_for_approval(proposal)
        response = self.service.aprovar_reversao(proposal.id)
        self.assertIn("Aprovacao de reversao registrada", response)
        self.assertEqual("REVERSAO_APROVADA", proposal.state)
        return proposal

    def _fake_preview(self, proposal, *, valid: bool = True, reason: str = ""):
        diff = (
            "diff --git a/aya/core/sample.py b/aya/core/sample.py\n"
            "--- a/aya/core/sample.py\n"
            "+++ b/aya/core/sample.py\n"
            "@@ -1,6 +1,5 @@\n"
            " import json\n"
            " \n"
            " class Sample:\n"
            "     def run(self, value: str) -> str:\n"
            "-        \"\"\"Executa sample.\"\"\"\n"
            "         return json.dumps(value)\n"
        )
        validation = self._passed_validation() if valid else [CheckResult("pytest", "python -m pytest", 1, 0, "falhou").__dict__ | {"passed": False}]
        return {
            "base_head": self._git_head(self.root),
            "target_commit": proposal.reversal_target_commit or proposal.integrated_commit or proposal.proposal_commit,
            "diff": diff if valid else "",
            "files": ["aya/core/sample.py"] if valid else [],
            "added": 0,
            "removed": 1 if valid else 0,
            "validation": validation,
            "conflicts": "" if valid else reason,
            "workspace_cleaned": True,
            "valid": valid,
            "invalidated_reason": reason,
        }

    def _panel(self, channel=AccessChannel.LOCAL_GRADIO):
        fake = type("FakeAssistant", (), {})()
        fake.aya_dev = self.service
        fake.permissions = PermissionManager()
        return AyaDevPanel(fake, channel=channel)

    def _git_head(self, path: Path) -> str:
        return subprocess.run(("git", "rev-parse", "HEAD"), cwd=path, capture_output=True, text=True, check=True).stdout.strip()


_GIT_HEAVY_TESTS = {
    "test_git_indisponivel_bloqueia_preparacao",
    "test_git_com_alteracoes_nao_salvas",
    "test_cria_worktree_isolado_sem_alterar_raiz",
    "test_git_apply_check_falhando_registra_falha_e_limpa_worktree",
    "test_preparar_structured_patch_gera_diff_real_e_aguarda_teste",
    "test_preparar_structured_patch_head_alterado_bloqueia_manifesto",
    "test_modelo_nao_pode_alterar_proposal_id_no_modo_estruturado",
    "test_preparar_structured_patch_validado_chega_a_aguardando_aprovacao",
    "test_preparar_structured_patch_segunda_tentativa_usa_erros_reais",
    "test_patch_markdown_falha_com_motivo_persistido_e_worktree_removido",
}
_GIT_HEAVY_PREFIXES = (
    "test_aplicar_",
    "test_integrar_",
    "test_solicitar_reversao_detecta_",
    "test_prever_reversao_",
    "test_aprovar_reversao_",
    "test_diff_reversao_",
    "test_reverter_",
    "test_rejeitar_",
)


def _mark_aya_dev_tests() -> None:
    for name, value in AyaDevTestCase.__dict__.items():
        if not name.startswith("test_"):
            continue
        if name in _GIT_HEAVY_TESTS or name.startswith(_GIT_HEAVY_PREFIXES):
            setattr(AyaDevTestCase, name, pytest.mark.integration(pytest.mark.git(pytest.mark.slow(value))))

_mark_aya_dev_tests()


if __name__ == "__main__":
    unittest.main()
