"""A paleta de comandos: tudo o que a janela faz, ao alcance de digitar.

A lateral tem dez seletores, três chaves e um rodapé com dois botões; o resto
está atrás de atalhos que só quem leu a documentação conhece. Para trocar a
voz, alguém rola a coluna, encontra o campo, abre a lista e procura o nome —
seis gestos para uma escolha. ``Ctrl+K`` abre esta paleta, e a mesma escolha
vira "digitar três letras e apertar Enter".

Três decisões sustentam o resto:

* **A lista é gerada pela janela, não escrita à mão.** Os comandos saem dos
  próprios seletores da lateral (``janela.campos``) e das próprias chaves.
  Uma voz nova no ``VOZES``, um tema novo no ``TEMAS``, um campo novo na
  coluna — todos aparecem aqui sem ninguém lembrar de vir aqui. Uma lista
  copiada à mão envelheceria no primeiro acréscimo, e envelheceria em
  silêncio.

* **A paleta não dispara o que custa dinheiro.** Iniciar uma sessão abre a
  conexão com a Live API e passa a consumir por minuto; enviar uma mensagem
  também chama a API. Nada disso entra aqui: quem gasta crédito o faz pelo
  botão grande, ou pelo atalho que configurou de propósito. ENCERRAR a sessão
  entra — terminar não custa, e é justamente o que se quer achar com pressa.

* **O que a janela proíbe, a paleta proíbe.** Um seletor desabilitado —
  o jogo, durante a sessão — não gera comando nenhum. Sem essa regra, a
  paleta seria a porta dos fundos para trocar o contexto de uma conexão já
  aberta, o que a lateral impede com um campo cinza.

A busca é por SUBSEQUÊNCIA, sem acento e sem caixa: "tamtex" acha "Tamanho do
texto" e "acao" acha "Ação". Quem digita tem pressa e não sabe o nome exato do
que procura — exigir o prefixo certo devolveria a lista vazia justamente para
quem mais precisa dela.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, NamedTuple

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QEnterEvent,
    QFont,
    QFontMetricsF,
    QHoverEvent,
    QKeyEvent,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QDialog,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import design
from ..banco import dobrar
from .atmosfera import ATENUACAO_NO_FUNDO_NU, Cenario, so_o_cursor
from .componentes import Holofote, acender_borda, caminho_forma
from .cursor import CursorVivo
from .movimento import animar_entrada

# Quantas linhas a paleta mostra de uma vez. Sete cabem sem rolagem e sem
# fazer a caixa virar um painel: o que não coube, o próximo caractere digitado
# resolve melhor do que uma barra de rolagem resolveria.
LIMITE = 7
LARGURA = 560
# Onde a caixa fica, medido do topo da janela. Centrada na vertical ela tapa
# justamente a conversa; no primeiro terço, ela parece descer da barra de
# título e deixa o conteúdo à vista.
ALTURA_RELATIVA = 0.14

# Depois destes caracteres começa uma palavra nova, e uma letra que cai aí vale
# quase tanto quanto a primeira de todas.
SEPARADORES = " -–—/:,.()[]"

# Antes de duas letras, a paleta não vai ao caderno: uma letra só traria a
# primeira palavra qualquer do banco, e cobraria uma consulta por tecla para
# mostrar o que ninguém pediu.
MINIMO_PARA_BUSCAR_FORA = 2

# Quantas palavras do caderno a paleta pede ao banco de cada vez. Seis cabem
# entre as sete linhas sem expulsar todas as ações; o resto é trabalho do banco
# para ninguém ver.
PALAVRAS_DO_CADERNO = 6

# Um trecho achado fora do título — no grupo ou nas palavras-chave — conta,
# mas vale menos: quem digita "jogo" quer a lista de jogos antes de qualquer
# rótulo que por acaso contenha a palavra.
PENA_FORA_DO_TITULO = 14


@dataclass(frozen=True)
class Comando:
    """Uma coisa que a janela faz, com um nome que se possa procurar.

    ``chaves`` são as palavras que ninguém vê e todo mundo digita: quem
    procura o caderno pode escrever "vocabulário", "palavras" ou "termos", e
    nenhuma delas está no rótulo do botão.
    """

    titulo: str
    grupo: str
    acao: Callable[[], None]
    dica: str = ""
    chaves: str = ""

    @property
    def procuravel(self) -> str:
        """Tudo o que casa com a busca, para quando o título sozinho não casa."""
        return f"{self.titulo} {self.grupo} {self.chaves}"

    @property
    def legenda(self) -> str:
        """O que aparece à direita da linha: o grupo e, se houver, a dica."""
        return " · ".join(parte for parte in (self.grupo, self.dica) if parte)


class Achado(NamedTuple):
    """Um comando que casou com a busca, e onde ele casou no título."""

    comando: Comando
    marcas: tuple[int, ...]


def _inicio_do_trecho(alvo: str, busca: str) -> int:
    """Onde ``busca`` aparece INTEIRA em ``alvo``; -1 se ela não aparece.

    Entre duas aparições, ganha a que começa uma palavra: "am" em "teams ammo"
    é o "ammo", e não o miolo de "teams".
    """
    onde = alvo.find(busca)
    primeira = onde
    while onde >= 0:
        if onde == 0 or alvo[onde - 1] in SEPARADORES:
            return onde
        onde = alvo.find(busca, onde + 1)
    return primeira


def pontuar(consulta: str, texto: str) -> tuple[int, tuple[int, ...]] | None:
    """Quanto ``texto`` casa com ``consulta``, e quais letras dele casaram.

    ``None`` quando as letras da consulta não aparecem em ordem no texto.

    A varredura é gulosa — cada letra fica na primeira posição possível —, e
    isso não devolve sempre o melhor casamento teórico: em "caderno", a busca
    "cae" marca o primeiro "a" em vez do segundo, que estaria mais perto do
    "e". Ela devolve sempre o MESMO casamento, em tempo linear, e a diferença
    some na hora de ordenar. Uma busca exaustiva custaria exponencial para
    mudar duas marcas de lugar.

    Os espaços da consulta são ignorados: "tam tex" e "tamtex" procuram a
    mesma coisa, porque quem digita rápido nem sempre acerta o espaço.
    """
    alvo = dobrar(texto)
    busca = dobrar(consulta).replace(" ", "")
    if not busca:
        return None

    # Casar INTEIRO vale mais do que casar salteado, e a varredura gulosa
    # sozinha perdia isso: em "ammo Caderno municao", a busca "muni" prendia o
    # 'm' no primeiro "ammo" e o resto virava um casamento esfarrapado — a
    # palavra que o banco tinha achado pela tradução ficava atrás de qualquer
    # rótulo que casasse de raspão.
    inteiro = _inicio_do_trecho(alvo, busca)
    if inteiro >= 0:
        posicoes = list(range(inteiro, inteiro + len(busca)))
    else:
        posicoes = []
        procurar_de = 0
        for letra in busca:
            onde = alvo.find(letra, procurar_de)
            if onde < 0:
                return None
            posicoes.append(onde)
            procurar_de = onde + 1

    pontos = 0
    anterior = -2
    for onde in posicoes:
        if onde == 0:
            pontos += 12          # a primeira letra do rótulo
        elif alvo[onde - 1] in SEPARADORES:
            pontos += 8           # começo de uma palavra do meio
        if onde == anterior + 1:
            pontos += 6           # coladas: "cad" vale mais que c...a...d
        # O buraco entre uma letra e a seguinte custa, com teto: sem o teto,
        # um acerto no fim de um rótulo longo ficaria atrás de qualquer lixo.
        pontos -= min(3, onde - anterior - 1)
        anterior = onde
    # Empate desfeito pelo rótulo mais curto: entre "Voz" e "Tamanho do texto",
    # quem digitou "vo" quis o primeiro.
    pontos -= len(alvo) // 12
    return pontos, tuple(posicoes)


def filtrar(
    comandos: Sequence[Comando], consulta: str, limite: int = LIMITE
) -> list[Achado]:
    """Os melhores comandos para ``consulta``, do mais provável ao menos.

    Sem consulta, os primeiros da lista: abrir a paleta já mostra as ações da
    janela, e não um retângulo vazio pedindo que alguém adivinhe o que digitar.
    """
    if not consulta.strip():
        return [Achado(comando, ()) for comando in comandos[:limite]]

    ranqueados: list[tuple[int, int, Achado]] = []
    for ordem, comando in enumerate(comandos):
        no_titulo = pontuar(consulta, comando.titulo)
        if no_titulo is not None:
            pontos, marcas = no_titulo
        else:
            fora = pontuar(consulta, comando.procuravel)
            if fora is None:
                continue
            # Sem marcas: as posições são de outro texto, e pintá-las no
            # título acenderia letras ao acaso.
            pontos, marcas = fora[0] - PENA_FORA_DO_TITULO, ()
        ranqueados.append((-pontos, ordem, Achado(comando, marcas)))
    ranqueados.sort(key=lambda item: (item[0], item[1]))
    return [achado for _pontos, _ordem, achado in ranqueados[:limite]]


class Linha(QAbstractButton):
    """Uma opção da paleta: título com as letras achadas acesas, grupo à direita.

    Não recebe foco de teclado — o foco mora no campo de busca, do primeiro
    caractere até o Enter. A escolha corrente é estado da paleta, e o mouse a
    toma ao passar por cima: quem move o mouse está escolhendo com ele.
    """

    RESPIRO_X = 14
    RESPIRO_Y = 9

    apontada = Signal()

    def __init__(self, janela: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._janela = janela
        self._comando: Comando | None = None
        self._marcas: tuple[int, ...] = ()
        self._escolhida = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._holofote = Holofote(
            self, reduzir=lambda: bool(janela.intensidade_atmosfera <= 0.0)
        )

    # -- conteúdo
    @property
    def comando(self) -> Comando | None:
        return self._comando

    @property
    def escolhida(self) -> bool:
        return self._escolhida

    def definir(self, comando: Comando, marcas: tuple[int, ...]) -> None:
        self._comando, self._marcas = comando, marcas
        self.setText(comando.titulo)
        self.setAccessibleName(f"{comando.titulo} — {comando.legenda}")
        self.update()

    def escolher(self, escolhida: bool) -> None:
        if escolhida == self._escolhida:
            return
        self._escolhida = escolhida
        self.update()

    # -- medidas
    def _fonte_titulo(self) -> QFont:
        return self._janela.fonte("corpo")

    def _fonte_legenda(self) -> QFont:
        return self._janela.fonte("legenda")

    def sizeHint(self) -> QSize:
        metricas = QFontMetricsF(self._fonte_titulo())
        return QSize(LARGURA, round(metricas.height()) + 2 * self.RESPIRO_Y)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    @property
    def corpo(self) -> QRectF:
        """O retângulo desenhado: é o que o anel do cursor abraça."""
        return QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

    @property
    def raio_borda(self) -> float:
        forma = self._janela.atmosfera.forma
        return {"chanfrada": 3.0, "reta": 2.0}.get(forma, float(design.RAIO_PEQUENO))

    # -- presença
    def enterEvent(self, evento: QEnterEvent) -> None:
        self._holofote.seguir(evento.position())
        self._holofote.acender(True)
        self.apontada.emit()
        super().enterEvent(evento)

    def leaveEvent(self, evento: QEvent) -> None:
        self._holofote.acender(False)
        super().leaveEvent(evento)

    def event(self, evento: QEvent) -> bool:
        if evento.type() == QEvent.Type.HoverMove and isinstance(evento, QHoverEvent):
            self._holofote.seguir(evento.position())
        return super().event(evento)

    # -- desenho
    def paintEvent(self, _evento: Any) -> None:
        if self._comando is None:
            return
        t = self._janela.tema
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self.corpo
        caminho = caminho_forma(area, self._janela.atmosfera.forma, self.raio_borda)

        fundo = t.surface
        if self._escolhida or self._holofote.valor > 0.005:
            fundo = t.surface_alta
            self._holofote.pintar(
                pintor, caminho, fundo=fundo, cor=t.accent, borda=t.border
            )
            # Um fio de acento na lateral: diz qual linha o Enter vai executar
            # mesmo quando a luz do holofote ainda está subindo.
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(QColor(t.accent))
            pintor.drawRect(QRectF(area.left(), area.top() + 6.0, 2.5, area.height() - 12.0))
        acender_borda(pintor, self, caminho)

        metricas = QFontMetricsF(self._fonte_titulo())
        legenda = self._comando.legenda
        metricas_legenda = QFontMetricsF(self._fonte_legenda())
        largura_legenda = metricas_legenda.horizontalAdvance(legenda) if legenda else 0.0
        base_x = area.left() + self.RESPIRO_X
        # A linha de base calculada, e não um drawText centrado numa caixa: as
        # letras acesas são pintadas uma a uma por cima do título, e precisam
        # da MESMA origem que ele, ao pixel.
        linha_base = area.center().y() + (metricas.ascent() - metricas.descent()) / 2
        disponivel = area.width() - 2 * self.RESPIRO_X - largura_legenda - 14.0
        titulo = metricas.elidedText(
            self._comando.titulo, Qt.TextElideMode.ElideRight, disponivel
        )

        pintor.setFont(self._fonte_titulo())
        pintor.setPen(QColor(design.garantir_contraste(t.primary, fundo)))
        pintor.drawText(QPointF(base_x, linha_base), titulo)
        # As letras que casaram, repintadas no acento E sublinhadas. Só a cor
        # não bastava: em metade dos temas o acento é vizinho da cor de texto
        # — no Cyberpunk, ciano sobre ciano —, e o destaque sumia justamente
        # onde ele diz POR QUE aquela linha está na lista. O fio embaixo
        # aparece em qualquer paleta.
        aceso = QColor(design.garantir_contraste(t.accent, fundo, 3.0))
        fio = QColor(aceso)
        fio.setAlphaF(0.75)
        pintor.setPen(aceso)
        for indice in self._marcas_visiveis(titulo):
            recuo = metricas.horizontalAdvance(titulo[:indice])
            pintor.drawText(QPointF(base_x + recuo, linha_base), titulo[indice])
            pintor.fillRect(
                QRectF(
                    base_x + recuo, linha_base + 2.0,
                    metricas.horizontalAdvance(titulo[indice]), 1.4,
                ),
                fio,
            )

        if legenda:
            pintor.setFont(self._fonte_legenda())
            pintor.setPen(QColor(design.garantir_contraste(t.text_muted, fundo)))
            pintor.drawText(
                QPointF(area.right() - self.RESPIRO_X - largura_legenda, linha_base), legenda
            )
        pintor.end()

    def _marcas_visiveis(self, titulo: str) -> tuple[int, ...]:
        """As marcas que sobreviveram à elisão do título.

        Um nome de microfone não cabe na linha e vira "Microfone (2- Realt…";
        acender a letra 30 pintaria em cima das reticências, ou fora do
        widget.
        """
        if self._comando is None:
            return ()
        iguais = 0
        # Sem `strict`: o título elidido é MAIS CURTO que o original, e é
        # exatamente onde ele acaba que se quer descobrir.
        for a, b in zip(self._comando.titulo, titulo, strict=False):
            if a != b:
                break
            iguais += 1
        return tuple(marca for marca in self._marcas if marca < iguais)


class Paleta(QDialog):
    """A caixa de comandos. ``escolhido`` guarda o que fazer depois de fechar.

    A ação não roda de dentro: quem escolhe "Revisar cartões" abriria um
    modal por cima de outro modal, e o caderno chamado daqui nasceria filho de
    uma caixa que está se fechando. A paleta só devolve a ação; quem a abriu a
    executa com a janela principal de volta no comando.
    """

    def __init__(
        self,
        janela: Any,
        comandos: Sequence[Comando],
        *,
        extras: Callable[[str], list[Comando]] | None = None,
    ) -> None:
        super().__init__(janela)
        self._janela = janela
        self._comandos = list(comandos)
        self._extras = extras
        self._achados: list[Achado] = []
        self._indice = 0
        self.escolhido: Callable[[], None] | None = None

        tema = janela.tema
        self._forma = janela.atmosfera.forma
        self._fundo = tema.surface
        self._borda = tema.border_forte
        self.setWindowTitle("Comandos")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(LARGURA)

        # A mesma resposta ao cursor das outras janelas, com o cenário daqui.
        self._cenario = Cenario()
        self._cenario.definir_intensidade(janela.intensidade_atmosfera)
        self._cenario.movimento = janela.intensidade_atmosfera > 0.0
        self._cenario.definir(tema, so_o_cursor(janela.atmosfera))
        self._cursor_vivo = CursorVivo(
            self, self._cenario,
            cor=lambda: str(self._janela.tema.accent),
            bordas=lambda: [(self.campo, float(design.RAIO_PEQUENO + 2))],
        )

        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(18, 16, 18, 12)
        coluna.setSpacing(6)

        self.campo = QLineEdit(objectName="paletaCampo")
        self.campo.setPlaceholderText("O que você quer fazer?")
        self.campo.setFont(janela.fonte("corpo"))
        self.campo.setAccessibleName("Procurar um comando")
        self.campo.textChanged.connect(self._buscar)
        self.campo.returnPressed.connect(self._ativar)
        coluna.addWidget(self.campo)
        coluna.addSpacing(4)

        self.linhas = [Linha(janela, self) for _ in range(LIMITE)]
        for posicao, linha in enumerate(self.linhas):
            linha.apontada.connect(lambda i=posicao: self._escolher(i))
            linha.clicked.connect(lambda _marcado=False, i=posicao: self._ativar(i))
            coluna.addWidget(linha)

        self.vazio = QLabel("Nada com esse nome.", objectName="paletaVazio")
        self.vazio.setFont(janela.fonte("corpo"))
        self.vazio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        coluna.addWidget(self.vazio)

        self.rodape = QLabel("↑ ↓ escolher · Enter ir · Esc fechar", objectName="paletaRodape")
        self.rodape.setFont(janela.fonte("micro"))
        self.rodape.setAlignment(Qt.AlignmentFlag.AlignCenter)
        coluna.addSpacing(4)
        coluna.addWidget(self.rodape)

        self._aplicar_tema()
        self._buscar("")

    # -- tema
    def _aplicar_tema(self) -> None:
        t = self._janela.tema
        raio = {"chanfrada": 3, "reta": 2}.get(self._forma, design.RAIO_PEQUENO)
        self.setStyleSheet(f"""
        QDialog {{ background: transparent; }}
        QWidget {{ color: {t.primary}; }}
        #paletaVazio, #paletaRodape {{ color: {t.text_muted}; background: transparent; }}
        QLineEdit#paletaCampo {{
            background: {t.surface_alta}; color: {t.primary};
            border: 1px solid {t.border}; border-radius: {raio + 2}px;
            padding: 11px 14px; selection-background-color: {t.selection};
        }}
        QLineEdit#paletaCampo:focus {{ border-color: {t.border_forte}; }}
        """)

    # -- busca
    def _buscar(self, consulta: str) -> None:
        # Os comandos fixos são os mesmos desde a abertura; os de fora — as
        # palavras do caderno — são perguntados A CADA TECLA, porque um caderno
        # de mil palavras não cabe numa lista montada de véspera. Eles entram
        # no MESMO ranqueamento: uma palavra digitada por inteiro ganha da ação
        # que casou de raspão, e é isso que se espera de quem digitou a palavra.
        reserva = self._comandos
        if self._extras is not None and len(consulta.strip()) >= MINIMO_PARA_BUSCAR_FORA:
            reserva = [*reserva, *self._extras(consulta)]
        self._achados = filtrar(reserva, consulta)
        for posicao, linha in enumerate(self.linhas):
            if posicao < len(self._achados):
                achado = self._achados[posicao]
                linha.definir(achado.comando, achado.marcas)
                linha.escolher(False)
            linha.setVisible(posicao < len(self._achados))
        self.vazio.setVisible(not self._achados)
        self._indice = -1
        self._escolher(0)
        # A caixa encolhe e cresce com a lista, sempre para baixo: o campo de
        # busca fica onde estava, e o que se está digitando não foge do olho.
        self.adjustSize()

    def _escolher(self, indice: int) -> None:
        if not self._achados:
            self._indice = 0
            return
        # Dá a volta: descer na última linha leva à primeira, como em toda
        # lista que se percorre pelo teclado sem barra de rolagem.
        indice %= len(self._achados)
        if indice == self._indice:
            return
        self._indice = indice
        for posicao, linha in enumerate(self.linhas):
            linha.escolher(posicao == indice)

    @property
    def escolha(self) -> Comando | None:
        """O comando que o Enter executaria agora."""
        if not self._achados:
            return None
        return self._achados[self._indice].comando

    def _ativar(self, indice: int | None = None) -> None:
        if indice is not None:
            self._escolher(indice)
        comando = self.escolha
        if comando is None:
            return
        self.escolhido = comando.acao
        self.accept()

    # -- teclado
    def keyPressEvent(self, evento: QKeyEvent) -> None:
        """Setas escolhem; o resto é do campo de busca.

        O ``QLineEdit`` não usa as setas verticais e as deixa subir até aqui,
        então a lista se percorre sem tirar o foco de onde se digita.
        """
        if evento.key() == Qt.Key.Key_Down:
            self._escolher(self._indice + 1)
            return
        if evento.key() == Qt.Key.Key_Up:
            self._escolher(self._indice - 1)
            return
        super().keyPressEvent(evento)

    # -- janela
    def posicionar(self) -> None:
        """Centrada na janela, no primeiro terço da altura."""
        janela = self._janela
        area = janela.geometry()
        self.move(
            area.x() + (area.width() - self.width()) // 2,
            area.y() + int(area.height() * ALTURA_RELATIVA),
        )

    def resizeEvent(self, evento: Any) -> None:
        super().resizeEvent(evento)
        if hasattr(self, "_cursor_vivo"):
            self._cursor_vivo.reposicionar()

    def showEvent(self, evento: Any) -> None:
        super().showEvent(evento)
        self.posicionar()
        self.campo.setFocus()
        # As linhas entram em cascata, como os cartões do caderno: a paleta
        # aparece de uma vez, e a lista se monta depois dela.
        animar_entrada(
            [linha for linha in self.linhas if linha.isVisible()],
            reduzir=bool(self._janela.intensidade_atmosfera <= 0.0),
        )
        self._cursor_vivo.reposicionar()

    def hideEvent(self, evento: Any) -> None:
        super().hideEvent(evento)
        self._cursor_vivo.esquecer()

    def paintEvent(self, _evento: Any) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        caminho = caminho_forma(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), self._forma, design.RAIO
        )
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(QColor(self._fundo))
        pintor.drawPath(caminho)
        pintor.save()
        pintor.setClipPath(caminho)
        self._cenario.pintar_luz(pintor, atenuacao=ATENUACAO_NO_FUNDO_NU)
        pintor.restore()
        acender_borda(pintor, self, caminho)
        caneta = QPen(QColor(self._borda))
        caneta.setWidthF(1.0)
        pintor.setPen(caneta)
        pintor.setBrush(Qt.BrushStyle.NoBrush)
        pintor.drawPath(caminho)
        pintor.end()
