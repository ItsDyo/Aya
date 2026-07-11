from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from openai import OpenAI

from aya.config import MODEL_CONFIG


class ChatClient(Protocol):
    def chat(self, model: str, messages: list[dict], temperature: float, max_tokens: int) -> str:
        ...


@dataclass
class LLMHealth:
    ok: bool
    message: str


class OllamaClient:
    def __init__(self, base_url: str = MODEL_CONFIG.ollama_base_url, api_key: str = MODEL_CONFIG.ollama_api_key):
        self.client = OpenAI(base_url=base_url, api_key=api_key)

    def chat(
        self,
        model: str,
        messages: list[dict],
        temperature: float = MODEL_CONFIG.default_temperature,
        max_tokens: int = MODEL_CONFIG.default_max_tokens,
    ) -> str:
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()

    def healthcheck(self, model: str) -> LLMHealth:
        try:
            resposta = self.chat(
                model=model,
                messages=[{"role": "user", "content": "Responda apenas: ok"}],
                temperature=0.0,
                max_tokens=8,
            )
        except Exception as exc:
            return LLMHealth(False, f"Falha ao chamar {model}: {exc}")
        return LLMHealth(True, f"{model} respondeu: {resposta}")


class StaticClient:
    """Cliente simples para testes automatizados."""

    def __init__(self, resposta: str = "Resposta simulada da Aya."):
        self.resposta = resposta
        self.calls: list[dict] = []

    def chat(
        self,
        model: str,
        messages: list[dict],
        temperature: float = MODEL_CONFIG.default_temperature,
        max_tokens: int = MODEL_CONFIG.default_max_tokens,
    ) -> str:
        self.calls.append({
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })
        return self.resposta
