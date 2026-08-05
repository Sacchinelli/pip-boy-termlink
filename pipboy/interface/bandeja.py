"""Ícone na bandeja do sistema: o aparelho ao alcance, mesmo escondido.

Quem usa o programa está com um jogo em primeiro plano. A bandeja dá as
quatro ações que importam sem sair do jogo nem caçar a janela: mostrar,
iniciar/encerrar a sessão, silenciar e sair. O menu é o nativo do sistema
de propósito — a bandeja é território do Windows, como a barra de tarefas,
e um menu temático flutuando ali leria como um corpo estranho.

Os rótulos se ajustam na abertura do menu (``aboutToShow``): "Iniciar
sessão" e "Encerrar sessão" são o mesmo item contado no momento certo.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .icone import criar_icone


def criar_bandeja(janela: Any) -> QSystemTrayIcon | None:
    """Instala o ícone e o menu. Devolve ``None`` onde não há bandeja."""
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return None

    bandeja = QSystemTrayIcon(criar_icone(), janela)
    bandeja.setToolTip("Pip-Boy TermLink")

    menu = QMenu()
    acao_mostrar = QAction("Mostrar janela", menu)
    acao_mostrar.triggered.connect(janela.sair_modo_compacto)
    menu.addAction(acao_mostrar)

    acao_compacto = QAction("Modo compacto", menu)
    acao_compacto.triggered.connect(janela.entrar_modo_compacto)
    menu.addAction(acao_compacto)
    menu.addSeparator()

    acao_sessao = QAction("Iniciar sessão", menu)
    acao_sessao.triggered.connect(janela.alternar_sessao)
    menu.addAction(acao_sessao)

    acao_mudo = QAction("Silenciar microfone", menu)
    acao_mudo.triggered.connect(janela.alternar_mudo)
    menu.addAction(acao_mudo)
    menu.addSeparator()

    acao_sair = QAction("Sair", menu)
    acao_sair.triggered.connect(janela.close)
    menu.addAction(acao_sair)

    def _ajustar_rotulos() -> None:
        ativa = janela.sessao_ativa
        acao_sessao.setText("Encerrar sessão" if ativa else "Iniciar sessão")
        acao_mudo.setEnabled(ativa)
        acao_mudo.setText("Reativar microfone" if janela.mudo else "Silenciar microfone")

    menu.aboutToShow.connect(_ajustar_rotulos)
    bandeja.setContextMenu(menu)
    # O menu é dono de nada no Qt — sem esta amarra ao ícone, o coletor o
    # levaria e o clique direito abriria o vazio.
    bandeja._menu = menu  # type: ignore[attr-defined]

    def _ativada(motivo: QSystemTrayIcon.ActivationReason) -> None:
        if motivo == QSystemTrayIcon.ActivationReason.DoubleClick:
            janela.sair_modo_compacto()

    bandeja.activated.connect(_ativada)
    bandeja.show()
    return bandeja
