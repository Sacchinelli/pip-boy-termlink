"""Rodada de revisão offline: repetição espaçada sem sessão e sem custo.

O modo Quiz por voz é ótimo, mas cobra o preço de uma sessão Live — tokens,
rede, microfone. Revisar o caderno é uma tarefa que não precisa de nada
disso: o banco sabe o que está vencido (``para_revisar``) e sabe registrar o
resultado (``avaliar``). Este módulo é o fio entre os dois — uma fila, um
cursor e três contadores — separado da interface para ser testável a seco e
reutilizável (a mesma rodada serviria a uma versão de linha de comando).

**Lembrar e escrever.** O cartão de sempre mostra o termo em inglês e pede a
tradução de cabeça: é reconhecer. Mas quem joga precisa é de DIZER a palavra
na hora — e trazer a palavra de volta (produzir) fixa mais que reconhecê-la
quando aparece, que é o que a pesquisa de prática de recuperação vem
mostrando desde os anos 2000. O modo de escrever inverte o cartão: a
tradução e a frase do jogo com um buraco no lugar da palavra, e o jogador
digita o termo. As funções abaixo conferem a resposta, abrem a lacuna na
frase e dão a pista — tudo sem Qt, para a regra ser testada a seco.

**Três notas, não duas.** Acertei, errei — e *difícil*: lembrou, mas custou.
É o "Hard" do Anki. Tratar o esforço como acerto pleno empurra a palavra
para longe cedo demais; tratá-lo como erro joga fora o que a pessoa sabia.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .vocabulary import Entrada, VocabularyStore

# Uma rodada é o que cabe entre duas partidas. Quem tiver mais vencidas
# encerra a rodada e começa outra — melhor que um túnel de cinquenta cartões.
CARTOES_POR_RODADA = 20

# Quantas tentativas o modo de escrever dá antes de mostrar a palavra. Três:
# a primeira é a lembrança de verdade, a segunda já vem com a pista, a
# terceira é o último chute. Mais que isso vira adivinhação por eliminação.
TENTATIVAS = 3

# O buraco na frase de exemplo. Largura fixa de propósito: um traço por letra
# entregaria o tamanho da palavra antes da hora — o tamanho é a PISTA, e ela
# só vem depois do primeiro erro.
LACUNA = "_____"

# O que se tira do começo de um termo para aceitar a resposta sem ele: o "to"
# do infinitivo e os artigos. Quem digita "scavenge" para "to scavenge" sabe
# a palavra; cobrar o "to" seria cobrar a convenção do caderno.
_PREFIXOS_OPCIONAIS = ("to ", "a ", "an ", "the ")

ACERTO = "acerto"
DIFICIL = "dificil"
ERRO = "erro"


def normalizar(texto: str) -> str:
    """A resposta como se compara: sem caixa, sem acento, sem pontuação solta.

    O apóstrofo tipográfico vira o reto (o teclado do celular troca um pelo
    outro), os espaços se juntam e a pontuação das pontas sai — "Ammo." e
    " ammo " são a mesma resposta.
    """
    texto = texto.replace("’", "'").replace("‘", "'")
    decomposto = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().split()).strip(" .,;:!?\"")


def nucleo(termo: str) -> str:
    """O termo sem o "to" do infinitivo e sem artigo — a palavra que se cobra."""
    forma = normalizar(termo)
    for prefixo in _PREFIXOS_OPCIONAIS:
        if forma.startswith(prefixo) and len(forma) > len(prefixo):
            return forma[len(prefixo):]
    return forma


def distancia(a: str, b: str) -> int:
    """Quantas edições separam ``a`` de ``b`` (Damerau-Levenshtein restrita).

    Trocar duas letras vizinhas conta UMA edição, e não duas: "recieve" por
    "receive" é o erro de digitação mais comum que existe, e precisa pesar
    como um só.
    """
    anterior2: list[int] = []
    anterior = list(range(len(b) + 1))
    for i, letra_a in enumerate(a, 1):
        atual = [i] + [0] * len(b)
        for j, letra_b in enumerate(b, 1):
            custo = 0 if letra_a == letra_b else 1
            atual[j] = min(anterior[j] + 1, atual[j - 1] + 1, anterior[j - 1] + custo)
            if i > 1 and j > 1 and letra_a == b[j - 2] and a[i - 2] == letra_b:
                atual[j] = min(atual[j], anterior2[j - 2] + 1)
        anterior2, anterior = anterior, atual
    return anterior[-1]


@dataclass(frozen=True, slots=True)
class Conferencia:
    """O que a resposta digitada tem da palavra.

    ``no_lugar`` compara letra a letra com a palavra, posição por posição —
    a "semelhança" do terminal de senhas do Fallout, o verde do Wordle —, e
    é o que a tela pinta. Espaços não contam como letra acertada.
    """

    resposta: str
    alvo: str
    certa: bool
    quase: bool
    no_lugar: tuple[bool, ...]

    @property
    def letras_no_lugar(self) -> int:
        return sum(
            1 for i, ok in enumerate(self.no_lugar)
            if ok and i < len(self.alvo) and self.alvo[i] != " "
        )

    @property
    def letras(self) -> int:
        return sum(1 for c in self.alvo if c != " ")


def conferir(resposta: str, termo: str) -> Conferencia:
    """Confere a resposta digitada contra o termo do caderno.

    Certa é a palavra inteira, com ou sem o "to"/artigo. *Quase* é um erro
    de digitação numa palavra de seis letras ou mais — uma edição, que na
    tela vira "confira a grafia" e na nota vira *difícil*: a pessoa lembrou
    a palavra, e a grafia é o que falta fixar. Em palavra curta, uma letra
    trocada já é outra palavra ("shot", "shoot", "short"), e não conta.
    """
    digitado = normalizar(resposta)
    completo = normalizar(termo)
    alvo = nucleo(termo)
    certa = bool(digitado) and digitado in (completo, alvo)
    quase = (
        not certa and len(alvo) >= 6 and bool(digitado)
        and min(distancia(digitado, alvo), distancia(digitado, completo)) == 1
    )
    # Quem digitou o "to" junto é comparado letra a letra sem ele, como o alvo.
    prefixo = completo[: len(completo) - len(alvo)]
    comparado = digitado[len(prefixo):] if prefixo and digitado.startswith(prefixo) else digitado
    no_lugar = tuple(
        i < len(alvo) and letra == alvo[i] for i, letra in enumerate(comparado)
    )
    return Conferencia(digitado, alvo, certa, quase, no_lugar)


def trechos(exemplo: str, termo: str) -> list[tuple[int, int]]:
    """Onde a palavra aparece na frase de exemplo: (início, fim) de cada vez.

    Acha também as formas flexionadas mais comuns — "scavenged" para
    "scavenge", "bounties" para "bounty" —, cortando o "e" ou o "y" do fim
    antes de procurar.
    """
    palavras = nucleo(termo).split()
    if not palavras or not exemplo:
        return []
    ultima = palavras[-1]
    raiz = ultima[:-1] if len(ultima) > 4 and ultima[-1] in "ey" else ultima
    padrao = r"(?<![\w'])" + r"\s+".join(map(re.escape, [*palavras[:-1], raiz])) + r"[\w']*"
    return [m.span() for m in re.finditer(padrao, exemplo, flags=re.IGNORECASE)]


def lacuna(exemplo: str, termo: str) -> str | None:
    """A frase de exemplo com um buraco onde a palavra estava.

    Sem a palavra na frase, devolve ``None``: mostrar a frase inteira
    entregaria a resposta, e quem chama esconde o exemplo.
    """
    achados = trechos(exemplo, termo)
    if not achados:
        return None
    partes, fim_anterior = [], 0
    for inicio, fim in achados:
        partes.append(exemplo[fim_anterior:inicio])
        partes.append(LACUNA)
        fim_anterior = fim
    partes.append(exemplo[fim_anterior:])
    return "".join(partes)


def pista(termo: str, reveladas: int = 1) -> str:
    """O desenho da palavra: as primeiras letras e um traço por letra que falta.

    "s _ _ _ _ _ _ _" para "to scavenge" — o tamanho e o começo, que é o que
    destrava a lembrança sem entregá-la. Espaços entre palavras ficam largos.
    """
    alvo = nucleo(termo)
    partes: list[str] = []
    contadas = 0
    for palavra in alvo.split(" "):
        letras = []
        for letra in palavra:
            letras.append(letra if contadas < reveladas else "_")
            contadas += 1
        partes.append(" ".join(letras))
    return "   ".join(partes)


def nota_da_escrita(conferencia: Conferencia, erradas_antes: int) -> str | None:
    """A nota de uma tentativa no modo de escrever; ``None`` = tente de novo.

    Certa de primeira é acerto. Certa depois de errar — com a pista já na
    tela —, ou quase certa, é difícil. Errada na última tentativa é erro.
    """
    if conferencia.certa:
        return ACERTO if erradas_antes == 0 else DIFICIL
    if conferencia.quase:
        return DIFICIL
    if erradas_antes + 1 >= TENTATIVAS:
        return ERRO
    return None


class RodadaDeRevisao:
    """Uma passada pelos cartões vencidos, na ordem da dívida mais antiga.

    A fila é fotografada na abertura: avaliar um cartão muda o que está
    vencido no banco, e uma fila viva faria a palavra errada — que volta a
    vencer na hora — reaparecer no fim da mesma rodada. Errou, ela volta na
    PRÓXIMA rodada, como no Anki.
    """

    def __init__(self, store: VocabularyStore, limite: int = CARTOES_POR_RODADA) -> None:
        self._store = store
        self._fila: list[Entrada] = store.para_revisar(limite)
        self._indice = 0
        self.acertos = 0
        self.dificeis = 0
        self.erros = 0

    @property
    def total(self) -> int:
        return len(self._fila)

    @property
    def posicao(self) -> int:
        """Número do cartão atual, de 1 até o total (0 se a fila nasceu vazia)."""
        return min(self._indice + 1, self.total)

    @property
    def atual(self) -> Entrada | None:
        if self._indice >= len(self._fila):
            return None
        return self._fila[self._indice]

    @property
    def terminada(self) -> bool:
        return self._indice >= len(self._fila)

    def responder(self, acertou: bool, *, hesitou: bool = False) -> int:
        """Registra a resposta do cartão atual e avança.

        ``hesitou`` é o *difícil*: acertou, mas custou (ver ``avaliar``).
        Devolve em quantos dias a palavra volta (0 = errou, volta já).
        """
        cartao = self.atual
        if cartao is None:
            raise RuntimeError("a rodada já terminou")
        try:
            resultado = self._store.avaliar(cartao.termo, acertou, hesitou=hesitou)
        except ValueError:
            # A palavra saiu do caderno depois que a fila foi fotografada.
            # Avançar em silêncio é o certo: não há o que agendar, e uma
            # exceção aqui sobe por um slot do Qt e vira caixa de erro por
            # causa de um cartão que o próprio jogador mandou apagar.
            self._indice += 1
            return 0
        if not acertou:
            self.erros += 1
        elif hesitou:
            self.dificeis += 1
        else:
            self.acertos += 1
        self._indice += 1
        dias = resultado["proxima_revisao_em_dias"]
        return int(dias) if isinstance(dias, (int, float)) else 0
