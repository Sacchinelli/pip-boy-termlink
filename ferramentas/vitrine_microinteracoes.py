"""Vitrine de microinterações: o cartão do caderno reagindo a quem chega.

Uso:  py ferramentas/vitrine_microinteracoes.py

Protótipo para decidir a DIREÇÃO antes de mexer no programa. Nada aqui abre
sessão, lê a chave ou toca no caderno de verdade: as palavras são montadas em
memória e a exportação é um cronômetro. Pode clicar em tudo.

O que está em teste, cada peça numa classe que se muda inteira para
``componentes.py`` se for aprovada:

* ``Transicao`` — um número de 0 a 1 que muda de ideia no meio do caminho sem
  pular e sem gastar o tempo inteiro para voltar.
* ``CartaoVivo`` — o cartão do caderno com luz que segue o cursor, contorno que
  acende perto dele e ações que aparecem quando alguém chega — pelo mouse OU
  pelo teclado.
* ``EfeitoEntrada`` — cartões que sobem e aparecem em cascata.
* ``BotaoDeEstado`` — ocioso → trabalhando → concluído, sem mudar de largura.

A regra que atravessa todas: no hover só se anima o que é PINTURA — cor, luz,
opacidade, deslocamento desenhado. Geometria de layout, nunca: um cartão que
cresce sob o cursor empurra a lista e tira do lugar o alvo do próximo clique.
A única exceção é a saída de um cartão removido, porque ali a mudança de
layout é justamente o que precisa ser visto.
"""

from __future__ import annotations

import math
import sys
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import (
    Property,
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QObject,
    QParallelAnimationGroup,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSequentialAnimationGroup,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QEnterEvent,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QHoverEvent,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pipboy import design
from pipboy.config import movimento_reduzido
from pipboy.interface.atmosfera import ATMOSFERAS, Cenario
from pipboy.interface.caderno import _plural, _selo
from pipboy.interface.componentes import (
    Botao,
    CampoSelecao,
    TransicaoDeTema,
    caminho_forma,
    css_campo_selecao,
)
from pipboy.interface.estilo import RAIO_PADRAO, RAIO_POR_FORMA, rgba
from pipboy.themes import DEFAULT_TEMA, TEMAS, GameTheme, paleta_de
from pipboy.vocabulary import DIAS_PARA_DOMINIO, Entrada


class Tipografia:
    """A rampa tipográfica da janela para um tema, sem precisar da janela.

    A vitrine nasceu em cima do ramo que tira a rampa para
    ``pipboy/interface/tipografia.py`` (PR #19). Enquanto ele não entra, esta
    cópia mínima faz o mesmo papel, pela mesma regra de ``Janela.fonte``: a
    primeira família candidata instalada nesta máquina, a última como reserva,
    no degrau pedido da rampa de ``design.TIPO``.
    """

    def __init__(self, tema: GameTheme) -> None:
        self._tema = tema
        self._instaladas = set(QFontDatabase.families())

    def definir_tema(self, tema: GameTheme) -> None:
        self._tema = tema

    def fonte(self, papel: str, *, ui: bool = True) -> QFont:
        candidatas = self._tema.ui_font_candidates if ui else self._tema.font_candidates
        familia = next((nome for nome in candidatas if nome in self._instaladas), candidatas[-1])
        tipo = design.TIPO[papel]
        fonte = QFont(familia, tipo.tamanho)
        fonte.setBold(tipo.peso == "bold")
        fonte.setItalic(tipo.estilo == "italic")
        return fonte

# ------------------------------------------------------------ Tokens de movimento
# Três durações e nenhuma outra. Assim como a grade de 4 px, é a escala que faz
# a interface parecer uma só: o olho percebe quando cada peça anda num tempo.
#
# RÁPIDO responde ao cursor — acima de ~150 ms a luz parece correr ATRÁS do
# mouse. MÉDIO é para o que aparece ou muda de estado. LENTO é para o que entra
# em cena, e só entra uma vez.
RAPIDO = 140
MEDIO = 220
LENTO = 340
# Atraso entre um cartão e o seguinte na entrada em cascata. Com mais que isso,
# uma lista de dez cartões leva meio segundo para ficar legível.
ESCALONAMENTO = 45


class Transicao(QObject):
    """Progresso de 0 a 1 que pode mudar de destino a qualquer momento.

    O ``Botao`` já faz isto à mão, em ``_animar``; aqui a receita vira peça.
    A diferença que importa está em ``ir``: a duração é PROPORCIONAL à
    distância. Sem isso, passar o cursor de raspão por um cartão — acender até
    20% e sair — gasta a duração inteira para apagar 20%, e a luz fica
    grudada atrás do mouse. É o detalhe que separa fluido de atrasado.
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
            # Movimento reduzido não é "sem resposta": o estado final chega
            # na hora. O que some é o caminho, não o destino.
            self._definir(destino)
            return
        self._animacao.setDuration(max(1, round(self._duracao * distancia)))
        self._animacao.setStartValue(self.valor)
        self._animacao.setEndValue(destino)
        self._animacao.start()

    def saltar(self, valor: float) -> None:
        self._animacao.stop()
        self._definir(valor)

    def _definir(self, valor: Any) -> None:
        self.valor = float(valor)
        self._ao_mudar(self.valor)


# --------------------------------------------------------------------- Entrada
class EfeitoEntrada(QGraphicsEffect):
    """Desenha o widget subindo e aparecendo, sem mexer na geometria dele.

    Um ``QGraphicsOpacityEffect`` só faz metade: aparece no lugar. Mover o
    widget de verdade brigaria com o layout, que o devolve ao lugar na próxima
    passagem. Aqui o deslocamento existe só na pintura — o layout nem fica
    sabendo — e o efeito é descartado ao fim, pela mesma razão documentada em
    ``Bolha.animar_entrada``: efeito pendurado custa uma superfície fora da tela
    em toda repintura.
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
        # Só para baixo: o widget parte de SUBIDA px abaixo do lugar final. Não
        # estender para cima mantém a imagem da fonte ancorada em (0, 0).
        return QRectF(retangulo).adjusted(0, 0, 0, self.SUBIDA)

    def draw(self, pintor: QPainter) -> None:
        # Sempre pela imagem, mesmo no quadro final: ``drawSource`` pintaria os
        # filhos com o mesmo pintor, e a auréola de um Botao lá dentro — outro
        # efeito — reclamaria. Ver ``CartaoVivo._aplicar_revelacao``.
        imagem = self.sourcePixmap(Qt.CoordinateSystem.LogicalCoordinates)
        pintor.save()
        pintor.setOpacity(self._progresso)
        pintor.drawPixmap(QPointF(0.0, (1.0 - self._progresso) * self.SUBIDA), imagem)
        pintor.restore()


def animar_entrada(widgets: Sequence[QWidget], *, reduzir: bool) -> None:
    """Cascata: cada widget sobe e aparece ESCALONAMENTO ms depois do anterior.

    A ordem conduz o olho de cima para baixo, na ordem de leitura. Todos juntos
    seriam um clarão; um de cada vez devagar seria uma espera.
    """
    if reduzir:
        return
    for ordem, widget in enumerate(widgets):
        efeito = EfeitoEntrada(widget)
        widget.setGraphicsEffect(efeito)
        grupo = QSequentialAnimationGroup(widget)
        grupo.addPause(ordem * ESCALONAMENTO)
        subida = QPropertyAnimation(efeito, b"progresso", grupo)
        subida.setDuration(LENTO)
        subida.setStartValue(0.0)
        subida.setEndValue(1.0)
        subida.setEasingCurve(QEasingCurve.Type.OutCubic)
        grupo.addAnimation(subida)

        def encerrar(alvo: QWidget = widget, proprio: EfeitoEntrada = efeito) -> None:
            # Uma segunda entrada pode ter trocado o efeito no meio desta; só
            # se remove o que ainda é nosso.
            if alvo.graphicsEffect() is proprio:
                alvo.setGraphicsEffect(None)  # type: ignore[arg-type]

        grupo.finished.connect(encerrar)
        grupo.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


# ---------------------------------------------------------------------- Cartão
class CartaoVivo(QFrame):
    """Uma palavra do caderno que percebe quem chega perto.

    Três respostas, em três tempos:

    1. **Luz, na hora.** Um holofote na cor do tema acompanha o cursor e o
       contorno acende do lado dele. É a resposta mais barata e a mais
       imediata: diz "este é o cartão sob o mouse" antes de qualquer decisão.
    2. **Ações, depois de uma pausa.** Os três botões só aparecem se o cursor
       PARAR no cartão (``INTENCAO_MS``). Varrer a lista com o mouse acende
       cada cartão de passagem, mas não faz trinta fileiras de botões piscarem.
    3. **Teclado vale o mesmo que mouse.** Tab até um botão revela as ações na
       hora e leva a luz até ele. Esconder controles no hover sem isso é
       trancar o teclado para fora — o erro clássico desse padrão.

    O que é revelado são AÇÕES, que repetem em todo cartão; nunca INFORMAÇÃO.
    O estado de revisão, a tradução e o exemplo ficam sempre à vista, porque
    é com eles que se decide o que fazer.
    """

    ALCANCE_LUZ = 260.0
    INTENCAO_MS = 70
    DESLIZE = 10.0
    TAMANHO_ACAO = 28
    MARGENS = (18, 14, 14, 12)  # esquerda, topo, direita, base

    def __init__(
        self,
        entrada: Entrada,
        *,
        tema: GameTheme,
        forma: str,
        tipografia: Tipografia,
        reduzir: Callable[[], bool],
        ao_remover: Callable[[CartaoVivo], None],
        ao_agir: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.entrada = entrada
        self._tema = tema
        self._forma = forma
        self._reduzir = reduzir
        self._fundo = tema.surface_alta
        self._cursor: QPointF | None = None
        self._sob_cursor = False
        self._foco: QWidget | None = None
        self._saindo = False

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        # HoverMove, e não mouseMoveEvent: o Qt DESCARTA o movimento sem botão
        # que cai sobre um filho sem rastreamento — ele não sobe para o pai.
        # Com rastreamento só no cartão, a luz congelava assim que o cursor
        # passava sobre a tradução ou o exemplo, que são quase o cartão todo.
        # O HoverMove, ao contrário, é entregue a TODO ancestral com WA_Hover.
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

        self._luz = Transicao(self, RAPIDO, lambda _v: self.update(), reduzir=reduzir)
        self._revelacao = Transicao(self, MEDIO, self._aplicar_revelacao, reduzir=reduzir)
        self._intencao = QTimer(self)
        self._intencao.setSingleShot(True)
        self._intencao.setInterval(self.INTENCAO_MS)
        self._intencao.timeout.connect(self._confirmar_intencao)

        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(*self.MARGENS)
        coluna.setSpacing(4)

        def rotulo(texto: str, papel_fonte: str, papel_cor: str, *, tema_fonte: bool = False) -> QLabel:
            item = QLabel(texto)
            item.setFont(tipografia.fonte(papel_fonte, ui=not tema_fonte))
            cor = design.garantir_contraste(getattr(tema, papel_cor), self._fundo)
            item.setStyleSheet(
                f"color: {cor}; background: transparent;"
                f" {design.css_selecao(self._fundo, tema.accent, cor)}"
            )
            return item

        topo = QHBoxLayout()
        topo.setSpacing(10)
        termo = rotulo(entrada.termo, "titulo", "primary", tema_fonte=True)
        termo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        topo.addWidget(termo)
        topo.addStretch(1)
        texto_selo, papel_selo = _selo(entrada)
        topo.addWidget(rotulo(texto_selo, "micro", papel_selo))
        coluna.addLayout(topo)

        traducao = rotulo(entrada.traducao, "corpo", "primary")
        traducao.setWordWrap(True)
        traducao.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        coluna.addWidget(traducao)

        if entrada.exemplo:
            exemplo = rotulo(entrada.exemplo, "vocab", "info", tema_fonte=True)
            exemplo.setWordWrap(True)
            exemplo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            coluna.addWidget(exemplo)

        # As ações moram no canto de baixo, que em repouso já é espaço vazio:
        # o rodapé é curto e alinhado à esquerda. Revelar ali não abre um
        # buraco no cartão parado, e o espaço é reservado desde o início —
        # aparecer nunca empurra texto.
        self._acoes = QWidget(self)
        fila = QHBoxLayout(self._acoes)
        fila.setContentsMargins(0, 0, 0, 0)
        fila.setSpacing(4)
        cores = paleta_de(tema)
        for simbolo, variante, papel_fonte, dica, acao in (
            ("◷", "sutil", "corpo_forte", "Abrir a conversa em que a palavra nasceu",
             lambda: ao_agir(f"Abriria a conversa em que “{entrada.termo}” apareceu.")),
            ("▤", "sutil", "corpo_forte", "Corrigir o texto sem perder a revisão",
             lambda: ao_agir(f"Abriria a correção de “{entrada.termo}”.")),
            ("×", "perigo_sutil", "titulo", "Remover do caderno",
             lambda: ao_remover(self)),
        ):
            botao = Botao(simbolo, variante=variante, paleta=lambda: cores, forma=forma)
            botao.setFont(tipografia.fonte(papel_fonte))
            botao.setFixedSize(self.TAMANHO_ACAO, self.TAMANHO_ACAO)
            botao.setToolTip(dica)
            botao.setAccessibleName(f"{dica}: {entrada.termo}")
            botao.clicked.connect(acao)
            botao.installEventFilter(self)
            fila.addWidget(botao)
        self._acoes.adjustSize()
        self._opacidade = QGraphicsOpacityEffect(self._acoes)
        self._acoes.setGraphicsEffect(self._opacidade)

        base = QHBoxLayout()
        base.setSpacing(8)
        partes = [entrada.jogo, _plural(entrada.encontros, "encontro", "encontros")]
        if entrada.acertos or entrada.erros:
            partes.append(
                f"{_plural(entrada.acertos, 'acerto', 'acertos')} · "
                f"{_plural(entrada.erros, 'erro', 'erros')}"
            )
        rodape = rotulo("   ·   ".join(p for p in partes if p), "micro", "secondary")
        rodape.setMinimumHeight(self.TAMANHO_ACAO)
        base.addWidget(rodape, 1)
        base.addSpacing(self._acoes.width())
        coluna.addLayout(base)

        self._aplicar_revelacao(0.0)

    # -- presença: mouse e teclado alimentam o mesmo estado
    def enterEvent(self, evento: QEnterEvent) -> None:
        self._sob_cursor = True
        self._cursor = evento.position()
        self._atualizar_presenca()
        super().enterEvent(evento)

    def leaveEvent(self, evento: QEvent) -> None:
        self._sob_cursor = False
        self._atualizar_presenca()
        super().leaveEvent(evento)

    def event(self, evento: QEvent) -> bool:
        if evento.type() == QEvent.Type.HoverMove and isinstance(evento, QHoverEvent):
            self._cursor = evento.position()
            if self._luz.valor > 0.0 and not self._reduzir():
                self.update()
        return super().event(evento)

    def eventFilter(self, alvo: QObject, evento: QEvent) -> bool:
        if evento.type() == QEvent.Type.FocusIn and isinstance(alvo, QWidget):
            self._foco = alvo
            self._atualizar_presenca()
        elif evento.type() == QEvent.Type.FocusOut and alvo is self._foco:
            self._foco = None
            self._atualizar_presenca()
        return super().eventFilter(alvo, evento)

    def _atualizar_presenca(self) -> None:
        if self._saindo:
            return
        presente = self._sob_cursor or self._foco is not None
        self._luz.ir(1.0 if presente else 0.0)
        if self._foco is not None:
            self._intencao.stop()
            self._revelacao.ir(1.0)
        elif self._sob_cursor:
            if self._revelacao.valor < 1.0 and not self._intencao.isActive():
                self._intencao.start()
        else:
            self._intencao.stop()
            self._revelacao.ir(0.0)

    def _confirmar_intencao(self) -> None:
        if self._sob_cursor:
            self._revelacao.ir(1.0)

    def _aplicar_revelacao(self, valor: float) -> None:
        self._opacidade.setOpacity(valor)
        # Desligado quando opaco, e não por economia. Em opacidade EXATAMENTE
        # 1.0 o QGraphicsOpacityEffect pega um atalho: pinta os filhos direto,
        # com o mesmo pintor. A auréola de cada Botao é outro efeito, que tenta
        # abrir um segundo pintor no mesmo dispositivo — e cada repintura do
        # cartão aceso cuspia "A paint device can only be painted by one
        # painter at a time". Abaixo de 1.0 o efeito pinta numa imagem antes,
        # e o aninhamento funciona (é o que a Bolha faz com o brilho de
        # fósforo). Em zero ele fica LIGADO: é o que mantém os botões
        # invisíveis sem tirá-los da ordem do Tab.
        self._opacidade.setEnabled(valor < 1.0)
        # Botão quase invisível não pode receber clique: o "×" apagaria uma
        # palavra que a pessoa nem viu que estava ali.
        self._acoes.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, valor < 0.35)
        self._posicionar_acoes()

    def _posicionar_acoes(self) -> None:
        _, _, direita, base = self.MARGENS
        deslize = round((1.0 - self._revelacao.valor) * self.DESLIZE)
        self._acoes.move(
            self.width() - direita - self._acoes.width() + deslize,
            self.height() - base - self._acoes.height(),
        )

    def resizeEvent(self, evento: Any) -> None:
        super().resizeEvent(evento)
        self._posicionar_acoes()

    # -- saída
    def sair(self, ao_terminar: Callable[[], None]) -> None:
        """Some e fecha o espaço que ocupava, em vez de sumir num quadro.

        Sem a transição, o cartão de baixo salta para cima e o olho perde qual
        palavra saiu. Esmaecer primeiro e recolher logo atrás mantém a
        continuidade: dá para ver a lista se fechando sobre o buraco.
        """
        if self._reduzir():
            ao_terminar()
            return
        # Congela o cartão como está. Uma revelação ainda em curso deixaria o
        # efeito das ações LIGADO sob o esmaecer, que começa em 1.0 — o atalho
        # descrito em ``_aplicar_revelacao``, com um efeito embaixo.
        self._saindo = True
        self._intencao.stop()
        self._revelacao.saltar(1.0)
        self._acoes.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        # O esmaecer abaixo começa em 1.0 — o mesmo atalho de
        # ``_aplicar_revelacao``, agora com as auréolas dois níveis abaixo.
        # Um cartão de saída não precisa de auréola nenhuma.
        for botao in self._acoes.findChildren(Botao):
            efeito = botao.graphicsEffect()
            if efeito is not None:
                efeito.setEnabled(False)
        efeito = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(efeito)
        grupo = QParallelAnimationGroup(self)
        esmaecer = QPropertyAnimation(efeito, b"opacity", grupo)
        esmaecer.setDuration(RAPIDO)
        esmaecer.setStartValue(1.0)
        esmaecer.setEndValue(0.0)
        recolher = QPropertyAnimation(self, b"maximumHeight", grupo)
        recolher.setDuration(MEDIO)
        recolher.setStartValue(self.height())
        recolher.setEndValue(0)
        recolher.setEasingCurve(QEasingCurve.Type.InOutCubic)
        grupo.addAnimation(esmaecer)
        grupo.addAnimation(recolher)
        grupo.finished.connect(ao_terminar)
        grupo.start()

    # -- desenho
    def _centro_da_luz(self) -> QPointF:
        if self._foco is not None and not self._sob_cursor:
            return QPointF(self._foco.mapTo(self, self._foco.rect().center()))
        if self._reduzir() or self._cursor is None:
            # Luz parada no alto, como uma luminária: o cartão ainda se destaca,
            # só não persegue o cursor.
            return QPointF(self.width() * 0.3, 0.0)
        return self._cursor

    def paintEvent(self, _evento: Any) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self._tema
        luz = self._luz.valor
        area = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        caminho = caminho_forma(area, self._forma, design.RAIO)

        # 1. A superfície sobe um degrau. Elevação em tema escuro é luz, não
        #    sombra: sombra preta sobre fundo quase preto não se vê.
        elevada = design.elevar(self._fundo, 0.07, t.primary)
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(QColor(design.misturar(self._fundo, elevada, luz)))
        pintor.drawPath(caminho)

        centro = self._centro_da_luz()
        if luz > 0.005:
            # 2. O holofote, somado à superfície — mesma regra do módulo de
            #    componentes: brilho é aditivo, e por isso parece luz, não tinta.
            pintor.save()
            pintor.setClipPath(caminho)
            pintor.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            holofote = QRadialGradient(centro, self.ALCANCE_LUZ)
            perto = QColor(t.primary)
            perto.setAlphaF(0.11 * luz)
            longe = QColor(perto)
            longe.setAlphaF(0.0)
            holofote.setColorAt(0.0, perto)
            holofote.setColorAt(1.0, longe)
            pintor.fillRect(area, holofote)
            pintor.restore()

        # 3. O contorno: um fio discreto em repouso que acende do lado do
        #    cursor. O gradiente radial na CANETA é o que faz a borda parecer
        #    iluminada pela mesma luz, e não pintada de outra cor.
        repouso = QColor(t.border)
        if luz > 0.005:
            fio = QRadialGradient(centro, self.ALCANCE_LUZ * 0.8)
            fio.setColorAt(0.0, QColor(design.misturar(t.border, t.primary, 0.75 * luz)))
            fio.setColorAt(1.0, repouso)
            caneta = QPen(QBrush(fio), 1.2)
        else:
            caneta = QPen(repouso, 1.0)
        pintor.setPen(caneta)
        pintor.setBrush(Qt.BrushStyle.NoBrush)
        pintor.drawPath(caminho)
        pintor.end()


# ------------------------------------------------------------ Botão com estado
class BotaoDeEstado(Botao):
    """Ocioso → trabalhando → concluído → ocioso, sem mudar de largura.

    Três decisões de feedback:

    * **A largura é a do maior rótulo.** Um botão que encolhe ao virar
      "Exportado" desloca o que está ao lado no instante em que a pessoa olha.
    * **Trabalhando não desabilita.** Desabilitar tira o foco do teclado e
      apaga a cor justo quando o botão é a coisa mais importante da tela. O
      clique repetido é ignorado em ``iniciar``, e o cursor vira ocupado.
    * **Sucesso muda a MATÉRIA, não só o texto.** O contorno se enche de cor e
      o sinal de visto se desenha traço a traço. Um rótulo trocando sozinho
      passa despercebido; uma superfície que se enche, não.

    Herda do ``Botao`` o hover, a pressão, a auréola e o foco — só a pintura
    é própria.
    """

    RETORNO_MS = 1800

    def __init__(
        self,
        rotulos: dict[str, str],
        *,
        paleta: Callable[[], dict[str, str]],
        forma: str,
        reduzir: Callable[[], bool],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(rotulos["ocioso"], variante="acento", paleta=paleta, forma=forma, parent=parent)
        self._rotulos = rotulos
        self._estado = "ocioso"
        self._anterior = "ocioso"
        self._reduzir = reduzir
        self._angulo = 0.0

        self._giro = QVariantAnimation(self)
        self._giro.setStartValue(0.0)
        self._giro.setEndValue(360.0)
        self._giro.setDuration(900)
        self._giro.setLoopCount(-1)
        self._giro.valueChanged.connect(self._girar)
        self._troca = Transicao(self, MEDIO, lambda _v: self.update(), reduzir=reduzir)
        self._sucesso = Transicao(self, LENTO, lambda _v: self.update(), reduzir=reduzir)
        self._retorno = QTimer(self)
        self._retorno.setSingleShot(True)
        self._retorno.setInterval(self.RETORNO_MS)
        self._retorno.timeout.connect(lambda: self._mudar("ocioso"))

    @property
    def estado(self) -> str:
        return self._estado

    def iniciar(self) -> bool:
        """Entra em "trabalhando". Devolve falso se já havia trabalho em curso."""
        if self._estado != "ocioso":
            return False
        self._mudar("trabalhando")
        return True

    def concluir(self) -> None:
        if self._estado == "trabalhando":
            self._mudar("concluido")

    def _mudar(self, estado: str) -> None:
        self._anterior, self._estado = self._estado, estado
        self.setText(self._rotulos[estado])
        self.setAccessibleDescription(self._rotulos[estado])
        self._troca.saltar(0.0)
        self._troca.ir(1.0)
        if estado == "trabalhando":
            self.setCursor(Qt.CursorShape.BusyCursor)
            self._giro.start()
        else:
            self._giro.stop()
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        if estado == "concluido":
            self._sucesso.ir(1.0)
            self._retorno.start()
        else:
            self._sucesso.ir(0.0)

    def _girar(self, valor: Any) -> None:
        self._angulo = float(valor)
        self.update()

    def sizeHint(self) -> QSize:
        # O construtor do Botao pode perguntar o tamanho antes de haver rótulos.
        rotulos = getattr(self, "_rotulos", {"ocioso": self.text()})
        metricas = QFontMetrics(self.font())
        texto = max(metricas.horizontalAdvance(r) for r in rotulos.values())
        return QSize(texto + 22 + 46, 38)

    # -- desenho
    def paintEvent(self, _evento: Any) -> None:
        p = self._paleta()
        if not p:
            return
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self._sucesso.valor

        area = QRectF(self.rect()).adjusted(0.5, 0.5 + self._pressao, -0.5, -0.5 + self._pressao)
        caminho = caminho_forma(area, self.forma, design.RAIO)
        fundo_ocioso = design.misturar(p["screen"], p["accent"], 0.14)
        fundo = design.misturar(fundo_ocioso, p["accent"], s)
        fundo = design.misturar(fundo, "#ffffff", 0.10 * self._hover * (1.0 - s))
        fundo = design.misturar(fundo, "#000000", 0.16 * self._pressao)
        frente = design.misturar(
            design.garantir_contraste(p["accent"], fundo_ocioso), p["on_accent"], s
        )

        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(QColor(fundo))
        pintor.drawPath(caminho)
        caneta = QPen(QColor(design.misturar(p["screen"], p["accent"], 0.55 + 0.45 * s)))
        caneta.setWidthF(1.2)
        pintor.setPen(caneta)
        pintor.setBrush(Qt.BrushStyle.NoBrush)
        pintor.drawPath(caminho)

        if self.hasFocus():
            anel = QPen(QColor(design.garantir_contraste(p["accent"], fundo, 3.0)))
            anel.setWidthF(1.6)
            pintor.setPen(anel)
            pintor.drawPath(
                caminho_forma(area.adjusted(2.5, 2.5, -2.5, -2.5), self.forma, max(2.0, design.RAIO - 2.5))
            )

        # O conteúdo que sai sobe e esmaece; o que entra vem de baixo. Seis
        # pixels bastam: é direção, não viagem.
        troca = self._troca.valor
        if troca < 1.0:
            self._pintar_conteudo(pintor, area, self._anterior, frente, 1.0 - troca, -6.0 * troca)
        self._pintar_conteudo(pintor, area, self._estado, frente, troca, 6.0 * (1.0 - troca))
        pintor.end()

    def _pintar_conteudo(
        self, pintor: QPainter, area: QRectF, estado: str, cor: str,
        opacidade: float, deslocamento: float,
    ) -> None:
        if opacidade <= 0.01:
            return
        texto = self._rotulos[estado]
        metricas = QFontMetrics(self.font())
        icone = 14.0 if estado != "ocioso" else 0.0
        vao = 8.0 if icone else 0.0
        largura = metricas.horizontalAdvance(texto) + icone + vao
        x = area.center().x() - largura / 2.0
        y = area.center().y() + deslocamento

        pintor.save()
        pintor.setOpacity(opacidade)
        caneta = QPen(QColor(cor))
        caneta.setWidthF(2.0)
        caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
        caneta.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pintor.setPen(caneta)
        pintor.setBrush(Qt.BrushStyle.NoBrush)
        caixa = QRectF(x, y - icone / 2.0, icone, icone)
        if estado == "trabalhando":
            # Arco de 270° girando: diz "em andamento" sem prometer quanto
            # falta, que é tudo que se sabe de uma escrita em disco.
            pintor.drawArc(caixa.adjusted(1, 1, -1, -1), int(-self._angulo * 16), 270 * 16)
        elif estado == "concluido":
            pintor.drawPath(_visto(caixa, self._sucesso.valor))
        pintor.setFont(self.font())
        pintor.drawText(
            QRectF(x + icone + vao, area.top() + deslocamento, largura, area.height()),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            texto,
        )
        pintor.restore()


def _visto(caixa: QRectF, progresso: float) -> QPainterPath:
    """Sinal de visto desenhado até ``progresso`` do seu comprimento.

    Desenhado, e não digitado: o "✓" é do bloco Dingbats, que Consolas e
    Georgia não têm — sairia como caixinha em metade dos temas.
    """
    pontos = (
        QPointF(caixa.left() + caixa.width() * 0.12, caixa.top() + caixa.height() * 0.55),
        QPointF(caixa.left() + caixa.width() * 0.40, caixa.top() + caixa.height() * 0.82),
        QPointF(caixa.left() + caixa.width() * 0.90, caixa.top() + caixa.height() * 0.20),
    )
    trechos = [math.dist((a.x(), a.y()), (b.x(), b.y())) for a, b in pairwise(pontos)]
    restante = max(0.0, min(1.0, progresso)) * sum(trechos)
    caminho = QPainterPath(pontos[0])
    for (a, b), comprimento in zip(pairwise(pontos), trechos, strict=True):
        if restante <= 0.0:
            break
        fracao = min(1.0, restante / comprimento)
        caminho.lineTo(a + (b - a) * fracao)
        restante -= comprimento
    return caminho


# --------------------------------------------------------------------- Vitrine
def _palavras() -> list[Entrada]:
    """Quatro palavras que cobrem os três selos: vencida, em dia e dominada."""
    agora = datetime.now(timezone.utc)

    def daqui(dias: int) -> str:
        return (agora + timedelta(days=dias)).isoformat(timespec="seconds")

    visto = agora.isoformat(timespec="seconds")
    return [
        Entrada("wasteland", "terra devastada", "Welcome to the wasteland, stranger.",
                "Fallout", 3, visto, acertos=1, erros=2),
        Entrada("to scavenge", "vasculhar, catar restos",
                "We need to scavenge for parts before nightfall.", "Fallout", 2, visto,
                acertos=2, intervalo_dias=3, proxima_revisao=daqui(3)),
        Entrada("bounty", "recompensa (pela captura de alguém)",
                "There's a bounty on your head, partner.", "Red Dead", 1, visto),
        Entrada("bonfire", "fogueira", "Rest at the bonfire to restore your flasks.",
                "Elden Ring", 6, visto, acertos=7,
                intervalo_dias=DIAS_PARA_DOMINIO, proxima_revisao=daqui(DIAS_PARA_DOMINIO)),
    ]


class Vitrine(QWidget):
    """Janela de teste: tema real, cenário real, componentes novos."""

    def __init__(self) -> None:
        super().__init__()
        self._nome = DEFAULT_TEMA
        self._tema = TEMAS[self._nome]
        # Começa pelo que o Windows já diz. O chip deixa conferir as duas versões.
        self._reduzir = movimento_reduzido()
        self._tipografia = Tipografia(self._tema)
        self._cenario = Cenario()
        self._cenario.movimento = False
        self._cenario.definir(self._tema, ATMOSFERAS[self._nome])
        self._cartoes: list[CartaoVivo] = []
        self._trabalho = QTimer(self)
        self._trabalho.setSingleShot(True)
        self._trabalho.setInterval(1400)

        self.setWindowTitle("Vitrine de microinterações")
        self.setMinimumSize(620, 600)
        self.resize(860, 800)
        QShortcut(QKeySequence("Esc"), self, self.close)
        self._montar()
        self._aplicar_tema()
        self._popular(animar=True)

    def _forma(self) -> str:
        return ATMOSFERAS[self._nome].forma

    def _montar(self) -> None:
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(32, 28, 32, 24)
        coluna.setSpacing(design.ESPACO_SM)

        self.titulo = QLabel("Caderno de vocabulário")
        self.titulo.setObjectName("vitrineTitulo")
        self.subtitulo = QLabel(
            "Protótipo de microinterações — passe o mouse, use Tab, remova um cartão."
        )
        self.subtitulo.setObjectName("vitrineMudo")
        coluna.addWidget(self.titulo)
        coluna.addWidget(self.subtitulo)
        coluna.addSpacing(design.ESPACO_MD)

        controles = QHBoxLayout()
        controles.setSpacing(design.ESPACO_SM)
        self.campo_tema = CampoSelecao()
        self.campo_tema.addItems(list(TEMAS))
        self.campo_tema.setCurrentText(self._nome)
        self.campo_tema.currentTextChanged.connect(self._trocar_tema)
        controles.addWidget(self.campo_tema)
        controles.addStretch(1)
        self.chip_reduzir = Botao("Reduzir movimento", variante="chip", paleta=self._paleta)
        self.chip_reduzir.setCheckable(True)
        self.chip_reduzir.setChecked(self._reduzir)
        self.chip_reduzir.toggled.connect(self._alternar_reduzir)
        controles.addWidget(self.chip_reduzir)
        self.botao_repetir = Botao("▶  Repetir entrada", variante="sutil", paleta=self._paleta)
        self.botao_repetir.clicked.connect(lambda: self._popular(animar=True))
        controles.addWidget(self.botao_repetir)
        coluna.addLayout(controles)
        coluna.addSpacing(design.ESPACO_LG)

        self.lista = QVBoxLayout()
        self.lista.setSpacing(design.ESPACO_MD)
        coluna.addLayout(self.lista)
        coluna.addStretch(1)

        rodape = QHBoxLayout()
        self.dica = QLabel("")
        self.dica.setObjectName("vitrineMudo")
        rodape.addWidget(self.dica, 1)
        self.botao_exportar = BotaoDeEstado(
            {"ocioso": "↓  Exportar caderno", "trabalhando": "Exportando…", "concluido": "Exportado"},
            paleta=self._paleta, forma=self._forma(), reduzir=lambda: self._reduzir,
        )
        self.botao_exportar.clicked.connect(self._exportar)
        self._trabalho.timeout.connect(self.botao_exportar.concluir)
        rodape.addWidget(self.botao_exportar)
        coluna.addLayout(rodape)

    def _paleta(self) -> dict[str, str]:
        return paleta_de(self._tema)

    def _aplicar_tema(self) -> None:
        t, forma = self._tema, self._forma()
        raio = RAIO_POR_FORMA.get(forma, RAIO_PADRAO)
        self._tipografia.definir_tema(t)
        self._cenario.definir(t, ATMOSFERAS[self._nome])
        self.titulo.setFont(self._tipografia.fonte("display", ui=False))
        for rotulo in (self.subtitulo, self.dica):
            rotulo.setFont(self._tipografia.fonte("legenda"))
        self.campo_tema.setFont(self._tipografia.fonte("aux"))
        self.campo_tema.definir_cor_seta(t.text_muted)
        for botao in (self.chip_reduzir, self.botao_repetir, self.botao_exportar):
            botao.setFont(self._tipografia.fonte("corpo_forte"))
            botao.forma = forma
        self.setStyleSheet(f"""
            QWidget {{ color: {t.primary}; }}
            QLabel {{ background: transparent; }}
            #vitrineTitulo {{ color: {t.primary}; }}
            #vitrineMudo {{ color: {t.text_muted}; }}
            {css_campo_selecao(t, raio, rgba)}
        """)
        self.dica.setText("Tab percorre as ações dos cartões sem mouse.")
        self.update()

    def _trocar_tema(self, nome: str) -> None:
        if nome not in TEMAS or nome == self._nome:
            return
        retrato = None if self._reduzir else self.grab()
        self._nome, self._tema = nome, TEMAS[nome]
        self._aplicar_tema()
        self._popular(animar=False)
        if retrato is not None:
            TransicaoDeTema(self, retrato)

    def _alternar_reduzir(self, ligado: bool) -> None:
        self._reduzir = ligado
        self.dica.setText(
            "Movimento reduzido: os estados mudam na hora, sem trajeto."
            if ligado else "Movimento completo."
        )

    def _popular(self, *, animar: bool) -> None:
        for cartao in self._cartoes:
            cartao.setParent(None)
            cartao.deleteLater()
        self._cartoes = [
            CartaoVivo(
                entrada, tema=self._tema, forma=self._forma(), tipografia=self._tipografia,
                reduzir=lambda: self._reduzir, ao_remover=self._remover, ao_agir=self.dica.setText,
            )
            for entrada in _palavras()
        ]
        for cartao in self._cartoes:
            self.lista.addWidget(cartao)
        if animar:
            animar_entrada(self._cartoes, reduzir=self._reduzir)

    def _remover(self, cartao: CartaoVivo) -> None:
        if cartao not in self._cartoes:
            return
        self._cartoes.remove(cartao)
        self.dica.setText(f"“{cartao.entrada.termo}” removida. ▶ Repetir entrada devolve as palavras.")

        def descartar() -> None:
            cartao.setParent(None)
            cartao.deleteLater()

        cartao.sair(descartar)

    def _exportar(self) -> None:
        if self.botao_exportar.iniciar():
            self.dica.setText("Exportação simulada: nenhum arquivo é escrito.")
            self._trabalho.start()

    def paintEvent(self, _evento: Any) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._cenario.pintar_fundo(pintor, self.width(), self.height())
        self._cenario.pintar_sobreposicao(pintor, self.width(), self.height())
        pintor.end()


def main() -> int:
    aplicacao = QApplication.instance() or QApplication(sys.argv)
    vitrine = Vitrine()
    vitrine.show()
    return aplicacao.exec()


if __name__ == "__main__":
    raise SystemExit(main())
