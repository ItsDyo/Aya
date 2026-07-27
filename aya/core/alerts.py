from __future__ import annotations

import logging
from dataclasses import dataclass


logger = logging.getLogger("aya.alerts")


@dataclass(frozen=True)
class Alert:
    """Alerta imutavel sobre algo que merece atencao."""

    kind: str
    title: str
    detail: str
    action: str
    priority: int


class AlertService:
    """Coleta alertas sob demanda, somente leitura e sem background."""

    PRIORITIES = {
        "critico": 1,
        "revisao": 2,
        "memoria": 3,
        "curadoria": 4,
        "meta": 5,
        "sugestao": 6,
    }

    def __init__(self, db, aya_dev=None, curation=None):
        self.db = db
        self.aya_dev = aya_dev
        self.curation = curation

    def collect(self) -> list[Alert]:
        alerts: list[Alert] = []
        alerts.extend(self._check_revisoes())
        alerts.extend(self._check_conflitos_memoria())
        alerts.extend(self._check_metas())
        alerts.extend(self._check_curadoria())
        alerts.extend(self._check_aya_dev())
        return sorted(alerts, key=lambda item: (item.priority, item.kind, item.title))

    def _has_connection(self) -> bool:
        return getattr(self.db, "connection", None) is not None

    def _check_revisoes(self) -> list[Alert]:
        alerts: list[Alert] = []
        try:
            if hasattr(self.db, "buscar_revisoes_pendentes"):
                count = len(self.db.buscar_revisoes_pendentes())
            elif hasattr(self.db, "contar_exercicios_pendentes"):
                count = self.db.contar_exercicios_pendentes()
            elif self._has_connection():
                cursor = self.db.connection.execute(
                    "SELECT COUNT(*) FROM exercicios WHERE revisar_em IS NOT NULL AND revisar_em <= datetime('now')"
                )
                count = cursor.fetchone()[0]
            else:
                return alerts

            if count > 0:
                alerts.append(
                    Alert(
                        kind="revisao",
                        title="Revisoes pendentes",
                        detail=f"{count} exercicio(s) vencido(s) para revisar.",
                        action="/revisoes",
                        priority=self.PRIORITIES["revisao"],
                    )
                )
        except Exception:
            logger.exception("Erro ao verificar revisoes")
        return alerts

    def _check_conflitos_memoria(self) -> list[Alert]:
        alerts: list[Alert] = []
        try:
            if hasattr(self.db, "listar_conflitos_memoria"):
                count = len(self.db.listar_conflitos_memoria())
            elif hasattr(self.db, "contar_conflitos_memoria"):
                count = self.db.contar_conflitos_memoria()
            elif self._has_connection():
                cursor = self.db.connection.execute(
                    "SELECT COUNT(*) FROM conflitos_memoria WHERE status = 'pendente'"
                )
                count = cursor.fetchone()[0]
            else:
                return alerts

            if count > 0:
                alerts.append(
                    Alert(
                        kind="memoria",
                        title="Conflitos de memoria",
                        detail=f"{count} conflito(s) de memoria pendente(s).",
                        action="/conflitos",
                        priority=self.PRIORITIES["memoria"],
                    )
                )
        except Exception:
            logger.exception("Erro ao verificar conflitos de memoria")
        return alerts

    def _check_metas(self) -> list[Alert]:
        alerts: list[Alert] = []
        try:
            if hasattr(self.db, "buscar_metas_ativas"):
                count = len(self.db.buscar_metas_ativas())
            elif self._has_connection():
                cursor = self.db.connection.execute("SELECT COUNT(*) FROM metas WHERE concluida = 0")
                count = cursor.fetchone()[0]
            else:
                return alerts

            if count > 0:
                alerts.append(
                    Alert(
                        kind="meta",
                        title="Metas ativas",
                        detail=f"{count} meta(s) ativa(s).",
                        action="/metas",
                        priority=self.PRIORITIES["meta"],
                    )
                )
        except Exception:
            logger.exception("Erro ao verificar metas")
        return alerts

    def _check_curadoria(self) -> list[Alert]:
        alerts: list[Alert] = []
        try:
            count = 0
            if hasattr(self.db, "contar_aprendizados_pendentes"):
                count += self.db.contar_aprendizados_pendentes()

            if self.curation and hasattr(self.curation, "resumo_higiene"):
                resumo = self.curation.resumo_higiene()
                count += int(resumo.get("fracas", 0) or 0)
            elif hasattr(self.db, "buscar_memorias_para_revisao"):
                count += len(self.db.buscar_memorias_para_revisao())

            if count > 0:
                alerts.append(
                    Alert(
                        kind="curadoria",
                        title="Curadoria pendente",
                        detail=f"{count} item(s) aguardando curadoria.",
                        action="/curadoria",
                        priority=self.PRIORITIES["curadoria"],
                    )
                )
        except Exception:
            logger.exception("Erro ao verificar curadoria")
        return alerts

    def _check_aya_dev(self) -> list[Alert]:
        alerts: list[Alert] = []
        try:
            if self.aya_dev is None or not hasattr(self.aya_dev, "proposals"):
                return alerts

            proposals = list(self.aya_dev.proposals.values())
            pending = [
                item
                for item in proposals
                if item.state in {"AGUARDANDO_APROVACAO", "AGUARDANDO_APROVACAO_REVERSAO"}
            ]
            critical = [
                item
                for item in proposals
                if item.state in {"REVERSAO_PARCIAL", "INTEGRACAO_BLOQUEADA", "REVERSAO_FALHOU"}
            ]

            if critical:
                alerts.append(
                    Alert(
                        kind="critico",
                        title="Aya Dev - problemas criticos",
                        detail=f"{len(critical)} proposta(s) com problema critico.",
                        action="/aya-dev status",
                        priority=self.PRIORITIES["critico"],
                    )
                )

            if pending:
                alerts.append(
                    Alert(
                        kind="sugestao",
                        title="Aya Dev - propostas pendentes",
                        detail=f"{len(pending)} proposta(s) aguardando aprovacao.",
                        action="/aya-dev propostas",
                        priority=self.PRIORITIES["sugestao"],
                    )
                )
        except Exception:
            logger.exception("Erro ao verificar Aya Dev")
        return alerts


def formatar_alertas(alerts: list[Alert]) -> str:
    if not alerts:
        return "Tudo em ordem! Nenhum alerta no momento."

    lines = ["Alertas da Aya", ""]
    for alert in alerts:
        lines.append(alert.title)
        lines.append(f"  -> {alert.detail}")
        lines.append(f"  Acao sugerida: {alert.action}")
        lines.append("")

    suggestions = {
        "critico": "Prioridade maxima: revise os problemas criticos do Aya Dev primeiro.",
        "revisao": "Sugestao: comece pelas revisoes vencidas para manter o aprendizado.",
        "memoria": "Sugestao: resolva os conflitos de memoria para manter consistencia.",
        "curadoria": "Sugestao: revise os itens pendentes de curadoria.",
        "meta": "Sugestao: escolha uma meta para focar hoje.",
        "sugestao": "Continue o bom trabalho!",
    }
    lines.append(suggestions.get(alerts[0].kind, "Verifique os itens acima."))
    return "\n".join(lines)
