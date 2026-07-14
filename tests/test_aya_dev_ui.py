from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
