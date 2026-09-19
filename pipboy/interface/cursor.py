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

from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QHoverEvent, QMouseEvent
from PySide6.QtWidgets import QAbstractButton, QApplication, QComboBox, QWidget

from .componentes import Botao

_MOVIMENTOS = (QEvent.Type.MouseMove, QEvent.Type.HoverMove)


def clicavel(widget: QWidget) -> bool:
    """O widget sob o cursor responde a clique? É o que faz o anel crescer."""
    return (
        isinstance(widget, (QAbstractButton, QComboBox))
        or widget.cursor().shape() == Qt.CursorShape.PointingHandCursor
    )


class CampoMagnetico:
    """Os botões magnéticos de uma janela, puxados pelo cursor dela.

    A janela sabe onde o cursor está; cada botão sabe como reagir. Isto só faz
    a ponte, levando o ponto para as coordenadas de cada botão.
    """

    def __init__(self, janela: QWidget) -> None:
        self._janela = janela
        self._botoes: list[Botao] | None = None

    @property
    def botoes(self) -> list[Botao]:
        # Procurados na primeira vez, e não na construção: a janela ainda está
        # sendo montada quando o campo nasce. Só os desta JANELA: o caderno e a
        # revisão são filhos da janela principal, e a busca recursiva trazia os
        # botões deles junto — puxados por um cursor de outra janela, com
        # coordenadas que não significam nada lá.
        if self._botoes is None:
            self._botoes = [
                b for b in self._janela.findChildren(Botao)
                if b.magnetico and b.window() is self._janela
            ]
        return self._botoes

    def mover(self, ponto: QPointF | None, _clicavel: bool = False) -> None:
        for botao in self.botoes:
            botao.atrair(None if ponto is None else botao.mapFrom(self._janela, ponto))


class RastreadorDeCursor(QObject):
    """Avisa ``ao_mover`` a cada movimento sobre a janela, e ``None`` ao sair.

    O filtro recebe TODO evento da aplicação — pintura, relógio, teclado —, e
    por isso a primeira coisa que ele olha é o tipo: tudo que não é movimento
    nem saída volta na hora.
    """

    def __init__(
        self,
        janela: QWidget,
        ao_mover: Callable[[QPointF | None, bool], None],
        ao_clicar: Callable[[QPointF], None] | None = None,
    ) -> None:
        super().__init__(janela)
        self._janela = janela
        self._ao_mover = ao_mover
        self._ao_clicar = ao_clicar
        # O Qt repassa um clique não aceito a cada ancestral do widget clicado, e
        # o filtro da aplicação o vê em cada um: um clique virava quatro ondas.
        # Instante e posição na tela identificam o MESMO clique entre as cópias.
        self._ultimo_clique: tuple[int, float, float] | None = None
        # O mesmo movimento chega mais de uma vez: como MouseMove ao widget sob
        # o cursor e como HoverMove a ele e a cada ancestral que o acompanha.
        # Cada aviso refaz a luz e o ímã de todos os botões; repetido, é só custo.
        self._ultimo_movimento: tuple[float, float, bool] | None = None
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
                ponto = alvo.mapTo(self._janela, evento.position())
                sobre_clicavel = clicavel(alvo)
                marca = (ponto.x(), ponto.y(), sobre_clicavel)
                if marca != self._ultimo_movimento:
                    self._ultimo_movimento = marca
                    self._ao_mover(ponto, sobre_clicavel)
        elif tipo == QEvent.Type.MouseButtonPress:
            if (
                self._ao_clicar is not None
                and isinstance(alvo, QWidget)
                and isinstance(evento, QMouseEvent)
                and alvo.window() is self._janela
            ):
                global_ = evento.globalPosition()
                chave = (evento.timestamp(), global_.x(), global_.y())
                if chave != self._ultimo_clique:
                    self._ultimo_clique = chave
                    self._ao_clicar(alvo.mapTo(self._janela, evento.position()))
        elif tipo == QEvent.Type.Leave and alvo is self._janela:
            self._ultimo_movimento = None
            self._ao_mover(None, False)
        return False
