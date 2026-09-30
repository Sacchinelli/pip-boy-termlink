"""Abertura das conexões SQLite dos dois bancos do programa.

O caderno e o histórico têm ciclos de vida opostos — um é pequeno, curado e
para sempre; o outro é volumoso, cronológico e descartável — mas abrem a
conexão exatamente do mesmo jeito, e é esse jeito que mora aqui.

O modo de diário é o **WAL**, e não o ``delete`` padrão do SQLite. A diferença
aparece na thread da INTERFACE: cada frase transcrita do assistente vira um
``registrar_fala`` com commit próprio, e no modo padrão todo commit paga um
``fsync`` — uma ida ao disco por frase falada, no meio do laço de eventos do
Qt. Com WAL e ``synchronous=NORMAL`` o commit escreve no diário e volta; o
``fsync`` fica para o ponto de controle, fora do caminho da fala.

O que se abre mão com ``NORMAL`` é a durabilidade contra QUEDA DE ENERGIA (os
commits dos últimos instantes podem se perder), não contra queda do programa:
um crash do processo não corrompe nem perde nada, porque o diário já está
escrito em disco. Para uma frase transcrita e uma palavra de vocabulário é a
troca certa — e o caderno, que é o dado que não se recupera, ainda tem a cópia
diária de ``criar_backup``.

Bancos em pasta de rede, ou em sistema de arquivos sem memória compartilhada,
recusam o WAL. A recusa é tratada e silenciosa de propósito: a conexão
continua perfeitamente utilizável no modo antigo, e um caderno que grava
devagar é muito melhor que um caderno que não abre.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

LOGGER = logging.getLogger("pip_boy.banco")

T = TypeVar("T")

# Versão do formato dos carimbos de tempo. 0 (ausente) é o formato antigo: ISO
# com o fuso LOCAL de quem gravou. 1 é ISO em UTC. Ver ``migrar_para_utc``.
VERSAO_UTC = 1


def carimbo(momento: datetime) -> str:
    """Um instante no formato que os dois bancos gravam: ISO, em UTC.

    Existe como função separada — e não embutida no ``agora()`` — porque nem
    todo carimbo gravado é "agora": a próxima revisão de uma palavra é um
    instante no FUTURO, e era exatamente ela que escapava. A conversão para UTC
    mora aqui, num ponto só, de modo que gravar um instante e gravar o instante
    atual passem pela mesma regra em vez de por duas cópias dela.

    Converter antes de formatar é o serviço: receber um ``datetime`` no fuso
    local produz o mesmo texto que receber o equivalente em UTC. É isso que
    torna a invariante testável numa máquina em UTC — o CI roda assim, e nela
    um ``.astimezone()`` indevido sairia idêntico ao certo e não seria pego.
    Passando um fuso explícito, o defeito aparece em qualquer máquina.

    Um ``datetime`` ingênuo é lido como local, que é o que ``astimezone`` já
    faz e o que ``dias_ate_revisao`` presume do outro lado.
    """
    return momento.astimezone(timezone.utc).isoformat(timespec="seconds")


def agora() -> str:
    """O instante atual, no formato que os dois bancos gravam.

    **Em UTC, e não no fuso local.** O programa gravava
    ``2026-08-22T14:03:00-03:00`` e comparava esses carimbos como TEXTO — é
    assim que o SQL responde "esta palavra venceu?" e "esta fala está dentro
    daquela conversa?". A comparação textual só é verdadeira enquanto o
    deslocamento nunca muda: entra o horário de verão, ou a pessoa viaja, e
    duas datas do mesmo instante passam a ordenar errado por uma hora inteira.
    O sintoma é discreto e o diagnóstico é impossível — uma revisão que vence
    cedo demais, uma palavra que aponta para a conversa vizinha.

    Em UTC o deslocamento é sempre o mesmo, e a ordem textual volta a ser a
    ordem do tempo. O fuso local continua existindo onde ele importa, que é na
    tela: quem exibe faz ``.astimezone()``, como o histórico já fazia.

    Duas datas ficam deliberadamente LOCAIS, e não passam por aqui: o dia da
    tabela ``atividade`` (a sequência de estudo é medida nos dias de quem
    estuda, não nos de Greenwich) e o nome do arquivo de backup diário.
    """
    return carimbo(datetime.now(timezone.utc))


def dobrar(texto: str) -> str:
    """Reduz um texto à forma em que a busca compara: sem acento e sem caixa.

    O ``LIKE`` do SQLite só ignora maiúsculas em ASCII — é o próprio manual
    quem avisa. Num programa em português isso não é detalhe: ``'AÇÃO' LIKE
    '%ação%'`` responde FALSO, e quem digitava "missão" no histórico não
    achava a fala em que o assistente escreveu "MISSÃO" — sem nenhum sinal de
    que algo tinha sido perdido, que é a pior forma de uma busca falhar.

    A decomposição NFD separa a letra do acento; descartar as marcas
    combinantes deixa "ação" e "acao" na mesma forma, e o ``casefold`` faz o
    resto. De quebra, quem digita sem acento — o normal em quem tem pressa —
    passa a encontrar o que está acentuado.
    """
    decomposto = unicodedata.normalize("NFD", texto)
    sem_marcas = "".join(c for c in decomposto if not unicodedata.combining(c))
    return sem_marcas.casefold()


def padrao_de_busca(texto: str) -> str:
    """Um trecho digitado, pronto para ``LIKE ? ESCAPE '\\'``. Vazio se não há busca.

    Estava duplicado nos dois bancos, letra por letra, e é o tipo de código em
    que uma correção num lado não chega ao outro: o ``ESCAPE`` existe para que
    um ``%`` digitado não vire curinga e devolva o caderno inteiro.
    """
    alvo = " ".join(texto.split()).strip()
    if not alvo:
        return ""
    escapado = dobrar(alvo).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escapado}%"


def texto_de_busca(*campos: str) -> str:
    """Junta os campos pesquisáveis de uma linha na coluna que a busca varre.

    A quebra de linha separa os campos porque ela é o único caractere que um
    termo de busca não pode conter (``padrao_de_busca`` colapsa todo espaço em
    branco): sem ela, procurar "wasteland ermo" casaria com o fim de um campo
    somado ao começo do seguinte.
    """
    return dobrar("\n".join(campos))


def migrar_para_utc(
    conexao: sqlite3.Connection, tabelas: tuple[tuple[str, tuple[str, ...]], ...]
) -> bool:
    """Reescreve em UTC os carimbos gravados no fuso local. Uma vez por banco.

    O trabalho é feito pelo próprio SQLite: as funções de data dele entendem
    ISO 8601 com deslocamento e sabem normalizá-lo. É uma passada por tabela,
    em vez de uma volta ao Python por linha — o histórico de um ano tem
    dezenas de milhares de falas, e isto roda no arranque.

    Campo vazio fica vazio: ``proxima_revisao = ''`` é o sentinela de "vencida
    agora" e não é data nenhuma, e o ``strftime`` devolveria NULL para ele.
    """
    versao = int(conexao.execute("PRAGMA user_version").fetchone()[0] or 0)
    if versao >= VERSAO_UTC:
        return False
    for tabela, colunas in tabelas:
        for coluna in colunas:
            # Interpolação de nome de tabela/coluna, e não de valor: os nomes
            # vêm das constantes deste programa, nunca de entrada de fora.
            conexao.execute(
                f"UPDATE {tabela} SET {coluna} = "
                f"COALESCE(strftime('%Y-%m-%dT%H:%M:%S+00:00', {coluna}), {coluna}) "
                f"WHERE {coluna} != ''"
            )
    conexao.execute(f"PRAGMA user_version = {VERSAO_UTC}")
    conexao.commit()
    LOGGER.info("Carimbos de tempo convertidos para UTC (versão %s).", VERSAO_UTC)
    return True


def conectar(path: Path) -> sqlite3.Connection:
    """Conexão compartilhada entre threads, com WAL quando o disco permite.

    ``check_same_thread=False`` é seguro aqui porque cada store protege a
    conexão com um ``Lock`` próprio — é o contrato documentado nos dois.
    """
    conexao = sqlite3.connect(path, check_same_thread=False)
    conexao.row_factory = sqlite3.Row
    try:
        modo = conexao.execute("PRAGMA journal_mode=WAL").fetchone()
        efetivo = str(modo[0]).lower() if modo else "?"
        if efetivo == "wal":
            # Só faz sentido acompanhado do WAL: no modo ``delete``, relaxar o
            # synchronous troca desempenho por risco de CORRUPÇÃO, e não apenas
            # pela perda dos últimos commits.
            conexao.execute("PRAGMA synchronous=NORMAL")
        else:
            LOGGER.info("WAL recusado em %s; seguindo no modo %s.", path.name, efetivo)
    except sqlite3.Error:
        LOGGER.info("WAL indisponível em %s; seguindo no modo padrão.", path.name, exc_info=True)
    return conexao

# ------------------------------------------------------------------ Resgate
# SQLITE_CORRUPT e SQLITE_NOTADB: os dois códigos que querem dizer "este
# arquivo não é mais um banco legível". Todo o resto — travado por outro
# processo ou por um antivírus, sem permissão, disco cheio — é passageiro ou é
# do ambiente, e mexer no arquivo por causa deles seria destruir um caderno
# perfeitamente bom.
_CODIGOS_DE_CORRUPCAO = (11, 26)
_FRASES_DE_CORRUPCAO = ("file is not a database", "database disk image is malformed")


@dataclass(frozen=True, slots=True)
class Resgate:
    """O que se fez com um banco que não abria: onde ele foi guardado e o que entrou no lugar."""

    guardado_como: Path
    restaurado_de: Path | None = None


def e_corrupcao(erro: BaseException) -> bool:
    """Se o erro diz que o arquivo está danificado — e não travado ou inacessível.

    Quem decide é o código de erro do SQLite (ou, sem ele, a mensagem): travado
    e sem permissão chegam com os códigos deles, e corrupção nunca chega como
    OperationalError — excluir essa classe à parte não decidiria nada.
    """
    if not isinstance(erro, sqlite3.DatabaseError):
        return False
    codigo = getattr(erro, "sqlite_errorcode", None)
    if codigo is not None:
        return (int(codigo) & 0xFF) in _CODIGOS_DE_CORRUPCAO
    mensagem = str(erro).lower()
    return any(frase in mensagem for frase in _FRASES_DE_CORRUPCAO)


def abrir_com_resgate(
    abrir: Callable[[Path], T], caminho: Path, *, copias: Path | None = None
) -> tuple[T, Resgate | None]:
    """Abre o banco; se ele estiver danificado, guarda-o ao lado e segue sem ele.

    O arquivo danificado nunca é apagado: vai para
    ``nome.danificado-AAAAMMDD-HHMMSS.sqlite3``, com os arquivos do diário
    (-wal, -shm) junto, para quem quiser tentar recuperá-lo. No lugar dele
    entra a cópia mais recente de ``copias`` que abra (as cópias diárias do
    caderno; uma cópia danificada é pulada em favor da anterior), ou um banco
    vazio. Sem isto, um caderno danificado impedia o programa de abrir, e o
    jogador ficava preso até descobrir sozinho qual arquivo renomear numa
    pasta que ele nem sabe que existe — com sete dias de cópias guardadas ao
    lado.

    Devolve o banco aberto e o ``Resgate`` (``None`` quando abriu direto).
    """
    try:
        return abrir(caminho), None
    except sqlite3.DatabaseError as erro:
        if not e_corrupcao(erro):
            raise
        # Uma linha, sem o traço: a pilha de um arquivo danificado não ajuda
        # ninguém, e a mensagem do SQLite já diz o que houve.
        LOGGER.warning(
            "O banco %s está danificado (%s); guardando e seguindo sem ele.", caminho.name, erro
        )

    momento = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    guardado = caminho.with_name(f"{caminho.stem}.danificado-{momento}{caminho.suffix}")
    caminho.replace(guardado)
    for sufixo in ("-wal", "-shm"):
        diario = caminho.with_name(caminho.name + sufixo)
        if diario.exists():
            diario.replace(guardado.with_name(guardado.name + sufixo))

    if copias is not None and copias.is_dir():
        # O nome da cópia é a data (vocabulario-AAAA-MM-DD.sqlite3), então a
        # ordem alfabética inversa é da mais nova para a mais velha.
        for copia in sorted(copias.glob(f"{caminho.stem}-*{caminho.suffix}"), reverse=True):
            shutil.copy2(copia, caminho)
            try:
                return abrir(caminho), Resgate(guardado, copia)
            except sqlite3.DatabaseError as erro:
                if not e_corrupcao(erro):
                    raise
                LOGGER.warning("A cópia %s também está danificada; tentando a anterior.", copia.name)
                caminho.unlink(missing_ok=True)
    return abrir(caminho), Resgate(guardado)


def aviso_de_resgate(o_que: str, resgate: Resgate) -> str:
    """O que dizer ao jogador sobre um banco resgatado, em uma frase só."""
    if resgate.restaurado_de is not None:
        # "vocabulario-2026-09-29" → "29/09".
        _, _, data = resgate.restaurado_de.stem.partition("-")
        partes = data.split("-")
        quando = f"de {partes[2]}/{partes[1]}" if len(partes) == 3 else "mais recente"
        destino = f"foi restaurado da cópia {quando}"
    elif o_que.startswith("O caderno"):
        destino = "não tinha cópia para restaurar, e o programa começou um caderno novo"
    else:
        destino = "recomeçou vazio"
    return (
        f"{o_que} não abria — o arquivo estava danificado — e {destino}. Nada foi apagado: "
        f"o arquivo danificado foi guardado como {resgate.guardado_como.name}, na pasta de dados."
    )
