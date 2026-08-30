"""Caixas de confirmação e aviso desenhadas no tema.

Um ``QMessageBox`` do sistema é a única superfície do programa que nunca
recebeu o tratamento do resto: chega como um retângulo cinza do Windows, com
o ícone circular azul que o sistema desenha SEMPRE colorido e com fonte
própria — o mesmo motivo pelo qual este projeto já proibia emoji nos rótulos —
e, pior, com os botões rotulados **em inglês** ("Yes" / "No") dentro de um
programa inteiramente em português. Apagar uma palavra do caderno era a hora
em que a ilusão do aparelho caía por completo.

Esta caixa usa as mesmas peças do resto: a paleta do jogo, a fonte do tema no
título, o vocabulário geométrico da atmosfera (canto arredondado, chanfrado ou
reto) e os botões pintados de ``componentes``. O ícone é um glifo do bloco
*Geometric Shapes*, que toda fonte de texto do Windows possui e que aceita a
cor do tema.

O provedor de tema é o mesmo objeto que o resto da interface já consome pelo
mesmo contrato — ``tema``, ``atmosfera``, ``fonte()`` e ``paleta()`` —, então a
caixa serve tanto à janela principal quanto ao caderno.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from .. import design
from .componentes import Botao, caminho_forma

# Glifos do bloco Geometric Shapes: existem em Consolas, Georgia, Segoe UI e
# Bahnschrift — as famílias dos dez temas — e assumem a cor que mandarmos.
GLIFO_PERGUNTA = "◇"
GLIFO_AVISO = "◆"
GLIFO_ERRO = "◈"

LARGURA_MAX = 460


class Caixa(QDialog):
    """Diálogo modal temático com uma pergunta ou um aviso."""

    def __init__(
        self,
        janela: Any,
        titulo: str,
        mensagem: str,
        *,
        glifo: str,
        papel_glifo: str,
        confirmar: str | None,
        cancelar: str,
        perigo: bool,
        campos: tuple[tuple[str, str, str], ...] = (),
    ) -> None:
        super().__init__(janela)
        self._janela = janela
        tema = janela.tema
        self._forma = janela.atmosfera.forma
        self._fundo = tema.surface
        self._borda = tema.border_forte

        self.setWindowTitle(titulo)
        self.setModal(True)
        # Sem moldura do sistema: uma barra de título cinza do Windows em volta
        # de uma caixa de fósforo verde denuncia a costura tanto quanto o
        # diálogo inteiro denunciava antes.
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(26, 22, 26, 20)
        raiz.setSpacing(14)

        topo = QHBoxLayout()
        topo.setSpacing(14)
        marca = QLabel(glifo)
        marca.setFont(janela.fonte("display", ui=False))
        marca.setStyleSheet(
            f"color: {design.garantir_contraste(getattr(tema, papel_glifo), self._fundo)};"
            " background: transparent;"
        )
        marca.setAlignment(Qt.AlignmentFlag.AlignTop)
        topo.addWidget(marca)

        coluna = QVBoxLayout()
        coluna.setSpacing(6)
        rotulo_titulo = QLabel(titulo)
        rotulo_titulo.setFont(janela.fonte("titulo", ui=False))
        rotulo_titulo.setStyleSheet(
            f"color: {design.garantir_contraste(tema.primary, self._fundo)};"
            " background: transparent;"
        )
        rotulo_titulo.setWordWrap(True)
        coluna.addWidget(rotulo_titulo)

        corpo = QLabel(mensagem)
        corpo.setFont(janela.fonte("corpo"))
        corpo.setWordWrap(True)
        corpo.setStyleSheet(
            f"color: {design.garantir_contraste(tema.secondary, self._fundo)};"
            " background: transparent;"
        )
        corpo.setMaximumWidth(LARGURA_MAX)
        coluna.addWidget(corpo)
        topo.addLayout(coluna, 1)
        raiz.addLayout(topo)

        # Campos editáveis, quando a caixa PERGUNTA algo em vez de só avisar.
        # Ficam aqui, e não numa segunda classe, para herdar de graça o que a
        # caixa já resolveu: a moldura desenhada, o fundo do tema, a fonte do
        # jogo e os botões — que era exatamente o que fazia um QInputDialog do
        # sistema destoar de tudo.
        self._campos: dict[str, QLineEdit] = {}
        for chave, rotulo, valor in campos:
            legenda = QLabel(rotulo)
            legenda.setFont(janela.fonte("micro"))
            legenda.setStyleSheet(
                f"color: {design.garantir_contraste(tema.secondary, self._fundo)};"
                " background: transparent;"
            )
            raiz.addWidget(legenda)
            entrada = QLineEdit(valor)
            entrada.setFont(janela.fonte("corpo"))
            entrada.setMinimumWidth(LARGURA_MAX)
            entrada.setStyleSheet(
                f"QLineEdit {{ background: {tema.surface_alta}; color: {tema.primary};"
                f" border: 1px solid {tema.border}; border-radius: {design.RAIO_PEQUENO}px;"
                " padding: 7px 10px; }"
                f"QLineEdit:focus {{ border-color: {tema.border_forte}; }}"
            )
            raiz.addWidget(entrada)
            self._campos[chave] = entrada

        acoes = QHBoxLayout()
        acoes.setSpacing(8)
        acoes.addStretch(1)

        botao_cancelar = Botao(
            cancelar, variante="sutil", paleta=janela.paleta, forma=self._forma
        )
        botao_cancelar.setFont(janela.fonte("corpo_forte"))
        botao_cancelar.clicked.connect(self.reject)
        acoes.addWidget(botao_cancelar)

        if confirmar is not None:
            botao_confirmar = Botao(
                confirmar,
                variante="perigo" if perigo else "primario",
                paleta=janela.paleta,
                forma=self._forma,
            )
            botao_confirmar.setFont(janela.fonte("corpo_forte"))
            botao_confirmar.clicked.connect(self.accept)
            acoes.addWidget(botao_confirmar)
            if self._campos:
                # Com campos a caixa não destrói nada — ela corrige. Aqui o
                # Enter reflexo é a resposta desejada, e o foco nasce no
                # primeiro campo para dar para digitar sem pegar no mouse.
                #
                # O Enter é ligado à mão porque ``Botao`` herda de
                # ``QAbstractButton``, e não de ``QPushButton``: não existe
                # botão "padrão" para o diálogo acionar sozinho.
                for campo in self._campos.values():
                    campo.returnPressed.connect(self.accept)
                next(iter(self._campos.values())).setFocus()
            else:
                # O foco nasce em CANCELAR. Numa caixa cuja ação apaga dados,
                # um Enter reflexo não pode ser a resposta afirmativa.
                botao_cancelar.setFocus()
        else:
            botao_cancelar.setFocus()

        raiz.addLayout(acoes)
        self.setMaximumWidth(LARGURA_MAX + 80)

    def valores(self) -> dict[str, str]:
        """O que está escrito nos campos, sem espaço sobrando."""
        return {chave: campo.text().strip() for chave, campo in self._campos.items()}

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


def confirmar_remocao(janela: Any, termo: str) -> bool:
    """Pergunta se um termo pode ser apagado. Devolve a resposta."""
    caixa = Caixa(
        janela,
        "Remover do caderno",
        f"Apagar “{termo}” e todo o histórico de revisão dessa palavra? "
        "Esta ação não pode ser desfeita.",
        glifo=GLIFO_PERGUNTA,
        papel_glifo="alert",
        confirmar="Remover",
        cancelar="Cancelar",
        perigo=True,
    )
    return caixa.exec() == QDialog.DialogCode.Accepted


def avisar(janela: Any, titulo: str, mensagem: str, *, erro: bool = False) -> None:
    """Aviso de uma via, com um único botão de saída."""
    Caixa(
        janela,
        titulo,
        mensagem,
        glifo=GLIFO_ERRO if erro else GLIFO_AVISO,
        papel_glifo="alert" if erro else "accent",
        confirmar=None,
        cancelar="Entendi",
        perigo=False,
    ).exec()


def pedir_correcao(
    janela: Any, *, termo: str, traducao: str, exemplo: str
) -> dict[str, str] | None:
    """Abre a caixa que corrige o texto de uma palavra. ``None`` se desistir.

    Corrigir e apagar são vizinhos no cartão e fazem coisas opostas: por isso
    esta caixa diz, no corpo, o que ela NÃO faz. Quem chega aqui vindo do "×"
    precisa saber que o histórico de revisão sobrevive — é justamente a dúvida
    que fazia a pessoa não mexer em nada e conviver com a tradução errada.
    """
    caixa = Caixa(
        janela,
        "Corrigir palavra",
        "O agendamento da revisão, os acertos e os erros ficam como estão — "
        "só o texto muda.",
        glifo=GLIFO_PERGUNTA,
        papel_glifo="accent",
        confirmar="Salvar",
        cancelar="Cancelar",
        perigo=False,
        campos=(
            ("termo", "Termo em inglês", termo),
            ("traducao", "Tradução", traducao),
            ("exemplo", "Exemplo (opcional)", exemplo),
        ),
    )
    if caixa.exec() != QDialog.DialogCode.Accepted:
        return None
    return caixa.valores()
