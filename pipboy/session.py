"""Sessão Live executada fora da thread gráfica.

Correções centrais em relação à versão anterior:

* **Transcrição agora funciona.** O código antigo lia ``input_transcription`` e
  ``output_transcription`` das respostas, mas nunca pedia essas transcrições na
  configuração — então os campos vinham sempre vazios e o registro ficava mudo.
* **Transcrições são acumuladas.** Elas chegam em pedaços, não em frases
  prontas. Imprimir cada pedaço produzia um registro picotado; aqui os pedaços
  são juntados e liberados no fim do turno.
* **Interrupção é tratada.** Quando o jogador fala por cima, o servidor manda
  ``interrupted``; sem descartar o áudio já enfileirado, o assistente continua
  falando por segundos depois de ser cortado.
* **A conexão se recupera sozinha.** O WebSocket morre a cada ~10 minutos por
  projeto. Com ``session_resumption`` a conversa continua de onde parou, e a
  compressão de janela remove o teto de 15 minutos por sessão.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import queue
import re
import threading
import time
from collections.abc import Callable
from typing import Any

from google import genai
from google.genai import types

from .audio import INICIO_DE_FALA, AudioError, AudioSession, MarcaDeFala
from .config import AppConfiguration
from .constants import (
    HEALTHY_CONNECTION_SECONDS,
    INPUT_SAMPLE_RATE,
    MAX_RECONNECT_ATTEMPTS,
    RECONNECT_BASE_DELAY,
    RECONNECT_MAX_DELAY,
)
from .events import Tag, UiEvent, UiEventKind
from .profiles import SessionSettings, build_greeting, build_system_instruction
from .themes import ROLE_ACCENT, ROLE_PRIMARY, theme_for
from .tools import ToolDispatcher, build_tools
from .vocabulary import VocabularyStore

LOGGER = logging.getLogger("pip_boy.session")


class _RenovacaoPedida(Exception):
    """Sinal interno: o servidor pediu (go_away) e o turno atual terminou."""


class ContagemDeTokens:
    """Total de tokens somado ao longo de várias conexões.

    ``usage_metadata.total_token_count`` é cumulativo dentro de UMA conexão. A
    sessão aqui sobrevive a várias — é o recurso central do programa — e o
    rodapé lia o número cru: a cada reciclagem do WebSocket o contador caía de
    dezenas de milhares para algumas centenas, o oposto do que um totalizador
    de consumo deve fazer.

    O reinício é *detectado*, não presumido. Não há garantia documentada de
    que uma conexão retomada comece do zero — ela pode continuar de onde
    parou —, e presumir o reinício faria a soma contar tudo duas vezes. A
    regra: se a primeira leitura de uma conexão for menor que a última da
    anterior, a contagem reiniciou e a conexão anterior vira histórico; se for
    maior ou igual, o servidor seguiu contando e não há nada a arquivar.
    """

    def __init__(self) -> None:
        self._historico = 0
        self._conexao = 0
        self._primeira_leitura = True

    def nova_conexao(self) -> None:
        self._primeira_leitura = True

    def registrar(self, total: int) -> int:
        """Informa o total relatado pelo servidor. Devolve o acumulado real."""
        if total <= 0:
            return self.total
        if self._primeira_leitura:
            self._primeira_leitura = False
            if total < self._conexao:
                self._historico += self._conexao
                self._conexao = 0
        # Dentro da mesma conexão o número só cresce; o max() protege contra
        # mensagens fora de ordem fazerem o mostrador andar para trás.
        self._conexao = max(self._conexao, total)
        return self.total

    @property
    def total(self) -> int:
        return self._historico + self._conexao


def politica_de_reconexao(*, duracao: float, tentativa: int) -> tuple[int, float | None]:
    """Decide se ainda vale reconectar e quanto esperar. Sem estado, sem rede.

    Recebe quanto durou a conexão que acabou de morrer e quantas tentativas
    seguidas já falharam; devolve ``(tentativa_atualizada, espera)``, com
    ``espera`` igual a ``None`` quando não há mais tentativa a fazer.

    Vive fora do laço, e sozinha, porque a regra tinha um buraco que só uma
    função exercitável revela. O contador era zerado também quando a conexão
    tivesse recebido TRÁFEGO — e tráfego sobe em qualquer resposta, inclusive
    numa mensagem de erro seguida de fechamento imediato. Nesse caso a tentativa
    nunca passava de 1, o teto nunca era alcançado, a espera ficava presa em um
    segundo, e o programa reconectava para sempre, uma vez por segundo,
    queimando cota do modelo a cada volta.

    Quem separa "fim natural de um WebSocket de dez minutos" de "nasceu morta" é
    a DURAÇÃO, sozinha: a primeira passa folgada pelo limiar, a segunda não.
    """
    if duracao > HEALTHY_CONNECTION_SECONDS:
        tentativa = 0
    tentativa += 1
    if tentativa > MAX_RECONNECT_ATTEMPTS:
        return tentativa, None
    espera = min(RECONNECT_BASE_DELAY * (2 ** (tentativa - 1)), RECONNECT_MAX_DELAY)
    return tentativa, espera


class LiveSessionWorker:
    """Ciclo de vida completo de uma sessão, em thread própria.

    O worker jamais toca num widget. Ele só publica ``UiEvent`` numa fila.
    """

    def __init__(
        self,
        *,
        session_id: int,
        configuration: AppConfiguration,
        settings: SessionSettings,
        store: VocabularyStore,
        publish: Callable[[UiEvent], None],
        input_device: int | None = None,
        output_device: int | None = None,
        game_gain: float = 0.45,
    ) -> None:
        self.session_id = session_id
        self._configuration = configuration
        self._settings = settings
        self._store = store
        self._publish = publish
        self._input_device = input_device
        self._output_device = output_device
        self._game_gain = game_gain

        self._stop_requested = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._text_queue: asyncio.Queue[str] | None = None
        self._audio: AudioSession | None = None

        self._input_buffer = ""
        self._output_buffer = ""
        self._resumption_handle: str | None = None
        self._first_connection = True
        self._tokens = ContagemDeTokens()
        self._trafego_na_conexao = False
        self._renovacao_pedida = False
        self._conexoes = 0
        # Cópia mutável da preferência: ``SessionSettings`` é congelado, e a
        # busca precisa poder ser DESLIGADA no meio do caminho quando o serviço
        # recusa a sessão por causa dela. Ver ``_connection_loop``.
        self._web_search = settings.web_search
        # Há um turno de fala declarado ao serviço neste exato momento? Por
        # conexão, não por sessão: ver ``_one_connection``.
        self._fala_aberta = False

        self._thread = threading.Thread(
            target=self._thread_main, name=f"live-session-{session_id}", daemon=True
        )

    # ------------------------------------------------------------------ API

    @property
    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def start(self) -> None:
        self._thread.start()

    def request_stop(self) -> None:
        """Solicita encerramento, mesmo se o laço assíncrono ainda não iniciou."""
        self._stop_requested.set()
        loop, event = self._loop, self._stop_event
        if loop is not None and event is not None:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(event.set)

    def send_text(self, text: str) -> None:
        """Enfileira uma mensagem digitada. Chamado da thread da interface."""
        text = text.strip()
        loop, text_queue = self._loop, self._text_queue
        if not text or loop is None or text_queue is None:
            return
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(text_queue.put_nowait, text)

    def set_muted(self, muted: bool) -> None:
        capture = self._audio.capture if self._audio else None
        if capture is None:
            return
        capture.muted.set() if muted else capture.muted.clear()

    def set_game_audio(self, enabled: bool) -> bool:
        """Liga/desliga a captura do jogo. Retorna o estado efetivo."""
        capture = self._audio.capture if self._audio else None
        if capture is None or not capture.has_loopback:
            return False
        capture.game_audio_enabled.set() if enabled else capture.game_audio_enabled.clear()
        return enabled

    @property
    def input_level(self) -> float:
        capture = self._audio.capture if self._audio else None
        return capture.last_level if capture else 0.0

    # -------------------------------------------------------------- Eventos

    def _log(self, text: str, tag: Tag = Tag.ASSISTENTE, autor: str = "") -> None:
        self._publish(
            UiEvent(
                UiEventKind.LOG, text=text, tag=tag, author=autor, session_id=self.session_id
            )
        )

    def _status(self, text: str, color_role: str) -> None:
        self._publish(
            UiEvent(UiEventKind.STATUS, text=text, color_role=color_role, session_id=self.session_id)
        )

    def _on_review(self, termo: str, acertou: bool, dias: int) -> None:
        if acertou:
            prazo = f"revisão em {dias} dia{'s' if dias != 1 else ''}"
        else:
            prazo = "voltará no próximo quiz"
        self._log(f"{'✓' if acertou else '✗'} {termo} — {prazo}", Tag.VOCAB)
        self._publish(
            UiEvent(UiEventKind.VOCAB_ADDED, session_id=self.session_id, payload=self._store.total())
        )

    def _on_vocab(self, termo: str, traducao: str, nova: bool) -> None:
        prefixo = "＋" if nova else "↻"
        self._log(f"{prefixo} {termo} — {traducao}", Tag.VOCAB)
        self._publish(
            UiEvent(UiEventKind.VOCAB_ADDED, session_id=self.session_id, payload=self._store.total())
        )

    # ---------------------------------------------------------------- Thread

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except AudioError as error:
            self._log(f"ERRO DE ÁUDIO: {error}", Tag.ERRO)
            LOGGER.error("Falha de áudio na sessão %s: %s", self.session_id, error)
        except Exception as error:
            if self._stop_requested.is_set():
                LOGGER.info("Sessão %s interrompida durante o encerramento: %s", self.session_id, error)
            else:
                LOGGER.exception("Falha inesperada na sessão %s", self.session_id)
                self._log(
                    f"ERRO: {self._friendly_error(error, busca_web=self._web_search)}", Tag.ERRO
                )
        finally:
            self._loop = None
            self._stop_event = None
            self._text_queue = None
            self._publish(UiEvent(UiEventKind.SESSION_FINISHED, session_id=self.session_id))

    @staticmethod
    def _detalhes_erro(error: Exception) -> tuple[int | None, str, str]:
        """Extrai código, status e mensagem do erro.

        Os erros do google-genai carregam ``code``, ``status`` e ``message``
        estruturados. Ler esses campos é infinitamente mais confiável do que
        procurar substrings no texto — a versão anterior deste método declarava
        "cota esgotada" sempre que a sequência '429' aparecesse em qualquer
        lugar da mensagem, inclusive dentro de um identificador de requisição.
        """
        codigo = getattr(error, "code", None)
        if not isinstance(codigo, int):
            codigo = None
        status = str(getattr(error, "status", "") or "").upper()
        mensagem = str(getattr(error, "message", "") or "").strip() or str(error).strip()

        if codigo is None:
            # Sem campo estruturado, procura um número delimitado e valida a
            # FAIXA em vez de confiar no formato. A borda exclui hífen e ponto
            # para que 'gemini-429-flash' ou 'v2.404.1' não sejam confundidos,
            # e a validação por faixa descarta 'port 5000' ou 'max tokens 4096'.
            for achado in re.finditer(r"(?<![\w.\-])(\d{3,4})(?![\w.\-])", mensagem):
                valor = int(achado.group(1))
                if 400 <= valor < 600 or 1000 <= valor <= 1015:
                    codigo = valor
                    break
        return codigo, status, mensagem

    # Frases com que o serviço sinaliza esgotamento, independentemente do código.
    _FRASES_COTA = (
        "exceeded your current quota",
        "quota exceeded",
        "check your plan and billing",
        "resource has been exhausted",
        "resource_exhausted",
    )
    _FRASES_DIARIO = ("per day", "perday", "rpd", "daily limit", "per-day")

    @classmethod
    def _e_cota(cls, codigo: int | None, status: str, mensagem: str) -> bool:
        """O serviço recusou por esgotamento de cota?

        O CONTEÚDO tem prioridade sobre o número. A Live API entrega erros de
        cota fechando o WebSocket com o código 1011, que significa apenas
        "erro interno" e não é status HTTP — classificar pelo código faria
        este caso cair no genérico, exatamente como aconteceu antes.
        """
        baixo = mensagem.lower()
        return (
            any(f in baixo for f in cls._FRASES_COTA)
            or codigo == 429
            or status == "RESOURCE_EXHAUSTED"
        )

    @staticmethod
    def _dica(
        codigo: int | None, status: str, mensagem: str, *, busca_web: bool = False
    ) -> str:
        baixo = mensagem.lower()
        cls = LiveSessionWorker

        if cls._e_cota(codigo, status, mensagem):
            # A ferramenta de busca (Google Search grounding) tem cota PRÓPRIA,
            # contada à parte da cota do modelo, e a Live API a cobra no aperto
            # de mão: com ela esgotada, a sessão INTEIRA é recusada com esta
            # mesma frase genérica. Culpar o modelo aqui mandava o jogador
            # esperar a renovação de uma cota que nunca fora tocada — o erro
            # some na hora ao desmarcar um chip.
            if busca_web:
                return (
                    "A BUSCA NA WEB é a causa mais provável: essa ferramenta tem cota "
                    "própria, separada da cota do modelo, e a Live API recusa a sessão "
                    "inteira quando ela acaba. Desmarque 'Busca na web' e conecte de "
                    "novo — se funcionar, era isso, e a cota do modelo está intacta."
                )
            if any(f in baixo for f in cls._FRASES_DIARIO):
                return (
                    "Limite DIÁRIO de requisições atingido. Reinicia à meia-noite no "
                    "horário do Pacífico (por volta das 4h–5h no Brasil)."
                )
            return (
                "Cota do modelo esgotada. Atenção: modelos Live em preview têm cotas "
                "MUITO menores que os modelos comuns, e elas não aparecem na página de "
                "cota geral — veja os limites do seu projeto em https://ai.dev/rate-limit. "
                "Cada conexão consome cota. Espere a renovação ou troque GEMINI_MODEL."
            )

        # Códigos de fechamento de WebSocket (1000–4999) não são status HTTP.
        if codigo is not None and 1000 <= codigo <= 4999:
            if codigo == 1008:
                return "O serviço recusou a sessão por violação de política."
            if codigo in (1001, 1006):
                return "A conexão caiu de forma abrupta. Costuma ser instabilidade de rede."
            return (
                "O serviço encerrou a conexão. A causa real está na mensagem abaixo "
                "e no pipboy.log."
            )

        if codigo in (401, 403) or status in ("UNAUTHENTICATED", "PERMISSION_DENIED"):
            return (
                "Chave de API inválida ou sem permissão para este modelo. "
                "Confira GEMINI_API_KEY no .env."
            )
        if codigo == 404 or status == "NOT_FOUND":
            return (
                "Modelo não encontrado para a sua conta. Ajuste GEMINI_MODEL no .env "
                "para um modelo com suporte à Live API."
            )
        if codigo == 400 or status == "INVALID_ARGUMENT":
            return (
                "O serviço recusou a configuração da sessão. Costuma ser voz não "
                "suportada pelo modelo escolhido, ou modelo sem suporte a áudio. "
                "Tente outra voz (Puck) ou revise GEMINI_MODEL."
            )
        if codigo == 503 or status == "UNAVAILABLE":
            return "O serviço está temporariamente indisponível. Tente de novo em instantes."
        if codigo is not None and 500 <= codigo < 600:
            return "Falha no lado do serviço. Não é problema da sua configuração."
        if any(t in baixo for t in ("getaddrinfo", "connection refused", "ssl", "timed out")):
            return "Não foi possível alcançar o serviço. Verifique sua conexão de internet."
        return ""

    @classmethod
    def _friendly_error(cls, error: Exception, *, busca_web: bool = False) -> str:
        """Traduz o erro SEM descartar a mensagem original.

        A versão anterior substituía o texto da API por um palpite. Quando o
        palpite errava, a informação real desaparecia e o diagnóstico ficava
        impossível. Agora a dica vem acompanhada do que o serviço realmente
        respondeu.

        ``busca_web`` diz se a conexão que falhou pedia a ferramenta de busca —
        informação que o texto do erro não carrega e sem a qual a dica de cota
        acusa o culpado errado.
        """
        codigo, status, mensagem = cls._detalhes_erro(error)
        dica = cls._dica(codigo, status, mensagem, busca_web=busca_web)

        if not dica:
            base = mensagem or f"{type(error).__name__}"
            return f"{base} — detalhes completos em pipboy.log"

        if codigo is None:
            rotulo = ""
        elif 1000 <= codigo <= 1015:
            rotulo = f"WebSocket {codigo}"
        else:
            rotulo = f"HTTP {codigo}"
        rotulo = " ".join(p for p in (rotulo, status) if p and p != "None")
        origem = f"[{rotulo}] " if rotulo else ""
        resumo = mensagem if len(mensagem) <= 200 else mensagem[:200] + "…"
        return f"{dica}\n    {origem}resposta do serviço: {resumo}"

    # ----------------------------------------------------------------- Sessão

    async def _run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        self._text_queue = asyncio.Queue()
        if self._stop_requested.is_set():
            self._stop_event.set()
            return

        self._log("Inicializando microfone e saída de áudio…", Tag.SISTEMA)
        with AudioSession(
            input_device=self._input_device,
            output_device=self._output_device,
            game_audio=self._settings.game_audio,
            game_gain=self._game_gain,
            speaker_mode=self._settings.speaker_mode,
        ) as audio:
            self._audio = audio
            if self._settings.game_audio and not (audio.capture and audio.capture.has_loopback):
                self._log(
                    "Áudio do jogo indisponível: nenhum dispositivo de loopback WASAPI "
                    "encontrado. Seguindo apenas com o microfone.",
                    Tag.SISTEMA,
                )

            self._log(
                f"SESSÃO INICIADA — {self._settings.persona_name} | {self._settings.game_name} | "
                f"{self._settings.voice_label} | {self._settings.level_name} | {self._settings.mode_name}",
                Tag.SISTEMA,
            )
            try:
                await self._connection_loop(audio)
            finally:
                self._audio = None

    async def _connection_loop(self, audio: AudioSession) -> None:
        """Mantém a sessão viva através de múltiplas conexões WebSocket."""
        assert self._stop_event is not None
        client = genai.Client(api_key=self._configuration.api_key)
        tentativa = 0

        while not self._stop_event.is_set():
            self._status("CONECTANDO…" if self._first_connection else "RECONECTANDO…", ROLE_ACCENT)
            inicio = time.monotonic()
            self._trafego_na_conexao = False
            self._renovacao_pedida = False
            try:
                await self._one_connection(client, audio)
            except asyncio.CancelledError:
                raise
            except _RenovacaoPedida:
                # O servidor avisou (go_away) e nós saímos no limite do turno,
                # antes da queda — sem corte de fala. Reconectar imediatamente
                # com o handle de retomada não é falha e não gasta tentativa.
                if self._stop_event.is_set():
                    return
                tentativa = 0
                self._log("Renovando a conexão a pedido do serviço…", Tag.SISTEMA)
                continue
            except AudioError:
                # Microfone morto não é problema de rede: reconectar não
                # ajudaria e criaria um laço de renovação infinito e mudo.
                raise
            except Exception as error:
                if self._stop_event.is_set():
                    return
                LOGGER.warning("Conexão da sessão %s caiu: %s", self.session_id, error)

                # Cota + busca ligada: antes de desistir, tente sem a busca. A
                # ferramenta de grounding tem cota própria e é cobrada no aperto
                # de mão, então ela derruba a sessão inteira sozinha — inclusive
                # na PRIMEIRA conexão, onde o ramo abaixo encerraria tudo. Uma
                # sessão sem busca é imensamente melhor que nenhuma sessão, e
                # não há risco de laço: a flag só desce, nunca sobe.
                if self._web_search and self._e_cota(*self._detalhes_erro(error)):
                    self._web_search = False
                    self._publish(
                        UiEvent(UiEventKind.WEB_SEARCH_DISABLED, session_id=self.session_id)
                    )
                    self._log(
                        "A busca na web esgotou a cota PRÓPRIA dela e derrubou a conexão. "
                        "Reconectando sem busca — a cota do modelo está intacta.",
                        Tag.SISTEMA,
                    )
                    tentativa = 0
                    continue

                if self._first_connection:
                    # Falha já na primeira conexão costuma ser configuração
                    # errada, não instabilidade de rede. Não insista.
                    raise
                if self._trafego_na_conexao:
                    # A conexão funcionou e chegou ao fim natural (o servidor
                    # recicla o WebSocket a cada ~10 min). Isso é rotina, não
                    # falha: o handle de retomada preserva a conversa.
                    self._log("Renovando a conexão com o serviço…", Tag.SISTEMA)
                else:
                    self._log(
                        "Conexão perdida: "
                        f"{self._friendly_error(error, busca_web=self._web_search)}",
                        Tag.ERRO,
                    )

            if self._stop_event.is_set():
                return

            tentativa, espera = politica_de_reconexao(
                duracao=time.monotonic() - inicio, tentativa=tentativa
            )
            if espera is None:
                self._log("Não foi possível restabelecer a conexão. Encerrando.", Tag.ERRO)
                return

            self._status(f"RECONECTANDO EM {espera:.0f}s", ROLE_ACCENT)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=espera)

    def _build_config(self) -> types.LiveConnectConfig:
        instrucao = build_system_instruction(self._settings)
        return types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=types.Content(parts=[types.Part(text=instrucao)]),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self._settings.voice_id
                    )
                ),
                language_code="pt-BR",
            ),
            # Sem estes dois campos o registro da conversa fica permanentemente vazio.
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            # Remove o teto de 15 minutos descartando o contexto mais antigo.
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow(),
            ),
            # Permite retomar a conversa quando o servidor derruba o WebSocket.
            session_resumption=types.SessionResumptionConfig(handle=self._resumption_handle),
            tools=build_tools(web_search=self._web_search),
            # Quem decide onde a fala termina é o portão de voz daqui, não o
            # VAD do serviço. O portão já mede o microfone bloco a bloco para
            # decidir o que transmitir; o serviço, sem esse aviso, refazia a
            # detecção do zero sobre o áudio recebido e levava cerca de 700 ms
            # para concluir o que já era sabido — a cada pergunta. Medido: 717 ms
            # com detecção automática contra 136 ms avisando.
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(disabled=True),
            ),
        )

    async def _one_connection(self, client: Any, audio: AudioSession) -> None:
        assert self._stop_event is not None
        config = self._build_config()
        self._conexoes += 1
        self._tokens.nova_conexao()
        # Socket novo não herda turno aberto: o estado precisa nascer fechado,
        # senão a primeira fala após uma reconexão seria enviada sem início
        # declarado e o serviço a descartaria inteira, em silêncio.
        self._fala_aberta = False

        async with client.aio.live.connect(
            model=self._configuration.model, config=config
        ) as session:
            if self._stop_event.is_set():
                return

            if self._first_connection:
                await session.send_realtime_input(text=build_greeting(self._settings))
                self._first_connection = False
            else:
                # Cada conexão consome cota do modelo. Tornar isso visível ajuda
                # a flagrar consumo anormal antes de esgotar o limite.
                self._log(
                    f"Conexão nº {self._conexoes} estabelecida (contexto preservado).",
                    Tag.SISTEMA,
                )
            self._status("CONVERSANDO", ROLE_PRIMARY)

            dispatcher = ToolDispatcher(
                self._store,
                jogo=self._settings.game_name,
                on_vocab=self._on_vocab,
                on_review=self._on_review,
            )
            await self._pump(session, audio, dispatcher)

    async def _pump(self, session: Any, audio: AudioSession, dispatcher: ToolDispatcher) -> None:
        """Executa envio, recebimento e parada em paralelo, propagando falhas."""
        assert self._stop_event is not None

        tarefas = (
            asyncio.create_task(self._send_audio(session, audio), name="send-audio"),
            asyncio.create_task(self._send_text(session), name="send-text"),
            asyncio.create_task(self._receive(session, audio, dispatcher), name="receive"),
            asyncio.create_task(self._stop_event.wait(), name="wait-stop"),
        )
        parada = tarefas[-1]
        try:
            concluidas, _ = await asyncio.wait(tarefas, return_when=asyncio.FIRST_COMPLETED)
            if parada not in concluidas:
                # Chamar result() preserva a exceção original para o log e para
                # a lógica de reconexão.
                for tarefa in concluidas:
                    tarefa.result()
        finally:
            for tarefa in tarefas:
                if not tarefa.done():
                    tarefa.cancel()
            await asyncio.gather(*tarefas, return_exceptions=True)

    async def _send_audio(self, session: Any, audio: AudioSession) -> None:
        assert self._stop_event is not None
        capture = audio.capture
        if capture is None:
            return

        while not self._stop_event.is_set():
            try:
                bloco = await asyncio.to_thread(capture.frames.get, True, 0.2)
            except queue.Empty:
                continue
            if bloco is None:
                if self._stop_event.is_set():
                    return
                # A captura só envia None sem pedido de parada quando o
                # microfone morreu e não pôde ser reaberto.
                raise AudioError(
                    "O microfone parou de responder e não pôde ser reaberto. "
                    "Verifique se ele continua conectado e inicie uma nova sessão."
                )
            if self._stop_event.is_set():
                return

            # As bordas de fala viajam na mesma fila do áudio justamente para
            # chegarem na ordem certa em relação a ele. O ``fala_aberta`` não é
            # zelo excessivo: um início repetido, ou um fim sem início, quebra o
            # contrato de atividade manual, e é exatamente o que aconteceria se
            # a conexão caísse no meio de uma frase — o socket novo não herda o
            # turno que o antigo tinha aberto.
            if isinstance(bloco, MarcaDeFala):
                abrindo = bloco is INICIO_DE_FALA
                if abrindo != self._fala_aberta:
                    self._fala_aberta = abrindo
                    await session.send_realtime_input(
                        **(
                            {"activity_start": types.ActivityStart()}
                            if abrindo
                            else {"activity_end": types.ActivityEnd()}
                        )
                    )
                continue

            if not self._fala_aberta:
                # Áudio sem início declarado seria descartado em silêncio pelo
                # serviço. Acontece na primeira conexão de uma fala que já
                # estava em curso; abrir aqui custa nada e salva a pergunta.
                self._fala_aberta = True
                await session.send_realtime_input(activity_start=types.ActivityStart())
            await session.send_realtime_input(
                audio=types.Blob(data=bloco, mime_type=f"audio/pcm;rate={INPUT_SAMPLE_RATE}")
            )

    async def _send_text(self, session: Any) -> None:
        assert self._stop_event is not None and self._text_queue is not None
        while not self._stop_event.is_set():
            try:
                texto = await asyncio.wait_for(self._text_queue.get(), timeout=0.3)
            except asyncio.TimeoutError:
                continue
            self._log(texto, Tag.USUARIO, autor="VOCÊ")
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=texto)]),
                turn_complete=True,
            )

    # ------------------------------------------------------------ Recepção

    def _flush_input(self) -> None:
        texto = " ".join(self._input_buffer.split()).strip()
        self._input_buffer = ""
        if texto:
            self._log(texto, Tag.USUARIO, autor="VOCÊ")

    def _flush_output(self, sufixo: str = "") -> None:
        texto = " ".join(self._output_buffer.split()).strip()
        self._output_buffer = ""
        if texto:
            self._log(
                f"{texto}{sufixo}",
                Tag.ASSISTENTE,
                autor=theme_for(self._settings.game_name).assistant_name,
            )

    async def _receive(self, session: Any, audio: AudioSession, dispatcher: ToolDispatcher) -> None:
        """Consome o fluxo do servidor enquanto a conexão viver.

        ``session.receive()`` se esgota ao FIM DE CADA TURNO, não apenas quando
        o WebSocket cai — o autor da primeira versão deste projeto estava certo
        ao envolvê-lo num laço externo. Sem isso, cada resposta do modelo era
        interpretada como queda de conexão e disparava uma reconexão completa,
        consumindo o contador de tentativas até a sessão desistir.

        A distinção entre "turno acabou" e "socket morreu" é feita observando se
        a passagem produziu alguma resposta. Passagens vazias em sequência
        indicam conexão morta; a contagem e a pausa curta evitam o laço ocupado
        a 100% de CPU que motivou a remoção equivocada deste laço.
        """
        assert self._stop_event is not None
        vazios_consecutivos = 0

        while not self._stop_event.is_set():
            recebeu_algo = False
            async for response in session.receive():
                recebeu_algo = True
                self._trafego_na_conexao = True
                if self._stop_event.is_set():
                    return
                await self._processar_resposta(response, session, audio, dispatcher)

            # Fim de turno (ou de conexão): nada pode ficar preso no buffer.
            self._flush_input()
            self._flush_output()
            if self._stop_event.is_set():
                return
            if self._renovacao_pedida:
                # Limite de turno: nada está sendo falado. Momento perfeito
                # para trocar de conexão sem o jogador perceber.
                raise _RenovacaoPedida

            if recebeu_algo:
                vazios_consecutivos = 0
                continue

            vazios_consecutivos += 1
            if vazios_consecutivos >= 3:
                raise ConnectionError("A conexão de áudio foi encerrada pelo serviço.")
            await asyncio.sleep(0.1 * vazios_consecutivos)

    async def _processar_resposta(
        self, response: Any, session: Any, audio: AudioSession, dispatcher: ToolDispatcher
    ) -> None:
        playback = audio.playback

        # --- Sinalizações de ciclo de vida da sessão ---
        atualizacao = getattr(response, "session_resumption_update", None)
        if atualizacao is not None and getattr(atualizacao, "resumable", False):
            novo = getattr(atualizacao, "new_handle", None)
            if novo:
                self._resumption_handle = novo

        go_away = getattr(response, "go_away", None)
        if go_away is not None:
            restante = getattr(go_away, "time_left", None)
            LOGGER.info("Servidor sinalizou desconexão em %s", restante)
            # Em vez de esperar a queda (que pode cortar o assistente no meio
            # de uma palavra), saímos por conta própria no fim do turno atual
            # e reconectamos com o handle de retomada. Renovação sem lacuna.
            self._renovacao_pedida = True
            self._status("RENOVANDO CONEXÃO…", ROLE_ACCENT)

        uso = getattr(response, "usage_metadata", None)
        if uso is not None:
            total = getattr(uso, "total_token_count", None)
            if total:
                self._publish(
                    UiEvent(
                        UiEventKind.USAGE,
                        session_id=self.session_id,
                        payload=self._tokens.registrar(int(total)),
                    )
                )

        # --- Chamadas de ferramenta ---
        tool_call = getattr(response, "tool_call", None)
        if tool_call is not None:
            await self._handle_tool_call(session, tool_call, dispatcher)
            return

        content = getattr(response, "server_content", None)
        if content is None:
            return

        # --- Interrupção: o jogador falou por cima ---
        if getattr(content, "interrupted", False):
            if playback is not None:
                playback.flush()
            self._flush_output(" […interrompido]")
            return

        # --- Áudio do modelo ---
        model_turn = getattr(content, "model_turn", None)
        if model_turn is not None and playback is not None:
            for part in getattr(model_turn, "parts", ()) or ():
                inline = getattr(part, "inline_data", None)
                dados = getattr(inline, "data", None) if inline else None
                if dados:
                    playback.push(dados)

        # --- Transcrições (chegam em pedaços; são acumuladas) ---
        entrada = self._transcript_text(getattr(content, "input_transcription", None))
        if entrada:
            self._input_buffer += entrada

        saida = self._transcript_text(getattr(content, "output_transcription", None))
        if saida:
            # A fala do jogador termina quando o modelo começa a responder.
            if self._input_buffer:
                self._flush_input()
            self._output_buffer += saida

        if getattr(content, "turn_complete", False):
            self._flush_input()
            self._flush_output()

    async def _handle_tool_call(self, session: Any, tool_call: Any, dispatcher: ToolDispatcher) -> None:
        respostas: list[types.FunctionResponse] = []
        for chamada in getattr(tool_call, "function_calls", ()) or ():
            nome = getattr(chamada, "name", "") or ""
            args = dict(getattr(chamada, "args", None) or {})
            LOGGER.info("Ferramenta chamada: %s(%s)", nome, args)
            resultado = await asyncio.to_thread(dispatcher.dispatch, nome, args)
            respostas.append(
                types.FunctionResponse(
                    id=getattr(chamada, "id", None), name=nome, response=resultado
                )
            )
        if respostas:
            await session.send_tool_response(function_responses=respostas)

    @staticmethod
    def _transcript_text(transcription: Any) -> str:
        return str(getattr(transcription, "text", "") or "")
