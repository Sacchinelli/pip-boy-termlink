"""Modo compacto: o essencial da sessão numa cápsula sobre o jogo.

Este programa foi feito para viver ATRÁS de um jogo — e atrás de um jogo
ninguém vê o medidor, o estado nem se o microfone está mudo. A cápsula
resolve isso: uma janela mínima, sempre no topo, com o estado da sessão, o
nível do microfone, o mudo e a volta para a janela cheia. Quem joga em
janela sem bordas (a maioria) a deixa num canto da tela como um mostrador
de aparelho.

Sem barra de tarefas (``Qt.Tool``), sem moldura, arrastável por qualquer
ponto. O conteúdo se sincroniza com a janela principal por um relógio curto
— nenhum estado é duplicado, a cápsula apenas ESPELHA o que a janela sabe.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QWidget

from .. import design
from .componentes import Medidor, caminho_forma

ALTURA = 56
LARGURA_MIN = 300
INTERVALO_ESPELHO_MS = 150


class _BotaoGlifo(QAbstractButton):
    """Botão mínimo de um glifo só, no vocabulário do tema."""

    def __init__(self, glifo: str, dica: str, janela: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._glifo = glifo
        self._janela = janela
        self.setFixedSize(30, 30)
        self.setToolTip(dica)
        self.setAccessibleName(dica)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def definir_glifo(self, glifo: str) -> None:
        if glifo != self._glifo:
            self._glifo = glifo
            self.update()

    def paintEvent(self, _evento: Any) -> None:
        tema = self._janela.tema
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.underMouse():
            fundo = QColor(tema.primary)
            fundo.setAlphaF(0.12)
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(fundo)
            pintor.drawRoundedRect(QRectF(self.rect()), 6, 6)
        cor = tema.primary if self.underMouse() else tema.text_muted
        pintor.setPen(QColor(design.garantir_contraste(cor, tema.surface)))
        pintor.setFont(self._janela.fonte("corpo"))
        pintor.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._glifo)
        pintor.end()

    def enterEvent(self, evento: Any) -> None:
        self.update()
        super().enterEvent(evento)

    def leaveEvent(self, evento: Any) -> None:
        self.update()
        super().leaveEvent(evento)


class JanelaCompacta(QWidget):
    """A cápsula. Criada uma vez e reutilizada; ``mostrar()`` a posiciona."""

    def __init__(self, janela: Any) -> None:
        super().__init__()
        self._janela = janela
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedHeight(ALTURA)
        self.setMinimumWidth(LARGURA_MIN)
        self.setWindowTitle("Pip-Boy — compacto")

        linha = QHBoxLayout(self)
        linha.setContentsMargins(16, 8, 10, 8)
        linha.setSpacing(10)

        self._estado = QLabel("")
        linha.addWidget(self._estado)
        linha.addStretch(1)

        self._medidor = Medidor()
        self._medidor.setToolTip("Nível do microfone")
        linha.addWidget(self._medidor)

        self._botao_mudo = _BotaoGlifo("○", "Silenciar o microfone", janela, self)
        self._botao_mudo.clicked.connect(janela.alternar_mudo)
        linha.addWidget(self._botao_mudo)

        self._botao_expandir = _BotaoGlifo("◱", "Voltar à janela completa", janela, self)
        self._botao_expandir.clicked.connect(self.expandir)
        linha.addWidget(self._botao_expandir)

        self._espelho = QTimer(self)
        self._espelho.timeout.connect(self._sincronizar)
        self._posicionada = False

        self.aplicar_tema()

    # ------------------------------------------------------------ Ciclo
    def mostrar(self) -> None:
        """Aparece onde o jogador a deixou — ou no canto, na primeira vez."""
        self.aplicar_tema()
        if not self._no_lugar_do_jogador():
            self._encostar_no_canto()
        self.show()
        self.raise_()
        self._espelho.start(INTERVALO_ESPELHO_MS)
        self._sincronizar()

    def _no_lugar_do_jogador(self) -> bool:
        """A cápsula tem uma posição escolhida, e ela ainda é alcançável?

        Arrastar a cápsula para um canto do monitor é a primeira coisa que
        se faz com ela; reposicioná-la no canto a cada entrada no modo
        compacto desfazia essa escolha toda vez. A posição só é descartada
        quando deixa de existir — o monitor onde ela estava foi desligado,
        ou a resolução mudou —, porque aí a alternativa é uma janela
        sempre-no-topo invisível, que é pior que um canto inesperado.
        """
        if not self._posicionada:
            return False
        tela = self.screen() or self._janela.screen()
        if tela is None:
            return True
        return tela.availableGeometry().intersects(self.frameGeometry())

    def _encostar_no_canto(self) -> None:
        tela = self._janela.screen()
        if tela is None:
            return
        area = tela.availableGeometry()
        self.move(area.right() - self.width() - 24, area.top() + 24)
        self._posicionada = True

    def moveEvent(self, evento: Any) -> None:
        super().moveEvent(evento)
        # Qualquer movimento com a cápsula visível veio do jogador: o
        # posicionamento automático acontece antes do show().
        if self.isVisible():
            self._posicionada = True

    def recolher(self) -> None:
        """Esconde a cápsula e para o espelho. Não mexe na janela principal."""
        self._espelho.stop()
        self.hide()

    def expandir(self) -> None:
        self._janela.sair_modo_compacto()

    def closeEvent(self, evento: Any) -> None:
        """Fechar a cápsula é pedir a janela de volta — não sumir com tudo.

        No modo compacto a cápsula é a única janela visível, e ela não tem
        botão na barra de tarefas (``Qt.Tool``). Deixá-la simplesmente
        fechar escondia o programa inteiro: sem cápsula, sem janela
        principal e — numa máquina onde a bandeja não esteja disponível —
        sem nenhum caminho de volta além de matar o processo.

        A exceção é o encerramento: ali quem está fechando a cápsula é a
        própria janela principal, e reabri-la desfaria a saída.
        """
        self._espelho.stop()
        super().closeEvent(evento)
        encerrando = getattr(self._janela, "_encerrando", False)
        if not encerrando and not self._janela.isVisible():
            self._janela.sair_modo_compacto()

    # ------------------------------------------------------------- Espelho
    def _sincronizar(self) -> None:
        # Tudo aqui passa pelo contrato PÚBLICO da janela. A cápsula lia
        # `_worker`, `_mudo` e `_estado_texto` direto: três nomes privados de
        # outro módulo, que qualquer renomeação lá dentro quebraria em silêncio
        # — e num relógio de 150 ms, quebrar em silêncio é quebrar bastante.
        janela = self._janela
        ativa = janela.sessao_ativa
        texto = janela.estado_texto if ativa else janela.tema.idle_text
        if janela.mudo:
            texto = f"{texto} · MUDO"
        self._estado.setText(texto.upper())
        self._medidor.definir_ativo(ativa)
        self._medidor.definir_nivel(janela.nivel_entrada)
        self._botao_mudo.definir_glifo("●" if janela.mudo else "○")

    # -------------------------------------------------------------- Visual
    def aplicar_tema(self) -> None:
        tema = self._janela.tema
        self._estado.setFont(self._janela.fonte("micro"))
        self._estado.setStyleSheet(
            f"color: {design.garantir_contraste(tema.primary, tema.surface)};"
            " background: transparent;"
        )
        self._medidor.definir_cores(
            primary=tema.primary, accent=tema.accent, alert=tema.alert,
            apagada=design.elevar(tema.screen, 0.16, tema.primary),
        )
        # A largura é MEDIDA, não estimada: o maior texto possível do estado
        # (o ocioso do tema mais o sufixo de mudo, em maiúsculas) mais o
        # espaço fixo de medidor, botões, espaçamentos e margens.
        metricas = QFontMetrics(self._janela.fonte("micro"))
        maior_texto = f"{tema.idle_text} · MUDO".upper()
        fixo = (
            design.MEDIDOR_BARRAS
            * (design.MEDIDOR_LARGURA_BARRA + design.MEDIDOR_ESPACO_BARRA)
            + 2 * 30       # os dois botões de glifo
            + 3 * 10 + 26  # espaçamentos e margens do layout
            + 24           # folga de respiro
        )
        self.setFixedWidth(
            max(LARGURA_MIN, metricas.horizontalAdvance(maior_texto) + fixo)
        )
        self.update()

    def paintEvent(self, _evento: Any) -> None:
        tema = self._janela.tema
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        caminho = caminho_forma(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
            self._janela.atmosfera.forma,
            design.RAIO,
        )
        fundo = QColor(tema.surface)
        fundo.setAlphaF(0.94)
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(fundo)
        pintor.drawPath(caminho)
        caneta = QPen(QColor(tema.border_forte))
        caneta.setWidthF(1.0)
        pintor.setPen(caneta)
        pintor.setBrush(Qt.BrushStyle.NoBrush)
        pintor.drawPath(caminho)
        pintor.end()

    # ------------------------------------------------------------- Arrasto
    def mousePressEvent(self, evento: Any) -> None:
        if evento.button() == Qt.MouseButton.LeftButton:
            alca = self.windowHandle()
            if alca is not None:
                alca.startSystemMove()
                return
        super().mousePressEvent(evento)
