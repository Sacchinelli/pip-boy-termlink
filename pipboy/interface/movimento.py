"""As peças de movimento que não são componentes: progresso e entrada.

O ``Botao`` nasceu com a própria receita de animação escrita à mão, e ela
serviu enquanto só ele se mexia. Quando o cartão do caderno passou a reagir a
quem chega, a receita precisaria ser copiada duas vezes no mesmo arquivo — e
copiada sem o detalhe que faltava nela, a duração proporcional. Aqui ela vira
peça, junto da entrada em cascata, que é a outra coisa que mais de uma janela
vai querer.

A regra que atravessa as duas: anima-se o que é PINTURA — cor, luz, opacidade,
deslocamento desenhado. Nada aqui mexe em geometria de layout, porque um
elemento que cresce ou anda de verdade empurra os vizinhos e tira do lugar o
alvo do próximo clique.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from PySide6.QtCore import (
    Property,
    QAbstractAnimation,
    QEasingCurve,
    QObject,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSequentialAnimationGroup,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsEffect, QWidget

from .. import design


class Transicao(QObject):
    """Progresso de 0 a 1 que pode mudar de destino a qualquer momento.

    A diferença para a receita do ``Botao`` está em ``ir``: a duração é
    PROPORCIONAL à distância que falta. Sem isso, passar o cursor de raspão por
    um cartão — acender até 20% e sair — gasta a duração inteira para apagar
    20%, e a luz fica grudada atrás do mouse. É o detalhe que separa fluido de
    atrasado.
    """

    def __init__(
        self,
        dono: QObject,
        duracao: int,
        ao_mudar: Callable[[float], None],
        *,
        reduzir: Callable[[], bool],
        curva: QEasingCurve.Type = QEasingCurve.Type.OutCubic,
    ) -> None:
        super().__init__(dono)
        self.valor = 0.0
        self._duracao = duracao
        self._ao_mudar = ao_mudar
        self._reduzir = reduzir
        self._animacao = QVariantAnimation(self)
        self._animacao.setEasingCurve(curva)
        self._animacao.valueChanged.connect(self._definir)

    def ir(self, destino: float) -> None:
        self._animacao.stop()
        distancia = abs(destino - self.valor)
        if distancia < 0.001:
            return
        if self._reduzir():
            # Movimento reduzido não é "sem resposta": o estado final chega na
            # hora. O que some é o trajeto, não o destino.
            self._definir(destino)
            return
        self._animacao.setDuration(max(1, round(self._duracao * distancia)))
        self._animacao.setStartValue(self.valor)
        self._animacao.setEndValue(destino)
        self._animacao.start()

    def saltar(self, valor: float) -> None:
        """Vai direto ao valor, interrompendo o que estiver em curso."""
        self._animacao.stop()
        self._definir(valor)

    def _definir(self, valor: Any) -> None:
        self.valor = float(valor)
        self._ao_mudar(self.valor)


class EfeitoEntrada(QGraphicsEffect):
    """Desenha o widget subindo e aparecendo, sem mexer na geometria dele.

    Um ``QGraphicsOpacityEffect`` faz só metade: aparece no lugar. Mover o
    widget de verdade brigaria com o layout, que o devolve ao lugar na próxima
    passagem. Aqui o deslocamento existe só na pintura — o layout nem fica
    sabendo — e o efeito é descartado ao fim, pela razão documentada em
    ``Bolha.animar_entrada``: efeito pendurado custa uma superfície fora da
    tela em toda repintura.
    """

    SUBIDA = 14.0

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._progresso = 0.0

    def _get_progresso(self) -> float:
        return self._progresso

    def _set_progresso(self, valor: float) -> None:
        self._progresso = valor
        self.update()

    progresso = Property(float, _get_progresso, _set_progresso)

    def boundingRectFor(self, retangulo: QRectF | QRect) -> QRectF:
        # Só para baixo: o widget parte de SUBIDA px abaixo do lugar final.
        # Não estender para cima mantém a imagem da fonte ancorada em (0, 0).
        return QRectF(retangulo).adjusted(0, 0, 0, self.SUBIDA)

    def draw(self, pintor: QPainter) -> None:
        # Sempre pela imagem, inclusive no último quadro. ``drawSource`` pinta
        # os filhos com o MESMO pintor, e um Botao lá dentro tem a auréola, que
        # é outro efeito e tenta abrir um segundo pintor no mesmo dispositivo:
        # "A paint device can only be painted by one painter at a time".
        imagem = self.sourcePixmap(Qt.CoordinateSystem.LogicalCoordinates)
        pintor.save()
        pintor.setOpacity(self._progresso)
        pintor.drawPixmap(QPointF(0.0, (1.0 - self._progresso) * self.SUBIDA), imagem)
        pintor.restore()


def animar_entrada(widgets: Sequence[QWidget], *, reduzir: bool) -> None:
    """Cascata: cada widget sobe e aparece ``ESCALONAMENTO`` ms após o anterior.

    A ordem conduz o olho de cima para baixo, que é a ordem de leitura. Todos
    juntos seriam um clarão; um de cada vez, devagar, seriam uma espera.

    Quem chama decide QUANTOS: só o que cabe na tela merece entrada. Um widget
    fora da vista pagaria efeito e animação para ninguém ver.
    """
    if reduzir:
        return
    for ordem, widget in enumerate(widgets):
        efeito = EfeitoEntrada(widget)
        widget.setGraphicsEffect(efeito)
        grupo = QSequentialAnimationGroup(widget)
        grupo.addPause(ordem * design.ESCALONAMENTO)
        subida = QPropertyAnimation(efeito, b"progresso", grupo)
        subida.setDuration(design.DURACAO_LENTA)
        subida.setStartValue(0.0)
        subida.setEndValue(1.0)
        subida.setEasingCurve(QEasingCurve.Type.OutCubic)
        grupo.addAnimation(subida)

        def encerrar(alvo: QWidget = widget, proprio: EfeitoEntrada = efeito) -> None:
            # Uma segunda entrada pode ter trocado o efeito no meio desta; só se
            # remove o que ainda é nosso.
            if alvo.graphicsEffect() is proprio:
                # None limpa o efeito — aceito pelo Qt, ainda ausente nas stubs.
                alvo.setGraphicsEffect(None)  # type: ignore[arg-type]

        grupo.finished.connect(encerrar)
        grupo.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


class ImagemQueSai(QWidget):
    """A fotografia do que estava na tela, indo embora por cima do que chegou.

    É a ``TransicaoDeTema`` com direção: além de esmaecer, a imagem anda. Quem
    chama fotografa ANTES de trocar o conteúdo, troca, e cria esta peça por
    cima — o conteúdo novo já está no lugar e a foto do antigo sai deslizando.
    Não intercepta o mouse, e se destrói ao fim.

    Quem respeita o movimento reduzido é o chamador: sem movimento, não se
    cria a peça e a troca acontece num quadro.
    """

    def __init__(
        self,
        parent: QWidget,
        retrato: QPixmap,
        *,
        deslocamento: QPointF,
        duracao: int = design.DURACAO_MEDIA,
    ) -> None:
        super().__init__(parent)
        self._retrato = retrato
        self._deslocamento = deslocamento
        self._progresso = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(parent.rect())

        self._animacao = QVariantAnimation(self)
        self._animacao.setStartValue(0.0)
        self._animacao.setEndValue(1.0)
        self._animacao.setDuration(duracao)
        self._animacao.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animacao.valueChanged.connect(self._avancar)
        self._animacao.finished.connect(self.deleteLater)
        self.show()
        self.raise_()
        self._animacao.start()

    def _avancar(self, valor: Any) -> None:
        self._progresso = float(valor)
        self.update()

    def paintEvent(self, _evento: Any) -> None:
        pintor = QPainter(self)
        # A foto some mais rápido do que anda: sem isso, no meio do caminho as
        # duas camadas de texto ficam igualmente legíveis e embaralhadas.
        pintor.setOpacity(max(0.0, 1.0 - self._progresso * 1.6))
        pintor.drawPixmap(self._deslocamento * self._progresso, self._retrato)
        pintor.end()
