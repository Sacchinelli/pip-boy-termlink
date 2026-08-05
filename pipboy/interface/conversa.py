"""A conversa: o palco onde o produto acontece.

Substituiu o console de registro. As diferenças que importam:

* **Fala é bloco, não linha.** Cada resposta vira uma bolha de largura própria,
  com o texto quebrado dentro dela.
* **Autor por posição.** O jogador à direita, o assistente à esquerda — a
  convenção que todo mundo já sabe ler sem legenda.
* **Agrupamento.** Falas seguidas do mesmo interlocutor compartilham um só
  cabeçalho com nome e hora.
* **Sistema e vocabulário não são conversa.** Viram anotações centradas e
  discretas, fora do fluxo do diálogo.

O acréscimo é incremental: uma fala nova cria um widget e o insere. Recompor a
lista inteira a cada mensagem faria a janela piscar a cada frase do assistente.
"""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import design
from ..events import Tag
from .componentes import Bolha, LinhaFala

# Teto de falas guardadas. Uma sessão de horas não precisa carregar o começo
# da noite, e cada bolha é um widget de verdade.
LIMITE_FALAS = 400


class Conversa(QScrollArea):
    def __init__(self, janela: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._janela = janela
        self._autor_anterior: str | None = None
        self._itens: list[QWidget] = []
        # As falas ficam guardadas como dados, não só como widgets: trocar de
        # jogo no meio de uma sessão repinta a conversa em vez de apagá-la.
        self._mensagens: list[tuple[str, Tag, str]] = []

        self.setObjectName("conversa")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._interno = QWidget(objectName="fundoConversa")
        self._fluxo = QVBoxLayout(self._interno)
        self._fluxo.setContentsMargins(24, 20, 24, 20)
        # Espaçamento MÍNIMO no fluxo: o respiro entre turnos vem da margem
        # superior de quem tem cabeçalho (ver LinhaFala). Uniforme, o layout
        # afastava duas falas seguidas do assistente tanto quanto afastava o
        # assistente do jogador, e a conversa perdia o agrupamento que o
        # cabeçalho compartilhado tinha acabado de estabelecer.
        self._fluxo.setSpacing(3)
        # A mola fica ANTES das falas, não depois: uma conversa curta encosta
        # no campo de digitação em vez de flutuar no topo de um painel vazio
        # pela metade. É como toda conversa se comporta, e é o que faz o
        # último turno — o único que importa — cair onde o olho já está.
        self._fluxo.addStretch(1)
        self.setWidget(self._interno)

    # ------------------------------------------------------------- inserção
    def adicionar(self, texto: str, tag: Tag, autor: str = "") -> None:
        self._mensagens.append((texto, tag, autor))
        if len(self._mensagens) > LIMITE_FALAS:
            del self._mensagens[0]
        no_fim = self._no_fim()
        self._inserir(texto, tag, autor)
        self._podar()

        if no_fim:
            # Só depois de o layout existir: rolar antes disso não faz nada.
            QTimer.singleShot(0, self.ir_para_o_fim)

    def _inserir(self, texto: str, tag: Tag, autor: str) -> None:
        tema, atmosfera = self._janela.tema, self._janela.atmosfera
        if tag in (Tag.SISTEMA, Tag.VOCAB):
            widget = self._nota(texto, tag, tema, atmosfera)
            self._autor_anterior = None
        else:
            widget = self._fala(texto, tag, autor, tema, atmosfera)
            self._autor_anterior = autor
        # Depois da mola, que ocupa o índice 0 e empurra tudo para baixo.
        self._fluxo.addWidget(widget)
        self._itens.append(widget)

    def _podar(self) -> None:
        while len(self._itens) > LIMITE_FALAS:
            velho = self._itens.pop(0)
            self._fluxo.removeWidget(velho)
            # setParent(None) antes da remoção diferida: sobre fundo
            # translúcido, um widget que continua vivo aparece como fantasma.
            velho.setParent(None)
            velho.deleteLater()

    def limpar(self, *, esquecer: bool = True) -> None:
        if esquecer:
            self._mensagens.clear()
        for widget in self._itens:
            self._fluxo.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()
        self._itens.clear()
        self._autor_anterior = None
        self._repintar_pilha()

    # ---------------------------------------------------------------- peças
    def _nota(self, texto: str, tag: Tag, tema: Any, atmosfera: Any) -> QWidget:
        vocab = tag is Tag.VOCAB
        rotulo = QLabel(texto)
        rotulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rotulo.setWordWrap(True)

        if not vocab:
            rotulo.setFont(self._janela.fonte("micro"))
            rotulo.setStyleSheet(f"color: {tema.text_muted}; background: transparent;")
            rotulo.setContentsMargins(0, 14, 0, 10)
            return rotulo

        raio = 2 if atmosfera.forma != "arredondada" else design.RAIO_PEQUENO
        fundo = design.misturar(tema.surface, tema.info, 0.14)
        rotulo.setFont(self._janela.fonte("vocab", ui=False))
        rotulo.setStyleSheet(
            f"color: {tema.info_text}; background: {fundo};"
            f" border-radius: {raio}px; padding: 5px 12px;"
        )
        rotulo.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)

        embrulho = QWidget()
        caixa = QHBoxLayout(embrulho)
        # A anotação pertence à fala que acabou de acontecer: cola nela por
        # cima e se separa do próximo turno por baixo.
        caixa.setContentsMargins(0, 2, 0, 8)
        caixa.addStretch(1)
        caixa.addWidget(rotulo)
        caixa.addStretch(1)
        return embrulho

    def _fala(
        self, texto: str, tag: Tag, autor: str, tema: Any, atmosfera: Any
    ) -> QWidget:
        do_jogador = tag is Tag.USUARIO
        if tag is Tag.ERRO:
            fundo = design.misturar(tema.surface, tema.alert, 0.20)
            cor = design.garantir_contraste(tema.alert, fundo)
            contorno = design.misturar(fundo, tema.alert, 0.45)
        elif do_jogador:
            fundo = design.misturar(tema.surface, tema.accent, 0.22)
            cor = design.garantir_contraste(tema.primary, fundo)
            contorno = design.misturar(fundo, tema.accent, 0.35)
        else:
            fundo = tema.surface_alta
            cor = design.garantir_contraste(tema.primary, fundo)
            contorno = tema.border

        bolha = Bolha(
            texto,
            fundo=fundo,
            cor_texto=cor,
            # Assistente na fonte do tema, jogador na neutra: a diferença
            # entre "o assistente falou" e "eu digitei".
            fonte=self._janela.fonte("corpo", ui=do_jogador),
            largura_max=design.BOLHA_LARGURA_MAX,
            forma=atmosfera.forma,
            brilho_texto=0.0 if do_jogador else atmosfera.brilho_texto,
            contorno=contorno,
            acento=tema.accent,
        )
        # O separador só existe se houver os dois lados. A sessão publica TODOS
        # os erros sem autor (é o programa falando, não o personagem), e o
        # formato fixo produzia um cabeçalho começando por um ponto órfão:
        # "  ·  17:43". A hora sozinha basta — e uma falha merece carimbo de
        # hora tanto quanto uma fala.
        mesmo_autor = bool(autor) and autor == self._autor_anterior
        hora = time.strftime("%H:%M")
        cabecalho = None if mesmo_autor else (f"{autor}  ·  {hora}" if autor else hora)
        linha = LinhaFala(
            bolha,
            cabecalho=cabecalho,
            cor_cabecalho=tema.text_muted,
            fonte_cabecalho=self._janela.fonte("micro"),
            direita=do_jogador,
        )
        bolha.animar_entrada()
        return linha

    # -------------------------------------------------------------- rolagem
    def _no_fim(self) -> bool:
        barra = self.verticalScrollBar()
        return barra.value() >= barra.maximum() - 4

    def ir_para_o_fim(self) -> None:
        barra = self.verticalScrollBar()
        barra.setValue(barra.maximum())

    # ----------------------------------------------------------------- tema
    def repintar(self) -> None:
        """Reconstrói as falas com a paleta e a forma do tema atual.

        As bolhas desenham a si mesmas com cores capturadas na construção, e
        não há como reconfigurá-las em massa sem refazer o cálculo de
        contraste de cada uma. Reconstruir a partir dos dados guardados é
        honesto e imperceptível: são dezenas de widgets, não milhares.
        """
        no_fim = self._no_fim()
        guardadas = list(self._mensagens)
        self.limpar(esquecer=False)
        for texto, tag, autor in guardadas:
            self._inserir(texto, tag, autor)
        self._mensagens = guardadas
        self._repintar_pilha()
        if no_fim:
            QTimer.singleShot(0, self.ir_para_o_fim)

    def _repintar_pilha(self) -> None:
        conteudo = self.widget()
        if conteudo is not None:
            conteudo.update()
        self.viewport().update()
        self.update()
