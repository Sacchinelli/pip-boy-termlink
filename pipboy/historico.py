"""Histórico de conversas: o que o tutor ensinou não morre com a janela.

A transcrição sempre existiu — acumulada nas bolhas da conversa — e sempre
foi descartada no fechamento. Para quem estuda, reler a explicação de ontem
vale tanto quanto o caderno de palavras: a palavra sem o contexto em que ela
apareceu é metade da memória.

Banco separado do vocabulário de propósito: o caderno é pequeno, curado e
para sempre; o histórico é volumoso, cronológico e descartável por sessão.
Misturá-los faria o backup diário do caderno carregar megabytes de conversa.

O mesmo contrato de concorrência do ``VocabularyStore``: uma conexão, um
``Lock``, escrita curta. E a mesma regra de privacidade do resto do projeto:
tudo fica em ``%LOCALAPPDATA%``, nada sai da máquina.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .banco import conectar

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessoes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    iniciada_em TEXT NOT NULL,
    jogo        TEXT NOT NULL DEFAULT '',
    modo        TEXT NOT NULL DEFAULT '',
    nivel       TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS falas (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    sessao_id INTEGER NOT NULL REFERENCES sessoes(id) ON DELETE CASCADE,
    quando    TEXT NOT NULL,
    autor     TEXT NOT NULL DEFAULT '',
    tag       TEXT NOT NULL DEFAULT '',
    texto     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_falas_sessao ON falas (sessao_id, id);
CREATE INDEX IF NOT EXISTS idx_sessoes_inicio ON sessoes (iniciada_em DESC);
CREATE TABLE IF NOT EXISTS atividade (
    dia TEXT PRIMARY KEY  -- AAAA-MM-DD, no fuso local de quem estuda
);
"""


# Por quantos dias uma conversa fica guardada.
#
# O caderno tem cópia diária com rotação; o histórico não tinha teto NENHUM.
# Ele guarda transcrições inteiras, cresce todo dia e a única forma de apagar
# era sessão a sessão, à mão, numa lista que só mostra as sessenta mais
# recentes — ou seja: na prática, nunca. Um arquivo que só cresce e que
# ninguém nunca poda é um vazamento com passo lento.
#
# Um ano é deliberadamente generoso: é mais do que qualquer pessoa volta para
# reler, e ainda assim faz o arquivo chegar num tamanho estável em vez de
# subir para sempre. Quem quiser guardar menos apaga à mão; quem quiser
# guardar mais tem aqui a única linha a mudar.
RETENCAO_DIAS: int = 365


def _agora() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class ResumoDeSessao:
    id: int
    iniciada_em: str
    jogo: str
    modo: str
    nivel: str
    falas: int


@dataclass(frozen=True, slots=True)
class Fala:
    quando: str
    autor: str
    tag: str
    texto: str


def sessao_em(periodos: Iterable[tuple[int, str, str]], quando: str) -> int | None:
    """Qual sessão estava acontecendo no instante ``quando``. Sem banco.

    Recebe ``(id, início, fim)`` de cada sessão — o fim sendo a última fala
    dela — e devolve o id da que contém o instante, ou ``None``.

    É o fio entre os dois bancos, que não têm chave estrangeira um para o
    outro de propósito. O que torna isto uma RESPOSTA em vez de um palpite é
    exigir o instante dentro do período fechado, e não apenas depois do
    começo: uma palavra cuja conversa já saiu do histórico — apagada à mão,
    ou podada pela retenção — cairia, com a regra frouxa, na sessão anterior
    que por acaso sobrou, e o jogador abriria uma conversa que nada tem a ver
    com a palavra que ele clicou. Aqui ela devolve ``None``, e quem chamou
    diz que não há o que abrir.

    A última fala serve de fim porque é o único carimbo de fechamento que
    existe: a tabela guarda quando a sessão começou, não quando acabou. Para
    esta pergunta basta — a anotação de vocabulário é ELA MESMA uma fala, e
    entra no histórico no mesmo instante em que a palavra entra no caderno.

    O desempate é por ``(início, id)``, e não só pelo início, porque os
    carimbos têm resolução de UM SEGUNDO: encerrar e recomeçar uma sessão na
    mesma batida do relógio produz dois períodos idênticos. Desempatando só
    pelo início, a resposta passava a depender da ordem em que o banco
    devolveu as linhas — que nenhuma cláusula garante. O id maior é a sessão
    mais nova, que é a resposta certa quando as duas cabem.
    """
    achado: tuple[str, int] | None = None
    for identificador, inicio, fim in periodos:
        if inicio <= quando <= fim and (achado is None or (inicio, identificador) > achado):
            achado = (inicio, identificador)
    return achado[1] if achado is not None else None


class HistoricoStore:
    """Acesso thread-safe ao histórico de sessões."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._connection = conectar(path)
        with self._lock:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.executescript(_SCHEMA)
            self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    # ------------------------------------------------------------- Escrita
    def iniciar_sessao(self, *, jogo: str = "", modo: str = "", nivel: str = "") -> int:
        with self._lock:
            cursor = self._connection.execute(
                "INSERT INTO sessoes (iniciada_em, jogo, modo, nivel) VALUES (?, ?, ?, ?)",
                (_agora(), jogo, modo, nivel),
            )
            self._connection.commit()
            return int(cursor.lastrowid or 0)

    def registrar_fala(self, sessao_id: int, *, autor: str, tag: str, texto: str) -> None:
        texto = texto.strip()
        if not texto:
            return
        with self._lock:
            self._connection.execute(
                "INSERT INTO falas (sessao_id, quando, autor, tag, texto) "
                "VALUES (?, ?, ?, ?, ?)",
                (sessao_id, _agora(), autor, tag, texto),
            )
            self._connection.commit()

    def remover_sessao(self, sessao_id: int) -> bool:
        """Apaga uma sessão e suas falas. Devolve se havia algo para apagar."""
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM sessoes WHERE id = ?", (sessao_id,)
            )
            self._connection.commit()
            return cursor.rowcount > 0

    def podar_antigas(self, dias: int = RETENCAO_DIAS) -> int:
        """Apaga sessões mais velhas que ``dias``. Devolve quantas se foram.

        As falas vão junto pelo ``ON DELETE CASCADE``, e a tabela ``atividade``
        NÃO é tocada: ela guarda um dia por linha, custa nada, e é dela que sai
        a sequência de estudo — podá-la apagaria a única coisa do programa que
        mede constância ao longo de anos.

        Sem ``VACUUM`` de propósito. Ele devolveria o espaço ao sistema de
        arquivos uma vez, ao preço de reescrever o banco inteiro no arranque —
        justo quando a janela está sendo construída. Sem ele, as páginas
        liberadas são reaproveitadas pelas sessões seguintes: o arquivo para de
        crescer, que é o problema real, em vez de encolher e voltar a subir.
        """
        if dias <= 0:
            return 0
        limite = (
            datetime.now(timezone.utc).astimezone() - timedelta(days=dias)
        ).isoformat(timespec="seconds")
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM sessoes WHERE iniciada_em < ?", (limite,)
            )
            self._connection.commit()
            return int(cursor.rowcount or 0)

    def descartar_sessao_vazia(self, sessao_id: int) -> bool:
        """Remove a sessão se ela terminou sem NENHUMA fala gravada.

        Abrir e fechar sem conversar não é história — é ruído que empurraria
        as sessões reais para baixo na lista.
        """
        with self._lock:
            tem_fala = self._connection.execute(
                "SELECT 1 FROM falas WHERE sessao_id = ? LIMIT 1", (sessao_id,)
            ).fetchone()
            if tem_fala is not None:
                return False
            self._connection.execute("DELETE FROM sessoes WHERE id = ?", (sessao_id,))
            self._connection.commit()
            return True

    # ------------------------------------------------------------ Sequência
    # Um dia de estudo é um dia em que QUALQUER coisa aconteceu: uma sessão
    # por voz ou uma rodada de revisão offline. A tabela guarda só o dia —
    # o suficiente para a única pergunta que a sequência responde: "há
    # quantos dias seguidos eu não deixo isto morrer?"

    def marcar_atividade(self, dia: str | None = None) -> None:
        """Registra que hoje (ou o dia dado, AAAA-MM-DD) teve estudo."""
        alvo = dia or datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
        with self._lock:
            self._connection.execute(
                "INSERT OR IGNORE INTO atividade (dia) VALUES (?)", (alvo,)
            )
            self._connection.commit()

    def sequencia_atual(self) -> int:
        """Dias consecutivos de estudo, contando de hoje (ou ontem) para trás.

        Ontem ainda vale: às 8 da manhã, quem estudou todos os dias até a
        véspera não "zerou" — a sequência está viva, esperando o estudo de
        hoje. Só o buraco de um dia inteiro a derruba.
        """
        with self._lock:
            dias = {
                str(r[0]) for r in self._connection.execute("SELECT dia FROM atividade")
            }
        if not dias:
            return 0
        hoje = datetime.now(timezone.utc).astimezone().date()
        inicio = hoje if hoje.isoformat() in dias else hoje - timedelta(days=1)
        if inicio.isoformat() not in dias:
            return 0
        conta = 0
        cursor: date = inicio
        while cursor.isoformat() in dias:
            conta += 1
            cursor -= timedelta(days=1)
        return conta

    # -------------------------------------------------------------- Leitura
    def listar_sessoes(self, limite: int = 60) -> list[ResumoDeSessao]:
        """As sessões mais recentes primeiro, cada uma com sua contagem."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT s.id, s.iniciada_em, s.jogo, s.modo, s.nivel, "
                "COUNT(f.id) AS falas "
                "FROM sessoes s LEFT JOIN falas f ON f.sessao_id = s.id "
                "GROUP BY s.id ORDER BY s.iniciada_em DESC, s.id DESC LIMIT ?",
                (max(1, limite),),
            ).fetchall()
        return [
            ResumoDeSessao(
                int(r["id"]), str(r["iniciada_em"]), str(r["jogo"]),
                str(r["modo"]), str(r["nivel"]), int(r["falas"]),
            )
            for r in rows
        ]

    def sessao(self, sessao_id: int) -> ResumoDeSessao | None:
        """Uma sessão pelo id, ou ``None``.

        Existe à parte de ``listar_sessoes`` porque aquela é uma LISTA, com
        teto: quem chega pelo caderno pede uma sessão específica, que pode ser
        de meses atrás e estar muito além das sessenta mais recentes. Buscá-la
        na lista faria o salto funcionar só para o vocabulário novo — e falhar
        calado justamente no vocabulário antigo, que é o que mais precisa do
        contexto de volta.
        """
        with self._lock:
            row = self._connection.execute(
                "SELECT s.id, s.iniciada_em, s.jogo, s.modo, s.nivel, "
                "COUNT(f.id) AS falas "
                "FROM sessoes s LEFT JOIN falas f ON f.sessao_id = s.id "
                "WHERE s.id = ? GROUP BY s.id",
                (sessao_id,),
            ).fetchone()
        if row is None:
            return None
        return ResumoDeSessao(
            int(row["id"]), str(row["iniciada_em"]), str(row["jogo"]),
            str(row["modo"]), str(row["nivel"]), int(row["falas"]),
        )

    def periodos(self) -> list[tuple[int, str, str]]:
        """``(id, início, fim)`` de cada sessão, para ``sessao_em``.

        Uma consulta só, e não uma por palavra: o caderno resolve o destino de
        até 250 cartões de uma vez, e 250 idas ao banco por tecla digitada na
        busca travariam a janela que a existência desses cartões deveria
        tornar agradável.
        """
        with self._lock:
            rows = self._connection.execute(
                "SELECT s.id, s.iniciada_em, "
                "COALESCE(MAX(f.quando), s.iniciada_em) AS fim "
                "FROM sessoes s LEFT JOIN falas f ON f.sessao_id = s.id "
                "GROUP BY s.id"
            ).fetchall()
        return [(int(r["id"]), str(r["iniciada_em"]), str(r["fim"])) for r in rows]

    def falas_de(self, sessao_id: int) -> list[Fala]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT quando, autor, tag, texto FROM falas "
                "WHERE sessao_id = ? ORDER BY id ASC",
                (sessao_id,),
            ).fetchall()
        return [
            Fala(str(r["quando"]), str(r["autor"]), str(r["tag"]), str(r["texto"]))
            for r in rows
        ]

    def total_sessoes(self) -> int:
        with self._lock:
            return int(
                self._connection.execute("SELECT COUNT(*) FROM sessoes").fetchone()[0]
            )
