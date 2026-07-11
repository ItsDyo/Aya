from __future__ import annotations

import json
from pathlib import Path

from aya.data.database import Database
from aya.paths import FINE_TUNING_DATASET_PATH, ensure_runtime_dirs


class FineTuningExporter:
    """Exporta dados locais da Aya em JSONL para fine-tuning futuro."""

    def __init__(self, db: Database, system_prompt: str):
        self.db = db
        self.system_prompt = system_prompt

    def exportar(self, caminho: str | None = None) -> str:
        exemplos = [
            *self._exemplos_de_conversas(),
            *self._exemplos_de_conhecimento(),
            *self._exemplos_de_memorias(),
        ]

        if not exemplos:
            return "Ainda não há dados suficientes para exportar fine-tuning."

        ensure_runtime_dirs()
        destino = FINE_TUNING_DATASET_PATH if caminho is None else Path(caminho)
        with destino.open("w", encoding="utf-8") as f:
            for exemplo in exemplos:
                f.write(json.dumps(exemplo, ensure_ascii=False) + "\n")
        return f"Dataset exportado em {destino} com {len(exemplos)} exemplo(s)."

    def _exemplos_de_conversas(self) -> list[dict]:
        exemplos = []
        conversas = self.db.exportar_conversas(limite=200)
        for atual, proxima in zip(conversas, conversas[1:]):
            if atual["role"] != "user" or proxima["role"] != "assistant":
                continue
            if "Tive um problema" in proxima["content"]:
                continue
            exemplos.append({
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    atual,
                    proxima,
                ]
            })
        return exemplos

    def _exemplos_de_conhecimento(self) -> list[dict]:
        exemplos = []
        for item in self.db.buscar_conhecimento(limite=200):
            exemplos.append({
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": f"Explique este tópico salvo: {item['topico']}"},
                    {"role": "assistant", "content": item["conteudo"]},
                ]
            })
        return exemplos

    def _exemplos_de_memorias(self) -> list[dict]:
        exemplos = []
        for memoria in self.db.buscar_memorias(limite=200):
            exemplos.append({
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": f"O que você sabe sobre {memoria['chave']}?"},
                    {"role": "assistant", "content": f"Tenho esta memória local: {memoria['valor']}"},
                ]
            })
        return exemplos
