"""A campainha: quem toca os blips sintetizados de ``pipboy/sons.py``.

Separada da síntese pelo mesmo corte de sempre — lá números, aqui Qt. Os
WAVs vivem em cache na pasta de dados e são regenerados por tema na
primeira vez; o ``QSoundEffect`` os carrega uma vez e toca sem latência.

O silêncio é respeitado duas vezes: atmosfera *Desligada* silencia os blips
(a preferência de calma vale para o ouvido), e qualquer falha de áudio —
máquina sem dispositivo, backend ausente no CI — degrada para o mudo sem
derrubar nada. Som de interface é enfeite; enfeite não quebra aparelho.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QUrl

from ..config import data_directory
from ..sons import gerar_cache

LOGGER = logging.getLogger("pip_boy.campainha")

VOLUME = 0.5  # do QSoundEffect; a amplitude do WAV já nasce contida


class Campainha:
    """Quatro efeitos carregados, trocados junto com o tema."""

    def __init__(self, janela: Any) -> None:
        self._janela = janela
        self._efeitos: dict[str, Any] = {}
        self._caminhos: dict[str, Any] = {}
        self._disponivel = True

    def aplicar_tema(self) -> None:
        """Sintetiza (se preciso) os blips do tema e anota onde estão.

        Nenhum ``QSoundEffect`` nasce aqui: eles são criados no primeiro
        toque. Além de tirar o custo do arranque, isso mantém o QtMultimedia
        fora de qualquer execução que nunca toca som — como a suíte de
        interface offscreen, onde um efeito vivo derruba o teardown.
        """
        if not self._disponivel:
            return
        try:
            self._caminhos = gerar_cache(
                data_directory() / "sons", self._janela.tema.name
            )
            for evento, efeito in self._efeitos.items():
                efeito.setSource(QUrl.fromLocalFile(str(self._caminhos[evento])))
        except Exception:
            self._disponivel = False
            self._efeitos.clear()
            LOGGER.debug("Campainha indisponível.", exc_info=True)

    def encerrar(self) -> None:
        """Solta os efeitos ANTES do teardown do Qt.

        Um ``QSoundEffect`` vivo durante a destruição da aplicação derruba o
        processo na saída (0xC000041D) — depois de todo o resto ter dado
        certo. A campainha morre junto com a janela, explicitamente.
        """
        self._disponivel = False
        for efeito in self._efeitos.values():
            efeito.stop()
            efeito.deleteLater()
        self._efeitos.clear()

    def tocar(self, evento: str) -> None:
        if not self._disponivel or evento not in self._caminhos:
            return
        if self._janela.intensidade_atmosfera <= 0.0:
            return  # atmosfera desligada silencia também o ouvido
        try:
            efeito = self._efeitos.get(evento)
            if efeito is None:
                from PySide6.QtMultimedia import QSoundEffect

                efeito = QSoundEffect(self._janela)
                efeito.setVolume(VOLUME)
                efeito.setSource(QUrl.fromLocalFile(str(self._caminhos[evento])))
                self._efeitos[evento] = efeito
            efeito.play()
        except Exception:  # pragma: no cover - backend de áudio instável
            self._disponivel = False
