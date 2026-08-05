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


# Timbre por tema. Quem não estiver aqui usa a receita padrão — o mesmo
# contrato da atmosfera: acrescentar é uma linha, esquecer não quebra nada.
RECEITAS: dict[str, ReceitaSonora] = {
    "Fallout": ReceitaSonora("quadrada", 392.0, 784.0),        # terminal 8-bit
    "Elden Ring": ReceitaSonora("triangular", 330.0, 660.0),   # sino distante
    "Skyrim": ReceitaSonora("triangular", 294.0, 587.0),
    "The Witcher 3": ReceitaSonora("triangular", 262.0, 523.0),
    "Red Dead": ReceitaSonora("triangular", 247.0, 494.0),
    "GTA": ReceitaSonora("senoide", 440.0, 880.0),
    "Cyberpunk 2077": ReceitaSonora("quadrada", 523.0, 1046.0),  # netrunner
    "FPS / Multiplayer": ReceitaSonora("senoide", 494.0, 988.0),
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
    """O blip de um evento, como float32 em [-1, 1]."""
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
    cru = f"{receita.forma}:{receita.grave:.1f}:{receita.agudo:.1f}"
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
