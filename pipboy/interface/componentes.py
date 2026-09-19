"""Componentes desenhados sobre ``QAbstractButton`` e ``QPainter``.

Três ideias sustentam este módulo:

1. **Estado é contínuo, não binário.** Um botão não está "sob o cursor" ou
   "fora": ele está a 37% do caminho entre os dois. Cada componente guarda
   progressos de 0 a 1 animados por ``QPropertyAnimation`` com curva de
   suavização, e o desenho interpola tudo a partir deles. É o que separa um
   controle que responde de um que pisca.

2. **A forma também é temática.** A atmosfera de cada jogo escolhe entre canto
   arredondado, canto chanfrado (o corte diagonal do HUD de ficção científica)
   e canto reto. Cor sozinha não caracteriza um jogo; geometria caracteriza.

3. **Brilho é aditivo.** Halos e realces são compostos com
   ``CompositionMode_Plus``, então somam luz ao fundo em vez de cobri-lo — que
   é como luz se comporta, e a razão de um fósforo verde parecer aceso.
"""

from __future__ import annotations

import math
import random
import time
from collections.abc import Callable
from itertools import pairwise
from typing import Any, NamedTuple

from PySide6.QtCore import (
    Property,
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QPointF,
    QPropertyAnimation,
    QRectF,
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
    QFontMetrics,
    QHoverEvent,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import design
from .movimento import Transicao


# ------------------------------------------------------------------- Geometria
def caminho_forma(retangulo: QRectF, forma: str, raio: float) -> QPainterPath:
    """Contorno de uma superfície, no vocabulário geométrico do tema."""
    caminho = QPainterPath()
    if forma == "chanfrada":
        # Canto cortado a 45°, o traço de painel técnico e de HUD futurista.
        c = min(raio * 1.3, retangulo.width() / 2, retangulo.height() / 2)
        x, y, larg, alt = (
            retangulo.left(), retangulo.top(), retangulo.width(), retangulo.height()
        )
        caminho.moveTo(x + c, y)
        caminho.lineTo(x + larg, y)
        caminho.lineTo(x + larg, y + alt - c)
        caminho.lineTo(x + larg - c, y + alt)
        caminho.lineTo(x, y + alt)
        caminho.lineTo(x, y + c)
        caminho.closeSubpath()
        return caminho
    if forma == "reta":
        caminho.addRoundedRect(retangulo, 2.0, 2.0)
        return caminho
    caminho.addRoundedRect(retangulo, raio, raio)
    return caminho


def sombra(
    alvo: QWidget, *, raio: int = 24, alpha: int = 90, deslocamento: int = 6,
    cor: str = "#000000",
) -> QGraphicsDropShadowEffect:
    efeito = QGraphicsDropShadowEffect(alvo)
    efeito.setBlurRadius(raio)
    efeito.setOffset(0, deslocamento)
    c = QColor(cor)
    c.setAlpha(alpha)
    efeito.setColor(c)
    alvo.setGraphicsEffect(efeito)
    return efeito


# ------------------------------------------------------------- Movimento
# Quem decide se há movimento é a janela principal, pela atmosfera: ela troca a
# regra ao nascer. Com movimento reduzido, a luz dentro dos botões fica parada no
# centro e nenhum botão é puxado pelo cursor. Uma regra do módulo, e não um
# parâmetro, porque há botões em toda janela e só uma atmosfera.
_regra_do_movimento: Callable[[], bool] = lambda: False  # noqa: E731


def definir_movimento_reduzido(regra: Callable[[], bool]) -> None:
    global _regra_do_movimento
    _regra_do_movimento = regra


def movimento_reduzido() -> bool:
    return bool(_regra_do_movimento())


# ------------------------------------------------------------- Luz do cursor
class LuzDoCursor(NamedTuple):
    """A luz que segue o cursor pela janela principal, como os componentes a veem."""

    janela: QWidget
    ponto: QPointF  # em coordenadas da janela
    forca: float  # de 0 a 1, já com a intensidade da atmosfera
    cor: QColor


# Até onde a luz acende as bordas, em pixels. Tem de caber na caixa que a janela
# repinta em volta da luz a cada quadro (o raio da luz, na atmosfera): uma borda
# acesa fora dela não seria repintada quando a luz se afasta, e ficaria acesa.
ALCANCE_BORDA = 230.0

# Cada janela com luz própria registra de onde ela vem, e acende só os seus
# widgets: a luz de uma janela não tem por que acender os botões de outra.
_fontes_da_luz: dict[QWidget, Callable[[], LuzDoCursor | None]] = {}


def definir_fonte_da_luz(janela: QWidget, fonte: Callable[[], LuzDoCursor | None]) -> None:
    """``janela`` passa a acender as bordas dos seus widgets com a luz de ``fonte``."""
    novo = janela not in _fontes_da_luz
    _fontes_da_luz[janela] = fonte
    if novo:
        janela.destroyed.connect(lambda *_: _fontes_da_luz.pop(janela, None))


def acender_borda(
    pintor: QPainter,
    widget: QWidget,
    caminho: QPainterPath,
    *,
    largura: float = 1.3,
    forca_maxima: float = 0.85,
) -> bool:
    """Acende o contorno ``caminho`` de ``widget`` onde a luz do cursor chega.

    É o efeito das páginas que respondem ao mouse: as bordas perto do cursor
    se acendem antes de ele tocar em nada, e a interface inteira parece
    iluminada por ele. A luz é a MESMA que anda pelo fundo da janela, com o
    mesmo atraso, e por isso a borda nunca adianta nem fica para trás dela.
    Um contorno invisível em repouso também acende: a luz revela a forma.
    Devolve se desenhou alguma coisa.
    """
    fonte = _fontes_da_luz.get(widget.window())
    luz = fonte() if fonte is not None else None
    if luz is None or luz.forca <= 0.01:
        return False
    local = widget.mapFrom(luz.janela, luz.ponto)
    alcance = caminho.boundingRect().adjusted(
        -ALCANCE_BORDA, -ALCANCE_BORDA, ALCANCE_BORDA, ALCANCE_BORDA
    )
    if not alcance.contains(local):
        return False
    gradiente = QRadialGradient(local, ALCANCE_BORDA)
    perto = QColor(luz.cor)
    perto.setAlphaF(min(1.0, forca_maxima * luz.forca))
    meio = QColor(perto)
    meio.setAlphaF(perto.alphaF() * 0.35)
    longe = QColor(perto)
    longe.setAlphaF(0.0)
    gradiente.setColorAt(0.0, perto)
    gradiente.setColorAt(0.45, meio)
    gradiente.setColorAt(1.0, longe)
    pintor.save()
    pintor.setBrush(Qt.BrushStyle.NoBrush)
    pintor.setPen(QPen(QBrush(gradiente), largura))
    pintor.drawPath(caminho)
    pintor.restore()
    return True


# ---------------------------------------------------------------------- Botão
class Botao(QAbstractButton):
    """Botão pintado por inteiro, com transições animadas e foco visível.

    Herda de ``QAbstractButton`` — e não de ``QPushButton`` — porque queremos o
    comportamento (clique, alternância, atalho, acessibilidade, foco por
    teclado) sem uma única linha do desenho nativo.
    """

    DURACAO_HOVER = 160
    DURACAO_PRESSAO = 90
    # O botão magnético é desenhado com esta folga em volta do corpo, que é o
    # espaço para onde ele pode ser puxado: um widget não pinta fora de si.
    FOLGA_IMA = 8
    # A partir de quantos pixels além da borda o botão começa a sentir o cursor.
    ALCANCE_IMA = 110.0

    def __init__(
        self,
        texto: str = "",
        *,
        variante: str = "sutil",
        paleta: Callable[[], dict[str, str]] | None = None,
        forma: str = "arredondada",
        largura_min: int = 0,
        alinhamento_esquerdo: bool = False,
        magnetico: bool = False,
        folga_ima: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._halo_suspenso = False
        self.setText(texto)
        # A folga é o quanto o botão pode ser puxado. O principal ganha a folga
        # inteira; os secundários, uma menor — o ímã deles é um aceno, e uma
        # folga grande em todo botão incharia a janela.
        self._folga = (self.FOLGA_IMA if folga_ima is None else folga_ima) if magnetico else 0
        self._direcao_ima = QPointF()
        # Onde o cursor está sobre o botão, para a luz interna o seguir.
        self._cursor_local: QPointF | None = None
        self.variante = variante
        self.forma = forma
        self._paleta = paleta or (lambda: {})
        self._largura_min = largura_min
        self._esquerdo = alinhamento_esquerdo
        self._hover = 0.0
        self._pressao = 0.0

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(38 + 2 * self._folga)
        # HoverMove para a luz interna seguir o cursor: ver o Holofote sobre por
        # que não mouseMoveEvent.
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

        self._anim_hover = QPropertyAnimation(self, b"progressoHover", self)
        self._anim_hover.setDuration(self.DURACAO_HOVER)
        self._anim_hover.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_pressao = QPropertyAnimation(self, b"progressoPressao", self)
        self._anim_pressao.setDuration(self.DURACAO_PRESSAO)
        self._anim_pressao.setEasingCurve(QEasingCurve.Type.OutQuad)

        self._halo = sombra(self, raio=1, alpha=0, deslocamento=0)
        self._halo.setEnabled(False)
        self._forca_ima = Transicao(
            self, design.DURACAO_MEDIA, self._repintar_ima, reduzir=lambda: False
        )

    # -- ímã
    def atrair(self, ponto: QPointF | None) -> None:
        """O cursor, em coordenadas deste botão; ``None`` solta o ímã.

        Perto do botão, o corpo é puxado na direção do cursor — mais forte
        quanto mais perto — e a auréola acende antes de o cursor chegar: o
        botão principal percebe a intenção, não só o toque. Só vale para o
        botão construído com ``magnetico=True``.
        """
        if not self._folga:
            return
        if (
            ponto is None or not self.isEnabled() or not self.isVisible()
            or movimento_reduzido()
        ):
            self._forca_ima.ir(0.0)
            return
        corpo = QRectF(self.rect()).adjusted(self._folga, self._folga, -self._folga, -self._folga)
        falta = ponto - corpo.center()
        fora = max(
            0.0, abs(falta.x()) - corpo.width() / 2, abs(falta.y()) - corpo.height() / 2
        )
        forca = max(0.0, 1.0 - fora / self.ALCANCE_IMA)
        if forca <= 0.0 and self._forca_ima.valor <= 0.0:
            # Longe e já solto: nada a desenhar. O campo chama TODO botão a cada
            # movimento do cursor, e esta repintura de quem nem sente o ímã
            # custava cinco botões por quadro. O ``ir`` interrompe uma subida
            # pedida há pouco que ainda não saiu do zero.
            self._forca_ima.ir(0.0)
            return
        limite = float(self._folga)
        self._direcao_ima = QPointF(
            max(-limite, min(limite, falta.x() * 0.16)),
            max(-limite, min(limite, falta.y() * 0.30)),
        )
        self._forca_ima.ir(forca)
        self.update()

    @property
    def magnetico(self) -> bool:
        return self._folga > 0

    def tornar_magnetico(self, folga: int = FOLGA_IMA) -> None:
        """Liga o ímã num botão já construído, reservando a folga em volta dele."""
        self._folga = folga
        self.setMinimumHeight(38 + 2 * folga)
        self.updateGeometry()

    def suspender_halo(self) -> None:
        """Apaga a auréola de vez, para um botão que vai sumir sob outro efeito.

        Um efeito do Qt dentro de outro que pega o atalho de pintura direta
        reclama de dois pintores no mesmo pixmap. Quem desmonta o botão assim
        o avisa antes, e o hover não a religa mais.
        """
        self._halo_suspenso = True
        self._halo.setEnabled(False)

    @property
    def deslocamento_ima(self) -> QPointF:
        return self._direcao_ima * self._forca_ima.valor

    @property
    def cursor_local(self) -> QPointF | None:
        return self._cursor_local

    def _repintar_ima(self, _valor: float) -> None:
        self._atualizar_halo()
        self.update()

    # -- propriedades animáveis
    def _get_hover(self) -> float:
        return self._hover

    def _set_hover(self, valor: float) -> None:
        self._hover = valor
        self._atualizar_halo()
        self.update()

    def _get_pressao(self) -> float:
        return self._pressao

    def _set_pressao(self, valor: float) -> None:
        self._pressao = valor
        self.update()

    progressoHover = Property(float, _get_hover, _set_hover)
    progressoPressao = Property(float, _get_pressao, _set_pressao)

    def _animar(self, animacao: QPropertyAnimation, destino: float) -> None:
        animacao.stop()
        nome = bytes(animacao.propertyName()).decode()
        animacao.setStartValue(animacao.targetObject().property(nome))
        animacao.setEndValue(destino)
        animacao.start()

    # -- eventos
    def enterEvent(self, evento: Any) -> None:
        if self.isEnabled():
            self._animar(self._anim_hover, 1.0)
        if isinstance(evento, QEnterEvent):
            self._cursor_local = QPointF(evento.position())
        super().enterEvent(evento)

    def event(self, evento: QEvent) -> bool:
        if evento.type() == QEvent.Type.HoverMove and isinstance(evento, QHoverEvent):
            self._cursor_local = QPointF(evento.position())
            if self._hover > 0.0:
                self.update()
        return super().event(evento)

    def leaveEvent(self, evento: Any) -> None:
        self._animar(self._anim_hover, 0.0)
        super().leaveEvent(evento)

    def mousePressEvent(self, evento: Any) -> None:
        self._animar(self._anim_pressao, 1.0)
        super().mousePressEvent(evento)

    def mouseReleaseEvent(self, evento: Any) -> None:
        self._animar(self._anim_pressao, 0.0)
        super().mouseReleaseEvent(evento)

    def changeEvent(self, evento: Any) -> None:
        super().changeEvent(evento)
        if not self.isEnabled():
            self._anim_hover.stop()
            self._hover = 0.0
            self._atualizar_halo()
        self.update()

    def sizeHint(self) -> QSize:
        metricas = QFontMetrics(self.font())
        largura = metricas.horizontalAdvance(self.text()) + 46
        folga = 2 * self._folga
        return QRectF(0, 0, max(self._largura_min, largura) + folga, 38 + folga).size().toSize()

    def minimumSizeHint(self) -> QSize:
        """O texto do botão é um piso, não uma sugestão.

        Sem isto, a política ``Preferred`` deixa o Qt encolher o botão abaixo
        do próprio rótulo quando a barra fica apertada, e nós desenhamos o
        texto com ``drawText`` num retângulo menor que ele: na janela no
        tamanho mínimo, "○   Mudo" saía recortado no meio, como "Mudc". Um
        botão pintado por conta própria não tem elipse para se salvar — quem
        precisa ceder espaço numa barra lotada é o texto auxiliar ao lado,
        não o rótulo de um controle.
        """
        return self.sizeHint()

    # -- cor
    def _cores(self) -> tuple[QColor, QColor, QColor | None, QColor]:
        """Fundo, texto, contorno e cor do halo, já no estado atual."""
        p = self._paleta()
        vazio = QColor("#808080")
        if not p:
            return vazio, vazio, None, vazio

        if not self.isEnabled():
            # Texto em text_disabled, não em faint: um chip desligado ainda
            # precisa dizer QUAL opção está desligada. Quem comunica o
            # estado é a superfície rebaixada, não a ilegibilidade.
            return (
                QColor(design.misturar(p["screen"], p["surface"], 0.5)),
                QColor(p["text_disabled"]),
                None,
                QColor(p["faint"]),
            )

        ligado = self.isCheckable() and self.isChecked()
        if self.variante == "primario":
            fundo, frente, contorno = QColor(p["primary"]), QColor(p["on_primary"]), None
            halo = QColor(p["primary"])
        elif self.variante == "perigo":
            fundo, frente, contorno = QColor(p["alert"]), QColor(p["on_alert"]), None
            halo = QColor(p["alert"])
        elif self.variante == "acento":
            base = QColor(p["accent"])
            fundo = QColor(design.misturar(p["screen"], p["accent"], 0.14))
            frente = QColor(design.garantir_contraste(p["accent"], fundo.name()))
            contorno = QColor(design.misturar(p["screen"], p["accent"], 0.55))
            halo = base
        elif self.variante == "perigo_sutil":
            # Destrutivo, mas repetido dezenas de vezes numa lista: gritar em
            # vermelho em todos os cartões transformaria o caderno num painel
            # de alarmes. Fica neutro em repouso e assume o vermelho conforme o
            # cursor chega — o aviso aparece no instante em que passa a
            # importar. A interpolação é o próprio ``_hover``.
            base = QColor(p["alert"])
            fundo = QColor(design.misturar(p["surface_alta"], p["alert"], 0.42 * self._hover))
            frente = QColor(
                design.garantir_contraste(
                    design.misturar(p["text_muted"], p["alert"], self._hover), fundo.name()
                )
            )
            contorno = QColor(design.misturar(p["border"], p["alert"], 0.7 * self._hover))
            halo = base
        elif self.variante == "chip":
            if ligado:
                fundo = QColor(design.misturar(p["surface"], p["accent"], 0.26))
                frente = QColor(design.garantir_contraste(p["accent"], fundo.name()))
                contorno = QColor(design.misturar(p["surface"], p["accent"], 0.55))
            else:
                fundo = QColor(p["surface_alta"])
                frente = QColor(p["text_muted"])
                contorno = QColor(p["border"])
            halo = QColor(p["accent"])
        else:  # sutil
            fundo = QColor(p["surface_alta"])
            frente = QColor(p["text_muted"])
            contorno = None
            halo = QColor(p["primary"])
        return fundo, frente, contorno, halo

    def _atualizar_halo(self) -> None:
        """Auréola externa proporcional ao avanço do cursor.

        Uma sombra colorida com deslocamento zero é uma auréola. Animar o raio
        junto com a opacidade evita o efeito de "liga/desliga" que uma sombra
        fixa produziria.
        """
        _, _, _, halo = self._cores()
        forca = getattr(self, "_forca_ima", None)
        proximidade = 0.75 * forca.valor if forca is not None else 0.0
        intensidade = max(self._hover, proximidade) * (
            1.0 if self.variante in ("primario", "perigo") else 0.6
        )
        cor = QColor(halo)
        cor.setAlpha(int(150 * intensidade))
        # Apagada, a auréola DESLIGA. Ligado, o efeito desenha o botão num pixmap
        # à parte e o desfoca a cada repintura, mesmo com alfa zero — e a luz do
        # cursor repinta os botões sob ela a cada quadro.
        ligada = cor.alpha() > 0 and not self._halo_suspenso
        if self._halo.isEnabled() != ligada:
            self._halo.setEnabled(ligada)
        if not ligada:
            return
        self._halo.setColor(cor)
        self._halo.setBlurRadius(6 + 26 * intensidade)
        self._halo.setOffset(0, 0)

    # -- desenho
    def paintEvent(self, _evento: Any) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        fundo, frente, contorno, halo = self._cores()

        # A pressão afunda o botão 1 px e escurece: resposta física ao toque.
        recuo = self._pressao
        folga = self._folga
        area = QRectF(self.rect()).adjusted(
            0.5 + folga, 0.5 + folga + recuo, -0.5 - folga, -0.5 - folga + recuo
        ).translated(self.deslocamento_ima)
        caminho = caminho_forma(area, self.forma, design.RAIO)

        if self.isEnabled():
            fundo = QColor(design.misturar(fundo.name(), "#ffffff", 0.12 * self._hover))
            fundo = QColor(design.misturar(fundo.name(), "#000000", 0.16 * self._pressao))
            if self._hover > 0.0:
                # O rótulo era escolhido contra o fundo EM REPOUSO, e o hover
                # clareava o fundo sem reconferir: no Cyberpunk, o amarelo-oliva
                # do texto sumia no botão aceso. O contraste é garantido contra o
                # fundo já clareado e com a luz interna somada.
                aceso = design.misturar(fundo.name(), halo.name(), 0.25 * self._hover)
                frente = QColor(design.garantir_contraste(frente.name(), aceso))

        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(fundo)
        pintor.drawPath(caminho)

        if contorno is not None:
            caneta = QPen(contorno)
            caneta.setWidthF(1.2)
            pintor.setPen(caneta)
            pintor.setBrush(Qt.BrushStyle.NoBrush)
            pintor.drawPath(caminho)
        if self.isEnabled():
            acender_borda(pintor, self, caminho)

        # Realce interno aditivo: um véu uniforme que dá volume e, por cima dele,
        # uma luz que acompanha o cursor DENTRO do botão — o ponto que ele toca
        # acende mais que o resto. Os dois somem junto com o cursor.
        if self._hover > 0.01 and self.isEnabled():
            pintor.save()
            pintor.setClipPath(caminho)
            pintor.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            brilho = QColor(halo)
            brilho.setAlphaF(min(1.0, 0.08 * self._hover))
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(brilho)
            pintor.drawPath(caminho)
            centro = (
                area.center()
                if self._cursor_local is None or movimento_reduzido()
                else self._cursor_local
            )
            # Contida: com mais força, a luz da cor do tema lavava o próprio
            # rótulo do botão — amarelo sobre amarelo no Cyberpunk.
            luz = QRadialGradient(centro, max(area.width(), area.height()) * 0.55)
            perto = QColor(halo)
            perto.setAlphaF(min(1.0, 0.17 * self._hover))
            longe = QColor(perto)
            longe.setAlphaF(0.0)
            luz.setColorAt(0.0, perto)
            luz.setColorAt(1.0, longe)
            pintor.fillRect(area, luz)
            pintor.restore()

        if self.hasFocus():
            # Anel de foco POR DENTRO. A versão anterior desenhava o anel 3 px
            # para fora do corpo, e um widget não pinta fora do próprio
            # retângulo: o Qt recortava o anel inteiro. Nos temas de canto
            # arredondado ele simplesmente sumia — navegação por teclado sem
            # indicação nenhuma — e nos chanfrados sobravam os bicos das
            # diagonais, uns riscos soltos ao lado do botão. Por dentro o anel
            # cabe, e o contraste garantido contra o próprio preenchimento
            # impede que ele se confunda com a borda.
            caneta = QPen(QColor(design.garantir_contraste(halo.name(), fundo.name(), 3.0)))
            caneta.setWidthF(1.6)
            pintor.setPen(caneta)
            pintor.setBrush(Qt.BrushStyle.NoBrush)
            pintor.drawPath(
                caminho_forma(
                    area.adjusted(2.5, 2.5, -2.5, -2.5),
                    self.forma,
                    max(2.0, design.RAIO - 2.5),
                )
            )

        self._pintar_rotulo(pintor, area, frente)
        pintor.end()

    def _pintar_rotulo(self, pintor: QPainter, area: QRectF, frente: QColor) -> None:
        """O conteúdo sobre o corpo já pintado. Separado para quem troca só isto."""
        pintor.setPen(frente)
        pintor.setFont(self.font())
        bandeiras = (
            Qt.AlignmentFlag.AlignVCenter
            | (Qt.AlignmentFlag.AlignLeft if self._esquerdo else Qt.AlignmentFlag.AlignHCenter)
        )
        # 14 px é o respiro de um botão de texto. Num botão-ícone de 28 px,
        # tirar 14 de cada lado deixa um retângulo de largura ZERO e o Qt
        # simplesmente não desenha — foi assim que o "×" de remover um termo
        # virou uma caixinha vazia. O recuo nunca pode comer mais que um quarto
        # da largura de cada lado.
        recuo_h = min(14.0, area.width() / 4.0)
        pintor.drawText(area.adjusted(recuo_h, 0, -recuo_h, 0), int(bandeiras), self.text())


class BotaoDeEstado(Botao):
    """Botão que confirma, no próprio lugar, o que acabou de fazer.

    Nasceu do Exportar do caderno. A exportação escrevia o arquivo e anunciava
    o resultado no registro da janela principal — que fica ATRÁS do caderno.
    Quem clicava via o seletor de arquivo fechar e mais nada: sem saber se o
    arquivo tinha sido escrito, o natural era exportar de novo.

    Três decisões de feedback:

    * **Sucesso muda a matéria, não só o texto.** O corpo se enche da cor de
      acento e um sinal de visto se desenha traço a traço. Um rótulo trocando
      sozinho passa despercebido; uma superfície que se enche, não.
    * **A largura é a do maior rótulo.** Um botão que muda de tamanho ao virar
      "Exportado" desloca os vizinhos no instante em que a pessoa olha.
    * **Volta sozinho.** O estado confirmado é notícia, não configuração: em
      ``RETORNO_MS`` o botão está pronto de novo, sem pedir clique para fechar.

    Hover, pressão, auréola e anel de foco continuam sendo os do ``Botao``: só
    as cores (``_cores``) e o conteúdo (``_pintar_rotulo``) são trocados.
    """

    RETORNO_MS = 1800
    ICONE = 14.0
    VAO = 8.0

    def __init__(
        self,
        texto: str,
        concluido: str,
        *,
        reduzir: Callable[[], bool],
        variante: str = "sutil",
        paleta: Callable[[], dict[str, str]] | None = None,
        forma: str = "arredondada",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(texto, variante=variante, paleta=paleta, forma=forma, parent=parent)
        self._rotulos = {"ocioso": texto, "concluido": concluido}
        self._estado = "ocioso"
        self._anterior = "ocioso"
        self._dica_ociosa = ""
        self._troca = Transicao(self, design.DURACAO_MEDIA, self._repintar, reduzir=reduzir)
        self._troca.saltar(1.0)
        self._sucesso = Transicao(self, design.DURACAO_LENTA, self._repintar, reduzir=reduzir)
        self._retorno = QTimer(self)
        self._retorno.setSingleShot(True)
        self._retorno.setInterval(self.RETORNO_MS)
        self._retorno.timeout.connect(lambda: self._mudar("ocioso"))

    @property
    def estado(self) -> str:
        return self._estado

    def concluir(self, detalhe: str = "") -> None:
        """Mostra o sucesso por ``RETORNO_MS``; ``detalhe`` vira a dica nesse meio-tempo."""
        if self._estado == "ocioso":
            self._dica_ociosa = self.toolTip()
        if detalhe:
            self.setToolTip(detalhe)
            self.setAccessibleDescription(detalhe)
        self._mudar("concluido")

    def _mudar(self, estado: str) -> None:
        if estado == "concluido":
            # Concluir de novo dentro da janela só estende o aviso.
            self._retorno.start()
        if estado == self._estado:
            return
        if estado == "ocioso":
            self.setToolTip(self._dica_ociosa)
            self.setAccessibleDescription("")
        self._anterior, self._estado = self._estado, estado
        self.setText(self._rotulos[estado])
        self._troca.saltar(0.0)
        self._troca.ir(1.0)
        self._sucesso.ir(1.0 if estado == "concluido" else 0.0)

    def _repintar(self, _valor: float) -> None:
        self._atualizar_halo()
        self.update()

    def sizeHint(self) -> QSize:
        # O construtor do Botao pode perguntar o tamanho antes de haver rótulos.
        rotulos = getattr(self, "_rotulos", None)
        if rotulos is None:
            return super().sizeHint()
        metricas = QFontMetrics(self.font())
        largura = max(
            metricas.horizontalAdvance(rotulos["ocioso"]),
            metricas.horizontalAdvance(rotulos["concluido"]) + self.ICONE + self.VAO,
        )
        folga = 2 * self._folga
        return QSize(max(self._largura_min, round(largura) + 46) + folga, 38 + folga)

    def _cores(self) -> tuple[QColor, QColor, QColor | None, QColor]:
        fundo, frente, contorno, halo = super()._cores()
        sucesso = getattr(self, "_sucesso", None)
        p = self._paleta()
        if sucesso is None or sucesso.valor <= 0.0 or not p or not self.isEnabled():
            return fundo, frente, contorno, halo
        s = sucesso.valor
        base = contorno.name() if contorno is not None else fundo.name()
        return (
            QColor(design.misturar(fundo.name(), p["accent"], s)),
            QColor(design.misturar(frente.name(), p["on_accent"], s)),
            QColor(design.misturar(base, p["accent"], s)),
            QColor(p["accent"]),
        )

    def _pintar_rotulo(self, pintor: QPainter, area: QRectF, frente: QColor) -> None:
        # O que sai sobe e esmaece; o que entra vem de baixo. Seis pixels
        # bastam: é direção, não viagem.
        troca = self._troca.valor
        if troca < 1.0:
            self._pintar_conteudo(pintor, area, frente, self._anterior, 1.0 - troca, -6.0 * troca)
        self._pintar_conteudo(pintor, area, frente, self._estado, troca, 6.0 * (1.0 - troca))

    def _pintar_conteudo(
        self, pintor: QPainter, area: QRectF, cor: QColor, estado: str,
        opacidade: float, deslocamento: float,
    ) -> None:
        if opacidade <= 0.01:
            return
        texto = self._rotulos[estado]
        icone = self.ICONE if estado == "concluido" else 0.0
        vao = self.VAO if icone else 0.0
        largura = QFontMetrics(self.font()).horizontalAdvance(texto) + icone + vao
        x = area.center().x() - largura / 2.0
        centro_y = area.center().y() + deslocamento

        pintor.save()
        pintor.setOpacity(opacidade)
        if icone:
            caneta = QPen(cor)
            caneta.setWidthF(2.0)
            caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
            caneta.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pintor.setPen(caneta)
            pintor.setBrush(Qt.BrushStyle.NoBrush)
            caixa = QRectF(x, centro_y - icone / 2.0, icone, icone)
            pintor.drawPath(caminho_visto(caixa, self._sucesso.valor))
        pintor.setPen(cor)
        pintor.setFont(self.font())
        pintor.drawText(
            QRectF(x + icone + vao, area.top() + deslocamento, largura, area.height()),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            texto,
        )
        pintor.restore()


def caminho_visto(caixa: QRectF, progresso: float) -> QPainterPath:
    """Sinal de visto desenhado até ``progresso`` do próprio comprimento.

    Desenhado, e não digitado: o "✓" é do bloco Dingbats, que Consolas e
    Georgia não têm — sairia como caixinha em metade dos temas, a mesma
    armadilha do "✕" documentada no caderno.
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
        caminho.lineTo(a + (b - a) * min(1.0, restante / comprimento))
        restante -= comprimento
    return caminho


# ------------------------------------------------------------------ Holofote
class Holofote:
    """A luz de uma superfície que percebe o cursor.

    Um holofote na cor pedida acompanha o cursor, a superfície sobe um degrau
    e o contorno acende do lado da luz. Nasceu no cartão do caderno e saiu de
    lá quando a tela inicial quis a mesma luz nos próprios cartões: duas cópias
    de um gradiente radial divergem no primeiro ajuste de alcance, e a janela
    passaria a ter duas luzes que quase combinam.

    Não é widget: quem hospeda sabe se está sob o cursor, onde ele está e quem
    tem o foco, e repassa isso. O holofote guarda a posição, anima a
    intensidade e pinta.
    """

    ALCANCE = 260.0

    def __init__(self, dono: QWidget, *, reduzir: Callable[[], bool]) -> None:
        self._dono = dono
        self._reduzir = reduzir
        self.cursor: QPointF | None = None
        self._intensidade = Transicao(
            dono, design.DURACAO_RAPIDA, lambda _v: dono.update(), reduzir=reduzir
        )
        # O dono passa a receber HoverMove, e é por ele que deve seguir o
        # cursor — não por mouseMoveEvent. O Qt DESCARTA o movimento sem botão
        # que cai sobre um filho sem rastreamento, e ele não sobe para o pai:
        # no cartão do caderno, a luz congelava assim que o cursor passava
        # sobre a tradução ou o exemplo, que são quase o cartão todo. O
        # HoverMove é entregue a todo ancestral com WA_Hover.
        dono.setAttribute(Qt.WidgetAttribute.WA_Hover)

    @property
    def valor(self) -> float:
        return self._intensidade.valor

    def acender(self, ligado: bool) -> None:
        self._intensidade.ir(1.0 if ligado else 0.0)

    def seguir(self, ponto: QPointF) -> None:
        self.cursor = ponto
        if self.valor > 0.0 and not self._reduzir():
            self._dono.update()

    def _centro(self, foco: QWidget | None) -> QPointF:
        if foco is self._dono:
            return QPointF(self._dono.rect().center())
        if foco is not None:
            return QPointF(foco.mapTo(self._dono, foco.rect().center()))
        if self._reduzir() or self.cursor is None:
            # Luz parada no alto, como uma luminária: a superfície ainda se
            # destaca, só não persegue o cursor.
            return QPointF(self._dono.width() * 0.3, 0.0)
        return self.cursor

    def pintar(
        self, pintor: QPainter, caminho: QPainterPath, *,
        fundo: str, cor: str, borda: str, foco: QWidget | None = None,
    ) -> None:
        """Superfície, luz e contorno. ``foco`` guia a luz quando não há cursor.

        Quem chama passa ``foco`` só quando a presença veio do TECLADO: com o
        cursor em cima, é ele quem manda na luz.
        """
        luz = self.valor
        area = caminho.boundingRect()

        # A superfície sobe um degrau. Elevação em tema escuro é luz, não
        # sombra: sombra preta sobre um fundo quase preto não se vê.
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(QColor(design.misturar(fundo, design.elevar(fundo, 0.07, cor), luz)))
        pintor.drawPath(caminho)

        centro = self._centro(foco)
        if luz > 0.005:
            # Somada à superfície, pela regra deste módulo: brilho é aditivo.
            pintor.save()
            pintor.setClipPath(caminho)
            pintor.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            gradiente = QRadialGradient(centro, self.ALCANCE)
            perto = QColor(cor)
            perto.setAlphaF(0.16 * luz)
            longe = QColor(perto)
            longe.setAlphaF(0.0)
            gradiente.setColorAt(0.0, perto)
            gradiente.setColorAt(1.0, longe)
            pintor.fillRect(area, gradiente)
            pintor.restore()

        # Um fio discreto em repouso, que acende do lado da luz. O gradiente
        # radial na CANETA é o que faz a borda parecer iluminada pela mesma
        # luz, e não pintada de outra cor.
        repouso = QColor(borda)
        if luz > 0.005:
            fio = QRadialGradient(centro, self.ALCANCE * 0.8)
            fio.setColorAt(0.0, QColor(design.misturar(borda, cor, 0.95 * luz)))
            fio.setColorAt(1.0, repouso)
            caneta = QPen(QBrush(fio), 1.2)
        else:
            caneta = QPen(repouso, 1.0)
        pintor.setPen(caneta)
        pintor.setBrush(Qt.BrushStyle.NoBrush)
        pintor.drawPath(caminho)


# ------------------------------------------------------------------- Seletor
class CampoSelecao(QComboBox):
    """Combobox com a seta desenhada por nós, para acompanhar o tema."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cor_seta = QColor("#888888")
        self._cor_luz = QColor("#888888")
        # O canto que a folha de estilo dá à caixa: a borda acesa segue o mesmo.
        self._raio_borda = 8.0
        self._cursor_local: QPointF | None = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # O seletor também acende sob o cursor, como os botões: numa coluna de
        # oito seletores iguais, a luz diz em qual deles o mouse está.
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._luz = Transicao(
            self, design.DURACAO_RAPIDA, lambda _v: self.update(), reduzir=movimento_reduzido
        )

    def definir_cor_seta(self, cor: str) -> None:
        self._cor_seta = QColor(cor)
        self.update()

    def definir_cor_luz(self, cor: str, raio_borda: float | None = None) -> None:
        self._cor_luz = QColor(cor)
        if raio_borda is not None:
            self._raio_borda = raio_borda
        self.update()

    @property
    def luz(self) -> float:
        return self._luz.valor

    def enterEvent(self, evento: Any) -> None:
        if self.isEnabled():
            self._luz.ir(1.0)
        if isinstance(evento, QEnterEvent):
            self._cursor_local = QPointF(evento.position())
        super().enterEvent(evento)

    def leaveEvent(self, evento: Any) -> None:
        self._luz.ir(0.0)
        super().leaveEvent(evento)

    def event(self, evento: QEvent) -> bool:
        if evento.type() == QEvent.Type.HoverMove and isinstance(evento, QHoverEvent):
            self._cursor_local = QPointF(evento.position())
            if self._luz.valor > 0.0:
                self.update()
        return super().event(evento)

    def paintEvent(self, evento: Any) -> None:
        super().paintEvent(evento)
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._luz.valor > 0.01 and self.isEnabled():
            centro = (
                QPointF(self.rect().center())
                if self._cursor_local is None or movimento_reduzido()
                else self._cursor_local
            )
            luz = QRadialGradient(centro, max(60.0, self.width() * 0.45))
            perto = QColor(self._cor_luz)
            perto.setAlphaF(0.16 * self._luz.valor)
            longe = QColor(perto)
            longe.setAlphaF(0.0)
            luz.setColorAt(0.0, perto)
            luz.setColorAt(1.0, longe)
            pintor.save()
            pintor.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            pintor.fillRect(self.rect(), luz)
            pintor.restore()
        if self.isEnabled():
            contorno = QPainterPath()
            contorno.addRoundedRect(
                QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                self._raio_borda, self._raio_borda,
            )
            acender_borda(pintor, self, contorno)
        caneta = QPen(self._cor_seta)
        caneta.setWidthF(1.6)
        caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
        caneta.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pintor.setPen(caneta)

        cx = self.width() - 18
        cy = self.height() / 2
        caminho = QPainterPath()
        caminho.moveTo(cx - 4, cy - 2)
        caminho.lineTo(cx, cy + 2.5)
        caminho.lineTo(cx + 4, cy - 2)
        pintor.drawPath(caminho)
        pintor.end()


def css_campo_selecao(tema: Any, raio: int, rgba: Callable[[str, float], str]) -> str:
    """Folha de estilo do ``CampoSelecao``, para quem hospedar um.

    Mora ao lado do widget porque a pele é dele, não da janela. Ela nasceu
    dentro da folha da janela principal, e quando o caderno passou a ter um
    seletor a alternativa era copiar quarenta linhas de CSS — com os
    comentários que explicam cada armadilha — para uma segunda folha, onde
    envelheceriam separadas.

    ``rgba`` é injetado porque a translucidez das superfícies serve à
    atmosfera pintada atrás delas, e quem sabe se há atmosfera atrás é o
    hospedeiro: a janela principal tem cenário vivo, um diálogo pode não ter.
    """
    return f"""
        QComboBox {{
            background: {rgba(tema.surface_alta, 0.92)}; color: {tema.primary};
            border: 1px solid transparent; border-radius: {raio}px;
            padding: 6px 30px 6px 12px;
        }}
        QComboBox:hover, QComboBox:focus {{ border-color: {tema.border_forte}; }}
        /* Travado, não apagado: o texto continua legível (é o que diz o que
           está valendo na sessão) e quem comunica o travamento é a superfície,
           que perde o preenchimento e passa a mostrar só o contorno. Meia dúzia
           de contornos tracejados empilhados numa coluna lê como formulário
           quebrado; o traço contínuo diz a mesma coisa sem o ruído. */
        QComboBox:disabled {{
            color: {tema.text_disabled};
            background: {rgba(tema.surface_alta, 0.30)};
            border: 1px solid {tema.border};
        }}
        QComboBox::drop-down {{ border: none; width: 28px; }}
        QComboBox QAbstractItemView {{
            background: {tema.surface_alta}; color: {tema.primary};
            border: 1px solid {tema.border}; border-radius: {raio}px;
            outline: none; padding: 4px;
        }}
        /* O item precisa ser estilizado NOMINALMENTE. Declarar apenas
           'selection-background-color' na lista não basta: o popup não detém o
           foco de teclado enquanto é desenhado, e nesse estado o Qt resolve o
           destaque pelo grupo de paleta *Inactive* — que no Windows é um cinza
           do sistema. A linha escolhida saía lavada, com o cinza por baixo de
           um texto pensado para o realce do tema. Com a regra ::item o estado
           é nosso, ativo ou não. */
        /* ESCOLHIDO e SOB O CURSOR são coisas diferentes e precisam parecer
           diferentes. Estavam com o mesmo preenchimento cheio de acento, então
           a lista mostrava dois blocos amarelos idênticos e não dizia qual era
           o valor atual. Além disso, uma faixa sólida de ponta a ponta é o
           tratamento de lista do Windows 95.

           Agora: o cursor apenas ELEVA a linha, em cinza, sem cor nenhuma —
           passar o mouse não é uma decisão. O valor escolhido ganha uma barra
           de acento na margem e o texto na cor do acento, com só um véu de
           fundo. A barra transparente em TODOS os itens reserva o espaço, para
           que a linha escolhida não pule 3 px para o lado. */
        QComboBox QAbstractItemView::item {{
            padding: 7px 10px; border-radius: {max(2, raio - 2)}px;
            color: {tema.primary}; background: transparent;
            border-left: 3px solid transparent;
        }}
        QComboBox QAbstractItemView::item:hover {{
            background: {design.elevar(tema.screen, 0.18, tema.primary)};
        }}
        QComboBox QAbstractItemView::item:selected {{
            background: {design.misturar(tema.surface_alta, tema.accent, 0.13)};
            color: {design.garantir_contraste(
                tema.accent, design.misturar(tema.surface_alta, tema.accent, 0.13))};
            border-left: 3px solid {tema.accent};
        }}
        QComboBox QAbstractItemView::item:selected:hover {{
            background: {design.misturar(tema.surface_alta, tema.accent, 0.22)};
            color: {design.garantir_contraste(
                tema.accent, design.misturar(tema.surface_alta, tema.accent, 0.22))};
        }}
    """


# ------------------------------------------------------------------- Medidor
class Medidor(QWidget):
    """Medidor de nível com balística de VU e brilho aditivo nas barras vivas."""

    QUEDA = 0.055
    PICO_SEGURA_S = 0.9
    PICO_QUEDA = 0.02

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._valor = 0.0
        self._pico = 0.0
        self._pico_em = 0.0
        self._nivel_alvo = 0.0
        self._limiar = 0.0
        self._ativo = False
        self._cores = {
            "primary": "#4dff7a", "accent": "#ffb000",
            "alert": "#ff5c5c", "apagada": "#1c4a2c", "limiar": "#7f8c8d",
        }
        self.setFixedSize(
            design.MEDIDOR_BARRAS * (design.MEDIDOR_LARGURA_BARRA + design.MEDIDOR_ESPACO_BARRA),
            design.MEDIDOR_ALTURA + 2,
        )
        # Ligado só enquanto houver sessão: sem áudio entrando não há balística
        # para integrar, e o traço de repouso é estático.
        self._relogio = QTimer(self)
        self._relogio.timeout.connect(self._quadro)

    def definir_cores(self, **cores: str) -> None:
        self._cores.update(cores)
        self.update()

    def definir_nivel(self, nivel: float) -> None:
        # A conversão para a régua acontece na ENTRADA, e não na pintura, para
        # que a balística (queda e retenção de pico) integre em unidades de
        # tela. Convertida só na hora de desenhar, a queda constante de
        # ``QUEDA`` viraria um tombo acelerado no alto da régua e uma lesma no
        # pé — a mesma velocidade de sinal parecendo três velocidades de tinta.
        self._nivel_alvo = design.escala_do_medidor(nivel)

    def definir_limiar(self, limiar: float) -> None:
        """Onde o portão de voz abre, na mesma régua do nível. 0.0 esconde.

        É o que transforma o medidor de enfeite em diagnóstico: enquanto o
        limiar era invisível, "estou falando e ele não me ouve" não tinha como
        ser respondido olhando a tela.
        """
        novo = design.escala_do_medidor(limiar) if limiar > 0.0 else 0.0
        if abs(novo - self._limiar) > 0.005:
            self._limiar = novo
            self.update()

    def definir_ativo(self, ativo: bool) -> None:
        """Liga ou apaga o medidor conforme exista sessão.

        Sem sessão não há sinal, e dezoito barras apagadas viravam um bloco de
        ruído cinza permanente ao lado da cápsula de estado — a peça mais
        chamativa de uma barra que deveria estar em repouso. Apagado, o medidor
        vira um traço fino de linha de base; aceso, cresce e ganha cor.
        """
        if ativo != self._ativo:
            self._ativo = ativo
            if ativo:
                self._relogio.start(60)
            else:
                self._valor = self._pico = 0.0
                self._relogio.stop()
            self.update()

    def _quadro(self) -> None:
        if not self._ativo and self._valor <= 0.0 and self._pico <= 0.0:
            # Já está no traço de repouso e nada muda: repintar dezesseis vezes
            # por segundo um desenho idêntico é trabalho puro.
            return
        agora = time.monotonic()
        nivel = self._nivel_alvo
        self._valor = max(nivel, self._valor - self.QUEDA)
        if nivel >= self._pico:
            self._pico, self._pico_em = nivel, agora
        elif agora - self._pico_em > self.PICO_SEGURA_S:
            self._pico = max(self._valor, self._pico - self.PICO_QUEDA)
        self.update()

    def paintEvent(self, _evento: Any) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        pintor.setPen(Qt.PenStyle.NoPen)

        passo = design.MEDIDOR_LARGURA_BARRA + design.MEDIDOR_ESPACO_BARRA
        acesas = round(self._valor * design.MEDIDOR_BARRAS)
        indice_pico = min(
            design.MEDIDOR_BARRAS - 1, round(self._pico * design.MEDIDOR_BARRAS) - 1
        )
        base = float(design.MEDIDOR_ALTURA)

        if not self._ativo:
            repouso = QColor(self._cores["apagada"])
            repouso.setAlphaF(0.65)
            pintor.setBrush(repouso)
            for i in range(design.MEDIDOR_BARRAS):
                pintor.drawRoundedRect(
                    QRectF(i * passo, base - 2.0, design.MEDIDOR_LARGURA_BARRA, 2.0),
                    1.0, 1.0,
                )
            pintor.end()
            return

        # O risco do limiar vai ANTES das barras e cai numa FOLGA entre elas:
        # atravessado por cima do desenho ele leria como defeito de pintura, e
        # a folga é o único lugar da régua onde uma linha vertical não disputa
        # espaço com nada. À esquerda dele o portão retém; à direita, transmite.
        if self._limiar > 0.0:
            barra_limiar = round(self._limiar * design.MEDIDOR_BARRAS)
            if 0 < barra_limiar < design.MEDIDOR_BARRAS:
                x = barra_limiar * passo - design.MEDIDOR_ESPACO_BARRA / 2.0
                pintor.setBrush(QColor(self._cores["limiar"]))
                pintor.drawRect(QRectF(x - 0.5, 0.0, 1.0, base + 2.0))

        for i in range(design.MEDIDOR_BARRAS):
            fracao = i / (design.MEDIDOR_BARRAS - 1)
            altura = base * (0.45 + 0.55 * fracao)
            if fracao >= 0.85:
                viva = self._cores["alert"]
            elif fracao >= 0.65:
                viva = self._cores["accent"]
            else:
                viva = self._cores["primary"]

            acesa = i < acesas
            if acesa:
                cor = viva
            elif i == indice_pico and self._pico > 0.02:
                cor = design.misturar(self._cores["apagada"], viva, 0.55)
            else:
                cor = self._cores["apagada"]

            retangulo = QRectF(i * passo, base - altura, design.MEDIDOR_LARGURA_BARRA, altura)
            pintor.setBrush(QColor(cor))
            pintor.drawRoundedRect(retangulo, 1.5, 1.5)

            if acesa:
                # Barra acesa sangra luz para os lados, como um segmento real.
                pintor.save()
                pintor.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
                brilho = QColor(viva)
                brilho.setAlphaF(0.16)
                pintor.setBrush(brilho)
                pintor.drawRoundedRect(retangulo.adjusted(-1.6, -1.2, 1.6, 1.2), 2.5, 2.5)
                pintor.restore()
        pintor.end()


# ------------------------------------------------------------------- Rótulo
class RotuloElidido(QLabel):
    """Rótulo que abrevia com elipse em vez de ser cortado pelo layout.

    A distinção que faz isto funcionar: ``sizeHint`` devolve sempre a largura
    do texto COMPLETO, e ``minimumSizeHint`` devolve zero. O layout portanto
    pede o espaço inteiro quando ele existe e sabe que pode tomá-lo de volta
    quando falta — sem o efeito catraca de encolher a dica junto com o texto
    já abreviado, que travaria o rótulo estreito para sempre. A elipse é só
    pintura; o texto de verdade continua guardado e vai para a dica.
    """

    def __init__(self, parent: QWidget | None = None, **kwargs: Any) -> None:
        super().__init__(parent, **kwargs)
        self._completo = ""
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def definir_texto(self, texto: str) -> None:
        if texto != self._completo:
            self._completo = texto
            self.setToolTip(texto)
            self.updateGeometry()
            self._aplicar()

    def _aplicar(self) -> None:
        metricas = QFontMetrics(self.font())
        super().setText(
            metricas.elidedText(
                self._completo, Qt.TextElideMode.ElideRight, max(0, self.width())
            )
        )

    def sizeHint(self) -> QSize:
        metricas = QFontMetrics(self.font())
        return QSize(metricas.horizontalAdvance(self._completo), metricas.height())

    def minimumSizeHint(self) -> QSize:
        return QSize(0, QFontMetrics(self.font()).height())

    def resizeEvent(self, evento: Any) -> None:
        super().resizeEvent(evento)
        self._aplicar()


class RotuloDecifravel(QLabel):
    """Um rótulo que se decifra: as letras embaralham e se resolvem uma a uma.

    O efeito dos terminais nas páginas que respondem ao mouse — e dos próprios
    jogos: um terminal do Fallout liga assim. Sob o cursor, o nome do aparelho
    e os títulos das seções embaralham e se resolvem da esquerda para a
    direita em meio segundo; trocar de jogo decifra o nome novo no lugar do
    antigo.

    O texto do rótulo é sempre o de verdade. ``text()`` o devolve mesmo no meio
    do embaralho, e o nome acessível também: um leitor de tela não lê "K#V7".
    Só o que se DESENHA passa pelo embaralho, e o tamanho fica preso ao do
    texto verdadeiro enquanto isso — a régua ao lado de um título não pode
    tremer, nem uma quebra de linha pular.
    """

    DURACAO = 480
    # Parte do tempo em que todas as letras ficam embaralhadas antes de a
    # primeira se resolver: sem ela, a primeira letra nem chegava a mudar.
    ESPERA = 0.18
    # De quanto em quanto tempo as letras sorteadas trocam. A cada quadro da
    # animação, sessenta vezes por segundo, o embaralho vira chiado.
    TROCA_MS = 45
    # Só ASCII: existe em toda fonte de todo tema, e nenhuma letra vira caixinha.
    MAIUSCULAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#%&*+<>/="
    MINUSCULAS = "abcdefghijklmnopqrstuvwxyz0123456789"

    def __init__(
        self, texto: str = "", parent: QWidget | None = None, *, objectName: str = ""
    ) -> None:
        super().__init__(texto, parent)
        if objectName:
            self.setObjectName(objectName)
        self._texto = texto
        self.setAccessibleName(texto)
        self._limites: tuple[QSize, QSize] | None = None
        self._animacao = QVariantAnimation(self)
        self._animacao.setStartValue(0.0)
        self._animacao.setEndValue(1.0)
        self._animacao.setDuration(self.DURACAO)
        self._animacao.valueChanged.connect(self._quadro)
        # O último quadro já desenha o texto inteiro: no fim, só falta soltar.
        self._animacao.finished.connect(self._soltar)

    def text(self) -> str:
        return self._texto

    def setText(self, texto: str) -> None:
        self._texto = texto
        self.setAccessibleName(texto)
        if self.decifrando:
            # O embaralho continua, agora rumo ao texto novo — e com o tamanho
            # dele.
            self._soltar()
            QLabel.setText(self, texto)
            self._prender()
        else:
            QLabel.setText(self, texto)

    @property
    def decifrando(self) -> bool:
        return self._animacao.state() == QAbstractAnimation.State.Running

    @property
    def desenhado(self) -> str:
        """O que está desenhado agora, embaralhado ou não."""
        return QLabel.text(self)

    def decifrar(self) -> None:
        """Embaralha o texto e o resolve letra a letra. Nada, com movimento reduzido."""
        if movimento_reduzido() or not self.isVisible() or not self._texto.strip():
            return
        if self.decifrando:
            return
        self._prender()
        self._animacao.start()

    def enterEvent(self, evento: Any) -> None:
        self.decifrar()
        super().enterEvent(evento)

    def _prender(self) -> None:
        """Prende o tamanho ao do texto verdadeiro, que já está desenhado."""
        self._limites = (self.minimumSize(), self.maximumSize())
        dica = self.sizeHint()
        self.setFixedSize(max(self.width(), dica.width()), max(self.height(), dica.height()))

    def _soltar(self) -> None:
        if self._limites is not None:
            minimo, maximo = self._limites
            self.setMinimumSize(minimo)
            self.setMaximumSize(maximo)
            self._limites = None

    def _quadro(self, valor: Any) -> None:
        progresso = float(valor)
        balde = int(progresso * self.DURACAO / self.TROCA_MS)
        # A mesma semente dentro de um balde: as letras sorteadas ficam paradas
        # entre uma troca e outra, e o que avança nesse meio-tempo é só quem se
        # resolveu.
        sorteio = random.Random(balde * 7919 + len(self._texto))
        resolvidas = int(max(0.0, (progresso - self.ESPERA) / (1.0 - self.ESPERA)) * len(self._texto))
        letras = [
            letra
            if i < resolvidas or not letra.isalnum()
            else sorteio.choice(self.MINUSCULAS if letra.islower() else self.MAIUSCULAS)
            for i, letra in enumerate(self._texto)
        ]
        QLabel.setText(self, "".join(letras))


class Desvanecer(QWidget):
    """Véu de gradiente no pé de uma área rolável.

    Uma coluna que rola sem dar sinal disso não parece rolável: parece
    cortada. Era o caso da lateral, onde o corte caía sobre o título de uma
    seção e a última linha visível virava um cabeçalho órfão. O véu resolve
    isso com a economia de uma sombra — sem barra extra, sem seta, sem texto —
    e some sozinho quando a rolagem chega ao fim, porque aí não há mais nada
    para anunciar.
    """

    ALTURA = 26

    def __init__(self, parent: QWidget, cor: Callable[[], str]) -> None:
        super().__init__(parent)
        self._cor = cor
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedHeight(self.ALTURA)

    def paintEvent(self, _evento: Any) -> None:
        pintor = QPainter(self)
        gradiente = QLinearGradient(0.0, 0.0, 0.0, float(self.height()))
        opaca = QColor(self._cor())
        transparente = QColor(opaca)
        transparente.setAlpha(0)
        gradiente.setColorAt(0.0, transparente)
        gradiente.setColorAt(1.0, opaca)
        pintor.fillRect(self.rect(), gradiente)
        pintor.end()


# -------------------------------------------------------------------- Pílula
class Pilula(QWidget):
    """Cápsula de estado com pulso contínuo e anel de propagação."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._texto = "OFFLINE"
        self._cor = QColor("#8b98a5")
        self._cheia = QColor("#8b98a5")
        self._fundo = QColor("#171c22")
        self._pulsando = False
        self.setFixedHeight(design.PILULA_ALTURA)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        # O relógio só existe para animar o anel de propagação. Ele era ligado
        # na construção e nunca mais parava: vinte e cinco despertares por
        # segundo, pela vida inteira do programa, para conferir um booleano que
        # passa quase todo o tempo em falso. Agora ele acompanha o estado.
        self._relogio = QTimer(self)
        self._relogio.timeout.connect(self._talvez_repintar)

    def _talvez_repintar(self) -> None:
        self.update()

    def definir(self, texto: str, cor: str, fundo_janela: str, pulsando: bool) -> None:
        fundo = design.misturar(fundo_janela, cor, 0.18)
        self._texto = texto
        self._cheia = QColor(cor)
        self._cor = QColor(design.garantir_contraste(cor, fundo))
        self._fundo = QColor(fundo)
        self._pulsando = pulsando
        if pulsando and not self._relogio.isActive():
            self._relogio.start(40)
        elif not pulsando and self._relogio.isActive():
            self._relogio.stop()
        self.setFixedWidth(self.fontMetrics().horizontalAdvance(texto) + 46)
        self.update()

    def paintEvent(self, _evento: Any) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        pintor.setPen(Qt.PenStyle.NoPen)

        altura = float(self.height())
        pintor.setBrush(self._fundo)
        pintor.drawRoundedRect(QRectF(0, 0, self.width(), altura), altura / 2, altura / 2)

        cx, cy, raio = 14.0, altura / 2, 3.5
        if self._pulsando:
            # Anel que nasce no ponto e se dissipa: comunica "algo está
            # acontecendo agora" muito melhor que um ponto que só pisca.
            fase = (time.monotonic() * 1.1) % 1.0
            anel = QColor(self._cheia)
            anel.setAlphaF(max(0.0, 0.45 * (1.0 - fase)))
            caneta = QPen(anel)
            caneta.setWidthF(1.4)
            pintor.setPen(caneta)
            pintor.setBrush(Qt.BrushStyle.NoBrush)
            pintor.drawEllipse(QPointF(cx, cy), raio + 7 * fase, raio + 7 * fase)
            pintor.setPen(Qt.PenStyle.NoPen)

        pintor.save()
        pintor.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        auréola = QColor(self._cheia)
        auréola.setAlphaF(0.28)
        pintor.setBrush(auréola)
        pintor.drawEllipse(QPointF(cx, cy), raio * 2.4, raio * 2.4)
        pintor.restore()

        pintor.setBrush(self._cheia)
        pintor.drawEllipse(QPointF(cx, cy), raio, raio)

        pintor.setPen(self._cor)
        pintor.drawText(
            QRectF(26, 0, self.width() - 30, altura),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self._texto,
        )
        pintor.end()


# --------------------------------------------------------------------- Bolha
class Bolha(QFrame):
    """Uma fala. Forma temática, sombra, brilho de fósforo e entrada animada."""

    def __init__(
        self,
        texto: str,
        *,
        fundo: str,
        cor_texto: str,
        fonte: QFont,
        largura_max: int,
        forma: str = "arredondada",
        brilho_texto: float = 0.0,
        contorno: str = "",
        acento: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._fundo = QColor(fundo)
        self._contorno = QColor(contorno) if contorno else None
        self._forma = forma

        caixa = QVBoxLayout(self)
        caixa.setContentsMargins(15, 11, 15, 11)

        rotulo = QLabel(texto)
        rotulo.setWordWrap(True)
        rotulo.setFont(fonte)
        realce = design.css_selecao(fundo, acento or cor_texto, cor_texto)
        rotulo.setStyleSheet(f"color: {cor_texto}; background: transparent; {realce}")
        rotulo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        # A largura precisa ser calculada: um QLabel com quebra de linha dentro
        # de um layout colapsa para a largura mínima, e a bolha sairia estreita
        # e alta em vez de acompanhar o texto até o limite.
        disponivel = largura_max - 30
        ideal = QFontMetrics(fonte).horizontalAdvance(texto)
        rotulo.setFixedWidth(max(80, min(disponivel, ideal)))
        caixa.addWidget(rotulo)

        if brilho_texto > 0:
            # Fósforo: as letras sangram luz na própria cor. É o traço mais
            # reconhecível de um terminal CRT, e nenhuma cor sozinha o produz.
            sombra(
                rotulo, raio=int(10 * brilho_texto), alpha=int(190 * brilho_texto),
                deslocamento=0, cor=cor_texto,
            )

        self.setMaximumWidth(largura_max)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _evento: Any) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        caminho = caminho_forma(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), self._forma, design.RAIO
        )
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(self._fundo)
        pintor.drawPath(caminho)

        if self._contorno is not None:
            # O painel da conversa é translúcido de propósito, e por isso a
            # bolha do assistente ficava a 1.27:1 dele — presente na conta,
            # quase nada no olho. Encher mais a bolha mataria a atmosfera que
            # atravessa o painel; um fio de 1 px define a MESMA borda por
            # outro meio, que é como um cartão se separa do fundo sem pesar.
            caneta = QPen(self._contorno)
            caneta.setWidthF(1.0)
            pintor.setPen(caneta)
            pintor.setBrush(Qt.BrushStyle.NoBrush)
            pintor.drawPath(caminho)
        acender_borda(pintor, self, caminho)
        pintor.end()

    def animar_entrada(self) -> None:
        """Aparecimento suave, com o efeito descartado ao fim.

        Duas armadilhas resolvidas aqui. A primeira: um ``QGraphicsOpacityEffect``
        que fica pendurado no widget para sempre custa uma superfície fora da
        tela em toda repintura, e a conversa acumula centenas deles. A segunda,
        pior: se o laço de eventos não chegar a rodar — janela ainda oculta,
        captura de tela, máquina travada — a opacidade nunca sai de zero e a
        fala simplesmente não aparece. Descartar o efeito no fim garante que o
        estado final seja o widget normal, não uma animação interrompida.
        """
        efeito = QGraphicsOpacityEffect(self)
        efeito.setOpacity(0.0)
        self.setGraphicsEffect(efeito)
        self._animacao: QPropertyAnimation | None = QPropertyAnimation(efeito, b"opacity", self)
        self._animacao.setDuration(220)
        self._animacao.setStartValue(0.0)
        self._animacao.setEndValue(1.0)
        self._animacao.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animacao.finished.connect(self._encerrar_entrada)
        self._animacao.start()

    def _encerrar_entrada(self) -> None:
        # None limpa o efeito — aceito pelo Qt, ainda ausente nas stubs.
        self.setGraphicsEffect(None)  # type: ignore[arg-type]
        self._animacao = None


class LinhaFala(QWidget):
    """Cabeçalho (autor · hora) mais a bolha, alinhados pelo lado do autor."""

    def __init__(
        self,
        bolha: Bolha,
        *,
        cabecalho: str | None,
        cor_cabecalho: str,
        fonte_cabecalho: QFont,
        direita: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        coluna = QVBoxLayout(self)
        # Só quem ABRE um turno afasta-se do que veio antes. Falas
        # seguidas do mesmo interlocutor não têm cabeçalho e ficam
        # coladas, que é o que faz um bloco de fala parecer um bloco.
        coluna.setContentsMargins(0, 13 if cabecalho else 0, 0, 0)
        coluna.setSpacing(4)

        if cabecalho:
            rotulo = QLabel(cabecalho)
            rotulo.setFont(fonte_cabecalho)
            rotulo.setStyleSheet(f"color: {cor_cabecalho}; background: transparent;")
            rotulo.setAlignment(
                Qt.AlignmentFlag.AlignRight if direita else Qt.AlignmentFlag.AlignLeft
            )
            coluna.addWidget(rotulo)

        linha = QHBoxLayout()
        linha.setContentsMargins(0, 0, 0, 0)
        if direita:
            linha.addStretch(1)
            linha.addWidget(bolha)
        else:
            linha.addWidget(bolha)
            linha.addStretch(1)
        coluna.addLayout(linha)


# ------------------------------------------------------------------ Transição
class TransicaoDeTema(QWidget):
    """Dissolve a fotografia do tema antigo sobre o novo.

    Trocar de jogo repinta a janela inteira num único quadro — funcional, mas
    com a brusquidão de um interruptor. Aqui a janela é fotografada ANTES da
    troca e a fotografia desvanece por cima do tema novo, como um aparelho
    que troca de modo, não um programa que troca de folha de estilo.

    O widget é transparente ao mouse (a janela continua utilizável durante a
    dissolução) e se destrói ao final. Quem respeita a preferência de
    atmosfera desligada é o chamador — animação também é atmosfera.
    """

    DURACAO = 380

    def __init__(self, parent: QWidget, retrato: Any) -> None:
        super().__init__(parent)
        self._retrato = retrato
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(parent.rect())

        efeito = QGraphicsOpacityEffect(self)
        efeito.setOpacity(1.0)
        self.setGraphicsEffect(efeito)
        animacao = QPropertyAnimation(efeito, b"opacity", self)
        animacao.setDuration(self.DURACAO)
        animacao.setStartValue(1.0)
        animacao.setEndValue(0.0)
        animacao.setEasingCurve(QEasingCurve.Type.OutCubic)
        animacao.finished.connect(self.deleteLater)
        self.show()
        self.raise_()
        animacao.start()

    def paintEvent(self, _evento: Any) -> None:
        pintor = QPainter(self)
        pintor.drawPixmap(0, 0, self._retrato)
        pintor.end()
