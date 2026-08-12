"""Verifica que todo símbolo desenhado pela interface aparece — nenhum vira caixinha.

Uso:  py ferramentas/verificar_glifos.py

O README avisa duas vezes sobre esta armadilha, e as duas vezes porque ela já
mordeu: o "✕" saía como um tracinho vertical irreconhecível em Consolas e
Georgia, e emoji são desenhados pelo Windows sempre coloridos, com fonte
própria, ignorando a paleta do tema. A regra que nasceu daí é usar só o bloco
*Geometric Shapes* e as setas básicas, que toda fonte de texto do Windows
possui. Este script é o que faz a regra valer sozinha.

**Por que não é um teste da suíte.** A suíte de interface roda em
``QT_QPA_PLATFORM=offscreen``, e nesse backend o Qt enxerga ZERO famílias de
fonte — ela desenha a janela inteira em caixinhas e passa, feliz. Ou seja: o
único defeito que esta verificação existe para pegar é exatamente o que aquela
suíte é estruturalmente incapaz de ver. Aqui a plataforma é a padrão, com a
base de fontes real do sistema.

**O que ele examina.** Não uma lista de símbolos escrita à mão, que
envelheceria no primeiro glifo novo — mas o CÓDIGO: todo literal de texto de
``pipboy/`` é lido com o ``ast``, e dele saem os caracteres da categoria
*Symbol* do Unicode. É o recorte exato do problema: ele pega ◷, ×, ▶, ↻ e os
emoji, e deixa passar acento, travessão e reticências, que são prosa.

Docstrings ficam de fora. Elas são texto para quem lê o código, não para a
tela, e a seta de "novas → aprendendo → dominadas" numa explicação não
justifica exigir a seta de nenhuma fonte.

**O que ele garante.** A medição é ``QFontMetrics.inFont``, e ela responde a
pergunta do usuário: este caractere vai aparecer? O Qt substitui a fonte por
caractere na hora de pintar, e o ``inFont`` conta essa substituição — a ponto
de responder que sim para um ideograma chinês perguntado a uma fonte latina de
38 KB. Reprovar aqui significa, então, que NENHUMA fonte do sistema tem o
glifo: caixinha na certa, em qualquer máquina. Foi assim que o ``＋`` fullwidth
foi pego, e é uma garantia forte, que vale ter no CI.

**O que ele NÃO garante** é que o glifo esteja na fonte que o tema escolheu.
Boa parte dos símbolos é emprestada de outra família pelo Windows e sai
desenhada fora da tipografia do tema — 26 dos 35, hoje. Quem responde essa
outra pergunta é ``ferramentas/cobertura_de_glifos.py``, lendo a tabela ``cmap``
dos arquivos, onde não há empréstimo possível.

O projeto **depende** do socorro do sistema para símbolos. Sempre dependeu,
desde antes de existir qualquer verificação, e funciona. Uma versão anterior
desta docstring afirmava o oposto — que a exigência era o símbolo existir na
fonte do tema, e que "depender do socorro do sistema é o mesmo que não ter
regra". Era uma garantia que este script nunca deu, e acreditar nela é pior
que não tê-la: some a diferença entre "aparece" e "aparece certo".
"""

from __future__ import annotations

import ast
import contextlib
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

for _fluxo in (sys.stdout, sys.stderr):
    with contextlib.suppress(AttributeError, ValueError):
        _fluxo.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

# Símbolos que o programa desenha sem que apareçam como literal em pipboy/:
# o teclado numérico do jogador não entra aqui, mas a moeda do rodapé vem do
# .env e o padrão é este.
EXTRAS = ("$",)


def _docstrings(arvore: ast.AST) -> set[int]:
    """Identidade dos nós que são docstring, para o varredor pulá-los."""
    alvos: set[int] = set()
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        corpo = getattr(no, "body", None)
        if not corpo:
            continue
        primeiro = corpo[0]
        if (
            isinstance(primeiro, ast.Expr)
            and isinstance(primeiro.value, ast.Constant)
            and isinstance(primeiro.value.value, str)
        ):
            alvos.add(id(primeiro.value))
    return alvos


def simbolos_no_codigo() -> dict[str, list[str]]:
    """Todo caractere da categoria *Symbol* nos literais de ``pipboy/``.

    Devolve ``{caractere: [arquivo:linha, …]}`` — a origem viaja junto porque
    um alarme sem endereço obriga quem o recebe a caçar o glifo no código.
    """
    achados: dict[str, list[str]] = {}
    for arquivo in sorted((RAIZ / "pipboy").rglob("*.py")):
        try:
            arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
        except (OSError, SyntaxError) as erro:
            print(f"  aviso: {arquivo.name} não pôde ser lido ({erro})")
            continue
        ignorar = _docstrings(arvore)
        for no in ast.walk(arvore):
            if not isinstance(no, ast.Constant) or not isinstance(no.value, str):
                continue
            if id(no) in ignorar:
                continue
            for caractere in no.value:
                if unicodedata.category(caractere).startswith("S"):
                    origem = f"{arquivo.relative_to(RAIZ).as_posix()}:{no.lineno}"
                    achados.setdefault(caractere, [])
                    if origem not in achados[caractere]:
                        achados[caractere].append(origem)
    for caractere in EXTRAS:
        achados.setdefault(caractere, ["(padrão do rodapé)"])
    return achados


def _nome(caractere: str) -> str:
    try:
        descricao = unicodedata.name(caractere)
    except ValueError:  # pragma: no cover - só para caracteres sem nome
        descricao = "sem nome"
    return f"{caractere}  U+{ord(caractere):04X} {descricao}"


def main() -> int:
    print("=" * 68)
    print("  VERIFICAÇÃO DE GLIFOS — PIP-BOY TERMLINK")
    print("=" * 68)

    from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics
    from PySide6.QtWidgets import QApplication

    QApplication(sys.argv)
    instaladas = {str(f) for f in QFontDatabase.families()}
    if not instaladas:
        # Acontece em backends sem base de fontes — o offscreen é um deles.
        # Não saber medir não é o mesmo que encontrar defeito: o script avisa
        # e sai limpo, em vez de reprovar um código que pode estar correto.
        print("\n  Nenhuma família de fonte visível nesta plataforma Qt.")
        print("  A verificação precisa da base de fontes do sistema; nada foi medido.")
        print("  (Não rode com QT_QPA_PLATFORM=offscreen.)")
        print("=" * 68 + "\n")
        return 0

    from pipboy.interface.janela import FONTES_MONO
    from pipboy.themes import TEMAS

    def primeira(candidatas: tuple[str, ...]) -> str:
        return next((c for c in candidatas if c in instaladas), candidatas[-1])

    # Toda fonte que o programa pode acabar usando para desenhar texto. O
    # dicionário guarda quem pediu cada uma, para o relatório dizer qual tema
    # quebra — a mesma família costuma servir a vários.
    familias: dict[str, list[str]] = {}
    for nome, tema in TEMAS.items():
        for papel, candidatas in (
            ("controles", tema.ui_font_candidates),
            ("tema", tema.font_candidates),
        ):
            familias.setdefault(primeira(candidatas), []).append(f"{nome}/{papel}")
    familias.setdefault(primeira(FONTES_MONO), []).append("rodapé/mono")

    simbolos = simbolos_no_codigo()
    print(f"\n  {len(simbolos)} símbolo(s) no código, {len(familias)} família(s) em uso.\n")

    problemas: list[str] = []
    for caractere, origens in sorted(simbolos.items()):
        ausentes = [
            familia
            for familia in sorted(familias)
            if not QFontMetrics(QFont(familia, 10)).inFont(caractere)
        ]
        if ausentes:
            problemas.append(
                f"{_nome(caractere)}\n"
                f"      ausente em: {', '.join(ausentes)}\n"
                f"      usado por:  {', '.join(sorted({t for f in ausentes for t in familias[f]}))}\n"
                f"      no código:  {', '.join(origens[:4])}"
            )
        else:
            print(f"  [ ok ] {_nome(caractere)}")

    print("\n" + "=" * 68)
    if problemas:
        print(f"  {len(problemas)} SÍMBOLO(S) SEM GLIFO — VÃO APARECER COMO CAIXINHA")
        print("=" * 68)
        for i, p in enumerate(problemas, 1):
            print(f"  {i}. {p}")
        print(
            "\n  Troque por um do bloco Geometric Shapes (U+25A0–25FF) ou por uma\n"
            "  seta básica, que toda fonte de texto do Windows possui.\n"
        )
        return 1
    print("  TODO SÍMBOLO APARECE — nenhum vira caixinha em nenhum tema.")
    print("=" * 68)
    print("  (Parte deles é emprestada de outra família pelo Windows, e sai fora")
    print("   da tipografia do tema. Quanto: py ferramentas/cobertura_de_glifos.py)")
    print("=" * 68 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
