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
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSizeF,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QPainter,
    QPainterPath,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QWidget,
)

from .. import design
from ..config import (
    AppConfiguration,
    Preferences,
    data_directory,
    movimento_reduzido,
)
from ..constants import (
    SHUTDOWN_TIMEOUT_SECONDS,
)
from ..events import Tag, UiEvent, UiEventKind
from ..historico import HistoricoStore
from ..profiles import (
    DEFAULT_JOGO,
    DEFAULT_MODO,
    DEFAULT_NIVEL,
    DEFAULT_PERSONA,
    DEFAULT_VOZ,
    VOZES,
    SessionSettings,
    personas_for,
)
from ..themes import GameTheme, paleta_de, theme_for
from ..vocabulary import FILTRO_REVISAR, VocabularyStore
from . import montagem
from .atalhos import Atalhos, globais_disponiveis
from .atmosfera import Cenario, atmosfera_de
from .caderno import JanelaCaderno
from .componentes import (
    Botao,
    CampoSelecao,
    Desvanecer,
    LuzDoCursor,
    TransicaoDeTema,
    acender_borda,
    definir_fonte_da_luz,
    definir_movimento_reduzido,
)
from .cursor import CampoMagnetico, RastreadorDeCursor, abraco_de, centro_de
from .dialogo import avisar
from .estilo import RAIO_PADRAO, RAIO_POR_FORMA, folha_da_janela
from .moldura import (
    GripsRedimensionamento,
    aplicar_cantos_do_sistema,
)
from .montagem import (
    DICA_OUVIR_O_JOGO,
    DICA_SEM_LOOPBACK,
    ESCALA_TEXTO_PADRAO,
    ESCALAS_TEXTO,
    GANHO_JOGO_PADRAO,
    GLIFO_MIC_ATIVO,
    GLIFO_MIC_MUDO,
    NIVEIS_ATMOSFERA,
    NIVEIS_GANHO_JOGO,
)
from .movimento import SinalFlutuante
from .paleta import PALAVRAS_DO_CADERNO, Comando, Paleta
from .preferencias import Escolha, Marca, VinculoDePreferencias
from .relogios import Batidas, Relogios
from .tela_inicial import Resumo

if TYPE_CHECKING:  # pragma: no cover
    # O módulo de áudio puxa o PyAudio, que custa 175 ms para importar. Ele não
    # entra no caminho da abertura: só o nome do tipo é preciso aqui, e com
    # ``from __future__ import annotations`` isso não custa import nenhum.
    from ..audio import Device
    from ..session import LiveSessionWorker

LOGGER = logging.getLogger("pip_boy.interface")


FONTES_MONO: tuple[str, ...] = ("Cascadia Mono", "Consolas", "Courier New", "Courier")


class Sobreposicao(QWidget):
    """Vidro do aparelho: a camada que fica na frente de tudo.

    Transparente a eventos de mouse, para não roubar cliques. É o único widget
    que repinta a cada quadro. ``pintar_bordas`` desenha, por cima do vidro, os
    contornos que a luz do cursor acende nos painéis da janela.
    """

    def __init__(
        self,
        cenario: Cenario,
        parent: QWidget,
        pintar_bordas: Callable[[QPainter], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._cenario = cenario
        self._pintar_bordas = pintar_bordas
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _evento: Any) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._cenario.pintar_sobreposicao(pintor, self.width(), self.height())
        if self._pintar_bordas is not None:
            self._pintar_bordas(pintor)
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
        # Falhas de escrita já anunciadas nesta execução. Ver _falha_de_gravacao.
        self._falhas_anunciadas: set[str] = set()
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
        # A mesma régua para os botões de todas as janelas: sem atmosfera, a luz
        # dentro deles fica parada e nenhum é puxado pelo cursor.
        definir_movimento_reduzido(lambda: self._intensidade_atmosfera <= 0.0)
        definir_fonte_da_luz(self, self._luz_do_cursor)
        # O total que a lateral mostra agora. É contra ele que uma palavra
        # salva pela sessão se mede, para o sinal dizer QUANTAS entraram.
        self._total_no_caderno = 0
        self.sinal_do_caderno: SinalFlutuante | None = None
        # Nasce antes de qualquer widget: `fonte()` é chamada durante a
        # montagem, e ela lê este fator.
        self._escala_texto = 1.0
        # A atmosfera nasceu desligada por causa do Windows, e não por escolha?
        # Só para poder dizer isso ao jogador uma vez, no registro.
        self._atmosfera_veio_do_sistema = False

        self._tema: GameTheme = theme_for(self._prefs.jogo)
        self._atmosfera = atmosfera_de(self._tema.name)
        self._instaladas = set(QFontDatabase.families())
        self._mono = self._primeira_instalada(FONTES_MONO)

        self._cenario = Cenario()

        self._entradas: list[Device] = []
        self._saidas: list[Device] = []
        self._loopback: Device | None = None
        self._carregar_dispositivos()

        self._configurar_janela()
        self._montar()
        self._sobreposicao = Sobreposicao(self._cenario, self, self._pintar_bordas_de_luz)
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
        self._relogios = Relogios(
            self,
            Batidas(
                drenar_eventos=self._drenar_eventos,
                atualizar_medidor=self._atualizar_medidor,
                atualizar_meta=self._atualizar_meta,
                avancar_cenario=self._avancar_cenario,
                sondar_jogo=self._sondar_jogo,
                deve_animar=self._deve_animar,
                interagindo=lambda: self._cenario.seguindo_cursor,
                frequencia_da_tela=self._frequencia_da_tela,
            ),
        )
        self._relogios.iniciar()
        # Depois dos relógios: o primeiro movimento já pede um quadro.
        self._campo_magnetico = CampoMagnetico(self)
        self._alvo_do_anel: QWidget | None = None
        self._rastreador = RastreadorDeCursor(
            self, self._cursor_mudou, self._clique, self._foco_mudou
        )
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

        # O modelo, a chave mascarada e os atalhos globais eram as duas primeiras
        # anotações da conversa, sozinhas no pé de um painel vazio. Moram agora
        # no rodapé da tela inicial (ver resumo_inicial). Este aviso continua
        # sendo anotação: é notícia de uma vez, não apresentação.
        if self._atmosfera_veio_do_sistema:
            # Sem este aviso, a primeira execução numa máquina com animação
            # desligada parece um programa sem a aparência que ele anuncia —
            # e o jogador não teria como ligar o que não sabe que existe.
            self._registrar(
                "O Windows está configurado para reduzir animações, então a atmosfera "
                "começou DESLIGADA. Para ver o ambiente completo, mude 'Atmosfera do "
                "jogo' na coluna ao lado — a escolha fica gravada.",
                Tag.SISTEMA,
            )

    # ------------------------------------------------------------ Dispositivos

    def _carregar_dispositivos(self) -> None:
        """Enumera os dispositivos de áudio numa thread, fora do arranque.

        Medido nesta máquina, com cache quente: importar o módulo de áudio
        (que puxa o PyAudio) custa 175 ms e enumerar custa outros 122 ms —
        praticamente trezentos milissegundos com a tela em branco, antes de a
        janela existir. É o mesmo problema que o SDK do Gemini já teve, e a
        resposta é a mesma que ``_aquecer_sessao`` deu a ele: sair do caminho
        da abertura e voltar pela fila de eventos quando estiver pronto.

        As duas caixas nascem com "Padrão do sistema" — que é uma opção
        legítima, e não um espaço reservado — e ganham o resto ao chegar. Quem
        clicar em INICIAR antes disso abre a sessão nos aparelhos padrão do
        Windows, exatamente como quem nunca mexeu nas caixas.
        """

        def trabalho() -> None:
            try:
                from ..audio import list_devices

                achados = list_devices()
            except Exception:
                LOGGER.exception("Falha ao listar dispositivos de áudio.")
                return
            self._eventos.put(UiEvent(UiEventKind.DEVICES_READY, payload=achados))

        threading.Thread(target=trabalho, name="listar-dispositivos", daemon=True).start()

    def _dispositivos_prontos(self, achados: Any) -> None:
        """Recebe a lista da thread e recompõe o que dependia dela."""
        self._entradas, self._saidas, self._loopback = achados
        for campo, lista, destino in (
            (self.campo_entrada, self._entradas, "dispositivo_entrada"),
            (self.campo_saida, self._saidas, "dispositivo_saida"),
        ):
            escolhido = campo.currentText()
            campo.blockSignals(True)
            campo.clear()
            campo.addItems(["Padrão do sistema"] + [d.label for d in lista])
            campo.setCurrentText(escolhido)
            campo.blockSignals(False)
            self._preferencias.reaplicar(destino)
        tem_loopback = self._loopback is not None
        self.chip_jogo.setEnabled(tem_loopback and self._worker is None)
        self.chip_jogo.setToolTip(
            DICA_OUVIR_O_JOGO if tem_loopback else DICA_SEM_LOOPBACK
        )
        if tem_loopback:
            self._preferencias.reaplicar("ouvir_jogo")

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

        Ponto de estrangulamento de TODA a tipografia do programa — inclusive
        das janelas satélites, que recebem a janela como provedor. É por isso
        que o tamanho do texto é um fator aplicado aqui, e não uma rampa
        alternativa a manter em paralelo.
        """
        tipo = design.TIPO[papel]
        familia = self._primeira_instalada(
            self._tema.ui_font_candidates if ui else self._tema.font_candidates
        )
        fonte = QFont(familia, design.escalar(tipo.tamanho, self._escala_texto))
        fonte.setBold(tipo.peso == "bold")
        fonte.setItalic(tipo.estilo == "italic")
        return fonte

    def _fonte_mono(self, papel: str) -> QFont:
        tipo = design.TIPO[papel]
        return QFont(self._mono, design.escalar(tipo.tamanho, self._escala_texto))

    @property
    def largura_lateral(self) -> int:
        """A coluna de ajustes é uma coluna de TEXTO, e acompanha o tamanho dele."""
        return design.escalar(design.LARGURA_LATERAL, self._escala_texto)

    def _ajustar_marca(self, texto: str) -> QFont:
        """Encolhe o nome do ambiente até ele caber na largura da coluna."""
        fonte = self.fonte("display", ui=False)
        maximo = fonte.pointSize()
        limite = design.escalar(design.CABECALHO_LARGURA_MAX, self._escala_texto)
        for tamanho in range(maximo, maximo - 10, -1):
            fonte.setPointSize(tamanho)
            if QFontMetrics(fonte).horizontalAdvance(texto) <= limite:
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
        """Constrói os widgets e adota as peças que a montagem devolveu.

        A construção mora em ``montagem.py``; o que sobra aqui é a adoção. As
        atribuições são uma a uma, e não um laço sobre os campos do dataclass,
        porque é este bloco que declara ao mypy — e a quem lê — que a janela
        tem cada uma dessas peças.
        """
        pecas = montagem.montar(self)
        moldura, lateral, rodape, palco = (
            pecas.moldura, pecas.lateral, pecas.rodape, pecas.palco
        )

        self.barra_titulo = moldura.barra_titulo
        self.coluna_lateral = moldura.coluna_lateral
        self.lateral = moldura.lateral
        self.rolagem_lateral = moldura.rolagem_lateral
        self.rodape_lateral = moldura.rodape_lateral
        self.palco = moldura.palco
        self._veu = moldura.veu

        self.marca = lateral.marca
        self.submarca = lateral.submarca
        self.campos = lateral.campos
        self._rotulos_secao = lateral.rotulos_secao
        self._rotulos_campo = lateral.rotulos_campo
        self.campo_jogo = lateral.campo_jogo
        self.campo_persona = lateral.campo_persona
        self.campo_nivel = lateral.campo_nivel
        self.campo_modo = lateral.campo_modo
        self.campo_voz = lateral.campo_voz
        self.campo_entrada = lateral.campo_entrada
        self.campo_saida = lateral.campo_saida
        self.campo_ganho_jogo = lateral.campo_ganho_jogo
        self.campo_atmosfera = lateral.campo_atmosfera
        self.campo_tamanho_texto = lateral.campo_tamanho_texto
        self.chip_alto_falante = lateral.chip_alto_falante
        self.chip_jogo = lateral.chip_jogo
        self.chip_busca = lateral.chip_busca
        self.ajustes_de_sessao = lateral.ajustes_de_sessao
        self.bloco_volume = lateral.bloco_volume
        self.resumo_sessao = lateral.resumo_sessao

        self.rotulo_caderno = rodape.rotulo_caderno
        self.botao_caderno = rodape.botao_caderno
        self.botao_historico = rodape.botao_historico

        self.pilula = palco.pilula
        self.medidor = palco.medidor
        self.rotulo_meta = palco.rotulo_meta
        self.botao_mudo = palco.botao_mudo
        self.botao_acao = palco.botao_acao
        self.conversa = palco.conversa
        self.entrada_texto = palco.entrada_texto
        self.botao_enviar = palco.botao_enviar

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
        # O nome do jogo novo se decifra no lugar do antigo, por baixo da
        # dissolução — e continua depois dela, que é mais curta.
        self.marca.decifrar()

    def _aplicar_tema(self) -> None:
        t = self._tema
        self.setWindowTitle(t.window_title)
        self.barra_titulo.aplicar_tema()
        # Só os TEXTOS aqui; as fontes de todos eles saem de _aplicar_fontes,
        # chamada logo abaixo — duplicar as duas coisas fazia a marca ser
        # medida duas vezes por repintura, e a segunda apagava a primeira.
        self.marca.setText(t.header_title)
        self.submarca.setText(t.header_subtitle)

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

        self._aplicar_fontes()
        self.medidor.definir_cores(
            primary=t.primary, accent=t.accent, alert=t.alert,
            apagada=design.elevar(t.screen, 0.16, t.primary),
            # Neutro de propósito: o risco é uma marca de régua, não um estado.
            # Na cor do tema competiria com as barras vivas, que são o dado.
            limiar=t.text_muted,
        )
        self.setStyleSheet(folha_da_janela(self._tema, self._atmosfera.forma))
        self._posicionar_veu()
        raio = RAIO_POR_FORMA.get(self._atmosfera.forma, RAIO_PADRAO)
        for campo in self.campos.values():
            campo.definir_cor_seta(t.text_muted)
            campo.definir_cor_luz(t.primary, raio_borda=raio)
        self._atualizar_pilula()
        self._campainha.aplicar_tema()
        if self._capsula is not None:
            self._capsula.aplicar_tema()
        if hasattr(self, "_sobreposicao"):
            self._sobreposicao.raise_()
            # O quadro cheio é obrigatório aqui: o vidro e o fundo do tema
            # novo cobrem a janela inteira, e a repintura por região só sabe
            # das camadas VIVAS. Sem isto, trocar de jogo deixaria a
            # atmosfera antiga na tela até a próxima partícula passar por cima.
            self._sobreposicao.update()
        # O ambiente novo pode ter camadas vivas onde o anterior não tinha (ou
        # o contrário): o relógio de quadros precisa ser reavaliado na troca.
        self._relogios.sincronizar_animacao()
        self.update()

    def _aplicar_fontes(self) -> None:
        """Reaplica a rampa inteira aos widgets da janela principal.

        As janelas satélites já refaziam suas fontes em ``aplicar_tema``; a
        principal montava as dela uma vez e nunca mais, porque a família dos
        controles é a mesma em todos os temas e a rampa era fixa. Com o
        tamanho do texto ajustável, "uma vez e nunca mais" vira "metade da
        janela ignora a escolha".
        """
        self.coluna_lateral.setFixedWidth(self.largura_lateral)
        self.marca.setFont(self._ajustar_marca(self._tema.header_title))
        self.submarca.setFont(self.fonte("micro"))
        for rotulo in self._rotulos_secao:
            rotulo.setFont(self.fonte("secao"))
        for etiqueta in self._rotulos_campo:
            etiqueta.setFont(self.fonte("rotulo"))
        for campo in self.campos.values():
            campo.setFont(self.fonte("aux"))
        for chip in (self.chip_alto_falante, self.chip_jogo, self.chip_busca):
            chip.setFont(self.fonte("legenda"))
        for rotulo_resumo in self.resumo_sessao.rotulos:
            rotulo_resumo.setFont(self.fonte("rotulo"))
        for valor_resumo in self.resumo_sessao.valores:
            valor_resumo.setFont(self.fonte("aux"))
        self.resumo_sessao.dica.setFont(self.fonte("micro"))
        self.rotulo_caderno.setFont(self.fonte("micro"))
        self.pilula.setFont(self.fonte("micro"))
        self.rotulo_meta.setFont(self._fonte_mono("micro"))
        self.entrada_texto.setFont(self.fonte("corpo"))
        for botao in (
            self.botao_caderno, self.botao_historico,
            self.botao_acao, self.botao_mudo, self.botao_enviar,
        ):
            botao.setFont(self.fonte("corpo_forte"))

    def _ajustar_tamanho_texto(self, escolha: str) -> None:
        """Aplica o tamanho do texto na janela e em tudo que ela hospeda.

        Como a atmosfera, isto é acessibilidade e não gosto — então vale em
        toda superfície do programa, e não só onde o controle está. As janelas
        satélites pegam a rampa nova pelo ``aplicar_tema`` delas, que é o
        mesmo caminho por onde já pegam a paleta.
        """
        nova = ESCALAS_TEXTO.get(escolha, 1.0)
        if nova == self._escala_texto:
            return
        self._escala_texto = nova
        self._aplicar_tema()
        # As bolhas guardam a fonte capturada na construção; só refazendo.
        self.conversa.repintar()
        for satelite in (self._caderno, self._visor_historico, self._capsula):
            if satelite is not None:
                satelite.aplicar_tema()

    def _ajustar_atmosfera(self, escolha: str) -> None:
        self._intensidade_atmosfera = NIVEIS_ATMOSFERA.get(escolha, 1.0)
        self._cenario.definir_intensidade(self._intensidade_atmosfera)
        self._cenario.movimento = self._intensidade_atmosfera > 0.0
        self._relogios.sincronizar_animacao()
        # O controle é de ACESSIBILIDADE, não de gosto: quem o baixa por causa
        # de cintilação ou baixa visão precisa que ele valha em toda superfície
        # do programa. O caderno e o histórico têm cenário próprio e ficavam de
        # fora — desligar a atmosfera na janela principal continuava entregando,
        # lá dentro, varredura, grão e vinheta em intensidade cheia e, depois,
        # a luz e o rastro do cursor.
        for satelite in (self._caderno, self._visor_historico):
            if satelite is not None:
                satelite.definir_intensidade(self._intensidade_atmosfera)
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

    def changeEvent(self, evento: Any) -> None:
        super().changeEvent(evento)
        if evento.type() == QEvent.Type.WindowStateChange:
            self._relogios.sincronizar_animacao()
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
        self._relogios.sincronizar_animacao()

    def showEvent(self, evento: Any) -> None:
        super().showEvent(evento)
        self._relogios.sincronizar_animacao()
        # Cantos arredondados e sombra do Windows 11: o DWM precisa do winId,
        # que só existe com a janela criada — daí ficar aqui e não no arranque.
        aplicar_cantos_do_sistema(self)
        if not self._ja_apareceu:
            self._ja_apareceu = True
            # O aparelho liga: o nome dele se decifra na primeira vez que a
            # janela aparece.
            self.marca.decifrar()
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

    def _deve_animar(self) -> bool:
        """A atmosfera tem para quem desenhar agora?

        A política de parada mora aqui, e não em ``relogios.py``, porque as
        três razões para parar são estado DESTA janela: o jogador desligou a
        atmosfera, o ambiente escolhido não tem camada viva alguma (dois dos
        dez não têm), ou a janela não está à vista — minimizada, o relógio
        repintava trinta vezes por segundo disputando CPU com o jogo.
        """
        return (
            self._intensidade_atmosfera > 0.0
            and self._cenario.precisa_quadros
            and self.isVisible()
            and not self.isMinimized()
        )

    def _avancar_cenario(self, passo: float) -> None:
        """Avança a animação e pede de volta só o que mudou.

        Repintar a janela inteira para mexer alguns pontos de luz custava,
        medido em 1920×1032, entre 1,8 e 2,2 ms por quadro — de 5 a 7% de um
        núcleo, permanentes, num programa feito para ficar aberto atrás de um
        jogo. ``None`` é o pedido explícito do quadro cheio, que a tremulação
        do tubo continua fazendo.
        """
        # A cada quadro, e não só a cada movimento: o botão magnético segue
        # andando depois que o cursor para, e o anel que o abraça vai junto.
        self._cenario.definir_abraco(abraco_de(self._alvo_do_anel, self))
        self._cenario.avancar(passo)
        regiao = self._cenario.regiao_suja()
        if regiao is None:
            self._sobreposicao.update()
        else:
            # A luz do cursor mora no FUNDO da janela: repintá-la é repintar a
            # janela naquela região, o que leva junto os painéis e o vidro da
            # frente. E o vidro é translúcido: repintar um pedaço dele já era
            # repintar tudo o que está atrás. Por isso um pedido só, com as duas
            # regiões unidas — as caixinhas de partícula e de faísca que caem
            # dentro da caixa da luz somem nela. A área é a mesma, em muito menos
            # retângulos, e cada retângulo a mais é um recorte a mais em cada
            # desenho de cada widget embaixo dele.
            regiao = regiao.united(self._cenario.regiao_da_luz())
            if not regiao.isEmpty():
                self.update(regiao)
        # Assentada a luz, o passo volta ao de repouso — e, num ambiente sem
        # partícula, o relógio para, mesmo com o mouse parado sobre a janela.
        self._relogios.sincronizar_animacao()

    def _luz_do_cursor(self) -> LuzDoCursor | None:
        """A luz que anda pelo fundo, para os componentes acenderem as bordas.

        A força já vem multiplicada pela intensidade da atmosfera: desligada,
        ela é zero, e a luz não existe — nem para as bordas.
        """
        ponto, forca = self._cenario.luz
        forca *= self._intensidade_atmosfera
        if forca <= 0.01:
            return None
        return LuzDoCursor(self, ponto, forca, QColor(self._tema.accent))

    def _pintar_bordas_de_luz(self, pintor: QPainter) -> None:
        """Os contornos dos painéis, acesos pela luz do cursor, no vidro da janela.

        O painel da conversa e o campo de texto não têm contorno em repouso —
        são superfícies translúcidas sobre a atmosfera — e é justamente isso
        que a luz revela quando o cursor se aproxima. Desenhados no vidro, e
        não por eles: a folha de estilo pinta as duas superfícies, e o vidro é
        a camada que já repinta junto com a luz.
        """
        raio = RAIO_POR_FORMA.get(self._atmosfera.forma, RAIO_PADRAO)
        for painel, canto in ((self.conversa, raio + 4), (self.entrada_texto, raio + 2)):
            if not painel.isVisible():
                continue
            caixa = QRectF(
                QPointF(painel.mapTo(self, QPoint(0, 0))), QSizeF(painel.size())
            ).adjusted(0.5, 0.5, -0.5, -0.5)
            contorno = QPainterPath()
            contorno.addRoundedRect(caixa, canto, canto)
            acender_borda(pintor, self._sobreposicao, contorno)
        # O fio que separa a coluna lateral do palco.
        if self.coluna_lateral.isVisible():
            topo = self.coluna_lateral.mapTo(self, QPoint(self.coluna_lateral.width(), 0))
            fio = QPainterPath(QPointF(topo.x() - 0.5, topo.y()))
            fio.lineTo(QPointF(topo.x() - 0.5, topo.y() + self.coluna_lateral.height()))
            acender_borda(pintor, self._sobreposicao, fio, largura=1.6)

    def _frequencia_da_tela(self) -> float:
        tela = self.screen()
        return tela.refreshRate() if tela is not None else 0.0

    def _cursor_mudou(self, ponto: QPointF | None, alvo: QWidget | None = None) -> None:
        """O cursor andou sobre a janela (ou saiu dela, com ``None``).

        A atmosfera ganha uma luz que o segue e partículas que fogem dele, e o
        botão principal o sente chegando. Com a atmosfera desligada, nada
        disso existe: é a mesma régua de todo o movimento do programa.
        """
        if self._intensidade_atmosfera <= 0.0:
            ponto = None
        # O clicável sob o cursor: o anel o abraça, em vez de só crescer.
        self._alvo_do_anel = alvo if ponto is not None else None
        self._cenario.definir_cursor(ponto, sobre_clicavel=self._alvo_do_anel is not None)
        self._cenario.definir_abraco(abraco_de(self._alvo_do_anel, self))
        self._campo_magnetico.mover(ponto)
        # Sempre, e não só com o relógio parado: com ele correndo no passo de
        # repouso, é aqui que ele acelera para acompanhar o cursor.
        self._relogios.sincronizar_animacao()

    def _foco_mudou(self, alvo: QWidget) -> None:
        """O teclado levou o foco para outro lugar: a luz vai junto.

        Navegar por Tab era invisível fora do anel de foco de cada widget,
        enquanto o mouse tinha luz, anel e rastro. Agora o foco de TECLADO
        move a luz para o meio do campo que o recebeu — com o rastro mostrando
        o caminho — e o anel o abraça, como faria o cursor. O foco vindo do
        mouse não passa por aqui: quem clicou já tem o cursor no lugar.
        """
        self._cursor_mudou(centro_de(alvo, self), alvo)

    def _clique(self, ponto: QPointF) -> None:
        """Todo clique na janela solta uma onda do ponto tocado."""
        if self._intensidade_atmosfera <= 0.0:
            return
        self._cenario.pulsar(ponto)
        self._relogios.sincronizar_animacao()

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
            # Só aparece com PRECO_POR_MILHAO_TOKENS no .env: sem preço, o
            # programa não tem como dizer nada sobre dinheiro — e não inventa.
            custo = self._configuration.custo_de(self._tokens)
            if custo:
                partes.append(custo)
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
            antes = self._total_no_caderno
            self.caderno_mudou()
            self._campainha.tocar("vocab")
            # O evento também vem de reencontro e de resposta de quiz, que não
            # mudam o total: só palavra NOVA ganha o sinal.
            if self._total_no_caderno > antes:
                self._anunciar_palavras(self._total_no_caderno - antes)
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
        elif tipo is UiEventKind.DEVICES_READY:
            self._dispositivos_prontos(evento.payload)
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
            try:
                self._historico.registrar_fala(
                    self._sessao_historico, autor=autor, tag=tag.value, texto=texto
                )
            except Exception as erro:
                self._falha_de_gravacao(
                    "historico",
                    "A conversa desta sessão NÃO está sendo gravada no histórico.",
                    erro,
                )

    def _falha_de_gravacao(self, chave: str, aviso: str, erro: Exception) -> None:
        """Anuncia uma falha de escrita — uma vez, e nunca em silêncio.

        Estas duas gravações (a fala no histórico, o dia no contador de
        sequência) eram engolidas por um ``suppress(Exception)`` mudo. Disco
        cheio, banco travado por um antivírus ou arquivo corrompido faziam o
        programa parar de guardar o que ele promete guardar para sempre — sem
        uma linha na tela, sem uma linha no log, e sem nenhuma diferença
        visível até o jogador procurar a conversa de ontem e não achar.

        Avisar UMA vez é o essencial: um banco que recusa uma escrita recusa
        todas, e um aviso por frase falada transformaria a conversa num muro
        de erros. A primeira aparição fala; as repetições ficam no log, em
        nível de depuração, para o caso de alguém investigar.
        """
        if chave in self._falhas_anunciadas:
            LOGGER.debug("Falha de gravação repetida (%s): %s", chave, erro)
            return
        self._falhas_anunciadas.add(chave)
        LOGGER.exception("Falha de gravação (%s).", chave, exc_info=erro)
        # Tag.SISTEMA de propósito: é a única que não volta para o histórico,
        # e portanto a única que não pode reentrar nesta mesma falha.
        self._registrar(f"{aviso} Detalhe no pipboy.log: {erro}", Tag.SISTEMA)

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
        self._total_no_caderno = total
        texto = f"Caderno · {total} termos"
        vencidas = self._store.pendentes()
        if vencidas:
            texto += f"\n{vencidas} para revisar"
        self.rotulo_caderno.setText(texto)
        self.conversa.atualizar_inicial()

    def _definir_controles(self, ativa: bool, pode_parar: bool = True) -> None:
        # Os dois controles de APRESENTAÇÃO seguem vivos durante a sessão. O
        # travamento existe porque jogo, nível e microfone vão na abertura da
        # conexão e trocá-los no meio mentiria sobre o que está valendo; letra
        # e atmosfera não vão para lugar nenhum. E são justamente os dois
        # ajustes de acessibilidade: quem precisa de letra maior para LER a
        # conversa precisa disso durante a conversa, não depois dela.
        livres = (self.campo_atmosfera, self.campo_tamanho_texto)
        for campo in self.campos.values():
            if campo not in livres:
                campo.setEnabled(not ativa)
        for chip in (self.chip_alto_falante, self.chip_busca):
            chip.setEnabled(not ativa)
        self.botao_acao.variante = "perigo" if ativa else "primario"
        self.botao_acao.setText(
            self._tema.stop_label if ativa else self._tema.start_label
        )
        self.botao_acao.setEnabled(not (ativa and not pode_parar))
        self.conversa.definir_sessao_ativa(ativa)
        self.botao_mudo.setEnabled(ativa)
        self._relogios.medir_entrada(ativa)
        self._atualizar_medidor()
        self._mostrar_resumo_da_sessao(ativa)

    def linhas_do_resumo(self) -> list[tuple[str, str]]:
        """O que vai na abertura da conexão, como a coluna o resume na sessão.

        Lido dos PRÓPRIOS seletores, e não de uma cópia da configuração: é o
        que eles mostram que o jogador escolheu, e é o que precisa continuar
        visível quando eles se recolhem.
        """
        nomes = ("jogo", "persona", "nivel", "modo", "voz", "entrada", "saida")
        linhas = [
            (self.campos[nome].accessibleName(), self.campos[nome].currentText())
            for nome in nomes
        ]
        opcoes = [
            chip.text() for chip in (self.chip_alto_falante, self.chip_busca)
            if chip.isChecked()
        ]
        if opcoes:
            linhas.append(("Opções", " · ".join(opcoes)))
        return linhas

    def _mostrar_resumo_da_sessao(self, ativa: bool) -> None:
        """Com a sessão no ar, os ajustes travados dão lugar ao resumo deles.

        Ver ``montagem.ResumoDaSessao``. Continuam existindo — e travados —
        por baixo: o resumo é o que se MOSTRA, e o travamento continua sendo o
        que impede a troca.
        """
        if ativa:
            self.resumo_sessao.definir(self.linhas_do_resumo())
        self.resumo_sessao.setVisible(ativa)
        self.ajustes_de_sessao.setVisible(not ativa)
        self.bloco_volume.setVisible(not ativa)
        # "Ouvir o jogo" só fica na coluna da sessão se der para mexer nele:
        # sem dispositivo de loopback, ele é uma caixa cinza que não liga, e
        # a coluna da sessão é justamente a que mostra só o que ainda vale.
        self.chip_jogo.setVisible(not ativa or self.chip_jogo.isEnabled())
        self._posicionar_veu()

    # ----------------------------------------------------------- Preferências

    def _geometria_atual(self) -> str:
        g = self.geometry()
        return f"{g.width()},{g.height()},{g.x()},{g.y()}"

    def _aplicar_preferencias(self) -> None:
        """Monta a tabela de vínculo e leva o arquivo para a tela.

        O espelhamento campo a campo mora em ``preferencias.py``; o que sobra
        aqui é o que só a janela sabe — que atmosfera é padrão nesta máquina, e
        o que fazer depois de as escolhas estarem na tela.
        """
        p = self._prefs
        # O sistema decide só o PADRÃO, e só enquanto não houver escolha
        # gravada: a chave só falta no arquivo antes da primeira vez que o
        # jogador mexeu nela. Depois disso a escolha é dele, mesmo que
        # contrarie o Windows — o programa lê a preferência do sistema, não
        # obedece a ela para sempre.
        #
        # E o padrão é DESLIGADA, não Discreta. O que o Windows pede é menos
        # ANIMAÇÃO, e 'Discreta' continua animando: ela reduz a intensidade,
        # mas só 'Desligada' para a partícula, a cintilação e as transições.
        # Atender pela metade um pedido de acessibilidade é não atender.
        pediu_calma = movimento_reduzido()
        padrao_atmosfera = "Desligada" if pediu_calma else "Completa"
        self._atmosfera_veio_do_sistema = pediu_calma and "atmosfera" not in p.extras

        self._preferencias = VinculoDePreferencias(
            p,
            escolhas=(
                # O jogo vem primeiro: ele determina a lista de personas.
                Escolha("jogo", self.campo_jogo, DEFAULT_JOGO),
                Escolha("persona", self.campo_persona, DEFAULT_PERSONA),
                Escolha("voz", self.campo_voz, DEFAULT_VOZ),
                Escolha("nivel", self.campo_nivel, DEFAULT_NIVEL),
                Escolha("modo", self.campo_modo, DEFAULT_MODO),
                Escolha("dispositivo_entrada", self.campo_entrada, "Padrão do sistema"),
                Escolha("dispositivo_saida", self.campo_saida, "Padrão do sistema"),
                Escolha(
                    "ganho_jogo", self.campo_ganho_jogo, GANHO_JOGO_PADRAO, NIVEIS_GANHO_JOGO
                ),
                Escolha("extras:atmosfera", self.campo_atmosfera, padrao_atmosfera),
                Escolha("extras:tamanho_texto", self.campo_tamanho_texto, ESCALA_TEXTO_PADRAO),
            ),
            marcas=(
                Marca("saida_alto_falante", self.chip_alto_falante),
                Marca("busca_web", self.chip_busca),
                Marca("ouvir_jogo", self.chip_jogo, ativa=lambda: self._loopback is not None),
            ),
            geometria=self._geometria_atual,
            pai=self,
        )
        self._preferencias.aplicar()

        self._ajustar_atmosfera(self.campo_atmosfera.currentText())
        # Direto no campo, sem passar por _ajustar_tamanho_texto: aqui a janela
        # ainda está sendo montada, o _aplicar_tema logo a seguir já refaz tudo,
        # e as satélites que aquele método repinta ainda nem existem.
        self._escala_texto = ESCALAS_TEXTO.get(self.campo_tamanho_texto.currentText(), 1.0)
        self._atualizar_caderno()

    # --------------------------------------------------------------- Atalhos

    def _registrar_atalhos(self) -> None:
        """Monta a tabela de atalhos e manda instalar.

        Esc e F12 ficam de fora dos globais de propósito: sequestrá-las no
        sistema inteiro quebraria o menu de pausa do jogo, que é exatamente
        onde este programa é usado.
        """
        self._atalhos = Atalhos(
            self,
            locais={
                "F12": self.alternar_sessao,
                "Escape": self.encerrar_sessao,
                "Ctrl+B": self.abrir_caderno,
                "Ctrl+H": self.abrir_historico,
                "Ctrl+R": self.revisar_agora,
                "Ctrl+M": self.entrar_modo_compacto,
                "Ctrl+L": self.focar_texto,
                "Ctrl+K": self.abrir_paleta,
            },
            # Pares, e não um dicionário: chaveado pela combinação, dois
            # atalhos com a mesma tecla no .env colapsariam num só antes de
            # qualquer código rodar. Ver atalhos.resolver_globais.
            globais=(
                (self._configuration.hotkey_toggle, UiEventKind.START_REQUEST),
                (self._configuration.hotkey_mute, UiEventKind.TOGGLE_MUTE_REQUEST),
                (self._configuration.hotkey_game_audio, UiEventKind.TOGGLE_GAME_AUDIO_REQUEST),
            ),
            globais_ligados=self._configuration.global_hotkeys_enabled,
            publicar=self._eventos.put,
            avisar=lambda texto: self._registrar(texto, Tag.SISTEMA),
        )
        self._atalhos.instalar()

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
        self._preferencias.salvar()
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

    def dica_do_caderno(self, palavra: str) -> str:
        """O que o caderno sabe sobre ``palavra``, para a dica da fala.

        A conversa passa a reconhecer o próprio vocabulário do jogador: a
        palavra que ele já ensinou ao caderno chega com a tradução e a data da
        próxima revisão, sem rede nenhuma — é tudo do banco local. A que ele
        não tem ensina o gesto, que de outro modo ninguém descobriria.
        """
        entrada = self._store.entrada(palavra)
        if entrada is None:
            return "Clique para perguntar o que significa"
        dias = entrada.dias_ate_revisao
        if dias <= 0:
            quando = "para revisar"
        elif dias == 1:
            quando = "revisar amanhã"
        else:
            quando = f"revisar em {dias} dias"
        return f"{entrada.termo} — {entrada.traducao} · {quando} · do seu caderno"

    def perguntar_sobre(self, palavra: str) -> None:
        """Escreve no campo a pergunta sobre ``palavra``, tocada numa fala.

        A palavra desconhecida está no meio da frase que o tutor acabou de
        dizer, e perguntar por ela exigia digitá-la de novo. Escreve, e não
        envia: a mesma regra das fichas da tela inicial.
        """
        self.propor_texto(f"O que significa ‘{palavra}’?")

    def propor_texto(self, texto: str) -> None:
        """Escreve ``texto`` no campo de digitação, com o foco, e NÃO envia.

        As fichas de exemplo da tela inicial chegam aqui. Enviar é um gesto de
        quem digita: abre a conversa com a API, e sem sessão só responde
        "Inicie uma sessão".
        """
        # setText já leva o cursor ao fim da linha: a frase fica pronta para
        # continuar sendo escrita, e não para ser sobrescrita.
        self.entrada_texto.setText(texto)
        self.entrada_texto.setFocus()

    def enviar_texto(self) -> None:
        texto = self.entrada_texto.text().strip()
        if not texto:
            return
        if self._worker is None:
            self._registrar("Inicie uma sessão antes de enviar mensagens.", Tag.SISTEMA)
            return
        self.entrada_texto.clear()
        self._worker.send_text(texto)

    def focar_texto(self) -> None:
        """Leva o cursor para o campo de texto, com o que havia lá selecionado."""
        self.entrada_texto.setFocus()
        self.entrada_texto.selectAll()

    def comandos(self) -> list[Comando]:
        """Tudo o que a paleta alcança, montado a partir da própria janela.

        A lista NÃO é escrita à mão: as opções saem dos seletores da lateral e
        das chaves, lidos agora. Uma voz nova em ``VOZES``, um tema novo em
        ``TEMAS``, um campo novo na coluna — todos entram na paleta sem que
        ninguém precise lembrar de vir aqui, e uma lista copiada envelheceria
        no primeiro acréscimo, em silêncio.

        O que está desabilitado fica de fora: o seletor de jogo, durante uma
        sessão, é cinza porque o contexto vai na abertura da conexão. Sem esta
        regra a paleta seria a porta dos fundos para trocá-lo.

        Iniciar uma sessão e enviar uma mensagem chamam a Live API e consomem
        crédito; nenhum dos dois entra aqui. ENCERRAR entra: terminar não
        custa, e é o que se procura com pressa.
        """
        lista = [
            Comando("Abrir o caderno", "Ação", self.abrir_caderno, "Ctrl+B",
                    "vocabulário palavras termos salvos"),
            Comando("Ver o histórico", "Ação", self.abrir_historico, "Ctrl+H",
                    "conversas sessões falas transcrição"),
            Comando("Revisar cartões", "Ação", self.revisar_agora, "Ctrl+R",
                    "estudar revisão vencidas repetição espaçada"),
            Comando("Modo compacto", "Ação", self.entrar_modo_compacto, "Ctrl+M",
                    "cápsula sobre o jogo janela pequena"),
            Comando("Escrever no campo de texto", "Ação", self.focar_texto, "Ctrl+L",
                    "digitar teclado mensagem"),
        ]
        if self.sessao_ativa:
            lista.append(Comando("Encerrar a sessão", "Ação", self.encerrar_sessao, "Esc",
                                 "parar terminar desligar"))
            lista.append(Comando(
                "Reativar o microfone" if self.mudo else "Silenciar o microfone",
                "Ação", self.alternar_mudo, chaves="mudo mute voz microfone",
            ))
        for chip in (self.chip_alto_falante, self.chip_jogo, self.chip_busca):
            if not chip.isEnabled():
                continue
            # O parâmetro com valor padrão amarra o alvo DESTA volta. Sem
            # ele, as três fechaduras olhariam a mesma variável do laço, e a
            # última venceria: os três comandos alternariam a busca na web.
            def alternar(alvo: Botao = chip) -> None:
                alvo.setChecked(not alvo.isChecked())

            lista.append(Comando(
                chip.text(), "Chave", alternar,
                "ligada" if chip.isChecked() else "desligada",
                "alternar ligar desligar",
            ))
        for campo in self.campos.values():
            if not campo.isEnabled():
                continue
            rotulo = campo.accessibleName()
            atual = campo.currentText()
            for posicao in range(campo.count()):
                valor = campo.itemText(posicao)

                def escolher(alvo: CampoSelecao = campo, escolha: str = valor) -> None:
                    alvo.setCurrentText(escolha)

                lista.append(Comando(
                    valor, rotulo, escolher, "atual" if valor == atual else "",
                ))
        return lista

    def palavras_do_caderno(self, consulta: str) -> list[Comando]:
        """As palavras do caderno que casam com ``consulta``, como comandos.

        A paleta pergunta isto a cada tecla em vez de receber o caderno inteiro
        na abertura: mil palavras viram mil objetos para mostrar sete, e o
        banco já sabe procurar — por termo, tradução E exemplo, sem acento e
        sem caixa, que é o mesmo caminho da busca do caderno.

        A tradução e o exemplo vão nas CHAVES do comando, e não só na dica.
        Foi o banco quem casou a busca com eles; sem isso o ranqueador da
        paleta, que olha o título e as chaves, jogaria fora justamente a
        palavra que o banco achou por "munição".
        """
        return [
            Comando(
                entrada.termo, "Caderno",
                partial(self.procurar_no_caderno, entrada.termo),
                entrada.traducao,
                f"{entrada.traducao} {entrada.exemplo}",
            )
            for entrada in self._store.listar(busca=consulta, limite=PALAVRAS_DO_CADERNO)
        ]

    def procurar_no_caderno(self, termo: str) -> None:
        """Abre o caderno já mostrando ``termo``."""
        self.abrir_caderno()
        if self._caderno is not None:
            self._caderno.procurar(termo)

    def abrir_paleta(self) -> None:
        """A paleta de comandos (Ctrl+K).

        A ação escolhida roda DEPOIS que a paleta fecha, e não de dentro dela:
        "Revisar cartões" abre um modal, e um modal nascido dentro de outro
        que está se fechando fica órfão de janela-mãe na hora de se posicionar.
        """
        paleta = Paleta(self, self.comandos(), extras=self.palavras_do_caderno)
        paleta.exec()
        escolhido = paleta.escolhido
        paleta.deleteLater()
        if escolhido is not None:
            escolhido()

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
        try:
            self._historico.marcar_atividade()
        except Exception as erro:
            self._falha_de_gravacao(
                "atividade",
                "A sequência de estudo não está sendo contada.",
                erro,
            )

    def resumo_inicial(self) -> Resumo:
        """Os números e textos da tela inicial, lidos na hora em que ela aparece."""
        config = self._configuration
        globais = globais_disponiveis() and config.global_hotkeys_enabled
        vencidas = self._store.pendentes()
        palavra = ""
        if vencidas:
            primeiras = self._store.listar(filtro=FILTRO_REVISAR, limite=1)
            palavra = primeiras[0].termo if primeiras else ""
        try:
            conversas = self._historico.total_sessoes()
        except Exception:
            conversas = 0
        return Resumo(
            termos=self._store.total(),
            vencidas=vencidas,
            conversas=conversas,
            sequencia=self.sequencia_de_estudo(),
            palavra=palavra,
            atalhos=(
                (
                    (config.hotkey_toggle, "iniciar/parar"),
                    (config.hotkey_mute, "mudo"),
                    (config.hotkey_game_audio, "áudio do jogo"),
                )
                if globais else ()
            ),
            diagnostico=f"Modelo {config.model} · chave {config.redacted_key()}",
        )

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

    def _anunciar_palavras(self, novas: int) -> None:
        """Um "+1" sobe do contador do caderno, na lateral.

        A lateral é o único lugar da janela principal que mostra o tamanho do
        caderno, e a mudança de "3 termos" para "4 termos" acontecia num quadro,
        num texto miúdo, no canto oposto ao da conversa. O som da campainha já
        dizia que algo foi salvo; o sinal diz ONDE aquilo foi parar.
        """
        rotulo = self.rotulo_caderno
        pai = rotulo.parentWidget()
        if self._intensidade_atmosfera <= 0.0 or pai is None or not rotulo.isVisible():
            return
        primeira_linha = rotulo.text().split("\n", 1)[0]
        fonte = self.fonte("legenda")
        fonte.setBold(True)
        ancora = QPoint(
            rotulo.x() + QFontMetrics(rotulo.font()).horizontalAdvance(primeira_linha) + 8,
            rotulo.y() - 2,
        )
        self.sinal_do_caderno = SinalFlutuante(
            pai, f"+{novas}", ancora=ancora, cor=self._tema.accent_text, fonte=fonte
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

    def exportar_vocabulario(self) -> int | None:
        """Pergunta o destino e exporta. Devolve quantos termos foram escritos.

        ``None`` quando nada foi escrito — caderno vazio, seletor cancelado ou
        falha de disco. É a pergunta de quem confirma o sucesso na própria
        tela: o botão do caderno, que fica na frente do registro onde o total
        também é anunciado.
        """
        if self._store.total() == 0:
            avisar(
                self, "Caderno vazio",
                "Nada foi salvo ainda. Inicie uma sessão e pergunte o significado "
                "de qualquer palavra em inglês: o assistente anota sozinho.",
            )
            return None
        destino, _ = QFileDialog.getSaveFileName(
            self, "Exportar vocabulário", "vocabulario_pipboy.txt",
            "Anki / TSV (*.txt);;Markdown (*.md)",
        )
        if not destino:
            return None
        caminho = Path(destino)
        try:
            if caminho.suffix.lower() == ".md":
                total = self._store.exportar_markdown(caminho)
            else:
                total = self._store.exportar_csv(caminho)
        except OSError as erro:
            avisar(self, "Falha ao exportar", str(erro), erro=True)
            return None
        self._registrar(f"{total} termos exportados para {caminho.name}.", Tag.SISTEMA)
        return total

    def importar_vocabulario(self) -> None:
        """Traz termos de um TSV para o caderno, sem tocar no que já existe."""
        origem, _ = QFileDialog.getOpenFileName(
            self, "Importar vocabulário", "", "Anki / TSV (*.txt *.tsv);;Todos (*)"
        )
        if not origem:
            return
        try:
            resultado = self._store.importar_csv(Path(origem))
        except OSError as erro:
            avisar(self, "Falha ao importar", str(erro), erro=True)
            return

        partes = [f"{resultado.novos} termo(s) novo(s)"]
        if resultado.existentes:
            # Dito sempre que acontecer, e não escondido num total: quem
            # importa de volta o próprio caderno vê "0 novos" e precisa saber
            # que isso é o esperado, não uma falha silenciosa.
            partes.append(f"{resultado.existentes} já estava(m) no caderno e ficou(ram) intacto(s)")
        if resultado.ignorados:
            partes.append(f"{resultado.ignorados} linha(s) sem termo ou tradução")
        avisar(self, "Importação concluída", ".\n".join(partes) + ".")

        self.caderno_mudou(f"{resultado.novos} termo(s) importado(s) de {Path(origem).name}.")
        if self._caderno is not None:
            self._caderno.atualizar()

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
                self._preferencias.salvar()
                self.encerrar_sessao()
                self._prazo_encerramento = time.monotonic() + SHUTDOWN_TIMEOUT_SECONDS
                self._espera = QTimer(self)
                self._espera.timeout.connect(self._verificar_encerramento)
                self._espera.start(75)
            evento.ignore()
            return

        if not self._encerrando:
            self._preferencias.salvar()
        self._encerrando = True
        self._atalhos.remover()
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
