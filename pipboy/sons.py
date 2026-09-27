"""Sons de interface sintetizados: o aparelho também se ouve.

Um Pip-Boy apita. O mesmo princípio que gera a atmosfera com QPainter gera
os blips com NumPy: nenhum arquivo de áudio no repositório — cada tema tem
uma *receita* (forma de onda, frequências, duração) e o WAV é sintetizado na
primeira execução e guardado em cache na pasta de dados.

Quatro eventos merecem som, e só quatro: sessão iniciada, sessão encerrada,
palavra salva no caderno e erro. Interface que apita a cada clique é um
brinquedo; um aparelho só fala quando algo aconteceu.

Este módulo é a SÍNTESE (pura, testável). Quem toca é a interface, que
também decide quando ficar em silêncio — a intensidade da atmosfera vale
para o ouvido tanto quanto para o olho.
"""

from __future__ import annotations

import contextlib
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

TAXA = 22_050  # Hz — sobra para blips; metade do custo de disco de 44.1k
AMPLITUDE = 0.32  # teto absoluto: efeito de interface não disputa com a voz

# Eventos sonoros do programa. As chaves são a API pública deste módulo.
EVENTOS = ("iniciar", "encerrar", "vocab", "erro")


@dataclass(frozen=True, slots=True)
class ReceitaSonora:
    """O timbre de um tema, em números.

    ``forma`` escolhe o oscilador: *senoide* (limpa, futurista), *quadrada*
    (8-bit, terminal), *triangular* (macia, arcana). As frequências são os
    dois polos do blip — subida para iniciar, descida para encerrar.
    """

    forma: str = "senoide"
    grave: float = 440.0
    agudo: float = 880.0
    # O gesto sonoro do jogo (ver VOZES); vazio, o blip de sempre.
    voz: str = ""


# Timbre por tema. Quem não estiver aqui usa a receita padrão — o mesmo
# contrato da atmosfera: acrescentar é uma linha, esquecer não quebra nada.
RECEITAS: dict[str, ReceitaSonora] = {
    "Fallout": ReceitaSonora("quadrada", 392.0, 784.0, "pipboy"),        # terminal 8-bit
    "Elden Ring": ReceitaSonora("triangular", 330.0, 660.0, "graca"),   # sino distante
    "Skyrim": ReceitaSonora("triangular", 294.0, 587.0, "trompa"),
    "The Witcher 3": ReceitaSonora("triangular", 262.0, 523.0, "medalhao"),
    "Red Dead": ReceitaSonora("triangular", 247.0, 494.0, "violao"),
    "GTA": ReceitaSonora("senoide", 440.0, 880.0, "celular"),
    "Cyberpunk 2077": ReceitaSonora("quadrada", 523.0, 1046.0, "glitch"),  # netrunner
    # Rádio de esquadrão: quadrada e grave, o estalo de um canal abrindo.
    "FPS / Multiplayer": ReceitaSonora("quadrada", 311.0, 622.0, "radio"),
    "RPG / Aventura (geral)": ReceitaSonora("triangular", 277.2, 554.4, "harpa"),
}
RECEITA_PADRAO = ReceitaSonora()


def _oscilador(forma: str, frequencia: np.ndarray) -> np.ndarray:
    """Oscilador de frequência variável, integrada por acumulação de fase.

    A fase sai do ``cumsum`` da frequência — é ele que permite um sweep sem
    descontinuidade. Um vetor de tempo era recebido e ignorado desde sempre:
    dava a impressão de que a fase vinha de ``2πft``, que é a fórmula errada
    para frequência que varia.
    """
    fase = 2 * np.pi * np.cumsum(frequencia) / TAXA
    if forma == "quadrada":
        # Suavizada por tanh: a quadrada pura estala nos alto-falantes.
        return np.tanh(3.0 * np.sin(fase))
    if forma == "triangular":
        return 2.0 / np.pi * np.arcsin(np.sin(fase))
    return np.sin(fase)


def _envelope(n: int, ataque: float = 0.01, queda: float = 0.6) -> np.ndarray:
    """Sobe rápido, cai como exponencial — o desenho de um blip de aparelho."""
    t = np.linspace(0.0, 1.0, n, endpoint=False)
    subida = np.clip(t / max(ataque, 1e-6), 0.0, 1.0)
    return subida * np.exp(-t / queda)


def sintetizar(evento: str, receita: ReceitaSonora) -> np.ndarray:
    """O som de um evento, como float32 em [-1, 1]: a voz do jogo, ou o blip."""
    if receita.voz in VOZES:
        if evento not in EVENTOS:
            raise ValueError(f"evento sonoro desconhecido: {evento}")
        return _acabar(VOZES[receita.voz](evento))
    if evento == "iniciar":
        duracao, de, para = 0.16, receita.grave, receita.agudo
    elif evento == "encerrar":
        duracao, de, para = 0.16, receita.agudo, receita.grave
    elif evento == "vocab":
        # Dois toques curtos no agudo: uma anotação, não um alarme.
        um = sintetizar_tom(receita, receita.agudo, 0.05)
        silencio = np.zeros(int(TAXA * 0.04), dtype=np.float32)
        dois = sintetizar_tom(receita, receita.agudo * 1.25, 0.07)
        return np.concatenate([um, silencio, dois])
    elif evento == "erro":
        # Grave, batido, inconfundível — e ainda assim curto.
        um = sintetizar_tom(receita, receita.grave * 0.5, 0.09)
        silencio = np.zeros(int(TAXA * 0.05), dtype=np.float32)
        return np.concatenate([um, silencio, um])
    else:
        raise ValueError(f"evento sonoro desconhecido: {evento}")

    n = int(TAXA * duracao)
    frequencia = np.geomspace(de, para, n)
    onda = _oscilador(receita.forma, frequencia)
    return (onda * _envelope(n) * AMPLITUDE).astype(np.float32)


def sintetizar_tom(receita: ReceitaSonora, frequencia: float, duracao: float) -> np.ndarray:
    n = int(TAXA * duracao)
    onda = _oscilador(receita.forma, np.full(n, frequencia))
    return (onda * _envelope(n, queda=0.35) * AMPLITUDE).astype(np.float32)


# ------------------------------------------------------------------- Vozes
# O timbre mudava de jogo para jogo — senoide, quadrada, triangular —, mas o
# DESENHO de cada evento era o mesmo nos dez: uma subida para iniciar, uma
# descida para encerrar, dois toques para a palavra, uma batida grave para o
# erro. Um jogo se reconhece pelo desenho do som, e não só pela forma da onda:
# o bip em degraus do Pip-Boy ligando, o sino da graça, o dedilhado de violão
# do acampamento, o "ding" de mensagem do celular, o estalo do marcador de
# acerto. Cada tema declara uma VOZ (``ReceitaSonora.voz``) — o mesmo contrato
# de quatro eventos, com o gesto sonoro do jogo. Tudo sintetizado aqui, sem
# arquivo de áudio nenhum; o ruído é sorteado com semente fixa, e a síntese
# continua determinística.

DURACAO_MAXIMA = 0.9  # segundos: o sino da graça precisa de cauda; mais que isso é música


def _silencio(duracao: float) -> np.ndarray:
    return np.zeros(int(TAXA * duracao), dtype=np.float64)


def _tom(frequencia: float, duracao: float, forma: str = "senoide", queda: float = 0.35,
         ataque: float = 0.01) -> np.ndarray:
    n = int(TAXA * duracao)
    return _oscilador(forma, np.full(n, frequencia)) * _envelope(n, ataque, queda)


def _ruido(duracao: float, semente: int, queda: float = 0.3) -> np.ndarray:
    """Chiado com semente fixa. ``queda`` é FRAÇÃO da duração, como em ``_envelope``."""
    n = int(TAXA * duracao)
    sorteio = np.random.default_rng(semente)
    bruto = sorteio.uniform(-1.0, 1.0, n)
    # Um passa-baixa de um polo: o chiado de rádio não é o chiado branco.
    suave = np.empty(n)
    acumulado = 0.0
    for i in range(n):
        acumulado = 0.65 * acumulado + 0.35 * bruto[i]
        suave[i] = acumulado
    return suave * _envelope(n, 0.002, queda) * 2.0


def _corda(frequencia: float, duracao: float, semente: int, amortecimento: float = 0.996) -> np.ndarray:
    """Uma corda dedilhada pelo algoritmo de Karplus-Strong.

    Um período de ruído circula numa linha de atraso, e a média de cada
    amostra com a seguinte é um passa-baixa que apaga primeiro os agudos —
    como numa corda de verdade, que perde o brilho antes do corpo.
    """
    periodo = max(2, round(TAXA / frequencia))
    sorteio = np.random.default_rng(semente)
    linha = sorteio.uniform(-1.0, 1.0, periodo)
    n = int(TAXA * duracao)
    saida = np.empty(n)
    for i in range(n):
        atual = linha[i % periodo]
        saida[i] = atual
        linha[i % periodo] = amortecimento * 0.5 * (atual + linha[(i + 1) % periodo])
    return saida


def _sino(frequencia: float, duracao: float) -> np.ndarray:
    """Um sino por síntese aditiva: parciais inarmônicas, cada uma com a sua queda.

    As razões são as do sino de Risset, e o que o faz soar sino e não órgão é
    exatamente isso: as parciais não são múltiplos inteiros da fundamental, e
    as agudas somem antes das graves.
    """
    n = int(TAXA * duracao)
    t = np.arange(n) / TAXA
    soma = np.zeros(n)
    for razao, amplitude, queda in (
        (0.56, 1.0, 0.9), (0.92, 0.67, 0.6), (1.19, 1.0, 0.45), (1.71, 1.8, 0.3),
        (2.0, 0.67, 0.25), (2.74, 1.46, 0.2), (3.0, 1.33, 0.15), (3.76, 1.33, 0.12),
    ):
        soma += amplitude * np.sin(2 * np.pi * frequencia * razao * t) * np.exp(-t / queda)
    return soma * np.clip(t / 0.004, 0.0, 1.0)


def _trompa(frequencia: float, duracao: float) -> np.ndarray:
    """Um sopro grave: harmônicos em 1/n, ataque lento e um vibrato leve."""
    n = int(TAXA * duracao)
    t = np.arange(n) / TAXA
    vibrato = 1.0 + 0.006 * np.sin(2 * np.pi * 5.5 * t)
    fase = 2 * np.pi * np.cumsum(np.full(n, frequencia) * vibrato) / TAXA
    soma = sum(np.sin(fase * k) / k for k in range(1, 7))
    ataque = np.clip(t / 0.06, 0.0, 1.0)
    return soma * ataque * np.exp(-t / (duracao * 0.8))


def _zumbido(frequencia: float, duracao: float, tremor: float = 14.0) -> np.ndarray:
    """O medalhão vibrando: um tom com o volume tremendo, e um brilho metálico."""
    n = int(TAXA * duracao)
    t = np.arange(n) / TAXA
    onda = np.sin(2 * np.pi * frequencia * t) + 0.25 * np.sin(2 * np.pi * frequencia * 6 * t)
    tremido = 0.55 + 0.45 * np.sin(2 * np.pi * tremor * t)
    return onda * tremido * _envelope(n, 0.02, duracao * 0.7)


def _degraus(frequencias: list[float], passo: float, forma: str) -> np.ndarray:
    return np.concatenate([_tom(f, passo, forma, queda=0.5, ataque=0.004) for f in frequencias])


def _juntar(*partes: np.ndarray) -> np.ndarray:
    return np.concatenate([np.asarray(p, dtype=np.float64) for p in partes])


def _somar(*partes: tuple[float, np.ndarray]) -> np.ndarray:
    """Soma camadas, cada uma começando no instante dado (em segundos)."""
    fim = max(int(TAXA * inicio) + len(p) for inicio, p in partes)
    soma = np.zeros(fim)
    for inicio, p in partes:
        de = int(TAXA * inicio)
        soma[de:de + len(p)] += p
    return soma


def _acabar(onda: np.ndarray) -> np.ndarray:
    """No teto de amplitude, com as pontas suavizadas: um corte seco estala."""
    pico = float(np.abs(onda).max()) or 1.0
    onda = onda / pico * AMPLITUDE
    borda = min(len(onda) // 4, int(TAXA * 0.004))
    if borda > 0:
        rampa = np.linspace(0.0, 1.0, borda)
        onda[:borda] *= rampa
        onda[-borda:] *= rampa[::-1]
    return onda.astype(np.float32)


def _voz_pipboy(evento: str) -> np.ndarray:
    """Fallout: o estalo do aparelho e o bip de 8 bits em degraus."""
    estalo = _ruido(0.008, 1, queda=0.2)
    if evento == "iniciar":
        return _juntar(estalo, _silencio(0.02), _degraus([392.0, 523.0, 784.0], 0.06, "quadrada"))
    if evento == "encerrar":
        return _juntar(_degraus([784.0, 523.0, 392.0], 0.06, "quadrada"), _silencio(0.02), estalo)
    if evento == "vocab":
        # A holotape entrando: dois estalos e o bip de leitura.
        return _juntar(estalo, _silencio(0.03), estalo, _silencio(0.03),
                       _tom(1046.0, 0.08, "quadrada", queda=0.4))
    # Negado: um zumbido grave de 8 bits, tremido.
    n = int(TAXA * 0.24)
    t = np.arange(n) / TAXA
    return _tom(110.0, 0.24, "quadrada", queda=0.6) * (0.6 + 0.4 * np.sign(np.sin(2 * np.pi * 16 * t)))


def _voz_graca(evento: str) -> np.ndarray:
    """Elden Ring: sinos — a graça que acende, com a cauda longa do eco."""
    if evento == "iniciar":
        return _somar((0.0, _sino(330.0, 0.8)), (0.07, _sino(495.0, 0.72)))
    if evento == "encerrar":
        return _somar((0.0, _sino(495.0, 0.8)), (0.07, _sino(330.0, 0.72)))
    if evento == "vocab":
        return _sino(990.0, 0.7)
    return _sino(165.0, 0.45) * np.exp(-np.arange(int(TAXA * 0.45)) / (TAXA * 0.12))


def _voz_trompa(evento: str) -> np.ndarray:
    """Skyrim: a trompa do norte, e o brilho da habilidade que sobe."""
    if evento == "iniciar":
        return _juntar(_trompa(196.0, 0.22), _trompa(294.0, 0.32))
    if evento == "encerrar":
        return _juntar(_trompa(294.0, 0.22), _trompa(196.0, 0.32))
    if evento == "vocab":
        return _degraus([587.0, 740.0, 880.0], 0.07, "triangular")
    # Um tambor grave: o tom despenca e some.
    n = int(TAXA * 0.3)
    frequencia = np.geomspace(140.0, 55.0, n)
    return _oscilador("senoide", frequencia) * _envelope(n, 0.003, 0.09) + 0.3 * _ruido(0.3, 7, 0.04)


def _voz_medalhao(evento: str) -> np.ndarray:
    """The Witcher 3: o medalhão vibrando, e o tinido do aço."""
    if evento == "iniciar":
        # A espada saindo da bainha: um chiado que sobe, e o medalhão.
        return _somar((0.0, _ruido(0.16, 3, 0.6)), (0.1, _zumbido(220.0, 0.36)))
    if evento == "encerrar":
        return _zumbido(196.0, 0.4, tremor=10.0)
    if evento == "vocab":
        tinido = _tom(2637.0, 0.12, queda=0.08) + 0.6 * _tom(3951.0, 0.12, queda=0.05)
        return _somar((0.0, tinido), (0.06, 0.6 * _zumbido(330.0, 0.28)))
    return _zumbido(110.0, 0.34, tremor=8.0)


def _voz_violao(evento: str) -> np.ndarray:
    """Red Dead: o violão do acampamento, dedilhado."""
    if evento == "iniciar":
        return _somar((0.0, _corda(164.8, 0.5, 11)), (0.08, _corda(246.9, 0.45, 12)),
                      (0.16, _corda(329.6, 0.4, 13)))
    if evento == "encerrar":
        return _somar((0.0, _corda(329.6, 0.5, 14)), (0.08, _corda(246.9, 0.45, 15)),
                      (0.16, _corda(164.8, 0.4, 16)))
    if evento == "vocab":
        return _somar((0.0, _corda(493.9, 0.35, 17)), (0.07, _corda(659.3, 0.35, 18)))
    # Uma corda grave que desafina contra a vizinha: algo deu errado.
    return _somar((0.0, _corda(82.4, 0.4, 19, 0.99)), (0.0, _corda(87.3, 0.4, 20, 0.99)))


def _voz_celular(evento: str) -> np.ndarray:
    """GTA: o celular — a estática da rádio, o "ding" de mensagem, o tom de ocupado."""
    ding = _tom(1318.5, 0.07, queda=0.3) + _tom(1760.0, 0.07, queda=0.3)
    if evento == "iniciar":
        return _juntar(_ruido(0.09, 21, 0.6), _silencio(0.02), ding)
    if evento == "encerrar":
        return _juntar(_tom(1760.0, 0.06), _tom(1318.5, 0.08), _silencio(0.02), _ruido(0.07, 22, 0.5))
    if evento == "vocab":
        return _juntar(_tom(1568.0, 0.06), _silencio(0.02), _tom(2093.0, 0.09))
    # Ocupado: 480 e 620 Hz juntos, os mesmos do telefone de verdade — em
    # dois toques curtos, porque meio segundo ligado seria uma sirene.
    toque = _tom(480.0, 0.12, queda=2.0) + _tom(620.0, 0.12, queda=2.0)
    return _juntar(toque, _silencio(0.08), toque)


def _voz_glitch(evento: str) -> np.ndarray:
    """Cyberpunk: a rajada de dados, em degraus sorteados, quebrada em bits."""
    sorteio = np.random.default_rng({"iniciar": 31, "encerrar": 32, "vocab": 33}.get(evento, 34))
    if evento in ("iniciar", "encerrar"):
        base = np.geomspace(400.0, 1800.0, 12)
        if evento == "encerrar":
            base = base[::-1]
        passos = [float(f * sorteio.uniform(0.85, 1.15)) for f in base]
        onda = _degraus(passos, 0.018, "quadrada")
    elif evento == "vocab":
        onda = _degraus([1046.0, 1318.0, 1568.0, 2093.0], 0.028, "quadrada")
    else:
        onda = _tom(150.0, 0.3, "quadrada", queda=1.0)
        portao = np.repeat(sorteio.integers(0, 2, 30), len(onda) // 30 + 1)[: len(onda)]
        onda = onda * (0.25 + 0.75 * portao)
    # A quebra em bits: poucos níveis, que é o que soa digital.
    return np.round(onda * 6.0) / 6.0


def _voz_radio(evento: str) -> np.ndarray:
    """FPS: o canal do esquadrão — o chiado que abre, o bip de câmbio, o marcador de acerto."""
    cambio = _tom(1000.0, 0.05, queda=0.5)
    if evento == "iniciar":
        return _juntar(_ruido(0.07, 41, 0.5), _silencio(0.015), cambio)
    if evento == "encerrar":
        return _juntar(cambio, _silencio(0.015), _ruido(0.14, 42, 0.4))
    if evento == "vocab":
        # O marcador de acerto: dois estalos agudos e secos.
        estalo = _tom(3000.0, 0.016, queda=0.35, ataque=0.03) + 0.5 * _ruido(0.016, 43, 0.35)
        return _juntar(estalo, _silencio(0.045), estalo)
    return _tom(150.0, 0.22, "quadrada", queda=0.5)


def _voz_harpa(evento: str) -> np.ndarray:
    """RPG: a harpa do menestrel, em arpejo, e o brilho de um encanto."""

    def nota(frequencia: float, duracao: float = 0.28) -> np.ndarray:
        n = int(TAXA * duracao)
        t = np.arange(n) / TAXA
        onda = (np.sin(2 * np.pi * frequencia * t) + 0.4 * np.sin(4 * np.pi * frequencia * t)
                + 0.15 * np.sin(6 * np.pi * frequencia * t))
        return onda * np.clip(t / 0.003, 0.0, 1.0) * np.exp(-t / 0.12)

    if evento == "iniciar":
        return _somar(*((i * 0.06, nota(f)) for i, f in enumerate((261.6, 329.6, 392.0, 523.3))))
    if evento == "encerrar":
        return _somar(*((i * 0.06, nota(f)) for i, f in enumerate((523.3, 392.0, 329.6, 261.6))))
    if evento == "vocab":
        return _somar(*((i * 0.035, nota(f, 0.2)) for i, f in enumerate((1046.5, 1318.5, 1568.0, 2093.0))))
    return _somar((0.0, nota(220.0, 0.35)), (0.0, nota(233.1, 0.35)))


VOZES: dict[str, Any] = {
    "pipboy": _voz_pipboy,
    "graca": _voz_graca,
    "trompa": _voz_trompa,
    "medalhao": _voz_medalhao,
    "violao": _voz_violao,
    "celular": _voz_celular,
    "glitch": _voz_glitch,
    "radio": _voz_radio,
    "harpa": _voz_harpa,
}


def para_wav(amostras: np.ndarray) -> bytes:
    """Um WAV PCM16 mono completo, pronto para gravar em disco."""
    pcm = (np.clip(amostras, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    cabecalho = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(pcm), b"WAVE",
        b"fmt ", 16, 1, 1, TAXA, TAXA * 2, 2, 16,
        b"data", len(pcm),
    )
    return cabecalho + pcm


def _assinatura(receita: ReceitaSonora) -> str:
    """Identidade curta e estável de uma receita, para o nome do arquivo.

    O cache era chaveado só pelo nome do tema. Afinar um timbre aqui — mudar
    uma forma de onda ou uma frequência — não invalidava nada: quem já tivesse
    aberto o programa uma vez continuava ouvindo, para sempre, os WAVs da
    receita antiga, e o defeito não aparecia em nenhuma máquina nova. Com a
    receita no nome, uma edição gera um conjunto novo por construção.
    """
    cru = f"{receita.forma}:{receita.grave:.1f}:{receita.agudo:.1f}:{receita.voz}"
    return f"{zlib.crc32(cru.encode('utf-8')):08x}"


def gerar_cache(pasta: Path, tema: str) -> dict[str, Path]:
    """Garante os quatro WAVs de um tema no disco e devolve seus caminhos.

    O nome do arquivo carrega o tema E a receita: trocar de jogo troca o
    conjunto, e um cache antigo nunca é tocado com o timbre errado.
    """
    receita = RECEITAS.get(tema, RECEITA_PADRAO)
    pasta.mkdir(parents=True, exist_ok=True)
    seguro = "".join(c if c.isalnum() else "_" for c in tema).strip("_") or "padrao"
    marca = _assinatura(receita)
    caminhos: dict[str, Path] = {}
    for evento in EVENTOS:
        destino = pasta / f"{seguro}-{marca}-{evento}.wav"
        if not destino.is_file():
            destino.write_bytes(para_wav(sintetizar(evento, receita)))
        caminhos[evento] = destino

    # Receitas velhas DESTE tema saem; as dos outros ficam. Varrer a pasta
    # inteira faria alternar entre dois jogos ressintetizar os dois a cada
    # troca, que é trocar um cache eternamente velho por cache nenhum.
    # Nenhum nome saneado contém '-', então o prefixo não alcança tema vizinho.
    atual = f"{seguro}-{marca}-"
    for antigo in pasta.glob(f"{seguro}-*.wav"):
        if not antigo.name.startswith(atual):
            with contextlib.suppress(OSError):
                antigo.unlink()
    return caminhos
