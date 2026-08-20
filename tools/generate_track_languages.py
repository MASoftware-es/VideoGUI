#!/usr/bin/env python3
"""Regenera la plantilla de idiomas desde el paquete ISO Codes de Linux."""

import gettext
import json
from pathlib import Path


SOURCE = Path("/usr/share/iso-codes/json/iso_639-2.json")
OUTPUT = Path(__file__).resolve().parents[1] / "gui" / "data" / "track_languages.json"
EXTRAS = {
    "spa": ["español", "espanol", "castellano", "spanish", "spain"],
    "eng": ["inglés", "ingles", "english"], "fra": ["francés", "frances", "french"],
    "deu": ["alemán", "aleman", "german", "deutsch"], "ita": ["italiano", "italian"],
    "por": ["portugués", "portugues", "portuguese"], "jpn": ["japonés", "japones", "japanese"],
    "zho": ["chino", "chinese", "mandarin"], "kor": ["coreano", "korean"],
    "rus": ["ruso", "russian"], "cat": ["catalán", "catalan", "català"],
    "eus": ["vasco", "euskera", "basque"], "glg": ["gallego", "galego", "galician"],
}
NAME_OVERRIDES = {"roh": "Romanche", "rom": "Romaní"}


def main() -> None:
    entries = json.loads(SOURCE.read_text(encoding="utf-8"))["639-2"]
    try:
        with open("/usr/share/locale/es/LC_MESSAGES/iso_639-2.mo", "rb") as stream:
            translator = gettext.GNUTranslations(stream).gettext
    except OSError:
        translator = lambda value: value
    languages = []
    for entry in entries:
        identifier = entry["alpha_3"]
        english = entry["name"].split(";")[0]
        spanish = NAME_OVERRIDES.get(identifier, translator(entry["name"]).split(";")[0])
        aliases = [entry.get("alpha_2"), identifier, entry.get("bibliographic"), english, spanish, *EXTRAS.get(identifier, [])]
        aliases = list(dict.fromkeys(alias for alias in aliases if alias))
        languages.append({"id": identifier, "name": spanish, "aliases": aliases})
    languages.sort(key=lambda item: item["name"].casefold())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({"version": 1, "languages": languages}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__": main()
