import json

from gui.presets import Preset, load_presets, normalized_name, save_presets


def test_presets_round_trip_in_independent_json(tmp_path):
    path = tmp_path / "VideoGUI" / "presets.json"
    preset = Preset("Cine", video={"video_codec": "hevc"}, audio={"audio_codec": "aac"}, keep_subtitles=False)
    save_presets(path, [preset])
    loaded = load_presets(path)
    assert loaded[0].name == "Cine"
    assert loaded[0].video["video_codec"] == "hevc"
    assert loaded[0].video["quality"] == 30
    assert loaded[0].audio["audio_codec"] == "aac"
    assert loaded[0].keep_subtitles is False
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1


def test_names_are_case_and_whitespace_insensitive():
    assert normalized_name("  Mi Perfil ") == normalized_name("MI PERFIL")


def test_loader_ignores_duplicate_names(tmp_path):
    path = tmp_path / "presets.json"
    path.write_text('{"presets": [{"name": "Cine"}, {"name": "CINE"}]}', encoding="utf-8")
    assert [preset.name for preset in load_presets(path)] == ["Cine"]


def test_old_presets_get_disabled_language_filters():
    preset = Preset.from_dict({"name": "Anterior"})
    assert preset.video["copy_video"] is False
    for kind in ("video", "audio", "subtitle"):
        assert preset.track_languages[kind] == {"enabled": False, "language_ids": [], "keep_unknown": True}


def test_video_copy_is_saved_in_preset(tmp_path):
    path = tmp_path / "presets.json"
    save_presets(path, [Preset("Sin recodificar", video={"copy_video": True})])
    assert load_presets(path)[0].video["copy_video"] is True


def test_only_default_video_track_is_saved_and_old_presets_default_to_disabled(tmp_path):
    path = tmp_path / "presets.json"
    save_presets(path, [Preset("Principal", only_default_video_track=True)])
    assert load_presets(path)[0].only_default_video_track is True

    path.write_text('{"presets": [{"name": "Antiguo"}]}', encoding="utf-8")
    assert load_presets(path)[0].only_default_video_track is False


def test_track_numbers_are_saved_and_old_presets_select_first_ten(tmp_path):
    path = tmp_path / "presets.json"
    save_presets(path, [Preset("Pistas", track_numbers={"video": [1, 3], "audio": [2], "subtitle": [4, 5]})])
    loaded = load_presets(path)[0]
    assert loaded.track_numbers == {"video": [1, 3], "audio": [2], "subtitle": [4, 5]}

    path.write_text('{"presets": [{"name": "Antiguo"}]}', encoding="utf-8")
    assert load_presets(path)[0].track_numbers == {kind: list(range(1, 11)) for kind in ("video", "audio", "subtitle")}


def test_new_presets_select_twenty_tracks_and_default_selection_is_per_kind(tmp_path):
    preset = Preset("Nuevo", only_default_tracks={"audio": True, "subtitle": True})
    assert preset.track_numbers == {"video": list(range(1, 21)), "audio": [], "subtitle": []}
    assert preset.only_default("video") is False
    assert preset.only_default("audio") is True
    assert preset.only_default("subtitle") is True

    path = tmp_path / "presets.json"
    save_presets(path, [preset])
    loaded = load_presets(path)[0]
    assert loaded.only_default_tracks == {"video": False, "audio": True, "subtitle": True}
