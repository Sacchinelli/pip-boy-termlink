"""Testes da interface — a janela inteira, sem tela, sem áudio e sem rede.

Uso:  py tests/test_interface.py

A suíte do núcleo prova a lógica; esta prova que a INTERFACE constrói: a
janela principal com os dez temas, o caderno, os cartões de revisão, o
painel de progresso, o histórico, a cápsula compacta e o cartão de
boas-vindas. O backend ``offscreen`` do Qt rasteriza tudo sem monitor, então
ela roda igual no CI — onde não há tela, nem microfone, nem bandeja.

O que ela pega: o NameError no tema nove, o import circular novo, a chave de
paleta digitada errada, o widget que explode ao trocar de tema — a classe de
defeito que os testes do núcleo, de propósito, nunca veem.
"""

from __future__ import annotations

import os
import queue
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Pasta de dados redirecionada ANTES de qualquer import do pacote: este teste
# não pode tocar no caderno nem nas preferências de quem o roda.
_TEMP = tempfile.mkdtemp(prefix="pipboy-teste-ui-")
os.environ["LOCALAPPDATA"] = _TEMP
os.environ["XDG_DATA_HOME"] = _TEMP
os.environ["GEMINI_API_KEY"] = "AIzaTESTE_INTERFACE_1234"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

for fluxo in (sys.stdout, sys.stderr):
    with __import__("contextlib").suppress(AttributeError, ValueError):
        fluxo.reconfigure(encoding="utf-8", errors="replace")

_falhas = 0


def checar(condicao: bool, descricao: str) -> None:
    global _falhas
    if condicao:
        print(f"  ok   {descricao}")
    else:
        _falhas += 1
        print(f"  FALHA  {descricao}")


def main() -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    aplicacao = QApplication.instance() or QApplication([])

    from pipboy.config import AppConfiguration, data_directory
    from pipboy.historico import HistoricoStore
    from pipboy.themes import PAPEIS_DA_PALETA, TEMAS
    from pipboy.vocabulary import VocabularyStore

    print("tabelas paralelas")
    # themes.TEMAS, atmosfera.ATMOSFERAS e sons.RECEITAS são três dicionários
    # independentes chaveados pelo mesmo nome de jogo, e os três degradam em
    # SILÊNCIO para um padrão quando a chave falta. O docstring de themes.py
    # promete que acrescentar um GameTheme basta — quem fizer isso ganharia um
    # jogo sem atmosfera própria e sem timbre próprio, sem nenhum aviso.
    from pipboy.interface.atmosfera import ATMOSFERAS

    faltando_atmosfera = sorted(set(TEMAS) - set(ATMOSFERAS))
    checar(not faltando_atmosfera, f"todo tema tem atmosfera própria ({faltando_atmosfera})")
    sobrando_atmosfera = sorted(set(ATMOSFERAS) - set(TEMAS))
    checar(not sobrando_atmosfera, f"nenhuma atmosfera órfã ({sobrando_atmosfera})")

    # sons.RECEITAS é parcial DE PROPÓSITO: dois temas usam o timbre padrão.
    # O que não pode é uma chave que não corresponde a tema nenhum — essa é
    # sempre erro de digitação, e produz um timbre que jamais toca.
    from pipboy.sons import RECEITAS

    receitas_orfas = sorted(set(RECEITAS) - set(TEMAS))
    checar(not receitas_orfas, f"nenhuma receita sonora órfã ({receitas_orfas})")

    print("construção da janela")
    configuration = AppConfiguration.load(Path(_TEMP))
    from pipboy.interface.janela import Janela

    janela = Janela(configuration)
    janela.resize(1240, 860)
    janela.show()
    aplicacao.processEvents()
    checar(janela.isVisible(), "a janela principal constrói e aparece")
    checar(janela.barra_titulo.height() > 0, "a barra de título tem altura")

    print("dispositivos por thread")
    # A enumeração de áudio saiu do construtor (custava ~300 ms com a tela em
    # branco) e volta pela fila de eventos. O que se testa aqui é o RETORNO:
    # dispositivos sintéticos, sem tocar no hardware de quem roda a suíte.
    #
    # E a thread REAL continua correndo enquanto isto roda. Ela entrega a lista
    # desta máquina quando ficar pronta — inclusive no meio deste bloco, por
    # cima da lista sintética. Não é hipótese: o mesmo commit passou numa
    # execução do CI e reprovou na seguinte, e a diferença foi o instante em
    # que a thread respondeu. Por isso a fila é esvaziada, o estado é forçado
    # ao conhecido, e o laço de eventos não roda até a última pergunta — um
    # evento que chegue atrasado fica na fila sem atrapalhar ninguém.
    from pipboy.audio import Device

    while True:
        try:
            janela._eventos.get_nowait()
        except queue.Empty:
            break
    janela._dispositivos_prontos(([], [], None))

    checar(
        janela.campo_entrada.count() == 1 and janela.campo_entrada.itemText(0).startswith("Padrão"),
        "sem lista, a caixa oferece só 'Padrão do sistema' — que já é resposta completa",
    )
    checar(not janela.chip_jogo.isEnabled(), "e sem loopback conhecido 'Ouvir o jogo' fica inerte")
    janela._prefs.dispositivo_entrada = "9: Microfone de Teste"
    janela._dispositivos_prontos(
        (
            [Device(9, "Microfone de Teste", 1, 48_000)],
            [Device(4, "Saída de Teste", 2, 48_000)],
            Device(7, "Loopback de Teste", 2, 48_000, is_loopback=True),
        )
    )
    checar(janela.campo_entrada.count() == 2, "a lista de microfones chega depois e entra na caixa")
    checar(
        janela.campo_entrada.currentText() == "9: Microfone de Teste",
        f"e a preferência gravada é reoferecida ({janela.campo_entrada.currentText()})",
    )
    checar(janela.chip_jogo.isEnabled(), "com loopback, o chip do jogo é habilitado")
    checar(
        janela._indice_dispositivo(janela.campo_entrada, janela._entradas) == 9,
        "e o índice do dispositivo escolhido chega à sessão",
    )

    print("relógio de quadros")
    # Repintar a janela inteira a 30 quadros por segundo custa de 5 a 7% de um
    # núcleo. Dois ambientes não têm camada viva alguma, e para eles o relógio
    # não deve nem correr; nos demais, só a região das partículas é pedida.
    #
    # A atmosfera é FIXADA em Completa aqui, e não herdada. O padrão dela sai
    # da preferência de animação do Windows, que numa máquina (ou num runner
    # de CI) com "efeitos de animação" desligado nasce Desligada — e aí não há
    # partícula, nem relógio, nem região, e estas checagens passariam a testar
    # o computador de quem as roda em vez do código. Foi exatamente assim que
    # elas passaram aqui e reprovaram no CI.
    atmosfera_anterior = janela.campo_atmosfera.currentText()
    janela.campo_atmosfera.setCurrentText("Completa")
    aplicacao.processEvents()
    janela._trocar_jogo("Genérico / Outro")
    aplicacao.processEvents()
    checar(not janela._cenario.tem_camada_viva, "ambiente sem partícula não tem camada viva")
    checar(not janela._relogios.animando, "e o relógio de quadros nem corre")
    janela._trocar_jogo("Elden Ring")
    aplicacao.processEvents()
    checar(janela._cenario.tem_camada_viva, "ambiente com partículas tem camada viva")
    checar(janela._relogios.animando, "e o relógio volta a correr")
    janela._cenario.avancar(1 / 30)
    regiao = janela._cenario.regiao_suja()
    checar(regiao is not None and not regiao.isEmpty(), "as partículas pedem uma região")
    assert regiao is not None
    # A QRegion do PySide6 não expõe rects(), mas é percorrível.
    area_regiao = sum(r.width() * r.height() for r in regiao)
    area_janela = janela.width() * janela.height()
    checar(
        area_regiao < area_janela * 0.5,
        f"e ela é MENOR que a janela ({area_regiao} de {area_janela} pixels)",
    )
    janela._trocar_jogo("Fallout")
    aplicacao.processEvents()
    janela._cenario.avancar(1 / 30)
    checar(
        janela._cenario.regiao_suja() is None,
        "a tremulação do tubo continua pedindo o quadro cheio",
    )
    janela.campo_atmosfera.setCurrentText(atmosfera_anterior)
    aplicacao.processEvents()

    print("os dez temas")
    for nome in TEMAS:
        janela._trocar_jogo(nome)
        aplicacao.processEvents()
        # O grab força uma repintura completa: paintEvent de cada componente,
        # atmosfera e folha de estilo do tema — é aqui que um tema quebrado cai.
        imagem = janela.grab()
        checar(not imagem.isNull(), f"tema desenha por inteiro: {nome}")

    print("as janelas satélites")
    dados = data_directory()
    store = VocabularyStore(dados / "vocabulario.sqlite3")
    store.registrar("wasteland", "terra devastada", "The wasteland.", "Fallout")
    store.registrar("bonfire", "fogueira", jogo="Elden Ring")

    janela.abrir_caderno()
    aplicacao.processEvents()
    assert janela._caderno is not None
    checar(janela._caderno.isVisible(), "caderno abre")
    checar(not janela._caderno.grab().isNull(), "caderno desenha")

    # -- Filtro por jogo: uma dimensão separada dos chips de estado.
    from pipboy.interface.caderno import TODOS_OS_JOGOS

    caderno = janela._caderno
    caderno.atualizar()
    aplicacao.processEvents()
    opcoes = [caderno.campo_jogo.itemText(i) for i in range(caderno.campo_jogo.count())]
    checar(opcoes == [TODOS_OS_JOGOS, "Elden Ring", "Fallout"], f"seletor lista os jogos ({opcoes})")
    checar(caderno.campo_jogo.isVisible(), "com dois jogos, o seletor aparece")

    caderno.campo_jogo.setCurrentText("Fallout")
    aplicacao.processEvents()
    mostrados = [c._entrada.termo for c in caderno._cartoes]
    checar(mostrados == ["wasteland"], f"escolher o jogo recorta a lista ({mostrados})")
    checar("1 resultado" in caderno.contagem.text(), "e a contagem do rodapé acompanha")

    # Os chips continuam mandando no estado, e os dois eixos se somam.
    caderno._escolher_filtro("dominadas")
    aplicacao.processEvents()
    checar(caderno._cartoes == [], "'dominadas' + 'Fallout' não devolve nada ainda")
    checar("Fallout" in caderno.vazio.text(), "e o vazio diz de que jogo está falando")

    caderno._escolher_filtro("todas")
    caderno.campo_jogo.setCurrentText(TODOS_OS_JOGOS)
    aplicacao.processEvents()
    checar(len(caderno._cartoes) == 2, "voltar para 'todos os jogos' devolve a lista")

    print("microinterações do caderno")
    # A atmosfera é fixada em Completa pelo mesmo motivo do relógio de quadros:
    # num runner sem "efeitos de animação" ela nasce Desligada, as transições
    # daqui virariam saltos, e as checagens passariam a medir a máquina.
    from collections.abc import Callable

    from PySide6.QtCore import QEvent, QEventLoop, QPointF, QTimer, qInstallMessageHandler
    from PySide6.QtGui import QEnterEvent, QFocusEvent, QMouseEvent
    from PySide6.QtWidgets import QLabel, QWidget

    import pipboy.interface.caderno as mod_caderno
    import pipboy.interface.janela as mod_exportar
    from pipboy.interface.componentes import Botao
    from pipboy.interface.movimento import EfeitoEntrada

    def esperar(ms: int) -> None:
        laco = QEventLoop()
        QTimer.singleShot(ms, laco.quit)
        laco.exec()

    def aguardar(condicao: Callable[[], bool], limite_ms: int = 4000) -> bool:
        # Espera pelo ESTADO, não por um tempo fixo: o runner de CI é mais
        # lento que qualquer máquina de desenvolvimento, e um "espera 400 ms"
        # que aqui sobra lá falta.
        for _ in range(limite_ms // 50):
            if condicao():
                return True
            esperar(50)
        return bool(condicao())

    def entrar(alvo: QWidget, x: float, y: float) -> None:
        ponto = QPointF(x, y)
        QApplication.sendEvent(alvo, QEnterEvent(ponto, ponto, QPointF(alvo.mapToGlobal(ponto))))

    def sair(alvo: QWidget) -> None:
        QApplication.sendEvent(alvo, QEvent(QEvent.Type.Leave))

    atmosfera_caderno = janela.campo_atmosfera.currentText()
    janela.campo_atmosfera.setCurrentText("Completa")
    aplicacao.processEvents()

    # Trocar de filtro, logo acima, já dispara uma cascata. Sem esperá-la
    # acabar, a checagem da REABERTURA enxergaria os efeitos da troca e
    # passaria mesmo com a reabertura sem animação nenhuma.
    aguardar(lambda: all(c.graphicsEffect() is None for c in caderno._cartoes))
    caderno.hide()
    caderno.show()
    checar(
        all(isinstance(c.graphicsEffect(), EfeitoEntrada) for c in caderno._cartoes),
        "reabrir o caderno faz os cartões entrarem em cascata",
    )
    checar(
        aguardar(lambda: all(c.graphicsEffect() is None for c in caderno._cartoes)),
        "e nenhum efeito fica pendurado quando a entrada termina",
    )

    cartao = caderno._cartoes[0]
    acoes = cartao._acoes
    avisos_qt: list[str] = []
    qInstallMessageHandler(lambda _tipo, _contexto, mensagem: avisos_qt.append(mensagem))
    try:
        entrar(cartao, 40, 20)
        checar(
            cartao._intencao.isActive() and cartao._revelacao.valor == 0.0,
            "chegar ao cartão arma a intenção sem revelar as ações de cara",
        )
        checar(
            acoes.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents),
            "e ação invisível não recebe clique",
        )
        # O movimento cai sobre um FILHO: é o caso que congelava a luz.
        rotulo = next(r for r in cartao.findChildren(QLabel) if r.text() == cartao._entrada.traducao)
        centro = QPointF(rotulo.rect().center())
        QApplication.sendEvent(
            rotulo,
            QMouseEvent(
                QEvent.Type.MouseMove, centro, QPointF(rotulo.mapToGlobal(centro)),
                Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            ),
        )
        esperado = QPointF(rotulo.mapTo(cartao, centro.toPoint()))
        checar(
            cartao._holofote.cursor == esperado,
            f"o cursor sobre a tradução ainda conduz a luz ({cartao._holofote.cursor} vs {esperado})",
        )
        checar(
            aguardar(lambda: cartao._revelacao.valor == 1.0 and cartao._holofote.valor == 1.0),
            "parado no cartão, a luz acende e as ações aparecem",
        )
        checar(
            not acoes.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents),
            "e passam a aceitar clique",
        )
        avisos_qt.clear()
        cartao.update()
        acoes.update()
        esperar(80)
        checar(
            not [a for a in avisos_qt if "ainter" in a],
            f"repintar o cartão aceso não briga por pintor ({avisos_qt[:2]})",
        )
        sair(cartao)
        checar(aguardar(lambda: cartao._revelacao.valor == 0.0), "sair esconde as ações")

        # O foco é ENTREGUE, e não pedido com setFocus: a esta altura do roteiro
        # o backend offscreen não tem janela ativa nenhuma, e um setFocus sem
        # janela ativa guarda o pedido sem nunca emitir o evento. O que se prova
        # aqui é a reação do cartão ao Tab, não o gerenciador de janelas.
        corrigir = acoes.findChildren(Botao)[1]
        QApplication.sendEvent(
            corrigir, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason)
        )
        checar(
            aguardar(lambda: cartao._revelacao.valor == 1.0),
            "Tab até uma ação revela as ações sem mouse nenhum",
        )
        QApplication.sendEvent(
            corrigir, QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.TabFocusReason)
        )
        checar(aguardar(lambda: cartao._revelacao.valor == 0.0), "e o foco saindo esconde de novo")
    finally:
        qInstallMessageHandler(None)

    # -- Exportar confirma no próprio botão. Antes, o resultado ia só para o
    #    registro da janela principal, escondido atrás do caderno.
    exportar = caderno.botao_exportar
    largura_exportar = exportar.width()
    dica_exportar = exportar.toolTip()
    destino_exportar = dados / "exportado.txt"
    salvar_original = mod_exportar.QFileDialog.getSaveFileName
    try:
        mod_exportar.QFileDialog.getSaveFileName = staticmethod(  # type: ignore[assignment]
            lambda *a, **k: ("", "")
        )
        exportar.click()
        checar(exportar.estado == "ocioso", "cancelar o seletor não confirma nada")
        mod_exportar.QFileDialog.getSaveFileName = staticmethod(  # type: ignore[assignment]
            lambda *a, **k: (str(destino_exportar), "")
        )
        exportar.click()
        aplicacao.processEvents()
        checar(
            destino_exportar.exists() and exportar.estado == "concluido",
            "exportar confirma no botão que foi clicado",
        )
        checar(
            f"{store.total()} termos exportados" in exportar.toolTip(),
            f"e a dica diz quanto foi escrito ({exportar.toolTip()})",
        )
        checar(exportar.width() == largura_exportar, "sem mudar a largura do botão")
        checar(
            aguardar(lambda: exportar.estado == "ocioso"),
            "a confirmação volta sozinha",
        )
        checar(exportar.toolTip() == dica_exportar, "e devolve a dica original")
    finally:
        mod_exportar.QFileDialog.getSaveFileName = salvar_original  # type: ignore[assignment]

    # -- Remover esmaece e fecha o buraco SEM devolver a lista ao topo.
    extras = [f"scrap {i:02d}" for i in range(14)]
    for termo in extras:
        store.registrar(termo, "sucata", "Scrap metal everywhere.", "Fallout")
    caderno.atualizar()
    barra = caderno.rolagem.verticalScrollBar()
    checar(aguardar(lambda: barra.maximum() > 0), "com dezesseis palavras a lista rola")
    barra.setValue(barra.maximum())
    # A ordem da lista é a do caderno, não a de inserção: o alvo é procurado
    # entre as palavras de apoio, para não levar junto uma das verdadeiras.
    removido = next(c for c in reversed(caderno._cartoes) if c._entrada.termo in extras)
    confirmar_original = mod_caderno.confirmar_remocao
    try:
        mod_caderno.confirmar_remocao = lambda *a, **k: True  # type: ignore[assignment]
        caderno._remover(removido._entrada)
        checar(
            removido.graphicsEffect() is not None,
            "remover esmaece o cartão em vez de sumir num quadro",
        )
        checar(
            aguardar(lambda: len(caderno._cartoes) == len(extras) + 1),
            "e a lista se fecha sobre ele",
        )
        aplicacao.processEvents()
        checar(barra.value() > 0, f"sem devolver a rolagem ao topo ({barra.value()})")
    finally:
        mod_caderno.confirmar_remocao = confirmar_original  # type: ignore[assignment]
        for termo in extras:
            store.remover(termo)
        caderno.atualizar()
        aplicacao.processEvents()
    checar(len(caderno._cartoes) == 2, "as palavras de apoio saem sem deixar rastro")

    # -- Atmosfera desligada: o estado final chega, o trajeto não.
    janela.campo_atmosfera.setCurrentText("Desligada")
    aplicacao.processEvents()
    cartao = caderno._cartoes[0]
    entrar(cartao, 40, 20)
    checar(cartao._holofote.valor == 1.0, "com a atmosfera desligada a luz chega sem trajeto")
    sair(cartao)
    caderno.hide()
    caderno.show()
    checar(
        all(c.graphicsEffect() is None for c in caderno._cartoes),
        "e o caderno abre sem cascata",
    )
    janela.campo_atmosfera.setCurrentText(atmosfera_caderno)
    aplicacao.processEvents()

    # -- Correção: a borracha que faltava ao lado do "×". A caixa é
    #    substituída pelo mesmo motivo do QFileDialog acima — ela bloqueia
    #    esperando alguém digitar; o resto do caminho é o de produção.
    import pipboy.interface.caderno as mod_caderno

    alvo = caderno._cartoes[0]._entrada
    original = mod_caderno.pedir_correcao
    mod_caderno.pedir_correcao = lambda *a, **k: {  # type: ignore[assignment]
        "termo": alvo.termo,
        "traducao": "tradução corrigida",
        "exemplo": alvo.exemplo,
    }
    try:
        caderno._corrigir(alvo)
        aplicacao.processEvents()
        textos = [c._entrada.traducao for c in caderno._cartoes]
        checar("tradução corrigida" in textos, f"corrigir troca o texto na lista ({textos})")

        # E o caminho do erro: renomear para uma palavra que já existe não pode
        # estourar na cara de quem clicou.
        outro = next(
            c._entrada for c in caderno._cartoes if c._entrada.termo != alvo.termo
        )
        mod_caderno.pedir_correcao = lambda *a, **k: {  # type: ignore[assignment]
            "termo": outro.termo,
            "traducao": alvo.traducao,
            "exemplo": "",
        }
        avisos: list[str] = []
        aviso_real = mod_caderno.avisar
        mod_caderno.avisar = lambda _j, _t, m, **k: avisos.append(m)  # type: ignore[assignment]
        try:
            caderno._corrigir(alvo)
        finally:
            mod_caderno.avisar = aviso_real  # type: ignore[assignment]
        checar(bool(avisos), f"colisão vira aviso, não exceção ({avisos})")
        checar(len(caderno._cartoes) == 2, "e as duas palavras continuam lá")
    finally:
        mod_caderno.pedir_correcao = original  # type: ignore[assignment]

    # A caixa com campos, construída de verdade: é ela que a correção usa.
    from pipboy.interface.dialogo import Caixa as CaixaCampos

    caixa_campos = CaixaCampos(
        janela,
        "Corrigir palavra",
        "mensagem",
        glifo="◇",
        papel_glifo="accent",
        confirmar="Salvar",
        cancelar="Cancelar",
        perigo=False,
        campos=(("termo", "Termo", "wasteland"), ("traducao", "Tradução", "ermo")),
    )
    checar(
        caixa_campos.valores() == {"termo": "wasteland", "traducao": "ermo"},
        "a caixa de campos nasce preenchida e devolve o que está escrito",
    )
    checar(not caixa_campos.grab().isNull(), "e desenha no tema")
    caixa_campos.deleteLater()

    # -- Importação: a porta de entrada do caderno, pelo caminho da janela.
    #    O QFileDialog é substituído porque um diálogo nativo trava a suíte
    #    esperando alguém clicar; o resto do caminho é o de produção.
    import pipboy.interface.janela as mod_import
    from pipboy.interface.dialogo import Caixa

    # 'wasteland' já está no caderno e 'raider' não. O repetido tem de ser um
    # termo que EXISTE aqui: 'ghoul' só nasce mais adiante neste arquivo, e
    # criá-lo antes da sessão do histórico quebraria o teste do elo entre a
    # palavra e a conversa em que ela foi ensinada.
    arquivo = dados / "importar.txt"
    arquivo.write_text(
        "raider\tsaqueador\tRaiders ahead.\tFallout\n"
        "wasteland\tterra devastada\tThe wasteland.\tFallout\n",
        encoding="utf-8",
    )
    escolha_original = mod_import.QFileDialog.getOpenFileName
    aviso_original = mod_import.avisar
    vistos: list[str] = []
    try:
        mod_import.QFileDialog.getOpenFileName = staticmethod(  # type: ignore[assignment]
            lambda *a, **k: (str(arquivo), "")
        )
        mod_import.avisar = lambda *a, **k: vistos.append(str(a[2]))  # type: ignore[assignment]
        antes_total = store.total()
        janela.importar_vocabulario()
        aplicacao.processEvents()
        checar(store.total() == antes_total + 1, "importar soma só o termo que faltava")
        checar(
            any("já estava" in v for v in vistos),
            f"e o aviso diz o que aconteceu com o repetido ({vistos})",
        )
        checar(
            any(c._entrada.termo == "raider" for c in janela._caderno._cartoes),
            "o caderno aberto mostra o termo novo sem precisar ser reaberto",
        )
    finally:
        mod_import.QFileDialog.getOpenFileName = escolha_original  # type: ignore[assignment]
        mod_import.avisar = aviso_original  # type: ignore[assignment]
    assert Caixa is not None  # o diálogo temático existe; só não foi aberto aqui

    from pipboy.interface.progresso import JanelaProgresso

    progresso = JanelaProgresso(janela, store, parent=janela)
    progresso.show()
    aplicacao.processEvents()
    checar(not progresso.grab().isNull(), "painel de progresso desenha")
    progresso.close()

    from pipboy.interface.revisao import JanelaRevisao

    revisao = JanelaRevisao(janela, store, parent=janela)
    revisao.show()
    aplicacao.processEvents()
    checar(not revisao.grab().isNull(), "cartões de revisão desenham")
    revisao._revelar()
    aplicacao.processEvents()
    revisao._responder(True)
    aplicacao.processEvents()
    checar(not revisao.grab().isNull(), "revisão sobrevive a revelar e responder")
    revisao.close()

    historico = HistoricoStore(dados / "historico.sqlite3")
    sessao = historico.iniciar_sessao(jogo="Fallout")
    historico.registrar_fala(sessao, autor="VOCÊ", tag="usuario", texto="what is a ghoul?")
    historico.registrar_fala(sessao, autor="PIP-BOY", tag="assistente", texto="Carniçal.")
    janela.abrir_historico()
    aplicacao.processEvents()
    visor = janela._visor_historico
    checar(visor.isVisible(), "histórico abre")
    checar(not visor.grab().isNull(), "histórico desenha")

    visor._busca.setText("ghoul")
    aplicacao.processEvents()
    checar("1 de 2 falas" in visor._cabecalho.text(), "a busca filtra a transcrição")
    visor._busca.setText("zzzz")
    aplicacao.processEvents()
    checar(not visor.grab().isNull(), "busca sem resultado desenha o aviso")
    visor._busca.clear()
    aplicacao.processEvents()
    checar("de 2 falas" not in visor._cabecalho.text(), "limpar a busca devolve tudo")

    # -- Do caderno de volta para a conversa em que a palavra nasceu.
    # A ordem aqui é a de produção: a palavra entra no caderno e SÓ ENTÃO a
    # anotação vira fala. É o que garante que o fim do período da sessão
    # nunca fique atrás do instante em que a palavra nasceu.
    from pipboy.historico import sessao_em

    ghoul, _ = store.registrar("ghoul", "carniçal", "A ghoul.", "Fallout")
    historico.registrar_fala(sessao, autor="", tag="vocab", texto="⊕ ghoul — carniçal")

    destino = sessao_em(janela.periodos_de_conversa(), ghoul.criado_em)
    checar(destino == sessao, f"a palavra encontra a conversa em que nasceu ({destino})")

    janela.abrir_conversa(sessao, "ghoul")
    aplicacao.processEvents()
    visor = janela._visor_historico
    checar(visor._sessao_aberta == sessao, "o salto abre a conversa certa")
    checar(visor._destaque == "ghoul", "e leva junto a palavra que trouxe até aqui")
    checar(not visor.grab().isNull(), "a conversa com a linha destacada desenha")
    # Trocar de sessão à mão apaga o destaque: ele pertence ao salto, não à
    # janela — senão a próxima conversa aberta viria marcada sem motivo.
    visor._abrir_sessao(historico.listar_sessoes()[0])
    checar(visor._destaque == "", "abrir outra sessão à mão limpa o destaque")

    # O botão do cartão só existe quando há para onde ir. 'wasteland' faz o
    # papel do vocabulário herdado de versões sem histórico, e ele não pode
    # virar um botão que não faz nada.
    #
    # A data é recuada à força: tudo neste teste acontece no mesmo segundo, e
    # os carimbos têm essa resolução — sem recuar, 'wasteland' nasceria dentro
    # da sessão criada logo acima e o caso deixaria de ser o que se quer medir.
    with store._lock:
        store._connection.execute(
            "UPDATE vocabulario SET criado_em = ? WHERE termo = ?",
            ("2020-01-01T10:00:00-03:00", "wasteland"),
        )
        store._connection.commit()

    janela._caderno.atualizar()
    aplicacao.processEvents()
    cartoes = {c._entrada.termo: c for c in janela._caderno._cartoes}
    checar(
        cartoes["ghoul"].botao_conversa.isEnabled(),
        "palavra com conversa tem o botão vivo",
    )
    checar(
        not cartoes["wasteland"].botao_conversa.isEnabled(),
        "palavra sem conversa tem o botão desabilitado, não ausente",
    )
    checar(
        "não está no histórico" in cartoes["wasteland"].botao_conversa.toolTip(),
        "e o botão desabilitado diz por quê",
    )

    # -- Busca entre TODAS as conversas, na coluna da esquerda.
    outra_sessao = historico.iniciar_sessao(jogo="Elden Ring")
    historico.registrar_fala(
        outra_sessao, autor="VOCÊ", tag="usuario", texto="o que é bonfire?"
    )
    janela.abrir_historico()
    aplicacao.processEvents()
    visor = janela._visor_historico

    def buscar_sessoes(texto: str) -> None:
        visor._busca_sessoes.setText(texto)
        visor._espera_sessoes.stop()  # o amortecedor de 180 ms não espera aqui
        visor._recarregar()
        aplicacao.processEvents()

    buscar_sessoes("bonfire")
    checar(visor._sessao_aberta == outra_sessao, "a busca abre a conversa que casa")
    checar(visor._destaque == "bonfire", "e leva o termo procurado até a transcrição")
    checar(not visor.grab().isNull(), "a lista filtrada desenha")

    buscar_sessoes("ghoul")
    checar(visor._sessao_aberta == sessao, "outro termo leva a outra conversa")

    buscar_sessoes("zzzznadadisso")
    checar(visor._sessao_aberta is None, "termo sem resultado não deixa conversa aberta")
    checar("Nenhuma conversa contém" in visor._cabecalho.text(), "e explica o vazio")
    checar(visor._destaque == "", "o destaque some junto com o resultado")

    buscar_sessoes("")
    checar(visor._sessao_aberta is not None, "limpar a busca devolve a lista inteira")

    # Vindo do caderno com um filtro ativo, o filtro é de quem estava aqui
    # antes — e esconderia da lista justamente a conversa pedida.
    buscar_sessoes("bonfire")
    janela.abrir_conversa(sessao, "ghoul")
    aplicacao.processEvents()
    checar(
        janela._visor_historico._busca_sessoes.text() == "",
        "o salto pelo caderno limpa o filtro de conversas",
    )
    checar(
        janela._visor_historico._sessao_aberta == sessao,
        "e abre a conversa pedida, não a que o filtro deixara aberta",
    )
    janela._visor_historico.close()
    visor.close()

    print("tela inicial")
    # O que a conversa mostra antes de haver conversa. O modelo, a chave e os
    # atalhos globais eram anotações soltas no pé do painel; agora moram aqui.
    from pipboy.events import Tag as TagInicial
    from pipboy.interface.tela_inicial import tecla_legivel

    tela = janela.conversa.tela_inicial
    janela.conversa.limpar()
    aplicacao.processEvents()
    checar(not tela.isHidden(), "com a conversa vazia, a tela inicial está à vista")
    checar(
        not any("Atalhos globais" in texto for texto, _, _ in janela.conversa._mensagens),
        "os atalhos globais não são mais anotação solta na conversa",
    )
    checar(
        janela._configuration.model in tela.diagnostico.text(),
        "o modelo em uso aparece no rodapé da tela inicial",
    )
    checar(
        tecla_legivel("ctrl+alt+p") == "Ctrl+Alt+P" and tecla_legivel("f12") == "F12",
        "as teclas do .env são escritas como se leem numa tecla",
    )

    janela.conversa.atualizar_inicial()
    checar(
        str(store.total()) in tela.cartao_caderno.detalhe,
        f"o cartão do caderno traz o total de agora ({tela.cartao_caderno.detalhe})",
    )
    checar(
        tela.cartao_revisar.destaque == (store.pendentes() > 0),
        "o cartão de revisar se destaca só quando há palavra vencida",
    )
    store.registrar("scrap", "sucata", "", "Fallout")
    janela.caderno_mudou()
    checar(
        str(store.total()) in tela.cartao_caderno.detalhe,
        "uma palavra nova no caderno atualiza o cartão na hora",
    )
    store.remover("scrap")
    janela.caderno_mudou()
    checar(
        janela.conversa.tela_inicial.corpo.text().count(janela.tema.assistant_name.replace("-", "‑")) == 1,
        "o texto chama o assistente pelo nome do tema",
    )

    # Nenhum destes cartões gasta a chave: abrem janelas locais.
    tela.cartao_caderno.click()
    aplicacao.processEvents()
    checar(janela._caderno is not None and janela._caderno.isVisible(), "o cartão abre o caderno")
    janela._caderno.close()
    tela.cartao_historico.click()
    aplicacao.processEvents()
    checar(
        janela._visor_historico is not None and janela._visor_historico.isVisible(),
        "e o outro abre o histórico",
    )
    janela._visor_historico.close()

    # A luz dos cartões é a mesma do caderno.
    ponto = QPointF(40, 12)
    QApplication.sendEvent(
        tela.cartao_caderno, QEnterEvent(ponto, ponto, QPointF(tela.cartao_caderno.mapToGlobal(ponto)))
    )
    checar(
        aguardar(lambda: tela.cartao_caderno._holofote.valor == 1.0),
        "passar o mouse acende o cartão",
    )
    QApplication.sendEvent(tela.cartao_caderno, QEvent(QEvent.Type.Leave))
    QApplication.sendEvent(
        tela.cartao_historico, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason)
    )
    checar(
        aguardar(lambda: tela.cartao_historico._holofote.valor == 1.0),
        "e chegar pelo Tab acende do mesmo jeito",
    )
    QApplication.sendEvent(
        tela.cartao_historico, QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.TabFocusReason)
    )

    # Anotação do sistema convive com a tela; sessão e fala a tiram de cena.
    janela._registrar("aviso qualquer", TagInicial.SISTEMA)
    checar(not tela.isHidden(), "uma anotação do sistema não esconde a tela inicial")
    janela._definir_controles(ativa=True)
    checar(tela.isHidden(), "iniciar a sessão tira a tela de cena")
    atmosfera_inicial = janela.campo_atmosfera.currentText()
    janela.campo_atmosfera.setCurrentText("Completa")
    aplicacao.processEvents()
    janela._definir_controles(ativa=False)
    checar(not tela.isHidden(), "encerrar sem ter falado nada a traz de volta")
    checar(
        any(isinstance(b.graphicsEffect(), EfeitoEntrada) for b in tela._blocos),
        "e ela volta em cascata",
    )
    checar(
        aguardar(lambda: all(b.graphicsEffect() is None for b in tela._blocos)),
        "sem deixar efeito pendurado",
    )
    janela._registrar("Hello, wastelander.", TagInicial.ASSISTENTE, "PIP-BOY")
    checar(tela.isHidden(), "a primeira fala tira a tela de cena")
    janela._definir_controles(ativa=False)
    checar(tela.isHidden(), "e ela não volta enquanto houver conversa")
    janela.conversa.limpar()
    checar(not tela.isHidden(), "limpar a conversa devolve a tela")
    janela.campo_atmosfera.setCurrentText(atmosfera_inicial)
    aplicacao.processEvents()

    # Troca de tema: o glifo e o botão são os do jogo novo.
    tema_antes = janela.campo_jogo.currentText()
    janela._trocar_jogo("Cyberpunk 2077")
    aplicacao.processEvents()
    checar(tela.glifo.text() == "▚", f"o glifo acompanha o tema ({tela.glifo.text()})")
    checar("CONECTAR" in tela.corpo.text(), "e o texto usa o nome do botão daquele tema")
    janela._trocar_jogo(tema_antes)
    aplicacao.processEvents()

    # Estreita e com letra grande, os cartões empilham em vez de cortar o título.
    # O que se confere é a REGRA, e não um resultado fixo: sem fontes no
    # backend offscreen o texto mede diferente do Windows, e "cabe lado a
    # lado" passaria a depender da máquina que roda a suíte.
    from pipboy.design import ESPACO_MD

    def fileira_coerente() -> bool:
        cartoes = (tela.cartao_revisar, tela.cartao_caderno, tela.cartao_historico)
        necessaria = 3 * max(c.largura_ideal() for c in cartoes) + 2 * ESPACO_MD
        return tela.empilhada == (necessaria > min(tela.width(), tela.LARGURA_MAX))

    tamanho_antes = janela.size()
    escala_antes = janela.campo_tamanho_texto.currentText()
    janela.resize(980, 620)
    aplicacao.processEvents()
    checar(fileira_coerente(), "no tamanho mínimo, a fileira segue a conta de largura")
    ideal_padrao = tela.cartao_revisar.largura_ideal()
    janela.campo_tamanho_texto.setCurrentText("Maior")
    aplicacao.processEvents()
    checar(
        tela.cartao_revisar.largura_ideal() > ideal_padrao,
        "com letra maior, cada cartão pede mais largura",
    )
    checar(aguardar(fileira_coerente), "e a fileira refaz a conta sozinha")
    # Só o redimensionamento, sem trocar letra nem tema: é o caso de quem
    # arrasta a borda da janela. O teto de largura sai do caminho para que
    # "larga" seja larga de verdade com qualquer métrica de fonte.
    tela.LARGURA_MAX = 100_000
    tela.resize(100_000, tela.height())
    checar(not tela.empilhada, "larga o bastante, os três voltam a ficar lado a lado")
    tela.resize(260, tela.height())
    checar(tela.empilhada, "estreita a ponto de não caber, a fileira empilha")
    del tela.LARGURA_MAX
    janela.campo_tamanho_texto.setCurrentText(escala_antes)
    janela.resize(tamanho_antes)
    aplicacao.processEvents()

    print("revisão com retorno")
    # Um caderno SÓ desta seção: responder cartões reagenda as palavras, e as
    # do caderno principal ainda são contadas mais adiante.
    from pipboy.interface.movimento import ImagemQueSai
    from pipboy.interface.revisao import JanelaRevisao, quando_volta

    caderno_revisao = VocabularyStore(dados / "revisao-com-retorno.sqlite3")
    caderno_revisao.registrar("wasteland", "terra devastada", "Welcome to the wasteland.", "Fallout")
    caderno_revisao.registrar("to scavenge", "vasculhar", "", "Fallout")
    caderno_revisao.registrar("bounty", "recompensa", "A bounty on your head.", "Red Dead")

    checar(
        (quando_volta(0), quando_volta(1), quando_volta(4))
        == ("na próxima rodada", "amanhã", "em 4 dias"),
        "os dias até a volta são ditos como se diz",
    )

    atmosfera_revisao = janela.campo_atmosfera.currentText()
    janela.campo_atmosfera.setCurrentText("Completa")
    aplicacao.processEvents()
    avisos_revisao: list[str] = []
    qInstallMessageHandler(lambda _t, _c, mensagem: avisos_revisao.append(mensagem))
    rodada_ui = JanelaRevisao(janela, caderno_revisao, parent=janela)
    try:
        rodada_ui.show()
        aplicacao.processEvents()
        checar(rodada_ui._barra.isVisible(), "a barra da rodada aparece com cartões na fila")
        checar(rodada_ui._dica.isVisible(), "antes de revelar, o verso pede para tentar lembrar")
        altura_frente = rodada_ui.height()
        posicao_botoes = rodada_ui._botao_revelar.mapTo(rodada_ui, rodada_ui._botao_revelar.rect().topLeft()).y()

        primeiro = rodada_ui._rodada.atual
        assert primeiro is not None
        rodada_ui._revelar()
        aplicacao.processEvents()
        checar(
            not rodada_ui._dica.isVisible() and rodada_ui._traducao.text() == primeiro.traducao,
            "revelar troca a dica pela resposta",
        )
        checar(
            isinstance(rodada_ui._traducao.graphicsEffect(), EfeitoEntrada),
            "e a resposta entra subindo em vez de aparecer",
        )
        posicao_resposta = rodada_ui._botao_acertei.mapTo(rodada_ui, rodada_ui._botao_acertei.rect().topLeft()).y()
        checar(
            rodada_ui.height() == altura_frente and posicao_resposta == posicao_botoes,
            f"revelar não empurra os botões ({posicao_botoes} → {posicao_resposta})",
        )

        rodada_ui._responder(True)
        aplicacao.processEvents()
        checar(rodada_ui._barra.resultados == [True], "acertar pinta o primeiro segmento")
        checar(
            primeiro.termo in rodada_ui._recado.toolTip() and "volta" in rodada_ui._recado.toolTip(),
            f"e o recado diz quando a palavra volta ({rodada_ui._recado.toolTip()})",
        )
        checar(
            len(rodada_ui._cartao.findChildren(ImagemQueSai)) == 1,
            "o cartão respondido sai deslizando por cima do próximo",
        )
        checar(
            aguardar(lambda: not rodada_ui._cartao.findChildren(ImagemQueSai)),
            "e a foto dele some sozinha",
        )

        segundo = rodada_ui._rodada.atual
        assert segundo is not None
        rodada_ui._revelar()
        rodada_ui._responder(False)
        aplicacao.processEvents()
        checar(rodada_ui._barra.resultados == [True, False], "errar pinta o segmento seguinte")
        checar(
            rodada_ui._recado.toolTip() == f"{segundo.termo} volta na próxima rodada",
            f"e a palavra errada volta na próxima rodada ({rodada_ui._recado.toolTip()})",
        )

        rodada_ui._revelar()
        rodada_ui._responder(False)
        aplicacao.processEvents()
        checar(
            rodada_ui._termo.text() == "1 acerto · 2 erros",
            f"o resumo conjuga acerto no singular ({rodada_ui._termo.text()})",
        )
        checar(
            rodada_ui._meta.text() == "2 palavras ainda vencidas.",
            f"e as vencidas no plural, sem parênteses ({rodada_ui._meta.text()})",
        )
        checar(rodada_ui.height() == altura_frente, "o resumo cabe na mesma altura do cartão")
        aguardar(lambda: not rodada_ui._cartao.findChildren(ImagemQueSai))
        avisos_revisao.clear()
        rodada_ui.update()
        esperar(80)
        checar(
            not [a for a in avisos_revisao if "ainter" in a],
            f"repintar a revisão não briga por pintor ({avisos_revisao[:2]})",
        )

        # Nova rodada zera a barra; atmosfera desligada troca sem foto.
        rodada_ui._nova_rodada()
        checar(rodada_ui._barra.resultados == [], "nova rodada recomeça a barra")
        janela.campo_atmosfera.setCurrentText("Desligada")
        aplicacao.processEvents()
        rodada_ui._revelar()
        rodada_ui._responder(True)
        checar(
            not rodada_ui._cartao.findChildren(ImagemQueSai),
            "com a atmosfera desligada o cartão troca num quadro",
        )
        checar(rodada_ui._recado.toolTip() != "", "mas o recado continua dizendo o que houve")
    finally:
        qInstallMessageHandler(None)
        rodada_ui.close()
        caderno_revisao.close()
        janela.campo_atmosfera.setCurrentText(atmosfera_revisao)
        aplicacao.processEvents()

    print("progresso que responde")
    from datetime import date as Data

    from PySide6.QtGui import QMouseEvent as EventoMouse

    from pipboy.interface.progresso import (
        JanelaProgresso,
        descrever_semana,
        segundas_do_grafico,
    )

    # A virada do ano é o caso que um rótulo "dd/mm" não resolve sozinho.
    segundas = segundas_do_grafico(3, Data(2026, 1, 1))
    checar(
        segundas == [Data(2025, 12, 15), Data(2025, 12, 22), Data(2025, 12, 29)],
        f"as segundas das barras atravessam a virada do ano ({segundas})",
    )
    semanas_teste = [("15/12", 1), ("22/12", 7), ("29/12", 7)]
    checar(
        descrever_semana(semanas_teste, 2, segundas)
        == ("29/12 – 04/01 · esta semana", "7 palavras novas, igual à anterior"),
        "a ficha da semana corrente diz o intervalo e compara com a anterior",
    )
    checar(
        descrever_semana(semanas_teste, 1, segundas)[1] == "7 palavras novas, 6 a mais que a anterior",
        "e diz quanto cresceu",
    )
    checar(
        descrever_semana(semanas_teste, 0, segundas)[1] == "1 palavra nova",
        "a primeira barra não tem com quem se comparar, e fala no singular",
    )

    def mover_em(alvo: QWidget, x: float, y: float) -> None:
        ponto = QPointF(x, y)
        QApplication.sendEvent(
            alvo,
            EventoMouse(
                QEvent.Type.MouseMove, ponto, QPointF(alvo.mapToGlobal(ponto)),
                Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            ),
        )

    atmosfera_progresso = janela.campo_atmosfera.currentText()
    janela.campo_atmosfera.setCurrentText("Completa")
    aplicacao.processEvents()
    nunca_aberto = JanelaProgresso(janela, store, parent=janela)
    checar(
        nunca_aberto.grafico_semanas.crescimento.progresso(7) == 1.0,
        "um painel fotografado sem nunca ter aparecido não sai com as barras vazias",
    )
    nunca_aberto.deleteLater()

    # A linha do tempo lida em instantes fixos, sem relógio nenhum.
    from pipboy.interface.movimento import Crescimento

    linha_do_tempo = Crescimento(janela, 2, reduzir=lambda: False, atraso=120, duracao=300)
    linha_do_tempo._avancar(100.0)
    checar(linha_do_tempo.progresso(0) == 0.0, "antes do atraso, nada cresceu")
    linha_do_tempo._avancar(420.0)
    checar(
        linha_do_tempo.progresso(0) == 1.0 and linha_do_tempo.progresso(1) < 1.0,
        "no fim da duração o primeiro chegou e o segundo, escalonado, ainda não",
    )
    linha_do_tempo.deleteLater()

    avisos_progresso: list[str] = []
    qInstallMessageHandler(lambda _t, _c, mensagem: avisos_progresso.append(mensagem))
    painel = JanelaProgresso(janela, store, parent=janela)
    try:
        painel.show()
        checar(
            painel.grafico_semanas.crescimento.ativo
            and painel.grafico_semanas.crescimento.progresso(0) < 1.0,
            "abrir o painel faz as barras crescerem",
        )
        jogos_atraso = painel.grafico_jogos.crescimento.atraso if painel.grafico_jogos else 10**6
        checar(
            painel.grafico_semanas.crescimento.atraso
            < painel.regua.crescimento.atraso
            < jogos_atraso,
            "cada gráfico começa depois do de cima, na ordem de leitura",
        )
        checar(
            aguardar(lambda: not painel.grafico_semanas.crescimento.ativo
                     and painel.grafico_semanas.crescimento.progresso(7) == 1.0),
            "até chegarem ao tamanho certo",
        )

        grafico = painel.grafico_semanas
        mover_em(grafico, grafico.width() * (2.5 / 8), grafico.height() / 2)
        checar(grafico.apontado == 2, f"o cursor sobre a terceira barra a aponta ({grafico.apontado})")
        checar(aguardar(lambda: grafico._destaque.valor == 1.0), "e o destaque acende")
        QApplication.sendEvent(grafico, QEvent(QEvent.Type.Leave))
        checar(grafico.apontado is None, "sair do gráfico solta o apontado")
        # Lido ANTES de o laço de eventos rodar: um destaque que sumisse num
        # quadro já estaria em zero aqui.
        checar(grafico._destaque.valor > 0.0, "e o destaque apaga em vez de sumir num quadro")
        checar(aguardar(lambda: grafico._destaque.valor == 0.0), "até apagar de todo")

        altura_regua = painel.regua.height()
        mover_em(painel.regua, painel.regua.width() * 0.02, 6)
        checar(
            painel.regua.explicacao.startswith("Novas:"),
            f"apontar um trecho da régua explica a categoria ({painel.regua.explicacao})",
        )
        aplicacao.processEvents()
        checar(
            painel.regua.height() == altura_regua
            and painel.regua.retangulo_explicacao().bottom() <= painel.regua.height(),
            "a explicação cabe no lugar reservado, sem mudar a altura da régua",
        )

        jogos_painel = painel.grafico_jogos
        assert jogos_painel is not None
        checar(
            "%" not in jogos_painel.rotulo_de_valor(0),
            "fora do cursor, a barra de um jogo mostra só o número",
        )
        mover_em(jogos_painel, 10, 5)
        checar(
            jogos_painel.apontado == 0 and "% do caderno" in jogos_painel.rotulo_de_valor(0),
            f"sob o cursor, mostra a fatia do caderno ({jogos_painel.rotulo_de_valor(0)})",
        )
        avisos_progresso.clear()
        painel.update()
        esperar(80)
        checar(
            not [a for a in avisos_progresso if "ainter" in a],
            f"repintar o painel apontado não gera aviso ({avisos_progresso[:2]})",
        )
    finally:
        qInstallMessageHandler(None)
        painel.close()

    janela.campo_atmosfera.setCurrentText("Desligada")
    aplicacao.processEvents()
    calmo = JanelaProgresso(janela, store, parent=janela)
    calmo.show()
    checar(
        not calmo.grafico_semanas.crescimento.ativo
        and calmo.grafico_semanas.crescimento.progresso(7) == 1.0,
        "com a atmosfera desligada as barras já abrem no tamanho certo",
    )
    calmo.close()
    janela.campo_atmosfera.setCurrentText(atmosfera_progresso)
    aplicacao.processEvents()

    print("atalhos diretos")
    # revisar_agora abre um diálogo MODAL: sem alguém para fechá-lo, o exec()
    # nunca voltaria e a suíte penduraria. O tiro agendado é esse alguém.
    def _fechar_modal() -> None:
        ativo = aplicacao.activeModalWidget()
        if ativo is not None:
            ativo.close()

    QTimer.singleShot(120, _fechar_modal)
    janela.revisar_agora()
    checar(True, "Ctrl+R abre a revisão direto, sem passar pelo caderno")

    # O que a chamada direta acima NÃO prova é que a TECLA chega ao método. Os
    # QShortcut nascem em atalhos.py e ficam presos à janela; aqui se pergunta
    # à própria janela quais ela tem, e se um deles de fato dispara a ação.
    # Só filhos DIRETOS: as janelas satélites têm atalhos próprios, e eles não
    # são desta lista.
    from PySide6.QtGui import QShortcut

    instalados = {
        a.key().toString()
        for a in janela.findChildren(QShortcut, options=Qt.FindChildOption.FindDirectChildrenOnly)
    }
    checar(
        instalados == {"F12", "Esc", "Ctrl+B", "Ctrl+H", "Ctrl+R", "Ctrl+M", "Ctrl+L"},
        f"os sete atalhos locais estão instalados ({sorted(instalados)})",
    )
    janela.conversa.setFocus()
    aplicacao.processEvents()
    atalho_l = next(
        a
        for a in janela.findChildren(QShortcut, options=Qt.FindChildOption.FindDirectChildrenOnly)
        if a.key().toString() == "Ctrl+L"
    )
    atalho_l.activated.emit()
    aplicacao.processEvents()
    checar(
        janela.focusWidget() is janela.entrada_texto,
        "e disparar Ctrl+L leva mesmo o cursor ao campo de texto",
    )

    print("modo compacto")
    janela.entrar_modo_compacto()
    aplicacao.processEvents()
    checar(janela._capsula.isVisible(), "cápsula aparece")
    checar(not janela.isVisible(), "janela principal se esconde")
    checar(not janela._capsula.grab().isNull(), "cápsula desenha")
    janela.sair_modo_compacto()
    aplicacao.processEvents()
    checar(janela.isVisible(), "voltar do modo compacto restaura a janela")
    checar(not janela._capsula.isVisible(), "a cápsula se recolhe")

    print("boas-vindas")
    from pipboy.interface.boas_vindas import JanelaBoasVindas

    boas_vindas = JanelaBoasVindas("aviso de teste")
    boas_vindas.show()
    aplicacao.processEvents()
    checar(not boas_vindas.grab().isNull(), "cartão de boas-vindas desenha")
    boas_vindas.close()

    print("regressões da interface")
    # Cada verificação abaixo corresponde a um defeito que já existiu.

    # 1. Reabrir o histórico mostrava a conversa congelada no passado — o que
    #    atinge justamente a sessão que está acontecendo AGORA, a mais
    #    provável de se querer reler. A fala nova vai para a sessão que a
    #    janela tem aberta, que é o caso que a correção promete cobrir.
    janela.abrir_historico()
    aplicacao.processEvents()
    visor_reg = janela._visor_historico
    aberta = visor_reg._sessao_aberta
    antes = len(visor_reg._falas_abertas)
    visor_reg.close()
    assert aberta is not None
    historico.registrar_fala(aberta, autor="VOCÊ", tag="usuario", texto="fala nova")
    janela.abrir_historico()
    aplicacao.processEvents()
    depois = len(janela._visor_historico._falas_abertas)
    checar(depois == antes + 1, f"reabrir o histórico relê a transcrição ({antes}→{depois})")
    janela._visor_historico.close()

    # 1b. Tamanho do texto: acessibilidade, e por isso vale em toda superfície
    #     do programa — inclusive nas janelas satélites e DURANTE a sessão.
    from pipboy.interface.janela import ESCALA_TEXTO_PADRAO

    antes_corpo = janela.fonte("corpo").pointSize()
    antes_lateral = janela.largura_lateral
    antes_secao = janela._rotulos_secao[0].font().pointSize()
    antes_campo = janela._rotulos_campo[0].font().pointSize()

    janela.abrir_caderno()
    aplicacao.processEvents()
    antes_caderno = janela._caderno.busca.font().pointSize()

    janela.campo_tamanho_texto.setCurrentText("Maior")
    aplicacao.processEvents()
    checar(janela.fonte("corpo").pointSize() > antes_corpo, "a rampa cresce")
    checar(janela.largura_lateral > antes_lateral, "a coluna de texto cresce junto")
    # Estes dois recebiam fonte uma vez só, dentro de funções locais da
    # montagem: eram os únicos rótulos fora do alcance de uma repintura.
    checar(
        janela._rotulos_secao[0].font().pointSize() > antes_secao,
        "os títulos de seção acompanham",
    )
    checar(
        janela._rotulos_campo[0].font().pointSize() > antes_campo,
        "e os rótulos de campo também",
    )
    checar(
        janela._caderno.busca.font().pointSize() > antes_caderno,
        "o caderno aberto acompanha sem precisar ser reaberto",
    )
    checar(not janela.grab().isNull(), "a janela desenha inteira na escala maior")
    checar(not janela._caderno.grab().isNull(), "e o caderno também")

    # O travamento de sessão existe para o que vai na abertura da conexão.
    # Letra e atmosfera não vão a lugar nenhum — e são justamente os dois
    # ajustes de acessibilidade, que quem precisa deles precisa DURANTE.
    janela._definir_controles(ativa=True)
    checar(janela.campo_tamanho_texto.isEnabled(), "o tamanho do texto não trava na sessão")
    checar(janela.campo_atmosfera.isEnabled(), "a atmosfera também não")
    checar(not janela.campo_jogo.isEnabled(), "mas o jogo trava, como sempre")
    janela._definir_controles(ativa=False)

    janela.campo_tamanho_texto.setCurrentText(ESCALA_TEXTO_PADRAO)
    aplicacao.processEvents()
    checar(janela.fonte("corpo").pointSize() == antes_corpo, "e volta ao padrão")
    janela._preferencias.salvar()
    checar(
        janela._prefs.extras.get("tamanho_texto") == ESCALA_TEXTO_PADRAO,
        "a escolha é persistida junto das outras preferências",
    )
    janela._caderno.close()

    # 1c. "Reduzir animações" do Windows decide o PADRÃO da atmosfera — e só
    #     o padrão. A preferência do sistema é injetada porque o caminho que
    #     importa é o de quem a ligou, e um teste não mexe na configuração da
    #     máquina de quem o roda.
    import pipboy.interface.janela as mod_janela

    original_movimento = mod_janela.movimento_reduzido
    try:
        mod_janela.movimento_reduzido = lambda: True  # type: ignore[assignment]
        janela._prefs.extras.pop("atmosfera", None)
        janela._aplicar_preferencias()
        aplicacao.processEvents()
        checar(
            janela.campo_atmosfera.currentText() == "Desligada",
            "com o sistema pedindo calma, a atmosfera nasce desligada",
        )
        # 'Discreta' continuaria animando; só 'Desligada' para o movimento, que
        # é literalmente o que o sistema pediu.
        checar(janela.intensidade_atmosfera == 0.0, "e o movimento realmente para")
        checar(janela._atmosfera_veio_do_sistema, "o jogador é avisado de onde isso veio")

        # Escolha gravada vence o sistema: o programa LÊ a preferência dele,
        # não obedece a ela para sempre.
        janela._prefs.extras["atmosfera"] = "Completa"
        janela._aplicar_preferencias()
        aplicacao.processEvents()
        checar(
            janela.campo_atmosfera.currentText() == "Completa",
            "uma escolha já gravada vence o pedido do sistema",
        )
        checar(not janela._atmosfera_veio_do_sistema, "e nesse caso não há o que avisar")

        mod_janela.movimento_reduzido = lambda: False  # type: ignore[assignment]
        janela._prefs.extras.pop("atmosfera", None)
        janela._aplicar_preferencias()
        aplicacao.processEvents()
        checar(
            janela.campo_atmosfera.currentText() == "Completa",
            "sem pedido do sistema, o padrão continua sendo a atmosfera cheia",
        )
    finally:
        mod_janela.movimento_reduzido = original_movimento  # type: ignore[assignment]
        janela._prefs.extras["atmosfera"] = "Completa"
        janela._aplicar_preferencias()
        aplicacao.processEvents()

    # 2. O botão de maximizar ficava preso em "Restaurar" para sempre.
    botao_max = janela.barra_titulo.botao_maximizar
    assert botao_max is not None
    botao_max.definir_maximizada(True)
    checar(botao_max.toolTip() == "Restaurar", "maximizada anuncia 'Restaurar'")
    botao_max.definir_maximizada(False)
    checar(botao_max.toolTip() == "Maximizar", "restaurada volta a anunciar 'Maximizar'")

    # 3. A cápsula voltava ao canto e esquecia onde o jogador a pôs.
    janela.entrar_modo_compacto()
    aplicacao.processEvents()
    janela._capsula.move(120, 140)
    escolhida = janela._capsula.pos()
    janela.sair_modo_compacto()
    aplicacao.processEvents()
    janela.entrar_modo_compacto()
    aplicacao.processEvents()
    checar(janela._capsula.pos() == escolhida, "a cápsula lembra onde foi arrastada")

    # 4. Fechar a cápsula escondia o programa inteiro, sem volta.
    janela._capsula.close()
    aplicacao.processEvents()
    checar(janela.isVisible(), "fechar a cápsula devolve a janela principal")

    # 5. A intensidade da atmosfera parava na porta do caderno: 'Desligada'
    #    continuava entregando varredura, grão e vinheta em força total lá
    #    dentro, porque parar o MOVIMENTO não é o mesmo que atenuar as camadas
    #    estáticas. É um controle de acessibilidade — precisa valer em todo
    #    lugar ou não vale em lugar nenhum.
    janela.campo_atmosfera.setCurrentText("Desligada")
    aplicacao.processEvents()
    checar(janela.intensidade_atmosfera == 0.0, "desligar a atmosfera zera a intensidade")
    janela.abrir_caderno()
    aplicacao.processEvents()
    assert janela._caderno is not None
    checar(
        janela._caderno._cenario._efetiva.varredura == 0.0,
        "atmosfera desligada alcança o cenário do caderno",
    )
    janela._caderno.close()
    janela.campo_atmosfera.setCurrentText("Completa")
    aplicacao.processEvents()
    checar(janela.intensidade_atmosfera == 1.0, "voltar para completa restaura a intensidade")
    # Aberto DEPOIS da escolha, o caderno também precisa nascer atenuado.
    janela.campo_atmosfera.setCurrentText("Discreta")
    aplicacao.processEvents()
    caderno_novo = type(janela._caderno)(janela, store)
    checar(
        caderno_novo._cenario._efetiva.grao < janela._caderno._cenario._atmosfera.grao,
        "caderno criado depois já nasce com a intensidade escolhida",
    )
    caderno_novo.close()
    janela.campo_atmosfera.setCurrentText("Completa")
    aplicacao.processEvents()

    # 6. A paleta era montada por duas listas de papéis copiadas à mão. Um papel
    #    esquecido numa delas só aparecia como KeyError dentro de um paintEvent.
    from pipboy.interface.boas_vindas import _ProvedorMinimo

    checar(
        set(janela.paleta()) == set(PAPEIS_DA_PALETA) == set(_ProvedorMinimo().paleta()),
        "os dois provedores entregam exatamente os papéis declarados",
    )

    # 7. O contrato de estado é público: cápsula, bandeja e campainha dependem
    #    dele e liam nomes privados da janela.
    checar(janela.sessao_ativa is False, "sem sessão, sessao_ativa é falso")
    checar(janela.mudo is False, "sem sessão, mudo é falso")
    checar(janela.nivel_entrada == 0.0, "sem sessão, o nível de entrada é zero")
    checar(janela.limiar_entrada == 0.0, "sem sessão, não há limiar a desenhar")
    checar(janela.estado_texto == janela.tema.idle_text, "parada, a janela mostra o ocioso do tema")

    # 7b. O risco do limiar no medidor. É o encanamento inteiro — sessão →
    #     janela → widget — e ele atravessa três módulos sem teste de tipo que
    #     o cubra, porque o Qt devolve Any em quase tudo.
    janela.medidor.definir_ativo(True)
    janela.medidor.definir_limiar(0.0)
    checar(janela.medidor._limiar == 0.0, "limiar zero não desenha risco")
    janela.medidor.definir_limiar(0.035)
    checar(
        0.0 < janela.medidor._limiar < 1.0,
        f"o limiar entra na régua do medidor ({janela.medidor._limiar:.2f})",
    )
    # Mesma régua para os dois: se o nível e o limiar fossem convertidos por
    # caminhos diferentes, o risco marcaria um ponto que o nível nunca cruza.
    janela.medidor.definir_nivel(0.035)
    checar(
        abs(janela.medidor._nivel_alvo - janela.medidor._limiar) < 1e-9,
        "nível e limiar iguais caem no mesmo ponto da régua",
    )
    janela.medidor.definir_nivel(0.30)
    checar(
        janela.medidor._nivel_alvo > janela.medidor._limiar,
        "fala normal fica à direita do risco",
    )
    janela.medidor.repaint()  # o risco tem que sobreviver a uma pintura real
    janela.medidor.definir_ativo(False)

    # 8. Eventos de uma sessão que já morreu entravam na conversa da seguinte —
    #    e iam para o histórico gravados sob o id errado.
    from pipboy.events import Tag, UiEvent, UiEventKind

    antes_falas = len(janela.conversa._mensagens)
    janela._tratar_evento(
        UiEvent(UiEventKind.LOG, text="fala de sessão morta", tag=Tag.ASSISTENTE, session_id=999)
    )
    checar(
        len(janela.conversa._mensagens) == antes_falas,
        "fala de sessão encerrada não entra na conversa atual",
    )
    janela._tratar_evento(UiEvent(UiEventKind.LOG, text="aviso do sistema", tag=Tag.SISTEMA))
    checar(
        len(janela.conversa._mensagens) == antes_falas + 1,
        "evento sem sessão (id zero) continua passando",
    )

    # 9. Voltar do modo compacto desmaximizava a janela.
    janela.showMaximized()
    aplicacao.processEvents()
    janela.entrar_modo_compacto()
    aplicacao.processEvents()
    janela.sair_modo_compacto()
    aplicacao.processEvents()
    checar(
        bool(janela.windowState() & Qt.WindowState.WindowMaximized),
        "maximizada sobrevive à ida e volta do modo compacto",
    )
    janela.showNormal()
    aplicacao.processEvents()

    print("encerramento")
    janela.close()
    aplicacao.processEvents()
    checar(not janela.isVisible(), "a janela fecha limpa, sem sessão ativa")

    store.close()
    historico.close()

    return relatar()


def relatar() -> int:
    print()
    if _falhas:
        print(f"{_falhas} falha(s).")
        return 1
    print("Tudo certo.")
    return 0


if __name__ == "__main__":
    try:
        codigo = main()
    except Exception:
        # Esta suíte é um roteiro linear: uma exceção no meio dele levava
        # embora o relatório inteiro, e o que sobrava era um traço de pilha
        # sem dizer quantas checagens tinham passado até ali. O traço continua
        # (é ele que aponta o defeito), mas agora acompanhado da conta.
        import traceback

        traceback.print_exc(file=sys.stdout)
        _falhas += 1
        codigo = relatar()
    # Saída dura, de propósito.
    #
    # Este arreio deixa vivos, por necessidade, vários diálogos de topo e o
    # objeto QApplication. Ao encerrar pelo caminho normal, o coletor do
    # Python libera esses invólucros em ordem arbitrária DEPOIS de o Qt já
    # ter destruído os objetos C++ correspondentes, e o processo estala com
    # 0xC000041D em cerca de metade das execuções — um verde que o CI leria
    # como vermelho, de forma intermitente, que é a pior espécie de falso
    # negativo. ``os._exit`` devolve o código sem passar por essa corrida.
    #
    # Isto NÃO mascara um defeito do programa: o caminho de saída real
    # (janela.close() encerrando o laço de eventos, com caderno, histórico,
    # cápsula e campainha abertos) foi medido separadamente e encerra limpo
    # de forma consistente. Quem cria janelas soltas e conexões duplicadas
    # é este arquivo, e é só ele que precisa desta porta.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(codigo)
