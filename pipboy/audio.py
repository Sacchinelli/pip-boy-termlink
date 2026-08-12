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
    VOICE_GATE_NOISE_FACTOR,
    VOICE_GATE_NOISE_PERCENTILE,
    VOICE_GATE_NOISE_WINDOW_BLOCKS,
    VOICE_GATE_PREROLL_BLOCKS,
    VOICE_GATE_THRESHOLD,
    VOICE_GATE_THRESHOLD_MAX,
    VOICE_GATE_THRESHOLD_MIN,
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


class PisoDeRuido:
    """Quanto barulho esta sala faz quando ninguém está falando.

    Estatística de mínimos: a janela dos últimos segundos, ordenada, e o
    percentil baixo dela. O truque todo está em por que isso funciona —
    fala humana tem buraco. Entre palavras, entre sílabas, entre frases: numa
    janela de dez segundos, muito mais de 10% dos blocos são fundo mesmo com
    alguém falando sem parar. O percentil baixo cai justamente nesses buracos,
    e um pico de fala não move a estimativa porque ele mora no topo da ordem.

    Por isso a janela recebe TODOS os blocos, inclusive os que o portão está
    transmitindo. Aprender apenas do que o portão recusou parece mais
    disciplinado e produz um impasse: a sala fica barulhenta, o portão trava
    aberto, nada mais é recusado, nada mais é aprendido, e o portão fica
    aberto para sempre — exatamente o defeito que este objeto veio corrigir.

    Enquanto a janela não junta amostra bastante, ``limiar`` devolve o valor
    de partida. Um portão que se calibra com meio segundo de sala é um portão
    que se calibra com o pigarro de quem sentou.
    """

    def __init__(
        self,
        *,
        inicial: float = VOICE_GATE_THRESHOLD,
        janela: int = VOICE_GATE_NOISE_WINDOW_BLOCKS,
        percentil: float = VOICE_GATE_NOISE_PERCENTILE,
        fator: float = VOICE_GATE_NOISE_FACTOR,
        minimo: float = VOICE_GATE_THRESHOLD_MIN,
        maximo: float = VOICE_GATE_THRESHOLD_MAX,
    ) -> None:
        self._inicial = inicial
        self._percentil = min(1.0, max(0.0, percentil))
        self._fator = fator
        self._minimo = minimo
        self._maximo = maximo
        self._janela: deque[float] = deque(maxlen=max(1, janela))
        # Um quarto da janela ≈ 2,5 s: tempo de a sala se apresentar, curto o
        # bastante para a calibração valer já na primeira pergunta.
        self._amostras_minimas = max(1, max(1, janela) // 4)

    def observar(self, nivel: float) -> None:
        self._janela.append(max(0.0, nivel))

    @property
    def maduro(self) -> bool:
        """Já há amostra suficiente para o piso valer mais que o palpite?"""
        return len(self._janela) >= self._amostras_minimas

    @property
    def piso(self) -> float:
        """Nível de fundo estimado. ``-1.0`` enquanto a janela não amadurece."""
        if not self.maduro:
            return -1.0
        ordenados = sorted(self._janela)
        # Índice truncado e preso ao fim: com o percentil em 1.0, ou com a
        # janela pequena, ele apontaria uma casa além do último elemento.
        indice = min(len(ordenados) - 1, int(len(ordenados) * self._percentil))
        return ordenados[indice]

    @property
    def limiar(self) -> float:
        """O limiar que o portão deve usar agora, já entre os dois batentes."""
        piso = self.piso
        if piso < 0.0:
            return self._inicial
        return min(self._maximo, max(self._minimo, piso * self._fator))


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

    O limiar não é fixo: ele acompanha o ``PisoDeRuido``, que mede a sala em
    vez de presumi-la. ``adaptativo=False`` congela o limiar no valor dado —
    serve para exercitar a decisão do portão sem a calibração no meio.
    """

    def __init__(
        self,
        *,
        limiar: float = VOICE_GATE_THRESHOLD,
        pre_roll: int = VOICE_GATE_PREROLL_BLOCKS,
        cauda: float = VOICE_GATE_HANGOVER_SECONDS,
        adaptativo: bool = True,
    ) -> None:
        self._limiar_inicial = limiar
        self._piso = PisoDeRuido(inicial=limiar) if adaptativo else None
        self._cauda = cauda
        self._buffer: deque[bytes] = deque(maxlen=max(0, pre_roll))
        self._aberto_ate = 0.0
        self._aberto = False
        self.blocos_enviados = 0
        self.blocos_retidos = 0

    @property
    def aberto(self) -> bool:
        """O portão está transmitindo agora?

        É o que permite avisar o serviço quando a fala começa e termina. Sem
        esse aviso, o servidor roda o VAD DELE do zero sobre o áudio que
        recebe e leva cerca de setecentos milissegundos para concluir o que
        este objeto já sabia — a cada pergunta.
        """
        return self._aberto

    @property
    def limiar(self) -> float:
        """O limiar em vigor neste instante — calibrado, se houver calibração.

        Público porque é a única forma de responder "por que o portão não está
        economizando nada?" sem instrumentar a thread de captura por dentro.
        """
        return self._piso.limiar if self._piso is not None else self._limiar_inicial

    def avaliar(self, bloco: bytes, nivel: float, agora: float) -> list[bytes]:
        """Devolve os blocos a transmitir agora — nenhum, este, ou o pré-rolo."""
        # A janela do piso recebe este bloco ANTES da decisão. Um bloco não
        # muda um percentil sobre dez segundos, e observar primeiro mantém a
        # regra simples: tudo o que o portão vê, o piso vê.
        if self._piso is not None:
            self._piso.observar(nivel)

        # O bloco passa por MÉRITO PRÓPRIO quando está acima do limiar, e não
        # apenas por estar dentro da cauda. Decidir só pela cauda deixava o
        # portão fechado para sempre com ``cauda=0``: ``agora >= agora`` é
        # verdadeiro no exato instante em que a fala começa.
        ativo = nivel >= self.limiar
        if ativo:
            self._aberto_ate = agora + self._cauda

        if not ativo and agora >= self._aberto_ate:
            self._buffer.append(bloco)
            self.blocos_retidos += 1
            self._aberto = False
            return []

        saida = list(self._buffer)
        self._buffer.clear()
        saida.append(bloco)
        self.blocos_enviados += len(saida)
        self._aberto = True
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

    def fechar(self) -> bool:
        """Força o portão fechado. Devolve se ele estava aberto.

        Existe por causa do contrato de atividade manual: todo aviso de início
        de fala PRECISA de um fim correspondente, senão o serviço fica
        esperando o resto de um turno que nunca vem e a sessão emudece. Mudo,
        assistente falando e troca de conexão fecham o portão por fora do
        laço normal — e o valor devolvido diz a quem chamou se ainda há um
        fim de fala a anunciar.
        """
        estava = self._aberto
        self._aberto = False
        self._aberto_ate = 0.0
        return estava

    @property
    def piso_de_ruido(self) -> float:
        """Nível de fundo medido, ou ``-1.0`` sem calibração ou sem amostra."""
        return self._piso.piso if self._piso is not None else -1.0

    @property
    def economia(self) -> float:
        """Fração dos blocos que não foi transmitida."""
        total = self.blocos_enviados + self.blocos_retidos
        return self.blocos_retidos / total if total else 0.0


class MarcaDeFala:
    """Sentinela de borda de fala, viajando na fila junto com o áudio.

    A ordem entre "a fala começou" e os blocos que a compõem é o significado
    inteiro do aviso: mandar o início depois do pré-rolo faria o serviço
    descartar justamente a primeira sílaba que o pré-rolo existe para
    preservar. Por isso as marcas vão pela MESMA fila dos blocos, e não por um
    canal paralelo que chegaria fora de hora.
    """

    __slots__ = ("nome",)

    def __init__(self, nome: str) -> None:
        self.nome = nome

    def __repr__(self) -> str:  # pragma: no cover - conveniência de depuração
        return f"<{self.nome}>"


INICIO_DE_FALA = MarcaDeFala("INICIO_DE_FALA")
FIM_DE_FALA = MarcaDeFala("FIM_DE_FALA")

# O que trafega da captura para o envio: um bloco de áudio, uma borda de fala,
# ou ``None`` para "acabou" (parada pedida ou microfone morto).
ItemDeCaptura = bytes | MarcaDeFala


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
        self.frames: queue.Queue[ItemDeCaptura | None] = queue.Queue(maxsize=CAPTURE_QUEUE_BLOCKS)
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

    def _enfileirar(self, bloco: ItemDeCaptura) -> None:
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

            # O sinal é decodificado e reamostrado ANTES de qualquer decisão,
            # para que o medidor da tela e o portão julguem exatamente o mesmo
            # número. Eram dois: a tela recebia o RMS do bloco cru, na taxa
            # nativa do dispositivo, e o portão media o vetor já reamostrado
            # para 16 kHz — a interpolação suaviza o sinal e derruba um pouco o
            # RMS, então os dois discordavam justamente em quem abre o portão.
            # Enquanto o limiar era invisível, a discordância era acadêmica;
            # agora que o medidor DESENHA o limiar, ela viraria uma mentira
            # desenhada na tela.
            #
            # O custo de reamostrar também no caminho que não envia (mudo, ou
            # assistente falando) é uma interpolação de mil amostras dezesseis
            # vezes por segundo — e, na maioria das máquinas, nem isso: em
            # 16 kHz nativo ``resample`` devolve o próprio vetor.
            amostras = dsp.pcm_to_array(bruto).astype(np.int32)
            if self._native_rate != INPUT_SAMPLE_RATE:
                amostras = dsp.resample(amostras, self._native_rate, INPUT_SAMPLE_RATE)

            # O nível que abre o portão é o do MICROFONE, medido antes da
            # mistura. Medi-lo depois — como se fazia — entregava a decisão ao
            # jogo, que nunca está em silêncio: o portão ficava escancarado a
            # sessão inteira e a economia que ele existe para dar virava zero
            # justamente para quem liga 'Ouvir o jogo'.
            nivel_microfone = dsp.nivel_de(amostras)
            self.last_level = nivel_microfone

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
                # Emudecer ou começar a falar por cima interrompe uma fala que
                # podia estar em curso. O serviço precisa saber que ela acabou
                # aqui, senão fica esperando o resto de um turno que este ramo
                # garantiu que nunca virá.
                if self.portao_de_voz.fechar():
                    self._enfileirar(FIM_DE_FALA)
                continue

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
            estava_aberto = self.portao_de_voz.aberto
            envios = self.portao_de_voz.avaliar(pronto, nivel_microfone, time.monotonic())

            # As marcas cercam o áudio, e o lado em que entram importa: o
            # início vai ANTES do pré-rolo (senão o serviço descarta a primeira
            # sílaba) e o fim vai DEPOIS do último bloco (senão corta a última).
            if envios and not estava_aberto:
                self._enfileirar(INICIO_DE_FALA)
            for envio in envios:
                self._enfileirar(envio)
            if estava_aberto and not self.portao_de_voz.aberto:
                self._enfileirar(FIM_DE_FALA)

        # A captura morrendo com o portão aberto deixaria um turno pendurado.
        if self.portao_de_voz.fechar():
            self._enfileirar(FIM_DE_FALA)
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
        portao = self.portao_de_voz
        if portao.blocos_enviados or portao.blocos_retidos:
            # Sem esta linha, "o portão não está economizando nada" é uma
            # queixa sem como ser investigada depois do fato: a sala que ele
            # mediu e o limiar a que chegou não sobrevivem ao processo.
            LOGGER.info(
                "Portão de voz: %.0f%% dos blocos retidos, limiar final %.3f "
                "(piso de ruído %.3f).",
                portao.economia * 100,
                portao.limiar,
                portao.piso_de_ruido,
            )
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
