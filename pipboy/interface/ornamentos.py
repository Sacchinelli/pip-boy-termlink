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

import random
from collections.abc import Callable, Mapping
from typing import Any

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from .. import design

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


# ------------------------------------------------------------------- Molduras
# O painel da conversa é a maior superfície da janela, e era o mesmo retângulo
# translúcido de cantos arredondados nos dez ambientes. A moldura é o que os
# menus de cada jogo põem em volta do que importa — e, como nas divisórias, o
# que se desenha é o estilo, com a paleta do tema. Tudo fica RENTE à borda: o
# miolo do painel é da conversa, e nenhum ornamento passa por cima dela.


def _graca(pintor: QPainter, caixa: QRectF, t: Any) -> None:
    """Elden Ring: filigranas de ouro no alto e no pé, que somem nas pontas.

    Nada fecha as laterais. É o que os menus da Terra Intermédia fazem: o que
    importa fica entre dois fios dourados, e o resto se dissolve no escuro.
    """
    meio = caixa.center().x()
    # Recuados o bastante para o losango caber inteiro: rente à borda, a
    # metade de cima dele ficava fora da camada e saía um triângulo.
    for y in (caixa.top() + 5.0, caixa.bottom() - 5.0):
        _fio_que_some(pintor, meio - 8, caixa.left() + 12, y, t.accent, 0.7, 1.0)
        _fio_que_some(pintor, meio + 8, caixa.right() - 12, y, t.accent, 0.7, 1.0)
        pintor.setPen(QPen(_cor(t.accent, 0.95), 1.0))
        _losango(pintor, QPointF(meio, y), 3.6, cheio=True)


def _placa(pintor: QPainter, caixa: QRectF, t: Any) -> None:
    """Skyrim: placa de pedra entalhada — fio duplo no alto e no pé, losangos
    vazados nos quatro cantos, como os cravos de um tampo nórdico."""
    pintor.setPen(QPen(_cor(t.primary, 0.32), 1.0))
    for y, sentido in ((caixa.top() + 2, 1), (caixa.bottom() - 2, -1)):
        for deslocamento in (0.0, 3.0 * sentido):
            pintor.drawLine(
                QPointF(caixa.left() + 12, y + deslocamento),
                QPointF(caixa.right() - 12, y + deslocamento),
            )
    pintor.setPen(QPen(_cor(t.primary, 0.7), 1.1))
    for x in (caixa.left() + 6, caixa.right() - 6):
        for y in (caixa.top() + 5.0, caixa.bottom() - 5.0):
            _losango(pintor, QPointF(x, y), 3.8, cheio=False)


def _ferragens(pintor: QPainter, caixa: QRectF, t: Any) -> None:
    """The Witcher 3: cantoneiras de ferro com um rebite, como num grimório de
    couro — o painel parece encadernado, e não impresso."""
    braco = 16.0
    pintor.setPen(QPen(QColor(t.border_forte), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
    cantos = (
        (caixa.left() + 1, caixa.top() + 1, 1.0, 1.0),
        (caixa.right() - 1, caixa.top() + 1, -1.0, 1.0),
        (caixa.left() + 1, caixa.bottom() - 1, 1.0, -1.0),
        (caixa.right() - 1, caixa.bottom() - 1, -1.0, -1.0),
    )
    for x, y, dx, dy in cantos:
        pintor.drawLine(QPointF(x, y), QPointF(x + dx * braco, y))
        pintor.drawLine(QPointF(x, y), QPointF(x, y + dy * braco))
    pintor.setPen(Qt.PenStyle.NoPen)
    pintor.setBrush(_cor(t.accent, 0.85))
    for x, y, dx, dy in cantos:
        pintor.drawEllipse(QPointF(x + dx * 4.5, y + dy * 4.5), 1.8, 1.8)


def _cartaz_moldura(pintor: QPainter, caixa: QRectF, t: Any) -> None:
    """Red Dead: a moldura dupla de um cartaz de procurado, com os quatro
    quadrados de tinta dos cantos de dentro."""
    pintor.setBrush(Qt.BrushStyle.NoBrush)
    pintor.setPen(QPen(_cor(t.primary, 0.42), 1.6))
    pintor.drawRect(caixa.adjusted(2, 2, -2, -2))
    pintor.setPen(QPen(_cor(t.primary, 0.25), 1.0))
    interna = caixa.adjusted(6, 6, -6, -6)
    pintor.drawRect(interna)
    for x in (interna.left(), interna.right()):
        for y in (interna.top(), interna.bottom()):
            pintor.fillRect(QRectF(x - 2, y - 2, 4, 4), _cor(t.primary, 0.55))


def _neon_moldura(pintor: QPainter, caixa: QRectF, t: Any) -> None:
    """GTA: o letreiro de neon no pé do painel, do rosa ao ciano, com halo — e
    um fio fino de ciano no alto, como o reflexo dele no vidro."""
    y = caixa.bottom() - 2.5
    gradiente = QLinearGradient(QPointF(caixa.left(), y), QPointF(caixa.right(), y))
    for alfa, largura in ((0.10, 7.0), (0.22, 4.0), (0.95, 1.8)):
        gradiente.setColorAt(0.0, _cor(t.accent, 0.0))
        gradiente.setColorAt(0.15, _cor(t.accent, alfa))
        gradiente.setColorAt(0.85, _cor(t.info, alfa))
        gradiente.setColorAt(1.0, _cor(t.info, 0.0))
        pintor.setPen(
            QPen(QBrush(gradiente), largura, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        )
        pintor.drawLine(QPointF(caixa.left() + 10, y), QPointF(caixa.right() - 10, y))
    _fio_que_some(pintor, caixa.center().x(), caixa.left() + 20, caixa.top() + 1.5, t.info, 0.3, 1.0)
    _fio_que_some(pintor, caixa.center().x(), caixa.right() - 20, caixa.top() + 1.5, t.info, 0.3, 1.0)


def _circuito(pintor: QPainter, caixa: QRectF, t: Any) -> None:
    """Cyberpunk 2077: dois cantos chanfrados em traço de acento, o bloco de
    identificação no alto e o barramento recortado no pé."""
    corte, braco = 12.0, 46.0
    pintor.setPen(QPen(_cor(t.accent, 0.85), 1.4))
    esquerda, topo = caixa.left() + 1, caixa.top() + 1
    pintor.drawLine(QPointF(esquerda, topo + corte + braco), QPointF(esquerda, topo + corte))
    pintor.drawLine(QPointF(esquerda, topo + corte), QPointF(esquerda + corte, topo))
    pintor.drawLine(QPointF(esquerda + corte, topo), QPointF(esquerda + corte + braco, topo))
    direita, base = caixa.right() - 1, caixa.bottom() - 1
    pintor.drawLine(QPointF(direita, base - corte - braco), QPointF(direita, base - corte))
    pintor.drawLine(QPointF(direita, base - corte), QPointF(direita - corte, base))
    pintor.drawLine(QPointF(direita - corte, base), QPointF(direita - corte - braco, base))
    pintor.fillRect(
        QRectF(esquerda + corte + braco + 8, topo - 1, 18, 3), _cor(t.accent, 0.95)
    )
    _segmentada(pintor, QRectF(caixa.left() + 16, base - 6, caixa.width() * 0.45, 6), t)


def _pagina(pintor: QPainter, caixa: QRectF, t: Any) -> None:
    """RPG: página de manuscrito — fio duplo de ouro e um arabesco em cada
    canto, o quarto de círculo das iluminuras."""
    pintor.setBrush(Qt.BrushStyle.NoBrush)
    pintor.setPen(QPen(_cor(t.accent, 0.38), 1.0))
    externa = caixa.adjusted(3, 3, -3, -3)
    interna = caixa.adjusted(7, 7, -7, -7)
    pintor.drawRect(externa)
    pintor.drawRect(interna)
    raio = 10.0
    pintor.setPen(QPen(_cor(t.accent, 0.8), 1.2))
    for x, y, inicio in (
        (interna.left(), interna.top(), 270),
        (interna.right(), interna.top(), 180),
        (interna.left(), interna.bottom(), 0),
        (interna.right(), interna.bottom(), 90),
    ):
        pintor.drawArc(QRectF(x - raio, y - raio, 2 * raio, 2 * raio), inicio * 16, 90 * 16)


MOLDURAS: dict[str, Callable[[QPainter, QRectF, Any], None]] = {
    "graca": _graca,
    "placa": _placa,
    "ferragens": _ferragens,
    "cartaz": _cartaz_moldura,
    "neon": _neon_moldura,
    "circuito": _circuito,
    "pagina": _pagina,
}

# Até onde, a partir da borda, uma moldura pode desenhar. O resto é da conversa.
FAIXA_MOLDURA = 16.0


def pintar_moldura(pintor: QPainter, caixa: QRectF, estilo: str, tema: Any) -> None:
    """Desenha a moldura de ``estilo`` rente à borda de ``caixa``; vazio é nada."""
    desenhar = MOLDURAS.get(estilo)
    if desenhar is None or caixa.width() < 80 or caixa.height() < 80:
        return
    pintor.save()
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    desenhar(pintor, caixa, tema)
    pintor.restore()


class MolduraDoPainel(QWidget):
    """A moldura do jogo em volta de um painel, por cima dele e sem tocá-lo.

    Vive no mesmo pai que o painel e segue a geometria dele (um filtro de
    eventos no painel avisa quando ele muda). É transparente ao mouse: nenhum
    clique, rolagem ou seleção de texto da conversa passa a morar nela.

    Desenha de um retrato guardado: o painel fica embaixo da luz do cursor, e
    a cada quadro em que a luz passa por perto esta camada é pintada de novo
    na região suja. Refazer gradientes ali seria trabalho por quadro para
    desenhar a mesma coisa; o retrato só se refaz quando muda o tamanho, o
    jogo ou o traço.
    """

    def __init__(self, provedor: Any, painel: QWidget) -> None:
        super().__init__(painel.parentWidget())
        self._provedor = provedor
        self._painel = painel
        self._retrato: QPixmap | None = None
        self._chave: tuple[Any, ...] | None = None
        self.setObjectName("molduraPainel")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        painel.installEventFilter(self)
        self.acompanhar()

    @property
    def estilo(self) -> str:
        return str(getattr(self._provedor.atmosfera, "moldura", ""))

    def acompanhar(self) -> None:
        """Cobre o painel de novo, por cima dele."""
        self.setGeometry(self._painel.geometry())
        self.setVisible(self._painel.isVisible() and bool(self.estilo))
        self.raise_()
        self.update()

    def eventFilter(self, alvo: Any, evento: Any) -> bool:
        if alvo is self._painel and evento.type() in (
            QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show, QEvent.Type.Hide,
        ):
            self.acompanhar()
        return False

    def paintEvent(self, _evento: Any) -> None:
        estilo, tema = self.estilo, self._provedor.tema
        if not estilo:
            return
        chave = (self.width(), self.height(), estilo, tema.name, self.devicePixelRatioF())
        if self._retrato is None or chave != self._chave:
            razao = self.devicePixelRatioF()
            retrato = QPixmap(round(self.width() * razao), round(self.height() * razao))
            retrato.setDevicePixelRatio(razao)
            retrato.fill(QColor(0, 0, 0, 0))
            pintor_retrato = QPainter(retrato)
            pintar_moldura(pintor_retrato, QRectF(self.rect()), estilo, tema)
            pintor_retrato.end()
            self._retrato, self._chave = retrato, chave
        pintor = QPainter(self)
        pintor.drawPixmap(0, 0, self._retrato)
        pintor.end()


# ------------------------------------------------------------------- Seleção
# O item escolhido — o filtro ligado do caderno, a sessão aberta no histórico,
# a chave acesa na coluna, a linha que o Enter executaria na paleta — era o
# mesmo retângulo tingido de acento nos dez ambientes. É o lugar onde um menu
# de jogo mais se reconhece: a pincelada vermelha atrás do item nos menus do
# velho oeste, a barra invertida do terminal de fósforo, a mira travada do
# visor. Cada estilo pinta por cima do corpo do botão e devolve a cor em que o
# rótulo deve ser escrito, já com contraste garantido contra o que pintou.
#
# A paleta chega como o dicionário que os componentes já recebem (ver
# themes.paleta_de), e não como o tema: o botão não conhece o tema, e não deve
# passar a conhecer por causa de um ornamento.

_ESTILO_SELECAO: list[str] = [""]


def definir_estilo_de_selecao(estilo: str) -> None:
    """O estilo em vigor. Um por vez: o programa inteiro veste um jogo só."""
    _ESTILO_SELECAO[0] = estilo


def estilo_de_selecao() -> str:
    return _ESTILO_SELECAO[0]


class _Paleta:
    """O dicionário de papéis com acesso por atributo, como o tema."""

    def __init__(self, papeis: Mapping[str, str]) -> None:
        self._papeis = papeis

    def __getattr__(self, nome: str) -> str:
        try:
            return self._papeis[nome]
        except KeyError as erro:  # pragma: no cover - papel ausente é defeito
            raise AttributeError(nome) from erro


def _legivel(frente: str, fundo: QColor) -> QColor:
    return QColor(design.garantir_contraste(frente, fundo.name()))


def _invertida(pintor: QPainter, caixa: QRectF, caminho: QPainterPath, p: _Paleta) -> QColor:
    """Fallout: a barra invertida do Pip-Boy — o item escolhido acende inteiro
    no verde do fósforo, e a letra fica escura dentro dele."""
    fundo = QColor(p.primary)
    pintor.fillPath(caminho, fundo)
    return _legivel(p.on_primary, fundo)


def _contorno_de_pincel(caixa: QRectF) -> QPainterPath:
    """O contorno de uma pincelada: bordas que tremem e pontas esfiapadas.

    Sorteado com semente tirada do TAMANHO, e não do relógio: o mesmo botão
    tem sempre a mesma pincelada, e repintar não a faz tremer.
    """
    sorteio = random.Random(int(caixa.width()) * 7919 + int(caixa.height()) * 31)
    meio = caixa.center().y()
    metade = caixa.height() * 0.40
    esquerda, direita = caixa.left() + 3.0, caixa.right() - 3.0
    caminho = QPainterPath()
    passo = 7.0
    # Borda de cima, da esquerda para a direita.
    x = esquerda + 6.0
    caminho.moveTo(x, meio - metade + sorteio.uniform(-1.2, 1.2))
    while x < direita - 6.0:
        x = min(direita - 6.0, x + passo)
        caminho.lineTo(x, meio - metade + sorteio.uniform(-1.6, 1.6))
    # Ponta direita, esfiapada: o pincel levantando do papel.
    for fracao in (-0.7, -0.3, 0.1, 0.5, 0.85):
        caminho.lineTo(direita - sorteio.uniform(0.0, 7.0), meio + fracao * metade)
    # Borda de baixo, de volta.
    while x > esquerda + 6.0:
        x = max(esquerda + 6.0, x - passo)
        caminho.lineTo(x, meio + metade + sorteio.uniform(-1.6, 1.6))
    # Ponta esquerda, a da carga de tinta: mais cheia, menos esfiapada.
    for fracao in (0.7, 0.2, -0.3, -0.75):
        caminho.lineTo(esquerda + sorteio.uniform(0.0, 4.0), meio + fracao * metade)
    caminho.closeSubpath()
    return caminho


def _pincelada(pintor: QPainter, caixa: QRectF, _caminho: QPainterPath, p: _Paleta) -> QColor:
    """Red Dead: a pincelada vermelha atrás do item escolhido.

    É o gesto que identifica os menus do velho oeste antes de qualquer letra:
    tinta vermelha passada à mão, com as bordas tremidas e as pontas abertas,
    e as cerdas deixando riscos mais escuros no meio da faixa.
    """
    tinta = QColor(design.misturar(p.alert, "#000000", 0.22))
    contorno = _contorno_de_pincel(caixa)
    pintor.fillPath(contorno, tinta)
    # As cerdas: riscos finos e mais escuros, presos dentro da tinta.
    pintor.save()
    pintor.setClipPath(contorno)
    sorteio = random.Random(int(caixa.width()) * 131 + 17)
    cerda = QColor(design.misturar(tinta.name(), "#000000", 0.35))
    cerda.setAlphaF(0.55)
    for _ in range(4):
        y = caixa.center().y() + sorteio.uniform(-0.3, 0.3) * caixa.height()
        pintor.setPen(QPen(cerda, sorteio.uniform(0.6, 1.3)))
        pintor.drawLine(
            QPointF(caixa.left() + sorteio.uniform(4, 30), y),
            QPointF(caixa.right() - sorteio.uniform(4, 40), y + sorteio.uniform(-1.0, 1.0)),
        )
    pintor.restore()
    return _legivel(p.primary, tinta)


def _brilho_dourado(
    pintor: QPainter, caixa: QRectF, _caminho: QPainterPath, p: _Paleta
) -> QColor:
    """Elden Ring: uma faixa de luz dourada que acende no meio e se apaga nas
    pontas, entre dois fios de ouro — o item escolhido não ganha caixa, ganha
    graça."""
    meio = caixa.center().y()
    faixa = QLinearGradient(QPointF(caixa.left(), meio), QPointF(caixa.right(), meio))
    faixa.setColorAt(0.0, _cor(p.accent, 0.0))
    faixa.setColorAt(0.35, _cor(p.accent, 0.26))
    faixa.setColorAt(0.65, _cor(p.accent, 0.26))
    faixa.setColorAt(1.0, _cor(p.accent, 0.0))
    pintor.fillRect(caixa.adjusted(1, 3, -1, -3), QBrush(faixa))
    for y in (caixa.top() + 2.0, caixa.bottom() - 2.0):
        _fio_que_some(pintor, caixa.center().x(), caixa.left() + 4, y, p.accent, 0.8, 1.0)
        _fio_que_some(pintor, caixa.center().x(), caixa.right() - 4, y, p.accent, 0.8, 1.0)
    return _legivel(p.accent, QColor(design.misturar(p.surface_alta, p.accent, 0.26)))


def _losangos(pintor: QPainter, caixa: QRectF, _caminho: QPainterPath, p: _Paleta) -> QColor:
    """Skyrim: o item escolhido entre dois losangos vazados, sobre uma faixa
    clara que se apaga nas pontas, como a pedra polida pelo uso."""
    meio = caixa.center().y()
    faixa = QLinearGradient(QPointF(caixa.left(), meio), QPointF(caixa.right(), meio))
    faixa.setColorAt(0.0, _cor(p.primary, 0.0))
    faixa.setColorAt(0.5, _cor(p.primary, 0.16))
    faixa.setColorAt(1.0, _cor(p.primary, 0.0))
    pintor.fillRect(caixa.adjusted(1, 2, -1, -2), QBrush(faixa))
    pintor.setPen(QPen(_cor(p.primary, 0.9), 1.2))
    _losango(pintor, QPointF(caixa.left() + 7, meio), 3.4, cheio=False)
    _losango(pintor, QPointF(caixa.right() - 7, meio), 3.4, cheio=False)
    return _legivel(p.primary, QColor(design.misturar(p.surface_alta, p.primary, 0.16)))


def _brasa(pintor: QPainter, caixa: QRectF, _caminho: QPainterPath, p: _Paleta) -> QColor:
    """The Witcher 3: brasa acesa na borda esquerda, esfriando para a direita,
    com um filete de sangue marcando o item — o realce do bestiário."""
    meio = caixa.center().y()
    faixa = QLinearGradient(QPointF(caixa.left(), meio), QPointF(caixa.right(), meio))
    faixa.setColorAt(0.0, _cor(p.accent, 0.46))
    faixa.setColorAt(0.7, _cor(p.accent, 0.08))
    faixa.setColorAt(1.0, _cor(p.accent, 0.0))
    pintor.fillRect(caixa.adjusted(1, 1, -1, -1), QBrush(faixa))
    pintor.fillRect(
        QRectF(caixa.left() + 1, caixa.top() + 3, 3, caixa.height() - 6), QColor(p.accent)
    )
    # O rótulo começa sobre a parte mais quente: é contra ela que se garante.
    return _legivel(p.primary, QColor(design.misturar(p.surface_alta, p.accent, 0.46)))


def _letreiro(pintor: QPainter, caixa: QRectF, caminho: QPainterPath, p: _Paleta) -> QColor:
    """GTA: o letreiro aceso — rosa cheio, com o tubo de ciano correndo embaixo."""
    fundo = QColor(p.accent)
    pintor.fillPath(caminho, fundo)
    y = caixa.bottom() - 3.0
    for alfa, largura in ((0.25, 5.0), (1.0, 1.6)):
        pintor.setPen(
            QPen(_cor(p.info, alfa), largura, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        )
        pintor.drawLine(QPointF(caixa.left() + 8, y), QPointF(caixa.right() - 8, y))
    return _legivel(p.on_accent, fundo)


def _aba(pintor: QPainter, caixa: QRectF, _caminho: QPainterPath, p: _Paleta) -> QColor:
    """Cyberpunk 2077: uma aba de dados com o canto chanfrado, a barra de
    seleção acesa na esquerda e o traço do chanfro em acento."""
    corte = min(10.0, caixa.height() * 0.4)
    aba = QPainterPath()
    aba.moveTo(caixa.left() + 1, caixa.top() + 1)
    aba.lineTo(caixa.right() - corte, caixa.top() + 1)
    aba.lineTo(caixa.right() - 1, caixa.top() + corte)
    aba.lineTo(caixa.right() - 1, caixa.bottom() - 1)
    aba.lineTo(caixa.left() + 1, caixa.bottom() - 1)
    aba.closeSubpath()
    fundo = QColor(design.misturar(p.surface_alta, p.accent, 0.24))
    pintor.fillPath(aba, fundo)
    pintor.setPen(QPen(_cor(p.accent, 0.95), 1.4))
    pintor.drawLine(
        QPointF(caixa.right() - corte, caixa.top() + 1),
        QPointF(caixa.right() - 1, caixa.top() + corte),
    )
    pintor.fillRect(
        QRectF(caixa.left() + 1, caixa.top() + 1, 3, caixa.height() - 2), QColor(p.accent)
    )
    return _legivel(p.accent, fundo)


def _iluminura_selecao(
    pintor: QPainter, caixa: QRectF, _caminho: QPainterPath, p: _Paleta
) -> QColor:
    """RPG: a palavra iluminada — um véu de ouro e o sublinhado de manuscrito,
    com um losango em cada ponta."""
    fundo = QColor(design.misturar(p.surface_alta, p.accent, 0.14))
    pintor.fillRect(caixa.adjusted(1, 1, -1, -1), fundo)
    y = caixa.bottom() - 4.0
    pintor.setPen(QPen(_cor(p.accent, 0.85), 1.0))
    pintor.drawLine(QPointF(caixa.left() + 14, y), QPointF(caixa.right() - 14, y))
    _losango(pintor, QPointF(caixa.left() + 10, y), 2.6, cheio=True)
    _losango(pintor, QPointF(caixa.right() - 10, y), 2.6, cheio=True)
    return _legivel(p.accent, fundo)


def _mira(pintor: QPainter, caixa: QRectF, _caminho: QPainterPath, p: _Paleta) -> QColor:
    """FPS: o alvo travado — os quatro colchetes do visor fechados em volta do
    item escolhido, sobre um véu do laranja de sinalização."""
    fundo = QColor(design.misturar(p.surface_alta, p.accent, 0.12))
    pintor.fillRect(caixa.adjusted(1, 1, -1, -1), fundo)
    braco = min(8.0, caixa.height() * 0.3)
    dentro = caixa.adjusted(2, 2, -2, -2)
    pintor.setPen(QPen(QColor(p.accent), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
    for x, y, dx, dy in (
        (dentro.left(), dentro.top(), 1.0, 1.0),
        (dentro.right(), dentro.top(), -1.0, 1.0),
        (dentro.left(), dentro.bottom(), 1.0, -1.0),
        (dentro.right(), dentro.bottom(), -1.0, -1.0),
    ):
        pintor.drawLine(QPointF(x, y), QPointF(x + dx * braco, y))
        pintor.drawLine(QPointF(x, y), QPointF(x, y + dy * braco))
    return _legivel(p.primary, fundo)


SELECOES: dict[str, Callable[[QPainter, QRectF, QPainterPath, _Paleta], QColor]] = {
    "invertida": _invertida,
    "pincelada": _pincelada,
    "brilho_dourado": _brilho_dourado,
    "losangos": _losangos,
    "brasa": _brasa,
    "letreiro": _letreiro,
    "aba": _aba,
    "iluminura": _iluminura_selecao,
    "mira": _mira,
}


def pintar_selecao(
    pintor: QPainter,
    caixa: QRectF,
    caminho: QPainterPath,
    estilo: str,
    paleta: Mapping[str, str],
) -> QColor | None:
    """Pinta a marca de escolhido de ``estilo``; devolve a cor do rótulo.

    ``None`` quando o estilo é vazio ou desconhecido: quem chamou mantém o
    realce de sempre, o do tema neutro.
    """
    desenhar = SELECOES.get(estilo)
    if desenhar is None:
        return None
    pintor.save()
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    cor = desenhar(pintor, caixa, caminho, _Paleta(paleta))
    pintor.restore()
    return cor
