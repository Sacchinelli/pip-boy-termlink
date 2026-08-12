"""Testes do núcleo — rodam sem microfone, sem chave de API e sem internet.

Uso:  py tests/test_nucleo.py

Cobrem os módulos puros (dsp, vocabulario, profiles, config). A sessão Live e o
áudio precisam de dispositivos reais e ficam de fora de propósito: um teste que
exige hardware não é executado, e teste não executado não protege nada.
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# A pasta de dados é REDIRECIONADA, não apenas preenchida se faltar. Com
# ``setdefault``, numa máquina que já rodou o programa a variável já existe, e
# ``teste_config`` gravava preferências por cima das do usuário: a suíte que o
# README anuncia como inofensiva ("não precisa de chave nem de microfone")
# apagava o jogo, a voz, o nível e a geometria da janela de quem a rodasse.
# Um teste não pode escrever fora do seu próprio diretório temporário.
_TEMP = tempfile.mkdtemp(prefix="pipboy-testes-")
os.environ["LOCALAPPDATA"] = _TEMP
os.environ["XDG_DATA_HOME"] = _TEMP

# O console do Windows abre em cp1252 quando a página de código do sistema é a
# legada; sem isto, imprimir uma seta derruba a suíte inteira com
# UnicodeEncodeError antes de o primeiro teste terminar.
for fluxo in (sys.stdout, sys.stderr):
    with __import__("contextlib").suppress(AttributeError, ValueError):
        fluxo.reconfigure(encoding="utf-8", errors="replace")

import numpy as np

from pipboy import dsp
from pipboy.config import AppConfiguration, ConfigurationError, Preferences
from pipboy.profiles import (
    JOGOS,
    MODOS,
    NIVEIS,
    PERSONAS,
    VOZES,
    SessionSettings,
    build_greeting,
    build_system_instruction,
)
from pipboy.vocabulary import VocabularyStore

_falhas = 0


def checar(condicao: bool, descricao: str) -> None:
    global _falhas
    if condicao:
        print(f"  ok   {descricao}")
    else:
        _falhas += 1
        print(f"  FALHA  {descricao}")


def teste_dsp() -> None:
    print("dsp")
    pcm = np.array([100, -200, 300], dtype="<i2").tobytes()
    checar(dsp.array_to_pcm(dsp.pcm_to_array(pcm)) == pcm, "ida e volta PCM16")
    checar(list(dsp.downmix_to_mono(np.array([100, 200, 300, 400]), 2)) == [150, 350], "downmix estéreo")
    checar(abs(dsp.resample(np.arange(48000), 48000, 16000).size - 16000) < 20, "reamostragem 48k→16k")
    checar(dsp.mix(np.full(10, 1000), np.full(4, 1000), 0.5).size == 10, "mix preenche fonte curta")
    checar(dsp.mix(np.full(10, 1000), np.full(30, 1000), 0.5).size == 10, "mix trunca fonte longa")
    saturado = dsp.pcm_to_array(dsp.array_to_pcm(dsp.mix(np.full(2, 30000), np.full(2, 30000), 1.0)))
    checar(saturado[0] == 32767, "satura em vez de estourar o int16")
    checar(dsp.rms_level(b"\x00\x00" * 50) == 0.0, "nível de silêncio é zero")


def teste_vocabulario() -> None:
    print("vocabulario")
    store = VocabularyStore(Path(tempfile.mkdtemp()) / "v.sqlite3")
    _, novo = store.registrar("wasteland", "terra devastada", "Welcome to the wasteland.", "Fallout")
    checar(novo, "primeiro registro é novo")
    entrada, novo2 = store.registrar("WASTELAND", "ermo", jogo="Fallout")
    checar(not novo2 and entrada.encontros == 2, "reencontro incrementa em vez de duplicar")
    checar(entrada.termo == "wasteland", "mantém a grafia canônica do banco")
    checar(entrada.exemplo == "Welcome to the wasteland.", "não apaga exemplo com valor vazio")
    checar(store.total() == 1, "índice único ignora maiúsculas")

    store.registrar("ghoul", "carniçal")
    destino = Path(tempfile.mkdtemp()) / "anki.txt"
    checar(store.exportar_csv(destino) == 2, "exportação TSV para Anki")
    checar("\t" in destino.read_text(encoding="utf-8"), "separador é tabulação")

    # Um caderno grande é o caso em que o teto interno de 200 linhas cortava a
    # exportação em silêncio. O volume precisa passar de 200 para o teste
    # significar alguma coisa.
    grande = VocabularyStore(Path(tempfile.mkdtemp()) / "grande.sqlite3")
    for i in range(320):
        grande.registrar(f"termo{i:03d}", f"traducao{i:03d}")
    alvo_tsv = Path(tempfile.mkdtemp()) / "grande.txt"
    alvo_md = alvo_tsv.with_suffix(".md")
    checar(grande.total() == 320, "caderno grande gravado por inteiro")
    checar(grande.exportar_csv(alvo_tsv) == 320, "exportação TSV não trunca em 200")
    checar(
        len(alvo_tsv.read_text(encoding="utf-8").strip().splitlines()) == 320,
        "arquivo TSV tem uma linha por termo",
    )
    checar(grande.exportar_markdown(alvo_md) == 320, "exportação Markdown não trunca em 200")
    checar(len(grande.consultar()) == 20, "consulta sem limite explícito segue enxuta")
    checar(len(grande.consultar(limite=None)) == 320, "limite=None traz o caderno inteiro")
    grande.close()
    try:
        store.registrar("   ", "x")
        checar(False, "recusa termo vazio")
    except ValueError:
        checar(True, "recusa termo vazio")

    # Repetição espaçada
    checar(store.pendentes() == 2, "palavras novas vencem imediatamente")
    r1 = store.avaliar("WASTELAND", True)
    r2 = store.avaliar("wasteland", True)
    r3 = store.avaliar("wasteland", True)
    checar(
        (r1["proxima_revisao_em_dias"], r2["proxima_revisao_em_dias"]) == (1, 3)
        and r3["proxima_revisao_em_dias"] >= 7,
        "intervalos crescem com acertos (1 → 3 → 7+)",
    )
    checar(store.pendentes() == 1, "palavra agendada sai da fila")
    r4 = store.avaliar("wasteland", False)
    checar(
        r4["proxima_revisao_em_dias"] == 0 and store.pendentes() == 2,
        "erro traz a palavra de volta à fila",
    )
    checar(len(store.para_revisar()) == 2, "para_revisar lista as vencidas")
    try:
        store.avaliar("inexistente", True)
        checar(False, "avaliar recusa termo desconhecido")
    except ValueError:
        checar(True, "avaliar recusa termo desconhecido")
    store.close()

    # Migração de banco da versão anterior (sem as colunas de revisão)
    import sqlite3
    legado = Path(tempfile.mkdtemp()) / "legado.sqlite3"
    con = sqlite3.connect(legado)
    con.executescript(
        "CREATE TABLE vocabulario (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "termo TEXT NOT NULL COLLATE NOCASE, traducao TEXT NOT NULL, "
        "exemplo TEXT NOT NULL DEFAULT '', jogo TEXT NOT NULL DEFAULT '', "
        "criado_em TEXT NOT NULL, visto_em TEXT NOT NULL, "
        "encontros INTEGER NOT NULL DEFAULT 1); "
        "INSERT INTO vocabulario (termo, traducao, criado_em, visto_em) "
        "VALUES ('caps', 'tampinhas', '2026-01-01T00:00:00', '2026-01-01T00:00:00');"
    )
    con.commit()
    con.close()
    migrado = VocabularyStore(legado)
    checar(
        migrado.total() == 1 and migrado.pendentes() == 1,
        "banco antigo migra preservando dados e vence na hora",
    )
    migrado.avaliar("caps", True)
    checar(migrado.pendentes() == 0, "palavra migrada aceita avaliação")
    migrado.close()


def teste_portao_de_eco() -> None:
    """A regra que separa o eco acústico do eco digital.

    Regressão de um laço real: com 'Ouvir o jogo' ligado e fone de ouvido, o
    assistente ouvia a própria voz. O loopback WASAPI capta a SAÍDA do sistema,
    onde a fala dele também passa, mas o descarte estava amarrado à caixa
    'Alto-falante (anti-eco)' — que quem usa fone deixa desmarcada, e com razão.
    O modelo transcrevia o próprio assistente como se fosse o jogador, se
    interrompia e recomeçava.
    """
    print("portão de eco")
    try:
        from pipboy.audio import politica_de_portao
    except ImportError as erro:  # pragma: no cover - pyaudio ausente
        print(f"  ....  pulado ({erro.name} não instalado)")
        return

    def regra(**kw: bool) -> tuple[bool, bool]:
        base = {"mudo": False, "falando": False, "portao_acustico": False, "jogo_ligado": False}
        return politica_de_portao(**{**base, **kw})  # type: ignore[arg-type]

    checar(regra() == (True, False), "em repouso, envia o microfone e nada a descartar")
    checar(regra(mudo=True) == (False, False), "mudo corta o envio")

    # O caso que quebrava: fone (portão acústico DESLIGADO) + jogo ligado.
    checar(
        regra(falando=True, jogo_ligado=True) == (True, True),
        "de fone, falando: descarta o loopback mesmo sem portão acústico",
    )
    checar(
        regra(falando=True, jogo_ligado=True, portao_acustico=True) == (False, True),
        "de alto-falante, falando: corta o microfone E descarta o loopback",
    )
    checar(
        regra(falando=True) == (True, False),
        "sem o jogo ligado, falar de fone não bloqueia o microfone (dá para interromper)",
    )
    checar(
        regra(falando=True, portao_acustico=True) == (False, False),
        "o portão acústico continua valendo por conta própria",
    )
    checar(
        regra(mudo=True, jogo_ligado=True) == (False, True),
        "mudo também descarta o jogo, em vez de enfileirá-lo para depois",
    )
    # O descarte NÃO pode depender do portão acústico em nenhuma combinação.
    sem_portao = {regra(falando=True, jogo_ligado=True, portao_acustico=p)[1] for p in (False, True)}
    checar(sem_portao == {True}, "o descarte do loopback independe da caixa de alto-falante")


def teste_portao_de_voz() -> None:
    """Economia de tokens sem comer a fala do jogador.

    Áudio custa ~25 tokens/s por direção e o programa fica aberto enquanto se
    joga: uma hora de sessão em silêncio gastava ~90 mil tokens de entrada. O
    risco do conserto é cortar a pergunta, então o pré-rolo e a cauda são a
    parte que estes testes protegem.
    """
    print("portão de voz")
    try:
        from pipboy.audio import PortaoDeVoz
    except ImportError as erro:  # pragma: no cover
        print(f"  ....  pulado ({erro.name} não instalado)")
        return

    BLOCO = 0.064

    def correr(niveis: list[float], **kw: float) -> tuple[int, PortaoDeVoz]:
        g = PortaoDeVoz(**kw)  # type: ignore[arg-type]
        t, enviados = 0.0, 0
        for n in niveis:
            enviados += len(g.avaliar(b"\x00\x00", n, t))
            t += BLOCO
        return enviados, g

    enviados, g = correr([0.001] * 50)
    checar(enviados == 0 and g.economia == 1.0, "silêncio puro não transmite nada")

    enviados, _ = correr([0.4] * 50)
    checar(enviados == 50, "fala contínua transmite tudo")

    # Pré-rolo: a primeira sílaba acontece ANTES de o nível cruzar o limiar.
    enviados, _ = correr([0.001] * 10 + [0.4] * 5, pre_roll=5, cauda=0.0)
    checar(enviados == 10, "o ataque da fala leva junto os 5 blocos de pré-rolo")
    enviados, _ = correr([0.001] * 10 + [0.4] * 5, pre_roll=0, cauda=0.0)
    checar(enviados == 5, "sem pré-rolo, o ataque seria perdido")

    # Cauda: uma pausa curta no meio da frase não pode fechar o portão.
    pausa = [0.4] * 3 + [0.001] * 4 + [0.4] * 3   # ~256 ms de pausa
    enviados, _ = correr(pausa, pre_roll=0, cauda=0.8)
    checar(enviados == len(pausa), "pausa entre palavras não fecha o portão")
    enviados, _ = correr(pausa, pre_roll=0, cauda=0.0)
    checar(enviados < len(pausa), "sem cauda, a mesma pausa cortaria a frase")

    # Economia realista: alguém que fala 10% do tempo.
    niveis = ([0.001] * 45 + [0.4] * 5) * 4
    _, g = correr(niveis)
    checar(0.4 < g.economia < 0.95, f"sessão esparsa economiza {g.economia:.0%} dos blocos")

    # esquecer() precisa apagar o pré-rolo: são blocos captados enquanto
    # estávamos mudos ou enquanto o assistente falava.
    g = PortaoDeVoz(pre_roll=5, cauda=0.0)
    for i in range(5):
        g.avaliar(b"\x11\x11", 0.001, i * BLOCO)
    g.esquecer()
    saida = g.avaliar(b"\x22\x22", 0.4, 5 * BLOCO)
    checar(saida == [b"\x22\x22"], "esquecer() descarta o pré-rolo retido")

    # O estado de abertura é o que avisa o serviço onde a fala começa e termina.
    # Sem esse aviso o servidor refaz a detecção sozinho e gasta ~580 ms a mais
    # por pergunta (medido: 717 ms contra 136 ms).
    g = PortaoDeVoz(pre_roll=2, cauda=0.0)
    checar(not g.aberto, "portão nasce fechado")
    g.avaliar(b"\x00\x00", 0.001, 0.0)
    checar(not g.aberto, "silêncio não abre")
    g.avaliar(b"\x33\x33", 0.4, BLOCO)
    checar(g.aberto, "fala abre")
    g.avaliar(b"\x00\x00", 0.001, 2 * BLOCO)
    checar(not g.aberto, "silêncio depois da cauda fecha")

    # fechar() existe para o contrato de atividade manual: todo início precisa
    # de um fim, inclusive quando quem interrompe é o mudo ou o assistente.
    g = PortaoDeVoz(pre_roll=0, cauda=0.0)
    g.avaliar(b"\x33\x33", 0.4, 0.0)
    checar(g.fechar(), "fechar() devolve True quando havia fala em curso")
    checar(not g.aberto, "e o portão fica fechado")
    checar(not g.fechar(), "fechar() de novo não inventa um segundo fim de fala")


def teste_economia_com_jogo() -> None:
    """A conta que justifica a janela retroativa do áudio do jogo.

    Antes, o portão media o sinal JÁ MISTURADO. Como jogo em silêncio não
    existe, ele ficava aberto o tempo todo e a sessão gastava os 90 mil
    tokens por hora que o portão foi criado para evitar. Aqui se compara,
    no mesmo material, medir o mix (o jeito antigo) contra medir o
    microfone (o jeito novo).
    """
    print("economia com o jogo ligado")
    from pipboy.audio import PortaoDeVoz
    from pipboy.constants import VOICE_GATE_GAME_CONTEXT_BLOCKS

    bloco = b"\x00\x00" * 512
    # Material realista: ~3,2 minutos de jogo tocando sem parar e o jogador
    # fazendo três perguntas curtas. Um trecho curto demais mediria só a
    # primeira descarga da janela retroativa e diria pouco sobre uma sessão.
    total_blocos = 3000
    nivel_jogo = 0.20  # música e efeitos, bem acima do limiar
    fala_do_jogador: set[int] = set()
    for inicio in (500, 1500, 2500):
        fala_do_jogador |= set(range(inicio, inicio + 20))

    def nivel_do_microfone(i: int) -> float:
        return 0.30 if i in fala_do_jogador else 0.004

    enviados_mix = 0
    portao_mix = PortaoDeVoz(pre_roll=5)
    for i in range(total_blocos):
        # Jeito ANTIGO: o nível avaliado é o do mix, dominado pelo jogo.
        nivel_do_mix = max(nivel_do_microfone(i), nivel_jogo)
        enviados_mix += len(portao_mix.avaliar(bloco, nivel_do_mix, i * 0.064))

    enviados_mic = 0
    portao_mic = PortaoDeVoz(pre_roll=VOICE_GATE_GAME_CONTEXT_BLOCKS)
    for i in range(total_blocos):
        enviados_mic += len(portao_mic.avaliar(bloco, nivel_do_microfone(i), i * 0.064))

    checar(
        enviados_mix == total_blocos,
        f"medindo o mix, TUDO era transmitido ({enviados_mix}/{total_blocos})",
    )
    economia = 1 - enviados_mic / enviados_mix
    checar(
        economia >= 0.75,
        f"medindo o microfone, a economia passa de 75% (deu {economia:.0%}, "
        f"{enviados_mic} blocos contra {enviados_mix})",
    )

    # E o essencial: a pergunta continua chegando com o jogo que a antecedeu.
    portao = PortaoDeVoz(pre_roll=VOICE_GATE_GAME_CONTEXT_BLOCKS)
    for i in range(50):  # 50 blocos de jogo com o jogador calado
        checar_silencio = portao.avaliar(bloco, 0.004, i * 0.064)
        assert checar_silencio == []
    primeira_rajada = portao.avaliar(bloco, 0.30, 50 * 0.064)
    checar(
        len(primeira_rajada) == 51,
        f"ao falar, os 50 blocos de jogo retidos vão junto ({len(primeira_rajada)})",
    )
    checar(
        VOICE_GATE_GAME_CONTEXT_BLOCKS >= 150,
        f"a janela retroativa cobre ~10 s ({VOICE_GATE_GAME_CONTEXT_BLOCKS} blocos)",
    )

    # Redimensionar a janela no meio da sessão (o jogador vira a chave) não
    # descarta o que já estava retido.
    portao2 = PortaoDeVoz(pre_roll=5)
    for i in range(5):
        portao2.avaliar(bloco, 0.004, i * 0.064)
    portao2.definir_pre_rolo(VOICE_GATE_GAME_CONTEXT_BLOCKS)
    saida = portao2.avaliar(bloco, 0.30, 6 * 0.064)
    checar(len(saida) == 6, f"trocar a janela preserva o que já estava retido ({len(saida)})")


def teste_caderno_navegavel() -> None:
    """Busca, filtros, remoção e estatísticas — o que o visualizador consome.

    O modelo lê o caderno por ``consultar``/``para_revisar``, que são enxutos
    de propósito. Estes métodos servem ao jogador, que quer o caderno inteiro
    e procurar dentro dele, e por isso têm regras próprias que precisam ser
    verificadas separadamente.
    """
    print("caderno navegável")
    from pipboy.vocabulary import (
        FILTRO_DIFICEIS,
        FILTRO_DOMINADAS,
        FILTRO_REVISAR,
        FILTRO_TODAS,
    )

    store = VocabularyStore(Path(tempfile.mkdtemp()) / "caderno.sqlite3")
    store.registrar("wasteland", "terra devastada", "Welcome to the wasteland.", "Fallout")
    store.registrar("ghoul", "carniçal", "A ghoul crawls out.", "Fallout")
    store.registrar("thane", "thane", "You are a thane now.", "Skyrim")

    termos = lambda **kw: [e.termo for e in store.listar(**kw)]  # noqa: E731
    checar(len(termos()) == 3, "lista traz o caderno inteiro por padrão")
    checar(termos(busca="devastada") == ["wasteland"], "busca alcança a tradução")
    checar(termos(busca="crawls") == ["ghoul"], "busca alcança o exemplo")
    checar(termos(busca="GHOUL") == ["ghoul"], "busca ignora maiúsculas")
    # Um '%' digitado é literal, não curinga: sem ESCAPE ele traria tudo, e a
    # busca pareceria simplesmente não funcionar.
    checar(termos(busca="%") == [], "curinga digitado não vaza para o LIKE")
    checar(termos(busca="_") == [], "sublinhado digitado não vira curinga")
    checar(len(termos(limite=2)) == 2, "limite corta a listagem")

    checar(len(termos(filtro=FILTRO_REVISAR)) == 3, "tudo novo está vencido")
    checar(termos(filtro=FILTRO_DOMINADAS) == [], "nada dominado no começo")
    checar(termos(filtro=FILTRO_DIFICEIS) == [], "nada difícil antes de errar")

    for _ in range(6):
        store.avaliar("wasteland", True)
    store.avaliar("ghoul", False)
    store.avaliar("ghoul", False)
    checar(termos(filtro=FILTRO_DOMINADAS) == ["wasteland"], "acertos seguidos promovem a dominada")
    checar(termos(filtro=FILTRO_DIFICEIS) == ["ghoul"], "erros repetidos marcam como difícil")
    checar("thane" not in termos(filtro=FILTRO_DIFICEIS), "palavra nunca revisada não é difícil")

    entrada = store.listar(busca="wasteland")[0]
    checar(entrada.dias_ate_revisao > 1 and not entrada.vencida, "palavra agendada não está vencida")
    checar(entrada.dominada, "intervalo longo conta como dominada")
    checar(store.listar(busca="thane")[0].vencida, "sem data agendada, vence agora")

    est = store.estatisticas()
    checar(
        (est.total, est.vencidas, est.dominadas, est.acertos, est.erros) == (3, 2, 1, 6, 2),
        "estatísticas conferem com o conteúdo",
    )
    checar(abs(est.aproveitamento - 0.75) < 1e-9, "aproveitamento é acertos sobre tentativas")
    checar(VocabularyStore(Path(tempfile.mkdtemp()) / "z.sqlite3").estatisticas()
           .aproveitamento == 0.0, "caderno vazio não divide por zero")

    checar(store.remover("WASTELAND"), "remoção ignora maiúsculas")
    checar(not store.remover("wasteland"), "remover duas vezes devolve falso")
    checar(not store.remover("   "), "remover termo vazio é inofensivo")
    checar(store.total() == 2, "remoção diminui o total")
    # 'ghoul' vem primeiro porque avaliar() atualiza visto_em, e a listagem
    # padrão ordena pelo contato mais recente.
    checar(termos(filtro=FILTRO_TODAS) == ["ghoul", "thane"], "removido some da listagem")
    store.close()


def teste_profiles() -> None:
    print("profiles")
    total = 0
    for nivel in NIVEIS:
        for modo in MODOS:
            for jogo in JOGOS:
                s = SessionSettings(
                    next(iter(PERSONAS)), jogo, next(iter(VOZES)), VOZES[next(iter(VOZES))],
                    nivel, modo, False, False, False,
                )
                assert build_system_instruction(s) and build_greeting(s)
                total += 1
    checar(True, f"{total} combinações de prompt montam sem erro")

    com_jogo = SessionSettings(
        next(iter(PERSONAS)), "Fallout", next(iter(VOZES)), VOZES[next(iter(VOZES))],
        next(iter(NIVEIS)), next(iter(MODOS)), False, True, False,
    )
    sem_jogo = SessionSettings(
        next(iter(PERSONAS)), "Fallout", next(iter(VOZES)), VOZES[next(iter(VOZES))],
        next(iter(NIVEIS)), next(iter(MODOS)), False, False, False,
    )
    checar("=== ÁUDIO DO JOGO ===" in build_system_instruction(com_jogo), "bloco de áudio do jogo presente")
    checar("=== ÁUDIO DO JOGO ===" not in build_system_instruction(sem_jogo), "bloco ausente quando desligado")
    checar("registrar_vocabulario" in build_system_instruction(sem_jogo), "instrui o uso da ferramenta")


def teste_config() -> None:
    print("config")
    base = Path(tempfile.mkdtemp())
    os.environ["GEMINI_API_KEY"] = "AIzaTESTE1234567890"
    cfg = AppConfiguration.load(base)
    checar(cfg.redacted_key() == "AIza…7890", "chave é mascarada em log")
    checar("esc" not in cfg.hotkey_toggle.lower(), "atalho global não sequestra Esc")
    checar("f12" not in cfg.hotkey_toggle.lower(), "atalho global não sequestra F12")

    os.environ["GEMINI_API_KEY"] = "cole_sua_chave_aqui"
    try:
        AppConfiguration.load(base)
        checar(False, "rejeita a chave de exemplo")
    except ConfigurationError:
        checar(True, "rejeita a chave de exemplo")

    prefs = Preferences(persona="Instrutor Rígido")
    prefs.save()
    checar(Preferences.load().persona == "Instrutor Rígido", "preferências persistem")

    # Arquivo corrompido. Fica em %LOCALAPPDATA%, é editável à mão e pode ser
    # truncado por uma queda no meio do save. Um `"extras": []` impedia o
    # programa de ABRIR: a interface chama extras.get() e a exceção subia na
    # construção da janela.
    import json as _json
    alvo = Preferences._path()
    alvo.write_text(
        _json.dumps({
            "extras": [1, 2],            # dict virou lista
            "ganho_jogo": "alto",        # float virou texto
            "saida_alto_falante": "sim", # bool virou texto
            "nivel": 123,                # str virou número
            "jogo": "Skyrim",            # este é válido e deve sobreviver
            "ouvir_jogo": True,          # este também
        }),
        encoding="utf-8",
    )
    corrompido = Preferences.load()
    checar(corrompido.extras == {}, "extras com tipo errado volta ao padrão")
    checar(corrompido.ganho_jogo == Preferences().ganho_jogo, "ganho inválido volta ao padrão")
    checar(corrompido.saida_alto_falante is False, "texto não passa por campo booleano")
    checar(corrompido.nivel == "", "número não passa por campo de texto")
    checar(corrompido.jogo == "Skyrim", "campo válido sobrevive ao vizinho corrompido")
    checar(corrompido.ouvir_jogo is True, "booleano válido sobrevive")
    checar(Preferences._compativel(1, 0.5), "int serve num campo float")
    checar(not Preferences._compativel(True, 0.5), "bool NÃO serve num campo float")
    checar(not Preferences._compativel(1, False), "int NÃO serve num campo bool")
    alvo.unlink(missing_ok=True)

    # Gravação da chave pela tela de primeira execução.
    from pipboy.config import data_directory, salvar_chave

    env = data_directory() / ".env"
    env.write_text("GEMINI_MODEL=meu-modelo\n", encoding="utf-8")
    destino = salvar_chave("AIzaNOVA12345678901234")
    conteudo = destino.read_text(encoding="utf-8")
    checar(destino == env, "a chave vai para o .env da pasta de dados")
    checar("GEMINI_API_KEY=AIzaNOVA12345678901234" in conteudo, "chave gravada")
    checar("GEMINI_MODEL=meu-modelo" in conteudo, "linhas alheias sobrevivem")
    checar(os.environ.get("GEMINI_API_KEY", "").startswith("AIzaNOVA"), "processo atual enxerga a chave")
    salvar_chave("AIzaTROCADA1234567890x")
    conteudo = destino.read_text(encoding="utf-8")
    checar(conteudo.count("GEMINI_API_KEY") == 1, "regravar troca a linha em vez de duplicar")
    for invalida in ("", "com espaco aqui", "cole_sua_chave_aqui"):
        try:
            salvar_chave(invalida)
            checar(False, f"rejeita chave inválida: {invalida!r}")
        except ConfigurationError:
            checar(True, f"rejeita chave inválida: {invalida!r}")
    env.unlink(missing_ok=True)


def teste_design() -> None:
    """Contraste e coerência das dez paletas.

    A interface aceita qualquer paleta que alguém acrescente em themes.py. Sem
    esta verificação, um jogo novo com um vermelho bonito e escuro produz
    mensagens de erro ilegíveis — e ninguém descobre, porque a tela de erro é
    justamente a que o desenvolvedor nunca abre.

    Os pares abaixo são os mesmos que a interface realmente pinta, incluindo
    os fundos locais mais claros (chip ligado, cápsula, botão contornado), que
    derivam a cor do texto no ponto de uso.
    """
    print("design")
    from pipboy import design
    from pipboy.themes import TEMAS

    checar(design.contraste("#000000", "#ffffff") > 20.9, "contraste preto/branco é 21:1")
    checar(design.garantir_contraste("#0a1208", "#0a1208") != "#0a1208", "corrige cor sobre si mesma")
    escuro = design.garantir_contraste("#2c7a44", "#0a1208")
    checar(design.contraste(escuro, "#0a1208") >= 4.5, "garantir_contraste atinge o alvo")

    falhas: list[str] = []
    for nome, t in TEMAS.items():
        pares = {
            "corpo no console": (t.primary, t.surface),
            "rótulo no cartão": (t.text_muted, t.surface),
            "sistema no console": (t.accent_text, t.surface),
            "erro no console": (design.garantir_contraste(t.alert, t.alert_bg), t.alert_bg),
            "vocabulário no console": (t.info_text, t.surface),
            "campo de texto": (t.primary, t.surface_alta),
            "rodapé": (t.text_muted, t.screen),
            "botão primário": (t.on_primary, t.primary),
            "botão de estado ligado": (t.on_alert, t.alert),
            # Durante a sessão TODOS os campos ficam travados, e eles são a
            # única indicação de qual jogo, nível e microfone estão valendo.
            # Com a cor 'faint' que se usava aqui, os dez temas ficavam entre
            # 1.02:1 e 1.34:1 — ligar a sessão apagava as próprias escolhas.
            "campo travado": (t.text_disabled, t.surface_alta),
            "chip travado": (
                t.text_disabled, design.misturar(t.screen, t.surface, 0.5)
            ),
        }
        for base, mistura in ((t.accent, 0.10), (t.alert, 0.10)):
            fundo = design.misturar(t.screen, base, mistura)
            pares[f"botão contornado {base}"] = (design.garantir_contraste(base, fundo), fundo)
        pares["chip ligado"] = (
            design.garantir_contraste(t.accent, t.selection),
            t.selection,
        )
        for papel in (t.primary, t.accent, t.secondary):
            fundo = design.misturar(t.screen, papel, 0.16)
            pares[f"cápsula {papel}"] = (design.garantir_contraste(papel, fundo), fundo)

        # Estados do popup do seletor. "Escolhido" e "sob o cursor" precisam ser
        # visualmente distintos E ambos legíveis: o primeiro leva véu de acento,
        # o segundo apenas eleva a superfície em cinza.
        realce_hover = design.elevar(t.screen, 0.18, t.primary)
        pares["item do popup sob o cursor"] = (t.primary, realce_hover)
        for rotulo_item, mistura in (("escolhido", 0.13), ("escolhido sob o cursor", 0.22)):
            fundo_item = design.misturar(t.surface_alta, t.accent, mistura)
            pares[f"item do popup {rotulo_item}"] = (
                design.garantir_contraste(t.accent, fundo_item), fundo_item
            )

        # Texto SELECIONADO. Sem estas propriedades, um QLabel selecionável cai
        # no destaque do sistema — um bloco cinza-lavanda do Windows dentro de
        # um terminal de fósforo. Com elas, o par a verificar deixa de ser
        # texto/superfície e passa a ser texto/realce, que é mais apertado:
        # o realce é 35% de acento sobre a superfície, e portanto mais claro.
        for rotulo_sel, fundo_sel, base_sel in (
            ("seleção na bolha do assistente", t.surface_alta, t.primary),
            ("seleção na bolha do jogador", design.misturar(t.surface, t.accent, 0.22), t.primary),
            ("seleção no exemplo do caderno", t.surface_alta, t.info),
        ):
            css = design.css_selecao(
                fundo_sel, t.accent, design.garantir_contraste(base_sel, fundo_sel)
            )
            realce = css.split("selection-background-color:")[1].split(";")[0].strip()
            frente = css.split("selection-color:")[1].split(";")[0].strip()
            pares[rotulo_sel] = (frente, realce)

        for rotulo, (frente, fundo) in pares.items():
            razao = design.contraste(frente, fundo)
            if razao < 4.5:
                falhas.append(f"{nome} / {rotulo}: {razao:.2f}:1")

    checar(not falhas, f"{len(TEMAS)} temas legíveis (WCAG AA) em todos os fundos")
    for falha in falhas:
        print(f"         {falha}")

    # Uma paleta clara não é usada hoje, mas a derivação não pode quebrar nela.
    checar(design.legivel_sobre("#ffffff").startswith("#0"), "texto escuro sobre fundo claro")
    checar(design.legivel_sobre("#000000").startswith("#f"), "texto claro sobre fundo escuro")


def teste_contagem_tokens() -> None:
    """Totalizador de tokens ao longo de várias conexões.

    O rodapé mostra consumo acumulado, e a sessão troca de conexão sozinha
    várias vezes por hora. Um totalizador que anda para trás é pior que
    nenhum: ele mente sobre o gasto justamente em quem deixa o programa
    aberto por muito tempo.
    """
    print("contagem de tokens")
    try:
        from pipboy.session import ContagemDeTokens
    except ImportError as erro:  # google-genai ausente: o resto da suíte segue
        print(f"  ....  pulado ({erro.name} não instalado)")
        return

    c = ContagemDeTokens()
    checar(c.total == 0, "começa em zero")
    c.registrar(1200)
    c.registrar(5400)
    checar(c.total == 5400, "acompanha o crescimento dentro da conexão")
    c.registrar(5100)
    checar(c.total == 5400, "mensagem fora de ordem não faz o total recuar")

    # Conexão nova cuja contagem REINICIA: é o caso que quebrava o rodapé.
    c.nova_conexao()
    c.registrar(300)
    checar(c.total == 5700, "reinício de contagem soma em vez de zerar")
    c.registrar(900)
    checar(c.total == 6300, "segue somando sobre o histórico")

    # Conexão nova cuja contagem CONTINUA: somar de novo contaria em dobro.
    c.nova_conexao()
    c.registrar(1500)
    checar(c.total == 6900, "contagem contínua não é contada duas vezes")

    c2 = ContagemDeTokens()
    c2.registrar(0)
    c2.registrar(-5)
    checar(c2.total == 0, "ignora leitura vazia ou negativa")


def teste_classificacao_de_erro() -> None:
    """Tradução de falha do serviço em explicação para o jogador.

    É a parte mais densa de session.py e a única que o jogador lê num dia
    ruim. Vive de casos-limite conhecidos: a Live API entrega cota esgotada
    fechando o WebSocket com 1011 — "erro interno", que NÃO é status HTTP —,
    e a versão antiga declarava "cota esgotada" sempre que a sequência '429'
    aparecesse em qualquer lugar da mensagem, identificador de requisição
    incluído. Nenhum dos dois defeitos aparece sem exercitar o classificador.
    """
    print("classificação de erro")
    try:
        from pipboy.session import LiveSessionWorker as W
    except ImportError as erro:
        print(f"  ....  pulado ({erro.name} não instalado)")
        return

    def erro_de(mensagem: str, **campos: object) -> Exception:
        e = Exception(mensagem)
        for nome, valor in campos.items():
            setattr(e, nome, valor)
        return e

    # -- extração de código: campo estruturado ganha do texto
    codigo, status, _ = W._detalhes_erro(erro_de("qualquer", code=429, status="RESOURCE_EXHAUSTED"))
    checar((codigo, status) == (429, "RESOURCE_EXHAUSTED"), "lê code e status estruturados")

    checar(W._detalhes_erro(erro_de("falha em gemini-429-flash"))[0] is None,
           "429 dentro de um identificador não vira código")
    checar(W._detalhes_erro(erro_de("erro na versão v2.404.1"))[0] is None,
           "número dentro de uma versão não vira código")
    checar(W._detalhes_erro(erro_de("conectando em port 5000"))[0] is None,
           "número fora da faixa de status não vira código")
    checar(W._detalhes_erro(erro_de("max tokens 4096 excedido"))[0] is None,
           "limite de tokens não é confundido com status")
    checar(W._detalhes_erro(erro_de("servidor devolveu 503"))[0] == 503,
           "código HTTP delimitado é reconhecido")
    checar(W._detalhes_erro(erro_de("fechou com 1011"))[0] == 1011,
           "código de fechamento de WebSocket é reconhecido")

    # -- o CONTEÚDO manda no número: cota chega como 1011, não como 429
    dica = W._dica(1011, "", "You exceeded your current quota, please check your plan and billing")
    checar("Cota do modelo esgotada" in dica, "cota vestida de 1011 ainda é cota")
    checar("ai.dev/rate-limit" in dica, "a dica de cota aponta onde ver o limite real")

    diaria = W._dica(429, "", "Quota exceeded for quota metric 'Requests per day'")
    checar("DIÁRIO" in diaria, "limite por dia é distinguido do limite por minuto")
    checar("DIÁRIO" not in W._dica(429, "", "quota exceeded"), "cota genérica não vira diária")

    # -- a busca na web tem cota PRÓPRIA e usa a mesma frase genérica de cota:
    #    sem saber que a conexão pedia a ferramenta, a dica acusa o modelo.
    cota = "You exceeded your current quota, please check your plan and billing"
    com_busca = W._dica(1011, "", cota, busca_web=True)
    checar("BUSCA NA WEB" in com_busca, "com a busca ligada, a dica acusa a busca")
    checar("Cota do modelo esgotada" not in com_busca, "e não culpa a cota do modelo")
    checar("Cota do modelo esgotada" in W._dica(1011, "", cota, busca_web=False),
           "sem a busca ligada, a dica antiga permanece")
    checar("BUSCA NA WEB" not in W._dica(404, "", "", busca_web=True),
           "a busca só é acusada em erro de cota, não em qualquer falha")
    checar("BUSCA NA WEB" in W._friendly_error(erro_de(cota, code=1011), busca_web=True),
           "a tradução completa também repassa o aviso da busca")

    # -- o classificador de cota, isolado: é ele que decide o desligamento
    checar(W._e_cota(1011, "", cota), "cota vestida de 1011 é cota")
    checar(W._e_cota(429, "", "qualquer coisa"), "429 é cota")
    checar(W._e_cota(None, "RESOURCE_EXHAUSTED", ""), "status sozinho basta")
    checar(not W._e_cota(1008, "", "invalid authentication credentials"),
           "recusa por credencial NÃO é cota — desligar a busca não a resolveria")

    checar("política" in W._dica(1008, "", ""), "1008 é recusa por política")
    checar("instabilidade de rede" in W._dica(1006, "", ""), "1006 é queda abrupta")
    checar("Chave de API inválida" in W._dica(401, "", ""), "401 fala da chave")
    checar("Chave de API inválida" in W._dica(None, "PERMISSION_DENIED", ""), "status sozinho basta")
    checar("Modelo não encontrado" in W._dica(404, "", ""), "404 fala do modelo")
    checar("voz não" in W._dica(400, "", ""), "400 fala da configuração da sessão")
    checar("temporariamente indisponível" in W._dica(503, "", ""), "503 é indisponibilidade")
    checar("Não é problema da sua configuração" in W._dica(500, "", ""), "5xx é do lado do serviço")
    checar("conexão de internet" in W._dica(None, "", "getaddrinfo failed"), "falha de DNS é rede")
    checar(W._dica(None, "", "algo totalmente novo") == "", "erro desconhecido não recebe palpite")

    # -- a mensagem original NUNCA é descartada: era o defeito da versão antiga
    texto = W._friendly_error(erro_de("Detalhe cru do serviço", code=503))
    checar("Detalhe cru do serviço" in texto, "a resposta do serviço sobrevive à tradução")
    checar("[HTTP 503]" in texto, "código HTTP é rotulado como HTTP")
    checar("[WebSocket 1011]" in W._friendly_error(
        erro_de("quota exceeded", code=1011)), "código de socket é rotulado como WebSocket")
    sem_dica = W._friendly_error(erro_de("pane sem categoria conhecida"))
    checar("pipboy.log" in sem_dica, "sem dica, o jogador é mandado ao registro")
    checar("pane sem categoria conhecida" in sem_dica, "e a mensagem crua vai junto")

    longa = W._friendly_error(erro_de("x" * 400, code=503))
    checar("…" in longa, "resposta muito longa é truncada")


def teste_ferramentas() -> None:
    """Despacho das ferramentas que o modelo chama.

    É por aqui que o caderno é escrito: tudo o que chega vem do modelo, e
    nenhuma entrada malformada pode escapar como exceção — a Live API espera
    um FunctionResponse de volta, e uma exceção aqui mataria a conversa em vez
    de uma chamada.
    """
    print("ferramentas do modelo")
    try:
        from pipboy.tools import ToolDispatcher, build_tools
    except ImportError as erro:
        print(f"  ....  pulado ({erro.name} não instalado)")
        return

    declaradas = build_tools()[0].function_declarations
    nomes = {d.name for d in declaradas or ()}
    checar(
        nomes == {"registrar_vocabulario", "consultar_vocabulario", "avaliar_vocabulario"},
        f"as três ferramentas são declaradas ({sorted(nomes)})",
    )
    checar(len(build_tools(web_search=True)) == 2, "busca na web acrescenta uma ferramenta")
    checar(len(build_tools(web_search=False)) == 1, "sem busca, só as nossas")

    store = VocabularyStore(Path(tempfile.mkdtemp()) / "t.sqlite3")
    vistos: list[tuple[str, str, bool]] = []
    revisados: list[tuple[str, bool, int]] = []
    d = ToolDispatcher(
        store, jogo="Fallout",
        on_vocab=lambda t, tr, nova: vistos.append((t, tr, nova)),
        on_review=lambda t, ok, dias: revisados.append((t, ok, dias)),
    )

    r = d.dispatch("registrar_vocabulario", {"termo": "wasteland", "traducao": "terra devastada"})
    checar(r["status"] == "salvo" and r["novo"] is True, "registro novo é salvo")
    checar(vistos == [("wasteland", "terra devastada", True)], "a interface é avisada da palavra")
    checar(d.dispatch("registrar_vocabulario",
                      {"termo": "wasteland", "traducao": "ermo"})["novo"] is False,
           "reencontro não é palavra nova")
    checar(store.total() == 1, "reencontro não duplica no caderno")

    # Entradas que o modelo produz de verdade quando erra o esquema.
    checar("erro" in d.dispatch("registrar_vocabulario", {"termo": "só isso"}),
           "registro sem tradução é recusado com erro, não com exceção")
    checar("erro" in d.dispatch("registrar_vocabulario", {"termo": "  ", "traducao": "x"}),
           "termo em branco é recusado")
    checar("erro" in d.dispatch("ferramenta_que_nao_existe", {}),
           "ferramenta desconhecida devolve erro em vez de estourar")
    checar("erro" in d.dispatch("avaliar_vocabulario", {"termo": "nunca visto", "acertou": True}),
           "avaliar palavra fora do caderno vira erro, não exceção")
    checar(d.dispatch("registrar_vocabulario", None) is not None,  # type: ignore[arg-type]
           "args nulos não derrubam o despacho")

    # O teto por consulta é o que separa uma resposta de ferramenta de um
    # despejo de caderno dentro do prompt.
    for i in range(40):
        store.registrar(f"termo{i}", f"traducao{i}", "x" * 300, "Fallout")
    consulta = d.dispatch("consultar_vocabulario", {"quantidade": 999})
    checar(len(consulta["palavras"]) == d.MAX_PALAVRAS, "quantidade absurda é limitada ao teto")
    checar(len(d.dispatch("consultar_vocabulario", {"quantidade": 0})["palavras"]) == 1,
           "quantidade zero vira um, não uma lista vazia")
    checar(len(d.dispatch("consultar_vocabulario", {"quantidade": "muitas"})["palavras"]) == 10,
           "quantidade não numérica cai no padrão")
    exemplos = [p["exemplo"] for p in consulta["palavras"] if "exemplo" in p]
    checar(all(len(e) <= d.MAX_EXEMPLO for e in exemplos), "exemplo longo é cortado")
    checar(all("erros" not in p for p in consulta["palavras"]),
           "campo zerado não gasta token: sai da resposta")

    d.dispatch("avaliar_vocabulario", {"termo": "WASTELAND", "acertou": True})
    checar(revisados and revisados[-1][0] == "wasteland",
           "a avaliação devolve a grafia canônica do caderno, não a do modelo")
    checar(revisados[-1][2] >= 1, "acerto agenda a palavra para o futuro")


def teste_versao() -> None:
    """A versão declarada em dois lugares precisa ser a mesma."""
    print("versão")
    import re

    import pipboy

    texto = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    achado = re.search(r'(?m)^version\s*=\s*"([^"]+)"', texto)
    checar(achado is not None, "pyproject declara uma versão")
    if achado is not None:
        checar(
            achado.group(1) == pipboy.__version__,
            f"pyproject ({achado.group(1)}) e __version__ ({pipboy.__version__}) concordam",
        )


def teste_revisao() -> None:
    """Rodada de revisão offline.

    O contrato é o do Anki: fila fotografada na abertura, errar devolve a
    palavra à dívida (mas só para a PRÓXIMA rodada) e a rodada sabe quando
    acabou. É a lógica que os cartões da interface apenas desenham.
    """
    print("revisão offline")
    from pipboy.revisao import RodadaDeRevisao

    vazio = VocabularyStore(Path(tempfile.mkdtemp()) / "r0.sqlite3")
    rodada_vazia = RodadaDeRevisao(vazio)
    checar(rodada_vazia.total == 0 and rodada_vazia.terminada, "fila vazia já nasce terminada")
    checar(rodada_vazia.atual is None, "sem cartão atual na fila vazia")

    store = VocabularyStore(Path(tempfile.mkdtemp()) / "r1.sqlite3")
    for termo, traducao in (("stimpak", "estimulante"), ("ghoul", "carniçal"), ("perk", "vantagem")):
        store.registrar(termo, traducao, jogo="Fallout")

    rodada = RodadaDeRevisao(store)
    checar(rodada.total == 3, "as três vencidas entram na rodada")
    checar(rodada.posicao == 1 and not rodada.terminada, "começa no primeiro cartão")
    assert rodada.atual is not None

    dias = rodada.responder(True)
    checar(dias >= 1, "acerto agenda a palavra para o futuro")
    checar(rodada.acertos == 1 and rodada.posicao == 2, "acerto conta e avança")

    dias = rodada.responder(False)
    checar(dias == 0, "erro devolve a palavra à dívida imediata")
    checar(rodada.erros == 1, "erro conta")
    checar(rodada.total == 3, "a fila é fotografia: errar não a faz crescer")

    rodada.responder(True)
    checar(rodada.terminada and rodada.atual is None, "fila esgotada termina a rodada")
    try:
        rodada.responder(True)
        checar(False, "responder após o fim deveria falhar")
    except RuntimeError:
        checar(True, "responder após o fim deveria falhar")

    checar(store.pendentes() == 1, "só a errada continua vencida no banco")


def teste_backup() -> None:
    """Cópia diária do caderno com rotação.

    O contrato: caderno vazio não gera arquivo, a cópia é íntegra e legível,
    o mesmo dia não gera duas, e a rotação apaga da mais antiga em diante.
    """
    print("backup")
    pasta = Path(tempfile.mkdtemp()) / "backups"

    vazio = VocabularyStore(Path(tempfile.mkdtemp()) / "b0.sqlite3")
    checar(vazio.criar_backup(pasta) is None, "caderno vazio não gera cópia")

    store = VocabularyStore(Path(tempfile.mkdtemp()) / "b1.sqlite3")
    store.registrar("stimpak", "estimulante")
    store.registrar("ghoul", "carniçal")
    copia = store.criar_backup(pasta)
    checar(copia is not None and copia.is_file(), "primeira cópia do dia é criada")
    assert copia is not None
    restaurado = VocabularyStore(copia)
    checar(restaurado.total() == 2, "a cópia é um caderno íntegro e legível")
    restaurado.close()
    checar(store.criar_backup(pasta) is None, "segunda cópia no mesmo dia não sai")

    # Rotação: cópias de dias anteriores (forjadas pelo nome) somem primeiro.
    for dia in ("2020-01-01", "2020-01-02", "2020-01-03"):
        (pasta / f"vocabulario-{dia}.sqlite3").write_bytes(b"velho")
    copia.unlink()  # libera o dia de hoje para uma nova cópia
    store.criar_backup(pasta, manter=2)
    nomes = sorted(p.name for p in pasta.glob("vocabulario-*.sqlite3"))
    checar(len(nomes) == 2, "rotação mantém só as N mais novas")
    checar("vocabulario-2020-01-01.sqlite3" not in nomes, "a mais antiga é a primeira a ir")


def teste_progresso() -> None:
    """Consultas do painel de progresso.

    Elas devolvem rótulo e número prontos para desenhar; o contrato central
    é não mentir por omissão — semana sem palavra aparece com zero, jogo sem
    nome vira 'Sem jogo', caderno vazio não divide por zero.
    """
    print("progresso")
    store = VocabularyStore(Path(tempfile.mkdtemp()) / "p.sqlite3")

    semanas = store.novas_por_semana(8)
    checar(len(semanas) == 8, "sempre devolve o número pedido de semanas")
    checar(all(v == 0 for _, v in semanas), "caderno vazio é uma linha de zeros")
    checar(store.por_jogo() == [], "sem palavras, sem barras de jogo")
    checar(store.dominio() == (0, 0, 0), "domínio zerado no caderno vazio")

    store.registrar("stimpak", "estimulante", jogo="Fallout")
    store.registrar("ghoul", "carniçal", jogo="Fallout")
    store.registrar("bonfire", "fogueira", jogo="Elden Ring")
    store.registrar("perk", "vantagem")  # sem jogo

    semanas = store.novas_por_semana(8)
    checar(semanas[-1][1] == 4, "as quatro palavras caem na semana atual")
    checar(sum(v for _, v in semanas) == 4, "nenhuma palavra some do histograma")

    jogos = store.por_jogo()
    checar(jogos[0] == ("Fallout", 2), "o jogo com mais termos vem primeiro")
    checar(("Sem jogo", 1) in jogos, "palavra sem jogo não desaparece")

    novas, aprendendo, dominadas = store.dominio()
    checar((novas, aprendendo, dominadas) == (4, 0, 0), "tudo começa como novo")
    store.avaliar("stimpak", True)
    novas, aprendendo, dominadas = store.dominio()
    checar((novas, aprendendo) == (3, 1), "um acerto move a palavra para aprendendo")


def teste_regressoes() -> None:
    """Defeitos que já existiram uma vez. Cada linha aqui é uma cicatriz.

    Todos foram encontrados executando caminhos-limite, não lendo o código —
    e é executando que eles ficam impedidos de voltar.
    """
    print("regressões do núcleo")
    from pipboy.config import data_directory, salvar_chave
    from pipboy.revisao import RodadaDeRevisao

    # 1. Quebra de linha no exemplo partia a tabela do Markdown em duas, e o
    #    pedaço órfão saía fora da tabela.
    store = VocabularyStore(Path(tempfile.mkdtemp()) / "reg.sqlite3")
    store.registrar("line break", "quebra", "First.\nSecond. | com barra", "Fallout")
    store.registrar("normal", "normal", "Uma frase.", "Fallout")
    alvo = Path(tempfile.mkdtemp()) / "reg.md"
    store.exportar_markdown(alvo)
    linhas = alvo.read_text(encoding="utf-8").splitlines()
    tabela = [ln for ln in linhas if ln.startswith("|")]
    orfas = [ln for ln in linhas[2:] if ln.strip() and not ln.startswith("|")]
    checar(len(tabela) == 4, f"Markdown: cabeçalho, régua e dois termos ({len(tabela)})")
    checar(not orfas, f"Markdown: nenhuma linha órfã fora da tabela ({orfas})")
    checar(
        all(ln.count("|") - ln.count("\\|") == 6 for ln in tabela[2:]),
        "Markdown: toda linha de termo tem exatamente cinco colunas",
    )

    # 2. Responder um cartão cuja palavra saiu do caderno levantava ValueError
    #    de dentro de um slot do Qt — caixa de erro por causa de um apagar.
    rodada = RodadaDeRevisao(store)
    cartao = rodada.atual
    assert cartao is not None
    store.remover(cartao.termo)
    try:
        dias = rodada.responder(True)
        checar(dias == 0, "cartão removido no meio da rodada avança em silêncio")
    except Exception as erro:
        checar(False, f"cartão removido no meio da rodada avança em silêncio ({erro!r})")
    checar(rodada.acertos == 0, "cartão que sumiu não conta como acerto")

    # 3. Aspas coladas junto da chave iam cruas para o .env: o dotenv as
    #    descascava na execução seguinte, mas a atual falhava na conexão.
    env = data_directory() / ".env"
    env.unlink(missing_ok=True)
    salvar_chave('  "AIzaCOM_ASPAS_1234567"  ')
    linha_chave = next(
        ln for ln in env.read_text(encoding="utf-8").splitlines()
        if ln.startswith("GEMINI_API_KEY")
    )
    checar(linha_chave == "GEMINI_API_KEY=AIzaCOM_ASPAS_1234567", "aspas são descascadas")
    checar(os.environ["GEMINI_API_KEY"] == "AIzaCOM_ASPAS_1234567", "e o processo atual concorda")
    env.unlink(missing_ok=True)

    # 4. A fila entre captura e envio era menor que a rajada que o próprio
    #    portão produz. Ao abrir com 'Ouvir o jogo', ele entrega o pré-rolo
    #    INTEIRO — dez segundos, 157 blocos — contra uma fila de 64. A thread
    #    de captura ficava presa enfileirando, o microfone não era lido, e o
    #    driver descartava calado justamente o ataque da pergunta que o
    #    pré-rolo existe para salvar. É uma relação entre duas constantes, e
    #    só um teste que as compare impede que ela volte a se desencontrar.
    from pipboy.audio import PortaoDeVoz
    from pipboy.constants import (
        CAPTURE_QUEUE_BLOCKS,
        VOICE_GATE_GAME_CONTEXT_BLOCKS,
        VOICE_GATE_PREROLL_BLOCKS,
    )

    portao = PortaoDeVoz(limiar=0.5, pre_roll=VOICE_GATE_GAME_CONTEXT_BLOCKS, cauda=0.0)
    for i in range(VOICE_GATE_GAME_CONTEXT_BLOCKS * 2):  # enche a janela retida
        portao.avaliar(bytes([i % 256]) * 2, 0.0, float(i))
    rajada = portao.avaliar(b"\xff\xff", 0.9, 1e6)  # a fala começa
    checar(
        len(rajada) == VOICE_GATE_GAME_CONTEXT_BLOCKS + 1,
        f"a abertura entrega o pré-rolo inteiro de uma vez ({len(rajada)})",
    )
    checar(
        len(rajada) <= CAPTURE_QUEUE_BLOCKS,
        f"a fila de captura ({CAPTURE_QUEUE_BLOCKS}) comporta a rajada ({len(rajada)})",
    )
    checar(
        VOICE_GATE_GAME_CONTEXT_BLOCKS > VOICE_GATE_PREROLL_BLOCKS,
        "a janela do jogo é a maior das duas — é ela que dimensiona a fila",
    )

    # 5. Reconexão sem teto: zerar o contador por TRÁFEGO fazia uma conexão que
    #    responde um erro e desliga reconectar para sempre, uma vez por segundo,
    #    consumindo cota a cada volta.
    try:
        from pipboy.constants import MAX_RECONNECT_ATTEMPTS
        from pipboy.session import politica_de_reconexao
    except ImportError as erro:
        print(f"  ....  reconexão pulada ({erro.name} não instalado)")
        return

    tentativa, esperas = 0, []
    for _ in range(MAX_RECONNECT_ATTEMPTS + 3):
        # Conexão que morre na hora: é o caso que antes reconectava eternamente.
        tentativa, espera = politica_de_reconexao(duracao=0.4, tentativa=tentativa)
        if espera is None:
            break
        esperas.append(espera)
    checar(
        len(esperas) == MAX_RECONNECT_ATTEMPTS,
        f"conexão que morre na hora desiste após {MAX_RECONNECT_ATTEMPTS} ({len(esperas)})",
    )
    checar(esperas == sorted(esperas) and esperas[0] < esperas[-1], "a espera cresce a cada falha")
    checar(all(e <= 20.0 for e in esperas), "a espera respeita o teto")

    # Conexão longa é o fim natural do WebSocket: rotina, não falha.
    tentativa = MAX_RECONNECT_ATTEMPTS
    tentativa, espera = politica_de_reconexao(duracao=600.0, tentativa=tentativa)
    checar(tentativa == 1 and espera == 1.0, "conexão longa zera o contador e reconecta já")
    for _ in range(50):
        tentativa, espera = politica_de_reconexao(duracao=600.0, tentativa=tentativa)
        if espera is None:
            break
    checar(espera is not None, "reciclagem normal do WebSocket nunca esgota as tentativas")

    # 6. A cota da BUSCA derrubava a sessão inteira já na primeira conexão. A
    #    ferramenta de grounding é cobrada no aperto de mão e tem cota própria:
    #    a sessão precisa desistir DELA, não da sessão.
    teste_desligar_busca_ao_estourar_cota()


def teste_sinal_de_atividade() -> None:
    """As bordas de fala viram avisos de atividade, em alternância estrita.

    O serviço descarta áudio que chega sem início declarado e fica esperando o
    resto de um turno cujo fim nunca foi anunciado. Os dois erros emudecem a
    sessão inteira, e nenhum dos dois aparece como exceção — por isso a
    alternância é verificada aqui, e não deixada para o serviço reclamar.
    """
    print("sinal de atividade (fim de fala)")
    import asyncio
    import queue as _queue
    from types import SimpleNamespace

    from pipboy.audio import FIM_DE_FALA, INICIO_DE_FALA
    from pipboy.session import LiveSessionWorker

    class SessaoFalsa:
        def __init__(self) -> None:
            self.eventos: list[str] = []

        async def send_realtime_input(self, **kw):
            if "activity_start" in kw:
                self.eventos.append("inicio")
            elif "activity_end" in kw:
                self.eventos.append("fim")
            else:
                self.eventos.append("audio")

    def correr(itens: list) -> list[str]:
        w = LiveSessionWorker.__new__(LiveSessionWorker)
        w._stop_event = asyncio.Event()
        w._fala_aberta = False
        capture = SimpleNamespace(frames=_queue.Queue())
        for i in itens:
            capture.frames.put(i)
        sessao = SessaoFalsa()

        async def main():
            audio = SimpleNamespace(capture=capture)
            tarefa = asyncio.create_task(w._send_audio(sessao, audio))
            while not capture.frames.empty():
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.05)
            w._stop_event.set()
            await asyncio.wait_for(tarefa, timeout=2)

        asyncio.run(main())
        return sessao.eventos

    som = b"\x33\x33"

    # O caso normal: uma pergunta inteira, cercada pelas duas bordas.
    ev = correr([INICIO_DE_FALA, som, som, FIM_DE_FALA])
    checar(ev == ["inicio", "audio", "audio", "fim"], f"turno completo em ordem ({ev})")

    # Início repetido quebraria o contrato; o segundo é engolido.
    ev = correr([INICIO_DE_FALA, som, INICIO_DE_FALA, som, FIM_DE_FALA])
    checar(ev.count("inicio") == 1, f"início repetido não é reenviado ({ev})")

    # Fim sem início pendente é ruído — o serviço não deve recebê-lo.
    ev = correr([FIM_DE_FALA, FIM_DE_FALA])
    checar(ev == [], f"fim sem fala aberta não vira aviso ({ev})")

    # Áudio órfão (reconexão no meio de uma frase) precisa abrir o turno, senão
    # o serviço o descarta em silêncio e a pergunta se perde.
    ev = correr([som, som, FIM_DE_FALA])
    checar(ev[0] == "inicio", f"áudio sem início declarado abre o turno ({ev})")
    checar(ev == ["inicio", "audio", "audio", "fim"], f"e segue em ordem ({ev})")


def teste_desligar_busca_ao_estourar_cota() -> None:
    """O laço de conexão sacrifica a busca antes de sacrificar a sessão."""
    import asyncio
    from types import SimpleNamespace

    from pipboy.events import UiEventKind
    from pipboy.session import LiveSessionWorker

    def montar(web_search: bool) -> tuple[LiveSessionWorker, list]:
        eventos: list = []
        worker = LiveSessionWorker.__new__(LiveSessionWorker)  # sem thread nem áudio
        worker.session_id = 1
        worker._publish = eventos.append
        # O cliente é construído mas nunca usado: quem conecta é o dublê abaixo.
        worker._configuration = SimpleNamespace(api_key="chave-de-teste", model="modelo")
        worker._web_search = web_search
        worker._first_connection = True
        worker._trafego_na_conexao = False
        worker._renovacao_pedida = False
        worker._stop_event = asyncio.Event()
        return worker, eventos

    def rodar(worker: LiveSessionWorker, falhas: list[Exception]) -> int:
        """Roda o laço com um ``_one_connection`` de mentira. Devolve as tentativas."""
        chamadas = 0
        pedidos: list[bool] = []

        async def falso(_cliente, _audio):
            nonlocal chamadas
            pedidos.append(worker._web_search)
            chamadas += 1
            if falhas:
                raise falhas.pop(0)
            worker._stop_event.set()  # sucesso: encerra o laço

        worker._one_connection = falso  # type: ignore[method-assign]
        worker._status = lambda *a, **k: None  # type: ignore[method-assign]
        worker._log = lambda *a, **k: None  # type: ignore[method-assign]
        asyncio.run(worker._connection_loop(None))  # type: ignore[arg-type]
        worker._pedidos = pedidos  # type: ignore[attr-defined]
        return chamadas

    cota = Exception("You exceeded your current quota, please check your plan and billing")
    cota.code = 1011  # type: ignore[attr-defined]

    # -- com a busca ligada: reconecta SEM ela em vez de morrer
    worker, eventos = montar(web_search=True)
    chamadas = rodar(worker, [cota])
    checar(chamadas == 2, f"a sessão tenta de novo em vez de desistir ({chamadas} conexões)")
    checar(worker._pedidos == [True, False], "a segunda tentativa vai sem a busca")
    checar(not worker._web_search, "a busca fica desligada pelo resto da sessão")
    checar(
        any(e.kind is UiEventKind.WEB_SEARCH_DISABLED for e in eventos),
        "a interface é avisada para desmarcar o chip",
    )

    # -- sem a busca ligada, cota é cota: a primeira conexão ainda encerra
    worker, _ = montar(web_search=False)
    try:
        rodar(worker, [cota])
        caiu = False
    except Exception:
        caiu = True
    checar(caiu, "sem busca a ligar, o erro de cota continua subindo")

    # -- outro erro qualquer não deve custar a busca
    worker, _ = montar(web_search=True)
    credencial = Exception("Request had invalid authentication credentials")
    credencial.code = 1008  # type: ignore[attr-defined]
    with contextlib.suppress(Exception):
        rodar(worker, [credencial])
    checar(worker._web_search, "falha de credencial não desliga a busca")


def teste_sons() -> None:
    """Síntese dos blips de interface.

    O contrato: todo evento de todo tema produz um WAV válido, curto e com
    amplitude contida (efeito de interface não disputa com a voz do tutor);
    o cache grava uma vez e reutiliza; evento desconhecido é erro de
    programação, não silêncio.
    """
    print("sons")
    from pipboy.sons import (
        AMPLITUDE,
        EVENTOS,
        RECEITA_PADRAO,
        RECEITAS,
        TAXA,
        gerar_cache,
        para_wav,
        sintetizar,
    )

    for receita in (*RECEITAS.values(), RECEITA_PADRAO):
        for evento in EVENTOS:
            amostras = sintetizar(evento, receita)
            assert amostras.size > 0
    checar(True, "todo evento de todo timbre sintetiza")

    blip = sintetizar("iniciar", RECEITA_PADRAO)
    checar(blip.size <= TAXA // 2, "um blip dura menos de meio segundo")
    checar(float(abs(blip).max()) <= AMPLITUDE + 1e-6, "a amplitude respeita o teto")
    dois = sintetizar("iniciar", RECEITA_PADRAO)
    checar(bool((blip == dois).all()), "a síntese é determinística")

    wav = para_wav(blip)
    checar(wav[:4] == b"RIFF" and wav[8:12] == b"WAVE", "cabeçalho RIFF/WAVE válido")
    checar(len(wav) == 44 + blip.size * 2, "tamanho do arquivo bate com as amostras")

    pasta = Path(tempfile.mkdtemp()) / "sons"
    caminhos = gerar_cache(pasta, "Fallout")
    checar(set(caminhos) == set(EVENTOS), "cache cobre os quatro eventos")
    checar(all(c.is_file() for c in caminhos.values()), "os WAVs existem no disco")
    marca = caminhos["iniciar"].stat().st_mtime_ns
    gerar_cache(pasta, "Fallout")
    checar(caminhos["iniciar"].stat().st_mtime_ns == marca, "cache não regrava o que já existe")
    outros = gerar_cache(pasta, "Cyberpunk 2077")
    checar(outros["iniciar"] != caminhos["iniciar"], "cada tema tem seus próprios arquivos")

    try:
        sintetizar("clique", RECEITA_PADRAO)
        checar(False, "evento desconhecido deveria falhar")
    except ValueError:
        checar(True, "evento desconhecido deveria falhar")


def teste_historico() -> None:
    """Histórico de sessões: gravação, leitura, descarte de vazias, remoção."""
    print("histórico")
    from pipboy.historico import HistoricoStore

    store = HistoricoStore(Path(tempfile.mkdtemp()) / "h.sqlite3")
    checar(store.total_sessoes() == 0, "começa sem sessões")

    sessao = store.iniciar_sessao(jogo="Fallout", modo="Tutor Conversacional", nivel="B1–B2")
    checar(sessao > 0, "iniciar sessão devolve um id")
    store.registrar_fala(sessao, autor="VOCÊ", tag="usuario", texto="what is wasteland?")
    store.registrar_fala(sessao, autor="PIP-BOY", tag="assistente", texto="Terra devastada.")
    store.registrar_fala(sessao, autor="", tag="vocab", texto="wasteland — terra devastada")
    store.registrar_fala(sessao, autor="X", tag="usuario", texto="   ")  # vazio não grava

    falas = store.falas_de(sessao)
    checar(len(falas) == 3, "grava as falas na ordem, ignorando as vazias")
    checar(falas[0].texto == "what is wasteland?", "a primeira fala é a primeira")
    checar(falas[1].autor == "PIP-BOY", "autor preservado")

    resumos = store.listar_sessoes()
    checar(len(resumos) == 1 and resumos[0].falas == 3, "resumo conta as falas")
    checar(resumos[0].jogo == "Fallout", "metadados da sessão preservados")

    vazia = store.iniciar_sessao(jogo="GTA")
    checar(store.descartar_sessao_vazia(vazia), "sessão sem fala é descartada")
    checar(not store.descartar_sessao_vazia(sessao), "sessão com falas fica")
    checar(store.total_sessoes() == 1, "só a sessão real sobrevive")

    checar(store.remover_sessao(sessao), "remover sessão existente")
    checar(store.falas_de(sessao) == [], "as falas se vão com a sessão (CASCADE)")
    checar(not store.remover_sessao(sessao), "remover duas vezes devolve falso")

    # Sequência de estudo.
    from datetime import date, timedelta

    seq = HistoricoStore(Path(tempfile.mkdtemp()) / "seq.sqlite3")
    checar(seq.sequencia_atual() == 0, "sem atividade, sequência zero")
    hoje = date.today()
    seq.marcar_atividade()
    checar(seq.sequencia_atual() == 1, "estudar hoje inicia a sequência")
    seq.marcar_atividade()
    checar(seq.sequencia_atual() == 1, "estudar duas vezes no dia não conta dobrado")
    seq.marcar_atividade((hoje - timedelta(days=1)).isoformat())
    seq.marcar_atividade((hoje - timedelta(days=2)).isoformat())
    checar(seq.sequencia_atual() == 3, "três dias seguidos somam três")
    seq.marcar_atividade((hoje - timedelta(days=4)).isoformat())
    checar(seq.sequencia_atual() == 3, "um buraco interrompe a contagem")

    ontem = HistoricoStore(Path(tempfile.mkdtemp()) / "seq2.sqlite3")
    ontem.marcar_atividade((hoje - timedelta(days=1)).isoformat())
    ontem.marcar_atividade((hoje - timedelta(days=2)).isoformat())
    checar(ontem.sequencia_atual() == 2, "sem estudar hoje, ontem mantém a sequência viva")
    morta = HistoricoStore(Path(tempfile.mkdtemp()) / "seq3.sqlite3")
    morta.marcar_atividade((hoje - timedelta(days=2)).isoformat())
    checar(morta.sequencia_atual() == 0, "dois dias parado zera a sequência")


def teste_deteccao() -> None:
    """Reconhecimento do jogo pela lista de processos.

    A parte pura: dado um conjunto de nomes de executáveis, qual tema
    corresponde. A sonda real (tasklist) fica de fora — teste que depende do
    que está aberto na máquina de quem testa não afirma nada.
    """
    print("detecção de jogo")
    from pipboy.deteccao import JOGOS_CONHECIDOS, jogo_entre
    from pipboy.themes import TEMAS

    checar(jogo_entre([]) is None, "lista vazia não detecta nada")
    checar(jogo_entre(["explorer.exe", "steam.exe"]) is None, "processos comuns não são jogo")
    checar(jogo_entre(["Fallout4.exe"]) == "Fallout", "detecção ignora maiúsculas")
    checar(
        jogo_entre(["chrome.exe", "eldenring.exe"]) == "Elden Ring",
        "acha o jogo no meio dos outros processos",
    )

    orfaos = sorted(set(JOGOS_CONHECIDOS.values()) - set(TEMAS))
    checar(not orfaos, f"todo executável aponta para um tema existente {orfaos or ''}")


def teste_crash() -> None:
    """Rede de segurança de exceções.

    O capturador precisa registrar tudo, avisar uma única vez por defeito e
    deixar Ctrl+C passar intacto — os três contratos que o separam de um
    ``except Exception: pass`` glorificado.
    """
    print("crash")
    import logging

    from pipboy import crash

    registros: list[logging.LogRecord] = []

    class _Coletor(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            registros.append(record)

    coletor = _Coletor()
    crash.LOGGER.addHandler(coletor)
    crash.LOGGER.propagate = False
    hook_original, thread_original = sys.excepthook, __import__("threading").excepthook
    try:
        crash.instalar()
        checar(sys.excepthook is not hook_original, "instalar troca o excepthook")

        erro = ValueError("defeito de teste")
        sys.excepthook(ValueError, erro, None)
        checar(
            any(r.levelno == logging.CRITICAL for r in registros),
            "exceção não tratada vira registro CRITICAL",
        )
        checar(
            crash._assinatura(ValueError, erro) in crash._ja_avisados,
            "primeira aparição entra na lista de avisados",
        )
        antes = len(crash._ja_avisados)
        sys.excepthook(ValueError, erro, None)
        checar(len(crash._ja_avisados) == antes, "repetição não gera aviso novo")

        import threading

        registros.clear()
        args = threading.ExceptHookArgs(
            (RuntimeError, RuntimeError("na thread"), None, None)
        )
        threading.excepthook(args)
        checar(
            any("thread" in r.getMessage() for r in registros),
            "erro de thread é registrado com o nome da thread",
        )
        registros.clear()
        threading.excepthook(
            threading.ExceptHookArgs((SystemExit, SystemExit(0), None, None))
        )
        checar(not registros, "SystemExit numa thread não é notícia")
    finally:
        sys.excepthook = hook_original
        __import__("threading").excepthook = thread_original
        crash.LOGGER.removeHandler(coletor)
        crash._ja_avisados.clear()
        crash.registrar_janela(None)


def main() -> int:
    for teste in (
        teste_dsp,
        teste_vocabulario,
        teste_portao_de_eco,
        teste_portao_de_voz,
        teste_sinal_de_atividade,
        teste_economia_com_jogo,
        teste_caderno_navegavel,
        teste_profiles,
        teste_config,
        teste_design,
        teste_contagem_tokens,
        teste_classificacao_de_erro,
        teste_ferramentas,
        teste_versao,
        teste_revisao,
        teste_progresso,
        teste_backup,
        teste_regressoes,
        teste_sons,
        teste_historico,
        teste_deteccao,
        teste_crash,
    ):
        teste()
    print()
    if _falhas:
        print(f"{_falhas} falha(s).")
        return 1
    print("Tudo certo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
