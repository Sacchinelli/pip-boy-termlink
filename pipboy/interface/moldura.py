"""Moldura própria: barra de título temática e redimensionamento sem moldura.

A barra de título do Windows era o único pedaço da tela que o tema não
alcançava: um retângulo cinza do sistema coroando um terminal de fósforo
verde. Este módulo remove a moldura nativa (``FramelessWindowHint``) e devolve
cada função dela desenhada no tema — título, minimizar, maximizar, fechar,
arrastar e redimensionar.

Três decisões de desenho:

* **Os botões são desenhados, não digitados.** Glifos de fonte ("─", "□", "✕")
  mudam de espessura e alinhamento conforme a família instalada; três traços
  de ``QPainter`` são idênticos em qualquer máquina e aceitam a paleta.
* **Mover e redimensionar são do sistema.** ``startSystemMove`` e
  ``startSystemResize`` entregam a operação ao Windows, que a executa com o
  mesmo desempenho e o mesmo comportamento de uma janela nativa — inclusive o
  encaixe nas bordas do monitor durante o arrasto.
* **O que o sistema ainda faz bem, o sistema continua fazendo.** No Windows 11
  os cantos arredondados e a sombra da janela voltam por uma chamada ao DWM;
  onde a chamada não existe (Windows 10, Linux), ela falha em silêncio e a
  janela fica de canto reto — funcional do mesmo jeito.
"""

from __future__ import annotations

import sys
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from .. import design

ALTURA_BARRA = 38
LARGURA_BOTAO = 44
ESPESSURA_BORDA = 6      # faixa sensível de redimensionamento nas bordas
CANTO = 14               # e a área maior nos cantos, onde duas bordas se encontram


# ------------------------------------------------------------ Botão de janela
class BotaoJanela(QAbstractButton):
    """Minimizar, maximizar/restaurar ou fechar, pintado no tema.

    O botão de fechar é o único cuja resposta ao cursor é colorida: fundo no
    vermelho do tema, como todo usuário de Windows espera. Os outros dois
    apenas elevam a superfície.
    """

    def __init__(self, acao: str, paleta: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.acao = acao
        self._paleta = paleta
        self._maximizada = False
        self.setFixedSize(LARGURA_BOTAO, ALTURA_BARRA)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # Tab é dos controles reais.
        nomes = {
            "compacto": "Modo compacto — uma cápsula sobre o jogo",
            "minimizar": "Minimizar",
            "maximizar": "Maximizar",
            "fechar": "Fechar",
        }
        # O nome de origem fica guardado: o botão do meio alterna entre
        # "Maximizar" e "Restaurar", e sem uma referência fixa a volta não
        # tem para onde ir.
        self._nome = nomes[acao]
        self.setAccessibleName(self._nome)
        self.setToolTip(self._nome)

    def definir_maximizada(self, maximizada: bool) -> None:
        if maximizada == self._maximizada:
            return
        self._maximizada = maximizada
        if self.acao == "maximizar":
            nome = "Restaurar" if maximizada else self._nome
            self.setToolTip(nome)
            self.setAccessibleName(nome)
        self.update()

    def paintEvent(self, _evento: Any) -> None:
        p = self._paleta()
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)

        sob_cursor = self.underMouse() and self.isEnabled()
        pressionado = self.isDown()

        if sob_cursor:
            if self.acao == "fechar":
                fundo = QColor(p.get("alert", "#aa3333"))
                fundo.setAlphaF(0.85 if pressionado else 0.70)
            else:
                fundo = QColor(p.get("primary", "#888888"))
                fundo.setAlphaF(0.16 if pressionado else 0.10)
            pintor.fillRect(self.rect(), fundo)

        # Sobre o vermelho de fechar, o traço precisa da cor calculada para
        # ler sobre o acento; nos demais, a cor de texto usual.
        if self.acao == "fechar" and sob_cursor:
            cor = QColor(p.get("on_alert", "#ffffff"))
        else:
            cor = QColor(p.get("text_muted", "#aaaaaa"))
        caneta = QPen(cor)
        caneta.setWidthF(1.2)
        pintor.setPen(caneta)

        # Glifos de 10 px centrados, na convenção do próprio Windows.
        cx, cy, meio = self.width() / 2, self.height() / 2, 5.0
        if self.acao == "compacto":
            # Janela grande com uma cápsula no canto: o ícone de PiP.
            pintor.drawRect(QRectF(cx - meio, cy - meio, 2 * meio, 2 * meio))
            pintor.fillRect(QRectF(cx, cy + 1, meio, meio - 1), cor)
        elif self.acao == "minimizar":
            pintor.drawLine(QPointF(cx - meio, cy), QPointF(cx + meio, cy))
        elif self.acao == "maximizar":
            if self._maximizada:
                # Restaurar: dois retângulos sobrepostos.
                atras = QRectF(cx - meio + 2, cy - meio, 2 * meio - 2, 2 * meio - 2)
                pintor.drawRect(atras.adjusted(0, 0, 0, -2))
                pintor.fillRect(
                    QRectF(cx - meio, cy - meio + 2, 2 * meio - 2, 2 * meio - 2),
                    QColor(p.get("surface", "#222222")),
                )
                pintor.drawRect(QRectF(cx - meio, cy - meio + 2, 2 * meio - 2, 2 * meio - 2))
            else:
                pintor.drawRect(QRectF(cx - meio, cy - meio, 2 * meio, 2 * meio))
        else:
            pintor.drawLine(QPointF(cx - meio, cy - meio), QPointF(cx + meio, cy + meio))
            pintor.drawLine(QPointF(cx - meio, cy + meio), QPointF(cx + meio, cy - meio))
        pintor.end()

    def enterEvent(self, evento: Any) -> None:
        self.update()
        super().enterEvent(evento)

    def leaveEvent(self, evento: Any) -> None:
        self.update()
        super().leaveEvent(evento)


# ------------------------------------------------------------- Barra de título
class BarraDeTitulo(QWidget):
    """A faixa superior da janela, desenhada com as peças do próprio tema.

    O provedor de tema é o mesmo contrato que ``dialogo`` e ``caderno`` já
    consomem: ``tema``, ``fonte()`` e ``paleta()``. Ele pode ser um objeto
    diferente da janela hospedeira — o caderno é um diálogo sem tema próprio,
    vestido pelo tema da janela principal. Arrastar move a janela pelo
    sistema; duplo clique alterna maximizada, como na moldura substituída.
    """

    def __init__(
        self,
        janela: Any,
        *,
        provedor: Any | None = None,
        titulo: str | None = None,
        botoes: tuple[str, ...] = ("minimizar", "maximizar", "fechar"),
    ) -> None:
        super().__init__(janela)
        self._janela = janela
        self._provedor = provedor if provedor is not None else janela
        self._titulo_fixo = titulo
        self.setFixedHeight(ALTURA_BARRA)
        self.setObjectName("barraTitulo")

        linha = QHBoxLayout(self)
        linha.setContentsMargins(design.ESPACO_LG, 0, 0, 0)
        linha.setSpacing(design.ESPACO_SM)

        self._glifo = QLabel("◈")
        self._glifo.setObjectName("glifoTitulo")
        linha.addWidget(self._glifo)

        self._titulo = QLabel("")
        self._titulo.setObjectName("tituloJanela")
        linha.addWidget(self._titulo)
        linha.addStretch(1)

        acoes = {
            "compacto": lambda: janela.entrar_modo_compacto(),
            "minimizar": janela.showMinimized,
            "maximizar": self._alternar_maximizada,
            "fechar": janela.close,
        }
        self.botao_maximizar: BotaoJanela | None = None
        for acao in botoes:
            botao = BotaoJanela(acao, self._provedor.paleta, self)
            botao.clicked.connect(acoes[acao])
            linha.addWidget(botao)
            if acao == "maximizar":
                self.botao_maximizar = botao

    # -- tema
    def aplicar_tema(self) -> None:
        tema = self._provedor.tema
        self._titulo.setText(self._titulo_fixo or tema.window_title)
        self._titulo.setFont(self._provedor.fonte("legenda"))
        self._glifo.setFont(self._provedor.fonte("legenda"))
        cor_titulo = design.garantir_contraste(tema.text_muted, tema.surface)
        cor_glifo = design.garantir_contraste(tema.accent, tema.surface)
        self._titulo.setStyleSheet(f"color: {cor_titulo}; background: transparent;")
        self._glifo.setStyleSheet(f"color: {cor_glifo}; background: transparent;")
        self.update()

    # Tela cheia conta como maximizada para efeito de moldura: em nenhum dos
    # dois estados há o que redimensionar, e nos dois o botão do meio deve
    # oferecer "Restaurar". A janela principal já tratava os dois juntos ao
    # esconder as alças; só esta barra olhava um deles, e o botão ficava
    # anunciando "Maximizar" numa janela ocupando o monitor inteiro.
    _EXPANDIDA: Qt.WindowState = (
        Qt.WindowState.WindowMaximized | Qt.WindowState.WindowFullScreen
    )

    def _expandida(self) -> bool:
        return bool(self._janela.windowState() & self._EXPANDIDA)

    def sincronizar_estado(self) -> None:
        """Reflete maximizada/restaurada no glifo do botão do meio."""
        if self.botao_maximizar is None:
            return
        self.botao_maximizar.definir_maximizada(self._expandida())

    # -- comportamento de moldura
    def _alternar_maximizada(self) -> None:
        if self._expandida():
            self._janela.showNormal()
        else:
            self._janela.showMaximized()

    def mousePressEvent(self, evento: Any) -> None:
        if evento.button() == Qt.MouseButton.LeftButton:
            alca = self._janela.windowHandle()
            if alca is not None:
                alca.startSystemMove()
                return
        super().mousePressEvent(evento)

    def mouseDoubleClickEvent(self, evento: Any) -> None:
        # Só onde maximizar é oferecido: num diálogo, duplo clique não é nada.
        if evento.button() == Qt.MouseButton.LeftButton and self.botao_maximizar is not None:
            self._alternar_maximizada()
            return
        super().mouseDoubleClickEvent(evento)

    def paintEvent(self, _evento: Any) -> None:
        tema = self._provedor.tema
        pintor = QPainter(self)
        fundo = QColor(tema.surface)
        fundo.setAlphaF(0.92)
        pintor.fillRect(self.rect(), fundo)
        pintor.setPen(QColor(tema.border))
        pintor.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        pintor.end()


# ------------------------------------------------------- Bordas de redimensão
class _Borda(QWidget):
    """Uma faixa invisível numa borda ou canto que redimensiona pelo sistema."""

    def __init__(self, janela: QWidget, bordas: Qt.Edge, cursor: Qt.CursorShape) -> None:
        super().__init__(janela)
        self._janela = janela
        self._bordas = bordas
        self.setCursor(cursor)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def mousePressEvent(self, evento: Any) -> None:
        if evento.button() == Qt.MouseButton.LeftButton:
            alca = self._janela.windowHandle()
            if alca is not None:
                alca.startSystemResize(self._bordas)
                return
        super().mousePressEvent(evento)


class GripsRedimensionamento:
    """As oito faixas — quatro bordas e quatro cantos — de uma janela sem moldura.

    Os cantos são criados por último e por isso ficam por cima das bordas na
    área em que se sobrepõem: quem clica na quina espera o cursor diagonal.
    """

    def __init__(self, janela: QWidget) -> None:
        self._janela = janela
        E = Qt.Edge
        C = Qt.CursorShape
        self._faixas = [
            _Borda(janela, E.TopEdge, C.SizeVerCursor),
            _Borda(janela, E.BottomEdge, C.SizeVerCursor),
            _Borda(janela, E.LeftEdge, C.SizeHorCursor),
            _Borda(janela, E.RightEdge, C.SizeHorCursor),
            _Borda(janela, E.TopEdge | E.LeftEdge, C.SizeFDiagCursor),
            _Borda(janela, E.TopEdge | E.RightEdge, C.SizeBDiagCursor),
            _Borda(janela, E.BottomEdge | E.LeftEdge, C.SizeBDiagCursor),
            _Borda(janela, E.BottomEdge | E.RightEdge, C.SizeFDiagCursor),
        ]

    def reposicionar(self) -> None:
        larg, alt = self._janela.width(), self._janela.height()
        e, c = ESPESSURA_BORDA, CANTO
        topo, base, esq, dir_, te, td, be, bd = self._faixas
        topo.setGeometry(c, 0, larg - 2 * c, e)
        base.setGeometry(c, alt - e, larg - 2 * c, e)
        esq.setGeometry(0, c, e, alt - 2 * c)
        dir_.setGeometry(larg - e, c, e, alt - 2 * c)
        te.setGeometry(0, 0, c, c)
        td.setGeometry(larg - c, 0, c, c)
        be.setGeometry(0, alt - c, c, c)
        bd.setGeometry(larg - c, alt - c, c, c)
        for faixa in self._faixas:
            faixa.raise_()

    def definir_ativo(self, ativo: bool) -> None:
        """Maximizada ou em tela cheia, não há o que redimensionar."""
        for faixa in self._faixas:
            faixa.setVisible(ativo)


# ------------------------------------------------------------- Cantos nativos
def aplicar_cantos_do_sistema(janela: QWidget) -> None:
    """Pede ao DWM os cantos arredondados e a sombra do Windows 11.

    Uma janela sem moldura perde os dois. Esta chamada devolve-os onde o
    sistema oferece a API (Windows 11); em qualquer outro lugar falha em
    silêncio e a janela segue de canto reto, sem sombra — inteira funcional.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_ROUND = 2
        preferencia = ctypes.c_int(DWMWCP_ROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            int(janela.winId()),
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(preferencia),
            ctypes.sizeof(preferencia),
        )
    except (OSError, AttributeError):  # pragma: no cover - depende do Windows
        pass
