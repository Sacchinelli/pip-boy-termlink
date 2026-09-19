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
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import design
from ..vocabulary import DIAS_PARA_DOMINIO, VocabularyStore
from .atmosfera import ATENUACAO_NO_FUNDO_NU, Cenario, so_o_cursor
from .componentes import Botao, acender_borda, caminho_forma
from .cursor import CursorVivo
from .movimento import Crescimento, Transicao

LARGURA = 640
ALTURA_GRAFICO = 150
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
        self.setMinimumHeight(ALTURA_GRAFICO)

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


class JanelaProgresso(QDialog):
    """O caderno em números, numa única tela sem rolagem."""

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

        def secao(texto: str) -> None:
            etiqueta = QLabel(texto.upper())
            etiqueta.setFont(janela.fonte("secao"))
            etiqueta.setStyleSheet(
                f"color: {design.garantir_contraste(tema.text_muted, self._fundo)};"
                " background: transparent;"
            )
            coluna.addSpacing(10)
            coluna.addWidget(etiqueta)

        titulo = QLabel("PROGRESSO")
        titulo.setFont(janela.fonte("display", ui=False))
        titulo.setStyleSheet(
            f"color: {design.garantir_contraste(tema.primary, self._fundo)};"
            " background: transparent;"
        )
        coluna.addWidget(titulo)

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
        coluna.addWidget(self.grafico_semanas)

        secao("Domínio")
        self.regua = _ReguaDominio(janela, novas, aprendendo, dominadas)
        coluna.addWidget(self.regua)

        por_jogo = store.por_jogo(6)
        self.grafico_jogos: _GraficoJogos | None = None
        if por_jogo:
            secao("Por jogo")
            self.grafico_jogos = _GraficoJogos(janela, por_jogo, estatisticas.total)
            coluna.addWidget(self.grafico_jogos)

        acoes = QHBoxLayout()
        acoes.addStretch(1)
        botao = self._botao_fechar = Botao(
            "Fechar", variante="acento", paleta=janela.paleta, forma=self._forma
        )
        botao.setFont(janela.fonte("corpo_forte"))
        botao.clicked.connect(self.accept)
        acoes.addWidget(botao)
        coluna.addSpacing(8)
        coluna.addLayout(acoes)
        botao.setFocus()

    def resizeEvent(self, evento: Any) -> None:
        super().resizeEvent(evento)
        if hasattr(self, "_cursor_vivo"):
            self._cursor_vivo.reposicionar()

    def showEvent(self, evento: Any) -> None:
        super().showEvent(evento)
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
