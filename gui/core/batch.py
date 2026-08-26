"""Modelo, persistencia y validación de trabajos por lotes."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from gui.core.ffmpeg import HARDWARE_ENCODERS, available_encoders, can_use_hardware
from gui.core.media import MediaInfo, MediaTrack, probe_media
from gui.core.project import TrackConfig, container_warnings
from gui.presets import Preset, normalized_name
from gui.track_languages import TrackLanguage, recognize_language


PENDING = "pending"
CHECKING = "checking"
VALID = "valid"
ERROR = "error"
PROCESSING = "processing"
COMPLETED = "completed"
CANCELLED = "cancelled"


@dataclass
class BatchItem:
    source: str
    preset_name: str
    status: str = PENDING
    error: str = ""
    output_path: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "BatchItem":
        status = str(data.get("status", PENDING))
        if status not in {PENDING, CHECKING, VALID, ERROR, PROCESSING, COMPLETED, CANCELLED}:
            status = PENDING
        # Un proceso guardado no puede seguir activo al recuperar el trabajo.
        if status in {CHECKING, PROCESSING}:
            status = CANCELLED
        return cls(
            source=str(data["source"]), preset_name=str(data.get("preset_name", "")),
            status=status, error=str(data.get("error", "")), output_path=str(data.get("output_path", "")),
        )


@dataclass
class BatchSettings:
    default_preset: str = ""
    same_source_directory: bool = True
    output_directory: str = ""
    output_format: str = ".mkv"
    use_hardware: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "BatchSettings":
        output_format = str(data.get("output_format", ".mkv")).lower()
        if output_format not in {".mkv", ".mp4", ".avi"}:
            output_format = ".mkv"
        return cls(
            default_preset=str(data.get("default_preset", "")),
            same_source_directory=bool(data.get("same_source_directory", True)),
            output_directory=str(data.get("output_directory", "")),
            output_format=output_format,
            use_hardware=bool(data.get("use_hardware", True)),
        )


def find_preset(presets: list[Preset], name: str) -> Preset | None:
    key = normalized_name(name)
    return next((preset for preset in presets if normalized_name(preset.name) == key), None)


def save_batch_job(path: Path, settings: BatchSettings, items: list[BatchItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({
        "version": 1, "settings": asdict(settings),
        "items": [asdict(item) for item in items],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_batch_job(path: Path, translate=None) -> tuple[BatchSettings, list[BatchItem]]:
    def message(key: str) -> str:
        return translate(key) if translate else key

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError(message("batch_unsupported_format"))
    entries = data.get("items", [])
    if not isinstance(entries, list):
        raise ValueError(message("batch_invalid_item_list"))
    return BatchSettings.from_dict(dict(data.get("settings", {}))), [BatchItem.from_dict(entry) for entry in entries if isinstance(entry, dict)]


def configs_for_preset(media: MediaInfo, preset: Preset, languages: list[TrackLanguage]) -> list[TrackConfig]:
    audio_tracks = tuple(MediaTrack(
        track.index, "audio", track.codec, track.language, track.title, media.path,
        channels=track.channels, layout=track.layout, sample_rate=track.sample_rate,
        bitrate=track.bitrate, disposition_default=track.disposition_default,
    ) for track in media.audio_tracks)
    configs = [TrackConfig(track) for track in (*media.video_tracks, *audio_tracks, *media.subtitle_tracks)]
    ordinals = {"video": 0, "audio": 0, "subtitle": 0}
    for config in configs:
        ordinals[config.track.kind] += 1
        config.source_ordinal = ordinals[config.track.kind]
        values = preset.video if config.track.kind == "video" else preset.audio if config.track.kind == "audio" else {}
        if config.track.kind == "video":
            config.copy_video = False
        for field, value in values.items():
            setattr(config, field, value)
        rule = preset.track_languages[config.track.kind]
        included = True
        if rule["enabled"]:
            recognized = recognize_language(config.track.language, config.track.title, languages)
            included = bool(rule["keep_unknown"]) if recognized is None else recognized.identifier in set(rule["language_ids"])
        if preset.only_default(config.track.kind):
            kind_tracks = [candidate for candidate in configs if candidate.track.kind == config.track.kind]
            chosen = next((candidate for candidate in kind_tracks if candidate.track.disposition_default), kind_tracks[0] if kind_tracks else None)
            included = included and config is chosen
        else:
            included = included and config.source_ordinal in preset.track_numbers[config.track.kind]
        config.included = included and (preset.keep_subtitles if config.track.kind == "subtitle" else True)
    return configs


def empty_language_filter_kinds(configs: list[TrackConfig], preset: Preset) -> list[str]:
    """Tipos cuyo filtro de idiomas activo no conserva ninguna pista."""
    missing: list[str] = []
    for kind in ("video", "audio", "subtitle"):
        if kind == "subtitle" and not preset.keep_subtitles:
            continue
        if preset.track_languages[kind]["enabled"] and not any(
            config.track.kind == kind and config.included for config in configs
        ):
            missing.append(kind)
    return missing


def unique_output_path(source: Path, directory: Path, extension: str, reserved: set[Path]) -> Path:
    base = directory / f"{source.stem}_compressed{extension}"
    candidate, counter = base, 1
    normalized_reserved = {path.resolve() for path in reserved}
    while candidate.exists() or candidate.resolve() in normalized_reserved:
        candidate = directory / f"{source.stem}_compressed_{counter}{extension}"
        counter += 1
    return candidate


def required_encoders(configs: list[TrackConfig], use_hardware: bool) -> set[str]:
    required: set[str] = set()
    software_video = {"h264": "libx264", "hevc": "libx265", "av1": "libaom-av1", "vp9": "libvpx-vp9"}
    audio = {"aac": "aac", "ac3": "ac3", "mp3": "libmp3lame", "opus": "libopus", "vorbis": "libvorbis", "flac": "flac"}
    hardware = "nvidia" if use_hardware else "cpu"
    for config in configs:
        if not config.included:
            continue
        if config.track.kind == "video" and not config.copy_video and config.video_codec != "copy":
            required.add(HARDWARE_ENCODERS[config.video_codec] if can_use_hardware(config, hardware) else software_video[config.video_codec])
        elif config.track.kind == "audio" and config.audio_codec != "copy":
            required.add(audio[config.audio_codec])
    return required


def validate_batch_item(
    item: BatchItem, presets: list[Preset], languages: list[TrackLanguage],
    settings: BatchSettings, reserved: set[Path], translate=None,
) -> tuple[MediaInfo, list[TrackConfig], Path]:
    t = translate or (lambda key: key)
    preset = find_preset(presets, item.preset_name)
    if preset is None:
        raise ValueError(t("batch_validation_missing_preset").format(name=item.preset_name))
    media = probe_media(Path(item.source), translate)
    return validate_batch_media(item, media, presets, languages, settings, reserved, translate)


def validate_batch_media(
    item: BatchItem, media: MediaInfo, presets: list[Preset], languages: list[TrackLanguage],
    settings: BatchSettings, reserved: set[Path], translate=None,
) -> tuple[MediaInfo, list[TrackConfig], Path]:
    """Valida un elemento cuyo análisis ffprobe ya se ha realizado."""
    t = translate or (lambda key: key)
    preset = find_preset(presets, item.preset_name)
    if preset is None:
        raise ValueError(t("batch_validation_missing_preset").format(name=item.preset_name))
    configs = configs_for_preset(media, preset, languages)
    empty_filters = empty_language_filter_kinds(configs, preset)
    if empty_filters:
        kinds = ", ".join(t(f"media_kind_{kind}") for kind in empty_filters)
        raise ValueError(t("batch_validation_empty_language_filters").format(kinds=kinds))
    if not any(config.included and config.track.kind == "video" for config in configs):
        raise ValueError(t("batch_validation_no_video"))
    warnings = container_warnings(configs, settings.output_format, translate)
    if warnings:
        raise ValueError(t("batch_validation_container") + "\n" + "\n".join(warnings))
    needed = required_encoders(configs, settings.use_hardware)
    if settings.output_format == ".mp4" and any(config.included and config.track.kind == "subtitle" for config in configs):
        needed.add("mov_text")
    missing = sorted(needed - available_encoders())
    if missing:
        raise ValueError(t("batch_validation_encoders").format(encoders=", ".join(missing)))
    source = Path(item.source).expanduser().resolve()
    directory = source.parent if settings.same_source_directory else Path(settings.output_directory).expanduser().resolve()
    if not settings.same_source_directory and not settings.output_directory.strip():
        raise ValueError(t("batch_validation_no_output"))
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ValueError(t("batch_validation_create_output").format(error=error)) from error
    if not directory.is_dir() or not os.access(directory, os.W_OK):
        raise ValueError(t("batch_validation_output_unwritable").format(directory=directory))
    output = unique_output_path(source, directory, settings.output_format, reserved)
    return media, configs, output
