# Pip-Boy TermLink

Tutor de inglês por voz, em tempo real, para quem joga em inglês. O programa ouve seu microfone (e opcionalmente o áudio do próprio jogo), responde em português por voz usando a Live API do Gemini, e guarda automaticamente cada palavra que ensina num caderno de vocabulário que você pode consultar, revisar e exportar.

> Projeto não oficial, sem afiliação com os estúdios dos jogos citados ou com o Google.

## O que ele faz

- **Tradução instantânea sem sair do jogo.** Pergunte "o que significa *wasteland*?" e receba a resposta por voz em 1–2 frases.
- **A interface veste o jogo.** Trocar o jogo no seletor muda a janela inteira — paleta, fonte, títulos, rótulos dos botões, a persona sugerida e a *atmosfera*: varredura de CRT no Fallout, partículas douradas no Elden Ring, chuva de dados no Cyberpunk. Nada disso usa recurso dos jogos; é tudo gerado por código.
- **A janela responde ao mouse.** Uma luz segue o cursor pelo fundo da janela, com um leve atraso que dá peso ao movimento, e um anel acompanha o ponteiro e, sobre tudo que se pode clicar, deixa de ser círculo e **abraça** o contorno do alvo — o botão, o seletor, o cartão —, indo junto com o botão magnético enquanto o cursor o puxa. As partículas da atmosfera — brasas, neve, poeira, a chuva de dados do Cyberpunk — fogem do cursor e deslizam em profundidade conforme ele anda. Todo botão acende por dentro no ponto que o cursor toca; os de ação (**INICIAR**, Mudo, Enviar, Abrir caderno, Histórico, e os do caderno e da revisão) são **magnéticos**: puxados de leve na direção do mouse que se aproxima, acendendo antes do toque. Os cartões da tela inicial inclinam em 3D sob o cursor, os seletores da lateral acendem sob ele e cada clique solta uma onda do ponto tocado. A mesma luz **acende as bordas** por onde passa — das falas, dos botões, dos seletores, dos cartões e dos painéis, inclusive das superfícies que não têm contorno nenhum em repouso —, e o cursor deixa um **rastro** no material do jogo: brasas subindo no Witcher, neve caindo no Skyrim, dados escorrendo no Cyberpunk, que somem em menos de um segundo. E os títulos **se decifram** como num terminal: sob o cursor, o nome do aparelho e os títulos das seções embaralham e se resolvem letra a letra; ao trocar de jogo, o nome novo — NETRUNNER OS, DIÁRIO DO BRUXO — se decifra no lugar do antigo, e a tela inicial chega com o título se resolvendo. Para quem usa leitor de tela, o texto é sempre o verdadeiro. Com o cursor em cima, a janela anda no ritmo da tela — 72 quadros por segundo numa de 144 Hz, cada um exibido por dois ciclos exatos, 60 numa de 60 Hz — e volta a 30 quando tudo assenta. Nada disso custa enquanto você joga: só é calculado com o mouse em movimento sobre a janela, e o relógio de quadros para quando a luz assenta. O **teclado** tem a mesma linguagem: navegar por Tab leva a luz até o meio do campo que recebeu o foco, com o rastro mostrando o caminho e o anel o abraçando ao chegar — o foco deixa de ser um filete de contorno. O foco que apenas chega a uma janela (um diálogo que abre e escolhe o primeiro campo) não acende nada: o que conta é o foco andando dentro dela. Com a atmosfera **Desligada**, nada disso existe.
- **Toque numa palavra para perguntar por ela.** Na fala do tutor, cada palavra é um alvo: passar o cursor acende a palavra na cor do tema e clicar escreve *“O que significa ‘stimpaks’?”* no campo de texto, sem enviar. Em repouso não há marca nenhuma — uma fala inteira sublinhada não se lê —, e selecionar o texto continua valendo. É o gesto que faltava: a palavra desconhecida está no meio da frase, e perguntar por ela exigia digitá-la de novo. E a fala reconhece o seu próprio caderno: numa palavra que você já ensinou, a dica traz a tradução e quando ela vence (*“ammo — munição · revisar em 3 dias · do seu caderno”*), tudo do banco local, sem rede.
- **A janela diz por onde começar.** Antes da primeira fala, a conversa não é mais um painel vazio com duas linhas no pé: mostra o botão com o nome que ele tem naquele jogo (*Invocar*, *Conectar*, *Rastrear*) e o atalho que funciona de dentro do jogo, três exemplos do que dizer — um deles com uma palavra vencida do seu caderno —, cada um numa **ficha que se toca**: clicar escreve a pergunta no campo de texto, com o foco, sem enviar (enviar é seu) e cartões para **Revisar**, abrir o **Caderno** e o **Histórico** com os números de agora e a tecla de cada um. Nada ali gasta a chave. O modelo em uso e os atalhos globais, que eram as duas anotações soltas do arranque, moram no rodapé dela. A tela some quando a sessão começa ou chega a primeira fala, e volta se a sessão terminar sem nenhuma; numa janela estreita com letra grande, os cartões e as fichas empilham em vez de cortar o texto.
- **Tudo o que a janela faz, digitando.** `Ctrl+K` abre uma **paleta de comandos**: escreva três letras e aperte Enter. Ela alcança as ações (caderno, histórico, revisão, modo compacto, campo de texto), as três chaves — dizendo como cada uma está — e **cada valor de cada seletor da lateral**: jogo, personalidade, nível, modo, voz, microfone, saída, volume do jogo, atmosfera e tamanho do texto. Trocar a voz deixa de ser rolar a coluna, achar o campo, abrir a lista e procurar o nome. A lista não é escrita à mão: ela é montada dos próprios seletores, então uma voz nova aparece ali sem que ninguém precise lembrar da paleta. A busca é por subsequência, sem acento e sem caixa — `tamtex` acha *Tamanho do texto*, `acao` acha *Ação* —, e as letras que casaram ficam acesas e sublinhadas no resultado, que é o que explica por que aquela linha está na lista. O que a janela proíbe, a paleta proíbe: um campo desabilitado — o jogo, durante a sessão — não gera comando nenhum. E **nada ali chama a API**: iniciar uma sessão e enviar uma mensagem consomem crédito por minuto e ficam de fora; *encerrar* entra, porque terminar não custa e é justamente o que se procura com pressa. **E ela acha as palavras do seu caderno:** digite `muni` e *ammo · munição* aparece entre os comandos; o Enter abre o caderno já mostrando a palavra, desfazendo o filtro e o jogo que tinham ficado da última visita — quem pediu a palavra pediu a palavra, não a interseção dela com o que estava marcado. A consulta vai ao banco a cada tecla (da segunda letra em diante), pelo mesmo caminho da busca do caderno: termo, tradução e exemplo, sem acento e sem caixa. Ela responde ao cursor como as outras janelas — luz, anel abraçando a linha sob o mouse, bordas acesas — e a tela inicial a anuncia no rodapé, porque ninguém descobre um `Ctrl+K` sozinho.
- **Durante a sessão, a coluna lateral mostra só o que ainda vale.** Jogo, nível, voz e microfone vão na abertura da conexão e ficam travados enquanto ela dura — e travados eles eram uma parede de caixas cinzentas que empurrava para baixo da dobra os dois controles que ainda funcionavam. Com a sessão no ar, os ajustes dão lugar a um resumo de leitura (*Nesta sessão*: jogo, personalidade, nível, modo, voz, microfone, saída e as opções ligadas), que termina dizendo como trocar; *Ouvir o jogo*, atmosfera e tamanho do texto continuam à mão. A *Busca na web* saiu da seção de Áudio, onde não tinha nada a fazer, e foi para Ensino; o caderno e o histórico viraram duas portas lado a lado no rodapé.
- **A coluna lateral recolhe.** Numa janela estreita — abaixo de 1180 px, o que inclui a mínima e a metade de um monitor Full HD — ela vira sozinha uma faixa de 60 px com a marca do jogo e as portas do caderno e do histórico, e a conversa ganha a largura. O botão na barra de título e o `Ctrl+\` abrem e fecham à mão, e a escolha feita à mão vale mais que a largura, nos dois sentidos. Recolhida, a paleta (`Ctrl+K`) continua alcançando todos os ajustes.
- **Ouve o jogo.** Com a captura de loopback ativada, os últimos dez segundos do áudio do jogo ficam guardados no seu computador e seguem junto com a sua pergunta — basta dizer "o que ele acabou de dizer?". Guardar em vez de transmitir sem parar corta 81% dos tokens dessa função (veja *Custos*). A voz do próprio assistente é retirada dessa captura enquanto ele fala — sem isso ele se transcreveria como se fosse você e entraria em laço.
- **Caderno automático com revisão espaçada.** Toda palavra ensinada é salva em silêncio via *function calling*, com tradução, exemplo e o jogo em que apareceu. Cada palavra tem uma data de revisão agendada por um algoritmo tipo Anki (acertos afastam a revisão, erros a trazem de volta), e o modo Quiz cobra exatamente as vencidas. Quando a sessão salva uma palavra, a anotação dela entra na conversa e um **+1** sobe do contador do caderno, na lateral — a campainha já dizia que algo foi salvo; o sinal diz onde aquilo foi parar. Reencontro e resposta de quiz não ganham sinal, porque não mudam o total.
- **O caderno tem porta.** `Ctrl+B` abre o visualizador: a lista inteira, buscável por termo, tradução *ou exemplo* — porque ninguém lembra da palavra em inglês, lembra do contexto. A busca **ignora acento e caixa**: `missao` encontra *MISSÃO*. Não é refinamento — o `LIKE` do SQLite só ignora maiúsculas em ASCII, e num caderno metade em português isso significava que procurar "ação" não achava "AÇÃO", sem nenhum sinal de que algo tinha sido perdido. Quatro filtros respondem às perguntas que o número na lateral não responde: **Todas**, **Para revisar** (a fila da repetição espaçada), **Dominadas** e **Difíceis**, ordenado pelo que você mais erra. Ao lado deles, um seletor recorta por **jogo** — dimensão separada, e não mais um filtro, porque "difíceis" e "do Cyberpunk" são perguntas independentes e quem acaba de trocar de jogo quer as duas ao mesmo tempo. O seletor lista só os jogos que realmente deram palavras, e some quando há um só. Dá para apagar um termo e exportar tudo para Anki (TSV) ou Markdown.
- **E o caderno também sabe entrar.** O botão **Importar** soma ao caderno os termos de um TSV — para juntar os cadernos de duas máquinas usadas em paralelo (copiar o `.sqlite3` substitui, não funde) ou trazer uma lista pronta de um jogo. **Palavra que já existe é deixada em paz:** ela carrega facilidade, intervalo, próxima revisão, acertos e erros, e um arquivo de texto não tem como conhecer meses de repetição espaçada — um import que "atualizasse" levaria o agendamento junto, e você perderia o progresso justamente ao tentar somar a ele. Termos novos entram vencidos, para caírem no próximo quiz. O número de colunas decide o formato: duas são termo e tradução, **três** são o que a exportação daqui escreve (termo, verso, jogo — com o exemplo dentro do verso) e quatro ou mais são um campo cada (termo, tradução, exemplo, jogo). Linha sem termo ou sem tradução é contada e ignorada, nunca fatal.
- **Revisão offline, sem custo.** Dentro do caderno, o botão **Revisar** abre cartões das palavras vencidas — frente com o termo, verso com tradução e exemplo, botões *acertei/errei* (ou as teclas `Espaço`, `A` e `E`). É a mesma repetição espaçada do Quiz por voz, mas sem sessão, sem rede e sem gastar um token. Cada resposta aparece na tela: uma barra com um segmento por cartão pinta o seu na cor do resultado — no fim da rodada, ela mostra *onde* os erros caíram —, e um recado diz quando aquela palavra volta ("amanhã", "em 4 dias", "na próxima rodada"), que é o que faz a repetição espaçada deixar de ser mágica. A resposta tem lugar reservado no cartão, então revelar não empurra os botões para longe do dedo que vai apertar A ou E.
- **Painel de progresso.** O botão **Progresso** mostra o caderno em números: palavras novas por semana, a régua de domínio (novas → aprendendo → dominadas) e de que jogo o vocabulário está vindo — tudo desenhado no tema. As barras crescem ao abrir, em cascata, e a semana corrente aparece como **esta semana**, com a barra desenhada como algo que ainda vai encher — pintada igual às outras, uma quarta-feira parecia uma semana fraca. Passar o cursor revela o que não cabe no relance, sem esconder nada do que cabe: numa semana, o intervalo de datas e quanto ela cresceu ou caiu em relação à anterior; num jogo, a fatia do caderno; na régua, o que *novas*, *aprendendo* e *dominadas* querem dizer.
- **O ambiente se ajusta sozinho.** A cada meio minuto o programa olha os processos do Windows; se um jogo conhecido está aberto e a sessão está parada, a janela se veste dele e avisa no registro. A troca automática acontece no máximo uma vez por detecção — escolher outro ambiente à mão depois disso é respeitado.
- **Backup diário do caderno.** Ao abrir, o programa guarda uma cópia íntegra do banco em `backups/` (uma por dia, as sete últimas ficam). O vocabulário de meses é o único dado que não se recupera perdendo.
- **Primeira execução acolhedora.** Sem chave configurada, em vez de um erro sobre variáveis de ambiente aparece um cartão no tema explicando onde a chave nasce e recebendo a colagem — ele grava o `.env` no lugar certo sozinho.
- **Histórico de sessões.** Cada conversa fica gravada (só neste computador) e pode ser relida no botão **Histórico**: a lista de sessões à esquerda, a transcrição à direita, com direito a apagar o que não quiser guardar. Conversas com mais de um ano são descartadas na abertura (`RETENCAO_DIAS`, em `pipboy/historico.py`): transcrição inteira que ninguém nunca poda é um arquivo que só cresce. A sequência de estudo não acompanha essa poda — ela é medida em anos.
- **Busca em todas as conversas.** As duas caixas de busca do histórico respondem perguntas diferentes, e por isso moram em colunas diferentes: a da esquerda procura em **todas** as sessões e mostra quantas falas casam em cada uma — porque "onde foi mesmo que ele explicou isso?" é a pergunta que se faz, e ninguém sabe de antemão em qual conversa procurar; a da direita procura dentro da conversa já aberta. Clicar num resultado abre a conversa já rolada até a fala que casou. E rola de fato: até aqui a rolagem era pedida antes de a transcrição nova ser medida, e a conversa abria sempre no topo, com a fala marcada fora da tela. Agora a coluna desliza até ela e a fala pulsa uma vez ao chegar; a sessão aberta fica marcada na lista da esquerda, e trocar de sessão faz as falas entrarem em cascata. As duas ignoram acento e caixa, pela mesma razão do caderno — e a busca entre conversas passou a procurar primeiro as falas que casam e só depois as sessões delas, em vez de agrupar o histórico inteiro para descartar quase tudo no fim.
- **Da palavra de volta para a conversa.** A palavra sem o contexto em que apareceu é metade da memória, e o caderno guardava só metade. Cada palavra tem agora um botão **◷** que abre a conversa em que ela foi ensinada, rolada até a linha em que aquilo aconteceu, com o diálogo em volta. Os dois bancos não têm chave estrangeira um para o outro; o elo é o instante em que a palavra nasceu, e quando a conversa não existe mais (apagada, ou além da retenção) o botão fica desabilitado dizendo por quê, em vez de levar para o lugar errado.
- **Os cartões do caderno respondem a quem chega.** Cada palavra desenhava três ações o tempo todo — numa lista de trinta, noventa ícones disputando o olho com o que se veio ler. Agora uma luz na cor do tema acompanha o cursor, e **◷**, **▤** e **×** aparecem quando o cursor *para* no cartão (varrer a lista não faz fileiras de botões piscarem) **ou quando o `Tab` chega neles** — esconder controles só no hover trancaria o teclado para fora. O que se esconde são ações, nunca informação: tradução, exemplo e estado de revisão ficam sempre à vista. Remover uma palavra fecha a lista sobre o espaço dela sem voltar ao topo, e o **Exportar** confirma no próprio botão — o resultado ia só para o registro da janela principal, escondido atrás do caderno. Com a atmosfera **Desligada**, tudo isso chega na hora, sem trajeto. E o caderno responde ao cursor como a janela principal: a luz o segue pelo fundo, o anel cresce sobre o que se pode clicar, cada clique solta uma onda, o mouse deixa rastro no material do jogo e as bordas dos cartões acendem por onde ele passa. Parado, o caderno não anima nada — sem partícula nem tremulação próprias, o relógio dele só corre enquanto o cursor se mexe. O histórico, a revisão e a tela de progresso também: a luz passa pelo fundo liso delas (atenuada, porque ali não há painel translúcido na frente), as bordas acendem por onde o cursor passa e ele deixa rastro. Todas as cinco janelas do programa respondem ao mouse do mesmo jeito.
- **Modo compacto.** O botão de cápsula na barra de título encolhe o programa a uma barra mínima sempre-no-topo — estado, medidor do microfone e mudo — para deixar sobre o jogo em janela sem bordas. A sessão continua intacta; a cápsula é só outra vista dela.
- **Bandeja do sistema.** Iniciar/encerrar, silenciar, mostrar e sair, sem caçar a janela atrás do jogo.
- **O aparelho também se ouve.** Sessão iniciada, encerrada, palavra salva e erro têm um blip curto — sintetizado por código, com timbre próprio por jogo (o terminal 8-bit do Fallout, o sino do Elden Ring, o agudo netrunner do Cyberpunk). Nenhum arquivo de áudio no repositório, pelo mesmo princípio da atmosfera; o WAV nasce na primeira execução e fica em cache. Atmosfera **Desligada** silencia os blips também: a preferência por calma vale para o ouvido.
- **Sequência de estudo.** O painel de progresso conta há quantos dias seguidos você não deixa o estudo morrer — sessões por voz e revisões offline contam igual. Ontem ainda segura a sequência; só um dia inteiro em branco a derruba.
- **Cinco modos de ensino:** Tradutor Rápido, Tutor Conversacional, Treino de Pronúncia, Quiz de Vocabulário e Imersão Total.
- **Três níveis (A1–A2, B1–B2, C1+)** que mudam o quanto o assistente fala em português e o que ele corrige.
- **Sessões ilimitadas, sem cortes.** Compressão de janela de contexto e retomada de sessão mantêm a conversa viva além dos limites de 15 minutos por sessão e 10 minutos por conexão — e quando o servidor avisa que vai reciclar a conexão, a troca acontece no intervalo entre falas, nunca no meio de uma frase.

## Ambientes temáticos

Cada jogo tem o seu ambiente. A troca é imediata, sem reiniciar o programa.

| Jogo | Ambiente |
| --- | --- |
| Fallout | Terminal CRT de fósforo verde (Pip-Boy 3000 MK IV) |
| Elden Ring | Ouro sobre quase preto, com motes subindo |
| Skyrim | Noite de inverno no norte: gelo, neve e a aurora atravessando o céu |
| The Witcher 3 | Bestiário sóbrio em prata e vermelho-sangue |
| Red Dead | Película de cinema mudo: sépia, poeira no facho e riscos de rolo gasto |
| GTA | Rádio pirata sobre a cidade: noite quase preta e o pôr do sol de neon no horizonte |
| Cyberpunk 2077 | Interface netrunner em amarelo e ciano |
| RPG / Aventura (geral) | Grimório de beringela e ouro, com o selo desenhado na página |
| FPS / Multiplayer | Rede tática de esquadrão: grafite de oliva, laranja de sinalização e o enquadramento de um visor |
| Genérico / Outro | Tema neutro escuro para qualquer jogo |

Cada ambiente tem também uma **atmosfera** — varredura, grão, vinheta, partículas, interferência e a forma dos cantos — sintetizada com o QPainter. Não há textura, arte, logotipo ou fonte de terceiros no repositório: o que caracteriza um jogo na tela não é a cor, é o material, e material se desenha. A intensidade tem três níveis na coluna lateral (**Completa**, **Discreta**, **Desligada**), porque varredura e cintilação são obstáculo real para baixa visão.

**Cada ambiente tem uma camada que só ele tem.** É o que impede um jogo de ser outro com outra cor, e foi a régua que mostrou onde isso faltava: *Skyrim* media 2,87 do tema neutro, e a rádio pirata do *GTA* media 4,57 do grimório do *RPG* — dois fundos escuros parecidos e nada que dissesse de que jogo eram. Hoje a crônica nórdica tem a **aurora** cruzando o alto do céu, o grimório tem o **selo** arcano desenhado na página, a rádio tem a **linha do horizonte** de neon com o brilho subindo dela, o velho oeste tem os **riscos** verticais de uma película gasta e o visor tático tem as **cantoneiras**. Nenhuma delas custa por quadro: todas vão no pixmap do vidro, que só se refaz ao mudar de tamanho ou de tema. As paletas foram junto — gelo no lugar do ardósia, beringela no lugar do índigo, ouro sobre quase preto — e o par mais parecido da tabela passou de **2,87 para 5,27**.

**E cada jogo tem o traço dos menus dele.** Paleta, fonte e atmosfera diziam de que jogo era a janela; os componentes não — o fio que separa as seções da coluna era o mesmo risco cinza nos dez ambientes. Agora os títulos de seção falam na fonte do jogo, com o espaçamento entre letras dos menus dele, e o fio ao lado tem o ornamento que quem jogou reconhece: a filigrana dourada que some no escuro (Elden Ring), o fio duplo de pedra terminado num losango vazado (Skyrim), a argola do medalhão abrindo um fio de ferro (Witcher), a régua dupla dos cartazes de procurado (Red Dead), o tubo de neon do rosa ao ciano (GTA), o barramento de dados recortado (Cyberpunk), o fio de iluminura (RPG) e a escala de um visor (FPS). E o painel da conversa — a maior superfície da janela — ganha a moldura que os menus do jogo poriam em volta do que importa: filigranas de ouro no alto e no pé (Elden Ring), uma placa de pedra com cravos nos cantos (Skyrim), cantoneiras de ferro com rebite (Witcher), a moldura dupla do cartaz de procurado (Red Dead), o letreiro de neon no pé (GTA), cantos chanfrados com o barramento de dados (Cyberpunk) e a página de manuscrito com arabescos (RPG). Tudo rente à borda, sem passar por cima da conversa, e desenhado com QPainter sobre a paleta do tema — o que se evoca é o estilo dos menus, e não a marca de ninguém.

O ambiente de **FPS** foi o primeiro a ser refeito com a régua na mão. Ele media 3,97 de distância do tema deliberadamente *neutro* (`ferramentas/distancia_dos_temas.py`) — era o tema neutro com uma grade por cima, e a grade era a identidade inteira dele. Hoje é um campo de batalha moderno: grafite com fundo de **oliva** no lugar do cinza-azulado de escritório, **laranja de sinalização**, pó de escombro no ar, ruído de rádio em rajadas e uma camada nova — **cantoneiras**, os colchetes de canto e os tiques de meio de borda que dizem *equipamento apontado para alguma coisa*, onde papel milimetrado não dizia. O botão diz **DESDOBRAR** e **EXTRAIR**, o assistente é o líder do seu esquadrão, e o blip virou o estalo grave de um canal de rádio abrindo. O vizinho mais próximo dele passou de 3,97 (Genérico) para 8,82 (Fallout).

Na primeira execução, quem tem **"Efeitos de animação" desligado no Windows** recebe a atmosfera já em **Desligada**, com um aviso no registro dizendo de onde isso veio e como reverter. Quem desliga essa opção do sistema já disse uma vez, para o computador inteiro, que animação lhe faz mal; perguntar de novo na forma de uma janela que cintila é ignorar uma resposta já dada. É **Desligada**, e não Discreta, porque o que o sistema pede é menos *animação* e só esse nível para de fato a partícula, a cintilação e as transições — atender pela metade um pedido de acessibilidade é não atender. E o sistema decide apenas o **padrão**: assim que você escolher um nível, ele é seu, mesmo contrariando o Windows.

Ao lado dela, **Tamanho do texto** (Padrão, Grande, Maior) multiplica a rampa tipográfica inteira — e junto com ela a coluna lateral, que é uma coluna de texto e só trocaria "pequeno demais" por "cortado" se ficasse parada. Vale na janela, no caderno, no histórico e na cápsula, porque toda a tipografia do programa passa por um ponto só. Os dois controles de apresentação são os **únicos que continuam livres durante a sessão**: o travamento existe para o que vai na abertura da conexão (jogo, nível, microfone), e letra e atmosfera não vão a lugar nenhum — quem precisa de letra maior para ler a conversa precisa disso durante a conversa, não depois dela.

O jogo escolhido define quatro coisas de uma vez: a aparência, o contexto linguístico enviado ao modelo (que inglês esperar naquele título), o nome do assistente no registro e a primeira persona da lista — a persona temática. As personas gerais (Assistente Amigável, Instrutor Rígido, Professor Nativo) continuam disponíveis em qualquer jogo.

### Adicionar um jogo

Todos os ambientes vivem em `pipboy/themes.py`. Acrescente um `GameTheme` com os textos, a fonte e as oito cores da paleta: o seletor, a repintura da interface, o prompt e a persona temática passam a incluí-lo sem nenhuma outra edição. Para dar a ele uma atmosfera própria, acrescente uma `Atmosfera` em `pipboy/interface/atmosfera.py` com o mesmo nome — sem isso ele herda a neutra.

Em `font_candidates`, liste as famílias em ordem de preferência — a primeira instalada no sistema é a usada, e a última serve de reserva. **A segunda da lista importa tanto quanto a primeira:** Garamond, Rockwell e Bookman Old Style não acompanham o Windows, então temas que as pediam desabavam calados em Georgia, e três outros caíam juntos em Bahnschrift — dez ambientes rendiam seis tipografias numa instalação limpa. Escolha como segunda opção uma família de fábrica que nenhum outro tema use. `py diagnostico.py` mostra o que cada tema conseguiu na sua máquina e avisa quando dois colidem.

Você declara oito cores. As outras — superfícies elevadas, bordas, realce de seleção, estados de foco e as variantes legíveis de cada cor de texto — são calculadas a partir delas em `design.py`, e `py tests/test_nucleo.py` reprova a paleta se qualquer combinação de texto e fundo ficar abaixo de 4.5:1 (WCAG AA). O **campo travado** está entre os pares verificados: durante a sessão todos os seletores ficam desabilitados, e é só por eles que se enxerga qual jogo, nível e microfone estão valendo — um estado desabilitado ilegível apaga as escolhas do jogador justamente quando elas não podem mais ser trocadas. Para os símbolos do cabeçalho, use o bloco *Geometric Shapes* (◈ ✦ ❖ ★ ◉ ◎ ▲ ◆): o Windows desenha emoji sempre coloridos, com fonte própria, e eles ignoram a paleta do tema.

## Aparência de aparelho, até a moldura

A janela não usa a moldura do Windows: a barra de título — título, minimizar, maximizar, fechar — é desenhada pelo próprio tema, com botões pintados a traço (nada de glifo de fonte, que muda de espessura conforme a máquina). Arrastar e redimensionar são entregues ao sistema (`startSystemMove`/`startSystemResize`), então o comportamento é o de uma janela comum; no Windows 11, os cantos arredondados e a sombra voltam por uma chamada ao DWM. O caderno usa a mesma moldura.

Trocar de jogo dissolve o ambiente antigo sobre o novo em vez de estalar de um para o outro, e o programa abre com um cartão de arranque no tema do último jogo usado. Com a atmosfera **Desligada**, nenhuma dessas animações roda — animação também é atmosfera.

## Qualidade verificada por ferramenta

O código passa limpo por três verificadores, e a suíte de testes cobre o núcleo inteiro:

```powershell
py -m ruff check .                                # lint (zero apontamentos)
py -m mypy pipboy pip_boy.py diagnostico.py       # tipos, modo estrito
py tests/test_nucleo.py                           # ~400 testes sem hardware
py tests/test_interface.py                        # a interface inteira, sem tela
py ferramentas/verificar_glifos.py                # todo símbolo tem glifo nas fontes
py ferramentas/distancia_dos_temas.py             # o quanto os dez ambientes se parecem
```

A suíte de interface constrói a janela de verdade no backend *offscreen* do Qt: repinta os dez ambientes por completo, abre caderno, cartões de revisão, progresso, histórico, cápsula compacta e o cartão de boas-vindas, e exercita a busca. É ela que pega o que o núcleo nunca vê — a chave de paleta digitada errada, o import circular novo, o widget que explode ao trocar de tema. Roda sem monitor, sem microfone e sem rede, então o CI a executa igual.

**E há um defeito que ela é estruturalmente incapaz de ver.** No backend *offscreen* o Qt enxerga **zero** famílias de fonte: a suíte desenha a janela inteira em caixinhas e passa feliz, então um símbolo sem glifo — a armadilha que este README já descreve duas vezes, e que já mordeu — escapa dela por construção. `verificar_glifos.py` é a resposta: roda na plataforma padrão, com a base de fontes real, lê com o `ast` **todo literal de texto** de `pipboy/` (docstrings de fora, que são texto para quem lê o código) e exige que cada caractere da categoria *Symbol* do Unicode consiga ser desenhado. Não é uma lista escrita à mão, que envelheceria no primeiro glifo novo — é o código sendo lido.

Ele achou um na primeira execução: a anotação de palavra nova usava `＋` (U+FF0B, a forma *fullwidth*, feita para tipografia CJK), ausente de **todas** as fontes dos temas. Toda palavra salva aparecia com uma caixinha na frente, em todos os ambientes. Hoje é `⊕`. Se o runner não tiver base de fontes, o script diz que não mediu nada e sai limpo — não saber medir não é o mesmo que encontrar defeito.

**E o programa depende do Windows para desenhar boa parte desses símbolos.** Isto está escrito aqui porque é uma decisão, não um descuido: a verificação acima pergunta *"este caractere aparece?"*, e o Qt responde contando a substituição que o sistema faz por caractere na hora de pintar. Ela portanto garante que nada vira caixinha — garantia forte, e a que importa para quem usa. O que ela não garante é que o glifo esteja na fonte do tema: `ferramentas/cobertura_de_glifos.py` lê a tabela `cmap` dos arquivos e mostra que **26 dos 35 símbolos** faltam em ao menos uma das doze famílias em uso, saindo emprestados de outra. A melhor delas tem 27 de 35; a pior, 9. Exigir os 35 de todas significaria abrir mão de quase todo o repertório de símbolos, e o preço — um `▶` desenhado por outra família — é menor que o da alternativa.

**E há uma qualidade que nenhum verificador via: se os ambientes são mesmo dez.** "Trocar o jogo muda a janela inteira" é fácil de acreditar comparando o terminal verde do Fallout com o neon do Cyberpunk; o que ninguém olhava era o resto da tabela. `ferramentas/distancia_dos_temas.py` fotografa os dez na mesma janela, no mesmo estado, reduz cada foto a uma miniatura e compara pixel a pixel em **CIELAB** (ΔE76) — a régua do olho, não a dos bytes. Ele não reprova nada; ele mostra quem está perto de quem, e foi assim que se soube que *Skyrim* estava a 2,87 do tema **Genérico**, que o *visor tático* do FPS estava a 3,97 dele, e que *GTA* e *RPG / Aventura* — uma rádio pirata e um grimório — mediam 4,57 entre si, enquanto o extremo saudável da tabela (*Fallout* contra *RPG*) mede 20,98. Identidade de tema deixou de ser questão de gosto e passou a ter número.

**E nem os dois juntos substituem abrir a janela.** O *offscreen* prova que a interface se constrói e não explode; o verificador de glifos prova que os símbolos existem nas fontes. Nenhum dos dois olha para o resultado. Por isso o procedimento de rodar o programa de verdade — subir pelo `.venv`, provar que a janela desenhou, mandar os atalhos e fotografar — está registrado em `.claude/skills/rodar-pipboy/`, com as armadilhas que ele custou para descobrir: que **INICIAR** abre sessão com a Live API e passa a gastar a chave por minuto de áudio, de modo que conferir a interface não autoriza clicar nele; que conferir o ambiente pela `python314.dll` não prova nada, porque um ambiente virtual compartilha o binário do interpretador base; e que fotografar a *tela*, em vez de pedir o conteúdo à *janela*, produz uma imagem convincente do programa errado — mais rica em cores que a foto certa, e por isso invisível a qualquer limiar.

A configuração vive no `pyproject.toml`. Duas supressões são deliberadas e estão documentadas lá: o padrão `objectName=` no construtor (válido no PySide6, ausente das stubs) e os imports tardios do teste.

Exceções imprevistas não derrubam nem silenciam o programa: um capturador global (`pipboy/crash.py`) grava o traço completo no `pipboy.log` e avisa numa caixa temática — uma vez por defeito, sem tempestade de janelas.

## Executável

Para gerar um `.exe` único que roda sem Python instalado:

```powershell
py -m pip install pyinstaller
py ferramentas/gerar_icone.py
py -m PyInstaller pip_boy.spec
```

O resultado fica em `dist/PipBoyTermLink.exe`. Coloque um `.env` com a sua chave ao lado do executável (o `.env` **nunca** é embutido no binário — segredo não se distribui). O ícone do aplicativo também é desenhado por código, pelo mesmo princípio que proíbe binários de arte no repositório.

### O Windows pode recusar o executável

Com o **Smart App Control** ligado (padrão em muitas instalações limpas do Windows 11), tentar abrir o `.exe` recém-compilado devolve *"uma política de Controle de Aplicativo bloqueou este arquivo"*. Isso **não é defeito do programa**: o Smart App Control recusa qualquer executável sem assinatura digital e sem reputação estabelecida, o que inclui todo binário caseiro recém-gerado.

Para conferir o estado da máquina:

```powershell
(Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy").VerifiedAndReputablePolicyState
```

`0` = desligado, `1` = ativo e bloqueando, `2` = avaliação.

Os caminhos possíveis, do mais simples ao mais caro:

1. **Rodar pelo código-fonte** (`py pip_boy.py`). O Smart App Control não se aplica, e é o modo em que o projeto é desenvolvido. Para não digitar isso toda vez, `py ferramentas/criar_atalho.py` põe o ícone na área de trabalho apontando para o Python do projeto — mesmo programa, um duplo-clique.
2. **Assinar o executável** com um certificado de code signing. É o que faz o `.exe` ser aceito de saída em qualquer máquina — e o único caminho se você pretende distribuir para outras pessoas.
3. **Desligar o Smart App Control.** Funciona, mas leia antes: **essa mudança é de mão única.** Uma vez desligado, ele só volta a ser ligado com uma reinstalação limpa do Windows. Não é uma troca que valha a pena por causa de um programa que já roda pelo código-fonte.

## Requisitos

- Windows 10 ou 11 (a captura do áudio do jogo depende de WASAPI). Em Linux/macOS o programa roda, mas sem essa função.
- Python 3.10 ou superior.
- PySide6 (instalado pelo `requirements.txt`). A interface é Qt; o Tkinter não é mais usado.
- Microfone e saída de áudio funcionando.
- Chave de API do Gemini com acesso a um modelo Live: <https://aistudio.google.com/apikey>

## Instalação

```powershell
git clone https://github.com/sacchinelli/pip-boy-termlink.git
cd pip-boy-termlink
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Abra o `.env` e informe sua chave:

```dotenv
GEMINI_API_KEY=sua_chave_aqui
```

Para iniciar:

```powershell
py pip_boy.py
```

### Abrir pela área de trabalho

Um programa que só abre digitando um comando não é bem um aplicativo. Para ter o ícone lá fora:

```powershell
py ferramentas/criar_atalho.py
```

A ferramenta cria (ou atualiza) o atalho **Pip-Boy TermLink** na área de trabalho — na de verdade, inclusive quando o OneDrive a sincroniza e ela vira `OneDrive\Área de Trabalho`: quem diz onde ela fica é o shell do Windows, e não `%USERPROFILE%\Desktop`, que nesse caso é uma pasta fantasma que ninguém vê.

O atalho aponta para o `pythonw.exe` do `.venv`, o interpretador **sem console**. O duplo-clique abre a janela do programa e nada mais: sem terminal preto atrás dela, e sem uma segunda entrada na barra de tarefas que derrubaria o Pip-Boy junto se alguém a fechasse.

O ícone é desenhado antes de o atalho ser escrito, e isso não é ordem casual: quem não consegue desenhar o ícone não consegue desenhar a janela. Se faltar dependência naquele ambiente, a ferramenta diz o que falta e **não cria atalho nenhum** — um ícone bonito que não abre nada é pior do que atalho nenhum.

O preço do interpretador sem console é que `sys.stderr` vale `None`: erro nenhum tem para onde ir. Por isso as mensagens de arranque do `pip_boy.py` (estrutura de pastas errada, dependência ausente, Python velho demais) aparecem numa **caixa do Windows** quando não há console. Sem isso, um duplo-clique numa instalação quebrada não faria absolutamente nada — a pior mensagem de erro possível.

Para fixar na barra de tarefas, **arraste o atalho até ela**. Fixar pela janela já aberta guarda o `pythonw.exe` sozinho, sem o argumento, e o que fica fixado não abre coisa alguma.

Para conferir se o núcleo está saudável (não precisa de chave, microfone nem internet — e roda inteiramente numa pasta temporária, sem tocar no seu caderno nem nas suas preferências):

```powershell
py tests/test_nucleo.py
```

## Como usar

1. Escolha o jogo (a janela se reconfigura na hora), a personalidade, seu nível, o modo e — se não quiser os aparelhos padrão do Windows — o microfone e a saída de áudio.
2. Marque **Alto-falante (anti-eco)** se você *não* usa fone — sem isso o assistente ouve a própria voz e se interrompe num laço.
3. Marque **Ouvir o jogo** antes de iniciar se quiser que ele escute o áudio do jogo.
4. Clique em **INICIAR** e fale normalmente.
5. Depois de jogar um pouco, abra o caderno (**Ctrl+B**) para ver o que foi salvo — e use o modo **Quiz de Vocabulário** para cobrar as palavras vencidas.

### Atalhos

| Atalho | Ação | Escopo |
| --- | --- | --- |
| `Ctrl+Alt+P` | Iniciar / encerrar | Global (funciona dentro do jogo) |
| `Ctrl+Alt+M` | Silenciar o microfone | Global |
| `Ctrl+Alt+G` | Ligar/desligar o áudio do jogo | Global |
| `F12` / `Esc` | Alternar / encerrar | Só com a janela em foco |
| `Ctrl+K` | Paleta de comandos — tudo o que a janela faz | Só com a janela em foco |
| `Ctrl+B` | Abrir o caderno de vocabulário | Só com a janela em foco |
| `Ctrl+H` | Abrir o histórico de sessões | Só com a janela em foco |
| `Ctrl+R` | Revisar agora (cartões offline) | Só com a janela em foco |
| `Ctrl+M` | Entrar no modo compacto | Só com a janela em foco |
| `Ctrl+L` | Ir para o campo de texto | Só com a janela em foco |
| `Ctrl+\` | Recolher / mostrar a coluna lateral | Só com a janela em foco |
| `Ctrl+F` | Buscar (no caderno ou no histórico) | Só com essa janela em foco |

Os atalhos globais são configuráveis no `.env`. **Esc e F12 nunca são registrados globalmente** — sequestrar essas teclas no sistema inteiro quebraria o menu de pausa do jogo, que é exatamente onde este programa é usado.

## Onde ficam os arquivos

Dados gravados vão para `%LOCALAPPDATA%\PipBoyTermLink\` (e não para a pasta do programa, que pode ser somente leitura):

```text
pipboy.log              Diagnóstico rotativo
vocabulario.sqlite3     Caderno de vocabulário
historico.sqlite3       Transcrições das sessões e a sequência de estudo
preferencias.json       Últimas escolhas da interface
backups\                Cópias diárias do caderno (as sete últimas)
sons\                   Blips sintetizados, em cache por tema
```

Os dois bancos abrem em **WAL** (`pipboy/banco.py`). Não é ajuste fino: cada frase transcrita do assistente vira um commit na thread da interface, e no modo padrão do SQLite todo commit paga um `fsync` — uma ida ao disco por frase falada, no meio do laço de eventos do Qt. Junto do WAL vai `synchronous=NORMAL`, que abre mão de durabilidade contra queda de energia (os commits dos últimos instantes), não contra queda do programa. Você vai ver arquivos `-wal` e `-shm` ao lado dos bancos enquanto o programa estiver aberto; eles somem no fechamento. Um disco que recuse o WAL — pasta de rede, por exemplo — apenas continua no modo antigo.

**Os carimbos de tempo são gravados em UTC.** O SQL compara essas datas como TEXTO — é assim que se responde "esta palavra venceu?" e "em que conversa esta palavra nasceu?" — e comparação textual só é verdadeira enquanto o deslocamento do fuso não muda. Gravado no fuso local, o mesmo instante passava a ordenar uma hora fora do lugar depois de uma virada de horário de verão ou de uma viagem, com sintomas discretos demais para alguém desconfiar: uma revisão vencendo cedo, uma palavra apontando para a conversa vizinha. Bancos criados por versões anteriores são convertidos na primeira abertura, uma vez só (`PRAGMA user_version`). O fuso local continua onde ele importa — na tela, e no dia da sequência de estudo, que conta os dias de quem estuda e não os de Greenwich.

## Estrutura do projeto

```text
pip-boy-termlink/
├── pip_boy.py            # Lançador
├── pip_boy.spec          # Receita do executável (PyInstaller)
├── pyproject.toml        # Metadados, ruff e mypy
├── ferramentas/
│   ├── criar_atalho.py   # Põe o atalho do programa na área de trabalho
│   ├── cobertura_de_glifos.py # Quanto da tipografia é da fonte do tema
│   ├── gerar_icone.py    # Renderiza o .ico do build (nenhum binário no repo)
│   ├── verificar_glifos.py    # Todo símbolo do código existe nas fontes?
│   └── verificar_segredos.py  # Nada de segredo entre os arquivos rastreados
├── pipboy/
│   ├── __init__.py       # Logging, abertura e ponto de entrada
│   ├── constants.py      # Taxas de amostragem e temporizações
│   ├── banco.py          # Conexões SQLite (WAL), carimbos em UTC, dobra da busca
│   ├── crash.py          # Rede de segurança: exceção vira log + aviso
│   ├── deteccao.py       # Reconhece o jogo aberto pela lista de processos
│   ├── historico.py      # Banco de transcrições de sessões
│   ├── revisao.py        # Rodada de revisão offline (a lógica, sem Qt)
│   ├── sons.py           # Síntese dos blips (NumPy → WAV), por tema
│   ├── design.py         # Escala tipográfica, espaçamento e cor
│   ├── themes.py         # Ambiente de cada jogo: paleta, fonte, textos
│   ├── config.py         # .env, pasta de dados, preferências
│   ├── profiles.py       # Personas, níveis, modos e o prompt
│   ├── events.py         # Mensagens entre threads
│   ├── dsp.py            # Reamostragem, mixagem, medição (NumPy)
│   ├── audio.py          # Dispositivos, captura, portão de voz, loopback
│   ├── vocabulary.py     # Banco SQLite e exportação
│   ├── tools.py          # Function calling
│   ├── session.py        # Sessão Live, reconexão, transcrição
│   └── interface/        # Camada de apresentação (Qt)
│       ├── janela.py     # Composição da janela e ciclo de vida
│       ├── moldura.py    # Barra de título temática e redimensionamento
│       ├── abertura.py   # Cartão de arranque no tema do último jogo
│       ├── icone.py      # Ícone do app, desenhado por código
│       ├── estilo.py     # Folha de estilo derivada do tema (função pura)
│       ├── preferencias.py# Vínculo entre a coluna lateral e o arquivo
│       ├── conversa.py   # O diálogo em bolhas
│       ├── tela_inicial.py# O que a conversa mostra antes de haver conversa
│       ├── caderno.py    # Visualizador do vocabulário salvo
│       ├── revisao.py    # Cartões de revisão offline
│       ├── progresso.py  # Painel de progresso com gráficos
│       ├── historico.py  # Visualizador das sessões gravadas
│       ├── compacto.py   # A cápsula sempre-no-topo do modo compacto
│       ├── bandeja.py    # Ícone e menu na bandeja do sistema
│       ├── campainha.py  # Quem toca os blips sintetizados
│       ├── boas_vindas.py# Primeira execução: pedir a chave, no tema
│       ├── dialogo.py    # Caixas de confirmação e aviso, no tema
│       ├── componentes.py# Botão, chip, medidor, cápsula, bolha, transição
│       ├── movimento.py  # Progresso animável e entrada em cascata
│       ├── cursor.py     # Onde está o cursor, e os botões que ele puxa
│       └── atmosfera.py  # Cenário procedural de cada jogo
├── tests/
│   ├── test_nucleo.py    # Lógica: sem hardware, sem rede, sem efeito colateral
│   └── test_interface.py # A janela inteira, no backend offscreen do Qt
├── .claude/skills/
│   └── rodar-pipboy/     # Como subir e dirigir o app — o que teste algum vê
├── .env.example
└── requirements.txt
```

## Segurança e privacidade

- **Nunca publique o `.env`.** O `.gitignore` já o exclui. A chave nunca aparece inteira no log — só os quatro primeiros e quatro últimos caracteres.
- O áudio do microfone é enviado ao serviço Gemini. Se você ativar **Ouvir o jogo**, o áudio do jogo — incluindo vozes de outros jogadores em partidas online — também é enviado. Use apenas com quem sabe disso.
- A retomada de sessão faz o servidor guardar o contexto da conversa por até algumas horas. Se isso for um problema para você, edite `session.py` e remova o campo `session_resumption`.
- Revise `pipboy.log` antes de compartilhá-lo.
- O **histórico de sessões** (`historico.sqlite3`) guarda a transcrição das suas conversas com o tutor, apenas localmente. Sessões podem ser apagadas uma a uma pelo visualizador; apagar o arquivo remove tudo.

## Custos

Áudio consome cerca de 25 tokens por segundo em cada direção. Uma sessão de uma hora com conversa constante fica na casa das dezenas de milhares de tokens. O rodapé da janela mostra o total acumulado em tempo real.

**E mostra quanto isso custa, se você disser o preço.** "48.291 tokens" não significa nada para quem precisa decidir se continua a sessão — e este é um programa construído inteiro em torno de gastar menos. Preencha `PRECO_POR_MILHAO_TOKENS` no `.env` (e `MOEDA`, se quiser outro rótulo) e o rodapé passa a mostrar `~US$ 0,14` ao lado da contagem. O preço vem do `.env`, e não de uma constante do código, **de propósito**: um número sobre dinheiro que envelheceu é pior que número nenhum, porque não parece errado e ninguém confere. Sem preço configurado, o programa não estima nada. E o `~` não é enfeite: o serviço reporta um total só, sem separar entrada de saída nem áudio de texto, que têm preços diferentes — o que dá para oferecer com honestidade é ordem de grandeza, não fatura.

**O microfone só é transmitido quando há som.** Um portão de voz local mede o nível de cada bloco e retém o que estiver abaixo do limiar, com pré-rolo (para não cortar a primeira sílaba) e cauda (para não confundir pausa entre palavras com fim de fala). Antes disso, uma sessão aberta numa sala silenciosa gastava cerca de 90 mil tokens por hora sem ninguém perguntar nada. Numa conversa esparsa a economia fica em torno de 60%.

**E o limiar mede a sua sala, em vez de presumi-la.** Um número fixo aposta que toda sala se parece com a sala em que ele foi escolhido, e as duas formas de perder essa aposta são caras — e mudas, porque nos dois casos tudo continua *funcionando*:

| Sua sala | Com limiar fixo | Calibrado |
| --- | --- | --- |
| Ventilador, teclado mecânico, ganho de microfone alto | O fundo passa do limiar sozinho, o portão nunca fecha: **0% de economia** | **88%** |
| Silenciosa, microfone de ganho baixo | A fala inteira fica abaixo do limiar: **a pergunta é comida** | as perguntas passam inteiras |

**E o limiar é visível.** O medidor ao lado da cápsula de estado ganhou um risco vertical: à esquerda dele nada é transmitido, à direita o portão abre. É o que responde "estou falando e ele não me ouve" sem abrir log nenhum — se as barras não passam do risco, o problema é ganho de microfone, não o programa. Para o risco significar alguma coisa, a régua do medidor passou a ser **logarítmica**, como a de todo medidor de áudio: na régua linear que existia, fala normal acendia *duas* barras de dezoito e as dezesseis restantes esperavam um grito. E o número desenhado é o mesmo que o portão julga — antes a tela media o bloco cru, na taxa nativa do dispositivo, e o portão media o vetor já reamostrado, o que em ruído de sala dá 19% de diferença.

Os dois números saem de `py tests/test_nucleo.py`, no mesmo material. O piso de ruído é estimado por estatística de mínimos — a janela dos últimos dez segundos, ordenada, e um percentil baixo dela. Funciona porque fala humana tem buraco: entre palavras, entre sílabas, entre frases, muito mais de 10% dos blocos de uma janela de dez segundos são fundo, mesmo com alguém falando sem parar. O limiar resultante tem dois batentes, e o de cima é o que importa: ele fica **abaixo do nível da fala normal**, de modo que uma sala barulhenta demais faz o portão desistir de economizar em vez de cortar a pergunta. Perder tokens se recupera; perder a pergunta, não.

**Com "Ouvir o jogo" ligado, o som do jogo é contexto retroativo, não transmissão contínua.** O portão media o sinal já misturado — e jogo em silêncio não existe, então ele ficava escancarado a sessão inteira e devolvia exatamente os 90 mil tokens por hora que existe para evitar. Só que ninguém liga essa opção para o modelo *escutar* o jogo o tempo todo: liga para poder perguntar "o que ele acabou de dizer?". Agora o portão volta a decidir pelo **microfone**, e os últimos dez segundos de jogo ficam guardados localmente, de graça, seguindo junto com a pergunta quando ela vier. A medição está em `py tests/test_nucleo.py`: num trecho de três minutos com o jogo tocando sem parar e três perguntas curtas, **564 blocos transmitidos contra 3.000 — 81% de economia**, sem perder uma pergunta sequer.

As respostas de ferramenta também emagreceram: `consultar_vocabulario` devolvia até 2.300 tokens numa única resposta (mais que a instrução de sistema inteira), com campos vazios e zerados ocupando espaço. Hoje o teto é de 20 palavras, o exemplo é truncado e campo sem conteúdo não é enviado — **cerca de 70% a menos**. As declarações de ferramentas, reenviadas a cada uma das ~6 reconexões por hora, foram reescritas para dizer o mesmo com menos.

`Ctrl+Alt+M` continua cortando tudo na hora, para quando você quiser garantia de que nada sai.

## Problemas comuns

- **`py` não é reconhecido:** instale o Python 3.10+ marcando "Add to PATH".
- **A barra de tarefas mostra o ícone do Python:** era assim até a identidade do processo (AppUserModelID) ser declarada no arranque. Se ainda acontecer, o Windows está com o ícone em cache: feche o programa, aguarde alguns segundos e abra de novo.
- **A janela não abre e o console fala em `PySide6`:** rode `py -m pip install -r requirements.txt`. A interface depende do Qt.
- **O atalho da área de trabalho parou de abrir:** ele guarda o caminho da pasta do projeto e do `.venv`. Se você moveu ou renomeou qualquer um dos dois, rode `py ferramentas/criar_atalho.py` de novo. Se o duplo-clique mostrar uma caixa de erro, ela diz o que falta — é a mesma mensagem que apareceria no terminal.
- **A atmosfera atrapalha a leitura:** troque **Atmosfera do jogo** para *Discreta* ou *Desligada* na coluna lateral. *Discreta* reduz varredura, grão e a quantidade de partículas; *Desligada* para a animação por completo e devolve a CPU ao jogo. Mesmo *Completa* custa pouco: a sobreposição repinta só a região das partículas (2,4% da janela, medido pela suíte de interface) em vez da janela inteira, e nos dois ambientes sem camada viva o relógio de quadros nem chega a correr. O tubo do Fallout treme em rajadas de tempos em tempos, e não sem parar: a tremulação é a única camada que cobre a janela inteira, e contínua ela repintava tudo a cada quadro — dez vezes o custo das partículas, atrás do próprio jogo.
- **Uma palavra foi salva errada:** abra o caderno com `Ctrl+B`, busque por ela e passe o mouse sobre o cartão (ou chegue nele com `Tab`): **▤** corrige o texto sem perder a revisão, **×** remove.
- **O PowerShell bloqueia a ativação do ambiente:** rode `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` e tente de novo. Vale só para a janela atual.
- **"Ouvir o jogo" está desabilitado:** exige Windows com WASAPI e o pacote `PyAudioWPatch`. A opção precisa ser marcada *antes* de iniciar a sessão.
- **O assistente conversa sozinho:** você está usando alto-falante. Marque **Alto-falante (anti-eco)**. Isso trata o eco *acústico* (caixa → ar → microfone). O eco *digital* de **Ouvir o jogo** — o loopback capta a saída do sistema, onde a voz do assistente também passa — é descartado sozinho e não depende de nenhuma opção; se ainda assim ele se ouvir com o jogo ligado, é um bug, não configuração.
- **O medidor de nível não se move:** microfone errado, ou bloqueado em Configurações → Privacidade → Microfone. Escolha o dispositivo certo na caixa MICROFONE.
- **Você não ouve o assistente:** ele está falando em outro aparelho. Escolha o certo na caixa SAÍDA DE ÁUDIO. Ambas as caixas só podem ser trocadas com a sessão parada.
- **"Modelo indisponível":** ajuste `GEMINI_MODEL` no `.env` para um modelo Live habilitado na sua conta.

## Licença

[MIT](LICENSE) — © 2026 Sacchinelli.

Use, modifique e distribua à vontade, inclusive em projeto seu. A única
condição é manter o aviso de copyright: se este código (ou parte relevante
dele) for parar em outro lugar, o crédito vem junto.

Sem garantia de espécie alguma — é um projeto pessoal, não um produto.

### O que a licença não cobre

Ela vale para **este código**. Os jogos citados nos temas — Fallout, Elden
Ring, Skyrim, The Witcher, Red Dead, GTA, Cyberpunk 2077 — são marcas dos seus
respectivos estúdios, e este projeto não tem afiliação com nenhum deles nem com
o Google. Nenhum recurso dos jogos é usado: cada paleta, fonte, atmosfera e
blip é sintetizado por código, e é por isso que não há um único arquivo binário
no repositório.