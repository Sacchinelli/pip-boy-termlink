"""Vínculo entre a coluna lateral e o arquivo de preferências.

Isto era um par de métodos de setenta linhas dentro da ``Janela``, e era o
pedaço dela que menos tinha a ver com ser uma janela: nenhum destes campos
desenha coisa alguma, nenhum reage a evento do Qt, e o que eles fazem —
copiar um punhado de escolhas de um lado para o outro — é a definição de
plumbing. Fora da classe, ele vira uma tabela declarativa: cada escolha diz
onde mora no arquivo, qual é o padrão e, quando o que se vê difere do que se
grava, como traduzir entre os dois.

**A gravação agora acontece na mudança, e não só no fim.** As preferências
eram salvas em dois momentos: ao iniciar uma sessão e ao fechar a janela.
Quem fosse encerrado pelo Windows, ou perdesse energia, perdia tudo que
escolheu naquela execução — e a próxima abertura desmentia, calada, as
escolhas que a pessoa lembrava de ter feito. Agora cada mexida agenda uma
gravação; o atraso junta a rajada de sinais de uma troca de jogo (que
repovoa a lista de personas) numa escrita só.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from ..config import Preferences

LOGGER = logging.getLogger("pip_boy.interface.preferencias")

# Espera depois da última mexida antes de gravar. Trocar de jogo dispara três
# ou quatro sinais em sequência (o jogo, a persona que a lista repovoou, o
# tema); gravar em cada um seria escrever quatro vezes o mesmo arquivo.
ATRASO_DE_GRAVACAO_MS = 800

# Prefixo dos destinos que moram no dicionário ``extras`` em vez de num campo
# declarado do dataclass. Ver ``_ler`` e ``_escrever``.
_EXTRAS = "extras:"


@dataclass(frozen=True, slots=True)
class Escolha:
    """Uma escolha de lista suspensa: onde ela mora e qual é o padrão.

    ``tabela`` traduz entre o rótulo que aparece na tela e o valor gravado.
    Só o ganho do áudio do jogo precisa dela — a tela diz "Baixo", o arquivo
    diz ``0.45`` —, e é por ela existir que a volta (do número para o rótulo)
    tolera o ruído de ponto flutuante em vez de deixar o campo mostrando uma
    opção que não corresponde ao valor em uso.
    """

    destino: str
    campo: Any
    padrao: str
    tabela: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class Marca:
    """Uma caixa marcável e o campo booleano que ela espelha.

    ``ativa`` é uma pergunta feita na hora, e não um valor fixo, porque a
    resposta pode chegar depois da montagem: a lista de dispositivos de áudio
    é levantada numa thread, e até ela voltar não se sabe se existe loopback.

    Respondida com falso, a preferência gravada fica INTACTA em vez de receber
    o estado de uma caixa que o jogador não pôde usar — sem loopback WASAPI o
    chip 'Ouvir o jogo' nasce desmarcado por falta de dispositivo, e salvar
    isso apagaria a escolha de quem apenas trocou de fone.
    """

    destino: str
    chip: Any
    ativa: Callable[[], bool] | None = None

    @property
    def vale(self) -> bool:
        return self.ativa is None or self.ativa()


class VinculoDePreferencias:
    """Espelha a coluna lateral no ``preferencias.json``, nos dois sentidos."""

    def __init__(
        self,
        prefs: Preferences,
        *,
        escolhas: tuple[Escolha, ...],
        marcas: tuple[Marca, ...],
        geometria: Callable[[], str],
        pai: QWidget,
    ) -> None:
        self._prefs = prefs
        self._escolhas = escolhas
        self._marcas = marcas
        self._geometria = geometria
        self._aplicando = False

        self._espera = QTimer(pai)
        self._espera.setSingleShot(True)
        self._espera.setInterval(ATRASO_DE_GRAVACAO_MS)
        self._espera.timeout.connect(self.salvar)

        for escolha in escolhas:
            escolha.campo.currentTextChanged.connect(lambda _: self.agendar())
        for marca in marcas:
            marca.chip.toggled.connect(lambda _: self.agendar())

    # ------------------------------------------------------------- Leitura

    def _ler(self, destino: str) -> Any:
        if destino.startswith(_EXTRAS):
            return self._prefs.extras.get(destino[len(_EXTRAS) :])
        return getattr(self._prefs, destino)

    def _escrever(self, destino: str, valor: Any) -> None:
        if destino.startswith(_EXTRAS):
            self._prefs.extras[destino[len(_EXTRAS) :]] = valor
        else:
            setattr(self._prefs, destino, valor)

    @staticmethod
    def _rotulo_de(valor: Any, tabela: dict[str, Any], padrao: str) -> str:
        """Caminho de volta: do valor gravado para o rótulo da tela."""
        for rotulo, gravado in tabela.items():
            if isinstance(gravado, float) and isinstance(valor, (int, float)):
                if abs(float(valor) - gravado) < 1e-6:
                    return rotulo
            elif gravado == valor:
                return rotulo
        return padrao

    @staticmethod
    def _selecionar(campo: Any, valor: str, padrao: str) -> None:
        """Escolhe ``valor`` se ele existir na lista; senão o padrão; senão o 1º."""
        opcoes = [campo.itemText(i) for i in range(campo.count())]
        if not opcoes:
            return
        escolhido = valor if valor in opcoes else (padrao if padrao in opcoes else opcoes[0])
        campo.setCurrentText(escolhido)

    def aplicar(self) -> None:
        """Leva o arquivo para a tela. A ordem da tabela é a ordem de aplicação.

        Ela importa: o jogo vem antes da persona porque é ele que determina
        quais personas existem na lista.
        """
        self._aplicando = True
        try:
            for escolha in self._escolhas:
                bruto = self._ler(escolha.destino)
                if escolha.tabela is not None:
                    valor = self._rotulo_de(bruto, escolha.tabela, escolha.padrao)
                else:
                    valor = str(bruto or "")
                self._selecionar(escolha.campo, valor, escolha.padrao)
            for marca in self._marcas:
                if marca.vale:
                    marca.chip.setChecked(bool(self._ler(marca.destino)))
        finally:
            self._aplicando = False

    def reaplicar(self, *destinos: str) -> None:
        """Reaplica apenas os destinos nomeados, sem tocar no resto da tela.

        Existe para as escolhas cuja LISTA chega depois da janela: os
        dispositivos de áudio são enumerados numa thread, e quando a lista
        finalmente aparece a preferência gravada precisa ser reoferecida ao
        campo. Reaplicar tudo seria mais simples e estaria errado — no meio
        segundo entre a montagem e a resposta da thread o jogador já pode ter
        trocado o jogo, e a reaplicação desfaria a escolha dele.
        """
        alvos = set(destinos)
        self._aplicando = True
        try:
            for escolha in self._escolhas:
                if escolha.destino in alvos:
                    valor = str(self._ler(escolha.destino) or "")
                    self._selecionar(escolha.campo, valor, escolha.padrao)
            for marca in self._marcas:
                if marca.destino in alvos and marca.vale:
                    marca.chip.setChecked(bool(self._ler(marca.destino)))
        finally:
            self._aplicando = False

    # ------------------------------------------------------------- Escrita

    def agendar(self) -> None:
        """Marca que algo mudou. A gravação sai depois da pausa."""
        if self._aplicando:
            return  # a tela está copiando o arquivo; não é mudança do jogador
        self._espera.start()

    def salvar(self) -> None:
        """Leva a tela para o arquivo, agora."""
        self._espera.stop()
        for escolha in self._escolhas:
            if escolha.campo.count() == 0:
                # Lista ainda vazia (os dispositivos chegam por thread). Gravar
                # o "" que ela devolve apagaria a preferência do jogador com
                # uma resposta que a tela ainda não tinha como dar.
                continue
            rotulo = escolha.campo.currentText()
            if escolha.tabela is not None:
                self._escrever(escolha.destino, escolha.tabela.get(rotulo))
            else:
                self._escrever(escolha.destino, rotulo)
        for marca in self._marcas:
            if marca.vale:
                self._escrever(marca.destino, marca.chip.isChecked())
        self._prefs.extras["geometria"] = self._geometria()
        self._prefs.save()
