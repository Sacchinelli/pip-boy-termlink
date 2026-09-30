"""O aviso de palavra nova: cada jogo anuncia do jeito dele.

Quando a sessão salva uma palavra no caderno, a janela toca um blip, solta um
"+1" do contador da lateral e deixa uma anotação na conversa. Os três dizem que
algo foi salvo; nenhum diz em que jogo se está — e é justamente o instante em
que os jogos mais capricham. A faixa escura que atravessa a tela com letras de
ouro surgindo devagar (Elden Ring), o nome descoberto entre dois fios (Skyrim),
o "diário atualizado" no canto sobre uma pincelada vermelha (Red Dead), o
letreiro de missão cumprida (GTA), a medalha de pontos do abate (Battlefield):
quem jogou reconhece o anúncio antes de ler. Aprender uma palavra é a conquista
deste programa, e ela ganha o anúncio que o jogo daria.

Pela regra de ``ornamentos``: nada de imagem ou logotipo de terceiros — só
``QPainter`` sobre a paleta do tema e as fontes livres de ``fontes.py`` —, e o
que se evoca é o estilo, não a marca. Cada estilo é uma função de (pintor, painel, recado, contexto) que não
guarda estado; toda letra passa por ``_escrever``, que anota onde caiu e em que
cor, e é por essa anotação que a suíte mede o contraste sobre o que foi
pintado embaixo.

O anúncio fica DENTRO da moldura do painel e longe do pé dele: a fala mais
nova — e a anotação da palavra recém-salva — mora embaixo, e um anúncio que a
cobrisse esconderia a própria notícia.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from PySide6.QtCore import QEasingCurve, QEvent, QPointF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from .. import design
from .componentes import movimento_reduzido
from .ornamentos import FAIXA_MOLDURA, contorno_de_pincel

# Do canto do painel até o anúncio: a faixa da moldura e um respiro.
MARGEM = FAIXA_MOLDURA + 8.0
# O contraste pedido às letras do anúncio. Um pouco acima do AA para que o
# arredondamento de 8 bits da composição não o derrube para 4,49.
CONTRASTE = 4.8
# O véu atrás das letras. Alto de propósito: o anúncio passa por cima de
# falas da conversa, e é contra o PIOR fundo possível — letra clara embaixo —
# que as letras dele precisam continuar lendo.
VEU = 0.93


@dataclass(frozen=True, slots=True)
class Recado:
    """O que se anuncia: a palavra, o sentido dela e quantas chegaram juntas."""

    termo: str
    traducao: str = ""
    novas: int = 1


@dataclass(slots=True)
class Contexto:
    """O que um estilo precisa saber além do recado.

    ``entrada`` vai de 0 a 1 na chegada, já com a curva aplicada, e fica em 1
    sem movimento; ``vida`` é a fração do tempo de tela que já passou.
    ``letras`` desliga a escrita (e só ela): é como a suíte enxerga o que ficou
    EMBAIXO de cada letra.
    """

    tema: Any
    familia_tema: str
    familia_ui: str
    escala: float = 1.0
    # A letra dos títulos do jogo (ver GameTheme.titulos); vazia, a do tema.
    familia_titulo: str = ""
    entrada: float = 1.0
    vida: float = 0.5
    movimento: bool = True
    letras: bool = True
    escritos: list[tuple[QRectF, QColor, str]] = field(default_factory=list)

    def fonte(
        self, tamanho: float, *, tema: bool = True, negrito: bool = False,
        italico: bool = False, espaco: float = 0.0, titulo: bool = False,
    ) -> QFont:
        if titulo and self.familia_titulo:
            familia = self.familia_titulo
        else:
            familia = self.familia_tema if tema else self.familia_ui
        fonte = QFont(familia)
        fonte.setPointSizeF(tamanho * self.escala)
        fonte.setBold(negrito)
        fonte.setItalic(italico)
        if espaco:
            fonte.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, espaco)
        return fonte


def contexto_de(provedor: Any, **ajustes: Any) -> Contexto:
    """O contexto do jogo em vigor, com as fontes e o tamanho de texto da janela."""
    corpo = provedor.fonte("corpo")
    return Contexto(
        tema=provedor.tema,
        familia_tema=provedor.fonte("corpo", ui=False).family(),
        familia_ui=corpo.family(),
        familia_titulo=provedor.fonte("display", ui=False).family(),
        escala=corpo.pointSizeF() / design.TIPO["corpo"].tamanho,
        **ajustes,
    )


# ------------------------------------------------------------------ Letras
def _largura(fonte: QFont, texto: str) -> float:
    metricas = QFontMetricsF(fonte)
    # O maior entre avanço e tinta: a itálica passa do avanço pela direita.
    return max(metricas.horizontalAdvance(texto), metricas.boundingRect(texto).width()) + 2.0


def _altura(fonte: QFont) -> float:
    return QFontMetricsF(fonte).height()


def _encurtar(fonte: QFont, texto: str, maximo: float) -> str:
    return QFontMetricsF(fonte).elidedText(texto, Qt.TextElideMode.ElideRight, maximo)


def _escrever(
    pintor: QPainter, c: Contexto, fonte: QFont, cor: QColor, caixa: QRectF, texto: str,
    alinhar: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft,
) -> QRectF:
    """Escreve e anota onde a letra caiu e em que cor. Devolve a caixa justa."""
    bandeiras = int(alinhar | Qt.AlignmentFlag.AlignVCenter)
    justa = QFontMetricsF(fonte).boundingRect(caixa, bandeiras, texto)
    if c.letras:
        pintor.setFont(fonte)
        pintor.setPen(cor)
        pintor.drawText(caixa, bandeiras, texto)
    c.escritos.append((justa, QColor(cor), texto))
    return justa


def _legivel(c: Contexto, frente: str, veu: str, alfa: float = VEU) -> QColor:
    """``frente`` ajustada para ler sobre ``veu`` — sobre o fundo e sobre letra.

    O véu é translúcido: o que se vê atrás da letra é ele composto sobre o
    que houver embaixo. Garante-se contra as duas composições extremas, a
    tela vazia e uma fala clara, e vale a pior.
    """
    return QColor(_legivel_sobre(frente, veu, alfa, c.tema.screen, c.tema.primary))


@lru_cache(maxsize=256)
def _legivel_sobre(frente: str, veu: str, alfa: float, tela: str, fala: str) -> str:
    fundos = (design.misturar(tela, veu, alfa), design.misturar(fala, veu, alfa))
    pior = min(fundos, key=lambda fundo: design.contraste(frente, fundo))
    cor = design.garantir_contraste(frente, pior, CONTRASTE)
    for fundo in fundos:
        cor = design.garantir_contraste(cor, fundo, CONTRASTE)
    return cor


def _com_contagem(texto: str, novas: int) -> str:
    return f"{texto} ({novas})" if novas > 1 else texto


def _cor(base: str, alfa: float) -> QColor:
    cor = QColor(base)
    cor.setAlphaF(max(0.0, min(1.0, alfa)))
    return cor


def _escuro(t: Any, quanto: float = 0.55) -> str:
    """O véu escuro do jogo: a tela dele puxada para o preto, e não um preto neutro."""
    return design.misturar(t.screen, "#000000", quanto)


def _faixa_que_some(
    pintor: QPainter, caixa: QRectF, cor: str, alfa: float, borda: float
) -> None:
    """Uma faixa cheia no meio que se apaga nas duas pontas."""
    gradiente = QLinearGradient(caixa.topLeft(), caixa.topRight())
    gradiente.setColorAt(0.0, _cor(cor, 0.0))
    gradiente.setColorAt(borda, _cor(cor, alfa))
    gradiente.setColorAt(1.0 - borda, _cor(cor, alfa))
    gradiente.setColorAt(1.0, _cor(cor, 0.0))
    pintor.fillRect(caixa, QBrush(gradiente))


def _fio_que_some(
    pintor: QPainter, de: float, ate: float, y: float, cor: str, alfa: float, largura: float
) -> None:
    gradiente = QLinearGradient(QPointF(de, y), QPointF(ate, y))
    gradiente.setColorAt(0.0, _cor(cor, alfa))
    gradiente.setColorAt(1.0, _cor(cor, 0.0))
    pintor.setPen(QPen(QBrush(gradiente), largura))
    pintor.drawLine(QPointF(de, y), QPointF(ate, y))


# ----------------------------------------------------------------- Estilos
# O título de cada anúncio. Mora aqui, e não no tema, porque é inseparável do
# desenho: "DIÁRIO ATUALIZADO" é o que se escreve NA pincelada.
MANCHETES: dict[str, str] = {
    "": "Salvo no caderno",
    "terminal": "+ TERMO ADICIONADO",
    "graca": "PALAVRA APRENDIDA",
    "descoberta": "PALAVRA DESCOBERTA",
    "diario": "Glossário atualizado",
    "cartaz": "DIÁRIO ATUALIZADO",
    "missao": "PALAVRA NOVA",
    "fragmento": "// DADO RECEBIDO",
    "pergaminho": "Conhecimento adquirido",
    "abate": "PALAVRA CONFIRMADA",
}


def _cartao(pintor: QPainter, painel: QRectF, r: Recado, c: Contexto) -> QRectF:
    """O neutro: um cartão discreto no alto, que desce um pouco ao chegar."""
    t = c.tema
    fundo = t.surface_alta
    manchete_f = c.fonte(9, tema=False, espaco=0.6)
    termo_f = c.fonte(14, negrito=True)
    traducao_f = c.fonte(10, tema=False)
    limite = painel.width() * 0.5
    manchete = _com_contagem(MANCHETES[""], r.novas)
    termo = _encurtar(termo_f, r.termo, limite)
    traducao = _encurtar(traducao_f, r.traducao, limite)
    largura = max(_largura(manchete_f, manchete), _largura(termo_f, termo),
                  _largura(traducao_f, traducao)) + 40
    altura = 24 + _altura(manchete_f) + _altura(termo_f) + (_altura(traducao_f) if traducao else 0)
    y = painel.top() + MARGEM + 10.0 * (1.0 - c.entrada)
    caixa = QRectF(painel.center().x() - largura / 2, y, largura, altura)
    caminho = QPainterPath()
    caminho.addRoundedRect(caixa, 10.0, 10.0)
    pintor.fillPath(caminho, _cor(fundo, 0.98))
    pintor.setPen(QPen(QColor(t.border_forte), 1.0))
    pintor.drawPath(caminho)
    x, y = caixa.left() + 20, caixa.top() + 12
    for fonte, cor, texto in (
        (manchete_f, t.text_muted, manchete),
        (termo_f, t.primary, termo),
        (traducao_f, t.text_muted, traducao),
    ):
        if texto:
            _escrever(pintor, c, fonte, _legivel(c, cor, fundo, 0.98),
                      QRectF(x, y, caixa.width() - 40, _altura(fonte)), texto)
            y += _altura(fonte)
    return caixa


def _terminal(pintor: QPainter, painel: QRectF, r: Recado, c: Contexto) -> QRectF:
    """Fallout: a caixa do terminal no canto, com a barra invertida no alto e o
    termo sendo DATILOGRAFADO atrás do cursor em bloco."""
    t = c.tema
    fundo = _escuro(t, 0.35)
    barra_f = c.fonte(9, negrito=True, espaco=1.0)
    termo_f = c.fonte(15, negrito=True)
    traducao_f = c.fonte(10)
    limite = painel.width() * 0.45
    manchete = _com_contagem(MANCHETES["terminal"], r.novas)
    termo = _encurtar(termo_f, f"> {r.termo}", limite)
    traducao = _encurtar(traducao_f, f"  {r.traducao}", limite) if r.traducao else ""
    largura = max(220.0, _largura(barra_f, manchete), _largura(termo_f, termo) + 16,
                  _largura(traducao_f, traducao)) + 28
    alto_barra = _altura(barra_f) + 6
    altura = alto_barra + 14 + _altura(termo_f) + (_altura(traducao_f) if traducao else 0)
    caixa = QRectF(painel.left() + MARGEM, painel.top() + MARGEM, largura, altura)
    pintor.fillRect(caixa, _cor(fundo, VEU))
    pintor.setPen(QPen(QColor(t.primary), 1.0))
    pintor.drawRect(caixa.adjusted(0.5, 0.5, -0.5, -0.5))
    barra = QRectF(caixa.left(), caixa.top(), caixa.width(), alto_barra)
    pintor.fillRect(barra, QColor(t.primary))
    _escrever(pintor, c, barra_f, QColor(design.garantir_contraste(t.on_primary, t.primary, CONTRASTE)),
              barra.adjusted(10, 0, -10, 0), manchete)
    # Datilografado: as letras entram uma a uma durante a chegada.
    visiveis = len(termo) if c.entrada >= 1.0 else math.ceil(len(termo) * c.entrada)
    y = barra.bottom() + 7
    linha = QRectF(caixa.left() + 12, y, caixa.width() - 24, _altura(termo_f))
    cor_termo = _legivel(c, t.primary, fundo)
    escrito = _escrever(pintor, c, termo_f, cor_termo, linha, termo[:visiveis])
    # O cursor em bloco pisca — e fica aceso, parado, sem movimento.
    aceso = not c.movimento or c.entrada < 1.0 or int(c.vida * 8) % 2 == 0
    if c.letras and aceso:
        metricas = QFontMetricsF(termo_f)
        bloco = QRectF(escrito.right() + 2, linha.center().y() - metricas.ascent() / 2,
                       metricas.averageCharWidth() * 0.8, metricas.ascent())
        pintor.fillRect(bloco, cor_termo)
    if traducao:
        _escrever(pintor, c, traducao_f, _legivel(c, t.text_muted, fundo),
                  QRectF(linha.left(), linha.bottom(), linha.width(), _altura(traducao_f)),
                  traducao)
    return caixa


def _graca(pintor: QPainter, painel: QRectF, r: Recado, c: Contexto) -> QRectF:
    """Elden Ring: a faixa escura que atravessa a tela, com a palavra em
    maiúsculas de ouro, espaçadas, entre dois fios que se apagam nas pontas.
    Surge devagar e se aproxima quase nada enquanto está na tela."""
    t = c.tema
    veu = _escuro(t, 0.6)
    manchete_f = c.fonte(9, espaco=3.0, titulo=True)
    termo_f = c.fonte(26, espaco=3.0, titulo=True)
    traducao_f = c.fonte(11, italico=True)
    limite = painel.width() * 0.6
    termo = _encurtar(termo_f, r.termo.upper(), limite)
    traducao = _encurtar(traducao_f, r.traducao, limite)
    manchete = _com_contagem(MANCHETES["graca"], r.novas)
    altura = 30 + _altura(manchete_f) + _altura(termo_f) + (_altura(traducao_f) if traducao else 0)
    meio = max(painel.top() + MARGEM + altura / 2, painel.top() + painel.height() * 0.30)
    faixa = QRectF(painel.left() + FAIXA_MOLDURA, meio - altura / 2,
                   painel.width() - 2 * FAIXA_MOLDURA, altura)
    _faixa_que_some(pintor, faixa, veu, VEU, 0.2)
    centro = faixa.center().x()
    for y in (faixa.top() + 0.5, faixa.bottom() - 0.5):
        _fio_que_some(pintor, centro, faixa.left() + faixa.width() * 0.12, y, t.accent, 0.8, 1.0)
        _fio_que_some(pintor, centro, faixa.right() - faixa.width() * 0.12, y, t.accent, 0.8, 1.0)
    # A aproximação lenta: 4% ao longo da chegada, que aqui dura a vida toda.
    pintor.save()
    if c.movimento:
        escala = 1.0 + 0.04 * (1.0 - c.entrada)
        pintor.translate(centro, meio)
        pintor.scale(escala, escala)
        pintor.translate(-centro, -meio)
    y = faixa.top() + 14
    for fonte, cor, texto in (
        (manchete_f, t.accent, manchete),
        (termo_f, t.primary, termo),
        (traducao_f, t.text_muted, traducao),
    ):
        if texto:
            _escrever(pintor, c, fonte, _legivel(c, cor, veu),
                      QRectF(faixa.left(), y, faixa.width(), _altura(fonte)), texto,
                      Qt.AlignmentFlag.AlignHCenter)
            y += _altura(fonte)
    pintor.restore()
    return faixa


def _descoberta(pintor: QPainter, painel: QRectF, r: Recado, c: Contexto) -> QRectF:
    """Skyrim: o nome descoberto em maiúsculas no alto, entre dois fios que
    crescem para os lados, sobre uma sombra que não tem borda."""
    t = c.tema
    veu = _escuro(t, 0.6)
    manchete_f = c.fonte(9, espaco=3.0)
    termo_f = c.fonte(24, espaco=2.0)
    traducao_f = c.fonte(10, italico=True)
    limite = painel.width() * 0.5
    termo = _encurtar(termo_f, r.termo.upper(), limite)
    traducao = _encurtar(traducao_f, r.traducao, limite)
    manchete = _com_contagem(MANCHETES["descoberta"], r.novas)
    largura = max(_largura(manchete_f, manchete), _largura(termo_f, termo),
                  _largura(traducao_f, traducao))
    altura = _altura(manchete_f) + _altura(termo_f) + (_altura(traducao_f) if traducao else 0)
    # A sombra: uma elipse que só se apaga bem longe das letras. O
    # esmaecimento é longo e em curva: com um degrau só, ela virava uma
    # mancha de borda visível no meio do céu.
    raio = min(max(320.0, (largura / 2 + 50) / 0.5), painel.width() / 2 - FAIXA_MOLDURA)
    achatamento = min(0.5, (altura / 2 + 26) / (raio * 0.5))
    # E nem a ponta mais fraca dela sobe até a moldura.
    centro = QPointF(painel.center().x(),
                     max(painel.top() + FAIXA_MOLDURA + raio * achatamento,
                         painel.top() + painel.height() * 0.24))
    sombra = QRadialGradient(QPointF(0, 0), raio)
    for ponto, alfa in ((0.0, VEU), (0.5, VEU), (0.66, 0.62), (0.8, 0.3), (0.92, 0.09), (1.0, 0.0)):
        sombra.setColorAt(ponto, _cor(veu, alfa))
    pintor.save()
    pintor.translate(centro)
    pintor.scale(1.0, achatamento)
    pintor.setPen(Qt.PenStyle.NoPen)
    pintor.setBrush(QBrush(sombra))
    pintor.drawEllipse(QPointF(0, 0), raio, raio)
    pintor.restore()
    y = centro.y() - altura / 2
    faixa = QRectF(centro.x() - raio, y, raio * 2, altura)
    escrito_termo = QRectF()
    for fonte, cor, texto in (
        (manchete_f, t.text_muted, manchete),
        (termo_f, t.primary, termo),
        (traducao_f, t.text_muted, traducao),
    ):
        if texto:
            escrito = _escrever(pintor, c, fonte, _legivel(c, cor, veu),
                                QRectF(faixa.left(), y, faixa.width(), _altura(fonte)), texto,
                                Qt.AlignmentFlag.AlignHCenter)
            if fonte is termo_f:
                escrito_termo = escrito
            y += _altura(fonte)
    # Os fios crescem para fora do nome durante a chegada.
    comprimento = min(120.0, raio - largura / 2 - 24) * c.entrada
    if comprimento > 4:
        meio_y = escrito_termo.center().y()
        esquerda, direita = escrito_termo.left() - 16, escrito_termo.right() + 16
        _fio_que_some(pintor, esquerda, esquerda - comprimento, meio_y, t.accent, 0.85, 1.0)
        _fio_que_some(pintor, direita, direita + comprimento, meio_y, t.accent, 0.85, 1.0)
    return QRectF(centro.x() - raio, centro.y() - raio * achatamento, raio * 2,
                  raio * achatamento * 2)


def _diario(pintor: QPainter, painel: QRectF, r: Recado, c: Contexto) -> QRectF:
    """The Witcher 3: "Glossário atualizado" no canto, depois do medalhão, sobre
    uma sombra que se apaga para a direita — e desliza da borda ao chegar."""
    t = c.tema
    veu = _escuro(t, 0.55)
    manchete_f = c.fonte(12, negrito=True)
    termo_f = c.fonte(15)
    traducao_f = c.fonte(10, italico=True)
    limite = painel.width() * 0.45
    manchete = _com_contagem(MANCHETES["diario"], r.novas)
    termo = _encurtar(termo_f, r.termo, limite)
    traducao = _encurtar(traducao_f, r.traducao, limite)
    texto_l = max(_largura(manchete_f, manchete), _largura(termo_f, termo),
                  _largura(traducao_f, traducao))
    altura = 26 + _altura(manchete_f) + _altura(termo_f) + (_altura(traducao_f) if traducao else 0)
    x0 = painel.left() + MARGEM - 18.0 * (1.0 - c.entrada)
    y0 = painel.top() + MARGEM
    texto_x = x0 + 54
    cheia = texto_x + texto_l + 12 - x0
    caixa = QRectF(x0, y0, min(cheia + 140, painel.right() - MARGEM - x0), altura)
    gradiente = QLinearGradient(caixa.topLeft(), caixa.topRight())
    gradiente.setColorAt(0.0, _cor(veu, VEU))
    gradiente.setColorAt(min(0.95, cheia / caixa.width()), _cor(veu, VEU))
    gradiente.setColorAt(1.0, _cor(veu, 0.0))
    pintor.fillRect(caixa, QBrush(gradiente))
    # O medalhão: a argola dupla com os dentes em cima e embaixo.
    centro = QPointF(x0 + 26, caixa.center().y())
    pintor.setBrush(Qt.BrushStyle.NoBrush)
    pintor.setPen(QPen(QColor(t.accent), 1.8))
    pintor.drawEllipse(centro, 14.0, 14.0)
    pintor.setPen(QPen(_cor(t.accent, 0.6), 0.9))
    pintor.drawEllipse(centro, 9.5, 9.5)
    pintor.setBrush(QColor(t.accent))
    pintor.drawEllipse(centro, 2.4, 2.4)
    pintor.setPen(QPen(QColor(t.accent), 1.6))
    for dy in (-1.0, 1.0):
        pintor.drawLine(QPointF(centro.x(), centro.y() + dy * 14), QPointF(centro.x(), centro.y() + dy * 19))
    y = y0 + 12
    for fonte, cor, texto in (
        (manchete_f, t.accent_text, manchete),
        (termo_f, t.primary, termo),
        (traducao_f, t.text_muted, traducao),
    ):
        if texto:
            _escrever(pintor, c, fonte, _legivel(c, cor, veu),
                      QRectF(texto_x, y, texto_l, _altura(fonte)), texto)
            y += _altura(fonte)
            if fonte is manchete_f:
                _fio_que_some(pintor, texto_x, texto_x + texto_l + 60, y + 0.5, t.border_forte, 1.0, 1.0)
                y += 2
    return caixa


def _cartaz(pintor: QPainter, painel: QRectF, r: Recado, c: Contexto) -> QRectF:
    """Red Dead: o cartão escuro do canto, com "DIÁRIO ATUALIZADO" escrito numa
    pincelada vermelha que corre da esquerda para a direita ao chegar, e a
    régua dupla dos cartazes embaixo dela."""
    t = c.tema
    fundo = _escuro(t, 0.45)
    manchete_f = c.fonte(11, espaco=1.5, titulo=True)
    termo_f = c.fonte(16, negrito=True)
    traducao_f = c.fonte(10, italico=True)
    limite = painel.width() * 0.45
    manchete = _com_contagem(MANCHETES["cartaz"], r.novas)
    termo = _encurtar(termo_f, r.termo, limite)
    traducao = _encurtar(traducao_f, r.traducao, limite)
    alto_pincel = _altura(manchete_f) + 14
    largura = max(260.0, _largura(manchete_f, manchete) + 70, _largura(termo_f, termo) + 36,
                  _largura(traducao_f, traducao) + 36)
    altura = 12 + alto_pincel + 12 + _altura(termo_f) + (_altura(traducao_f) if traducao else 0) + 12
    caixa = QRectF(painel.left() + MARGEM, painel.top() + MARGEM, largura, altura)
    pintor.fillRect(caixa, _cor(fundo, VEU))
    pintor.setPen(QPen(_cor(t.primary, 0.35), 1.0))
    pintor.drawRect(caixa.adjusted(3.5, 3.5, -3.5, -3.5))
    pincel = QRectF(caixa.left() + 8, caixa.top() + 12, _largura(manchete_f, manchete) + 44, alto_pincel)
    tinta = QColor(design.misturar(t.alert, "#000000", 0.22))
    pintor.save()
    pintor.setClipRect(QRectF(pincel.left(), pincel.top() - 4, pincel.width() * c.entrada, pincel.height() + 8))
    pintor.fillPath(contorno_de_pincel(pincel), tinta)
    pintor.restore()
    _escrever(pintor, c, manchete_f, QColor(design.garantir_contraste(t.primary, tinta.name(), CONTRASTE)),
              pincel.adjusted(20, 0, -8, 0), manchete)
    y = pincel.bottom() + 6
    for alfa, largura_fio, dy in ((0.55, 2.0, 0.0), (0.35, 1.0, 3.5)):
        pintor.setPen(QPen(_cor(t.primary, alfa), largura_fio))
        pintor.drawLine(QPointF(caixa.left() + 16, y + dy), QPointF(caixa.right() - 16, y + dy))
    y += 8
    for fonte, cor, texto in ((termo_f, t.primary, termo), (traducao_f, t.text_muted, traducao)):
        if texto:
            _escrever(pintor, c, fonte, _legivel(c, cor, fundo),
                      QRectF(caixa.left() + 18, y, caixa.width() - 36, _altura(fonte)), texto)
            y += _altura(fonte)
    return caixa


def _missao(pintor: QPainter, painel: QRectF, r: Recado, c: Contexto) -> QRectF:
    """GTA: o letreiro de missão cumprida — o título grande em itálico de neon
    que chega grande demais e assenta, sobre a faixa escura de lado a lado."""
    t = c.tema
    veu = _escuro(t, 0.5)
    manchete_f = c.fonte(28, negrito=True, italico=True)
    termo_f = c.fonte(14, negrito=True)
    traducao_f = c.fonte(12)
    limite = painel.width() * 0.3
    termo = _encurtar(termo_f, r.termo, limite)
    traducao = _encurtar(traducao_f, r.traducao, limite)
    ganho = f"+{r.novas}"
    altura = 30 + _altura(manchete_f) + _altura(termo_f)
    meio = max(painel.top() + MARGEM + altura / 2, painel.top() + painel.height() * 0.30)
    faixa = QRectF(painel.left() + FAIXA_MOLDURA, meio - altura / 2,
                   painel.width() - 2 * FAIXA_MOLDURA, altura)
    _faixa_que_some(pintor, faixa, veu, VEU, 0.14)
    centro = faixa.center().x()
    cor_manchete = _legivel(c, t.accent, veu)
    y = faixa.top() + 12
    caixa_manchete = QRectF(faixa.left(), y, faixa.width(), _altura(manchete_f))
    pintor.save()
    if c.movimento:
        # Chega 45% maior e assenta. Mesmo no primeiro quadro, ampliado, o
        # título cabe na faixa: o respiro de cima foi medido para isso.
        escala = 1.0 + 0.45 * (1.0 - c.entrada)
        pintor.translate(centro, caixa_manchete.center().y())
        pintor.scale(escala, escala)
        pintor.translate(-centro, -caixa_manchete.center().y())
    if c.letras:
        # O halo do neon: o título repetido, fraco, meio pixel para cada lado.
        pintor.setFont(manchete_f)
        pintor.setPen(_cor(t.accent, 0.28))
        for dx, dy in ((-1.5, 0.0), (1.5, 0.0), (0.0, -1.5), (0.0, 1.5)):
            pintor.drawText(caixa_manchete.translated(dx, dy), int(Qt.AlignmentFlag.AlignCenter),
                            MANCHETES["missao"])
    _escrever(pintor, c, manchete_f, cor_manchete, caixa_manchete, MANCHETES["missao"],
              Qt.AlignmentFlag.AlignHCenter)
    pintor.restore()
    y += _altura(manchete_f) + 4
    pedacos = [(termo_f, t.primary, termo), (traducao_f, t.text_muted, traducao),
               (termo_f, t.info, ganho)]
    pedacos = [p for p in pedacos if p[2]]
    respiro = 18.0
    total = sum(_largura(f, texto) for f, _, texto in pedacos) + respiro * (len(pedacos) - 1)
    x = centro - total / 2
    for fonte, cor, texto in pedacos:
        w = _largura(fonte, texto)
        _escrever(pintor, c, fonte, _legivel(c, cor, veu), QRectF(x, y, w, _altura(termo_f)), texto)
        x += w + respiro
    return faixa


def _fragmento(pintor: QPainter, painel: QRectF, r: Recado, c: Contexto) -> QRectF:
    """Cyberpunk 2077: o dado recebido no canto direito, numa caixa de canto
    chanfrado com a barra amarela na borda — e um tranco de interferência,
    com o vermelho e o ciano descolados, no instante em que chega."""
    t = c.tema
    fundo = _escuro(t, 0.3)
    manchete_f = c.fonte(9, espaco=1.5)
    termo_f = c.fonte(17, negrito=True)
    traducao_f = c.fonte(10)
    limite = painel.width() * 0.4
    manchete = _com_contagem(MANCHETES["fragmento"], r.novas)
    termo = _encurtar(termo_f, r.termo.upper(), limite)
    traducao = _encurtar(traducao_f, r.traducao, limite)
    largura = max(260.0, _largura(manchete_f, manchete), _largura(termo_f, termo),
                  _largura(traducao_f, traducao)) + 44
    altura = 24 + _altura(manchete_f) + _altura(termo_f) + (_altura(traducao_f) if traducao else 0)
    tranco = 0.0
    if c.movimento and c.entrada < 1.0:
        sorteio = random.Random(int(c.entrada * 14))
        tranco = sorteio.uniform(-1.0, 1.0) * 7.0 * (1.0 - c.entrada)
    caixa = QRectF(painel.right() - MARGEM - largura + tranco, painel.top() + MARGEM, largura, altura)
    corte = 14.0
    forma = QPainterPath()
    forma.moveTo(caixa.left(), caixa.top())
    forma.lineTo(caixa.right(), caixa.top())
    forma.lineTo(caixa.right(), caixa.bottom() - corte)
    forma.lineTo(caixa.right() - corte, caixa.bottom())
    forma.lineTo(caixa.left(), caixa.bottom())
    forma.closeSubpath()
    pintor.fillPath(forma, _cor(fundo, VEU))
    pintor.setPen(QPen(_cor(t.accent, 0.85), 1.0))
    pintor.drawPath(forma)
    pintor.fillRect(QRectF(caixa.left(), caixa.top(), 3.0, caixa.height()), QColor(t.primary))
    for i in range(3):
        pintor.fillRect(QRectF(caixa.right() - 12 - i * 7, caixa.top() + 6, 4, 4), _cor(t.accent, 0.8))
    x, y = caixa.left() + 18, caixa.top() + 12
    for fonte, cor, texto in (
        (manchete_f, t.accent, manchete),
        (termo_f, t.primary, termo),
        (traducao_f, t.text_muted, traducao),
    ):
        if not texto:
            continue
        linha = QRectF(x, y, caixa.width() - 36, _altura(fonte))
        if c.letras and fonte is termo_f and c.movimento and c.entrada < 1.0:
            # A aberração: o termo em vermelho e em ciano, descolados.
            pintor.setFont(fonte)
            desvio = 3.0 * (1.0 - c.entrada)
            for tinta, dx in ((t.alert, -desvio), (t.accent, desvio)):
                pintor.setPen(_cor(tinta, 0.7 * (1.0 - c.entrada)))
                pintor.drawText(linha.translated(dx, 0),
                                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), texto)
        _escrever(pintor, c, fonte, _legivel(c, cor, fundo), linha, texto)
        y += _altura(fonte)
    return caixa.adjusted(-8, 0, 8, 0)


def _pergaminho(pintor: QPainter, painel: QRectF, r: Recado, c: Contexto) -> QRectF:
    """RPG: a fita de conquista no alto, com as pontas em rabo de andorinha
    dobradas para trás — e que se desenrola do meio para os lados."""
    t = c.tema
    fundo = design.misturar(t.surface_alta, t.accent, 0.14)
    manchete_f = c.fonte(10, italico=True)
    termo_f = c.fonte(17, negrito=True)
    traducao_f = c.fonte(10)
    limite = painel.width() * 0.45
    manchete = _com_contagem(MANCHETES["pergaminho"], r.novas)
    termo = _encurtar(termo_f, r.termo, limite)
    traducao = _encurtar(traducao_f, r.traducao, limite)
    largura = max(220.0, _largura(manchete_f, manchete), _largura(termo_f, termo),
                  _largura(traducao_f, traducao)) + 64
    altura = 18 + _altura(manchete_f) + _altura(termo_f) + (_altura(traducao_f) if traducao else 0)
    corpo = QRectF(painel.center().x() - largura / 2, painel.top() + MARGEM + 4, largura, altura)
    rabo, dobra = 28.0, 10.0
    area = corpo.adjusted(-rabo, 0, rabo, dobra)
    pintor.save()
    aberto = area.width() * (0.3 + 0.7 * c.entrada)
    pintor.setClipRect(QRectF(area.center().x() - aberto / 2, area.top() - 2, aberto, area.height() + 4))
    avesso = QColor(design.misturar(fundo, "#000000", 0.35))
    for lado in (-1.0, 1.0):
        borda = corpo.left() if lado < 0 else corpo.right()
        ponta = borda + lado * rabo
        topo, base = corpo.top() + dobra, corpo.bottom() + dobra
        fita = QPainterPath()
        fita.moveTo(borda - lado * 14, topo)
        fita.lineTo(ponta, topo)
        fita.lineTo(ponta - lado * 10, (topo + base) / 2)
        fita.lineTo(ponta, base)
        fita.lineTo(borda - lado * 14, base)
        fita.closeSubpath()
        pintor.fillPath(fita, avesso)
        pintor.setPen(QPen(_cor(t.accent, 0.6), 1.0))
        pintor.drawPath(fita)
        dobrinha = QPainterPath()
        dobrinha.moveTo(borda, corpo.bottom())
        dobrinha.lineTo(borda - lado * 14, corpo.bottom())
        dobrinha.lineTo(borda - lado * 14, base)
        dobrinha.closeSubpath()
        pintor.fillPath(dobrinha, QColor(design.misturar(fundo, "#000000", 0.6)))
    pintor.fillRect(corpo, QColor(fundo))
    pintor.setPen(QPen(QColor(t.accent), 1.0))
    pintor.drawRect(corpo.adjusted(0.5, 0.5, -0.5, -0.5))
    pintor.setPen(QPen(_cor(t.accent, 0.4), 1.0))
    pintor.drawRect(corpo.adjusted(3.5, 3.5, -3.5, -3.5))
    y = corpo.top() + 9
    for fonte, cor, texto in (
        (manchete_f, t.accent, manchete),
        (termo_f, t.primary, termo),
        (traducao_f, t.text_muted, traducao),
    ):
        if texto:
            _escrever(pintor, c, fonte, _legivel(c, cor, fundo, 1.0),
                      QRectF(corpo.left(), y, corpo.width(), _altura(fonte)), texto,
                      Qt.AlignmentFlag.AlignHCenter)
            y += _altura(fonte)
    pintor.restore()
    return area


def _hexagono(centro: QPointF, raio: float) -> QPainterPath:
    caminho = QPainterPath()
    for i in range(6):
        angulo = math.radians(60 * i)
        ponto = QPointF(centro.x() + raio * math.cos(angulo), centro.y() + raio * math.sin(angulo))
        if i == 0:
            caminho.moveTo(ponto)
        else:
            caminho.lineTo(ponto)
    caminho.closeSubpath()
    return caminho


def _abate(pintor: QPainter, painel: QRectF, r: Recado, c: Contexto) -> QRectF:
    """FPS: a medalha de pontos do abate — o hexágono laranja com o "+1" que
    carimba ao chegar, o título condensado e a régua do visor embaixo, tudo
    entrando de lado, rápido."""
    t = c.tema
    veu = _escuro(t, 0.55)
    manchete_f = c.fonte(11, negrito=True, espaco=1.5)
    termo_f = c.fonte(19, negrito=True, espaco=1.0)
    traducao_f = c.fonte(10, tema=False)
    ganho_f = c.fonte(12, negrito=True)
    limite = painel.width() * 0.4
    termo = _encurtar(termo_f, r.termo.upper(), limite)
    traducao = _encurtar(traducao_f, r.traducao, limite)
    manchete = MANCHETES["abate"]
    texto_l = max(_largura(manchete_f, manchete), _largura(termo_f, termo),
                  _largura(traducao_f, traducao))
    altura = _altura(manchete_f) + _altura(termo_f) + (_altura(traducao_f) if traducao else 0)
    raio = 22.0
    grupo_l = raio * 2 + 16 + texto_l
    deslize = 28.0 * (1.0 - c.entrada)
    meio = max(painel.top() + MARGEM + altura / 2 + 14, painel.top() + painel.height() * 0.28)
    x0 = painel.center().x() - grupo_l / 2 + deslize
    grupo = QRectF(x0, meio - altura / 2, grupo_l, altura)
    faixa = QRectF(max(painel.left() + FAIXA_MOLDURA, grupo.left() - 90), grupo.top() - 14,
                   0.0, altura + 28)
    faixa.setRight(min(painel.right() - FAIXA_MOLDURA, grupo.right() + 90))
    borda = min(0.4, 76.0 / max(1.0, faixa.width()))
    _faixa_que_some(pintor, faixa, veu, VEU, borda)
    # A régua do visor, sob o grupo.
    y_regua = faixa.bottom() - 4
    pintor.setPen(QPen(_cor(t.primary, 0.5), 1.0))
    pintor.drawLine(QPointF(grupo.left(), y_regua), QPointF(grupo.right(), y_regua))
    x = grupo.left()
    while x <= grupo.right():
        pintor.drawLine(QPointF(x, y_regua), QPointF(x, y_regua - 3))
        x += 12
    # A medalha carimba: chega grande e assenta.
    centro = QPointF(grupo.left() + raio, meio)
    carimbo = 1.0 + (0.5 * (1.0 - c.entrada) if c.movimento else 0.0)
    medalha = _hexagono(centro, raio * carimbo)
    pintor.fillPath(medalha, QColor(t.accent))
    pintor.setPen(QPen(_cor(t.primary, 0.8), 1.0))
    pintor.drawPath(_hexagono(centro, raio * carimbo + 3))
    _escrever(pintor, c, ganho_f, QColor(design.garantir_contraste(t.on_accent, t.accent, CONTRASTE)),
              QRectF(centro.x() - raio, centro.y() - raio, raio * 2, raio * 2), f"+{r.novas}",
              Qt.AlignmentFlag.AlignHCenter)
    x_texto = grupo.left() + raio * 2 + 16
    y = grupo.top()
    for fonte, cor, texto in (
        (manchete_f, t.primary, manchete),
        (termo_f, t.accent, termo),
        (traducao_f, t.text_muted, traducao),
    ):
        if texto:
            _escrever(pintor, c, fonte, _legivel(c, cor, veu),
                      QRectF(x_texto, y, texto_l, _altura(fonte)), texto)
            y += _altura(fonte)
    return faixa.united(QRectF(centro.x() - raio * 1.5 - 4, centro.y() - raio * 1.5 - 4,
                               raio * 3 + 8, raio * 3 + 8))


AVISOS: dict[str, Callable[[QPainter, QRectF, Recado, Contexto], QRectF]] = {
    "": _cartao,
    "terminal": _terminal,
    "graca": _graca,
    "descoberta": _descoberta,
    "diario": _diario,
    "cartaz": _cartaz,
    "missao": _missao,
    "fragmento": _fragmento,
    "pergaminho": _pergaminho,
    "abate": _abate,
}

# Quanto dura a CHEGADA de cada um, em ms. O Elden Ring se aproxima durante a
# vida inteira do anúncio; a máquina de escrever do terminal precisa de tempo
# para as letras; o resto chega depressa, como chegam as notificações deles.
CHEGADAS: dict[str, int] = {"graca": 3600, "terminal": 650, "cartaz": 480, "pergaminho": 420}
CHEGADA_PADRAO = 320
# E quanto leva a opacidade para acender: só o Elden Ring surge devagar.
ACENDER: dict[str, int] = {"graca": 900}
ACENDER_PADRAO = 150


def pintar_aviso(
    pintor: QPainter, painel: QRectF, estilo: str, recado: Recado, contexto: Contexto
) -> QRectF:
    """Pinta o anúncio de ``estilo`` e devolve a área que ele ocupa."""
    desenhar = AVISOS.get(estilo, _cartao)
    pintor.save()
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    pintor.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    area = desenhar(pintor, painel, recado, contexto)
    pintor.restore()
    return area


class AvisoDePalavra(QWidget):
    """O anúncio da palavra nova, por cima do painel da conversa.

    Uma camada só, que vive a vida da janela: fica escondida, acende quando
    uma palavra chega e se esconde de novo — uma palavra nova no meio do
    anúncio anterior o recomeça com a nova, em vez de empilhar dois. É
    transparente ao mouse, como a moldura: nada da conversa passa a morar
    nele. E repinta só a área do anúncio, e não o painel inteiro: embaixo
    dela está a conversa, que seria redesenhada a cada quadro por nada.
    """

    DURACAO = 3600
    APAGAR = 700

    def __init__(self, provedor: Any, painel: QWidget) -> None:
        super().__init__(painel.parentWidget())
        self._provedor = provedor
        self._painel = painel
        self.recado: Recado | None = None
        self.estilo = ""
        self._area = QRectF()
        self._curva = QEasingCurve(QEasingCurve.Type.OutCubic)
        self.setObjectName("avisoDePalavra")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._animacao = QVariantAnimation(self)
        self._animacao.setStartValue(0.0)
        self._animacao.setEndValue(1.0)
        self._animacao.setDuration(self.DURACAO)
        self._animacao.valueChanged.connect(self._avancar)
        self._animacao.finished.connect(self.hide)
        painel.installEventFilter(self)
        self.hide()

    def anunciar(self, recado: Recado) -> None:
        self.recado = recado
        self.estilo = str(getattr(self._provedor.atmosfera, "aviso", ""))
        self._area = QRectF()
        self.setGeometry(self._painel.geometry())
        self.show()
        self.raise_()
        self._animacao.stop()
        self._animacao.start()
        self.update()

    def recolher(self) -> None:
        """Some agora — numa troca de jogo, o anúncio do jogo anterior sobraria."""
        self._animacao.stop()
        self.hide()

    def eventFilter(self, alvo: Any, evento: Any) -> bool:
        if alvo is self._painel and evento.type() in (QEvent.Type.Resize, QEvent.Type.Move):
            self.setGeometry(self._painel.geometry())
        return False

    def _avancar(self, _valor: Any) -> None:
        if self._area.isNull():
            self.update()
        else:
            # A folga cobre o que anda entre dois quadros: o tranco do
            # Cyberpunk, o deslize do visor e do medalhão.
            self.update(self._area.toAlignedRect().adjusted(-12, -12, 12, 12))

    def _momento(self) -> tuple[float, float, float]:
        """(opacidade, entrada, vida) agora."""
        decorrido = float(self._animacao.currentTime())
        vida = min(1.0, decorrido / self.DURACAO)
        acender = ACENDER.get(self.estilo, ACENDER_PADRAO)
        opacidade = min(1.0, decorrido / acender, (self.DURACAO - decorrido) / self.APAGAR)
        chegada = min(1.0, decorrido / CHEGADAS.get(self.estilo, CHEGADA_PADRAO))
        return max(0.0, opacidade), self._curva.valueForProgress(chegada), vida

    def paintEvent(self, _evento: Any) -> None:
        if self.recado is None:
            return
        opacidade, entrada, vida = self._momento()
        parado = movimento_reduzido()
        contexto = contexto_de(
            self._provedor, entrada=1.0 if parado else entrada, vida=vida, movimento=not parado
        )
        pintor = QPainter(self)
        pintor.setOpacity(opacidade)
        area = pintar_aviso(pintor, QRectF(self.rect()), self.estilo, self.recado, contexto)
        pintor.end()
        self._area = area if self._area.isNull() else self._area.united(area)
