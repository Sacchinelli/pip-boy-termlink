"""Os cinco relógios da janela — o que corre, com que passo, e quando para.

A janela é movida por temporizadores, e eles estavam declarados juntos num
método mas geridos separados: um começava e nunca parava, outro só corria
durante a sessão, um terceiro parava com a janela minimizada. A política de
cada um vivia longe da sua declaração, espalhada por três seções da classe.

Reunidos aqui, o passo e a regra de parada de cada relógio ficam lado a lado —
e a razão de cada intervalo pode ser lida sem procurar quem o inicia.

Nenhum deles decide o que fazer quando bate: isso continua sendo da janela,
que é quem tem os widgets. O que mora aqui é a batida.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QElapsedTimer, Qt, QTimer
from PySide6.QtWidgets import QWidget

from ..constants import UI_POLL_INTERVAL_MS

# Fila de eventos da sessão: o passo com que a interface pergunta se a thread
# de sessão disse alguma coisa.
INTERVALO_BOMBA = UI_POLL_INTERVAL_MS

# Medidor de nível: precisa acompanhar a FALA, não o relógio de parede.
INTERVALO_MEDIDOR = 60

# Relógio e consumo da sessão. Meio segundo basta para um mostrador de minutos
# e segundos, e é metade do trabalho de um relógio de um quarto de segundo.
INTERVALO_META = 500

# Animação do cenário em repouso. 33 ms ≈ 30 quadros por segundo, que basta
# para partícula e tremulação e deixa folga de CPU para o áudio.
INTERVALO_QUADRO = 33

# Com o cursor em cima, a janela RESPONDE a ele — luz, anel, ondas —, e 30
# quadros ali se leem como engasgo. O passo passa a seguir a tela: um divisor
# da frequência dela perto de 15 ms, que numa tela de 144 Hz dá 72 quadros,
# cada um exibido por exatamente dois ciclos. Um passo fixo de 16 ms numa tela
# dessas alternaria dois e três ciclos, e o olho lê a alternância como tranco.
PASSO_INTERATIVO_ALVO = 15.0
# Piso do passo: acima de ~80 quadros o custo cresce e ninguém mais percebe.
INTERVALO_INTERATIVO_MINIMO = 12
# Sem saber a frequência da tela, a de 60 Hz.
INTERVALO_INTERATIVO_PADRAO = 17

# Sonda de jogo: meio minuto entre olhadas é rápido o bastante para quem acabou
# de abrir o jogo e lento o bastante para ninguém notar.
INTERVALO_SONDA = 30_000

# E uma olhada logo depois de abrir, sem esperar a primeira meia volta.
PRIMEIRA_SONDA = 1_500

# Teto do passo de animação. Se a janela ficou minimizada por um minuto, a
# diferença acumulada teleportaria toda partícula para fora da tela.
PASSO_MAXIMO = 0.1


def intervalo_interativo(frequencia: float) -> int:
    """O passo dos quadros com o cursor em cima, para uma tela de ``frequencia`` Hz.

    Um número inteiro de ciclos da tela, o mais perto possível de
    ``PASSO_INTERATIVO_ALVO``: 14 ms a 144 Hz, 17 ms a 60 e a 120 Hz.
    """
    if frequencia <= 1.0:
        return INTERVALO_INTERATIVO_PADRAO
    ciclo = 1000.0 / frequencia
    ciclos = max(1, round(PASSO_INTERATIVO_ALVO / ciclo))
    return max(INTERVALO_INTERATIVO_MINIMO, round(ciclo * ciclos))


@dataclass(frozen=True, slots=True)
class Batidas:
    """O que cada relógio faz quando bate.

    ``avancar_cenario`` recebe o tempo decorrido desde o quadro anterior, já
    limitado: quem sabe quanto tempo passou é o relógio, não quem desenha.

    ``deve_animar`` é uma PERGUNTA, e não um valor: a resposta muda quando a
    janela é minimizada, quando o jogador desliga a atmosfera e quando o
    ambiente escolhido não tem camada viva alguma. ``interagindo`` também: é
    verdade enquanto alguma coisa persegue o cursor, e é o que pede o passo
    rápido. ``frequencia_da_tela`` é a da tela onde a janela está agora.
    """

    drenar_eventos: Callable[[], None]
    atualizar_medidor: Callable[[], None]
    atualizar_meta: Callable[[], None]
    avancar_cenario: Callable[[float], None]
    sondar_jogo: Callable[[], None]
    deve_animar: Callable[[], bool]
    interagindo: Callable[[], bool]
    frequencia_da_tela: Callable[[], float]


class Relogios:
    """Dono dos temporizadores da janela principal."""

    def __init__(self, pai: QWidget, batidas: Batidas) -> None:
        self._batidas = batidas
        self._cronometro = QElapsedTimer()
        self._cronometro.start()
        self._ultimo_quadro = 0.0

        self._bomba = QTimer(pai, timeout=batidas.drenar_eventos)
        self._medidor = QTimer(pai, timeout=batidas.atualizar_medidor)
        self._meta = QTimer(pai, timeout=batidas.atualizar_meta)
        self._quadros = QTimer(pai, timeout=self._quadro)
        # Preciso, e não o padrão. No Windows, um relógio comum de 33 ms vira
        # uma mensagem WM_TIMER, que o sistema arredonda para o tique de
        # 15,6 ms do agendador — 46,7 ms, 21 quadros medidos — e só entrega com
        # a fila vazia: com o mouse se mexendo, menos ainda. Era a animação a
        # "15 fps" que se via ao passar o cursor pela janela.
        self._quadros.setTimerType(Qt.TimerType.PreciseTimer)
        self._sonda = QTimer(pai, timeout=batidas.sondar_jogo)

    def iniciar(self) -> None:
        """Põe em marcha os relógios que correm o tempo todo."""
        self._bomba.start(INTERVALO_BOMBA)
        self._meta.start(INTERVALO_META)
        self._sonda.start(INTERVALO_SONDA)
        QTimer.singleShot(PRIMEIRA_SONDA, self._batidas.sondar_jogo)
        self.sincronizar_animacao()

    def medir_entrada(self, ligado: bool) -> None:
        """Liga o medidor de nível. Fora da sessão ele leria zero, 16 vezes por segundo."""
        if ligado and not self._medidor.isActive():
            self._medidor.start(INTERVALO_MEDIDOR)
        elif not ligado and self._medidor.isActive():
            self._medidor.stop()

    @property
    def animando(self) -> bool:
        return self._quadros.isActive()

    @property
    def intervalo(self) -> int:
        """O passo atual do relógio de quadros, em milissegundos."""
        return self._quadros.interval()

    def _intervalo_desejado(self) -> int:
        if self._batidas.interagindo():
            return intervalo_interativo(self._batidas.frequencia_da_tela())
        return INTERVALO_QUADRO

    def sincronizar_animacao(self) -> None:
        """Liga o relógio de quadros só quando ele tem para quem desenhar.

        Este programa foi feito para ficar aberto ATRÁS de um jogo, e o relógio
        nunca olhava se a janela estava visível: minimizado, ele seguia
        repintando a sobreposição — grão, varredura e partículas sobre a área
        inteira — trinta vezes por segundo, disputando CPU justamente com o
        jogo que o usuário está jogando. A atmosfera é enfeite; quadro que
        ninguém vê é só calor.

        Chamada também a cada quadro e a cada movimento do cursor, para trocar
        de passo: rápido enquanto algo persegue o cursor, o de repouso quando
        tudo assentou. É barata — duas perguntas e uma comparação.
        """
        if self._batidas.deve_animar():
            intervalo = self._intervalo_desejado()
            if not self._quadros.isActive():
                # Recomeça a contagem: sem isto o primeiro passo depois de
                # restaurar a janela seria o tempo inteiro que ela passou oculta.
                self._ultimo_quadro = self._cronometro.elapsed() / 1000.0
                self._quadros.start(intervalo)
            elif self._quadros.interval() != intervalo:
                self._quadros.setInterval(intervalo)
        else:
            self._quadros.stop()

    def _quadro(self) -> None:
        agora = self._cronometro.elapsed() / 1000.0
        passo = min(PASSO_MAXIMO, max(0.0, agora - self._ultimo_quadro))
        self._ultimo_quadro = agora
        self._batidas.avancar_cenario(passo)
