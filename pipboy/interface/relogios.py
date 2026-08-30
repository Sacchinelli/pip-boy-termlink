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

from PySide6.QtCore import QElapsedTimer, QTimer
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

# Animação do cenário. 33 ms ≈ 30 quadros por segundo, que basta para partícula
# e tremulação e deixa folga de CPU para o áudio.
INTERVALO_QUADRO = 33

# Sonda de jogo: meio minuto entre olhadas é rápido o bastante para quem acabou
# de abrir o jogo e lento o bastante para ninguém notar.
INTERVALO_SONDA = 30_000

# E uma olhada logo depois de abrir, sem esperar a primeira meia volta.
PRIMEIRA_SONDA = 1_500

# Teto do passo de animação. Se a janela ficou minimizada por um minuto, a
# diferença acumulada teleportaria toda partícula para fora da tela.
PASSO_MAXIMO = 0.1


@dataclass(frozen=True, slots=True)
class Batidas:
    """O que cada relógio faz quando bate.

    ``avancar_cenario`` recebe o tempo decorrido desde o quadro anterior, já
    limitado: quem sabe quanto tempo passou é o relógio, não quem desenha.

    ``deve_animar`` é uma PERGUNTA, e não um valor: a resposta muda quando a
    janela é minimizada, quando o jogador desliga a atmosfera e quando o
    ambiente escolhido não tem camada viva alguma.
    """

    drenar_eventos: Callable[[], None]
    atualizar_medidor: Callable[[], None]
    atualizar_meta: Callable[[], None]
    avancar_cenario: Callable[[float], None]
    sondar_jogo: Callable[[], None]
    deve_animar: Callable[[], bool]


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

    def sincronizar_animacao(self) -> None:
        """Liga o relógio de quadros só quando ele tem para quem desenhar.

        Este programa foi feito para ficar aberto ATRÁS de um jogo, e o relógio
        nunca olhava se a janela estava visível: minimizado, ele seguia
        repintando a sobreposição — grão, varredura e partículas sobre a área
        inteira — trinta vezes por segundo, disputando CPU justamente com o
        jogo que o usuário está jogando. A atmosfera é enfeite; quadro que
        ninguém vê é só calor.
        """
        if self._batidas.deve_animar():
            if not self._quadros.isActive():
                # Recomeça a contagem: sem isto o primeiro passo depois de
                # restaurar a janela seria o tempo inteiro que ela passou oculta.
                self._ultimo_quadro = self._cronometro.elapsed() / 1000.0
                self._quadros.start(INTERVALO_QUADRO)
        else:
            self._quadros.stop()

    def _quadro(self) -> None:
        agora = self._cronometro.elapsed() / 1000.0
        passo = min(PASSO_MAXIMO, max(0.0, agora - self._ultimo_quadro))
        self._ultimo_quadro = agora
        self._batidas.avancar_cenario(passo)
