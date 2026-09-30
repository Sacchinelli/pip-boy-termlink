"""Atalhos de teclado da janela principal — os locais e os globais.

Duas coisas bem diferentes moram aqui, e é por serem diferentes que elas
merecem um lugar só:

* **Locais** são ``QShortcut`` presos à janela: valem quando ela está em foco,
  e desaparecem com ela. Custam nada e não incomodam ninguém.
* **Globais** são registrados no SISTEMA pela biblioteca ``keyboard``: valem
  dentro do jogo, que é o ponto do programa, e por isso precisam ser desfeitos
  no encerramento. Também podem falhar — a biblioteca pode faltar, o registro
  pode ser recusado, e a tecla pode estar repetida no ``.env``.

Nenhum deles é um QShortcut a mais numa lista: um atalho global mal registrado
sequestra uma tecla do sistema inteiro. É por isso que **Esc e F12 nunca são
globais** — sequestrá-las quebraria o menu de pausa do jogo, o exato contexto
em que este programa é usado.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable, Iterable
from typing import Any

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget

from ..events import UiEvent, UiEventKind

LOGGER = logging.getLogger("pip_boy.interface.atalhos")

try:
    import keyboard
except ImportError:  # pragma: no cover - a biblioteca é opcional
    keyboard = None


def globais_disponiveis() -> bool:
    """A biblioteca de atalhos globais está instalada nesta máquina?"""
    return keyboard is not None


def resolver_globais(
    mapa: Iterable[tuple[str, UiEventKind]],
) -> tuple[list[tuple[str, UiEventKind]], list[str]]:
    """Separa o que dá para registrar do que está repetido. Sem teclado, sem Qt.

    Devolve ``(a_registrar, repetidas)``.

    A regra existe por causa de um defeito silencioso: a lista vinha de um
    DICIONÁRIO chaveado pela combinação, e duas ações configuradas com a mesma
    tecla no ``.env`` colapsavam numa só antes de qualquer código rodar. A
    segunda simplesmente não existia — sem erro, sem aviso — e a tecla fazia a
    coisa errada para sempre. Com pares, a repetição sobrevive até aqui, onde
    pode ser dita em voz alta.

    Combinação vazia é ausência de escolha, não repetição: quem esvazia a
    variável no ``.env`` está desligando aquele atalho.
    """
    a_registrar: list[tuple[str, UiEventKind]] = []
    repetidas: list[str] = []
    vistas: set[str] = set()
    for combinacao, tipo in mapa:
        if not combinacao:
            continue
        if combinacao in vistas:
            repetidas.append(combinacao)
            continue
        vistas.add(combinacao)
        a_registrar.append((combinacao, tipo))
    return a_registrar, repetidas


class Atalhos:
    """Instala e desfaz os atalhos de uma janela.

    ``avisar`` recebe as notícias que o jogador precisa ler no registro da
    conversa: atalho global indisponível, repetido, ou desligado por completo.
    Elas vão para a tela, e não só para o log, porque um atalho que não
    funciona é indistinguível de um atalho que o usuário digitou errado.
    """

    def __init__(
        self,
        janela: QWidget,
        *,
        locais: dict[str, Callable[[], None]],
        globais: Iterable[tuple[str, UiEventKind]],
        globais_ligados: bool,
        publicar: Callable[[UiEvent], None],
        avisar: Callable[[str], None],
    ) -> None:
        self._janela = janela
        self._locais = locais
        self._globais = list(globais)
        self._globais_ligados = globais_ligados
        self._publicar = publicar
        self._avisar = avisar
        self._registrados: list[Any] = []

    def instalar(self) -> None:
        for combinacao, acao in self._locais.items():
            QShortcut(QKeySequence(combinacao), self._janela, activated=acao)

        if keyboard is None or not self._globais_ligados:
            self._avisar(
                "Atalhos globais desativados; use F12/Esc com a janela em foco."
            )
            return

        a_registrar, repetidas = resolver_globais(self._globais)
        for combinacao in repetidas:
            self._avisar(
                f"Atalho global {combinacao} está repetido no .env; a segunda "
                "atribuição foi ignorada."
            )
        for combinacao, tipo in a_registrar:
            try:
                self._registrados.append(
                    keyboard.add_hotkey(
                        combinacao, lambda t=tipo: self._publicar(UiEvent(t))
                    )
                )
            except Exception as erro:
                # Uma linha no aviso, o traço inteiro só em debug. Fora do
                # Windows a biblioteca recusa TODA combinação (precisa de root
                # em Linux), e cada recusa vinha com quinze linhas de pilha
                # repetidas — três atalhos, três traços idênticos, para dizer o
                # que a razão em uma linha já diz. O traço continua disponível
                # para quem ligar o nível de depuração.
                razao = str(erro).strip() or type(erro).__name__
                LOGGER.warning("Não foi possível registrar %s: %s", combinacao, razao)
                LOGGER.debug("Recusa de %s em detalhe.", combinacao, exc_info=True)
                self._avisar(f"Atalho global {combinacao} indisponível.")

    def remover(self) -> None:
        """Devolve ao sistema as teclas que tomamos dele."""
        if keyboard is None:
            return
        for handle in self._registrados:
            with contextlib.suppress(Exception):
                keyboard.remove_hotkey(handle)
        self._registrados.clear()
