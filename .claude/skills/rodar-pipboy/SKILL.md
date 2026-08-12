---
name: rodar-pipboy
description: Como subir e dirigir o Pip-Boy TermLink (o app PySide6 deste repositório) no Windows para conferir uma mudança na interface de verdade — lançar pelo .venv, provar que a janela desenhou, mandar atalhos e fotografar o resultado. Use sempre que pedirem para rodar, abrir, iniciar, testar na prática ou tirar print do app, quando perguntarem se uma mudança "funciona mesmo" ou "aparece na tela", ou quando você mexeu em qualquer coisa sob pipboy/interface/ e precisa ver o efeito. Use também antes de dizer que uma alteração visual está pronta — a suíte de testes roda em offscreen e não enxerga o que o usuário vê.
---

# Rodar o Pip-Boy TermLink

Este é um app Qt de janela única no Windows. Rodar significa abrir a janela e
mexer nela, não importar um módulo e imprimir um valor. A suíte
`tests/test_interface.py` roda com `QT_QPA_PLATFORM=offscreen`, onde o Qt não
enxerga fonte nenhuma e desenha a interface inteira em caixinhas — ela passa
feliz por cima de defeitos que saltam aos olhos numa tela real. É exatamente
essa lacuna que rodar o app fecha.

## Antes de tudo: o botão que custa dinheiro

**Não clique em INICIAR, e não envie `Ctrl+Alt+P`.** Esses dois abrem a sessão
com a Live API do Gemini usando a chave do `.env` do usuário, e a partir daí o
consumo é por minuto de áudio. Ninguém pediu isso ao pedir "roda o app".

A boa notícia é que quase tudo dá para conferir sem gastar: a janela sobe
completa, com todos os seletores populados e os dados reais do caderno, sem
tocar na rede. Se a sua mudança só puder ser vista dentro de uma sessão ao
vivo, **pare e pergunte** antes — é o usuário quem decide gastar crédito.

Atalhos seguros, todos offline: `Ctrl+B` caderno, `Ctrl+H` histórico,
`Ctrl+R` revisar cartões, `Ctrl+M` modo compacto, `Ctrl+L` foco no campo de
texto. Digitar no campo e clicar em **Enviar** também chama a API — não é só o
INICIAR.

## 1. Suba pelo .venv, em segundo plano

```
cd D:\Projeto_Tutor_Ingles
.\.venv\Scripts\python.exe pip_boy.py
```

Lance como comando de segundo plano, não em primeiro plano: a janela fica
aberta até alguém fechar, e um lançamento bloqueante trava o turno até o
timeout. O segundo plano ainda dá o arquivo de log, que é a metade invisível
da conferência.

Se o `.venv` não existir, crie antes — `py -m venv .venv` e
`.\.venv\Scripts\pip install -r requirements.txt`. Não caia na tentação de
rodar com `py pip_boy.py`: funciona, porque as dependências também estão no
Python global desta máquina, e por isso mesmo esconde justamente o tipo de
defeito que se quer pegar.

Dê uns segundos ao Qt e **leia o log até o fim**. Ele deve estar vazio. Aviso
de plugin de plataforma, `QFont` reclamando de família ausente ou qualquer
traceback contam como falha mesmo com a janela no ar.

## 2. Prove que subiu — e que subiu do lugar certo

```
powershell -File .claude\skills\rodar-pipboy\scripts\janela.ps1 -Acao estado
```

Espere `Janela ... 'PIP-BOY 3000 MK IV'`, `Respondendo ... True`, e o Qt vindo
de dentro do `.venv`.

Uma armadilha que já custou tempo: **não confira o ambiente pela
`python314.dll`**. Um ambiente virtual compartilha o binário do interpretador
base, então essa DLL aponta para a instalação global mesmo quando o `.venv`
está perfeitamente em uso, e parece erro sem ser. O que de fato muda é a
origem dos pacotes — por isso o script olha o `shiboken6`, o motor do PySide6.

Também aparecem dois processos `python.exe`: o app e um intermediário sem
janela. O script já filtra pelo que tem janela.

## 3. Dirija e olhe

Lançar sem interagir prova que o entrypoint resolve — é checagem de tipo com
passos extras. Leve o app até onde um usuário veria alguma coisa:

```
powershell -File .claude\skills\rodar-pipboy\scripts\janela.ps1 -Acao teclas -Teclas "^b" -Saida %TEMP%\caderno.png
```

Depois **abra o PNG e olhe**. Isso não é formalidade, e não basta ler os
números que o script imprime. Duas falhas reais já passaram por eles:

- Uma foto tirada com **outra janela por cima** do app. Ela é rica em cores e
  bem iluminada — passa por boa em qualquer heurística, e mostra o terminal no
  lugar do programa. (O script agora usa `PrintWindow`, que pede o conteúdo à
  própria janela e é imune a isso; o aviso fica porque a saída de emergência,
  raspar a tela, não é.)
- Um **layout quebrado**, que nenhuma medida de cor distingue de um layout
  certo.

Quem pega essas coisas são seus olhos.

Escolha o que dirigir pelo que você mexeu. Se foi no caderno, abra o caderno e
confira os números do cabeçalho contra o que o rodapé da janela principal diz.
Se foi no tema, troque o jogo no seletor e veja a janela se reconfigurar. Se
foi em tipografia, lembre que `ferramentas/verificar_glifos.py` cobre símbolo
ausente melhor que o olho — rode-o em vez de caçar caixinhas no print.

`Esc` fecha o diálogo que estiver aberto. Com a janela principal em foco,
porém, `Esc` **encerra o app** — mande-o só quando souber que há um diálogo na
frente.

## 4. Feche o ciclo

Diga ao usuário, explicitamente, se você deixou o app aberto ou o encerrou.
Deixar aberto costuma ser o que ele quer quando pediu para rodar — mas uma
janela órfã que ninguém sabe que existe segura o microfone e atrapalha o
lançamento seguinte.

Para encerrar: `Stop-Process -Id <pid>`.

## Se você for editar o script

Grave `janela.ps1` como **UTF-8 com BOM**. O Windows PowerShell 5.1 lê `.ps1`
sem BOM usando a página de código ANSI, e aí todo acento vira mojibake — o que
não seria só feio: as sequências quebradas desbalanceiam as aspas e o arquivo
para de compilar, com erros de sintaxe apontando para linhas que estão certas.
A maioria dos editores de arquivo grava sem BOM por padrão, então isso acontece
na primeira edição. Para consertar:

```
$t = Get-Content -Raw -Encoding UTF8 janela.ps1
Set-Content janela.ps1 -Value $t -Encoding UTF8 -NoNewline
```

Confira a sintaxe sem executar nada:

```
[System.Management.Automation.Language.Parser]::ParseFile($f, [ref]$null, [ref]$erros)
```

## O que relatar

Diga o que você **viu**, não o que você executou. "A janela subiu com o tema
Fallout, os seis seletores populados, microfone detectado, e o caderno abriu
com os 11 termos que o rodapé anuncia" é um relato. "Rodei o app e funcionou"
não é — e nada nele distingue um sucesso de um quadro preto.

Anexe os PNGs. É o usuário que sabe como o app dele deveria estar.
