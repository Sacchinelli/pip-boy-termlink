"""Configuração da aplicação e preferências persistidas.

Duas coisas distintas moram aqui:

* ``AppConfiguration`` — segredos e endpoints, lidos do ``.env`` uma única vez
  na inicialização. Imutável.
* ``Preferences`` — escolhas do usuário na interface (persona, voz, nível…),
  gravadas em JSON para que a próxima sessão já comece configurada.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .constants import APP_SLUG, DEFAULT_GAME_AUDIO_GAIN, DEFAULT_MODEL

LOGGER = logging.getLogger("pip_boy.config")


class ConfigurationError(RuntimeError):
    """Erro de configuração apresentável ao usuário sem stack trace."""


def application_directory() -> Path:
    """Pasta do executável (build congelado) ou da raiz do projeto."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_directory() -> Path:
    """Pasta gravável para log, banco de vocabulário e preferências.

    Usa ``%LOCALAPPDATA%`` no Windows para que o programa continue funcionando
    quando instalado em um diretório somente leitura (Program Files). Se algo
    der errado, cai de volta para a pasta da aplicação.
    """
    candidates: list[Path] = []
    local_appdata = os.getenv("LOCALAPPDATA") or os.getenv("XDG_DATA_HOME")
    if local_appdata:
        candidates.append(Path(local_appdata) / APP_SLUG)
    candidates.append(Path.home() / f".{APP_SLUG.lower()}")
    candidates.append(application_directory())

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".escrita"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return candidate
        except OSError:
            continue
    return application_directory()


def movimento_reduzido() -> bool:
    """O sistema pede menos animação? Falso fora do Windows e em caso de dúvida.

    Windows tem essa preferência desde sempre (*Efeitos visuais → Efeitos de
    animação*, nas versões novas; *Mostrar animações no Windows* nas antigas),
    e quem a desliga já disse uma vez, para o sistema inteiro, que animação lhe
    faz mal. Perguntar de novo, na forma de uma janela que roda partículas e
    cintila na primeira execução, é ignorar uma resposta que já foi dada.

    Mora em ``config.py`` porque é exatamente isto: configuração — só que lida
    do sistema em vez do nosso ``.env``.

    Qualquer falha devolve ``False``. Errar aqui para o lado de "não pediu
    nada" mantém o programa como ele é; errar para o outro lado apagaria a
    identidade visual de quem nunca pediu isso.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        SPI_GETCLIENTAREAANIMATION = 0x1042
        # A API devolve se a ANIMAÇÃO ESTÁ LIGADA, e não se ela foi reduzida;
        # o valor inicial 1 é o que sobra se a chamada não escrever nada.
        animacao = ctypes.c_int(1)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(animacao), 0
        )
        return bool(ok) and not animacao.value
    except (OSError, AttributeError, ValueError):  # pragma: no cover - depende do Windows
        LOGGER.debug("Preferência de animação do sistema indisponível.", exc_info=True)
        return False


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "sim", "on"}


def _env_float(name: str, default: float = 0.0) -> float:
    """Número do ambiente, tolerante à vírgula decimal e a lixo.

    Quem escreve um preço em português digita ``0,30``. Recusar isso — ou pior,
    derrubar a leitura da configuração inteira por causa dele — seria punir a
    grafia certa do idioma do programa. Valor ilegível ou negativo vira o
    padrão, que desliga a estimativa em vez de inventar um número.
    """
    raw = os.getenv(name, "").strip().replace(",", ".")
    if not raw:
        return default
    try:
        valor = float(raw)
    except ValueError:
        LOGGER.warning("%s=%r não é um número; a estimativa de custo fica desligada.", name, raw)
        return default
    return valor if valor > 0.0 else default


@dataclass(frozen=True, slots=True)
class AppConfiguration:
    """Segredos e parâmetros globais. Nunca lidos direto pela thread da UI."""

    api_key: str
    model: str
    hotkey_toggle: str
    hotkey_mute: str
    hotkey_game_audio: str
    global_hotkeys_enabled: bool
    # Preço por MILHÃO de tokens e o símbolo da moeda, para o rodapé traduzir
    # o contador em dinheiro. Zero desliga a estimativa — ver ``custo_de``.
    preco_por_milhao: float
    moeda: str

    @classmethod
    def load(cls, base_directory: Path) -> AppConfiguration:
        # Procura o .env ao lado do programa e também na pasta de dados,
        # cobrindo tanto o uso via código quanto o executável distribuído.
        for candidate in (base_directory / ".env", data_directory() / ".env"):
            if candidate.is_file():
                load_dotenv(candidate, override=False)

        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise ConfigurationError(
                "A variável GEMINI_API_KEY não foi encontrada.\n\n"
                "Crie o arquivo .env a partir de .env.example e informe sua chave.\n"
                f"Locais verificados:\n  {base_directory / '.env'}\n  {data_directory() / '.env'}"
            )
        if api_key.lower().startswith(("sua_chave", "your_key", "cole_")):
            raise ConfigurationError(
                "O arquivo .env ainda contém o valor de exemplo. "
                "Substitua-o pela sua chave real do Gemini."
            )

        return cls(
            api_key=api_key,
            model=os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_MODEL,
            # Atalhos globais NÃO usam Esc/F12: essas teclas pertencem ao jogo.
            hotkey_toggle=os.getenv("HOTKEY_TOGGLE", "ctrl+alt+p").strip(),
            hotkey_mute=os.getenv("HOTKEY_MUTE", "ctrl+alt+m").strip(),
            hotkey_game_audio=os.getenv("HOTKEY_GAME_AUDIO", "ctrl+alt+g").strip(),
            global_hotkeys_enabled=_env_flag("HOTKEYS_GLOBAIS", True),
            preco_por_milhao=_env_float("PRECO_POR_MILHAO_TOKENS"),
            moeda=os.getenv("MOEDA", "").strip() or "US$",
        )

    def custo_de(self, tokens: int) -> str:
        """O contador de tokens em dinheiro, ou ``""`` quando não dá para dizer.

        O rodapé mostrava "48.291 tokens", que não significa nada para quem
        precisa decidir se continua a sessão — e este é um programa construído
        inteiro em torno de gastar menos. Traduzir o número é o passo que
        faltava para ele virar informação acionável.

        **Sem preço configurado não há estimativa.** Um número sobre dinheiro
        que envelheceu é pior que número nenhum: ele não parece errado, e
        ninguém confere. Por isso o preço vem do ``.env``, escrito por quem
        olhou a tabela do próprio projeto, e não de uma constante daqui que
        estaria desatualizada no mês seguinte.

        A estimativa é grosseira por construção, e o ``~`` na tela diz isso: o
        serviço reporta UM total, sem separar entrada de saída nem áudio de
        texto, que têm preços diferentes. O que se pode honestamente oferecer é
        uma taxa média — ordem de grandeza, não fatura.
        """
        if self.preco_por_milhao <= 0.0 or tokens <= 0:
            return ""
        valor = tokens / 1_000_000 * self.preco_por_milhao
        if valor < 0.005:
            # Abaixo disto o arredondamento só sabe dizer "0,00", que ocupa
            # espaço no rodapé para não informar nada.
            return ""
        # Vírgula decimal e ponto de milhar, como se escreve em português.
        formatado = f"{valor:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
        return f"~{self.moeda} {formatado}"

    def redacted_key(self) -> str:
        """Versão segura da chave para exibir em log ou interface."""
        if len(self.api_key) <= 8:
            return "*" * len(self.api_key)
        return f"{self.api_key[:4]}…{self.api_key[-4:]}"


def salvar_chave(chave: str) -> Path:
    """Grava a GEMINI_API_KEY no ``.env`` da pasta de dados e no ambiente.

    A pasta de dados — e não a do programa — porque o executável pode viver
    num diretório somente leitura; ``AppConfiguration.load`` já procura o
    ``.env`` nos dois lugares. Linhas alheias de um ``.env`` existente são
    preservadas: a função troca UMA variável, não reescreve o arquivo do
    usuário.
    """
    # Aspas coladas na colagem: quem copia de um JSON ou de um exemplo de
    # documentação traz "AIza…" com as aspas. Gravadas cruas, o dotenv as
    # descasca na PRÓXIMA execução, mas o processo atual receberia a chave
    # com aspas e falharia na primeira conexão — um erro que some sozinho
    # ao reiniciar, que é a pior espécie de erro para se diagnosticar.
    chave = chave.strip().strip("\"'").strip()
    if not chave:
        raise ConfigurationError("A chave está vazia.")
    if any(c.isspace() for c in chave):
        raise ConfigurationError("A chave não pode conter espaços — confira o que foi colado.")
    if chave.lower().startswith(("sua_chave", "your_key", "cole_")):
        raise ConfigurationError("Esse é o texto de exemplo, não uma chave real.")

    destino = data_directory() / ".env"
    linhas = destino.read_text(encoding="utf-8").splitlines() if destino.is_file() else []
    nova_linha = f"GEMINI_API_KEY={chave}"
    for indice, linha in enumerate(linhas):
        if linha.split("=", 1)[0].strip() == "GEMINI_API_KEY":
            linhas[indice] = nova_linha
            break
    else:
        linhas.append(nova_linha)
    destino.write_text("\n".join(linhas) + "\n", encoding="utf-8")

    # O processo atual também precisa enxergar a chave: o load_dotenv com
    # override=False não substituiria um valor de exemplo já carregado.
    os.environ["GEMINI_API_KEY"] = chave
    return destino


@dataclass
class Preferences:
    """Escolhas da interface, persistidas entre execuções."""

    persona: str = ""
    jogo: str = ""
    voz: str = ""
    nivel: str = ""
    modo: str = ""
    saida_alto_falante: bool = False
    ouvir_jogo: bool = False
    ganho_jogo: float = DEFAULT_GAME_AUDIO_GAIN
    busca_web: bool = False
    dispositivo_entrada: str = ""
    dispositivo_saida: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def _path() -> Path:
        return data_directory() / "preferencias.json"

    @classmethod
    def load(cls) -> Preferences:
        path = cls._path()
        if not path.is_file():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        # Filtrar por NOME de campo não basta: o arquivo fica em
        # %LOCALAPPDATA%, é editável à mão e pode ficar truncado se a máquina
        # cair no meio de um save. Um `"extras": []` bastava para o programa
        # não abrir mais — a interface chama ``extras.get(...)`` e a exceção
        # sobe na construção da janela —, e um `"ganho_jogo": "alto"` derrubava
        # a thread de áudio no meio da sessão. Cada valor é conferido contra o
        # TIPO do padrão; o que não servir volta ao padrão, campo a campo, em
        # vez de descartar o arquivo inteiro.
        padrao = cls()
        aceitos: dict[str, Any] = {}
        for nome in cls.__dataclass_fields__:
            if nome not in raw:
                continue
            valor = raw[nome]
            if cls._compativel(valor, getattr(padrao, nome)):
                aceitos[nome] = valor
            else:
                LOGGER.warning(
                    "Preferência %r ignorada: esperado %s, veio %s.",
                    nome, type(getattr(padrao, nome)).__name__, type(valor).__name__,
                )
        return cls(**aceitos)

    @staticmethod
    def _compativel(valor: Any, modelo: Any) -> bool:
        """O valor lido serve no lugar do padrão?

        ``bool`` é subclasse de ``int`` em Python, então os dois casos são
        tratados à parte: sem isso, ``True`` passaria por um campo numérico e
        ``1`` passaria por um campo de caixa marcada.
        """
        if isinstance(modelo, bool):
            return isinstance(valor, bool)
        if isinstance(modelo, float):
            return isinstance(valor, (int, float)) and not isinstance(valor, bool)
        return isinstance(valor, type(modelo))

    def save(self) -> None:
        # Preferência é conveniência: nunca deve derrubar o programa.
        with contextlib.suppress(OSError):
            self._path().write_text(
                json.dumps(asdict(self), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
