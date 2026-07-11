from __future__ import annotations

from aya.core.project_tools import FileReview


class ChangePlanService:
    """Monta pedidos de planejamento sem executar alteracoes em arquivos."""

    def build_prompt(self, review: FileReview, objective: str = "") -> str:
        objetivo = (objective or "").strip() or "melhorar o arquivo com o menor risco possivel"
        return (
            "Modo plano de alteracao da Aya.\n"
            "Voce esta ajudando a planejar uma mudanca de codigo, mas NAO deve editar arquivos, "
            "NAO deve dizer que editou e NAO deve prometer que executou testes.\n"
            "Use apenas o contexto abaixo para propor um plano seguro e verificavel.\n\n"
            f"Objetivo do usuario: {objetivo}\n\n"
            f"{review.summary}\n\n"
            f"Conteudo do arquivo {review.path}:\n"
            "```text\n"
            f"{review.content}\n"
            "```\n\n"
            "Responda em portugues com estas secoes:\n"
            "1. Diagnostico breve do arquivo.\n"
            "2. Plano de alteracao em passos pequenos.\n"
            "3. Riscos e pontos de atencao.\n"
            "4. Testes e validacoes que devem ser executados.\n"
            "5. Perguntas obrigatorias se faltar informacao.\n"
            "6. Confirmacao necessaria antes de editar qualquer arquivo."
        )
