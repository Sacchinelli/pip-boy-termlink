"""Abertura: a tela de arranque, vestida com o tema do último jogo usado.

Entre o duplo clique e a janela pronta existe quase um segundo de carga —
dispositivos de áudio, fontes, banco do caderno. Este módulo preenche esse
vão com um cartão desenhado no tema que o jogador verá em seguida, para que
o programa *comece* dentro do ambiente em vez de chegar nele.

Importa só o necessário de propósito: se este arquivo puxasse a janela, a
carga pesada aconteceria ANTES de a abertura aparecer e o cartão perderia a
única função que tem.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QGuiApplication,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QSplashScreen

from .. import design
from ..config import Preferences
from ..themes import theme_for
from .atmosfera import atmosfera_de
from .componentes import caminho_forma

LARGURA, ALTURA = 520, 300


def _fonte_do_tema(candidatas: tuple[str, ...], tamanho: int, *, negrito: bool) -> QFont:
    instaladas = set(QFontDatabase.families())
    familia = next((f for f in candidatas if f in instaladas), candidatas[-1])
    fonte = QFont(familia, tamanho)
    fonte.setBold(negrito)
    return fonte


def criar_abertura() -> QSplashScreen:
    """Desenha e devolve a tela de arranque. Cabe ao chamador dar show()."""
    prefs = Preferences.load()
    tema = theme_for(prefs.jogo)
    atmosfera = atmosfera_de(tema.name)

    tela = QGuiApplication.primaryScreen()
    dpr = tela.devicePixelRatio() if tela is not None else 1.0
    mapa = QPixmap(int(LARGURA * dpr), int(ALTURA * dpr))
    mapa.setDevicePixelRatio(dpr)
    mapa.fill(Qt.GlobalColor.transparent)

    pintor = QPainter(mapa)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    retangulo = QRectF(0.5, 0.5, LARGURA - 1.0, ALTURA - 1.0)
    caminho = caminho_forma(retangulo, atmosfera.forma, design.RAIO)

    pintor.setPen(Qt.PenStyle.NoPen)
    pintor.setBrush(QColor(tema.screen))
    pintor.drawPath(caminho)
    caneta = QPen(QColor(tema.border_forte))
    caneta.setWidthF(1.0)
    pintor.setPen(caneta)
    pintor.setBrush(Qt.BrushStyle.NoBrush)
    pintor.drawPath(caminho)

    # Marca no centro ótico (um pouco acima do geométrico), subtítulo embaixo.
    cor_marca = design.garantir_contraste(tema.primary, tema.screen)
    pintor.setPen(QColor(cor_marca))
    pintor.setFont(_fonte_do_tema(tema.font_candidates, 24, negrito=True))
    pintor.drawText(
        QRectF(24, ALTURA * 0.30, LARGURA - 48, 44),
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
        tema.header_title,
    )

    cor_sub = design.garantir_contraste(tema.text_muted, tema.screen)
    pintor.setPen(QColor(cor_sub))
    pintor.setFont(_fonte_do_tema(tema.ui_font_candidates, 9, negrito=False))
    pintor.drawText(
        QRectF(24, ALTURA * 0.30 + 48, LARGURA - 48, 22),
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
        tema.header_subtitle,
    )

    # Fio de acento entre a marca e o aviso de carga: o traço de aparelho.
    cor_acento = QColor(tema.accent)
    pintor.setPen(QPen(cor_acento, 1.0))
    pintor.drawLine(
        int(LARGURA * 0.30), int(ALTURA * 0.68), int(LARGURA * 0.70), int(ALTURA * 0.68)
    )

    pintor.setPen(QColor(cor_sub))
    pintor.setFont(_fonte_do_tema(tema.ui_font_candidates, 8, negrito=False))
    pintor.drawText(
        QRectF(24, ALTURA * 0.72, LARGURA - 48, 20),
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
        "INICIALIZANDO…",
    )
    pintor.end()

    abertura = QSplashScreen(mapa)
    # A abertura herda a translucidez do cartão: cantos chanfrados de verdade.
    abertura.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    return abertura
