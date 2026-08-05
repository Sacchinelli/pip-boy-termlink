"""Sistema de design: tokens visuais, escala tipográfica e derivação de cor.

Quatro decisões sustentam a aparência do programa:

1. **Nenhuma cor derivada é escrita à mão.** Cada tema declara oito cores-base.
   Superfícies elevadas, bordas, estados de foco, realce de seleção e as
   variantes legíveis de texto são *calculadas* a partir delas. Um jogo novo
   ganha o sistema visual inteiro sem uma linha extra em ``themes.py``.

2. **Contraste é garantido, não conferido.** ``garantir_contraste`` levanta a
   luminosidade de uma cor preservando o matiz até bater a razão 4.5:1 da
   WCAG. Antes disso, o texto de erro do tema Elden Ring ficava em 2.9:1 —
   ilegível justamente na mensagem mais importante da tela.

3. **Espaçamento e tipografia vivem numa escala.** Medidas soltas (8, 9, 10,
   16, padx=6, pady=3, padx=16…) produzem desalinhamento que o olho percebe
   sem saber nomear. Aqui tudo sai de uma grade de 4 px e de uma rampa de
   sete tamanhos.

4. **Medidas são independentes de dispositivo.** O Qt 6 é ciente de DPI por
   conta própria: os números aqui são pixels lógicos e o próprio Qt os escala
   no monitor. A conversão manual que existia para o Tkinter foi removida
   junto com ele.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass
from functools import lru_cache
from typing import Final

# ---------------------------------------------------------------- Espaçamento
# Grade de 4 px. Todo padding, gap e margem da interface sai daqui.
ESPACO_XS: Final = 4
ESPACO_SM: Final = 8
ESPACO_MD: Final = 12
ESPACO_LG: Final = 16
ESPACO_XL: Final = 24
ESPACO_XXL: Final = 32

# Medidas de componentes, em pixels lógicos (passam por px()).
BORDA: Final = 1
RAIO: Final = 10            # canto das superfícies arredondadas
RAIO_PEQUENO: Final = 6
MEDIDOR_BARRAS: Final = 18
MEDIDOR_LARGURA_BARRA: Final = 3
MEDIDOR_ESPACO_BARRA: Final = 2
MEDIDOR_ALTURA: Final = 16
PILULA_ALTURA: Final = 26
LARGURA_LATERAL: Final = 296
CABECALHO_LARGURA_MAX: Final = 206
BOLHA_LARGURA_MAX: Final = 560


# ---------------------------------------------------------------- Tipografia
@dataclass(frozen=True, slots=True)
class Tipo:
    """Um degrau da rampa tipográfica."""

    tamanho: int
    peso: str = "normal"
    estilo: str = "roman"


TIPO: Final[dict[str, Tipo]] = {
    "display": Tipo(19, "bold"),      # marca, na fonte temática
    "titulo": Tipo(12, "bold"),       # nome de quem fala
    "secao": Tipo(9, "bold"),         # "Ensino", "Áudio" — divisórias da lateral
    "rotulo": Tipo(9),                # rótulo de campo
    "corpo": Tipo(11),                # conversa e campo de texto
    "corpo_forte": Tipo(10, "bold"),  # botões
    "aux": Tipo(10),                  # comboboxes, metadados
    "legenda": Tipo(9),               # subtítulo, chips
    "micro": Tipo(8),                 # hora, autor, sistema
    "vocab": Tipo(10, "normal", "italic"),
}

# Famílias neutras para os CONTROLES. A fonte temática de cada jogo continua
# assinando a marca e a fala do assistente — é ali que ela cria identidade.
# Aplicada também a rótulo, botão e campo, ela fazia a janela inteira parecer
# um documento do Word (nos temas serifados) ou um terminal (nos monoespaçados),
# que é a diferença entre um produto e um utilitário.
FONTES_UI: Final[tuple[str, ...]] = (
    "Segoe UI Variable Text",
    "Segoe UI",
    "Inter",
    "Roboto",
    "DejaVu Sans",
    "Arial",
)


# --------------------------------------------------------------------- Cor
def _rgb(cor: str) -> tuple[float, float, float]:
    valor = cor.lstrip("#")
    return tuple(int(valor[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgb)


@lru_cache(maxsize=2048)
def misturar(a: str, b: str, t: float) -> str:
    """Interpola duas cores. ``t=0`` devolve ``a``; ``t=1`` devolve ``b``."""
    return _hex(tuple(x + (y - x) * t for x, y in zip(_rgb(a), _rgb(b), strict=True)))  # type: ignore[arg-type]


def _linearizar(canal: float) -> float:
    return canal / 12.92 if canal <= 0.03928 else ((canal + 0.055) / 1.055) ** 2.4


@lru_cache(maxsize=2048)
def luminancia(cor: str) -> float:
    """Luminância relativa da WCAG (0.0 = preto, 1.0 = branco)."""
    r, g, b = (_linearizar(c) for c in _rgb(cor))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


@lru_cache(maxsize=4096)
def contraste(a: str, b: str) -> float:
    """Razão de contraste da WCAG entre duas cores (1.0 a 21.0)."""
    la, lb = luminancia(a), luminancia(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


@lru_cache(maxsize=2048)
def elevar(fundo: str, quantidade: float, matiz: str) -> str:
    """Superfície um degrau acima do fundo.

    Clareia de forma quase neutra e só então aplica um véu do matiz do tema. A
    versão anterior misturava direto com a cor principal, e uma superfície com
    5% de verde-fósforo puro sai *colorida*, não elevada — o efeito é de
    remendo, não de profundidade. Interfaces escuras modernas guardam a
    saturação para o acento e mantêm as superfícies quase cinzas.
    """
    return misturar(misturar(fundo, "#ffffff", quantidade), matiz, quantidade * 0.35)


@lru_cache(maxsize=512)
def legivel_sobre(fundo: str) -> str:
    """Tom de texto — quase-preto ou quase-branco — que melhor lê sobre o fundo.

    Usado nos botões preenchidos, onde o texto assenta sobre a cor do tema em
    vez de sobre o fundo da tela.
    """
    escuro, claro = "#0b0b0c", "#f6f7f8"
    return escuro if contraste(escuro, fundo) >= contraste(claro, fundo) else claro


@lru_cache(maxsize=2048)
def garantir_contraste(frente: str, fundo: str, minimo: float = 4.5) -> str:
    """Ajusta a luminosidade da cor até ela atingir o contraste mínimo.

    O matiz e a saturação são preservados, então a cor continua reconhecível
    como "o vermelho daquele tema" — apenas legível. Se nem o extremo da
    escala bastar (cinza sobre cinza), devolve o melhor resultado alcançado
    em vez de falhar.
    """
    if contraste(frente, fundo) >= minimo:
        return frente

    clarear = luminancia(fundo) < 0.5
    h, luz, s = colorsys.rgb_to_hls(*_rgb(frente))
    passo = 0.015 if clarear else -0.015
    melhor, melhor_contraste = frente, contraste(frente, fundo)

    for _ in range(80):
        luz = max(0.0, min(1.0, luz + passo))
        candidato = _hex(colorsys.hls_to_rgb(h, luz, s))
        atual = contraste(candidato, fundo)
        if atual > melhor_contraste:
            melhor, melhor_contraste = candidato, atual
        if atual >= minimo:
            return candidato
        if luz <= 0.0 or luz >= 1.0:
            break
    return melhor


def css_selecao(fundo: str, acento: str, texto: str) -> str:
    """Trecho de folha de estilo para o texto SELECIONADO sobre uma superfície.

    Um ``QLabel`` selecionável sem estas duas propriedades cai no destaque do
    sistema: no Windows, um bloco cinza-lavanda com texto escuro. Num terminal
    de fósforo verde ou num pergaminho dourado, selecionar uma palavra —
    exatamente o que se faz para copiá-la, e este programa é um caderno de
    vocabulário — acendia um retângulo claro de outro desenho.

    O realce é derivado do fundo REAL do widget, e não do ``screen`` do tema:
    uma bolha assenta sobre ``surface_alta``, e um destaque calculado contra a
    tela ficaria escuro demais ali. A cor do texto é elevada até 4.5:1 contra o
    realce que ela mesma vai receber.
    """
    realce = misturar(fundo, acento, 0.35)
    frente = garantir_contraste(texto, realce)
    if contraste(frente, realce) < 4.5:
        # O ajuste que preserva o matiz tem teto: o amarelo do Cyberpunk sobre
        # o ciano do próprio realce empaca em 4.30:1, porque não existe amarelo
        # escuro o bastante que ainda seja amarelo. Aqui a legibilidade ganha da
        # identidade — é a mesma decisão que os botões preenchidos já tomam com
        # ``legivel_sobre``, e o realce continua na cor do tema de qualquer modo.
        frente = legivel_sobre(realce)
    return (
        f"selection-background-color: {realce}; selection-color: {frente};"
    )
