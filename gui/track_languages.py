from __future__ import annotations

import json
import re
import shutil
import unicodedata
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


TEMPLATE_PATH = Path(__file__).resolve().parent / "data" / "track_languages.json"
EMPTY_ALIAS = "@empty"


@dataclass
class TrackLanguage:
    identifier: str
    name: str
    aliases: list[str]

    @classmethod
    def from_dict(cls, data: dict) -> "TrackLanguage":
        identifier, name = str(data["id"]).strip(), str(data["name"]).strip()
        aliases = list(dict.fromkeys(str(alias).strip() for alias in data.get("aliases", []) if str(alias).strip()))
        if not identifier or not name or not aliases: raise ValueError("Invalid track language")
        return cls(identifier, name, aliases)

    def to_dict(self) -> dict:
        data = asdict(self); data["id"] = data.pop("identifier"); return data


def new_language(name: str, aliases: list[str]) -> TrackLanguage:
    return TrackLanguage(uuid.uuid4().hex, name.strip(), aliases)


def ensure_user_catalog(path: Path) -> None:
    if path.exists(): return
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(TEMPLATE_PATH, path)


def restore_user_catalog(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    shutil.copyfile(TEMPLATE_PATH, temporary)
    temporary.replace(path)


def load_languages(path: Path) -> list[TrackLanguage]:
    try:
        ensure_user_catalog(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        result, identifiers, names = [], set(), set()
        for entry in data.get("languages", []):
            try: language = TrackLanguage.from_dict(entry)
            except (KeyError, TypeError, ValueError): continue
            name_key = normalize(language.name)
            if language.identifier not in identifiers and name_key not in names:
                result.append(language); identifiers.add(language.identifier); names.add(name_key)
        return sorted(result, key=lambda language: normalize(language.name))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return []


def save_languages(path: Path, languages: list[TrackLanguage]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({"version": 1, "languages": [language.to_dict() for language in languages]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    plain = "".join(character for character in decomposed if not unicodedata.combining(character))
    return " ".join(re.findall(r"[a-z0-9]+", plain))


def recognize_language(code: str, title: str, languages: list[TrackLanguage]) -> TrackLanguage | None:
    normalized_code, normalized_title = normalize(code), normalize(title)
    for language in languages:
        for alias in language.aliases:
            if alias.casefold() == EMPTY_ALIAS:
                continue
            candidate = normalize(alias)
            if not candidate:
                continue
            fields = (normalized_code,) if len(candidate) <= 3 and " " not in candidate else (normalized_code, normalized_title)
            if any(candidate == field or f" {candidate} " in f" {field} " for field in fields):
                return language
    # @empty es un fallback: primero se da oportunidad a los alias normales
    # de reconocer títulos como "Castellano" aunque falte el código.
    if not normalized_code:
        return next((language for language in languages if any(alias.casefold() == EMPTY_ALIAS for alias in language.aliases)), None)
    return None
