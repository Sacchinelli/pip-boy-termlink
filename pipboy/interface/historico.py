"""Visualizador do histórico: reler o que o tutor ensinou, sessão por sessão.

Duas colunas: à esquerda as sessões (data, jogo, quantas falas), à direita a
transcrição da sessão escolhida — cada fala com o autor na cor do seu papel,
como na conversa ao vivo. Uma sessão pode ser apagada; o histórico é do
jogador, não do programa.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import design
from ..historico import Fala, HistoricoStore, ResumoDeSessao
from .componentes import Botao, caminho_forma
from .dialogo import Caixa
from .moldura import BarraDeTitulo, GripsRedimensionamento, aplicar_cantos_do_sistema

LARGURA_LISTA = 250


def _data_amigavel(iso: str) -> str:
    try:
        quando = datetime.fromisoformat(iso).astimezone()
    except ValueError:
        return iso
    return quando.strftime("%d/%m/%Y %H:%M")


class JanelaHistorico(QDialog):
    """Catálogo das sessões gravadas, com a mesma moldura do caderno."""

    def __init__(self, janela: Any, historico: HistoricoStore) -> None:
        super().__init__(janela)
        self._janela = janela
        self._historico = historico
        self._sessao_aberta: int | None = None
        self._falas_abertas: list[Fala] = []
        self._titulo_sessao = ""
        # Palavra que trouxe o jogador até aqui, quando ele veio pelo caderno.
        self._destaque = ""

        self.setWindowTitle("Histórico de sessões")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setMinimumSize(720, 480)
        self.resize(920, 640)

        moldura = QVBoxLayout(self)
        moldura.setContentsMargins(0, 0, 0, 0)
        moldura.setSpacing(0)
        self.barra_titulo = BarraDeTitulo(
            self, provedor=janela, titulo="Histórico de sessões", botoes=("fechar",)
        )
        moldura.addWidget(self.barra_titulo)

        corpo = QWidget(objectName="historicoCorpo")
        moldura.addWidget(corpo, 1)
        linha = QHBoxLayout(corpo)
        linha.setContentsMargins(20, 16, 20, 16)
        linha.setSpacing(16)

        # -- coluna das sessões
        coluna_lista = QVBoxLayout()
        coluna_lista.setSpacing(8)
        self._rolagem_lista = QScrollArea(objectName="historicoLista")
        self._rolagem_lista.setWidgetResizable(True)
        self._rolagem_lista.setFrameShape(QFrame.Shape.NoFrame)
        self._rolagem_lista.setFixedWidth(LARGURA_LISTA)
        self._rolagem_lista.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._interno_lista = QWidget(objectName="historicoListaInterno")
        self._pilha_lista = QVBoxLayout(self._interno_lista)
        self._pilha_lista.setContentsMargins(0, 0, 6, 0)
        self._pilha_lista.setSpacing(6)
        self._pilha_lista.addStretch(1)
        self._rolagem_lista.setWidget(self._interno_lista)
        coluna_lista.addWidget(self._rolagem_lista, 1)
        linha.addLayout(coluna_lista)

        # -- transcrição
        coluna_falas = QVBoxLayout()
        coluna_falas.setSpacing(8)
        self._cabecalho = QLabel("")
        self._cabecalho.setWordWrap(True)
        coluna_falas.addWidget(self._cabecalho)

        # Busca dentro da transcrição aberta. Filtra as falas em vez de
        # rolar até a próxima ocorrência: numa conversa de uma hora, ver
        # só as cinco linhas que falam de "wasteland" é o que se quer.
        self._busca = QLineEdit(objectName="historicoBusca")
        self._busca.setPlaceholderText("Buscar nesta conversa…")
        self._busca.setClearButtonEnabled(True)
        self._busca.setAccessibleName("Buscar na transcrição")
        self._busca.textChanged.connect(self._filtrar)
        coluna_falas.addWidget(self._busca)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self._busca.setFocus)

        self._rolagem_falas = QScrollArea(objectName="historicoFalas")
        self._rolagem_falas.setWidgetResizable(True)
        self._rolagem_falas.setFrameShape(QFrame.Shape.NoFrame)
        self._interno_falas = QWidget(objectName="historicoFalasInterno")
        self._pilha_falas = QVBoxLayout(self._interno_falas)
        self._pilha_falas.setContentsMargins(0, 0, 12, 0)
        self._pilha_falas.setSpacing(10)
        self._pilha_falas.addStretch(1)
        self._rolagem_falas.setWidget(self._interno_falas)
        coluna_falas.addWidget(self._rolagem_falas, 1)

        rodape = QHBoxLayout()
        rodape.addStretch(1)
        self._botao_apagar = Botao(
            "✕   Apagar sessão", variante="perigo",
            paleta=janela.paleta, forma=janela.atmosfera.forma,
        )
        self._botao_apagar.clicked.connect(self._apagar_sessao)
        rodape.addWidget(self._botao_apagar)
        botao_fechar = Botao(
            "Fechar", variante="acento",
            paleta=janela.paleta, forma=janela.atmosfera.forma,
        )
        botao_fechar.clicked.connect(self.close)
        rodape.addWidget(botao_fechar)
        coluna_falas.addLayout(rodape)
        linha.addLayout(coluna_falas, 1)

        self._grips = GripsRedimensionamento(self)
        self._grips.reposicionar()
        self.aplicar_tema()
        self._recarregar()

    # ---------------------------------------------------------------- Tema
    def aplicar_tema(self) -> None:
        janela, t = self._janela, self._janela.tema
        self.barra_titulo.aplicar_tema()
        self._cabecalho.setFont(janela.fonte("legenda"))
        self._busca.setFont(janela.fonte("corpo"))
        raio = {"chanfrada": 3, "reta": 2}.get(janela.atmosfera.forma, 8)
        self.setStyleSheet(f"""
        QDialog {{ background: {t.screen}; }}
        QWidget {{ color: {t.primary}; }}
        #historicoCorpo, #historicoLista, #historicoListaInterno,
        #historicoFalas, #historicoFalasInterno {{ background: transparent; }}
        QLineEdit#historicoBusca {{
            background: {t.surface_alta}; color: {t.primary};
            border: 1px solid {t.border}; border-radius: {raio + 2}px;
            padding: 8px 12px; selection-background-color: {t.selection};
        }}
        QLineEdit#historicoBusca:focus {{ border-color: {t.border_forte}; }}
        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
        QScrollBar::handle:vertical {{
            background: {t.border}; border-radius: 4px; min-height: 40px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {t.border_forte}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height: 0px; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
        """)
        self._cabecalho.setStyleSheet(
            f"color: {design.garantir_contraste(t.text_muted, t.screen)};"
            " background: transparent;"
        )

    # --------------------------------------------------------------- Dados
    def recarregar(self) -> None:
        """Relê a lista de sessões e a transcrição aberta.

        Pública porque quem reabre esta janela — a janela principal — precisa
        pedir isso, e estava chamando o método privado de fora para consegui-lo.
        """
        self._recarregar()

    def _recarregar(self) -> None:
        janela = self._janela
        # Limpa a lista (o stretch do fim fica).
        while self._pilha_lista.count() > 1:
            item = self._pilha_lista.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()

        sessoes = self._historico.listar_sessoes()
        for resumo in sessoes:
            rotulo = f"{_data_amigavel(resumo.iniciada_em)}\n{resumo.jogo or 'Sem jogo'} · {resumo.falas} falas"
            botao = Botao(
                rotulo, variante="sutil", paleta=janela.paleta,
                forma=janela.atmosfera.forma, alinhamento_esquerdo=True,
            )
            botao.setFont(janela.fonte("legenda"))
            botao.setMinimumHeight(52)
            botao.clicked.connect(lambda _=False, s=resumo: self._abrir_sessao(s))
            self._pilha_lista.insertWidget(self._pilha_lista.count() - 1, botao)

        if not sessoes:
            self._cabecalho.setText(
                "Nenhuma sessão gravada ainda. A partir de agora, cada conversa "
                "com o tutor fica registrada aqui — só neste computador."
            )
            self._botao_apagar.setEnabled(False)
            self._sessao_aberta = None
            self._falas_abertas = []
            self._limpar_falas()
            return

        # A transcrição é SEMPRE relida, mesmo quando a sessão aberta é a
        # mesma: ela pode ter crescido desde a última vez que esta janela
        # esteve na tela — é o caso normal, aliás, porque a sessão que está
        # acontecendo agora é justamente a que se quer reler. Sem isto, quem
        # fechava e reabria o histórico via a conversa congelada no passado.
        atual = next((s for s in sessoes if s.id == self._sessao_aberta), None)
        self._abrir_sessao(atual or sessoes[0])

    def _limpar_falas(self) -> None:
        while self._pilha_falas.count() > 1:
            item = self._pilha_falas.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()

    def abrir_por_id(self, sessao_id: int, *, destaque: str = "") -> bool:
        """Abre uma sessão pelo id. Devolve se ela existia.

        É a porta pela qual o caderno entra: clicar numa palavra abre a
        conversa em que ela foi ensinada, com ``destaque`` marcando a linha em
        que aquilo aconteceu.
        """
        resumo = self._historico.sessao(sessao_id)
        if resumo is None:
            return False
        self._abrir_sessao(resumo, destaque=destaque)
        return True

    def _abrir_sessao(self, resumo: ResumoDeSessao, *, destaque: str = "") -> None:
        self._sessao_aberta = resumo.id
        self._destaque = destaque
        self._botao_apagar.setEnabled(True)
        partes = [p for p in (resumo.jogo, resumo.modo, resumo.nivel) if p]
        self._titulo_sessao = (
            f"{_data_amigavel(resumo.iniciada_em)}   ·   {'   ·   '.join(partes)}"
        )
        self._falas_abertas = self._historico.falas_de(resumo.id)
        self._busca.clear()  # trocar de sessão zera o filtro da anterior
        self._pintar_falas()

    def _filtrar(self) -> None:
        self._pintar_falas()

    def _pintar_falas(self) -> None:
        """Desenha a transcrição aberta, respeitando o filtro de busca."""
        janela, t = self._janela, self._janela.tema
        self._limpar_falas()

        alvo = " ".join(self._busca.text().split()).lower()
        visiveis = [
            f for f in self._falas_abertas
            if not alvo or alvo in f.texto.lower() or alvo in f.autor.lower()
        ]
        if alvo:
            self._cabecalho.setText(
                f"{self._titulo_sessao}   ·   "
                f"{len(visiveis)} de {len(self._falas_abertas)} falas"
            )
        else:
            self._cabecalho.setText(self._titulo_sessao)

        cores = {"usuario": t.info, "assistente": t.primary, "vocab": t.accent}
        marcado: QWidget | None = None
        alvo_destaque = self._destaque.lower()
        for fala in visiveis:
            bloco = QLabel(
                f"{fala.autor or fala.tag.upper()} — {fala.texto}"
                if fala.autor or fala.tag
                else fala.texto
            )
            bloco.setWordWrap(True)
            bloco.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            bloco.setFont(janela.fonte("corpo"))
            cor = cores.get(fala.tag, t.secondary)

            # A linha que trouxe o jogador até aqui: a anotação de vocabulário
            # daquela palavra. Só a PRIMEIRA — uma palavra reencontrada tem
            # várias, e a que interessa é a que a ensinou.
            e_o_destaque = (
                marcado is None
                and alvo_destaque != ""
                and fala.tag == "vocab"
                and alvo_destaque in fala.texto.lower()
            )
            if e_o_destaque:
                marcado = bloco
                fundo = design.misturar(t.screen, t.accent, 0.20)
                bloco.setStyleSheet(
                    f"color: {design.garantir_contraste(cor, fundo)};"
                    f" background: {fundo}; border-radius: 4px; padding: 6px 9px;"
                )
            else:
                bloco.setStyleSheet(
                    f"color: {design.garantir_contraste(cor, t.screen)};"
                    " background: transparent;"
                )
            self._pilha_falas.insertWidget(self._pilha_falas.count() - 1, bloco)

        if alvo and not visiveis:
            vazio = QLabel("Nenhuma fala desta conversa contém esse texto.")
            vazio.setWordWrap(True)
            vazio.setFont(janela.fonte("corpo"))
            vazio.setStyleSheet(
                f"color: {design.garantir_contraste(t.text_muted, t.screen)};"
                " background: transparent;"
            )
            self._pilha_falas.insertWidget(self._pilha_falas.count() - 1, vazio)

        self._rolagem_falas.verticalScrollBar().setValue(0)
        if marcado is not None:
            # Depois que o layout existir: antes disso o widget não tem
            # posição, e rolar até ele não faz nada. A margem generosa deixa a
            # linha marcada com conversa em volta — que é o motivo INTEIRO de
            # abrir a conversa em vez de só mostrar a palavra.
            QTimer.singleShot(
                0, lambda w=marcado: self._rolagem_falas.ensureWidgetVisible(w, 0, 140)
            )

    def _apagar_sessao(self) -> None:
        if self._sessao_aberta is None:
            return
        caixa = Caixa(
            self._janela,
            "Apagar sessão",
            "Apagar esta sessão e toda a transcrição dela? "
            "Esta ação não pode ser desfeita.",
            glifo="◇",
            papel_glifo="alert",
            confirmar="Apagar",
            cancelar="Cancelar",
            perigo=True,
        )
        if caixa.exec() != QDialog.DialogCode.Accepted:
            return
        self._historico.remover_sessao(self._sessao_aberta)
        self._sessao_aberta = None
        self._recarregar()

    # ------------------------------------------------------------- Moldura
    def resizeEvent(self, evento: Any) -> None:
        super().resizeEvent(evento)
        if hasattr(self, "_grips"):
            self._grips.reposicionar()

    def showEvent(self, evento: Any) -> None:
        super().showEvent(evento)
        aplicar_cantos_do_sistema(self)

    def paintEvent(self, _evento: Any) -> None:
        t = self._janela.tema
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        caminho = caminho_forma(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
            self._janela.atmosfera.forma,
            design.RAIO,
        )
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(QColor(t.screen))
        pintor.drawPath(caminho)
        caneta = QPen(QColor(t.border_forte))
        caneta.setWidthF(1.0)
        pintor.setPen(caneta)
        pintor.setBrush(Qt.BrushStyle.NoBrush)
        pintor.drawPath(caminho)
        pintor.end()
