from __future__ import annotations

import json
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

    def chat_structured(
        self,
        model: str,
        messages: list[dict],
        response_schema: dict,
        temperature: float = 0.0,
        max_tokens: int = MODEL_CONFIG.default_max_tokens,
    ) -> dict:
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "aya_patch_manifest",
                    "schema": response_schema,
                    "strict": True,
                },
            },
        )
        return json.loads(response.choices[0].message.content or "")

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

    def chat_structured(
        self,
        model: str,
        messages: list[dict],
        response_schema: dict,
        temperature: float = 0.0,
        max_tokens: int = MODEL_CONFIG.default_max_tokens,
    ) -> dict:
        self.calls.append({
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_schema": response_schema,
        })
        return json.loads(self.resposta)
