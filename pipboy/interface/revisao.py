"""Cartões de revisão offline, no tema do jogo.

A mecânica é a do Anki reduzida ao essencial de uma pausa entre partidas:
o termo aparece, o jogador tenta lembrar, revela a resposta e responde com
honestidade — acertei, foi difícil ou errei. Cada resposta alimenta a mesma
repetição espaçada do modo Quiz por voz, mas aqui **sem sessão, sem rede e
sem custo**.

Teclado em primeiro lugar: Espaço revela, A acerta, D marca difícil, E erra.
Quem está com a outra mão no controle não quer mirar em botão pequeno com o
mouse.

**Dois jeitos de revisar** (ver ``pipboy/revisao.py``). *Lembrar* é o cartão
de sempre: o termo em inglês, a tradução de cabeça. *Escrever* é o cartão ao
contrário: a tradução e a frase do jogo com um buraco, e o jogador DIGITA a
palavra — é o que prepara para dizê-la. Errar não encerra o cartão: a tela
pinta as letras que já estão no lugar, como o terminal de senhas do Fallout
diz a "semelhança" de uma tentativa, e desenha a pista — a primeira letra e
o tamanho. Três tentativas; a nota sai sozinha do que aconteceu (de
primeira, acerto; depois da pista, ou por uma letra, difícil; nunca, erro).
A escolha do jeito fica guardada nas preferências.

Cada gesto tem resposta na tela — e no ouvido, na voz do jogo (ver
``_registrar``) —, e cada resposta diz alguma coisa:

* **A barra da rodada** é uma fileira de segmentos, um por cartão, e cada
  resposta pinta o seu na cor da nota. No fim, a própria barra é o resumo —
  dá para ver ONDE os erros caíram, não só quantos foram.
* **O recado** diz quando a palavra volta: "em 3 dias", "na próxima rodada".
  A rodada sempre soube isso (``responder`` devolve os dias) e a tela jogava
  fora; é a informação que faz a repetição espaçada deixar de ser mágica.
* **O verso tem lugar reservado.** Revelar não empurra os botões: o polegar
  que apertou Espaço aperta A no mesmo lugar. Errar uma tentativa também
  não: o retorno e a pista já tinham o lugar deles.
* **O cartão respondido sai deslizando** enquanto o próximo entra, e a borda
  acende na cor do resultado. Com a atmosfera desligada, tudo acontece num
  quadro — o recado e a barra continuam dizendo o que houve.

E a rodada acontece no lugar do jogo em que já se treina: o Teste G.O.A.T. do
abrigo, a graça onde se memorizam magias, a meditação do bruxo, o estande de
tiro. O nome e o objeto dele vão no alto, a moldura do jogo se monta em volta
do cartão quando a janela abre, e o modo de escrever fala na voz do jogo — o
terminal pede a senha e responde com a semelhança, o protocolo de invasão
recusa a sequência, o rádio do esquadrão diz "negativo".
"""

from __future__ import annotations

import html
from typing import Any

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QKeyEvent,
    QKeySequence,
    QPainter,
    QPen,
    QShortcut,
)
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import design
from ..revisao import (
    ACERTO,
    DIFICIL,
    ERRO,
    TENTATIVAS,
    Conferencia,
    RodadaDeRevisao,
    conferir,
    lacuna,
    normalizar,
    nota_da_escrita,
    pista,
    trechos,
)
from ..texto import conforme, contagem
from ..vocabulary import Entrada, VocabularyStore
from .atmosfera import ATENUACAO_NO_FUNDO_NU, Cenario, so_o_cursor
from .componentes import Botao, RotuloElidido, acender_borda, caminho_forma
from .cursor import CursorVivo
from .icones import IconeDoJogo
from .movimento import ImagemQueSai, Transicao, animar_entrada
from .ornamentos import FAIXA_MOLDURA, MolduraDoPainel

LARGURA = 600

MODO_LEMBRAR = "lembrar"
MODO_ESCREVER = "escrever"
MODOS = (MODO_LEMBRAR, MODO_ESCREVER)

# A voz do jogo no modo de escrever: o convite do campo vazio e a recusa de
# uma tentativa errada, com quantas letras dela já estão no lugar. O terminal
# pede a senha e responde com a semelhança, como o terminal de senhas dos
# abrigos; a Night City recusa a sequência e conta o que entrou no buffer,
# como o protocolo de invasão; o esquadrão diz "negativo". Frases escritas
# aqui, no tom de cada um — não falas tiradas dos jogos.
VOZES_DA_ESCRITA: dict[str, tuple[str, str]] = {
    "Fallout": ("> digite a senha_", "Entrada negada. Semelhança={n}/{total}."),
    "Elden Ring": ("Gravar a palavra…", "Ainda não, Maculado — {n} de {total} letras no lugar."),
    "Skyrim": ("Dizer a palavra…", "A muralha não responde — {n} de {total} letras no lugar."),
    "The Witcher 3": ("Anotar a palavra…", "Pista falsa — {n} de {total} letras no lugar."),
    "Red Dead": ("Escrever a palavra…", "Tiro n'água, parceiro — {n} de {total} letras no lugar."),
    "GTA": ("Digitar a palavra…", "Deu ruim — {n} de {total} letras no lugar."),
    "Cyberpunk 2077": ("// inserir sequência", "Sequência recusada — {n}/{total} no buffer."),
    "RPG / Aventura (geral)": ("Escrever a palavra…", "Falhou no teste — {n} de {total} letras no lugar."),
    "FPS / Multiplayer": ("[ESQUADRÃO] palavra…", "Negativo — {n} de {total} letras no lugar."),
}
VOZ_PADRAO = ("Escreva em inglês…", "Ainda não — {n} de {total} letras no lugar.")

# O que se diz depois da nota, no modo de escrever.
DESFECHOS = {
    ACERTO: "De primeira.",
    DIFICIL: "Com esforço — ela volta mais cedo.",
    ERRO: "A palavra era esta.",
}
DESFECHO_QUASE = "Quase — confira a grafia."


def voz_da_escrita(jogo: str) -> tuple[str, str]:
    """O convite e a recusa do modo de escrever na voz do jogo."""
    return VOZES_DA_ESCRITA.get(jogo, VOZ_PADRAO)


def quando_volta(dias: int) -> str:
    """Os dias até a próxima revisão, ditos como se diz."""
    if dias <= 0:
        return "na próxima rodada"
    if dias == 1:
        return "amanhã"
    return f"em {dias} dias"


def ler_rodada(total: int, resultados: list[str]) -> str:
    """A barra da rodada em palavras, para o leitor de tela."""
    if total <= 0:
        return "Nenhum cartão nesta rodada."
    feitos = len(resultados)
    contas = (
        f"{contagem(resultados.count(ACERTO), 'acerto', 'acertos')}, "
        f"{contagem(resultados.count(DIFICIL), 'difícil', 'difíceis')}, "
        f"{contagem(resultados.count(ERRO), 'erro', 'erros')}"
    )
    return f"{feitos} de {total} cartões respondidos: {contas}."


def cor_da_nota(tema: Any, nota: str) -> str:
    """Acerto na cor do tema, difícil na cor de informação, erro no alerta."""
    return {ACERTO: tema.primary, DIFICIL: tema.info}.get(nota, tema.alert)


class BarraDaRodada(QWidget):
    """Um segmento por cartão, pintado na cor da nota quando respondido."""

    ALTURA = 4
    VAO = 3

    def __init__(self, janela: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._janela = janela
        self._total = 0
        self.resultados: list[str] = []
        self._chegada = Transicao(
            self, design.DURACAO_MEDIA, lambda _v: self.update(),
            reduzir=lambda: bool(janela.intensidade_atmosfera <= 0.0),
        )
        self._chegada.saltar(1.0)
        self.setFixedHeight(self.ALTURA)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def recomecar(self, total: int) -> None:
        self._total = total
        self.resultados = []
        self._chegada.saltar(1.0)
        self.setVisible(total > 0)
        self._anunciar()
        self.update()

    def _anunciar(self) -> None:
        # A barra é desenhada; sem isto, o leitor de tela não sabia dela.
        self.setAccessibleName("Rodada")
        self.setAccessibleDescription(ler_rodada(self._total, self.resultados))

    def registrar(self, nota: str) -> None:
        self.resultados.append(nota)
        self._anunciar()
        # O segmento recém-respondido acende a partir do cinza, em vez de
        # simplesmente já estar colorido quando o olho chega nele.
        self._chegada.saltar(0.0)
        self._chegada.ir(1.0)

    def paintEvent(self, _evento: Any) -> None:
        if self._total <= 0:
            return
        t = self._janela.tema
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        pintor.setPen(Qt.PenStyle.NoPen)
        largura = (self.width() - self.VAO * (self._total - 1)) / self._total
        raio = 1.0 if self._janela.atmosfera.forma != "arredondada" else self.ALTURA / 2
        respondidos = len(self.resultados)
        for indice in range(self._total):
            if indice < respondidos:
                cor = cor_da_nota(t, self.resultados[indice])
                if indice == respondidos - 1:
                    cor = design.misturar(t.border, cor, self._chegada.valor)
            elif indice == respondidos:
                # O da vez só se distingue do pendente; com mais que isto ele
                # se confundia com um acerto já pintado ao lado.
                cor = design.misturar(t.border, t.primary, 0.22)
            else:
                cor = t.border
            pintor.setBrush(QColor(cor))
            x = indice * (largura + self.VAO)
            pintor.drawRoundedRect(QRectF(x, 0.0, largura, float(self.ALTURA)), raio, raio)
        pintor.end()


class CampoDaPalavra(QLineEdit):
    """O campo do modo de escrever. O Enter é da rodada, não do campo.

    Ele confere a tentativa e, com a nota dada, passa ao próximo cartão — o
    mesmo dedo no mesmo lugar do começo ao fim da rodada. Um atalho de
    diálogo para o Enter brigaria com o campo por ele; aqui não há briga.
    """

    confirmado = Signal()

    def keyPressEvent(self, evento: QKeyEvent) -> None:
        if evento.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            evento.accept()
            self.confirmado.emit()
            return
        super().keyPressEvent(evento)


class VersoDaEscrita(QWidget):
    """O verso do modo de escrever: a frase com o buraco, o campo e o retorno.

    Tudo com lugar reservado desde o primeiro quadro — a frase em duas
    linhas, o retorno e a pista em uma cada —, para errar não empurrar os
    botões para longe do dedo.
    """

    def __init__(self, janela: Any, fundo: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._janela = janela
        self._fundo = fundo
        tema = janela.tema
        self._convite, self._recusa = voz_da_escrita(tema.name)

        pilha = QVBoxLayout(self)
        pilha.setContentsMargins(0, 0, 0, 0)
        pilha.setSpacing(6)

        def rotulo(nome_fonte: str, cor: str, *, ui: bool = True) -> QLabel:
            etiqueta = QLabel("")
            etiqueta.setFont(janela.fonte(nome_fonte, ui=ui))
            etiqueta.setStyleSheet(
                f"color: {design.garantir_contraste(cor, fundo)}; background: transparent;"
            )
            etiqueta.setWordWrap(True)
            return etiqueta

        self.frase = rotulo("vocab", tema.secondary, ui=False)
        self.frase.setTextFormat(Qt.TextFormat.RichText)
        self.campo = CampoDaPalavra()
        self.campo.setFont(janela.fonte("corpo"))
        self.campo.setPlaceholderText(self._convite)
        # O nome que o leitor de tela anuncia não muda com o jogo.
        self.campo.setAccessibleName("Escreva a palavra em inglês")
        raio = {"chanfrada": 3, "reta": 2}.get(janela.atmosfera.forma, design.RAIO_PEQUENO)
        self.campo.setStyleSheet(
            f"QLineEdit {{ background: {tema.surface_alta}; color: {tema.primary};"
            f" border: 1px solid {tema.border}; border-radius: {raio + 2}px;"
            f" padding: 8px 12px; selection-background-color: {tema.selection}; }}"
            f" QLineEdit:focus {{ border-color: {tema.border_forte}; }}"
            f" QLineEdit[readOnly=\"true\"] {{ color: {tema.text_muted}; }}"
        )
        self.retorno = rotulo("legenda", tema.text_muted)
        self.retorno.setTextFormat(Qt.TextFormat.RichText)
        # A pista é o que destrava a lembrança: na cor do tema, espaçada.
        self.pista = rotulo("corpo_forte", tema.primary)
        fonte_pista = self.pista.font()
        fonte_pista.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        self.pista.setFont(fonte_pista)
        for item in (self.frase, self.campo, self.retorno, self.pista):
            pilha.addWidget(item)
        pilha.addStretch(1)
        self.setMinimumHeight(
            2 * QFontMetrics(janela.fonte("vocab", ui=False)).lineSpacing()
            + self.campo.sizeHint().height()
            + QFontMetrics(janela.fonte("legenda")).lineSpacing()
            + QFontMetrics(janela.fonte("corpo_forte")).lineSpacing()
            + 3 * pilha.spacing()
        )

    # ------------------------------------------------------------ desenho
    def _cor(self, cor: str) -> str:
        return design.garantir_contraste(cor, self._fundo)

    def preparar(self, cartao: Entrada) -> None:
        """A frente do cartão: a frase com o buraco, o campo vazio."""
        frase = lacuna(cartao.exemplo, cartao.termo)
        self.frase.setText(html.escape(frase) if frase else "")
        self.frase.setVisible(bool(frase))
        self.campo.setReadOnly(False)
        self.campo.clear()
        self.campo.show()
        self.retorno.setText("")
        self.pista.setText("")

    def preparar_vazio(self) -> None:
        """O resumo da rodada: o lugar fica, o conteúdo sai."""
        for item in (self.frase, self.retorno, self.pista):
            item.setText("")
        self.campo.clear()
        self.campo.setReadOnly(True)
        self.campo.hide()

    def recusa(self, conferencia: Conferencia) -> str:
        return self._recusa.format(n=conferencia.letras_no_lugar, total=conferencia.letras)

    def mostrar_tentativa(self, conferencia: Conferencia, desenho: str, restantes: int) -> None:
        """Uma tentativa errada: as letras dela pintadas, a recusa e a pista.

        Cada letra da tentativa sai na cor do tema se está no lugar certo e no
        alerta se não está — o jogador vê ONDE errou, não só que errou.
        """
        tema = self._janela.tema
        certa, errada = self._cor(tema.primary), self._cor(tema.alert)
        letras = "".join(
            f'<span style="color:{certa if i < len(conferencia.no_lugar) and conferencia.no_lugar[i] else errada};">'
            f"{html.escape(letra) if letra != ' ' else '&nbsp;'}</span>"
            for i, letra in enumerate(conferencia.resposta)
        )
        sobra = f"{conforme(restantes, 'resta', 'restam')} {contagem(restantes, 'tentativa', 'tentativas')}"
        self.retorno.setText(
            f'<span style="font-weight:600; letter-spacing:1px;">{letras}</span>'
            f"&nbsp;&nbsp;·&nbsp;&nbsp;{html.escape(self.recusa(conferencia))}"
            f"&nbsp;&nbsp;·&nbsp;&nbsp;{sobra}"
        )
        self.pista.setText(desenho)
        self.campo.selectAll()

    def mostrar_desfecho(self, nota: str, conferencia: Conferencia | None, cartao: Entrada) -> None:
        """A nota dada: a palavra, o que houve e a frase inteira de volta."""
        tema = self._janela.tema
        cor = self._cor(cor_da_nota(tema, nota))
        quase = conferencia is not None and conferencia.quase and not conferencia.certa
        linha = DESFECHO_QUASE if quase else DESFECHOS[nota]
        self.retorno.setText(
            f'<span style="color:{cor}; font-weight:600;">{html.escape(cartao.termo)}</span>'
            f"&nbsp;&nbsp;·&nbsp;&nbsp;{html.escape(linha)}"
        )
        self.pista.setText("")
        if cartao.exemplo:
            # A frase volta inteira, com a palavra acesa onde estava o buraco
            # — do jeito que ela aparece na frase, flexionada ou não.
            partes, fim_anterior = [], 0
            for inicio, fim in trechos(cartao.exemplo, cartao.termo):
                partes.append(html.escape(cartao.exemplo[fim_anterior:inicio]))
                partes.append(
                    f'<span style="color:{cor}; font-weight:600;">'
                    f"{html.escape(cartao.exemplo[inicio:fim])}</span>"
                )
                fim_anterior = fim
            partes.append(html.escape(cartao.exemplo[fim_anterior:]))
            self.frase.setText("".join(partes))
            self.frase.show()
        self.campo.setReadOnly(True)


class JanelaRevisao(QDialog):
    """Uma rodada de cartões, modal sobre o caderno.

    ``janela`` é o provedor de tema (a janela principal); ``parent`` é quem
    abriu o diálogo — normalmente o próprio caderno.
    """

    DESLIZE_SAIDA = -36.0

    def __init__(
        self, janela: Any, store: VocabularyStore, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent if parent is not None else janela)
        self._janela = janela
        self._store = store
        self._rodada = RodadaDeRevisao(store)
        self._revelado = False
        # O modo de escrever: quantas tentativas erradas o cartão da vez já
        # teve, e se a nota dele já foi dada (esperando o Enter do próximo).
        self._erradas = 0
        self._conferido = False
        modo = janela.modo_de_revisao()
        self._modo = modo if modo in MODOS else MODO_LEMBRAR

        tema = janela.tema
        self._tema = tema
        self._forma = janela.atmosfera.forma
        self._fundo = tema.surface
        self._borda = tema.border_forte
        self._cor_lampejo = tema.primary

        self.setWindowTitle("Revisão")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(LARGURA)

        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(30, 24, 30, 22)
        coluna.setSpacing(10)

        def rotulo(nome_fonte: str, cor: str, *, ui: bool = True, wrap: bool = True) -> QLabel:
            etiqueta = QLabel("")
            etiqueta.setFont(janela.fonte(nome_fonte, ui=ui))
            etiqueta.setStyleSheet(
                f"color: {design.garantir_contraste(cor, self._fundo)};"
                " background: transparent;"
            )
            etiqueta.setWordWrap(wrap)
            return etiqueta

        # O cabeçalho: o objeto do jogo e o nome que ele dá a treinar, com a
        # função escrita ao lado, miúda — como no caderno e no histórico.
        cabecalho = QHBoxLayout()
        cabecalho.setSpacing(10)
        self.icone_titulo = IconeDoJogo(janela, "revisao")
        cabecalho.addWidget(self.icone_titulo, 0, Qt.AlignmentFlag.AlignBottom)
        self.titulo = rotulo("display", tema.primary, ui=False, wrap=False)
        self.titulo.setText(tema.nome_da_revisao)
        self.icone_titulo.definir_lado(QFontMetrics(self.titulo.font()).height())
        cabecalho.addWidget(self.titulo, 0, Qt.AlignmentFlag.AlignBottom)
        cabecalho.addStretch(1)
        self.subtitulo = rotulo("legenda", tema.text_muted, wrap=False)
        self.subtitulo.setText("revisão de vocabulário")
        cabecalho.addWidget(self.subtitulo, 0, Qt.AlignmentFlag.AlignBottom)
        coluna.addLayout(cabecalho)
        coluna.addSpacing(4)

        # Os dois jeitos de revisar, como os filtros do caderno: um chip
        # aceso por vez. Trocar no meio de um cartão recomeça ESTE cartão no
        # outro jeito, sem nota nenhuma.
        topo = QHBoxLayout()
        topo.setSpacing(6)
        self.chips_modo: dict[str, Botao] = {}
        for modo_chip, texto_chip, dica_chip in (
            (MODO_LEMBRAR, "Lembrar", "Ver o termo e lembrar a tradução"),
            (MODO_ESCREVER, "Escrever", "Ver a tradução e escrever o termo em inglês"),
        ):
            chip = Botao(texto_chip, variante="chip", paleta=janela.paleta, forma=self._forma)
            chip.setFont(janela.fonte("legenda"))
            chip.setCheckable(True)
            chip.setChecked(modo_chip == self._modo)
            chip.setToolTip(dica_chip)
            chip.clicked.connect(lambda _=False, m=modo_chip: self.definir_modo(m))
            topo.addWidget(chip)
            self.chips_modo[modo_chip] = chip
        topo.addSpacing(10)
        self._progresso = rotulo("micro", tema.text_muted, wrap=False)
        topo.addWidget(self._progresso)
        topo.addStretch(1)
        self._recado = RotuloElidido()
        self._recado.setFont(janela.fonte("micro"))
        self._recado.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        topo.addWidget(self._recado, 1)
        coluna.addLayout(topo)

        self._barra = BarraDaRodada(janela)
        coluna.addWidget(self._barra)
        coluna.addSpacing(8)

        # O cartão é um bloco próprio para poder ser fotografado inteiro na
        # troca: termo, metadados e verso saem juntos.
        self._cartao = QWidget()
        pilha = QVBoxLayout(self._cartao)
        # Com moldura, o cartão se afasta dela o bastante para os ornamentos
        # não passarem por cima do termo.
        folga = round(FAIXA_MOLDURA) + 2 if janela.atmosfera.moldura else 0
        pilha.setContentsMargins(folga, folga, folga, folga)
        pilha.setSpacing(10)
        self._termo = rotulo("display", tema.primary, ui=False)
        self._meta = rotulo("micro", tema.text_muted)
        pilha.addWidget(self._termo)
        pilha.addWidget(self._meta)
        pilha.addSpacing(4)

        verso = QWidget()
        pilha_verso = QVBoxLayout(verso)
        pilha_verso.setContentsMargins(0, 0, 0, 0)
        pilha_verso.setSpacing(6)
        self._dica = rotulo("legenda", tema.text_muted)
        self._dica.setText("Tente lembrar antes de revelar.")
        self._traducao = rotulo("corpo", tema.primary)
        self._exemplo = rotulo("vocab", tema.secondary)
        for item in (self._dica, self._traducao, self._exemplo):
            pilha_verso.addWidget(item)
        pilha_verso.addStretch(1)
        # Lugar reservado para uma tradução e duas linhas de exemplo: o caso
        # comum cabe sem mexer em nada. Um exemplo mais longo ainda cresce o
        # verso, e só aí os botões descem.
        verso.setMinimumHeight(
            QFontMetrics(janela.fonte("corpo")).lineSpacing()
            + 2 * QFontMetrics(janela.fonte("vocab", ui=False)).lineSpacing()
            + pilha_verso.spacing()
        )
        self._verso = verso
        pilha.addWidget(verso)
        self._escrita = VersoDaEscrita(janela, self._fundo)
        self._escrita.campo.confirmado.connect(self._enter_da_escrita)
        pilha.addWidget(self._escrita)
        coluna.addWidget(self._cartao)
        # A moldura do jogo em volta do cartão — por cima dele, montando ao
        # abrir; a foto do cartão que sai desliza por baixo dela.
        self.moldura_cartao = MolduraDoPainel(janela, self._cartao)
        coluna.addSpacing(10)

        acoes = QHBoxLayout()
        acoes.setSpacing(8)

        def botao(texto: str, variante: str, acao: Any) -> Botao:
            novo = Botao(texto, variante=variante, paleta=janela.paleta, forma=self._forma)
            novo.setFont(janela.fonte("corpo_forte"))
            novo.clicked.connect(acao)
            acoes.addWidget(novo)
            return novo

        self._botao_sair = botao("Encerrar", "sutil", self.reject)
        acoes.addStretch(1)
        self._botao_errei = botao("Errei  (E)", "perigo", lambda: self._responder(ERRO))
        self._botao_dificil = botao("Difícil  (D)", "sutil", lambda: self._responder(DIFICIL))
        self._botao_acertei = botao("Acertei  (A)", "primario", lambda: self._responder(ACERTO))
        self._botao_revelar = botao("Mostrar resposta  (Espaço)", "primario", self._revelar)
        self._botao_nao_sei = botao("Não sei", "sutil", self._nao_sei)
        self._botao_conferir = botao("Conferir  (Enter)", "primario", self._conferir)
        self._botao_proximo = botao("Próximo  (Enter)", "primario", self._proximo)
        self._botao_nova = botao("Nova rodada", "acento", self._nova_rodada)
        coluna.addLayout(acoes)
        # As ações são puxadas pelo cursor que se aproxima, como na janela
        # principal. Quem responde pelo teclado não é afetado.
        for acao in (
            self._botao_sair, self._botao_errei, self._botao_dificil, self._botao_acertei,
            self._botao_revelar, self._botao_nao_sei, self._botao_conferir,
            self._botao_proximo, self._botao_nova,
        ):
            acao.tornar_magnetico(4)
        # A mesma resposta ao cursor das outras janelas: luz pelo fundo, anel,
        # ondas, rastro e as bordas acesas. Sem movimento próprio no cenário —
        # quem está revisando está lendo uma palavra —, o relógio daqui só corre
        # enquanto o cursor se mexe.
        self._cenario = Cenario()
        self._cenario.definir_intensidade(janela.intensidade_atmosfera)
        self._cenario.movimento = janela.intensidade_atmosfera > 0.0
        self._cenario.definir(janela.tema, so_o_cursor(janela.atmosfera))
        self._cursor_vivo = CursorVivo(
            self, self._cenario, cor=lambda: self._janela.tema.accent
        )
        self._campo_magnetico = self._cursor_vivo.campo

        # A borda acende na cor do resultado e apaga: sobe rápido, desce devagar.
        self._lampejo = 0.0
        self._animacao_lampejo = QVariantAnimation(self)
        self._animacao_lampejo.setDuration(520)
        self._animacao_lampejo.setStartValue(0.0)
        self._animacao_lampejo.setKeyValueAt(0.2, 1.0)
        self._animacao_lampejo.setEndValue(0.0)
        self._animacao_lampejo.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._animacao_lampejo.valueChanged.connect(self._repintar_lampejo)

        # Os atalhos moram no diálogo, não nos botões: um botão escondido não
        # dispara atalho, e revelar/responder alternam visibilidade o tempo todo.
        # Com o campo do modo de escrever em foco, as letras são dele: o campo
        # pede a tecla antes do atalho, e digitar "a" escreve um "a".
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self._revelar)
        QShortcut(QKeySequence("A"), self, activated=lambda: self._responder(ACERTO))
        QShortcut(QKeySequence("D"), self, activated=lambda: self._responder(DIFICIL))
        QShortcut(QKeySequence("E"), self, activated=lambda: self._responder(ERRO))

        self._barra.recomecar(self._rodada.total)
        self._mostrar_cartao()

    # ------------------------------------------------------------ Estados
    @property
    def modo(self) -> str:
        return self._modo

    def _movimento_reduzido(self) -> bool:
        return bool(self._janela.intensidade_atmosfera <= 0.0)

    def definir_modo(self, modo: str) -> None:
        """Troca o jeito de revisar e guarda a escolha nas preferências.

        A nota de um cartão já conferido fica; é o PRÓXIMO que vem no jeito
        novo. Um cartão em aberto recomeça no jeito novo, sem nota.
        """
        if modo not in MODOS:
            return
        for nome_chip, chip in self.chips_modo.items():
            chip.setChecked(nome_chip == modo)
        if modo == self._modo:
            return
        self._modo = modo
        self._janela.definir_modo_de_revisao(modo)
        if self._conferido or self._rodada.terminada:
            return
        self._mostrar_cartao()
        # Os dois versos têm alturas diferentes: a janela acompanha o que
        # ficou, em vez de guardar o vão do outro jeito.
        self.adjustSize()
        animar_entrada(
            [w for w in (self._termo, self._meta) if not w.isHidden()],
            reduzir=self._movimento_reduzido(),
        )

    def _botoes(self, *visiveis: Botao) -> None:
        """Mostra só as ações do momento; as outras saem do caminho."""
        for acao in (
            self._botao_errei, self._botao_dificil, self._botao_acertei, self._botao_revelar,
            self._botao_nao_sei, self._botao_conferir, self._botao_proximo, self._botao_nova,
        ):
            acao.setVisible(acao in visiveis)

    def _mostrar_cartao(self) -> None:
        cartao = self._rodada.atual
        if cartao is None:
            self._mostrar_resumo()
            return
        self._revelado = False
        self._conferido = False
        self._erradas = 0
        self._progresso.setText(f"CARTÃO {self._rodada.posicao} DE {self._rodada.total}")
        self._traducao.setText("")
        self._exemplo.setText("")
        self._traducao.hide()
        self._exemplo.hide()
        self._botao_sair.setText("Encerrar")
        if self._modo == MODO_ESCREVER:
            # O cartão ao contrário: a tradução na frente, a palavra no campo.
            self._termo.setText(cartao.traducao)
            partes = [p for p in (cartao.jogo, "escreva o termo em inglês") if p]
            self._meta.setText(" · ".join(partes))
            self._verso.hide()
            self._escrita.show()
            self._escrita.preparar(cartao)
            self._botoes(self._botao_nao_sei, self._botao_conferir)
            self._escrita.campo.setFocus()
            return
        self._termo.setText(cartao.termo)
        partes = [p for p in (cartao.jogo, f"vista {cartao.encontros}×") if p]
        self._meta.setText(" · ".join(partes))
        self._escrita.hide()
        self._verso.show()
        self._dica.show()
        self._botoes(self._botao_revelar)
        self._botao_revelar.setFocus()

    def _revelar(self) -> None:
        cartao = self._rodada.atual
        if cartao is None or self._revelado or self._modo != MODO_LEMBRAR:
            return
        self._revelado = True
        self._dica.hide()
        self._traducao.setText(cartao.traducao)
        self._exemplo.setText(cartao.exemplo)
        self._traducao.show()
        self._exemplo.setVisible(bool(cartao.exemplo))
        animar_entrada(
            [w for w in (self._traducao, self._exemplo) if not w.isHidden()],
            reduzir=self._movimento_reduzido(),
        )
        self._botoes(self._botao_errei, self._botao_dificil, self._botao_acertei)
        self._botao_acertei.setFocus()

    def _registrar(self, nota: str) -> None:
        """Dá a nota ao cartão da vez: banco, sequência, barra e recado."""
        cartao = self._rodada.atual
        assert cartao is not None  # quem chama já conferiu
        dias = self._rodada.responder(nota != ERRO, hesitou=nota == DIFICIL)
        # Revisar offline também conta como dia de estudo na sequência.
        #
        # Chamada direta, sem getattr defensivo: `marcar_estudo` faz parte do
        # contrato da janela. O getattr que havia aqui transformaria uma
        # renomeação em silêncio — a sequência de estudo simplesmente pararia
        # de contar, e ninguém descobriria por meses.
        self._janela.marcar_estudo()
        # A nota no ouvido, na voz do jogo: o marcador de acerto do visor, o
        # dedilhado do violão no oeste, o "negado" do terminal. O acerto e o
        # difícil tocam o som de palavra ganha — lembrar custando ainda é
        # lembrar —; o erro, o de erro.
        self._janela.tocar_som("erro" if nota == ERRO else "vocab")
        cor = cor_da_nota(self._tema, nota)
        self._barra.registrar(nota)
        self._recado.setStyleSheet(
            f"color: {design.garantir_contraste(cor, self._fundo)}; background: transparent;"
        )
        self._recado.definir_texto(f"{cartao.termo} volta {quando_volta(dias)}")
        self._cor_lampejo = cor

    def _acender(self) -> None:
        if self._movimento_reduzido():
            return
        self._animacao_lampejo.stop()
        self._animacao_lampejo.start()

    def _responder(self, nota: str) -> None:
        """A nota do modo de lembrar: o jogador diz como foi."""
        if self._modo != MODO_LEMBRAR or not self._revelado or self._rodada.terminada:
            return  # Responder sem ver a resposta não é revisão, é chute.
        self._registrar(nota)
        self._trocar_de_cartao()

    def _trocar_de_cartao(self) -> None:
        """O cartão respondido sai deslizando e o próximo entra."""
        retrato = None if self._movimento_reduzido() else self._cartao.grab()
        self._mostrar_cartao()
        if retrato is not None:
            ImagemQueSai(self._cartao, retrato, deslocamento=QPointF(self.DESLIZE_SAIDA, 0.0))
            animar_entrada(
                [w for w in (self._termo, self._meta, self._dica) if not w.isHidden()],
                reduzir=False,
            )
            animar_entrada([self._recado], reduzir=False)
            self._acender()

    # ------------------------------------------------------ Modo de escrever
    def _enter_da_escrita(self) -> None:
        if self._conferido:
            self._proximo()
        else:
            self._conferir()

    def _conferir(self) -> None:
        """Confere a tentativa digitada e, se for o caso, dá a nota."""
        cartao = self._rodada.atual
        if self._modo != MODO_ESCREVER or self._conferido or cartao is None:
            return
        texto = self._escrita.campo.text()
        if not normalizar(texto):
            return  # Enter no campo vazio não gasta tentativa.
        conferencia = conferir(texto, cartao.termo)
        nota = nota_da_escrita(conferencia, self._erradas)
        if nota is None:
            self._erradas += 1
            self._escrita.mostrar_tentativa(
                conferencia, pista(cartao.termo, self._erradas), TENTATIVAS - self._erradas
            )
            animar_entrada([self._escrita.retorno], reduzir=self._movimento_reduzido())
            return
        self._dar_nota_da_escrita(nota, conferencia)

    def _nao_sei(self) -> None:
        """Desistir é honesto: a palavra aparece e a nota é erro."""
        if self._modo != MODO_ESCREVER or self._conferido or self._rodada.atual is None:
            return
        self._dar_nota_da_escrita(ERRO, None)

    def _dar_nota_da_escrita(self, nota: str, conferencia: Conferencia | None) -> None:
        cartao = self._rodada.atual
        assert cartao is not None
        self._registrar(nota)
        self._conferido = True
        self._escrita.mostrar_desfecho(nota, conferencia, cartao)
        animar_entrada(
            [w for w in (self._escrita.retorno, self._escrita.frase, self._recado) if not w.isHidden()],
            reduzir=self._movimento_reduzido(),
        )
        self._acender()
        self._botoes(self._botao_proximo)
        # O foco fica no campo, agora só de leitura: o Enter que conferiu é o
        # mesmo que passa ao próximo.
        self._escrita.campo.setFocus()

    def _proximo(self) -> None:
        if not self._conferido:
            return
        self._conferido = False
        self._trocar_de_cartao()

    # --------------------------------------------------------------- Resumo
    def _mostrar_resumo(self) -> None:
        self._revelado = False
        self._conferido = False
        restantes = self._store.pendentes()
        if self._rodada.total == 0:
            self._progresso.setText("FILA VAZIA")
            self._termo.setText("Nada vencido")
            self._meta.setText("Todas as palavras estão agendadas para o futuro.")
        else:
            self._progresso.setText("RODADA CONCLUÍDA")
            partes = [contagem(self._rodada.acertos, "acerto", "acertos")]
            if self._rodada.dificeis:
                partes.append(contagem(self._rodada.dificeis, "difícil", "difíceis"))
            partes.append(contagem(self._rodada.erros, "erro", "erros"))
            self._termo.setText(" · ".join(partes))
            self._meta.setText(
                f"{contagem(restantes, 'palavra ainda vencida', 'palavras ainda vencidas')}."
                if restantes
                else "Fila zerada — nada mais vencido por hoje."
            )
        self._traducao.setText("")
        self._exemplo.setText("")
        # O verso fica vazio, mas fica: some com ele e o resumo inteiro desce,
        # porque o diálogo mantém a altura que tinha. A barra acima já é o
        # retrato da rodada.
        for item in (self._dica, self._traducao, self._exemplo):
            item.hide()
        if not self._escrita.isHidden():
            # No modo de escrever, o verso dele é que guarda o lugar.
            self._escrita.preparar_vazio()
        pode_continuar = restantes > 0 and self._rodada.total > 0
        self._botoes(*((self._botao_nova,) if pode_continuar else ()))
        self._botao_sair.setText("Fechar")
        self._botao_sair.setFocus()

    def _nova_rodada(self) -> None:
        self._rodada = RodadaDeRevisao(self._store)
        self._barra.recomecar(self._rodada.total)
        self._recado.definir_texto("")
        self._mostrar_cartao()
        animar_entrada(
            [w for w in (self._termo, self._meta, self._dica) if not w.isHidden()],
            reduzir=self._movimento_reduzido(),
        )

    # ------------------------------------------------------------- Moldura
    def resizeEvent(self, evento: Any) -> None:
        super().resizeEvent(evento)
        if hasattr(self, "_cursor_vivo"):
            self._cursor_vivo.reposicionar()

    def showEvent(self, evento: Any) -> None:
        super().showEvent(evento)
        self.moldura_cartao.montar()
        self._cursor_vivo.reposicionar()

    def hideEvent(self, evento: Any) -> None:
        super().hideEvent(evento)
        # Escondida, ela não recebe o aviso de que o cursor saiu.
        self._cursor_vivo.esquecer()

    # ------------------------------------------------------------- Pintura
    def _repintar_lampejo(self, valor: Any) -> None:
        self._lampejo = float(valor)
        self.update()

    def paintEvent(self, _evento: Any) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        caminho = caminho_forma(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), self._forma, design.RAIO
        )
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(QColor(self._fundo))
        pintor.drawPath(caminho)
        # A luz do cursor sobre o fundo liso, recortada na moldura e atenuada:
        # aqui não há painel translúcido na frente dela.
        pintor.save()
        pintor.setClipPath(caminho)
        self._cenario.pintar_luz(pintor, atenuacao=ATENUACAO_NO_FUNDO_NU)
        pintor.restore()
        acender_borda(pintor, self, caminho)
        caneta = QPen(QColor(design.misturar(self._borda, self._cor_lampejo, self._lampejo)))
        caneta.setWidthF(1.0 + self._lampejo)
        pintor.setPen(caneta)
        pintor.setBrush(Qt.BrushStyle.NoBrush)
        pintor.drawPath(caminho)
        pintor.end()
