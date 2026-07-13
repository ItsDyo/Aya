from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from aya.core.aya_dev import AyaDevService
from aya.core.dev_workspace import CheckResult, GitState
from aya.core.llm import StaticClient
from aya.core.project_tools import ProjectTools
from aya.core.structured_patch import PATCH_MANIFEST_SCHEMA, StructuredPatchError


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
            return json.loads(self.payload)
        return self.payload


class DynamicStructuredClient(StaticClient):
    def chat_structured(self, **kwargs):
        self.calls.append(kwargs)
        text = kwargs["messages"][-1]["content"]
        proposal_id = next(line.split(": ", 1)[1] for line in text.splitlines() if line.startswith("proposal_id:"))
        base_commit = next(line.split(": ", 1)[1] for line in text.splitlines() if line.startswith("base_commit:"))
        sha = next(line.split("sha256=", 1)[1].split(",", 1)[0] for line in text.splitlines() if line.startswith("- aya/core/sample.py:"))
        return {
            "version": 1,
            "proposal_id": proposal_id,
            "base_commit": base_commit,
            "operations": [{
                "type": "insert_docstring",
                "file": "aya/core/sample.py",
                "symbol": "Sample.run",
                "expected_sha256": sha,
                "content": "Executa sample.",
            }],
            "tests": ["tests/test_sample.py"],
        }


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
        manifest = self._manifest(expected_sha256=self._sha("aya/core/sample.py"))
        manifest["proposal_id"] = proposal.id
        manifest["base_commit"] = "HEAD-ANTIGO"
        self.service.llm = StructuredClient(manifest)
        response = self.service.preparar(proposal.id)
        self.assertIn("base_commit", response)
        self.assertEqual("FALHOU", proposal.state)
        self.assertTrue(proposal.workspace_cleaned)

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
        subprocess.run(("git", "add", "."), cwd=self.root, capture_output=True, check=True)
        subprocess.run(("git", "commit", "-m", "state after failed attempt"), cwd=self.root, capture_output=True, check=True)
        self.service.llm = DynamicStructuredClient("review ok")
        response = self.service.preparar(proposal.id)
        self.assertIn("Patch preparado", response)
        context = self.service.llm.calls[-1]["messages"][-1]["content"]
        self.assertIn("manifesto recusado", context)
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
        proposal.state = "AGUARDANDO_APROVACAO"
        before = (self.root / "aya/core/sample.py").read_text(encoding="utf-8")
        self.service.aprovar(proposal.id)
        after = (self.root / "aya/core/sample.py").read_text(encoding="utf-8")
        self.assertEqual(before, after)
        self.assertIn("nao habilitada", self.service.aplicar(proposal.id).lower())

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
            operation.update({"old": old, "new": new})
        return {
            "version": 1,
            "proposal_id": "DEV-20260713-ABCDEF",
            "base_commit": "abc1234",
            "operations": [operation],
            "tests": ["tests/test_sample.py"],
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

    def test_pergunta_natural_sobre_proposta_usa_dados_estruturados(self):
        from aya.core.assistant import Assistant
        from aya.core.llm import StaticClient
        from aya.data.database import Database

        with tempfile.TemporaryDirectory() as tmp:
            assistant = Assistant(db=Database(Path(tmp) / "test.db"), llm=StaticClient("chat generico"))
            proposal = assistant.aya_dev.create_proposal(
                title="Documentar modulo",
                problem="Falta docstring.",
                evidence=["Indice AST confirmou aya/core/aya_dev.py."],
                related_files=["aya/core/aya_dev.py"],
                related_symbols=["AyaDevService"],
                probable_cause="Documentacao interna incompleta.",
                suggested_change="Adicionar docstring.",
                preserve=["comportamento atual"],
                impact="baixo",
                urgency="baixa",
                difficulty="baixa",
                required_tests=["tests/test_aya_dev.py"],
                done_criteria=["testes passam"],
            )
            response = assistant.responder(f"qual foi a falha da proposta {proposal.id} do Aya Dev?")
            self.assertIn("Falha", response)
            self.assertIn("Informacao nao registrada", response)
            self.assertNotIn("chat generico", response)
            assistant.encerrar()


if __name__ == "__main__":
    unittest.main()
