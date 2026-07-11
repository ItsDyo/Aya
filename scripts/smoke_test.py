import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aya.core.assistant import Assistant  # noqa: E402
from aya.core.llm import StaticClient  # noqa: E402
from aya.data.database import Database  # noqa: E402


def main():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "smoke.db")
        assistant = Assistant(db=db, llm=StaticClient("Resposta simulada."))
        perguntas = [
            "/status",
            "/salvar teste | A Aya guarda conhecimentos no SQLite. | sistema",
            "/buscar teste",
            "Explique o que você lembra sobre teste.",
        ]

        for pergunta in perguntas:
            print(f"\nVocê: {pergunta}")
            print(f"Aya: {assistant.responder(pergunta)}")
        assistant.encerrar()


if __name__ == "__main__":
    main()
