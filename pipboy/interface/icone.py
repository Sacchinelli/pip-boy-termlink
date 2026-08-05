"""Ícone do aplicativo, sintetizado com o QPainter.

Nenhum arquivo de imagem no repositório — o mesmo princípio da atmosfera. O
ícone é um visor de fósforo verde com o losango ◈ da marca: legível a 16 px
na barra de tarefas e coerente com o tema padrão do programa. O build
congelado usa exatamente este desenho para gerar o ``.ico`` do executável
(``ferramentas/gerar_icone.py``), então janela e arquivo mostram o mesmo rosto.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)

# A paleta do tema neutro/Fallout, fixada aqui de propósito: o ícone da barra
# de tarefas não deve trocar de cor junto com o tema — ícone é identidade.
_FUNDO = "#0b120c"
_VERDE = "#3ddc84"
_VERDE_ESCURO = "#1d5c3c"

TAMANHOS = (16, 24, 32, 48, 64, 128, 256)


def pintar_icone(tamanho: int) -> QPixmap:
    """Um quadro do ícone, desenhado do zero no tamanho pedido."""
    mapa = QPixmap(tamanho, tamanho)
    mapa.fill(Qt.GlobalColor.transparent)
    pintor = QPainter(mapa)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)

    t = float(tamanho)
    raio = t * 0.22
    borda = max(1.0, t / 32.0)
    retangulo = QRectF(borda / 2, borda / 2, t - borda, t - borda)

    # O corpo: um visor arredondado de vidro escuro.
    corpo = QPainterPath()
    corpo.addRoundedRect(retangulo, raio, raio)
    pintor.fillPath(corpo, QColor(_FUNDO))

    # Brilho do fósforo subindo do centro, como na tela do programa.
    brilho = QRadialGradient(QPointF(t / 2, t * 0.58), t * 0.75)
    centro = QColor(_VERDE)
    centro.setAlphaF(0.30)
    brilho.setColorAt(0.0, centro)
    fim = QColor(_VERDE)
    fim.setAlpha(0)
    brilho.setColorAt(1.0, fim)
    pintor.save()
    pintor.setClipPath(corpo)
    pintor.fillRect(retangulo, brilho)

    # Varredura: só a partir de 48 px — abaixo disso vira ruído cinza.
    if tamanho >= 48:
        linha = QColor(0, 0, 0, 70)
        passo = max(2, tamanho // 24)
        y = 0
        while y < tamanho:
            pintor.fillRect(QRectF(0, y, t, passo / 2), linha)
            y += passo
    pintor.restore()

    # O losango da marca, o mesmo ◈ da barra de título.
    lado = t * 0.46
    cx, cy = t / 2, t / 2
    losango = QPainterPath()
    losango.moveTo(cx, cy - lado / 2)
    losango.lineTo(cx + lado / 2, cy)
    losango.lineTo(cx, cy + lado / 2)
    losango.lineTo(cx - lado / 2, cy)
    losango.closeSubpath()
    caneta = QPen(QColor(_VERDE))
    caneta.setWidthF(max(1.0, t / 16.0))
    caneta.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    pintor.setPen(caneta)
    pintor.setBrush(QColor(_VERDE_ESCURO))
    pintor.drawPath(losango)

    interno = t * 0.14
    pintor.setBrush(QColor(_VERDE))
    pintor.setPen(Qt.PenStyle.NoPen)
    pintor.drawEllipse(QPointF(cx, cy), interno / 2, interno / 2)

    # A moldura por cima de tudo.
    caneta_borda = QPen(QColor(_VERDE_ESCURO))
    caneta_borda.setWidthF(borda)
    pintor.setPen(caneta_borda)
    pintor.setBrush(Qt.BrushStyle.NoBrush)
    pintor.drawRoundedRect(retangulo, raio, raio)
    pintor.end()
    return mapa


def criar_icone() -> QIcon:
    """O ícone da janela e da barra de tarefas, em todos os tamanhos."""
    icone = QIcon()
    for tamanho in TAMANHOS:
        icone.addPixmap(pintar_icone(tamanho))
    return icone
