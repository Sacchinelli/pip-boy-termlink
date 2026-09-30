"""Concordância de número: "1 palavra", "3 palavras", "0 palavras".

A regra é de uma linha, e era escrita à mão em cada tela — quatro cópias
da mesma função (no caderno, no progresso, na revisão e na tela inicial) e
outras tantas expressões soltas na janela, no histórico e na sessão. Cada
cópia é mais um lugar para um "1 palavras" escapar numa mudança de texto.
Em português, zero concorda com o plural.
"""

from __future__ import annotations


def conforme(quantidade: int, singular: str, plural: str) -> str:
    """Só a palavra, concordando com a quantidade: "fala" ou "falas"."""
    return singular if quantidade == 1 else plural


def contagem(quantidade: int, singular: str, plural: str) -> str:
    """A quantidade e a palavra que concorda com ela: "3 palavras"."""
    return f"{quantidade} {conforme(quantidade, singular, plural)}"
