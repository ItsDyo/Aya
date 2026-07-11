from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CodeAnalysis:
    language: str
    symptoms: list[str]
    file_refs: list[str]
    risky_commands: list[str]


class CodeAssistant:
    """Prepara pedidos de ajuda em programacao sem executar nada no sistema."""

    def analyze(self, text: str) -> CodeAnalysis:
        content = (text or "").strip()
        return CodeAnalysis(
            language=self._detect_language(content),
            symptoms=self._detect_symptoms(content),
            file_refs=self._detect_file_refs(content),
            risky_commands=self._detect_risky_commands(content),
        )

    def build_prompt(self, text: str, rag_context: str = "") -> str:
        content = (text or "").strip()
        analysis = self.analyze(content)
        lines = [
            "Modo agente de programacao da Aya.",
            "Ajude com o problema abaixo sem executar comandos e sem inventar arquivos que nao foram mostrados.",
            "",
            "Leitura rapida:",
            f"- Linguagem provavel: {analysis.language}",
        ]
        if analysis.symptoms:
            lines.append("- Sinais detectados: " + ", ".join(analysis.symptoms))
        if analysis.file_refs:
            lines.append("- Arquivos citados: " + ", ".join(analysis.file_refs[:8]))
        if analysis.risky_commands:
            lines.append("- Atenção: ha comandos potencialmente destrutivos; proponha alternativas seguras.")

        if rag_context:
            lines.extend([
                "",
                "Contexto local possivelmente relevante:",
                rag_context,
            ])

        lines.extend([
            "",
            "Tarefa:",
            "1. Explique a causa mais provavel.",
            "2. Mostre a correcao mais simples primeiro.",
            "3. Quando fizer sentido, mostre um trecho de codigo completo e pequeno.",
            "4. Liste como testar a correcao.",
            "5. Se faltar informacao, faca no maximo 2 perguntas objetivas.",
            "",
            "Problema ou codigo do usuario:",
            content,
        ])
        return "\n".join(lines)

    def _detect_language(self, text: str) -> str:
        lower = text.lower()
        if (
            "traceback (most recent call last)" in lower
            or re.search(r"\b(def|import|from)\s+\w+", text)
            or re.search(r"\b(print|self)\s*\(", text)
        ):
            return "Python"
        if re.search(r"\b(function|const|let|=>|console\.log)\b", text):
            return "JavaScript/TypeScript"
        if re.search(r"\b(select|insert|update|delete)\s+.+\b(from|into|set)\b", lower, re.DOTALL):
            return "SQL"
        if re.search(r"\b(class|public static void|system\.out\.println)\b", lower):
            return "Java"
        if re.search(r"<[a-z][\w-]*(\s|>)", lower):
            return "HTML/CSS"
        if "powershell" in lower or re.search(r"\b(get-childitem|select-string|invoke-webrequest)\b", lower):
            return "PowerShell"
        return "nao identificada"

    def _detect_symptoms(self, text: str) -> list[str]:
        lower = text.lower()
        symptoms: list[str] = []
        checks = [
            ("traceback", "traceback Python"),
            ("modulenotfounderror", "modulo ausente"),
            ("importerror", "erro de importacao"),
            ("syntaxerror", "erro de sintaxe"),
            ("typeerror", "erro de tipo"),
            ("attributeerror", "atributo inexistente"),
            ("permissionerror", "permissao/arquivo em uso"),
            ("timeout", "tempo esgotado"),
            ("failed", "falha reportada"),
            ("erro", "erro descrito"),
        ]
        for marker, label in checks:
            if marker in lower and label not in symptoms:
                symptoms.append(label)
        return symptoms[:6]

    def _detect_file_refs(self, text: str) -> list[str]:
        refs = re.findall(r"[\w./\\ -]+\.(?:py|js|ts|tsx|jsx|json|toml|yaml|yml|md|html|css|sql)", text, flags=re.I)
        cleaned: list[str] = []
        for ref in refs:
            value = ref.strip(" .,:;()[]{}'\"").replace("\\", "/")
            if value and value not in cleaned:
                cleaned.append(value)
        return cleaned

    def _detect_risky_commands(self, text: str) -> list[str]:
        risky: list[str] = []
        patterns = [
            r"\brm\s+-rf\b",
            r"\bdel\s+/[sq]\b",
            r"\bremove-item\b.*\b-recurse\b",
            r"\bgit\s+reset\s+--hard\b",
            r"\bdrop\s+database\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.I)
            if match:
                risky.append(match.group(0))
        return risky
