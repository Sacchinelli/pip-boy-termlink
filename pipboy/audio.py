"""Motor de áudio: descoberta de dispositivos, captura e reprodução.

Três decisões de projeto merecem explicação:

1. **Reprodução desacoplada.** O código original escrevia o áudio do modelo
   direto no laço de recepção. Como os pedaços chegam muito mais rápido do que
   tocam, o laço ficava travado no alto-falante e não conseguia processar o
   sinal de interrupção a tempo. Aqui a reprodução vive numa thread própria,
   alimentada por fila, e o laço de recepção nunca bloqueia.

2. **Portão anti-eco.** Com alto-falantes, o microfone reouve o assistente e o
   modelo se interrompe sozinho num laço infinito. O portão silencia a captura
   enquanto há reprodução. Quem usa fone desliga o portão e ganha a capacidade
   de interromper o assistente falando por cima.

3. **Captura do jogo (loopback WASAPI).** É a razão de existir do
   PyAudioWPatch, que o projeto já declarava como dependência mas nunca usava.
   Com ela o assistente ouve o próprio jogo e o jogador pode perguntar "o que
   ele acabou de dizer?".
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import numpy as np

from . import dsp
from .constants import (
    CAPTURE_QUEUE_BLOCKS,
    CHANNELS,
    ECHO_GATE_TAIL_SECONDS,
    FRAMES_PER_BUFFER,
    INPUT_SAMPLE_RATE,
    OUTPUT_SAMPLE_RATE,
    VOICE_GATE_GAME_CONTEXT_BLOCKS,
    VOICE_GATE_HANGOVER_SECONDS,
    VOICE_GATE_PREROLL_BLOCKS,
    VOICE_GATE_THRESHOLD,
)

LOGGER = logging.getLogger("pip_boy.audio")

try:  # PyAudioWPatch adiciona loopback WASAPI; fora do Windows usamos PyAudio puro.
    import pyaudiowpatch as pyaudio

    HAS_LOOPBACK_SUPPORT = True
except ImportError:  # pragma: no cover - depende da plataforma
    import pyaudio

    HAS_LOOPBACK_SUPPORT = False


class AudioError(RuntimeError):
    """Falha de dispositivo apresentável ao usuário."""


@dataclass(frozen=True, slots=True)
class Device:
    index: int
    name: str
    channels: int
    sample_rate: int
    is_loopback: bool = False

    @property
    def label(self) -> str:
        marca = " [jogo]" if self.is_loopback else ""
        return f"{self.index}: {self.name}{marca}"


def _device_from_info(info: dict[str, Any], *, input_side: bool, loopback: bool = False) -> Device:
    canais = int(info["maxInputChannels"] if input_side else info["maxOutputChannels"])
    return Device(
        index=int(info["index"]),
        name=str(info["name"]).strip(),
        channels=max(1, canais),
        sample_rate=int(info.get("defaultSampleRate") or 48_000),
        is_loopback=loopback,
    )


def list_devices() -> tuple[list[Device], list[Device], Device | None]:
    """Lista dispositivos de entrada, de saída e o loopback padrão do sistema."""
    audio = pyaudio.PyAudio()
    entradas: list[Device] = []
    saidas: list[Device] = []
    loopback: Device | None = None
    try:
        for i in range(audio.get_device_count()):
            try:
                info = audio.get_device_info_by_index(i)
            except OSError:
                continue
            if int(info.get("maxInputChannels", 0)) > 0:
                entradas.append(_device_from_info(info, input_side=True))
            if int(info.get("maxOutputChannels", 0)) > 0:
                saidas.append(_device_from_info(info, input_side=False))

        if HAS_LOOPBACK_SUPPORT:
            with suppress(Exception):
                info = audio.get_default_wasapi_loopback()
                if info:
                    loopback = _device_from_info(info, input_side=True, loopback=True)
    finally:
        audio.terminate()
    return entradas, saidas, loopback


class Playback:
    """Fila de reprodução com descarte imediato para suportar interrupção."""

    def __init__(self, audio: Any, device_index: int | None) -> None:
        self._audio = audio
        self._stream = audio.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=OUTPUT_SAMPLE_RATE,
            output=True,
            output_device_index=device_index,
            frames_per_buffer=FRAMES_PER_BUFFER,
        )
        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=256)
        self._stop = threading.Event()
        self._last_write = 0.0
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name="audio-playback", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                chunk = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if chunk is None:
                break
            try:
                self._stream.write(chunk)
                with self._lock:
                    self._last_write = time.monotonic()
            except OSError:
                if self._stop.is_set():
                    return
                LOGGER.warning("Falha ao escrever no dispositivo de saída.", exc_info=True)

    def push(self, chunk: bytes) -> None:
        if self._stop.is_set():
            return
        try:
            self._queue.put_nowait(chunk)
        except queue.Full:
            # Melhor perder um pedaço antigo do que acumular atraso crescente.
            with suppress(queue.Empty):
                self._queue.get_nowait()
            with suppress(queue.Full):
                self._queue.put_nowait(chunk)

    def flush(self) -> None:
        """Descarta tudo o que está pendente — usado quando o jogador interrompe.

        Esvaziar a fila não basta: o próprio dispositivo tem um buffer interno.
        ``stop_stream`` o descarta; ``start_stream`` devolve o fluxo pronto.
        """
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        with suppress(OSError):
            self._stream.stop_stream()
            self._stream.start_stream()
        with self._lock:
            self._last_write = 0.0

    @property
    def is_speaking(self) -> bool:
        """True enquanto há áudio saindo, mais uma cauda curta.

        A cauda evita que o portão anti-eco abra no meio de uma pausa natural
        da fala e deixe o microfone captar o final da frase.
        """
        if not self._queue.empty():
            return True
        with self._lock:
            last = self._last_write
        return last > 0.0 and (time.monotonic() - last) < ECHO_GATE_TAIL_SECONDS

    def close(self) -> None:
        self._stop.set()
        with suppress(queue.Full):
            self._queue.put_nowait(None)
        with suppress(OSError):
            self._stream.stop_stream()
        self._thread.join(timeout=2.0)
        with suppress(OSError):
            self._stream.close()


class PortaoDeVoz:
    """Decide se um bloco de áudio merece ser transmitido.

    Áudio custa ~25 tokens por segundo em CADA direção, e o programa é feito
    para ficar aberto enquanto se joga. Sem este portão, uma hora de sessão
    numa sala silenciosa gastava cerca de 90 mil tokens de entrada sem ninguém
    perguntar nada — o nível já era medido a cada bloco, mas só alimentava o
    medidor da tela. O README chegava a instruir o jogador a apertar Ctrl+Alt+M
    "quando não estiver perguntando nada", que é pedir à pessoa que faça
    manualmente o que o software tinha informação de sobra para fazer sozinho.

    Duas precauções impedem que a economia coma a fala:

    * **Pré-rolo.** Quando o nível cruza o limiar, a primeira sílaba JÁ
      aconteceu. Os últimos blocos abaixo do limiar ficam guardados e são
      enviados na frente, senão "wasteland" chega como "asteland".
    * **Cauda.** O portão continua aberto depois de o nível cair, para que a
      pausa entre duas palavras não seja confundida com fim de fala.

    O nível avaliado é o do sinal FINAL, já com o áudio do jogo misturado: com
    'Ouvir o jogo' ligado, o jogo é entrada legítima e deve manter o portão
    aberto mesmo com o jogador calado.
    """

    def __init__(
        self,
        *,
        limiar: float = VOICE_GATE_THRESHOLD,
        pre_roll: int = VOICE_GATE_PREROLL_BLOCKS,
        cauda: float = VOICE_GATE_HANGOVER_SECONDS,
    ) -> None:
        self._limiar = limiar
        self._cauda = cauda
        self._buffer: deque[bytes] = deque(maxlen=max(0, pre_roll))
        self._aberto_ate = 0.0
        self.blocos_enviados = 0
        self.blocos_retidos = 0

    def avaliar(self, bloco: bytes, nivel: float, agora: float) -> list[bytes]:
        """Devolve os blocos a transmitir agora — nenhum, este, ou o pré-rolo."""
        # O bloco passa por MÉRITO PRÓPRIO quando está acima do limiar, e não
        # apenas por estar dentro da cauda. Decidir só pela cauda deixava o
        # portão fechado para sempre com ``cauda=0``: ``agora >= agora`` é
        # verdadeiro no exato instante em que a fala começa.
        ativo = nivel >= self._limiar
        if ativo:
            self._aberto_ate = agora + self._cauda

        if not ativo and agora >= self._aberto_ate:
            self._buffer.append(bloco)
            self.blocos_retidos += 1
            return []

        saida = list(self._buffer)
        self._buffer.clear()
        saida.append(bloco)
        self.blocos_enviados += len(saida)
        return saida

    def definir_pre_rolo(self, blocos: int) -> None:
        """Redimensiona a janela retida, preservando o que já está nela.

        Existe porque 'Ouvir o jogo' é uma chave que o jogador vira no meio da
        sessão: com ela ligada o pré-rolo deixa de ser um punhado de blocos
        contra a sílaba cortada e passa a ser a janela retroativa do jogo.
        """
        blocos = max(0, blocos)
        if self._buffer.maxlen == blocos:
            return
        self._buffer = deque(self._buffer, maxlen=blocos)

    def abrir(self, agora: float) -> None:
        """Força o portão aberto — usado quando o jogador digita uma pergunta."""
        self._aberto_ate = agora + self._cauda

    def esquecer(self) -> None:
        """Descarta o pré-rolo. Chamado quando o bloco não deve existir."""
        self._buffer.clear()

    @property
    def economia(self) -> float:
        """Fração dos blocos que não foi transmitida."""
        total = self.blocos_enviados + self.blocos_retidos
        return self.blocos_retidos / total if total else 0.0


def politica_de_portao(
    *, mudo: bool, falando: bool, portao_acustico: bool, jogo_ligado: bool
) -> tuple[bool, bool]:
    """Decide o que fazer com um bloco de captura. Sem estado, sem hardware.

    Devolve ``(enviar_microfone, descartar_loopback)``.

    A regra existe separada porque os dois ecos deste programa têm naturezas
    diferentes e foram confundidos uma vez:

    * **Eco acústico** — alto-falante, ar, microfone. Só acontece sem fone, e é
      por isso que o jogador liga o portão na interface.
    * **Eco digital** — o loopback WASAPI é uma derivação da SAÍDA do sistema, e
      a voz do assistente sai por ali junto com o jogo. Independe de fone, de
      volume e de qualquer escolha do usuário: se estamos falando, o loopback
      contém a nossa voz, ponto.

    Tratar o segundo com a chave do primeiro deixava o assistente se ouvindo em
    laço para quem usa fone — exatamente o público que a opção 'Ouvir o jogo'
    atende.
    """
    enviar = not (mudo or (portao_acustico and falando))
    descartar_loopback = jogo_ligado and (falando or mudo)
    return enviar, descartar_loopback


class Capture:
    """Captura do microfone, com mistura opcional do áudio do jogo.

    O microfone dita o relógio: para cada bloco lido dele, consumimos a
    quantidade correspondente do buffer de loopback, preenchendo com silêncio
    se o jogo estiver atrasado. Isso evita que as duas fontes derivem uma da
    outra ao longo de uma sessão longa.
    """

    def __init__(
        self,
        audio: Any,
        *,
        input_device: int | None,
        loopback_device: Device | None,
        game_gain: float,
    ) -> None:
        self._audio = audio
        self._game_gain = game_gain
        self._stop = threading.Event()
        self.frames: queue.Queue[bytes | None] = queue.Queue(maxsize=CAPTURE_QUEUE_BLOCKS)
        self.blocos_descartados = 0

        self.muted = threading.Event()
        self.game_audio_enabled = threading.Event()
        self.echo_gate_enabled = threading.Event()
        self._playback: Playback | None = None
        self.last_level = 0.0

        self._input_device_index = input_device
        self._stream, self._native_rate = self._open_input(input_device)
        self._loopback_stream = None
        self._loopback_device = loopback_device
        self._loopback_buffer: deque[np.ndarray] = deque(maxlen=32)
        self.portao_de_voz = PortaoDeVoz()

        if loopback_device is not None:
            self._loopback_stream = self._open_loopback(loopback_device)

        self._thread = threading.Thread(target=self._run, name="audio-capture", daemon=True)

    def _open_input(self, device_index: int | None) -> tuple[Any, int]:
        """Tenta abrir direto em 16 kHz; se o driver recusar, abre no nativo.

        WASAPI em modo compartilhado às vezes rejeita taxas não nativas. Em vez
        de falhar, capturamos no que o dispositivo oferece e reamostramos.
        """
        for rate in (INPUT_SAMPLE_RATE, 48_000, 44_100):
            try:
                stream = self._audio.open(
                    format=pyaudio.paInt16,
                    channels=CHANNELS,
                    rate=rate,
                    input=True,
                    input_device_index=device_index,
                    frames_per_buffer=FRAMES_PER_BUFFER,
                )
                if rate != INPUT_SAMPLE_RATE:
                    LOGGER.info("Microfone aberto em %s Hz; reamostrando para 16 kHz.", rate)
                return stream, rate
            except OSError as error:
                LOGGER.debug("Microfone recusou %s Hz: %s", rate, error)
        raise AudioError(
            "Não foi possível abrir o microfone. Verifique se ele está conectado, "
            "habilitado nas configurações de privacidade do Windows e não está em uso "
            "exclusivo por outro programa."
        )

    def _open_loopback(self, device: Device) -> Any | None:
        try:
            return self._audio.open(
                format=pyaudio.paInt16,
                channels=device.channels,
                rate=device.sample_rate,
                input=True,
                input_device_index=device.index,
                frames_per_buffer=FRAMES_PER_BUFFER,
            )
        except OSError:
            LOGGER.warning("Loopback indisponível; áudio do jogo desativado.", exc_info=True)
            return None

    def attach_playback(self, playback: Playback) -> None:
        self._playback = playback

    def start(self) -> None:
        self._thread.start()

    def _drain_loopback(self) -> None:
        """Lê sem bloquear o que o jogo produziu desde a última passagem."""
        stream = self._loopback_stream
        device = self._loopback_device
        if stream is None or device is None:
            return
        try:
            disponivel = stream.get_read_available()
            while disponivel >= FRAMES_PER_BUFFER:
                bruto = stream.read(FRAMES_PER_BUFFER, exception_on_overflow=False)
                amostras = dsp.pcm_to_array(bruto)
                mono = dsp.downmix_to_mono(amostras, device.channels)
                self._loopback_buffer.append(dsp.resample(mono, device.sample_rate, INPUT_SAMPLE_RATE))
                disponivel -= FRAMES_PER_BUFFER
        except OSError:
            if not self._stop.is_set():
                LOGGER.debug("Leitura de loopback falhou.", exc_info=True)

    def _enfileirar(self, bloco: bytes) -> None:
        """Entrega um bloco ao envio SEM NUNCA bloquear a thread de captura.

        Enquanto esta thread espera numa fila cheia, ela não está lendo o
        microfone — e o que transborda no driver some sem exceção, porque a
        leitura usa ``exception_on_overflow=False``. Ou seja: bloquear aqui
        para não perder um bloco perde vários, e perde os errados.

        Cheia (o que a fila dimensionada para a rajada torna raro), o descarte
        é do bloco MAIS ANTIGO. Numa fila que carrega pré-rolo seguido de fala,
        o mais antigo é contexto e o mais novo é a pergunta; sacrificar a
        pergunta para preservar o contexto seria exatamente o avesso.
        """
        try:
            self.frames.put_nowait(bloco)
            return
        except queue.Full:
            pass
        with suppress(queue.Empty):
            self.frames.get_nowait()
            self.blocos_descartados += 1
        with suppress(queue.Full):
            self.frames.put_nowait(bloco)

    def _take_loopback(self, num_samples: int) -> np.ndarray:
        """Retira exatamente ``num_samples`` amostras do buffer do jogo."""
        if not self._loopback_buffer:
            return np.zeros(0, dtype=np.int32)
        coletado: list[np.ndarray] = []
        total = 0
        while self._loopback_buffer and total < num_samples:
            bloco = self._loopback_buffer.popleft()
            coletado.append(bloco)
            total += bloco.size
        if not coletado:
            return np.zeros(0, dtype=np.int32)
        junto = np.concatenate(coletado)
        if junto.size > num_samples:
            # Devolve a sobra para o começo da fila, preservando a continuidade.
            self._loopback_buffer.appendleft(junto[num_samples:])
            junto = junto[:num_samples]
        return junto

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                bruto = self._stream.read(FRAMES_PER_BUFFER, exception_on_overflow=False)
            except OSError:
                if self._stop.is_set():
                    break
                LOGGER.warning(
                    "Leitura do microfone falhou; tentando reabrir o dispositivo.",
                    exc_info=True,
                )
                if self._reabrir_microfone():
                    continue
                LOGGER.error("Microfone não pôde ser reaberto; encerrando a captura.")
                break

            if self._stop.is_set():
                break

            self.last_level = dsp.rms_level(bruto)

            silenciado = self.muted.is_set()
            # A nossa própria voz saindo pela placa de som, neste instante.
            falando = self._playback is not None and self._playback.is_speaking
            jogo_ligado = self.game_audio_enabled.is_set()
            enviar, descartar_jogo = politica_de_portao(
                mudo=silenciado,
                falando=falando,
                portao_acustico=self.echo_gate_enabled.is_set(),
                jogo_ligado=jogo_ligado,
            )

            # A janela retida acompanha a chave, e não o fluxo: dimensioná-la
            # só no caminho de envio deixava o portão com a janela da sessão
            # anterior enquanto o jogador estivesse mudo ou o assistente
            # falando — justo quando a chave costuma ser virada.
            self.portao_de_voz.definir_pre_rolo(
                VOICE_GATE_GAME_CONTEXT_BLOCKS if jogo_ligado else VOICE_GATE_PREROLL_BLOCKS
            )

            if jogo_ligado:
                # Esvaziar o dispositivo em toda passagem, mesmo sem consumir,
                # para o loopback não acumular atraso.
                self._drain_loopback()
                if descartar_jogo:
                    # O loopback é uma derivação DIGITAL da saída do sistema, e
                    # a fala do assistente sai por ali junto com o jogo. Fone de
                    # ouvido não protege: não é um caminho pelo ar. Sem este
                    # descarte, com o portão acústico desligado — que é o certo
                    # para quem usa fone — o assistente ouvia a si mesmo, era
                    # transcrito como se fosse o jogador, se interrompia e
                    # recomeçava em laço.
                    #
                    # Limpar é essencial, e não bastava pular a mistura: os
                    # blocos drenados durante o portão ficavam ENFILEIRADOS e
                    # eram entregues ao modelo assim que ele reabria.
                    self._loopback_buffer.clear()

            if not enviar:
                # Não enviar nada é melhor que enviar silêncio: economiza tokens
                # (o áudio custa ~25 tokens por segundo) e a VAD do servidor
                # lida bem com lacunas.
                #
                # O pré-rolo também precisa ser esquecido: são blocos captados
                # enquanto estávamos mudos ou falando, e enviá-los na abertura
                # do portão entregaria justamente o que o portão bloqueou.
                self.portao_de_voz.esquecer()
                continue

            amostras = dsp.pcm_to_array(bruto).astype(np.int32)
            if self._native_rate != INPUT_SAMPLE_RATE:
                amostras = dsp.resample(amostras, self._native_rate, INPUT_SAMPLE_RATE)

            # O nível que abre o portão é o do MICROFONE, medido antes da
            # mistura. Medi-lo depois — como se fazia — entregava a decisão ao
            # jogo, que nunca está em silêncio: o portão ficava escancarado a
            # sessão inteira e a economia que ele existe para dar virava zero
            # justamente para quem liga 'Ouvir o jogo'.
            nivel_microfone = dsp.nivel_de(amostras)

            if jogo_ligado:
                # Com o buffer limpo durante a fala, isto devolve silêncio — o
                # relógio segue casado com o microfone de qualquer modo.
                jogo = self._take_loopback(amostras.size)
                amostras = dsp.mix(amostras, jogo, self._game_gain)

            # A abertura do portão devolve o pré-rolo INTEIRO de uma vez — com
            # 'Ouvir o jogo', os dez segundos de contexto. É a rajada para a
            # qual CAPTURE_QUEUE_BLOCKS foi dimensionada, e é por ela que o
            # enfileiramento aqui não pode bloquear.
            pronto = dsp.array_to_pcm(amostras)
            for envio in self.portao_de_voz.avaliar(
                pronto, nivel_microfone, time.monotonic()
            ):
                self._enfileirar(envio)

        with suppress(queue.Full):
            self.frames.put_nowait(None)

    def _reabrir_microfone(self) -> bool:
        """Tenta recuperar o microfone após uma falha de leitura.

        Soluços de USB e trocas de dispositivo padrão no Windows derrubam o
        stream com OSError, mas o dispositivo volta em seguida. Três tentativas
        com espera crescente cobrem esses casos sem segurar a thread por muito
        tempo quando o microfone foi realmente removido.
        """
        with suppress(Exception):
            self._stream.close()
        for tentativa in range(1, 4):
            if self._stop.is_set():
                return False
            time.sleep(0.4 * tentativa)
            try:
                self._stream, self._native_rate = self._open_input(self._input_device_index)
            except (AudioError, OSError):
                LOGGER.debug("Reabertura %s do microfone falhou.", tentativa, exc_info=True)
                continue
            LOGGER.info("Microfone reaberto na tentativa %s.", tentativa)
            return True
        return False

    @property
    def has_loopback(self) -> bool:
        return self._loopback_stream is not None

    def close(self) -> None:
        self._stop.set()
        if self.blocos_descartados:
            # Se isto aparecer, a fila ficou pequena para a rajada do pré-rolo:
            # é o sintoma que CAPTURE_QUEUE_BLOCKS existe para não produzir.
            LOGGER.warning(
                "%s bloco(s) de captura descartados por fila cheia.", self.blocos_descartados
            )
        # Parar os streams desbloqueia qualquer read() pendente na thread.
        for stream in (self._stream, self._loopback_stream):
            if stream is None:
                continue
            with suppress(OSError):
                if stream.is_active():
                    stream.stop_stream()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)
        for stream in (self._stream, self._loopback_stream):
            if stream is None:
                continue
            with suppress(OSError):
                stream.close()
        with suppress(queue.Full):
            self.frames.put_nowait(None)


class AudioSession:
    """Dono do PyAudio e dos dois motores. Garante liberação mesmo em falha."""

    def __init__(
        self,
        *,
        input_device: int | None = None,
        output_device: int | None = None,
        game_audio: bool = False,
        game_gain: float = 0.45,
        speaker_mode: bool = False,
    ) -> None:
        self._audio = pyaudio.PyAudio()
        self.playback: Playback | None = None
        self.capture: Capture | None = None
        try:
            loopback: Device | None = None
            if game_audio and HAS_LOOPBACK_SUPPORT:
                with suppress(Exception):
                    info = self._audio.get_default_wasapi_loopback()
                    if info:
                        loopback = _device_from_info(info, input_side=True, loopback=True)

            self.playback = Playback(self._audio, output_device)
            self.capture = Capture(
                self._audio,
                input_device=input_device,
                loopback_device=loopback,
                game_gain=game_gain,
            )
            self.capture.attach_playback(self.playback)
            if speaker_mode:
                self.capture.echo_gate_enabled.set()
            if game_audio and self.capture.has_loopback:
                self.capture.game_audio_enabled.set()
            self.capture.start()
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self.capture is not None:
            with suppress(Exception):
                self.capture.close()
            self.capture = None
        if self.playback is not None:
            with suppress(Exception):
                self.playback.close()
            self.playback = None
        with suppress(Exception):
            self._audio.terminate()

    def __enter__(self) -> AudioSession:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
