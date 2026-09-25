"""Construção dos widgets da janela principal.

Terceira peça a sair da ``Janela``, e a maior: eram 344 linhas em cinco
métodos, a quinta parte da classe. Nenhuma delas decide coisa alguma — elas
instanciam widget, empilham em layout e ligam sinal. É a única parte da janela
que roda UMA vez e nunca mais.

**O que a extração acrescenta, além de tirar linhas de lá.** Enquanto a
montagem morava dentro da classe, o inventário do que a janela tem existia
apenas espalhado por 33 atribuições a ``self`` no meio de trezentas linhas de
layout: para saber se um widget existia, e com que nome, era preciso ler a
montagem inteira. Aqui ele é um tipo declarado, agrupado pela região da tela em
que cada peça vive, e o montador é uma função com SAÍDA em vez de um
procedimento com efeitos escondidos.

**O que ela deliberadamente não faz.** Não transforma a coluna lateral e o
palco em widgets próprios, que seria a decomposição de verdade. Os 33
atributos são alcançados umas 120 vezes no resto da janela e mais 47 na suíte
de interface; renomear tudo para ``janela.lateral.campo_jogo`` mexeria em
quase duzentos lugares sem mudar um pixel do que o programa faz. O nome de
cada peça continua o mesmo, e quem já sabia chamá-la continua chamando igual.

A montagem PRECISA da janela — para dela pendurar os widgets, para ler o tema
e a tipografia, e para ligar os sinais aos métodos que reagem. Ela recebe a
janela inteira e o docstring de ``montar`` diz o que usa dela.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..constants import DEFAULT_GAME_AUDIO_GAIN
from ..profiles import MODOS, NIVEIS, VOZES, personas_for
from ..themes import TEMAS
from .componentes import (
    Botao,
    CampoSelecao,
    Desvanecer,
    Medidor,
    Pilula,
    RotuloDecifravel,
    RotuloElidido,
)
from .conversa import Conversa
from .moldura import BarraDeTitulo

if TYPE_CHECKING:  # pragma: no cover
    from .janela import Janela


# Símbolos restritos ao bloco Geometric Shapes e às setas básicas, que toda
# fonte de texto do Windows possui. Emoji está fora de propósito: o Windows os
# desenha SEMPRE coloridos, com fonte própria, e um microfone amarelo no meio
# de um terminal de fósforo verde denuncia que aquele pixel é de outro desenho.
GLIFO_MIC_ATIVO = "○"
GLIFO_MIC_MUDO = "●"
GLIFO_CADERNO = "◫"

NIVEIS_ATMOSFERA: dict[str, float] = {"Completa": 1.0, "Discreta": 0.45, "Desligada": 0.0}

# Fator aplicado à rampa tipográfica inteira e às medidas que confinam texto.
# Os saltos são de 15%: menos que isso não se percebe, e mais que isso pula o
# tamanho que resolveria o problema de alguém.
ESCALAS_TEXTO: dict[str, float] = {"Padrão": 1.0, "Grande": 1.15, "Maior": 1.30}
ESCALA_TEXTO_PADRAO = "Padrão"

# Quanto do som do jogo entra na mistura enviada ao modelo. A preferência
# ``ganho_jogo`` existia, era lida na abertura da sessão e validada por teste —
# mas nenhum controle a escrevia: só se mudava editando o JSON à mão. O valor
# do meio É o padrão do programa, para que a escolha de fábrica volte igual ao
# arquivo em vez de virar um número solto ligeiramente diferente.
NIVEIS_GANHO_JOGO: dict[str, float] = {
    "Alto": 0.70,
    "Médio": DEFAULT_GAME_AUDIO_GAIN,
    "Baixo": 0.25,
}
GANHO_JOGO_PADRAO = "Médio"

# Dicas do chip 'Ouvir o jogo'. Ele nasce sem saber se existe loopback — a
# enumeração de dispositivos roda numa thread — e troca de dica quando sabe.
DICA_OUVIR_O_JOGO = (
    "Envia também o áudio que sai do seu computador, para você poder perguntar "
    "“o que ele acabou de dizer?”. Precisa ser marcado ANTES de iniciar. "
    "A voz do próprio assistente é descartada dessa captura automaticamente."
)
DICA_SEM_LOOPBACK = "Indisponível: exige Windows com WASAPI e o pacote PyAudioWPatch."


# ------------------------------------------------------------ Resumo da sessão
# Quantas linhas o resumo pode ter: os sete seletores que vão na abertura da
# conexão e uma linha de opções. As linhas nascem todas de uma vez e só são
# preenchidas ou escondidas — o resumo é refeito a cada sessão, e criar e
# destruir widget para isso é trabalho sem motivo.
LINHAS_DO_RESUMO = 8


class ResumoDaSessao(QWidget):
    """O que está valendo na sessão no ar, lido de relance.

    Durante a sessão, sete dos dez seletores ficam travados: jogo, nível e
    microfone vão na abertura da conexão, e trocá-los no meio mentiria sobre o
    que está valendo. Travados, eles continuavam ocupando a coluna inteira —
    uma parede de caixas cinzentas que não se podia usar, empurrando para
    baixo da dobra os dois controles que AINDA funcionavam e disputando o olho
    com a conversa, que é o produto. Na janela mínima, cinco caixas travadas
    eram tudo o que a coluna mostrava.

    A informação que eles carregavam — qual jogo, qual voz, qual microfone
    estão valendo agora — é a única coisa que importava neles durante a
    sessão, e ela cabe numa lista de leitura: rótulo discreto à esquerda,
    valor na cor do texto à direita, quebrando linha em vez de cortar. Mais
    legível que o texto apagado de um campo desabilitado, e sem prometer um
    clique que não vai funcionar.

    Termina dizendo como trocar — encerrando —, porque "travado" sem o
    próximo passo é só uma porta fechada.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("resumoSessao")
        self._pilha = QVBoxLayout(self)
        self._pilha.setContentsMargins(0, 0, 0, 0)
        self._pilha.setSpacing(0)
        self._grade = QGridLayout()
        self._grade.setContentsMargins(0, 0, 0, 0)
        self._grade.setHorizontalSpacing(12)
        self._grade.setVerticalSpacing(7)
        self._grade.setColumnStretch(1, 1)
        self.rotulos: list[QLabel] = []
        self.valores: list[QLabel] = []
        for linha in range(LINHAS_DO_RESUMO):
            rotulo = QLabel(objectName="rotuloCampo")
            rotulo.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            valor = QLabel(objectName="valorResumo")
            valor.setWordWrap(True)
            valor.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            # Selecionável: o nome de um microfone é justamente o que alguém
            # quer copiar para procurar nas configurações do Windows.
            valor.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._grade.addWidget(rotulo, linha, 0)
            self._grade.addWidget(valor, linha, 1)
            self.rotulos.append(rotulo)
            self.valores.append(valor)
        self.dica = QLabel(
            "Jogo, voz e microfone vão na abertura da conexão. "
            "Para trocar, encerre a sessão.",
            objectName="dicaResumo",
        )
        self.dica.setWordWrap(True)

    def montar(self, cabecalho: QHBoxLayout) -> None:
        """Encaixa o título de seção (feito pela montagem, como os outros)."""
        self._pilha.addLayout(cabecalho)
        self._pilha.addSpacing(9)
        self._pilha.addLayout(self._grade)
        self._pilha.addSpacing(10)
        self._pilha.addWidget(self.dica)
        self._pilha.addSpacing(14)

    def definir(self, linhas: Sequence[tuple[str, str]]) -> None:
        """Preenche o resumo; as linhas que sobram somem."""
        for indice, (rotulo, valor) in enumerate(zip(self.rotulos, self.valores, strict=True)):
            if indice < len(linhas):
                rotulo.setText(linhas[indice][0])
                valor.setText(linhas[indice][1])
                valor.setAccessibleName(f"{linhas[indice][0]}: {linhas[indice][1]}")
            rotulo.setVisible(indice < len(linhas))
            valor.setVisible(indice < len(linhas))

    @property
    def linhas(self) -> list[tuple[str, str]]:
        """O que o resumo mostra agora, na ordem."""
        return [
            (rotulo.text(), valor.text())
            for rotulo, valor in zip(self.rotulos, self.valores, strict=True)
            if not rotulo.isHidden()
        ]


# --------------------------------------------------------------- Inventário
@dataclass(slots=True)
class Moldura:
    """As superfícies: o que divide a janela antes de haver qualquer controle."""

    barra_titulo: BarraDeTitulo
    coluna_lateral: QWidget
    lateral: QWidget
    rolagem_lateral: QScrollArea
    rodape_lateral: QWidget
    palco: QWidget
    veu: Desvanecer


@dataclass(slots=True)
class Lateral:
    """A coluna de escolhas: tudo que se decide ANTES de falar."""

    marca: RotuloDecifravel
    submarca: QLabel
    # Os seletores também por nome, além do atributo: é assim que o travamento
    # de sessão percorre todos de uma vez, sem uma lista escrita à mão que
    # esqueceria o campo seguinte.
    campos: dict[str, CampoSelecao]
    rotulos_secao: list[RotuloDecifravel]
    rotulos_campo: list[QLabel]
    campo_jogo: CampoSelecao
    campo_persona: CampoSelecao
    campo_nivel: CampoSelecao
    campo_modo: CampoSelecao
    campo_voz: CampoSelecao
    campo_entrada: CampoSelecao
    campo_saida: CampoSelecao
    campo_ganho_jogo: CampoSelecao
    campo_atmosfera: CampoSelecao
    campo_tamanho_texto: CampoSelecao
    chip_alto_falante: Botao
    chip_jogo: Botao
    chip_busca: Botao
    # O que some quando a sessão começa, e o que aparece no lugar. Ver
    # ResumoDaSessao.
    ajustes_de_sessao: QWidget
    bloco_volume: QWidget
    resumo_sessao: ResumoDaSessao


@dataclass(slots=True)
class Rodape:
    """O bloco do caderno, ancorado ao pé da coluna e fora da rolagem."""

    rotulo_caderno: QLabel
    botao_caderno: Botao
    botao_historico: Botao


@dataclass(slots=True)
class Palco:
    """O produto: a conversa, com a barra de estado em cima e a entrada embaixo."""

    pilula: Pilula
    medidor: Medidor
    rotulo_meta: RotuloElidido
    botao_mudo: Botao
    botao_acao: Botao
    conversa: Conversa
    entrada_texto: QLineEdit
    botao_enviar: Botao


@dataclass(slots=True)
class Pecas:
    """Tudo que a montagem construiu, agrupado pela região da tela."""

    moldura: Moldura
    lateral: Lateral
    rodape: Rodape
    palco: Palco


# ------------------------------------------------------------------ Montagem
def montar(janela: Janela) -> Pecas:
    """Constrói a janela inteira e devolve o que ela precisa alcançar depois.

    Da janela, usa: ``fonte()`` e ``_fonte_mono()`` para a tipografia,
    ``paleta`` e ``_tema`` e ``_atmosfera`` para a aparência,
    ``largura_lateral`` para a coluna, ``_entradas``/``_saidas``/``_loopback``
    para as caixas de áudio, e os métodos que respondem aos sinais.
    """
    # A moldura é nossa: a barra de título temática ocupa a primeira faixa
    # e o conteúdo de sempre — lateral e palco — divide o resto.
    moldura = _moldura(janela)
    return Pecas(
        moldura=moldura,
        lateral=_lateral(janela, moldura.lateral),
        rodape=_rodape(janela, moldura.rodape_lateral),
        palco=_palco(janela, moldura.palco),
    )


def _moldura(janela: Janela) -> Moldura:
    pilha_externa = QVBoxLayout(janela)
    pilha_externa.setContentsMargins(0, 0, 0, 0)
    pilha_externa.setSpacing(0)
    barra_titulo = BarraDeTitulo(
        janela, botoes=("compacto", "minimizar", "maximizar", "fechar")
    )
    pilha_externa.addWidget(barra_titulo)

    raiz = QHBoxLayout()
    raiz.setContentsMargins(0, 0, 0, 0)
    raiz.setSpacing(0)
    pilha_externa.addLayout(raiz, 1)

    # A coluna da esquerda tem duas faixas: os ajustes ROLAM, o caderno FICA.
    # Antes tudo era um bloco só dentro da rolagem, e com 1002 px de conteúdo
    # contra 760 px de janela o botão do caderno e o controle de atmosfera
    # nasciam abaixo da dobra — as duas coisas que o usuário mais procura
    # ficavam invisíveis até alguém pensar em rolar uma coluna que não parece
    # rolável. Um destino permanente não é um ajuste; ancorá-lo no rodapé o
    # torna independente da altura da janela.
    coluna_lateral = QWidget(objectName="colunaLateral")
    coluna_lateral.setFixedWidth(janela.largura_lateral)
    pilha = QVBoxLayout(coluna_lateral)
    pilha.setContentsMargins(0, 0, 0, 0)
    pilha.setSpacing(0)

    lateral = QWidget(objectName="lateral")
    rolagem_lateral = QScrollArea(objectName="rolagemLateral")
    rolagem_lateral.setWidget(lateral)
    rolagem_lateral.setWidgetResizable(True)
    rolagem_lateral.setFrameShape(QFrame.Shape.NoFrame)
    rolagem_lateral.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    pilha.addWidget(rolagem_lateral, 1)

    veu = Desvanecer(rolagem_lateral, lambda: janela.tema.surface)
    barra_rolagem = rolagem_lateral.verticalScrollBar()
    barra_rolagem.valueChanged.connect(janela._posicionar_veu)
    barra_rolagem.rangeChanged.connect(janela._posicionar_veu)

    rodape_lateral = QWidget(objectName="rodapeLateral")
    pilha.addWidget(rodape_lateral)
    raiz.addWidget(coluna_lateral)

    palco = QWidget(objectName="palco")
    raiz.addWidget(palco, 1)

    return Moldura(
        barra_titulo=barra_titulo,
        coluna_lateral=coluna_lateral,
        lateral=lateral,
        rolagem_lateral=rolagem_lateral,
        rodape_lateral=rodape_lateral,
        palco=palco,
        veu=veu,
    )


def _lateral(janela: Janela, alvo: QWidget) -> Lateral:
    coluna = QVBoxLayout(alvo)
    coluna.setContentsMargins(24, 22, 24, 16)
    coluna.setSpacing(0)

    # O nome do aparelho e os títulos das seções se decifram sob o cursor.
    marca = RotuloDecifravel(objectName="marca")
    coluna.addWidget(marca)
    submarca = QLabel(objectName="submarca")
    submarca.setWordWrap(True)
    coluna.addWidget(submarca)
    coluna.addSpacing(16)

    campos: dict[str, CampoSelecao] = {}
    # Estes dois recebiam fonte uma vez só, dentro das funções locais abaixo, e
    # ficavam fora do alcance de qualquer repintura. Enquanto a rampa era fixa
    # isso nunca apareceu; com o tamanho do texto ajustável, seriam os únicos
    # rótulos da coluna a não crescer.
    rotulos_secao: list[RotuloDecifravel] = []
    rotulos_campo: list[QLabel] = []

    def secao(titulo: str, destino: QVBoxLayout | None = None) -> QHBoxLayout:
        # Título e fio na MESMA linha, o fio começando onde o texto acaba.
        # Empilhados, viravam duas faixas horizontais por seção, e a coluna
        # ganhava quatro divisórias de largura total competindo com os próprios
        # campos. Ao lado, o fio lê como prolongamento do rótulo: delimita
        # igual e ocupa uma linha em vez de duas.
        linha = QHBoxLayout()
        linha.setContentsMargins(0, 0, 0, 0)
        linha.setSpacing(10)
        rotulo = RotuloDecifravel(titulo.upper(), objectName="secao")
        rotulo.setFont(janela.fonte("secao"))
        rotulos_secao.append(rotulo)
        linha.addWidget(rotulo)
        regua = QFrame(objectName="regua")
        regua.setFixedHeight(1)
        regua.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        linha.addWidget(regua, 1)
        # Sem destino, o título ainda não entra em layout nenhum: quem o pediu
        # o encaixa (é o caso do resumo da sessão, que monta o próprio bloco).
        if destino is not None:
            destino.addLayout(linha)
            destino.addSpacing(9)
        return linha

    def campo(
        nome: str, rotulo: str, valores: list[str], dica: str = "",
        destino: QVBoxLayout | None = None,
    ) -> CampoSelecao:
        alvo = destino if destino is not None else coluna
        etiqueta = QLabel(rotulo, objectName="rotuloCampo")
        etiqueta.setFont(janela.fonte("rotulo"))
        rotulos_campo.append(etiqueta)
        alvo.addWidget(etiqueta)
        alvo.addSpacing(4)
        seletor = CampoSelecao()
        seletor.addItems(valores)
        # Sem isto, um microfone chamado 'Microfone (2- Realtek(R) Audio)' dá
        # 431 px de sizeHint contra 285 px de coluna, e o QComboBox arrasta o
        # layout inteiro para fora da área visível. Com um comprimento mínimo
        # declarado, o Qt encolhe o campo e elide o texto — a lista aberta
        # continua mostrando o nome inteiro.
        seletor.setSizeAdjustPolicy(
            CampoSelecao.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        seletor.setMinimumContentsLength(12)
        seletor.setFont(janela.fonte("aux"))
        seletor.setAccessibleName(rotulo)
        if dica:
            seletor.setToolTip(dica)
            etiqueta.setToolTip(dica)
        alvo.addWidget(seletor)
        alvo.addSpacing(9)
        campos[nome] = seletor
        return seletor

    # O resumo da sessão ocupa o lugar dos ajustes quando ela começa. Nasce
    # escondido e vem PRIMEIRO: com a sessão no ar, é a primeira coisa abaixo
    # do nome do aparelho.
    resumo_sessao = ResumoDaSessao()
    resumo_sessao.montar(secao("Nesta sessão"))
    resumo_sessao.hide()
    coluna.addWidget(resumo_sessao)

    # Tudo que vai na abertura da conexão, num bloco só: é ele que some quando
    # a sessão começa. Os dois controles que continuam valendo durante a
    # conversa — ouvir o jogo e a apresentação — ficam fora dele.
    ajustes_de_sessao = QWidget(objectName="ajustesDeSessao")
    ajustes = QVBoxLayout(ajustes_de_sessao)
    ajustes.setContentsMargins(0, 0, 0, 0)
    ajustes.setSpacing(0)
    coluna.addWidget(ajustes_de_sessao)

    secao("Ambiente", ajustes)
    campo_jogo = campo(
        "jogo", "Jogo", list(TEMAS),
        "Muda a aparência da janela e o contexto de inglês enviado ao modelo. "
        "Só pode ser trocado com a sessão parada — o contexto vai na abertura "
        "da conexão.",
        destino=ajustes,
    )
    campo_jogo.currentTextChanged.connect(janela._trocar_jogo)
    campo_persona = campo(
        "persona", "Personalidade", personas_for(janela.tema),
        "O tom das respostas. A primeira da lista é a personagem do jogo escolhido.",
        destino=ajustes,
    )

    ajustes.addSpacing(4)
    secao("Ensino", ajustes)
    campo_nivel = campo(
        "nivel", "Seu nível", list(NIVEIS),
        "Define o quanto o assistente fala em português e o que corrige.",
        destino=ajustes,
    )
    campo_modo = campo(
        "modo", "Modo", list(MODOS),
        "Como ele ensina: tradução rápida, conversa, pronúncia, quiz das palavras "
        "vencidas ou imersão só em inglês.",
        destino=ajustes,
    )
    campo_voz = campo(
        "voz", "Voz", list(VOZES), "Timbre da voz sintetizada.", destino=ajustes
    )

    def chave(texto: str, destino: QVBoxLayout) -> Botao:
        botao = Botao(
            texto, variante="chip", paleta=janela.paleta,
            forma=janela.atmosfera.forma, alinhamento_esquerdo=True,
        )
        botao.setCheckable(True)
        botao.setFont(janela.fonte("legenda"))
        # Um interruptor não precisa da altura de um botão de ação; a
        # hierarquia da coluna depende dessa diferença.
        botao.setFixedHeight(33)
        destino.addWidget(botao)
        destino.addSpacing(5)
        return botao

    # A busca na web morava na seção de Áudio, entre o alto-falante e o som do
    # jogo — e não tem nada de áudio: ela decide COMO o tutor responde, se
    # consultando a web antes. É ajuste de ensino, e mora com os de ensino.
    chip_busca = chave("Busca na web", ajustes)
    chip_busca.setToolTip(
        "Deixa o modelo consultar a web antes de responder. Reduz invenção sobre "
        "lore e patches, ao custo de latência."
    )

    ajustes.addSpacing(8)
    secao("Áudio", ajustes)
    # As duas listas chegam pela thread de enumeração (ver
    # _carregar_dispositivos); "Padrão do sistema" já é resposta completa para
    # quem não quer escolher aparelho nenhum.
    campo_entrada = campo(
        "entrada", "Microfone", ["Padrão do sistema"] + [d.label for d in janela._entradas],
        "Só pode ser trocado com a sessão parada.",
        destino=ajustes,
    )
    campo_saida = campo(
        "saida", "Saída", ["Padrão do sistema"] + [d.label for d in janela._saidas],
        "Onde o assistente fala. Só pode ser trocado com a sessão parada.",
        destino=ajustes,
    )
    chip_alto_falante = chave("Alto-falante (anti-eco)", ajustes)
    chip_alto_falante.setToolTip(
        "Marque se você NÃO usa fone. Sem isso o assistente ouve a própria voz "
        "pelo alto-falante e se interrompe num laço."
    )

    # "Ouvir o jogo" fica FORA do bloco: é o único ajuste de áudio que muda com
    # a sessão no ar. Na coluna parada ele continua a seção de Áudio, logo
    # abaixo do alto-falante; com a sessão no ar, ele fica sozinho entre o
    # resumo e a apresentação.
    chip_jogo = chave("Ouvir o jogo", coluna)
    # A lista de dispositivos ainda não voltou da thread; até ela chegar, o
    # chip diz o que é verdade agora — não há loopback conhecido.
    chip_jogo.setToolTip(DICA_SEM_LOOPBACK)
    chip_jogo.setEnabled(janela._loopback is not None)
    chip_jogo.toggled.connect(janela._alternar_audio_do_jogo)

    bloco_volume = QWidget(objectName="blocoVolume")
    volume = QVBoxLayout(bloco_volume)
    volume.setContentsMargins(0, 0, 0, 0)
    volume.setSpacing(0)
    coluna.addWidget(bloco_volume)
    volume.addSpacing(4)

    # Fica habilitado mesmo com 'Ouvir o jogo' desmarcado: é uma preferência, e
    # a dica já diz quando ela passa a valer. Amarrá-lo à caixa criaria dois
    # donos do mesmo `setEnabled` — a caixa e o travamento de sessão —
    # disputando o campo.
    campo_ganho_jogo = campo(
        "ganho_jogo", "Volume do jogo na mistura", list(NIVEIS_GANHO_JOGO),
        "Quanto do som do jogo entra junto da sua voz. Baixe se o jogo estiver "
        "abafando a pergunta. Vale para 'Ouvir o jogo' e só na próxima sessão.",
        destino=volume,
    )

    coluna.addSpacing(4)
    secao("Apresentação", coluna)
    campo_atmosfera = campo(
        "atmosfera", "Atmosfera do jogo", list(NIVEIS_ATMOSFERA),
        "Intensidade da varredura, do grão e das partículas. Reduza ou desligue "
        "se o efeito atrapalhar a leitura.",
    )
    campo_atmosfera.currentTextChanged.connect(janela._ajustar_atmosfera)
    campo_tamanho_texto = campo(
        "tamanho_texto", "Tamanho do texto", list(ESCALAS_TEXTO),
        "Aumenta a letra na janela inteira, inclusive no caderno e no histórico. "
        "Este programa costuma ficar ao lado do jogo, às vezes numa TV.",
    )
    campo_tamanho_texto.currentTextChanged.connect(janela._ajustar_tamanho_texto)

    coluna.addStretch(1)

    return Lateral(
        marca=marca, submarca=submarca, campos=campos,
        rotulos_secao=rotulos_secao, rotulos_campo=rotulos_campo,
        campo_jogo=campo_jogo, campo_persona=campo_persona, campo_nivel=campo_nivel,
        campo_modo=campo_modo, campo_voz=campo_voz, campo_entrada=campo_entrada,
        campo_saida=campo_saida, campo_ganho_jogo=campo_ganho_jogo,
        campo_atmosfera=campo_atmosfera, campo_tamanho_texto=campo_tamanho_texto,
        chip_alto_falante=chip_alto_falante, chip_jogo=chip_jogo, chip_busca=chip_busca,
        ajustes_de_sessao=ajustes_de_sessao, bloco_volume=bloco_volume,
        resumo_sessao=resumo_sessao,
    )


def _rodape(janela: Janela, alvo: QWidget) -> Rodape:
    caixa = QVBoxLayout(alvo)
    caixa.setContentsMargins(24, 14, 24, 18)
    caixa.setSpacing(8)

    rotulo_caderno = QLabel(objectName="caderno")
    rotulo_caderno.setFont(janela.fonte("micro"))
    caixa.addWidget(rotulo_caderno)

    # Uma porta só para o caderno. A exportação morava aqui e era a única coisa
    # que se podia fazer com o vocabulário salvo; agora ela é uma das ações lá
    # dentro, ao lado de ver, buscar e apagar.
    # Os botões de ação também são magnéticos, com uma folga menor que a do
    # INICIAR: o ímã deles é um aceno, não um convite.
    # Lado a lado, e não empilhados: são dois destinos do mesmo nível, e um
    # sobre o outro eles gastavam 60 px de altura numa coluna que, na janela
    # mínima, empurrava para baixo da dobra justamente os controles de
    # apresentação — os únicos ainda vivos durante a sessão. O nome completo
    # de cada um continua na dica e no leitor de tela.
    portas = QHBoxLayout()
    portas.setContentsMargins(0, 0, 0, 0)
    portas.setSpacing(8)
    botao_caderno = Botao(
        f"{GLIFO_CADERNO}  Caderno", variante="sutil",
        paleta=janela.paleta, forma=janela.atmosfera.forma, magnetico=True, folga_ima=4,
    )
    botao_caderno.setFont(janela.fonte("corpo_forte"))
    botao_caderno.setToolTip("Ver, buscar e exportar o vocabulário salvo (Ctrl+B)")
    botao_caderno.setAccessibleName("Abrir o caderno de vocabulário")
    botao_caderno.clicked.connect(janela.abrir_caderno)
    portas.addWidget(botao_caderno, 1)

    botao_historico = Botao(
        "◷  Histórico", variante="sutil",
        paleta=janela.paleta, forma=janela.atmosfera.forma, magnetico=True, folga_ima=4,
    )
    botao_historico.setFont(janela.fonte("corpo_forte"))
    botao_historico.setToolTip(
        "Reler as conversas de sessões anteriores — tudo fica só neste computador"
    )
    botao_historico.setAccessibleName("Abrir o histórico de sessões")
    botao_historico.clicked.connect(janela.abrir_historico)
    portas.addWidget(botao_historico, 1)
    caixa.addLayout(portas)

    return Rodape(
        rotulo_caderno=rotulo_caderno,
        botao_caderno=botao_caderno,
        botao_historico=botao_historico,
    )


def _palco(janela: Janela, alvo: QWidget) -> Palco:
    coluna = QVBoxLayout(alvo)
    coluna.setContentsMargins(24, 24, 24, 24)
    coluna.setSpacing(16)

    barra = QHBoxLayout()
    barra.setSpacing(16)
    pilula = Pilula()
    pilula.setFont(janela.fonte("micro"))
    barra.addWidget(pilula)
    medidor = Medidor()
    medidor.setToolTip(
        "Nível do seu microfone. O risco marca onde o portão de voz abre: "
        "à esquerda dele nada é transmitido. Parado = microfone errado ou bloqueado."
    )
    barra.addWidget(medidor)
    # Numa barra apertada é ESTE texto que cede — os botões ao lado não têm
    # como se abreviar.
    rotulo_meta = RotuloElidido(objectName="meta")
    rotulo_meta.setFont(janela._fonte_mono("micro"))
    barra.addWidget(rotulo_meta)
    barra.addStretch(1)

    botao_mudo = Botao(
        f"{GLIFO_MIC_ATIVO}   Mudo", variante="acento", paleta=janela.paleta,
        forma=janela.atmosfera.forma, magnetico=True, folga_ima=4,
    )
    botao_mudo.setFont(janela.fonte("corpo_forte"))
    botao_mudo.clicked.connect(janela.alternar_mudo)
    botao_mudo.setToolTip("Corta o envio do microfone. Nada é transmitido enquanto mudo.")
    botao_mudo.setEnabled(False)
    barra.addWidget(botao_mudo)

    # Magnético: o botão principal é puxado na direção do cursor quando ele
    # chega perto, e acende antes do toque. É o convite da janela inteira.
    botao_acao = Botao(
        variante="primario", paleta=janela.paleta, forma=janela.atmosfera.forma,
        largura_min=150, magnetico=True,
    )
    botao_acao.setFont(janela.fonte("corpo_forte"))
    botao_acao.clicked.connect(janela.alternar_sessao)
    botao_acao.setToolTip("Iniciar ou encerrar a sessão de voz (F12)")
    barra.addWidget(botao_acao)
    coluna.addLayout(barra)

    conversa = Conversa(janela)
    coluna.addWidget(conversa, 1)

    linha = QHBoxLayout()
    linha.setSpacing(8)
    entrada_texto = QLineEdit(objectName="entrada")
    entrada_texto.setPlaceholderText("Perguntar por texto…")
    entrada_texto.setFont(janela.fonte("corpo"))
    entrada_texto.setToolTip("Perguntar sem falar. Ctrl+L traz o cursor para cá.")
    entrada_texto.setAccessibleName("Perguntar por texto")
    entrada_texto.returnPressed.connect(janela.enviar_texto)
    linha.addWidget(entrada_texto, 1)
    botao_enviar = Botao(
        "Enviar", variante="sutil", paleta=janela.paleta, forma=janela.atmosfera.forma,
        magnetico=True, folga_ima=4,
    )
    botao_enviar.setFont(janela.fonte("corpo_forte"))
    botao_enviar.clicked.connect(janela.enviar_texto)
    linha.addWidget(botao_enviar)
    coluna.addLayout(linha)

    return Palco(
        pilula=pilula, medidor=medidor, rotulo_meta=rotulo_meta,
        botao_mudo=botao_mudo, botao_acao=botao_acao, conversa=conversa,
        entrada_texto=entrada_texto, botao_enviar=botao_enviar,
    )
