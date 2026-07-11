from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

from aya.config import VOICE_CONFIG


DEFAULT_VOICE_NAME = VOICE_CONFIG.name
DEFAULT_VOICE_DIR = VOICE_CONFIG.voice_dir
DEFAULT_MODEL_PATH = VOICE_CONFIG.model_path
DEFAULT_CONFIG_PATH = VOICE_CONFIG.config_path


class PiperVoice:
    """Sintese de voz local com Piper TTS."""

    def __init__(
        self,
        model_path: str | Path | None = None,
        config_path: str | Path | None = None,
        output_path: str | Path | None = None,
    ):
        self.model_path = Path(model_path or os.getenv("AYA_PIPER_MODEL", DEFAULT_MODEL_PATH))
        self.config_path = Path(config_path or os.getenv("AYA_PIPER_CONFIG", DEFAULT_CONFIG_PATH))
        self.output_path = Path(output_path or Path(tempfile.gettempdir()) / VOICE_CONFIG.output_file)

    def falar(self, texto: str, reproduzir: bool = True) -> tuple[str | None, str]:
        texto = (texto or "").strip()
        if not texto:
            return None, "Nao ha texto para falar."

        erro = self._validar_ambiente()
        if erro:
            return None, erro

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        comando = [
            self._piper_executable(),
            "--model",
            str(self.model_path),
            "--config",
            str(self.config_path),
            "--output_file",
            str(self.output_path),
        ]

        try:
            subprocess.run(
                comando,
                input=texto[: VOICE_CONFIG.max_chars],
                text=True,
                encoding="utf-8",
                check=True,
                capture_output=True,
                timeout=VOICE_CONFIG.timeout_seconds,
            )
            if not self.output_path.exists() or self.output_path.stat().st_size == 0:
                return None, "Piper executou, mas nao gerou arquivo de audio."
            if reproduzir:
                self.reproduzir(self.output_path)
            return str(self.output_path), ""
        except subprocess.CalledProcessError as exc:
            detalhe = (exc.stderr or exc.stdout or "").strip()
            return None, f"Erro ao executar Piper TTS. {detalhe}".strip()
        except subprocess.TimeoutExpired:
            return None, "Piper demorou demais para gerar a fala."
        except Exception as exc:
            return None, f"Nao consegui gerar/reproduzir a fala: {exc}"

    def reproduzir(self, audio_path: str | Path):
        path = str(audio_path)
        if os.name == "nt":
            import winsound

            winsound.PlaySound(path, winsound.SND_FILENAME)
            return

        player = shutil.which("aplay") or shutil.which("paplay") or shutil.which("ffplay")
        if player:
            if Path(player).name == "ffplay":
                subprocess.run([player, "-nodisp", "-autoexit", path], check=False)
            else:
                subprocess.run([player, path], check=False)

    def _validar_ambiente(self) -> str:
        if not self.model_path.exists():
            return (
                f"Modelo Piper nao encontrado: {self.model_path}\n"
                f"Baixe {DEFAULT_VOICE_NAME}.onnx e {DEFAULT_VOICE_NAME}.onnx.json "
                f"e coloque em: {DEFAULT_VOICE_DIR}"
            )
        if not self.config_path.exists():
            return (
                f"Config do modelo Piper nao encontrada: {self.config_path}\n"
                f"Baixe {DEFAULT_VOICE_NAME}.onnx.json e coloque junto do .onnx em: {DEFAULT_VOICE_DIR}"
            )
        if not self._piper_executable():
            return "Executavel Piper nao encontrado. Instale com: pip install piper-tts"
        return ""

    def _piper_executable(self) -> str:
        found = shutil.which("piper") or shutil.which("piper.exe")
        if found:
            return found
        scripts = Path(sys.executable).resolve().parent / "Scripts" / "piper.exe"
        if scripts.exists():
            return str(scripts)
        return ""


class VoiceIO:
    """Entrada/saida de voz opcional para a interface Gradio."""

    def __init__(self, piper: PiperVoice | None = None):
        self.piper = piper or PiperVoice()

    def transcribe(self, audio_path: str | None) -> tuple[str, str]:
        if not audio_path:
            return "", "Nenhum audio recebido."
        try:
            import speech_recognition as sr  # type: ignore
        except ImportError:
            return "", "Transcricao indisponivel. Instale: pip install SpeechRecognition pocketsphinx"

        recognizer = sr.Recognizer()
        try:
            with sr.AudioFile(audio_path) as source:
                audio = recognizer.record(source)
            text = recognizer.recognize_sphinx(audio, language="pt-BR")
            return text, ""
        except Exception as exc:
            return "", f"Nao consegui transcrever o audio localmente: {exc}"

    def synthesize(self, text: str) -> tuple[str | None, str]:
        return self.piper.falar(text, reproduzir=True)


def falar(texto: str) -> str | None:
    """Faz a Aya falar usando Piper TTS e reproduz automaticamente."""

    audio_path, erro = PiperVoice().falar(texto, reproduzir=True)
    if erro:
        raise RuntimeError(erro)
    return audio_path


def criar_wav_silencioso(target: str | Path):
    target = Path(target)
    with wave.open(str(target), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 1600)
