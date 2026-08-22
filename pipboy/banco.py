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

def agora() -> str:
    """O instante atual, no formato que os dois bancos gravam.

    Estava duplicado letra por letra em ``vocabulary.py`` e ``historico.py``.
    São duas cópias de uma decisão só — como o programa carimba o tempo — e o
    tipo de código em que uma correção num lado não chega ao outro.
    """
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


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
