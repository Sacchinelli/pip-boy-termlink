"""Onde está o cursor sobre a janela principal, visto de qualquer filho dela.

A atmosfera e o botão magnético precisam do cursor em coordenadas da JANELA,
esteja ele sobre a conversa, a lateral ou um rótulo qualquer. Nenhum widget
recebe isso sozinho: o movimento sem botão vai para o filho que está embaixo
do cursor — e, se esse filho não rastreia o mouse, o Qt o descarta sem subir
para o pai.

Descarta para os WIDGETS, mas não para os filtros da APLICAÇÃO: o Qt passa até
o movimento não rastreado por eles antes de jogá-lo fora. É aqui que o
rastreador escuta, e por isso ele vê o cursor em qualquer ponto da janela sem
ligar o rastreamento de nenhum widget.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QPointF
from PySide6.QtGui import QHoverEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget

_MOVIMENTOS = (QEvent.Type.MouseMove, QEvent.Type.HoverMove)


class RastreadorDeCursor(QObject):
    """Avisa ``ao_mover`` a cada movimento sobre a janela, e ``None`` ao sair.

    O filtro recebe TODO evento da aplicação — pintura, relógio, teclado —, e
    por isso a primeira coisa que ele olha é o tipo: tudo que não é movimento
    nem saída volta na hora.
    """

    def __init__(self, janela: QWidget, ao_mover: Callable[[QPointF | None], None]) -> None:
        super().__init__(janela)
        self._janela = janela
        self._ao_mover = ao_mover
        aplicacao = QApplication.instance()
        if aplicacao is not None:
            aplicacao.installEventFilter(self)

    def eventFilter(self, alvo: QObject, evento: QEvent) -> bool:
        tipo = evento.type()
        if tipo in _MOVIMENTOS:
            if (
                isinstance(alvo, QWidget)
                and isinstance(evento, (QMouseEvent, QHoverEvent))
                and alvo.window() is self._janela
            ):
                self._ao_mover(alvo.mapTo(self._janela, evento.position()))
        elif tipo == QEvent.Type.Leave and alvo is self._janela:
            self._ao_mover(None)
        return False
