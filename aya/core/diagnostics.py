from __future__ import annotations

import importlib.util
import shutil
import socket
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from aya.config import SERVER_CONFIG, ServerConfig
from aya.core.llm import ChatClient
from aya.core.voice import DEFAULT_CONFIG_PATH, DEFAULT_MODEL_PATH, PiperVoice
from aya.data.database import Database
from aya.paths import DATA_DIR, EXPORTS_DIR, LOGS_DIR


class DiagnosticsService:
    """Diagnosticos locais da Aya: banco, pastas, dependencias, modelos e voz."""

    def __init__(
        self,
        db: Database,
        llm: ChatClient,
        model_primary: str,
        model_reviewer: str,
        status_provider: Callable[[], str],
        backup_provider: Callable[[], str] | None = None,
        server_config: ServerConfig = SERVER_CONFIG,
    ):
        self.db = db
        self.llm = llm
        self.model_primary = model_primary
        self.model_reviewer = model_reviewer
        self.status_provider = status_provider
        self.backup_provider = backup_provider
        self.server_config = server_config

    def diagnostico(self) -> str:
        linhas = [self.status_provider()]
        if self.backup_provider:
            linhas.extend(["", self.backup_provider()])
        linhas.extend(["", *self._diagnostico_sistema()])
        linhas.extend(["", *self._diagnostico_acesso()])
        if hasattr(self.llm, "healthcheck"):
            linhas.append("")
            linhas.append("Modelos:")
            linhas.append(f"- {self.llm.healthcheck(self.model_primary).message}")
            linhas.append(f"- {self.llm.healthcheck(self.model_reviewer).message}")
        else:
            linhas.append("\nModelos: cliente de teste/injetado sem healthcheck.")
        return "\n".join(linhas)

    def modelos(self) -> str:
        return f"Modelo principal: {self.model_primary}\nModelo revisor: {self.model_reviewer}"

    def _diagnostico_sistema(self) -> list[str]:
        linhas = ["Sistema:"]

        def status(nome: str, ok: bool, detalhe: str = ""):
            marcador = "OK" if ok else "ATENCAO"
            sufixo = f" - {detalhe}" if detalhe else ""
            linhas.append(f"- [{marcador}] {nome}{sufixo}")

        try:
            quick_check = self.db.connection.execute("PRAGMA quick_check").fetchone()[0]
            status("Banco SQLite", quick_check == "ok", f"quick_check={quick_check}")
        except Exception as exc:
            status("Banco SQLite", False, str(exc))

        for pasta in (DATA_DIR, EXPORTS_DIR, LOGS_DIR):
            try:
                pasta.mkdir(exist_ok=True)
                teste = pasta / ".aya_write_test"
                teste.write_text("ok", encoding="utf-8")
                teste.unlink(missing_ok=True)
                status(f"Pasta {pasta.name}", True, str(pasta))
            except Exception as exc:
                status(f"Pasta {pasta.name}", False, str(exc))

        for modulo in ("gradio", "openai", "rich"):
            status(f"Dependencia {modulo}", importlib.util.find_spec(modulo) is not None)

        voice = PiperVoice()
        status("Piper executavel", bool(voice._piper_executable()), voice._piper_executable() or "pip install piper-tts")
        status("Modelo de voz", DEFAULT_MODEL_PATH.exists(), str(DEFAULT_MODEL_PATH))
        status("Config da voz", DEFAULT_CONFIG_PATH.exists(), str(DEFAULT_CONFIG_PATH))
        return linhas

    def _diagnostico_acesso(self) -> list[str]:
        linhas = ["Acesso local/remoto:"]

        def status(nome: str, ok: bool, detalhe: str = "", aviso: bool = False):
            marcador = "OK" if ok else ("AVISO" if aviso else "ATENCAO")
            sufixo = f" - {detalhe}" if detalhe else ""
            linhas.append(f"- [{marcador}] {nome}{sufixo}")

        cfg = self.server_config
        auth_detail = "habilitada" if cfg.auth else "desabilitada ou incompleta"
        status("Modo remoto", cfg.remote_mode, "AYA_REMOTE_MODE=true" if cfg.remote_mode else "local")
        status("Autenticacao Gradio", bool(cfg.auth), auth_detail, aviso=not cfg.is_network_exposed)
        status("Host Gradio", cfg.host in {"127.0.0.1", "localhost"}, cfg.host, aviso=True)
        status("Porta Gradio", self._porta_aberta("127.0.0.1", cfg.port), f"127.0.0.1:{cfg.port}", aviso=True)
        status(
            "Interface local",
            self._http_ok(f"http://127.0.0.1:{cfg.port}"),
            f"http://127.0.0.1:{cfg.port}",
            aviso=True,
        )
        tailscale = self._tailscale_path()
        status("Tailscale instalado", bool(tailscale), tailscale or "tailscale nao encontrado", aviso=True)
        if tailscale:
            connected, detail = self._tailscale_status(tailscale)
            status("Tailscale conectado", connected, detail, aviso=True)
            ip = self._tailscale_ip(tailscale)
            status("IP Tailscale", bool(ip), ip or "IPv4 nao retornado", aviso=True)
            linhas.append(f"- Comando Serve: \"{tailscale}\" serve {cfg.port}")
        else:
            linhas.append(f"- Comando Serve: tailscale serve {cfg.port}")
        linhas.append("- Seguranca: use Tailscale Serve; nao use Funnel e nao abra porta no roteador.")
        return linhas

    def _porta_aberta(self, host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=1.5):
                return True
        except OSError:
            return False

    def _http_ok(self, url: str) -> bool:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                return 200 <= response.status < 500
        except (OSError, urllib.error.URLError):
            return False

    def _tailscale_path(self) -> str | None:
        found = shutil.which("tailscale")
        if found:
            return found
        default = Path(r"C:\Program Files\Tailscale\tailscale.exe")
        return str(default) if default.exists() else None

    def _tailscale_status(self, tailscale: str) -> tuple[bool, str]:
        try:
            result = subprocess.run([tailscale, "status"], capture_output=True, text=True, timeout=5, check=False)
        except Exception as exc:
            return False, str(exc)
        detail = "conectado" if result.returncode == 0 else (result.stderr or result.stdout or "status falhou").strip()
        return result.returncode == 0, detail[:180]

    def _tailscale_ip(self, tailscale: str) -> str | None:
        try:
            result = subprocess.run([tailscale, "ip", "-4"], capture_output=True, text=True, timeout=5, check=False)
        except Exception:
            return None
        if result.returncode != 0:
            return None
        return next((line.strip() for line in result.stdout.splitlines() if line.strip()), None)
