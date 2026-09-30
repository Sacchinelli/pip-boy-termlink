# Como contribuir

O projeto tem convenções que não estão em nenhuma ferramenta, e é por isso que
elas estão escritas aqui. O [README](README.md) explica o programa; o
[SECURITY](SECURITY.md) explica o que ele toca e como relatar uma falha.

## Preparar o ambiente

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
copy .env.example .env   # e cole a sua chave do Gemini
```

`requirements-dev.txt` traz o programa e as ferramentas de verificação com
versão fixa — as mesmas do CI, para o verde daqui ser o verde de lá.

## Antes de abrir um pull request

```powershell
py ferramentas/verificar_segredos.py             # nada de segredo no que será publicado
py -m ruff check .
py -m mypy pipboy pip_boy.py diagnostico.py ferramentas
py tests/test_nucleo.py
$env:QT_QPA_PLATFORM="offscreen"; py tests/test_interface.py
```

Duas verificações a mais, conforme o que mudou:

- **Mudou comportamento?** Plante os defeitos que a mudança deveria impedir e
  confira que a suíte os pega: `py ferramentas/mutantes.py especificacao.py`
  (o formato está no docstring da ferramenta). Um defeito que passa em
  silêncio é um teste que não existe. Conte na mensagem do commit quantos
  foram plantados e quantos foram pegos — e, se algum escapou, por quê.
- **Mexeu na interface?** A suíte roda sem tela, e sem tela o Qt não enxerga
  as fontes. Rode o programa de verdade e olhe: o procedimento, com o que não
  apertar (**INICIAR gasta a chave por minuto de áudio**), está em
  `.claude/skills/rodar-pipboy/`.

## Convenções

- **Português** no código, nos comentários, nas mensagens e nos testes.
- **Comentário explica o porquê**, e não o que a linha faz: a decisão, o
  defeito que ela evita, a alternativa que foi descartada.
- **Formatação:** só o `ruff check`. O projeto não usa o `ruff format` — o
  motivo está no `pyproject.toml`.
- **Uma ideia por commit.** O título no presente, dizendo o que o commit faz
  ("Faz o painel caber em tela de notebook", "Tira a vitrine do
  repositório"). O corpo em prosa: o problema, a decisão, e um parágrafo final
  **"Conferido:"** com o que foi verificado.
- **Poucos pull requests, cada um com um tema** — vários commits dentro de
  cada um. Dezenas de PRs empilhados, um por commit, não se revisam.
- **Merge commit**, e não squash nem rebase: a mensagem de cada commit é
  documentação, e o squash a apagaria. O ramo é apagado ao mergear.
- **Nada de segredo, nada de dado pessoal:** o `.env`, os bancos
  (`*.sqlite3`), o `pipboy.log` e as pastas `build/` e `dist/` ficam fora do
  repositório. O `verificar_segredos.py` confere isso, e roda no CI antes de
  tudo.

## Versões

A versão mora em dois lugares que um teste obriga a concordar:
`pyproject.toml` e `pipboy/__init__.py`. Ao fechar uma versão, anote no
[CHANGELOG](CHANGELOG.md) o que mudou para quem usa, com o número dos pull
requests.
