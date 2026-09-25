"""O traço de cada jogo: divisórias e molduras desenhadas, sem arte nenhuma.

Paleta, fonte e atmosfera diziam de que jogo era a janela; os COMPONENTES não.
O fio que separa as seções da coluna lateral era o mesmo risco cinza de um
pixel nos dez ambientes, e é justamente nesse tipo de detalhe que um menu de
jogo se reconhece: a filigrana dourada que some nas pontas no Elden Ring, a
régua dupla de cartaz de procurado no velho oeste, o barramento de dados
recortado do Cyberpunk. Quem jogou reconhece o traço antes de ler o título.

Tudo aqui é desenho de ``QPainter`` sobre a paleta do tema, pela mesma regra do
resto do programa: nenhuma textura, imagem, fonte ou logotipo de terceiros. O
que se evoca é o ESTILO dos menus — o vocabulário de ornamentos —, e não a
marca de ninguém.

Cada estilo é uma função pura de (pintor, caixa, tema): não guarda estado, não
conhece widget e não depende de nada que só exista depois da montagem. É o que
permite a suíte desenhar cada um sobre o vazio e medir onde a tinta cai.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

# Altura da faixa em que uma divisória se desenha: o fio fica no meio, e os
# ornamentos — losango, argola, tiques — cabem nela sem cortar.
ALTURA_DIVISORIA = 11


def _cor(base: str, alfa: float) -> QColor:
    cor = QColor(base)
    cor.setAlphaF(max(0.0, min(1.0, alfa)))
    return cor


def _losango(pintor: QPainter, centro: QPointF, raio: float, *, cheio: bool) -> None:
    caminho = QPainterPath()
    caminho.moveTo(centro.x(), centro.y() - raio)
    caminho.lineTo(centro.x() + raio, centro.y())
    caminho.lineTo(centro.x(), centro.y() + raio)
    caminho.lineTo(centro.x() - raio, centro.y())
    caminho.closeSubpath()
    if cheio:
        pintor.fillPath(caminho, pintor.pen().color())
    else:
        pintor.drawPath(caminho)


def _fio_que_some(
    pintor: QPainter, de: float, ate: float, y: float, cor: str, alfa: float, largura: float
) -> None:
    """Um fio que nasce aceso em ``de`` e se apaga até ``ate``."""
    gradiente = QLinearGradient(QPointF(de, y), QPointF(ate, y))
    gradiente.setColorAt(0.0, _cor(cor, alfa))
    gradiente.setColorAt(1.0, _cor(cor, 0.0))
    pintor.setPen(QPen(QBrush(gradiente), largura))
    pintor.drawLine(QPointF(de, y), QPointF(ate, y))


# ----------------------------------------------------------------- Divisórias
def _linha(pintor: QPainter, caixa: QRectF, t: Any) -> None:
    """O fio neutro de um pixel: o do tema genérico e o do terminal."""
    y = caixa.center().y()
    pintor.setPen(QPen(QColor(t.border), 1.0))
    pintor.drawLine(QPointF(caixa.left(), y), QPointF(caixa.right(), y))


def _fio_de_ouro(pintor: QPainter, caixa: QRectF, t: Any) -> None:
    """Elden Ring: um losango de ouro e um fio fino que se apaga no escuro.

    Os menus da Terra Intermédia não fecham caixa nenhuma: separam com
    filigranas que nascem acesas e somem antes de chegar à borda.
    """
    y = caixa.center().y()
    pintor.setPen(QPen(_cor(t.accent, 0.95), 1.0))
    _losango(pintor, QPointF(caixa.left() + 3.5, y), 3.2, cheio=True)
    _fio_que_some(pintor, caixa.left() + 10, caixa.right(), y, t.accent, 0.75, 1.0)


def _nordica(pintor: QPainter, caixa: QRectF, t: Any) -> None:
    """Skyrim: fio duplo de pedra entalhada, terminado num losango vazado."""
    y = caixa.center().y()
    fim = caixa.right() - 9
    pintor.setPen(QPen(_cor(t.primary, 0.42), 1.0))
    pintor.drawLine(QPointF(caixa.left(), y - 1.5), QPointF(fim - 4, y - 1.5))
    pintor.drawLine(QPointF(caixa.left(), y + 1.5), QPointF(fim - 4, y + 1.5))
    pintor.setPen(QPen(_cor(t.primary, 0.75), 1.1))
    _losango(pintor, QPointF(fim + 1, y), 3.6, cheio=False)


def _medalhao(pintor: QPainter, caixa: QRectF, t: Any) -> None:
    """The Witcher 3: a argola do medalhão abrindo um fio de ferro."""
    y = caixa.center().y()
    pintor.setPen(QPen(_cor(t.accent, 0.9), 1.3))
    pintor.setBrush(Qt.BrushStyle.NoBrush)
    pintor.drawEllipse(QPointF(caixa.left() + 4.5, y), 3.4, 3.4)
    pintor.setPen(QPen(QColor(t.border_forte), 1.0))
    pintor.drawLine(QPointF(caixa.left() + 11, y), QPointF(caixa.right() - 3, y))
    pintor.drawLine(QPointF(caixa.right() - 3, y - 2.5), QPointF(caixa.right() - 3, y + 2.5))


def _cartaz(pintor: QPainter, caixa: QRectF, t: Any) -> None:
    """Red Dead: a régua dupla — grossa e fina — dos cartazes de procurado."""
    y = caixa.center().y()
    pintor.setPen(QPen(_cor(t.primary, 0.55), 2.0))
    pintor.drawLine(QPointF(caixa.left(), y - 1.5), QPointF(caixa.right(), y - 1.5))
    pintor.setPen(QPen(_cor(t.primary, 0.35), 1.0))
    pintor.drawLine(QPointF(caixa.left(), y + 2.0), QPointF(caixa.right(), y + 2.0))


def _neon(pintor: QPainter, caixa: QRectF, t: Any) -> None:
    """GTA: um tubo de neon do rosa ao ciano, com o halo em volta."""
    y = caixa.center().y()
    gradiente = QLinearGradient(QPointF(caixa.left(), y), QPointF(caixa.right(), y))
    for alfa, largura in ((0.10, 6.0), (0.22, 3.5), (0.95, 1.6)):
        gradiente.setColorAt(0.0, _cor(t.accent, alfa))
        gradiente.setColorAt(0.65, _cor(t.info, alfa))
        gradiente.setColorAt(1.0, _cor(t.info, 0.0))
        pintor.setPen(
            QPen(QBrush(gradiente), largura, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        )
        pintor.drawLine(QPointF(caixa.left() + 2, y), QPointF(caixa.right(), y))


# O compasso do barramento do Cyberpunk: comprimentos que se repetem com
# irregularidade proposital — um traço contínuo leria como fio, e não como dado.
_SEGMENTOS = (22.0, 5.0, 9.0, 3.0, 34.0, 6.0, 4.0, 14.0)


def _segmentada(pintor: QPainter, caixa: QRectF, t: Any) -> None:
    """Cyberpunk 2077: barramento de dados recortado, com o bloco de início."""
    y = caixa.center().y()
    pintor.fillRect(QRectF(caixa.left(), y - 2.0, 7.0, 4.0), _cor(t.accent, 0.95))
    pintor.setPen(QPen(_cor(t.accent, 0.55), 1.2))
    x = caixa.left() + 11
    indice = 0
    while x < caixa.right():
        fim = min(caixa.right(), x + _SEGMENTOS[indice % len(_SEGMENTOS)])
        pintor.drawLine(QPointF(x, y), QPointF(fim, y))
        x = fim + 3.0
        indice += 1


def _iluminura(pintor: QPainter, caixa: QRectF, t: Any) -> None:
    """RPG: o fio de iluminura, com um losango em cada ponta e um ponto no meio."""
    y = caixa.center().y()
    pintor.setPen(QPen(_cor(t.accent, 0.5), 1.0))
    pintor.drawLine(QPointF(caixa.left() + 7, y), QPointF(caixa.right() - 7, y))
    pintor.setPen(QPen(_cor(t.accent, 0.9), 1.0))
    _losango(pintor, QPointF(caixa.left() + 3, y), 2.8, cheio=True)
    _losango(pintor, QPointF(caixa.right() - 3, y), 2.8, cheio=True)
    pintor.setBrush(_cor(t.accent, 0.9))
    pintor.setPen(Qt.PenStyle.NoPen)
    pintor.drawEllipse(QPointF(caixa.center().x(), y), 1.6, 1.6)


def _regua(pintor: QPainter, caixa: QRectF, t: Any) -> None:
    """FPS: a escala de um visor, com tiques curtos e marcas a cada cinco."""
    y = caixa.center().y()
    pintor.setPen(QPen(QColor(t.border_forte), 1.0))
    pintor.drawLine(QPointF(caixa.left(), y), QPointF(caixa.right(), y))
    pintor.setPen(QPen(_cor(t.primary, 0.4), 1.0))
    passo, x, contagem = 6.0, caixa.left(), 0
    while x <= caixa.right():
        alto = 4.0 if contagem % 5 == 0 else 2.0
        pintor.drawLine(QPointF(x, y - alto), QPointF(x, y))
        x += passo
        contagem += 1


DIVISORIAS: dict[str, Callable[[QPainter, QRectF, Any], None]] = {
    "linha": _linha,
    "fio_de_ouro": _fio_de_ouro,
    "nordica": _nordica,
    "medalhao": _medalhao,
    "cartaz": _cartaz,
    "neon": _neon,
    "segmentada": _segmentada,
    "iluminura": _iluminura,
    "regua": _regua,
}


def pintar_divisoria(pintor: QPainter, caixa: QRectF, estilo: str, tema: Any) -> None:
    """Desenha a divisória de ``estilo`` em ``caixa``; estilo desconhecido é fio."""
    pintor.save()
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    DIVISORIAS.get(estilo, _linha)(pintor, caixa, tema)
    pintor.restore()


class Divisoria(QWidget):
    """O fio ao lado de cada título de seção, no traço do jogo em vigor.

    Lê o tema e a atmosfera do provedor NA HORA de pintar: trocar de jogo
    repinta a janela inteira, e a divisória sai no traço novo sem que ninguém
    precise avisá-la.
    """

    def __init__(self, provedor: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._provedor = provedor
        self.setObjectName("divisoria")
        self.setFixedHeight(ALTURA_DIVISORIA)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    @property
    def estilo(self) -> str:
        return str(getattr(self._provedor.atmosfera, "divisoria", "linha"))

    def paintEvent(self, _evento: Any) -> None:
        pintor = QPainter(self)
        pintar_divisoria(pintor, QRectF(self.rect()), self.estilo, self._provedor.tema)
        pintor.end()
