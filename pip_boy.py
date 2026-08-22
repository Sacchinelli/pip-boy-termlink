"""Lançador do Pip-Boy TermLink.

Mantido no lugar do arquivo original para que `py pip_boy.py` continue
funcionando. A aplicação em si vive no pacote `pipboy/`, na mesma pasta.

Este arquivo faz um diagnóstico explícito antes de importar qualquer coisa.
A versão anterior tratava todo ImportError como "falta um pacote do pip", o
que produzia uma mensagem enganosa quando o problema real era a estrutura de
pastas — justamente o erro mais comum ao baixar os arquivos soltos.
"""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
PACOTE = RAIZ / "pipboy"

# As mensagens de erro abaixo usam traços de caixa e acentos. Num console em
# cp1252 elas estourariam com UnicodeEncodeError, e o usuário veria um traço
# de pilha do Python no lugar da explicação que este arquivo existe para dar.
for _fluxo in (sys.stdout, sys.stderr):
    with contextlib.suppress(AttributeError, ValueError):
        # As stubs tipam sys.stdout como TextIO, que não declara reconfigure;
        # em runtime é TextIOWrapper, e o AttributeError está coberto acima.
        _fluxo.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

# Módulos que compõem o pacote. Se algum sumir, dizemos qual.
#
# Esta é a lista CANÔNICA: o diagnostico.py a importa daqui. Ele mantinha uma
# cópia própria que ficou para trás em cinco módulos (crash, deteccao,
# historico, revisao, sons) e por isso anunciava "tudo presente" numa instalação
# incompleta — exatamente a situação que ele existe para diagnosticar.
MODULOS = (
    "__init__", "audio", "config", "constants", "crash", "design", "deteccao",
    "dsp", "events", "historico", "profiles", "revisao", "session", "sons",
    "themes", "tools", "vocabulary",
)

# Nome do módulo importável -> nome do pacote no pip. Nem sempre coincidem.
DEPENDENCIAS = {
    "google.genai": "google-genai",
    "dotenv": "python-dotenv",
    "numpy": "numpy",
    "pyaudiowpatch": "PyAudioWPatch (Windows) ou pyaudio (Linux/macOS)",
    "pyaudio": "PyAudioWPatch (Windows) ou pyaudio (Linux/macOS)",
    "keyboard": "keyboard",
    "PySide6": "PySide6",
    "shiboken6": "PySide6",
}


def _erro(titulo: str, corpo: str) -> SystemExit:
    linha = "─" * 66
    return SystemExit(f"\n{linha}\n{titulo}\n{linha}\n{corpo}\n")


def _verificar_estrutura() -> None:
    """Confere se o pacote está no lugar antes de tentar importá-lo."""
    if not PACOTE.is_dir():
        vizinhos = sorted(p.name for p in RAIZ.iterdir() if p.suffix == ".py")
        soltos = [m for m in MODULOS if f"{m}.py" in vizinhos]
        detalhe = (
            "Encontrei os módulos soltos nesta pasta, fora do lugar:\n    "
            + ", ".join(f"{m}.py" for m in soltos)
            + "\n\nCrie uma subpasta chamada 'pipboy' e mova todos eles para dentro\n"
              "dela. O pip_boy.py fica FORA, na pasta de cima."
            if soltos
            else "Baixe o projeto completo novamente, preservando as pastas."
        )
        raise _erro(
            "ESTRUTURA DE PASTAS INCORRETA",
            f"Não existe a pasta do pacote:\n    {PACOTE}\n\n"
            f"'pipboy' NÃO é um pacote do pip — é a pasta do próprio projeto.\n"
            f"Nenhum 'pip install' resolve isto.\n\n{detalhe}\n\n"
            "Estrutura esperada:\n"
            "    pip_boy.py\n"
            "    requirements.txt\n"
            "    pipboy\\\n"
            "        __init__.py\n"
            "        audio.py\n"
            "        ... (demais módulos)",
        )

    faltando = [f"{m}.py" for m in MODULOS if not (PACOTE / f"{m}.py").is_file()]
    if faltando:
        presentes = sorted(p.name for p in PACOTE.glob("*.py"))
        raise _erro(
            "ARQUIVOS FALTANDO NO PACOTE",
            f"A pasta existe:\n    {PACOTE}\n\n"
            f"Mas faltam estes arquivos:\n    {', '.join(faltando)}\n\n"
            f"Presentes:\n    {', '.join(presentes) or '(nenhum)'}\n\n"
            "Atenção ao __init__.py: são DOIS underscores de cada lado, sem\n"
            "espaços. Alguns navegadores alteram esse nome ao baixar.",
        )


def _traduzir_import_error(error: ImportError) -> SystemExit:
    """Transforma o ImportError na instrução certa para o usuário."""
    nome = (getattr(error, "name", None) or "").split(".")[0]

    if nome in ("pipboy", "pip_boy"):
        return _erro(
            "O PACOTE 'pipboy' NÃO PÔDE SER CARREGADO",
            f"Os arquivos parecem estar em {PACOTE}, mas o Python não\n"
            f"conseguiu importá-los.\n\n"
            f"Detalhe técnico: {error}\n\n"
            "Causas comuns:\n"
            "  • Existe um arquivo 'pipboy.py' solto conflitando com a pasta.\n"
            "  • Há uma pasta __pycache__ antiga. Apague-a e tente de novo.\n"
            "  • O pip_boy.py foi movido para dentro da pasta pipboy\\.",
        )

    pacote_pip = DEPENDENCIAS.get(nome, nome or "uma dependência")
    return _erro(
        "DEPENDÊNCIA DO PYTHON AUSENTE",
        f"Falta o módulo: {nome or '(desconhecido)'}\n"
        f"Pacote a instalar: {pacote_pip}\n\n"
        f"Detalhe técnico: {error}\n\n"
        "Instale tudo de uma vez com:\n"
        "    py -m pip install -r requirements.txt\n\n"
        f"Python em uso: {sys.version.split()[0]} ({sys.executable})\n"
        "Se você criou um ambiente virtual (.venv), confirme que ele está\n"
        "ativado — instalar num Python e rodar em outro causa este erro.",
    )


def _sem_console() -> bool:
    """Não há para onde escrever: lançado pelo ``pythonw.exe`` ou já congelado.

    É o caso do atalho da área de trabalho, que usa o interpretador sem console
    para não abrir uma janela preta atrás da interface. O preço é este:
    ``sys.stderr`` vale ``None``, e toda a explicação que este arquivo existe
    para dar cairia no vazio.
    """
    return sys.platform == "win32" and getattr(sys, "stderr", None) is None


def _texto_de_caixa(mensagem: str) -> str:
    """A mesma mensagem, sem as réguas que só fazem sentido em monoespaçado.

    Na fonte proporcional de uma caixa do Windows elas viram um risco largo que
    estica o diálogo e não separa coisa nenhuma.
    """
    return "\n".join(linha for linha in mensagem.splitlines() if linha.strip("─ ")).strip()


def _avisar_sem_console(mensagem: str) -> None:
    """Mostra o erro numa caixa do Windows quando não há console para lê-lo.

    Sem isto, um duplo-clique no atalho de uma instalação quebrada não faria
    absolutamente nada — a pior mensagem de erro possível. Com console, esta
    função não faz nada: a mensagem já vai para o terminal, onde dá para
    copiar e colar, e uma caixa modal só atrapalharia.
    """
    if not _sem_console():
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            0, _texto_de_caixa(mensagem), "Pip-Boy TermLink", 0x10
        )
    except (OSError, AttributeError):  # pragma: no cover - depende do Windows
        pass


def main() -> int:
    # O linter marca esta checagem como "obsoleta" porque o projeto exige
    # 3.10+, mas ela existe exatamente para quem roda num Python mais velho.
    if sys.version_info < (3, 10):  # noqa: UP036
        raise _erro(
            "VERSÃO DO PYTHON MUITO ANTIGA",
            f"Este projeto precisa de Python 3.10 ou superior.\n"
            f"Você está usando {sys.version.split()[0]}.",
        )

    # No executável congelado o pacote vive dentro do próprio binário: não há
    # pasta para conferir, e a checagem reprovaria uma instalação correta.
    if not getattr(sys, "frozen", False):
        _verificar_estrutura()
        sys.path.insert(0, str(RAIZ))

    try:
        from pipboy import main as executar

        # A execução também precisa estar protegida: dependências como PySide6
        # e google-genai só são importadas quando main() roda, e um erro ali
        # escaparia de um try que cobrisse apenas a linha de import acima.
        return executar()
    except ImportError as error:
        raise _traduzir_import_error(error) from error


if __name__ == "__main__":
    # O contrato deste arquivo é que nenhuma falha do arranque termine em
    # silêncio. Sem console — o caso do atalho da área de trabalho — o silêncio
    # é justamente o padrão, e é aqui que ele é quebrado.
    try:
        _saida = main()
    except SystemExit as parada:
        if isinstance(parada.code, str):
            _avisar_sem_console(parada.code)
        raise
    except Exception as erro:
        _avisar_sem_console(
            "O programa não conseguiu abrir.\n\n"
            f"{type(erro).__name__}: {erro}\n\n"
            "Para ver o traço completo, rode 'py pip_boy.py' numa janela do "
            "PowerShell, na pasta do projeto."
        )
        raise
    raise SystemExit(_saida)
