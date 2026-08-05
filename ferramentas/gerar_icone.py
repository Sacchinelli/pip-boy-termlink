"""Gera o ``.ico`` do executável a partir do ícone desenhado por código.

Uso:  py ferramentas/gerar_icone.py

O repositório não guarda binário nenhum — o ``.ico`` é um artefato de build,
escrito em ``build/pipboy.ico`` e consumido pelo ``pip_boy.spec``. O desenho
vem de ``pipboy.interface.icone``, o mesmo usado pela janela em execução:
gerar aqui e desenhar lá nunca divergem porque são a mesma função.
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# Sem janela nenhuma: o backend offscreen basta para rasterizar pixmaps.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pipboy.interface.icone import TAMANHOS, pintar_icone  # noqa: E402


def _png(tamanho: int) -> bytes:
    mapa = pintar_icone(tamanho)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    mapa.save(buffer, "PNG")
    # QByteArray implementa o protocolo de buffer em runtime, mas as stubs do
    # PySide6 não o declaram — daí o mypy não achar sobrecarga de bytes() que
    # sirva. `.data()` devolve os bytes crus e é o caminho documentado.
    return bytes(buffer.data().data())


def gerar(destino: Path) -> None:
    """Escreve um ICO clássico: diretório + um PNG embutido por tamanho."""
    quadros = [(t, _png(t)) for t in TAMANHOS]
    destino.parent.mkdir(parents=True, exist_ok=True)

    with destino.open("wb") as arquivo:
        arquivo.write(struct.pack("<HHH", 0, 1, len(quadros)))
        deslocamento = 6 + 16 * len(quadros)
        for tamanho, dados in quadros:
            arquivo.write(
                struct.pack(
                    "<BBBBHHII",
                    tamanho % 256,  # 256 é registrado como 0, pela especificação
                    tamanho % 256,
                    0, 0, 1, 32,
                    len(dados),
                    deslocamento,
                )
            )
            deslocamento += len(dados)
        for _, dados in quadros:
            arquivo.write(dados)


if __name__ == "__main__":
    aplicacao = QApplication([])
    saida = RAIZ / "build" / "pipboy.ico"
    gerar(saida)
    print(f"Ícone gerado: {saida} ({saida.stat().st_size} bytes)")
