from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pytest

from aya.core.llm import StaticClient
from aya.data.database import Database


class AssistantAyaDevInitializationTest(unittest.TestCase):
    def test_assistant_normal_continua_inicializando(self):
        from aya.core.assistant import Assistant

        with tempfile.TemporaryDirectory() as tmp:
            assistant = Assistant(db=Database(Path(tmp) / "test.db"), llm=StaticClient())
            self.assertIn("Aya Dev", assistant.responder("/aya-dev status"))
            assistant.encerrar()

    @pytest.mark.ui
    def test_interface_gradio_normal_inicializa_com_aya_dev(self):
        from app import create_app
        from aya.core.assistant import Assistant

        path = Path(tempfile.gettempdir()) / "aya_ui_test.sqlite"
        assistant = Assistant(db=Database(path), llm=StaticClient())
        try:
            demo = create_app(assistant=assistant)
            self.assertEqual("Blocks", type(demo).__name__)
        finally:
            assistant.encerrar()
            try:
                path.unlink()
            except OSError:
                pass

    def test_pergunta_natural_sobre_proposta_usa_dados_estruturados(self):
        from aya.core.assistant import Assistant

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

    def test_painel_aya_dev_exibe_observacao_capacidade_e_rota(self):
        from aya.ui.aya_dev import AyaDevPanel

        class FakeAyaDev:
            def autonomy_status(self):
                return "Autonomia supervisionada"

            def evaluate_autonomy(self):
                return "Avaliacao de autonomia"

            def list_candidates(self, scope=""):
                return f"Candidatos {scope}"

            def observe_cycle(self):
                return "Observacao somente leitura"

            def capability_report(self, filter_text=""):
                return f"Operacao insert_docstring {filter_text}"

            def route_candidate(self, candidate_id):
                return f"Candidato {candidate_id} nao encontrado"

            def explain_route(self, candidate_id):
                return f"Candidato {candidate_id} nao encontrado"

            def list_experiments(self):
                return "Experimentos de calibracao"

            def experiment_results(self):
                return "Resultados de calibracao"

            def create_calibration_experiment(self, candidate_id):
                return f"Experimento criado para {candidate_id}"

            def execute_calibration_experiment(self, payload):
                return f"Experimento executado: {payload}"

        permissions = SimpleNamespace(allows=lambda channel, capability: True, denial_message=lambda channel, capability: "negado")
        assistant = SimpleNamespace(aya_dev=FakeAyaDev(), permissions=permissions)
        panel = AyaDevPanel(assistant)
        status, avaliacao, candidatos, observacao = panel.autonomy_overview()
        capacidade = panel.autonomy_capability("operacao insert_docstring")
        filtrados = panel.autonomy_candidates("informativos")
        rota, explicacao = panel.autonomy_route("AUTO-INEXISTENTE")
        experimentos, resultados = panel.calibration_overview()
        criado = panel.create_calibration_experiment("AUTO-1")
        executado = panel.run_calibration_experiment("EXP-1", "EXECUTAR EXPERIMENTO EXP-1")
        self.assertIn("Autonomia supervisionada", status)
        self.assertIn("Avaliacao de autonomia", avaliacao)
        self.assertIn("Candidatos atuais", candidatos)
        self.assertIn("somente leitura", observacao)
        self.assertIn("Operacao insert_docstring", capacidade)
        self.assertIn("Candidatos informativos", filtrados)
        self.assertIn("nao encontrado", rota)
        self.assertIn("nao encontrado", explicacao)
        self.assertIn("Experimentos de calibracao", experimentos)
        self.assertIn("Resultados de calibracao", resultados)
        self.assertIn("AUTO-1", criado)
        self.assertIn("EXP-1", executado)


if __name__ == "__main__":
    unittest.main()
