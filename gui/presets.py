from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


VIDEO_DEFAULTS: dict[str, Any] = {
    "copy_video": False, "video_codec": "h264", "resolution": "hd_720", "resolution_mode": "width",
    "custom_width": 1280, "custom_height": 720, "preserve_aspect": False,
    "aspect_ratio": "original", "fit_mode": "crop", "add_borders": False,
    "rate_control": "quality", "quality": 30, "bitrate_mbps": 4.0,
    "max_bitrate_mbps": 6.0,
}
AUDIO_DEFAULTS: dict[str, Any] = {"audio_codec": "mp3", "normalize": True}
LANGUAGE_FILTER_DEFAULT: dict[str, Any] = {"enabled": False, "language_ids": [], "keep_unknown": True}


@dataclass
class Preset:
    name: str
    video: dict[str, Any] = field(default_factory=lambda: dict(VIDEO_DEFAULTS))
    audio: dict[str, Any] = field(default_factory=lambda: dict(AUDIO_DEFAULTS))
    keep_subtitles: bool = True
    track_languages: dict[str, dict[str, Any]] = field(default_factory=dict)
    only_default_video_track: bool = False

    def __post_init__(self) -> None:
        video = dict(VIDEO_DEFAULTS); video.update(self.video); self.video = video
        audio = dict(AUDIO_DEFAULTS); audio.update(self.audio); self.audio = audio
        filters = {}
        for kind in ("video", "audio", "subtitle"):
            values = dict(LANGUAGE_FILTER_DEFAULT); values.update(self.track_languages.get(kind, {}))
            values["language_ids"] = list(dict.fromkeys(str(value) for value in values["language_ids"]))
            filters[kind] = values
        self.track_languages = filters

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Preset":
        name = str(data["name"]).strip()
        if not name:
            raise ValueError("Preset name cannot be empty")
        return cls(
            name, dict(data.get("video", {})), dict(data.get("audio", {})),
            bool(data.get("keep_subtitles", True)), dict(data.get("track_languages", {})),
            bool(data.get("only_default_video_track", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalized_name(name: str) -> str:
    return name.strip().casefold()


def load_presets(path: Path) -> list[Preset]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data.get("presets", []) if isinstance(data, dict) else []
        result: list[Preset] = []
        names: set[str] = set()
        for entry in entries:
            try:
                preset = Preset.from_dict(entry)
                key = normalized_name(preset.name)
                if key and key not in names:
                    result.append(preset); names.add(key)
            except (TypeError, ValueError, KeyError):
                continue
        return result
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
        return []


def save_presets(path: Path, presets: list[Preset]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"version": 1, "presets": [preset.to_dict() for preset in presets]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
