"""Rede de segurança: exceção não tratada vira registro e aviso, não um sumiço.

Sem isto, um erro imprevisto num slot do Qt imprime um traço de pilha num
console que o jogador não está olhando — ou que nem existe, no executável — e
a janela some sem explicação. O contrato deste módulo é que **nenhuma falha
termina em silêncio**: o traço completo vai para o ``pipboy.log`` e o jogador
vê um aviso, na caixa temática se a interface estiver de pé, na caixa nativa
se for justamente a interface que caiu.

Duas decisões de desenho:

* **O programa continua rodando.** Um erro num canto da interface não justifica
  derrubar uma sessão de tutoria no meio de uma frase. Registrar, avisar e
  seguir é o comportamento de um aparelho; morrer é o de um script.
* **Cada erro avisa uma vez.** O mesmo defeito disparado por um timer de
  animação a 30 quadros por segundo produziria uma tempestade de caixas
  modais. A primeira aparição avisa; as repetições só registram.
"""

from __future__ import annotations

import logging
import sys
import threading
from types import TracebackType
from typing import Any

LOGGER = logging.getLogger("pip_boy.crash")

# Janela principal registrada pelo arranque — é dela que vêm tema, fonte e
# paleta da caixa de aviso. Antes de existir (ou depois de morrer), o aviso
# recua para a caixa nativa.
_janela: Any = None

# Guarda de reentrância: um erro DENTRO do próprio aviso não pode abrir outro.
_avisando = False

# Assinaturas já mostradas ao jogador nesta execução.
_ja_avisados: set[str] = set()


def registrar_janela(janela: Any) -> None:
    """Informa qual janela fornece o tema da caixa de aviso."""
    global _janela
    _janela = janela


def _assinatura(tipo: type[BaseException], valor: BaseException) -> str:
    return f"{tipo.__qualname__}: {valor}"


def _mensagem_para_o_jogador(valor: BaseException) -> str:
    detalhe = str(valor).strip() or type(valor).__qualname__
    if len(detalhe) > 220:
        detalhe = detalhe[:217] + "…"
    return (
        "Aconteceu um erro que o programa não previu. Ele vai continuar "
        "funcionando, mas se algo ficar estranho, reinicie.\n\n"
        f"Detalhe técnico: {detalhe}\n\n"
        "O registro completo está no pipboy.log — inclua esse arquivo se for "
        "relatar o problema."
    )


def _avisar_jogador(tipo: type[BaseException], valor: BaseException) -> None:
    global _avisando
    if _avisando:
        return
    assinatura = _assinatura(tipo, valor)
    if assinatura in _ja_avisados:
        return
    _ja_avisados.add(assinatura)

    _avisando = True
    try:
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is None:
            return  # Sem laço de eventos não há como mostrar caixa nenhuma.

        titulo = "Erro inesperado"
        mensagem = _mensagem_para_o_jogador(valor)
        try:
            # A caixa temática exige uma janela viva com tema carregado.
            from .interface.dialogo import avisar

            if _janela is None:
                raise RuntimeError("sem janela registrada")
            avisar(_janela, titulo, mensagem, erro=True)
        except Exception:
            # A interface pode ser exatamente o que quebrou: caixa nativa.
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.critical(None, titulo, mensagem)
    except Exception:  # pragma: no cover - último recurso: nunca re-levantar
        LOGGER.exception("Falha ao exibir o aviso de erro.")
    finally:
        _avisando = False


def _hook_principal(
    tipo: type[BaseException],
    valor: BaseException,
    rastro: TracebackType | None,
) -> None:
    if issubclass(tipo, KeyboardInterrupt):
        # Ctrl+C no console é um pedido do usuário, não um defeito.
        sys.__excepthook__(tipo, valor, rastro)
        return
    LOGGER.critical("Exceção não tratada.", exc_info=(tipo, valor, rastro))
    _avisar_jogador(tipo, valor)


def _hook_thread(args: threading.ExceptHookArgs) -> None:
    if args.exc_type is SystemExit:
        return  # Encerramento deliberado de uma thread não é notícia.
    # exc_value pode vir None no protocolo do threading; o log aceita a tupla
    # completa ou nada — nunca uma tupla pela metade.
    info = (
        (args.exc_type, args.exc_value, args.exc_traceback)
        if args.exc_value is not None
        else None
    )
    LOGGER.critical(
        "Exceção não tratada na thread %s.",
        args.thread.name if args.thread else "?",
        exc_info=info,
    )
    # O aviso é agendado na thread do Qt: widget criado fora dela é indefinido.
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication

        valor = args.exc_value
        if QApplication.instance() is not None and valor is not None:
            tipo = args.exc_type
            QTimer.singleShot(0, lambda: _avisar_jogador(tipo, valor))
    except Exception:  # pragma: no cover
        pass


def instalar() -> None:
    """Instala os capturadores. Chamar uma vez, logo após configurar o log."""
    sys.excepthook = _hook_principal
    threading.excepthook = _hook_thread
