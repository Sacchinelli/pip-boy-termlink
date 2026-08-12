"""Constantes de tema, áudio e temporização.

Mantidas isoladas para que qualquer módulo possa importá-las sem puxar
dependências pesadas (genai, pyaudio, PySide6).
"""

from __future__ import annotations

from typing import Final

# Nome do produto, usado em diálogos do sistema. O título da janela vem do
# tema do jogo selecionado (ver themes.py).
APP_NAME: Final = "Pip-Boy TermLink"
APP_SLUG: Final = "PipBoyTermLink"
DEFAULT_MODEL: Final = "gemini-3.1-flash-live-preview"

# --- Áudio ---------------------------------------------------------------
# A Live API exige PCM 16 bits mono: 16 kHz na entrada, 24 kHz na saída.
INPUT_SAMPLE_RATE: Final = 16_000
OUTPUT_SAMPLE_RATE: Final = 24_000
CHANNELS: Final = 1
SAMPLE_WIDTH: Final = 2
FRAMES_PER_BUFFER: Final = 1_024

# Quanto de áudio do jogo entra na mistura (0.0 = mudo, 1.0 = mesmo nível da voz).
DEFAULT_GAME_AUDIO_GAIN: Final = 0.45
# Tempo extra de silêncio após o assistente parar de falar, no modo anti-eco.
ECHO_GATE_TAIL_SECONDS: Final = 0.35

# --- Portão de voz (detecção local de fala) ------------------------------
# Áudio custa ~25 tokens por segundo em cada direção. Uma sessão aberta numa
# sala silenciosa consumia 90 mil tokens por hora sem ninguém dizer nada: o
# nível do microfone era medido a cada bloco, mas só alimentava o medidor da
# tela — nunca decidia se valia a pena transmitir.
#
# O limiar é conservador de propósito. Errar para o lado de enviar demais custa
# tokens; errar para o lado de cortar demais custa a pergunta do jogador, que é
# o produto. Sala silenciosa fica por volta de 0.005–0.02; fala normal passa
# de 0.1.
#
# Este número é o ponto de PARTIDA, não a regra: ele vale nos primeiros
# segundos de captura, enquanto o piso de ruído ainda não tem amostra
# suficiente para se pronunciar. Ver VOICE_GATE_NOISE_* logo abaixo.
VOICE_GATE_THRESHOLD: Final = 0.035

# --- Piso de ruído (calibração automática do limiar) ---------------------
# Um limiar fixo aposta que toda sala se parece com a sala em que ele foi
# escolhido, e as duas maneiras de perder essa aposta são caras:
#
# * **Sala barulhenta** (ventilador, teclado mecânico, ganho de microfone
#   alto). O fundo passa dos 0.035 sozinho, o portão nunca fecha e a economia
#   que ele existe para dar é ZERO — sem nenhum sintoma visível, porque tudo
#   continua funcionando.
# * **Sala silenciosa com microfone de ganho baixo.** A fala inteira acontece
#   abaixo do limiar e o portão come a pergunta.
#
# A saída é o portão medir a sala em vez de presumi-la. O piso é estimado por
# ESTATÍSTICA DE MÍNIMOS: guarda-se a janela dos últimos segundos e toma-se um
# percentil baixo dela. A justificativa é que fala humana tem buracos — entre
# palavras, entre sílabas, entre frases —, então numa janela de dez segundos
# muito mais de 10% dos blocos são fundo, mesmo com alguém falando sem parar.
# Por isso a janela é alimentada com TODOS os blocos, e não só com os que o
# portão recusou: aprender apenas do silêncio criaria o impasse óbvio — sala
# fica barulhenta, portão trava aberto, nada mais é recusado, nada mais é
# aprendido, portão trava aberto para sempre.
VOICE_GATE_NOISE_WINDOW_SECONDS: Final = 10.0
VOICE_GATE_NOISE_WINDOW_BLOCKS: Final = round(
    VOICE_GATE_NOISE_WINDOW_SECONDS * INPUT_SAMPLE_RATE / FRAMES_PER_BUFFER
)
VOICE_GATE_NOISE_PERCENTILE: Final = 0.10
# Quanto o sinal precisa superar o fundo para contar como fala. Dobrar a
# amplitude são ~6 dB, que é a distância mínima confortável entre uma voz
# dirigida ao microfone e a sala em volta dela.
VOICE_GATE_NOISE_FACTOR: Final = 2.2
# Os dois batentes do limiar adaptativo, e nenhum dos dois é gosto:
#
# O PISO impede que uma sala tratada acusticamente derrube o limiar até o ruído
# do próprio microfone, onde qualquer estalo abriria o portão.
#
# O TETO é o que garante que a calibração nunca coma a fala. Fala normal passa
# de 0.1 (é o que a nota do limiar acima afirma, e continua valendo): um limiar
# acima disso cortaria a pergunta em vez de economizar. Numa sala barulhenta
# demais o portão desiste de economizar e deixa passar — perder tokens é uma
# perda recuperável, perder a pergunta não é.
VOICE_GATE_THRESHOLD_MIN: Final = 0.012
VOICE_GATE_THRESHOLD_MAX: Final = 0.09
# Blocos guardados antes da fala começar (1 bloco ≈ 64 ms a 16 kHz). Sem eles,
# o gatilho corta o ataque da primeira sílaba — "wasteland" virava "asteland".
VOICE_GATE_PREROLL_BLOCKS: Final = 5

# Janela retroativa do áudio do jogo, em segundos.
#
# Com 'Ouvir o jogo' ligado, o portão media o sinal JÁ MISTURADO — e jogo em
# silêncio não existe. O portão ficava permanentemente aberto e a sessão
# gastava os 90 mil tokens por hora que ele foi criado para evitar, agora com
# a desculpa de que "o jogo é entrada legítima".
#
# Só que ninguém liga essa opção para o modelo ESCUTAR o jogo o tempo todo: liga
# para poder perguntar "o que ele acabou de dizer?". Para isso não é preciso
# transmitir sempre — basta que os últimos segundos estejam guardados AQUI, de
# graça, e sigam junto com a pergunta quando ela vier. O portão volta a decidir
# pelo microfone, e o jogo vira contexto retroativo em vez de fluxo contínuo.
#
# Dez segundos cobrem uma fala de NPC inteira e custam 320 KB de RAM.
VOICE_GATE_GAME_CONTEXT_SECONDS: Final = 10.0
VOICE_GATE_GAME_CONTEXT_BLOCKS: Final = round(
    VOICE_GATE_GAME_CONTEXT_SECONDS * INPUT_SAMPLE_RATE / FRAMES_PER_BUFFER
)
# Quanto o portão segue aberto depois do nível cair. Cobre a pausa natural
# entre palavras sem deixar o servidor achar que o turno acabou cedo demais.
VOICE_GATE_HANGOVER_SECONDS: Final = 0.8

# Tamanho da fila entre a captura e o envio, EM BLOCOS.
#
# Não é um número escolhido por gosto: é o tamanho da pior rajada possível. Ao
# abrir, o portão entrega o pré-rolo inteiro mais o bloco atual de uma vez só —
# com 'Ouvir o jogo' isso são os dez segundos de contexto do jogo, 157 blocos.
# A fila tinha 64. A thread de captura ficava presa enfileirando enquanto o
# microfone não era lido, e o driver descartava em silêncio justamente o ataque
# da pergunta que o pré-rolo existe para preservar.
#
# A folga acima da rajada absorve a variação normal de um consumidor que faz um
# salto de thread e um envio de rede por bloco.
CAPTURE_QUEUE_BLOCKS: Final = VOICE_GATE_GAME_CONTEXT_BLOCKS + 64

# --- Ciclo de vida -------------------------------------------------------
SHUTDOWN_TIMEOUT_SECONDS: Final = 5.0
UI_POLL_INTERVAL_MS: Final = 60
MAX_RECONNECT_ATTEMPTS: Final = 6
RECONNECT_BASE_DELAY: Final = 1.0
RECONNECT_MAX_DELAY: Final = 20.0
# A partir de quantos segundos uma conexão conta como saudável — e portanto
# zera o contador de tentativas. Ver LiveSessionWorker._connection_loop: o
# critério PRECISA ser duração, não tráfego, senão uma conexão que aceita,
# responde um erro e desliga reconecta para sempre.
HEALTHY_CONNECTION_SECONDS: Final = 30.0

# --- Aparência -----------------------------------------------------------
# Nada de aparência mora mais aqui. Cada jogo tem a sua paleta em themes.py, e
# as medidas comuns — grade de espaçamento, rampa tipográfica, tamanhos de
# componente — vivem em design.py, junto das funções que as calculam.
