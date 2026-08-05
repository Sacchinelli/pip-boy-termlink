"""Painel de progresso: o caderno contado, desenhado no tema.

O banco sempre soube quantas palavras nasceram por semana, de que jogo elas
vieram e quantas já estão dominadas — mas ninguém via. Este painel desenha
essas três respostas com o QPainter, nas cores e na geometria do tema, como
todo o resto do programa: nenhuma biblioteca de gráfico, nenhum widget do
sistema, só barras que qualquer um lê de relance.

Os gráficos recebem dados prontos (rótulo e número) e não conhecem o banco:
`vocabulary.py` conta, aqui se desenha — a mesma divisão de trabalho do
resto do projeto.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import design
from ..vocabulary import VocabularyStore
from .componentes import Botao, caminho_forma

LARGURA = 640
ALTURA_GRAFICO = 150
ALTURA_BARRAS_JOGO = 26
ALTURA_REGUA = 22


class _GraficoSemanas(QWidget):
    """Barras verticais: palavras novas por semana."""

    def __init__(self, janela: Any, dados: list[tuple[str, int]]) -> None:
        super().__init__()
        self._janela = janela
        self._dados = dados
        self.setMinimumHeight(ALTURA_GRAFICO)

    def paintEvent(self, _evento: Any) -> None:
        tema = self._janela.tema
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        fonte = self._janela.fonte("micro")
        pintor.setFont(fonte)
        metricas = QFontMetrics(fonte)

        alt_rotulo = metricas.height() + 6
        area = QRectF(0, 4, self.width(), self.height() - alt_rotulo - 8)
        maximo = max((v for _, v in self._dados), default=0)

        passo = area.width() / max(1, len(self._dados))
        largura_barra = min(44.0, passo * 0.56)
        cor_barra = QColor(tema.accent)
        cor_apagada = QColor(design.elevar(tema.surface, 0.18, tema.primary))
        cor_texto = QColor(design.garantir_contraste(tema.text_muted, tema.surface))
        cor_valor = QColor(design.garantir_contraste(tema.primary, tema.surface))

        for i, (rotulo, valor) in enumerate(self._dados):
            centro_x = area.left() + passo * (i + 0.5)
            x = centro_x - largura_barra / 2

            if maximo > 0 and valor > 0:
                altura = max(3.0, area.height() * (valor / maximo))
                barra = QRectF(x, area.bottom() - altura, largura_barra, altura)
                pintor.setPen(Qt.PenStyle.NoPen)
                pintor.setBrush(cor_barra)
                pintor.drawRoundedRect(barra, 2, 2)
                # O número mora acima da barra; quando a barra toca o teto e
                # não sobra céu, ele entra NELA — cortado, nunca.
                acima = barra.top() - metricas.height() - 2
                if acima >= area.top():
                    pintor.setPen(cor_valor)
                    alvo = QRectF(
                        x - passo / 2, acima, largura_barra + passo, metricas.height()
                    )
                else:
                    pintor.setPen(QColor(design.legivel_sobre(tema.accent)))
                    alvo = QRectF(x, barra.top() + 2, largura_barra, metricas.height())
                pintor.drawText(alvo, Qt.AlignmentFlag.AlignCenter, str(valor))
            else:
                # Semana zerada: um traço no chão, para o eixo não ter buraco.
                pintor.setPen(Qt.PenStyle.NoPen)
                pintor.setBrush(cor_apagada)
                pintor.drawRect(QRectF(x, area.bottom() - 2, largura_barra, 2))

            pintor.setPen(cor_texto)
            pintor.drawText(
                QRectF(centro_x - passo / 2, area.bottom() + 4, passo, metricas.height()),
                Qt.AlignmentFlag.AlignCenter,
                rotulo,
            )
        pintor.end()


class _GraficoJogos(QWidget):
    """Barras horizontais: de que jogo o vocabulário está vindo."""

    def __init__(self, janela: Any, dados: list[tuple[str, int]]) -> None:
        super().__init__()
        self._janela = janela
        self._dados = dados
        self.setMinimumHeight(ALTURA_BARRAS_JOGO * max(1, len(dados)) + 8)

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

        cor_barra = QColor(tema.primary)
        cor_texto = QColor(design.garantir_contraste(tema.secondary, tema.surface))
        cor_valor = QColor(design.garantir_contraste(tema.primary, tema.surface))

        for i, (rotulo, valor) in enumerate(self._dados):
            y = i * ALTURA_BARRAS_JOGO
            linha = QRectF(0, y, self.width(), ALTURA_BARRAS_JOGO)

            pintor.setPen(cor_texto)
            texto = metricas.elidedText(rotulo, Qt.TextElideMode.ElideRight, larg_rotulo - 8)
            pintor.drawText(
                QRectF(0, y, larg_rotulo - 8, ALTURA_BARRAS_JOGO),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                texto,
            )

            if maximo > 0:
                comprimento = max(3.0, area_barras * (valor / maximo))
                barra = QRectF(
                    larg_rotulo, linha.center().y() - 5, comprimento, 10
                )
                pintor.setPen(Qt.PenStyle.NoPen)
                pintor.setBrush(cor_barra)
                pintor.drawRoundedRect(barra, 2, 2)
                pintor.setPen(cor_valor)
                pintor.drawText(
                    QRectF(barra.right() + 6, y, larg_valor, ALTURA_BARRAS_JOGO),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    str(valor),
                )
        pintor.end()


class _ReguaDominio(QWidget):
    """Uma barra empilhada: novas · aprendendo · dominadas."""

    def __init__(self, janela: Any, novas: int, aprendendo: int, dominadas: int) -> None:
        super().__init__()
        self._janela = janela
        self._partes = (novas, aprendendo, dominadas)
        self.setMinimumHeight(ALTURA_REGUA + 22)

    def paintEvent(self, _evento: Any) -> None:
        tema = self._janela.tema
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        fonte = self._janela.fonte("micro")
        pintor.setFont(fonte)
        metricas = QFontMetrics(fonte)

        novas, aprendendo, dominadas = self._partes
        total = novas + aprendendo + dominadas
        cores = (
            QColor(design.elevar(tema.surface, 0.22, tema.primary)),
            QColor(tema.info),
            QColor(tema.accent),
        )
        rotulos = (f"{novas} novas", f"{aprendendo} aprendendo", f"{dominadas} dominadas")

        trilho = QRectF(0, 0, self.width(), 12)
        if total == 0:
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(cores[0])
            pintor.drawRoundedRect(trilho, 3, 3)
        else:
            x = 0.0
            pintor.setPen(Qt.PenStyle.NoPen)
            for valor, cor in zip(self._partes, cores, strict=True):
                if valor <= 0:
                    continue
                comprimento = trilho.width() * (valor / total)
                pintor.setBrush(cor)
                pintor.drawRect(QRectF(x, 0, comprimento, trilho.height()))
                x += comprimento

        # Legenda: um quadradinho da cor e o rótulo, lado a lado.
        cor_texto = QColor(design.garantir_contraste(tema.text_muted, tema.surface))
        x = 0.0
        y = trilho.bottom() + 8
        for cor, rotulo in zip(cores, rotulos, strict=True):
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(cor)
            pintor.drawRect(QRectF(x, y + 2, 8, 8))
            pintor.setPen(cor_texto)
            largura_texto = metricas.horizontalAdvance(rotulo)
            pintor.drawText(
                QRectF(x + 12, y - 2, largura_texto + 4, metricas.height() + 4),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                rotulo,
            )
            x += 12 + largura_texto + 18
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
        sequencia = getattr(janela, "sequencia_de_estudo", lambda: 0)()
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
        coluna.addWidget(_GraficoSemanas(janela, store.novas_por_semana(8)))

        secao("Domínio")
        coluna.addWidget(_ReguaDominio(janela, novas, aprendendo, dominadas))

        por_jogo = store.por_jogo(6)
        if por_jogo:
            secao("Por jogo")
            coluna.addWidget(_GraficoJogos(janela, por_jogo))

        acoes = QHBoxLayout()
        acoes.addStretch(1)
        botao = Botao("Fechar", variante="acento", paleta=janela.paleta, forma=self._forma)
        botao.setFont(janela.fonte("corpo_forte"))
        botao.clicked.connect(self.accept)
        acoes.addWidget(botao)
        coluna.addSpacing(8)
        coluna.addLayout(acoes)
        botao.setFocus()

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
