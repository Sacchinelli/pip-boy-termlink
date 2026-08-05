# -*- mode: python ; coding: utf-8 -*-
"""Receita do executável.  Uso:  py -m PyInstaller pip_boy.spec

Antes do build, gere o ícone:  py ferramentas/gerar_icone.py
O resultado fica em dist/PipBoyTermLink.exe — um arquivo único, sem instalador.

O ``.env`` NUNCA é embutido: segredo não entra em binário distribuível. O
executável procura o ``.env`` ao lado de si mesmo (e na pasta de dados), como
``config.py`` já documenta.
"""

import os

# `datas=[]` garante que o .env não entra DENTRO do binário. Não garante o que
# importa na prática: que ele não esteja ao LADO dele. Como o executável procura
# o .env na própria pasta, um arquivo esquecido em dist/ viaja junto no primeiro
# zip que alguém mandar para um amigo — e a chave vai junto. O build para aqui
# em vez de produzir um pacote que vaza.
# SPECPATH é injetado pelo PyInstaller e aponta para a pasta deste arquivo;
# ancorar nele em vez de no diretório de trabalho faz a guarda valer mesmo
# quando o build é disparado de outro lugar.
_raiz = globals().get("SPECPATH") or os.path.abspath(".")
_env_no_dist = os.path.join(_raiz, "dist", ".env")
if os.path.isfile(_env_no_dist):
    raise SystemExit(
        f"\nBUILD INTERROMPIDO: existe um .env na pasta de distribuição.\n\n"
        f"    {_env_no_dist}\n\n"
        "Ele contém a sua chave da API e seria distribuído junto do executável,\n"
        "porque o programa procura o .env ao lado de si mesmo. Apague-o e refaça\n"
        "o build; a sua cópia de trabalho na raiz do projeto não é afetada.\n"
    )

a = Analysis(
    ["pip_boy.py"],
    pathex=[],
    binaries=[],
    datas=[],
    # O loopback WASAPI é carregado dinamicamente conforme a plataforma; o
    # tkinter não é usado desde a migração para o Qt e só engordaria o pacote.
    # QtNetwork fica: o QtMultimedia (campainha de blips) depende dele.
    hiddenimports=["pyaudiowpatch"],
    excludes=["tkinter", "PySide6.QtQml", "PySide6.QtQuick"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PipBoyTermLink",
    icon="build/pipboy.ico",
    console=False,  # aplicativo de janela: nada de console preto atrás
    disable_windowed_traceback=False,
    upx=False,
    strip=False,
)
