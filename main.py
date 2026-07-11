import logging

from aya.core.assistant import Assistant
from aya.paths import LOG_PATH, ensure_runtime_dirs

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.prompt import Prompt
except ImportError:
    Console = None
    Markdown = None
    Panel = None
    Prompt = None


ensure_runtime_dirs()
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main():
    assistant = Assistant()
    console = Console() if Console else None

    if console:
        console.print(Panel("Aya - Assistente de Estudos Local\nDigite /ajuda para ver comandos ou sair.", title="Aya"))
    else:
        print("Aya - Assistente de Estudos Local")
        print("Digite /ajuda para ver comandos ou sair para encerrar.")

    try:
        while True:
            entrada = Prompt.ask("\nVocê").strip() if Prompt else input("\nVocê: ").strip()
            if entrada.lower() in {"sair", "exit", "tchau"}:
                mensagem = "Até logo. Continue estudando com consistência."
                if console:
                    console.print(Panel(mensagem, title="Aya"))
                else:
                    print(f"Aya: {mensagem}")
                break

            resposta = assistant.responder(entrada)
            if console:
                console.print(Panel(Markdown(resposta), title="Aya"))
            else:
                print(f"Aya: {resposta}")
    finally:
        assistant.encerrar()


if __name__ == "__main__":
    main()
