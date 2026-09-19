"""Cenário procedural: a atmosfera de cada jogo, gerada por código.

**Nenhum recurso dos jogos é usado.** Não há textura, arte, logotipo ou fonte
de terceiros neste módulo — tudo é sintetizado com o QPainter a partir de uma
receita numérica. Isso não é só uma questão legal (é, e séria, se o programa
for distribuído): é o que permite que a atmosfera acompanhe qualquer resolução
e qualquer paleta sem um único arquivo binário no repositório.

O que caracteriza um jogo na tela não é a cor. É o *material*: o Fallout tem
uma tela de fósforo com linhas de varredura e brilho sangrando das letras; o
Elden Ring tem partículas douradas subindo contra um fundo de pergaminho; o
Cyberpunk tem interferência digital cortando a imagem. São esses os traços
reproduzidos aqui, cada um como uma camada componível.

Arquitetura em duas velocidades, que é o que torna isto viável a 30 quadros
por segundo em Python:

* **Camadas estáticas** (grão, varredura, vinheta, grade, brilho de fundo) são
  desenhadas UMA vez num ``QPixmap`` e daí em diante apenas copiadas. Recompor
  ruído pixel a pixel a cada quadro seria impossível.
* **Camadas vivas** (partículas, tremulação, interferência) são as únicas
  redesenhadas por quadro, e só sobre a área do palco.

O ruído é gerado a partir de uma semente fixa: o mesmo tema produz sempre o
mesmo grão, então a tela não "ferve" a cada redimensionamento.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QEasingCurve, QPointF, QRect, QRectF, Qt

if TYPE_CHECKING:
    from ..themes import GameTheme
from PySide6.QtGui import (
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
    QRadialGradient,
    QRegion,
)


# --------------------------------------------------------------------- Receita
@dataclass(frozen=True, slots=True)
class Atmosfera:
    """Receita do cenário de um jogo.

    Cada campo é a intensidade de uma camada, de 0.0 a 1.0. Um jogo novo é uma
    entrada nova nesta tabela — nenhum código de desenho precisa mudar.
    """

    # Camadas estáticas
    grao: float = 0.0
    varredura: float = 0.0          # linhas de varredura horizontais (CRT)
    passo_varredura: int = 3
    vinheta: float = 0.45
    curvatura: float = 0.0          # vinheta elíptica: sugere tubo abaulado
    brilho: float = 0.0             # halo radial na cor do tema
    brilho_y: float = 0.5           # posição vertical do halo (0 topo, 1 base)
    grade: float = 0.0              # grade técnica
    passo_grade: int = 40
    fibras: float = 0.0             # fibras horizontais de papel/couro

    # Camadas vivas
    particulas: str = ""            # motes | neve | brasas | poeira | dados | estatica
    densidade: int = 40
    tremulacao: float = 0.0         # oscilação global de brilho
    interferencia: float = 0.0      # faixas de ruído digital

    # Caráter das formas — o traço do jogo também está na geometria
    forma: str = "arredondada"      # arredondada | chanfrada | reta
    # Fósforo: quanto a letra do assistente sangra luz na própria cor.
    brilho_texto: float = 0.0

    semente: int = 7
    # Cor de acento das camadas vivas; vazio usa o acento do tema.
    cor_viva: str = ""


# Uma entrada por tema de ``pipboy.themes``. O nome é a chave.
ATMOSFERAS: Final[dict[str, Atmosfera]] = {
    # Terminal de fósforo: varredura densa, brilho sangrando do centro, tubo
    # abaulado e a tremulação característica de um CRT malcuidado.
    "Fallout": Atmosfera(
        grao=0.05, varredura=0.22, passo_varredura=3, vinheta=0.62, curvatura=0.55,
        brilho=0.30, brilho_y=0.45, tremulacao=0.035, particulas="estatica",
        densidade=18, forma="reta", semente=11,
     brilho_texto=0.6,),
    # Luz dourada baixa e partículas subindo, contra pergaminho.
    "Elden Ring": Atmosfera(
        grao=0.07, vinheta=0.66, brilho=0.26, brilho_y=0.82, fibras=0.05,
        particulas="motes", densidade=46, forma="arredondada", semente=3,
    ),
    # Nevasca fina e frio: vinheta azul, neve em diagonal, pedra granulada.
    "Skyrim": Atmosfera(
        grao=0.06, vinheta=0.58, brilho=0.16, brilho_y=0.18,
        particulas="neve", densidade=70, forma="reta", semente=19,
    ),
    # Couro e vela: grão grosso, halo quente lateral, brasas lentas.
    "The Witcher 3": Atmosfera(
        grao=0.08, vinheta=0.64, brilho=0.18, brilho_y=0.35, fibras=0.06,
        particulas="brasas", densidade=26, forma="reta", semente=23,
    ),
    # Papel envelhecido: fibras, poeira suspensa e muita vinheta de álbum.
    "Red Dead": Atmosfera(
        grao=0.10, vinheta=0.70, brilho=0.14, brilho_y=0.55, fibras=0.10,
        particulas="poeira", densidade=34, forma="reta", semente=29,
    ),
    # Fita de vídeo: varredura larga, neon estourado e interferência.
    "GTA": Atmosfera(
        grao=0.05, varredura=0.16, passo_varredura=4, vinheta=0.55,
        brilho=0.30, brilho_y=0.25, interferencia=0.35, particulas="estatica",
        densidade=14, forma="chanfrada", semente=31,
     brilho_texto=0.32,),
    # Interferência digital, varredura fina e chuva de dados descendo.
    "Cyberpunk 2077": Atmosfera(
        grao=0.04, varredura=0.22, passo_varredura=3, vinheta=0.58, curvatura=0.20,
        brilho=0.24, brilho_y=0.30, interferencia=0.55, particulas="dados",
        densidade=30, forma="chanfrada", semente=37,
     brilho_texto=0.4,),
    # Grimório: halo violeta ao centro e motes arcanos flutuando.
    "RPG / Aventura (geral)": Atmosfera(
        grao=0.06, vinheta=0.60, brilho=0.24, brilho_y=0.50,
        particulas="motes", densidade=38, forma="arredondada", semente=41,
     brilho_texto=0.18,),
    # Visor tático: grade técnica, vinheta seca, sem firula. A grade é a
    # identidade INTEIRA deste tema — não há partícula, varredura nem
    # tremulação para carregá-lo — então ela precisa de intensidade
    # suficiente para ser vista. Em 0.16 ela tocava 5% dos pixels com uma
    # variação de sete níveis: existia no código e não na tela.
    "FPS / Multiplayer": Atmosfera(
        grao=0.03, grade=0.5, passo_grade=44, vinheta=0.52, brilho=0.12,
        brilho_y=0.5, forma="chanfrada", semente=43,
    ),
    # Neutro: só profundidade, para não competir com jogo nenhum.
    "Genérico / Outro": Atmosfera(
        grao=0.035, vinheta=0.46, brilho=0.14, brilho_y=0.35,
        forma="arredondada", semente=47,
    ),
}

ATMOSFERA_PADRAO: Final = ATMOSFERAS["Genérico / Outro"]


def atmosfera_de(nome_do_jogo: str) -> Atmosfera:
    return ATMOSFERAS.get(nome_do_jogo, ATMOSFERA_PADRAO)


# ------------------------------------------------------------------ Cursor
# A atmosfera responde ao mouse: uma luz que o segue pela janela, partículas que
# fogem dele e um enxame que desliza em profundidade conforme ele anda. Tudo
# isso só é calculado enquanto o cursor se move SOBRE a janela — com o jogador
# dentro do jogo, o custo é zero.
#
# Raio em que as partículas fogem do cursor, e com que força (px/s no contato).
RAIO_FUGA: Final = 170.0
FORCA_FUGA: Final = 680.0
# A luz: um halo largo e um núcleo, somados ao FUNDO. Ela fica atrás do
# conteúdo, e não no vidro da frente: pintada por cima, ela lavava justamente o
# texto sob o cursor — o lugar para onde a pessoa está olhando. Atrás, ela
# atravessa os painéis translúcidos, e por isso o brilho é mais alto do que
# pareceria necessário.
#
# Atrás do conteúdo, o preço dela é repintar a cada quadro TUDO que está sob a
# caixa que ela ocupa — painéis, rótulos, bolhas, seletores. O halo tinha 460 px
# de raio, e dos 184 px para fora ele somava menos de 7% de uma cor já
# atravessando um painel: uma caixa de 920 px por lado para uma borda que não se
# via. Com 340 px e o degrau do meio no MESMO lugar (a 184 px do centro), a
# parte visível fica igual e a caixa perde 45% da área.
RAIO_LUZ: Final = 340.0
MEIO_LUZ: Final = 184.0 / 340.0
RAIO_NUCLEO: Final = 150.0
BRILHO_LUZ: Final = 0.50
BRILHO_NUCLEO: Final = 0.46
# Quanto o enxame desliza AO CONTRÁRIO do cursor, entre o centro e a borda.
PARALAXE: Final = 22.0
# Rapidez com que a luz alcança o cursor, em 1/s. Alta o bastante para seguir,
# baixa o bastante para ter peso: esse pequeno atraso é o que faz o movimento
# parecer fluido em vez de colado ao ponteiro.
SEGUIMENTO: Final = 11.0
# O anel que acompanha o cursor, com mais pressa que a luz, e que cresce sobre o
# que se pode clicar — o cursor dos sites que respondem ao mouse, desenhado no
# vidro da janela ao lado do ponteiro do sistema, sem substituí-lo.
RAIO_ANEL: Final = 13.0
RAIO_ANEL_CLICAVEL: Final = 22.0
SEGUIMENTO_ANEL: Final = 22.0
# A onda que sai de cada clique: o quanto cresce e quanto tempo dura.
RAIO_ONDA: Final = 46.0
DURACAO_ONDA: Final = 0.55

# A tremulação do tubo vem em RAJADAS: um soluço de brilho de tempos em tempos,
# e não uma oscilação sem fim. Ela é a única camada sem recorte possível — um
# brilho sobre a janela inteira —, e contínua ela repintava TUDO a cada quadro:
# 10 ms por quadro no tema do Fallout, trinta vezes por segundo, aberto atrás do
# próprio Fallout. Em rajadas o tubo continua malcuidado, e o quadro cheio só é
# pago enquanto ele treme. Rara, a rajada pode ser mais forte do que a
# oscilação contínua podia.
DURACAO_RAJADA: Final = 0.45
ESPERA_RAJADA: Final = (2.5, 7.0)
FORCA_RAJADA: Final = 1.6


# ------------------------------------------------------------------- Partículas
@dataclass(slots=True)
class _Particula:
    x: float
    y: float
    vx: float
    vy: float
    tamanho: float
    fase: float
    vida: float = 1.0


class _Enxame:
    """Sistema de partículas com integração por tempo decorrido.

    Integrar por ``dt`` em vez de por quadro mantém a velocidade constante
    quando a máquina engasga — a alternativa (somar um passo fixo por quadro)
    faz a neve cair mais devagar exatamente quando o computador está ocupado.
    """

    # Opacidade de cada modo: base e quanto a oscilação soma a ela.
    ALFAS: Final = {
        "motes": (0.18, 0.42),
        "brasas": (0.20, 0.55),
        "neve": (0.30, 0.25),
        "poeira": (0.10, 0.16),
        "estatica": (0.25, 0.45),
    }
    # Lado do desenho de referência de uma partícula redonda, em pixels.
    LADO_DESENHO = 48

    def __init__(self, modo: str, densidade: int, semente: int) -> None:
        self._modo = modo
        self._rng = random.Random(semente)
        self._particulas: list[_Particula] = []
        self._densidade = densidade
        self._largura = 1
        self._altura = 1
        # A partícula já desenhada, e em que cor. Ver ``_desenho_na_cor``.
        self._desenho: QPixmap | None = None
        self._cor_desenho = ""

    def redimensionar(self, largura: int, altura: int) -> None:
        if (largura, altura) == (self._largura, self._altura):
            return
        self._largura, self._altura = max(1, largura), max(1, altura)
        self._particulas = [self._nascer(inicial=True) for _ in range(self._densidade)]

    def _nascer(self, *, inicial: bool = False) -> _Particula:
        r = self._rng
        larg, alt = self._largura, self._altura
        x = r.uniform(0, larg)
        y = r.uniform(0, alt) if inicial else self._y_de_entrada(alt)
        fase = r.uniform(0, math.tau)

        if self._modo == "motes":
            return _Particula(x, y, r.uniform(-6, 6), r.uniform(-26, -10), r.uniform(1.2, 2.8), fase)
        if self._modo == "neve":
            return _Particula(x, y, r.uniform(-16, 6), r.uniform(26, 62), r.uniform(1.0, 2.4), fase)
        if self._modo == "brasas":
            return _Particula(x, y, r.uniform(-10, 10), r.uniform(-34, -14), r.uniform(0.9, 2.0), fase)
        if self._modo == "poeira":
            return _Particula(x, y, r.uniform(-8, 8), r.uniform(-5, 5), r.uniform(0.8, 1.8), fase)
        if self._modo == "dados":
            return _Particula(x, y, 0.0, r.uniform(160, 420), r.uniform(6, 22), fase)
        # estatica: não se move, apenas pisca e renasce em outro lugar
        return _Particula(x, y, 0.0, 0.0, r.uniform(0.8, 1.6), fase, vida=r.uniform(0.05, 0.6))

    def _y_de_entrada(self, altura: int) -> float:
        if self._modo in ("motes", "brasas"):
            return altura + 8
        if self._modo in ("neve", "dados"):
            return -8
        return self._rng.uniform(0, altura)

    def avancar(self, dt: float, fuga: QPointF | None = None) -> None:
        """Move o enxame. ``fuga`` é o cursor, no espaço das partículas.

        Perto dele, cada partícula é empurrada para longe — mais forte quanto
        mais perto, e nada a partir de ``RAIO_FUGA``. A chuva de dados só
        desvia para o lado: empurrada para cima, ela pareceria subir.
        """
        for i, p in enumerate(self._particulas):
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.fase += dt * 2.2
            if fuga is not None and self._modo != "estatica":
                dx, dy = p.x - fuga.x(), p.y - fuga.y()
                distancia2 = dx * dx + dy * dy
                if 1e-6 < distancia2 < RAIO_FUGA * RAIO_FUGA:
                    distancia = math.sqrt(distancia2)
                    empurrao = (1.0 - distancia / RAIO_FUGA) ** 2 * FORCA_FUGA * dt
                    p.x += dx / distancia * empurrao
                    if self._modo != "dados":
                        p.y += dy / distancia * empurrao
            if self._modo == "estatica":
                p.vida -= dt
                if p.vida <= 0:
                    self._particulas[i] = self._nascer()
                continue
            fora = (
                p.y < -30 or p.y > self._altura + 30
                or p.x < -30 or p.x > self._largura + 30
            )
            if fora:
                self._particulas[i] = self._nascer()

    # Folga somada a cada caixa de partícula. Cobre o antisserrilhado da borda
    # do halo e o arredondamento para pixel inteiro: uma caixa curta por um
    # pixel deixa rastro na tela, que é o defeito que a repintura por região
    # pode produzir e que nenhum teste offscreen enxerga.
    MARGEM = 3

    def caixas(self, deslocamento: QPointF | None = None) -> list[QRect]:
        """Onde cada partícula pinta AGORA, em pixels inteiros.

        Serve à repintura por região: o cenário une estas caixas antes e
        depois de ``avancar`` e pede à sobreposição só a diferença.
        """
        caixas: list[QRect] = []
        for p in self._particulas:
            if self._modo == "dados":
                area = QRectF(p.x, p.y, 1.4, p.tamanho)
            else:
                # O raio máximo do halo: tamanho × (1 + 0.25) × 3.2, com a
                # oscilação no pico. Ver o desenho em ``pintar``.
                raio = p.tamanho * 1.25 * 3.2
                area = QRectF(p.x - raio, p.y - raio, raio * 2, raio * 2)
            if deslocamento is not None:
                area.translate(deslocamento)
            caixas.append(
                area.adjusted(-self.MARGEM, -self.MARGEM, self.MARGEM, self.MARGEM)
                .toAlignedRect()
            )
        return caixas

    def _desenho_na_cor(self, cor: QColor) -> QPixmap:
        """A partícula desenhada UMA vez, em força cheia, na cor das camadas vivas.

        Cada quadro montava um gradiente por partícula — três cores, três
        paradas, um pincel — para desenhar sempre a mesma forma em outro lugar
        e com outra força: 0,40 ms por enxame de 46 motes, a 30 quadros por
        segundo, a tarde inteira, atrás do jogo. Copiado pronto, com a força
        como opacidade, custa 0,11. A soma é linear, e escalar o desenho é o
        mesmo que escalar cada cor do gradiente.
        """
        if self._desenho is not None and self._cor_desenho == cor.name():
            return self._desenho
        transparente = QColor(cor)
        transparente.setAlpha(0)
        if self._modo == "dados":
            # O rastro de um dado: some para cima, acende embaixo.
            imagem = QImage(4, 64, QImage.Format.Format_ARGB32_Premultiplied)
            imagem.fill(Qt.GlobalColor.transparent)
            gradiente = QLinearGradient(0, 0, 0, 64)
            gradiente.setColorAt(0.0, transparente)
            gradiente.setColorAt(1.0, cor)
            pintor = QPainter(imagem)
            pintor.fillRect(imagem.rect(), gradiente)
            pintor.end()
        else:
            # Halo suave em volta do núcleo: sem ele a partícula vira um
            # pontinho duro, que é exatamente a aparência de "bolinha desenhada".
            lado = self.LADO_DESENHO
            raio = lado / 2
            imagem = QImage(lado, lado, QImage.Format.Format_ARGB32_Premultiplied)
            imagem.fill(Qt.GlobalColor.transparent)
            halo = QRadialGradient(QPointF(raio, raio), raio)
            halo.setColorAt(0.0, cor)
            meio = QColor(cor)
            meio.setAlphaF(0.28)
            halo.setColorAt(0.45, meio)
            halo.setColorAt(1.0, transparente)
            pintor = QPainter(imagem)
            pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(halo)
            pintor.drawEllipse(QPointF(raio, raio), raio, raio)
            pintor.end()
        self._desenho = QPixmap.fromImage(imagem)
        self._cor_desenho = cor.name()
        return self._desenho

    def pintar(self, pintor: QPainter, cor: QColor, deslocamento: QPointF | None = None) -> None:
        if not self._particulas:
            return
        desenho = self._desenho_na_cor(cor)
        fonte = QRectF(desenho.rect())
        pintor.save()
        if deslocamento is not None:
            pintor.translate(deslocamento)
        # Composição aditiva: partículas de luz SOMAM ao fundo em vez de o
        # cobrir. É a diferença entre uma faísca e um ponto de tinta.
        pintor.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        pintor.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        if self._modo == "dados":
            for p in self._particulas:
                pintor.setOpacity(min(1.0, 0.25 + 0.35 * (0.5 + 0.5 * math.sin(p.fase))))
                pintor.drawPixmap(QRectF(p.x, p.y, 1.4, p.tamanho), desenho, fonte)
            pintor.restore()
            return

        base, variacao = self.ALFAS.get(self._modo, (0.3, 0.0))
        for p in self._particulas:
            oscilacao = 0.5 + 0.5 * math.sin(p.fase)
            raio = p.tamanho * (1.0 + 0.25 * oscilacao) * 3.2
            pintor.setOpacity(min(1.0, base + variacao * oscilacao))
            pintor.drawPixmap(
                QRectF(p.x - raio, p.y - raio, raio * 2, raio * 2), desenho, fonte
            )
        pintor.restore()


def _juntar_pares(antes: list[QRect], agora: list[QRect]) -> list[QRect]:
    """As caixas de antes e de agora, com cada par que se toca numa caixa só.

    A mesma partícula, um quadro depois, está a um pixel de onde estava: as duas
    caixas quase coincidem, e montar a região com as duas custava o dobro de
    retângulos. Uma partícula que renasceu longe fica com as duas — a união
    delas cobriria a janela.
    """
    caixas: list[QRect] = []
    for a, b in zip(antes, agora, strict=False):
        if a.intersects(b):
            caixas.append(a.united(b))
        else:
            caixas += (a, b)
    menor = min(len(antes), len(agora))
    return caixas + antes[menor:] + agora[menor:]


# ---------------------------------------------------------------------- Cenário
class Cenario:
    """Compõe e desenha a atmosfera. Não é um widget: pinta onde mandarem.

    Manter isto fora da hierarquia de widgets é deliberado — assim a mesma
    atmosfera pode ser pintada no fundo da janela, num painel ou numa
    miniatura de pré-visualização, sem duplicar estado.
    """

    def __init__(self) -> None:
        self._atmosfera = ATMOSFERA_PADRAO
        self._efetiva = ATMOSFERA_PADRAO
        self._tema: GameTheme | None = None
        self._estatico: QPixmap | None = None
        self._vidro: QPixmap | None = None
        self._tamanho = (0, 0)
        self._enxame: _Enxame | None = None
        self._t = 0.0
        self._faixas: list[tuple[float, float, float]] = []
        self._proxima_interferencia = 0.0
        # Caixas que mudaram no último ``avancar``. Ver ``regiao_suja``.
        self._sujas: list[QRect] = []
        self.movimento = True
        self._intensidade = 1.0
        # O cursor que a atmosfera persegue (None = fora da janela), a luz que
        # o alcança com atraso, a força dela (acende e apaga) e o deslize do
        # enxame. Ver ``definir_cursor``.
        self._cursor: QPointF | None = None
        self._luz = QPointF()
        self._forca_luz = 0.0
        self._paralaxe = QPointF()
        # Onde a luz estava e está: a região do FUNDO a repintar. Ver
        # ``regiao_da_luz``.
        self._luz_suja: list[QRect] = []
        self._anel = QPointF()
        self._raio_anel = RAIO_ANEL
        self._sobre_clicavel = False
        # Cada onda de clique: centro e idade, em segundos.
        self._ondas: list[tuple[QPointF, float]] = []
        # A luz já desenhada, com a chave (cores e densidade de pixels) de quando
        # foi feita. Ver ``_desenho_da_luz``.
        self._desenho_luz: QPixmap | None = None
        self._chave_luz: tuple[str, str, float] | None = None
        # A rajada de tremulação em curso (segundos desde o começo; None = o
        # tubo está quieto), quanto falta para a próxima, e se este quadro é o
        # que apaga a última. Ver ``_avancar_tremulacao``.
        self._rajada: float | None = None
        self._proxima_rajada = 0.0
        self._apagar_rajada = False
        self._sorteio_rajada = random.Random(0)

    # -- configuração
    def definir_cursor(self, ponto: QPointF | None, *, sobre_clicavel: bool = False) -> None:
        """Onde está o cursor, em coordenadas da janela; ``None`` quando saiu.

        A luz e o anel nascem EM CIMA do cursor quando ele entra, em vez de
        atravessarem a janela vindos de onde apagaram da última vez.
        ``sobre_clicavel`` faz o anel crescer: ele anuncia o que responde a um
        clique antes do clique.
        """
        if ponto is not None and self._forca_luz <= 0.001:
            self._luz = QPointF(ponto)
            self._anel = QPointF(ponto)
        self._cursor = None if ponto is None else QPointF(ponto)
        self._sobre_clicavel = sobre_clicavel and ponto is not None

    def pulsar(self, ponto: QPointF) -> None:
        """Uma onda sai do ponto do clique: a resposta imediata a qualquer toque."""
        if self.movimento:
            self._ondas.append((QPointF(ponto), 0.0))

    @property
    def anel(self) -> tuple[QPointF, float]:
        """Posição e raio atuais do anel do cursor."""
        return QPointF(self._anel), self._raio_anel

    @property
    def ondas(self) -> int:
        return len(self._ondas)

    @property
    def cursor(self) -> QPointF | None:
        return self._cursor

    @property
    def luz(self) -> tuple[QPointF, float]:
        """Posição e força atuais da luz que segue o cursor."""
        return QPointF(self._luz), self._forca_luz

    @property
    def paralaxe(self) -> QPointF:
        return QPointF(self._paralaxe)

    def _alvo_paralaxe(self) -> QPointF:
        if self._cursor is None:
            return QPointF()
        largura, altura = self._tamanho
        if largura <= 0 or altura <= 0:
            return QPointF()
        # Do centro para a borda, o enxame anda até PARALAXE no sentido oposto
        # ao do cursor: o que está "atrás" da janela se move ao contrário de
        # quem olha, e é isso que o olho lê como profundidade.
        return QPointF(
            (0.5 - self._cursor.x() / largura) * 2 * PARALAXE,
            (0.5 - self._cursor.y() / altura) * 2 * PARALAXE,
        )

    @property
    def seguindo_cursor(self) -> bool:
        """A luz ou o enxame ainda estão a caminho de onde o cursor os quer?

        Com o cursor parado e tudo assentado, não há o que animar: o relógio de
        quadros pode parar mesmo com o mouse em cima da janela.
        """
        if not self.movimento:
            return False
        alvo_forca = 1.0 if self._cursor is not None else 0.0
        if abs(self._forca_luz - alvo_forca) > 0.001:
            return True
        if self._ondas:
            return True
        if self._cursor is None:
            return False
        alvo_raio = RAIO_ANEL_CLICAVEL if self._sobre_clicavel else RAIO_ANEL
        if abs(self._raio_anel - alvo_raio) > 0.1:
            return True
        falta_anel = self._cursor - self._anel
        if abs(falta_anel.x()) + abs(falta_anel.y()) > 0.5:
            return True
        falta = self._cursor - self._luz
        falta_paralaxe = self._alvo_paralaxe() - self._paralaxe
        return (
            abs(falta.x()) + abs(falta.y()) > 0.5
            or abs(falta_paralaxe.x()) + abs(falta_paralaxe.y()) > 0.1
        )

    @property
    def precisa_quadros(self) -> bool:
        """O relógio de quadros tem trabalho: camada viva, ou luz a caminho."""
        return self.tem_camada_viva or self.seguindo_cursor

    def _caixa_luz(self) -> QRect | None:
        if self._forca_luz <= 0.001:
            return None
        return QRectF(
            self._luz.x() - RAIO_LUZ, self._luz.y() - RAIO_LUZ, RAIO_LUZ * 2, RAIO_LUZ * 2
        ).toAlignedRect()

    def regiao_da_luz(self) -> QRegion:
        """O pedaço do fundo que a luz ocupava e ocupa, para repintar só ele."""
        regiao = QRegion()
        for caixa in self._luz_suja:
            regiao += QRegion(caixa)
        return regiao

    def _seguir_cursor(self, dt: float) -> None:
        passo = 1.0 - math.exp(-SEGUIMENTO * dt)
        alvo_forca = 1.0 if self._cursor is not None else 0.0
        self._forca_luz += (alvo_forca - self._forca_luz) * (1.0 - math.exp(-6.0 * dt))
        if abs(self._forca_luz - alvo_forca) <= 0.001:
            self._forca_luz = alvo_forca
        if self._cursor is not None:
            self._luz += (self._cursor - self._luz) * passo
            passo_anel = 1.0 - math.exp(-SEGUIMENTO_ANEL * dt)
            self._anel += (self._cursor - self._anel) * passo_anel
            alvo_raio = RAIO_ANEL_CLICAVEL if self._sobre_clicavel else RAIO_ANEL
            self._raio_anel += (alvo_raio - self._raio_anel) * passo_anel
        self._paralaxe += (self._alvo_paralaxe() - self._paralaxe) * passo
        self._ondas = [(c, idade + dt) for c, idade in self._ondas if idade + dt < DURACAO_ONDA]
    def definir(self, tema: GameTheme, atmosfera: Atmosfera) -> None:
        self._tema = tema
        self._atmosfera = atmosfera
        self._sorteio_rajada = random.Random(atmosfera.semente)
        self._proxima_rajada = self._sorteio_rajada.uniform(*ESPERA_RAJADA)
        self._rajada = None
        self._invalidar()
        self._faixas.clear()

    def definir_intensidade(self, valor: float) -> None:
        """Regula a atmosfera inteira de 0 (desligada) a 1 (cheia).

        Uma tela de fósforo com varredura é bonita e é, ao mesmo tempo, um
        obstáculo de leitura para quem tem baixa visão ou sensibilidade a
        cintilação. Um efeito com esta força precisa de um controle no
        alcance do usuário; sem ele, o que sobra é uma escolha estética
        imposta.
        """
        valor = max(0.0, min(1.0, valor))
        if valor != self._intensidade:
            self._intensidade = valor
            self._invalidar()

    def _invalidar(self) -> None:
        """Descarta o que foi calculado para a receita antiga.

        O enxame entra aqui junto com os pixmaps porque a densidade é parte da
        receita EFETIVA, não da declarada: antes, ``definir_intensidade`` só
        invalidava as camadas estáticas e o enxame seguia com a contagem cheia
        de partículas — 'Discreta' apagava a varredura e o grão, mas a neve
        continuava caindo com a mesma força. Pelo mesmo motivo o enxame é
        reconstruído ao trocar de jogo, que antes restaurava a densidade
        integral de quem estava em 'Discreta'.
        """
        self._estatico = None
        self._vidro = None
        self._efetiva = self._calcular_efetiva()
        efetiva = self._efetiva
        self._enxame = (
            _Enxame(efetiva.particulas, efetiva.densidade, efetiva.semente)
            if efetiva.particulas and efetiva.densidade > 0
            else None
        )

    def _calcular_efetiva(self) -> Atmosfera:
        """A receita declarada, atenuada pela intensidade escolhida.

        Calculada AQUI, no ponto de invalidação, e não numa propriedade lida a
        cada acesso: ``avancar`` a consultava duas vezes e ``pintar_sobreposicao``
        uma, o que dava três construções de dataclass por quadro, por janela,
        trinta vezes por segundo — num módulo cujo desenho inteiro existe para
        tornar 30 fps viáveis em Python. Receita e intensidade só mudam por
        ``definir`` e ``definir_intensidade``, e ambas passam por ``_invalidar``.
        """
        i = self._intensidade
        a = self._atmosfera
        if i >= 0.999:
            return a
        return replace(
            a,
            grao=a.grao * i, varredura=a.varredura * i, vinheta=a.vinheta * i,
            brilho=a.brilho * i, grade=a.grade * i, fibras=a.fibras * i,
            tremulacao=a.tremulacao * i, interferencia=a.interferencia * i,
            densidade=int(a.densidade * i),
        )

    def redimensionar(self, largura: int, altura: int) -> None:
        if (largura, altura) != self._tamanho:
            self._tamanho = (largura, altura)
            self._estatico = None
            self._vidro = None
        if self._enxame is not None:
            self._enxame.redimensionar(largura, altura)

    def avancar(self, dt: float) -> None:
        if not self.movimento:
            return
        antes = self._caixas_vivas()
        luz_antes = self._caixa_luz()
        self._t += dt
        self._seguir_cursor(dt)
        luz_agora = self._caixa_luz()
        self._luz_suja = [c for c in (luz_antes, luz_agora) if c is not None]
        if self._enxame is not None:
            # O cursor está em coordenadas da janela; o enxame é desenhado
            # deslocado pelo parallax, e é contra ESSA posição que ele foge.
            fuga = None if self._cursor is None else self._cursor - self._paralaxe
            self._enxame.avancar(dt, fuga)
        if self._efetiva.interferencia > 0:
            self._avancar_interferencia(dt)
        if self._efetiva.tremulacao > 0:
            self._avancar_tremulacao(dt)
        # O que mudou é a união de onde as camadas vivas ESTAVAM com onde elas
        # ESTÃO: a caixa nova cobre a partícula desenhada, a velha apaga o
        # rastro que ela deixaria para trás.
        self._sujas = _juntar_pares(antes, self._caixas_vivas())

    def _caixas_vivas(self) -> list[QRect]:
        """Caixas ocupadas pelas camadas que se movem, no estado atual."""
        caixas: list[QRect] = []
        if self._enxame is not None:
            caixas += self._enxame.caixas(self._paralaxe)
        if self._forca_luz > 0.001:
            r = RAIO_ANEL_CLICAVEL + 4
            caixas.append(QRectF(self._anel.x() - r, self._anel.y() - r, 2 * r, 2 * r).toAlignedRect())
        for centro, _ in self._ondas:
            r = RAIO_ONDA + 4
            caixas.append(QRectF(centro.x() - r, centro.y() - r, 2 * r, 2 * r).toAlignedRect())
        if self._faixas:
            largura = self._tamanho[0] or 1
            for y, altura, _ in self._faixas:
                # As faixas de interferência atravessam a janela inteira.
                caixas.append(
                    QRectF(0, y - 2, largura, altura + 4).toAlignedRect()
                )
        return caixas

    def regiao_suja(self) -> QRegion | None:
        """O que precisa ser repintado neste quadro. ``None`` = a tela toda.

        A sobreposição repintava a janela inteira trinta vezes por segundo
        para mexer alguns pontos de luz: 1,8 a 2,2 ms por quadro numa janela
        de 1920×1032, ou 5 a 7% de um núcleo — permanentes, num programa cuja
        razão de existir é ficar aberto ATRÁS de um jogo. Recortada nas
        partículas, a mesma cena custa 0,02 a 0,84 ms.

        Duas camadas não têm recorte possível e devolvem ``None``, pedindo o
        quadro cheio: a tremulação do tubo, que é uma variação de brilho sobre
        a imagem inteira — enquanto dura uma rajada, e no quadro que a apaga —,
        e o primeiro quadro depois de uma troca de tema.
        """
        if not self.movimento:
            return QRegion()
        if self._efetiva.tremulacao > 0 and (self._rajada is not None or self._apagar_rajada):
            return None
        regiao = QRegion()
        for caixa in self._sujas:
            regiao += QRegion(caixa)
        return regiao

    @property
    def tem_camada_viva(self) -> bool:
        """Existe alguma camada que muda com o tempo neste ambiente?

        Dois dos dez ambientes não têm partícula, tremulação nem
        interferência: para eles o relógio de quadros repintava,
        indefinidamente, uma imagem idêntica à anterior.
        """
        a = self._efetiva
        return bool(a.particulas) or a.tremulacao > 0 or a.interferencia > 0

    @property
    def tremendo(self) -> bool:
        """Há uma rajada de tremulação em curso?"""
        return self._rajada is not None

    def _avancar_tremulacao(self, dt: float) -> None:
        """Conta o tempo da rajada em curso, ou o que falta para a próxima."""
        tremia = self._rajada is not None
        if self._rajada is None:
            self._proxima_rajada -= dt
            if self._proxima_rajada <= 0:
                self._rajada = 0.0
        else:
            self._rajada += dt
            if self._rajada >= DURACAO_RAJADA:
                self._rajada = None
                self._proxima_rajada = self._sorteio_rajada.uniform(*ESPERA_RAJADA)
        # O brilho da rajada ficou na tela: o quadro seguinte também é cheio.
        self._apagar_rajada = tremia and self._rajada is None

    def _avancar_interferencia(self, dt: float) -> None:
        """Faixas de ruído que aparecem em rajadas, não continuamente.

        Interferência constante vira textura e o olho para de vê-la. Em
        rajadas espaçadas, ela continua sendo interferência.
        """
        self._proxima_interferencia -= dt
        if self._proxima_interferencia <= 0:
            rng = random.Random(int(self._t * 1000) ^ self._efetiva.semente)
            self._proxima_interferencia = rng.uniform(1.4, 4.5)
            altura = self._tamanho[1] or 1
            quantidade = rng.randint(1, 3)
            self._faixas = [
                (rng.uniform(0, altura), rng.uniform(1.5, 5.0), rng.uniform(0.10, 0.30))
                for _ in range(quantidade)
            ]
        self._faixas = [(y, h, a - dt * 0.55) for (y, h, a) in self._faixas if a > 0.01]

    # -- desenho
    def pintar_fundo(self, pintor: QPainter, largura: int, altura: int) -> None:
        """Camada de trás: cor de base, halo, grade e fibras. Tudo estático."""
        if self._tema is None or largura <= 0 or altura <= 0:
            return
        self.redimensionar(largura, altura)
        if self._estatico is None:
            self._estatico = self._compor_estatico(largura, altura)
        pintor.drawPixmap(0, 0, self._estatico)
        if self._forca_luz > 0.001 and self.movimento:
            self._pintar_luz(pintor)

    def pintar_sobreposicao(self, pintor: QPainter, largura: int, altura: int) -> None:
        """Camada de vidro, desenhada POR CIMA de todo o conteúdo.

        É aqui que mora a diferença entre "um fundo bonito atrás da janela" e
        "a janela está dentro de um tubo de raios catódicos". Varredura,
        grão, vinheta e tremulação de um CRT não param no conteúdo: eles
        atravessam a imagem inteira, texto incluído. Colocar essas camadas
        atrás dos painéis, como estava, desperdiçava o efeito exatamente onde
        o olho passa mais tempo.
        """
        if self._tema is None or largura <= 0 or altura <= 0:
            return
        a = self._efetiva
        if self._vidro is None or self._vidro.size().toTuple() != (largura, altura):
            self._vidro = self._compor_vidro(largura, altura)
        pintor.drawPixmap(0, 0, self._vidro)

        cor_viva = QColor(a.cor_viva or self._tema.accent)

        if self._enxame is not None and self.movimento:
            self._enxame.pintar(pintor, cor_viva, self._paralaxe)

        if self.movimento:
            self._pintar_anel_e_ondas(pintor)

        if self._faixas and self.movimento:
            pintor.save()
            pintor.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            pintor.setPen(Qt.PenStyle.NoPen)
            for y, h, alfa in self._faixas:
                c = QColor(cor_viva)
                c.setAlphaF(min(1.0, alfa * a.interferencia))
                pintor.setBrush(c)
                pintor.drawRect(QRectF(0, y, largura, h))
            pintor.restore()

        if a.tremulacao > 0 and self.movimento and self._rajada is not None:
            # O soluço do tubo: o brilho sobe e desce dentro da rajada, com um
            # chiado rápido por cima. Uma senoide sozinha parece pulsação de
            # LED, não tela velha.
            envelope = math.sin(math.pi * min(1.0, self._rajada / DURACAO_RAJADA))
            chiado = 0.6 + 0.4 * math.sin(self._rajada * 43.0)
            forca = envelope * chiado * a.tremulacao * FORCA_RAJADA
            if forca > 0:
                pintor.save()
                pintor.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
                c = QColor(self._tema.primary)
                c.setAlphaF(min(1.0, forca))
                pintor.fillRect(QRectF(0, 0, largura, altura), c)
                pintor.restore()

    def _pintar_anel_e_ondas(self, pintor: QPainter) -> None:
        """O anel que persegue o cursor e as ondas dos cliques, no vidro."""
        if self._tema is None:
            return
        pintor.save()
        pintor.setBrush(Qt.BrushStyle.NoBrush)
        cor = QColor(self._tema.accent)
        forca = self._forca_luz * self._intensidade
        if forca > 0.001:
            crescido = (self._raio_anel - RAIO_ANEL) / (RAIO_ANEL_CLICAVEL - RAIO_ANEL)
            contorno = QColor(cor)
            contorno.setAlphaF(min(1.0, 0.85 * forca))
            caneta = QPen(contorno)
            caneta.setWidthF(1.6)
            pintor.setPen(caneta)
            if crescido > 0.01:
                # Sobre o que é clicável, o anel ganha um miolo: vira alvo.
                miolo = QColor(cor)
                miolo.setAlphaF(min(1.0, 0.14 * crescido * forca))
                pintor.setBrush(miolo)
            pintor.drawEllipse(self._anel, self._raio_anel, self._raio_anel)
            pintor.setBrush(Qt.BrushStyle.NoBrush)
        curva = QEasingCurve(QEasingCurve.Type.OutCubic)
        for centro, idade in self._ondas:
            progresso = idade / DURACAO_ONDA
            raio = 8.0 + (RAIO_ONDA - 8.0) * curva.valueForProgress(progresso)
            onda = QColor(cor)
            onda.setAlphaF(max(0.0, 0.75 * (1.0 - progresso)) * self._intensidade)
            caneta = QPen(onda)
            caneta.setWidthF(0.6 + 2.2 * (1.0 - progresso))
            pintor.setPen(caneta)
            pintor.drawEllipse(centro, raio, raio)
        pintor.restore()

    def _pintar_luz(self, pintor: QPainter) -> None:
        """A luz que segue o cursor: um halo largo e um núcleo, somados.

        O halo tem a cor principal do tema e o núcleo, a de destaque: âmbar no
        verde do Fallout, ciano no amarelo do Cyberpunk. Uma luz da mesma cor
        do fundo se confundia com ele; duas cores fazem o ponto quente se ver.

        A força entra como opacidade sobre o desenho pronto: a soma é linear,
        e escalar o desenho inteiro é o mesmo que escalar cada gradiente.
        """
        if self._tema is None:
            return
        dispositivo = pintor.device()
        densidade = dispositivo.devicePixelRatioF() if dispositivo is not None else 1.0
        desenho = self._desenho_da_luz(densidade)
        pintor.save()
        pintor.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        pintor.setOpacity(min(1.0, self._forca_luz * self._intensidade))
        pintor.drawPixmap(
            QPointF(self._luz.x() - RAIO_LUZ, self._luz.y() - RAIO_LUZ), desenho
        )
        pintor.restore()

    def _desenho_da_luz(self, densidade: float) -> QPixmap:
        """Halo e núcleo compostos UMA vez por tema, em força cheia.

        Dois gradientes radiais recalculados pixel a pixel a cada quadro
        custavam 0,59 ms numa caixa de 680 px; copiar o desenho pronto com
        opacidade custa 0,10. A luz se move a cada quadro, mas o desenho dela
        não muda.
        """
        assert self._tema is not None
        chave = (self._tema.primary, self._tema.accent, densidade)
        if self._desenho_luz is not None and self._chave_luz == chave:
            return self._desenho_luz
        lado = math.ceil(2 * RAIO_LUZ * densidade)
        imagem = QImage(lado, lado, QImage.Format.Format_ARGB32_Premultiplied)
        imagem.setDevicePixelRatio(densidade)
        imagem.fill(Qt.GlobalColor.transparent)
        pintor = QPainter(imagem)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        pintor.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        pintor.setPen(Qt.PenStyle.NoPen)
        centro = QPointF(RAIO_LUZ, RAIO_LUZ)
        camadas = (
            (RAIO_LUZ, BRILHO_LUZ, self._tema.primary, MEIO_LUZ),
            (RAIO_NUCLEO, BRILHO_NUCLEO, self._tema.accent, 0.4),
        )
        for raio, brilho, cor, degrau in camadas:
            gradiente = QRadialGradient(centro, raio)
            perto = QColor(cor)
            perto.setAlphaF(min(1.0, brilho))
            meio = QColor(perto)
            meio.setAlphaF(perto.alphaF() * 0.35)
            longe = QColor(perto)
            longe.setAlphaF(0.0)
            gradiente.setColorAt(0.0, perto)
            gradiente.setColorAt(degrau, meio)
            gradiente.setColorAt(1.0, longe)
            pintor.setBrush(gradiente)
            pintor.drawEllipse(centro, raio, raio)
        pintor.end()
        self._desenho_luz = QPixmap.fromImage(imagem)
        self._chave_luz = chave
        return self._desenho_luz

    def _compor_vidro(self, largura: int, altura: int) -> QPixmap:
        """Camadas fixas da sobreposição, também cacheadas num pixmap."""
        a = self._efetiva
        mapa = QPixmap(largura, altura)
        mapa.fill(QColor(0, 0, 0, 0))
        pintor = QPainter(mapa)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        if a.grao > 0:
            self._camada_grao(pintor, largura, altura, a)
        if a.varredura > 0:
            self._camada_varredura(pintor, largura, altura, a)
        if a.grade > 0 and self._tema is not None:
            # A grade é uma RETÍCULA, não um papel de parede: pertence ao
            # vidro, junto da varredura, e não ao fundo. No fundo ela ficava
            # atrás da lateral (90% opaca) e do painel da conversa (62%) e só
            # sobrevivia nas margens — o 'visor tático', cuja identidade
            # inteira é essa grade, media 2.52 de diferença contra o tema
            # deliberadamente neutro, que mede 2.64. A camada existia e não
            # aparecia.
            self._camada_grade(pintor, largura, altura, a, self._tema)
        if a.vinheta > 0:
            self._camada_vinheta(pintor, largura, altura, a)
        pintor.end()
        return mapa

    # -- camadas estáticas
    def _compor_estatico(self, largura: int, altura: int) -> QPixmap:
        a = self._efetiva
        t = self._tema
        assert t is not None  # os chamadores só compõem depois de definir()
        mapa = QPixmap(largura, altura)
        mapa.fill(QColor(t.screen))

        pintor = QPainter(mapa)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)

        if a.brilho > 0:
            self._camada_brilho(pintor, largura, altura, a, t)
        if a.fibras > 0:
            self._camada_fibras(pintor, largura, altura, a, t)
        pintor.end()
        return mapa

    @staticmethod
    def _camada_brilho(
        pintor: QPainter, largura: int, altura: int, a: Atmosfera, t: GameTheme
    ) -> None:
        gradiente = QRadialGradient(
            QPointF(largura / 2, altura * a.brilho_y), max(largura, altura) * 0.75
        )
        centro = QColor(t.accent if a.brilho_y > 0.6 else t.primary)
        centro.setAlphaF(a.brilho * 0.30)
        gradiente.setColorAt(0.0, centro)
        meio = QColor(centro)
        meio.setAlphaF(a.brilho * 0.10)
        gradiente.setColorAt(0.45, meio)
        fim = QColor(centro)
        fim.setAlpha(0)
        gradiente.setColorAt(1.0, fim)
        pintor.save()
        pintor.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        pintor.fillRect(QRectF(0, 0, largura, altura), gradiente)
        pintor.restore()

    @staticmethod
    def _camada_grade(
        pintor: QPainter, largura: int, altura: int, a: Atmosfera, t: GameTheme
    ) -> None:
        cor = QColor(t.primary)
        cor.setAlphaF(a.grade * 0.22)
        pintor.setPen(cor)
        passo = a.passo_grade
        for x in range(0, largura, passo):
            pintor.drawLine(x, 0, x, altura)
        for y in range(0, altura, passo):
            pintor.drawLine(0, y, largura, y)
        # Marcas de referência a cada quatro divisões: é o detalhe que
        # transforma uma grade genérica em visor de instrumento.
        forte = QColor(t.primary)
        forte.setAlphaF(a.grade * 0.5)
        pintor.setPen(forte)
        for x in range(0, largura, passo * 4):
            for y in range(0, altura, passo * 4):
                pintor.drawLine(x - 4, y, x + 4, y)
                pintor.drawLine(x, y - 4, x, y + 4)

    @staticmethod
    def _camada_fibras(
        pintor: QPainter, largura: int, altura: int, a: Atmosfera, t: GameTheme
    ) -> None:
        rng = random.Random(a.semente * 13)
        for _ in range(int(altura * a.fibras * 1.4)):
            y = rng.uniform(0, altura)
            comprimento = rng.uniform(largura * 0.15, largura * 0.9)
            x = rng.uniform(-largura * 0.1, largura * 0.9)
            cor = QColor(t.primary)
            cor.setAlphaF(rng.uniform(0.010, 0.038))
            pintor.setPen(cor)
            pintor.drawLine(QPointF(x, y), QPointF(x + comprimento, y + rng.uniform(-1, 1)))

    @staticmethod
    def _camada_grao(pintor: QPainter, largura: int, altura: int, a: Atmosfera) -> None:
        """Grão gerado uma vez num ladrilho e repetido.

        Sortear ruído para cada pixel da janela custaria centenas de
        milissegundos em Python. Um ladrilho de 160 px preenchido de uma vez a
        partir de um ``bytearray`` custa menos de um milissegundo e se repete
        sem emenda perceptível sob esta opacidade.
        """
        lado = 160
        rng = random.Random(a.semente)
        dados = bytearray(lado * lado * 4)
        alfa_max = int(255 * min(1.0, a.grao))
        for i in range(0, len(dados), 4):
            v = rng.randint(60, 255)
            dados[i] = dados[i + 1] = dados[i + 2] = v
            dados[i + 3] = rng.randint(0, alfa_max)
        imagem = QImage(bytes(dados), lado, lado, QImage.Format.Format_ARGB32).copy()
        ladrilho = QPixmap.fromImage(imagem)
        pintor.save()
        pintor.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        for x in range(0, largura, lado):
            for y in range(0, altura, lado):
                pintor.drawPixmap(x, y, ladrilho)
        pintor.restore()

    @staticmethod
    def _camada_varredura(pintor: QPainter, largura: int, altura: int, a: Atmosfera) -> None:
        escuro = QColor(0, 0, 0)
        escuro.setAlphaF(min(1.0, a.varredura))
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(escuro)
        for y in range(0, altura, a.passo_varredura):
            pintor.drawRect(QRectF(0, y, largura, 1))

    @staticmethod
    def _camada_vinheta(pintor: QPainter, largura: int, altura: int, a: Atmosfera) -> None:
        # A curvatura estica o gradiente na horizontal, o que dá a leitura de
        # um tubo abaulado em vez de uma moldura escura chapada.
        raio = max(largura, altura) * (0.78 - 0.18 * a.curvatura)
        gradiente = QRadialGradient(QPointF(largura / 2, altura / 2), raio)
        transparente = QColor(0, 0, 0, 0)
        gradiente.setColorAt(0.0, transparente)
        gradiente.setColorAt(0.55, transparente)
        meio = QColor(0, 0, 0)
        meio.setAlphaF(a.vinheta * 0.35)
        gradiente.setColorAt(0.82, meio)
        borda = QColor(0, 0, 0)
        borda.setAlphaF(a.vinheta)
        gradiente.setColorAt(1.0, borda)
        pintor.fillRect(QRectF(0, 0, largura, altura), gradiente)
