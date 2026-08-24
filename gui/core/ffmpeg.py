from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

from gui.config import PROBE_TIMEOUT_SECONDS
from gui.core.media import AudioTrack
from gui.core.project import RESOLUTIONS, TrackConfig


VIDEO_DIMENSION_ALIGNMENT = {
    "h264": 2,
    "hevc": 2,
    "av1": 2,
    "vp9": 2,
    "copy": 1,
}

HARDWARE_ENCODERS = {"h264": "h264_nvenc", "hevc": "hevc_nvenc", "av1": "av1_nvenc"}
_ENCODER_CACHE: set[str] | None = None


def available_encoders() -> set[str]:
    global _ENCODER_CACHE
    if _ENCODER_CACHE is None:
        try:
            output = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"], check=True,
                capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECONDS,
            ).stdout
            _ENCODER_CACHE = {
                line.split()[1] for line in output.splitlines()
                if len(line.split()) >= 2 and line.startswith((" V", " A", " S"))
            }
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            _ENCODER_CACHE = set()
    return _ENCODER_CACHE


def can_use_hardware(config: TrackConfig, hardware: str) -> bool:
    if config.copy_video or config.video_codec == "copy":
        return False
    encoder = HARDWARE_ENCODERS.get(config.video_codec)
    return hardware == "nvidia" and encoder in available_encoders()


def cuda_video_filter(config: TrackConfig) -> str | None:
    """Devuelve el filtro CUDA equivalente, o None si requiere filtros de CPU."""
    width, height = RESOLUTIONS.get(config.resolution, (config.custom_width, config.custom_height))
    if config.resolution == "custom":
        alignment = required_dimension_alignment(config.video_codec)
        width = aligned_dimension(config.custom_width, alignment)
        height = aligned_dimension(config.custom_height, alignment)
    if config.resolution == "original":
        if config.preserve_aspect or config.aspect_ratio == "original": return ""
        return None
    width, height = max(2, width), max(2, height)
    if config.resolution_mode == "width":
        return f"scale_cuda=w='min({width},iw)':h=-2:format=nv12"
    if config.preserve_aspect:
        if config.add_borders: return None
        return f"scale_cuda=w='min({width},iw)':h='min({height},ih)':force_original_aspect_ratio=decrease:force_divisible_by=2:format=nv12"
    width, height = dimensions_for_aspect(width, height, config.aspect_ratio)
    if config.fit_mode == "crop": return None
    return f"scale_cuda={width}:{height}:format=nv12"


def can_use_cuda_pipeline(config: TrackConfig, hardware: str) -> bool:
    return can_use_hardware(config, hardware) and cuda_video_filter(config) is not None


def required_dimension_alignment(video_codec: str) -> int:
    return VIDEO_DIMENSION_ALIGNMENT.get(video_codec, 2)


def aligned_dimension(value: int, alignment: int) -> int:
    alignment = max(1, alignment)
    return max(alignment, value // alignment * alignment)


@dataclass(frozen=True)
class EncodingOptions:
    max_width: int = 1280
    quality: int = 30
    preset: str = "p4"
    audio_bitrate: str = "256k"
    hardware: str = "nvidia"


def audio_filter(track: AudioTrack) -> str:
    compressor = "acompressor=threshold=0.125:ratio=3:attack=20:release=250:makeup=1.5"
    loudness = "loudnorm=I=-16:LRA=6:TP=-1.5"
    if track.channels >= 6:
        if "7.1" in track.layout:
            downmix = "pan=stereo|FL<0.65*FL+1.15*FC+0.30*SL+0.30*BL+0.15*LFE|FR<0.65*FR+1.15*FC+0.30*SR+0.30*BR+0.15*LFE"
        elif "side" in track.layout:
            downmix = "pan=stereo|FL<0.65*FL+1.15*FC+0.45*SL+0.15*LFE|FR<0.65*FR+1.15*FC+0.45*SR+0.15*LFE"
        else:
            downmix = "pan=stereo|FL<0.65*FL+1.15*FC+0.45*BL+0.15*LFE|FR<0.65*FR+1.15*FC+0.45*BR+0.15*LFE"
        return f"{downmix},{compressor},{loudness}"
    if track.channels == 1:
        return f"pan=stereo|FL=FC|FR=FC,{compressor},{loudness}"
    return f"{compressor},{loudness}"


def build_command(source: Path, destination: Path, track: AudioTrack, options: EncodingOptions) -> list[str]:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if options.hardware == "nvidia":
        command += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
        video_filter = f"scale_cuda=w='min({options.max_width},iw)':h=-2:format=nv12"
        video_codec = ["-c:v", "h264_nvenc", "-preset:v", options.preset, "-cq:v", str(options.quality)]
    else:
        video_filter = f"scale=w='min({options.max_width},iw)':h=-2"
        video_codec = ["-c:v", "libx264", "-preset", "medium", "-crf", str(options.quality)]

    return command + ["-i", str(source),
        "-map", "0:v:0", "-map", f"0:{track.index}", "-map", "0:s?", "-map", "0:t?",
        "-map_metadata", "0", "-map_chapters", "0", "-vf", video_filter, *video_codec,
        "-fps_mode", "passthrough", "-af", audio_filter(track), "-c:a", "libmp3lame",
        "-b:a", options.audio_bitrate, "-ar", "48000", "-ac", "2",
        "-metadata:s:a:0", "language=spa", "-metadata:s:a:0", "title=Castellano",
        "-disposition:a:0", "default", "-c:s", "copy", "-c:t", "copy",
        "-nostats", "-progress", "pipe:1", "-y", str(destination),
    ]


def build_project_command(
    source: Path,
    destination: Path,
    configs: list[TrackConfig],
    options: EncodingOptions,
) -> list[str]:
    """Construye una conversión con todas las pistas y el orden definido en la GUI."""
    included = [config for config in configs if config.included]
    sources = [source]
    for config in included:
        if config.track.source not in sources:
            sources.append(config.track.source)

    command = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    hardware_video_sources = {config.track.source for config in included if config.track.kind == "video" and can_use_hardware(config, options.hardware)}
    cuda_video_sources = {
        input_path for input_path in sources
        if any(config.track.kind == "video" and config.track.source == input_path and can_use_cuda_pipeline(config, options.hardware) for config in included)
        and all(config.track.kind != "video" or config.track.source != input_path or config.copy_video or can_use_cuda_pipeline(config, options.hardware) for config in included)
    }
    for input_path in sources:
        if options.hardware == "nvidia" and input_path in hardware_video_sources:
            command += ["-hwaccel", "cuda"]
            if input_path in cuda_video_sources:
                command += ["-hwaccel_output_format", "cuda"]
        command += ["-i", str(input_path)]
    for config in included:
        command += ["-map", f"{sources.index(config.track.source)}:{config.track.index}"]

    video_configs = [config for config in included if config.track.kind == "video"]
    audio_configs = [config for config in included if config.track.kind == "audio"]
    subtitle_configs = [config for config in included if config.track.kind == "subtitle"]
    for index, config in enumerate(video_configs):
        command += video_options(config, index, options.hardware, config.track.source in cuda_video_sources)

    codec_names = {"copy": "copy", "aac": "aac", "ac3": "ac3", "mp3": "libmp3lame", "opus": "libopus", "flac": "flac"}
    for index, config in enumerate(audio_configs):
        selected_codec = config.audio_codec
        codec = codec_names.get(selected_codec, selected_codec)
        command += [f"-c:a:{index}", codec]
        if config.normalize and selected_codec != "copy":
            command += [f"-filter:a:{index}", audio_filter(config.as_audio_track())]
        if codec != "copy":
            command += [f"-b:a:{index}", options.audio_bitrate]
        command += [f"-metadata:s:a:{index}", f"language={config.language}"]
        command += [f"-metadata:s:a:{index}", f"title={config.title}"]
        command += [f"-disposition:a:{index}", "default" if config.default else "0"]

    # MP4 utiliza mov_text para subtítulos internos. La validación del
    # contenedor impide llegar aquí con subtítulos gráficos no convertibles.
    command += ["-c:s", "mov_text" if destination.suffix.lower() == ".mp4" else "copy"]
    for index, config in enumerate(video_configs):
        command += [f"-metadata:s:v:{index}", f"language={config.language}"]
        command += [f"-metadata:s:v:{index}", f"title={config.title}"]
        if not config.copy_video:
            command += [f"-disposition:v:{index}", "default" if config.default else "0"]
    for index, config in enumerate(subtitle_configs):
        command += [f"-metadata:s:s:{index}", f"language={config.language}"]
        command += [f"-metadata:s:s:{index}", f"title={config.title}"]
        dispositions = "+".join(name for enabled, name in ((config.default, "default"), (config.forced, "forced")) if enabled)
        command += [f"-disposition:s:{index}", dispositions or "0"]
    return command + [
        "-map_metadata", "0", "-map_chapters", "0", "-fps_mode", "passthrough",
        "-nostats", "-progress", "pipe:1", "-y", str(destination),
    ]


def video_options(config: TrackConfig, index: int, hardware: str, cuda_pipeline: bool | None = None) -> list[str]:
    if config.copy_video or config.video_codec == "copy":
        return [f"-c:v:{index}", "copy"]
    use_hardware = can_use_hardware(config, hardware)
    encoders = {
        "h264": "h264_nvenc" if use_hardware else "libx264",
        "hevc": "hevc_nvenc" if use_hardware else "libx265",
        "av1": "av1_nvenc" if use_hardware else "libaom-av1",
        "vp9": "libvpx-vp9",
    }
    encoder = encoders[config.video_codec]
    result = [f"-c:v:{index}", encoder]
    if cuda_pipeline is None:
        cuda_pipeline = can_use_cuda_pipeline(config, hardware)
    filter_chain = cuda_video_filter(config) if cuda_pipeline else video_filter(config)
    if filter_chain:
        result += [f"-filter:v:{index}", filter_chain]
    if encoder.endswith("_nvenc"):
        result += [f"-preset:v:{index}", "p4"]

    bitrate = f"{config.bitrate_mbps:g}M"
    maximum = f"{config.max_bitrate_mbps:g}M"
    buffer_size = f"{max(config.max_bitrate_mbps * 2, config.bitrate_mbps * 2):g}M"
    if config.rate_control == "quality":
        if encoder.endswith("_nvenc"):
            result += [f"-cq:v:{index}", str(config.quality), f"-b:v:{index}", "0"]
        else:
            result += [f"-crf:v:{index}", str(config.quality)]
            if config.video_codec in {"av1", "vp9"}:
                result += [f"-b:v:{index}", "0"]
    elif config.rate_control == "vbr":
        if encoder.endswith("_nvenc"): result += [f"-rc:v:{index}", "vbr"]
        result += [f"-b:v:{index}", bitrate, f"-maxrate:v:{index}", maximum, f"-bufsize:v:{index}", buffer_size]
    else:
        if encoder.endswith("_nvenc"): result += [f"-rc:v:{index}", "cbr"]
        result += [f"-b:v:{index}", bitrate, f"-minrate:v:{index}", bitrate, f"-maxrate:v:{index}", bitrate, f"-bufsize:v:{index}", f"{config.bitrate_mbps * 2:g}M"]
    return result


def video_filter(config: TrackConfig) -> str:
    width, height = RESOLUTIONS.get(config.resolution, (config.custom_width, config.custom_height))
    if config.resolution == "custom":
        alignment = required_dimension_alignment(config.video_codec)
        width = aligned_dimension(config.custom_width, alignment)
        height = aligned_dimension(config.custom_height, alignment)
    if config.resolution == "original":
        if config.preserve_aspect or config.aspect_ratio == "original": return ""
        return f"setsar=1,setdar={config.aspect_ratio}"
    width, height = max(2, width), max(2, height)
    if config.resolution_mode == "width":
        return f"scale=w='min({width},iw)':h=-2"
    if config.preserve_aspect:
        scale = f"scale=w='min({width},iw)':h='min({height},ih)':force_original_aspect_ratio=decrease:force_divisible_by=2"
        if config.add_borders:
            return f"{scale},pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
        return scale
    width, height = dimensions_for_aspect(width, height, config.aspect_ratio)
    if config.fit_mode == "crop":
        return f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    return f"scale={width}:{height},setsar=1"


def dimensions_for_aspect(width: int, height: int, aspect: str) -> tuple[int, int]:
    if aspect == "original": return width, height
    try:
        numerator, denominator = (float(part) for part in aspect.replace(":", "/").split("/", 1))
        ratio = numerator / denominator
    except (ValueError, ZeroDivisionError):
        return width, height
    if ratio >= width / height:
        height = round(width / ratio)
    else:
        width = round(height * ratio)
    return max(2, width // 2 * 2), max(2, height // 2 * 2)
