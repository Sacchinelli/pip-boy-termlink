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
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

LOGGER = logging.getLogger("pip_boy.banco")

# Versão do formato dos carimbos de tempo. 0 (ausente) é o formato antigo: ISO
# com o fuso LOCAL de quem gravou. 1 é ISO em UTC. Ver ``migrar_para_utc``.
VERSAO_UTC = 1


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
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
