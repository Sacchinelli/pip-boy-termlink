# Segurança e privacidade

## Que dados este programa toca

Vale a pena ser explícito, porque um tutor por voz é, por definição, um programa
que ouve o microfone da pessoa.

| Dado | Onde fica | Sai da máquina? |
| --- | --- | --- |
| Chave da API do Gemini | `.env`, ao lado do programa ou em `%LOCALAPPDATA%\PipBoyTermLink` | Só para a API do Google, na conexão |
| Áudio do microfone | Não é gravado em disco | Sim — é o serviço que transcreve e responde |
| Áudio do jogo (opcional) | Buffer em memória, dez segundos | Só quando você fala; o resto é descartado |
| Caderno de vocabulário | `%LOCALAPPDATA%\PipBoyTermLink\vocabulario.sqlite3` | Não |
| Histórico de conversas | `%LOCALAPPDATA%\PipBoyTermLink\historico.sqlite3` | Não |
| Preferências | `%LOCALAPPDATA%\PipBoyTermLink\preferencias.json` | Não |
| Registro de execução | `%LOCALAPPDATA%\PipBoyTermLink\pipboy.log` | Não |

Nada disso é enviado a nenhum servidor deste projeto — não existe servidor deste
projeto. O único destino externo é a Live API do Gemini, sujeita aos termos do
Google.

**O registro nunca contém a chave inteira.** Todo destino do log passa por um
formatador que mascara qualquer chave do Google na linha já escrita — mensagem,
argumentos e traço de pilha —, deixando só os quatro primeiros e os quatro
últimos caracteres. O objeto de configuração também deixa a chave fora do
próprio `repr`.

## Se você for relatar um defeito

O `pipboy.log` ajuda muito e não contém a sua chave. Mas ele **contém a
transcrição do que foi falado na sessão**. Leia antes de anexar a um issue
público, e apague o que não quiser publicar.

O mesmo vale para capturas de tela: a janela de conversa e o caderno de
vocabulário mostram o que você estudou.

## Se você for contribuir

Antes de abrir um pull request:

```bash
python ferramentas/verificar_segredos.py
```

Ele confere que as regras de ignore continuam pegando o `.env` (inclusive a
cópia que o build deixa em `dist/`) e varre os arquivos publicáveis atrás de
credenciais e de caminhos absolutos da sua máquina. O mesmo passo roda na CI, no
início de tudo — um segredo comitado já é público no instante do push, e nenhum
teste verde desfaz isso.

Dois cuidados que a ferramenta não consegue automatizar:

- **Nunca comite `build/` ou `dist/`.** O PyInstaller grava caminhos absolutos
  da máquina que compilou dentro dos `.toc` — nome de usuário, estrutura de
  pastas, versão do Python instalada. São 200 MB de dado pessoal disfarçado de
  arquivo intermediário. Estão no `.gitignore`; a questão é não forçar.
- **Cuidado ao colar mensagens de erro.** Um traço de pilha do Windows carrega
  o caminho completo, e o caminho completo tem o seu nome de usuário.

## Reportar uma vulnerabilidade

**Em privado**, pela aba *Security* do repositório, em *Report a vulnerability*
(ou direto em
<https://github.com/Sacchinelli/pip-boy-termlink/security/advisories/new>). O
relato fica visível só para quem mantém o projeto até ser corrigido. Nunca abra
uma issue pública para uma falha de segurança — e nunca inclua chaves, tokens
ou dados pessoais, nem no relato privado.

Este é um projeto pessoal, sem equipe e sem compromisso de prazo de resposta.
