"""Janela principal e orquestração do ciclo de vida da sessão.

Regra invariante, herdada da versão anterior e igualmente válida aqui: tudo
que toca num widget roda na thread principal. A sessão publica ``UiEvent``
numa ``queue.Queue`` e um ``QTimer`` a drena — nada de sinal do Qt emitido de
dentro da thread de áudio, nada de widget atravessando fronteira.

A janela tem duas colunas. **Lateral**: tudo que se escolhe antes de falar,
agrupado por assunto e travado durante a sessão. **Palco**: a conversa, que é
o produto, e a barra de estado e ações.
"""

from __future__ import annotations

import contextlib
import logging
import queue
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import (
    QEasingCurve,
    QElapsedTimer,
    QEvent,
    QPropertyAnimation,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QFont,
    QFontDatabase,
    QFontMetrics,
    QKeySequence,
    QPainter,
    QShortcut,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import design
from ..audio import HAS_LOOPBACK_SUPPORT, Device, list_devices
from ..config import AppConfiguration, Preferences, data_directory
from ..constants import (
    DEFAULT_GAME_AUDIO_GAIN,
    SHUTDOWN_TIMEOUT_SECONDS,
    UI_POLL_INTERVAL_MS,
)
from ..events import Tag, UiEvent, UiEventKind
from ..historico import HistoricoStore
from ..profiles import (
    DEFAULT_JOGO,
    DEFAULT_MODO,
    DEFAULT_NIVEL,
    DEFAULT_PERSONA,
    DEFAULT_VOZ,
    MODOS,
    NIVEIS,
    VOZES,
    SessionSettings,
    personas_for,
)
from ..themes import TEMAS, GameTheme, paleta_de, theme_for
from ..vocabulary import VocabularyStore
from .atmosfera import Cenario, atmosfera_de
from .caderno import JanelaCaderno
from .componentes import (
    Botao,
    CampoSelecao,
    Desvanecer,
    Medidor,
    Pilula,
    RotuloElidido,
    TransicaoDeTema,
    css_campo_selecao,
)
from .conversa import Conversa
from .dialogo import avisar
from .moldura import (
    BarraDeTitulo,
    GripsRedimensionamento,
    aplicar_cantos_do_sistema,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..session import LiveSessionWorker

LOGGER = logging.getLogger("pip_boy.interface")

try:
    import keyboard
except ImportError:  # pragma: no cover
    keyboard = None


# Símbolos restritos ao bloco Geometric Shapes e às setas básicas, que toda
# fonte de texto do Windows possui. Emoji está fora de propósito: o Windows os
# desenha SEMPRE coloridos, com fonte própria, e um microfone amarelo no meio
# de um terminal de fósforo verde denuncia que aquele pixel é de outro desenho.
GLIFO_MIC_ATIVO = "○"
GLIFO_MIC_MUDO = "●"
GLIFO_CADERNO = "◫"

FONTES_MONO: tuple[str, ...] = ("Cascadia Mono", "Consolas", "Courier New", "Courier")

NIVEIS_ATMOSFERA: dict[str, float] = {"Completa": 1.0, "Discreta": 0.45, "Desligada": 0.0}

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


def _rgba(cor: str, alfa: float) -> str:
    """Converte '#rrggbb' na notação rgba() do Qt, com opacidade.

    A folha de estilo precisa disto para que as superfícies deixem o cenário
    aparecer por trás — sem opacidade não há atmosfera, só um fundo tapado.
    """
    valor = cor.lstrip("#")
    r, g, b = (int(valor[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alfa:.3f})"


class Sobreposicao(QWidget):
    """Vidro do aparelho: a camada que fica na frente de tudo.

    Transparente a eventos de mouse, para não roubar cliques. É o único widget
    que repinta a cada quadro.
    """

    def __init__(self, cenario: Cenario, parent: QWidget) -> None:
        super().__init__(parent)
        self._cenario = cenario
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _evento: Any) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._cenario.pintar_sobreposicao(pintor, self.width(), self.height())
        pintor.end()


class Janela(QWidget):
    def __init__(self, configuration: AppConfiguration) -> None:
        super().__init__()
        self._configuration = configuration
        self._prefs = Preferences.load()
        self._store = VocabularyStore(data_directory() / "vocabulario.sqlite3")
        try:
            copia = self._store.criar_backup(data_directory() / "backups")
            if copia is not None:
                LOGGER.info("Backup diário do caderno: %s", copia.name)
        except Exception:
            LOGGER.exception("Backup do caderno falhou — o programa segue sem ele.")
        self._historico = HistoricoStore(data_directory() / "historico.sqlite3")
        try:
            podadas = self._historico.podar_antigas()
            if podadas:
                LOGGER.info("Histórico: %s sessão(ões) além da retenção removidas.", podadas)
        except Exception:
            LOGGER.exception("Poda do histórico falhou — o programa segue sem ela.")
        self._sessao_historico: int | None = None

        self._eventos: queue.Queue[UiEvent] = queue.Queue()
        self._worker: LiveSessionWorker | None = None
        self._contador_sessoes = 0
        self._encerrando = False
        self._prazo_encerramento = 0.0
        self._atalhos_globais: list[Any] = []
        self._inicio_sessao = 0.0
        self._mudo = False
        self._tokens = 0
        self._caderno: JanelaCaderno | None = None
        self._visor_historico: Any = None
        self._capsula: Any = None
        self._ja_apareceu = False
        self._jogo_detectado = ""
        self._estado_texto = ""
        self._estado_papel = "secondary"
        # Nasce declarada em vez de aparecer no primeiro _ajustar_atmosfera:
        # meia dúzia de leitores usavam getattr com padrão para contornar a
        # janela em que ela não existia.
        self._intensidade_atmosfera = 1.0

        self._tema: GameTheme = theme_for(self._prefs.jogo)
        self._atmosfera = atmosfera_de(self._tema.name)
        self._instaladas = set(QFontDatabase.families())
        self._mono = self._primeira_instalada(FONTES_MONO)

        self._cenario = Cenario()
        self._cronometro = QElapsedTimer()
        self._cronometro.start()
        self._ultimo_quadro = 0.0

        self._entradas: list[Device] = []
        self._saidas: list[Device] = []
        self._loopback: Device | None = None
        self._carregar_dispositivos()

        self._configurar_janela()
        self._montar()
        self._sobreposicao = Sobreposicao(self._cenario, self)
        self._sobreposicao.setGeometry(self.rect())
        self._sobreposicao.raise_()
        # As alças vêm depois da sobreposição: precisam do mouse, e ela é
        # transparente a ele — a ordem visual não interfere.
        self._grips = GripsRedimensionamento(self)
        self._grips.reposicionar()
        from .campainha import Campainha

        self._campainha = Campainha(self)
        # Os relógios vêm antes das preferências: aplicar a preferência de
        # atmosfera já mexe no relógio de quadros.
        self._iniciar_relogios()
        self._aplicar_preferencias()
        self._aplicar_tema()
        self._registrar_atalhos()
        self._aquecer_sessao()
        try:
            from .bandeja import criar_bandeja

            self._bandeja = criar_bandeja(self)
        except Exception:
            self._bandeja = None
            LOGGER.exception("Bandeja indisponível — o programa segue sem ela.")

        self._registrar(
            f"Modelo {configuration.model} · chave {configuration.redacted_key()} · "
            f"{self._store.total()} termos no caderno",
            Tag.SISTEMA,
        )
        if keyboard is not None and configuration.global_hotkeys_enabled:
            self._registrar(
                f"Atalhos globais: {configuration.hotkey_toggle} iniciar/parar · "
                f"{configuration.hotkey_mute} mudo · "
                f"{configuration.hotkey_game_audio} áudio do jogo",
                Tag.SISTEMA,
            )

    # ------------------------------------------------------------ Dispositivos

    def _carregar_dispositivos(self) -> None:
        try:
            self._entradas, self._saidas, self._loopback = list_devices()
        except Exception:
            LOGGER.exception("Falha ao listar dispositivos de áudio.")
            self._entradas, self._saidas, self._loopback = [], [], None

    def _indice_dispositivo(self, campo: CampoSelecao, lista: list[Device]) -> int | None:
        rotulo = campo.currentText()
        if not rotulo or rotulo.startswith("Padrão"):
            return None
        for device in lista:
            if device.label == rotulo:
                return device.index
        return None

    # ------------------------------------------------------------------- Tema

    @property
    def tema(self) -> GameTheme:
        return self._tema

    @property
    def atmosfera(self) -> Any:
        return self._atmosfera

    # -------------------------------------------------------- Contrato de estado
    # A janela já publicava um contrato de TEMA (tema, atmosfera, fonte, paleta)
    # que o caderno, os diálogos, a moldura e o cartão de boas-vindas consomem
    # sem saber quem o fornece. O estado da sessão não tinha o equivalente, e o
    # resultado era a cápsula, a bandeja e a campainha lendo `_worker`, `_mudo`,
    # `_estado_texto` e `_intensidade_atmosfera` direto — quatro módulos
    # amarrados a nomes privados de um quinto. Estas cinco propriedades são esse
    # contrato; nenhum consumidor externo precisa de mais que isto.

    @property
    def sessao_ativa(self) -> bool:
        return self._worker is not None

    @property
    def mudo(self) -> bool:
        return self._mudo

    @property
    def estado_texto(self) -> str:
        """O estado publicado pela sessão, ou o ocioso do tema quando parada."""
        return self._estado_texto or self._tema.idle_text

    @property
    def nivel_entrada(self) -> float:
        return self._worker.input_level if self._worker is not None else 0.0

    @property
    def limiar_entrada(self) -> float:
        """Limiar do portão de voz, para o medidor desenhar. 0.0 sem sessão."""
        return self._worker.input_threshold if self._worker is not None else 0.0

    @property
    def intensidade_atmosfera(self) -> float:
        """0.0 (desligada) a 1.0 (completa). Vale para o olho e para o ouvido."""
        return self._intensidade_atmosfera

    @property
    def encerrando(self) -> bool:
        """O programa está saindo?

        A cápsula precisa saber: fechá-la normalmente devolve a janela
        principal, mas durante o encerramento quem a está fechando é a própria
        janela — e reabrir ali desfaria a saída.
        """
        return self._encerrando

    def paleta(self) -> dict[str, str]:
        """Cores do tema num dicionário simples, para os componentes pintados."""
        return paleta_de(self._tema)

    def _primeira_instalada(self, candidatas: tuple[str, ...]) -> str:
        for nome in candidatas:
            if nome in self._instaladas:
                return nome
        return candidatas[-1]

    def fonte(self, papel: str, *, ui: bool = True) -> QFont:
        """Fonte para um degrau da rampa tipográfica.

        ``ui=True`` usa a família neutra dos controles; ``ui=False`` usa a
        fonte do tema, reservada à marca e à fala do assistente.
        """
        tipo = design.TIPO[papel]
        familia = self._primeira_instalada(
            self._tema.ui_font_candidates if ui else self._tema.font_candidates
        )
        fonte = QFont(familia, tipo.tamanho)
        fonte.setBold(tipo.peso == "bold")
        fonte.setItalic(tipo.estilo == "italic")
        return fonte

    def _fonte_mono(self, papel: str) -> QFont:
        tipo = design.TIPO[papel]
        return QFont(self._mono, tipo.tamanho)

    def _ajustar_marca(self, texto: str) -> QFont:
        """Encolhe o nome do ambiente até ele caber na largura da coluna."""
        fonte = self.fonte("display", ui=False)
        maximo = design.TIPO["display"].tamanho
        for tamanho in range(maximo, maximo - 10, -1):
            fonte.setPointSize(tamanho)
            if QFontMetrics(fonte).horizontalAdvance(texto) <= design.CABECALHO_LARGURA_MAX:
                break
        return fonte

    # ----------------------------------------------------------------- Janela

    def _configurar_janela(self) -> None:
        self.setWindowTitle(self._tema.window_title)
        # Sem a moldura do sistema: a barra de título é desenhada no tema pela
        # BarraDeTitulo. Os hints de minimizar/maximizar continuam declarados
        # para que a barra de tarefas e o Win+Seta tratem a janela como comum.
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setMinimumSize(980, 620)
        geometria = str(self._prefs.extras.get("geometria", "") or "")
        try:
            largura, altura, x, y = (int(v) for v in geometria.split(","))
        except (TypeError, ValueError):
            self.resize(1240, 860)
            return
        # Uma geometria de um monitor que não existe mais deixaria a janela
        # num canto invisível — sintoma clássico de "o programa não abre".
        tela = self.screen().availableGeometry() if self.screen() else None
        if tela is None or not (980 <= largura <= tela.width() and 620 <= altura <= tela.height()):
            self.resize(1240, 860)
            return
        self.setGeometry(max(tela.x(), x), max(tela.y(), y), largura, altura)

    def _montar(self) -> None:
        # A moldura é nossa: a barra de título temática ocupa a primeira faixa
        # e o conteúdo de sempre — lateral e palco — divide o resto.
        moldura = QVBoxLayout(self)
        moldura.setContentsMargins(0, 0, 0, 0)
        moldura.setSpacing(0)
        self.barra_titulo = BarraDeTitulo(
            self, botoes=("compacto", "minimizar", "maximizar", "fechar")
        )
        moldura.addWidget(self.barra_titulo)

        raiz = QHBoxLayout()
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)
        moldura.addLayout(raiz, 1)

        # A coluna da esquerda tem duas faixas: os ajustes ROLAM, o caderno
        # FICA. Antes tudo era um bloco só dentro da rolagem, e com 1002 px de
        # conteúdo contra 760 px de janela o botão do caderno e o controle de
        # atmosfera nasciam abaixo da dobra — as duas coisas que o usuário mais
        # procura ficavam invisíveis até alguém pensar em rolar uma coluna que
        # não parece rolável. Um destino permanente não é um ajuste; ancorá-lo
        # no rodapé o torna independente da altura da janela.
        self.coluna_lateral = QWidget(objectName="colunaLateral")
        self.coluna_lateral.setFixedWidth(design.LARGURA_LATERAL)
        pilha = QVBoxLayout(self.coluna_lateral)
        pilha.setContentsMargins(0, 0, 0, 0)
        pilha.setSpacing(0)

        self.lateral = QWidget(objectName="lateral")
        self.rolagem_lateral = QScrollArea(objectName="rolagemLateral")
        self.rolagem_lateral.setWidget(self.lateral)
        self.rolagem_lateral.setWidgetResizable(True)
        self.rolagem_lateral.setFrameShape(QFrame.Shape.NoFrame)
        self.rolagem_lateral.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        pilha.addWidget(self.rolagem_lateral, 1)

        self._veu = Desvanecer(self.rolagem_lateral, lambda: self._tema.surface)
        barra_lateral = self.rolagem_lateral.verticalScrollBar()
        barra_lateral.valueChanged.connect(self._posicionar_veu)
        barra_lateral.rangeChanged.connect(self._posicionar_veu)

        self.rodape_lateral = QWidget(objectName="rodapeLateral")
        pilha.addWidget(self.rodape_lateral)
        raiz.addWidget(self.coluna_lateral)

        self.palco = QWidget(objectName="palco")
        raiz.addWidget(self.palco, 1)

        self._montar_lateral()
        self._montar_rodape_lateral()
        self._montar_palco()

    def _montar_lateral(self) -> None:
        coluna = QVBoxLayout(self.lateral)
        coluna.setContentsMargins(24, 22, 24, 16)
        coluna.setSpacing(0)

        self.marca = QLabel(objectName="marca")
        coluna.addWidget(self.marca)
        self.submarca = QLabel(objectName="submarca")
        self.submarca.setWordWrap(True)
        coluna.addWidget(self.submarca)
        coluna.addSpacing(16)

        self.campos: dict[str, CampoSelecao] = {}

        def secao(titulo: str) -> None:
            # Título e fio na MESMA linha, o fio começando onde o texto acaba.
            # Empilhados, viravam duas faixas horizontais por seção, e a coluna
            # ganhava quatro divisórias de largura total competindo com os
            # próprios campos. Ao lado, o fio lê como prolongamento do rótulo:
            # delimita igual e ocupa uma linha em vez de duas.
            linha = QHBoxLayout()
            linha.setContentsMargins(0, 0, 0, 0)
            linha.setSpacing(10)
            rotulo = QLabel(titulo.upper(), objectName="secao")
            rotulo.setFont(self.fonte("secao"))
            linha.addWidget(rotulo)
            regua = QFrame(objectName="regua")
            regua.setFixedHeight(1)
            regua.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            linha.addWidget(regua, 1)
            coluna.addLayout(linha)
            coluna.addSpacing(9)

        def campo(nome: str, rotulo: str, valores: list[str], dica: str = "") -> CampoSelecao:
            etiqueta = QLabel(rotulo, objectName="rotuloCampo")
            etiqueta.setFont(self.fonte("rotulo"))
            coluna.addWidget(etiqueta)
            coluna.addSpacing(4)
            seletor = CampoSelecao()
            seletor.addItems(valores)
            # Sem isto, um microfone chamado 'Microfone (2- Realtek(R) Audio)'
            # dá 431 px de sizeHint contra 285 px de coluna, e o QComboBox
            # arrasta o layout inteiro para fora da área visível. Com um
            # comprimento mínimo declarado, o Qt encolhe o campo e elide o
            # texto — a lista aberta continua mostrando o nome inteiro.
            seletor.setSizeAdjustPolicy(
                CampoSelecao.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            seletor.setMinimumContentsLength(12)
            seletor.setFont(self.fonte("aux"))
            seletor.setAccessibleName(rotulo)
            if dica:
                seletor.setToolTip(dica)
                etiqueta.setToolTip(dica)
            coluna.addWidget(seletor)
            coluna.addSpacing(9)
            self.campos[nome] = seletor
            return seletor

        secao("Ambiente")
        self.campo_jogo = campo(
            "jogo", "Jogo", list(TEMAS),
            "Muda a aparência da janela e o contexto de inglês enviado ao modelo. "
            "Só pode ser trocado com a sessão parada — o contexto vai na abertura "
            "da conexão.",
        )
        self.campo_jogo.currentTextChanged.connect(self._trocar_jogo)
        self.campo_persona = campo(
            "persona", "Personalidade", personas_for(self._tema),
            "O tom das respostas. A primeira da lista é a personagem do jogo escolhido.",
        )

        coluna.addSpacing(4)
        secao("Ensino")
        self.campo_nivel = campo(
            "nivel", "Seu nível", list(NIVEIS),
            "Define o quanto o assistente fala em português e o que corrige.",
        )
        self.campo_modo = campo(
            "modo", "Modo", list(MODOS),
            "Como ele ensina: tradução rápida, conversa, pronúncia, quiz das palavras "
            "vencidas ou imersão só em inglês.",
        )
        self.campo_voz = campo("voz", "Voz", list(VOZES), "Timbre da voz sintetizada.")

        coluna.addSpacing(4)
        secao("Áudio")
        self.campo_entrada = campo(
            "entrada", "Microfone", ["Padrão do sistema"] + [d.label for d in self._entradas],
            "Só pode ser trocado com a sessão parada.",
        )
        self.campo_saida = campo(
            "saida", "Saída", ["Padrão do sistema"] + [d.label for d in self._saidas],
            "Onde o assistente fala. Só pode ser trocado com a sessão parada.",
        )

        self.chip_alto_falante = Botao(
            "Alto-falante (anti-eco)", variante="chip", paleta=self.paleta,
            forma=self._atmosfera.forma, alinhamento_esquerdo=True,
        )
        self.chip_jogo = Botao(
            "Ouvir o jogo", variante="chip", paleta=self.paleta,
            forma=self._atmosfera.forma, alinhamento_esquerdo=True,
        )
        self.chip_busca = Botao(
            "Busca na web", variante="chip", paleta=self.paleta,
            forma=self._atmosfera.forma, alinhamento_esquerdo=True,
        )
        self.chip_alto_falante.setToolTip(
            "Marque se você NÃO usa fone. Sem isso o assistente ouve a própria voz "
            "pelo alto-falante e se interrompe num laço."
        )
        self.chip_busca.setToolTip(
            "Deixa o modelo consultar a web antes de responder. Reduz invenção sobre "
            "lore e patches, ao custo de latência."
        )
        self.chip_jogo.setToolTip(
            "Envia também o áudio que sai do seu computador, para você poder perguntar "
            "“o que ele acabou de dizer?”. Precisa ser marcado ANTES de iniciar. "
            "A voz do próprio assistente é descartada dessa captura automaticamente."
            if HAS_LOOPBACK_SUPPORT and self._loopback
            else "Indisponível: exige Windows com WASAPI e o pacote PyAudioWPatch."
        )
        for chip in (self.chip_alto_falante, self.chip_jogo, self.chip_busca):
            chip.setCheckable(True)
            chip.setFont(self.fonte("legenda"))
            # Um interruptor não precisa da altura de um botão de ação; a
            # hierarquia da coluna depende dessa diferença.
            chip.setFixedHeight(33)
            coluna.addWidget(chip)
            coluna.addSpacing(5)
        self.chip_jogo.setEnabled(bool(HAS_LOOPBACK_SUPPORT and self._loopback))
        self.chip_jogo.toggled.connect(self._alternar_audio_do_jogo)

        coluna.addSpacing(4)
        # Fica habilitado mesmo com 'Ouvir o jogo' desmarcado: é uma preferência,
        # e a dica já diz quando ela passa a valer. Amarrá-lo à caixa criaria
        # dois donos do mesmo `setEnabled` — a caixa e o travamento de sessão —
        # disputando o campo.
        self.campo_ganho_jogo = campo(
            "ganho_jogo", "Volume do jogo na mistura", list(NIVEIS_GANHO_JOGO),
            "Quanto do som do jogo entra junto da sua voz. Baixe se o jogo estiver "
            "abafando a pergunta. Vale para 'Ouvir o jogo' e só na próxima sessão.",
        )

        coluna.addSpacing(4)
        secao("Apresentação")
        self.campo_atmosfera = campo(
            "atmosfera", "Atmosfera do jogo", list(NIVEIS_ATMOSFERA),
            "Intensidade da varredura, do grão e das partículas. Reduza ou desligue "
            "se o efeito atrapalhar a leitura.",
        )
        self.campo_atmosfera.currentTextChanged.connect(self._ajustar_atmosfera)

        coluna.addStretch(1)

    def _montar_rodape_lateral(self) -> None:
        """Bloco do caderno, ancorado ao pé da coluna e fora da rolagem."""
        caixa = QVBoxLayout(self.rodape_lateral)
        caixa.setContentsMargins(24, 14, 24, 18)
        caixa.setSpacing(8)

        self.rotulo_caderno = QLabel(objectName="caderno")
        self.rotulo_caderno.setFont(self.fonte("micro"))
        caixa.addWidget(self.rotulo_caderno)

        # Uma porta só para o caderno. A exportação morava aqui e era a única
        # coisa que se podia fazer com o vocabulário salvo; agora ela é uma das
        # ações lá dentro, ao lado de ver, buscar e apagar.
        self.botao_caderno = Botao(
            f"{GLIFO_CADERNO}   Abrir caderno", variante="sutil",
            paleta=self.paleta, forma=self._atmosfera.forma,
        )
        self.botao_caderno.setFont(self.fonte("corpo_forte"))
        self.botao_caderno.setToolTip(
            "Ver, buscar e exportar o vocabulário salvo (Ctrl+B)"
        )
        self.botao_caderno.clicked.connect(self.abrir_caderno)
        caixa.addWidget(self.botao_caderno)

        self.botao_historico = Botao(
            "◷   Histórico", variante="sutil",
            paleta=self.paleta, forma=self._atmosfera.forma,
        )
        self.botao_historico.setFont(self.fonte("corpo_forte"))
        self.botao_historico.setToolTip(
            "Reler as conversas de sessões anteriores — tudo fica só neste computador"
        )
        self.botao_historico.clicked.connect(self.abrir_historico)
        caixa.addWidget(self.botao_historico)

    def _montar_palco(self) -> None:
        coluna = QVBoxLayout(self.palco)
        coluna.setContentsMargins(24, 24, 24, 24)
        coluna.setSpacing(16)

        barra = QHBoxLayout()
        barra.setSpacing(16)
        self.pilula = Pilula()
        self.pilula.setFont(self.fonte("micro"))
        barra.addWidget(self.pilula)
        self.medidor = Medidor()
        self.medidor.setToolTip(
            "Nível do seu microfone. O risco marca onde o portão de voz abre: "
            "à esquerda dele nada é transmitido. Parado = microfone errado ou bloqueado."
        )
        barra.addWidget(self.medidor)
        # Numa barra apertada é ESTE texto que cede — os botões ao lado não
        # têm como se abreviar.
        self.rotulo_meta = RotuloElidido(objectName="meta")
        self.rotulo_meta.setFont(self._fonte_mono("micro"))
        barra.addWidget(self.rotulo_meta)
        barra.addStretch(1)

        self.botao_mudo = Botao(
            f"{GLIFO_MIC_ATIVO}   Mudo", variante="acento", paleta=self.paleta,
            forma=self._atmosfera.forma,
        )
        self.botao_mudo.setFont(self.fonte("corpo_forte"))
        self.botao_mudo.clicked.connect(self.alternar_mudo)
        self.botao_mudo.setToolTip("Corta o envio do microfone. Nada é transmitido enquanto mudo.")
        self.botao_mudo.setEnabled(False)
        barra.addWidget(self.botao_mudo)

        self.botao_acao = Botao(
            variante="primario", paleta=self.paleta, forma=self._atmosfera.forma,
            largura_min=150,
        )
        self.botao_acao.setFont(self.fonte("corpo_forte"))
        self.botao_acao.clicked.connect(self.alternar_sessao)
        self.botao_acao.setToolTip("Iniciar ou encerrar a sessão de voz (F12)")
        barra.addWidget(self.botao_acao)
        coluna.addLayout(barra)

        self.conversa = Conversa(self)
        coluna.addWidget(self.conversa, 1)

        linha = QHBoxLayout()
        linha.setSpacing(8)
        self.entrada_texto = QLineEdit(objectName="entrada")
        self.entrada_texto.setPlaceholderText("Perguntar por texto…")
        self.entrada_texto.setFont(self.fonte("corpo"))
        self.entrada_texto.setToolTip("Perguntar sem falar. Ctrl+L traz o cursor para cá.")
        self.entrada_texto.setAccessibleName("Perguntar por texto")
        self.entrada_texto.returnPressed.connect(self.enviar_texto)
        linha.addWidget(self.entrada_texto, 1)
        self.botao_enviar = Botao(
            "Enviar", variante="sutil", paleta=self.paleta, forma=self._atmosfera.forma
        )
        self.botao_enviar.setFont(self.fonte("corpo_forte"))
        self.botao_enviar.clicked.connect(self.enviar_texto)
        linha.addWidget(self.botao_enviar)
        coluna.addLayout(linha)

    # ------------------------------------------------------------- Aparência

    def _trocar_jogo(self, nome: str) -> None:
        tema = theme_for(nome)
        if tema is self._tema:
            return
        # Fotografa o ambiente atual antes de qualquer repintura; a foto
        # dissolve por cima do tema novo ao final. Com a atmosfera desligada
        # não há dissolução — animação também é atmosfera.
        retrato = (
            self.grab()
            if self.isVisible() and self._intensidade_atmosfera > 0.0
            else None
        )
        # A persona temática ocupa sempre o índice 0; preservar o índice mantém
        # a escolha do jogador (temática continua temática, geral continua geral).
        indice = max(self.campo_persona.currentIndex(), 0)
        self._tema = tema
        self._atmosfera = atmosfera_de(nome)
        nomes = personas_for(tema)
        self.campo_persona.blockSignals(True)
        self.campo_persona.clear()
        self.campo_persona.addItems(nomes)
        self.campo_persona.setCurrentIndex(min(indice, len(nomes) - 1))
        self.campo_persona.blockSignals(False)
        self._aplicar_tema()
        self.conversa.repintar()
        if self._caderno is not None:
            self._caderno.aplicar_tema()
        self._registrar(f"Ambiente: {tema.name}", Tag.SISTEMA)
        if retrato is not None:
            TransicaoDeTema(self, retrato)

    def _aplicar_tema(self) -> None:
        t = self._tema
        self.setWindowTitle(t.window_title)
        self.barra_titulo.aplicar_tema()
        self.marca.setText(t.header_title)
        self.marca.setFont(self._ajustar_marca(t.header_title))
        self.submarca.setText(t.header_subtitle)
        self.submarca.setFont(self.fonte("micro"))

        ativa = self._worker is not None
        self.botao_acao.setText(t.stop_label if ativa else t.start_label)
        self.botao_acao.variante = "perigo" if ativa else "primario"

        self._cenario.definir(t, self._atmosfera)
        for botao in (
            self.botao_acao, self.botao_mudo, self.botao_caderno,
            self.botao_historico, self.botao_enviar,
            self.chip_alto_falante, self.chip_jogo, self.chip_busca,
        ):
            botao.forma = self._atmosfera.forma
            botao.update()

        self.medidor.definir_cores(
            primary=t.primary, accent=t.accent, alert=t.alert,
            apagada=design.elevar(t.screen, 0.16, t.primary),
            # Neutro de propósito: o risco é uma marca de régua, não um estado.
            # Na cor do tema competiria com as barras vivas, que são o dado.
            limiar=t.text_muted,
        )
        self.pilula.setFont(self.fonte("micro"))
        self.setStyleSheet(self._folha())
        self._posicionar_veu()
        for campo in self.campos.values():
            campo.definir_cor_seta(t.text_muted)
        self._atualizar_pilula()
        self._campainha.aplicar_tema()
        if self._capsula is not None:
            self._capsula.aplicar_tema()
        if hasattr(self, "_sobreposicao"):
            self._sobreposicao.raise_()
        self.update()

    def _folha(self) -> str:
        """Folha de estilo derivada do tema — o equivalente ao repintar."""
        t = self._tema
        raio = {"chanfrada": 3, "reta": 2}.get(self._atmosfera.forma, 8)
        return f"""
        QWidget {{ color: {t.primary}; }}
        #lateral, #rolagemLateral, #colunaLateral, #rodapeLateral {{
            background: {_rgba(t.surface, 0.90)};
        }}
        #colunaLateral {{ border-right: 1px solid {t.border}; }}
        /* O caderno é ancorado; o fio o separa dos ajustes que rolam por trás. */
        #rodapeLateral {{ border-top: 1px solid {t.border}; }}
        /* O palco é transparente de propósito: o que aparece atrás dele é o
           cenário pintado por paintEvent. */
        #palco {{ background: transparent; }}

        #marca    {{ color: {t.primary}; }}
        #submarca {{ color: {t.text_muted}; }}
        #secao    {{ color: {t.text_muted}; letter-spacing: 1px; }}
        #rotuloCampo, #meta {{ color: {t.text_muted}; }}
        #regua    {{ background: {t.border}; }}
        #caderno  {{ color: {t.info_text}; }}

        {css_campo_selecao(t, raio, _rgba)}

        /* Translúcido para a atmosfera atravessar a superfície da conversa —
           é o que dá profundidade sem competir com a leitura. O raio acompanha
           a forma do tema: um painel de canto redondo no meio de uma interface
           chanfrada é a única peça que denuncia que o tema é uma camada de
           tinta, e não o material da janela. */
        #conversa, #fundoConversa {{
            background: {_rgba(t.surface, 0.62)}; border-radius: {raio + 4}px;
        }}
        QScrollArea {{ border: none; }}
        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 6px 2px; }}
        QScrollBar::handle:vertical {{
            background: {t.border}; border-radius: 4px; min-height: 40px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {t.border_forte}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height: 0px; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

        QLineEdit#entrada {{
            background: {_rgba(t.surface_alta, 0.92)}; color: {t.primary};
            border: 1px solid transparent; border-radius: {raio + 2}px;
            padding: 12px 14px; selection-background-color: {t.selection};
        }}
        QLineEdit#entrada:focus {{ border-color: {t.border_forte}; }}
        """

    def _ajustar_atmosfera(self, escolha: str) -> None:
        self._intensidade_atmosfera = NIVEIS_ATMOSFERA.get(escolha, 1.0)
        self._cenario.definir_intensidade(self._intensidade_atmosfera)
        self._cenario.movimento = self._intensidade_atmosfera > 0.0
        self._sincronizar_animacao()
        # O controle é de ACESSIBILIDADE, não de gosto: quem o baixa por causa
        # de cintilação ou baixa visão precisa que ele valha em toda superfície
        # do programa. O caderno tem cenário próprio (sem relógio de quadros) e
        # ficava de fora — desligar a atmosfera na janela principal continuava
        # entregando varredura, grão e vinheta em intensidade cheia lá dentro,
        # porque `movimento = False` só suprime as camadas VIVAS.
        if self._caderno is not None:
            self._caderno.definir_intensidade(self._intensidade_atmosfera)
        self.update()
        self._sobreposicao.update()

    def _aquecer_sessao(self) -> None:
        """Carrega o SDK do Gemini fora do caminho da partida.

        ``google.genai`` custa cerca de 1.35 s para importar — 81% do tempo
        até a janela aparecer — e nada nele é tocado antes de o jogador clicar
        em INICIAR. Ele saiu do topo do módulo; se ficasse apenas adiado até o
        clique, o custo apenas mudaria de lugar e cairia no pior momento
        possível, congelando a interface justo quando se pede uma sessão.
        Carregar numa thread enquanto a pessoa escolhe jogo e persona resolve
        os dois: a janela abre na hora e o SDK já está pronto no clique.

        Não há corrida: o import de Python é protegido por trava, e a chamada
        em ``iniciar_sessao`` simplesmente encontra o módulo pronto no cache —
        ou espera esta thread terminar, se o clique vier antes.
        """
        def carregar() -> None:
            try:
                import pipboy.session  # noqa: F401
            except Exception:
                LOGGER.debug("Pré-carga do SDK falhou.", exc_info=True)

        threading.Thread(target=carregar, name="preload-sdk", daemon=True).start()

    def _sincronizar_animacao(self) -> None:
        """Liga o relógio de quadros só quando ele tem para quem desenhar.

        Este programa foi feito para ficar aberto ATRÁS de um jogo, e o relógio
        nunca olhava se a janela estava visível: minimizado, ele seguia
        repintando a sobreposição — grão, varredura e partículas sobre a área
        inteira — trinta vezes por segundo, disputando CPU justamente com o
        jogo que o usuário está jogando. A atmosfera é enfeite; quadro que
        ninguém vê é só calor.
        """
        deve_animar = (
            self._intensidade_atmosfera > 0.0
            and self.isVisible()
            and not self.isMinimized()
        )
        if deve_animar:
            if not self._quadros.isActive():
                # Recomeça o relógio do zero: sem isto o primeiro dt depois de
                # restaurar a janela seria o tempo inteiro que ela passou oculta.
                self._ultimo_quadro = self._cronometro.elapsed() / 1000.0
                self._quadros.start(33)
        else:
            self._quadros.stop()

    def changeEvent(self, evento: Any) -> None:
        super().changeEvent(evento)
        if evento.type() == QEvent.Type.WindowStateChange:
            self._sincronizar_animacao()
            if hasattr(self, "barra_titulo"):
                self.barra_titulo.sincronizar_estado()
            if hasattr(self, "_grips"):
                maximizada = bool(
                    self.windowState()
                    & (Qt.WindowState.WindowMaximized | Qt.WindowState.WindowFullScreen)
                )
                self._grips.definir_ativo(not maximizada)

    def hideEvent(self, evento: Any) -> None:
        super().hideEvent(evento)
        self._sincronizar_animacao()

    def showEvent(self, evento: Any) -> None:
        super().showEvent(evento)
        self._sincronizar_animacao()
        # Cantos arredondados e sombra do Windows 11: o DWM precisa do winId,
        # que só existe com a janela criada — daí ficar aqui e não no arranque.
        aplicar_cantos_do_sistema(self)
        if not self._ja_apareceu:
            self._ja_apareceu = True
            # O aparecimento tem a mesma cortesia do resto: um fade curto em
            # vez de um estalo — a menos que a atmosfera esteja desligada.
            if self._intensidade_atmosfera > 0.0:
                self.setWindowOpacity(0.0)
                surgimento = QPropertyAnimation(self, b"windowOpacity", self)
                surgimento.setDuration(240)
                surgimento.setStartValue(0.0)
                surgimento.setEndValue(1.0)
                surgimento.setEasingCurve(QEasingCurve.Type.OutCubic)
                surgimento.start(
                    QPropertyAnimation.DeletionPolicy.DeleteWhenStopped
                )

    # ---------------------------------------------------------------- Cenário

    def paintEvent(self, _evento: Any) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._cenario.pintar_fundo(pintor, self.width(), self.height())
        pintor.end()

    def _posicionar_veu(self, *_args: Any) -> None:
        """Cola o véu no pé da rolagem e o esconde quando ela acabou."""
        if not hasattr(self, "_veu"):
            return
        viewport = self.rolagem_lateral.viewport()
        barra = self.rolagem_lateral.verticalScrollBar()
        self._veu.setGeometry(
            0, viewport.height() - Desvanecer.ALTURA,
            viewport.width(), Desvanecer.ALTURA,
        )
        self._veu.setVisible(barra.value() < barra.maximum() - 2)
        self._veu.raise_()

    def resizeEvent(self, evento: Any) -> None:
        super().resizeEvent(evento)
        self._posicionar_veu()
        if hasattr(self, "_sobreposicao"):
            self._sobreposicao.setGeometry(self.rect())
            self._sobreposicao.raise_()
        if hasattr(self, "_grips"):
            self._grips.reposicionar()

    # --------------------------------------------------------------- Relógios

    def _iniciar_relogios(self) -> None:
        # Fila de eventos da sessão. Mesmo intervalo da versão anterior.
        self._bomba = QTimer(self)
        self._bomba.timeout.connect(self._drenar_eventos)
        self._bomba.start(UI_POLL_INTERVAL_MS)

        # Medidor de nível: precisa acompanhar a fala, não o relógio. Só corre
        # durante a sessão — fora dela leria zero dezesseis vezes por segundo.
        self._pulso = QTimer(self)
        self._pulso.timeout.connect(self._atualizar_medidor)

        # Relógio e consumo da sessão.
        self._tique = QTimer(self)
        self._tique.timeout.connect(self._atualizar_meta)
        self._tique.start(500)

        # Animação do cenário. 33 ms ≈ 30 quadros por segundo, que basta para
        # partícula e tremulação e deixa folga de CPU para o áudio.
        self._quadros = QTimer(self)
        self._quadros.timeout.connect(self._quadro_cenario)
        self._quadros.start(33)

        # Sonda de jogo: meio minuto entre olhadas é rápido o bastante para
        # quem acabou de abrir o jogo e lento o bastante para ninguém notar.
        self._sonda_jogo = QTimer(self)
        self._sonda_jogo.timeout.connect(self._sondar_jogo)
        self._sonda_jogo.start(30_000)
        QTimer.singleShot(1_500, self._sondar_jogo)  # e uma olhada logo ao abrir

    def _quadro_cenario(self) -> None:
        agora = self._cronometro.elapsed() / 1000.0
        # O passo é limitado: se a janela ficou minimizada por um minuto, a
        # diferença acumulada teleportaria toda partícula para fora da tela.
        dt = min(0.1, max(0.0, agora - self._ultimo_quadro))
        self._ultimo_quadro = agora
        self._cenario.avancar(dt)
        self._sobreposicao.update()

    def _atualizar_medidor(self) -> None:
        self.medidor.definir_ativo(self.sessao_ativa)
        self.medidor.definir_nivel(self.nivel_entrada)
        self.medidor.definir_limiar(self.limiar_entrada)

    def _atualizar_meta(self) -> None:
        if self._worker is None:
            self.rotulo_meta.definir_texto("")
            return
        decorrido = int(time.monotonic() - self._inicio_sessao)
        partes = [f"{decorrido // 60:02d}:{decorrido % 60:02d}"]
        if self._mudo:
            partes.append("MUDO")
        if self.chip_jogo.isChecked():
            partes.append("OUVINDO O JOGO")
        if self._tokens:
            partes.append(f"{self._tokens:,} tokens".replace(",", "."))
        self.rotulo_meta.definir_texto("   ·   ".join(partes))

    # ------------------------------------------------------------- Eventos

    def _drenar_eventos(self) -> None:
        try:
            while True:
                self._tratar_evento(self._eventos.get_nowait())
        except queue.Empty:
            pass

    def _da_sessao_atual(self, evento: UiEvent) -> bool:
        """O evento veio da sessão que está no ar?

        Eventos de atalho global e da sonda de jogo nascem com ``session_id``
        zero e não pertencem a sessão nenhuma — passam sempre.

        Os demais precisam da conferência. Encerrar uma sessão pede a parada e
        devolve o controle na hora, mas a thread pode levar até
        SHUTDOWN_TIMEOUT_SECONDS para morrer, e nesse intervalo o jogador já
        pode ter começado outra. Sem o filtro, a fala final da sessão velha
        entrava na conversa da nova — e, pior, ia parar no histórico gravada
        sob o id da sessão errada, que é uma corrupção silenciosa de um dado
        que o programa promete guardar para sempre.
        """
        if evento.session_id == 0:
            return True
        return self._worker is not None and evento.session_id == self._worker.session_id

    def _tratar_evento(self, evento: UiEvent) -> None:
        tipo = evento.kind
        if tipo is UiEventKind.LOG:
            if self._da_sessao_atual(evento):
                self._registrar(evento.text, evento.tag, evento.author)
            else:
                # Não é ruído descartável: some da tela, fica no registro.
                LOGGER.info("Fala de sessão encerrada (%s): %s", evento.session_id, evento.text)
        elif tipo is UiEventKind.STATUS:
            if self._da_sessao_atual(evento):
                self._definir_estado(evento.text, evento.color_role)
        elif tipo is UiEventKind.VOCAB_ADDED:
            self.caderno_mudou()
            self._campainha.tocar("vocab")
        elif tipo is UiEventKind.USAGE:
            if self._da_sessao_atual(evento):
                self._tokens = int(evento.payload or 0)
        elif tipo is UiEventKind.START_REQUEST:
            self.alternar_sessao()
        elif tipo is UiEventKind.STOP_REQUEST:
            self.encerrar_sessao()
        elif tipo is UiEventKind.TOGGLE_MUTE_REQUEST:
            self.alternar_mudo()
        elif tipo is UiEventKind.TOGGLE_GAME_AUDIO_REQUEST:
            self.chip_jogo.setChecked(not self.chip_jogo.isChecked())
        elif tipo is UiEventKind.SESSION_FINISHED:
            self._sessao_encerrada(evento.session_id)
        elif tipo is UiEventKind.GAME_DETECTED:
            self._jogo_detectado_mudou(evento.text)
        # A sessão seguiu sem busca; o chip marcado passaria a mentir. Ele é
        # desmarcado de verdade — e não só visualmente — para que a próxima
        # sessão não repita a recusa. A explicação já chegou ao registro pelo
        # LOG que a sessão publicou junto.
        elif tipo is UiEventKind.WEB_SEARCH_DISABLED and self._da_sessao_atual(evento):
            self.chip_busca.setChecked(False)

    def _jogo_detectado_mudou(self, nome: str) -> None:
        """Reage à sonda de processos — trocando o ambiente no máximo UMA vez.

        A regra que impede o cabo de guerra com o jogador: só a MUDANÇA de
        detecção age. Se ele detectar o Fallout, trocar, e o jogador escolher
        outro ambiente em seguida, a sonda seguirá vendo o mesmo Fallout — e
        mesmice não é mudança, então a escolha manual fica de pé.
        """
        if nome == self._jogo_detectado:
            return
        self._jogo_detectado = nome
        if not nome or self._worker is not None:
            return  # nada rodando, ou sessão ativa (campos travados)
        if self.campo_jogo.currentText() == nome:
            return
        indice = self.campo_jogo.findText(nome)
        if indice < 0:
            return
        self.campo_jogo.setCurrentIndex(indice)  # dispara _trocar_jogo
        self._registrar(f"{nome} em execução — o ambiente se ajustou sozinho.", Tag.SISTEMA)

    def _sondar_jogo(self) -> None:
        """Pergunta ao sistema, numa thread própria, que jogo está aberto.

        O tasklist leva algumas centenas de milissegundos; rodá-lo na thread
        da interface congelaria a animação. A resposta volta pela mesma fila
        de eventos que a sessão usa — nenhum widget é tocado fora daqui.
        """
        if self._worker is not None:
            return  # durante a sessão os campos estão travados: sondar é ruído

        def trabalho() -> None:
            try:
                from ..deteccao import jogo_em_execucao

                nome = jogo_em_execucao() or ""
            except Exception:
                return  # conveniência não derruba nada
            self._eventos.put(UiEvent(UiEventKind.GAME_DETECTED, text=nome))

        threading.Thread(target=trabalho, name="detector-jogo", daemon=True).start()

    def _registrar(self, texto: str, tag: Tag = Tag.ASSISTENTE, autor: str = "") -> None:
        self.conversa.adicionar(texto, tag, autor)
        if tag is Tag.ERRO:
            self._campainha.tocar("erro")
        # A conversa em si — não os avisos do sistema — também vai para o
        # histórico, enquanto houver sessão aberta para recebê-la.
        if self._sessao_historico is not None and tag in (
            Tag.USUARIO, Tag.ASSISTENTE, Tag.VOCAB
        ):
            with contextlib.suppress(Exception):
                self._historico.registrar_fala(
                    self._sessao_historico, autor=autor, tag=tag.value, texto=texto
                )

    # --------------------------------------------------------------- Estado

    def _definir_estado(self, texto: str, papel: str) -> None:
        self._estado_texto, self._estado_papel = texto, papel
        self._atualizar_pilula()

    def _atualizar_pilula(self) -> None:
        # Texto vazio é o sentinela de "parado", e não a string "OFFLINE":
        # resolvido aqui, ele vira o ocioso do tema — AGUARDANDO O MACULADO no
        # Elden Ring, AGUARDANDO ORDENS no tático — e se atualiza sozinho ao
        # trocar de jogo, porque _aplicar_tema passa por este método.
        texto = self.estado_texto
        papel = self._estado_papel
        self.pilula.definir(
            texto, getattr(self._tema, papel), self._tema.screen,
            # 'accent' é sempre estado de passagem — conectando, renovando,
            # encerrando. É o próprio papel publicado pela sessão que
            # distingue, sem interpretar texto.
            pulsando=papel == "accent",
        )

    def _atualizar_caderno(self) -> None:
        total = self._store.total()
        texto = f"Caderno · {total} termos"
        vencidas = self._store.pendentes()
        if vencidas:
            texto += f"\n{vencidas} para revisar"
        self.rotulo_caderno.setText(texto)

    def _definir_controles(self, ativa: bool, pode_parar: bool = True) -> None:
        for campo in self.campos.values():
            if campo is not self.campo_atmosfera:
                campo.setEnabled(not ativa)
        for chip in (self.chip_alto_falante, self.chip_busca):
            chip.setEnabled(not ativa)
        self.botao_acao.variante = "perigo" if ativa else "primario"
        self.botao_acao.setText(
            self._tema.stop_label if ativa else self._tema.start_label
        )
        self.botao_acao.setEnabled(not (ativa and not pode_parar))
        self.botao_mudo.setEnabled(ativa)
        if ativa and not self._pulso.isActive():
            self._pulso.start(60)
        elif not ativa and self._pulso.isActive():
            self._pulso.stop()
        self._atualizar_medidor()

    # ----------------------------------------------------------- Preferências

    def _aplicar_preferencias(self) -> None:
        def selecionar(campo: CampoSelecao, valor: str, padrao: str) -> None:
            opcoes = [campo.itemText(i) for i in range(campo.count())]
            escolhido = valor if valor in opcoes else (padrao if padrao in opcoes else opcoes[0])
            campo.setCurrentText(escolhido)

        p = self._prefs
        # O jogo vem primeiro: ele determina a lista de personas.
        selecionar(self.campo_jogo, p.jogo, DEFAULT_JOGO)
        selecionar(self.campo_persona, p.persona, DEFAULT_PERSONA)
        selecionar(self.campo_voz, p.voz, DEFAULT_VOZ)
        selecionar(self.campo_nivel, p.nivel, DEFAULT_NIVEL)
        selecionar(self.campo_modo, p.modo, DEFAULT_MODO)
        selecionar(self.campo_entrada, p.dispositivo_entrada, "Padrão do sistema")
        selecionar(self.campo_saida, p.dispositivo_saida, "Padrão do sistema")
        self.chip_alto_falante.setChecked(p.saida_alto_falante)
        self.chip_busca.setChecked(p.busca_web)
        if HAS_LOOPBACK_SUPPORT and self._loopback:
            self.chip_jogo.setChecked(p.ouvir_jogo)
        # O caminho de volta é do NÚMERO para o rótulo. Um arquivo editado à mão
        # pode trazer um ganho fora da tabela; a tolerância aceita o ruído de
        # ponto flutuante e o resto cai no padrão em vez de deixar o campo
        # mostrando uma opção que não corresponde ao valor em uso.
        rotulo_ganho = next(
            (r for r, v in NIVEIS_GANHO_JOGO.items() if abs(v - p.ganho_jogo) < 1e-6),
            GANHO_JOGO_PADRAO,
        )
        selecionar(self.campo_ganho_jogo, rotulo_ganho, GANHO_JOGO_PADRAO)
        atmosfera = str(p.extras.get("atmosfera", "Completa"))
        selecionar(self.campo_atmosfera, atmosfera, "Completa")
        self._ajustar_atmosfera(self.campo_atmosfera.currentText())
        self._atualizar_caderno()

    def _salvar_preferencias(self) -> None:
        p = self._prefs
        p.persona = self.campo_persona.currentText()
        p.jogo = self.campo_jogo.currentText()
        p.voz = self.campo_voz.currentText()
        p.nivel = self.campo_nivel.currentText()
        p.modo = self.campo_modo.currentText()
        p.dispositivo_entrada = self.campo_entrada.currentText()
        p.dispositivo_saida = self.campo_saida.currentText()
        p.saida_alto_falante = self.chip_alto_falante.isChecked()
        p.ouvir_jogo = self.chip_jogo.isChecked()
        p.busca_web = self.chip_busca.isChecked()
        p.ganho_jogo = NIVEIS_GANHO_JOGO.get(
            self.campo_ganho_jogo.currentText(), DEFAULT_GAME_AUDIO_GAIN
        )
        p.extras["atmosfera"] = self.campo_atmosfera.currentText()
        g = self.geometry()
        p.extras["geometria"] = f"{g.width()},{g.height()},{g.x()},{g.y()}"
        p.save()

    # --------------------------------------------------------------- Atalhos

    def _registrar_atalhos(self) -> None:
        # Atalhos locais (janela em foco). F12/Esc só valem aqui.
        QShortcut(QKeySequence("F12"), self, activated=self.alternar_sessao)
        QShortcut(QKeySequence("Escape"), self, activated=self.encerrar_sessao)
        QShortcut(QKeySequence("Ctrl+B"), self, activated=self.abrir_caderno)
        QShortcut(QKeySequence("Ctrl+H"), self, activated=self.abrir_historico)
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self.revisar_agora)
        QShortcut(QKeySequence("Ctrl+M"), self, activated=self.entrar_modo_compacto)
        QShortcut(
            QKeySequence("Ctrl+L"), self,
            activated=lambda: (self.entrada_texto.setFocus(), self.entrada_texto.selectAll()),
        )

        if keyboard is None or not self._configuration.global_hotkeys_enabled:
            self._registrar(
                "Atalhos globais desativados; use F12/Esc com a janela em foco.", Tag.SISTEMA
            )
            return

        # Deliberadamente NÃO registramos Esc nem F12 globalmente: sequestrar
        # essas teclas no sistema inteiro quebra o menu de pausa do jogo — o
        # exato contexto em que este programa é usado.
        # Lista de pares, não dicionário. Chaveado pela COMBINAÇÃO, dois atalhos
        # configurados com a mesma tecla no .env colapsavam em um só antes de
        # qualquer código rodar — o segundo simplesmente não existia, sem erro,
        # sem aviso, e a tecla fazia a coisa errada para sempre.
        mapa = (
            (self._configuration.hotkey_toggle, UiEventKind.START_REQUEST),
            (self._configuration.hotkey_mute, UiEventKind.TOGGLE_MUTE_REQUEST),
            (self._configuration.hotkey_game_audio, UiEventKind.TOGGLE_GAME_AUDIO_REQUEST),
        )
        ja_usadas: set[str] = set()
        for combinacao, tipo in mapa:
            if not combinacao:
                continue
            if combinacao in ja_usadas:
                self._registrar(
                    f"Atalho global {combinacao} está repetido no .env; a segunda "
                    "atribuição foi ignorada.",
                    Tag.SISTEMA,
                )
                continue
            ja_usadas.add(combinacao)
            try:
                self._atalhos_globais.append(
                    keyboard.add_hotkey(
                        combinacao, lambda t=tipo: self._eventos.put(UiEvent(t))
                    )
                )
            except Exception:
                LOGGER.warning("Não foi possível registrar %s.", combinacao, exc_info=True)
                self._registrar(f"Atalho global {combinacao} indisponível.", Tag.SISTEMA)

    def _remover_atalhos(self) -> None:
        if keyboard is None:
            return
        for handle in self._atalhos_globais:
            with contextlib.suppress(Exception):
                keyboard.remove_hotkey(handle)
        self._atalhos_globais.clear()

    # ----------------------------------------------------------------- Ações

    def _configuracao_atual(self) -> SessionSettings:
        voz = self.campo_voz.currentText()
        return SessionSettings(
            persona_name=self.campo_persona.currentText(),
            game_name=self.campo_jogo.currentText(),
            voice_label=voz,
            voice_id=VOZES[voz],
            level_name=self.campo_nivel.currentText(),
            mode_name=self.campo_modo.currentText(),
            speaker_mode=self.chip_alto_falante.isChecked(),
            game_audio=self.chip_jogo.isChecked(),
            web_search=self.chip_busca.isChecked(),
        )

    def alternar_sessao(self) -> None:
        self.encerrar_sessao() if self._worker is not None else self.iniciar_sessao()

    def iniciar_sessao(self) -> None:
        if self._encerrando or self._worker is not None:
            return
        self._salvar_preferencias()
        self._contador_sessoes += 1
        self._mudo = False
        self._tokens = 0
        self.botao_mudo.setText(f"{GLIFO_MIC_ATIVO}   Mudo")
        self.botao_mudo.variante = "acento"

        from ..session import LiveSessionWorker

        worker = LiveSessionWorker(
            session_id=self._contador_sessoes,
            configuration=self._configuration,
            settings=self._configuracao_atual(),
            store=self._store,
            publish=self._eventos.put,
            input_device=self._indice_dispositivo(self.campo_entrada, self._entradas),
            output_device=self._indice_dispositivo(self.campo_saida, self._saidas),
            game_gain=self._prefs.ganho_jogo,
        )
        self._worker = worker
        self._inicio_sessao = time.monotonic()
        try:
            self._sessao_historico = self._historico.iniciar_sessao(
                jogo=self.campo_jogo.currentText(),
                modo=self.campo_modo.currentText(),
                nivel=self.campo_nivel.currentText(),
            )
            self._historico.marcar_atividade()
        except Exception:
            self._sessao_historico = None
            LOGGER.exception("Histórico indisponível — a sessão segue sem ele.")
        self._definir_controles(ativa=True)
        # Travar os chips faz o Qt entregar o foco ao vizinho seguinte, que
        # calha de ser "Ouvir o jogo": começar a sessão acendia um anel de foco
        # num interruptor qualquer da lateral. Agora que o anel é visível (ele
        # era recortado antes, e o problema passava despercebido), o destino
        # precisa ser deliberado — e o campo de texto é o que a pessoa mais
        # provavelmente quer em seguida.
        self.entrada_texto.setFocus()
        self._definir_estado("INICIANDO", "accent")
        worker.start()
        self._campainha.tocar("iniciar")

    def encerrar_sessao(self) -> None:
        if self._worker is None:
            return
        self._definir_controles(ativa=True, pode_parar=False)
        self._definir_estado("ENCERRANDO", "accent")
        self._worker.request_stop()

    def alternar_mudo(self) -> None:
        if self._worker is None:
            return
        self._mudo = not self._mudo
        self._worker.set_muted(self._mudo)
        self.botao_mudo.setText(
            f"{GLIFO_MIC_MUDO if self._mudo else GLIFO_MIC_ATIVO}   Mudo"
        )
        # "perigo", não "perigo_cheio": esta última nunca existiu em
        # componentes._cores, e uma variante desconhecida cai silenciosamente no
        # ramo "sutil" — o botão de mudo ficava cinza justamente no estado em
        # que precisa gritar que o microfone está cortado.
        self.botao_mudo.variante = "perigo" if self._mudo else "acento"
        self.botao_mudo.update()
        self._registrar(
            "Microfone silenciado." if self._mudo else "Microfone reativado.", Tag.SISTEMA
        )

    def _alternar_audio_do_jogo(self, desejado: bool) -> None:
        if self._worker is None:
            return
        efetivo = self._worker.set_game_audio(desejado)
        if desejado and not efetivo:
            self._registrar(
                "Captura do jogo indisponível nesta sessão. Marque a opção antes de "
                "iniciar para que o dispositivo de loopback seja aberto.",
                Tag.SISTEMA,
            )
            self.chip_jogo.blockSignals(True)
            self.chip_jogo.setChecked(False)
            self.chip_jogo.blockSignals(False)
        else:
            self._registrar(
                f"Áudio do jogo {'ativado' if efetivo else 'desativado'}.", Tag.SISTEMA
            )

    def enviar_texto(self) -> None:
        texto = self.entrada_texto.text().strip()
        if not texto:
            return
        if self._worker is None:
            self._registrar("Inicie uma sessão antes de enviar mensagens.", Tag.SISTEMA)
            return
        self.entrada_texto.clear()
        self._worker.send_text(texto)

    def abrir_caderno(self) -> None:
        """Abre (ou traz para a frente) o visualizador do caderno.

        Não é modal de propósito: consultar o que já foi aprendido no meio de
        uma conversa é exatamente o uso previsto, e um diálogo modal congelaria
        a janela principal — inclusive o botão de encerrar a sessão.
        """
        if self._caderno is None:
            self._caderno = JanelaCaderno(self, self._store)
        else:
            self._caderno.aplicar_tema()
        self._caderno.show()
        self._caderno.raise_()
        self._caderno.activateWindow()

    def revisar_agora(self) -> None:
        """Abre a revisão offline direto, sem passar pelo caderno (Ctrl+R).

        Quem já sabe que quer revisar não deveria ter que abrir uma janela
        para clicar num botão que abre outra. Se não há nada vencido, a
        própria tela de cartões explica — melhor que um atalho que não faz
        nada e deixa a pessoa achando que a tecla não funcionou.
        """
        from .revisao import JanelaRevisao

        JanelaRevisao(self, self._store, parent=self).exec()
        self.caderno_mudou()
        if self._caderno is not None:
            self._caderno.atualizar()

    def marcar_estudo(self) -> None:
        """Ponto único de 'hoje houve estudo' — sessão ou revisão offline."""
        with contextlib.suppress(Exception):
            self._historico.marcar_atividade()

    def sequencia_de_estudo(self) -> int:
        try:
            return self._historico.sequencia_atual()
        except Exception:
            return 0

    def entrar_modo_compacto(self) -> None:
        """Encolhe o programa a uma cápsula sempre-no-topo e esconde a janela.

        A sessão, os relógios e a fila de eventos continuam vivos — a cápsula
        é só outra vista do mesmo estado.
        """
        from .compacto import JanelaCompacta

        if getattr(self, "_capsula", None) is None:
            self._capsula = JanelaCompacta(self)
        self._capsula.mostrar()
        self.hide()

    def sair_modo_compacto(self) -> None:
        """Volta à janela completa — de onde quer que o pedido venha.

        ``showNormal`` só entra em cena para desminimizar: chamado sempre,
        ele também DESMAXIMIZA, e quem jogava com a janela maximizada a
        recebia de volta em tamanho normal depois de cada passagem pelo
        modo compacto. ``show()`` sozinho devolve a janela ao estado em que
        ela estava antes de se esconder.
        """
        if self._capsula is not None and self._capsula.isVisible():
            self._capsula.recolher()
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def abrir_historico(self) -> None:
        """Abre o visualizador de sessões passadas. Não modal, como o caderno."""
        from .historico import JanelaHistorico

        if self._visor_historico is None:
            self._visor_historico = JanelaHistorico(self, self._historico)
        else:
            self._visor_historico.aplicar_tema()
            self._visor_historico.recarregar()
        self._visor_historico.show()
        self._visor_historico.raise_()
        self._visor_historico.activateWindow()

    def periodos_de_conversa(self) -> list[tuple[int, str, str]]:
        """``(id, início, fim)`` das sessões gravadas, para casar com uma palavra.

        O caderno usa isto para decidir, de uma vez para todos os cartões
        visíveis, quais deles têm uma conversa para onde voltar.
        """
        try:
            return self._historico.periodos()
        except Exception:
            LOGGER.exception("Períodos do histórico indisponíveis.")
            return []

    def abrir_conversa(self, sessao_id: int, termo: str = "") -> None:
        """Abre o histórico na sessão dada, marcando onde ``termo`` foi ensinado."""
        self.abrir_historico()
        visor = self._visor_historico
        if visor is not None and not visor.abrir_por_id(sessao_id, destaque=termo):
            avisar(
                self,
                "Conversa indisponível",
                "A conversa em que esta palavra foi ensinada não está mais no "
                "histórico. A palavra continua no caderno.",
            )

    def caderno_mudou(self, aviso: str = "") -> None:
        """Ponto único de reação a uma escrita no caderno, venha de onde vier.

        A sessão publica VOCAB_ADDED quando o modelo salva uma palavra; o
        visualizador chama isto quando o jogador apaga uma. Os dois precisam
        atualizar o mesmo contador na lateral.
        """
        self._atualizar_caderno()
        if aviso:
            self._registrar(aviso, Tag.SISTEMA)

    def exportar_vocabulario(self) -> None:
        if self._store.total() == 0:
            avisar(
                self, "Caderno vazio",
                "Nada foi salvo ainda. Inicie uma sessão e pergunte o significado "
                "de qualquer palavra em inglês: o assistente anota sozinho.",
            )
            return
        destino, _ = QFileDialog.getSaveFileName(
            self, "Exportar vocabulário", "vocabulario_pipboy.txt",
            "Anki / TSV (*.txt);;Markdown (*.md)",
        )
        if not destino:
            return
        caminho = Path(destino)
        try:
            if caminho.suffix.lower() == ".md":
                total = self._store.exportar_markdown(caminho)
            else:
                total = self._store.exportar_csv(caminho)
        except OSError as erro:
            avisar(self, "Falha ao exportar", str(erro), erro=True)
            return
        self._registrar(f"{total} termos exportados para {caminho.name}.", Tag.SISTEMA)

    # ------------------------------------------------------------ Encerramento

    def _sessao_encerrada(self, session_id: int) -> None:
        if self._worker is None or self._worker.session_id != session_id:
            return
        self._worker = None
        self._mudo = False
        if self._sessao_historico is not None:
            with contextlib.suppress(Exception):
                # Sessão sem uma fala sequer não é história — é ruído.
                self._historico.descartar_sessao_vazia(self._sessao_historico)
            self._sessao_historico = None
        self._definir_controles(ativa=False)
        self._definir_estado("", "secondary")
        self._registrar("Sessão encerrada.", Tag.SISTEMA)
        self._campainha.tocar("encerrar")
        self._atualizar_caderno()
        if self._encerrando:
            # O relógio de espera cumpriu o papel: a sessão soltou o microfone
            # sozinha, antes do prazo. Sem parar aqui ele seguia disparando a
            # cada 75 ms sobre uma janela já fechada até se corrigir no tique
            # seguinte — funciona por acidente, e acidente não é contrato.
            espera = getattr(self, "_espera", None)
            if espera is not None:
                espera.stop()
            self.close()

    def closeEvent(self, evento: Any) -> None:
        """Fecha só depois de a sessão soltar o microfone.

        Derrubar a janela com a thread de áudio viva deixa o dispositivo preso
        até o processo morrer — e no Windows isso significa que o próximo
        programa a pedir o microfone recebe um erro.
        """
        if self._worker is not None and self._worker.is_alive:
            if not self._encerrando:
                self._encerrando = True
                self._salvar_preferencias()
                self.encerrar_sessao()
                self._prazo_encerramento = time.monotonic() + SHUTDOWN_TIMEOUT_SECONDS
                self._espera = QTimer(self)
                self._espera.timeout.connect(self._verificar_encerramento)
                self._espera.start(75)
            evento.ignore()
            return

        if not self._encerrando:
            self._salvar_preferencias()
        self._encerrando = True
        self._remover_atalhos()
        # O visualizador do caderno consulta o banco a cada repintura. Fechá-lo
        # ANTES de fechar a conexão evita que uma janela sobrevivente tente ler
        # de um sqlite3 já encerrado.
        if self._caderno is not None:
            self._caderno.close()
            self._caderno = None
        if self._visor_historico is not None:
            self._visor_historico.close()
            self._visor_historico = None
        if self._capsula is not None:
            self._capsula.close()
            self._capsula = None
        bandeja = getattr(self, "_bandeja", None)
        if bandeja is not None:
            bandeja.hide()  # sem isto o ícone fantasma fica na bandeja
            self._bandeja = None
        self._campainha.encerrar()
        try:
            self._store.close()
        except Exception:
            LOGGER.warning("Falha ao fechar o caderno.", exc_info=True)
        try:
            self._historico.close()
        except Exception:
            LOGGER.warning("Falha ao fechar o histórico.", exc_info=True)
        evento.accept()

    def _verificar_encerramento(self) -> None:
        if self._worker is None or not self._worker.is_alive:
            self._espera.stop()
            self.close()
            return
        if time.monotonic() >= self._prazo_encerramento:
            LOGGER.warning("A thread de sessão não encerrou dentro do prazo.")
            self._espera.stop()
            self._worker = None
            self.close()
