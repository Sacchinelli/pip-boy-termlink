"""A folha de estilo da janela principal, derivada do tema.

Segunda peça a sair da ``Janela``, pela mesma razão que a primeira: isto não
é comportamento de janela. É uma FUNÇÃO PURA do tema e da forma dos cantos —
mesmas entradas, mesmo texto de saída, sem tocar num widget, sem ler estado e
sem depender de nada que só exista depois da montagem. Enquanto morava dentro
da classe, ela era mais um método numa lista de setenta, e a única forma de
conferir o CSS de um tema era construir a janela inteira.

Aqui, ``py -c "from pipboy.interface.estilo import folha_da_janela; ..."``
imprime a folha de qualquer um dos dez ambientes.
"""

from __future__ import annotations

from ..themes import GameTheme
from .componentes import css_campo_selecao

# Raio dos cantos por forma do tema. Um painel de canto redondo no meio de uma
# interface chanfrada é a única peça que denuncia que o tema é uma camada de
# tinta, e não o material da janela.
RAIO_POR_FORMA: dict[str, int] = {"chanfrada": 3, "reta": 2}
RAIO_PADRAO = 8


def rgba(cor: str, alfa: float) -> str:
    """Converte '#rrggbb' na notação rgba() do Qt, com opacidade.

    A folha de estilo precisa disto para que as superfícies deixem o cenário
    aparecer por trás — sem opacidade não há atmosfera, só um fundo tapado.
    """
    valor = cor.lstrip("#")
    r, g, b = (int(valor[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alfa:.3f})"


def folha_da_janela(tema: GameTheme, forma: str) -> str:
    """Folha de estilo derivada do tema — o equivalente ao repintar."""
    t = tema
    raio = RAIO_POR_FORMA.get(forma, RAIO_PADRAO)
    return f"""
    QWidget {{ color: {t.primary}; }}
    #lateral, #rolagemLateral, #colunaLateral, #rodapeLateral, #trilhoLateral {{
        background: {rgba(t.surface, 0.90)};
    }}
    #glifoTrilho {{ color: {t.accent_text}; background: transparent; }}
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
    /* O resumo da sessão: o valor na cor do texto, e não na de um campo
       travado — ele é para ser LIDO. A dica, discreta como uma legenda. */
    #resumoSessao, #ajustesDeSessao, #blocoVolume {{ background: transparent; }}
    #valorResumo {{ color: {t.primary}; }}
    #dicaResumo  {{ color: {t.text_muted}; }}
    #regua    {{ background: {t.border}; }}
    #caderno  {{ color: {t.info_text}; }}

    {css_campo_selecao(t, raio, rgba)}

    /* Translúcido para a atmosfera atravessar a superfície da conversa —
       é o que dá profundidade sem competir com a leitura. */
    #conversa, #fundoConversa {{
        background: {rgba(t.surface, 0.62)}; border-radius: {raio + 4}px;
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
        background: {rgba(t.surface_alta, 0.92)}; color: {t.primary};
        border: 1px solid transparent; border-radius: {raio + 2}px;
        padding: 12px 14px; selection-background-color: {t.selection};
    }}
    QLineEdit#entrada:focus {{ border-color: {t.border_forte}; }}
    """
