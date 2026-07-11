from __future__ import annotations

from datetime import datetime

from aya.config import RUNTIME_CONFIG
from aya.data.database import Database


class MemoryManager:
    """Monta o contexto dinamico usado pela Aya antes de chamar os modelos."""

    def __init__(self, db: Database):
        self.db = db

    def construir_contexto_completo(self, sessao_ativa=None) -> str:
        agora = datetime.now()
        secoes = [
            f"[Contexto atual - {agora.strftime('%A, %d/%m/%Y as %H:%M')}]",
            self._secao_perfil(),
            self._secao_memorias(),
            self._secao_semana(),
            self._secao_hoje(),
            self._secao_metas(),
            self._secao_dificuldades(),
            self._secao_eventos(),
            self._secao_sessao_ativa(sessao_ativa),
        ]
        return "\n\n".join(filter(None, secoes))

    def _secao_perfil(self) -> str | None:
        perfil = self.db.carregar_perfil()
        if not perfil:
            return None

        labels = {
            "nome": "Nome",
            "horario_produtivo": "Horario mais produtivo",
            "linguagem_favorita": "Linguagem favorita",
            "metodo_preferido": "Metodo de estudo preferido",
            "maior_dificuldade": "Maior dificuldade relatada",
            "dias_consecutivos": "Dias consecutivos estudando",
        }

        linhas = ["Perfil do usuario:"]
        for chave, valor in perfil.items():
            linhas.append(f"  - {labels.get(chave, chave)}: {valor}")
        return "\n".join(linhas)

    def _secao_memorias(self) -> str | None:
        memorias = self.db.buscar_memorias(limite=RUNTIME_CONFIG.context_memory_limit)
        if not memorias:
            return None

        self.db.registrar_uso_memorias([item["id"] for item in memorias])
        linhas = ["Memorias persistentes relevantes:"]
        for item in memorias:
            dominio = item["dominio"] if "dominio" in item.keys() else "geral"
            linhas.append(
                f"  - [{dominio}/{item['tipo']}, confianca {item['confianca']:.2f}] "
                f"{item['chave']}: {item['valor']}"
            )
        return "\n".join(linhas)

    def _secao_semana(self) -> str:
        resumo = self.db.buscar_resumo_semanal()
        if resumo["total_sessoes"] == 0:
            return "Ultimos 7 dias: nenhuma sessao registrada ainda."

        horas, minutos = divmod(resumo["total_minutos"], 60)
        tempo = f"{horas}h {minutos}min" if horas else f"{minutos}min"
        return (
            f"Ultimos 7 dias: {resumo['total_sessoes']} sessao(oes) concluida(s), "
            f"{tempo} estudados, {resumo['materias_distintas']} materia(s)."
        )

    def _secao_hoje(self) -> str:
        sessoes = self.db.buscar_sessoes_hoje()
        if not sessoes:
            return "Hoje: nenhuma sessao iniciada ainda."

        materias = [s["materia"] for s in sessoes]
        minutos_reais = sum((s["duracao_minutos"] or 0) for s in sessoes if s["concluida"])
        texto = f"Hoje estudou: {', '.join(materias)}."
        if minutos_reais:
            horas, minutos = divmod(minutos_reais, 60)
            tempo = f"{horas}h {minutos}min" if horas else f"{minutos}min"
            texto += f" Total: {tempo}."
        return texto

    def _secao_metas(self) -> str | None:
        metas = self.db.buscar_metas_ativas()
        if not metas:
            return None
        linhas = ["Metas ativas:"]
        for meta in metas[:5]:
            linhas.append(f"  - [{meta['tipo']}] {meta['descricao']}")
        return "\n".join(linhas)

    def _secao_dificuldades(self) -> str | None:
        dificuldades = self.db.buscar_dificuldades_abertas()
        if not dificuldades:
            return None
        linhas = ["Dificuldades pendentes:"]
        for item in dificuldades:
            linha = f"  - {item['materia']}: {item['topico']}"
            if item["descricao"]:
                linha += f" - {item['descricao']}"
            linhas.append(linha)
        return "\n".join(linhas)

    def _secao_eventos(self) -> str | None:
        eventos = self.db.buscar_eventos_aprendizado(limite=RUNTIME_CONFIG.context_event_limit)
        if not eventos:
            return None
        linhas = ["Eventos recentes de aprendizado:"]
        for evento in eventos:
            linhas.append(f"  - [{evento['tipo']}] {evento['descricao']}")
        return "\n".join(linhas)

    def _secao_sessao_ativa(self, sessao) -> str | None:
        if not sessao:
            return None
        return (
            f"SESSAO EM ANDAMENTO: {sessao.materia}, "
            f"{sessao.duracao_atual_minutos}min decorridos, "
            f"meta de {sessao.duracao_planejada_minutos}min, "
            f"{sessao.tempo_restante_minutos}min restantes."
        )
