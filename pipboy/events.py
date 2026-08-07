"""Mensagens trocadas entre a thread de sessão e a thread da interface.

Nenhum widget do Qt atravessa esta fronteira. A thread de sessão só publica
``UiEvent`` numa ``queue.Queue``, o que elimina a classe inteira de bugs de
concorrência gráfica.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class UiEventKind(str, Enum):
    LOG = "log"
    STATUS = "status"
    VOCAB_ADDED = "vocab_added"
    USAGE = "usage"
    SESSION_FINISHED = "session_finished"
    START_REQUEST = "start_request"
    STOP_REQUEST = "stop_request"
    TOGGLE_MUTE_REQUEST = "toggle_mute_request"
    TOGGLE_GAME_AUDIO_REQUEST = "toggle_game_audio_request"
    # A sonda de processos roda numa thread própria e publica aqui o jogo
    # reconhecido (text = nome do tema; vazio = nenhum jogo conhecido).
    GAME_DETECTED = "game_detected"
    # A sessão desistiu da busca na web para conseguir conectar. O chip
    # precisa saber: marcado enquanto a sessão roda sem busca, ele mente.
    WEB_SEARCH_DISABLED = "web_search_disabled"


class Tag(str, Enum):
    """Categorias visuais do registro."""

    SISTEMA = "sistema"
    USUARIO = "usuario"
    ASSISTENTE = "assistente"
    ERRO = "erro"
    VOCAB = "vocab"


@dataclass(frozen=True, slots=True)
class UiEvent:
    kind: UiEventKind
    text: str = ""
    # Quem falou, separado do que foi dito. A sessão antes entregava
    # "PIP-BOY: bom dia" numa string só, e a interface não tinha como saber
    # onde terminava o nome — o que impedia qualquer apresentação que não
    # fosse uma linha corrida de log.
    author: str = ""
    # Papel de cor (ver themes.ROLE_*), nunca um hexadecimal: só a interface
    # sabe qual tema está ativo no momento em que o evento é consumido.
    color_role: str = ""
    tag: Tag = Tag.ASSISTENTE
    session_id: int = 0
    payload: Any = None
