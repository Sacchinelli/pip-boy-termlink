"""Primeira execução: pedir a chave com hospitalidade, não com um erro.

Antes, abrir o programa sem ``.env`` terminava numa caixa cinza do sistema
explicando variáveis de ambiente — para alguém que talvez tenha acabado de
baixar um ``.exe`` e nunca tenha ouvido falar de ``.env``. Este cartão faz o
que aquele erro mandava o usuário fazer sozinho: explica onde a chave nasce,
recebe a colagem e grava no lugar certo (``config.salvar_chave``).

A janela principal ainda não existe aqui, então o cartão resolve o próprio
tema — o do último jogo usado, como a tela de abertura.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from .. import design
from ..config import ConfigurationError, Preferences, salvar_chave
from ..themes import GameTheme, paleta_de, theme_for
from .atmosfera import atmosfera_de
from .componentes import Botao, caminho_forma

LARGURA = 560
ENDERECO_CHAVE = "https://aistudio.google.com/apikey"


class _ProvedorMinimo:
    """O contrato de tema dos componentes, sem precisar da janela principal."""

    def __init__(self) -> None:
        self.tema: GameTheme = theme_for(Preferences.load().jogo)
        self.atmosfera = atmosfera_de(self.tema.name)
        self._instaladas = set(QFontDatabase.families())

    def fonte(self, papel: str, *, ui: bool = True) -> QFont:
        tipo = design.TIPO[papel]
        candidatas = self.tema.ui_font_candidates if ui else self.tema.font_candidates
        familia = next((f for f in candidatas if f in self._instaladas), candidatas[-1])
        fonte = QFont(familia, tipo.tamanho)
        fonte.setBold(tipo.peso == "bold")
        fonte.setItalic(tipo.estilo == "italic")
        return fonte

    def paleta(self) -> dict[str, str]:
        return paleta_de(self.tema)


class JanelaBoasVindas(QDialog):
    """Cartão modal que recebe a chave e a grava. ``exec()`` == Accepted → salvou."""

    def __init__(self, aviso: str = "") -> None:
        super().__init__()
        provedor = _ProvedorMinimo()
        tema = provedor.tema
        self._forma = provedor.atmosfera.forma
        self._fundo = tema.surface
        self._borda = tema.border_forte

        self.setWindowTitle("Pip-Boy TermLink — primeira execução")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(LARGURA)

        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(30, 26, 30, 22)
        coluna.setSpacing(10)

        def cor(papel: str) -> str:
            return design.garantir_contraste(getattr(tema, papel), self._fundo)

        titulo = QLabel("QUASE PRONTO")
        titulo.setFont(provedor.fonte("display", ui=False))
        titulo.setStyleSheet(f"color: {cor('primary')}; background: transparent;")
        coluna.addWidget(titulo)

        corpo = QLabel(
            "O tutor fala com você pela Live API do Gemini, e para isso precisa "
            "de uma chave — gratuita, criada em um minuto:"
        )
        corpo.setFont(provedor.fonte("corpo"))
        corpo.setWordWrap(True)
        corpo.setStyleSheet(f"color: {cor('secondary')}; background: transparent;")
        coluna.addWidget(corpo)

        endereco = QLabel(
            f'<a href="{ENDERECO_CHAVE}" style="color: {cor("accent")};">{ENDERECO_CHAVE}</a>'
        )
        endereco.setFont(provedor.fonte("corpo"))
        endereco.setOpenExternalLinks(True)
        endereco.setStyleSheet("background: transparent;")
        coluna.addWidget(endereco)
        coluna.addSpacing(8)

        self._campo = QLineEdit()
        self._campo.setPlaceholderText("Cole a chave aqui (começa com AIza…)")
        self._campo.setFont(provedor.fonte("corpo"))
        self._campo.setAccessibleName("Chave da API do Gemini")
        raio = {"chanfrada": 3, "reta": 2}.get(self._forma, 8)
        self._campo.setStyleSheet(
            f"QLineEdit {{ background: {tema.surface_alta}; color: {tema.primary};"
            f" border: 1px solid {tema.border}; border-radius: {raio}px;"
            f" padding: 10px 12px; selection-background-color: {tema.selection}; }}"
            f"QLineEdit:focus {{ border-color: {tema.border_forte}; }}"
        )
        self._campo.returnPressed.connect(self._salvar)
        coluna.addWidget(self._campo)

        self._erro = QLabel(aviso)
        self._erro.setFont(provedor.fonte("legenda"))
        self._erro.setWordWrap(True)
        self._erro.setStyleSheet(f"color: {cor('alert')}; background: transparent;")
        self._erro.setVisible(bool(aviso))
        coluna.addWidget(self._erro)

        detalhe = QLabel(
            "A chave fica só no seu computador, num arquivo .env na sua pasta "
            "de dados — nunca aparece inteira no registro do programa."
        )
        detalhe.setFont(provedor.fonte("legenda"))
        detalhe.setWordWrap(True)
        detalhe.setStyleSheet(f"color: {cor('text_muted')}; background: transparent;")
        coluna.addWidget(detalhe)
        coluna.addSpacing(10)

        acoes = QHBoxLayout()
        acoes.setSpacing(8)
        acoes.addStretch(1)
        sair = Botao("Sair", variante="sutil", paleta=provedor.paleta, forma=self._forma)
        sair.setFont(provedor.fonte("corpo_forte"))
        sair.clicked.connect(self.reject)
        acoes.addWidget(sair)
        salvar = Botao(
            "Salvar e começar", variante="primario", paleta=provedor.paleta, forma=self._forma
        )
        salvar.setFont(provedor.fonte("corpo_forte"))
        salvar.clicked.connect(self._salvar)
        acoes.addWidget(salvar)
        coluna.addLayout(acoes)
        self._campo.setFocus()

    def _salvar(self) -> None:
        try:
            salvar_chave(self._campo.text())
        except ConfigurationError as erro:
            self._erro.setText(str(erro))
            self._erro.show()
            self._campo.setFocus()
            return
        self.accept()

    def paintEvent(self, _evento: object) -> None:
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


def pedir_chave(aviso: str = "") -> bool:
    """Abre o cartão e devolve se uma chave foi salva."""
    return JanelaBoasVindas(aviso).exec() == QDialog.DialogCode.Accepted
