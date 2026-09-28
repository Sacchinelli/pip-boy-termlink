"""O nível do caderno: a experiência de quem estuda, contada como num jogo.

Todo jogo da lista mede o avanço de quem joga com um número que só sobe —
o LVL do Pip-Boy, o nível de runas, a reputação nas ruas, a patente do
esquadrão. O caderno sempre teve o que é preciso para o mesmo número: as
palavras guardadas, as revisões certas e as palavras dominadas. Aqui ele é
contado, sem banco novo e sem nada gravado — é uma LEITURA do caderno, e por
isso nunca fica fora de sincronia com ele.

A regra é curta o bastante para caber numa dica de ferramenta, e é o que a
tela mostra a quem pergunta: 10 XP por palavra no caderno, 5 por revisão
certa, 25 por palavra dominada. Dominar pesa mais porque é o que custa mais
— e é o que o jogador quer de fato.

A curva é a triangular dos RPGs de mesa: cada nível pede 100 XP a mais que
o anterior (100, 200, 300…), então o nível 2 chega com dez palavras e o 10
com algumas centenas de palavras revisadas. Sobe rápido no começo, quando é
preciso motivo para voltar, e devagar depois, quando o hábito já existe.
"""

from __future__ import annotations

from dataclasses import dataclass

from .vocabulary import Estatisticas

XP_POR_PALAVRA = 10
XP_POR_ACERTO = 5
XP_POR_DOMINADA = 25
XP_POR_DEGRAU = 100

REGRA_DO_XP = (
    f"{XP_POR_PALAVRA} XP por palavra no caderno, {XP_POR_ACERTO} por revisão certa "
    f"e {XP_POR_DOMINADA} por palavra dominada."
)


def xp_do_caderno(estatisticas: Estatisticas) -> int:
    """A experiência acumulada: palavras, revisões certas e palavras dominadas."""
    return (
        XP_POR_PALAVRA * estatisticas.total
        + XP_POR_ACERTO * estatisticas.acertos
        + XP_POR_DOMINADA * estatisticas.dominadas
    )


def xp_para(nivel: int) -> int:
    """O XP acumulado em que o nível começa: 0, 100, 300, 600, 1000…"""
    return XP_POR_DEGRAU * nivel * (nivel - 1) // 2


@dataclass(frozen=True, slots=True)
class Nivel:
    """Onde o XP cai na curva: o nível, e o trecho dele já percorrido."""

    numero: int
    xp: int
    piso: int
    teto: int

    @property
    def fracao(self) -> float:
        """Quanto do caminho até o próximo nível já foi feito, de 0 a 1."""
        return (self.xp - self.piso) / max(1, self.teto - self.piso)

    @property
    def faltam(self) -> int:
        return self.teto - self.xp


def nivel_de(xp: int) -> Nivel:
    """O nível de um total de XP (a partir do 1, que começa no zero)."""
    xp = max(0, xp)
    numero = 1
    while xp_para(numero + 1) <= xp:
        numero += 1
    return Nivel(numero, xp, xp_para(numero), xp_para(numero + 1))
