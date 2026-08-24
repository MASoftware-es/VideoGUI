import json
from pathlib import Path

import pytest

from gui.core.media import MediaError, media_from_probe_output


def test_media_can_be_built_from_async_ffprobe_output():
    output = json.dumps({
        "streams": [
            {"index": 0, "codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080},
            {"index": 1, "codec_type": "audio", "codec_name": "aac", "channels": 2},
        ],
        "format": {"duration": "12.5"},
    })

    media = media_from_probe_output(Path("movie.mkv"), output)

    assert media.duration == 12.5
    assert media.video_codec == "h264"
    assert len(media.audio_tracks) == 1


def test_invalid_async_ffprobe_output_is_reported_as_media_error():
    with pytest.raises(MediaError):
        media_from_probe_output(Path("movie.mkv"), "not json")
