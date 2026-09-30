"""Cartões de revisão offline, no tema do jogo.

A mecânica é a do Anki reduzida ao essencial de uma pausa entre partidas:
o termo aparece, o jogador tenta lembrar, revela a resposta e responde com
honestidade — acertei ou errei. Cada resposta alimenta a mesma repetição
espaçada do modo Quiz por voz, mas aqui **sem sessão, sem rede e sem custo**.

Teclado em primeiro lugar: Espaço revela, A acerta, E erra. Quem está com a
outra mão no controle não quer mirar em botão pequeno com o mouse.

Cada gesto tem resposta na tela, e cada resposta diz alguma coisa:

* **A barra da rodada** é uma fileira de segmentos, um por cartão, e cada
  resposta pinta o seu na cor do resultado. No fim, a própria barra é o
  resumo — dá para ver ONDE os erros caíram, não só quantos foram.
* **O recado** diz quando a palavra volta: "em 3 dias", "na próxima rodada".
  A rodada sempre soube isso (``responder`` devolve os dias) e a tela jogava
  fora; é a informação que faz a repetição espaçada deixar de ser mágica.
* **O verso tem lugar reservado.** Revelar não empurra os botões: o polegar
  que apertou Espaço aperta A no mesmo lugar.
* **O cartão respondido sai deslizando** enquanto o próximo entra, e a borda
  acende na cor do resultado. Com a atmosfera desligada, tudo acontece num
  quadro — o recado e a barra continuam dizendo o que houve.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFontMetrics, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import design
from ..revisao import RodadaDeRevisao
from ..vocabulary import VocabularyStore
from .atmosfera import ATENUACAO_NO_FUNDO_NU, Cenario, so_o_cursor
from .componentes import Botao, RotuloElidido, acender_borda, caminho_forma
from .cursor import CursorVivo
from .movimento import ImagemQueSai, Transicao, animar_entrada

LARGURA = 520


def _plural(quantidade: int, singular: str, plural: str) -> str:
    return f"{quantidade} {singular if quantidade == 1 else plural}"


def quando_volta(dias: int) -> str:
    """Os dias até a próxima revisão, ditos como se diz."""
    if dias <= 0:
        return "na próxima rodada"
    if dias == 1:
        return "amanhã"
    return f"em {dias} dias"


class BarraDaRodada(QWidget):
    """Um segmento por cartão, pintado na cor do resultado quando respondido."""

    ALTURA = 4
    VAO = 3

    def __init__(self, janela: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._janela = janela
        self._total = 0
        self.resultados: list[bool] = []
        self._chegada = Transicao(
            self, design.DURACAO_MEDIA, lambda _v: self.update(),
            reduzir=lambda: bool(janela.intensidade_atmosfera <= 0.0),
        )
        self._chegada.saltar(1.0)
        self.setFixedHeight(self.ALTURA)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def recomecar(self, total: int) -> None:
        self._total = total
        self.resultados = []
        self._chegada.saltar(1.0)
        self.setVisible(total > 0)
        self.update()

    def registrar(self, acertou: bool) -> None:
        self.resultados.append(acertou)
        # O segmento recém-respondido acende a partir do cinza, em vez de
        # simplesmente já estar colorido quando o olho chega nele.
        self._chegada.saltar(0.0)
        self._chegada.ir(1.0)

    def paintEvent(self, _evento: Any) -> None:
        if self._total <= 0:
            return
        t = self._janela.tema
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        pintor.setPen(Qt.PenStyle.NoPen)
        largura = (self.width() - self.VAO * (self._total - 1)) / self._total
        raio = 1.0 if self._janela.atmosfera.forma != "arredondada" else self.ALTURA / 2
        respondidos = len(self.resultados)
        for indice in range(self._total):
            if indice < respondidos:
                cor = t.primary if self.resultados[indice] else t.alert
                if indice == respondidos - 1:
                    cor = design.misturar(t.border, cor, self._chegada.valor)
            elif indice == respondidos:
                # O da vez só se distingue do pendente; com mais que isto ele
                # se confundia com um acerto já pintado ao lado.
                cor = design.misturar(t.border, t.primary, 0.22)
            else:
                cor = t.border
            pintor.setBrush(QColor(cor))
            x = indice * (largura + self.VAO)
            pintor.drawRoundedRect(QRectF(x, 0.0, largura, float(self.ALTURA)), raio, raio)
        pintor.end()


class JanelaRevisao(QDialog):
    """Uma rodada de cartões, modal sobre o caderno.

    ``janela`` é o provedor de tema (a janela principal); ``parent`` é quem
    abriu o diálogo — normalmente o próprio caderno.
    """

    DESLIZE_SAIDA = -36.0

    def __init__(
        self, janela: Any, store: VocabularyStore, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent if parent is not None else janela)
        self._janela = janela
        self._store = store
        self._rodada = RodadaDeRevisao(store)
        self._revelado = False

        tema = janela.tema
        self._tema = tema
        self._forma = janela.atmosfera.forma
        self._fundo = tema.surface
        self._borda = tema.border_forte
        self._cor_lampejo = tema.primary

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
            return etiqueta

        topo = QHBoxLayout()
        topo.setSpacing(12)
        self._progresso = rotulo("micro", tema.text_muted, wrap=False)
        topo.addWidget(self._progresso)
        topo.addStretch(1)
        self._recado = RotuloElidido()
        self._recado.setFont(janela.fonte("micro"))
        self._recado.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        topo.addWidget(self._recado, 1)
        coluna.addLayout(topo)

        self._barra = BarraDaRodada(janela)
        coluna.addWidget(self._barra)
        coluna.addSpacing(8)

        # O cartão é um bloco próprio para poder ser fotografado inteiro na
        # troca: termo, metadados e verso saem juntos.
        self._cartao = QWidget()
        pilha = QVBoxLayout(self._cartao)
        pilha.setContentsMargins(0, 0, 0, 0)
        pilha.setSpacing(10)
        self._termo = rotulo("display", tema.primary, ui=False)
        self._meta = rotulo("micro", tema.text_muted)
        pilha.addWidget(self._termo)
        pilha.addWidget(self._meta)
        pilha.addSpacing(4)

        verso = QWidget()
        pilha_verso = QVBoxLayout(verso)
        pilha_verso.setContentsMargins(0, 0, 0, 0)
        pilha_verso.setSpacing(6)
        self._dica = rotulo("legenda", tema.text_muted)
        self._dica.setText("Tente lembrar antes de revelar.")
        self._traducao = rotulo("corpo", tema.primary)
        self._exemplo = rotulo("vocab", tema.secondary)
        for item in (self._dica, self._traducao, self._exemplo):
            pilha_verso.addWidget(item)
        pilha_verso.addStretch(1)
        # Lugar reservado para uma tradução e duas linhas de exemplo: o caso
        # comum cabe sem mexer em nada. Um exemplo mais longo ainda cresce o
        # verso, e só aí os botões descem.
        verso.setMinimumHeight(
            QFontMetrics(janela.fonte("corpo")).lineSpacing()
            + 2 * QFontMetrics(janela.fonte("vocab", ui=False)).lineSpacing()
            + pilha_verso.spacing()
        )
        self._verso = verso
        pilha.addWidget(verso)
        coluna.addWidget(self._cartao)
        coluna.addSpacing(10)

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
        # As ações são puxadas pelo cursor que se aproxima, como na janela
        # principal. Quem responde pelo teclado não é afetado.
        for botao in (
            self._botao_sair, self._botao_errei, self._botao_acertei,
            self._botao_revelar, self._botao_nova,
        ):
            botao.tornar_magnetico(4)
        # A mesma resposta ao cursor das outras janelas: luz pelo fundo, anel,
        # ondas, rastro e as bordas acesas. Sem movimento próprio no cenário —
        # quem está revisando está lendo uma palavra —, o relógio daqui só corre
        # enquanto o cursor se mexe.
        self._cenario = Cenario()
        self._cenario.definir_intensidade(janela.intensidade_atmosfera)
        self._cenario.movimento = janela.intensidade_atmosfera > 0.0
        self._cenario.definir(janela.tema, so_o_cursor(janela.atmosfera))
        self._cursor_vivo = CursorVivo(
            self, self._cenario, cor=lambda: self._janela.tema.accent
        )
        self._campo_magnetico = self._cursor_vivo.campo

        # A borda acende na cor do resultado e apaga: sobe rápido, desce devagar.
        self._lampejo = 0.0
        self._animacao_lampejo = QVariantAnimation(self)
        self._animacao_lampejo.setDuration(520)
        self._animacao_lampejo.setStartValue(0.0)
        self._animacao_lampejo.setKeyValueAt(0.2, 1.0)
        self._animacao_lampejo.setEndValue(0.0)
        self._animacao_lampejo.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._animacao_lampejo.valueChanged.connect(self._repintar_lampejo)

        # Os atalhos moram no diálogo, não nos botões: um botão escondido não
        # dispara atalho, e revelar/responder alternam visibilidade o tempo todo.
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self._revelar)
        QShortcut(QKeySequence("A"), self, activated=lambda: self._responder(True))
        QShortcut(QKeySequence("E"), self, activated=lambda: self._responder(False))

        self._barra.recomecar(self._rodada.total)
        self._mostrar_cartao()

    # ------------------------------------------------------------ Estados
    def _movimento_reduzido(self) -> bool:
        return bool(self._janela.intensidade_atmosfera <= 0.0)

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
        self._traducao.hide()
        self._exemplo.hide()
        self._dica.show()
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
        self._dica.hide()
        self._traducao.setText(cartao.traducao)
        self._exemplo.setText(cartao.exemplo)
        self._traducao.show()
        self._exemplo.setVisible(bool(cartao.exemplo))
        animar_entrada(
            [w for w in (self._traducao, self._exemplo) if not w.isHidden()],
            reduzir=self._movimento_reduzido(),
        )
        self._botao_revelar.hide()
        self._botao_errei.show()
        self._botao_acertei.show()
        self._botao_acertei.setFocus()

    def _responder(self, acertou: bool) -> None:
        if not self._revelado or self._rodada.terminada:
            return  # Responder sem ver a resposta não é revisão, é chute.
        cartao = self._rodada.atual
        assert cartao is not None  # garantido por `terminada` acima
        dias = self._rodada.responder(acertou)
        # Revisar offline também conta como dia de estudo na sequência.
        #
        # Chamada direta, sem getattr defensivo: `marcar_estudo` faz parte do
        # contrato da janela. O getattr que havia aqui transformaria uma
        # renomeação em silêncio — a sequência de estudo simplesmente pararia
        # de contar, e ninguém descobriria por meses.
        self._janela.marcar_estudo()

        t = self._tema
        cor = t.primary if acertou else t.alert
        self._barra.registrar(acertou)
        self._recado.setStyleSheet(
            f"color: {design.garantir_contraste(cor, self._fundo)}; background: transparent;"
        )
        self._recado.definir_texto(f"{cartao.termo} volta {quando_volta(dias)}")

        retrato = None if self._movimento_reduzido() else self._cartao.grab()
        self._mostrar_cartao()
        if retrato is not None:
            ImagemQueSai(self._cartao, retrato, deslocamento=QPointF(self.DESLIZE_SAIDA, 0.0))
            animar_entrada(
                [w for w in (self._termo, self._meta, self._dica) if not w.isHidden()],
                reduzir=False,
            )
            animar_entrada([self._recado], reduzir=False)
            self._cor_lampejo = cor
            self._animacao_lampejo.stop()
            self._animacao_lampejo.start()

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
                f"{_plural(self._rodada.acertos, 'acerto', 'acertos')} · "
                f"{_plural(self._rodada.erros, 'erro', 'erros')}"
            )
            self._meta.setText(
                f"{_plural(restantes, 'palavra ainda vencida', 'palavras ainda vencidas')}."
                if restantes
                else "Fila zerada — nada mais vencido por hoje."
            )
        self._traducao.setText("")
        self._exemplo.setText("")
        # O verso fica vazio, mas fica: some com ele e o resumo inteiro desce,
        # porque o diálogo mantém a altura que tinha. A barra acima já é o
        # retrato da rodada.
        for item in (self._dica, self._traducao, self._exemplo):
            item.hide()
        self._botao_revelar.hide()
        self._botao_errei.hide()
        self._botao_acertei.hide()
        self._botao_nova.setVisible(restantes > 0 and self._rodada.total > 0)
        self._botao_sair.setText("Fechar")
        self._botao_sair.setFocus()

    def _nova_rodada(self) -> None:
        self._rodada = RodadaDeRevisao(self._store)
        self._barra.recomecar(self._rodada.total)
        self._recado.definir_texto("")
        self._mostrar_cartao()
        animar_entrada(
            [w for w in (self._termo, self._meta, self._dica) if not w.isHidden()],
            reduzir=self._movimento_reduzido(),
        )

    # ------------------------------------------------------------- Moldura
    def resizeEvent(self, evento: Any) -> None:
        super().resizeEvent(evento)
        if hasattr(self, "_cursor_vivo"):
            self._cursor_vivo.reposicionar()

    def showEvent(self, evento: Any) -> None:
        super().showEvent(evento)
        self._cursor_vivo.reposicionar()

    def hideEvent(self, evento: Any) -> None:
        super().hideEvent(evento)
        # Escondida, ela não recebe o aviso de que o cursor saiu.
        self._cursor_vivo.esquecer()

    # ------------------------------------------------------------- Pintura
    def _repintar_lampejo(self, valor: Any) -> None:
        self._lampejo = float(valor)
        self.update()

    def paintEvent(self, _evento: Any) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        caminho = caminho_forma(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), self._forma, design.RAIO
        )
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(QColor(self._fundo))
        pintor.drawPath(caminho)
        # A luz do cursor sobre o fundo liso, recortada na moldura e atenuada:
        # aqui não há painel translúcido na frente dela.
        pintor.save()
        pintor.setClipPath(caminho)
        self._cenario.pintar_luz(pintor, atenuacao=ATENUACAO_NO_FUNDO_NU)
        pintor.restore()
        acender_borda(pintor, self, caminho)
        caneta = QPen(QColor(design.misturar(self._borda, self._cor_lampejo, self._lampejo)))
        caneta.setWidthF(1.0 + self._lampejo)
        pintor.setPen(caneta)
        pintor.setBrush(Qt.BrushStyle.NoBrush)
        pintor.drawPath(caminho)
        pintor.end()
