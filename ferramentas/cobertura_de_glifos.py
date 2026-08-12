"""Mede quanto da tipografia é da fonte do tema e quanto é empréstimo do Windows.

Uso:  py ferramentas/cobertura_de_glifos.py

**Isto não é um portão, é um instrumento.** Sai sempre com código 0, de
propósito, e não entra no CI. Ele não diz "passou" nem "falhou" — diz um número
que hoje ninguém tinha, e que muda como se lê o resultado do verificar_glifos.py.

**A pergunta que ele responde.** O ``verificar_glifos.py`` mede com
``QFontMetrics.inFont``, e esse método conta a substituição do sistema: ele
responde ``True`` para um ideograma chinês perguntando a uma fonte latina de
38 KB, porque o Windows empresta o glifo de outra família na hora de pintar.
Ótimo para a pergunta "algo vai virar caixinha na tela?" — foi assim que o
``＋`` fullwidth foi pego, já que aquele não tinha empréstimo disponível.

Mas o critério que o projeto documenta é outro: *o símbolo tem de existir na
fonte que o tema escolheu*. Para saber isso é preciso olhar o arquivo, não
perguntar ao Qt. Este script lê a tabela ``cmap`` de cada fonte — o mapa de
ponto de código para glifo — onde não há ambiguidade nem socorro.

**O que esperar do resultado.** Nenhuma família chega perto dos 35 símbolos, e
isso inclui as fontes que já estavam aqui muito antes desta ferramenta. O
programa sempre dependeu do empréstimo, e sempre funcionou. O número existe
para que a decisão sobre o que fazer a respeito — apertar o critério, reduzir
o repertório de símbolos, ou assumir o empréstimo por escrito — seja tomada
com o dado à vista, em vez de com a impressão de que o verificador já garante
o que não garante.
"""

from __future__ import annotations

import contextlib
import sys
import winreg
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

for _fluxo in (sys.stdout, sys.stderr):
    with contextlib.suppress(AttributeError, ValueError):
        _fluxo.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

CHAVES = (
    # A de máquina traz o que veio com o Windows; a de usuário, o que alguém
    # instalou sem ser administrador — é onde caem EB Garamond e Zilla Slab.
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
    (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"),
)
PASTAS = (
    Path(r"C:\Windows\Fonts"),
    Path.home() / "AppData/Local/Microsoft/Windows/Fonts",
)


def _arquivos_de_fonte() -> list[Path]:
    """Todo arquivo de fonte registrado, de máquina e de usuário."""
    caminhos: list[Path] = []
    for raiz, sub in CHAVES:
        try:
            chave = winreg.OpenKey(raiz, sub)
        except OSError:
            continue
        with chave:
            total = winreg.QueryInfoKey(chave)[1]
            for i in range(total):
                with contextlib.suppress(OSError):
                    _, dado, _ = winreg.EnumValue(chave, i)
                    if not isinstance(dado, str):
                        continue
                    bruto = Path(dado)
                    # O registro guarda ora o caminho completo, ora só o nome
                    # do arquivo — este último some se procurado no diretório
                    # errado, e a família simplesmente não apareceria no
                    # relatório, como se não estivesse instalada.
                    candidatos = [bruto] if bruto.is_absolute() else [p / dado for p in PASTAS]
                    caminhos.extend(c for c in candidatos if c.is_file())
    return caminhos


def familias_instaladas() -> dict[str, Path]:
    """Nome de família -> arquivo. A primeira ocorrência vence."""
    from fontTools.ttLib import TTFont

    mapa: dict[str, Path] = {}
    for caminho in _arquivos_de_fonte():
        with contextlib.suppress(Exception):
            fonte = TTFont(str(caminho), fontNumber=0, lazy=True)
            registro = fonte["name"].getName(1, 3, 1) or fonte["name"].getName(1, 1, 0)
            fonte.close()
            if registro:
                mapa.setdefault(str(registro), caminho)
    return mapa


def localizar(familia: str, instaladas: dict[str, Path]) -> Path | None:
    """Arquivo de uma família, tolerando nomes de instância de fonte variável.

    O Qt oferece "Segoe UI Variable Text", "…Display", "…Small" — instâncias
    nomeadas de um único arquivo, cuja tabela `name` diz apenas "Segoe UI
    Variable". Sem esta tolerância, a fonte que desenha TODOS os controles de
    TODOS os temas saía do relatório como se não estivesse instalada, que é a
    pior forma de errar: silenciosa e no item mais usado.
    """
    if familia in instaladas:
        return instaladas[familia]
    # Do nome mais longo para o mais curto: entre "Segoe UI" e "Segoe UI
    # Variable", quem casa com "Segoe UI Variable Text" é o segundo.
    for nome in sorted(instaladas, key=len, reverse=True):
        if familia.startswith(nome + " "):
            return instaladas[nome]
    return None


def pontos_na_cmap(caminho: Path) -> set[int]:
    """Pontos de código que o ARQUIVO mapeia para um glifo."""
    from fontTools.ttLib import TTFont

    fonte = TTFont(str(caminho), fontNumber=0, lazy=True)
    try:
        return {ponto for tabela in fonte["cmap"].tables for ponto in tabela.cmap}
    finally:
        fonte.close()


def main() -> int:
    print("=" * 74)
    print("  COBERTURA DE GLIFOS — quanto é da fonte, quanto é do Windows")
    print("=" * 74)

    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication

    QApplication(sys.argv)
    visiveis = {str(f) for f in QFontDatabase.families()}
    if not visiveis:
        print("\n  Nenhuma família visível nesta plataforma Qt; nada foi medido.")
        print("  (Não rode com QT_QPA_PLATFORM=offscreen.)")
        print("=" * 74 + "\n")
        return 0

    from verificar_glifos import simbolos_no_codigo

    from pipboy.interface.janela import FONTES_MONO
    from pipboy.themes import TEMAS

    def primeira(candidatas: tuple[str, ...]) -> str:
        return next((c for c in candidatas if c in visiveis), candidatas[-1])

    # Mesma resolução do verificar_glifos.py, e pela mesma razão: medir uma
    # família que o programa não usaria seria medir nada.
    papeis: dict[str, list[str]] = {}
    for nome, tema in TEMAS.items():
        papeis.setdefault(primeira(tema.font_candidates), []).append(nome)
    papeis.setdefault(primeira(TEMAS["Fallout"].ui_font_candidates), []).append("controles")
    papeis.setdefault(primeira(FONTES_MONO), []).append("rodapé/mono")

    simbolos = sorted(simbolos_no_codigo())
    instaladas = familias_instaladas()
    print(f"\n  {len(simbolos)} símbolos no código · {len(papeis)} famílias em uso\n")

    print(f"  {'Família':<22} {'Usada por':<30} {'na fonte':>9}")
    print("  " + "-" * 68)
    emprestados: set[str] = set()
    for familia in sorted(papeis):
        arquivo = localizar(familia, instaladas)
        if arquivo is None:
            print(f"  {familia:<22} {', '.join(papeis[familia])[:30]:<30} {'arquivo?':>9}")
            continue
        mapa = pontos_na_cmap(arquivo)
        faltando = [c for c in simbolos if ord(c) not in mapa]
        emprestados.update(faltando)
        quantos = f"{len(simbolos) - len(faltando)}/{len(simbolos)}"
        print(f"  {familia:<22} {', '.join(papeis[familia])[:30]:<30} {quantos:>9}")

    print()
    if emprestados:
        print(f"  {len(emprestados)} símbolo(s) faltam em ao menos uma fonte em uso:")
        print("    " + " ".join(sorted(emprestados)))
        print("\n  Eles aparecem na tela mesmo assim, emprestados de outra família pelo")
        print("  Windows — com o desenho de outra fonte, fora da tipografia do tema.")
    else:
        print("  Toda fonte em uso desenha todos os símbolos por conta própria.")

    print("\n" + "=" * 74)
    print("  Relatório, não veredito: este script não reprova nada.")
    print("=" * 74 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
