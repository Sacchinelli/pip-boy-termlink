"""Verificação pré-publicação: nada de segredo nem de dado pessoal no repositório.

Uso:  py ferramentas/verificar_segredos.py

Roda antes de publicar e no CI a cada push. Sai com código 1 se encontrar
qualquer coisa que não deveria virar público.

A decisão de projeto que importa: este script inspeciona **o que o git
entregaria**, não a pasta. A diferença não é detalhe. O `.env` com a chave real
fica na raiz do projeto o tempo todo — é assim que o programa funciona — e um
verificador que varresse o disco apontaria para ele em toda execução, todo dia,
até alguém aprender a ignorar o aviso. Aí, no dia em que a regra de ignore
quebrasse de verdade, o alarme já não significaria mais nada.

Então a pergunta certa não é "existe um segredo nesta máquina?" (existe, e tem
que existir), e sim "existe um segredo entre os arquivos que o git vai
publicar?". As duas checagens abaixo respondem exatamente isso:

1. As regras de ignore ainda pegam os caminhos críticos? (o `.env`, a cópia
   dele em dist/, os artefatos de build)
2. Algum arquivo RASTREADO contém padrão de credencial ou caminho de máquina?
"""

from __future__ import annotations

import contextlib
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

for _fluxo in (sys.stdout, sys.stderr):
    with contextlib.suppress(AttributeError, ValueError):
        _fluxo.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

OK, FALHA = "  [ ok ]", "  [FALHA]"

# Caminhos que PRECISAM continuar ignorados. Se um deles passar a ser rastreado,
# a regra de ignore quebrou — e é exatamente esse o momento em que um
# verificador precisa gritar, porque nenhum outro sinal apareceria.
DEVEM_SER_IGNORADOS = (
    ".env",
    "dist/.env",
    "dist/PipBoyTermLink.exe",
    "build/pip_boy/EXE-00.toc",
    "preferencias.json",
    "vocabulario.sqlite3",
    "pipboy.log",
)

# Padrões de credencial. As chaves do Google têm formato fixo: 'AIza' seguido de
# exatamente 35 caracteres. O comprimento é o que separa uma chave real dos
# valores de teste da suíte ('AIzaTESTE1234567890', 19 caracteres) — sem ele, o
# verificador reprovaria os próprios testes e seria desligado na primeira semana.
PADROES: tuple[tuple[str, str], ...] = (
    (r"AIza[0-9A-Za-z_\-]{35}", "chave de API do Google (formato completo)"),
    (r"ya29\.[0-9A-Za-z_\-]{20,}", "token OAuth do Google"),
    (r"sk-[A-Za-z0-9]{32,}", "chave de API no formato OpenAI"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "chave privada"),
    (r"gh[pousr]_[A-Za-z0-9]{30,}", "token do GitHub"),
    (r"(?i)\bAKIA[0-9A-Z]{16}\b", "chave de acesso da AWS"),
)

# Caminhos absolutos de máquina. O PyInstaller os grava aos montes nos artefatos
# de build (nome de usuário, estrutura do OneDrive, versão do Python instalada),
# e eles só ficam fora do repositório porque build/ é ignorado. Se um vazar para
# um arquivo rastreado, é dado pessoal publicado sem que ninguém tenha decidido.
CAMINHOS_DE_MAQUINA: tuple[tuple[str, str], ...] = (
    (r"[A-Za-z]:\\Users\\(?!<|%|\$|seu_|usuario\b)[A-Za-z0-9_.\-]+", "caminho de usuário no Windows"),
    (r"/home/(?!<|\$|seu_|usuario\b)[a-z0-9_.\-]+/", "caminho de usuário no Linux"),
    (r"/Users/(?!<|\$|seu_|usuario\b)[A-Za-z0-9_.\-]+/", "caminho de usuário no macOS"),
)

# Extensões que não vale a pena abrir como texto.
BINARIAS = {".png", ".ico", ".exe", ".pyz", ".sqlite3", ".db", ".wav", ".zip", ".pdf"}

_problemas: list[str] = []


def falhar(msg: str) -> None:
    print(f"{FALHA} {msg}")
    _problemas.append(msg)


def _git(*args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(
            ["git", *args], cwd=RAIZ, capture_output=True, text=True, encoding="utf-8",
        )
    except (OSError, subprocess.SubprocessError) as erro:
        return 127, str(erro)
    return r.returncode, (r.stdout or "")


def checar_repositorio() -> bool:
    codigo, _ = _git("rev-parse", "--git-dir")
    if codigo != 0:
        falhar(
            "Isto não é um repositório git (ou o git não está no PATH).\n"
            "         → Rode 'git init' na raiz do projeto antes de publicar."
        )
        return False
    return True


def checar_ignorados() -> None:
    print("\n1. Regras de ignore")
    for caminho in DEVEM_SER_IGNORADOS:
        codigo, _ = _git("check-ignore", "-q", "--", caminho)
        if codigo == 0:
            print(f"{OK} ignorado: {caminho}")
        else:
            falhar(
                f"'{caminho}' NÃO está ignorado e pode ser publicado.\n"
                f"         → Confira a regra correspondente no .gitignore."
            )


def _arquivos_rastreados() -> list[Path]:
    """O que o git já rastreia mais o que ele adicionaria agora.

    Os dois conjuntos, porque um arquivo recém-criado ainda não está no índice
    mas seria publicado no próximo 'git add -A' — e é justamente o arquivo novo
    que costuma trazer o segredo colado sem querer.
    """
    nomes: set[str] = set()
    for args in (("ls-files",), ("ls-files", "--others", "--exclude-standard")):
        codigo, saida = _git(*args)
        if codigo == 0:
            nomes.update(linha.strip() for linha in saida.splitlines() if linha.strip())
    return [RAIZ / n for n in sorted(nomes)]


def checar_conteudo() -> None:
    print("\n2. Conteúdo dos arquivos publicáveis")
    arquivos = _arquivos_rastreados()
    if not arquivos:
        falhar("Nenhum arquivo rastreado encontrado — a verificação não provou nada.")
        return

    achados = 0
    for arquivo in arquivos:
        if arquivo.suffix.lower() in BINARIAS or not arquivo.is_file():
            continue
        try:
            texto = arquivo.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        relativo = arquivo.relative_to(RAIZ).as_posix()
        for padrao, descricao in (*PADROES, *CAMINHOS_DE_MAQUINA):
            for achado in re.finditer(padrao, texto):
                linha = texto.count("\n", 0, achado.start()) + 1
                # O valor encontrado NUNCA é impresso: um verificador que
                # despeja a chave no log do CI publica o que veio impedir.
                falhar(f"{relativo}:{linha} — {descricao}")
                achados += 1
    if achados == 0:
        print(f"{OK} {len(arquivos)} arquivos verificados, nenhum segredo ou caminho de máquina.")


def checar_exemplo() -> None:
    print("\n3. Modelo de configuração")
    exemplo = RAIZ / ".env.example"
    if not exemplo.is_file():
        falhar(".env.example não existe — quem clonar não saberá o que configurar.")
        return
    conteudo = exemplo.read_text(encoding="utf-8", errors="replace")
    if "GEMINI_API_KEY" not in conteudo:
        falhar(".env.example não menciona GEMINI_API_KEY.")
        return
    valor = ""
    for linha in conteudo.splitlines():
        if linha.strip().startswith("GEMINI_API_KEY"):
            valor = linha.split("=", 1)[-1].strip()
    if not valor.lower().startswith(("cole_", "sua_", "your_", "<")):
        falhar(
            ".env.example parece conter uma chave real em vez do texto de exemplo.\n"
            "         → O valor deve começar com 'cole_' ou 'sua_'."
        )
    else:
        print(f"{OK} .env.example traz apenas o texto de exemplo.")


def main() -> int:
    print("=" * 68)
    print("  VERIFICAÇÃO PRÉ-PUBLICAÇÃO — PIP-BOY TERMLINK")
    print("=" * 68)

    if checar_repositorio():
        checar_ignorados()
        checar_conteudo()
    checar_exemplo()

    print("\n" + "=" * 68)
    if _problemas:
        print(f"  {len(_problemas)} PROBLEMA(S) — NÃO PUBLIQUE ANTES DE RESOLVER")
        print("=" * 68)
        for i, p in enumerate(_problemas, 1):
            print(f"  {i}. {p}")
        print()
        return 1
    print("  NADA A VAZAR — o repositório pode ser publicado.")
    print("=" * 68 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
