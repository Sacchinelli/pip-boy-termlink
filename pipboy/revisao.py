"""Rodada de revisão offline: repetição espaçada sem sessão e sem custo.

O modo Quiz por voz é ótimo, mas cobra o preço de uma sessão Live — tokens,
rede, microfone. Revisar o caderno é uma tarefa que não precisa de nada
disso: o banco sabe o que está vencido (``para_revisar``) e sabe registrar o
resultado (``avaliar``). Este módulo é o fio entre os dois — uma fila, um
cursor e dois contadores — separado da interface para ser testável a seco e
reutilizável (a mesma rodada serviria a uma versão de linha de comando).
"""

from __future__ import annotations

from .vocabulary import Entrada, VocabularyStore

# Uma rodada é o que cabe entre duas partidas. Quem tiver mais vencidas
# encerra a rodada e começa outra — melhor que um túnel de cinquenta cartões.
CARTOES_POR_RODADA = 20


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

    def responder(self, acertou: bool) -> int:
        """Registra a resposta do cartão atual e avança.

        Devolve em quantos dias a palavra volta (0 = errou, volta já).
        """
        cartao = self.atual
        if cartao is None:
            raise RuntimeError("a rodada já terminou")
        try:
            resultado = self._store.avaliar(cartao.termo, acertou)
        except ValueError:
            # A palavra saiu do caderno depois que a fila foi fotografada.
            # Avançar em silêncio é o certo: não há o que agendar, e uma
            # exceção aqui sobe por um slot do Qt e vira caixa de erro por
            # causa de um cartão que o próprio jogador mandou apagar.
            self._indice += 1
            return 0
        if acertou:
            self.acertos += 1
        else:
            self.erros += 1
        self._indice += 1
        dias = resultado["proxima_revisao_em_dias"]
        return int(dias) if isinstance(dias, (int, float)) else 0
