"""Caderno de vocabulário persistente.

Toda palavra que o assistente ensina é gravada aqui via function calling. É o
que separa "um tradutor por voz" de "um professor que lembra do que você já
viu" — e o que permite o modo Quiz e a exportação para Anki.

Concorrência: uma única conexão compartilhada com ``check_same_thread=False``,
protegida por um ``Lock``. O volume é de dezenas de escritas por hora; não há
razão para algo mais elaborado.
"""

from __future__ import annotations

import contextlib
import csv
import math
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .banco import conectar

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vocabulario (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    termo           TEXT NOT NULL COLLATE NOCASE,
    traducao        TEXT NOT NULL,
    exemplo         TEXT NOT NULL DEFAULT '',
    jogo            TEXT NOT NULL DEFAULT '',
    criado_em       TEXT NOT NULL,
    visto_em        TEXT NOT NULL,
    encontros       INTEGER NOT NULL DEFAULT 1,
    facilidade      REAL    NOT NULL DEFAULT 2.5,
    intervalo_dias  INTEGER NOT NULL DEFAULT 0,
    proxima_revisao TEXT    NOT NULL DEFAULT '',
    acertos         INTEGER NOT NULL DEFAULT 0,
    erros           INTEGER NOT NULL DEFAULT 0
);
"""

# Índices ficam separados do CREATE TABLE de propósito: num banco antigo, o
# índice de revisão referencia uma coluna que só passa a existir depois da
# migração. A ordem obrigatória é tabela -> ALTER TABLE -> índices.
_INDICES = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_termo ON vocabulario (termo COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_visto ON vocabulario (visto_em DESC);
CREATE INDEX IF NOT EXISTS idx_revisao ON vocabulario (proxima_revisao ASC);
"""

# Colunas adicionadas depois da primeira versão. Bancos criados antes são
# atualizados no lugar, preservando os dados — ninguém perde o caderno por
# atualizar o programa.
_MIGRACOES: tuple[tuple[str, str], ...] = (
    ("facilidade", "REAL NOT NULL DEFAULT 2.5"),
    ("intervalo_dias", "INTEGER NOT NULL DEFAULT 0"),
    ("proxima_revisao", "TEXT NOT NULL DEFAULT ''"),
    ("acertos", "INTEGER NOT NULL DEFAULT 0"),
    ("erros", "INTEGER NOT NULL DEFAULT 0"),
)


# Intervalo a partir do qual uma palavra conta como dominada. Vinte e um dias
# é o ponto em que o SM-2 já a promoveu várias vezes seguidas — antes disso
# "dominada" seria só "acertei uma vez".
DIAS_PARA_DOMINIO = 21

# Filtros do caderno. Ficam aqui, e não na interface, porque quem sabe
# traduzir "difícil" em SQL é o banco.
FILTRO_TODAS = "todas"
FILTRO_REVISAR = "revisar"
FILTRO_DOMINADAS = "dominadas"
FILTRO_DIFICEIS = "dificeis"
FILTROS = (FILTRO_TODAS, FILTRO_REVISAR, FILTRO_DOMINADAS, FILTRO_DIFICEIS)


@dataclass(frozen=True, slots=True)
class Entrada:
    termo: str
    traducao: str
    exemplo: str
    jogo: str
    encontros: int
    visto_em: str
    acertos: int = 0
    erros: int = 0
    intervalo_dias: int = 0
    proxima_revisao: str = ""

    @property
    def dias_ate_revisao(self) -> int:
        """Dias que faltam para a próxima revisão; 0 ou menos = vencida.

        Uma data ilegível (banco editado à mão, versão futura) conta como
        vencida em vez de derrubar a listagem: no pior caso a palavra aparece
        num quiz a mais, o que é inofensivo.
        """
        if not self.proxima_revisao:
            return 0
        try:
            alvo = datetime.fromisoformat(self.proxima_revisao)
        except ValueError:
            return 0
        if alvo.tzinfo is None:
            alvo = alvo.astimezone()
        delta = alvo - datetime.now(timezone.utc).astimezone()
        # Arredonda para cima: faltando 30 h, o honesto é dizer "2 dias", não
        # "1 dia" — a revisão ainda não vence amanhã. Truncar para baixo faria
        # tudo que vence nas próximas 24 h aparecer como "hoje", inclusive o
        # que só vence de madrugada.
        return math.ceil(delta.total_seconds() / 86400)

    @property
    def vencida(self) -> bool:
        return self.dias_ate_revisao <= 0

    @property
    def dominada(self) -> bool:
        return self.intervalo_dias >= DIAS_PARA_DOMINIO


@dataclass(frozen=True, slots=True)
class Estatisticas:
    """Resumo do caderno, para o cabeçalho do visualizador."""

    total: int
    vencidas: int
    dominadas: int
    acertos: int
    erros: int

    @property
    def aproveitamento(self) -> float:
        """Fração de acertos nas revisões; 0.0 quando nunca houve revisão."""
        tentativas = self.acertos + self.erros
        return self.acertos / tentativas if tentativas else 0.0


def _agora() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _semana_de(momento: datetime) -> str:
    """Identificador da semana (segunda a domingo) a que um instante pertence.

    Semana ISO, e não ``%Y-%W``: o segundo reinicia a contagem em 1º de
    janeiro, então a semana que atravessa a virada do ano é PARTIDA em dois
    baldes — 31/dez cai em '2026-52' e 1º/jan, da mesma semana, em '2027-00'.
    Uma vez por ano o painel de progresso mostrava a barra da virada pela
    metade e uma segunda barra fantasma com o resto. O ano ISO acompanha a
    semana em vez de cortá-la ao meio.
    """
    ano, semana, _ = momento.isocalendar()
    return f"{ano:04d}-{semana:02d}"


class VocabularyStore:
    """Acesso thread-safe ao banco de vocabulário.

    Além de guardar termos, agenda revisões por repetição espaçada — uma
    variação enxuta do SM-2 (o algoritmo do Anki). A regra: acertou, o
    intervalo cresce (1 dia, 3 dias, depois multiplicado pela facilidade);
    errou, a palavra volta para revisão imediata e fica um pouco mais
    "difícil". Palavras novas e as importadas de versões antigas vencem na
    hora, para entrarem no primeiro quiz.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._connection = conectar(path)
        with self._lock:
            self._connection.executescript(_SCHEMA)
            existentes = {
                linha[1]
                for linha in self._connection.execute("PRAGMA table_info(vocabulario)")
            }
            for coluna, definicao in _MIGRACOES:
                if coluna not in existentes:
                    self._connection.execute(
                        f"ALTER TABLE vocabulario ADD COLUMN {coluna} {definicao}"
                    )
            self._connection.executescript(_INDICES)
            self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def registrar(
        self, termo: str, traducao: str, exemplo: str = "", jogo: str = ""
    ) -> tuple[Entrada, bool]:
        """Insere ou atualiza um termo. Retorna a entrada e se ela é nova.

        Reencontrar uma palavra não é um erro — é sinal de que ela importa.
        Por isso o contador ``encontros`` sobe em vez de a escrita falhar.
        """
        termo = " ".join(termo.split()).strip()
        if not termo:
            raise ValueError("termo vazio")
        traducao = " ".join(traducao.split()).strip()
        agora = _agora()

        with self._lock:
            cursor = self._connection.execute(
                "SELECT * FROM vocabulario WHERE termo = ? COLLATE NOCASE", (termo,)
            )
            existente = cursor.fetchone()

            if existente is None:
                self._connection.execute(
                    "INSERT INTO vocabulario "
                    "(termo, traducao, exemplo, jogo, criado_em, visto_em, encontros) "
                    "VALUES (?, ?, ?, ?, ?, ?, 1)",
                    (termo, traducao, exemplo, jogo, agora, agora),
                )
                self._connection.commit()
                return Entrada(termo, traducao, exemplo, jogo, 1, agora), True

            encontros = int(existente["encontros"]) + 1
            # Só sobrescreve exemplo/tradução quando o novo dado tem conteúdo.
            nova_traducao = traducao or existente["traducao"]
            novo_exemplo = exemplo or existente["exemplo"]
            self._connection.execute(
                "UPDATE vocabulario SET traducao = ?, exemplo = ?, jogo = ?, "
                "visto_em = ?, encontros = ? WHERE id = ?",
                (
                    nova_traducao,
                    novo_exemplo,
                    jogo or existente["jogo"],
                    agora,
                    encontros,
                    existente["id"],
                ),
            )
            self._connection.commit()
            # Devolve a grafia CANÔNICA já gravada, não a que acabou de chegar:
            # o banco não altera o campo `termo` no update, então retornar a
            # nova faria a interface exibir algo diferente do caderno.
            return (
                Entrada(
                    str(existente["termo"]),
                    nova_traducao,
                    novo_exemplo,
                    jogo or existente["jogo"],
                    encontros,
                    agora,
                ),
                False,
            )

    def consultar(
        self, limite: int | None = 20, jogo: str = "", aleatorio: bool = False
    ) -> list[Entrada]:
        """Palavras do caderno. ``limite=None`` traz o caderno inteiro.

        O teto que existia aqui era de 200 linhas, pensado para não despejar o
        caderno todo dentro de um prompt. Só que a exportação passa por este
        mesmo método: quem tivesse mais de 200 palavras exportava 200 e não
        recebia aviso nenhum. Limitar o que vai para o MODELO é
        responsabilidade de quem fala com ele — ``tools.py`` já corta em 50 —,
        e não deste método, que também serve ao usuário.
        """
        ordem = "RANDOM()" if aleatorio else "visto_em DESC"
        sql = f"SELECT * FROM vocabulario {{filtro}} ORDER BY {ordem} LIMIT ?"
        params: list[object] = []
        filtro = ""
        if jogo:
            filtro = "WHERE jogo = ?"
            params.append(jogo)
        # -1 é como o SQLite escreve "sem limite".
        params.append(-1 if limite is None else max(1, limite))

        with self._lock:
            rows = self._connection.execute(sql.format(filtro=filtro), params).fetchall()
        return [self._linha_para_entrada(r) for r in rows]

    @staticmethod
    def _linha_para_entrada(r: sqlite3.Row) -> Entrada:
        return Entrada(
            r["termo"], r["traducao"], r["exemplo"], r["jogo"], r["encontros"],
            r["visto_em"], int(r["acertos"]), int(r["erros"]),
            int(r["intervalo_dias"]), str(r["proxima_revisao"]),
        )

    # ------------------------------------------------- Repetição espaçada

    _VENCIDAS_WHERE = "(proxima_revisao = '' OR proxima_revisao <= ?)"

    def para_revisar(self, limite: int = 10) -> list[Entrada]:
        """Palavras vencidas, da mais atrasada para a mais recente.

        O vazio ('') ordena antes de qualquer data ISO, então palavras novas e
        as herdadas de versões antigas do banco entram primeiro — exatamente o
        comportamento desejado para o primeiro quiz.
        """
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM vocabulario WHERE "
                + self._VENCIDAS_WHERE
                + " ORDER BY proxima_revisao ASC, visto_em ASC LIMIT ?",
                (_agora(), max(1, min(limite, 50))),
            ).fetchall()
        return [self._linha_para_entrada(r) for r in rows]

    def pendentes(self) -> int:
        """Quantas palavras estão vencidas agora."""
        with self._lock:
            return int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM vocabulario WHERE " + self._VENCIDAS_WHERE,
                    (_agora(),),
                ).fetchone()[0]
            )

    def avaliar(self, termo: str, acertou: bool) -> dict[str, object]:
        """Registra o resultado de uma revisão e agenda a próxima.

        SM-2 simplificado: sem notas de 0 a 5 (inviáveis numa conversa por
        voz), apenas acertou/errou. A ``facilidade`` faz o papel do fator E do
        algoritmo original, limitada entre 1.3 e 3.0.
        """
        termo = " ".join(termo.split()).strip()
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM vocabulario WHERE termo = ? COLLATE NOCASE", (termo,)
            ).fetchone()
            if row is None:
                raise ValueError(f"termo não está no caderno: {termo}")

            facilidade = float(row["facilidade"] or 2.5)
            intervalo = int(row["intervalo_dias"] or 0)
            acertos, erros = int(row["acertos"]), int(row["erros"])

            if acertou:
                acertos += 1
                if intervalo <= 0:
                    intervalo = 1
                elif intervalo == 1:
                    intervalo = 3
                else:
                    intervalo = max(intervalo + 1, round(intervalo * facilidade))
                facilidade = min(3.0, facilidade + 0.1)
                proxima = (
                    datetime.now(timezone.utc).astimezone() + timedelta(days=intervalo)
                ).isoformat(timespec="seconds")
            else:
                erros += 1
                intervalo = 0
                facilidade = max(1.3, facilidade - 0.2)
                proxima = ""  # vencida: volta para o próximo quiz

            self._connection.execute(
                "UPDATE vocabulario SET facilidade = ?, intervalo_dias = ?, "
                "proxima_revisao = ?, acertos = ?, erros = ?, visto_em = ? WHERE id = ?",
                (facilidade, intervalo, proxima, acertos, erros, _agora(), row["id"]),
            )
            self._connection.commit()

        return {
            "termo": str(row["termo"]),
            "acertou": acertou,
            "proxima_revisao_em_dias": intervalo,
            "acertos": acertos,
            "erros": erros,
        }

    def total(self) -> int:
        with self._lock:
            return int(self._connection.execute("SELECT COUNT(*) FROM vocabulario").fetchone()[0])

    # ------------------------------------------------------- Leitura pelo dono
    # O modelo consulta o caderno por ``consultar`` e ``para_revisar``, que são
    # deliberadamente enxutos: o que vai para dentro de um prompt precisa caber
    # nele. Os métodos abaixo servem ao JOGADOR, que quer ver o caderno inteiro
    # e procurar dentro dele — requisitos opostos, e por isso métodos separados.

    def listar(
        self, *, busca: str = "", filtro: str = FILTRO_TODAS, limite: int | None = None
    ) -> list[Entrada]:
        """Palavras do caderno para exibição, filtradas e ordenadas.

        A busca casa termo, tradução e exemplo — quem lembra "aquela do
        stimpak" não lembra necessariamente do termo em inglês. O ``LIKE`` do
        SQLite já ignora maiúsculas em ASCII; ``ESCAPE`` impede que um ``%``
        digitado vire curinga e traga o caderno inteiro.
        """
        condicoes: list[str] = []
        params: list[object] = []

        alvo = " ".join(busca.split()).strip()
        if alvo:
            padrao = "%" + alvo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            condicoes.append(
                "(termo LIKE ? ESCAPE '\\' OR traducao LIKE ? ESCAPE '\\' "
                "OR exemplo LIKE ? ESCAPE '\\')"
            )
            params += [padrao, padrao, padrao]

        if filtro == FILTRO_REVISAR:
            condicoes.append(self._VENCIDAS_WHERE)
            params.append(_agora())
            ordem = "proxima_revisao ASC, visto_em ASC"
        elif filtro == FILTRO_DOMINADAS:
            condicoes.append("intervalo_dias >= ?")
            params.append(DIAS_PARA_DOMINIO)
            ordem = "intervalo_dias DESC, termo COLLATE NOCASE ASC"
        elif filtro == FILTRO_DIFICEIS:
            # Só entra quem já errou: sem isso, toda palavra nunca revisada
            # (0 × 0) apareceria como difícil, que é o oposto do que se procura.
            condicoes.append("erros > 0 AND erros >= acertos")
            ordem = "erros DESC, termo COLLATE NOCASE ASC"
        else:
            ordem = "visto_em DESC"

        onde = ("WHERE " + " AND ".join(condicoes)) if condicoes else ""
        params.append(-1 if limite is None else max(1, limite))
        sql = f"SELECT * FROM vocabulario {onde} ORDER BY {ordem} LIMIT ?"

        with self._lock:
            rows = self._connection.execute(sql, params).fetchall()
        return [self._linha_para_entrada(r) for r in rows]

    def remover(self, termo: str) -> bool:
        """Apaga um termo do caderno. Devolve se havia algo para apagar."""
        termo = " ".join(termo.split()).strip()
        if not termo:
            return False
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM vocabulario WHERE termo = ? COLLATE NOCASE", (termo,)
            )
            self._connection.commit()
            return cursor.rowcount > 0

    def estatisticas(self) -> Estatisticas:
        """Resumo do caderno numa única passagem pela tabela."""
        with self._lock:
            linha = self._connection.execute(
                "SELECT COUNT(*) AS total, "
                f"SUM(CASE WHEN {self._VENCIDAS_WHERE} THEN 1 ELSE 0 END) AS vencidas, "
                "SUM(CASE WHEN intervalo_dias >= ? THEN 1 ELSE 0 END) AS dominadas, "
                "COALESCE(SUM(acertos), 0) AS acertos, "
                "COALESCE(SUM(erros), 0) AS erros "
                "FROM vocabulario",
                (_agora(), DIAS_PARA_DOMINIO),
            ).fetchone()
        return Estatisticas(
            total=int(linha["total"] or 0),
            vencidas=int(linha["vencidas"] or 0),
            dominadas=int(linha["dominadas"] or 0),
            acertos=int(linha["acertos"] or 0),
            erros=int(linha["erros"] or 0),
        )

    # --------------------------------------------------------------- Backup

    def criar_backup(self, pasta: Path, manter: int = 7) -> Path | None:
        """Uma cópia íntegra por dia, com rotação das últimas ``manter``.

        O caderno é o único dado do programa que não se recupera perdendo — a
        conversa se refaz, as preferências se reescolhem, o vocabulário de
        meses não. A cópia usa a API de backup do SQLite (consistente mesmo
        com a conexão aberta), sai UMA vez por dia para não virar ruído de
        disco e devolve ``None`` quando não há o que fazer: caderno vazio não
        merece arquivo, e a cópia de hoje não precisa de irmã gêmea.
        """
        if self.total() == 0:
            return None
        pasta.mkdir(parents=True, exist_ok=True)
        hoje = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
        destino = pasta / f"vocabulario-{hoje}.sqlite3"
        if destino.exists():
            return None

        with self._lock:
            copia = sqlite3.connect(destino)
            try:
                self._connection.backup(copia)
            finally:
                copia.close()

        # Rotação: a lista ordena por nome, e o nome É a data (ISO ordena).
        copias = sorted(pasta.glob("vocabulario-*.sqlite3"))
        for antiga in copias[: -max(1, manter)]:
            # Uma cópia velha presa não pode impedir a nova de existir.
            with contextlib.suppress(OSError):
                antiga.unlink()
        return destino

    # ------------------------------------------------------------- Progresso
    # Consultas do painel de progresso. Devolvem dados prontos para desenhar,
    # sem nenhum vocabulário de interface: rótulo e número, nada mais.

    def novas_por_semana(self, semanas: int = 8) -> list[tuple[str, int]]:
        """Palavras NOVAS por semana, das mais antigas para a atual.

        Semanas sem nenhuma palavra aparecem com zero: um gráfico que pula
        semanas vazias esconde exatamente a informação que ele existe para
        dar — a constância (ou a falta dela).

        O agrupamento é feito em Python, no fuso LOCAL: o strftime do SQLite
        converteria os offsets para UTC, e uma palavra salva no domingo à
        noite cairia na barra da semana errada.

        O rótulo é a SEGUNDA-FEIRA do balde, não "o mesmo dia da semana N
        semanas atrás": o balde vai de segunda a domingo (ver ``_semana_de``),
        e datar uma barra por uma quinta-feira qualquer dentro dela convidava
        a ler o eixo como se cada coluna começasse naquele dia.
        """
        semanas = max(1, semanas)
        with self._lock:
            rows = self._connection.execute("SELECT criado_em FROM vocabulario").fetchall()
        por_semana: dict[str, int] = {}
        for r in rows:
            try:
                quando = datetime.fromisoformat(str(r["criado_em"])).astimezone()
            except ValueError:
                continue  # data ilegível não derruba o painel
            chave = _semana_de(quando)
            por_semana[chave] = por_semana.get(chave, 0) + 1

        resultado: list[tuple[str, int]] = []
        alvo = datetime.now(timezone.utc).astimezone()
        for atras in range(semanas - 1, -1, -1):
            data = alvo - timedelta(weeks=atras)
            segunda = data - timedelta(days=data.weekday())
            resultado.append((segunda.strftime("%d/%m"), por_semana.get(_semana_de(data), 0)))
        return resultado

    def por_jogo(self, limite: int = 6) -> list[tuple[str, int]]:
        """Total de termos por jogo, do maior para o menor."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT COALESCE(NULLIF(jogo, ''), 'Sem jogo') AS rotulo, "
                "COUNT(*) AS total FROM vocabulario "
                "GROUP BY rotulo ORDER BY total DESC, rotulo ASC LIMIT ?",
                (max(1, limite),),
            ).fetchall()
        return [(str(r["rotulo"]), int(r["total"])) for r in rows]

    def dominio(self) -> tuple[int, int, int]:
        """(novas, aprendendo, dominadas) — a régua de progresso do caderno."""
        with self._lock:
            linha = self._connection.execute(
                "SELECT "
                "SUM(CASE WHEN intervalo_dias <= 0 THEN 1 ELSE 0 END) AS novas, "
                "SUM(CASE WHEN intervalo_dias > 0 AND intervalo_dias < ? "
                "    THEN 1 ELSE 0 END) AS aprendendo, "
                "SUM(CASE WHEN intervalo_dias >= ? THEN 1 ELSE 0 END) AS dominadas "
                "FROM vocabulario",
                (DIAS_PARA_DOMINIO, DIAS_PARA_DOMINIO),
            ).fetchone()
        return (
            int(linha["novas"] or 0),
            int(linha["aprendendo"] or 0),
            int(linha["dominadas"] or 0),
        )

    def exportar_csv(self, destino: Path) -> int:
        """Exporta em CSV separado por tabulação, pronto para importar no Anki.

        Anki lê frente/verso separados por tab por padrão; o campo extra vira
        contexto no verso do cartão.
        """
        entradas = self.consultar(limite=None)
        with destino.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
            for e in entradas:
                verso = e.traducao
                if e.exemplo:
                    verso = f"{verso}<br><i>{e.exemplo}</i>"
                writer.writerow([e.termo, verso, e.jogo])
        return len(entradas)

    @staticmethod
    def _celula_markdown(texto: str) -> str:
        """Prepara um texto qualquer para caber numa célula de tabela.

        Duas coisas quebram uma linha de tabela em Markdown, e as duas podem
        vir do modelo sem aviso: a barra vertical, que abre uma coluna nova,
        e a QUEBRA DE LINHA, que termina a linha inteira no meio — o exemplo
        "First line.\\nSecond line." partia a tabela em duas e deixava um
        fragmento órfão fora dela. Escapar só a barra, como antes, cobria
        metade do problema.
        """
        return " ".join(texto.split()).replace("\\", "\\\\").replace("|", "\\|")

    def exportar_markdown(self, destino: Path) -> int:
        entradas = sorted(self.consultar(limite=None), key=lambda e: e.termo.lower())
        celula = self._celula_markdown
        linhas = ["# Vocabulário — Pip-Boy TermLink", ""]
        linhas.append("| Termo | Tradução | Exemplo | Jogo | Vezes |")
        linhas.append("| --- | --- | --- | --- | --- |")
        for e in entradas:
            linhas.append(
                f"| **{celula(e.termo)}** | {celula(e.traducao)} | "
                f"{celula(e.exemplo)} | {celula(e.jogo)} | {e.encontros} |"
            )
        destino.write_text("\n".join(linhas) + "\n", encoding="utf-8")
        return len(entradas)
