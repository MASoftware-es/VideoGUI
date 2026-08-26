from pathlib import Path

from gui.core.ffmpeg import EncodingOptions, aligned_dimension, audio_filter, available_encoders, build_command, cuda_video_filter, dimensions_for_aspect, required_dimension_alignment, video_filter, video_options
from gui.core.ffmpeg import build_project_command
from gui.core.media import AudioTrack, MediaTrack, preferred_audio_track
from gui.core.project import TrackConfig, container_warnings
from gui.i18n import discover_languages, text


LANGUAGES = discover_languages()
ES = lambda key: text(LANGUAGES, "es", key)


def track(index=2, channels=6, layout="5.1(side)", language="spa", title="Castellano"):
    return AudioTrack(index, "eac3", channels, layout, language, title)


def test_prefers_spanish_audio():
    english = AudioTrack(1, "aac", 2, "stereo", "eng", "English")
    spanish = track()
    assert preferred_audio_track((english, spanish)) == spanish


def test_does_not_guess_when_several_tracks_have_no_spanish_metadata():
    first = AudioTrack(1, "aac", 2, "stereo", "eng", "")
    second = AudioTrack(2, "aac", 2, "stereo", "fra", "")
    assert preferred_audio_track((first, second)) is None


def test_multichannel_filter_reinforces_centre_channel():
    assert "1.15*FC" in audio_filter(track())
    assert "loudnorm=I=-16" in audio_filter(track())


def test_encoder_discovery_includes_audio_encoders():
    assert "aac" in available_encoders()


def test_cpu_command_maps_selected_audio_and_subtitles():
    command = build_command(Path("movie.mkv"), Path("out.mkv"), track(), EncodingOptions(hardware="cpu"))
    assert command[:6] == ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "movie.mkv"]
    assert "libx264" in command
    assert command[command.index("0:2") - 1] == "-map"
    assert "0:s?" in command


def test_nvidia_options_are_before_input():
    command = build_command(Path("movie.mkv"), Path("out.mkv"), track(), EncodingOptions())
    assert command.index("cuda") < command.index("-i")
    assert "h264_nvenc" in command


def test_project_command_preserves_track_order_and_transcodes_normalized_audio():
    source = Path("movie.mkv")
    video = TrackConfig(MediaTrack(0, "video", "hevc", "", "Principal", source))
    audio = TrackConfig(MediaTrack(2, "audio", "eac3", "spa", "Castellano", source, channels=6, layout="5.1(side)"), normalize=True)
    command = build_project_command(source, Path("out.mkv"), [video, audio], EncodingOptions(hardware="cpu"))
    first_map = command.index("-map")
    assert command[first_map + 1:first_map + 4] == ["0:0", "-map", "0:2"]
    assert command[command.index("-c:a:0") + 1] == "libmp3lame"
    assert "-filter:a:0" in command


def test_copy_audio_ignores_normalization_and_uses_no_filter():
    source = Path("movie.mkv")
    audio = TrackConfig(
        MediaTrack(2, "audio", "eac3", "spa", "Castellano", source, channels=6, layout="5.1(side)"),
        audio_codec="copy", normalize=True,
    )
    command = build_project_command(source, Path("out.mkv"), [audio], EncodingOptions(hardware="cpu"))
    assert command[command.index("-c:a:0") + 1] == "copy"
    assert "-filter:a:0" not in command


def test_vorbis_audio_uses_libvorbis_encoder():
    source = Path("movie.mkv")
    audio = TrackConfig(MediaTrack(2, "audio", "aac", "spa", "Audio", source), audio_codec="vorbis", normalize=False)
    command = build_project_command(source, Path("out.mkv"), [audio], EncodingOptions(hardware="cpu"))
    assert command[command.index("-c:a:0") + 1] == "libvorbis"
    assert command[command.index("-q:a:0") + 1] == "6"
    assert "-b:a:0" not in command


def test_container_validation_accounts_for_encoded_video():
    source = Path("movie.mkv")
    video = TrackConfig(MediaTrack(0, "video", "vp9", "", "", source))
    assert container_warnings([video], ".mp4", ES) == []


def test_avi_warns_about_subtitles():
    subtitle = TrackConfig(MediaTrack(3, "subtitle", "subrip", "spa", "", Path("movie.mkv")))
    assert container_warnings([subtitle], ".avi", ES)


def test_avi_warns_about_multiple_video_and_audio_tracks():
    source = Path("movie.mkv")
    configs = [
        TrackConfig(MediaTrack(0, "video", "h264", "", "Vídeo 1", source)),
        TrackConfig(MediaTrack(1, "video", "h264", "", "Vídeo 2", source)),
        TrackConfig(MediaTrack(2, "audio", "mp3", "spa", "Audio 1", source), audio_codec="copy"),
        TrackConfig(MediaTrack(3, "audio", "mp3", "eng", "Audio 2", source), audio_codec="copy"),
    ]
    warnings = container_warnings(configs, ".avi", ES)
    assert any("una sola pista de vídeo" in warning for warning in warnings)
    assert any("una sola pista de audio" in warning for warning in warnings)


def test_mp4_converts_text_subtitles_to_mov_text():
    source = Path("movie.mkv")
    subtitle = TrackConfig(MediaTrack(3, "subtitle", "subrip", "spa", "Español", source))
    assert container_warnings([subtitle], ".mp4", ES) == []
    command = build_project_command(source, Path("out.mp4"), [subtitle], EncodingOptions(hardware="cpu"))
    assert command[command.index("-c:s") + 1] == "mov_text"


def test_mp4_rejects_graphical_subtitles():
    subtitle = TrackConfig(MediaTrack(3, "subtitle", "hdmv_pgs_subtitle", "spa", "Español", Path("movie.mkv")))
    assert container_warnings([subtitle], ".mp4", ES)


def test_default_video_profile_matches_original_script():
    config = TrackConfig(MediaTrack(0, "video", "hevc", "", "", Path("movie.mkv")))
    options = video_options(config, 0, "nvidia")
    assert options[options.index("-c:v:0") + 1] == "h264_nvenc"
    assert options[options.index("-cq:v:0") + 1] == "30"
    assert video_filter(config) == "scale=w='min(1280,iw)':h=-2"


def test_project_command_uses_full_cuda_pipeline_like_script():
    source = Path("movie.mkv")
    video = TrackConfig(MediaTrack(0, "video", "h264", "", "", source))
    command = build_project_command(source, Path("out.mkv"), [video], EncodingOptions())
    assert command[command.index("-hwaccel_output_format") + 1] == "cuda"
    assert "scale_cuda=w='min(1280,iw)':h=-2:format=nv12" in command
    assert command[command.index("-c:v:0") + 1] == "h264_nvenc"


def test_cuda_filter_rejects_operations_not_available_in_installed_ffmpeg():
    config = TrackConfig(MediaTrack(0, "video", "h264", "", "", Path("movie.mkv")), resolution_mode="standard", preserve_aspect=True, add_borders=True)
    assert cuda_video_filter(config) is None


def test_black_borders_create_a_1280_by_720_canvas():
    config = TrackConfig(MediaTrack(0, "video", "h264", "", "", Path("movie.mkv")), resolution_mode="standard", preserve_aspect=True, add_borders=True)
    assert "pad=1280:720" in video_filter(config)


def test_variable_bitrate_has_target_and_maximum():
    config = TrackConfig(
        MediaTrack(0, "video", "h264", "", "", Path("movie.mkv")),
        rate_control="vbr", bitrate_mbps=5.0, max_bitrate_mbps=8.0,
    )
    options = video_options(config, 0, "cpu")
    assert options[options.index("-b:v:0") + 1] == "5M"
    assert options[options.index("-maxrate:v:0") + 1] == "8M"


def test_copy_video_disables_filters_and_rate_control():
    config = TrackConfig(MediaTrack(0, "video", "hevc", "", "", Path("movie.mkv")), video_codec="copy")
    assert video_options(config, 0, "nvidia") == ["-c:v:0", "copy"]


def test_copy_video_only_overrides_language_and_title_metadata():
    source = Path("movie.mkv")
    video = TrackConfig(MediaTrack(0, "video", "hevc", "", "", source), copy_video=True, title="Principal", language="spa")
    command = build_project_command(source, Path("out.mkv"), [video], EncodingOptions())
    assert command[command.index("-c:v:0") + 1] == "copy"
    assert "-filter:v:0" not in command
    assert "-disposition:v:0" not in command
    assert "language=spa" in command and "title=Principal" in command


def test_global_hardware_setting_can_force_software_encoder():
    config = TrackConfig(MediaTrack(0, "video", "h264", "", "", Path("movie.mkv")))
    options = video_options(config, 0, "cpu")
    assert options[options.index("-c:v:0") + 1] == "libx264"


def test_standard_resolution_does_not_upscale_without_borders():
    config = TrackConfig(MediaTrack(0, "video", "h264", "", "", Path("movie.mkv")), resolution="fhd_1080", resolution_mode="standard", preserve_aspect=True)
    assert "min(1920,iw)" in video_filter(config)
    assert "min(1080,ih)" in video_filter(config)


def test_manual_aspect_ratio_fits_inside_resolution():
    assert dimensions_for_aspect(1920, 1080, "4/3") == (1440, 1080)
    assert dimensions_for_aspect(1920, 1080, "21:9") == (1920, 822)


def test_custom_dimensions_are_aligned_for_yuv420_codecs():
    assert required_dimension_alignment("h264") == 2
    assert aligned_dimension(1921, 2) == 1920
    config = TrackConfig(
        MediaTrack(0, "video", "h264", "", "", Path("movie.mkv")),
        resolution="custom", resolution_mode="standard",
        custom_width=1921, custom_height=1081,
    )
    assert video_filter(config).startswith("scale=1920:1080")


def test_reset_restores_script_encoding_without_track_state_or_metadata():
    config = TrackConfig(MediaTrack(0, "video", "hevc", "spa", "Principal", Path("movie.mkv")))
    config.included = False
    config.title = "Descripción editada"
    config.video_codec = "av1"
    config.resolution = "uhd_2160"
    config.rate_control = "cbr"
    config.add_borders = True
    config.reset_encoding_defaults()
    assert (config.video_codec, config.resolution, config.resolution_mode, config.rate_control, config.quality) == ("h264", "hd_720", "width", "quality", 30)
    assert config.add_borders is False
    assert config.preserve_aspect is False
    assert config.copy_video is False
    assert config.included is False
    assert config.title == "Descripción editada"
