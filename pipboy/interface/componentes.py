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

import time
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
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


# ---------------------------------------------------------------------- Botão
class Botao(QAbstractButton):
    """Botão pintado por inteiro, com transições animadas e foco visível.

    Herda de ``QAbstractButton`` — e não de ``QPushButton`` — porque queremos o
    comportamento (clique, alternância, atalho, acessibilidade, foco por
    teclado) sem uma única linha do desenho nativo.
    """

    DURACAO_HOVER = 160
    DURACAO_PRESSAO = 90

    def __init__(
        self,
        texto: str = "",
        *,
        variante: str = "sutil",
        paleta: Callable[[], dict[str, str]] | None = None,
        forma: str = "arredondada",
        largura_min: int = 0,
        alinhamento_esquerdo: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setText(texto)
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
        self.setMinimumHeight(38)

        self._anim_hover = QPropertyAnimation(self, b"progressoHover", self)
        self._anim_hover.setDuration(self.DURACAO_HOVER)
        self._anim_hover.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_pressao = QPropertyAnimation(self, b"progressoPressao", self)
        self._anim_pressao.setDuration(self.DURACAO_PRESSAO)
        self._anim_pressao.setEasingCurve(QEasingCurve.Type.OutQuad)

        self._halo = sombra(self, raio=1, alpha=0, deslocamento=0)

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
        super().enterEvent(evento)

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
        return QRectF(0, 0, max(self._largura_min, largura), 38).size().toSize()

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
        intensidade = self._hover * (1.0 if self.variante in ("primario", "perigo") else 0.6)
        cor = QColor(halo)
        cor.setAlpha(int(150 * intensidade))
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
        area = QRectF(self.rect()).adjusted(0.5, 0.5 + recuo, -0.5, -0.5 + recuo)
        caminho = caminho_forma(area, self.forma, design.RAIO)

        if self.isEnabled():
            fundo = QColor(design.misturar(fundo.name(), "#ffffff", 0.12 * self._hover))
            fundo = QColor(design.misturar(fundo.name(), "#000000", 0.16 * self._pressao))

        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(fundo)
        pintor.drawPath(caminho)

        if contorno is not None:
            caneta = QPen(contorno)
            caneta.setWidthF(1.2)
            pintor.setPen(caneta)
            pintor.setBrush(Qt.BrushStyle.NoBrush)
            pintor.drawPath(caminho)

        # Realce interno aditivo na borda superior: dá volume sem gradiente
        # chapado, e some junto com o cursor.
        if self._hover > 0.01 and self.isEnabled():
            pintor.save()
            pintor.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            brilho = QColor(halo)
            brilho.setAlphaF(min(1.0, 0.10 * self._hover))
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(brilho)
            pintor.drawPath(caminho)
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
        pintor.end()


# ------------------------------------------------------------------- Seletor
class CampoSelecao(QComboBox):
    """Combobox com a seta desenhada por nós, para acompanhar o tema."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cor_seta = QColor("#888888")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def definir_cor_seta(self, cor: str) -> None:
        self._cor_seta = QColor(cor)
        self.update()

    def paintEvent(self, evento: Any) -> None:
        super().paintEvent(evento)
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
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
