"""As dicas de tela de carregamento: uma por dia, no tom de cada jogo.

Todo jogo destes tem a sua: a linha no pé da tela de carregamento do Skyrim,
o conselho otimista da Vault-Tec no Fallout, a mensagem deixada no chão da
Terra Intermédia no formato que os jogadores usam ("tente...", "adiante...").
É a voz do jogo falando com quem espera — e é o lugar em que um programa
ensina o que ninguém descobre sozinho: que dá para tocar numa palavra da fala
para perguntar por ela, que o Ctrl+R revisa sem gastar a chave.

Metade ensina inglês, metade ensina o programa. Nenhuma promete o que ele não
faz: as que citam um atalho global usam um marcador — ``{iniciar}``,
``{mudo}``, ``{audio}`` — preenchido com a tecla configurada no ``.env``, e
somem quando os atalhos globais não existem nesta máquina ou foram
desligados. ``{assistente}`` vira o nome de quem responde no tema.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Final

# Os marcadores de atalho global que uma dica pode citar.
MARCADORES: Final = frozenset({"iniciar", "mudo", "audio"})
_MARCADOR = re.compile(r"\{(\w+)\}")
# O tamanho máximo de uma dica: ela é UMA linha de rodapé, e não um parágrafo.
TAMANHO_MAXIMO: Final = 150


@dataclass(frozen=True, slots=True)
class Dicas:
    """O rótulo com que o jogo apresenta a dica e as frases dele."""

    rotulo: str
    frases: tuple[str, ...]


DICAS: Final[dict[str, Dicas]] = {
    "Fallout": Dicas("DICA DA VAULT-TEC", (
        "Toque numa palavra da fala do {assistente} para perguntar o que ela significa. A Vault-Tec"
        " recomenda curiosidade moderada.",
        "{iniciar} liga e desliga a conversa sem sair do jogo. Nenhum morador precisou tirar a luva.",
        "Palavra vencida é palavra esquecida: Ctrl+R revisa o caderno sem gastar a chave. Sem"
        " radiação envolvida.",
        "Depois de uma palavra nova, peça 'use it in a sentence': ouvir o uso fixa mais do que a"
        " tradução.",
    )),
    "Elden Ring": Dicas("MENSAGEM DEIXADA", (
        "Tente perguntar, Maculado: 'what does this word mean?'. Palavras adiante.",
        "Arcaísmos adiante: 'thou', 'thee' e 'hath' são 'você', 'te' e 'tem'. Peça ao {assistente}"
        " que compare com o inglês de hoje.",
        "Visite o caderno (Ctrl+B): cada palavra aprendida fica lá, com o jogo em que nasceu.",
        "Tente revisar. Palavra não revisada se perde como runa não guardada — Ctrl+R.",
    )),
    "Skyrim": Dicas("DICA", (
        "Toque numa palavra da fala do {assistente} para perguntar por ela — até os dragões"
        " aprendem palavras novas.",
        "Ctrl+K abre todos os comandos da janela: é o grito que abre qualquer porta.",
        "As palavras vencidas esperam no caderno como livros não lidos: Ctrl+R revisa sem abrir"
        " sessão.",
        "Peça 'say it slower' quando uma fala passar rápido demais — o {assistente} repete com calma.",
    )),
    "The Witcher 3": Dicas("NOTA DO BESTIÁRIO", (
        "Todo contrato começa pelo nome do monstro: pergunte 'how do you spell it?' e anote a"
        " grafia.",
        "Frases do jogo têm gíria antiga. Peça ao {assistente} a versão moderna e a literal, lado"
        " a lado.",
        "O histórico (Ctrl+H) guarda cada conversa: dá para voltar à caçada em que a palavra"
        " apareceu.",
        "Antes de partir, Ctrl+R cobra as palavras vencidas — offline, sem gastar a chave.",
    )),
    "Red Dead": Dicas("DICA DO PARCEIRO", (
        "Sotaque do oeste engole letras: 'gonna', 'ain't', 'y'all'. Peça ao {assistente} a forma"
        " por extenso.",
        "Toque numa palavra da fala para perguntar por ela — sem precisar escrever de novo.",
        "O caderno (Ctrl+B) é o seu diário: cada palavra com o dia em que você a pegou na trilha.",
        "{iniciar} liga a conversa de dentro do jogo, sem largar as rédeas.",
    )),
    "GTA": Dicas("DICA DA RÁDIO", (
        "Gíria de rua muda rápido: pergunte 'is this slang still used?' antes de sair usando.",
        "{mudo} deixa o microfone mudo sem sair do jogo — para quando a perseguição apertar.",
        "Peça 'say it like a radio host' para treinar o ouvido no ritmo de verdade.",
        "Ctrl+M põe a janela no modo compacto: só o essencial na tela enquanto você dirige.",
    )),
    "Cyberpunk 2077": Dicas("// DICA", (
        "Jargão de netrunner vem em siglas: pergunte 'what does it stand for?' e descompacte.",
        "Ctrl+K abre a paleta de comandos: toda ação da janela a uma busca de distância.",
        "Toque numa palavra da fala do {assistente} para perguntar por ela, sem digitar.",
        "Ctrl+R revisa o caderno offline: nenhuma requisição sai da máquina.",
    )),
    "RPG / Aventura (geral)": Dicas("CONSELHO DO MESTRE", (
        "Depois de uma palavra nova, peça 'give me three synonyms': aventureiro não carrega uma"
        " arma só.",
        "Ctrl+B abre o grimório de palavras; Ctrl+R cobra as que venceram.",
        "Descrições de item têm o inglês mais rico do jogo: leia uma em voz alta e peça correção"
        " de pronúncia.",
        "Toque numa palavra da fala do {assistente} para perguntar por ela.",
    )),
    "FPS / Multiplayer": Dicas("DICA TÁTICA", (
        "Callouts são curtos: aprenda 'flank', 'push', 'hold' e 'fall back' antes da próxima"
        " partida.",
        "{iniciar} abre o canal sem sair do jogo; {mudo} corta o seu microfone.",
        "Peça ao {assistente} 'give me the callout for this' e repita em voz alta.",
        "Depois da partida, Ctrl+R revisa o que ficou no caderno.",
    )),
    "Genérico / Outro": Dicas("DICA", (
        "Toque numa palavra da fala do tutor para perguntar por ela.",
        "Ctrl+K abre todos os comandos da janela.",
        "Ctrl+R revisa as palavras vencidas, sem gastar a chave.",
        "Fale em português ou em inglês: o {assistente} acompanha os dois.",
    )),
}


def marcadores_de(frase: str) -> set[str]:
    return set(_MARCADOR.findall(frase))


def dicas_do_jogo(jogo: str, assistente: str, atalhos: Mapping[str, str]) -> list[str]:
    """As frases do jogo que valem nesta máquina, já com as teclas e o nome.

    ``atalhos`` vai de marcador a tecla ("iniciar" → "Ctrl+Alt+P"); vazio,
    as frases que citam atalho global ficam de fora.
    """
    dicas = DICAS.get(jogo, DICAS["Genérico / Outro"])
    valores = {"assistente": assistente, **atalhos}
    return [
        frase.format(**valores)
        for frase in dicas.frases
        if marcadores_de(frase) - {"assistente"} <= set(atalhos)
    ]


def dica_do_dia(
    jogo: str, assistente: str, atalhos: Mapping[str, str], dia: date
) -> tuple[str, str]:
    """(rótulo, frase) do dia: a mesma dica o dia inteiro, outra amanhã."""
    frases = dicas_do_jogo(jogo, assistente, atalhos)
    rotulo = DICAS.get(jogo, DICAS["Genérico / Outro"]).rotulo
    if not frases:
        return rotulo, ""
    return rotulo, frases[dia.toordinal() % len(frases)]
