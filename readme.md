# VideoGUI

VideoGUI is a Linux desktop application for inspecting, organizing, and converting the tracks in a video through a graphical interface. It uses FFmpeg as its media engine and Qt 6 for the interface.

It is designed to prepare video files without writing FFmpeg commands: you can choose which tracks to keep, change their order and description, adjust the picture, convert audio, and preserve subtitles, chapters, and metadata.

## Main features

- Reads AVI, MP4, and MKV videos.
- Converts to MKV, MP4, or AVI.
- Manages video, audio, and subtitle tracks independently.
- Displays technical information for each track: codec, resolution, FPS, and pixel format for video; channels, sample rate, and bitrate for audio; and forced status for subtitles.
- Adds tracks from external files.
- Changes the order, title, language, and default or forced disposition of each track.
- Copies tracks directly without re-encoding when the original content should be preserved.
- Encodes video as H.264, HEVC, AV1, or VP9.
- Resizes to common resolutions or custom dimensions.
- Preserves or changes the aspect ratio using cropping, distortion, or black borders.
- Supports constant quality, variable bitrate, and constant bitrate control.
- Supports AAC, AC3, MP3, Opus, and FLAC audio, as well as direct copying.
- Normalizes volume and enhances dialogue.
- Uses NVIDIA NVENC/CUDA acceleration when available, with an automatic CPU fallback.
- Provides batch processing with preflight validation, saved-job recovery, and progress for both the current file and the complete queue.
- Provides reusable presets with independent language filters for video, audio, and subtitle tracks.
- Includes English, Spanish, French, Italian, and German interfaces and several visual themes.
- Plays audible alerts for message and confirmation dialogs.

## Requirements

VideoGUI requires:

- Linux with a graphical environment.
- Bash 4.2 or later.
- Python 3.10 or later.
- FFmpeg and FFprobe.
- Qt graphical libraries for OpenGL/EGL, X11/XCB, and xkbcommon.
- Enough free disk space for converted videos.

The installer recognizes Debian, Ubuntu, Linux Mint, Fedora, RHEL, Arch Linux, openSUSE, and SUSE-based distributions.

GPU acceleration is optional. To use NVIDIA acceleration, the installed driver and FFmpeg build must provide the appropriate NVENC encoders. The application can also run entirely on the CPU.

The CUDA path converts videos scaled on the GPU to `NV12`. This allows H.264 NVENC to encode common H.264 and HEVC sources reliably, including 10-bit SDR sources, although output from this path is 8-bit. Direct video copying preserves the original format and bit depth. For 10-bit HDR material that must remain 10-bit, use direct copying or verify the result with a suitable configuration and encoder before processing a complete collection.

## Recommended installation

Download or extract VideoGUI into a folder where your user has write permission. Open a terminal in that folder and run:

```bash
chmod +x bin/setup bin/videogui
./bin/setup --install
```

The installer performs the following operations:

1. Detects the Linux distribution.
2. Checks Python, FFmpeg, and the required libraries.
3. Requests permission before installing missing system packages.
4. Creates a private Python environment in `gui/.venv`.
5. Installs VideoGUI and PySide6 in that environment.
6. Checks whether NVIDIA NVENC is available.

`sudo` may request the administrator password to install system dependencies.

To check the requirements without installing or modifying anything:

```bash
./bin/setup --check
```

To skip the package installer's confirmation prompt:

```bash
./bin/setup --install --yes
```

## Manual installation

If your distribution is not recognized, use its package manager to install Python 3.10 or later, the `venv` module, FFmpeg, FFprobe, and the graphical libraries required by Qt. Then run the following commands from the VideoGUI folder:

```bash
python3 -m venv gui/.venv
gui/.venv/bin/python -m pip install --upgrade pip
gui/.venv/bin/python -m pip install -e .
```

## Starting VideoGUI

After installation, run:

```bash
./bin/videogui
```

The application uses its private environment, so you do not need to activate a virtual environment manually.

## Creating a package for another computer

To generate a clean, portable VideoGUI ZIP archive, run:

```bash
./bin/package
```

This creates `dist/VideoGUI.zip` without the virtual environment, caches, temporary files, or internal repository data. On the destination computer, extract the archive and run `bin/setup --install` to create the environment and check its dependencies there.

## Basic usage

### 1. Open a video

Click **Open video…** on the **Single file** tab and select an AVI, MP4, or MKV file. VideoGUI inspects the file with FFprobe and displays its video, audio, and subtitle tracks separately.

It proposes an output name ending in `_compressed.mkv`. Both the name and output directory can be changed.

### 2. Select the tracks

Use the **Video**, **Audio**, and **Subtitles** tabs to review the content.

- **Remove / restore** excludes or includes a track again without modifying the original file.
- **Move up** and **Move down**, or dragging with the mouse, change the final order.
- **Add…** adds a compatible track from another file.
- The description and language fields are stored as output-track metadata.
- **Default** and **Forced** control the playback disposition.

The **Information** panel shows technical details for the selected track. For video it includes resolution, FPS, and pixel format; for audio it includes channels, channel layout, sample rate, and bitrate; for subtitles it indicates whether the original track was marked as forced.

The original video is never modified. All changes apply only to the new output file.

### 3. Configure video

For each video track, you can choose:

- Copy the original track without re-encoding.
- H.264, HEVC, AV1, or VP9 output.
- Original, 4K, 1440p, 1080p, 720p, 480p, or custom resolution.
- Fitting within a standard frame or automatic sizing based on width.
- Aspect-ratio preservation.
- Cropping, distortion, or black borders.
- Constant quality (CQ/CRF), variable bitrate (VBR), or constant bitrate (CBR).

In constant-quality mode, a lower number normally provides higher quality and produces a larger file; a higher number reduces file size at the expense of quality.

The **Use hardware acceleration when available** checkbox enables NVIDIA NVENC when FFmpeg provides the requested encoder. If it is unavailable, VideoGUI automatically uses the corresponding CPU encoder. Clear the checkbox to always force CPU processing.

When the picture adjustment can run entirely through CUDA, decoding and scaling both remain on the GPU. CUDA scaling forces the 8-bit `NV12` format for compatibility with H.264 NVENC, including when the source is HEVC Main 10. Operations unavailable in the CUDA filters used by VideoGUI—such as some cropping or border combinations—use CPU filters while retaining NVENC as the encoder whenever possible.

### 4. Configure audio

Each audio track can be copied directly or converted to AAC, AC3, MP3, Opus, or FLAC.

The audio-format list includes **Vorbis (OGG)**. The track is encoded as Vorbis through `libvorbis` in variable-quality VBR mode; OGG is the container commonly used to distribute this codec as standalone audio. In VideoGUI, the Vorbis track is stored inside the selected video container, preferably MKV.

**Normalize and enhance dialogue** applies dynamic-range compression and loudness normalization. For multichannel audio, it also performs a stereo downmix adapted to the channel layout. This option is disabled when **Copy original** is selected because direct copying cannot apply filters.

### 5. Choose the output format

Under **Output directory**, select **Same as source** to always save the result beside the open file. While selected, the path is updated whenever another file is opened, and both directory editing and the **Browse** button remain disabled. Clear it to choose a different folder.

Select **MKV**, **MP4**, or **AVI** under **Output format**. The proposed name automatically uses the appropriate extension. You can also type a valid extension in the name to update the selector. If the name has no supported extension, VideoGUI uses the selected format.

MKV is the most flexible option for combining different codecs, audio tracks, and subtitles. MP4 and AVI support fewer combinations; the application warns you before conversion if a selected track is incompatible with the chosen container.

### 6. Convert

Click **Convert**. The bottom progress bar displays the percentage and processing speed. During conversion, the button changes to **Stop**.

If you stop the process and confirm cancellation, the incomplete file is deleted. If a file with the same name already exists, VideoGUI asks for confirmation before overwriting it.

## Presets

**Presets** store settings for reuse with individual files and batch jobs. Manage them from **Application > Presets…**, where you can create, edit, duplicate, and delete them.

Each preset stores:

- Video encoding: direct copy or codec, resolution, adjustment mode, aspect ratio, cropping or borders, and quality or bitrate control.
- Audio conversion and whether dialogue normalization and enhancement are enabled.
- Whether subtitles are kept.
- The track numbers eligible for processing, from 1 to 20 and configured independently for video, audio, and subtitles.
- An independent language filter for video, audio, and subtitle tracks.
- Whether each filter also keeps tracks whose language cannot be recognized.

Names are compared without regard to case or surrounding whitespace, so equivalent presets such as `Cinema` and ` cinema ` cannot both be created. **Duplicate** creates a complete copy and asks for a new name.

In **Single file**, the selected preset is applied to every track in the open video and remains selected for the next file. If selected before opening a video, it is applied after inspection finishes. External tracks added later also receive the corresponding settings. If an option is changed manually or the included tracks no longer match the profile, the selector changes to **Custom / No preset**.

Track numbering is calculated independently for each media type and retains the original inspection order: video 1, video 2, audio 1, audio 2, and so on. Tracks after number twenty are excluded, and selected numbers that do not exist in a file are ignored. When enabled, the language filter is applied in addition to number selection. For every media type, **Include only the default track** clears and disables number selection; if no track of that type is marked as default, its first track is used.

At least one preset is required for **Batch processing**. The top selector determines the profile assigned to files added later, while each row can use a different one. **Apply to all** assigns the top preset to every row and returns them to Pending status. Saved jobs store the preset name rather than a copy of its contents: testing and processing always use its current version. If the preset has been deleted, the row asks you to select another one.

Presets are stored in:

```text
~/.config/VideoGUI/presets.json
```

If `XDG_CONFIG_HOME` is defined, VideoGUI uses `$XDG_CONFIG_HOME/VideoGUI/presets.json`.

## Track languages

VideoGUI uses a configurable catalogue to recognize a track's language from its language code and description. Manage it from **Application > Preferences > Manage track languages…**.

For each language, you can specify:

- A display name shown in preset settings.
- One or more recognition strings, written on separate lines or separated by commas.
- The special `@empty` alias, which recognizes tracks without a language code or language description.

Recognition is case-insensitive and ignores accents and punctuation. It also prevents short aliases from matching inside other words. When several rules could match, an explicit match in the code or description takes precedence over the general `@empty` rule.

Language filters are configured independently for **Video**, **Audio**, and **Subtitles** in each preset. For each track type, you can:

- Disable the filter to keep every language.
- Enable it and select exactly which languages to keep.
- Choose whether to keep or exclude tracks whose language is not recognized.

When a preset is applied to a single file, the application reports unrecognized tracks and applies the selected unknown-language rule. In batch processing, **Test** reports an error when an active filter keeps no tracks of a required type. If subtitles are disabled in the preset, it does not require a subtitle-language match.

Deleting a language also removes its reference from every preset that uses it. After confirmation, **Restore languages** replaces the entire personal catalogue with the template included with VideoGUI and removes all customizations.

The personal catalogue is stored in:

```text
~/.config/VideoGUI/track_languages.json
```

If `XDG_CONFIG_HOME` is defined, VideoGUI uses `$XDG_CONFIG_HOME/VideoGUI/track_languages.json`. The application creates this file from its initial template and does not overwrite it on subsequent launches.

## Batch processing

The **Batch processing** tab converts several videos sequentially. You must create at least one preset under **Application > Presets…** before using it.

The general preset is assigned to files added later. Each row retains its own selection and can be changed without affecting the others. **Apply to all** replaces every row's preset with the general preset and returns each row to Pending status. Files can be selected in several operations, removed using multiple selection, and reordered with the arrow buttons. They can also be sorted ascending or descending by clicking the **Source file**, **Preset**, and **Status** headers.

Output can be saved beside each original file or in a common folder, in MKV, MP4, or AVI format. Names are formed by appending `_compressed`; if the destination already exists or conflicts with another output in the job, `_1`, `_2`, and subsequent suffixes are added without overwriting files.

When a single row is selected, you can open its source or destination folder directly. During processing, the application separately displays the progress and speed of the current file and the overall percentage with the number of completed files.

**Test** inspects every row that is not completed and validates its preset, tracks, encoders, container, and output folder. Results appear in the table, and errors can be reviewed without stopping validation. **Process** repeats validation and sequentially converts valid rows; an error does not prevent later rows from running.

**Stop** cancels only the active conversion, deletes its incomplete output, and stops the queue. Completed rows are preserved and are not converted again unless they are selected and **Set as Pending** is clicked. Cancelled rows are validated again the next time **Test** or **Process** is clicked.

**Save job…** stores order, preset names, statuses, errors, results, and all processing options in a `.vgbatch.json` file. **Load job…** replaces the current job and restores that data. Testing and processing always use the current configuration of each named preset. If a preset was deleted, its row asks you to select another.

## Language and appearance

Under **Application > Preferences**, you can select:

- English, Spanish, French, Italian, or German.
- Default, Blue, Dark, Ochre, or Red theme.

The selection is saved for the next launch.

Message and confirmation dialogs play an audible alert so that completion, errors, and pending decisions can also be noticed when the window is not in the foreground.

## Saved configuration

VideoGUI automatically stores preferences through the Qt settings system. On Linux, the file is normally stored at:

```text
~/.config/VideoGUI/VideoGUI.conf
```

If the `XDG_CONFIG_HOME` environment variable is defined, the path is:

```text
$XDG_CONFIG_HOME/VideoGUI/VideoGUI.conf
```

This file stores:

- Selected language and theme.
- Window position, size, and maximized state.
- Last active tab: single file or batch processing.
- Last output directory.
- Last selected output format.
- Hardware-acceleration preference.
- Last video codec, resolution, aspect-ratio, quality, and bitrate settings.
- Last audio format and normalization state.
- Name of the last selected preset.

Complete preset data and the personal language catalogue are stored separately in the files documented in their respective sections.

These preferences apply to videos opened later. **Default values** restores the initial encoding profile.

Converted files are saved in the output directory selected in the main window. VideoGUI does not move or replace the original file.

## Installation paths

VideoGUI keeps its components inside the folder where it was extracted:

```text
VideoGUI/
├── bin/videogui       Application launcher
├── bin/setup          Dependency installer and checker
├── bin/package        Portable ZIP package generator
├── gui/.venv/         Private Python and PySide6 environment
└── gui/               Application, languages, icon, and themes
```

The `gui/.venv` environment contains no personal preferences or videos. It can be rebuilt by running `./bin/setup --install` again.

## Troubleshooting

### The application reports that FFprobe is missing

Install FFmpeg from your distribution's repositories. FFprobe is normally included in the same package. Then check the installation:

```bash
ffmpeg -version
ffprobe -version
```

### The launcher cannot find the virtual environment

Run the installation again from the application folder:

```bash
./bin/setup --install
```

### NVIDIA acceleration is unavailable

Check the encoders detected by FFmpeg:

```bash
ffmpeg -hide_banner -encoders | grep nvenc
```

If the required encoder is not listed, update the NVIDIA driver or install an FFmpeg build with NVENC support. In the meantime, disable hardware acceleration to use the CPU.

### A 10-bit video fails or looks different when using NVIDIA

In the CUDA scaling path, VideoGUI converts the picture to 8-bit `NV12` so that H.264 NVENC can also accept HEVC Main 10 sources. If it still fails, check that the GPU can decode the source codec and that the driver is compatible with the installed FFmpeg version. You can disable acceleration to use CPU filters and encoders.

This conversion is suitable for typical SDR content. It can alter colors in HDR material because it does not perform HDR-to-SDR tone mapping by itself. If you need to preserve HDR or 10-bit output, copy the video track without re-encoding or use a suitable external configuration and verify the result.

### MP4 or AVI rejects a track

Select MKV as the output format, copy or convert the track to a compatible codec, or exclude it before conversion.

### Resetting all settings

Close VideoGUI and rename or delete the preferences file:

```text
~/.config/VideoGUI/VideoGUI.conf
```

When started again, VideoGUI creates a new configuration with default values.
