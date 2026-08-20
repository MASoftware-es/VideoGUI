"""Inspección de archivos y pistas multimedia."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_EXTENSIONS = {".avi", ".mkv", ".mp4"}
SPANISH_CODES = {"spa", "es", "esp"}
SPANISH_NAMES = ("español", "espanol", "castellano", "spanish")


class MediaError(RuntimeError):
    pass


@dataclass(frozen=True)
class AudioTrack:
    index: int
    codec: str
    channels: int
    layout: str
    language: str
    title: str
    sample_rate: int = 0
    bitrate: int = 0
    disposition_default: bool = False

    @property
    def display_name(self) -> str:
        language = self.language or "—"
        title = f" · {self.title}" if self.title else ""
        return f"0:{self.index} · {language} · {self.channels} ch · {self.codec}{title}"


@dataclass(frozen=True)
class MediaInfo:
    path: Path
    duration: float
    width: int
    height: int
    video_codec: str
    video_tracks: tuple["MediaTrack", ...]
    audio_tracks: tuple[AudioTrack, ...]
    subtitle_tracks: tuple["MediaTrack", ...]


@dataclass(frozen=True)
class MediaTrack:
    index: int
    kind: str
    codec: str
    language: str
    title: str
    source: Path
    width: int = 0
    height: int = 0
    frame_rate: str = ""
    pixel_format: str = ""
    channels: int = 0
    layout: str = ""
    sample_rate: int = 0
    bitrate: int = 0
    disposition_default: bool = False
    disposition_forced: bool = False

    @property
    def display_name(self) -> str:
        language = self.language or "—"
        title = f" · {self.title}" if self.title else ""
        return f"0:{self.index} · {language} · {self.codec}{title}"


def probe_media(path: Path, translate=None) -> MediaInfo:
    def message(key: str, **values) -> str:
        return (translate(key) if translate else key).format(**values)

    path = path.expanduser().resolve()
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise MediaError(message("media_unsupported_format"))
    if not path.is_file():
        raise MediaError(message("media_file_missing", path=path))

    command = [
        "ffprobe", "-v", "error", "-show_streams", "-show_format",
        "-of", "json", str(path),
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        data = json.loads(result.stdout)
    except FileNotFoundError as exc:
        raise MediaError(message("media_ffprobe_missing")) from exc
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise MediaError(message("media_probe_failed", detail=detail.strip())) from exc

    streams = data.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    if video is None:
        raise MediaError(message("media_no_video"))

    def tags(stream: dict) -> dict:
        return stream.get("tags", {})

    def media_track(stream: dict, kind: str) -> MediaTrack:
        disposition = stream.get("disposition", {})
        return MediaTrack(
            index=int(stream["index"]), kind=kind,
            codec=stream.get("codec_name", ""),
            language=tags(stream).get("language", ""),
            title=tags(stream).get("title", ""), source=path,
            width=int(stream.get("width", 0)), height=int(stream.get("height", 0)),
            frame_rate=stream.get("avg_frame_rate", stream.get("r_frame_rate", "")),
            pixel_format=stream.get("pix_fmt", ""),
            channels=int(stream.get("channels", 0)), layout=stream.get("channel_layout", ""),
            sample_rate=int(stream.get("sample_rate", 0) or 0),
            bitrate=int(stream.get("bit_rate", 0) or 0),
            disposition_default=bool(disposition.get("default", 0)),
            disposition_forced=bool(disposition.get("forced", 0)),
        )

    video_tracks = tuple(media_track(stream, "video") for stream in streams if stream.get("codec_type") == "video")
    audio_tracks = tuple(
        AudioTrack(
            index=int(stream["index"]),
            codec=stream.get("codec_name", ""),
            channels=int(stream.get("channels", 0)),
            layout=stream.get("channel_layout", ""),
            language=stream.get("tags", {}).get("language", ""),
            title=stream.get("tags", {}).get("title", ""),
            sample_rate=int(stream.get("sample_rate", 0) or 0),
            bitrate=int(stream.get("bit_rate", 0) or 0),
            disposition_default=bool(stream.get("disposition", {}).get("default", 0)),
        )
        for stream in streams
        if stream.get("codec_type") == "audio"
    )
    return MediaInfo(
        path=path,
        duration=float(data.get("format", {}).get("duration", 0) or 0),
        width=int(video.get("width", 0)),
        height=int(video.get("height", 0)),
        video_codec=video.get("codec_name", ""),
        video_tracks=video_tracks,
        audio_tracks=audio_tracks,
        subtitle_tracks=tuple(media_track(stream, "subtitle") for stream in streams if stream.get("codec_type") == "subtitle"),
    )


def probe_external_tracks(path: Path, kind: str, translate=None) -> tuple[MediaTrack, ...]:
    """Devuelve las pistas del tipo solicitado contenidas en un archivo externo."""
    def message(key: str, **values) -> str:
        return (translate(key) if translate else key).format(**values)

    path = path.expanduser().resolve()
    if not path.is_file():
        raise MediaError(message("media_file_missing", path=path))
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
            check=True, capture_output=True, text=True,
        )
        streams = json.loads(result.stdout).get("streams", [])
    except FileNotFoundError as exc:
        raise MediaError(message("media_ffprobe_missing")) from exc
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise MediaError(message("media_external_probe_failed", detail=exc)) from exc

    result_tracks = []
    for stream in streams:
        if stream.get("codec_type") != kind:
            continue
        tags = stream.get("tags", {})
        disposition = stream.get("disposition", {})
        result_tracks.append(MediaTrack(
            index=int(stream["index"]), kind=kind,
            codec=stream.get("codec_name", ""),
            language=tags.get("language", ""), title=tags.get("title", ""), source=path,
            width=int(stream.get("width", 0)), height=int(stream.get("height", 0)),
            frame_rate=stream.get("avg_frame_rate", stream.get("r_frame_rate", "")),
            pixel_format=stream.get("pix_fmt", ""), channels=int(stream.get("channels", 0)),
            layout=stream.get("channel_layout", ""), sample_rate=int(stream.get("sample_rate", 0) or 0),
            bitrate=int(stream.get("bit_rate", 0) or 0),
            disposition_default=bool(disposition.get("default", 0)),
            disposition_forced=bool(disposition.get("forced", 0)),
        ))
    if not result_tracks:
        kind_name = translate(f"media_kind_{kind}") if translate else kind
        raise MediaError(message("media_no_tracks", kind=kind_name))
    return tuple(result_tracks)


def preferred_audio_track(tracks: tuple[AudioTrack, ...]) -> AudioTrack | None:
    for track in tracks:
        searchable = f"{track.language} {track.title}".lower()
        if track.language.lower() in SPANISH_CODES or any(name in searchable for name in SPANISH_NAMES):
            return track
    return tracks[0] if len(tracks) == 1 else None
