"""Pip-Boy TermLink — tutor de inglês por voz para jogos.

Projeto não oficial, sem afiliação com os estúdios dos jogos citados nem com
o Google.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Fonte única da versão: o pyproject.toml declara a mesma string, e o teste do
# núcleo confere que as duas não voltem a divergir.
__version__ = "3.0.0"

LOGGER = logging.getLogger("pip_boy")


def configure_logging(directory: Path) -> None:
    """Log rotativo em arquivo, sem sequestrar stdout/stderr da aplicação."""
    if LOGGER.handlers:
        return

    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(threadName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        handler = RotatingFileHandler(
            directory / "pipboy.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(formatter)
        LOGGER.addHandler(handler)
    except OSError:
        pass  # Sem permissão de escrita: o console ainda recebe os eventos.

    if not getattr(sys, "frozen", False):
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        LOGGER.addHandler(console)


def _identidade_no_windows(slug: str) -> None:
    """Dá ao processo uma identidade própria na barra de tarefas do Windows.

    Sem isto o Windows não vê "o Pip-Boy TermLink": vê "uma janela do
    python.exe". Ele agrupa o botão da barra de tarefas sob o interpretador
    e desenha o ícone DELE — o logotipo azul e amarelo do Python — por mais
    que a aplicação Qt declare o seu com ``setWindowIcon``. O ícone da
    janela e o da barra de tarefas vêm de lugares diferentes, e só este
    identificador (AppUserModelID) manda no segundo.

    Precisa ser chamado ANTES de a primeira janela existir. No executável
    congelado o problema não aparece — lá o processo já é o nosso —, mas a
    chamada é inofensiva e mantém o mesmo agrupamento nos dois modos.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            f"sacchinelli.{slug}"
        )
    except (OSError, AttributeError):  # pragma: no cover - depende do Windows
        LOGGER.debug("AppUserModelID indisponível.", exc_info=True)


def main() -> int:
    """Ponto de entrada da aplicação."""
    from .config import (
        AppConfiguration,
        ConfigurationError,
        application_directory,
        data_directory,
    )
    from .constants import APP_NAME, APP_SLUG

    base = application_directory()
    configure_logging(data_directory())

    # Antes de qualquer janela: é o que faz a barra de tarefas mostrar o
    # nosso ícone em vez do ícone do Python que nos lançou.
    _identidade_no_windows(APP_SLUG)

    # Rede de segurança: daqui em diante, nenhuma exceção termina em silêncio.
    from . import crash

    crash.instalar()

    # A aplicação Qt é criada ANTES de qualquer coisa que possa falhar, porque
    # a caixa de erro também é um widget: sem ela, uma chave ausente
    # terminaria o programa em silêncio, sem janela nenhuma.
    from PySide6.QtWidgets import QApplication, QMessageBox

    # instance() devolve o tipo básico do Qt; o isinstance devolve ao mypy a
    # certeza de que temos uma QApplication de widgets, com ícone e tudo.
    instancia = QApplication.instance()
    aplicacao = instancia if isinstance(instancia, QApplication) else QApplication(sys.argv)
    aplicacao.setApplicationName(APP_NAME)
    try:
        from .interface.icone import criar_icone

        aplicacao.setWindowIcon(criar_icone())
    except Exception:
        LOGGER.debug("Ícone indisponível.", exc_info=True)

    # A abertura cobre o segundo de carga com o tema do último jogo usado.
    # Se falhar por qualquer motivo, o arranque segue sem ela: é enfeite.
    abertura = None
    try:
        from .interface.abertura import criar_abertura

        abertura = criar_abertura()
        abertura.show()
        aplicacao.processEvents()
    except Exception:
        LOGGER.debug("Abertura indisponível.", exc_info=True)

    def falhar(mensagem: str) -> None:
        # A ÚNICA caixa nativa que resta, e de propósito: aqui ainda não
        # há janela, tema escolhido nem sequer garantia de que a camada
        # de interface tenha importado — é exatamente o que este ramo
        # trata. Uma caixa temática dependeria justamente do que falhou.
        LOGGER.error(mensagem)
        QMessageBox.critical(None, APP_NAME, mensagem)

    try:
        configuration = AppConfiguration.load(base)
    except ConfigurationError as erro:
        # Sem chave não é um defeito — é a primeira execução. O cartão de
        # boas-vindas explica, recebe a colagem e grava; só se ele falhar (ou
        # o usuário desistir) é que a mensagem de erro clássica aparece.
        if abertura is not None:
            abertura.close()
        try:
            from .interface.boas_vindas import pedir_chave

            if not pedir_chave():
                return 0  # desistir na primeira tela é uma saída, não um erro
        except Exception:
            LOGGER.exception("Cartão de boas-vindas indisponível.")
            falhar(str(erro))
            return 2
        try:
            configuration = AppConfiguration.load(base)
        except ConfigurationError as segundo_erro:  # pragma: no cover
            falhar(str(segundo_erro))
            return 2

    try:
        from .interface import Janela
    except ImportError as erro:  # pragma: no cover
        falhar(
            f"Dependência ausente: {erro.name or 'desconhecida'}.\n\n"
            "Instale as dependências com:\n    py -m pip install -r requirements.txt"
        )
        return 3

    janela = Janela(configuration)
    crash.registrar_janela(janela)  # A caixa de erro passa a vestir o tema.
    janela.show()
    if abertura is not None:
        abertura.finish(janela)
    return int(aplicacao.exec())
