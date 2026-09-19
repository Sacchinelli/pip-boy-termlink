"""Visualizador do caderno de vocabulário.

O caderno era, até aqui, um cômodo sem porta: o modelo escrevia nele via
*function calling*, a lateral mostrava um número, e a única forma de ver o
conteúdo era exportar um arquivo e abri-lo em outro programa. Quem tem
trezentas palavras salvas não tinha como responder "quais eu ando errando?".

Esta janela é essa porta. Ela responde a três perguntas que o número sozinho
não responde:

* **O que eu já aprendi?** — a lista inteira, buscável por termo, tradução ou
  exemplo, porque ninguém lembra da palavra em inglês; lembra do contexto.
* **O que está vencido?** — a fila da repetição espaçada, a mesma que o modo
  Quiz consome.
* **O que não entra na minha cabeça?** — o filtro *Difíceis*, que ordena pelo
  número de erros. É a informação mais acionável do caderno e a única que não
  aparece em lugar nenhum durante a conversa.

A janela é temática como o resto do programa: herda a paleta, a fonte e o
vocabulário geométrico do jogo escolhido, e pinta o mesmo fundo procedural —
só a camada estática, sem partícula nem animação, porque um catálogo se lê
parado.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QEnterEvent,
    QHoverEvent,
    QKeySequence,
    QPainter,
    QShortcut,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import design
from ..historico import sessao_em
from ..vocabulary import (
    FILTRO_DIFICEIS,
    FILTRO_DOMINADAS,
    FILTRO_REVISAR,
    FILTRO_TODAS,
    Entrada,
    VocabularyStore,
)
from .atmosfera import Cenario, so_o_cursor
from .componentes import (
    Botao,
    BotaoDeEstado,
    CampoSelecao,
    Desvanecer,
    Holofote,
    acender_borda,
    caminho_forma,
    css_campo_selecao,
)
from .cursor import CursorVivo
from .dialogo import avisar, confirmar_remocao, pedir_correcao
from .moldura import (
    BarraDeTitulo,
    GripsRedimensionamento,
    aplicar_cantos_do_sistema,
)
from .movimento import Transicao, animar_entrada

# Rótulo visível -> filtro do banco. A ordem é a da barra de filtros.
FILTROS_VISIVEIS: dict[str, str] = {
    "Todas": FILTRO_TODAS,
    "Para revisar": FILTRO_REVISAR,
    "Difíceis": FILTRO_DIFICEIS,
    "Dominadas": FILTRO_DOMINADAS,
}

# Teto de cartões desenhados. Um caderno de mil palavras não cabe na tela de
# ninguém, e construir mil widgets a cada tecla digitada trava a busca. Quem
# procura algo específico refina a busca; quem quer tudo, exporta.
LIMITE_CARTOES = 250

# A busca só consulta o banco depois desta pausa. Sem isso, digitar
# "wasteland" dispara nove consultas e nove reconstruções da lista.
ESPERA_BUSCA_MS = 180

# Primeira opção do seletor de jogo — a que não filtra nada.
TODOS_OS_JOGOS = "Todos os jogos"

# Quantos cartões entram em cascata. É o que cabe na janela no tamanho padrão:
# um cartão fora da vista pagaria efeito e animação para ninguém ver, e numa
# lista de 250 a cascata inteira levaria mais de dez segundos.
CASCATA_MAXIMA = 8


def _plural(quantidade: int, singular: str, plural: str) -> str:
    return f"{quantidade} {singular if quantidade == 1 else plural}"


def _selo(entrada: Entrada) -> tuple[str, str]:
    """Texto e papel de cor do estado de revisão de uma palavra."""
    if entrada.vencida:
        return "revisar agora", "accent"
    dias = entrada.dias_ate_revisao
    prazo = "amanhã" if dias == 1 else f"em {_plural(dias, 'dia', 'dias')}"
    return (f"dominada · {prazo}", "info") if entrada.dominada else (prazo, "secondary")


class CartaoTermo(QFrame):
    """Uma palavra do caderno: termo, tradução, exemplo e histórico.

    O cartão percebe quem chega perto, com três respostas em três tempos:

    1. **Luz, na hora.** Um holofote na cor do tema acompanha o cursor e o
       contorno acende do lado dele. É a resposta mais barata e a mais imediata:
       diz "este é o cartão sob o mouse" antes de qualquer decisão.
    2. **Ações, depois de uma pausa.** Os três botões eram desenhados em todo
       cartão, o tempo todo: numa lista de trinta palavras, noventa ícones
       disputando o olho com o que se veio ler. Agora eles aparecem quando o
       cursor PARA no cartão (``INTENCAO_MS``) — varrer a lista acende cada
       cartão de passagem, mas não faz trinta fileiras de botões piscarem.
    3. **Teclado vale o mesmo que mouse.** Tab até uma ação revela as ações na
       hora e leva a luz até ela. Esconder controles no hover sem isso seria
       trancar o teclado para fora — o erro clássico desse padrão.

    O que se esconde são AÇÕES, repetidas em todo cartão; nunca INFORMAÇÃO. O
    estado de revisão, a tradução e o exemplo ficam sempre à vista, porque é
    com eles que se decide o que fazer.
    """

    INTENCAO_MS = 70
    DESLIZE = 10.0
    TAMANHO_ACAO = 28
    MARGENS = (16, 13, 13, 13)  # esquerda, topo, direita, base

    def __init__(
        self,
        entrada: Entrada,
        *,
        janela: Any,
        ao_remover: Callable[[Entrada], None],
        ao_corrigir: Callable[[Entrada], None],
        sessao: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._entrada = entrada
        tema = janela.tema
        self._tema = tema
        self._forma = janela.atmosfera.forma
        self._fundo = tema.surface_alta
        # "Animação também é atmosfera", como na troca de tema: a mesma escolha
        # que para a partícula para a luz que persegue o cursor.
        self._reduzir: Callable[[], bool] = lambda: janela.intensidade_atmosfera <= 0.0
        self._sob_cursor = False
        self._foco: QWidget | None = None
        self._saindo = False
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        self._holofote = Holofote(self, reduzir=self._reduzir)
        self._revelacao = Transicao(
            self, design.DURACAO_MEDIA, self._aplicar_revelacao, reduzir=self._reduzir
        )
        self._intencao = QTimer(self)
        self._intencao.setSingleShot(True)
        self._intencao.setInterval(self.INTENCAO_MS)
        self._intencao.timeout.connect(self._confirmar_intencao)

        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(*self.MARGENS)
        coluna.setSpacing(5)

        topo = QHBoxLayout()
        topo.setSpacing(10)
        # O termo usa a fonte do TEMA: é a palavra do jogo, a única coisa nesta
        # janela que veio de lá. Tradução e metadados ficam na fonte neutra.
        termo = QLabel(entrada.termo)
        termo.setFont(janela.fonte("titulo", ui=False))
        termo.setStyleSheet(
            f"color: {design.garantir_contraste(tema.primary, self._fundo)};"
            f" background: transparent; {self._realce(tema, tema.primary)}"
        )
        termo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        topo.addWidget(termo)
        topo.addStretch(1)

        texto_selo, papel_selo = _selo(entrada)
        selo = QLabel(texto_selo)
        selo.setFont(janela.fonte("micro"))
        selo.setStyleSheet(
            f"color: {design.garantir_contraste(getattr(tema, papel_selo), self._fundo)};"
            " background: transparent;"
        )
        topo.addWidget(selo)
        coluna.addLayout(topo)

        traducao = QLabel(entrada.traducao)
        traducao.setWordWrap(True)
        traducao.setFont(janela.fonte("corpo"))
        traducao.setStyleSheet(
            f"color: {design.garantir_contraste(tema.primary, self._fundo)};"
            f" background: transparent; {self._realce(tema, tema.primary)}"
        )
        traducao.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        coluna.addWidget(traducao)

        if entrada.exemplo:
            exemplo = QLabel(entrada.exemplo)
            exemplo.setWordWrap(True)
            exemplo.setFont(janela.fonte("vocab", ui=False))
            exemplo.setStyleSheet(
                f"color: {design.garantir_contraste(tema.info, self._fundo)};"
                f" background: transparent; {self._realce(tema, tema.info)}"
            )
            exemplo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            coluna.addWidget(exemplo)

        # As ações moram no canto de baixo, que em repouso já é espaço vazio:
        # o rodapé é curto e alinhado à esquerda. Revelar ali não abre buraco
        # no cartão parado, e o espaço é reservado desde o início — aparecer
        # nunca empurra texto. Elas ficam FORA do layout para que o deslize
        # seja só um ``move`` do grupo, sem refazer a disposição do cartão.
        self._acoes = QWidget(self)
        fila = QHBoxLayout(self._acoes)
        fila.setContentsMargins(0, 0, 0, 0)
        fila.setSpacing(4)

        # De volta à conversa em que a palavra nasceu. O caderno guarda o QUE
        # foi ensinado; o histórico guarda o EM QUE MOMENTO — e a palavra sem
        # o contexto em que ela apareceu é metade da memória. Os dois bancos
        # já tinham tudo para fechar esse arco e não havia porta entre eles.
        #
        # O botão só existe quando há conversa: desabilitado, ele diz por quê,
        # em vez de simplesmente não reagir ao clique.
        self.botao_conversa = conversa = Botao(
            "◷", variante="sutil", paleta=janela.paleta, forma=self._forma
        )
        conversa.setFont(janela.fonte("corpo_forte"))
        conversa.setEnabled(sessao is not None)
        if sessao is None:
            conversa.setToolTip(
                "A conversa em que esta palavra apareceu não está no histórico."
            )
            conversa.setAccessibleName(f"Conversa de {entrada.termo} indisponível")
        else:
            conversa.setToolTip(f"Abrir a conversa em que “{entrada.termo}” foi ensinada")
            conversa.setAccessibleName(f"Abrir a conversa de {entrada.termo}")
            conversa.clicked.connect(
                lambda _=False, s=sessao: janela.abrir_conversa(s, entrada.termo)
            )

        # Quem escreve o caderno é o modelo, em silêncio, e de vez em quando
        # ele erra a tradução. Sem esta porta a única saída era o "×" ao lado —
        # que leva junto meses de repetição espaçada para consertar um typo.
        #
        # "▤" é do bloco Geometric Shapes, como todo símbolo desta interface:
        # o lápis (U+270E) seria o desenho óbvio e é do bloco Dingbats, que
        # Consolas e Georgia não têm — sairia como caixinha em metade dos temas.
        corrigir = Botao("▤", variante="sutil", paleta=janela.paleta, forma=self._forma)
        corrigir.setFont(janela.fonte("corpo_forte"))
        corrigir.setToolTip(f"Corrigir o texto de “{entrada.termo}” sem perder a revisão")
        corrigir.setAccessibleName(f"Corrigir {entrada.termo}")
        corrigir.clicked.connect(lambda: ao_corrigir(entrada))

        # "×" (U+00D7, Latin-1) e não "✕" (U+2715, Dingbats): o segundo não
        # existe em Consolas nem em Georgia — as fontes de metade dos temas —
        # e saía como um tracinho vertical irreconhecível. É a mesma armadilha
        # já documentada para os emoji do cabeçalho.
        apagar = Botao("×", variante="perigo_sutil", paleta=janela.paleta, forma=self._forma)
        apagar.setFont(janela.fonte("titulo"))
        apagar.setToolTip(f"Remover “{entrada.termo}” do caderno")
        apagar.setAccessibleName(f"Remover {entrada.termo}")
        apagar.clicked.connect(lambda: ao_remover(entrada))

        for botao in (conversa, corrigir, apagar):
            botao.setFixedSize(self.TAMANHO_ACAO, self.TAMANHO_ACAO)
            botao.installEventFilter(self)
            fila.addWidget(botao)
        self._acoes.adjustSize()
        self._opacidade = QGraphicsOpacityEffect(self._acoes)
        self._acoes.setGraphicsEffect(self._opacidade)

        base = QHBoxLayout()
        base.setSpacing(8)
        partes = [
            p for p in (entrada.jogo, _plural(entrada.encontros, "encontro", "encontros")) if p
        ]
        if entrada.acertos or entrada.erros:
            partes.append(
                f"{_plural(entrada.acertos, 'acerto', 'acertos')} · "
                f"{_plural(entrada.erros, 'erro', 'erros')}"
            )
        rodape = QLabel("   ·   ".join(partes))
        rodape.setFont(janela.fonte("micro"))
        rodape.setStyleSheet(
            f"color: {design.garantir_contraste(tema.secondary, self._fundo)};"
            " background: transparent;"
        )
        rodape.setMinimumHeight(self.TAMANHO_ACAO)
        base.addWidget(rodape, 1)
        base.addSpacing(self._acoes.width())
        coluna.addLayout(base)

        self._aplicar_revelacao(0.0)

    def _realce(self, tema: Any, cor_texto: str) -> str:
        """Realce de seleção contra o fundo deste cartão."""
        return design.css_selecao(
            self._fundo, tema.accent, design.garantir_contraste(cor_texto, self._fundo)
        )

    # -- presença: mouse e teclado alimentam o mesmo estado
    def enterEvent(self, evento: QEnterEvent) -> None:
        self._sob_cursor = True
        self._holofote.seguir(evento.position())
        self._atualizar_presenca()
        super().enterEvent(evento)

    def leaveEvent(self, evento: QEvent) -> None:
        self._sob_cursor = False
        self._atualizar_presenca()
        super().leaveEvent(evento)

    def event(self, evento: QEvent) -> bool:
        if evento.type() == QEvent.Type.HoverMove and isinstance(evento, QHoverEvent):
            self._holofote.seguir(evento.position())
        return super().event(evento)

    def eventFilter(self, alvo: QObject, evento: QEvent) -> bool:
        if evento.type() == QEvent.Type.FocusIn and isinstance(alvo, QWidget):
            self._foco = alvo
            self._atualizar_presenca()
        elif evento.type() == QEvent.Type.FocusOut and alvo is self._foco:
            self._foco = None
            self._atualizar_presenca()
        return super().eventFilter(alvo, evento)

    def _atualizar_presenca(self) -> None:
        if self._saindo:
            return
        self._holofote.acender(self._sob_cursor or self._foco is not None)
        if self._foco is not None:
            self._intencao.stop()
            self._revelacao.ir(1.0)
        elif self._sob_cursor:
            if self._revelacao.valor < 1.0 and not self._intencao.isActive():
                self._intencao.start()
        else:
            self._intencao.stop()
            self._revelacao.ir(0.0)

    def _confirmar_intencao(self) -> None:
        if self._sob_cursor:
            self._revelacao.ir(1.0)

    def _aplicar_revelacao(self, valor: float) -> None:
        self._opacidade.setOpacity(valor)
        # Desligado quando opaco, e não por economia. Em opacidade EXATAMENTE
        # 1.0 o QGraphicsOpacityEffect pega um atalho: pinta os filhos direto,
        # com o mesmo pintor. A auréola de cada Botao é outro efeito, que tenta
        # abrir um segundo pintor no mesmo dispositivo — e cada repintura do
        # cartão aceso cuspia "A paint device can only be painted by one
        # painter at a time". Abaixo de 1.0 o efeito pinta numa imagem antes, e
        # o aninhamento funciona (é o que a Bolha faz com o brilho de fósforo).
        # Em zero ele fica LIGADO: é o que mantém os botões invisíveis sem
        # tirá-los da ordem do Tab.
        self._opacidade.setEnabled(valor < 1.0)
        # Botão quase invisível não pode receber clique: o "×" levaria a uma
        # remoção que a pessoa nem viu que estava ao alcance.
        self._acoes.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, valor < 0.35)
        self._posicionar_acoes()

    def _posicionar_acoes(self) -> None:
        _, _, direita, base = self.MARGENS
        deslize = round((1.0 - self._revelacao.valor) * self.DESLIZE)
        self._acoes.move(
            self.width() - direita - self._acoes.width() + deslize,
            self.height() - base - self._acoes.height(),
        )

    def resizeEvent(self, evento: Any) -> None:
        super().resizeEvent(evento)
        self._posicionar_acoes()

    # -- saída
    def sair(self, ao_terminar: Callable[[], None]) -> None:
        """Esmaece e fecha o espaço que ocupava, em vez de sumir num quadro.

        Sem transição, o cartão de baixo salta para cima e o olho perde qual
        palavra saiu. Esmaecer primeiro e recolher logo atrás mantém a
        continuidade: dá para ver a lista se fechando sobre o buraco. É a única
        animação do cartão que mexe em layout, porque ali a mudança de layout é
        justamente o que precisa ser visto.
        """
        if self._reduzir():
            ao_terminar()
            return
        # Congela o cartão como está. Uma revelação ainda em curso deixaria o
        # efeito das ações ligado sob o esmaecer, que começa em 1.0 — o atalho
        # de ``_aplicar_revelacao``, com um efeito embaixo.
        self._saindo = True
        self._intencao.stop()
        self._revelacao.saltar(1.0)
        self._acoes.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        # Pelo mesmo atalho, as auréolas dois níveis abaixo reclamariam. Um
        # cartão de saída não precisa de auréola nenhuma.
        for botao in self._acoes.findChildren(Botao):
            botao.suspender_halo()
        efeito = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(efeito)
        grupo = QParallelAnimationGroup(self)
        esmaecer = QPropertyAnimation(efeito, b"opacity", grupo)
        esmaecer.setDuration(design.DURACAO_RAPIDA)
        esmaecer.setStartValue(1.0)
        esmaecer.setEndValue(0.0)
        recolher = QPropertyAnimation(self, b"maximumHeight", grupo)
        recolher.setDuration(design.DURACAO_MEDIA)
        recolher.setStartValue(self.height())
        recolher.setEndValue(0)
        recolher.setEasingCurve(QEasingCurve.Type.InOutCubic)
        grupo.addAnimation(esmaecer)
        grupo.addAnimation(recolher)
        grupo.finished.connect(ao_terminar)
        grupo.start()

    # -- desenho
    def paintEvent(self, _evento: Any) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        contorno = caminho_forma(area, self._forma, design.RAIO)
        self._holofote.pintar(
            pintor,
            contorno,
            fundo=self._fundo,
            cor=self._tema.primary,
            borda=self._tema.border,
            foco=None if self._sob_cursor else self._foco,
        )
        acender_borda(pintor, self, contorno)
        pintor.end()


class JanelaCaderno(QDialog):
    """Catálogo navegável do vocabulário salvo."""

    def __init__(self, janela: Any, store: VocabularyStore) -> None:
        super().__init__(janela)
        self._janela = janela
        self._store = store
        self._filtro = FILTRO_TODAS
        self._jogo = ""
        self._cartoes: list[CartaoTermo] = []

        # O mesmo material da janela principal, sem o movimento próprio dela:
        # nem partícula, nem tremulação, nem interferência (ver ``aplicar_tema``).
        # Um catálogo se lê parado, e uma segunda animação a 30 fps competiria
        # com o áudio pela CPU. O que se mexe aqui é só o que segue o cursor —
        # a luz, o anel, as ondas, o rastro —, e só enquanto ele se mexe.
        #
        # A intensidade vem da janela, e não do padrão: parar o movimento não é
        # o mesmo que atenuar a atmosfera. Quem escolheu 'Discreta' ou
        # 'Desligada' fez isso pelos olhos, e a escolha não pode parar na porta
        # desta janela.
        self._cenario = Cenario()
        self._cenario.definir_intensidade(janela.intensidade_atmosfera)
        self._cenario.movimento = janela.intensidade_atmosfera > 0.0
        self._raio_busca = 10.0

        self.setWindowTitle("Caderno de vocabulário")
        # A mesma moldura própria da janela principal: um caderno com barra
        # de título cinza do Windows seria o remendo que o dialogo.py já
        # eliminou das caixas de confirmação.
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setMinimumSize(560, 460)
        self.resize(760, 660)
        self._montar()
        self._grips = GripsRedimensionamento(self)
        self._grips.reposicionar()

        # Esc já fecha um QDialog por conta própria; falta só o caminho de
        # volta ao campo de busca sem passar pelo mouse.
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.busca.setFocus)

        # aplicar_tema termina chamando atualizar(), que carrega a lista.
        self.aplicar_tema()

    # ------------------------------------------------------------- montagem
    def _montar(self) -> None:
        moldura = QVBoxLayout(self)
        moldura.setContentsMargins(0, 0, 0, 0)
        moldura.setSpacing(0)
        self.barra_titulo = BarraDeTitulo(
            self,
            provedor=self._janela,
            titulo="Caderno de vocabulário",
            botoes=("fechar",),
        )
        moldura.addWidget(self.barra_titulo)
        corpo = QWidget(objectName="cadernoCorpo")
        moldura.addWidget(corpo, 1)

        coluna = QVBoxLayout(corpo)
        coluna.setContentsMargins(24, 22, 24, 20)
        coluna.setSpacing(14)

        self.titulo = QLabel("CADERNO DE VOCABULÁRIO", objectName="cadernoTitulo")
        coluna.addWidget(self.titulo)
        self.resumo = QLabel("", objectName="cadernoResumo")
        self.resumo.setWordWrap(True)
        coluna.addWidget(self.resumo)

        self.busca = QLineEdit(objectName="cadernoBusca")
        self.busca.setPlaceholderText("Buscar por termo, tradução ou exemplo…")
        self.busca.setClearButtonEnabled(True)
        self.busca.setToolTip("Ctrl+F volta o cursor para cá")
        self.busca.setAccessibleName("Buscar no caderno")
        self.busca.textChanged.connect(self._agendar_busca)
        coluna.addWidget(self.busca)

        self._espera = QTimer(self)
        self._espera.setSingleShot(True)
        self._espera.setInterval(ESPERA_BUSCA_MS)
        self._espera.timeout.connect(self.atualizar)

        filtros = QHBoxLayout()
        filtros.setSpacing(6)
        self.chips: dict[str, Botao] = {}
        for rotulo, valor in FILTROS_VISIVEIS.items():
            chip = Botao(rotulo, variante="chip", paleta=self._janela.paleta)
            chip.setCheckable(True)
            chip.setChecked(valor == FILTRO_TODAS)
            chip.clicked.connect(lambda _=False, v=valor: self._escolher_filtro(v))
            filtros.addWidget(chip)
            self.chips[valor] = chip
        filtros.addStretch(1)

        # O jogo é uma dimensão SEPARADA do estado de revisão, e por isso não é
        # mais um chip: "difíceis" e "do Cyberpunk" são perguntas independentes,
        # e quem quer as duas ao mesmo tempo — o pedido natural de quem acabou
        # de trocar de jogo — não conseguiria se elas disputassem o mesmo
        # controle. Na mesma linha dos chips, à direita, porque é o mesmo
        # assunto: recortar a lista.
        self.campo_jogo = CampoSelecao()
        self.campo_jogo.setSizeAdjustPolicy(
            CampoSelecao.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.campo_jogo.setMinimumContentsLength(14)
        self.campo_jogo.setAccessibleName("Filtrar por jogo")
        self.campo_jogo.setToolTip("Mostrar só o vocabulário de um jogo")
        self.campo_jogo.currentIndexChanged.connect(lambda _: self.atualizar(animar=True))
        filtros.addWidget(self.campo_jogo)
        coluna.addLayout(filtros)

        self.rolagem = QScrollArea(objectName="cadernoRolagem")
        self.rolagem.setWidgetResizable(True)
        self.rolagem.setFrameShape(QFrame.Shape.NoFrame)
        self.rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._interno = QWidget(objectName="cadernoLista")
        self._fluxo = QVBoxLayout(self._interno)
        self._fluxo.setContentsMargins(4, 4, 12, 4)
        self._fluxo.setSpacing(9)
        self._fluxo.addStretch(1)
        self.rolagem.setWidget(self._interno)
        coluna.addWidget(self.rolagem, 1)

        # Mesmo véu da coluna de ajustes: a lista de termos também é uma
        # área rolável cujo corte, sem aviso, parece um cartão truncado.
        self._veu = Desvanecer(self.rolagem, lambda: self._janela.tema.screen)
        barra = self.rolagem.verticalScrollBar()
        barra.valueChanged.connect(self._posicionar_veu)
        barra.rangeChanged.connect(self._posicionar_veu)

        self.vazio = QLabel("", objectName="cadernoVazio")
        self.vazio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.vazio.setWordWrap(True)
        self.vazio.hide()
        coluna.addWidget(self.vazio)

        rodape = QHBoxLayout()
        rodape.setSpacing(8)
        self.contagem = QLabel("", objectName="cadernoContagem")
        rodape.addWidget(self.contagem)
        rodape.addStretch(1)
        # A revisão offline mora aqui, ao lado do dado que ela consome: cobra
        # as vencidas com a mesma repetição espaçada do Quiz, mas sem sessão,
        # sem rede e sem gastar um token.
        self.botao_progresso = Botao("◔   Progresso", variante="sutil", paleta=self._janela.paleta)
        self.botao_progresso.setToolTip("O caderno em números: ritmo, domínio e jogos")
        self.botao_progresso.clicked.connect(self._abrir_progresso)
        rodape.addWidget(self.botao_progresso)
        self.botao_revisar = Botao("▶   Revisar", variante="primario", paleta=self._janela.paleta)
        self.botao_revisar.setToolTip(
            "Cartões das palavras vencidas — funciona offline, sem gastar tokens"
        )
        self.botao_revisar.clicked.connect(self._abrir_revisao)
        rodape.addWidget(self.botao_revisar)
        # O resultado da exportação ia só para o registro da janela principal,
        # que fica ATRÁS deste caderno: o seletor de arquivo fechava e nada mais
        # acontecia. A confirmação agora aparece no botão que foi clicado.
        self.botao_exportar = BotaoDeEstado(
            "↓   Exportar", "Exportado",
            reduzir=self._movimento_reduzido, variante="sutil", paleta=self._janela.paleta,
        )
        self.botao_exportar.setToolTip("Salvar o caderno como TSV para o Anki ou como Markdown")
        self.botao_exportar.clicked.connect(self._exportar)
        rodape.addWidget(self.botao_exportar)
        self.botao_importar = Botao("↑   Importar", variante="sutil", paleta=self._janela.paleta)
        self.botao_importar.setToolTip(
            "Somar ao caderno os termos de um arquivo TSV. Palavras que já existem "
            "ficam como estão — o histórico de revisão delas não é tocado."
        )
        self.botao_importar.clicked.connect(self._janela.importar_vocabulario)
        rodape.addWidget(self.botao_importar)
        self.botao_fechar = Botao("Fechar", variante="acento", paleta=self._janela.paleta)
        self.botao_fechar.clicked.connect(self.close)
        rodape.addWidget(self.botao_fechar)
        coluna.addLayout(rodape)

        # O rodapé responde ao cursor como os botões da janela principal: cada
        # um é puxado de leve pelo mouse que se aproxima e acende antes do toque.
        for botao in (
            self.botao_progresso, self.botao_revisar, self.botao_exportar,
            self.botao_importar, self.botao_fechar,
        ):
            botao.tornar_magnetico(4)
        # A mesma resposta ao cursor da janela principal, com o cenário daqui:
        # luz, anel, ondas, rastro e as bordas dos cartões acesas por onde ele
        # passa — e o campo de busca, que a folha de estilo pinta, aceso no vidro.
        self._cursor_vivo = CursorVivo(
            self, self._cenario,
            cor=lambda: self._janela.tema.accent,
            bordas=lambda: [(self.busca, self._raio_busca)],
        )
        self._campo_magnetico = self._cursor_vivo.campo

    # ---------------------------------------------------------------- tema
    def definir_intensidade(self, valor: float) -> None:
        """Acompanha o controle de atmosfera da janela principal."""
        self._cenario.definir_intensidade(valor)
        self._cenario.movimento = valor > 0.0
        self._cursor_vivo.sincronizar()
        self.update()

    def aplicar_tema(self) -> None:
        """Repinta a janela com o tema atual. Chamada ao trocar de jogo."""
        janela, t = self._janela, self._janela.tema
        forma = janela.atmosfera.forma
        raio = {"chanfrada": 3, "reta": 2}.get(forma, 8)

        # `definir` recalcula a receita preservando a intensidade corrente, então
        # trocar de jogo não devolve a atmosfera cheia a quem a tinha atenuado.
        self._cenario.definir(t, so_o_cursor(janela.atmosfera))
        self._raio_busca = float(raio + 2)
        self.barra_titulo.aplicar_tema()
        self.titulo.setFont(janela.fonte("display", ui=False))
        self.resumo.setFont(janela.fonte("legenda"))
        self.busca.setFont(janela.fonte("corpo"))
        self.contagem.setFont(janela.fonte("micro"))
        self.vazio.setFont(janela.fonte("corpo"))
        for chip in self.chips.values():
            chip.setFont(janela.fonte("legenda"))
            chip.forma = forma
        self.campo_jogo.setFont(janela.fonte("legenda"))
        self.campo_jogo.definir_cor_seta(t.text_muted)
        self.campo_jogo.definir_cor_luz(t.primary, raio_borda=raio)
        for botao in (
            self.botao_progresso, self.botao_revisar, self.botao_exportar,
            self.botao_importar, self.botao_fechar,
        ):
            botao.setFont(janela.fonte("corpo_forte"))
            botao.forma = forma

        self.setStyleSheet(f"""
        QDialog {{ background: {t.screen}; }}
        QWidget {{ color: {t.primary}; }}
        #cadernoTitulo   {{ color: {t.primary}; }}
        #cadernoResumo, #cadernoContagem {{ color: {t.text_muted}; }}
        #cadernoVazio    {{ color: {t.text_muted}; padding: 28px; }}
        #cadernoRolagem, #cadernoLista, #cadernoCorpo {{ background: transparent; }}
        QLineEdit#cadernoBusca {{
            background: {t.surface_alta}; color: {t.primary};
            border: 1px solid {t.border}; border-radius: {raio + 2}px;
            padding: 10px 13px; selection-background-color: {t.selection};
        }}
        QLineEdit#cadernoBusca:focus {{ border-color: {t.border_forte}; }}
        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
        QScrollBar::handle:vertical {{
            background: {t.border}; border-radius: 4px; min-height: 40px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {t.border_forte}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height: 0px; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
        {css_campo_selecao(t, raio, lambda cor, _alfa: cor)}
        """)
        self.atualizar()

    def _posicionar_veu(self, *_args: Any) -> None:
        viewport = self.rolagem.viewport()
        barra = self.rolagem.verticalScrollBar()
        self._veu.setGeometry(
            0, viewport.height() - Desvanecer.ALTURA,
            viewport.width(), Desvanecer.ALTURA,
        )
        self._veu.setVisible(barra.value() < barra.maximum() - 2)
        self._veu.raise_()

    def resizeEvent(self, evento: Any) -> None:
        super().resizeEvent(evento)
        self._posicionar_veu()
        if hasattr(self, "_grips"):
            self._grips.reposicionar()
        if hasattr(self, "_cursor_vivo"):
            self._cursor_vivo.reposicionar()

    def showEvent(self, evento: Any) -> None:
        super().showEvent(evento)
        aplicar_cantos_do_sistema(self)
        # A lista chega por baixo em vez de simplesmente estar lá: abrir o
        # caderno é uma troca de lugar, e a cascata diz de onde para onde.
        # Reabrir anima de novo; um Ctrl+B com ele já aberto, não.
        animar_entrada(self._cartoes[:CASCATA_MAXIMA], reduzir=self._movimento_reduzido())
        self._cursor_vivo.reposicionar()

    def hideEvent(self, evento: Any) -> None:
        super().hideEvent(evento)
        # Escondido, o caderno não tem para quem desenhar, e o cursor que estava
        # nele não vai avisar que saiu: tudo que o seguia se apaga, e o relógio
        # para.
        self._cursor_vivo.esquecer()

    def _movimento_reduzido(self) -> bool:
        # A mesma régua da janela principal: animação também é atmosfera.
        return bool(self._janela.intensidade_atmosfera <= 0.0)

    def closeEvent(self, evento: Any) -> None:
        """Fechar o caderno também desarma a busca pendente.

        ``close()`` esconde o diálogo mas não para os relógios dele. Digitar no
        campo de busca e fechar dentro dos 180 ms do amortecedor deixava um
        disparo agendado para depois — e, no encerramento do programa, ele
        chegava a ``atualizar()`` com a conexão do caderno já fechada pela
        janela principal, que fecha o banco logo após fechar esta janela.
        """
        self._espera.stop()
        super().closeEvent(evento)

    def paintEvent(self, _evento: Any) -> None:
        """Fundo + vidro, as camadas do cenário atrás dos cartões.

        Só o fundo deixava o caderno parecendo outro programa: no Fallout, a
        janela principal está dentro de um tubo de raios catódicos e o caderno
        era um retângulo liso. Sem camada viva na receita, ``pintar_sobreposicao``
        desenha só o pixmap cacheado de grão, varredura e vinheta. A luz do
        cursor vem no fundo; o anel, as ondas e o rastro, no vidro do
        ``CursorVivo``, por cima dos cartões.
        """
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._cenario.pintar_fundo(pintor, self.width(), self.height())
        self._cenario.pintar_sobreposicao(
            pintor, self.width(), self.height(), com_cursor=False
        )
        pintor.end()

    # -------------------------------------------------------------- conteúdo
    def _agendar_busca(self, _texto: str) -> None:
        self._espera.start()

    def _escolher_filtro(self, valor: str) -> None:
        self._filtro = valor
        for chave, chip in self.chips.items():
            # Os chips são um grupo exclusivo: marcar um desmarca os outros.
            chip.setChecked(chave == valor)
        self.atualizar(animar=True)

    def _sincronizar_jogos(self) -> str:
        """Reflete no seletor os jogos que o caderno tem. Devolve o escolhido.

        Só reconstrói quando a lista MUDOU: ``atualizar`` roda a cada tecla
        digitada na busca, e refazer os itens do combo a cada uma faria o
        popup se fechar debaixo do dedo de quem estivesse com ele aberto.
        """
        desejados = [TODOS_OS_JOGOS, *self._store.jogos()]
        atuais = [self.campo_jogo.itemText(i) for i in range(self.campo_jogo.count())]
        if desejados != atuais:
            escolhido = self.campo_jogo.currentText() or TODOS_OS_JOGOS
            self.campo_jogo.blockSignals(True)
            self.campo_jogo.clear()
            self.campo_jogo.addItems(desejados)
            # Um jogo que sumiu do caderno (última palavra dele apagada) não
            # pode deixar o seletor mostrando uma opção que não existe mais.
            self.campo_jogo.setCurrentText(
                escolhido if escolhido in desejados else TODOS_OS_JOGOS
            )
            self.campo_jogo.blockSignals(False)
        # Um seletor com uma opção só não é uma escolha; ele some do caminho.
        self.campo_jogo.setVisible(len(desejados) > 1)
        atual = self.campo_jogo.currentText()
        return "" if atual == TODOS_OS_JOGOS else atual

    def atualizar(self, *, animar: bool = False, manter_rolagem: bool = False) -> None:
        """Recarrega estatísticas e lista a partir do banco.

        ``animar`` é para quando a lista TROCA de assunto — outro filtro, outro
        jogo. A busca não anima: ela recarrega a cada pausa na digitação, e uma
        cascata por pausa seria a lista pulando debaixo dos olhos de quem lê.

        ``manter_rolagem`` é para quando a lista é a MESMA com uma palavra a
        menos ou corrigida. Voltar ao topo depois de apagar o 40º termo jogava
        a pessoa para longe do lugar em que ela estava trabalhando.
        """
        self._espera.stop()
        self._jogo = self._sincronizar_jogos()
        estatisticas = self._store.estatisticas()
        if estatisticas.acertos or estatisticas.erros:
            aproveitamento = f"   ·   {estatisticas.aproveitamento:.0%} de acerto nas revisões"
        else:
            aproveitamento = ""
        self.resumo.setText(
            f"{_plural(estatisticas.total, 'termo', 'termos')}"
            f"   ·   {estatisticas.vencidas} para revisar"
            f"   ·   {_plural(estatisticas.dominadas, 'dominada', 'dominadas')}"
            f"{aproveitamento}"
        )

        entradas = self._store.listar(
            busca=self.busca.text(), filtro=self._filtro, jogo=self._jogo,
            limite=LIMITE_CARTOES + 1,
        )
        excedeu = len(entradas) > LIMITE_CARTOES
        entradas = entradas[:LIMITE_CARTOES]
        self._preencher(entradas, manter_rolagem=manter_rolagem)
        if animar:
            animar_entrada(self._cartoes[:CASCATA_MAXIMA], reduzir=self._movimento_reduzido())

        if excedeu:
            self.contagem.setText(f"mostrando os primeiros {LIMITE_CARTOES} — refine a busca")
        elif entradas:
            self.contagem.setText(_plural(len(entradas), "resultado", "resultados"))
        else:
            self.contagem.setText("")

        self.vazio.setText("" if entradas else self._mensagem_vazia(estatisticas.total))
        self.vazio.setVisible(not entradas)
        self.rolagem.setVisible(bool(entradas))

        # O botão de revisar anuncia o tamanho da dívida e some do caminho
        # quando não há dívida nenhuma.
        self.botao_revisar.setText(
            f"▶   Revisar ({estatisticas.vencidas})" if estatisticas.vencidas else "▶   Revisar"
        )
        self.botao_revisar.setEnabled(estatisticas.vencidas > 0)

    def _abrir_progresso(self) -> None:
        from .progresso import JanelaProgresso

        JanelaProgresso(self._janela, self._store, parent=self).exec()

    def _abrir_revisao(self) -> None:
        from .revisao import JanelaRevisao

        JanelaRevisao(self._janela, self._store, parent=self).exec()
        # A rodada mexeu em agendamentos e contadores: a lista, o resumo e o
        # contador da janela principal precisam refletir o novo estado.
        self._janela.caderno_mudou()
        self.atualizar()

    def _mensagem_vazia(self, total: int) -> str:
        if total == 0:
            return (
                "O caderno ainda está vazio.\n\n"
                "Inicie uma sessão e pergunte o significado de qualquer palavra "
                "em inglês: o assistente salva aqui, sozinho, tudo o que ensinar."
            )
        # O jogo entra na frase em vez de deixar o vazio parecer o caderno
        # inteiro: com um filtro de jogo ativo, "nenhuma palavra difícil" é
        # ambíguo entre "nenhuma no caderno" e "nenhuma NESTE jogo".
        onde = f" em {self._jogo}" if self._jogo else ""
        if self.busca.text().strip():
            return f"Nenhuma palavra{onde} corresponde a esta busca."
        if self._jogo and self._filtro == FILTRO_TODAS:
            return f"Nenhuma palavra de {self._jogo} no caderno."
        if self._jogo:
            return {
                FILTRO_REVISAR: f"Nada de {self._jogo} vencido para revisar.",
                FILTRO_DOMINADAS: f"Nenhuma palavra de {self._jogo} dominada ainda.",
                FILTRO_DIFICEIS: f"Nenhuma palavra problemática em {self._jogo}.",
            }.get(self._filtro, f"Nada para mostrar em {self._jogo}.")
        return {
            FILTRO_REVISAR: "Nada vencido. Você está em dia com as revisões.",
            FILTRO_DOMINADAS: (
                "Nenhuma palavra dominada ainda. Uma palavra entra aqui depois de "
                "sobreviver a várias revisões seguidas."
            ),
            FILTRO_DIFICEIS: "Nenhuma palavra problemática. Bom sinal.",
        }.get(self._filtro, "Nada para mostrar.")

    def _preencher(self, entradas: list[Entrada], *, manter_rolagem: bool = False) -> None:
        barra = self.rolagem.verticalScrollBar()
        posicao = barra.value() if manter_rolagem else 0
        for cartao in self._cartoes:
            self._fluxo.removeWidget(cartao)
            cartao.setParent(None)
            cartao.deleteLater()
        self._cartoes.clear()
        # Os períodos vêm UMA vez para a lista inteira. Perguntar por cartão
        # seriam 250 consultas a cada tecla digitada na busca.
        periodos = self._janela.periodos_de_conversa()
        for entrada in entradas:
            cartao = CartaoTermo(
                entrada,
                janela=self._janela,
                ao_remover=self._remover,
                ao_corrigir=self._corrigir,
                sessao=sessao_em(periodos, entrada.criado_em) if entrada.criado_em else None,
            )
            self._fluxo.insertWidget(self._fluxo.count() - 1, cartao)
            self._cartoes.append(cartao)
        # Ainda com o alcance antigo: a lista nova só é medida no próximo passo
        # do laço, e o Qt apara a posição sozinho se o alcance encolher.
        barra.setValue(posicao)
        self._posicionar_veu()

    def _corrigir(self, entrada: Entrada) -> None:
        novos = pedir_correcao(
            self._janela,
            termo=entrada.termo,
            traducao=entrada.traducao,
            exemplo=entrada.exemplo,
        )
        if novos is None:
            return
        try:
            atualizada = self._store.editar(
                entrada.termo,
                novo_termo=novos["termo"],
                traducao=novos["traducao"],
                exemplo=novos["exemplo"],
            )
        except ValueError as erro:
            # Campo vazio ou nome já usado por outra palavra. O texto do erro
            # já diz qual das duas coisas foi, e a correção não se perde: a
            # lista continua como estava, para tentar de novo.
            avisar(self._janela, "Não deu para corrigir", str(erro), erro=True)
            return
        self.atualizar(manter_rolagem=True)
        self._janela.caderno_mudou(f"“{atualizada.termo}” corrigido no caderno.")

    def _remover(self, entrada: Entrada) -> None:
        if not confirmar_remocao(self._janela, entrada.termo):
            return
        if not self._store.remover(entrada.termo):
            return
        # A lateral mostra o total e a fila de revisão; ela precisa saber já.
        self._janela.caderno_mudou(f"“{entrada.termo}” removido do caderno.")
        cartao = next((c for c in self._cartoes if c._entrada is entrada), None)
        if cartao is None:
            self.atualizar(manter_rolagem=True)
            return

        def recarregar() -> None:
            # Fechar o programa fecha este caderno e, logo depois, o banco. Uma
            # saída ainda em curso que chegasse aqui consultaria uma conexão
            # encerrada — a mesma corrida que ``closeEvent`` desarma na busca.
            if self.isVisible():
                self.atualizar(manter_rolagem=True)

        cartao.sair(recarregar)

    def _exportar(self) -> None:
        total = self._janela.exportar_vocabulario()
        if total is not None:
            self.botao_exportar.concluir(
                _plural(total, "termo exportado", "termos exportados")
            )
