from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from aya.config import SECURITY_CONFIG

IGNORAR_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", "data_local", "exports", "logs", "backups"}
EXTENSOES_TEXTO = {".py", ".md", ".txt", ".json", ".toml", ".yaml", ".yml"}
ARQUIVOS_BLOQUEADOS = {".env", ".env.local"}
EXTENSOES_BLOQUEADAS = {".db", ".sqlite", ".sqlite3", ".key", ".pem"}


@dataclass
class FileSummary:
    path: str
    lines: int
    chars: int


@dataclass
class ProjectFinding:
    severity: str
    path: str
    line: int
    message: str


@dataclass
class FileReview:
    path: str
    content: str
    summary: str


class ProjectTools:
    def __init__(self, root: str | Path = SECURITY_CONFIG.allowed_file_root):
        self.root = Path(root).resolve()

    def listar_arquivos(self) -> list[Path]:
        arquivos = []
        for path in self.root.rglob("*"):
            if any(part in IGNORAR_DIRS for part in path.parts):
                continue
            if path.is_file() and path.suffix.lower() in EXTENSOES_TEXTO:
                arquivos.append(path)
        return sorted(arquivos)

    def resumir_projeto(self) -> str:
        arquivos = self.listar_arquivos()
        summaries = [self._resumir_arquivo(path) for path in arquivos]

        total_linhas = sum(item.lines for item in summaries)
        linhas = [
            "Resumo do projeto:",
            f"- Raiz: {self.root}",
            f"- Arquivos de texto/código: {len(summaries)}",
            f"- Linhas aproximadas: {total_linhas}",
            "",
            "Arquivos principais:",
        ]
        for item in summaries[:30]:
            linhas.append(f"- {item.path}: {item.lines} linhas")
        if len(summaries) > 30:
            linhas.append(f"- ... mais {len(summaries) - 30} arquivo(s)")
        return "\n".join(linhas)

    def diagnosticar_projeto(self) -> str:
        arquivos = self.listar_arquivos()
        summaries = [self._resumir_arquivo(path) for path in arquivos]
        findings = self._coletar_findings(arquivos, summaries)
        extensoes = self._contar_extensoes(arquivos)

        linhas = [
            "Diagnostico local do projeto:",
            f"- Raiz: {self.root}",
            f"- Arquivos analisados: {len(arquivos)}",
            f"- Linhas aproximadas: {sum(item.lines for item in summaries)}",
            f"- Testes detectados: {'sim' if self._tem_testes(arquivos) else 'nao'}",
        ]

        if extensoes:
            linhas.append("- Extensoes: " + ", ".join(f"{ext}={total}" for ext, total in extensoes[:8]))

        grandes = sorted(summaries, key=lambda item: item.lines, reverse=True)[:5]
        if grandes:
            linhas.append("")
            linhas.append("Arquivos maiores:")
            for item in grandes:
                linhas.append(f"- {item.path}: {item.lines} linhas")

        if findings:
            linhas.append("")
            linhas.append("Achados:")
            for finding in findings[:12]:
                location = f"{finding.path}:{finding.line}" if finding.line else finding.path
                linhas.append(f"- [{finding.severity}] {location} - {finding.message}")
        else:
            linhas.append("")
            linhas.append("Achados: nenhum risco simples detectado.")

        linhas.append("")
        linhas.append("Proximos passos sugeridos:")
        for passo in self._sugerir_passos(arquivos, summaries, findings):
            linhas.append(f"- {passo}")
        return "\n".join(linhas)

    def ler_arquivo(self, caminho: str, limite_chars: int = 12000) -> str:
        path = (self.root / caminho).resolve()
        if not self._dentro_da_raiz(path):
            return "Não posso ler arquivos fora da raiz do projeto por este comando."
        if self._bloqueado(path):
            return "Esse arquivo fica bloqueado por seguranca."
        if not path.exists() or not path.is_file():
            return "Arquivo não encontrado."
        if path.suffix.lower() not in EXTENSOES_TEXTO:
            return "Esse tipo de arquivo não é lido por segurança neste comando."

        texto = path.read_text(encoding="utf-8", errors="replace")
        if len(texto) > limite_chars:
            texto = texto[:limite_chars] + "\n... [arquivo truncado]"
        return texto

    def preparar_revisao_arquivo(self, caminho: str, limite_chars: int = 16000) -> FileReview | str:
        path = (self.root / caminho).resolve()
        if not self._dentro_da_raiz(path):
            return "Nao posso revisar arquivos fora da raiz do projeto por este comando."
        if self._bloqueado(path):
            return "Esse arquivo fica bloqueado por seguranca."
        if not path.exists() or not path.is_file():
            return "Arquivo nao encontrado."
        if path.suffix.lower() not in EXTENSOES_TEXTO:
            return "Esse tipo de arquivo nao e revisado por seguranca neste comando."

        texto = path.read_text(encoding="utf-8", errors="replace")
        truncado = len(texto) > limite_chars
        conteudo = texto[:limite_chars]
        if truncado:
            conteudo += "\n... [arquivo truncado para revisao]"

        rel = str(path.relative_to(self.root))
        linhas = texto.splitlines()
        findings = self._coletar_findings([path], [FileSummary(rel, len(linhas) or 1, len(texto))])
        resumo = self._resumo_revisao(rel, linhas, findings, truncado)
        return FileReview(path=rel, content=conteudo, summary=resumo)

    def _resumir_arquivo(self, path: Path) -> FileSummary:
        texto = path.read_text(encoding="utf-8", errors="replace")
        rel = str(path.relative_to(self.root))
        return FileSummary(path=rel, lines=texto.count("\n") + 1, chars=len(texto))

    def _coletar_findings(self, arquivos: list[Path], summaries: list[FileSummary]) -> list[ProjectFinding]:
        findings: list[ProjectFinding] = []
        for item in summaries:
            if item.lines > 600:
                findings.append(ProjectFinding("medio", item.path, 0, "arquivo grande; considere dividir responsabilidades"))
            if item.chars > 80_000:
                findings.append(ProjectFinding("baixo", item.path, 0, "arquivo pesado para contexto de modelo local"))

        for path in arquivos:
            rel = str(path.relative_to(self.root))
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for number, line in enumerate(lines, start=1):
                lower = line.lower()
                if "todo" in lower or "fixme" in lower:
                    findings.append(ProjectFinding("baixo", rel, number, "marcador TODO/FIXME encontrado"))
                if self._parece_segredo(line):
                    findings.append(ProjectFinding("alto", rel, number, "possivel segredo/token em arquivo de texto"))
        return findings

    def _contar_extensoes(self, arquivos: list[Path]) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        for path in arquivos:
            ext = path.suffix.lower() or "[sem extensao]"
            counts[ext] = counts.get(ext, 0) + 1
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))

    def _tem_testes(self, arquivos: list[Path]) -> bool:
        return any("test" in path.name.lower() or "tests" in [part.lower() for part in path.parts] for path in arquivos)

    def _resumo_revisao(
        self,
        rel: str,
        lines: list[str],
        findings: list[ProjectFinding],
        truncado: bool,
    ) -> str:
        imports = self._extrair_imports(lines)
        simbolos = self._extrair_simbolos(lines)
        resumo = [
            "Resumo estatico do arquivo:",
            f"- Arquivo: {rel}",
            f"- Linhas: {len(lines) or 1}",
            f"- Truncado: {'sim' if truncado else 'nao'}",
        ]
        if imports:
            resumo.append("- Imports principais: " + ", ".join(imports[:12]))
        if simbolos:
            resumo.append("- Classes/funcoes: " + ", ".join(simbolos[:20]))
        if findings:
            resumo.append("- Achados simples:")
            for finding in findings[:10]:
                location = f"{finding.path}:{finding.line}" if finding.line else finding.path
                resumo.append(f"  - [{finding.severity}] {location} - {finding.message}")
        else:
            resumo.append("- Achados simples: nenhum marcador obvio detectado")
        return "\n".join(resumo)

    def _extrair_imports(self, lines: list[str]) -> list[str]:
        imports: list[str] = []
        for line in lines:
            stripped = line.strip()
            match = re.match(r"(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", stripped)
            if match:
                value = match.group(1) or match.group(2)
                if value and value not in imports:
                    imports.append(value)
        return imports

    def _extrair_simbolos(self, lines: list[str]) -> list[str]:
        symbols: list[str] = []
        for line in lines:
            match = re.match(r"\s*(class|def|async def)\s+([A-Za-z_]\w*)", line)
            if match:
                prefix = "class" if match.group(1) == "class" else "def"
                symbols.append(f"{prefix} {match.group(2)}")
        return symbols

    def _parece_segredo(self, line: str) -> bool:
        patterns = [
            r"api[_-]?key\s*[:=]\s*['\"][^'\"]{12,}",
            r"secret\s*[:=]\s*['\"][^'\"]{12,}",
            r"token\s*[:=]\s*['\"][^'\"]{20,}",
            r"sk-[A-Za-z0-9_-]{20,}",
        ]
        return any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in patterns)

    def _sugerir_passos(self, arquivos: list[Path], summaries: list[FileSummary], findings: list[ProjectFinding]) -> list[str]:
        passos: list[str] = []
        if not self._tem_testes(arquivos):
            passos.append("Criar uma pasta tests/ com testes de comportamento principal.")
        if any(f.severity == "alto" for f in findings):
            passos.append("Revisar possiveis segredos antes de compartilhar o projeto.")
        if any(item.lines > 600 for item in summaries):
            passos.append("Quebrar arquivos grandes em modulos menores.")
        if not any(path.name.lower() == "readme.md" for path in arquivos):
            passos.append("Adicionar README.md com instalacao e comandos principais.")
        if not any(path.name.lower() in {"requirements.txt", "pyproject.toml"} for path in arquivos):
            passos.append("Registrar dependencias em requirements.txt ou pyproject.toml.")
        if not passos:
            passos.append("Rodar testes e escolher uma melhoria pequena para o proximo ciclo.")
        return passos[:5]

    def _dentro_da_raiz(self, path: Path) -> bool:
        try:
            path.relative_to(self.root)
            return True
        except ValueError:
            return False

    def _bloqueado(self, path: Path) -> bool:
        parts = {part.lower() for part in path.parts}
        if parts & IGNORAR_DIRS:
            return True
        if path.name.lower() in ARQUIVOS_BLOQUEADOS:
            return True
        return path.suffix.lower() in EXTENSOES_BLOQUEADAS
