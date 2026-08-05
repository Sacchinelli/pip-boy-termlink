"""Camada de apresentação em Qt.

Nada aqui é importado pelo núcleo. ``session``, ``audio``, ``vocabulary``,
``tools``, ``profiles`` e ``config`` não sabem que esta pasta existe — é por
isso que a troca de biblioteca gráfica custou só reescrever a apresentação.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..config import AppConfiguration
    from .janela import Janela as Janela

__all__ = ["Janela", "executar"]


def __getattr__(nome: str) -> Any:
    """Import preguiçoso (PEP 562): ``Janela`` só carrega quando pedida.

    A tela de abertura importa deste pacote; se o ``__init__`` puxasse a
    janela no topo, a carga pesada aconteceria antes de a abertura aparecer
    e ela perderia a única função que tem.
    """
    if nome == "Janela":
        from .janela import Janela

        return Janela
    raise AttributeError(f"module {__name__!r} has no attribute {nome!r}")


def executar(configuration: AppConfiguration) -> int:
    """Abre a janela e roda o laço de eventos. Devolve o código de saída."""
    from PySide6.QtWidgets import QApplication

    from .janela import Janela

    aplicacao = QApplication.instance() or QApplication([])
    janela = Janela(configuration)
    janela.show()
    return int(aplicacao.exec())
