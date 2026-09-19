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

    print("histórico que orienta")
    # Uma conversa longa o bastante para a fala marcada ficar fora da tela.
    sessao_longa = historico.iniciar_sessao(jogo="Fallout")
    for numero in range(24):
        historico.registrar_fala(
            sessao_longa, autor="VOCÊ", tag="usuario", texto=f"pergunta de aquecimento {numero}"
        )
    historico.registrar_fala(sessao_longa, autor="", tag="vocab", texto="⊕ scrap — sucata")

    atmosfera_historico = janela.campo_atmosfera.currentText()
    janela.campo_atmosfera.setCurrentText("Completa")
    aplicacao.processEvents()

    from pipboy.interface.historico import JanelaHistorico

    def fala_a_vista(visor_alvo: JanelaHistorico) -> bool:
        linha = visor_alvo.linha_marcada
        if linha is None:
            return False
        vista = visor_alvo._rolagem_falas.viewport()
        topo = linha.mapTo(vista, linha.rect().topLeft()).y()
        return bool(topo >= 0 and topo + linha.height() <= vista.height())

    janela.abrir_conversa(sessao_longa, "scrap")
    visor = janela._visor_historico
    assert visor is not None
    # Lido antes de o laço rodar: uma cascata aqui ainda estaria em curso.
    primeira_fala = visor._pilha_falas.itemAt(0).widget()
    checar(
        primeira_fala is not None and primeira_fala.graphicsEffect() is None,
        "chegando a uma fala, a coluna não anima em cascata por cima da rolagem",
    )
    checar(
        visor._itens_lista[sessao_longa].isChecked()
        and not any(b.isChecked() for s, b in visor._itens_lista.items() if s != sessao_longa),
        "a sessão aberta fica marcada na lista, e só ela",
    )
    checar(
        aguardar(lambda: fala_a_vista(visor)),
        "a transcrição rola até a fala marcada, que estava fora da tela",
    )
    checar(
        aguardar(lambda: visor.linha_marcada is not None and visor.linha_marcada.pulsando),
        "e a fala pulsa ao chegar",
    )

    visor._itens_lista[sessao_longa].click()
    checar(
        visor._itens_lista[sessao_longa].isChecked(),
        "clicar na sessão já aberta não a desmarca",
    )
    outra = next(s for s in historico.listar_sessoes() if s.id != sessao_longa)
    visor._abrir_sessao(outra)
    checar(
        visor._itens_lista[outra.id].isChecked() and not visor._itens_lista[sessao_longa].isChecked(),
        "abrir outra sessão move a marca",
    )
    primeira_fala = visor._pilha_falas.itemAt(0).widget()
    checar(
        primeira_fala is not None and isinstance(primeira_fala.graphicsEffect(), EfeitoEntrada),
        "e a conversa nova entra em cascata",
    )
    resumo_longo = historico.sessao(sessao_longa)
    assert resumo_longo is not None
    visor._abrir_sessao(resumo_longo)
    visor._busca.setText("aquecimento")
    aplicacao.processEvents()
    primeira_fala = visor._pilha_falas.itemAt(0).widget()
    checar(
        isinstance(primeira_fala, QLabel)
        and "aquecimento" in primeira_fala.text()
        and primeira_fala.graphicsEffect() is None,
        "filtrar pela busca redesenha sem cascata",
    )
    visor._busca.clear()
    checar(
        visor._botao_fechar.font().pointSize() == janela.fonte("corpo_forte").pointSize(),
        "os botões do rodapé usam a fonte dos outros botões",
    )

    janela.campo_atmosfera.setCurrentText("Desligada")
    aplicacao.processEvents()
    janela.abrir_conversa(sessao_longa, "scrap")
    checar(
        aguardar(lambda: fala_a_vista(visor)),
        "com a atmosfera desligada a fala também chega à vista",
    )
    checar(
        visor._rolagem_animada is None and visor.linha_marcada is not None
        and not visor.linha_marcada.pulsando,
        "mas sem rolagem animada nem pulso",
    )
    visor.close()
    historico.remover_sessao(sessao_longa)
    janela.campo_atmosfera.setCurrentText(atmosfera_historico)
    aplicacao.processEvents()

    print("palavra salva chega ao caderno")
    # Os eventos são os mesmos que a sessão publica ao salvar uma palavra; a
    # sessão em si não é aberta (ela gastaria a chave).
    from PySide6.QtGui import QFontMetrics
    from shiboken6 import isValid

    from pipboy.events import Tag as TagPalavra
    from pipboy.events import UiEvent as EventoUi
    from pipboy.events import UiEventKind as TipoEvento
    from pipboy.interface.movimento import SinalFlutuante

    atmosfera_palavra = janela.campo_atmosfera.currentText()
    janela.campo_atmosfera.setCurrentText("Completa")
    aplicacao.processEvents()
    janela.caderno_mudou()
    janela.sinal_do_caderno = None

    store.registrar("scrap", "sucata", "", "Fallout")
    janela._tratar_evento(
        EventoUi(TipoEvento.LOG, text="⊕ scrap — sucata", tag=TagPalavra.VOCAB)
    )
    anotacao = janela.conversa._itens[-1]
    checar(
        isinstance(anotacao.graphicsEffect(), EfeitoEntrada),
        "a anotação de palavra salva entra, em vez de simplesmente estar lá",
    )
    pilula = anotacao.findChild(QLabel)
    checar(
        pilula is not None
        and pilula.minimumWidth() >= QFontMetrics(pilula.font()).horizontalAdvance("⊕ scrap — sucata"),
        "e cabe numa linha só, sem quebrar um texto curto ao meio",
    )
    janela._tratar_evento(EventoUi(TipoEvento.VOCAB_ADDED, payload=store.total()))
    sinal = janela.sinal_do_caderno
    checar(
        isinstance(sinal, SinalFlutuante) and sinal.texto == "+1",
        "o contador do caderno solta um +1",
    )
    checar(f"{store.total()} termos" in janela.rotulo_caderno.text(), "e o número ao lado já é o novo")
    checar(
        sinal is not None and sinal.parentWidget() is janela.rotulo_caderno.parentWidget(),
        "o sinal nasce ao lado do contador, na lateral",
    )
    checar(aguardar(lambda: not isValid(sinal)), "e some sozinho")

    # Reencontro e resposta de quiz publicam o mesmo evento sem mudar o total.
    janela.sinal_do_caderno = None
    janela._tratar_evento(EventoUi(TipoEvento.VOCAB_ADDED, payload=store.total()))
    checar(janela.sinal_do_caderno is None, "sem palavra nova, não há sinal")

    # Palavras que nenhuma outra seção cria: "ghoul" e "raider" já estão no
    # caderno a esta altura, e reencontrá-las não muda o total.
    store.registrar("vertibird", "aeronave de rotor", "", "Fallout")
    store.registrar("nuka", "refrigerante Nuka-Cola", "", "Fallout")
    janela._tratar_evento(EventoUi(TipoEvento.VOCAB_ADDED, payload=store.total()))
    checar(
        janela.sinal_do_caderno is not None and janela.sinal_do_caderno.texto == "+2",
        "duas palavras de uma vez viram +2",
    )

    janela.conversa.repintar()
    checar(
        janela.conversa._itens[-1].graphicsEffect() is None,
        "a troca de tema reconstrói a anotação sem anunciá-la de novo",
    )

    janela.campo_atmosfera.setCurrentText("Desligada")
    aplicacao.processEvents()
    janela.sinal_do_caderno = None
    store.registrar("stimpak", "estimulante", "", "Fallout")
    janela._tratar_evento(EventoUi(TipoEvento.VOCAB_ADDED, payload=store.total()))
    checar(janela.sinal_do_caderno is None, "com a atmosfera desligada o número muda sem sinal")

    for termo in ("scrap", "vertibird", "nuka", "stimpak"):
        store.remover(termo)
    janela.conversa.limpar()
    janela.caderno_mudou()
    janela.campo_atmosfera.setCurrentText(atmosfera_palavra)
    aplicacao.processEvents()

    print("a janela reage ao cursor")
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtGui import QMouseEvent as MovimentoMouse

    from pipboy.interface import atmosfera as mod_atmosfera
    from pipboy.interface.atmosfera import Cenario as CenarioCursor
    from pipboy.interface.atmosfera import atmosfera_de
    from pipboy.interface.componentes import Botao as BotaoIma
    from pipboy.themes import TEMAS as TEMAS_CURSOR

    # A atmosfera é fixada em Completa ANTES de tudo, e não só antes da janela
    # inteira: o ímã de um botão avulso também obedece à regra de movimento, que
    # a janela define pela atmosfera. No runner do CI a animação do Windows vem
    # desligada, a atmosfera nasce Desligada, e o botão avulso não era puxado —
    # passava aqui e reprovava lá, a armadilha do relógio de quadros de novo.
    atmosfera_cursor = janela.campo_atmosfera.currentText()
    janela.campo_atmosfera.setCurrentText("Completa")
    aplicacao.processEvents()

    # -- As partículas fogem: uma partícula parada ao lado do cursor é empurrada
    #    para longe dele, e a chuva de dados só desvia para o lado.
    enxame = mod_atmosfera._Enxame("neve", 1, 7)
    enxame.redimensionar(800, 600)
    particula = enxame._particulas[0]
    particula.x, particula.y, particula.vx, particula.vy = 100.0, 100.0, 0.0, 0.0
    enxame.avancar(0.05, QPointF(110.0, 100.0))
    checar(particula.x < 100.0, f"a partícula foge do cursor ({particula.x:.1f})")
    longe = mod_atmosfera._Enxame("neve", 1, 7)
    longe.redimensionar(800, 600)
    distante = longe._particulas[0]
    distante.x, distante.y, distante.vx, distante.vy = 100.0, 100.0, 0.0, 0.0
    longe.avancar(0.05, QPointF(100.0 + mod_atmosfera.RAIO_FUGA + 5, 100.0))
    checar(distante.x == 100.0, "e fora do raio de fuga nada muda")
    chuva = mod_atmosfera._Enxame("dados", 1, 7)
    chuva.redimensionar(800, 600)
    gota = chuva._particulas[0]
    gota.x, gota.y, gota.vx, gota.vy = 100.0, 100.0, 0.0, 0.0
    chuva.avancar(0.05, QPointF(110.0, 110.0))
    checar(gota.x < 100.0 and gota.y == 100.0, "a chuva de dados só desvia para o lado")

    # -- A luz segue com atraso, assenta, e o relógio pode parar.
    cenario = CenarioCursor()
    cenario.definir(TEMAS_CURSOR["Genérico / Outro"], atmosfera_de("Genérico / Outro"))
    cenario.redimensionar(1000, 800)
    checar(not cenario.precisa_quadros, "sem partícula e sem cursor, a atmosfera não pede quadros")
    cenario.definir_cursor(QPointF(200.0, 200.0))
    cenario.avancar(0.016)
    cenario.definir_cursor(QPointF(700.0, 400.0))
    cenario.avancar(0.016)
    luz, forca = cenario.luz
    checar(
        cenario.precisa_quadros and 200.0 < luz.x() < 700.0,
        f"a luz vai até o cursor com atraso, em vez de colar nele ({luz.x():.0f})",
    )
    checar(not cenario.regiao_da_luz().isEmpty(), "e pede para repintar só onde passou")
    for _ in range(90):
        cenario.avancar(0.033)
    luz, forca = cenario.luz
    checar(
        abs(luz.x() - 700.0) < 1.0 and forca == 1.0 and not cenario.seguindo_cursor,
        "parado o cursor, a luz assenta nele e não pede mais quadros",
    )
    checar(
        cenario.paralaxe.x() < 0.0,
        f"com o cursor à direita, o enxame desliza para a esquerda ({cenario.paralaxe.x():.1f})",
    )

    def brilho_em(cenario_alvo: CenarioCursor, ponto: QPoint) -> int:
        imagem = QImage(1000, 800, QImage.Format.Format_ARGB32_Premultiplied)
        imagem.fill(0)
        pintor = QPainter(imagem)
        cenario_alvo.pintar_fundo(pintor, 1000, 800)
        pintor.end()
        cor = imagem.pixelColor(ponto)
        return cor.red() + cor.green() + cor.blue()

    aceso = brilho_em(cenario, QPoint(700, 400))
    cenario.definir_cursor(None)
    for _ in range(90):
        cenario.avancar(0.033)
    checar(cenario.luz[1] == 0.0 and not cenario.precisa_quadros, "o cursor saiu: a luz apaga e o relógio pode parar")
    checar(
        aceso > brilho_em(cenario, QPoint(700, 400)) + 30,
        "a luz é pintada no FUNDO, atrás do conteúdo, onde o cursor está",
    )

    # -- O ímã do botão principal.
    comum = BotaoIma("Comum")
    comum.atrair(QPointF(5.0, 5.0))
    checar(comum.deslocamento_ima == QPointF(), "um botão comum ignora o ímã")
    ima = BotaoIma("Iniciar", largura_min=150, magnetico=True)
    ima.resize(ima.sizeHint())
    ima.show()  # botão oculto não é puxado: a revisão esconde e mostra os seus
    checar(
        ima.sizeHint().height() == 38 + 2 * BotaoIma.FOLGA_IMA,
        "o botão magnético reserva a folga para onde pode ser puxado",
    )
    ima.atrair(QPointF(ima.width() + 30.0, ima.height() / 2))
    checar(
        aguardar(lambda: ima.deslocamento_ima.x() > 0.0),
        f"com o cursor chegando pela direita, o botão é puxado para a direita ({ima.deslocamento_ima})",
    )
    checar(
        abs(ima.deslocamento_ima.x()) <= BotaoIma.FOLGA_IMA,
        "sem passar da folga que tem para se mover",
    )
    ima.atrair(QPointF(ima.width() + 30.0 + BotaoIma.ALCANCE_IMA * 3, 0.0))
    checar(aguardar(lambda: ima.deslocamento_ima == QPointF()), "longe demais, ele volta ao lugar")
    ima.deleteLater()

    # -- A janela inteira: o rastreador vê o cursor sobre um filho qualquer.
    janela._trocar_jogo("Genérico / Outro")
    aplicacao.processEvents()
    rotulo_filho = janela._rotulos_campo[0]
    checar(not rotulo_filho.hasMouseTracking(), "o alvo do teste é um filho sem rastreamento")
    local = QPointF(3.0, 3.0)
    QApplication.sendEvent(
        rotulo_filho,
        MovimentoMouse(
            QEvent.Type.MouseMove, local, QPointF(rotulo_filho.mapToGlobal(local)),
            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        ),
    )
    esperado_cursor = QPointF(rotulo_filho.mapTo(janela, local.toPoint()))
    checar(
        janela._cenario.cursor == esperado_cursor,
        f"o movimento sobre um rótulo sem rastreamento chega à atmosfera ({janela._cenario.cursor})",
    )
    checar(
        janela._relogios.animando,
        "e liga o relógio de quadros num ambiente que não tem partícula",
    )
    checar(
        aguardar(lambda: not janela._relogios.animando),
        "que para sozinho quando a luz assenta",
    )
    QApplication.sendEvent(janela, QEvent(QEvent.Type.Leave))
    checar(janela._cenario.cursor is None, "sair da janela solta o cursor")

    botao_principal = janela.botao_acao
    perto = botao_principal.mapTo(janela, QPoint(-30, botao_principal.height() // 2))
    janela._cursor_mudou(QPointF(perto))
    checar(
        aguardar(lambda: botao_principal.deslocamento_ima.x() < 0.0),
        "o INICIAR é puxado na direção do cursor que se aproxima pela esquerda",
    )
    janela._cursor_mudou(None)

    # -- O cartão da tela inicial inclina em direção ao cursor.
    cartao_3d = janela.conversa.tela_inicial.cartao_caderno
    borda_direita = QPointF(cartao_3d.width() - 2.0, cartao_3d.height() / 2)
    QApplication.sendEvent(
        cartao_3d, QEnterEvent(borda_direita, borda_direita, QPointF(cartao_3d.mapToGlobal(borda_direita)))
    )
    checar(
        aguardar(lambda: cartao_3d._holofote.valor == 1.0),
        "o cartão acende sob o cursor",
    )
    giro_y, giro_x = cartao_3d.inclinacao()
    checar(
        giro_y < 0.0 and abs(giro_y) <= cartao_3d.INCLINACAO and abs(giro_x) < 1.0,
        f"e inclina: o lado sob o cursor afasta ({giro_y:.1f}°, {giro_x:.1f}°)",
    )
    QApplication.sendEvent(cartao_3d, QEvent(QEvent.Type.Leave))
    checar(
        aguardar(lambda: cartao_3d.inclinacao() == (0.0, 0.0)),
        "ao sair, volta ao plano junto com a luz",
    )
    QApplication.sendEvent(
        cartao_3d, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason)
    )
    checar(
        aguardar(lambda: cartao_3d._holofote.valor == 1.0) and cartao_3d.inclinacao() == (0.0, 0.0),
        "pelo teclado o cartão acende, mas não tem de onde inclinar",
    )
    QApplication.sendEvent(
        cartao_3d, QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.TabFocusReason)
    )

    # -- Atmosfera desligada: nada disso existe.
    janela.campo_atmosfera.setCurrentText("Desligada")
    aplicacao.processEvents()
    janela._cursor_mudou(QPointF(400.0, 300.0))
    checar(janela._cenario.cursor is None, "com a atmosfera desligada o cursor não acende nada")
    janela.campo_atmosfera.setCurrentText(atmosfera_cursor)
    aplicacao.processEvents()

    print("a reação ao cursor se espalha")
    from pipboy.interface.atmosfera import RAIO_ANEL, RAIO_ANEL_CLICAVEL  # noqa: F401
    from pipboy.interface.componentes import CampoSelecao as SeletorLuz
    from pipboy.interface.componentes import movimento_reduzido

    atmosfera_espalha = janela.campo_atmosfera.currentText()
    janela.campo_atmosfera.setCurrentText("Completa")
    aplicacao.processEvents()

    def mover_sobre(alvo: QWidget, local: QPointF) -> None:
        QApplication.sendEvent(
            alvo,
            MovimentoMouse(
                QEvent.Type.MouseMove, local, QPointF(alvo.mapToGlobal(local)),
                Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            ),
        )

    # -- Os botões de ação da janela são todos magnéticos.
    # O caderno já foi aberto a esta altura, e ele é filho da janela: a checagem
    # é de IGUALDADE justamente para pegar os botões dele entrando aqui.
    janela._campo_magnetico._botoes = None
    magneticos = set(janela._campo_magnetico.botoes)
    checar(
        magneticos == {janela.botao_acao, janela.botao_mudo, janela.botao_enviar,
                       janela.botao_caderno, janela.botao_historico},
        f"INICIAR, Mudo, Enviar, Abrir caderno e Histórico sentem o cursor, e só eles ({len(magneticos)})",
    )
    historico_botao = janela.botao_historico
    perto_historico = historico_botao.mapTo(janela, QPoint(historico_botao.width() + 20, historico_botao.height() // 2))
    janela._cursor_mudou(QPointF(perto_historico))
    checar(
        aguardar(lambda: historico_botao.deslocamento_ima.x() > 0.0),
        "e o Histórico é puxado para o cursor que chega pela direita",
    )
    checar(
        abs(historico_botao.deslocamento_ima.x()) <= 4.0,
        "com uma folga menor que a do INICIAR: nos secundários o ímã é um aceno",
    )
    janela._cursor_mudou(None)

    # -- A luz dentro de cada botão acompanha o cursor.
    centro_historico = QPointF(historico_botao.width() * 0.8, historico_botao.height() / 2)
    QApplication.sendEvent(
        historico_botao,
        QEnterEvent(centro_historico, centro_historico, QPointF(historico_botao.mapToGlobal(centro_historico))),
    )
    mover_sobre(historico_botao, QPointF(historico_botao.width() * 0.3, historico_botao.height() / 2))
    checar(
        historico_botao.cursor_local is not None
        and abs(historico_botao.cursor_local.x() - historico_botao.width() * 0.3) < 1.0,
        "a luz dentro do botão vai para onde o cursor está",
    )
    QApplication.sendEvent(historico_botao, QEvent(QEvent.Type.Leave))

    # -- O anel abraça o que é clicável, e o rastreador sabe o que é.
    from pipboy.interface.cursor import abraco_de

    def anel_abraca(widget: QWidget) -> bool:
        # O alvo é refeito a cada consulta: o ímã segue puxando o botão.
        abraco = abraco_de(widget, janela)
        if abraco is None or not janela._cenario.abracando:
            return False
        anel, alvo = janela._cenario.anel, abraco[0]
        return (
            abs(anel.x() - alvo.x()) + abs(anel.y() - alvo.y())
            + abs(anel.width() - alvo.width()) + abs(anel.height() - alvo.height())
        ) < 1.0

    mover_sobre(historico_botao, QPointF(10.0, 10.0))
    checar(
        aguardar(lambda: anel_abraca(historico_botao)),
        f"sobre um botão, o anel abraça o contorno dele ({janela._cenario.anel})",
    )
    mover_sobre(rotulo_filho, QPointF(3.0, 3.0))
    checar(
        aguardar(
            lambda: not janela._cenario.abracando
            and abs(janela._cenario.anel.width() - 2 * RAIO_ANEL) < 0.5
            and abs(janela._cenario.anel.height() - 2 * RAIO_ANEL) < 0.5
        ),
        "sobre um rótulo, ele volta a ser o círculo de repouso",
    )

    # -- Cada clique solta UMA onda, mesmo repassado a cada ancestral.
    ponto_clique = QPointF(4.0, 4.0)
    QApplication.sendEvent(
        rotulo_filho,
        MovimentoMouse(
            QEvent.Type.MouseButtonPress, ponto_clique, QPointF(rotulo_filho.mapToGlobal(ponto_clique)),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        ),
    )
    checar(janela._cenario.ondas == 1, f"um clique vira uma onda, e não uma por ancestral ({janela._cenario.ondas})")
    checar(aguardar(lambda: janela._cenario.ondas == 0), "que se desfaz sozinha")
    QApplication.sendEvent(janela, QEvent(QEvent.Type.Leave))

    # -- Os seletores da lateral acendem sob o cursor.
    seletor = janela.campo_jogo
    checar(isinstance(seletor, SeletorLuz), "o seletor de jogo é um CampoSelecao")
    meio_seletor = QPointF(seletor.width() / 2, seletor.height() / 2)
    QApplication.sendEvent(
        seletor, QEnterEvent(meio_seletor, meio_seletor, QPointF(seletor.mapToGlobal(meio_seletor)))
    )
    checar(aguardar(lambda: seletor.luz == 1.0), "o seletor acende sob o cursor")
    QApplication.sendEvent(seletor, QEvent(QEvent.Type.Leave))
    checar(aguardar(lambda: seletor.luz == 0.0), "e apaga quando ele sai")

    # -- O caderno e a revisão têm os próprios ímãs.
    janela.abrir_caderno()
    aplicacao.processEvents()
    caderno_ima = janela._caderno
    assert caderno_ima is not None
    checar(
        len(caderno_ima._campo_magnetico.botoes) == 5,
        f"os cinco botões do rodapé do caderno são magnéticos ({len(caderno_ima._campo_magnetico.botoes)})",
    )
    fechar = caderno_ima.botao_fechar
    mover_sobre(fechar, QPointF(fechar.width() - 2.0, fechar.height() / 2))
    checar(
        aguardar(lambda: fechar.deslocamento_ima.x() > 0.0),
        "e o rastreador do caderno os puxa pelo cursor dele",
    )
    caderno_ima.close()

    from pipboy.interface.revisao import JanelaRevisao as RevisaoIma

    revisao_ima = RevisaoIma(janela, store, parent=janela)
    checar(
        len(revisao_ima._campo_magnetico.botoes) == 5,
        "as ações da revisão também",
    )
    revisao_ima.close()

    # -- Sem atmosfera, a regra de movimento vale para os botões de toda janela.
    janela.campo_atmosfera.setCurrentText("Desligada")
    aplicacao.processEvents()
    checar(movimento_reduzido(), "a atmosfera desligada chega à regra dos botões")
    janela.botao_historico.atrair(QPointF(-10.0, 10.0))
    checar(
        aguardar(lambda: janela.botao_historico.deslocamento_ima == QPointF()),
        "e nenhum botão é puxado",
    )
    janela.campo_atmosfera.setCurrentText(atmosfera_espalha)
    aplicacao.processEvents()

    print("a resposta ao cursor é fluida")
    from PySide6.QtCore import QObject, QRect
    from PySide6.QtGui import QColor as CorFluida

    from pipboy.interface.cursor import RastreadorDeCursor
    from pipboy.interface.relogios import INTERVALO_QUADRO, intervalo_interativo

    atmosfera_fluida = janela.campo_atmosfera.currentText()
    janela.campo_atmosfera.setCurrentText("Completa")
    aplicacao.processEvents()

    # -- O passo acompanha a tela: um número inteiro de ciclos perto de 15 ms.
    checar(
        intervalo_interativo(144.0) == 14,
        f"numa tela de 144 Hz, 14 ms: cada quadro dura dois ciclos ({intervalo_interativo(144.0)})",
    )
    checar(intervalo_interativo(60.0) == 17, "a 60 Hz, um ciclo")
    checar(intervalo_interativo(120.0) == 17, "a 120 Hz, dois")
    checar(intervalo_interativo(90.0) == 12, "nunca abaixo do piso, que protege a CPU")
    checar(intervalo_interativo(0.0) == 17, "e sem saber a frequência, o passo de 60 Hz")

    # -- O relógio comum, no Windows, vira uma mensagem de baixa prioridade
    #    arredondada ao tique do sistema: 33 ms davam 21 quadros medidos.
    checar(
        janela._relogios._quadros.timerType() == Qt.TimerType.PreciseTimer,
        "o relógio de quadros é preciso",
    )

    # -- Com o cursor em cima ele acelera; assentada a luz, volta ao repouso.
    janela._trocar_jogo("Elden Ring")
    aplicacao.processEvents()
    janela._cursor_mudou(None)
    checar(
        aguardar(lambda: janela._relogios.intervalo == INTERVALO_QUADRO),
        f"sem cursor, o passo de repouso ({janela._relogios.intervalo} ms)",
    )
    janela._cursor_mudou(QPointF(300.0, 300.0))
    rapido = intervalo_interativo(janela._frequencia_da_tela())
    checar(
        janela._relogios.intervalo == rapido,
        f"com o cursor chegando, o passo da tela ({janela._relogios.intervalo} ms)",
    )
    checar(
        aguardar(lambda: janela._relogios.intervalo == INTERVALO_QUADRO),
        "e, assentada a luz sob o cursor parado, o de repouso de novo",
    )
    janela._cursor_mudou(None)

    # -- A auréola apagada fica DESLIGADA: ligado, o efeito desfoca o botão a
    #    cada repintura, com alfa zero ou não.
    botao_fluido = janela.botao_historico
    halo_fluido = botao_fluido.graphicsEffect()
    assert halo_fluido is not None
    checar(not halo_fluido.isEnabled(), "em repouso, a auréola do botão está desligada")
    meio_fluido = QPointF(botao_fluido.width() / 2, botao_fluido.height() / 2)
    QApplication.sendEvent(
        botao_fluido,
        QEnterEvent(meio_fluido, meio_fluido, QPointF(botao_fluido.mapToGlobal(meio_fluido))),
    )
    checar(aguardar(halo_fluido.isEnabled), "ela liga com o cursor em cima")
    QApplication.sendEvent(botao_fluido, QEvent(QEvent.Type.Leave))
    checar(aguardar(lambda: not halo_fluido.isEnabled()), "e desliga de novo quando ele sai")
    suspenso = BotaoIma("Some", paleta=janela.paleta)
    suspenso.suspender_halo()
    suspenso._set_hover(1.0)
    efeito_suspenso = suspenso.graphicsEffect()
    checar(
        efeito_suspenso is not None and not efeito_suspenso.isEnabled(),
        "suspensa para sumir sob outro efeito, nem o hover a religa",
    )
    suspenso.deleteLater()

    # -- Longe e já solto, um botão magnético não repinta a cada movimento.
    janela._trocar_jogo("Genérico / Outro")
    aplicacao.processEvents()
    pinturas: list[int] = []

    class ContaPintura(QObject):
        def eventFilter(self, _alvo: QObject, evento: QEvent) -> bool:
            if evento.type() == QEvent.Type.Paint:
                pinturas.append(1)
            return False

    # O INICIAR, e não o Mudo: o Mudo fica desabilitado fora da sessão, e botão
    # desabilitado solta o ímã antes de chegar à conta que isto confere.
    inicio_fluido = janela.botao_acao
    checar(
        inicio_fluido.isEnabled() and inicio_fluido.magnetico,
        "o alvo do teste é um botão magnético habilitado",
    )
    contador_pinturas = ContaPintura()
    inicio_fluido.installEventFilter(contador_pinturas)
    canto = QPointF(12.0, janela.height() - 12.0)
    centro_inicio = QPointF(inicio_fluido.mapTo(janela, inicio_fluido.rect().center()))
    distancia_inicio = (centro_inicio - canto).manhattanLength()
    janela._cursor_mudou(canto)
    aguardar(lambda: not janela._cenario.seguindo_cursor)
    aplicacao.processEvents()
    pinturas.clear()
    for passo_fluido in range(6):
        janela._cursor_mudou(QPointF(12.0 + passo_fluido, janela.height() - 12.0))
        aplicacao.processEvents()
    checar(
        distancia_inicio > 2 * mod_atmosfera.RAIO_LUZ and not pinturas,
        f"o cursor do outro lado da janela não repinta o INICIAR ({len(pinturas)} pinturas)",
    )
    inicio_fluido.removeEventFilter(contador_pinturas)
    janela._cursor_mudou(None)

    # -- O mesmo movimento chega ao rastreador mais de uma vez — como MouseMove
    #    e como HoverMove —, e cada aviso refaz luz e ímã. Ele avisa uma vez.
    avisos: list[QPointF | None] = []
    rastreador_fluido = RastreadorDeCursor(janela, lambda ponto, _c: avisos.append(ponto))
    rotulo_fluido = janela._rotulos_campo[0]
    for _ in range(3):
        mover_sobre(rotulo_fluido, QPointF(4.0, 4.0))
    checar(len(avisos) == 1, f"três vezes o mesmo movimento, um aviso ({len(avisos)})")
    mover_sobre(rotulo_fluido, QPointF(5.0, 4.0))
    checar(len(avisos) == 2, "e um movimento de verdade avisa de novo")
    aplicacao.removeEventFilter(rastreador_fluido)
    rastreador_fluido.deleteLater()
    QApplication.sendEvent(janela, QEvent(QEvent.Type.Leave))

    # -- A luz e as partículas saem de desenhos prontos. Nenhum pixel deles pode
    #    cair fora da caixa que a repintura por região pede: o que vaza fica na
    #    tela como rastro, e nenhuma outra checagem offscreen o enxerga.
    def vazamento(
        pintar: Callable[[QPainter], None], caixas: list[QRect], largura: int, altura: int
    ) -> tuple[int, int]:
        """Quantos pixels ``pintar`` acende, e quantos deles ficam fora das caixas."""
        imagem = QImage(largura, altura, QImage.Format.Format_ARGB32_Premultiplied)
        imagem.fill(0)
        pintor = QPainter(imagem)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        pintar(pintor)
        pintor.end()
        alfas = bytes(imagem.constBits())[3::4]
        acesos = len(alfas) - alfas.count(0)
        pintor = QPainter(imagem)
        pintor.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        for caixa in caixas:
            pintor.fillRect(caixa, Qt.GlobalColor.black)
        pintor.end()
        restantes = bytes(imagem.constBits())[3::4]
        return acesos, len(restantes) - restantes.count(0)

    for modo in ("motes", "neve", "estatica", "dados"):
        enxame_pronto = mod_atmosfera._Enxame(modo, 40, 5)
        enxame_pronto.redimensionar(800, 600)
        for _ in range(7):
            enxame_pronto.avancar(0.13)
        acesos, fora = vazamento(
            lambda pintor, e=enxame_pronto: e.pintar(pintor, CorFluida("#ffe08a")),
            enxame_pronto.caixas(), 800, 600,
        )
        checar(
            acesos > 0 and fora == 0,
            f"as partículas '{modo}' acendem só dentro das próprias caixas ({acesos} pixels, {fora} fora)",
        )
    # -- A mesma partícula um quadro depois vira UMA caixa; a que renasceu longe
    #    fica com as duas, e não com uma caixa que atravessa a janela.
    parada, andou, renasceu = QRect(10, 10, 20, 20), QRect(11, 10, 20, 20), QRect(500, 400, 20, 20)
    juntas = mod_atmosfera._juntar_pares([parada, parada], [andou, renasceu])
    area_juntas = sum(c.width() * c.height() for c in juntas)
    cobertas = all(any(j.contains(c) for j in juntas) for c in (parada, andou, renasceu))
    checar(
        len(juntas) == 3 and cobertas and area_juntas < 2000,
        f"antes e agora da mesma partícula viram uma caixa, e a que renasceu fica com as duas ({len(juntas)})",
    )
    luz_pronta = CenarioCursor()
    luz_pronta.definir(TEMAS_CURSOR["Fallout"], atmosfera_de("Fallout"))
    luz_pronta.redimensionar(1400, 1000)
    luz_pronta.definir_cursor(QPointF(640.3, 470.6))
    for _ in range(40):
        luz_pronta.avancar(0.033)
    # Um último passo com a luz andando: assentada, ela não pede caixa nenhuma.
    luz_pronta.definir_cursor(QPointF(652.7, 466.2))
    luz_pronta.avancar(0.033)
    acesos, fora = vazamento(luz_pronta.pintar_luz, list(luz_pronta.regiao_da_luz()), 1400, 1000)
    checar(
        acesos > 0 and fora == 0,
        f"a luz do cursor acende só dentro da caixa que pede ({acesos} pixels, {fora} fora)",
    )

    # -- O tubo do Fallout treme em rajadas, e só elas pedem o quadro cheio.
    janela._trocar_jogo("Fallout")
    # A troca de tema se dissolve sob a foto do tema anterior, que cobre a
    # janela inteira até sumir: o brilho da rajada ficaria embaixo dela.
    from pipboy.interface.componentes import TransicaoDeTema as DissolucaoDoTema

    aguardar(lambda: not janela.findChildren(DissolucaoDoTema))
    tubo = janela._cenario
    tubo._proxima_rajada = 60.0
    tubo.avancar(1 / 30)
    quieto = tubo.regiao_suja()
    checar(
        quieto is not None and not tubo.tremendo,
        "com o tubo quieto, o Fallout pede só a região das partículas",
    )
    assert quieto is not None
    checar(
        sum(r.width() * r.height() for r in quieto) < janela.width() * janela.height() * 0.5,
        "que é menor que a janela",
    )

    def brilho_medio() -> float:
        foto = janela.grab().toImage()
        pontos = [
            foto.pixelColor(foto.width() * (i + 1) // 21, foto.height() * (k + 1) // 21)
            for i in range(20) for k in range(20)
        ]
        return sum(c.red() + c.green() + c.blue() for c in pontos) / len(pontos)

    antes_da_rajada = brilho_medio()
    tubo._proxima_rajada = 0.0
    tubo.avancar(1 / 30)
    checar(tubo.tremendo and tubo.regiao_suja() is None, "chegada a rajada, o quadro é cheio")
    tubo._rajada = mod_atmosfera.DURACAO_RAJADA / 2
    durante_a_rajada = brilho_medio()
    checar(
        durante_a_rajada > antes_da_rajada + 3.0,
        f"e o tubo acende a janela inteira enquanto treme ({antes_da_rajada:.1f} → {durante_a_rajada:.1f})",
    )
    passos_rajada = 0
    while tubo.tremendo and passos_rajada < 200:
        tubo.avancar(1 / 30)
        passos_rajada += 1
    checar(
        not tubo.tremendo and tubo.regiao_suja() is None,
        "o quadro que encerra a rajada ainda é cheio: ele apaga o brilho que ficou",
    )
    tubo.avancar(1 / 30)
    checar(tubo.regiao_suja() is not None, "e o seguinte volta ao recorte")
    checar(
        mod_atmosfera.ESPERA_RAJADA[0] <= tubo._proxima_rajada <= mod_atmosfera.ESPERA_RAJADA[1],
        f"com a próxima rajada sorteada para daqui a alguns segundos ({tubo._proxima_rajada:.1f} s)",
    )

    janela.campo_atmosfera.setCurrentText(atmosfera_fluida)
    aplicacao.processEvents()

    print("a luz chega às bordas e o cursor deixa rastro")
    from PySide6.QtCore import QRectF as RetanguloBorda
    from PySide6.QtGui import QPainterPath as QPainterPathBorda

    from pipboy.events import Tag as TagBorda
    from pipboy.interface.componentes import ALCANCE_BORDA, acender_borda
    from pipboy.interface.componentes import Bolha as BolhaBorda
    from pipboy.interface.estilo import RAIO_PADRAO, RAIO_POR_FORMA

    atmosfera_bordas = janela.campo_atmosfera.currentText()
    janela.campo_atmosfera.setCurrentText("Completa")
    aplicacao.processEvents()

    # -- A borda acesa tem de caber na caixa que a janela repinta em volta da
    #    luz: fora dela, ninguém a apagaria quando a luz se afasta.
    checar(
        ALCANCE_BORDA <= mod_atmosfera.RAIO_LUZ,
        f"a luz acende bordas só dentro da caixa que ela repinta ({ALCANCE_BORDA} ≤ {mod_atmosfera.RAIO_LUZ})",
    )

    def assentar_cursor(ponto: QPointF | None) -> None:
        janela._cursor_mudou(ponto)
        aguardar(lambda: not janela._cenario.seguindo_cursor)

    def contorno_de(widget: QWidget) -> QPainterPathBorda:
        caminho = QPainterPathBorda()
        caminho.addRect(RetanguloBorda(widget.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        return caminho

    def acende(widget: QWidget) -> bool:
        imagem = QImage(8, 8, QImage.Format.Format_ARGB32_Premultiplied)
        pintor = QPainter(imagem)
        desenhou = acender_borda(pintor, widget, contorno_de(widget))
        pintor.end()
        return desenhou

    janela._trocar_jogo("Cyberpunk 2077")
    aguardar(lambda: not janela.findChildren(DissolucaoDoTema))
    botao_borda = janela.botao_acao
    perto_do_botao = QPointF(botao_borda.mapTo(janela, QPoint(-40, botao_borda.height() // 2)))
    assentar_cursor(perto_do_botao)
    checar(acende(botao_borda), "com a luz ao lado do INICIAR, a borda dele acende")
    longe_do_botao = QPointF(40.0, janela.height() - 40.0)
    assentar_cursor(longe_do_botao)
    checar(not acende(botao_borda), "com a luz do outro lado da janela, não")
    assentar_cursor(perto_do_botao)
    janela.abrir_caderno()
    aplicacao.processEvents()
    caderno_borda = janela._caderno
    assert caderno_borda is not None
    # A luz posta EM CIMA do botão do caderno, pela tela: a distância não o
    # recusa, e só a janela diferente pode.
    fechar_borda = caderno_borda.botao_fechar
    sobre_o_caderno = janela.mapFromGlobal(fechar_borda.mapToGlobal(fechar_borda.rect().center()))
    assentar_cursor(QPointF(sobre_o_caderno))
    checar(
        not acende(fechar_borda),
        "a luz da janela principal não acende o que é de outra janela, nem passando por cima",
    )
    caderno_borda.close()
    aplicacao.processEvents()

    # -- O painel da conversa não tem contorno em repouso: a luz o revela.
    painel = janela.conversa
    borda_esquerda = painel.mapTo(janela, QPoint(0, painel.height() // 2))
    x_borda, y_borda = borda_esquerda.x(), borda_esquerda.y()

    def destaque_da_borda() -> int:
        """O quanto o fio da borda brilha a mais que o painel logo ao lado.

        A luz do fundo também clareia o painel perto do cursor; a diferença
        para quatro pixels dentro isola o contorno.
        """
        foto = janela.grab().toImage()

        def soma(x: int) -> int:
            cor = foto.pixelColor(x, y_borda)
            return cor.red() + cor.green() + cor.blue()

        return soma(x_borda) - soma(x_borda + 4)

    assentar_cursor(QPointF(x_borda + 30.0, y_borda))
    acesa = destaque_da_borda()
    assentar_cursor(None)
    aguardar(lambda: janela._cenario.luz[1] == 0.0)
    apagada = destaque_da_borda()
    checar(
        acesa > apagada + 40,
        f"o contorno do painel da conversa acende perto do cursor ({apagada} → {acesa})",
    )

    # -- As falas também: a bolha perto do cursor ganha contorno de luz.
    janela.conversa.adicionar("Try saying it out loud.", TagBorda.ASSISTENTE)
    aplicacao.processEvents()
    fala_borda = janela.conversa._itens[-1]
    bolhas_fala = fala_borda.findChildren(BolhaBorda)
    assert bolhas_fala
    bolha_borda = bolhas_fala[0]
    aguardar(
        lambda: fala_borda.graphicsEffect() is None and bolha_borda.graphicsEffect() is None
    )
    canto_bolha = bolha_borda.mapTo(janela, QPoint(bolha_borda.width() + 20, bolha_borda.height() // 2))
    assentar_cursor(QPointF(canto_bolha))
    checar(acende(bolha_borda), "a bolha ao lado do cursor acende o contorno")
    foto_acesa = bolha_borda.grab().toImage()
    assentar_cursor(None)
    aguardar(lambda: janela._cenario.luz[1] == 0.0)
    foto_apagada = bolha_borda.grab().toImage()
    lado_direito = QPoint(bolha_borda.width() - 1, bolha_borda.height() // 2)
    checar(
        foto_acesa.pixelColor(lado_direito) != foto_apagada.pixelColor(lado_direito),
        "e o contorno aceso aparece na própria bolha",
    )
    janela.conversa.limpar()
    aplicacao.processEvents()

    # -- A borda do seletor segue o canto que a folha de estilo dá a ele.
    raio_esperado = RAIO_POR_FORMA.get(janela.atmosfera.forma, RAIO_PADRAO)
    checar(
        janela.campo_jogo._raio_borda == raio_esperado,
        f"o seletor acende com o canto da própria caixa ({janela.campo_jogo._raio_borda})",
    )

    # -- Sem atmosfera, a luz não existe — nem para as bordas.
    assentar_cursor(perto_do_botao)
    janela.campo_atmosfera.setCurrentText("Desligada")
    aplicacao.processEvents()
    checar(not acende(botao_borda), "com a atmosfera desligada, nenhuma borda acende")
    janela.campo_atmosfera.setCurrentText("Completa")
    aplicacao.processEvents()
    assentar_cursor(None)

    # -- Com o cursor descansando sobre a janela, a luz assentada não pede
    #    repintura, mesmo com as partículas pedindo quadros.
    parada = CenarioCursor()
    parada.definir(TEMAS_CURSOR["Elden Ring"], atmosfera_de("Elden Ring"))
    parada.redimensionar(1000, 800)
    parada.definir_cursor(QPointF(500.0, 400.0))
    for _ in range(120):
        parada.avancar(0.033)
    checar(
        parada.precisa_quadros and parada.regiao_da_luz().isEmpty(),
        "com o cursor descansando, a luz assentada não pede repintura; só as partículas pedem",
    )
    parada.definir_cursor(QPointF(520.0, 400.0))
    parada.avancar(0.033)
    checar(not parada.regiao_da_luz().isEmpty(), "e o cursor que volta a andar a acorda")

    # -- O rastro: faíscas no caminho do cursor, no material do jogo.
    rastro = CenarioCursor()
    rastro.definir(TEMAS_CURSOR["The Witcher 3"], atmosfera_de("The Witcher 3"))
    rastro.redimensionar(1000, 800)
    rastro.definir_cursor(QPointF(200.0, 400.0))
    rastro.avancar(0.016)
    checar(rastro.faiscas == 0, "o cursor que acabou de chegar não deixa rastro")
    rastro.definir_cursor(QPointF(400.0, 400.0))
    rastro.avancar(0.016)
    checar(
        rastro.faiscas == mod_atmosfera.SEMEADURA_MAXIMA,
        f"um puxão de 200 px semeia no máximo {mod_atmosfera.SEMEADURA_MAXIMA} faíscas de uma vez "
        f"({rastro.faiscas})",
    )
    xs = sorted(f.x for f in rastro._rastro)
    checar(
        xs[0] < 300.0 < xs[-1],
        f"espalhadas pelo caminho, e não num tufo no fim ({xs[0]:.0f} a {xs[-1]:.0f})",
    )
    alturas = [f.y for f in rastro._rastro]
    rastro.avancar(0.1)
    checar(
        all(f.y < y for f, y in zip(rastro._rastro, alturas, strict=True)),
        "no Witcher, as faíscas são brasas: sobem",
    )
    for passo_rastro in range(30):
        rastro.definir_cursor(QPointF(200.0 + 150.0 * (passo_rastro % 2), 300.0 + passo_rastro))
        rastro.avancar(0.016)
    checar(
        rastro.faiscas <= mod_atmosfera.MAXIMO_RASTRO,
        f"e nunca passam de {mod_atmosfera.MAXIMO_RASTRO} vivas ({rastro.faiscas})",
    )
    # O relógio tem trabalho enquanto houver faísca viva — mesmo com a luz
    # assentada e o cursor parado, quando mais nada pediria quadro.
    sozinha = CenarioCursor()
    sozinha.definir(TEMAS_CURSOR["Genérico / Outro"], atmosfera_de("Genérico / Outro"))
    sozinha.redimensionar(1000, 800)
    sozinha.definir_cursor(QPointF(500.0, 400.0))
    for _ in range(120):
        sozinha.avancar(0.033)
    assentada = not sozinha.seguindo_cursor
    sozinha._semear(QPointF(480.0, 400.0))
    checar(
        assentada and sozinha.seguindo_cursor,
        "com a luz assentada, uma faísca viva basta para o relógio seguir correndo",
    )
    acesos, fora = vazamento(
        lambda pintor: rastro._pintar_rastro(pintor, CorFluida("#ffe08a")),
        rastro._caixas_vivas(), 1000, 800,
    )
    checar(
        acesos > 0 and fora == 0,
        f"cada faísca acende só dentro da caixa que pede ({acesos} pixels, {fora} fora)",
    )
    for _ in range(40):
        rastro.avancar(0.033)
    checar(rastro.faiscas == 0, "com o cursor parado, o rastro some em pouco mais de meio segundo")

    chuva_rastro = CenarioCursor()
    chuva_rastro.definir(TEMAS_CURSOR["Cyberpunk 2077"], atmosfera_de("Cyberpunk 2077"))
    chuva_rastro.redimensionar(1000, 800)
    chuva_rastro.definir_cursor(QPointF(200.0, 400.0))
    chuva_rastro.avancar(0.016)
    chuva_rastro.definir_cursor(QPointF(320.0, 400.0))
    chuva_rastro.avancar(0.016)
    gotas = [f.y for f in chuva_rastro._rastro]
    chuva_rastro.avancar(0.1)
    checar(
        gotas and all(f.y > y for f, y in zip(chuva_rastro._rastro, gotas, strict=True)),
        "no Cyberpunk, dados escorrendo para baixo",
    )
    acesos, fora = vazamento(
        lambda pintor: chuva_rastro._pintar_rastro(pintor, CorFluida("#00f0ff")),
        chuva_rastro._caixas_vivas(), 1000, 800,
    )
    checar(acesos > 0 and fora == 0, f"também dentro das caixas ({acesos} pixels, {fora} fora)")

    quieto_rastro = CenarioCursor()
    quieto_rastro.definir(TEMAS_CURSOR["The Witcher 3"], atmosfera_de("The Witcher 3"))
    quieto_rastro.redimensionar(1000, 800)
    quieto_rastro.movimento = False
    quieto_rastro.definir_cursor(QPointF(200.0, 400.0))
    quieto_rastro.avancar(0.016)
    quieto_rastro.definir_cursor(QPointF(400.0, 400.0))
    quieto_rastro.avancar(0.016)
    checar(quieto_rastro.faiscas == 0, "sem movimento, sem rastro")

    # -- Na janela: o cursor atravessando a conversa deixa faíscas.
    janela._trocar_jogo("The Witcher 3")
    aguardar(lambda: not janela.findChildren(DissolucaoDoTema))
    for passo_rastro in range(6):
        janela._cursor_mudou(QPointF(500.0 + 40.0 * passo_rastro, 400.0))
        janela._avancar_cenario(0.016)
    checar(janela._cenario.faiscas > 0, f"na janela, o cursor deixa rastro ({janela._cenario.faiscas})")
    regiao_rastro = janela._cenario.regiao_suja()
    checar(
        regiao_rastro is not None and all(
            regiao_rastro.contains(QPoint(round(f.x), round(f.y))) for f in janela._cenario._rastro
        ),
        "e a região que o vidro repinta cobre cada faísca",
    )
    assentar_cursor(None)

    janela.campo_atmosfera.setCurrentText(atmosfera_bordas)
    aplicacao.processEvents()

    print("os títulos se decifram")
    from PySide6.QtWidgets import QHBoxLayout as LinhaDecifra

    from pipboy.interface.componentes import RotuloDecifravel

    atmosfera_decifra = janela.campo_atmosfera.currentText()
    janela.campo_atmosfera.setCurrentText("Completa")
    aplicacao.processEvents()

    suporte = QWidget()
    linha_decifra = LinhaDecifra(suporte)
    titulo_teste = RotuloDecifravel("PIP-BOY 3000 · Mk iv")
    linha_decifra.addWidget(titulo_teste)
    regua_teste = QWidget()
    linha_decifra.addWidget(regua_teste, 1)
    suporte.resize(420, 40)
    suporte.show()
    aplicacao.processEvents()
    texto_teste = "PIP-BOY 3000 · Mk iv"
    largura_antes, regua_antes = titulo_teste.width(), regua_teste.x()

    # -- Sob o cursor, embaralha; o texto de verdade continua sendo o texto.
    meio_titulo = QPointF(titulo_teste.width() / 2, titulo_teste.height() / 2)
    QApplication.sendEvent(
        titulo_teste,
        QEnterEvent(meio_titulo, meio_titulo, QPointF(titulo_teste.mapToGlobal(meio_titulo))),
    )
    checar(
        aguardar(lambda: titulo_teste.desenhado != texto_teste),
        f"sob o cursor, o título embaralha ({titulo_teste.desenhado!r})",
    )
    embaralhado = titulo_teste.desenhado
    checar(
        titulo_teste.text() == texto_teste and titulo_teste.accessibleName() == texto_teste,
        "e o texto dele, para quem lê e para o leitor de tela, continua o verdadeiro",
    )
    checar(
        len(embaralhado) == len(texto_teste)
        and all(d == t for d, t in zip(embaralhado, texto_teste, strict=True) if not t.isalnum()),
        "espaços, hífen e o ponto do meio ficam no lugar: só letras e números embaralham",
    )
    trocadas = [d for d, t in zip(embaralhado, texto_teste, strict=True) if d != t]
    checar(
        all(ord(d) < 128 for d in trocadas),
        "com símbolos ASCII, que existem em toda fonte de todo tema",
    )
    checar(
        all(
            d.islower() or d.isdigit()
            for d, t in zip(embaralhado, texto_teste, strict=True)
            if t.islower() and d != t
        ),
        "e a minúscula embaralha em minúscula",
    )
    # Sem as fontes do sistema, toda letra vira uma caixinha da mesma largura,
    # e embaralhar nunca mudaria o tamanho: o que se confere é a trava em si.
    checar(
        titulo_teste.minimumWidth() == titulo_teste.maximumWidth() == largura_antes
        and titulo_teste.width() == largura_antes and regua_teste.x() == regua_antes,
        "a largura fica presa à do texto verdadeiro: a régua ao lado não treme",
    )
    checar(
        aguardar(lambda: not titulo_teste.decifrando)
        and titulo_teste.desenhado == texto_teste,
        "e em meio segundo ele se resolve no texto verdadeiro",
    )
    checar(
        titulo_teste.maximumWidth() == 16777215 and titulo_teste.minimumWidth() == 0,
        "soltando o tamanho que prendeu",
    )

    # -- Um texto novo no meio do embaralho: é para ele que o embaralho vai.
    titulo_teste.decifrar()
    titulo_teste.setText("ÁUDIO")
    checar(
        titulo_teste.text() == "ÁUDIO" and titulo_teste.accessibleName() == "ÁUDIO",
        "trocado no meio do embaralho, o texto já é o novo",
    )
    checar(
        aguardar(lambda: not titulo_teste.decifrando) and titulo_teste.desenhado == "ÁUDIO",
        "e o embaralho se resolve nele",
    )

    # -- Movimento reduzido: nada embaralha.
    janela.campo_atmosfera.setCurrentText("Desligada")
    aplicacao.processEvents()
    titulo_teste.decifrar()
    checar(
        not titulo_teste.decifrando and titulo_teste.desenhado == "ÁUDIO",
        "com a atmosfera desligada, o título não embaralha",
    )
    janela.campo_atmosfera.setCurrentText("Completa")
    aplicacao.processEvents()
    suporte.deleteLater()

    # -- Na janela: a marca e os títulos das seções.
    checar(
        all(isinstance(r, RotuloDecifravel) for r in janela._rotulos_secao),
        f"os {len(janela._rotulos_secao)} títulos de seção se decifram",
    )
    janela._trocar_jogo("Skyrim")
    checar(
        janela.marca.decifrando and janela.marca.text() == janela.tema.header_title,
        "trocado o jogo, o nome novo se decifra — e o texto já é o dele",
    )
    checar(
        aguardar(lambda: not janela.marca.decifrando)
        and janela.marca.desenhado == janela.tema.header_title,
        "até se resolver nele",
    )
    tela_decifra = janela.conversa.tela_inicial
    checar(tela_decifra.isVisible(), "com a conversa vazia, a tela inicial está à vista")
    tela_decifra.entrar()
    checar(tela_decifra.titulo.decifrando, "e chega com o título se decifrando")
    aguardar(lambda: not tela_decifra.titulo.decifrando)

    janela.campo_atmosfera.setCurrentText(atmosfera_decifra)
    aplicacao.processEvents()

    print("o caderno responde ao cursor")
    from dataclasses import replace as substituir

    from pipboy.interface.atmosfera import so_o_cursor
    from pipboy.interface.cursor import CursorVivo

    atmosfera_caderno_vivo = janela.campo_atmosfera.currentText()
    janela.campo_atmosfera.setCurrentText("Completa")
    aplicacao.processEvents()

    # -- A receita só do cursor: o material do jogo fica, o movimento próprio sai.
    receita = so_o_cursor(atmosfera_de("The Witcher 3"))
    checar(
        receita.particulas == "brasas" and receita.densidade == 0
        and receita.tremulacao == 0.0 and receita.interferencia == 0.0,
        "a receita só do cursor guarda o material (brasas, para o rastro) e tira o movimento",
    )
    parado = CenarioCursor()
    parado.definir(TEMAS_CURSOR["Fallout"], so_o_cursor(atmosfera_de("Fallout")))
    parado.redimensionar(800, 600)
    checar(
        not parado.tem_camada_viva and not parado.precisa_quadros,
        "com ela, parado, nem o Fallout pede quadro",
    )
    rala = CenarioCursor()
    rala.definir(TEMAS_CURSOR["Elden Ring"], substituir(atmosfera_de("Elden Ring"), densidade=0))
    checar(
        not rala.tem_camada_viva,
        "partícula com densidade zero não é camada viva: o relógio corria por nada",
    )

    # -- O caderno aberto e parado não anima nada.
    janela._trocar_jogo("The Witcher 3")
    aguardar(lambda: not janela.findChildren(DissolucaoDoTema))
    janela.abrir_caderno()
    aplicacao.processEvents()
    caderno_vivo = janela._caderno
    assert caderno_vivo is not None
    vivo = caderno_vivo._cursor_vivo
    checar(isinstance(vivo, CursorVivo), "o caderno tem a resposta ao cursor da janela principal")
    checar(
        caderno_vivo._cenario.movimento
        and not caderno_vivo._cenario.tem_camada_viva
        and not vivo.animando,
        "aberto e parado, o caderno não anima nada",
    )
    filhos_caderno = [w for w in caderno_vivo.children() if isinstance(w, QWidget)]
    checar(
        vivo.vidro.geometry() == caderno_vivo.rect()
        and vivo.vidro.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        and filhos_caderno[-1] is vivo.vidro,
        "o vidro do cursor cobre o caderno, por cima de tudo, sem roubar clique",
    )

    # -- O cursor sobre o caderno: luz, relógio e rastro, na janela dele.
    viewport_caderno = caderno_vivo.rolagem.viewport()
    for passo_caderno in range(10):
        mover_sobre(viewport_caderno, QPointF(40.0 + 30.0 * passo_caderno, 30.0 + 8.0 * passo_caderno))
        # Um quadro entre um movimento e outro: o rastro nasce do caminho
        # que o cursor fez de um quadro para o seguinte.
        esperar(25)
    checar(
        caderno_vivo._cenario.cursor is not None and vivo.animando,
        "o cursor sobre o caderno acende a luz dele, e o relógio corre",
    )
    checar(caderno_vivo._cenario.faiscas > 0, f"e ele deixa rastro ({caderno_vivo._cenario.faiscas})")
    checar(
        vivo._relogio.timerType() == Qt.TimerType.PreciseTimer,
        "com relógio preciso, como o da janela principal",
    )

    # -- A borda do cartão sob a luz acende; parado tudo, o relógio para.
    cartao_vivo = caderno_vivo._cartoes[0]
    mover_sobre(cartao_vivo, QPointF(cartao_vivo.width() / 2, cartao_vivo.height() / 2))
    checar(
        aguardar(lambda: not vivo.animando),
        "parado o cursor e assentada a luz, o relógio do caderno para",
    )
    checar(acende(cartao_vivo), "o cartão sob a luz do caderno acende a borda")
    # E a borda acesa aparece no próprio cartão: o fio de cima, logo acima da luz.
    fio_de_cima = QPoint(cartao_vivo.width() // 2, 0)
    cartao_aceso = cartao_vivo.grab().toImage().pixelColor(fio_de_cima)
    vivo.esquecer()
    cartao_apagado = cartao_vivo.grab().toImage().pixelColor(fio_de_cima)
    checar(
        cartao_aceso != cartao_apagado,
        f"e aparece no próprio cartão ({cartao_apagado.name()} → {cartao_aceso.name()})",
    )
    mover_sobre(cartao_vivo, QPointF(cartao_vivo.width() / 2, cartao_vivo.height() / 2))

    # -- Cada clique solta uma onda, como na janela principal.
    ponto_clique_caderno = QPointF(12.0, 12.0)
    QApplication.sendEvent(
        viewport_caderno,
        MovimentoMouse(
            QEvent.Type.MouseButtonPress, ponto_clique_caderno,
            QPointF(viewport_caderno.mapToGlobal(ponto_clique_caderno)),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        ),
    )
    checar(caderno_vivo._cenario.ondas == 1, "um clique no caderno solta uma onda")

    # -- Fechado com o cursor em cima, ele não recebe o aviso de que o cursor
    #    saiu: tudo que o seguia se apaga na hora.
    caderno_vivo.close()
    aplicacao.processEvents()
    checar(
        caderno_vivo._cenario.cursor is None
        and caderno_vivo._cenario.luz[1] == 0.0
        and caderno_vivo._cenario.ondas == 0
        and caderno_vivo._cenario.faiscas == 0
        and not vivo.animando,
        "fechado com o cursor em cima, o caderno esquece o cursor na hora",
    )

    # -- Sem atmosfera, nada disso existe no caderno.
    janela.campo_atmosfera.setCurrentText("Desligada")
    aplicacao.processEvents()
    janela.abrir_caderno()
    aplicacao.processEvents()
    mover_sobre(viewport_caderno, QPointF(50.0, 50.0))
    checar(
        caderno_vivo._cenario.cursor is None and not vivo.animando,
        "com a atmosfera desligada, o cursor não acende nada no caderno",
    )
    caderno_vivo.close()
    janela.campo_atmosfera.setCurrentText(atmosfera_caderno_vivo)
    aplicacao.processEvents()

    print("o histórico responde ao cursor")
    from PySide6.QtGui import QColor as QColorHistorico

    from pipboy.interface.atmosfera import ATENUACAO_NO_FUNDO_NU

    atmosfera_historico_vivo = janela.campo_atmosfera.currentText()
    janela.campo_atmosfera.setCurrentText("Completa")
    aplicacao.processEvents()

    # -- A luz atenuada para um fundo sem painel na frente: um terço.
    def centro_da_luz(atenuacao: float) -> int:
        cena = CenarioCursor()
        cena.definir(TEMAS_CURSOR["Fallout"], so_o_cursor(atmosfera_de("Fallout")))
        cena.redimensionar(400, 400)
        cena.definir_cursor(QPointF(200.0, 200.0))
        for _ in range(60):
            cena.avancar(0.033)
        imagem = QImage(400, 400, QImage.Format.Format_ARGB32_Premultiplied)
        imagem.fill(QColorHistorico("#101010"))
        pintor = QPainter(imagem)
        cena.pintar_luz(pintor, atenuacao=atenuacao)
        pintor.end()
        cor = imagem.pixelColor(200, 200)
        return cor.red() + cor.green() + cor.blue()

    cheia, atenuada = centro_da_luz(1.0), centro_da_luz(ATENUACAO_NO_FUNDO_NU)
    checar(
        atenuada < cheia * 0.6,
        f"no fundo nu do histórico, a luz vem atenuada ({atenuada} contra {cheia})",
    )

    janela._trocar_jogo("Cyberpunk 2077")
    aguardar(lambda: not janela.findChildren(DissolucaoDoTema))
    sessao_viva = historico.iniciar_sessao(jogo="Cyberpunk 2077")
    historico.registrar_fala(sessao_viva, autor="VOCÊ", tag="usuario", texto="what is a fixer?")
    historico.registrar_fala(sessao_viva, autor="RELIC", tag="assistente", texto="Um intermediário.")
    janela.abrir_historico()
    aplicacao.processEvents()
    visor = janela._visor_historico
    assert visor is not None
    vivo_historico = visor._cursor_vivo
    checar(isinstance(vivo_historico, CursorVivo), "o histórico tem a resposta ao cursor")
    checar(
        visor._cenario.movimento
        and not visor._cenario.tem_camada_viva
        and not vivo_historico.animando,
        "aberto e parado, o histórico não anima nada",
    )

    # -- O cursor sobre ele: luz, rastro, e a borda da sessão sob a luz.
    item_sessao = next(iter(visor._itens_lista.values()))
    for passo_historico in range(8):
        mover_sobre(item_sessao, QPointF(10.0 + 20.0 * passo_historico, 12.0))
        esperar(25)
    checar(
        visor._cenario.cursor is not None and vivo_historico.animando
        and visor._cenario.faiscas > 0,
        f"o cursor sobre o histórico acende a luz e deixa rastro ({visor._cenario.faiscas})",
    )
    checar(aguardar(lambda: not vivo_historico.animando), "e o relógio dele para quando tudo assenta")
    checar(acende(item_sessao), "a sessão sob a luz acende a borda")

    # -- A luz aparece no fundo liso: na parte vazia da transcrição, onde o
    #    fundo é o que se vê.
    vazio_falas = visor._rolagem_falas.viewport()
    ponto_vazio = QPoint(vazio_falas.width() // 2, vazio_falas.height() * 3 // 4)
    mover_sobre(vazio_falas, QPointF(ponto_vazio))
    aguardar(lambda: not vivo_historico.animando)
    ponto_fundo = vazio_falas.mapTo(visor, ponto_vazio)
    fundo_aceso = visor.grab().toImage().pixelColor(ponto_fundo)
    vivo_historico.esquecer()
    fundo_apagado = visor.grab().toImage().pixelColor(ponto_fundo)
    checar(
        fundo_aceso != fundo_apagado,
        f"a luz aparece no fundo do histórico ({fundo_apagado.name()} → {fundo_aceso.name()})",
    )

    # -- A atmosfera da janela principal chega ao histórico.
    janela.campo_atmosfera.setCurrentText("Desligada")
    aplicacao.processEvents()
    mover_sobre(item_sessao, QPointF(20.0, 12.0))
    checar(
        not visor._cenario.movimento and visor._cenario.cursor is None
        and not vivo_historico.animando,
        "com a atmosfera desligada, o histórico também não acende nada",
    )
    janela.campo_atmosfera.setCurrentText(atmosfera_historico_vivo)
    aplicacao.processEvents()

    # -- Escondido com o cursor em cima, ele esquece o cursor.
    janela.campo_atmosfera.setCurrentText("Completa")
    aplicacao.processEvents()
    mover_sobre(item_sessao, QPointF(30.0, 12.0))
    visor.close()
    aplicacao.processEvents()
    checar(
        visor._cenario.cursor is None and not vivo_historico.animando,
        "fechado com o cursor em cima, o histórico esquece o cursor",
    )
    historico.remover_sessao(sessao_viva)
    janela.campo_atmosfera.setCurrentText(atmosfera_historico_vivo)
    aplicacao.processEvents()

    print("o anel abraça o que se pode clicar")
    from PySide6.QtCore import QRectF as RetanguloAbraco

    from pipboy import design as design_abraco
    from pipboy.interface.cursor import FOLGA_ABRACO

    atmosfera_abraco = janela.campo_atmosfera.currentText()
    janela.campo_atmosfera.setCurrentText("Completa")
    aplicacao.processEvents()

    # -- O contorno abraçado: o corpo do botão, com folga, no canto da forma.
    botao_abraco = janela.botao_historico
    abraco_botao = abraco_de(botao_abraco, janela)
    assert abraco_botao is not None
    corpo_na_janela = botao_abraco.corpo.translated(QPointF(botao_abraco.mapTo(janela, QPoint(0, 0))))
    checar(
        abraco_botao[0] == corpo_na_janela.adjusted(-FOLGA_ABRACO, -FOLGA_ABRACO, FOLGA_ABRACO, FOLGA_ABRACO),
        "o anel abraça o CORPO do botão, com uma folga em volta, sem a margem do ímã",
    )
    canto_da_forma = {"chanfrada": 3.0, "reta": 2.0}.get(botao_abraco.forma, float(design_abraco.RAIO))
    checar(
        abraco_botao[1] == canto_da_forma + FOLGA_ABRACO,
        f"com o canto da forma do tema ({abraco_botao[1]})",
    )
    seletor_abraco = janela.campo_nivel
    abraco_seletor = abraco_de(seletor_abraco, janela)
    checar(
        abraco_seletor is not None
        and abraco_seletor[1] == seletor_abraco.raio_borda + FOLGA_ABRACO,
        "e o seletor, com o canto que a folha de estilo dá a ele",
    )

    # -- O ímã puxa o botão, e o contorno vai junto.
    ima_abraco = BotaoIma("Puxado", largura_min=150, magnetico=True)
    ima_abraco.resize(ima_abraco.sizeHint())
    ima_abraco.show()
    solto = abraco_de(ima_abraco, ima_abraco)
    ima_abraco.atrair(QPointF(ima_abraco.width() + 30.0, ima_abraco.height() / 2))
    aguardar(lambda: ima_abraco.deslocamento_ima.x() > 2.0)
    puxado = abraco_de(ima_abraco, ima_abraco)
    checar(
        solto is not None and puxado is not None
        and abs(puxado[0].x() - solto[0].x() - ima_abraco.deslocamento_ima.x()) < 0.01,
        "o ímã puxa o botão e o contorno abraçado vai junto",
    )

    # -- Grande demais para abraçar, o anel só cresce, como antes. Um painel
    #    inteiro: largo E alto, que é o que lê como moldura em vez de alvo.
    largo = QWidget()
    largo.setCursor(Qt.CursorShape.PointingHandCursor)
    largo.resize(700, 300)
    largo.show()
    checar(abraco_de(largo, largo) is None, "um painel inteiro não é abraçado")
    faixa = BotaoIma("Larga e baixa", largura_min=700)
    faixa.resize(faixa.sizeHint())
    faixa.show()
    checar(
        abraco_de(faixa, faixa) is not None,
        "mas uma faixa larga e baixa, como uma ficha de sugestão, é",
    )
    faixa.deleteLater()
    crescido = CenarioCursor()
    crescido.definir(TEMAS_CURSOR["Genérico / Outro"], atmosfera_de("Genérico / Outro"))
    crescido.redimensionar(1000, 800)
    crescido.definir_cursor(QPointF(300.0, 300.0), sobre_clicavel=True)
    crescido.definir_abraco(None)
    for _ in range(60):
        crescido.avancar(0.033)
    checar(
        not crescido.abracando
        and abs(crescido.anel.width() - 2 * mod_atmosfera.RAIO_ANEL_CLICAVEL) < 0.5,
        "e sobre ele o anel cresce em círculo",
    )

    # -- Um botão que já não existe não derruba o quadro seguinte.
    efemero = BotaoIma("Some logo")
    efemero.show()
    efemero.deleteLater()
    aplicacao.processEvents()
    aplicacao.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    checar(abraco_de(efemero, janela) is None, "o botão destruído sob o cursor não abraça nem derruba nada")

    # -- O rastreador entrega QUAL clicável está sob o cursor.
    sob_cursor: list[QWidget | None] = []
    rastreador_abraco = RastreadorDeCursor(janela, lambda _p, alvo: sob_cursor.append(alvo))
    mover_sobre(botao_abraco, QPointF(12.0, 12.0))
    mover_sobre(rotulo_filho, QPointF(5.0, 5.0))
    checar(
        len(sob_cursor) >= 2 and sob_cursor[-2] is botao_abraco and sob_cursor[-1] is None,
        "o rastreador entrega o botão sob o cursor, e nada sobre um rótulo",
    )
    aplicacao.removeEventFilter(rastreador_abraco)
    rastreador_abraco.deleteLater()

    # -- A meio caminho entre o círculo e o contorno, o anel pinta dentro da
    #    própria caixa: o que vaza fica na tela como rastro.
    meio_caminho = CenarioCursor()
    meio_caminho.definir(TEMAS_CURSOR["Cyberpunk 2077"], atmosfera_de("Cyberpunk 2077"))
    meio_caminho.redimensionar(1000, 800)
    meio_caminho.definir_cursor(QPointF(200.0, 200.0), sobre_clicavel=True)
    meio_caminho.definir_abraco((RetanguloAbraco(220.0, 180.0, 220.0, 50.0), 8.0))
    for _ in range(3):
        meio_caminho.avancar(0.016)
    acesos, fora = vazamento(meio_caminho._pintar_anel_e_ondas, meio_caminho._caixas_vivas(), 1000, 800)
    checar(
        acesos > 0 and fora == 0,
        f"a meio caminho, o anel pinta só dentro da caixa que pede ({acesos} pixels, {fora} fora)",
    )
    for _ in range(40):
        meio_caminho.avancar(0.033)
    checar(
        meio_caminho.abracando
        and abs(meio_caminho.anel.x() - 220.0) < 0.5
        and abs(meio_caminho.anel.width() - 220.0) < 0.5
        and abs(meio_caminho.anel.height() - 50.0) < 0.5,
        f"e chega ao contorno inteiro ({meio_caminho.anel})",
    )
    meio_caminho.definir_cursor(None)
    checar(not meio_caminho.abracando, "o cursor que sai solta o abraço")

    # -- O caderno também: o CursorVivo abraça os botões dele.
    janela.abrir_caderno()
    aplicacao.processEvents()
    caderno_abraco = janela._caderno
    assert caderno_abraco is not None
    fechar_abraco = caderno_abraco.botao_fechar
    mover_sobre(fechar_abraco, QPointF(fechar_abraco.width() / 2, fechar_abraco.height() / 2))
    checar(
        aguardar(lambda: caderno_abraco._cenario.abracando),
        "no caderno, o anel abraça o botão sob o cursor",
    )
    caderno_abraco.close()
    aplicacao.processEvents()

    for temporario in (ima_abraco, largo):
        temporario.deleteLater()
    janela.campo_atmosfera.setCurrentText(atmosfera_abraco)
    aplicacao.processEvents()

    print("as sugestões se tocam")
    from pipboy.interface.tela_inicial import FichaSugestao

    atmosfera_fichas = janela.campo_atmosfera.currentText()
    janela.campo_atmosfera.setCurrentText("Completa")
    aplicacao.processEvents()
    tela_fichas = janela.conversa.tela_inicial
    tela_fichas.atualizar()
    aplicacao.processEvents()

    fichas = tela_fichas.fichas
    checar(
        len(fichas) == 3 and all(isinstance(f, FichaSugestao) for f in fichas),
        "os três exemplos viraram fichas",
    )
    palavra_ficha = janela.resumo_inicial().palavra or "loot"
    checar(
        fichas[0].frase == f"O que significa ‘{palavra_ficha}’?"
        and fichas[0].text() == f"“{fichas[0].frase}”",
        f"a primeira pergunta pela palavra do caderno ({fichas[0].frase})",
    )
    checar(
        all(f.frase in f.accessibleName() for f in fichas),
        "e cada ficha diz ao leitor de tela o que vai escrever",
    )

    # -- O clique escreve no campo de texto, e não envia.
    janela.entrada_texto.clear()
    mensagens_antes = list(janela.conversa._mensagens)
    fichas[1].click()
    aplicacao.processEvents()
    checar(
        janela.entrada_texto.text() == fichas[1].frase
        and janela.entrada_texto.cursorPosition() == len(fichas[1].frase),
        "o clique escreve a pergunta no campo de texto, com o cursor no fim",
    )
    checar(
        janela.conversa._mensagens == mensagens_antes and janela._worker is None,
        "e não envia nada: nem a mensagem, nem o aviso de sessão",
    )
    janela.entrada_texto.clear()

    # -- Sob o cursor, a ficha sobe; o anel abraça o corpo já subido.
    ficha_viva = fichas[2]
    meio_ficha = QPointF(ficha_viva.width() / 2, ficha_viva.height() / 2)
    topo_repouso = ficha_viva.corpo.top()
    QApplication.sendEvent(
        ficha_viva, QEnterEvent(meio_ficha, meio_ficha, QPointF(ficha_viva.mapToGlobal(meio_ficha)))
    )
    checar(
        aguardar(lambda: ficha_viva.elevacao == FichaSugestao.SUBIDA),
        "sob o cursor, a ficha sobe",
    )
    checar(
        abs(topo_repouso - ficha_viva.corpo.top() - FichaSugestao.SUBIDA) < 0.01,
        "o corpo dela sobe junto",
    )
    abraco_ficha = abraco_de(ficha_viva, janela)
    corpo_ficha = ficha_viva.corpo.translated(QPointF(ficha_viva.mapTo(janela, QPoint(0, 0))))
    checar(
        abraco_ficha is not None
        and abraco_ficha[0] == corpo_ficha.adjusted(-FOLGA_ABRACO, -FOLGA_ABRACO, FOLGA_ABRACO, FOLGA_ABRACO)
        and abraco_ficha[1] == ficha_viva.raio_borda + FOLGA_ABRACO,
        "e o anel do cursor abraça a ficha subida, no canto dela",
    )
    QApplication.sendEvent(ficha_viva, QEvent(QEvent.Type.Leave))
    checar(aguardar(lambda: ficha_viva.elevacao == 0.0), "e desce quando o cursor sai")

    # -- Movimento reduzido: acende, mas não sobe.
    janela.campo_atmosfera.setCurrentText("Desligada")
    aplicacao.processEvents()
    QApplication.sendEvent(
        ficha_viva, QEnterEvent(meio_ficha, meio_ficha, QPointF(ficha_viva.mapToGlobal(meio_ficha)))
    )
    aplicacao.processEvents()
    checar(ficha_viva.elevacao == 0.0, "com a atmosfera desligada, a ficha não sobe")
    QApplication.sendEvent(ficha_viva, QEvent(QEvent.Type.Leave))
    janela.campo_atmosfera.setCurrentText("Completa")
    aplicacao.processEvents()

    # -- Sem espaço para as três numa linha, uma sobre a outra.
    largura_tela = tela_fichas.width()
    tela_fichas.resize(300, tela_fichas.height())
    tela_fichas._ajustar_fileira()
    checar(tela_fichas.fichas_empilhadas, "numa tela estreita, as fichas se empilham")
    tela_fichas.resize(largura_tela, tela_fichas.height())
    tela_fichas._ajustar_fileira()
    checar(
        not tela_fichas.fichas_empilhadas or sum(f.sizeHint().width() for f in fichas) > largura_tela,
        "e voltam para a linha quando cabem",
    )

    janela.campo_atmosfera.setCurrentText(atmosfera_fichas)
    aplicacao.processEvents()

    print("a revisão e o progresso respondem ao cursor")
    from pipboy.interface.atmosfera import ATENUACAO_NO_FUNDO_NU as ATENUACAO_NUA
    from pipboy.interface.progresso import JanelaProgresso as ProgressoVivo
    from pipboy.interface.revisao import JanelaRevisao as RevisaoViva

    atmosfera_satelites = janela.campo_atmosfera.currentText()
    janela.campo_atmosfera.setCurrentText("Completa")
    aplicacao.processEvents()

    def responde_ao_cursor(satelite: QWidget, alvo: QWidget, nome: str) -> None:
        """A bateria que toda janela satélite tem de passar."""
        vivo = satelite._cursor_vivo
        checar(
            isinstance(vivo, CursorVivo)
            and satelite._cenario.movimento
            and not satelite._cenario.tem_camada_viva
            and not vivo.animando,
            f"a {nome} aberta e parada não anima nada",
        )
        for passo in range(8):
            mover_sobre(alvo, QPointF(12.0 + 14.0 * passo, 10.0 + 4.0 * passo))
            esperar(25)
        checar(
            satelite._cenario.cursor is not None
            and vivo.animando
            and satelite._cenario.faiscas > 0,
            f"o cursor sobre a {nome} acende a luz e deixa rastro ({satelite._cenario.faiscas})",
        )
        meio_alvo = QPointF(alvo.width() / 2, alvo.height() / 2)
        mover_sobre(alvo, meio_alvo)
        checar(aguardar(lambda: not vivo.animando), f"e o relógio da {nome} para quando assenta")
        checar(acende(alvo), f"o que está sob a luz acende a borda na {nome}")
        # A luz na margem da janela, e a medida 60 px acima dela: dentro do
        # alcance da luz, fora do anel, e longe de qualquer botão opaco — a luz
        # do fundo não aparece por cima de um.
        margem = QPointF(satelite.width() - 12.0, satelite.height() / 2)
        mover_sobre(satelite, margem)
        aguardar(lambda: not vivo.animando)
        ponto_nu = QPoint(round(margem.x()), round(margem.y()) - 60)
        aceso = satelite.grab().toImage().pixelColor(ponto_nu)
        vivo.esquecer()
        apagado = satelite.grab().toImage().pixelColor(ponto_nu)
        checar(
            aceso != apagado,
            f"e a luz aparece no fundo liso da {nome} ({apagado.name()} → {aceso.name()})",
        )
        # Escondida com o cursor em cima, ela não recebe o aviso de saída.
        mover_sobre(alvo, meio_alvo)
        satelite.hide()
        aplicacao.processEvents()
        checar(
            satelite._cenario.cursor is None and not vivo.animando,
            f"escondida com o cursor em cima, a {nome} esquece o cursor",
        )
        satelite.show()
        aplicacao.processEvents()

    revisao_viva = RevisaoViva(janela, store, parent=janela)
    revisao_viva.show()
    aplicacao.processEvents()
    responde_ao_cursor(revisao_viva, revisao_viva._botao_sair, "revisão")
    checar(
        revisao_viva._campo_magnetico is revisao_viva._cursor_vivo.campo,
        "o ímã da revisão é o do próprio CursorVivo, e não um campo à parte",
    )
    revisao_viva.close()
    aplicacao.processEvents()

    progresso_vivo = ProgressoVivo(janela, store, parent=janela)
    progresso_vivo.show()
    aplicacao.processEvents()
    responde_ao_cursor(progresso_vivo, progresso_vivo._botao_fechar, "tela de progresso")
    progresso_vivo.close()
    aplicacao.processEvents()

    # -- A atenuação da luz num fundo nu é a mesma para todas elas.
    checar(
        0.0 < ATENUACAO_NUA < 1.0,
        f"a luz num fundo sem painel na frente vem atenuada, em toda janela ({ATENUACAO_NUA})",
    )

    janela.campo_atmosfera.setCurrentText(atmosfera_satelites)
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
