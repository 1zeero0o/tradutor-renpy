import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .model import MARKERS, Entry

MAX_BATCH = 25


class TranslationError(ValueError):
    pass


def google_language(language: str) -> str:
    return {
        "portuguese_br": "pt",
        "portuguese": "pt",
        "english": "en",
        "spanish": "es",
        "french": "fr",
        "german": "de",
        "italian": "it",
        "japanese": "ja",
        "korean": "ko",
        "russian": "ru",
        "chinese": "zh-CN",
    }.get(language, language)


def translate_google(text: str, target: str, source: str = "auto") -> str:
    if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z]{2,4})?", target):
        raise TranslationError("Código de idioma Google inválido. Exemplo: pt, en, es ou zh-CN.")
    if not text.strip() or len(text) > 5000:
        raise TranslationError("O Google aceita nesta versão textos de 1 a 5000 caracteres.")
    placeholders = {}

    def protect(match):
        token = f"RNTKEEP{len(placeholders):04d}X"
        if token in text:
            raise TranslationError("Texto contém um identificador reservado de proteção de tags.")
        placeholders[token] = match[0]
        return token

    protected = MARKERS.sub(protect, text)
    url = "https://translate.googleapis.com/translate_a/single?" + urlencode(
        {
            "client": "gtx",
            "sl": source,
            "tl": target,
            "dt": "t",
            "q": protected,
        }
    )
    request = Request(
        url, headers={"User-Agent": "TradutorRenpy/0.2", "Accept": "application/json"}
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        translated = "".join(segment[0] for segment in payload[0] if segment and segment[0])
    except HTTPError as error:
        raise TranslationError(
            f"Google respondeu HTTP {error.code}. "
            "Verifique o acesso à Internet ou tente mais tarde."
        ) from error
    except (URLError, TimeoutError, OSError) as error:
        raise TranslationError(f"Falha de conexão com o Google: {error}") from error
    except (ValueError, TypeError, IndexError, KeyError) as error:
        raise TranslationError("Resposta inesperada do Google Tradutor.") from error
    for token, marker in placeholders.items():
        pattern = re.compile(r"\s*".join(re.escape(char) for char in token), re.IGNORECASE)
        translated, count = pattern.subn(lambda _, value=marker: value, translated)
        if count != 1:
            raise TranslationError(
                "O Google alterou uma variável/tag; a tradução não foi aplicada."
            )
    probe = Entry("", "", "", 0, text, translation=translated)
    if not translated.strip() or probe.issues:
        raise TranslationError(
            "Tradução vazia ou com variáveis/tags inválidas; revise manualmente."
        )
    return translated
