"""A conversa antes da conversa.

Antes de iniciar, o palco era um painel do tamanho da janela com duas linhas
minúsculas no pé — o modelo em uso e os atalhos globais. A primeira coisa que
alguém via ao abrir o programa era um vazio, e a única pista do que fazer era
um botão no canto de cima.

Esta tela responde às três perguntas de quem abre um programa de voz:

* **Como começo?** O botão com o nome que ele tem NESTE tema — "Invocar" no
  Elden Ring, "Conectar" no Cyberpunk — e o atalho que funciona de dentro do
  jogo, que é onde o programa é usado.
* **O que eu digo?** Três exemplos, um deles com uma palavra vencida do próprio
  caderno quando existe uma: ninguém sabe o que perguntar a um microfone. Cada
  exemplo é uma ficha que se toca: o clique o escreve no campo de texto.
* **O que dá para fazer sem sessão?** Revisar, abrir o caderno e o histórico,
  com os números de agora e a tecla de cada um. Nada disso gasta a chave.

Ela ocupa o espaço livre ACIMA das anotações do sistema, que continuam no pé da
conversa: "Inicie uma sessão antes de enviar mensagens" é resposta a um gesto,
e não pode ficar escondida atrás de uma apresentação. Quem decide quando ela
aparece é a ``Conversa``.
"""

from __future__ import annotations

import html
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QEnterEvent,
    QFocusEvent,
    QFont,
    QFontMetrics,
    QHoverEvent,
    QPainter,
    QPen,
    QTransform,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QBoxLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import design
from .componentes import Holofote, RotuloDecifravel, acender_borda, caminho_forma
from .movimento import animar_entrada


@dataclass(frozen=True, slots=True)
class Resumo:
    """O que a tela inicial mostra, lido na hora em que ela aparece."""

    termos: int
    vencidas: int
    conversas: int
    sequencia: int
    # Uma palavra vencida do caderno, para o exemplo. Vazia quando não há.
    palavra: str
    # Os atalhos globais como (tecla, o que faz), o de iniciar primeiro. Vazio
    # quando atalhos globais não existem nesta máquina ou foram desligados.
    atalhos: tuple[tuple[str, str], ...]
    diagnostico: str


def _contagem(quantidade: int, singular: str, plural: str) -> str:
    return f"{quantidade} {singular if quantidade == 1 else plural}"


def _inteiro(texto: str) -> str:
    """Trecho que a quebra de linha não pode partir.

    "PIP-BOY" quebrava no hífen, deixando "PIP-" no fim de uma linha e
    "BOY" no começo da outra; o mesmo valeria para "▶ INICIAR", que precisa
    ser lido de uma vez para ser achado no canto da janela. Hífen e espaço
    inseparáveis resolvem sem texto rico — o white-space: nowrap num span
    foi tentado e o Qt o ignora dentro de um parágrafo que quebra linha.
    """
    return texto.replace("-", "‑").replace(" ", " ")


def tecla_legivel(combinacao: str) -> str:
    """'ctrl+alt+p' como se escreve numa tecla: 'Ctrl+Alt+P'.

    O ``.env`` guarda as combinações no formato da biblioteca de atalhos, em
    minúsculas. É o formato certo para ela e o errado para ler — e a tela
    inicial é justamente onde a pessoa lê qual tecla apertar.
    """
    return "+".join(
        parte.upper() if len(parte) == 1 else parte.capitalize()
        for parte in combinacao.split("+")
    )


class CartaoAcao(QAbstractButton):
    """Um atalho da tela inicial: glifo, título, detalhe e a tecla que faz o mesmo.

    A tecla fica escrita no cartão de propósito. É assim que um atalho se
    ensina — no lugar em que a pessoa já está olhando, na hora em que ela
    procura aquilo —, e não numa tabela do README.

    Pintado por inteiro, sem rótulos filhos: um widget só não tem movimento de
    mouse que se perca num filho, nem efeito gráfico de filho para aninhar.
    """

    RESPIRO = 14
    # O cartão inclina em direção ao cursor, até este ângulo em cada eixo, com
    # uma perspectiva curta o bastante para a inclinação se VER num cartão
    # pequeno. A folga em volta do corpo é o espaço que a inclinação ocupa.
    INCLINACAO = 12.0
    DISTANCIA = 340.0
    FOLGA_3D = 6

    def __init__(
        self, glifo: str, titulo: str, tecla: str, *, janela: Any, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._janela = janela
        self._glifo = glifo
        self._tecla = tecla
        self._detalhe = ""
        self._destaque = False
        self._sob_cursor = False
        self._focado = False
        self.setText(titulo)
        self.setAccessibleName(titulo)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._reduzir: Callable[[], bool] = lambda: bool(janela.intensidade_atmosfera <= 0.0)
        self._holofote = Holofote(self, reduzir=self._reduzir)

    @property
    def detalhe(self) -> str:
        return self._detalhe

    @property
    def destaque(self) -> bool:
        return self._destaque

    def definir(self, detalhe: str, *, destaque: bool = False) -> None:
        """Troca a linha de detalhe. ``destaque`` pinta o cartão no acento."""
        self._detalhe = detalhe
        self._destaque = destaque
        self.setAccessibleDescription(f"{detalhe}. Atalho: {self._tecla}")
        self.setToolTip(f"{detalhe} ({self._tecla})")
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        # Das fontes da janela, e não da própria: é o que faz o cartão crescer
        # junto quando o tamanho do texto muda.
        titulo = QFontMetrics(self._janela.fonte("corpo_forte")).height()
        detalhe = QFontMetrics(self._janela.fonte("micro")).height()
        return QSize(190, self.RESPIRO * 2 + titulo + 4 + detalhe + 2 * self.FOLGA_3D)

    def minimumSizeHint(self) -> QSize:
        return QSize(150, self.sizeHint().height())

    def largura_ideal(self) -> int:
        """A largura em que título, tecla e detalhe cabem sem reticências."""
        janela = self._janela
        m_titulo = QFontMetrics(janela.fonte("corpo_forte"))
        m_micro = QFontMetrics(janela.fonte("micro"))
        glifo = QFontMetrics(janela.fonte("titulo")).horizontalAdvance(self._glifo) + 10
        tecla = m_micro.horizontalAdvance(self._tecla) + 12
        conteudo = max(
            m_titulo.horizontalAdvance(self.text()) + 8 + tecla,
            m_micro.horizontalAdvance(self._detalhe),
        )
        return glifo + conteudo + self.RESPIRO * 2 + 4 + 2 * self.FOLGA_3D

    def inclinacao(self) -> tuple[float, float]:
        """Os ângulos, em torno de Y e de X, com que o cartão segue o cursor.

        O lado sob o cursor afunda e o oposto sobe, como um cartão de verdade
        empurrado com o dedo. A inclinação acompanha a luz: acende junto ao
        entrar e volta ao plano junto ao sair. Pelo teclado não há de onde
        inclinar — o cartão só acende.
        """
        luz = self._holofote.valor
        cursor = self._holofote.cursor
        if luz <= 0.01 or cursor is None or self._reduzir():
            return 0.0, 0.0
        if self._focado and not self._sob_cursor:
            return 0.0, 0.0
        largura, altura = max(1, self.width()), max(1, self.height())
        dx = max(-1.0, min(1.0, (cursor.x() / largura - 0.5) * 2))
        dy = max(-1.0, min(1.0, (cursor.y() / altura - 0.5) * 2))
        # Sinais escolhidos olhando a tela: com eles, o lado sob o cursor afasta.
        return -dx * self.INCLINACAO * luz, dy * self.INCLINACAO * luz

    def _transformacao(self) -> QTransform | None:
        giro_y, giro_x = self.inclinacao()
        if giro_y == 0.0 and giro_x == 0.0:
            return None
        centro = QPointF(self.rect().center())
        realce = 1.0 + 0.035 * self._holofote.valor
        transformacao = QTransform()
        transformacao.translate(centro.x(), centro.y())
        transformacao.rotate(giro_y, Qt.Axis.YAxis, self.DISTANCIA)
        transformacao.rotate(giro_x, Qt.Axis.XAxis, self.DISTANCIA)
        transformacao.scale(realce, realce)
        transformacao.translate(-centro.x(), -centro.y())
        return transformacao

    # -- presença
    def enterEvent(self, evento: QEnterEvent) -> None:
        self._sob_cursor = True
        self._holofote.seguir(evento.position())
        self._holofote.acender(True)
        super().enterEvent(evento)

    def leaveEvent(self, evento: QEvent) -> None:
        self._sob_cursor = False
        self._holofote.acender(self.hasFocus())
        super().leaveEvent(evento)

    def event(self, evento: QEvent) -> bool:
        if evento.type() == QEvent.Type.HoverMove and isinstance(evento, QHoverEvent):
            self._holofote.seguir(evento.position())
        return super().event(evento)

    def focusInEvent(self, evento: QFocusEvent) -> None:
        super().focusInEvent(evento)
        self._focado = True
        self._holofote.acender(True)
        self.update()

    def focusOutEvent(self, evento: QFocusEvent) -> None:
        super().focusOutEvent(evento)
        self._focado = False
        self._holofote.acender(self._sob_cursor)
        self.update()

    # -- desenho
    def paintEvent(self, _evento: Any) -> None:
        janela = self._janela
        t = janela.tema
        forma = janela.atmosfera.forma
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        pintor.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        transformacao = self._transformacao()
        if transformacao is not None:
            pintor.setTransform(transformacao)

        # Afunda 1 px enquanto pressionado, como o Botao.
        recuo = 1.0 if self.isDown() else 0.0
        f = self.FOLGA_3D
        area = QRectF(self.rect()).adjusted(0.5 + f, 0.5 + f + recuo, -0.5 - f, -0.5 - f + recuo)
        fundo = t.surface_alta
        cor = t.accent if self._destaque else t.primary
        borda = design.misturar(t.border, t.accent, 0.45) if self._destaque else t.border
        focado = self.hasFocus()
        contorno = caminho_forma(area, forma, design.RAIO)
        self._holofote.pintar(
            pintor, contorno, fundo=fundo, cor=cor, borda=borda,
            foco=self if focado and not self._sob_cursor else None,
        )
        acender_borda(pintor, self, contorno)
        if focado:
            anel = QPen(QColor(design.garantir_contraste(cor, fundo, 3.0)))
            anel.setWidthF(1.6)
            pintor.setPen(anel)
            pintor.setBrush(Qt.BrushStyle.NoBrush)
            pintor.drawPath(
                caminho_forma(
                    area.adjusted(2.5, 2.5, -2.5, -2.5), forma, max(2.0, design.RAIO - 2.5)
                )
            )

        fonte_titulo = janela.fonte("corpo_forte")
        fonte_micro = janela.fonte("micro")
        fonte_glifo = janela.fonte("titulo")
        m_titulo, m_micro = QFontMetrics(fonte_titulo), QFontMetrics(fonte_micro)
        interno = area.adjusted(self.RESPIRO + 2, self.RESPIRO, -self.RESPIRO, -self.RESPIRO)
        altura_titulo = float(m_titulo.height())

        largura_glifo = QFontMetrics(fonte_glifo).horizontalAdvance(self._glifo) + 10.0
        pintor.setFont(fonte_glifo)
        pintor.setPen(QColor(design.garantir_contraste(cor, fundo)))
        pintor.drawText(
            QRectF(interno.left(), interno.top(), largura_glifo, altura_titulo),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self._glifo,
        )

        # A tecla desenhada como tecla: contorno fino e texto pequeno.
        largura_tecla = m_micro.horizontalAdvance(self._tecla) + 12.0
        altura_tecla = m_micro.height() + 4.0
        caixa_tecla = QRectF(
            interno.right() - largura_tecla,
            interno.top() + (altura_titulo - altura_tecla) / 2.0,
            largura_tecla,
            altura_tecla,
        )
        pintor.setPen(QPen(QColor(t.border_forte), 1.0))
        pintor.setBrush(Qt.BrushStyle.NoBrush)
        pintor.drawRoundedRect(caixa_tecla, 4.0, 4.0)
        pintor.setFont(fonte_micro)
        pintor.setPen(QColor(design.garantir_contraste(t.text_muted, fundo)))
        pintor.drawText(caixa_tecla, int(Qt.AlignmentFlag.AlignCenter), self._tecla)

        x_texto = interno.left() + largura_glifo
        largura_titulo = max(0.0, caixa_tecla.left() - 8.0 - x_texto)
        pintor.setFont(fonte_titulo)
        pintor.setPen(QColor(design.garantir_contraste(t.primary, fundo)))
        pintor.drawText(
            QRectF(x_texto, interno.top(), largura_titulo, altura_titulo),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            m_titulo.elidedText(self.text(), Qt.TextElideMode.ElideRight, int(largura_titulo)),
        )

        largura_detalhe = max(0.0, interno.right() - x_texto)
        pintor.setFont(fonte_micro)
        pintor.setPen(
            QColor(design.garantir_contraste(t.accent if self._destaque else t.text_muted, fundo))
        )
        pintor.drawText(
            QRectF(x_texto, interno.top() + altura_titulo + 4.0, largura_detalhe, m_micro.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            m_micro.elidedText(self._detalhe, Qt.TextElideMode.ElideRight, int(largura_detalhe)),
        )
        pintor.end()


class FichaSugestao(QAbstractButton):
    """Um exemplo do que dizer que se toca: o clique o escreve no campo de texto.

    Os exemplos eram uma linha de texto parada — diziam o que perguntar, mas
    não davam um jeito de começar. Cada um virou uma ficha que acende e sobe de
    leve sob o cursor, como os cartões ao lado, e que leva a frase para o campo
    de texto, com o foco e o cursor no fim, pronta para ir.

    Leva, e não envia. Enviar abre uma conversa com a API, e sem sessão ativa
    só produz "Inicie uma sessão antes de enviar mensagens": quem decide
    mandar é quem aperta Enter.

    Pintada por inteiro, como o ``CartaoAcao``, e pelo mesmo ``Holofote``.
    """

    RESPIRO_X = 13
    RESPIRO_Y = 5
    # Quanto a ficha sobe sob o cursor. A altura do widget já reserva esse
    # espaço em cima: um widget não pinta fora de si.
    SUBIDA = 2.0

    def __init__(self, frase: str, *, janela: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._janela = janela
        self._frase = ""
        self._sob_cursor = False
        self._focado = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setToolTip("Escreve esta pergunta no campo de texto, sem enviar")
        self._reduzir: Callable[[], bool] = lambda: bool(janela.intensidade_atmosfera <= 0.0)
        self._holofote = Holofote(self, reduzir=self._reduzir)
        self.definir_frase(frase)

    @property
    def frase(self) -> str:
        return self._frase

    def definir_frase(self, frase: str) -> None:
        self._frase = frase
        self.setText(f"“{frase}”")
        self.setAccessibleName(f"Escrever no campo de texto: {frase}")
        self.updateGeometry()
        self.update()

    def _fonte(self) -> Any:
        return self._janela.fonte("vocab", ui=False)

    def sizeHint(self) -> QSize:
        metricas = QFontMetrics(self._fonte())
        return QSize(
            metricas.horizontalAdvance(self.text()) + 2 * self.RESPIRO_X,
            metricas.height() + 2 * self.RESPIRO_Y + round(self.SUBIDA),
        )

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    @property
    def elevacao(self) -> float:
        """Quanto a ficha subiu agora, em pixels."""
        return 0.0 if self._reduzir() else self.SUBIDA * self._holofote.valor

    @property
    def corpo(self) -> QRectF:
        """A ficha desenhada, já subida: é o que o anel do cursor abraça."""
        return QRectF(self.rect()).adjusted(0.5, 0.5 + self.SUBIDA, -0.5, -0.5).translated(
            0.0, -self.elevacao
        )

    @property
    def raio_borda(self) -> float:
        """O canto da ficha: pílula no tema arredondado; o do tema nos outros."""
        forma = self._janela.atmosfera.forma
        return {"chanfrada": 3.0, "reta": 2.0}.get(forma, self.corpo.height() / 2)

    # -- presença
    def enterEvent(self, evento: QEnterEvent) -> None:
        self._sob_cursor = True
        self._holofote.seguir(evento.position())
        self._holofote.acender(True)
        super().enterEvent(evento)

    def leaveEvent(self, evento: QEvent) -> None:
        self._sob_cursor = False
        self._holofote.acender(self.hasFocus())
        super().leaveEvent(evento)

    def event(self, evento: QEvent) -> bool:
        if evento.type() == QEvent.Type.HoverMove and isinstance(evento, QHoverEvent):
            self._holofote.seguir(evento.position())
        return super().event(evento)

    def focusInEvent(self, evento: QFocusEvent) -> None:
        super().focusInEvent(evento)
        self._focado = True
        self._holofote.acender(True)

    def focusOutEvent(self, evento: QFocusEvent) -> None:
        super().focusOutEvent(evento)
        self._focado = False
        self._holofote.acender(self._sob_cursor)

    # -- desenho
    def paintEvent(self, _evento: Any) -> None:
        t = self._janela.tema
        forma = self._janela.atmosfera.forma
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self.corpo
        caminho = caminho_forma(area, forma, area.height() / 2)
        fundo = t.surface_alta
        self._holofote.pintar(
            pintor, caminho, fundo=fundo, cor=t.accent, borda=t.border,
            foco=self if self._focado and not self._sob_cursor else None,
        )
        acender_borda(pintor, self, caminho)
        if self.hasFocus():
            anel = QPen(QColor(design.garantir_contraste(t.accent, fundo, 3.0)))
            anel.setWidthF(1.6)
            pintor.setPen(anel)
            pintor.setBrush(Qt.BrushStyle.NoBrush)
            pintor.drawPath(
                caminho_forma(area.adjusted(2.5, 2.5, -2.5, -2.5), forma, area.height() / 2 - 2.5)
            )
        pintor.setFont(self._fonte())
        pintor.setPen(QColor(design.garantir_contraste(t.info_text, fundo)))
        pintor.drawText(area, int(Qt.AlignmentFlag.AlignCenter), self.text())
        pintor.end()


class TelaInicial(QWidget):
    """O que a conversa mostra enquanto não há conversa."""

    LARGURA_MAX = 660

    def __init__(self, janela: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._janela = janela
        self.setObjectName("telaInicial")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        externa = QHBoxLayout(self)
        externa.setContentsMargins(0, 0, 0, 0)
        externa.addStretch(1)
        miolo = QWidget()
        miolo.setMaximumWidth(self.LARGURA_MAX)
        miolo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        externa.addWidget(miolo, 20)
        externa.addStretch(1)

        coluna = QVBoxLayout(miolo)
        coluna.setContentsMargins(0, design.ESPACO_LG, 0, design.ESPACO_LG)
        coluna.setSpacing(design.ESPACO_SM)
        coluna.addStretch(1)

        def rotulo(nome: str) -> QLabel:
            item = QLabel("")
            item.setObjectName(nome)
            item.setAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setWordWrap(True)
            return item

        self.glifo = rotulo("inicialGlifo")
        # O título se decifra quando a tela chega, como um terminal que liga.
        self.titulo = RotuloDecifravel(janela.tema.saudacao, objectName="inicialTitulo")
        self.titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.titulo.setWordWrap(True)
        self.corpo = rotulo("inicialCorpo")
        self.sequencia = rotulo("inicialSequencia")

        fileira = QWidget()
        self._fileira = cartoes = QHBoxLayout(fileira)
        cartoes.setContentsMargins(0, design.ESPACO_MD, 0, design.ESPACO_MD)
        cartoes.setSpacing(design.ESPACO_MD)
        self.cartao_revisar = CartaoAcao("▶", "Revisar", "Ctrl+R", janela=janela)
        self.cartao_revisar.clicked.connect(janela.revisar_agora)
        self.cartao_caderno = CartaoAcao("▤", "Caderno", "Ctrl+B", janela=janela)
        self.cartao_caderno.clicked.connect(janela.abrir_caderno)
        self.cartao_historico = CartaoAcao("◷", "Histórico", "Ctrl+H", janela=janela)
        self.cartao_historico.clicked.connect(janela.abrir_historico)
        for cartao in (self.cartao_revisar, self.cartao_caderno, self.cartao_historico):
            cartoes.addWidget(cartao, 1)

        exemplos = QWidget()
        pilha = QVBoxLayout(exemplos)
        pilha.setContentsMargins(0, 0, 0, 0)
        pilha.setSpacing(design.ESPACO_XS)
        self.secao_exemplos = rotulo("inicialSecao")
        self.secao_exemplos.setText("EXPERIMENTE DIZER")
        pilha.addWidget(self.secao_exemplos)
        # As fichas lado a lado, centradas; uma sobre a outra quando não cabem.
        self._fileira_fichas = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._fileira_fichas.setSpacing(design.ESPACO_SM)
        self.fichas = [FichaSugestao("", janela=janela) for _ in range(3)]
        self._fileira_fichas.addStretch(1)
        for ficha in self.fichas:
            ficha.clicked.connect(lambda _marcado=False, f=ficha: janela.propor_texto(f.frase))
            self._fileira_fichas.addWidget(ficha, 0, Qt.AlignmentFlag.AlignHCenter)
        self._fileira_fichas.addStretch(1)
        pilha.addLayout(self._fileira_fichas)

        rodape = QWidget()
        base = QVBoxLayout(rodape)
        base.setContentsMargins(0, design.ESPACO_MD, 0, 0)
        base.setSpacing(2)
        # Os atalhos numa linha só, e o Ctrl+K primeiro: a paleta é invisível
        # por natureza, ninguém descobre um Ctrl+K sozinho, e é aqui que quem
        # está parado na tela inicial procura o que fazer. Eram três linhas
        # soltas no pé do painel — atalhos globais, paleta, diagnóstico —, todas
        # na mesma cor apagada, e o olho não tinha onde pousar. Agora as TECLAS
        # ficam legíveis e o que elas fazem, discreto; o diagnóstico, que é
        # para quando algo dá errado, fica sozinho embaixo.
        self.atalhos = rotulo("inicialRodape")
        self.atalhos.setTextFormat(Qt.TextFormat.RichText)
        self.diagnostico = rotulo("inicialRodape")
        base.addWidget(self.atalhos)
        base.addWidget(self.diagnostico)

        # Os blocos, na ordem em que entram em cascata.
        self._blocos: list[QWidget] = [
            self.glifo, self.titulo, self.corpo, self.sequencia, fileira, exemplos, rodape,
        ]
        for bloco in self._blocos:
            coluna.addWidget(bloco)
        coluna.addStretch(1)

    def atualizar(self) -> None:
        """Aplica o tema e os números de agora. Barato: poucos rótulos."""
        janela = self._janela
        t = janela.tema
        resumo: Resumo = janela.resumo_inicial()

        partes = t.header_title.split()
        self.glifo.setText(partes[0] if partes and not partes[0].isalnum() else "◆")
        fonte_glifo = janela.fonte("display", ui=False)
        fonte_glifo.setPointSize(round(fonte_glifo.pointSize() * 1.7))
        self.glifo.setFont(fonte_glifo)
        # O título e o nome da seção de exemplos no traço do jogo: a fonte
        # dele, com o espaçamento entre letras dos menus dele.
        fonte_titulo = janela.fonte("display", ui=False)
        fonte_titulo.setLetterSpacing(
            QFont.SpacingType.AbsoluteSpacing, janela.atmosfera.espacamento_titulo
        )
        self.titulo.setFont(fonte_titulo)
        # A frase do jogo, e não uma frase de programa. Ela se decifra quando a
        # tela chega, como já fazia; trocar de jogo com a tela à vista a troca.
        if self.titulo.text() != t.saudacao:
            self.titulo.setText(t.saudacao)
        self.secao_exemplos.setFont(janela.fonte_de_secao())
        for item, papel in (
            (self.corpo, "corpo"), (self.sequencia, "legenda"),
            (self.atalhos, "micro"), (self.diagnostico, "micro"),
        ):
            item.setFont(janela.fonte(papel, ui=papel != "vocab"))

        # O botão com o nome que ele tem neste tema, sem o espaçamento duplo
        # que o rótulo usa para afastar o glifo dentro do botão.
        botao = " ".join(t.start_label.split())
        atalho = (
            f" — ou {_inteiro(tecla_legivel(resumo.atalhos[0][0]))}, de dentro do jogo —"
            if resumo.atalhos else ""
        )
        self.corpo.setText(
            f"Aperte {_inteiro(botao)}{atalho} e fale em português ou em inglês. "
            f"{_inteiro(t.assistant_name)} responde por voz e guarda no caderno cada "
            "palavra que ensinar."
        )

        if resumo.sequencia > 1:
            self.sequencia.setText(f"◆ sequência de {resumo.sequencia} dias de estudo")
        elif resumo.sequencia == 1:
            self.sequencia.setText("◆ 1º dia da sequência — volte amanhã")
        self.sequencia.setVisible(resumo.sequencia > 0)

        # Detalhes curtos de propósito: é a linha mais larga do cartão, e é ela
        # que decide se os três cabem lado a lado na janela no tamanho mínimo.
        self.cartao_revisar.definir(
            f"{_contagem(resumo.vencidas, 'vencida', 'vencidas')} · offline"
            if resumo.vencidas else "Em dia",
            destaque=resumo.vencidas > 0,
        )
        self.cartao_caderno.definir(
            _contagem(resumo.termos, "termo", "termos") if resumo.termos else "Ainda vazio"
        )
        self.cartao_historico.definir(
            _contagem(resumo.conversas, "conversa", "conversas")
            if resumo.conversas else "Nenhuma ainda"
        )

        palavra = resumo.palavra or "loot"
        frases = (
            f"O que significa ‘{palavra}’?",
            "Como se diz ‘mochila’ em inglês?",
            "Qual a diferença entre ‘will’ e ‘going to’?",
        )
        for ficha, frase in zip(self.fichas, frases, strict=True):
            ficha.definir_frase(frase)

        cor_tecla = design.garantir_contraste(t.primary, t.surface)

        def tecla(texto: str) -> str:
            return f'<span style="color:{cor_tecla};">{html.escape(texto)}</span>'

        partes = [f"{tecla('Ctrl+K')} comandos"]
        if resumo.atalhos:
            # "De dentro do jogo" diz o que "global" dizia, na língua de quem
            # joga: estes funcionam com o jogo em primeiro plano; o Ctrl+K, não.
            partes.append(
                "de dentro do jogo: "
                + " · ".join(
                    f"{tecla(tecla_legivel(combinacao))} {html.escape(acao)}"
                    for combinacao, acao in resumo.atalhos
                )
            )
        self.atalhos.setText("   ·   ".join(partes))
        self.diagnostico.setText(resumo.diagnostico)

        self.setStyleSheet(f"""
            QLabel {{ background: transparent; }}
            #inicialGlifo {{ color: {t.accent_text}; }}
            #inicialTitulo {{ color: {t.primary}; }}
            #inicialCorpo {{ color: {t.text_muted}; }}
            #inicialSequencia {{ color: {t.accent_text}; }}
            #inicialSecao {{ color: {t.text_muted}; }}
            #inicialRodape {{ color: {t.text_muted}; }}
        """)
        for cartao in (self.cartao_revisar, self.cartao_caderno, self.cartao_historico):
            cartao.updateGeometry()
        self._ajustar_fileira()

    def resizeEvent(self, evento: Any) -> None:
        super().resizeEvent(evento)
        self._ajustar_fileira()

    def _ajustar_fileira(self) -> None:
        """Três lado a lado quando cabem inteiros; um sobre o outro quando não.

        Com a janela no tamanho mínimo e o texto em "Maior", a fileira cortava
        os três títulos em "Re…", "Ca…" e "Hi…". Um cartão empilhado ocupa mais
        altura, e altura a conversa tem para rolar; título cortado não se lê.
        """
        cartoes = (self.cartao_revisar, self.cartao_caderno, self.cartao_historico)
        necessaria = max(c.largura_ideal() for c in cartoes)
        disponivel = min(self.width(), self.LARGURA_MAX)
        cabe = len(cartoes) * necessaria + (len(cartoes) - 1) * design.ESPACO_MD <= disponivel
        direcao = (
            QBoxLayout.Direction.LeftToRight if cabe else QBoxLayout.Direction.TopToBottom
        )
        if self._fileira.direction() != direcao:
            self._fileira.setDirection(direcao)
        # As fichas: numa linha quando as três cabem, uma sobre a outra quando não.
        fichas = sum(f.sizeHint().width() for f in self.fichas)
        cabem = fichas + (len(self.fichas) - 1) * design.ESPACO_SM <= disponivel
        direcao_fichas = (
            QBoxLayout.Direction.LeftToRight if cabem else QBoxLayout.Direction.TopToBottom
        )
        if self._fileira_fichas.direction() != direcao_fichas:
            self._fileira_fichas.setDirection(direcao_fichas)

    @property
    def empilhada(self) -> bool:
        return self._fileira.direction() == QBoxLayout.Direction.TopToBottom

    @property
    def fichas_empilhadas(self) -> bool:
        return self._fileira_fichas.direction() == QBoxLayout.Direction.TopToBottom

    def entrar(self) -> None:
        """Cascata de cima para baixo, na ordem de leitura, e o título se decifrando."""
        animar_entrada(
            [bloco for bloco in self._blocos if not bloco.isHidden()],
            reduzir=bool(self._janela.intensidade_atmosfera <= 0.0),
        )
        self.titulo.decifrar()
