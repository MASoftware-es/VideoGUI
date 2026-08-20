from pathlib import Path

from gui.core.batch import (
    CANCELLED, COMPLETED, ERROR, BatchItem, BatchSettings, configs_for_preset, empty_language_filter_kinds,
    load_batch_job, save_batch_job, unique_output_path,
)
from gui.core.media import AudioTrack, MediaInfo, MediaTrack
from gui.presets import Preset
from gui.track_languages import TrackLanguage


def test_batch_job_round_trip_preserves_settings_states_errors_and_outputs(tmp_path):
    settings = BatchSettings("Cine", False, "/videos/out", ".mp4", False)
    items = [
        BatchItem("/videos/a.mkv", "Cine", COMPLETED, "", "/videos/out/a_compressed.mp4"),
        BatchItem("/videos/b.mkv", "Cine", ERROR, "Fallo de prueba", ""),
        BatchItem("/videos/c.mkv", "Cine", CANCELLED, "Cancelado", ""),
    ]
    path = tmp_path / "trabajo.vgbatch.json"
    save_batch_job(path, settings, items)
    loaded_settings, loaded_items = load_batch_job(path)
    assert loaded_settings == settings
    assert loaded_items == items


def test_active_saved_state_becomes_cancelled_when_loaded(tmp_path):
    path = tmp_path / "trabajo.vgbatch.json"
    path.write_text('{"version": 1, "settings": {}, "items": [{"source": "a.mkv", "status": "processing"}]}', encoding="utf-8")
    _, items = load_batch_job(path)
    assert items[0].status == CANCELLED


def test_legacy_fingerprint_is_ignored_and_not_saved_again(tmp_path):
    path = tmp_path / "legacy.vgbatch.json"
    path.write_text('{"version": 1, "settings": {}, "items": [{"source": "a.mkv", "preset_name": "Cine", "preset_fingerprint": "legacy"}]}', encoding="utf-8")
    settings, items = load_batch_job(path)
    save_batch_job(path, settings, items)
    assert "preset_fingerprint" not in path.read_text(encoding="utf-8")


def test_preset_language_filters_are_applied_to_tracks():
    source = Path("movie.mkv")
    media = MediaInfo(
        source, 60, 1920, 1080, "h264",
        (MediaTrack(0, "video", "h264", "", "", source),),
        (AudioTrack(1, "aac", 2, "stereo", "spa", "Castellano"), AudioTrack(2, "aac", 2, "stereo", "eng", "English")),
        (),
    )
    preset = Preset("Solo español", track_languages={"audio": {"enabled": True, "language_ids": ["spa"], "keep_unknown": False}})
    languages = [TrackLanguage("spa", "Español", ["spa", "castellano"]), TrackLanguage("eng", "English", ["eng", "english"])]
    configs = configs_for_preset(media, preset, languages)
    audio = [config for config in configs if config.track.kind == "audio"]
    assert [config.included for config in audio] == [True, False]


def test_batch_preset_can_copy_video_without_reencoding():
    source = Path("movie.mkv")
    media = MediaInfo(source, 60, 1920, 1080, "hevc", (MediaTrack(0, "video", "hevc", "", "", source),), (), ())
    configs = configs_for_preset(media, Preset("Copia", video={"copy_video": True}), [])
    assert configs[0].copy_video is True


def test_active_language_filter_requires_a_match_for_each_track_kind():
    source = Path("movie.mkv")
    media = MediaInfo(
        source, 60, 1920, 1080, "h264",
        (MediaTrack(0, "video", "h264", "eng", "", source),),
        (AudioTrack(1, "aac", 2, "stereo", "eng", "English"),),
        (MediaTrack(2, "subtitle", "subrip", "eng", "English", source),),
    )
    filters = {kind: {"enabled": True, "language_ids": ["spa"], "keep_unknown": False} for kind in ("video", "audio", "subtitle")}
    preset = Preset("Solo español", track_languages=filters)
    languages = [TrackLanguage("spa", "Español", ["spa"]), TrackLanguage("eng", "English", ["eng"])]
    configs = configs_for_preset(media, preset, languages)
    assert empty_language_filter_kinds(configs, preset) == ["video", "audio", "subtitle"]


def test_disabled_subtitles_do_not_require_a_language_match():
    preset = Preset("Sin subtítulos", keep_subtitles=False, track_languages={"subtitle": {"enabled": True, "language_ids": ["spa"], "keep_unknown": False}})
    assert empty_language_filter_kinds([], preset) == []


def test_unique_output_path_avoids_disk_and_reserved_names(tmp_path):
    source = tmp_path / "movie.mkv"
    (tmp_path / "movie_compressed.mkv").touch()
    reserved = {tmp_path / "movie_compressed_1.mkv"}
    assert unique_output_path(source, tmp_path, ".mkv", reserved).name == "movie_compressed_2.mkv"
