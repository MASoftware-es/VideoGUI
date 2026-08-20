from __future__ import annotations

from dataclasses import dataclass

from gui.core.media import AudioTrack, MediaTrack


@dataclass
class TrackConfig:
    track: MediaTrack
    included: bool = True
    title: str = ""
    language: str = ""
    default: bool = False
    forced: bool = False
    audio_codec: str = "mp3"
    normalize: bool = True
    video_codec: str = "h264"
    copy_video: bool = False
    resolution: str = "hd_720"
    resolution_mode: str = "width"
    custom_width: int = 1280
    custom_height: int = 720
    preserve_aspect: bool = False
    aspect_ratio: str = "original"
    fit_mode: str = "crop"
    add_borders: bool = False
    rate_control: str = "quality"
    quality: int = 30
    bitrate_mbps: float = 4.0
    max_bitrate_mbps: float = 6.0

    def __post_init__(self) -> None:
        if not self.title:
            self.title = self.track.title
        if not self.language:
            self.language = self.track.language
        self.default = self.track.disposition_default
        self.forced = self.track.disposition_forced

    def reset_encoding_defaults(self) -> None:
        """Restaura el perfil de codificación predeterminado."""
        if self.track.kind == "video":
            self.video_codec = "h264"
            self.copy_video = False
            self.resolution = "hd_720"
            self.resolution_mode = "width"
            self.custom_width, self.custom_height = 1280, 720
            self.preserve_aspect = False
            self.aspect_ratio = "original"
            self.fit_mode = "crop"
            self.add_borders = False
            self.rate_control = "quality"
            self.quality = 30
            self.bitrate_mbps, self.max_bitrate_mbps = 4.0, 6.0
        elif self.track.kind == "audio":
            self.audio_codec = "mp3"
            self.normalize = True

    def as_audio_track(self) -> AudioTrack:
        return AudioTrack(
            self.track.index, self.track.codec, self.track.channels,
            self.track.layout, self.language, self.title,
        )


CONTAINER_SUPPORT = {
    ".mkv": None,
    ".mp4": {
        "video": {"h264", "hevc", "mpeg4", "av1"},
        "audio": {"aac", "mp3", "ac3", "eac3", "alac"},
        "subtitle": {"mov_text"},
    },
    ".avi": {
        "video": {"h264", "mpeg4", "msmpeg4v3", "mjpeg"},
        "audio": {"mp3", "ac3", "pcm_s16le"},
        "subtitle": set(),
    },
}

# FFmpeg puede convertir estos formatos de subtítulos basados en texto al
# formato mov_text que utiliza MP4. Los subtítulos gráficos (PGS, DVB, DVD…)
# no se pueden convertir de ese modo sin aplicar OCR o incrustarlos en vídeo.
MP4_TEXT_SUBTITLE_CODECS = {
    "ass", "ssa", "subrip", "srt", "text", "webvtt", "mov_text",
}

RESOLUTIONS = {
    "original": (0, 0),
    "uhd_2160": (3840, 2160),
    "qhd_1440": (2560, 1440),
    "fhd_1080": (1920, 1080),
    "hd_720": (1280, 720),
    "sd_480": (854, 480),
}


def output_video_codec(config: TrackConfig) -> str:
    return config.track.codec if config.copy_video or config.video_codec == "copy" else config.video_codec


def container_warnings(configs: list[TrackConfig], extension: str, translate=None) -> list[str]:
    def message(key: str, **values) -> str:
        return (translate(key) if translate else key).format(**values)

    extension = extension.lower()
    support = CONTAINER_SUPPORT.get(extension)
    if support is None:
        return []
    warnings = []
    included = [config for config in configs if config.included]

    if extension == ".avi":
        video_count = sum(config.track.kind == "video" for config in included)
        audio_count = sum(config.track.kind == "audio" for config in included)
        if video_count > 1:
            warnings.append(message("container_avi_video_count", count=video_count))
        if audio_count > 1:
            warnings.append(message("container_avi_audio_count", count=audio_count))

    for config in included:
        if config.track.kind == "video":
            codec = output_video_codec(config)
        elif config.track.kind == "subtitle" and extension == ".mp4":
            if config.track.codec in MP4_TEXT_SUBTITLE_CODECS:
                continue
            warnings.append(message(
                "container_mp4_graphical_subtitle",
                track=config.title or config.track.index, codec=config.track.codec,
            ))
            continue
        else:
            codec = config.audio_codec if config.track.kind == "audio" and config.audio_codec != "copy" else config.track.codec
        if codec not in support[config.track.kind]:
            kind = translate(f"media_kind_{config.track.kind}") if translate else config.track.kind
            warnings.append(message("container_incompatible_codec", kind=kind, track=config.title or config.track.index, codec=codec))
    return warnings
