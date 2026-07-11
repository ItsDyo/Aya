"""
utils/helpers.py
================
Funções auxiliares sem dependência de nenhum módulo do projeto.

CONCEITOS QUE VOCÊ VAI APRENDER AQUI:
  - Funções puras: dado o mesmo input, retornam sempre o mesmo output
  - divmod(): retorna (quociente, resto) em uma só chamada
  - Coerção de tipo: int() e str() convertendo entre tipos
  - Guard clause: checar logo no início e retornar cedo, evitando aninhamento

POR QUE SEPARAR AQUI?
  Funções que não pertencem a nenhuma classe específica ficam aqui.
  Qualquer módulo pode importar sem criar dependências circulares.
  Fácil de testar — inputs simples, outputs previsíveis.
"""

import os
from datetime import datetime


def formatar_duracao(minutos: int) -> str:
    """
    Converte minutos em string legível.

    divmod(90, 60) retorna (1, 30) — quociente e resto de uma vez.
    Evita fazer duas operações separadas: 90 // 60 e 90 % 60.

    Exemplos:
      formatar_duracao(45)  → "45 minutos"
      formatar_duracao(60)  → "1 hora"
      formatar_duracao(90)  → "1h 30min"
      formatar_duracao(120) → "2 horas"
    """
    if minutos < 60:
        return f"{minutos} minuto{'s' if minutos != 1 else ''}"

    horas, resto = divmod(minutos, 60)
    label_hora = f"{horas} hora{'s' if horas != 1 else ''}"

    if resto == 0:
        return label_hora
    return f"{horas}h {resto}min"


def validar_minutos(texto: str) -> int | None:
    """
    Converte texto em inteiro de minutos válido.
    Retorna None se a entrada for inválida — o chamador decide o que fazer.

    Por que retornar None em vez de lançar exceção?
    Erros de digitação são esperados na CLI — não são situações excepcionais.
    None é mais simples de tratar com um if do que um try/except.

    Guard clauses: verificações no início que retornam cedo.
    O "caminho feliz" fica sem aninhamento no final.
    """
    try:
        minutos = int(texto.strip())
    except (ValueError, AttributeError):
        return None  # não é número

    if minutos <= 0:
        return None  # não faz sentido estudar 0 minutos

    if minutos > 480:
        return None  # mais de 8 horas — provavelmente erro de digitação

    return minutos


def saudacao_por_horario() -> str:
    """
    Retorna saudação adequada ao horário atual.
    Pequeno detalhe que torna a experiência mais humana.
    """
    hora = datetime.now().hour
    if hora < 12:
        return "Bom dia"
    if hora < 18:
        return "Boa tarde"
    return "Boa noite"


def limpar_terminal():
    """
    Limpa a tela do terminal.
    os.name == 'nt' significa Windows ('nt' = Windows NT).
    Qualquer outro valor é Unix/Linux/Mac.
    """
    os.system("cls" if os.name == "nt" else "clear")


def barra(char: str = "─", largura: int = 48) -> str:
    """Linha decorativa para separar seções no terminal."""
    return char * largura


def formatar_data_curta(iso_string: str) -> str:
    """
    Converte timestamp ISO (2024-03-15T20:30:00) em data legível (15/03/2024).
    Útil para exibir datas das sessões no /status.
    """
    try:
        dt = datetime.fromisoformat(iso_string)
        return dt.strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return "—"