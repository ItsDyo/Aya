from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from aya.core.aya_dev import AyaDevService
from aya.core.llm import StaticClient
from aya.core.project_tools import ProjectTools


class AyaDevMetricsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "projeto"
        (self.root / "aya" / "core").mkdir(parents=True)
        (self.root / "tests").mkdir()
        (self.root / "aya" / "core" / "sample.py").write_text(
            "class Sample:\n    def run(self):\n        return 'ok'\n",
            encoding="utf-8",
        )
        (self.root / "tests" / "test_sample.py").write_text(
            "from aya.core.sample import Sample\n\n\ndef test_sample():\n    assert Sample().run() == 'ok'\n",
            encoding="utf-8",
        )
        state = self.root.parent / "state"
        self.storage = state / "history.json"
        self.memory = state / "engineering_memory.jsonl"
        self.service = AyaDevService(
            self.root,
            StaticClient("ok"),
            ProjectTools(self.root),
            storage_path=self.storage,
            index_path=state / "index.json",
            engineering_memory_path=self.memory,
            workspace_root=self.root.parent / "workspaces",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def proposal(self, **overrides):
        values = {
            "title": "Documentar Sample",
            "problem": "Metodo run precisa de memoria tecnica.",
            "evidence": ["Indice AST confirmou aya/core/sample.py."],
            "related_files": ["aya/core/sample.py", "tests/test_sample.py"],
            "related_symbols": ["Sample", "run"],
            "probable_cause": "Responsabilidade pouco explicita.",
            "suggested_change": "Adicionar registro pequeno.",
            "preserve": ["retorno atual"],
            "impact": "baixo",
            "urgency": "baixa",
            "difficulty": "baixa",
            "required_tests": ["tests/test_sample.py"],
            "done_criteria": ["metricas estaveis"],
        }
        values.update(overrides)
        return self.service.create_proposal(**values)

    def test_metricas_vazias_sao_deterministicas_e_somente_leitura(self):
        first = self.service.execute("metricas")
        second = self.service.execute("metricas")

        self.assertEqual(first, second)
        self.assertIn("Propostas registradas: 0", first)
        self.assertIn("nao executa Git, modelo, testes ou rede", first)
        self.assertFalse(self.storage.exists())

    def test_metricas_contam_estado_risco_validacao_e_falha(self):
        proposal = self.proposal()
        proposal.state = "FALHOU"
        proposal.failure_stage = "validacao"
        proposal.failure_reason = "pytest"
        proposal.validation = [{"name": "pytest", "passed": False}, {"name": "ruff", "passed": True}]
        self.service._save()

        result = self.service.execute("metricas")

        self.assertIn("Propostas registradas: 1", result)
        self.assertIn("Estados: FALHOU=1", result)
        self.assertIn("Riscos: alto=1", result)
        self.assertIn("Validacoes registradas: 2 (aprovadas=1, reprovadas=1)", result)
        self.assertIn("validacao:pytest=1", result)
        self.assertIn(proposal.id, result)

    def test_metricas_ocultam_dados_sensiveis_em_motivos_de_falha(self):
        proposal = self.proposal()
        proposal.state = "FALHOU"
        proposal.failure_stage = "validacao"
        proposal.failure_reason = "token=segredo"
        self.service._save()

        result = self.service.execute("metricas")

        self.assertIn("validacao:", result)
        self.assertNotIn("segredo", result)

    def test_memoria_tecnica_registra_sanitiza_e_e_idempotente(self):
        first = self.service.execute("registrar-memoria risco | Token exposto | token=segredo")
        second = self.service.execute("registrar-memoria risco | Token exposto | token=segredo")

        self.assertIn("Memoria tecnica registrada: ENG-", first)
        self.assertIn("ja registrada", second)
        listing = self.service.execute("memoria-tecnica")
        self.assertIn("[risco] Token exposto", listing)
        self.assertNotIn("segredo", listing)

    def test_memoria_tecnica_mostra_sinais_derivados_sem_registro_manual(self):
        proposal = self.proposal()
        proposal.state = "INTEGRADA"
        self.service._save()

        listing = self.service.execute("memoria-tecnica")

        self.assertIn("Nenhuma memoria tecnica registrada manualmente", listing)
        self.assertIn("Integracoes concluidas por fast-forward estrito: 1", listing)

    def test_comando_de_memoria_tecnica_recusa_payload_incompleto(self):
        result = self.service.execute("registrar-memoria apenas titulo")

        self.assertIn("Use assim", result)
        self.assertFalse(self.memory.exists())

    def test_metricas_contam_memorias_tecnicas_sem_alterar_historico(self):
        self.service.execute("registrar-memoria teste | Validacao | Suite rapida aprovada")
        before = self.memory.read_text(encoding="utf-8")

        result = self.service.execute("metricas")
        after = self.memory.read_text(encoding="utf-8")

        self.assertIn("Memorias tecnicas registradas: 1", result)
        self.assertEqual(before, after)

    def test_evento_relevante_registra_memoria_tecnica_automaticamente(self):
        proposal = self.proposal()

        self.service._event(proposal, "commit integrado por fast-forward", "INTEGRANDO", "INTEGRADA")
        self.service._event(proposal, "commit integrado por fast-forward", "INTEGRANDO", "INTEGRADA")

        listing = self.service.execute("memoria-tecnica")
        self.assertIn(f"{proposal.id}: INTEGRADA", listing)
        self.assertIn("[decisao]", listing)
        self.assertEqual(1, len(self.service._load_engineering_memory()))

    def test_eventos_tecnicos_lista_historico_relevante_sem_escrever(self):
        proposal = self.proposal()
        self.service._event(proposal, "patch recusado token=segredo", "PREPARANDO", "FALHOU")
        before = self.memory.read_text(encoding="utf-8")

        result = self.service.execute("eventos-tecnicos")
        after = self.memory.read_text(encoding="utf-8")

        self.assertIn(proposal.id, result)
        self.assertIn("FALHOU", result)
        self.assertNotIn("segredo", result)
        self.assertEqual(before, after)

    def test_evento_nao_relevante_nao_registra_memoria_tecnica(self):
        proposal = self.proposal()

        self.service._event(proposal, "plano local criado", "PROPOSTA", "PLANEJADA")

        self.assertFalse(self.memory.exists())
        self.assertIn("nenhum evento relevante", self.service.execute("eventos-tecnicos"))


if __name__ == "__main__":
    unittest.main()
