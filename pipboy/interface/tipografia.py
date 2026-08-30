"""A rampa tipográfica do programa: uma família por papel, um fator por escolha.

Quarta peça a sair da ``Janela``, e a que menos tinha razão de estar lá: nada
aqui toca num widget. É uma função de três coisas — o degrau da rampa pedido,
o tema em vigor e o fator de tamanho escolhido — para um ``QFont``. Dentro da
classe, exercitar a rampa exigia construir a janela inteira; aqui basta um
tema.

**A duplicação que a extração desfez.** "A primeira família candidata que
existe nesta máquina, com a última como reserva" estava escrita em TRÊS
lugares: aqui, na tela de abertura e no cartão de boas-vindas. É a regra que
o README explica com mais cuidado — a segunda candidata importa tanto quanto a
primeira, porque Garamond, Rockwell e Bookman não acompanham o Windows e temas
que as pediam desabavam calados em Georgia. Uma regra dessas não sobrevive em
triplicata.

**E o fator de tamanho passou a valer no cartão de boas-vindas.** Ele montava
fontes com a rampa crua, ignorando a escolha de tamanho — a mesma falha que o
``_aplicar_fontes`` da janela existe para corrigir, na única tela que aparece
antes de a janela existir. Como o projeto já decidiu que tamanho de texto é
acessibilidade e não gosto, e que por isso vale em toda superfície, esta era
uma superfície faltando.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache

from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics

from .. import design
from ..themes import GameTheme

# Monoespaçadas, da preferida à reserva. O rodapé de consumo é uma coluna de
# números que muda a cada meio segundo: com fonte proporcional, os dígitos
# mudam de largura e o texto inteiro dança.
FONTES_MONO: tuple[str, ...] = ("Cascadia Mono", "Consolas", "Courier New", "Courier")


@lru_cache(maxsize=1)
def _familias_instaladas() -> frozenset[str]:
    """As famílias desta máquina, perguntadas uma vez só.

    Preguiçoso de propósito: o ``QFontDatabase`` exige uma ``QApplication``
    viva, e este módulo é importado antes de haver uma.
    """
    return frozenset(QFontDatabase.families())


def primeira_instalada(candidatas: Sequence[str]) -> str:
    """A primeira candidata que existe aqui; a última serve de reserva.

    A reserva não é detalhe: um tema que peça uma família ausente cai nela em
    silêncio, e é por isso que a última da lista tem de ser uma fonte de
    fábrica que nenhum outro tema use — senão dez ambientes rendem seis
    tipografias numa instalação limpa. Ver ``py diagnostico.py``, que mostra o
    que cada tema conseguiu nesta máquina.
    """
    instaladas = _familias_instaladas()
    return next((f for f in candidatas if f in instaladas), candidatas[-1])


class Tipografia:
    """Ponto de estrangulamento de toda a tipografia de uma superfície.

    O fator de tamanho é aplicado AQUI, e não numa rampa alternativa mantida
    em paralelo: é o que faz "Maior" alcançar a janela, o caderno, o histórico
    e a cápsula sem que nenhum deles precise saber que a escolha existe.
    """

    def __init__(self, tema: GameTheme, *, escala: float = 1.0) -> None:
        self._tema = tema
        self._escala = escala
        self._mono = primeira_instalada(FONTES_MONO)

    def definir_tema(self, tema: GameTheme) -> None:
        self._tema = tema

    def definir_escala(self, fator: float) -> bool:
        """Troca o fator de tamanho. Devolve se ele MUDOU.

        Quem chama usa a resposta para não repintar a interface inteira — e as
        janelas satélites junto — quando a escolha é a que já estava em vigor.
        """
        if fator == self._escala:
            return False
        self._escala = fator
        return True

    @property
    def escala(self) -> float:
        return self._escala

    def fonte(self, papel: str, *, ui: bool = True) -> QFont:
        """Fonte para um degrau da rampa.

        ``ui=True`` usa a família neutra dos controles; ``ui=False`` usa a
        fonte do tema, reservada à marca e à fala do assistente.
        """
        tipo = design.TIPO[papel]
        familia = primeira_instalada(
            self._tema.ui_font_candidates if ui else self._tema.font_candidates
        )
        fonte = QFont(familia, design.escalar(tipo.tamanho, self._escala))
        fonte.setBold(tipo.peso == "bold")
        fonte.setItalic(tipo.estilo == "italic")
        return fonte

    def mono(self, papel: str) -> QFont:
        tipo = design.TIPO[papel]
        return QFont(self._mono, design.escalar(tipo.tamanho, self._escala))

    @property
    def largura_lateral(self) -> int:
        """A coluna de ajustes é uma coluna de TEXTO, e acompanha o tamanho dele."""
        return design.escalar(design.LARGURA_LATERAL, self._escala)

    def marca(self, texto: str) -> QFont:
        """Encolhe o nome do ambiente até ele caber na largura da coluna."""
        fonte = self.fonte("display", ui=False)
        maximo = fonte.pointSize()
        limite = design.escalar(design.CABECALHO_LARGURA_MAX, self._escala)
        for tamanho in range(maximo, maximo - 10, -1):
            fonte.setPointSize(tamanho)
            if QFontMetrics(fonte).horizontalAdvance(texto) <= limite:
                break
        return fonte
