from __future__ import annotations

from collections.abc import Iterable


class ContinuityReport:
    """Monta uma visao de continuidade pessoal sem depender do LLM."""

    def build(
        self,
        *,
        status: str,
        metas: Iterable,
        dificuldades: Iterable,
        sessoes: Iterable,
        revisoes: Iterable,
        aprendizados: Iterable,
        diario: Iterable,
        eventos: Iterable,
        memorias: Iterable,
        higiene: dict | None = None,
    ) -> str:
        metas = list(metas)
        dificuldades = list(dificuldades)
        sessoes = list(sessoes)
        revisoes = list(revisoes)
        aprendizados = list(aprendizados)
        diario = list(diario)
        eventos = list(eventos)
        memorias = list(memorias)
        higiene = higiene or {}

        linhas = ["Continuidade da Aya:", ""]
        linhas.extend(self._section("Estado atual", status.splitlines()[1:]))
        linhas.extend(self._section("Saude da memoria", self._format_higiene(higiene)))
        linhas.extend(self._rows("Metas ativas", metas, self._format_meta))
        linhas.extend(self._rows("Dificuldades abertas", dificuldades, self._format_dificuldade))
        linhas.extend(self._rows("Sessoes recentes", sessoes, self._format_sessao))
        linhas.extend(self._rows("Revisoes vencidas", revisoes, self._format_revisao))
        linhas.extend(self._rows("Aprendizados pendentes", aprendizados, self._format_aprendizado))
        linhas.extend(self._rows("Diario recente", diario, self._format_diario))
        linhas.extend(self._rows("Memorias fortes", memorias, self._format_memoria))
        linhas.extend(self._rows("Eventos recentes", eventos, self._format_evento))
        linhas.extend(self._proximos_passos(revisoes, aprendizados, dificuldades, metas, higiene))
        return "\n".join(linhas).strip()

    def _section(self, title: str, lines: list[str]) -> list[str]:
        if not lines:
            return []
        return [f"{title}:"] + [f"- {line.lstrip('- ').strip()}" for line in lines[:8]] + [""]

    def _rows(self, title: str, rows: Iterable, formatter) -> list[str]:
        rows = list(rows)
        if not rows:
            return []
        linhas = [f"{title}:"]
        for row in rows[:6]:
            linhas.append(f"- {formatter(row)}")
        linhas.append("")
        return linhas

    def _proximos_passos(self, revisoes, aprendizados, dificuldades, metas, higiene=None) -> list[str]:
        passos: list[str] = []
        if revisoes:
            passos.append("Fazer uma revisao curta antes de estudar coisa nova.")
        if higiene and higiene.get("precisa_revisao"):
            passos.append("Rodar `/higiene` e limpar memorias duplicadas, conflitantes ou temporarias.")
        if aprendizados:
            passos.append("Revisar aprendizados pendentes para manter a memoria limpa.")
        if dificuldades:
            passos.append("Escolher uma dificuldade aberta e pedir um exercicio direcionado.")
        if not metas:
            passos.append("Criar uma meta pequena para os proximos dias.")
        if not passos:
            passos.append("Continuar uma conversa normal e salvar o que for importante.")
        return ["Proximos passos sugeridos:"] + [f"- {passo}" for passo in passos[:4]]

    def _format_meta(self, row) -> str:
        return f"#{row['id']} [{row['tipo']}] {row['descricao']}"

    def _format_dificuldade(self, row) -> str:
        desc = f" - {row['descricao']}" if row["descricao"] else ""
        return f"{row['materia']}: {row['topico']}{desc}"

    def _format_sessao(self, row) -> str:
        estado = "concluida" if row["concluida"] else "aberta"
        minutos = row["duracao_minutos"] or row["duracao_planejada"] or 0
        return f"{row['materia']} ({estado}, {minutos} min)"

    def _format_revisao(self, row) -> str:
        return f"#{row['id']} {row['topico']} - revisar em {row['revisar_em']}"

    def _format_aprendizado(self, row) -> str:
        valor = self._short(row["valor"], 90)
        return f"#{row['id']} [{row['categoria']}/{row['tipo'] or 'geral'}] {row['chave']} = {valor}"

    def _format_diario(self, row) -> str:
        return f"[{row['tom']}] {self._short(row['resumo'], 120)}"

    def _format_evento(self, row) -> str:
        return f"[{row['tipo']}] {self._short(row['descricao'], 110)}"

    def _format_memoria(self, row) -> str:
        return f"[{self._dominio(row)}/{row['tipo']}] {row['chave']}: {self._short(row['valor'], 100)}"

    def _short(self, value: str, limit: int) -> str:
        value = " ".join((value or "").split())
        if len(value) <= limit:
            return value
        return value[: limit - 3] + "..."

    def _format_higiene(self, higiene: dict) -> list[str]:
        if not higiene or not higiene.get("total"):
            return ["sem memorias ativas"]
        if not higiene.get("precisa_revisao"):
            return [f"boa ({higiene.get('score', 100)}/100)"]
        return [
            f"revisar ({higiene.get('score', 0)}/100)",
            f"duplicatas: {higiene.get('duplicatas', 0)}",
            f"conflitos: {higiene.get('conflitos', 0)}",
            f"fracas/temporarias: {higiene.get('fracas', 0)}",
        ]

    def _dominio(self, row) -> str:
        try:
            return row["dominio"] or "geral"
        except (KeyError, IndexError):
            return "geral"
