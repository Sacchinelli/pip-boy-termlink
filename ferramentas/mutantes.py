"""Testes de mutação: planta um defeito de cada vez e confere se a suíte pega.

Uma suíte verde diz que o código faz o que os testes perguntam — não que os
testes perguntam o que importa. O jeito de saber é quebrar de propósito: tirar
a linha que monta a moldura, trocar a nota "difícil" por "acerto", esquecer de
guardar a preferência. Se a suíte continua verde com o defeito dentro, o teste
daquilo não existe, por mais que o nome dele diga que sim.

Uso::

    python ferramentas/mutantes.py especificacao.py [--paralelo N] [--sem-base]

A especificação é um arquivo Python com uma lista ``MUTANTES`` de tuplas::

    MUTANTES = [
        # (nome, arquivo a partir da raiz, trecho original, trecho mutado, suíte)
        ("revisão não monta a moldura", "pipboy/interface/revisao.py",
         "        self.moldura_cartao.montar()\\n", "", "interface"),
    ]

A suíte é ``"nucleo"`` ou ``"interface"``. O trecho original precisa aparecer
UMA vez no arquivo: se sumiu, o código mudou e o mutante apodreceu; se aparece
duas, não se sabe qual quebrar. Os dois casos são relatados, e nenhum roda.

Cada mutante roda numa CÓPIA do projeto, num diretório temporário — a árvore
de trabalho nunca é tocada. Isso resolve dois problemas do jeito antigo
(mudar o arquivo, rodar, restaurar): um Ctrl+C no meio não deixa mais um
defeito plantado no código de verdade, e dá para continuar editando enquanto
os mutantes rodam. E, cada um na sua cópia, eles rodam ao mesmo tempo.

Antes dos mutantes, as suítes rodam uma vez SEM defeito nenhum (a "base"):
um mutante "pego" por um teste que já falhava não prova nada. Base vermelha
interrompe tudo.

A cópia deixa de fora o que a suíte não lê e o que não deve viajar: o
``.git``, o ambiente virtual, as pastas de build — e todo arquivo oculto da
raiz, a começar pelo ``.env`` com a chave da API, que nenhum teste usa (o CI
roda sem ele) e que não tem por que ser duplicado em pasta temporária.

Sai com código 1 se algum mutante escapou, se algum trecho não foi achado ou
se a base estava vermelha.
"""

from __future__ import annotations

import argparse
import io
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SUITES = {"nucleo": "tests/test_nucleo.py", "interface": "tests/test_interface.py"}
# O que a cópia não leva: pesado, gerado, ou que não deve sair do lugar.
FORA_DA_COPIA = {".git", ".venv", "build", "dist", "__pycache__", ".mypy_cache", ".ruff_cache"}
# Quanto tempo uma suíte pode levar antes de ser dada como travada. A de
# interface leva minutos nesta máquina; com várias ao mesmo tempo, mais.
LIMITE_S = 3600


@dataclass(frozen=True, slots=True)
class Mutante:
    nome: str
    arquivo: str
    original: str
    mutado: str
    suite: str


@dataclass(frozen=True, slots=True)
class Resultado:
    nome: str
    falhas: tuple[str, ...]
    erro: str = ""

    @property
    def pego(self) -> bool:
        return bool(self.falhas)


def ler_especificacao(caminho: Path) -> list[Mutante]:
    """Os mutantes da especificação, na ordem em que foram escritos."""
    brutos = runpy.run_path(str(caminho)).get("MUTANTES")
    if not isinstance(brutos, list):
        raise SystemExit(f"{caminho}: falta a lista MUTANTES")
    mutantes = []
    for item in brutos:
        if not (isinstance(item, tuple) and len(item) == 5 and all(isinstance(p, str) for p in item)):
            raise SystemExit(f"{caminho}: mutante mal formado: {item!r}")
        mutante = Mutante(*item)
        if mutante.suite not in SUITES:
            raise SystemExit(f"{caminho}: suíte desconhecida em {mutante.nome!r}: {mutante.suite}")
        mutantes.append(mutante)
    return mutantes


def problemas(mutantes: Sequence[Mutante], raiz: Path = RAIZ) -> list[str]:
    """Os mutantes que não dá para plantar: trecho sumido ou repetido."""
    achados = []
    for mutante in mutantes:
        alvo = raiz / mutante.arquivo
        if not alvo.is_file():
            achados.append(f"{mutante.nome}: o arquivo {mutante.arquivo} não existe")
            continue
        vezes = alvo.read_text(encoding="utf-8").count(mutante.original)
        if vezes != 1:
            motivo = "sumiu — o código mudou" if vezes == 0 else f"aparece {vezes} vezes"
            achados.append(f"{mutante.nome}: o trecho original {motivo}")
    return achados


def fora_da_copia(raiz: Path, pasta: Path, nomes: list[str]) -> set[str]:
    """O que ``copiar_projeto`` pula dentro de ``pasta``."""
    na_raiz = pasta.resolve() == raiz.resolve()
    return {
        n for n in nomes
        if n in FORA_DA_COPIA or n.endswith(".pyc") or (na_raiz and n.startswith("."))
    }


def copiar_projeto(raiz: Path, destino: Path) -> Path:
    """Uma cópia do projeto em ``destino``, sem o que a suíte não precisa."""
    copia = destino / "projeto"
    shutil.copytree(
        raiz, copia, ignore=lambda pasta, nomes: fora_da_copia(raiz, Path(pasta), nomes)
    )
    return copia


def falhas_da_saida(texto: str, suite: str) -> tuple[str, ...]:
    """As linhas que dizem que a suíte reprovou alguma coisa.

    Na de interface, um traço de pilha também conta: uma exceção dentro de um
    slot do Qt é impressa e engolida, e o teste seguinte pode passar por cima
    dela. Na do núcleo, não: ali há testes que conferem justamente o registro
    de um erro, e o traço dele sai no meio da saída de propósito.
    """
    return tuple(
        linha.strip() for linha in texto.splitlines()
        if "FALHA" in linha or linha.lstrip().startswith("ERRO ")
        or (suite == "interface" and linha.startswith("Traceback"))
    )


def rodar_suite(projeto: Path, suite: str) -> tuple[int, str]:
    ambiente = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"}
    processo = subprocess.run(
        [sys.executable, SUITES[suite]], cwd=projeto, capture_output=True,
        encoding="utf-8", errors="replace", timeout=LIMITE_S, env=ambiente,
    )
    return processo.returncode, processo.stdout + processo.stderr


def rodar_mutante(mutante: Mutante, raiz: Path = RAIZ) -> Resultado:
    """Planta o defeito numa cópia do projeto, roda a suíte e joga a cópia fora."""
    with tempfile.TemporaryDirectory(prefix="pipboy-mutante-") as pasta:
        projeto = copiar_projeto(raiz, Path(pasta))
        alvo = projeto / mutante.arquivo
        texto = alvo.read_text(encoding="utf-8")
        alvo.write_text(texto.replace(mutante.original, mutante.mutado), encoding="utf-8", newline="")
        try:
            codigo, saida = rodar_suite(projeto, mutante.suite)
        except subprocess.TimeoutExpired:
            return Resultado(mutante.nome, (), erro="a suíte passou do tempo")
    falhas = falhas_da_saida(saida, mutante.suite)
    if not falhas and codigo != 0:
        falhas = (f"a suíte saiu com código {codigo}",)
    return Resultado(mutante.nome, falhas)


def checagens_da_saida(texto: str) -> int:
    """Quantas checagens a suíte aprovou (as linhas "  ok")."""
    return sum(1 for linha in texto.splitlines() if linha.startswith("  ok"))


def rodar_base(suites: set[str], raiz: Path = RAIZ) -> list[str]:
    """As suítes sem defeito nenhum; devolve o que já estava vermelho.

    Verde, cada suíte diz quantas checagens aprovou — o número que dá a
    medida do que os mutantes a seguir estão pondo à prova.
    """
    vermelhas = []
    with tempfile.TemporaryDirectory(prefix="pipboy-base-") as pasta:
        projeto = copiar_projeto(raiz, Path(pasta))
        with ThreadPoolExecutor(max_workers=len(suites) or 1) as executor:
            corridas = {suite: executor.submit(rodar_suite, projeto, suite) for suite in sorted(suites)}
        for suite, corrida in corridas.items():
            codigo, saida = corrida.result()
            falhas = falhas_da_saida(saida, suite)
            if codigo != 0 or falhas:
                vermelhas.append(f"{suite}: {(falhas or (f'código {codigo}',))[0]}")
            else:
                print(_ascii(f"[base] {suite}: verde, {checagens_da_saida(saida)} checagens"), flush=True)
    return vermelhas


def _ascii(texto: str) -> str:
    """O console do Windows nem sempre fala UTF-8; o relatório não pode morrer por um acento."""
    codificacao = sys.stdout.encoding or "utf-8"
    return texto.encode(codificacao, "replace").decode(codificacao)


def main(argv: Sequence[str] | None = None) -> int:
    # Por um cano (o CI, um arquivo de log), a saída sai em UTF-8: o relatório
    # é todo acentuado, e a página de código do Windows o estragaria.
    if isinstance(sys.stdout, io.TextIOWrapper) and not sys.stdout.isatty():
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("especificacao", type=Path)
    parser.add_argument("--paralelo", type=int, default=max(1, min(4, (os.cpu_count() or 2) // 2)))
    parser.add_argument("--sem-base", action="store_true", help="pular a rodada sem defeito")
    parser.add_argument("--raiz", type=Path, default=RAIZ, help="o projeto a copiar (padrão: este)")
    args = parser.parse_args(argv)
    raiz: Path = args.raiz.resolve()

    mutantes = ler_especificacao(args.especificacao)
    # Uma foto do projeto, tirada agora: cada mutante copia DELA, e não da
    # árvore de trabalho. Sem isso, o mutante que começa dez minutos depois
    # levaria junto o que foi editado nesses dez minutos — e a rodada
    # testaria um código que já não é o que foi pedido.
    with tempfile.TemporaryDirectory(prefix="pipboy-foto-") as pasta_foto:
        foto = copiar_projeto(raiz, Path(pasta_foto))
        return _rodar(mutantes, foto, args.paralelo, base=not args.sem_base)


def _rodar(mutantes: list[Mutante], foto: Path, paralelo: int, *, base: bool) -> int:
    invalidos = problemas(mutantes, foto)
    for linha in invalidos:
        print(_ascii(f"[INVÁLIDO] {linha}"), flush=True)
    validos = [m for m in mutantes if not any(linha.startswith(m.nome + ":") for linha in invalidos)]

    if base:
        vermelhas = rodar_base({m.suite for m in validos}, foto)
        for linha in vermelhas:
            print(_ascii(f"[BASE VERMELHA] {linha}"), flush=True)
        if vermelhas:
            return 1

    escaparam = 0
    with ThreadPoolExecutor(max_workers=max(1, paralelo)) as executor:
        for resultado in executor.map(lambda m: rodar_mutante(m, foto), validos):
            if resultado.erro:
                escaparam += 1
                print(_ascii(f"[ERRO] {resultado.nome}: {resultado.erro}"), flush=True)
            elif resultado.pego:
                print(_ascii(f"[pego] {resultado.nome} — {len(resultado.falhas)} falha(s)"), flush=True)
                print(_ascii(f"         {resultado.falhas[0][:150]}"), flush=True)
            else:
                escaparam += 1
                print(_ascii(f"[ESCAPOU] {resultado.nome}"), flush=True)
    pegos = len(validos) - escaparam
    print(_ascii(f"\n{pegos} de {len(validos)} mutante(s) pego(s)"
                 + (f", {len(invalidos)} inválido(s)" if invalidos else "") + "."))
    return 1 if escaparam or invalidos else 0


if __name__ == "__main__":
    raise SystemExit(main())
