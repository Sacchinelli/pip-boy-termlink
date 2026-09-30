"""As fontes que acompanham o programa: a tipografia de cada jogo, de verdade.

Paleta, ornamento e movimento já eram do jogo; a letra, só por aproximação —
Consolas no lugar do terminal do Pip-Boy, Bahnschrift no lugar da Night
City, Segoe nos controles dos dez. E a letra é o que o olho reconhece
primeiro. Em ``pipboy/fontes/`` vão famílias livres (SIL Open Font License,
cada uma com a sua licença ao lado), escolhidas pelo que os próprios jogos
usam ou pelo que mais se parece com isso:

* Share Tech Mono e Roboto Condensed — as do Pip-Boy do Fallout 4;
* Rajdhani — a da interface do Cyberpunk 2077;
* Barlow Condensed — a família da qual a do Battlefield 6 deriva;
* Cinzel — a romana de inscrição mais próxima dos títulos do Elden Ring;
* Jost — parente livre da Futura, que é a letra dos menus do Skyrim;
* D-DIN — um DIN, que é a letra da interface do Witcher 3;
* Rye — o tipo de madeira dos cartazes de procurado do velho oeste;
* IM FELL English — os tipos de livro antigo, para o grimório.

O GTA fica sem: as letras dele (Pricedown e Chalet) não são livres.

As fontes entram no banco do Qt só para este programa — nada é instalado
no Windows de ninguém — e a escolha continua pela cadeia de candidatas de
cada tema: sem os arquivos (um build que os esqueça), cai na reserva de
fábrica, como sempre caiu.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from PySide6.QtGui import QFont, QFontDatabase, QFontMetricsF

from .. import design

LOGGER = logging.getLogger("pip_boy.fontes")

PASTA_DAS_FONTES = Path(__file__).resolve().parent.parent / "fontes"
# A referência do ajuste óptico é a letra dos controles do tema neutro — a
# primeira de design.FONTES_UI instalada: é contra ela que tudo foi medido.
# Até onde o ajuste óptico pode ir. Fora disso a medida é que está errada —
# uma família sem métrica, uma fonte de reserva quadrada.
AJUSTE_MINIMO, AJUSTE_MAXIMO = 0.9, 1.25

# Monoespaçadas, da preferida à reserva. O rodapé de consumo é uma coluna de
# números que muda a cada meio segundo: com fonte proporcional, os dígitos
# mudam de largura e o texto inteiro dança.
FONTES_MONO: tuple[str, ...] = ("Cascadia Mono", "Consolas", "Courier New", "Courier")

_REGISTRADAS: list[str] = []


def registrar_fontes() -> list[str]:
    """Põe as fontes do programa no banco do Qt. Idempotente; exige a aplicação.

    Devolve as famílias registradas. Um arquivo que o Qt recusa é anotado no
    registro e pulado: fonte é aparência, e aparência não derruba o programa.
    """
    if _REGISTRADAS:
        return list(_REGISTRADAS)
    for arquivo in sorted(PASTA_DAS_FONTES.rglob("*.ttf")):
        identificador = QFontDatabase.addApplicationFont(str(arquivo))
        if identificador < 0:
            LOGGER.warning("Fonte recusada pelo Qt: %s", arquivo.name)
            continue
        for familia in QFontDatabase.applicationFontFamilies(identificador):
            if familia not in _REGISTRADAS:
                _REGISTRADAS.append(familia)
    return list(_REGISTRADAS)


@lru_cache(maxsize=1)
def familias_instaladas() -> frozenset[str]:
    """As famílias que o Qt enxerga, já com as embutidas registradas.

    Perguntado uma vez só: a lista não muda com o programa aberto, e ela era
    montada de novo em cada lugar que escolhia uma fonte. Exige a aplicação
    Qt viva, como toda pergunta ao banco de fontes.
    """
    registrar_fontes()
    return frozenset(QFontDatabase.families())


def primeira_instalada(candidatas: Sequence[str]) -> str:
    """A primeira candidata que existe nesta máquina; a última é a reserva.

    A regra de TODA escolha de fonte do programa, num lugar só. Ela estava
    escrita em sete — a janela, a abertura, o cartão de boas-vindas, o
    ajuste óptico, o diagnóstico e as duas ferramentas de glifos —, e o
    diagnóstico nem registrava as fontes embutidas antes de perguntar:
    relatava "queria Cinzel, obteve Georgia" de uma fonte que o programa
    usava. A reserva não é detalhe: por isso a última candidata de cada tema
    é uma fonte de fábrica que nenhum outro tema usa (ver themes.py).
    """
    instaladas = familias_instaladas()
    return next((nome for nome in candidatas if nome in instaladas), candidatas[-1])


def fonte_do_papel(tema: Any, papel: str, *, ui: bool = True, escala: float = 1.0) -> QFont:
    """A fonte de um degrau da rampa tipográfica (``design.TIPO``) no tema.

    ``ui=True`` é a letra dos controles; ``ui=False``, a do jogo — e, no
    degrau "display", a de título dele. A letra de LER vem no corpo aparente
    da de referência (``ajuste_optico``); o título, no corpo que o desenho
    dele pede. Negrito só se a família o tem, e o título na composição do
    jogo (``compor_titulo``). ``escala`` é o tamanho do texto escolhido.
    """
    tipo = design.TIPO[papel]
    if ui:
        candidatas = tema.ui_font_candidates
    elif papel == "display":
        candidatas = tema.display_candidates
    else:
        candidatas = tema.font_candidates
    familia = primeira_instalada(candidatas)
    ajuste = 1.0 if papel == "display" else ajuste_optico(familia)
    fonte = QFont(familia, design.escalar(tipo.tamanho, escala * ajuste))
    fonte.setBold(tipo.peso == "bold" and tem_negrito(familia))
    fonte.setItalic(tipo.estilo == "italic")
    if papel == "display" and not ui:
        compor_titulo(fonte, tema)
    return fonte


@lru_cache(maxsize=64)
def tem_negrito(familia: str) -> bool:
    """Se a família traz um peso negrito de verdade.

    Sem ele, o Qt engrossa a letra na marra — e um tipo de madeira como a
    Rye, engrossado, vira um borrão. Quem pede negrito a uma família que não
    o tem leva a letra regular, que é como ela foi desenhada.
    """
    estilos = QFontDatabase.styles(familia)
    # Família desconhecida (uma reserva que nem está instalada): quem decide
    # é o Qt, como sempre decidiu.
    return not estilos or any("bold" in estilo.lower() for estilo in estilos)


def compor_titulo(fonte: QFont, tema: Any) -> None:
    """Peso e caixa dos títulos do jogo (ver GameTheme.titulos_leves).

    A caixa alta é da LETRA (``setCapitalization``), e não do texto: o rótulo
    continua dizendo "O norte está à escuta", e é isso que o leitor de tela
    lê e que a busca encontra.
    """
    if getattr(tema, "titulos_leves", False):
        fonte.setBold(False)
        fonte.setWeight(QFont.Weight.Light)
    if getattr(tema, "titulos_em_caixa_alta", False):
        fonte.setCapitalization(QFont.Capitalization.AllUppercase)


@lru_cache(maxsize=64)
def ajuste_optico(familia: str) -> float:
    """O fator que iguala a altura-x da família à da letra de referência.

    É o ``font-size-adjust`` do CSS: letras de famílias diferentes no mesmo
    corpo têm tamanhos aparentes muito diferentes. A Rajdhani tem a altura-x
    baixa, e a 9 pt ficava menor que a Segoe a 8; a legenda do Cyberpunk
    sumia. Medido, e não tabelado: vale para qualquer família da cadeia.
    """
    referencia_nome = primeira_instalada(design.FONTES_UI)
    if familia == referencia_nome:
        return 1.0
    def razao(nome: str) -> float:
        # A altura-x sobre o CORPO (o em), e não sobre a altura da linha: é
        # a definição do font-size-adjust. Sobre a linha, a entrelinha larga
        # da Segoe fazia toda outra família parecer grande demais. E medida
        # na caixa da letra "x" desenhada, e não na métrica declarada, que em
        # algumas fontes de título vem errada.
        fonte = QFont(nome)
        fonte.setPixelSize(100)
        return QFontMetricsF(fonte).tightBoundingRect("x").height() / 100.0

    referencia, propria = razao(referencia_nome), razao(familia)
    if referencia <= 0.0 or propria <= 0.0:
        return 1.0
    return max(AJUSTE_MINIMO, min(AJUSTE_MAXIMO, referencia / propria))
