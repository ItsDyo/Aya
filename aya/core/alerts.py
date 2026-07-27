from __future__ import annotations

import logging
from dataclasses import dataclass


logger = logging.getLogger("aya.alerts")

ALERT_CATEGORIES = frozenset({"aya-dev", "critico", "curadoria", "memoria", "meta", "revisao"})


@dataclass(frozen=True)
class Alert:
    """Alerta imutavel sobre algo que merece atencao."""

    kind: str
    title: str
    detail: str
    action: str
    priority: int
    items: tuple[dict[str, str], ...] = ()


class AlertService:
    """Coleta alertas sob demanda, somente leitura e sem background."""

    DETAIL_LIMIT = 10

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

    def collect(self, detailed: bool = False, category: str | None = None) -> list[Alert]:
        alerts: list[Alert] = []
        normalized = self.normalize_category(category)
        collectors = {
            "revisao": self._check_revisoes,
            "memoria": self._check_conflitos_memoria,
            "meta": self._check_metas,
            "curadoria": self._check_curadoria,
            "aya-dev": self._check_aya_dev,
        }

        if normalized == "":
            return []
        if normalized == "critico":
            alerts.extend(item for item in self._check_aya_dev(detailed) if item.kind == "critico")
        elif normalized:
            collector = collectors.get(normalized)
            if collector:
                alerts.extend(collector(detailed))
        else:
            alerts.extend(self._check_revisoes(detailed))
            alerts.extend(self._check_conflitos_memoria(detailed))
            alerts.extend(self._check_metas(detailed))
            alerts.extend(self._check_curadoria(detailed))
            alerts.extend(self._check_aya_dev(detailed))
        return sorted(alerts, key=lambda item: (item.priority, item.kind, item.title))

    @staticmethod
    def normalize_category(category: str | None) -> str | None:
        normalized = (category or "").strip().lower()
        if not normalized:
            return None
        return normalized if normalized in ALERT_CATEGORIES else ""

    def _has_connection(self) -> bool:
        return getattr(self.db, "connection", None) is not None

    @staticmethod
    def _row_value(row, key: str, default: str = "") -> str:
        try:
            if hasattr(row, "keys") and key in row.keys():
                value = row[key]
            elif isinstance(row, dict):
                value = row.get(key, default)
            else:
                value = default
        except (KeyError, IndexError, TypeError):
            value = default
        return AlertService._safe_text(value, default=default)

    @staticmethod
    def _safe_text(value, *, default: str = "", limit: int = 80) -> str:
        text = str(value if value not in (None, "") else default).replace("\r", " ").replace("\n", " ")
        text = " ".join(text.split())
        if len(text) <= limit:
            return text
        return f"{text[: max(0, limit - 3)]}..."

    def _check_revisoes(self, detailed: bool = False) -> list[Alert]:
        alerts: list[Alert] = []
        try:
            items: tuple[dict[str, str], ...] = ()
            if hasattr(self.db, "buscar_revisoes_pendentes"):
                revisoes = list(self.db.buscar_revisoes_pendentes())
                count = len(revisoes)
                if detailed:
                    items = tuple(
                        {
                            "id": self._row_value(item, "id", "?"),
                            "topico": self._row_value(item, "topico", "sem topico"),
                        }
                        for item in revisoes[: self.DETAIL_LIMIT]
                    )
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
                        items=items,
                    )
                )
        except Exception:
            logger.exception("Erro ao verificar revisoes")
        return alerts

    def _check_conflitos_memoria(self, detailed: bool = False) -> list[Alert]:
        alerts: list[Alert] = []
        try:
            items: tuple[dict[str, str], ...] = ()
            if hasattr(self.db, "listar_conflitos_memoria"):
                conflitos = list(self.db.listar_conflitos_memoria())
                count = len(conflitos)
                if detailed:
                    items = tuple(
                        {
                            "id": self._row_value(item, "id", "?"),
                            "memoria_id": self._row_value(item, "memoria_id", "?"),
                            "chave": self._row_value(item, "chave", "sem chave"),
                        }
                        for item in conflitos[: self.DETAIL_LIMIT]
                    )
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
                        items=items,
                    )
                )
        except Exception:
            logger.exception("Erro ao verificar conflitos de memoria")
        return alerts

    def _check_metas(self, detailed: bool = False) -> list[Alert]:
        alerts: list[Alert] = []
        try:
            items: tuple[dict[str, str], ...] = ()
            if hasattr(self.db, "buscar_metas_ativas"):
                metas = list(self.db.buscar_metas_ativas())
                count = len(metas)
                if detailed:
                    items = tuple(
                        {
                            "id": self._row_value(item, "id", "?"),
                            "tipo": self._row_value(item, "tipo", "geral"),
                            "descricao": self._row_value(item, "descricao", "sem descricao"),
                        }
                        for item in metas[: self.DETAIL_LIMIT]
                    )
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
                        items=items,
                    )
                )
        except Exception:
            logger.exception("Erro ao verificar metas")
        return alerts

    def _check_curadoria(self, detailed: bool = False) -> list[Alert]:
        alerts: list[Alert] = []
        try:
            aprendizados = 0
            fracas = 0
            if hasattr(self.db, "contar_aprendizados_pendentes"):
                aprendizados = self.db.contar_aprendizados_pendentes()

            if self.curation and hasattr(self.curation, "resumo_higiene"):
                resumo = self.curation.resumo_higiene()
                fracas = int(resumo.get("fracas", 0) or 0)
            elif hasattr(self.db, "buscar_memorias_para_revisao"):
                fracas = len(self.db.buscar_memorias_para_revisao())

            count = aprendizados + fracas

            if count > 0:
                items = ()
                if detailed:
                    items = tuple(
                        item
                        for item in (
                            {"tipo": "aprendizados_pendentes", "quantidade": str(aprendizados)},
                            {"tipo": "memorias_fracas", "quantidade": str(fracas)},
                        )
                        if item["quantidade"] != "0"
                    )
                alerts.append(
                    Alert(
                        kind="curadoria",
                        title="Curadoria pendente",
                        detail=f"{count} item(s) aguardando curadoria.",
                        action="/curadoria",
                        priority=self.PRIORITIES["curadoria"],
                        items=items,
                    )
                )
        except Exception:
            logger.exception("Erro ao verificar curadoria")
        return alerts

    def _check_aya_dev(self, detailed: bool = False) -> list[Alert]:
        alerts: list[Alert] = []
        try:
            if self.aya_dev is None or not hasattr(self.aya_dev, "proposals"):
                return alerts

            proposals = list(self.aya_dev.proposals.items())
            pending = [
                (proposal_id, item)
                for proposal_id, item in proposals
                if item.state in {"AGUARDANDO_APROVACAO", "AGUARDANDO_APROVACAO_REVERSAO"}
            ]
            critical = [
                (proposal_id, item)
                for proposal_id, item in proposals
                if item.state in {"REVERSAO_PARCIAL", "INTEGRACAO_BLOQUEADA", "REVERSAO_FALHOU"}
            ]

            if critical:
                items = ()
                if detailed:
                    items = tuple(
                        {"id": self._safe_text(proposal_id), "estado": self._safe_text(item.state)}
                        for proposal_id, item in critical[: self.DETAIL_LIMIT]
                    )
                alerts.append(
                    Alert(
                        kind="critico",
                        title="Aya Dev - problemas criticos",
                        detail=f"{len(critical)} proposta(s) com problema critico.",
                        action="/aya-dev status",
                        priority=self.PRIORITIES["critico"],
                        items=items,
                    )
                )

            if pending:
                items = ()
                if detailed:
                    items = tuple(
                        {"id": self._safe_text(proposal_id), "estado": self._safe_text(item.state)}
                        for proposal_id, item in pending[: self.DETAIL_LIMIT]
                    )
                alerts.append(
                    Alert(
                        kind="sugestao",
                        title="Aya Dev - propostas pendentes",
                        detail=f"{len(pending)} proposta(s) aguardando aprovacao.",
                        action="/aya-dev propostas",
                        priority=self.PRIORITIES["sugestao"],
                        items=items,
                    )
                )
        except Exception:
            logger.exception("Erro ao verificar Aya Dev")
        return alerts


def formatar_alertas(alerts: list[Alert], detailed: bool = False) -> str:
    if not alerts:
        return "Tudo em ordem! Nenhum alerta no momento."

    if detailed:
        return _formatar_alertas_detalhados(alerts)

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


def _formatar_alertas_detalhados(alerts: list[Alert]) -> str:
    lines = ["Alertas da Aya - detalhes", ""]
    for alert in alerts:
        lines.append("=" * 40)
        lines.append(alert.title)
        lines.append(f"  -> {alert.detail}")
        lines.append(f"  Acao sugerida: {alert.action}")
        if alert.items:
            lines.append("  Itens:")
            for item in alert.items:
                parts = []
                for key, value in item.items():
                    if key == "id":
                        parts.append(f"#{value}")
                    elif key == "quantidade":
                        parts.append(f"{value} item(s)")
                    else:
                        parts.append(f"{key}={value}")
                lines.append(f"    - {', '.join(parts)}")
        else:
            lines.append("  (sem detalhes disponiveis)")
        lines.append("")

    lines.append("Use os comandos sugeridos acima para agir sobre cada item.")
    return "\n".join(lines)
