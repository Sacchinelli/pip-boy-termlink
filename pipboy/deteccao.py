"""Detecção do jogo em execução: o aparelho se veste sozinho.

O seletor de jogo define aparência, contexto linguístico e persona — e o
jogador esquece de trocá-lo. Este módulo olha a lista de processos do
Windows de tempos em tempos e reconhece os executáveis dos jogos que o
programa já veste. A interface decide o que fazer com a resposta (trocar o
ambiente, avisar, ignorar); aqui só se responde a pergunta "que jogo
conhecido está rodando?".

A consulta usa o ``tasklist`` do próprio Windows: sem dependência nova, sem
privilégio especial e sem abrir handle de processo alheio — só se lê a
mesma lista que o Gerenciador de Tarefas mostra. Fora do Windows a resposta
é sempre "nenhum", e o recurso simplesmente não existe.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from collections.abc import Iterable

# Executável (minúsculo) -> nome do tema em themes.py. A tabela cobre os
# lançadores mais comuns de cada título; acrescentar um jogo é uma linha.
JOGOS_CONHECIDOS: dict[str, str] = {
    "fallout3.exe": "Fallout",
    "falloutnv.exe": "Fallout",
    "fallout4.exe": "Fallout",
    "fallout76.exe": "Fallout",
    "eldenring.exe": "Elden Ring",
    "nightreign.exe": "Elden Ring",
    "skyrimse.exe": "Skyrim",
    "skyrim.exe": "Skyrim",
    "tesv.exe": "Skyrim",
    "witcher3.exe": "The Witcher 3",
    "rdr2.exe": "Red Dead",
    "rdr.exe": "Red Dead",
    "gta5.exe": "GTA",
    "gta5_enhanced.exe": "GTA",
    "gtav.exe": "GTA",
    "cyberpunk2077.exe": "Cyberpunk 2077",
}


def jogo_entre(processos: Iterable[str]) -> str | None:
    """O tema do primeiro jogo conhecido na lista, ou ``None``.

    A comparação ignora maiúsculas — o Windows preserva a caixa do arquivo,
    e "Fallout4.exe" e "fallout4.exe" são o mesmo jogo.
    """
    for nome in processos:
        tema = JOGOS_CONHECIDOS.get(nome.strip().lower())
        if tema is not None:
            return tema
    return None


def processos_em_execucao() -> set[str]:
    """Nomes de executáveis em execução, em minúsculas. Vazio fora do Windows.

    Qualquer falha — tasklist ausente, saída truncada, timeout — devolve o
    conjunto vazio: detecção é conveniência, e conveniência não derruba nada.
    """
    if sys.platform != "win32":
        return set()
    try:
        resultado = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if resultado.returncode != 0:
        return set()

    nomes: set[str] = set()
    for linha in csv.reader(resultado.stdout.splitlines()):
        if linha:
            nomes.add(linha[0].strip().lower())
    return nomes


def jogo_em_execucao() -> str | None:
    """Atalho: o tema do jogo rodando agora, ou ``None``."""
    return jogo_entre(processos_em_execucao())
