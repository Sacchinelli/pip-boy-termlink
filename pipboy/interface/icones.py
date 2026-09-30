"""Os ícones de cada jogo: o caderno e o histórico, desenhados no traço dele.

As duas portas da janela — o caderno de palavras e o histórico de conversas —
eram dois símbolos do bloco Geometric Shapes, os mesmos nos dez ambientes:
um retângulo riscado e um relógio. Os jogos têm o objeto de cada coisa. O
caderno é uma holotape no Pip-Boy, um tomo com fecho no Elden Ring, o diário
com correia do velho oeste, o celular no GTA, o fragmento de dados na Night
City, as plaquetas de identificação no visor. O histórico é o terminal, o
brilho de uma graça, o pergaminho enrolado do norte, o aviso de contrato
pregado no quadro do bruxo, a fogueira do acampamento, o rádio, o
braindance, a ampulheta, a prancheta do relatório de missão.

Tudo desenhado com ``QPainter`` numa caixa de lado 1 — cada ícone é uma
função pura de (pintor, cor), sem imagem nenhuma — e com caneta cosmética:
a espessura do traço é em pixels de tela, e não escala com a caixa, então o
mesmo desenho sai nítido a 16 px numa porta e a 24 px no trilho. O tema
neutro, e qualquer estilo desconhecido, fica com os glifos de sempre.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

# O que se desenha quando o jogo não tem ícone próprio: os glifos de antes.
GLIFOS_PADRAO: dict[str, str] = {"caderno": "◫", "historico": "◷"}

Desenho = Callable[[QPainter, QColor], None]

_ESTILO_ICONE: list[str] = [""]


def definir_estilo_de_icone(estilo: str) -> None:
    """O conjunto de ícones em vigor. Um por vez, como a marca de escolhido."""
    _ESTILO_ICONE[0] = estilo


def estilo_de_icone() -> str:
    return _ESTILO_ICONE[0]


# --------------------------------------------------------------- primitivas
def _linha(p: QPainter, *pontos: tuple[float, float]) -> None:
    caminho = QPainterPath(QPointF(*pontos[0]))
    for ponto in pontos[1:]:
        caminho.lineTo(QPointF(*ponto))
    p.drawPath(caminho)


def _fechado(p: QPainter, *pontos: tuple[float, float], cheio: QColor | None = None) -> None:
    caminho = QPainterPath(QPointF(*pontos[0]))
    for ponto in pontos[1:]:
        caminho.lineTo(QPointF(*ponto))
    caminho.closeSubpath()
    if cheio is not None:
        p.fillPath(caminho, cheio)
    p.drawPath(caminho)


def _ponto(p: QPainter, x: float, y: float, r: float, cor: QColor) -> None:
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(cor)
    p.drawEllipse(QPointF(x, y), r, r)
    p.restore()


def _livro(p: QPainter) -> None:
    """O corpo de um livro fechado, com a lombada: a base de três cadernos."""
    p.drawRect(QRectF(0.2, 0.12, 0.6, 0.76))
    _linha(p, (0.3, 0.12), (0.3, 0.88))


# ------------------------------------------------------------------ Fallout
def _holotape(p: QPainter, cor: QColor) -> None:
    """A holotape: a fita de dados que se enfia no Pip-Boy."""
    p.drawRoundedRect(QRectF(0.1, 0.24, 0.8, 0.54), 0.06, 0.06)
    _linha(p, (0.18, 0.38), (0.82, 0.38))
    p.drawEllipse(QPointF(0.36, 0.58), 0.09, 0.09)
    p.drawEllipse(QPointF(0.64, 0.58), 0.09, 0.09)


def _terminal(p: QPainter, cor: QColor) -> None:
    """O terminal da RobCo, com o prompt e o cursor em bloco."""
    p.drawRect(QRectF(0.1, 0.14, 0.8, 0.56))
    _linha(p, (0.5, 0.7), (0.5, 0.8))
    _linha(p, (0.3, 0.84), (0.7, 0.84))
    _linha(p, (0.24, 0.3), (0.36, 0.42), (0.24, 0.54))
    p.fillRect(QRectF(0.44, 0.46, 0.14, 0.08), cor)


# --------------------------------------------------------------- Elden Ring
def _tomo(p: QPainter, cor: QColor) -> None:
    """O tomo de encantamentos, com o losango de ouro na capa e o fecho."""
    _livro(p)
    _fechado(p, (0.55, 0.36), (0.66, 0.5), (0.55, 0.64), (0.44, 0.5), cheio=cor)
    _linha(p, (0.8, 0.42), (0.88, 0.42), (0.88, 0.58), (0.8, 0.58))


def _graca(p: QPainter, cor: QColor) -> None:
    """Uma graça: a haste de luz dourada que sobe do chão, com os raios."""
    _fechado(p, (0.5, 0.08), (0.58, 0.55), (0.5, 0.86), (0.42, 0.55))
    _linha(p, (0.32, 0.46), (0.2, 0.4))
    _linha(p, (0.68, 0.46), (0.8, 0.4))
    _linha(p, (0.34, 0.62), (0.24, 0.64))
    _linha(p, (0.66, 0.62), (0.76, 0.64))
    _linha(p, (0.22, 0.9), (0.78, 0.9))


# ------------------------------------------------------------------- Skyrim
def _tomo_de_palavras(p: QPainter, cor: QColor) -> None:
    """O tomo com a escrita dos dragões: três garras riscadas na capa."""
    _livro(p)
    for x in (0.44, 0.56, 0.68):
        _linha(p, (x + 0.04, 0.3), (x - 0.06, 0.52))
    _linha(p, (0.38, 0.64), (0.72, 0.64))


def _pergaminho(p: QPainter, cor: QColor) -> None:
    """Um Pergaminho Antigo: o corpo aberto entre dois rolos."""
    p.drawRect(QRectF(0.24, 0.3, 0.52, 0.4))
    for x in (0.2, 0.8):
        p.drawEllipse(QPointF(x, 0.5), 0.07, 0.24)
    _linha(p, (0.34, 0.44), (0.66, 0.44))
    _linha(p, (0.34, 0.56), (0.6, 0.56))


# ------------------------------------------------------------ The Witcher 3
def _bestiario(p: QPainter, cor: QColor) -> None:
    """O bestiário, com o medalhão do lobo na capa."""
    _livro(p)
    p.drawEllipse(QPointF(0.56, 0.48), 0.14, 0.14)
    _ponto(p, 0.56, 0.48, 0.04, cor)
    _linha(p, (0.56, 0.26), (0.56, 0.34))


def _contrato(p: QPainter, cor: QColor) -> None:
    """O aviso de contrato pregado no quadro da vila."""
    p.save()
    p.translate(0.5, 0.5)
    p.rotate(-4)
    p.translate(-0.5, -0.5)
    p.drawRect(QRectF(0.2, 0.18, 0.6, 0.72))
    _linha(p, (0.3, 0.42), (0.7, 0.42))
    _linha(p, (0.3, 0.56), (0.7, 0.56))
    _linha(p, (0.3, 0.7), (0.58, 0.7))
    p.restore()
    _ponto(p, 0.5, 0.2, 0.06, cor)


# ----------------------------------------------------------------- Red Dead
def _diario(p: QPainter, cor: QColor) -> None:
    """O diário de couro, fechado pela correia com fivela."""
    p.drawRect(QRectF(0.16, 0.14, 0.6, 0.72))
    _linha(p, (0.16, 0.44), (0.88, 0.44))
    _linha(p, (0.16, 0.56), (0.88, 0.56))
    p.drawRect(QRectF(0.72, 0.4, 0.1, 0.2))


def _fogueira(p: QPainter, cor: QColor) -> None:
    """A fogueira do acampamento: duas toras cruzadas e a chama."""
    _linha(p, (0.2, 0.88), (0.8, 0.7))
    _linha(p, (0.2, 0.7), (0.8, 0.88))
    chama = QPainterPath(QPointF(0.5, 0.14))
    chama.cubicTo(QPointF(0.7, 0.38), QPointF(0.72, 0.62), QPointF(0.5, 0.7))
    chama.cubicTo(QPointF(0.28, 0.62), QPointF(0.3, 0.4), QPointF(0.44, 0.3))
    chama.cubicTo(QPointF(0.46, 0.42), QPointF(0.5, 0.44), QPointF(0.5, 0.14))
    p.drawPath(chama)


# ---------------------------------------------------------------------- GTA
def _celular(p: QPainter, cor: QColor) -> None:
    """O celular: é por ele que tudo passa na cidade."""
    p.drawRoundedRect(QRectF(0.3, 0.08, 0.4, 0.84), 0.08, 0.08)
    p.drawRect(QRectF(0.36, 0.18, 0.28, 0.56))
    _ponto(p, 0.5, 0.83, 0.035, cor)


def _radio(p: QPainter, cor: QColor) -> None:
    """A roda das rádios: o anel de estações em volta do miolo."""
    p.drawEllipse(QPointF(0.5, 0.5), 0.38, 0.38)
    p.drawEllipse(QPointF(0.5, 0.5), 0.12, 0.12)
    for passo in range(8):
        angulo = math.tau * passo / 8
        dx, dy = math.cos(angulo), math.sin(angulo)
        _linha(p, (0.5 + dx * 0.19, 0.5 + dy * 0.19), (0.5 + dx * 0.3, 0.5 + dy * 0.3))


# ---------------------------------------------------------------- Cyberpunk
def _fragmento(p: QPainter, cor: QColor) -> None:
    """O fragmento de dados, com o canto cortado e os contatos no pé."""
    _fechado(p, (0.28, 0.1), (0.72, 0.1), (0.72, 0.74), (0.58, 0.9), (0.28, 0.9))
    _linha(p, (0.28, 0.3), (0.72, 0.3))
    for x in (0.38, 0.48, 0.58):
        _linha(p, (x, 0.66), (x, 0.8))


def _braindance(p: QPainter, cor: QColor) -> None:
    """O braindance: o anel de gravação partido, com o sinal de reproduzir."""
    caixa = QRectF(0.12, 0.12, 0.76, 0.76)
    for inicio in (20, 140, 260):
        p.drawArc(caixa, inicio * 16, 95 * 16)
    _fechado(p, (0.42, 0.34), (0.66, 0.5), (0.42, 0.66), cheio=cor)


# ---------------------------------------------------------------------- RPG
def _grimorio(p: QPainter, cor: QColor) -> None:
    """O grimório, com a estrela de quatro pontas na capa."""
    _livro(p)
    cx, cy = 0.56, 0.48
    _fechado(
        p, (cx, cy - 0.2), (cx + 0.05, cy - 0.05), (cx + 0.18, cy), (cx + 0.05, cy + 0.05),
        (cx, cy + 0.2), (cx - 0.05, cy + 0.05), (cx - 0.18, cy), (cx - 0.05, cy - 0.05),
        cheio=cor,
    )


def _ampulheta(p: QPainter, cor: QColor) -> None:
    """A ampulheta: o tempo passado, que é o que um histórico guarda."""
    _linha(p, (0.24, 0.1), (0.76, 0.1))
    _linha(p, (0.24, 0.9), (0.76, 0.9))
    _fechado(p, (0.3, 0.1), (0.7, 0.1), (0.5, 0.5), (0.7, 0.9), (0.3, 0.9), (0.5, 0.5))
    _fechado(p, (0.38, 0.8), (0.62, 0.8), (0.5, 0.64), cheio=cor)


# ---------------------------------------------------------------------- FPS
def _plaquetas(p: QPainter, cor: QColor) -> None:
    """As plaquetas de identificação, as duas, na corrente."""
    p.drawRoundedRect(QRectF(0.14, 0.26, 0.34, 0.56), 0.12, 0.12)
    p.drawRoundedRect(QRectF(0.52, 0.34, 0.34, 0.56), 0.12, 0.12)
    _ponto(p, 0.31, 0.34, 0.035, cor)
    _ponto(p, 0.69, 0.42, 0.035, cor)
    corrente = QPainterPath(QPointF(0.31, 0.34))
    corrente.cubicTo(QPointF(0.36, 0.06), QPointF(0.64, 0.1), QPointF(0.69, 0.42))
    p.drawPath(corrente)
    _linha(p, (0.22, 0.56), (0.4, 0.56))
    _linha(p, (0.6, 0.64), (0.78, 0.64))


def _prancheta(p: QPainter, cor: QColor) -> None:
    """A prancheta do relatório de missão, com as marcas de conferido."""
    p.drawRect(QRectF(0.22, 0.16, 0.56, 0.74))
    p.fillRect(QRectF(0.38, 0.1, 0.24, 0.1), cor)
    _linha(p, (0.3, 0.42), (0.36, 0.48), (0.46, 0.36))
    _linha(p, (0.52, 0.44), (0.7, 0.44))
    _linha(p, (0.3, 0.66), (0.36, 0.72), (0.46, 0.6))
    _linha(p, (0.52, 0.68), (0.7, 0.68))


ICONES: dict[str, dict[str, Desenho]] = {
    "terminal": {"caderno": _holotape, "historico": _terminal},
    "graca": {"caderno": _tomo, "historico": _graca},
    "nordico": {"caderno": _tomo_de_palavras, "historico": _pergaminho},
    "bruxo": {"caderno": _bestiario, "historico": _contrato},
    "oeste": {"caderno": _diario, "historico": _fogueira},
    "celular": {"caderno": _celular, "historico": _radio},
    "dados": {"caderno": _fragmento, "historico": _braindance},
    "grimorio": {"caderno": _grimorio, "historico": _ampulheta},
    "tatico": {"caderno": _plaquetas, "historico": _prancheta},
}


def pintar_icone(
    pintor: QPainter, nome: str, caixa: QRectF, cor: QColor, *, estilo: str | None = None
) -> None:
    """Desenha o ícone ``nome`` do jogo em vigor dentro de ``caixa``, na cor pedida.

    Sem desenho próprio, escreve o glifo de sempre, na fonte que o pintor já
    tem — que é a do botão que chamou.
    """
    desenhar = ICONES.get(estilo_de_icone() if estilo is None else estilo, {}).get(nome)
    pintor.save()
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    if desenhar is None:
        pintor.setPen(cor)
        pintor.drawText(caixa, int(Qt.AlignmentFlag.AlignCenter), GLIFOS_PADRAO.get(nome, "◆"))
        pintor.restore()
        return
    lado = min(caixa.width(), caixa.height())
    pintor.translate(caixa.center().x() - lado / 2, caixa.center().y() - lado / 2)
    pintor.scale(lado, lado)
    caneta = QPen(cor)
    caneta.setCosmetic(True)
    caneta.setWidthF(max(1.2, lado * 0.075))
    caneta.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
    pintor.setPen(caneta)
    pintor.setBrush(Qt.BrushStyle.NoBrush)
    desenhar(pintor, cor)
    pintor.restore()


class IconeDoJogo(QWidget):
    """O ícone do jogo em vigor, sozinho: ao lado do título de uma janela.

    Lê o tema a cada pintura — trocar de jogo com a janela aberta troca o
    desenho sem ninguém avisar este widget.
    """

    def __init__(self, provedor: Any, nome: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._provedor = provedor
        self.nome = nome
        self._lado = 24
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAccessibleName("")

    def definir_lado(self, lado: int) -> None:
        self._lado = max(12, lado)
        self.setFixedSize(self._lado, self._lado)
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(self._lado, self._lado)

    def paintEvent(self, _evento: Any) -> None:
        pintor = QPainter(self)
        pintor.setFont(self.font())
        pintar_icone(
            pintor, self.nome, QRectF(self.rect()).adjusted(1, 1, -1, -1),
            QColor(self._provedor.tema.accent_text),
        )
        pintor.end()
