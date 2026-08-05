"""Ferramentas expostas ao modelo (function calling).

A Live API não executa ferramentas automaticamente: ela emite ``tool_call`` e
espera um ``FunctionResponse`` de volta. O despacho fica aqui, isolado da
sessão, para que adicionar uma ferramenta nova seja escrever uma função e uma
declaração — sem tocar no laço de rede.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, cast

from google.genai import types

from .vocabulary import VocabularyStore

LOGGER = logging.getLogger("pip_boy.tools")


def build_tools(*, web_search: bool = False) -> types.ToolListUnion:
    """Declarações enviadas na configuração da sessão.

    Estas descrições são reenviadas por INTEIRO a cada conexão, e a conexão
    recicla a cada dez minutos: cada palavra aqui é paga seis vezes por hora.
    Elas foram reescritas para dizer o mesmo com menos — o que sobrou é o que
    muda o comportamento do modelo (o SEMPRE, o SILÊNCIO, o "não anuncie"),
    não a prosa que explicava o óbvio.
    """
    declaracoes = [
        types.FunctionDeclaration(
            name="registrar_vocabulario",
            description=(
                "Salva no caderno, em silêncio, uma palavra ou expressão em inglês "
                "que você acabou de ensinar. Chame SEMPRE que ensinar algo novo e "
                "nunca anuncie a chamada."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "termo": types.Schema(
                        type=types.Type.STRING,
                        description="Em inglês, na forma base.",
                    ),
                    "traducao": types.Schema(
                        type=types.Type.STRING,
                        description="Tradução curta em português.",
                    ),
                    "exemplo": types.Schema(
                        type=types.Type.STRING,
                        description="Frase curta de exemplo, de preferência do jogo.",
                    ),
                },
                required=["termo", "traducao"],
            ),
        ),
        types.FunctionDeclaration(
            name="consultar_vocabulario",
            description=(
                "Traz palavras do caderno. Com revisao=true, só as VENCIDAS pela "
                "repetição espaçada, da mais atrasada para a menos — é assim que um "
                "quiz começa."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "quantidade": types.Schema(
                        type=types.Type.INTEGER,
                        description="1 a 20. Padrão 10.",
                    ),
                    "aleatorio": types.Schema(
                        type=types.Type.BOOLEAN,
                        description="Sorteia em vez de trazer as mais recentes.",
                    ),
                    "revisao": types.Schema(
                        type=types.Type.BOOLEAN,
                        description="Só as vencidas para revisão.",
                    ),
                },
            ),
        ),
        types.FunctionDeclaration(
            name="avaliar_vocabulario",
            description=(
                "Registra em SILÊNCIO se o jogador acertou ou errou uma palavra no "
                "quiz. É esta chamada que agenda a próxima revisão: acerto afasta, "
                "erro traz de volta. Chame após CADA resposta avaliável, sem anunciar."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "termo": types.Schema(
                        type=types.Type.STRING,
                        description="A palavra avaliada, como está no caderno.",
                    ),
                    "acertou": types.Schema(
                        type=types.Type.BOOLEAN,
                        description="Verdadeiro se o jogador soube a palavra.",
                    ),
                },
                required=["termo", "acertou"],
            ),
        ),
    ]

    ferramentas: types.ToolListUnion = [types.Tool(function_declarations=declaracoes)]
    if web_search:
        # Grounding com busca. Opcional: aumenta latência e custo, mas evita
        # invenção em perguntas sobre lore, patches ou builds específicas.
        ferramentas.append(types.Tool(google_search=types.GoogleSearch()))
    return ferramentas


class ToolDispatcher:
    """Executa chamadas de ferramenta e formata a resposta para o modelo."""

    def __init__(
        self,
        store: VocabularyStore,
        *,
        jogo: str,
        on_vocab: Callable[[str, str, bool], None] | None = None,
        on_review: Callable[[str, bool, int], None] | None = None,
    ) -> None:
        self._store = store
        self._jogo = jogo
        self._on_vocab = on_vocab
        self._on_review = on_review

    def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            LOGGER.warning("Ferramenta desconhecida solicitada: %s", name)
            return {"erro": f"ferramenta desconhecida: {name}"}
        try:
            return handler(args or {})
        except Exception as error:
            LOGGER.exception("Falha ao executar a ferramenta %s", name)
            # Devolver o erro em vez de estourar mantém a conversa viva: o
            # modelo consegue se recuperar e avisar o jogador.
            return {"erro": str(error) or type(error).__name__}

    def _tool_registrar_vocabulario(self, args: dict[str, Any]) -> dict[str, Any]:
        termo = str(args.get("termo", "")).strip()
        traducao = str(args.get("traducao", "")).strip()
        if not termo or not traducao:
            return {"erro": "termo e traducao são obrigatórios"}

        entrada, nova = self._store.registrar(
            termo=termo,
            traducao=traducao,
            exemplo=str(args.get("exemplo", "")).strip(),
            jogo=self._jogo,
        )
        if self._on_vocab is not None:
            self._on_vocab(entrada.termo, entrada.traducao, nova)
        return {
            "status": "salvo",
            "novo": nova,
            "encontros": entrada.encontros,
            "total_no_caderno": self._store.total(),
        }

    # Teto de palavras por consulta. Cinquenta custavam ~2.300 tokens numa
    # única resposta de ferramenta — mais que a instrução de sistema inteira —
    # e nenhum quiz falado usa cinquenta palavras de uma vez. Vinte já é mais
    # do que cabe numa conversa antes do jogador perder o fio.
    MAX_PALAVRAS = 20
    # O exemplo é o campo mais gordo e o menos necessário: serve de lembrete de
    # contexto, não de citação literal.
    MAX_EXEMPLO = 90

    def _tool_consultar_vocabulario(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            quantidade = int(args.get("quantidade", 10))
        except (TypeError, ValueError):
            quantidade = 10
        quantidade = max(1, min(quantidade, self.MAX_PALAVRAS))

        if bool(args.get("revisao", False)):
            entradas = self._store.para_revisar(limite=quantidade)
        else:
            entradas = self._store.consultar(
                limite=quantidade, aleatorio=bool(args.get("aleatorio", False))
            )

        palavras: list[dict[str, Any]] = []
        for e in entradas:
            # Campo vazio ou zerado não é informação — é peso. "erros": 0 em
            # cinquenta linhas custa tokens para dizer o que a ausência já diz.
            palavra: dict[str, Any] = {"termo": e.termo, "traducao": e.traducao}
            if e.exemplo:
                exemplo = e.exemplo.strip()
                if len(exemplo) > self.MAX_EXEMPLO:
                    exemplo = exemplo[: self.MAX_EXEMPLO - 1].rstrip() + "…"
                palavra["exemplo"] = exemplo
            if e.jogo:
                palavra["jogo"] = e.jogo
            if e.acertos:
                palavra["acertos"] = e.acertos
            if e.erros:
                palavra["erros"] = e.erros
            palavras.append(palavra)

        return {
            "total_no_caderno": self._store.total(),
            "vencidas_para_revisao": self._store.pendentes(),
            "palavras": palavras,
        }

    def _tool_avaliar_vocabulario(self, args: dict[str, Any]) -> dict[str, Any]:
        termo = str(args.get("termo", "")).strip()
        if not termo:
            return {"erro": "termo é obrigatório"}
        acertou = bool(args.get("acertou", False))
        resultado = self._store.avaliar(termo, acertou)
        if self._on_review is not None:
            self._on_review(
                str(resultado["termo"]), acertou, cast(int, resultado["proxima_revisao_em_dias"])
            )
        resultado["status"] = "avaliado"
        resultado["vencidas_restantes"] = self._store.pendentes()
        return resultado
