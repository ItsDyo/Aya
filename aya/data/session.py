"""
core/session.py
===============
Representa uma sessão de estudo ativa na memória do programa.

CONCEITOS QUE VOCÊ VAI APRENDER AQUI:
  - @dataclass: decorator que gera __init__ e __repr__ automaticamente
  - @property: método que se parece com atributo; calculado na hora
  - field(default_factory=...): valor padrão que é criado novo a cada instância
  - Optional[int]: tipo que pode ser int ou None (ainda não foi salvo no banco)
  - timedelta: diferença entre dois momentos no tempo

POR QUE UM ARQUIVO SÓ PARA ISSO?
  Esta classe não tem lógica de banco, não fala com a API.
  Ela só guarda o estado de "o que está acontecendo agora".
  Separar aqui segue o SRP: cada arquivo tem um único motivo para mudar.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class StudySession:
    """
    Estado de uma sessão de estudo em andamento.

    @dataclass gera automaticamente:
      __init__(self, materia, duracao_planejada_minutos, ...)
      __repr__(self) → "StudySession(materia='Python', ...)"

    Sem @dataclass você escreveria tudo isso à mão — mais código,
    mais chance de erro, sem benefício.
    """

    materia: str
    duracao_planejada_minutos: int

    # field(default_factory=datetime.now) cria um datetime novo
    # para cada instância. Se usássemos inicio: datetime = datetime.now(),
    # todos os objetos compartilhariam o mesmo momento — bug clássico
    # com valores mutáveis como padrão em Python.
    inicio: datetime = field(default_factory=datetime.now)

    # Optional[int] = int | None — o ID só existe depois de salvar no banco
    sessao_id: Optional[int] = None

    notas: str = ""

    # ── Properties: calculados na hora, não armazenados ──────

    @property
    def duracao_atual_minutos(self) -> int:
        """
        Quantos minutos se passaram desde o início.

        Por que @property e não um método normal?
        - session.duracao_atual_minutos lê como atributo
        - session.duracao_atual_minutos() pareceria estático
        - A property comunica: "este valor muda com o tempo"

        total_seconds() retorna float; int() descarta as frações de segundo.
        """
        delta = datetime.now() - self.inicio
        return int(delta.total_seconds() / 60)

    @property
    def percentual_concluido(self) -> float:
        """Porcentagem do tempo planejado já cumprida (0.0 a 100.0)."""
        if self.duracao_planejada_minutos == 0:
            return 0.0
        pct = (self.duracao_atual_minutos / self.duracao_planejada_minutos) * 100
        return min(100.0, pct)  # nunca passa de 100%

    @property
    def tempo_restante_minutos(self) -> int:
        """Minutos que faltam para atingir a meta. Nunca negativo."""
        restante = self.duracao_planejada_minutos - self.duracao_atual_minutos
        return max(0, restante)

    @property
    def esta_no_prazo(self) -> bool:
        """True enquanto ainda estiver dentro do tempo planejado."""
        return self.duracao_atual_minutos <= self.duracao_planejada_minutos

    def resumo_para_display(self) -> str:
        """
        String curta para exibir no prefixo do terminal.
        Ex: "Python · 23min · 37min restantes"
        """
        return (
            f"{self.materia} · "
            f"{self.duracao_atual_minutos}min decorridos · "
            f"{self.tempo_restante_minutos}min restantes"
        )