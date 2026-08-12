"""Diagnóstico do ambiente do Pip-Boy TermLink.

Verifica uma coisa de cada vez e diz exatamente o que está faltando, em vez de
parar no primeiro erro. Não precisa de chave de API nem de microfone.

Uso:  py diagnostico.py
"""

from __future__ import annotations

import contextlib
import importlib
import platform
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
OK, FALHA, AVISO = "  [ ok ]", "  [FALHA]", "  [aviso]"

# O cmd.exe abre em cp1252 quando a página de código do sistema é a legada, e
# uma seta no meio de uma correção derrubava este script com
# UnicodeEncodeError — no exato momento em que ele existe para explicar um
# problema. Nunca falhar por causa de um caractere.
for _fluxo in (sys.stdout, sys.stderr):
    with contextlib.suppress(AttributeError, ValueError):
        # As stubs tipam sys.stdout como TextIO, que não declara reconfigure;
        # em runtime é TextIOWrapper, e o AttributeError está coberto acima.
        _fluxo.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

_problemas: list[str] = []
_avisos: list[str] = []

# Uma biblioteca de áudio importável? A checagem de dispositivos depende disso e
# decidia procurando a substring "audio" dentro das mensagens de problema já
# acumuladas — um teste sobre o TEXTO de outra checagem, que qualquer reescrita
# de frase (ou um problema alheio que mencionasse áudio) inverteria em silêncio.
# Um booleano diz a mesma coisa sem depender de redação.
_audio_ok = False


def secao(titulo: str) -> None:
    print(f"\n{titulo}\n{'-' * len(titulo)}")


def falhar(msg: str, correcao: str) -> None:
    print(f"{FALHA} {msg}")
    _problemas.append(f"{msg}\n         → {correcao}")


def avisar(msg: str, nota: str) -> None:
    print(f"{AVISO} {msg}")
    _avisos.append(f"{msg}\n         → {nota}")


def checar_python() -> None:
    secao("1. Interpretador")
    versao = sys.version_info
    print(f"  Versão .... {platform.python_version()}")
    print(f"  Executável. {sys.executable}")
    print(f"  Sistema ... {platform.system()} {platform.release()}")

    if versao < (3, 10):
        falhar(
            f"Python {platform.python_version()} é antigo demais.",
            "Instale o Python 3.12 ou 3.13.",
        )
    elif versao >= (3, 14):
        avisar(
            f"Python {platform.python_version()} é muito recente.",
            "Bibliotecas de áudio compiladas demoram a publicar binários para "
            "versões novas. Se algo abaixo falhar por falta de wheel, o caminho "
            "mais rápido é usar Python 3.12 ou 3.13.",
        )
    else:
        print(f"{OK} Versão adequada.")

    em_venv = sys.prefix != sys.base_prefix
    print(f"{OK if em_venv else AVISO} Ambiente virtual: {'sim' if em_venv else 'não'}")
    if not em_venv:
        avisar(
            "Você não está num ambiente virtual.",
            "Não é obrigatório, mas instalar num Python e executar em outro é a "
            "causa mais comum de 'dependência ausente' depois de instalar tudo.",
        )


def _modulos_esperados() -> tuple[str, ...]:
    """A lista canônica, importada do lançador em vez de copiada.

    A cópia local ficara cinco módulos para trás — sem crash, deteccao,
    historico, revisao nem sons —, então uma instalação à qual faltasse
    justamente um deles recebia deste script um "os 12 módulos estão presentes"
    e quebrava logo depois. Duas listas para a mesma verdade só permanecem
    iguais por sorte.
    """
    sys.path.insert(0, str(RAIZ))
    try:
        from pip_boy import MODULOS
    except Exception:
        return ()
    return tuple(MODULOS)


def checar_estrutura() -> None:
    secao("2. Arquivos do projeto")
    pacote = RAIZ / "pipboy"
    modulos = _modulos_esperados()
    if not modulos:
        avisar(
            "Não foi possível ler a lista de módulos de pip_boy.py.",
            "O arquivo deve ficar ao lado deste. A checagem de módulos foi pulada.",
        )

    if not pacote.is_dir():
        falhar(
            "A pasta 'pipboy' não existe.",
            "Ela não vem do pip — é a pasta do projeto. Deve ficar ao lado deste arquivo.",
        )
        return

    ausentes = [f"{m}.py" for m in modulos if not (pacote / f"{m}.py").is_file()]
    if ausentes:
        falhar(f"Faltam módulos: {', '.join(ausentes)}", "Baixe o projeto novamente.")
    elif modulos:
        print(f"{OK} Os {len(modulos)} módulos estão presentes.")

    if (RAIZ / ".env").is_file():
        print(f"{OK} Arquivo .env encontrado.")
        chave = ""
        for linha in (RAIZ / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
            if linha.strip().startswith("GEMINI_API_KEY"):
                chave = linha.split("=", 1)[-1].strip()
        if not chave:
            falhar("GEMINI_API_KEY não está definida no .env.", "Adicione a linha com sua chave.")
        elif chave.lower().startswith(("cole_", "sua_", "your_")):
            falhar("O .env ainda tem o valor de exemplo.", "Substitua pela chave real.")
        else:
            mascara = f"{chave[:4]}…{chave[-4:]}" if len(chave) > 8 else "****"
            print(f"{OK} Chave presente ({mascara}, {len(chave)} caracteres).")
    else:
        falhar("Arquivo .env não encontrado.", "Crie-o com a linha GEMINI_API_KEY=sua_chave.")

    # Só o bytecode do NOSSO código interessa. Um rglob cru desce para dentro
    # do .venv e do build/, onde cada dependência traz os próprios caches: com
    # o PySide6 instalado o aviso saltava de 4 para 262 pastas, sugerindo uma
    # bagunça que não existe e escondendo o caso real que ele deve pegar —
    # bytecode de um módulo que você renomeou ou moveu.
    IGNORADAS = {".venv", "venv", "env", "ENV", "build", "dist", ".git"}
    caches = [
        c for c in RAIZ.rglob("__pycache__")
        if not IGNORADAS.intersection(c.relative_to(RAIZ).parts)
    ]
    if caches:
        # O conselho sai da MESMA lista que a contagem, e não de um comando
        # escrito à mão. O anterior era um -Recurse na raiz: depois do filtro
        # acima ele apagava 262 pastas enquanto o aviso falava de 4, incluindo
        # as do .venv que a contagem ignora de propósito. Repetir as exclusões
        # em PowerShell resolveria o número e criaria uma segunda lista para
        # manter — que envelheceria na primeira pasta nova.
        alvos = " ".join(f'"{c.relative_to(RAIZ)}"' for c in sorted(caches))
        avisar(
            f"{len(caches)} pasta(s) __pycache__ com bytecode antigo.",
            f"Apague-as se você reorganizou arquivos: Remove-Item -Recurse -Force {alvos}",
        )

    perdido = pacote / "test_nucleo.py"
    if perdido.is_file():
        avisar(
            "test_nucleo.py está dentro de pipboy\\.",
            "Ele pertence a tests\\. Não quebra nada, mas não faz parte do pacote.",
        )


def checar_dependencias() -> None:
    secao("3. Dependências")
    # (módulo importável, pacote no pip, obrigatório, observação)
    itens = [
        ("numpy", "numpy", True, "Processamento de áudio."),
        ("dotenv", "python-dotenv", True, "Leitura do .env."),
        ("google.genai", "google-genai", True, "Cliente da Live API."),
        ("PySide6", "PySide6", True, "Interface gráfica."),
        ("keyboard", "keyboard", False, "Atalhos globais. Sem ele, use F12/Esc com a janela em foco."),
    ]

    for modulo, pacote_pip, obrigatorio, nota in itens:
        try:
            mod = importlib.import_module(modulo)
        except Exception as error:
            (falhar if obrigatorio else avisar)(
                f"{modulo}: {type(error).__name__} — {error}",
                f"py -m pip install {pacote_pip}",
            )
            continue
        versao = getattr(mod, "__version__", "") or ""
        print(f"{OK} {modulo:14} {versao:10} {nota}")

    # Áudio: um dos dois serve, mas só o fork tem loopback.
    global _audio_ok
    motor = None
    for nome in ("pyaudiowpatch", "pyaudio"):
        try:
            importlib.import_module(nome)
            motor = nome
            break
        except Exception:
            continue
    _audio_ok = motor is not None

    if motor == "pyaudiowpatch":
        print(f"{OK} pyaudiowpatch             Áudio + captura do jogo (loopback).")
    elif motor == "pyaudio":
        print(f"{OK} pyaudio                   Áudio básico.")
        avisar(
            "Você tem pyaudio, não PyAudioWPatch.",
            "Funciona, mas sem 'Ouvir o jogo'. Para ter o recurso: "
            "py -m pip install PyAudioWPatch",
        )
    else:
        falhar(
            "Nenhuma biblioteca de áudio instalada.",
            "Windows: py -m pip install PyAudioWPatch | "
            "Linux/macOS: py -m pip install pyaudio",
        )


def checar_dispositivos() -> None:
    secao("4. Dispositivos de áudio")
    if not _audio_ok:
        print("  Pulado: resolva a instalação da biblioteca de áudio primeiro.")
        return
    try:
        sys.path.insert(0, str(RAIZ))
        from pipboy.audio import HAS_LOOPBACK_SUPPORT, list_devices
    except Exception as error:
        falhar(f"Não foi possível carregar o módulo de áudio: {error}", "Resolva os itens acima.")
        return

    try:
        entradas, saidas, loopback = list_devices()
    except Exception as error:
        falhar(f"Falha ao listar dispositivos: {error}", "Verifique os drivers de áudio.")
        return

    if entradas:
        print(f"{OK} {len(entradas)} entrada(s). Padrão provável: {entradas[0].name}")
    else:
        falhar(
            "Nenhum microfone detectado.",
            "Configurações → Privacidade → Microfone, e confira se está conectado.",
        )

    if saidas:
        print(f"{OK} {len(saidas)} saída(s). Padrão provável: {saidas[0].name}")
    else:
        falhar("Nenhuma saída de áudio detectada.", "Verifique alto-falantes ou fones.")

    if loopback is not None:
        print(f"{OK} Loopback disponível: {loopback.name}")
    elif HAS_LOOPBACK_SUPPORT:
        avisar("Loopback WASAPI não encontrado.", "'Ouvir o jogo' ficará desabilitado.")
    else:
        avisar("Sem suporte a loopback nesta plataforma.", "Recurso disponível apenas no Windows.")


def checar_fontes() -> None:
    """Que fonte cada tema realmente consegue NESTA máquina.

    A cadeia de ``font_candidates`` é uma intenção, não uma garantia: Garamond,
    Rockwell e Bookman Old Style não acompanham o Windows, e antes disto quatro
    temas desabavam calados em Georgia e três em Bahnschrift. Uma colisão não
    quebra nada — por isso ninguém percebe —, apenas apaga a identidade que a
    fonte deveria carregar. Como o resultado depende do que está instalado, isto
    é um relatório de máquina, e não um teste que possa reprovar em toda parte.
    """
    secao("5. Tipografia dos temas")
    try:
        sys.path.insert(0, str(RAIZ))
        from PySide6.QtGui import QFontDatabase
        from PySide6.QtWidgets import QApplication

        from pipboy.themes import TEMAS
    except Exception as error:
        avisar(f"Não foi possível inspecionar fontes: {error}", "Resolva os itens acima.")
        return

    QApplication.instance() or QApplication([])
    instaladas = set(QFontDatabase.families())
    if not instaladas:
        avisar("O Qt não listou nenhuma fonte.", "Ambiente sem servidor gráfico?")
        return

    resolvidas: dict[str, list[str]] = {}
    for nome, tema in TEMAS.items():
        alvo = tema.font_candidates[0]
        obtida = next(
            (f for f in tema.font_candidates if f in instaladas), tema.font_candidates[-1]
        )
        resolvidas.setdefault(obtida, []).append(nome)
        nota = "" if obtida == alvo else f"  (queria {alvo})"
        print(f"  {nome:24} {obtida}{nota}")

    colisoes = {f: t for f, t in resolvidas.items() if len(t) > 1}
    if colisoes:
        for fonte, temas in colisoes.items():
            avisar(
                f"{len(temas)} temas dividem '{fonte}': {', '.join(temas)}.",
                "Instale a fonte preferida, ou dê a um deles outra reserva em themes.py.",
            )
    else:
        print(f"{OK} Os {len(TEMAS)} temas usam {len(resolvidas)} fontes distintas.")


def main() -> int:
    print("=" * 68)
    print("  DIAGNÓSTICO — PIP-BOY TERMLINK")
    print("=" * 68)

    checar_python()
    checar_estrutura()
    checar_dependencias()
    checar_dispositivos()
    checar_fontes()

    print("\n" + "=" * 68)
    if _problemas:
        print(f"  {len(_problemas)} PROBLEMA(S) QUE IMPEDEM A EXECUÇÃO")
        print("=" * 68)
        for i, p in enumerate(_problemas, 1):
            print(f"  {i}. {p}")
    else:
        print("  TUDO PRONTO — execute:  py pip_boy.py")
        print("=" * 68)

    if _avisos:
        print(f"\n  {len(_avisos)} aviso(s) — não impedem a execução:")
        for i, a in enumerate(_avisos, 1):
            print(f"  {i}. {a}")

    print()
    return 1 if _problemas else 0


if __name__ == "__main__":
    raise SystemExit(main())
