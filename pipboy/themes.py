"""Ambientes temáticos por jogo: paleta, fonte, vocabulário e persona.

Trocar o jogo no seletor troca a interface inteira. Este módulo é a única
fonte de verdade desse ambiente — a interface não conhece nenhuma cor literal,
apenas *papéis* de cor, e a thread de sessão publica papéis em vez de hex.

Adicionar um jogo é acrescentar um ``GameTheme`` em ``_TEMAS``: o seletor, a
repintura, o contexto do prompt e a persona temática passam a incluí-lo.

Mantido sem dependências pesadas (PySide6, genai, pyaudio) de propósito: os
testes e o restante do núcleo importam daqui livremente.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from . import design

# --- Papéis de cor -------------------------------------------------------
# Cada papel é o nome de um campo (ou propriedade) de GameTheme. A interface e
# a sessão falam em papéis; só o tema conhece o valor hexadecimal.
#
# Papéis-base: declarados por tema.
ROLE_SHELL: Final = "shell"
ROLE_SCREEN: Final = "screen"
ROLE_PRIMARY: Final = "primary"
ROLE_SECONDARY: Final = "secondary"
ROLE_FAINT: Final = "faint"
ROLE_ACCENT: Final = "accent"
ROLE_ALERT: Final = "alert"
ROLE_INFO: Final = "info"

# Papéis derivados: calculados a partir dos oito acima (ver design.py).
ROLE_SURFACE: Final = "surface"
ROLE_SURFACE_ALTA: Final = "surface_alta"
ROLE_BORDER: Final = "border"
ROLE_BORDER_FORTE: Final = "border_forte"
ROLE_HOVER: Final = "hover"
ROLE_PRESSED: Final = "pressed"
ROLE_SELECTION: Final = "selection"
ROLE_TEXT_MUTED: Final = "text_muted"
ROLE_TEXT_DISABLED: Final = "text_disabled"
ROLE_ACCENT_TEXT: Final = "accent_text"
ROLE_ALERT_TEXT: Final = "alert_text"
ROLE_INFO_TEXT: Final = "info_text"
ROLE_ALERT_BG: Final = "alert_bg"
ROLE_ON_PRIMARY: Final = "on_primary"
ROLE_ON_ACCENT: Final = "on_accent"
ROLE_ON_ALERT: Final = "on_alert"

# Os papéis que compõem uma paleta entregue aos componentes pintados.
#
# A lista vivia copiada à mão em dois provedores — a janela principal e o
# provedor mínimo do cartão de boas-vindas. Um papel novo precisava ser lembrado
# nos dois, e esquecer um só aparecia como KeyError dentro de um paintEvent, na
# primeira vez que alguém pintasse um botão daquela variante. Aqui a lista é uma
# só, e `paleta_de` é o único jeito de montá-la.
PAPEIS_DA_PALETA: Final[tuple[str, ...]] = (
    ROLE_SHELL, ROLE_SCREEN, ROLE_PRIMARY, ROLE_SECONDARY, ROLE_FAINT,
    ROLE_ACCENT, ROLE_ALERT, ROLE_INFO, ROLE_SURFACE, ROLE_SURFACE_ALTA,
    ROLE_BORDER, ROLE_BORDER_FORTE, ROLE_HOVER, ROLE_PRESSED, ROLE_SELECTION,
    ROLE_TEXT_MUTED, ROLE_TEXT_DISABLED, ROLE_ACCENT_TEXT, ROLE_ALERT_TEXT,
    ROLE_INFO_TEXT, ROLE_ON_PRIMARY, ROLE_ON_ACCENT, ROLE_ON_ALERT,
)

# Um papel de PREENCHIMENTO (o ponto da cápsula, uma barra do medidor) pode ser
# vibrante à vontade; o mesmo papel usado como TEXTO precisa da variante
# legível — daí os pares accent/accent_text, alert/alert_text e assim por
# diante. A escolha entre um e outro é de quem desenha o componente.


@dataclass(frozen=True, slots=True)
class GameTheme:
    """Tudo o que muda quando o jogador troca de jogo.

    ``context`` é o texto enviado ao modelo (o que o jogo exige em termos de
    inglês); os demais campos definem como a janela se apresenta.
    """

    name: str
    context: str
    assistant_name: str
    window_title: str
    header_title: str
    header_subtitle: str
    idle_text: str
    start_label: str
    stop_label: str
    persona_label: str
    persona_prompt: str
    # Primeira família instalada no sistema é a usada; a última é a reserva.
    #
    # A cadeia precisa ser distinta das dos OUTROS temas, e não só bonita:
    # Garamond, Rockwell e Bookman Old Style não acompanham o Windows, então
    # Elden Ring e Red Dead desabavam em Georgia — a mesma de Witcher e RPG —
    # e três temas caíam juntos em Bahnschrift. Dez ambientes rendiam seis
    # tipografias, e a identidade que a fonte deveria carregar evaporava numa
    # instalação limpa. A 1ª escolha continua sendo a ideal; a última é uma
    # família de fábrica ESCOLHIDA PARA NÃO COLIDIR.
    #
    # Entre as duas entram EB Garamond e Zilla Slab, que são livres (OFL) e
    # portanto instaláveis por quem quiser a tipografia pretendida de fato. Elas
    # existem justamente porque a reserva de fábrica não resolve o caso do Red
    # Dead: o Windows não traz UMA slab serif sequer, e slab é a alma do visual
    # western — Cambria é um acordo, não um substituto. Ninguém precisa
    # instalá-las: sem elas a cadeia segue para a reserva de sempre, e é por
    # isso que elas entram no meio e não no fim.
    font_candidates: tuple[str, ...]
    shell: str
    screen: str
    primary: str
    secondary: str
    faint: str
    accent: str
    alert: str
    info: str

    # --- Cores derivadas -------------------------------------------------
    # Calculadas, nunca declaradas. Duas famílias:
    #
    #  * SUPERFÍCIES — misturas do fundo com a cor principal do tema. Tingir a
    #    elevação com o matiz do tema (em vez de cinza neutro) é o que faz o
    #    pergaminho parecer pergaminho e o CRT parecer CRT nas bordas e nos
    #    painéis, sem nenhuma cor nova por tema.
    #  * TEXTOS SEGUROS — a mesma cor, elevada até 4.5:1 contra o fundo.
    #
    # Os cálculos são memorizados em design.py, então ler estas propriedades
    # num laço de repintura custa uma consulta de dicionário.

    @property
    def ui_font_candidates(self) -> tuple[str, ...]:
        """Fonte dos controles — neutra e igual em todos os temas.

        A fonte do tema assina a marca e a fala do assistente. Rótulo, botão e
        campo usam esta: é assim que um produto com skins funciona, e é o que
        separa "aplicativo com tema" de "aplicativo feito na fonte do tema".
        """
        return design.FONTES_UI

    @property
    def surface(self) -> str:
        """Fundo de painel, um degrau acima da tela."""
        return design.elevar(self.screen, 0.055, self.primary)

    @property
    def surface_alta(self) -> str:
        """Fundo de elemento interativo em repouso (campo, chip, bolha)."""
        return design.elevar(self.screen, 0.10, self.primary)

    @property
    def border(self) -> str:
        """Traço de 1 px que separa painéis. Discreto por definição."""
        return design.elevar(self.screen, 0.15, self.primary)

    @property
    def border_forte(self) -> str:
        """Traço de contorno de elemento interativo e de foco."""
        return design.elevar(self.screen, 0.26, self.primary)

    @property
    def hover(self) -> str:
        return design.elevar(self.screen, 0.13, self.primary)

    @property
    def pressed(self) -> str:
        return design.elevar(self.screen, 0.19, self.primary)

    @property
    def selection(self) -> str:
        """Fundo de texto selecionado no console e no campo de entrada."""
        return design.misturar(self.screen, self.accent, 0.28)

    def texto(self, cor: str) -> str:
        """Variante legível de uma cor sobre os fundos gerais da janela.

        Uma cor de texto assenta ora sobre ``screen`` (rodapé, cabeçalho), ora
        sobre ``surface`` (console, cartões). Garantir o contraste só contra o
        primeiro deixava passar o segundo, que é o mais claro dos dois — e é
        justamente onde vive a maior parte do texto. As duas passagens
        convergem porque ``surface`` é derivada de ``screen``.

        Fundos locais mais claros (chip ligado, cápsula de estado, botão
        contornado) não são cobertos aqui: eles derivam a própria cor de texto
        no ponto de uso, contra o fundo que realmente têm.
        """
        return design.garantir_contraste(
            design.garantir_contraste(cor, self.screen), self.surface
        )

    @property
    def text_muted(self) -> str:
        return self.texto(self.secondary)

    @property
    def text_disabled(self) -> str:
        """Texto de um controle travado — apagado, mas ainda legível.

        Um campo desabilitado não é decoração: durante a sessão ele é a ÚNICA
        indicação de qual jogo, persona, nível, modo, voz e microfone estão
        valendo, justamente quando nada disso pode mais ser trocado. Antes,
        esses campos usavam ``faint`` — uma cor pensada para barra apagada de
        medidor, que dá de 1.02:1 a 1.34:1 contra a superfície do campo nos dez
        temas. Na prática, ligar a sessão apagava as suas próprias escolhas.

        O travamento é comunicado pela SUPERFÍCIE (mais fosca) e pelo cursor,
        não por sumir com o texto. O contraste é derivado contra
        ``surface_alta``, que é o fundo real de um campo.
        """
        return design.garantir_contraste(self.secondary, self.surface_alta)

    @property
    def accent_text(self) -> str:
        return self.texto(self.accent)

    @property
    def alert_text(self) -> str:
        return self.texto(self.alert)

    @property
    def info_text(self) -> str:
        return self.texto(self.info)

    @property
    def alert_bg(self) -> str:
        """Realce de fundo das linhas de erro no console."""
        return design.misturar(self.screen, self.alert, 0.13)

    @property
    def on_primary(self) -> str:
        return design.legivel_sobre(self.primary)

    @property
    def on_accent(self) -> str:
        return design.legivel_sobre(self.accent)

    @property
    def on_alert(self) -> str:
        return design.legivel_sobre(self.alert)


_TEMAS: Final[tuple[GameTheme, ...]] = (
    GameTheme(
        name="Fallout",
        context=(
            "O jogador está em um título da série Fallout (Bethesda). O inglês do jogo "
            "mistura gíria americana retrofuturista dos anos 50, jargão militar e termos "
            "de sobrevivência: caps, ghoul, raider, stimpak, wasteland, settlement."
        ),
        assistant_name="PIP-BOY",
        window_title="PIP-BOY 3000 MK IV",
        header_title="◈ PIP-BOY 3000 MK IV",
        header_subtitle="TERMLINK — TUTOR DE INGLÊS PARA JOGOS",
        idle_text="AGUARDANDO ENTRADA",
        start_label="▶  INICIAR",
        stop_label="■  ENCERRAR",
        persona_label="Pip-Boy Sarcástico",
        persona_prompt=(
            "Você é o sistema de rádio do Pip-Boy em Fallout, com personalidade "
            "sarcástica e apocalíptica de pós-guerra nuclear. Fala com humor ácido, "
            "faz piadas secas sobre radiação e sobre a incompetência da humanidade, "
            "mas por trás do deboche você ajuda de verdade e com precisão."
        ),
        font_candidates=("Consolas", "Courier New"),
        shell="#161a15",
        screen="#0a1208",
        primary="#4dff7a",
        secondary="#2c7a44",
        faint="#1c4a2c",
        accent="#ffb000",
        alert="#ff5c5c",
        info="#7ad4ff",
    ),
    GameTheme(
        name="Elden Ring",
        context=(
            "O jogador está em Elden Ring (FromSoftware). O inglês é arcaico e literário, "
            "com formas em desuso (thou, thee, hath, mine own), vocabulário de alta "
            "fantasia e frases deliberadamente enigmáticas."
        ),
        assistant_name="DEDO",
        window_title="Arquivo da Terra Intermédia",
        header_title="✦ TERRA INTERMÉDIA",
        header_subtitle="GRAÇA GUIADORA — TUTOR DE INGLÊS",
        idle_text="AGUARDANDO O MACULADO",
        start_label="▶  INVOCAR",
        stop_label="■  DISPENSAR",
        persona_label="Donzela dos Dedos",
        persona_prompt=(
            "Você é uma donzela dos dedos da Terra Intermédia: solene, cerimoniosa e "
            "levemente arcaica no vocabulário. Trata o jogador como 'Maculado' e fala "
            "com gravidade ritual, mas suas explicações são sempre claras e diretas — "
            "o mistério fica no tom, nunca no conteúdo."
        ),
        font_candidates=("Garamond", "EB Garamond", "Constantia", "Georgia", "Times New Roman"),
        shell="#0b0906",
        screen="#14100b",
        primary="#d9b96b",
        secondary="#8a7440",
        faint="#3d3320",
        accent="#e0a24a",
        alert="#a33b2a",
        info="#9fb8c8",
    ),
    GameTheme(
        name="Skyrim",
        context=(
            "O jogador está em The Elder Scrolls V: Skyrim (Bethesda). O inglês é formal "
            "e pseudo-medieval, com títulos e cargos (thane, jarl, housecarl), nomes "
            "nórdicos difíceis de ouvir e falas de guarda repetidas à exaustão."
        ),
        assistant_name="GUIA",
        window_title="Pergaminho do Dovahkiin",
        header_title="❖ PERGAMINHO DO DOVAHKIIN",
        header_subtitle="CRÔNICA DE SKYRIM — TUTOR DE INGLÊS",
        idle_text="AGUARDANDO O DOVAHKIIN",
        start_label="▶  DESPERTAR",
        stop_label="■  REPOUSAR",
        persona_label="Bardo de Taverna",
        persona_prompt=(
            "Você é um bardo de taverna nórdica: caloroso, teatral e cheio de causos "
            "sobre as terras geladas. Trata o jogador como um herói em ascensão e "
            "adora uma boa história, mas corta a lorota assim que ele precisa de uma "
            "resposta objetiva."
        ),
        font_candidates=("Palatino Linotype", "Book Antiqua", "Sylfaen", "Times New Roman"),
        shell="#080b0e",
        screen="#121820",
        primary="#cfe0ea",
        secondary="#7b93a3",
        faint="#2b3a46",
        accent="#d8c48a",
        alert="#b0483c",
        info="#8fd0b0",
    ),
    GameTheme(
        name="The Witcher 3",
        context=(
            "O jogador está em The Witcher 3. O inglês tem sotaque britânico variado, "
            "gíria rústica eslava traduzida e vocabulário de caça a monstros e política medieval."
        ),
        assistant_name="BRUXO",
        window_title="Diário do Bruxo",
        # Glifo do bloco Geometric Shapes, e não ⚔ (U+2694): o Windows resolve
        # ⚔ pela fonte de emoji e o desenha COLORIDO, ignorando a paleta.
        header_title="◎ DIÁRIO DO BRUXO",
        header_subtitle="MEDALHÃO DE LOBO — TUTOR DE INGLÊS",
        idle_text="AGUARDANDO CONTRATO",
        start_label="▶  RASTREAR",
        stop_label="■  ENCERRAR",
        persona_label="Bruxo Estoico",
        persona_prompt=(
            "Você é um bruxo da Escola do Lobo: estoico, pragmático e econômico nas "
            "palavras. Não se impressiona com nada, trata cada dúvida como um contrato "
            "a cumprir e responde com frieza profissional — sem rispidez e sem nunca "
            "deixar de entregar o que foi pedido."
        ),
        font_candidates=("Georgia", "Cambria", "Times New Roman"),
        # Chão QUENTE. Tudo neste tema já era quente — a prata creme do
        # texto, o vermelho-sangue do acento, e uma atmosfera que a própria
        # receita chama de "couro e vela", com fibras, brasas e halo morno.
        # Só o fundo era frio (azulado), o que punha a vela sobre uma pedra
        # de geleira e deixava o bestiário a 0.3 de distância perceptual do
        # visor tático, que é frio por direito. A luminância é a mesma: o
        # que mudou foi a temperatura, não o tom.
        shell="#0d0b09",
        screen="#1a1714",
        primary="#d8d3c7",
        secondary="#8a8578",
        faint="#3d3a35",
        accent="#c0392b",
        alert="#e05a3a",
        info="#7fa8c0",
    ),
    GameTheme(
        name="Red Dead",
        context=(
            "O jogador está em Red Dead Redemption (Rockstar). O inglês é o do velho "
            "oeste americano: sotaques sulistas e caipiras carregados, contrações e "
            "formas não padrão (ain't, reckon, y'all, howdy) e vocabulário de caça, "
            "cavalos, ferrovia e vida fora da lei."
        ),
        assistant_name="PARCEIRO",
        window_title="Diário do Fora da Lei",
        header_title="★ DIÁRIO DO FORA DA LEI",
        header_subtitle="COMPANHEIRO DE TRILHA — TUTOR DE INGLÊS",
        idle_text="AGUARDANDO O FORASTEIRO",
        start_label="▶  PARTIR",
        stop_label="■  DESMONTAR",
        persona_label="Fora da Lei Veterano",
        persona_prompt=(
            "Você é um fora da lei veterano do velho oeste: fala arrastada, direta e "
            "com humor seco de quem já viu de tudo. Chama o jogador de 'parceiro', não "
            "tem paciência para rodeio e explica as coisas como quem ensina alguém a "
            "montar: mostrando, não teorizando."
        ),
        font_candidates=("Rockwell", "Zilla Slab", "Bookman Old Style", "Cambria", "Times New Roman"),
        shell="#170f0b",
        screen="#241a13",
        primary="#ecd9b0",
        secondary="#a8875c",
        faint="#4a3627",
        accent="#d8a13a",
        alert="#c0392b",
        info="#9ec4a0",
    ),
    GameTheme(
        name="GTA",
        context=(
            "O jogador está em um GTA (Rockstar). O inglês é urbano e coloquial, pesado "
            "em gíria de rua americana, contrações, palavrão e sotaques de imigrante, "
            "com muita ironia e sátira de mídia americana."
        ),
        assistant_name="RÁDIO",
        window_title="Rádio da Cidade",
        header_title="◉ RÁDIO DA CIDADE",
        header_subtitle="TRANSMISSÃO PIRATA — TUTOR DE INGLÊS",
        idle_text="AGUARDANDO CHAMADA",
        start_label="▶  LIGAR",
        stop_label="■  DESLIGAR",
        persona_label="Locutor de Rádio Pirata",
        persona_prompt=(
            "Você é o locutor de uma rádio pirata da cidade: acelerado, debochado e "
            "cheio de energia de madrugada. Trata cada dúvida como um pedido de ouvinte "
            "no ar — responde rápido, com graça, e emenda na próxima sem enrolar."
        ),
        font_candidates=("Trebuchet MS", "Corbel", "Segoe UI", "Arial"),
        shell="#08090f",
        screen="#131425",
        primary="#f2f2f7",
        secondary="#8f8fa8",
        faint="#2c2d47",
        accent="#ff2d95",
        alert="#ff5c5c",
        info="#24d3ff",
    ),
    GameTheme(
        name="Cyberpunk 2077",
        context=(
            "O jogador está em Cyberpunk 2077 (CD Projekt Red). O inglês mistura gíria "
            "futurista inventada (choom, preem, nova, gonk), jargão técnico de invasão e "
            "implantes, e palavras soltas de espanhol e japonês no meio das frases."
        ),
        assistant_name="RELIC",
        window_title="NETRUNNER OS",
        header_title="▚ NETRUNNER OS",
        header_subtitle="RELIC v2.0 — TUTOR DE INGLÊS",
        idle_text="AGUARDANDO INPUT",
        start_label="▶  CONECTAR",
        stop_label="■  DESCONECTAR",
        persona_label="Netrunner Cínico",
        persona_prompt=(
            "Você é um netrunner de Night City: cínico, rápido no gatilho verbal e cheio "
            "de gíria de rua. Despreza corporação e conversa mole, mas entrega a "
            "informação certa na hora certa — para você, dado limpo é questão de honra."
        ),
        font_candidates=("Bahnschrift", "Consolas", "Segoe UI"),
        shell="#08080a",
        screen="#101014",
        primary="#fcee0a",
        secondary="#9a9410",
        faint="#2d2d12",
        accent="#00f0ff",
        alert="#ff003c",
        info="#ff4fd8",
    ),
    GameTheme(
        name="RPG / Aventura (geral)",
        context=(
            "O jogador está em um RPG ou jogo de aventura em inglês, com diálogos longos, "
            "descrições de itens e menus densos."
        ),
        assistant_name="MESTRE",
        window_title="Grimório de Viagem",
        header_title="✧ GRIMÓRIO DE VIAGEM",
        header_subtitle="MESTRE DE JOGO — TUTOR DE INGLÊS",
        idle_text="AGUARDANDO O AVENTUREIRO",
        start_label="▶  INICIAR",
        stop_label="■  ENCERRAR",
        persona_label="Mestre de Jogo",
        persona_prompt=(
            "Você é um mestre de RPG de mesa: narrador nato, atento ao jogador e hábil "
            "em transformar qualquer dúvida numa cena curta que fixa a palavra. Nunca "
            "rouba a cena — descreve o necessário e devolve o turno."
        ),
        font_candidates=("Sitka Text", "Sylfaen", "Georgia", "Times New Roman"),
        shell="#0a0812",
        screen="#16111f",
        primary="#d9cdf0",
        secondary="#8b7bab",
        faint="#33284a",
        accent="#c9a227",
        alert="#d05a5a",
        info="#7fd4c0",
    ),
    GameTheme(
        name="FPS / Multiplayer",
        context=(
            "O jogador está em um jogo competitivo online. O inglês é rápido, abreviado e "
            "cheio de gíria de comunidade: push, flank, camp, clutch, nerf, GG, AFK."
        ),
        assistant_name="COMANDO",
        window_title="Comms Tático",
        header_title="▲ COMMS TÁTICO",
        header_subtitle="CANAL DE ESQUADRÃO — TUTOR DE INGLÊS",
        idle_text="AGUARDANDO ORDENS",
        start_label="▶  ENGAJAR",
        stop_label="■  RECUAR",
        persona_label="Comandante de Esquadrão",
        persona_prompt=(
            "Você é um comandante de esquadrão no rádio: frases curtas, tom de comando e "
            "zero ruído. Entrega a informação como quem passa uma call no meio da "
            "partida — o jogador tem dois segundos de atenção e você respeita isso."
        ),
        font_candidates=("Tahoma", "Franklin Gothic Medium", "Segoe UI"),
        shell="#0a0b0c",
        screen="#15181a",
        primary="#e2e6e8",
        secondary="#8b9296",
        faint="#2c3235",
        accent="#ff7a1a",
        alert="#ff3b30",
        info="#4fc3f7",
    ),
    GameTheme(
        name="Genérico / Outro",
        context="O jogador pode estar jogando qualquer jogo em inglês.",
        assistant_name="TUTOR",
        window_title="Pip-Boy TermLink",
        header_title="◆ TUTOR DE INGLÊS",
        header_subtitle="MODO UNIVERSAL — QUALQUER JOGO",
        idle_text="AGUARDANDO ENTRADA",
        start_label="▶  INICIAR",
        stop_label="■  ENCERRAR",
        persona_label="Comentarista Entusiasmado",
        persona_prompt=(
            "Você é um comentarista de jogos entusiasmado e bem-humorado, que conhece "
            "muitos títulos e explica tudo com energia. Adora uma referência cruzada "
            "entre jogos, desde que ela caiba em uma frase."
        ),
        font_candidates=("Segoe UI", "Consolas", "Arial"),
        shell="#0d1116",
        screen="#171c22",
        primary="#e6edf3",
        secondary="#8b98a5",
        faint="#2d353d",
        accent="#58a6ff",
        alert="#f85149",
        info="#7ee787",
    ),
)

TEMAS: Final[dict[str, GameTheme]] = {tema.name: tema for tema in _TEMAS}
DEFAULT_TEMA: Final = _TEMAS[0].name


def theme_for(game_name: str) -> GameTheme:
    """Tema do jogo, com o padrão como rede de segurança.

    Preferências salvas por uma versão anterior podem citar um jogo que não
    existe mais; nesse caso a janela abre no tema padrão em vez de quebrar.
    """
    return TEMAS.get(game_name, TEMAS[DEFAULT_TEMA])


def paleta_de(tema: GameTheme) -> dict[str, str]:
    """Fotografia das cores de um tema, para os componentes pintados.

    Eles não importam este módulo: recebem o dicionário e ficam reaproveitáveis
    fora deste programa. Ver PAPEIS_DA_PALETA.
    """
    return {papel: getattr(tema, papel) for papel in PAPEIS_DA_PALETA}
