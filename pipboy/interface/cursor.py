"""Onde está o cursor sobre a janela principal, visto de qualquer filho dela.

A atmosfera e o botão magnético precisam do cursor em coordenadas da JANELA,
esteja ele sobre a conversa, a lateral ou um rótulo qualquer. Nenhum widget
recebe isso sozinho: o movimento sem botão vai para o filho que está embaixo
do cursor — e, se esse filho não rastreia o mouse, o Qt o descarta sem subir
para o pai.

Descarta para os WIDGETS, mas não para os filtros da APLICAÇÃO: o Qt passa até
o movimento não rastreado por eles antes de jogá-lo fora. É aqui que o
rastreador escuta, e por isso ele vê o cursor em qualquer ponto da janela sem
ligar o rastreamento de nenhum widget.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import (
    QElapsedTimer,
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QRectF,
    QSizeF,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QHoverEvent, QMouseEvent, QPainter, QPainterPath
from PySide6.QtWidgets import QAbstractButton, QApplication, QComboBox, QWidget

from .. import design
from .atmosfera import Cenario
from .componentes import (
    Botao,
    LuzDoCursor,
    acender_borda,
    definir_fonte_da_luz,
    movimento_reduzido,
)
from .relogios import PASSO_MAXIMO, intervalo_interativo

_MOVIMENTOS = (QEvent.Type.MouseMove, QEvent.Type.HoverMove)


def clicavel(widget: QWidget) -> bool:
    """O widget sob o cursor responde a clique? É o que faz o anel crescer."""
    return (
        isinstance(widget, (QAbstractButton, QComboBox))
        or widget.cursor().shape() == Qt.CursorShape.PointingHandCursor
    )


# Quanto o anel abraçando fica afastado do corpo do que abraça.
FOLGA_ABRACO = 5.0
# Acima disto o alvo é grande demais para abraçar: um contorno em volta de um
# painel inteiro lê como moldura, e não como alvo, e o anel só cresce. A conta
# é de ÁREA, e não de largura: uma ficha de sugestão é larga e baixa, e abraçar
# uma ficha é exatamente o que se quer.
AREA_MAXIMA_ABRACO = 88_000.0
ALTURA_MAXIMA_ABRACO = 170.0


def abraco_de(widget: QWidget | None, janela: QWidget) -> tuple[QRectF, float] | None:
    """O contorno que o anel abraça sobre ``widget``, em coordenadas de ``janela``.

    Com o canto do próprio widget: arredondado, chanfrado ou reto conforme o
    tema, e no seletor, o que a folha de estilo dá a ele. Do botão magnético,
    o corpo JÁ PUXADO pelo ímã: o anel vai junto com ele. ``None`` para quem
    não está à vista, é de outra janela, já foi destruído ou é grande demais.
    """
    if widget is None:
        return None
    try:
        if not widget.isVisible() or widget.window() is not janela:
            return None
        # O corpo que o widget diz ter — o botão puxado pelo ímã, a ficha que
        # subiu —, ou o retângulo inteiro de quem não diz nada.
        corpo_declarado = getattr(widget, "corpo", None)
        corpo = corpo_declarado if isinstance(corpo_declarado, QRectF) else QRectF(widget.rect())
        if isinstance(widget, Botao):
            canto = {"chanfrada": 3.0, "reta": 2.0}.get(widget.forma, float(design.RAIO))
        else:
            canto = float(getattr(widget, "raio_borda", design.RAIO))
        origem = QPointF(widget.mapTo(janela, QPoint(0, 0)))
    except RuntimeError:
        # A lista do histórico se refaz a cada busca: o botão que estava sob o
        # cursor pode já não existir quando o quadro seguinte pergunta por ele.
        return None
    caixa = corpo.translated(origem).adjusted(
        -FOLGA_ABRACO, -FOLGA_ABRACO, FOLGA_ABRACO, FOLGA_ABRACO
    )
    if caixa.height() > ALTURA_MAXIMA_ABRACO or caixa.width() * caixa.height() > AREA_MAXIMA_ABRACO:
        return None
    return caixa, canto + FOLGA_ABRACO


class CampoMagnetico:
    """Os botões magnéticos de uma janela, puxados pelo cursor dela.

    A janela sabe onde o cursor está; cada botão sabe como reagir. Isto só faz
    a ponte, levando o ponto para as coordenadas de cada botão.
    """

    def __init__(self, janela: QWidget) -> None:
        self._janela = janela
        self._botoes: list[Botao] | None = None

    @property
    def botoes(self) -> list[Botao]:
        # Procurados na primeira vez, e não na construção: a janela ainda está
        # sendo montada quando o campo nasce. Só os desta JANELA: o caderno e a
        # revisão são filhos da janela principal, e a busca recursiva trazia os
        # botões deles junto — puxados por um cursor de outra janela, com
        # coordenadas que não significam nada lá.
        if self._botoes is None:
            self._botoes = [
                b for b in self._janela.findChildren(Botao)
                if b.magnetico and b.window() is self._janela
            ]
        return self._botoes

    def mover(self, ponto: QPointF | None, _alvo: QWidget | None = None) -> None:
        for botao in self.botoes:
            botao.atrair(None if ponto is None else botao.mapFrom(self._janela, ponto))


class RastreadorDeCursor(QObject):
    """Avisa ``ao_mover`` a cada movimento sobre a janela, e ``None`` ao sair.

    Com o ponto vai o widget clicável sob o cursor — ``None`` sobre o que não
    responde a clique —, que é o que o anel abraça.

    O filtro recebe TODO evento da aplicação — pintura, relógio, teclado —, e
    por isso a primeira coisa que ele olha é o tipo: tudo que não é movimento
    nem saída volta na hora.
    """

    def __init__(
        self,
        janela: QWidget,
        ao_mover: Callable[[QPointF | None, QWidget | None], None],
        ao_clicar: Callable[[QPointF], None] | None = None,
    ) -> None:
        super().__init__(janela)
        self._janela = janela
        self._ao_mover = ao_mover
        self._ao_clicar = ao_clicar
        # O Qt repassa um clique não aceito a cada ancestral do widget clicado, e
        # o filtro da aplicação o vê em cada um: um clique virava quatro ondas.
        # Instante e posição na tela identificam o MESMO clique entre as cópias.
        self._ultimo_clique: tuple[int, float, float] | None = None
        # O mesmo movimento chega mais de uma vez: como MouseMove ao widget sob
        # o cursor e como HoverMove a ele e a cada ancestral que o acompanha.
        # Cada aviso refaz a luz e o ímã de todos os botões; repetido, é só custo.
        self._ultimo_movimento: tuple[float, float, int] | None = None
        aplicacao = QApplication.instance()
        if aplicacao is not None:
            aplicacao.installEventFilter(self)

    def eventFilter(self, alvo: QObject, evento: QEvent) -> bool:
        tipo = evento.type()
        if tipo in _MOVIMENTOS:
            if (
                isinstance(alvo, QWidget)
                and isinstance(evento, (QMouseEvent, QHoverEvent))
                and alvo.window() is self._janela
            ):
                ponto = alvo.mapTo(self._janela, evento.position())
                sob_o_cursor = alvo if clicavel(alvo) else None
                marca = (ponto.x(), ponto.y(), id(sob_o_cursor) if sob_o_cursor else 0)
                if marca != self._ultimo_movimento:
                    self._ultimo_movimento = marca
                    self._ao_mover(ponto, sob_o_cursor)
        elif tipo == QEvent.Type.MouseButtonPress:
            if (
                self._ao_clicar is not None
                and isinstance(alvo, QWidget)
                and isinstance(evento, QMouseEvent)
                and alvo.window() is self._janela
            ):
                global_ = evento.globalPosition()
                chave = (evento.timestamp(), global_.x(), global_.y())
                if chave != self._ultimo_clique:
                    self._ultimo_clique = chave
                    self._ao_clicar(alvo.mapTo(self._janela, evento.position()))
        elif tipo == QEvent.Type.Leave and alvo is self._janela:
            self._ultimo_movimento = None
            self._ao_mover(None, None)
        return False


class _VidroDoCursor(QWidget):
    """O vidro de uma janela satélite: o que segue o cursor, por cima de tudo."""

    def __init__(self, vivo: CursorVivo, janela: QWidget) -> None:
        super().__init__(janela)
        self._vivo = vivo
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _evento: Any) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._vivo.pintar_vidro(pintor)
        pintor.end()


class CursorVivo(QObject):
    """A resposta ao cursor numa janela satélite: luz, anel, ondas, rastro, ímã e bordas.

    A janela principal tem relógio de quadros e vidro próprios, e o caderno era
    estático: a mesma atmosfera, parada, e só os botões do rodapé sentiam o
    cursor. Esta peça dá a qualquer janela a mesma resposta da principal, com o
    cenário DELA.

    O relógio só corre enquanto alguma coisa persegue o cursor — a luz a
    caminho, o anel, uma onda, uma faísca viva — e para quando tudo assenta:
    a janela não tem partícula nem tremulação próprias (ver ``so_o_cursor``),
    e parada ela não custa nada. O passo é o mesmo da janela principal, o da
    tela. Com a atmosfera desligada, nada disso existe.

    ``cor`` dá a cor das bordas acesas; ``bordas`` lista os contornos que a
    janela quer acesos no vidro — superfícies da folha de estilo, que não se
    pintam sozinhas —, cada um com o raio do canto.
    """

    def __init__(
        self,
        janela: QWidget,
        cenario: Cenario,
        *,
        cor: Callable[[], str],
        bordas: Callable[[], list[tuple[QWidget, float]]] = lambda: [],
    ) -> None:
        super().__init__(janela)
        self._janela = janela
        self._cenario = cenario
        self._cor = cor
        self._bordas = bordas
        self.vidro = _VidroDoCursor(self, janela)
        self.campo = CampoMagnetico(janela)
        self._rastreador = RastreadorDeCursor(janela, self._mover, self._clicar)
        self._relogio = QTimer(self)
        self._relogio.setTimerType(Qt.TimerType.PreciseTimer)
        self._relogio.timeout.connect(self._quadro)
        self._cronometro = QElapsedTimer()
        self._cronometro.start()
        self._ultimo = 0.0
        # O clicável sob o cursor, que o anel abraça. Ver ``abraco_de``.
        self._alvo: QWidget | None = None
        definir_fonte_da_luz(janela, self._luz)
        self.reposicionar()

    @property
    def animando(self) -> bool:
        return self._relogio.isActive()

    def reposicionar(self) -> None:
        """O vidro cobre a janela inteira e fica por cima de tudo."""
        self.vidro.setGeometry(self._janela.rect())
        self.vidro.raise_()

    def esquecer(self) -> None:
        """A janela se escondeu: o cursor que estava nela não está mais."""
        self._cenario.apagar_cursor()
        self._alvo = None
        self.campo.mover(None)
        self.sincronizar()

    def sincronizar(self) -> None:
        """Liga o relógio se algo persegue o cursor, e o desliga quando assenta."""
        if (
            self._cenario.movimento
            and self._cenario.precisa_quadros
            and self._janela.isVisible()
            and not movimento_reduzido()
        ):
            tela = self._janela.screen()
            passo = intervalo_interativo(tela.refreshRate() if tela is not None else 0.0)
            if not self._relogio.isActive():
                self._ultimo = self._cronometro.elapsed() / 1000.0
                self._relogio.start(passo)
            elif self._relogio.interval() != passo:
                self._relogio.setInterval(passo)
        else:
            self._relogio.stop()

    def _mover(self, ponto: QPointF | None, alvo: QWidget | None = None) -> None:
        if movimento_reduzido():
            ponto = None
        self._alvo = alvo if ponto is not None else None
        self._cenario.definir_cursor(ponto, sobre_clicavel=self._alvo is not None)
        self._cenario.definir_abraco(abraco_de(self._alvo, self._janela))
        self.campo.mover(ponto)
        self.sincronizar()

    def _clicar(self, ponto: QPointF) -> None:
        if movimento_reduzido():
            return
        self._cenario.pulsar(ponto)
        self.sincronizar()

    def _quadro(self) -> None:
        agora = self._cronometro.elapsed() / 1000.0
        passo = min(PASSO_MAXIMO, max(0.0, agora - self._ultimo))
        self._ultimo = agora
        # A cada quadro, e não só a cada movimento: o botão magnético segue
        # andando depois que o cursor para, e o anel vai junto.
        self._cenario.definir_abraco(abraco_de(self._alvo, self._janela))
        self._cenario.avancar(passo)
        # Um pedido só, luz e vidro unidos — o mesmo raciocínio da janela
        # principal: o vidro é translúcido, e repintá-lo já é repintar o que
        # está atrás.
        regiao = self._cenario.regiao_suja()
        if regiao is None:
            self._janela.update()
        else:
            regiao = regiao.united(self._cenario.regiao_da_luz())
            if not regiao.isEmpty():
                self._janela.update(regiao)
        self.sincronizar()

    def _luz(self) -> LuzDoCursor | None:
        ponto, forca = self._cenario.luz
        forca *= self._cenario.intensidade
        if forca <= 0.01 or not self._cenario.movimento:
            return None
        return LuzDoCursor(self._janela, ponto, forca, QColor(self._cor()))

    def pintar_vidro(self, pintor: QPainter) -> None:
        self._cenario.pintar_cursor(pintor)
        for widget, canto in self._bordas():
            if not widget.isVisible():
                continue
            caixa = QRectF(
                QPointF(widget.mapTo(self._janela, QPoint(0, 0))), QSizeF(widget.size())
            ).adjusted(0.5, 0.5, -0.5, -0.5)
            contorno = QPainterPath()
            contorno.addRoundedRect(caixa, canto, canto)
            acender_borda(pintor, self.vidro, contorno)
