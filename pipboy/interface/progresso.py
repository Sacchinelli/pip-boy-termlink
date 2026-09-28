"""Painel de progresso: o caderno contado, desenhado no tema.

O banco sempre soube quantas palavras nasceram por semana, de que jogo elas
vieram e quantas já estão dominadas — mas ninguém via. Este painel desenha
essas três respostas com o QPainter, nas cores e na geometria do tema, como
todo o resto do programa: nenhuma biblioteca de gráfico, nenhum widget do
sistema, só barras que qualquer um lê de relance.

Os gráficos recebem dados prontos (rótulo e número) e não conhecem o banco:
`vocabulary.py` conta, aqui se desenha — a mesma divisão de trabalho do
resto do projeto.

Duas camadas de leitura, e a regra que separa uma da outra:

* **De relance, sem tocar em nada:** os números de cada barra, a legenda da
  régua, a semana corrente marcada como "esta semana". Tudo que alguém
  precisa para entender o painel está à vista o tempo todo.
* **Ao passar o cursor, o que não cabe no relance:** o intervalo de datas de
  uma semana e a diferença para a anterior, a fatia do caderno que um jogo
  representa, o que "aprendendo" quer dizer. É detalhe, nunca o dado
  principal — e por isso tudo bem que o teclado não chegue lá.

As barras crescem ao abrir, em cascata, e cada gráfico começa um pouco depois
do de cima: o olho percorre a tela na ordem em que ela se lê.

E o painel é a tela do jogo em que já se mede o quanto se avançou: o STAT do
Pip-Boy, o nível de runas, as habilidades do Skyrim, a carreira do visor. O
nome e o objeto dela vão no alto, e a moldura do jogo se monta em volta dos
gráficos quando a janela abre. Logo abaixo do título, o nível do caderno —
o LVL do terminal, a patente do visor, a reputação da Night City — numa
barra de experiência desenhada no medidor do jogo.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import design
from ..nivel import REGRA_DO_XP, Nivel, nivel_de, xp_do_caderno
from ..vocabulary import DIAS_PARA_DOMINIO, VocabularyStore
from .atmosfera import ATENUACAO_NO_FUNDO_NU, Cenario, so_o_cursor
from .componentes import Botao, acender_borda, caminho_forma
from .cursor import CursorVivo
from .icones import IconeDoJogo
from .movimento import Crescimento, Transicao
from .ornamentos import FAIXA_MOLDURA, MolduraDoPainel

LARGURA = 640
ALTURA_GRAFICO = 150
# O quanto os dois gráficos de barras aceitam encolher numa tela baixa: ainda
# legíveis, com a barra mais alta a meio caminho do tamanho de sempre.
ALTURA_GRAFICO_MINIMA = 88
ALTURA_PREVISAO_MINIMA = 78
# A folga que a janela deixa entre ela e as bordas da área útil da tela.
MARGEM_DA_TELA = 24
ALTURA_BARRAS_JOGO = 26
ALTURA_REGUA = 22

EXPLICACOES_DOMINIO = (
    "Novas: ainda sem intervalo — nunca acertadas, ou erradas na última revisão.",
    f"Aprendendo: já acertadas, voltam em menos de {DIAS_PARA_DOMINIO} dias.",
    f"Dominadas: só voltam depois de {DIAS_PARA_DOMINIO} dias ou mais.",
)


def _plural(quantidade: int, singular: str, plural: str) -> str:
    return f"{quantidade} {singular if quantidade == 1 else plural}"


def segundas_do_grafico(quantidade: int, hoje: date | None = None) -> list[date]:
    """As segundas-feiras das barras, da mais antiga à semana corrente.

    A mesma conta de ``VocabularyStore.novas_por_semana``, que dá às barras só
    o rótulo "dd/mm": o ano não vem junto, e reconstruir a data a partir do
    rótulo erraria na virada do ano.
    """
    alvo = hoje if hoje is not None else datetime.now(timezone.utc).astimezone().date()
    segunda_atual = alvo - timedelta(days=alvo.weekday())
    return [segunda_atual - timedelta(weeks=atras) for atras in range(quantidade - 1, -1, -1)]


def descrever_semana(
    dados: list[tuple[str, int]], indice: int, segundas: list[date]
) -> tuple[str, str]:
    """Título e corpo da ficha de uma semana: o intervalo e a comparação."""
    inicio = segundas[indice]
    fim = inicio + timedelta(days=6)
    titulo = f"{inicio:%d/%m} – {fim:%d/%m}"
    if indice == len(dados) - 1:
        titulo += " · esta semana"
    valor = dados[indice][1]
    corpo = _plural(valor, "palavra nova", "palavras novas")
    if indice > 0:
        diferenca = valor - dados[indice - 1][1]
        if diferenca > 0:
            corpo += f", {diferenca} a mais que a anterior"
        elif diferenca < 0:
            corpo += f", {-diferenca} a menos que a anterior"
        else:
            corpo += ", igual à anterior"
    return titulo, corpo


class _Grafico(QWidget):
    """O que os três gráficos têm em comum: crescer ao abrir e apontar um item.

    O item sob o cursor fica em ``apontado``; ``_indice`` guarda o último
    apontado, para que o destaque apague devagar no lugar em que estava em
    vez de sumir num quadro quando o cursor sai.
    """

    def __init__(self, janela: Any, itens: int, *, atraso: int) -> None:
        super().__init__()
        self._janela = janela
        reduzir = lambda: bool(janela.intensidade_atmosfera <= 0.0)  # noqa: E731
        self.crescimento = Crescimento(self, itens, reduzir=reduzir, atraso=atraso)
        self._destaque = Transicao(
            self, design.DURACAO_RAPIDA, lambda _v: self.update(), reduzir=reduzir
        )
        self.apontado: int | None = None
        self._indice: int | None = None
        self._cresceu = False
        # Sem filhos: o rastreamento do próprio widget basta para o hover.
        self.setMouseTracking(True)

    def showEvent(self, evento: Any) -> None:
        super().showEvent(evento)
        if not self._cresceu:
            self._cresceu = True
            self.crescimento.iniciar()

    def mouseMoveEvent(self, evento: QMouseEvent) -> None:
        self._apontar(self._item_em(evento.position()))
        super().mouseMoveEvent(evento)

    def leaveEvent(self, evento: Any) -> None:
        self._apontar(None)
        super().leaveEvent(evento)

    def _apontar(self, indice: int | None) -> None:
        if indice == self.apontado:
            return
        self.apontado = indice
        if indice is not None:
            self._indice = indice
        self._destaque.ir(1.0 if indice is not None else 0.0)
        self.update()

    def _item_em(self, ponto: QPointF) -> int | None:
        raise NotImplementedError

    def _apagar(self, cor: str, indice: int) -> str:
        """Os itens que NÃO estão sob o cursor recuam para o fundo."""
        if self._indice is None or indice == self._indice:
            return cor
        return design.misturar(cor, self._janela.tema.surface, 0.5 * self._destaque.valor)

    def _faixa(self, pintor: QPainter, retangulo: QRectF, indice: int) -> None:
        """Uma faixa discreta atrás do item apontado."""
        if indice != self._indice or self._destaque.valor <= 0.01:
            return
        tema = self._janela.tema
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(
            QColor(design.misturar(tema.surface, tema.primary, 0.07 * self._destaque.valor))
        )
        pintor.drawRoundedRect(retangulo, 4, 4)

    def _ficha(
        self, pintor: QPainter, ancora: QPointF, titulo: str, corpo: str
    ) -> None:
        """Um cartãozinho de detalhe centrado na âncora, sem sair do widget."""
        if self._destaque.valor <= 0.01:
            return
        tema = self._janela.tema
        fonte_titulo: QFont = self._janela.fonte("legenda")
        fonte_titulo.setBold(True)
        fonte_corpo: QFont = self._janela.fonte("micro")
        m_titulo, m_corpo = QFontMetrics(fonte_titulo), QFontMetrics(fonte_corpo)
        largura = max(m_titulo.horizontalAdvance(titulo), m_corpo.horizontalAdvance(corpo)) + 20
        altura = m_titulo.height() + m_corpo.height() + 14
        x = min(max(0.0, ancora.x() - largura / 2), self.width() - largura)
        y = max(0.0, ancora.y() - altura)
        caixa = QRectF(x, y, largura, altura)

        fundo = tema.surface_alta
        pintor.save()
        pintor.setOpacity(self._destaque.valor)
        pintor.setPen(QPen(QColor(tema.border_forte), 1.0))
        pintor.setBrush(QColor(fundo))
        pintor.drawRoundedRect(caixa, 5, 5)
        pintor.setFont(fonte_titulo)
        pintor.setPen(QColor(design.garantir_contraste(tema.primary, fundo)))
        pintor.drawText(
            QRectF(x + 10, y + 6, largura - 20, m_titulo.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            titulo,
        )
        pintor.setFont(fonte_corpo)
        pintor.setPen(QColor(design.garantir_contraste(tema.text_muted, fundo)))
        pintor.drawText(
            QRectF(x + 10, y + 7 + m_titulo.height(), largura - 20, m_corpo.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            corpo,
        )
        pintor.restore()


class _GraficoSemanas(_Grafico):
    """Barras verticais: palavras novas por semana."""

    def __init__(self, janela: Any, dados: list[tuple[str, int]]) -> None:
        super().__init__(janela, len(dados), atraso=0)
        self._dados = dados
        self._segundas = segundas_do_grafico(len(dados))
        # Elástico: o tamanho de sempre é o preferido, e numa tela baixa ele
        # cede antes de o painel precisar rolar (ver JanelaProgresso).
        self.setMinimumHeight(ALTURA_GRAFICO_MINIMA)

    def sizeHint(self) -> QSize:
        return QSize(super().sizeHint().width(), ALTURA_GRAFICO)

    def _area(self) -> tuple[QRectF, float]:
        metricas = QFontMetrics(self._janela.fonte("micro"))
        area = QRectF(0, 4, self.width(), self.height() - metricas.height() - 14)
        return area, area.width() / max(1, len(self._dados))

    def _item_em(self, ponto: QPointF) -> int | None:
        area, passo = self._area()
        indice = int((ponto.x() - area.left()) // passo)
        return indice if 0 <= indice < len(self._dados) else None

    def paintEvent(self, _evento: Any) -> None:
        tema = self._janela.tema
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        fonte = self._janela.fonte("micro")
        pintor.setFont(fonte)
        metricas = QFontMetrics(fonte)

        area, passo = self._area()
        maximo = max((v for _, v in self._dados), default=0)
        largura_barra = min(44.0, passo * 0.56)
        cor_apagada = design.elevar(tema.surface, 0.18, tema.primary)
        cor_texto = design.garantir_contraste(tema.text_muted, tema.surface)
        cor_valor = design.garantir_contraste(tema.primary, tema.surface)
        ultima = len(self._dados) - 1
        topo_apontado = area.bottom()

        for i, (rotulo, valor) in enumerate(self._dados):
            centro_x = area.left() + passo * (i + 0.5)
            x = centro_x - largura_barra / 2
            crescido = self.crescimento.progresso(i)
            self._faixa(
                pintor,
                QRectF(centro_x - passo / 2 + 2, area.top(), passo - 4, self.height() - area.top()),
                i,
            )

            if maximo > 0 and valor > 0:
                altura = max(3.0, area.height() * (valor / maximo)) * crescido
                barra = QRectF(x, area.bottom() - altura, largura_barra, altura)
                pintor.setPen(Qt.PenStyle.NoPen)
                if i == ultima:
                    # A semana corrente ainda está acontecendo: barra por
                    # dentro mais clara e contorno na cor cheia, como algo que
                    # ainda vai encher. Pintada igual às outras, uma quarta-feira
                    # parecia uma semana fraca.
                    pintor.setBrush(QColor(self._apagar(design.misturar(tema.surface, tema.accent, 0.45), i)))
                    pintor.setPen(QPen(QColor(self._apagar(tema.accent, i)), 1.2))
                else:
                    pintor.setBrush(QColor(self._apagar(tema.accent, i)))
                pintor.drawRoundedRect(barra, 2, 2)
                if i == self._indice:
                    topo_apontado = barra.top()
                # O número mora acima da barra; quando a barra toca o teto e
                # não sobra céu, ele entra NELA — cortado, nunca.
                pintor.save()
                pintor.setOpacity(crescido)
                acima = barra.top() - metricas.height() - 2
                if acima >= area.top():
                    pintor.setPen(QColor(self._apagar(cor_valor, i)))
                    alvo = QRectF(
                        x - passo / 2, acima, largura_barra + passo, metricas.height()
                    )
                else:
                    pintor.setPen(QColor(design.legivel_sobre(tema.accent)))
                    alvo = QRectF(x, barra.top() + 2, largura_barra, metricas.height())
                pintor.drawText(alvo, Qt.AlignmentFlag.AlignCenter, str(valor))
                pintor.restore()
            else:
                # Semana zerada: um traço no chão, para o eixo não ter buraco.
                pintor.setPen(Qt.PenStyle.NoPen)
                pintor.setBrush(QColor(cor_apagada))
                pintor.drawRect(QRectF(x, area.bottom() - 2, largura_barra, 2))

            pintor.setPen(QColor(self._apagar(cor_texto, i)))
            pintor.drawText(
                QRectF(centro_x - passo / 2, area.bottom() + 4, passo, metricas.height()),
                Qt.AlignmentFlag.AlignCenter,
                "esta semana" if i == ultima else rotulo,
            )

        if self._indice is not None and self._indice < len(self._dados):
            titulo, corpo = descrever_semana(self._dados, self._indice, self._segundas)
            centro = area.left() + passo * (self._indice + 0.5)
            self._ficha(pintor, QPointF(centro, max(area.top() + 40, topo_apontado - 20)), titulo, corpo)
        pintor.end()


# Os nomes curtos dos dias, de segunda a domingo (``date.weekday``).
DIAS_DA_SEMANA = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")
DIAS_DA_PREVISAO = 7
SEMANAS_DO_CALENDARIO = 15
ALTURA_PREVISAO = 110


def rotulo_do_dia(dia: date, hoje: date) -> str:
    """O nome do dia na previsão: hoje, amanhã, e depois o dia da semana."""
    diferenca = (dia - hoje).days
    if diferenca == 0:
        return "hoje"
    if diferenca == 1:
        return "amanhã"
    return DIAS_DA_SEMANA[dia.weekday()]


def descrever_previsao(dados: list[tuple[date, int]], indice: int) -> tuple[str, str]:
    """Título e corpo da ficha de um dia da previsão."""
    dia, valor = dados[indice]
    titulo = f"{DIAS_DA_SEMANA[dia.weekday()]}, {dia:%d/%m}"
    if indice == 0:
        # Hoje junta a dívida inteira: o que já venceu e o que vence até a
        # meia-noite (ver VocabularyStore.previsao).
        titulo += " · hoje"
        corpo = (
            _plural(valor, "palavra vence hoje", "palavras vencem hoje")
            if valor else "nada vence hoje"
        )
    else:
        corpo = _plural(valor, "palavra vence", "palavras vencem") if valor else "nenhuma palavra vence"
    return titulo, corpo


def grade_do_calendario(hoje: date, semanas: int) -> list[list[date | None]]:
    """As colunas do calendário: uma por semana, de segunda a domingo.

    A última coluna é a semana corrente; os dias dela que ainda não chegaram
    ficam vazios (``None``) — um quadrado apagado no futuro leria como um dia
    perdido.
    """
    segunda = hoje - timedelta(days=hoje.weekday())
    colunas: list[list[date | None]] = []
    for atras in range(semanas - 1, -1, -1):
        inicio = segunda - timedelta(weeks=atras)
        dias: list[date | None] = []
        for passo in range(7):
            dia = inicio + timedelta(days=passo)
            dias.append(dia if dia <= hoje else None)
        colunas.append(dias)
    return colunas


def descrever_dia(dia: date, hoje: date, estudou: bool) -> tuple[str, str]:
    """Título e corpo da ficha de um dia do calendário."""
    titulo = f"{DIAS_DA_SEMANA[dia.weekday()]}, {dia:%d/%m}"
    if dia == hoje:
        titulo += " · hoje"
        return titulo, "dia de estudo" if estudou else "ainda sem estudo hoje"
    return titulo, "dia de estudo" if estudou else "sem estudo"


# A forma de um dia de estudo no calendário, no traço do jogo: a estrela das
# constelações do norte, o losango da graça e do grimório, o bloco do
# terminal e do visor, o recorte chanfrado da Night City, o círculo do
# medalhão e do furo de bala do oeste. O resto fica com o quadrado macio.
FORMAS_DO_DIA: dict[str, str] = {
    "terminal": "bloco", "tatico": "bloco",
    "graca": "losango", "grimorio": "losango",
    "nordico": "estrela",
    "dados": "chanfro",
    "bruxo": "circulo", "oeste": "circulo",
}


def caminho_do_dia(caixa: QRectF, forma: str) -> QPainterPath:
    """O contorno de um dia do calendário na forma pedida."""
    caminho = QPainterPath()
    c = caixa.center()
    r = caixa.width() / 2
    if forma == "losango":
        caminho.moveTo(c.x(), caixa.top())
        caminho.lineTo(caixa.right(), c.y())
        caminho.lineTo(c.x(), caixa.bottom())
        caminho.lineTo(caixa.left(), c.y())
        caminho.closeSubpath()
    elif forma == "estrela":
        for passo in range(8):
            angulo = -math.pi / 2 + math.pi * passo / 4
            raio = r if passo % 2 == 0 else r * 0.42
            ponto = QPointF(c.x() + raio * math.cos(angulo), c.y() + raio * math.sin(angulo))
            if passo == 0:
                caminho.moveTo(ponto)
            else:
                caminho.lineTo(ponto)
        caminho.closeSubpath()
    elif forma == "chanfro":
        corte = caixa.width() * 0.32
        caminho.moveTo(caixa.left() + corte, caixa.top())
        caminho.lineTo(caixa.right(), caixa.top())
        caminho.lineTo(caixa.right(), caixa.bottom() - corte)
        caminho.lineTo(caixa.right() - corte, caixa.bottom())
        caminho.lineTo(caixa.left(), caixa.bottom())
        caminho.lineTo(caixa.left(), caixa.top() + corte)
        caminho.closeSubpath()
    elif forma == "circulo":
        caminho.addEllipse(caixa)
    elif forma == "bloco":
        caminho.addRect(caixa)
    else:
        caminho.addRoundedRect(caixa, caixa.width() * 0.25, caixa.width() * 0.25)
    return caminho


class _GraficoPrevisao(_Grafico):
    """Barras verticais: quantas palavras vencem em cada um dos próximos dias.

    A de hoje é a dívida que uma revisão feita agora paga, e sai na cor de
    acento; as outras, na cor do tema. É a mesma divisão de trabalho dos
    outros gráficos: os números vêm prontos de ``VocabularyStore.previsao``.
    """

    def __init__(self, janela: Any, dados: list[tuple[date, int]]) -> None:
        super().__init__(janela, len(dados), atraso=60)
        self._dados = dados
        self._hoje = dados[0][0] if dados else date.today()
        self.setMinimumHeight(ALTURA_PREVISAO_MINIMA)

    def sizeHint(self) -> QSize:
        return QSize(super().sizeHint().width(), ALTURA_PREVISAO)

    def _area(self) -> tuple[QRectF, float]:
        metricas = QFontMetrics(self._janela.fonte("micro"))
        area = QRectF(0, metricas.height() + 4, self.width(), self.height() - 2 * metricas.height() - 12)
        return area, area.width() / max(1, len(self._dados))

    def _item_em(self, ponto: QPointF) -> int | None:
        area, passo = self._area()
        indice = int((ponto.x() - area.left()) // passo)
        return indice if 0 <= indice < len(self._dados) else None

    def paintEvent(self, _evento: Any) -> None:
        tema = self._janela.tema
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        fonte = self._janela.fonte("micro")
        pintor.setFont(fonte)
        metricas = QFontMetrics(fonte)
        area, passo = self._area()
        maximo = max((v for _, v in self._dados), default=0)
        largura_barra = min(26.0, passo * 0.56)
        cor_texto = design.garantir_contraste(tema.text_muted, tema.surface)
        cor_valor = design.garantir_contraste(tema.primary, tema.surface)
        topo_apontado = area.bottom()
        for i, (dia, valor) in enumerate(self._dados):
            centro_x = area.left() + passo * (i + 0.5)
            x = centro_x - largura_barra / 2
            crescido = self.crescimento.progresso(i)
            self._faixa(pintor, QRectF(centro_x - passo / 2 + 1, 0, passo - 2, self.height()), i)
            cor = tema.accent if i == 0 else tema.primary
            if maximo > 0 and valor > 0:
                altura = max(3.0, area.height() * (valor / maximo)) * crescido
                barra = QRectF(x, area.bottom() - altura, largura_barra, altura)
                pintor.setPen(Qt.PenStyle.NoPen)
                pintor.setBrush(QColor(self._apagar(cor, i)))
                pintor.drawRoundedRect(barra, 2, 2)
                if i == self._indice:
                    topo_apontado = barra.top()
                pintor.save()
                pintor.setOpacity(crescido)
                pintor.setPen(QColor(self._apagar(cor_valor, i)))
                pintor.drawText(
                    QRectF(centro_x - passo / 2, barra.top() - metricas.height() - 2, passo, metricas.height()),
                    Qt.AlignmentFlag.AlignCenter, str(valor),
                )
                pintor.restore()
            else:
                pintor.setPen(Qt.PenStyle.NoPen)
                pintor.setBrush(QColor(design.elevar(tema.surface, 0.18, tema.primary)))
                pintor.drawRect(QRectF(x, area.bottom() - 2, largura_barra, 2))
            pintor.setPen(QColor(self._apagar(cor_texto, i)))
            pintor.drawText(
                QRectF(centro_x - passo / 2, area.bottom() + 4, passo, metricas.height()),
                Qt.AlignmentFlag.AlignCenter, rotulo_do_dia(dia, self._hoje),
            )
        if self._indice is not None and self._indice < len(self._dados):
            titulo, corpo = descrever_previsao(self._dados, self._indice)
            centro = area.left() + passo * (self._indice + 0.5)
            self._ficha(pintor, QPointF(centro, max(area.top() + 40, topo_apontado - 8)), titulo, corpo)
        pintor.end()


class _CalendarioDeEstudo(_Grafico):
    """Os dias de estudo das últimas semanas, uma coluna por semana.

    A sequência diz há quantos dias seguidos; o calendário mostra o resto —
    os buracos, o fim de semana que sempre cai, o mês bom. Cada dia de estudo
    acende na forma do jogo (ver ``FORMAS_DO_DIA``); o de hoje, sem estudo
    ainda, tem só o contorno: está esperando.
    """

    LADO = 11.0
    VAO = 3.0

    def __init__(self, janela: Any, estudados: set[date], hoje: date) -> None:
        colunas = grade_do_calendario(hoje, SEMANAS_DO_CALENDARIO)
        super().__init__(janela, len(colunas), atraso=90)
        self._colunas = colunas
        self._estudados = estudados
        self._hoje = hoje
        self.forma = FORMAS_DO_DIA.get(str(getattr(janela.atmosfera, "icones", "")), "macio")
        metricas = QFontMetrics(janela.fonte("micro"))
        self._margem = float(metricas.horizontalAdvance("sáb") + 6)
        self.setMinimumHeight(round(7 * (self.LADO + self.VAO) + 2))
        self.setMinimumWidth(round(self._margem + len(self._colunas) * (self.LADO + self.VAO)))

    def caixa(self, coluna: int, linha: int) -> QRectF:
        passo = self.LADO + self.VAO
        return QRectF(self._margem + coluna * passo, 1 + linha * passo, self.LADO, self.LADO)

    def _celula_em(self, ponto: QPointF) -> tuple[int, int] | None:
        passo = self.LADO + self.VAO
        coluna = int((ponto.x() - self._margem) // passo)
        linha = int((ponto.y() - 1) // passo)
        if 0 <= coluna < len(self._colunas) and 0 <= linha < 7 and self._colunas[coluna][linha]:
            return coluna, linha
        return None

    def _item_em(self, ponto: QPointF) -> int | None:
        celula = self._celula_em(ponto)
        return None if celula is None else celula[0] * 7 + celula[1]

    def dia_do_item(self, indice: int) -> date | None:
        return self._colunas[indice // 7][indice % 7]

    def paintEvent(self, _evento: Any) -> None:
        tema = self._janela.tema
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        fonte = self._janela.fonte("micro")
        pintor.setFont(fonte)
        cor_texto = design.garantir_contraste(tema.text_muted, tema.surface)
        pintor.setPen(QColor(cor_texto))
        for linha in (0, 2, 4):
            caixa = self.caixa(0, linha)
            pintor.drawText(
                QRectF(0, caixa.top() - 3, self._margem - 6, caixa.height() + 6),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                DIAS_DA_SEMANA[linha],
            )
        apagado = design.elevar(tema.surface, 0.14, tema.primary)
        for coluna, dias in enumerate(self._colunas):
            crescido = self.crescimento.progresso(coluna)
            for linha, dia in enumerate(dias):
                if dia is None:
                    continue
                indice = coluna * 7 + linha
                caminho = caminho_do_dia(self.caixa(coluna, linha), self.forma)
                pintor.save()
                pintor.setOpacity(0.25 + 0.75 * crescido)
                if dia in self._estudados:
                    pintor.fillPath(caminho, QColor(self._apagar(tema.accent, indice)))
                else:
                    pintor.fillPath(caminho, QColor(self._apagar(apagado, indice)))
                if dia == self._hoje:
                    caneta = QPen(QColor(design.garantir_contraste(tema.accent, tema.surface, 3.0)))
                    caneta.setWidthF(1.2)
                    pintor.setPen(caneta)
                    pintor.setBrush(Qt.BrushStyle.NoBrush)
                    pintor.drawPath(caminho_do_dia(self.caixa(coluna, linha).adjusted(-1.5, -1.5, 1.5, 1.5), self.forma))
                pintor.restore()
        if self._indice is not None:
            dia_apontado = self.dia_do_item(self._indice)
            if dia_apontado is not None:
                titulo, corpo = descrever_dia(dia_apontado, self._hoje, dia_apontado in self._estudados)
                caixa = self.caixa(self._indice // 7, self._indice % 7)
                self._ficha(pintor, QPointF(caixa.center().x(), max(caixa.top(), 40.0)), titulo, corpo)
        pintor.end()


class _GraficoJogos(_Grafico):
    """Barras horizontais: de que jogo o vocabulário está vindo."""

    def __init__(self, janela: Any, dados: list[tuple[str, int]], total: int) -> None:
        super().__init__(janela, len(dados), atraso=240)
        self._dados = dados
        self._total = total
        self.setMinimumHeight(ALTURA_BARRAS_JOGO * max(1, len(dados)) + 8)

    def _item_em(self, ponto: QPointF) -> int | None:
        indice = int(ponto.y() // ALTURA_BARRAS_JOGO)
        return indice if 0 <= indice < len(self._dados) else None

    def rotulo_de_valor(self, indice: int) -> str:
        """O número da barra; sob o cursor, também a fatia do caderno."""
        valor = self._dados[indice][1]
        if indice != self.apontado or self._total <= 0:
            return str(valor)
        return f"{valor} · {valor / self._total:.0%} do caderno"

    def paintEvent(self, _evento: Any) -> None:
        tema = self._janela.tema
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        fonte = self._janela.fonte("legenda")
        pintor.setFont(fonte)
        metricas = QFontMetrics(fonte)

        maximo = max((v for _, v in self._dados), default=0)
        larg_rotulo = min(
            180, max((metricas.horizontalAdvance(r) for r, _ in self._dados), default=0) + 10
        )
        larg_valor = metricas.horizontalAdvance("9999") + 8
        area_barras = self.width() - larg_rotulo - larg_valor
        cor_texto = design.garantir_contraste(tema.secondary, tema.surface)
        cor_valor = design.garantir_contraste(tema.primary, tema.surface)

        for i, (rotulo, valor) in enumerate(self._dados):
            y = i * ALTURA_BARRAS_JOGO
            linha = QRectF(0, y, self.width(), ALTURA_BARRAS_JOGO)
            self._faixa(pintor, linha.adjusted(0, 1, 0, -1), i)

            pintor.setPen(QColor(self._apagar(cor_texto, i)))
            texto = metricas.elidedText(rotulo, Qt.TextElideMode.ElideRight, larg_rotulo - 8)
            pintor.drawText(
                QRectF(0, y, larg_rotulo - 8, ALTURA_BARRAS_JOGO),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                texto,
            )

            if maximo > 0:
                crescido = self.crescimento.progresso(i)
                comprimento = max(3.0, area_barras * (valor / maximo)) * crescido
                barra = QRectF(larg_rotulo, linha.center().y() - 5, comprimento, 10)
                pintor.setPen(Qt.PenStyle.NoPen)
                pintor.setBrush(QColor(self._apagar(tema.primary, i)))
                pintor.drawRoundedRect(barra, 2, 2)
                pintor.save()
                pintor.setOpacity(crescido)
                texto_valor = self.rotulo_de_valor(i)
                largura_valor = metricas.horizontalAdvance(texto_valor)
                if barra.right() + 6 + largura_valor <= self.width():
                    pintor.setPen(QColor(self._apagar(cor_valor, i)))
                    alvo = QRectF(barra.right() + 6, y, largura_valor + 4, ALTURA_BARRAS_JOGO)
                    alinhamento = Qt.AlignmentFlag.AlignLeft
                else:
                    # O rótulo longo do apontado não cabe depois da barra mais
                    # comprida. Reservar a largura dele encolhia TODAS as barras
                    # o tempo todo por causa de um detalhe de hover; entrar na
                    # própria barra custa só a quem está apontando.
                    pintor.setPen(QColor(design.legivel_sobre(tema.primary)))
                    alvo = QRectF(barra.left(), y, barra.width() - 8, ALTURA_BARRAS_JOGO)
                    alinhamento = Qt.AlignmentFlag.AlignRight
                pintor.drawText(alvo, alinhamento | Qt.AlignmentFlag.AlignVCenter, texto_valor)
                pintor.restore()
        pintor.end()


class _ReguaDominio(_Grafico):
    """Uma barra empilhada: novas · aprendendo · dominadas."""

    def __init__(self, janela: Any, novas: int, aprendendo: int, dominadas: int) -> None:
        super().__init__(janela, 1, atraso=120)
        self._partes = (novas, aprendendo, dominadas)
        self._legenda: list[QRectF] = []
        self._segmentos: list[tuple[float, float]] = []
        linha_explicacao = QFontMetrics(janela.fonte("micro")).height() + 6
        # A linha da explicação é reservada desde o início: aparecer sob o
        # cursor não pode empurrar o gráfico de baixo.
        self.setMinimumHeight(ALTURA_REGUA + 22 + linha_explicacao)

    def _item_em(self, ponto: QPointF) -> int | None:
        if ponto.y() <= 16:
            for indice, (inicio, fim) in enumerate(self._segmentos):
                if inicio <= ponto.x() < fim:
                    return indice
        for indice, caixa in enumerate(self._legenda):
            if caixa.adjusted(-4, -4, 4, 4).contains(ponto):
                return indice
        return None

    @property
    def explicacao(self) -> str:
        return EXPLICACOES_DOMINIO[self.apontado] if self.apontado is not None else ""

    def retangulo_explicacao(self) -> QRectF:
        """Onde a explicação é escrita: abaixo da legenda, dentro do widget."""
        altura = QFontMetrics(self._janela.fonte("micro")).height()
        topo = 12 + 8 + altura + 8
        return QRectF(0, topo, self.width(), altura + 2)

    def paintEvent(self, _evento: Any) -> None:
        tema = self._janela.tema
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        fonte = self._janela.fonte("micro")
        pintor.setFont(fonte)
        metricas = QFontMetrics(fonte)

        novas, aprendendo, dominadas = self._partes
        total = novas + aprendendo + dominadas
        cores = (design.elevar(tema.surface, 0.22, tema.primary), tema.info, tema.accent)
        rotulos = (f"{novas} novas", f"{aprendendo} aprendendo", f"{dominadas} dominadas")

        trilho = QRectF(0, 0, self.width(), 12)
        visivel = trilho.width() * self.crescimento.progresso(0)
        self._segmentos = []
        pintor.setPen(Qt.PenStyle.NoPen)
        if total == 0:
            pintor.setBrush(QColor(cores[0]))
            pintor.drawRoundedRect(QRectF(0, 0, visivel, trilho.height()), 3, 3)
        else:
            x = 0.0
            for indice, (valor, cor) in enumerate(zip(self._partes, cores, strict=True)):
                comprimento = trilho.width() * (valor / total)
                self._segmentos.append((x, x + comprimento))
                if valor > 0 and x < visivel:
                    pintor.setBrush(QColor(self._apagar(cor, indice)))
                    pintor.drawRect(QRectF(x, 0, min(comprimento, visivel - x), trilho.height()))
                x += comprimento

        # Legenda: um quadradinho da cor e o rótulo, lado a lado.
        cor_texto = design.garantir_contraste(tema.text_muted, tema.surface)
        x = 0.0
        y = trilho.bottom() + 8
        self._legenda = []
        for indice, (cor, rotulo) in enumerate(zip(cores, rotulos, strict=True)):
            largura_texto = metricas.horizontalAdvance(rotulo)
            self._legenda.append(QRectF(x, y - 2, 12 + largura_texto + 4, metricas.height() + 4))
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(QColor(self._apagar(cor, indice)))
            pintor.drawRect(QRectF(x, y + 2, 8, 8))
            pintor.setPen(QColor(self._apagar(cor_texto, indice)))
            pintor.drawText(
                QRectF(x + 12, y - 2, largura_texto + 4, metricas.height() + 4),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                rotulo,
            )
            x += 12 + largura_texto + 18

        if self._indice is not None and self._destaque.valor > 0.01:
            pintor.save()
            pintor.setOpacity(self._destaque.valor)
            pintor.setPen(QColor(design.garantir_contraste(tema.text_muted, tema.surface)))
            pintor.drawText(
                self.retangulo_explicacao(),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                EXPLICACOES_DOMINIO[self._indice],
            )
            pintor.restore()
        pintor.end()


# ------------------------------------------------------------------- Nível
# Como cada jogo chama o número que só sobe. O visor dá patente; o RPG, um
# título a cada cinco níveis. Os outros dão o nome e o número.
NOMES_DO_NIVEL: dict[str, str] = {
    "Fallout": "LVL",
    "Elden Ring": "Nível",
    "Skyrim": "Nível",
    "The Witcher 3": "Nível",
    "Red Dead": "Rank",
    "GTA": "Rank",
    "Cyberpunk 2077": "Reputação",
    "RPG / Aventura (geral)": "Nível",
    "FPS / Multiplayer": "Patente",
}
PATENTES = (
    "Recruta", "Soldado", "Cabo", "Terceiro-sargento", "Segundo-sargento",
    "Primeiro-sargento", "Subtenente", "Aspirante", "Segundo-tenente",
    "Primeiro-tenente", "Capitão", "Major", "Tenente-coronel", "Coronel", "General",
)
TITULOS_DO_RPG = ("Aprendiz", "Aventureiro", "Veterano", "Herói", "Lenda")


def rotulo_do_nivel(jogo: str, numero: int) -> str:
    """O nível dito do jeito do jogo: "LVL 7", "Cabo · 3", "Veterano · 12"."""
    if jogo == "FPS / Multiplayer":
        return f"{PATENTES[min(numero, len(PATENTES)) - 1]} · {numero}"
    if jogo == "RPG / Aventura (geral)":
        return f"{TITULOS_DO_RPG[min((numero - 1) // 5, len(TITULOS_DO_RPG) - 1)]} · {numero}"
    return f"{NOMES_DO_NIVEL.get(jogo, 'Nível')} {numero}"


# A barra de experiência no traço do medidor de cada jogo: os blocos do
# Pip-Boy, o fio fino com moldura de ouro da Terra Intermédia, a barra do
# norte que cresce do centro para as pontas, o paralelogramo do bruxo, o
# núcleo redondo do velho oeste, a barra lisa do GTA, a chanfrada que se
# desfaz em bits da Night City, a de vidro do RPG e os traços do visor.
BARRAS_DE_NIVEL: dict[str, str] = {
    "terminal": "blocos",
    "graca": "fio_dourado",
    "nordico": "do_centro",
    "bruxo": "inclinada",
    "oeste": "nucleo",
    "celular": "plana",
    "dados": "chanfrada",
    "grimorio": "vidro",
    "tatico": "tracos",
}
BARRA_PADRAO = "simples"


def cor_da_barra(estilo: str, tema: Any) -> str:
    """A cor do trecho cheio: o acento do jogo; no terminal, o fósforo dele.

    O Pip-Boy é monocromático — a barra de experiência dele é do mesmo verde
    do resto da tela, e uma barra âmbar ali seria de outro aparelho.
    """
    return str(tema.primary if estilo == "blocos" else tema.accent)


def pintar_barra_de_nivel(
    pintor: QPainter, caixa: QRectF, fracao: float, estilo: str, tema: Any
) -> None:
    """A barra de experiência, cheia até ``fracao``, no estilo pedido.

    O trilho vazio é sempre visível: sem ele, um nível recém-alcançado (fração
    zero) não desenharia nada, e a tela pareceria quebrada justo na hora boa.
    """
    fracao = max(0.0, min(1.0, fracao))
    cheia = QColor(cor_da_barra(estilo, tema))
    trilho = QColor(design.elevar(tema.surface, 0.16, tema.primary))
    contorno = QColor(design.misturar(tema.border_forte, tema.accent, 0.35))
    pintor.save()
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    pintor.setPen(Qt.PenStyle.NoPen)
    x, y, w, h = caixa.x(), caixa.y(), caixa.width(), caixa.height()
    if estilo == "blocos":
        blocos, vao = 20, 2.0
        lado = (w - vao * (blocos - 1)) / blocos
        acesos = round(fracao * blocos)
        for indice in range(blocos):
            bloco = QRectF(x + indice * (lado + vao), y, lado, h)
            pintor.fillRect(bloco, cheia if indice < acesos else trilho)
    elif estilo == "fio_dourado":
        interno = caixa.adjusted(0, h * 0.25, 0, -h * 0.25)
        pintor.fillRect(interno, trilho)
        pintor.fillRect(QRectF(interno.x(), interno.y(), interno.width() * fracao, interno.height()), cheia)
        caneta = QPen(contorno, 1.0)
        pintor.setPen(caneta)
        pintor.setBrush(Qt.BrushStyle.NoBrush)
        pintor.drawRect(interno.adjusted(-1.5, -1.5, 1.5, 1.5))
    elif estilo == "do_centro":
        meio = y + h / 2
        pintor.fillRect(QRectF(x, meio - 1, w, 2), trilho)
        largura = w * fracao
        pintor.fillRect(QRectF(x + (w - largura) / 2, y + h * 0.2, largura, h * 0.6), cheia)
        for ponta in (x, x + w):
            losango = QPainterPath()
            losango.moveTo(ponta, meio - h / 2)
            losango.lineTo(ponta + h / 2, meio)
            losango.lineTo(ponta, meio + h / 2)
            losango.lineTo(ponta - h / 2, meio)
            losango.closeSubpath()
            pintor.fillPath(losango, contorno)
    elif estilo == "inclinada":
        def paralelogramo(largura: float) -> QPainterPath:
            caminho = QPainterPath()
            caminho.moveTo(x + h, y)
            caminho.lineTo(x + h + largura, y)
            caminho.lineTo(x + largura, y + h)
            caminho.lineTo(x, y + h)
            caminho.closeSubpath()
            return caminho

        pintor.fillPath(paralelogramo(w - h), trilho)
        if fracao > 0:
            pintor.fillPath(paralelogramo((w - h) * fracao), cheia)
    elif estilo == "nucleo":
        lado = min(w, h)
        anel = QRectF(x + (w - lado) / 2, y + (h - lado) / 2, lado, lado).adjusted(2, 2, -2, -2)
        caneta = QPen(trilho, max(2.5, lado * 0.12))
        caneta.setCapStyle(Qt.PenCapStyle.FlatCap)
        pintor.setPen(caneta)
        pintor.drawEllipse(anel)
        caneta.setColor(cheia)
        pintor.setPen(caneta)
        pintor.drawArc(anel, 90 * 16, -round(360 * 16 * fracao))
    elif estilo == "plana":
        pintor.fillRect(caixa, trilho)
        pintor.fillRect(QRectF(x, y, w * fracao, h), cheia)
        pintor.setPen(QPen(QColor(tema.surface), 1.0))
        for quinto in range(1, 5):
            pintor.drawLine(QPointF(x + w * quinto / 5, y), QPointF(x + w * quinto / 5, y + h))
    elif estilo == "chanfrada":
        corte = h * 0.8

        def chanfro(largura: float) -> QPainterPath:
            caminho = QPainterPath()
            caminho.moveTo(x, y)
            caminho.lineTo(x + largura, y)
            caminho.lineTo(x + largura, y + h - corte)
            caminho.lineTo(x + max(0.0, largura - corte), y + h)
            caminho.lineTo(x, y + h)
            caminho.closeSubpath()
            return caminho

        pintor.fillPath(chanfro(w), trilho)
        cheio = w * fracao
        if cheio > 0:
            pintor.fillPath(chanfro(cheio), cheia)
            # A ponta se desfaz em bits soltos, como dado ainda chegando.
            for passo, largura_bit in ((4.0, 3.0), (10.0, 2.0), (15.0, 1.5)):
                if x + cheio + passo + largura_bit < x + w:
                    pintor.fillRect(QRectF(x + cheio + passo, y + h * 0.25, largura_bit, h * 0.5), cheia)
    elif estilo == "vidro":
        raio = h / 2
        pintor.setBrush(trilho)
        pintor.drawRoundedRect(caixa, raio, raio)
        if fracao > 0:
            preenchida = QRectF(x, y, max(h, w * fracao), h)
            gradiente = QLinearGradient(preenchida.topLeft(), preenchida.bottomLeft())
            gradiente.setColorAt(0.0, QColor(design.misturar(tema.accent, "#ffffff", 0.35)))
            gradiente.setColorAt(0.55, cheia)
            gradiente.setColorAt(1.0, QColor(design.misturar(tema.accent, "#000000", 0.25)))
            pintor.setBrush(gradiente)
            pintor.drawRoundedRect(preenchida, raio, raio)
    elif estilo == "tracos":
        tracos = 30
        passo = w / tracos
        acesos = round(fracao * tracos)
        for indice in range(tracos):
            pintor.fillRect(
                QRectF(x + indice * passo, y, max(1.5, passo * 0.45), h),
                cheia if indice < acesos else trilho,
            )
    else:
        raio = min(3.0, h / 2)
        pintor.setBrush(trilho)
        pintor.drawRoundedRect(caixa, raio, raio)
        if fracao > 0:
            pintor.setBrush(cheia)
            pintor.drawRoundedRect(QRectF(x, y, max(2 * raio, w * fracao), h), raio, raio)
    pintor.restore()


class BarraDeNivel(QWidget):
    """O nível do caderno no alto do painel: o nome do jogo, a barra e o XP.

    A barra enche ao abrir, junto com os gráficos; passar o cursor mostra a
    regra do XP — o número só convence quem sabe de onde ele vem.
    """

    ALTURA = 40
    ALTURA_BARRA = 10.0

    def __init__(self, janela: Any, nivel: Nivel) -> None:
        super().__init__()
        self._janela = janela
        self.nivel = nivel
        self.estilo = BARRAS_DE_NIVEL.get(str(getattr(janela.atmosfera, "icones", "")), BARRA_PADRAO)
        self.rotulo = rotulo_do_nivel(janela.tema.name, nivel.numero)
        reduzir = lambda: bool(janela.intensidade_atmosfera <= 0.0)  # noqa: E731
        self.crescimento = Crescimento(self, 1, reduzir=reduzir, atraso=0)
        self._cresceu = False
        self.setFixedHeight(self.ALTURA)
        self.setToolTip(REGRA_DO_XP)
        self.setAccessibleName(
            f"{self.rotulo}: {nivel.xp} de {nivel.teto} XP, faltam {nivel.faltam} para o próximo"
        )

    @property
    def texto_do_xp(self) -> str:
        return f"{self.nivel.xp - self.nivel.piso} / {self.nivel.teto - self.nivel.piso} XP"

    def showEvent(self, evento: Any) -> None:
        super().showEvent(evento)
        if not self._cresceu:
            self._cresceu = True
            self.crescimento.iniciar()

    def caixa_da_barra(self) -> QRectF:
        """Onde a barra é desenhada — no núcleo, o anel à esquerda."""
        if self.estilo == "nucleo":
            return QRectF(0, 0, float(self.ALTURA), float(self.ALTURA))
        m_rotulo = QFontMetrics(self._fonte_rotulo())
        m_xp = QFontMetrics(self._janela.fonte("micro"))
        esquerda = m_rotulo.horizontalAdvance(self.rotulo) + 16
        direita = m_xp.horizontalAdvance(self.texto_do_xp) + 14
        return QRectF(
            esquerda, (self.height() - self.ALTURA_BARRA) / 2,
            max(40.0, self.width() - esquerda - direita), self.ALTURA_BARRA,
        )

    def _fonte_rotulo(self) -> QFont:
        fonte: QFont = self._janela.fonte("titulo", ui=False)
        return fonte

    def paintEvent(self, _evento: Any) -> None:
        tema = self._janela.tema
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        caixa = self.caixa_da_barra()
        fracao = self.nivel.fracao * self.crescimento.progresso(0)
        pintar_barra_de_nivel(pintor, caixa, fracao, self.estilo, tema)
        cor_rotulo = design.garantir_contraste(tema.primary, tema.surface)
        cor_xp = design.garantir_contraste(tema.text_muted, tema.surface)
        pintor.setFont(self._fonte_rotulo())
        pintor.setPen(QColor(cor_rotulo))
        if self.estilo == "nucleo":
            # O número dentro do anel; o nome e o que falta ao lado dele.
            pintor.drawText(caixa, int(Qt.AlignmentFlag.AlignCenter), str(self.nivel.numero))
            nome = NOMES_DO_NIVEL.get(tema.name, "Nível")
            texto = QRectF(caixa.right() + 12, 0, self.width() - caixa.right() - 12, self.height())
            pintor.drawText(texto, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), nome)
            pintor.setFont(self._janela.fonte("micro"))
            pintor.setPen(QColor(cor_xp))
            pintor.drawText(
                texto, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                f"{self.texto_do_xp} · faltam {self.nivel.faltam} para o {self.nivel.numero + 1}",
            )
            pintor.end()
            return
        pintor.drawText(
            QRectF(0, 0, caixa.left() - 8, self.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), self.rotulo,
        )
        pintor.setFont(self._janela.fonte("micro"))
        pintor.setPen(QColor(cor_xp))
        pintor.drawText(
            QRectF(caixa.right() + 10, 0, self.width() - caixa.right() - 10, self.height()),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), self.texto_do_xp,
        )
        pintor.end()


class RolagemDoPainel(QScrollArea):
    """A rolagem dos gráficos, que pede a altura INTEIRA deles.

    A ``QScrollArea`` do Qt limita o próprio tamanho preferido a umas vinte
    linhas de texto, e o painel abriria rolando mesmo numa tela que o comporta
    de sobra. Esta pede o que o conteúdo pede: rolar é o recurso de uma tela
    baixa, não o jeito normal de ver o painel.
    """

    def sizeHint(self) -> QSize:
        conteudo = self.widget()
        if conteudo is None:
            return super().sizeHint()
        dica = conteudo.sizeHint()
        return QSize(dica.width(), dica.height() + 2 * self.frameWidth())


class JanelaProgresso(QDialog):
    """O caderno em números, numa única tela.

    Numa tela que o comporta, sem rolagem nenhuma. Numa tela baixa — um
    notebook de 768 linhas, onde o painel inteiro não cabe e o botão de
    fechar ficaria abaixo da barra de tarefas —, os dois gráficos de barras
    encolhem primeiro, e só o que ainda sobrar rola (ver ``caber_na_altura``).
    O cabeçalho, o nível e os botões ficam sempre à vista.

    Fecha com ``REVISAR`` quando o jogador sai pelo botão de revisar a dívida
    de hoje: quem abriu o painel (o caderno) abre os cartões em seguida.
    """

    REVISAR = 2

    def __init__(self, janela: Any, store: VocabularyStore, parent: QWidget | None = None) -> None:
        super().__init__(parent if parent is not None else janela)
        self._janela = janela
        tema = janela.tema
        self._forma = janela.atmosfera.forma
        self._fundo = tema.surface
        self._borda = tema.border_forte

        self.setWindowTitle("Progresso")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(LARGURA)

        # A mesma resposta ao cursor das outras janelas, com o cenário daqui:
        # sem movimento próprio, ela só se mexe enquanto o cursor se mexe.
        self._cenario = Cenario()
        self._cenario.definir_intensidade(janela.intensidade_atmosfera)
        self._cenario.movimento = janela.intensidade_atmosfera > 0.0
        self._cenario.definir(tema, so_o_cursor(janela.atmosfera))
        self._cursor_vivo = CursorVivo(
            self, self._cenario, cor=lambda: self._janela.tema.accent
        )

        estatisticas = store.estatisticas()
        novas, aprendendo, dominadas = store.dominio()

        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(30, 24, 30, 22)
        coluna.setSpacing(8)

        # Os gráficos moram num painel próprio, para a moldura do jogo ter o
        # que contornar; o cabeçalho e o botão ficam fora dela.
        self.painel = QWidget()
        pilha = QVBoxLayout(self.painel)
        folga = round(FAIXA_MOLDURA) + 2 if janela.atmosfera.moldura else 0
        pilha.setContentsMargins(folga, max(0, folga - 10), folga, folga)
        pilha.setSpacing(8)

        def secao(texto: str) -> None:
            etiqueta = QLabel(texto.upper())
            etiqueta.setFont(janela.fonte("secao"))
            etiqueta.setStyleSheet(
                f"color: {design.garantir_contraste(tema.text_muted, self._fundo)};"
                " background: transparent;"
            )
            pilha.addSpacing(10)
            pilha.addWidget(etiqueta)

        # O cabeçalho: o objeto do jogo e o nome que ele dá a esta tela, com a
        # função escrita ao lado, miúda — como no caderno e no histórico.
        cabecalho = QHBoxLayout()
        cabecalho.setSpacing(10)
        self.icone_titulo = IconeDoJogo(janela, "progresso")
        cabecalho.addWidget(self.icone_titulo, 0, Qt.AlignmentFlag.AlignBottom)
        titulo = self.titulo = QLabel(tema.nome_do_progresso)
        titulo.setFont(janela.fonte("display", ui=False))
        titulo.setStyleSheet(
            f"color: {design.garantir_contraste(tema.primary, self._fundo)};"
            " background: transparent;"
        )
        self.icone_titulo.definir_lado(QFontMetrics(titulo.font()).height())
        cabecalho.addWidget(titulo, 0, Qt.AlignmentFlag.AlignBottom)
        cabecalho.addStretch(1)
        self.subtitulo = QLabel("progresso do caderno")
        self.subtitulo.setFont(janela.fonte("legenda"))
        self.subtitulo.setStyleSheet(
            f"color: {design.garantir_contraste(tema.text_muted, self._fundo)};"
            " background: transparent;"
        )
        cabecalho.addWidget(self.subtitulo, 0, Qt.AlignmentFlag.AlignBottom)
        coluna.addLayout(cabecalho)
        # O nível do caderno, no nome e na barra do jogo (ver pipboy/nivel.py).
        self.barra_nivel = BarraDeNivel(janela, nivel_de(xp_do_caderno(estatisticas)))
        coluna.addWidget(self.barra_nivel)

        partes = [f"{estatisticas.total} termos no caderno"]
        if estatisticas.acertos or estatisticas.erros:
            partes.append(f"{estatisticas.aproveitamento:.0%} de acerto nas revisões")
        # Direto, sem getattr: faz parte do contrato da janela, e o padrão
        # silencioso escondia uma renomeação como "sequência de zero dias".
        sequencia = janela.sequencia_de_estudo()
        if sequencia > 1:
            partes.append(f"◆ sequência de {sequencia} dias de estudo")
        elif sequencia == 1:
            partes.append("◆ 1º dia da sequência — volte amanhã")
        resumo = QLabel(" · ".join(partes))
        resumo.setFont(janela.fonte("legenda"))
        resumo.setStyleSheet(
            f"color: {design.garantir_contraste(tema.text_muted, self._fundo)};"
            " background: transparent;"
        )
        coluna.addWidget(resumo)

        secao("Palavras novas por semana")
        self.grafico_semanas = _GraficoSemanas(janela, store.novas_por_semana(8))
        pilha.addWidget(self.grafico_semanas)

        # O que vem pela frente e o que ficou para trás, lado a lado: quantas
        # palavras vencem em cada um dos próximos dias e em que dias houve
        # estudo nas últimas semanas.
        hoje = datetime.now(timezone.utc).astimezone().date()
        previsao = store.previsao(DIAS_DA_PREVISAO)
        self.grafico_previsao = _GraficoPrevisao(janela, previsao)
        inicio = hoje - timedelta(weeks=SEMANAS_DO_CALENDARIO)
        self.calendario = _CalendarioDeEstudo(janela, janela.dias_de_estudo(inicio), hoje)
        dupla = QHBoxLayout()
        dupla.setSpacing(28)
        for texto_secao, grafico in (
            ("Próximos 7 dias", self.grafico_previsao),
            ("Dias de estudo", self.calendario),
        ):
            coluna_dupla = QVBoxLayout()
            coluna_dupla.setSpacing(8)
            etiqueta_dupla = QLabel(texto_secao.upper())
            etiqueta_dupla.setFont(janela.fonte("secao"))
            etiqueta_dupla.setStyleSheet(
                f"color: {design.garantir_contraste(tema.text_muted, self._fundo)};"
                " background: transparent;"
            )
            coluna_dupla.addWidget(etiqueta_dupla)
            coluna_dupla.addWidget(grafico)
            coluna_dupla.addStretch(1)
            dupla.addLayout(coluna_dupla, 1 if grafico is self.grafico_previsao else 0)
        pilha.addSpacing(10)
        pilha.addLayout(dupla)

        secao("Domínio")
        self.regua = _ReguaDominio(janela, novas, aprendendo, dominadas)
        pilha.addWidget(self.regua)

        por_jogo = store.por_jogo(6)
        self.grafico_jogos: _GraficoJogos | None = None
        if por_jogo:
            secao("Por jogo")
            self.grafico_jogos = _GraficoJogos(janela, por_jogo, estatisticas.total)
            pilha.addWidget(self.grafico_jogos)
        self.rolagem = RolagemDoPainel()
        self.rolagem.setWidgetResizable(True)
        self.rolagem.setFrameShape(QFrame.Shape.NoFrame)
        self.rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rolagem.setWidget(self.painel)
        self.rolagem.setStyleSheet(f"""
        QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
        QScrollBar::handle:vertical {{
            background: {tema.border}; border-radius: 4px; min-height: 40px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {tema.border_forte}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height: 0px; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
        """)
        coluna.addWidget(self.rolagem, 1)
        self.moldura_graficos = MolduraDoPainel(janela, self.rolagem)

        acoes = QHBoxLayout()
        acoes.addStretch(1)
        botao = self._botao_fechar = Botao(
            "Fechar", variante="acento", paleta=janela.paleta, forma=self._forma
        )
        botao.setFont(janela.fonte("corpo_forte"))
        botao.clicked.connect(self.accept)
        acoes.addWidget(botao)
        # A dívida de agora, com o caminho para pagá-la ao lado do número.
        vencidas_hoje = store.pendentes()
        self.botao_revisar = Botao(
            f"Revisar ({vencidas_hoje})", variante="primario", icone="revisao",
            paleta=janela.paleta, forma=self._forma,
        )
        self.botao_revisar.setFont(janela.fonte("corpo_forte"))
        self.botao_revisar.setToolTip("Fechar o painel e revisar as palavras vencidas")
        self.botao_revisar.clicked.connect(lambda: self.done(self.REVISAR))
        self.botao_revisar.setVisible(vencidas_hoje > 0)
        acoes.addWidget(self.botao_revisar)
        coluna.addSpacing(8)
        coluna.addLayout(acoes)
        botao.setFocus()

    def resizeEvent(self, evento: Any) -> None:
        super().resizeEvent(evento)
        if hasattr(self, "_cursor_vivo"):
            self._cursor_vivo.reposicionar()

    def caber_na_altura(self, disponivel: int) -> None:
        """Ajusta a janela a ``disponivel`` pixels de altura, no máximo.

        Com espaço, ela fica no tamanho preferido de tudo. Sem, a altura é a
        que há: o layout encolhe os gráficos elásticos até o mínimo deles, e
        daí para baixo a rolagem assume o resto.
        """
        preferida = self.sizeHint().height()
        self.resize(self.width(), max(self.minimumSizeHint().height(), min(preferida, disponivel)))

    def showEvent(self, evento: Any) -> None:
        super().showEvent(evento)
        tela = self.screen()
        if tela is not None:
            area = tela.availableGeometry()
            self.caber_na_altura(area.height() - 2 * MARGEM_DA_TELA)
            # Encolhida, a janela pode ter ficado centrada sobre um ponto que a
            # empurra para fora da tela; traz de volta para dentro.
            geometria = self.frameGeometry()
            topo = min(max(geometria.top(), area.top() + MARGEM_DA_TELA),
                       area.bottom() - MARGEM_DA_TELA - geometria.height())
            if topo != geometria.top():
                self.move(geometria.left(), max(area.top(), topo))
        self.moldura_graficos.montar()
        self._cursor_vivo.reposicionar()

    def hideEvent(self, evento: Any) -> None:
        super().hideEvent(evento)
        self._cursor_vivo.esquecer()

    def paintEvent(self, _evento: Any) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        caminho = caminho_forma(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), self._forma, design.RAIO
        )
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(QColor(self._fundo))
        pintor.drawPath(caminho)
        # A luz do cursor sobre o fundo liso, atenuada e recortada na moldura.
        pintor.save()
        pintor.setClipPath(caminho)
        self._cenario.pintar_luz(pintor, atenuacao=ATENUACAO_NO_FUNDO_NU)
        pintor.restore()
        acender_borda(pintor, self, caminho)
        caneta = QPen(QColor(self._borda))
        caneta.setWidthF(1.0)
        pintor.setPen(caneta)
        pintor.setBrush(Qt.BrushStyle.NoBrush)
        pintor.drawPath(caminho)
        pintor.end()
