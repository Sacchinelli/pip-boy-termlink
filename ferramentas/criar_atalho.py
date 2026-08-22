"""Cria o atalho do Pip-Boy TermLink na área de trabalho.

Uso:  py ferramentas/criar_atalho.py

Um programa que só abre digitando ``py pip_boy.py`` num terminal não é um
aplicativo — é um script. Este arquivo fecha essa distância sem compilar nada:
escreve um atalho do Windows (``.lnk``) apontando para o Python do projeto,
com o ícone desenhado pelo próprio programa e a pasta de trabalho certa.

**Por que um atalho, e não o ``.exe``.** O ``pip_boy.spec`` continua valendo, e
é o caminho para entregar o programa a quem não tem Python. Só que num Windows
11 com o **Smart App Control** ligado — padrão em instalação limpa — o binário
recém-compilado é recusado pelo sistema por não ter assinatura nem reputação
(o README explica o diagnóstico e as saídas). O atalho não esbarra nessa
política, porque quem executa é o Python já instalado na máquina, e não um
binário novo. É também o modo em que o projeto é desenvolvido: o atalho e a
linha de comando lançam exatamente o mesmo código.

**Por que ``pythonw.exe`` e não ``python.exe``.** O primeiro é o interpretador
sem console. Com o segundo, todo duplo-clique abre uma janela preta atrás da
interface, que ocupa a barra de tarefas como se fosse um segundo programa e
derruba o Pip-Boy junto se alguém a fechar. Em troca, o ``pythonw`` deixa o
``sys.stderr`` valendo ``None``: erro nenhum tem para onde ir. Por isso o
``pip_boy.py`` mostra uma caixa do Windows quando percebe que não há console —
sem ela, um duplo-clique numa instalação quebrada não faria absolutamente
nada, que é a pior mensagem de erro possível.

**Por que a área de trabalho não é ``%USERPROFILE%\\Desktop``.** Com o OneDrive
sincronizando a pasta — comum, e muitas vezes ligado sem que ninguém escolha —
a área de trabalho de verdade fica em ``OneDrive\\Área de Trabalho``, com
acento e no idioma do Windows. Montar esse caminho à mão cria o atalho numa
pasta fantasma que o usuário nunca vê. Quem sabe onde ela está é o shell, e é
a ele que perguntamos.

**O ícone é gerado antes, e isso não é só cosmético.** Rodar o
``gerar_icone.py`` com o mesmo Python que vai lançar o programa é a prova de
que aquele ambiente importa o PySide6 e desenha. Se falhar, o atalho não é
criado: um ícone bonito que não abre nada é pior do que atalho nenhum.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from pipboy.constants import APP_NAME  # noqa: E402

for _fluxo in (sys.stdout, sys.stderr):
    with contextlib.suppress(AttributeError, ValueError):
        _fluxo.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

OK, FALHA = "  [ ok ]", "  [FALHA]"

LANCADOR = RAIZ / "pip_boy.py"
GERADOR = RAIZ / "ferramentas" / "gerar_icone.py"
ICONE = RAIZ / "build" / "pipboy.ico"
DESCRICAO = "Tutor de inglês por voz, em tempo real, para quem joga em inglês."

# CSIDL_DESKTOPDIRECTORY: a pasta de ARQUIVOS da área de trabalho, e não o
# "Desktop" virtual do shell (0x0000), que também contém Este Computador e a
# Lixeira e não é lugar onde se escreva arquivo.
_CSIDL_DESKTOPDIRECTORY = 0x0010

# Os valores viajam por variáveis de ambiente, e não interpolados no script:
# um caminho com aspas ou acento não tem como virar comando, e o PowerShell os
# recebe já em UTF-16, sem passar por página de código nenhuma.
_ESCREVER_ATALHO = """\
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$atalho = $shell.CreateShortcut($env:PIPBOY_LNK)
$atalho.TargetPath = $env:PIPBOY_ALVO
$atalho.Arguments = '"' + $env:PIPBOY_SCRIPT + '"'
$atalho.WorkingDirectory = $env:PIPBOY_DIR
$atalho.IconLocation = $env:PIPBOY_ICONE + ',0'
$atalho.Description = $env:PIPBOY_DESC
$atalho.Save()
"""


def _erro(titulo: str, corpo: str) -> SystemExit:
    linha = "─" * 68
    return SystemExit(f"\n{FALHA} {titulo}\n{linha}\n{corpo}\n")


def _ambiente() -> tuple[Path, Path]:
    """Devolve (``python.exe``, ``pythonw.exe``) do ambiente que roda o programa.

    O ``.venv`` do projeto vem primeiro de propósito: é onde as dependências
    foram instaladas segundo o README. Um atalho apontado para o Python global
    funcionaria nesta máquina por acidente — porque as bibliotecas também estão
    lá — e falharia na próxima, onde ninguém saberia por quê.
    """
    for pasta in (RAIZ / ".venv" / "Scripts", Path(sys.executable).resolve().parent):
        console, janela = pasta / "python.exe", pasta / "pythonw.exe"
        if console.is_file() and janela.is_file():
            return console, janela

    raise _erro(
        "NÃO ENCONTREI UM PYTHON PARA O ATALHO APONTAR",
        "Procurei o par python.exe/pythonw.exe em:\n"
        f"    {RAIZ / '.venv' / 'Scripts'}\n"
        f"    {Path(sys.executable).resolve().parent}\n\n"
        "Crie o ambiente do projeto e instale as dependências:\n"
        "    py -m venv .venv\n"
        "    .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt",
    )


def _desenhar_icone(python: Path) -> None:
    """Redesenha o ``.ico`` — e prova que este Python consegue abrir o programa."""
    processo = subprocess.run(
        [str(python), str(GERADOR)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(RAIZ),
    )
    if processo.returncode == 0 and ICONE.is_file():
        return

    detalhe = (processo.stderr or processo.stdout or "").strip()
    raise _erro(
        "O PYTHON DO ATALHO NÃO CONSEGUE ABRIR O PROGRAMA",
        "Ele não desenhou o ícone, e quem não desenha o ícone não desenha a\n"
        "janela. Nenhum atalho foi criado.\n\n"
        f"Python: {python}\n\n"
        f"Detalhe técnico:\n{detalhe or '(sem saída)'}\n\n"
        "Quase sempre é dependência faltando NESTE ambiente:\n"
        f"    {python} -m pip install -r requirements.txt\n\n"
        "Para um diagnóstico completo:  py diagnostico.py",
    )


def _area_de_trabalho() -> Path:
    """Pergunta ao shell onde fica a área de trabalho deste usuário."""
    buffer = ctypes.create_unicode_buffer(260)
    with contextlib.suppress(OSError, AttributeError):
        codigo = ctypes.windll.shell32.SHGetFolderPathW(
            None, _CSIDL_DESKTOPDIRECTORY, None, 0, buffer
        )
        if codigo == 0 and buffer.value:
            return Path(buffer.value)
    return Path.home() / "Desktop"


def _escrever_atalho(destino: Path, alvo: Path) -> None:
    """Cria o ``.lnk`` pelo COM do shell, que é quem sabe escrever esse formato."""
    ambiente = dict(
        os.environ,
        PIPBOY_LNK=str(destino),
        PIPBOY_ALVO=str(alvo),
        PIPBOY_SCRIPT=str(LANCADOR),
        PIPBOY_DIR=str(RAIZ),
        PIPBOY_ICONE=str(ICONE),
        PIPBOY_DESC=DESCRICAO,
    )
    # utf-8-sig: sem BOM, o PowerShell 5.1 lê o arquivo na página de código do
    # sistema, e um acento que apareça aqui um dia vira lixo silencioso.
    with tempfile.NamedTemporaryFile(
        "w", suffix=".ps1", encoding="utf-8-sig", delete=False
    ) as arquivo:
        arquivo.write(_ESCREVER_ATALHO)
        script = Path(arquivo.name)

    try:
        processo = subprocess.run(
            # -ExecutionPolicy Bypass: a política padrão recusa scripts, e é a
            # mesma pedra que o README avisa na ativação do ambiente.
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=ambiente,
        )
    finally:
        script.unlink(missing_ok=True)

    if processo.returncode != 0:
        raise _erro(
            "O WINDOWS RECUSOU CRIAR O ATALHO",
            f"Destino: {destino}\n\n"
            f"Detalhe técnico:\n{(processo.stderr or processo.stdout or '').strip()}",
        )


def main() -> int:
    print("=" * 70)
    print("  ATALHO NA ÁREA DE TRABALHO — PIP-BOY TERMLINK")
    print("=" * 70)

    if sys.platform != "win32":
        raise _erro(
            "ATALHO É COISA DO WINDOWS",
            "O formato .lnk não existe em Linux nem no macOS. Lá o equivalente\n"
            "é um arquivo .desktop ou um .app, e o programa continua abrindo\n"
            "por 'py pip_boy.py'.",
        )

    if not LANCADOR.is_file():
        raise _erro(
            "LANÇADOR NÃO ENCONTRADO",
            f"Esperava o arquivo:\n    {LANCADOR}\n\n"
            "Rode esta ferramenta de dentro do projeto, sem tirá-la da pasta.",
        )

    console, janela = _ambiente()
    print(f"{OK} Python do atalho: {janela}")

    _desenhar_icone(console)
    print(f"{OK} Ícone desenhado:  {ICONE}")

    mesa = _area_de_trabalho()
    if not mesa.is_dir():
        raise _erro(
            "NÃO ACHEI A ÁREA DE TRABALHO",
            f"O caminho devolvido pelo Windows não existe:\n    {mesa}",
        )

    destino = mesa / f"{APP_NAME}.lnk"
    existia = destino.exists()
    _escrever_atalho(destino, janela)

    print(f"{OK} Atalho {'atualizado' if existia else 'criado'}:  {destino}")
    print("\n" + "=" * 70)
    print("  PRONTO — o Pip-Boy TermLink abre com um duplo-clique.")
    print("=" * 70)
    print(
        "\n  Para tê-lo também na barra de tarefas, ARRASTE o atalho até ela:\n"
        "  arrastar fixa este atalho, enquanto fixar pela janela já aberta\n"
        "  guarda o pythonw.exe sozinho — que, sem argumento nenhum, não abre\n"
        "  coisa alguma.\n"
        "\n  O atalho aponta para esta pasta do projeto. Mudar o projeto de\n"
        "  lugar pede rodar esta ferramenta de novo.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
