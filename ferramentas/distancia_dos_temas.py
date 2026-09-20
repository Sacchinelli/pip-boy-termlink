"""Mede o quanto os dez ambientes se parecem entre si, dois a dois.

Uso:  py ferramentas/distancia_dos_temas.py

**Isto não é um portão, é um instrumento.** Sai sempre com código 0 e não
entra no CI. Ele não reprova tema nenhum — dá um número onde antes havia só
opinião.

**A pergunta que ele responde.** "Trocar o jogo muda a janela inteira" é a
promessa do programa, e ela é fácil de acreditar olhando dois temas escolhidos
a dedo: o terminal verde do Fallout ao lado do neon do Cyberpunk convence
qualquer um. O que ninguém vê é o resto da tabela — se *Elden Ring* e
*RPG / Aventura* são a mesma tela dourada com outro título, ou se o *visor
tático* do FPS é só o tema neutro com uma grade por cima. Um tema genérico não
denuncia a si mesmo; ele só não é escolhido.

**Como mede.** Cada tema é fotografado na mesma janela, no mesmo tamanho, no
mesmo estado (parada, atmosfera Completa, sem cursor em cima). As fotos são
reduzidas a uma miniatura e comparadas pixel a pixel em **CIELAB**, com a
distância ΔE76 — a régua que aproxima "o quanto dois tons parecem diferentes
para o olho", e não "o quanto os bytes diferem". A média sobre a miniatura
inteira é a distância do par.

O layout é o mesmo de propósito: o que precisa diferenciar um ambiente do
outro é a cor, a atmosfera e a tipografia — não a posição dos botões. É por
isso que a medida não tenta descontar a estrutura comum.

**Como ler.** ΔE de 2,3 é o limiar clássico do "mal dá para ver a diferença"
entre dois tons vizinhos. Aqui a conta é uma média sobre a tela inteira, com
grandes áreas de fundo quase idênticas em qualquer tema, então o número é
naturalmente baixo: a régua prática deste programa é a tabela dos vizinhos
mais próximos, e não um valor absoluto. O que interessa é quem está no fim da
lista — e, principalmente, quem está lá **compartilhando a fonte** com o
vizinho, porque aí não sobrou identidade nenhuma.
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
from itertools import combinations
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

for _fluxo in (sys.stdout, sys.stderr):
    with contextlib.suppress(AttributeError, ValueError):
        _fluxo.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

# Sem tela e com as fontes de verdade: a mesma combinação das fotos de
# conferência. Sem o FONTDIR, o backend offscreen não enxerga fonte alguma e
# mediria dez temas desenhados em caixinhas — todos iguais, pelo motivo errado.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
# O caderno e as preferências de quem roda a ferramenta ficam de fora.
_TEMP = tempfile.mkdtemp(prefix="pipboy-regua-")
os.environ["LOCALAPPDATA"] = _TEMP
os.environ.setdefault("GEMINI_API_KEY", "AIzaREGUA_DOS_TEMAS_0000")

import numpy as np  # noqa: E402
from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QFontInfo, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pipboy.config import AppConfiguration  # noqa: E402
from pipboy.interface.atmosfera import atmosfera_de  # noqa: E402
from pipboy.interface.janela import Janela  # noqa: E402
from pipboy.themes import TEMAS  # noqa: E402

LARGURA, ALTURA = 1100, 760
# A miniatura: grande o bastante para guardar painéis, texto e o halo da
# atmosfera; pequena o bastante para a comparação ser instantânea.
MINI_L, MINI_A = 88, 60
# Quanto esperar a troca de tema assentar (a dissolução do ambiente antigo).
ESPERA_MS = 900


def _lab(imagem: QImage) -> np.ndarray:
    """A miniatura em CIELAB, como (N, 3) float."""
    imagem = imagem.convertToFormat(QImage.Format.Format_RGB32)
    bruto = np.frombuffer(bytes(imagem.constBits()), dtype=np.uint8)
    bruto = bruto.reshape(-1, 4)[:, :3][:, ::-1]  # BGRA -> RGB
    rgb = bruto.astype(np.float64) / 255.0

    # sRGB -> linear -> XYZ (D65) -> Lab.
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    m = np.array([
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ])
    xyz = linear @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16.0 / 116.0)
    return np.stack(
        [116.0 * f[:, 1] - 16.0, 500.0 * (f[:, 0] - f[:, 1]), 200.0 * (f[:, 1] - f[:, 2])],
        axis=1,
    )


def _esperar(ms: int) -> None:
    laco = QEventLoop()
    QTimer.singleShot(ms, laco.quit)
    laco.exec()


def main() -> int:
    aplicacao = QApplication.instance() or QApplication([])
    assert isinstance(aplicacao, QApplication)
    janela = Janela(AppConfiguration.load(Path(_TEMP)))
    janela.resize(LARGURA, ALTURA)
    janela.show()
    janela.campo_atmosfera.setCurrentText("Completa")
    _esperar(ESPERA_MS)

    fotos: dict[str, np.ndarray] = {}
    fichas: dict[str, tuple[str, str, str]] = {}
    for nome in TEMAS:
        # Pelo seletor, como um jogador faria: é o caminho que dispara a
        # dissolução do ambiente antigo e a repintura de tudo.
        janela.campo_jogo.setCurrentText(nome)
        _esperar(ESPERA_MS)
        mini = janela.grab().toImage().scaled(
            MINI_L, MINI_A,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        fotos[nome] = _lab(mini)
        receita = atmosfera_de(nome)
        vivas = ", ".join(
            parte for parte in (
                receita.particulas,
                "varredura" if receita.varredura else "",
                "grade" if receita.grade else "",
                "fibras" if receita.fibras else "",
                "tremulação" if receita.tremulacao else "",
                "interferência" if receita.interferencia else "",
            ) if parte
        )
        fichas[nome] = (
            QFontInfo(janela.fonte("display", ui=False)).family(),
            vivas or "—",
            receita.forma,
        )

    print()
    print("=" * 74)
    print("  CADA TEMA, COMO ELE CHEGA NA TELA")
    print("=" * 74)
    largura_nome = max(len(n) for n in TEMAS)
    for nome, (fonte, vivas, forma) in fichas.items():
        print(f"  {nome:<{largura_nome}}  {fonte:<22} {forma:<12} {vivas}")

    pares = sorted(
        (float(np.mean(np.linalg.norm(fotos[a] - fotos[b], axis=1))), a, b)
        for a, b in combinations(TEMAS, 2)
    )
    print()
    print("=" * 74)
    print("  OS PARES MAIS PARECIDOS (ΔE76 médio por pixel)")
    print("=" * 74)
    for distancia, a, b in pares[:8]:
        fonte_a, fonte_b = fichas[a][0], fichas[b][0]
        mesma = "  ← e a MESMA fonte" if fonte_a == fonte_b else ""
        print(f"  {distancia:6.2f}   {a}  ↔  {b}{mesma}")
    print()
    print(f"  ... e no outro extremo, {pares[-1][1]} ↔ {pares[-1][2]} com {pares[-1][0]:.2f}.")

    # A vizinhança de cada tema: com quem ele mais se confunde, e a que
    # distância. É a leitura que diz DE QUEM um tema precisa se afastar.
    print()
    print("=" * 74)
    print("  O VIZINHO MAIS PRÓXIMO DE CADA UM")
    print("=" * 74)
    for nome in TEMAS:
        vizinho = min(
            ((d, outro) for d, a, b in pares for outro in (a, b) if nome in (a, b) and outro != nome)
        )
        print(f"  {nome:<{largura_nome}}  {vizinho[0]:6.2f}  {vizinho[1]}")

    print()
    print("=" * 74)
    print("  Relatório, não veredito: este script não reprova nada.")
    print("=" * 74)
    print()
    janela.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
