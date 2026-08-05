"""Processamento de sinal para o caminho de áudio.

Tudo aqui opera sobre PCM 16 bits little-endian, o formato exigido pela Live API.

Nota de portabilidade: o módulo ``audioop`` da biblioteca padrão faria boa parte
disto, mas foi REMOVIDO no Python 3.13 (PEP 594). Usar NumPy mantém o projeto
funcionando nas versões atuais e futuras do Python.
"""

from __future__ import annotations

import numpy as np

_INT16_MAX = 32767


def pcm_to_array(data: bytes) -> np.ndarray:
    """Converte bytes PCM16 em um vetor de inteiros de 16 bits."""
    return np.frombuffer(data, dtype="<i2")


def array_to_pcm(samples: np.ndarray) -> bytes:
    """Converte de volta para bytes, saturando em vez de estourar."""
    clipped = np.clip(samples, -_INT16_MAX - 1, _INT16_MAX)
    return clipped.astype("<i2").tobytes()


def downmix_to_mono(samples: np.ndarray, channels: int) -> np.ndarray:
    """Reduz um sinal intercalado de N canais para mono, pela média."""
    if channels <= 1:
        return samples
    usable = (samples.size // channels) * channels
    if usable == 0:
        return np.zeros(0, dtype=samples.dtype)
    frames = samples[:usable].reshape(-1, channels)
    return frames.mean(axis=1).astype(np.int32)


def resample(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    """Reamostragem por interpolação linear.

    Suficiente para voz falada e sem dependências pesadas. Não é a reamostragem
    de maior qualidade possível, mas o gargalo aqui é o codec do modelo, não
    alguns dB de aliasing acima de 8 kHz.
    """
    if source_rate == target_rate or samples.size == 0:
        return samples
    duration = samples.size / source_rate
    target_size = int(duration * target_rate)
    if target_size <= 0:
        return np.zeros(0, dtype=np.int32)
    source_positions = np.arange(samples.size, dtype=np.float64)
    target_positions = np.linspace(0.0, samples.size - 1.0, target_size)
    return np.interp(target_positions, source_positions, samples).astype(np.int32)


def mix(primary: np.ndarray, secondary: np.ndarray, secondary_gain: float) -> np.ndarray:
    """Soma duas fontes, alinhando comprimentos e aplicando ganho na secundária.

    A secundária é preenchida com silêncio ou truncada para casar com a
    primária, que dita o relógio da captura.
    """
    if secondary.size == 0 or secondary_gain <= 0.0:
        return primary
    if secondary.size < primary.size:
        secondary = np.pad(secondary, (0, primary.size - secondary.size))
    elif secondary.size > primary.size:
        secondary = secondary[: primary.size]
    return primary.astype(np.int32) + (secondary.astype(np.float64) * secondary_gain).astype(np.int32)


def nivel_de(samples: np.ndarray) -> float:
    """Nível médio de um bloco já decodificado, normalizado em 0.0–1.0."""
    if samples.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    return min(1.0, rms / _INT16_MAX * 4.0)


def rms_level(data: bytes) -> float:
    """Nível médio do bloco em PCM, para o medidor da interface."""
    return nivel_de(pcm_to_array(data))


def silence(num_samples: int) -> bytes:
    """Bloco de silêncio com o tamanho pedido."""
    return b"\x00\x00" * num_samples
