from __future__ import annotations

from aya.data.database import Database
from aya.data.session import StudySession


class StudyPlanner:
    """Gerencia sessoes de estudo, metas e dificuldades."""

    def __init__(self, db: Database):
        self.db = db

    def iniciar_sessao(self, materia: str, minutos: int, sessao_ativa: StudySession | None) -> tuple[str, StudySession | None]:
        materia = (materia or "").strip()
        if sessao_ativa:
            return f"Já existe uma sessão em andamento: {sessao_ativa.resumo_para_display()}.", sessao_ativa
        if not materia or minutos <= 0:
            return "Use assim: `/estudar Matemática | 25`.", sessao_ativa

        sessao_id = self.db.iniciar_sessao(materia, minutos)
        nova_sessao = StudySession(materia=materia, duracao_planejada_minutos=minutos, sessao_id=sessao_id)
        return f"Sessão iniciada: {materia} por {minutos} minutos.", nova_sessao

    def encerrar_sessao(self, notas: str, sessao_ativa: StudySession | None) -> tuple[str, StudySession | None]:
        if not sessao_ativa:
            return "Não há sessão ativa agora. Use `/estudar matéria | minutos` para começar uma.", None

        sessao = sessao_ativa
        duracao = max(1, sessao.duracao_atual_minutos)
        self.db.concluir_sessao(sessao.sessao_id, duracao, (notas or "").strip())
        return f"Sessão de {sessao.materia} encerrada com {duracao} minuto(s) registrado(s).", None

    def criar_meta(self, descricao: str, tipo: str = "geral") -> str:
        descricao = (descricao or "").strip()
        tipo = (tipo or "geral").strip()
        if not descricao:
            return "Me diga a descrição da meta. Ex: `/meta semanal | estudar Python 3 vezes`."
        meta_id = self.db.criar_meta(descricao, tipo)
        return f"Meta criada com ID {meta_id}: [{tipo}] {descricao}."

    def ver_metas(self) -> str:
        metas = self.db.buscar_metas_ativas()
        if not metas:
            return "Você ainda não tem metas ativas. Quer criar uma com `/meta semanal | ...`?"
        return "\n".join(["Metas ativas:"] + [f"- #{m['id']} [{m['tipo']}] {m['descricao']}" for m in metas])

    def registrar_dificuldade(self, materia: str, topico: str, descricao: str = "") -> str:
        materia = (materia or "").strip()
        topico = (topico or "").strip()
        descricao = (descricao or "").strip()
        if not materia or not topico:
            return "Use assim: `/dificuldade Matemática | Frações | erro ao simplificar`."
        self.db.registrar_dificuldade(materia, topico, descricao)
        return f"Registrei sua dificuldade em {materia}: {topico}."
