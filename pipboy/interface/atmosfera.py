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

from PySide6.QtCore import QPointF, QRectF, Qt

if TYPE_CHECKING:
    from ..themes import GameTheme
from PySide6.QtGui import (
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPixmap,
    QRadialGradient,
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

    def __init__(self, modo: str, densidade: int, semente: int) -> None:
        self._modo = modo
        self._rng = random.Random(semente)
        self._particulas: list[_Particula] = []
        self._densidade = densidade
        self._largura = 1
        self._altura = 1

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

    def avancar(self, dt: float) -> None:
        for i, p in enumerate(self._particulas):
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.fase += dt * 2.2
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

    def pintar(self, pintor: QPainter, cor: QColor) -> None:
        if not self._particulas:
            return
        pintor.save()
        # Composição aditiva: partículas de luz SOMAM ao fundo em vez de o
        # cobrir. É a diferença entre uma faísca e um ponto de tinta.
        pintor.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        pintor.setPen(Qt.PenStyle.NoPen)

        for p in self._particulas:
            if self._modo == "dados":
                brilho = 0.25 + 0.35 * (0.5 + 0.5 * math.sin(p.fase))
                c = QColor(cor)
                c.setAlphaF(min(1.0, brilho))
                gradiente = QLinearGradient(p.x, p.y, p.x, p.y + p.tamanho)
                transparente = QColor(cor)
                transparente.setAlpha(0)
                gradiente.setColorAt(0.0, transparente)
                gradiente.setColorAt(1.0, c)
                pintor.setBrush(gradiente)
                pintor.drawRect(QRectF(p.x, p.y, 1.4, p.tamanho))
                continue

            oscilacao = 0.5 + 0.5 * math.sin(p.fase)
            alfa = {
                "motes": 0.18 + 0.42 * oscilacao,
                "brasas": 0.20 + 0.55 * oscilacao,
                "neve": 0.30 + 0.25 * oscilacao,
                "poeira": 0.10 + 0.16 * oscilacao,
                "estatica": 0.25 + 0.45 * oscilacao,
            }.get(self._modo, 0.3)

            raio = p.tamanho * (1.0 + 0.25 * oscilacao)
            c = QColor(cor)
            c.setAlphaF(min(1.0, alfa))
            # Halo suave em volta do núcleo: sem ele a partícula vira um
            # pontinho duro, que é exatamente a aparência de "bolinha desenhada".
            halo = QRadialGradient(QPointF(p.x, p.y), raio * 3.2)
            halo.setColorAt(0.0, c)
            meio = QColor(c)
            meio.setAlphaF(c.alphaF() * 0.28)
            halo.setColorAt(0.45, meio)
            fim = QColor(c)
            fim.setAlpha(0)
            halo.setColorAt(1.0, fim)
            pintor.setBrush(halo)
            pintor.drawEllipse(QPointF(p.x, p.y), raio * 3.2, raio * 3.2)
        pintor.restore()


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
        self.movimento = True
        self._intensidade = 1.0

    # -- configuração
    def definir(self, tema: GameTheme, atmosfera: Atmosfera) -> None:
        self._tema = tema
        self._atmosfera = atmosfera
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
        self._t += dt
        if self._enxame is not None:
            self._enxame.avancar(dt)
        if self._efetiva.interferencia > 0:
            self._avancar_interferencia(dt)

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
            self._enxame.pintar(pintor, cor_viva)

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

        if a.tremulacao > 0 and self.movimento:
            # Tremulação do tubo: uma oscilação lenta somada a um chiado
            # rápido de amplitude menor. Uma senoide sozinha parece pulsação
            # de LED, não tela velha.
            osc = math.sin(self._t * 5.1) * 0.6 + math.sin(self._t * 31.7) * 0.4
            if osc > 0:
                pintor.save()
                pintor.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
                c = QColor(self._tema.primary)
                c.setAlphaF(min(1.0, osc * a.tremulacao))
                pintor.fillRect(QRectF(0, 0, largura, altura), c)
                pintor.restore()

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
