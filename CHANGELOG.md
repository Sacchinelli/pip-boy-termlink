# Histórico de versões

O que mudou para quem usa, versão a versão. O porquê de cada mudança — e o que
foi conferido nela — está na mensagem do commit e na descrição do pull request
indicado entre parênteses.

## 3.1.0 — 2026-09-30

### Cada jogo com a cara dele

- Dez ambientes que não se confundem: o traço dos menus nas divisórias e
  molduras, a marca do item escolhido, o botão de partida, a tela inicial como
  menu do jogo, o ritmo das animações e a chegada dos títulos, a mira do
  cursor, o material do vidro (digitais no Pip-Boy, a constelação do norte, o
  estêncil do visor) e fontes livres embutidas para cada um (#80).
- Os objetos, as falas e os sons de cada jogo: ícones desenhados para as
  portas, a conversa no formato de fala do jogo, a dica do dia na voz dele, os
  quatro sons com timbre próprio, e o caderno, o histórico, a revisão e o
  progresso com o nome e a moldura que o jogo daria (#81, #82).
- Os dois pares de temas que ainda se pareciam foram afastados: o par mais
  parecido mede 7,10 na régua dos temas, contra 2,87 na primeira medida (#82).

### Estudo

- Revisão em dois jeitos: *lembrar* (o cartão de sempre) e *escrever* (a
  tradução e a frase do jogo com um buraco, para digitar a palavra), com pista
  letra a letra, três tentativas e a nota *difícil* da repetição espaçada (#82).
- Painel de progresso que planeja: previsão dos próximos sete dias, calendário
  dos dias de estudo, nível do caderno na barra de experiência de cada jogo, e
  um atalho para revisar a dívida de hoje (#82).
- A repetição espaçada foi consertada, e o caderno ganhou borracha: corrigir
  uma palavra não apaga o que ela já aprendeu (#17).
- A busca acha a palavra com ou sem acento (#12).

### A interface

- A janela responde ao cursor e ao teclado: luz que segue o mouse, bordas que
  acendem, títulos que se decifram, o anel que abraça o que se pode clicar, e o
  foco do teclado levando a mesma luz (#78).
- Paleta de comandos (`Ctrl+K`), que também acha as palavras do caderno (#79).
- A tela reorganizada por importância: coluna lateral recolhível, caderno e
  histórico densos, ações no lugar certo (#79).
- A tela inicial diz por onde começar; caderno, revisão, progresso e histórico
  respondem a cada gesto (#77).
- O painel de progresso cabe em tela de notebook, os gráficos são lidos por
  leitor de tela, e a revisão tem som (#82).
- Atalho na área de trabalho que abre o programa com duplo-clique, sem console (#10).

### Robustez e segurança

- Um caderno ou histórico danificado não impede mais o programa de abrir: o
  arquivo é guardado ao lado, e o caderno volta da cópia diária (#85).
- O que o modelo grava e o que se importa passam pela mesma limpeza, com
  tamanho máximo por campo; a tela mostra o caderno como texto, nunca como
  HTML interpretado (#85).
- A chave da API não aparece em lugar nenhum do log, nem dentro de um traço de
  pilha (#85).
- Carimbos de tempo gravados em UTC, e o histórico podado pelo mesmo carimbo
  que o grava (#13, #18).
- Falhas que passavam em silêncio agora aparecem; a falha de autenticação é
  reconhecida pelo conteúdo, e não pelo código (#1, #3, #11).

### Desempenho

- O programa abre mais rápido e pesa menos aberto (#14).

### Manutenção

- CI nas duas pontas do Python suportado (3.10 e 3.14), com ferramentas de
  versão fixa, e auditoria semanal das dependências (#4, #84).
- Testes de mutação no repositório (`ferramentas/mutantes.py`), em cópias
  paralelas (#82).
- A escolha da fonte num lugar só, sem cópias de código, e as suítes sem
  deixar lixo no disco (#83).
- A janela principal foi dividida em módulos (#15, #16).
- Ferramentas de medida: a régua dos temas, a cobertura de glifos e o
  verificador de glifos (#8, #9, #79).

## 3.0.0 — 2026-08-04

Primeira versão publicada: o tutor de inglês por voz em tempo real, com dez
ambientes temáticos, caderno de vocabulário com repetição espaçada, revisão
offline, painel de progresso, histórico de conversas e modo compacto.
