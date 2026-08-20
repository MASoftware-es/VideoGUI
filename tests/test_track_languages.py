from gui.track_languages import EMPTY_ALIAS, TEMPLATE_PATH, TrackLanguage, load_languages, recognize_language, restore_user_catalog, save_languages


def test_catalogue_round_trip_and_recognition(tmp_path):
    path = tmp_path / "track_languages.json"
    languages = [TrackLanguage("spa", "Español", ["es", "spa", "español", "castellano"])]
    save_languages(path, languages)
    loaded = load_languages(path)
    assert recognize_language("spa", "", loaded).identifier == "spa"
    assert recognize_language("", "Audio Castellano 5.1", loaded).identifier == "spa"


def test_short_aliases_do_not_match_inside_words():
    languages = [TrackLanguage("spa", "Español", ["es"]), TrackLanguage("sin", "Cingalés", ["sin"])]
    assert recognize_language("", "English", languages) is None
    assert recognize_language("", "Comentarios sin identificar", languages) is None
    assert recognize_language("es-ES", "", languages).identifier == "spa"


def test_recognition_ignores_case_accents_and_punctuation():
    languages = [TrackLanguage("spa", "Español", ["español"])]
    assert recognize_language("", "ESPAÑOL (España)", languages).identifier == "spa"


def test_empty_alias_recognizes_a_missing_language_code():
    languages = [TrackLanguage("und", "Sin especificar", [EMPTY_ALIAS])]
    assert recognize_language("", "", languages).identifier == "und"
    assert recognize_language("", "Comentario sin identificar", languages).identifier == "und"
    assert recognize_language("eng", "", languages) is None


def test_normal_title_alias_takes_precedence_over_empty_fallback():
    languages = [
        TrackLanguage("und", "Sin especificar", [EMPTY_ALIAS]),
        TrackLanguage("spa", "Español", ["castellano"]),
    ]
    assert recognize_language("", "Audio Castellano", languages).identifier == "spa"


def test_restore_replaces_personal_catalogue_with_template(tmp_path):
    path = tmp_path / "track_languages.json"
    save_languages(path, [TrackLanguage("custom", "Personalizado", ["custom"])])
    restore_user_catalog(path)
    assert path.read_bytes() == TEMPLATE_PATH.read_bytes()
    assert all(language.identifier != "custom" for language in load_languages(path))
