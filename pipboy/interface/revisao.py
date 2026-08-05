"""Cartões de revisão offline, no tema do jogo.

A mecânica é a do Anki reduzida ao essencial de uma pausa entre partidas:
o termo aparece, o jogador tenta lembrar, revela a resposta e responde com
honestidade — acertei ou errei. Cada resposta alimenta a mesma repetição
espaçada do modo Quiz por voz, mas aqui **sem sessão, sem rede e sem custo**.

Teclado em primeiro lugar: Espaço revela, A acerta, E erra. Quem está com a
outra mão no controle não quer mirar em botão pequeno com o mouse.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import design
from ..revisao import RodadaDeRevisao
from ..vocabulary import VocabularyStore
from .componentes import Botao, caminho_forma

LARGURA = 520


class JanelaRevisao(QDialog):
    """Uma rodada de cartões, modal sobre o caderno.

    ``janela`` é o provedor de tema (a janela principal); ``parent`` é quem
    abriu o diálogo — normalmente o próprio caderno.
    """

    def __init__(
        self, janela: Any, store: VocabularyStore, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent if parent is not None else janela)
        self._janela = janela
        self._store = store
        self._rodada = RodadaDeRevisao(store)
        self._revelado = False

        tema = janela.tema
        self._forma = janela.atmosfera.forma
        self._fundo = tema.surface
        self._borda = tema.border_forte

        self.setWindowTitle("Revisão")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(LARGURA)

        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(30, 24, 30, 22)
        coluna.setSpacing(10)

        def rotulo(nome_fonte: str, cor: str, *, ui: bool = True, wrap: bool = True) -> QLabel:
            etiqueta = QLabel("")
            etiqueta.setFont(janela.fonte(nome_fonte, ui=ui))
            etiqueta.setStyleSheet(
                f"color: {design.garantir_contraste(cor, self._fundo)};"
                " background: transparent;"
            )
            etiqueta.setWordWrap(wrap)
            coluna.addWidget(etiqueta)
            return etiqueta

        self._progresso = rotulo("micro", tema.text_muted)
        coluna.addSpacing(6)
        self._termo = rotulo("display", tema.primary, ui=False)
        self._meta = rotulo("micro", tema.text_muted)
        coluna.addSpacing(10)
        self._traducao = rotulo("corpo", tema.primary)
        self._exemplo = rotulo("vocab", tema.secondary)
        coluna.addSpacing(14)

        acoes = QHBoxLayout()
        acoes.setSpacing(8)
        self._botao_sair = Botao(
            "Encerrar", variante="sutil", paleta=janela.paleta, forma=self._forma
        )
        self._botao_sair.setFont(janela.fonte("corpo_forte"))
        self._botao_sair.clicked.connect(self.reject)
        acoes.addWidget(self._botao_sair)
        acoes.addStretch(1)

        self._botao_errei = Botao(
            "Errei  (E)", variante="perigo", paleta=janela.paleta, forma=self._forma
        )
        self._botao_errei.setFont(janela.fonte("corpo_forte"))
        self._botao_errei.clicked.connect(lambda: self._responder(False))
        acoes.addWidget(self._botao_errei)

        self._botao_acertei = Botao(
            "Acertei  (A)", variante="primario", paleta=janela.paleta, forma=self._forma
        )
        self._botao_acertei.setFont(janela.fonte("corpo_forte"))
        self._botao_acertei.clicked.connect(lambda: self._responder(True))
        acoes.addWidget(self._botao_acertei)

        self._botao_revelar = Botao(
            "Mostrar resposta  (Espaço)",
            variante="primario",
            paleta=janela.paleta,
            forma=self._forma,
        )
        self._botao_revelar.setFont(janela.fonte("corpo_forte"))
        self._botao_revelar.clicked.connect(self._revelar)
        acoes.addWidget(self._botao_revelar)

        self._botao_nova = Botao(
            "Nova rodada", variante="acento", paleta=janela.paleta, forma=self._forma
        )
        self._botao_nova.setFont(janela.fonte("corpo_forte"))
        self._botao_nova.clicked.connect(self._nova_rodada)
        acoes.addWidget(self._botao_nova)
        coluna.addLayout(acoes)

        # Os atalhos moram no diálogo, não nos botões: um botão escondido não
        # dispara atalho, e revelar/responder alternam visibilidade o tempo todo.
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self._revelar)
        QShortcut(QKeySequence("A"), self, activated=lambda: self._responder(True))
        QShortcut(QKeySequence("E"), self, activated=lambda: self._responder(False))

        self._mostrar_cartao()

    # ------------------------------------------------------------ Estados
    def _mostrar_cartao(self) -> None:
        cartao = self._rodada.atual
        if cartao is None:
            self._mostrar_resumo()
            return
        self._revelado = False
        self._progresso.setText(
            f"REVISÃO · CARTÃO {self._rodada.posicao} DE {self._rodada.total}"
        )
        self._termo.setText(cartao.termo)
        partes = [p for p in (cartao.jogo, f"vista {cartao.encontros}×") if p]
        self._meta.setText(" · ".join(partes))
        self._traducao.setText("")
        self._exemplo.setText("")
        self._botao_revelar.show()
        self._botao_errei.hide()
        self._botao_acertei.hide()
        self._botao_nova.hide()
        self._botao_sair.setText("Encerrar")
        self._botao_revelar.setFocus()

    def _revelar(self) -> None:
        cartao = self._rodada.atual
        if cartao is None or self._revelado:
            return
        self._revelado = True
        self._traducao.setText(cartao.traducao)
        self._exemplo.setText(cartao.exemplo)
        self._botao_revelar.hide()
        self._botao_errei.show()
        self._botao_acertei.show()
        self._botao_acertei.setFocus()

    def _responder(self, acertou: bool) -> None:
        if not self._revelado or self._rodada.terminada:
            return  # Responder sem ver a resposta não é revisão, é chute.
        self._rodada.responder(acertou)
        # Revisar offline também conta como dia de estudo na sequência.
        marcar = getattr(self._janela, "marcar_estudo", None)
        if marcar is not None:
            marcar()
        self._mostrar_cartao()

    def _mostrar_resumo(self) -> None:
        self._revelado = False
        restantes = self._store.pendentes()
        if self._rodada.total == 0:
            self._progresso.setText("REVISÃO")
            self._termo.setText("Nada vencido")
            self._meta.setText("Todas as palavras estão agendadas para o futuro.")
        else:
            self._progresso.setText("RODADA CONCLUÍDA")
            self._termo.setText(
                f"{self._rodada.acertos} acertos · {self._rodada.erros} erros"
            )
            self._meta.setText(
                f"{restantes} palavra(s) ainda vencida(s)."
                if restantes
                else "Fila zerada — nada mais vencido por hoje."
            )
        self._traducao.setText("")
        self._exemplo.setText("")
        self._botao_revelar.hide()
        self._botao_errei.hide()
        self._botao_acertei.hide()
        self._botao_nova.setVisible(restantes > 0 and self._rodada.total > 0)
        self._botao_sair.setText("Fechar")
        self._botao_sair.setFocus()

    def _nova_rodada(self) -> None:
        self._rodada = RodadaDeRevisao(self._store)
        self._mostrar_cartao()

    # ------------------------------------------------------------- Pintura
    def paintEvent(self, _evento: Any) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        caminho = caminho_forma(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), self._forma, design.RAIO
        )
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(QColor(self._fundo))
        pintor.drawPath(caminho)
        caneta = QPen(QColor(self._borda))
        caneta.setWidthF(1.0)
        pintor.setPen(caneta)
        pintor.setBrush(Qt.BrushStyle.NoBrush)
        pintor.drawPath(caminho)
        pintor.end()
