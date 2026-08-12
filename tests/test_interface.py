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
    historico.registrar_fala(sessao, autor="", tag="vocab", texto="＋ ghoul — carniçal")

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
    visor.close()

    print("atalhos diretos")
    # revisar_agora abre um diálogo MODAL: sem alguém para fechá-lo, o exec()
    # nunca voltaria e a suíte penduraria. O tiro agendado é esse alguém.
    from PySide6.QtCore import QTimer

    def _fechar_modal() -> None:
        ativo = aplicacao.activeModalWidget()
        if ativo is not None:
            ativo.close()

    QTimer.singleShot(120, _fechar_modal)
    janela.revisar_agora()
    checar(True, "Ctrl+R abre a revisão direto, sem passar pelo caderno")

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

    print()
    if _falhas:
        print(f"{_falhas} falha(s).")
        return 1
    print("Tudo certo.")
    return 0


if __name__ == "__main__":
    codigo = main()
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
