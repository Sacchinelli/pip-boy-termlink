"""Visualizador do histórico: reler o que o tutor ensinou, sessão por sessão.

Duas colunas: à esquerda as sessões (data, jogo, quantas falas), à direita a
transcrição da sessão escolhida — cada fala com o autor na cor do seu papel,
como na conversa ao vivo. Uma sessão pode ser apagada; o histórico é do
jogador, não do programa.

Quase sempre se chega aqui por um SALTO — o ◷ de uma palavra no caderno, um
resultado da busca entre conversas —, e um salto desorienta. Três coisas dizem
onde se está:

* **A sessão aberta fica marcada na lista.** Antes, as entradas eram todas
  iguais, e a única forma de saber qual conversa estava na direita era ler a
  data no cabeçalho e procurá-la na coluna.
* **A transcrição rola até a fala em vez de pular**, e a fala pulsa uma vez
  ao chegar. Um pulo instantâneo deixa o olho no alto da coluna, procurando.
* **Trocar de sessão faz as falas entrarem em cascata**, que é o que distingue
  "outra conversa" de "a mesma conversa redesenhada". Filtrar pela busca não
  anima: ela redesenha a cada tecla.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QApplication,
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
from .atmosfera import Cenario, so_o_cursor
from .componentes import Botao, caminho_forma
from .cursor import CursorVivo
from .dialogo import Caixa
from .moldura import BarraDeTitulo, GripsRedimensionamento, aplicar_cantos_do_sistema
from .movimento import animar_entrada

LARGURA_LISTA = 250

# A busca entre conversas só consulta o banco depois desta pausa, pelo mesmo
# motivo do caderno: ela varre a tabela de falas inteira.
ESPERA_BUSCA_MS = 180

# Falas que entram em cascata ao trocar de sessão: as que cabem na tela.
CASCATA_MAXIMA = 10

# Folga acima e abaixo da fala marcada ao rolar até ela: a linha chega com
# conversa em volta, que é o motivo inteiro de abrir a conversa.
FOLGA_MARCADA = 140


def _data_amigavel(iso: str) -> str:
    try:
        quando = datetime.fromisoformat(iso).astimezone()
    except ValueError:
        return iso
    return quando.strftime("%d/%m/%Y %H:%M")


# O quanto da luz do cursor aparece no fundo liso do histórico. Ver paintEvent.
ATENUACAO_DA_LUZ = 0.34


class LinhaMarcada(QLabel):
    """A fala que trouxe alguém até aqui: fundo próprio e um pulso ao chegar.

    O fundo é pintado, e não posto na folha de estilo, para poder pulsar sem
    reaplicar CSS a cada quadro.
    """

    DURACAO_PULSO = 900

    def __init__(self, texto: str, *, fundo: str, acento: str) -> None:
        super().__init__(texto)
        self._fundo = fundo
        self._acento = acento
        self.pulso = 0.0
        self._animacao = QVariantAnimation(self)
        self._animacao.setDuration(self.DURACAO_PULSO)
        self._animacao.setStartValue(0.0)
        self._animacao.setKeyValueAt(0.25, 1.0)
        self._animacao.setEndValue(0.0)
        self._animacao.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._animacao.valueChanged.connect(self._repintar)

    @property
    def pulsando(self) -> bool:
        return self._animacao.state() == QVariantAnimation.State.Running

    def pulsar(self) -> None:
        self._animacao.stop()
        self._animacao.start()

    def _repintar(self, valor: Any) -> None:
        self.pulso = float(valor)
        self.update()

    def paintEvent(self, evento: Any) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(QColor(design.misturar(self._fundo, self._acento, 0.35 * self.pulso)))
        pintor.drawRoundedRect(QRectF(self.rect()), 4, 4)
        pintor.end()
        super().paintEvent(evento)


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
        self._itens_lista: dict[int, Botao] = {}
        self.linha_marcada: LinhaMarcada | None = None
        self._rolagem_animada: QPropertyAnimation | None = None

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

        # Busca em TODAS as conversas. A outra caixa, à direita, procura
        # dentro da conversa aberta — são perguntas diferentes e por isso
        # moram em colunas diferentes: esta responde "em qual conversa?",
        # aquela responde "onde, dentro desta?".
        # O amortecedor nasce ANTES da caixa que o dispara: a conexão abaixo o
        # menciona, e criá-lo depois deixaria o nome pendurado no ar.
        # A consulta varre a tabela de falas inteira; disparar a cada tecla
        # faria "wasteland" custar nove varreduras do histórico de um ano.
        self._espera_sessoes = QTimer(self)
        self._espera_sessoes.setSingleShot(True)
        self._espera_sessoes.setInterval(ESPERA_BUSCA_MS)
        self._espera_sessoes.timeout.connect(self._recarregar)

        self._busca_sessoes = QLineEdit(objectName="historicoBusca")
        self._busca_sessoes.setPlaceholderText("Buscar em todas as conversas…")
        self._busca_sessoes.setClearButtonEnabled(True)
        self._busca_sessoes.setAccessibleName("Buscar em todas as conversas")
        self._busca_sessoes.setToolTip(
            "Procura em todas as sessões gravadas. A lista passa a mostrar só as "
            "conversas que contêm o texto, com quantas falas casam em cada uma."
        )
        self._busca_sessoes.textChanged.connect(lambda _: self._espera_sessoes.start())
        coluna_lista.addWidget(self._busca_sessoes)

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
        self._botao_fechar = Botao(
            "Fechar", variante="acento",
            paleta=janela.paleta, forma=janela.atmosfera.forma,
        )
        self._botao_fechar.clicked.connect(self.close)
        rodape.addWidget(self._botao_fechar)
        coluna_falas.addLayout(rodape)
        linha.addLayout(coluna_falas, 1)

        self._grips = GripsRedimensionamento(self)
        self._grips.reposicionar()
        # A mesma resposta ao cursor do caderno e da janela principal: a luz
        # pelo fundo, o anel, as ondas, o rastro, e as bordas acesas — a lista
        # de sessões, que é de botões, e os dois campos de busca. O fundo
        # continua liso; o cenário daqui existe só para o que segue o cursor, e
        # só se mexe enquanto ele se mexe.
        self._cenario = Cenario()
        self._cenario.definir_intensidade(janela.intensidade_atmosfera)
        self._cenario.movimento = janela.intensidade_atmosfera > 0.0
        self._raio_busca = 10.0
        self._cursor_vivo = CursorVivo(
            self, self._cenario,
            cor=lambda: self._janela.tema.accent,
            bordas=lambda: [
                (self._busca_sessoes, self._raio_busca), (self._busca, self._raio_busca),
            ],
        )
        self.aplicar_tema()
        self._recarregar()

    # ---------------------------------------------------------------- Tema
    def aplicar_tema(self) -> None:
        janela, t = self._janela, self._janela.tema
        self.barra_titulo.aplicar_tema()
        self._cabecalho.setFont(janela.fonte("legenda"))
        self._busca.setFont(janela.fonte("corpo"))
        self._busca_sessoes.setFont(janela.fonte("aux"))
        # Sem isto os dois botões herdavam a fonte do diálogo, e saíam numa
        # letra diferente da de todas as outras janelas — no Fallout, em
        # caixa-alta pixelada.
        for botao in (self._botao_apagar, self._botao_fechar):
            botao.setFont(janela.fonte("corpo_forte"))
            botao.forma = janela.atmosfera.forma
        raio = {"chanfrada": 3, "reta": 2}.get(janela.atmosfera.forma, 8)
        self._raio_busca = float(raio + 2)
        self._cenario.definir(t, so_o_cursor(janela.atmosfera))
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

    def _montar_lista(self) -> list[ResumoDeSessao]:
        """Reconstrói a coluna das sessões conforme a busca. Não abre nada."""
        janela = self._janela
        self._espera_sessoes.stop()
        # Limpa a lista (o stretch do fim fica).
        self._itens_lista = {}
        while self._pilha_lista.count() > 1:
            item = self._pilha_lista.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()

        procurado = " ".join(self._busca_sessoes.text().split()).strip()
        if procurado:
            achados = self._historico.buscar_sessoes(procurado)
        else:
            achados = [(r, 0) for r in self._historico.listar_sessoes()]

        for resumo, casam in achados:
            # Com busca ativa, o número que importa é quantas falas casam —
            # é ele que diz onde vale entrar. Sem busca, o tamanho da conversa.
            contagem = f"{casam} de {resumo.falas} falas" if procurado else f"{resumo.falas} falas"
            rotulo = (
                f"{_data_amigavel(resumo.iniciada_em)}\n"
                f"{resumo.jogo or 'Sem jogo'} · {contagem}"
            )
            # Chip, e não botão sutil: é uma lista de ESCOLHA, e o chip ligado
            # é a forma que o programa já usa para "esta é a que está valendo".
            botao = Botao(
                rotulo, variante="chip", paleta=janela.paleta,
                forma=janela.atmosfera.forma, alinhamento_esquerdo=True,
            )
            botao.setCheckable(True)
            botao.setFont(janela.fonte("legenda"))
            botao.setMinimumHeight(52)
            self._itens_lista[resumo.id] = botao
            # Clicar num RESULTADO leva o texto procurado junto: a conversa
            # abre já rolada até a fala que casou. Sem isso, achar a conversa
            # certa devolveria ao jogador uma hora de transcrição e o problema
            # de novo, só que menor.
            botao.clicked.connect(
                lambda _=False, s=resumo, d=procurado: self._abrir_sessao(s, destaque=d)
            )
            self._pilha_lista.insertWidget(self._pilha_lista.count() - 1, botao)
        return [r for r, _ in achados]

    def _recarregar(self) -> None:
        sessoes = self._montar_lista()
        if not sessoes:
            self._cabecalho.setText(
                f"Nenhuma conversa contém “{self._busca_sessoes.text().strip()}”."
                if self._busca_sessoes.text().strip()
                else "Nenhuma sessão gravada ainda. A partir de agora, cada conversa "
                "com o tutor fica registrada aqui — só neste computador."
            )
            self._botao_apagar.setEnabled(False)
            self._sessao_aberta = None
            self._falas_abertas = []
            self._destaque = ""
            self._limpar_falas()
            return

        # A transcrição é SEMPRE relida, mesmo quando a sessão aberta é a
        # mesma: ela pode ter crescido desde a última vez que esta janela
        # esteve na tela — é o caso normal, aliás, porque a sessão que está
        # acontecendo agora é justamente a que se quer reler. Sem isto, quem
        # fechava e reabria o histórico via a conversa congelada no passado.
        atual = next((s for s in sessoes if s.id == self._sessao_aberta), None)
        procurado = " ".join(self._busca_sessoes.text().split()).strip()
        self._abrir_sessao(atual or sessoes[0], destaque=procurado)

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
        # Um filtro deixado de uma visita anterior não é de quem chega pelo
        # caderno, e esconderia da lista justamente a conversa que se pediu.
        # Os sinais são bloqueados para a limpeza não agendar uma recarga que
        # chegaria depois e reabriria outra sessão por cima desta.
        self._busca_sessoes.blockSignals(True)
        self._busca_sessoes.clear()
        self._busca_sessoes.blockSignals(False)
        self._montar_lista()
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
        for sessao_id, item in self._itens_lista.items():
            # Também desfaz a alternância que o clique acabou de fazer num
            # chip: clicar na sessão já aberta não pode desmarcá-la.
            item.setChecked(sessao_id == resumo.id)
        self._busca.blockSignals(True)
        self._busca.clear()  # trocar de sessão zera o filtro da anterior
        self._busca.blockSignals(False)
        self._pintar_falas(animar=True)

    def _linha_a_marcar(self, falas: list[Fala]) -> int:
        """Posição da fala a destacar, ou -1. A de vocabulário tem preferência."""
        alvo = self._destaque.lower()
        if not alvo:
            return -1
        primeira = -1
        for posicao, fala in enumerate(falas):
            if alvo not in fala.texto.lower():
                continue
            if fala.tag == "vocab":
                return posicao
            if primeira < 0:
                primeira = posicao
        return primeira

    def _filtrar(self) -> None:
        self._pintar_falas(animar=False)

    def _movimento_reduzido(self) -> bool:
        return bool(self._janela.intensidade_atmosfera <= 0.0)

    def _pintar_falas(self, *, animar: bool = False) -> None:
        """Desenha a transcrição aberta, respeitando o filtro de busca."""
        janela, t = self._janela, self._janela.tema
        if self._rolagem_animada is not None:
            self._rolagem_animada.stop()
            self._rolagem_animada = None
        self.linha_marcada = None
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
        # Qual linha marcar. A anotação de vocabulário tem preferência sobre
        # uma menção qualquer porque as duas portas que trazem alguém até aqui
        # pedem coisas diferentes: vindo do caderno, o que interessa é onde a
        # palavra foi ENSINADA — e ela costuma ter sido perguntada antes disso,
        # numa fala que viria primeiro. Vindo da busca entre conversas, não há
        # anotação nenhuma e a primeira menção é a resposta certa.
        indice_marcado = self._linha_a_marcar(visiveis)
        blocos: list[QWidget] = []
        for posicao, fala in enumerate(visiveis):
            texto = (
                f"{fala.autor or fala.tag.upper()} — {fala.texto}"
                if fala.autor or fala.tag
                else fala.texto
            )
            cor = cores.get(fala.tag, t.secondary)
            if posicao == indice_marcado:
                fundo = design.misturar(t.screen, t.accent, 0.20)
                marcada = LinhaMarcada(texto, fundo=fundo, acento=t.accent)
                self.linha_marcada = marcada
                bloco: QLabel = marcada
                bloco.setStyleSheet(
                    f"color: {design.garantir_contraste(cor, fundo)};"
                    " background: transparent; padding: 6px 9px;"
                )
            else:
                bloco = QLabel(texto)
                bloco.setStyleSheet(
                    f"color: {design.garantir_contraste(cor, t.screen)};"
                    " background: transparent;"
                )
            bloco.setWordWrap(True)
            bloco.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            bloco.setFont(janela.fonte("corpo"))
            self._pilha_falas.insertWidget(self._pilha_falas.count() - 1, bloco)
            blocos.append(bloco)

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
        # Um movimento por vez: com uma fala de destino, quem guia o olho é a
        # rolagem até ela, e uma cascata no alto da coluna animaria justamente
        # as linhas que estão saindo de vista.
        if animar and self.linha_marcada is None:
            animar_entrada(blocos[:CASCATA_MAXIMA], reduzir=self._movimento_reduzido())
        if self.linha_marcada is not None:
            # Depois que o layout existir: antes disso o widget não tem
            # posição, e rolar até ele não faz nada.
            QTimer.singleShot(0, lambda w=self.linha_marcada: self._chegar_em(w))

    def _chegar_em(self, linha: LinhaMarcada) -> None:
        """Rola até a fala marcada e a faz pulsar quando chega."""
        if linha is not self.linha_marcada:
            return  # a transcrição foi redesenhada antes deste quadro
        # O layout das falas recém-inseridas ainda está na fila: sem processá-lo,
        # a área de rolagem não conhece a altura nova, o máximo da barra é zero e
        # não há para onde rolar. Era o que acontecia antes desta função existir
        # — a promessa de abrir "já rolada até a fala" nunca se cumpria, porque
        # um único giro do laço não bastava para o conteúdo ser medido.
        QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
        barra = self._rolagem_falas.verticalScrollBar()
        # O destino é o que ensureWidgetVisible escolheria; ele é perguntado ao
        # próprio Qt e desfeito no mesmo instante, antes de qualquer pintura.
        partida = barra.value()
        self._rolagem_falas.ensureWidgetVisible(linha, 0, FOLGA_MARCADA)
        destino = barra.value()
        if self._movimento_reduzido() or destino == partida:
            if not self._movimento_reduzido():
                linha.pulsar()
            return
        barra.setValue(partida)
        animacao = QPropertyAnimation(barra, b"value", self)
        animacao.setDuration(design.DURACAO_LENTA + 140)
        animacao.setStartValue(partida)
        animacao.setEndValue(destino)
        animacao.setEasingCurve(QEasingCurve.Type.OutCubic)
        animacao.finished.connect(linha.pulsar)
        self._rolagem_animada = animacao
        animacao.start()

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

    def definir_intensidade(self, valor: float) -> None:
        """Acompanha o controle de atmosfera da janela principal."""
        self._cenario.definir_intensidade(valor)
        self._cenario.movimento = valor > 0.0
        self._cursor_vivo.sincronizar()
        self.update()

    # ------------------------------------------------------------- Moldura
    def resizeEvent(self, evento: Any) -> None:
        super().resizeEvent(evento)
        if hasattr(self, "_grips"):
            self._grips.reposicionar()
        if hasattr(self, "_cursor_vivo"):
            self._cursor_vivo.reposicionar()

    def showEvent(self, evento: Any) -> None:
        super().showEvent(evento)
        aplicar_cantos_do_sistema(self)
        self._cursor_vivo.reposicionar()

    def hideEvent(self, evento: Any) -> None:
        super().hideEvent(evento)
        # Escondido, o cursor que estava aqui não vai avisar que saiu.
        self._cursor_vivo.esquecer()

    def closeEvent(self, evento: Any) -> None:
        """Fechar também desarma a busca pendente.

        ``close()`` esconde o diálogo mas não para os relógios dele. Digitar na
        busca entre conversas e fechar dentro dos 180 ms do amortecedor deixava
        um disparo agendado para depois — e, no encerramento do programa, ele
        chegaria ao banco já fechado pela janela principal, que fecha esta
        janela imediatamente antes de fechar o histórico. É a mesma armadilha
        que o caderno já documenta.
        """
        self._espera_sessoes.stop()
        super().closeEvent(evento)

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
        # A luz do cursor sobre o fundo liso, sem vazar pelos cantos da moldura.
        # Atenuada: aqui não há painel translúcido na frente dela, como na
        # janela principal e no caderno, e com a força inteira ela virava uma
        # bola de luz sobre a transcrição. Um terço é o que atravessa o painel
        # da conversa.
        pintor.save()
        pintor.setClipPath(caminho)
        self._cenario.pintar_luz(pintor, atenuacao=ATENUACAO_DA_LUZ)
        pintor.restore()
        caneta = QPen(QColor(t.border_forte))
        caneta.setWidthF(1.0)
        pintor.setPen(caneta)
        pintor.setBrush(Qt.BrushStyle.NoBrush)
        pintor.drawPath(caminho)
        pintor.end()
