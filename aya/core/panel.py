from __future__ import annotations

from collections.abc import Callable, Iterable


class PanelBuilder:
    """Monta a visao geral da Aya sem depender do LLM."""

    def build(
        self,
        *,
        resumo: dict,
        sessao_ativa,
        total_conversas: int,
        total_conhecimentos: int,
        total_memorias: int,
        metas: Iterable,
        revisoes: Iterable,
        dificuldades: Iterable,
        memorias_revisao: Iterable,
        aprendizados: Iterable,
        eventos: Iterable,
        higiene: dict | None = None,
    ) -> str:
        metas = list(metas)
        revisoes = list(revisoes)
        dificuldades = list(dificuldades)
        memorias_revisao = list(memorias_revisao)
        aprendizados = list(aprendizados)
        eventos = list(eventos)
        higiene = higiene or {}

        linhas = [
            "Painel da Aya:",
            "",
            "Agora:",
            f"- Sessao ativa: {sessao_ativa.resumo_para_display() if sessao_ativa else 'nenhuma'}",
            f"- Conversas salvas: {total_conversas}",
            f"- Conhecimentos: {total_conhecimentos}",
            f"- Memorias ativas: {total_memorias}",
            f"- Saude da memoria: {self._format_higiene(higiene)}",
            f"- Ultimos 7 dias: {resumo['total_sessoes']} sessao(oes), {resumo['total_minutos']} minuto(s)",
            "",
        ]

        linhas.extend(self._lista("Metas ativas", metas, lambda row: f"#{row['id']} [{row['tipo']}] {row['descricao']}"))
        linhas.extend(self._lista("Revisoes pendentes", revisoes, lambda row: f"#{row['id']} {row['topico']}"))
        linhas.extend(self._lista("Dificuldades abertas", dificuldades, lambda row: f"{row['materia']}: {row['topico']}"))
        linhas.extend(self._lista(
            "Curadoria",
            memorias_revisao,
            lambda row: (
                f"Memoria #{row['id']} [{self._dominio(row)}/{row['tipo']}] "
                f"{row['chave']} (confianca {row['confianca']:.2f})"
            ),
        ))
        linhas.extend(self._lista(
            "Aprendizados pendentes",
            aprendizados,
            lambda row: f"#{row['id']} [{row['categoria']}/{row['tipo'] or 'geral'}] {row['chave']}",
        ))
        linhas.extend(self._lista("Eventos recentes", eventos, lambda row: f"[{row['tipo']}] {row['descricao']}"))

        linhas.append("Proximos passos:")
        linhas.extend(f"- {passo}" for passo in self._proximos_passos(revisoes, aprendizados, memorias_revisao, dificuldades, metas, higiene))
        return "\n".join(linhas).strip()

    def _lista(self, titulo: str, rows: Iterable, formatter: Callable) -> list[str]:
        rows = list(rows)
        linhas = [f"{titulo}:"]
        if not rows:
            linhas.append("- nada pendente")
            linhas.append("")
            return linhas
        for row in rows:
            texto = formatter(row).replace("\n", " ").strip()
            if len(texto) > 160:
                texto = texto[:157] + "..."
            linhas.append(f"- {texto}")
        linhas.append("")
        return linhas

    def _proximos_passos(self, revisoes, aprendizados, memorias_revisao, dificuldades, metas, higiene=None) -> list[str]:
        if revisoes:
            return ["Fazer uma revisao pendente antes de iniciar conteudo novo."]
        if higiene and higiene.get("precisa_revisao"):
            return ["Rodar `/higiene` e revisar memorias duplicadas, conflitantes ou temporarias."]
        if aprendizados or memorias_revisao:
            return ["Abrir a curadoria e limpar memorias/aprendizados pendentes."]
        if dificuldades:
            return ["Pedir um exercicio focado na dificuldade aberta mais importante."]
        if not metas:
            return ["Criar uma meta pequena para orientar a proxima sessao."]
        return ["Continuar estudando e salvar o que for importante."]

    def _format_higiene(self, higiene: dict) -> str:
        if not higiene or not higiene.get("total"):
            return "sem memorias ativas"
        problemas = higiene.get("duplicatas", 0) + higiene.get("conflitos", 0) + higiene.get("fracas", 0)
        if problemas == 0:
            return f"boa ({higiene.get('score', 100)}/100)"
        return (
            f"revisar ({higiene.get('score', 0)}/100; "
            f"{higiene.get('duplicatas', 0)} dup, "
            f"{higiene.get('conflitos', 0)} conf, "
            f"{higiene.get('fracas', 0)} fracas)"
        )

    def _dominio(self, row) -> str:
        try:
            return row["dominio"] or "geral"
        except (KeyError, IndexError):
            return "geral"
