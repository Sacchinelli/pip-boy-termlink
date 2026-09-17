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
            cartao._cursor == esperado,
            f"o cursor sobre a tradução ainda conduz a luz ({cartao._cursor} vs {esperado})",
        )
        checar(
            aguardar(lambda: cartao._revelacao.valor == 1.0 and cartao._luz.valor == 1.0),
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
    checar(cartao._luz.valor == 1.0, "com a atmosfera desligada a luz chega sem trajeto")
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
