import tomllib
from pathlib import Path

from gui.config import APP_MODIFICATION_DATE, APP_VERSION
from gui.i18n import discover_languages, text
from gui.themes import discover_themes
from gui.app import DIALOG_SOUND_PATH


def test_application_version_matches_package_metadata():
    project_file = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project = tomllib.loads(project_file.read_text(encoding="utf-8"))
    assert APP_VERSION == project["project"]["version"]
    assert APP_MODIFICATION_DATE


def test_discovers_bundled_languages():
    languages = discover_languages()
    assert set(languages) >= {"es", "en", "fr", "it", "de"}
    assert languages["es"].name
    assert text(languages, "en", "convert") == "Convert"
    assert text(languages, "fr", "convert") == "Convertir"
    assert text(languages, "it", "convert") == "Converti"
    assert text(languages, "de", "convert") == "Konvertieren"


def test_every_language_resolves_the_complete_base_catalogue():
    languages = discover_languages()
    base_keys = set(languages["es"].strings)
    for language in languages.values():
        assert set(language.strings) == base_keys


def test_bundles_dialog_notification_sound():
    assert DIALOG_SOUND_PATH.is_file()
    assert DIALOG_SOUND_PATH.suffix == ".ogg"


def test_unknown_language_falls_back_to_spanish():
    languages = discover_languages()
    assert text(languages, "missing", "convert") == "Convertir"


def test_discovers_bundled_themes_and_stylesheets():
    themes = discover_themes()
    assert set(themes) == {"default", "blue", "dark", "ochre", "red"}
    assert "QMainWindow" in themes["dark"].stylesheet
    assert themes["default"].display_name("en") == "Default"
    assert themes["ochre"].display_name("es") == "Ocre"
    assert themes["red"].display_name("en") == "Red"
    expected_backgrounds = {
        "default": "#f4f6f8",
        "blue": "#C8DCEB",
        "dark": "#171a1f",
        "ochre": "#E0D2B3",
        "red": "#DFC3C6",
    }
    for identifier, background in expected_backgrounds.items():
        assert "${" not in themes[identifier].stylesheet
        assert background in themes[identifier].stylesheet
        assert 'QPushButton[danger="true"]' in themes[identifier].stylesheet
        assert 'QPushButton[success="true"]' in themes[identifier].stylesheet
        assert 'QProgressBar[scope="total"]::chunk' in themes[identifier].stylesheet


def test_every_theme_resolves_its_danger_colour():
    themes = discover_themes()
    expected_danger_colours = {
        "default": "#b3261e",
        "blue": "#983C4A",
        "dark": "#da3633",
        "ochre": "#93473B",
        "red": "#9D3340",
    }
    for identifier, colour in expected_danger_colours.items():
        assert colour in themes[identifier].stylesheet


def test_every_theme_defines_a_processing_row_colour():
    for theme in discover_themes().values():
        assert theme.colors["processing_row"]
        assert theme.colors["processing_row"] in theme.stylesheet
