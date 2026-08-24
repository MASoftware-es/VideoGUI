from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QItemSelectionModel, QObject, QProcess, QSettings, Qt, QUrl, Signal, QTimer
from PySide6.QtGui import QAction, QActionGroup, QBrush, QColor, QCloseEvent, QDesktopServices, QFont, QIcon, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QInputDialog,
    QDoubleSpinBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSpinBox,
    QSizePolicy, QSplitter, QStyle, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from gui.core.batch import (
    CANCELLED, CHECKING, COMPLETED, ERROR, PENDING, PROCESSING, VALID,
    BatchItem, BatchSettings, find_preset, load_batch_job,
    save_batch_job, validate_batch_item, validate_batch_media,
)
from gui.config import PROBE_TIMEOUT_SECONDS
from gui.core.ffmpeg import EncodingOptions, aligned_dimension, build_project_command, required_dimension_alignment
from gui.core.media import MediaError, MediaTrack, SUPPORTED_EXTENSIONS, media_from_probe_output, probe_external_tracks, probe_media
from gui.core.project import TrackConfig, container_warnings
from gui.i18n import discover_languages, text
from gui.presets import AUDIO_DEFAULTS, VIDEO_DEFAULTS, Preset, load_presets, normalized_name, save_presets
from gui.themes import discover_themes
from gui.track_languages import EMPTY_ALIAS, TrackLanguage, load_languages, new_language, normalize, recognize_language, restore_user_catalog, save_languages


ICON_PATH = Path(__file__).resolve().parent / "assets" / "icon.png"
DIALOG_SOUND_PATH = Path(__file__).resolve().parent / "assets" / "dialog.ogg"

VIDEO_PREFERENCE_DEFAULTS = {
    "video_codec": "h264", "copy_video": False, "resolution": "hd_720", "resolution_mode": "width", "custom_width": 1280,
    "custom_height": 720, "preserve_aspect": False, "aspect_ratio": "original",
    "fit_mode": "crop", "add_borders": False, "rate_control": "quality",
    "quality": 30, "bitrate_mbps": 4.0, "max_bitrate_mbps": 6.0,
}
AUDIO_PREFERENCE_DEFAULTS = {"audio_codec": "mp3", "normalize": True}


class DialogSound(QObject):
    """Reproduce el aviso sonoro al mostrarse cualquier QMessageBox."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.audio_output = QAudioOutput(self); self.audio_output.setVolume(1.0)
        self.player = QMediaPlayer(self); self.player.setAudioOutput(self.audio_output)
        self.player.setSource(QUrl.fromLocalFile(str(DIALOG_SOUND_PATH)))

    def eventFilter(self, watched, event) -> bool:
        if isinstance(watched, QMessageBox) and event.type() == QEvent.Type.Show:
            self.player.stop(); self.player.setPosition(0); self.player.play()
        return super().eventFilter(watched, event)


def ask_yes_no(parent: QWidget, title: str, message: str, translate) -> bool:
    """Muestra una confirmación cuyos botones siguen el idioma de VideoGUI."""
    dialog = QMessageBox(parent)
    dialog.setWindowTitle(title); dialog.setText(message)
    dialog.setIcon(QMessageBox.Icon.Question)
    dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    dialog.setDefaultButton(QMessageBox.StandardButton.No)
    yes_button = dialog.button(QMessageBox.StandardButton.Yes)
    yes_button.setText(translate("yes")); yes_button.setProperty("danger", True)
    dialog.button(QMessageBox.StandardButton.No).setText(translate("no"))
    dialog.exec()
    return dialog.clickedButton() is dialog.button(QMessageBox.StandardButton.Yes)


def set_button_role(button: QPushButton, *, danger: bool = False, execution: bool = False, success: bool = False) -> None:
    """Actualiza el estilo semántico de un botón, incluso si ya es visible."""
    button.setProperty("danger", danger); button.setProperty("execution", execution); button.setProperty("success", success)
    button.style().unpolish(button); button.style().polish(button); button.update()


class VideoSettingsWidget(QWidget):
    changed = Signal()

    def __init__(self, translate, source_aspect_ratio=None) -> None:
        super().__init__(); self.t = translate; self.source_aspect_ratio = source_aspect_ratio; self.loading = False
        self.video_codec = QComboBox()
        for label, value in (("H.264", "h264"), ("H.265 / HEVC", "hevc"), ("AV1", "av1"), ("VP9", "vp9")): self.video_codec.addItem(label, value)
        self.resolution = QComboBox()
        for value in ("original", "uhd_2160", "qhd_1440", "fhd_1080", "hd_720", "sd_480", "custom"): self.resolution.addItem("", value)
        self.resolution_mode, self.aspect, self.fit_mode, self.rate_control = QComboBox(), QComboBox(), QComboBox(), QComboBox()
        self.aspect.setEditable(True)
        for label, value in (("", "original"), ("16:9", "16/9"), ("16:10", "16/10"), ("4:3", "4/3"), ("21:9", "21/9")): self.aspect.addItem(label, value)
        self.width, self.height = QSpinBox(), QSpinBox()
        for control in (self.width, self.height): control.setRange(2, 8192); control.setSingleStep(2)
        self.size_widget = QWidget(); size = QHBoxLayout(self.size_widget); size.setContentsMargins(0, 0, 0, 0); size.addWidget(self.width); size.addWidget(QLabel("×")); size.addWidget(self.height)
        self.preserve_aspect, self.add_borders = QCheckBox(), QCheckBox()
        self.quality = QSpinBox(); self.quality.setRange(0, 51)
        self.bitrate, self.max_bitrate = QDoubleSpinBox(), QDoubleSpinBox()
        for control in (self.bitrate, self.max_bitrate): control.setRange(0.1, 200.0); control.setDecimals(1); control.setSuffix(" Mbps")
        self.form = QFormLayout(self); self.form.setContentsMargins(0, 0, 0, 0)
        self.rows = (("video_codec", self.video_codec), ("resolution", self.resolution), ("resolution_mode", self.resolution_mode), ("custom_size", self.size_widget), ("preserve_aspect", self.preserve_aspect), ("aspect_ratio", self.aspect), ("fit_mode", self.fit_mode), ("add_borders", self.add_borders), ("rate_control", self.rate_control), ("quality_value", self.quality), ("bitrate", self.bitrate), ("max_bitrate", self.max_bitrate))
        for key, widget in self.rows: self.form.addRow(QLabel(), widget)
        for combo in (self.video_codec, self.resolution, self.resolution_mode, self.aspect, self.fit_mode, self.rate_control): combo.currentIndexChanged.connect(self._control_changed)
        for check in (self.preserve_aspect, self.add_borders): check.toggled.connect(self._control_changed)
        self.width.valueChanged.connect(self._width_changed); self.height.valueChanged.connect(self._height_changed)
        self.width.editingFinished.connect(self._normalize_dimensions); self.height.editingFinished.connect(self._normalize_dimensions)
        for spin in (self.quality, self.bitrate, self.max_bitrate): spin.valueChanged.connect(self._control_changed)
        self.add_borders.toggled.connect(lambda checked: self.preserve_aspect.setChecked(True) if checked else None)
        self.preserve_aspect.toggled.connect(lambda checked: self.add_borders.setChecked(False) if not checked else None)
        self.retranslate(); self.load_values(VIDEO_DEFAULTS)

    def retranslate(self) -> None:
        current = {combo: combo.currentData() for combo in (self.resolution_mode, self.fit_mode, self.rate_control)}
        resolution_labels = {
            "original": self.t("resolution_original"), "uhd_2160": self.t("resolution_uhd"), "qhd_1440": self.t("resolution_qhd"),
            "fhd_1080": self.t("resolution_fhd"), "hd_720": self.t("resolution_hd"), "sd_480": self.t("resolution_sd"), "custom": self.t("custom"),
        }
        for value, label in resolution_labels.items(): self.resolution.setItemText(self.resolution.findData(value), label)
        self.aspect.setItemText(self.aspect.findData("original"), self.t("resolution_original"))
        definitions = ((self.resolution_mode, (("standard_frame", "standard"), ("fit_width", "width"))), (self.fit_mode, (("crop", "crop"), ("distort", "distort"))), (self.rate_control, (("constant_quality", "quality"), ("variable_bitrate", "vbr"), ("constant_bitrate", "cbr"))))
        for combo, entries in definitions:
            combo.blockSignals(True); combo.clear()
            for key, value in entries: combo.addItem(self.t(key), value)
            combo.setCurrentIndex(max(0, combo.findData(current[combo]))); combo.blockSignals(False)
        for row, (key, widget) in enumerate(self.rows):
            item = self.form.itemAt(row, QFormLayout.ItemRole.LabelRole)
            if item and item.widget():
                item.widget().setText(self.t(key)); tooltip = self.t(f"{key}_tooltip") if key in {"quality_value", "bitrate", "max_bitrate"} else ""
                item.widget().setToolTip(tooltip); widget.setToolTip(tooltip)

    @staticmethod
    def _select(combo: QComboBox, value: object) -> None:
        index = combo.findData(value)
        if index >= 0: combo.setCurrentIndex(index)

    def load_values(self, values: dict) -> None:
        self.loading = True
        for combo, key in ((self.video_codec, "video_codec"), (self.resolution, "resolution"), (self.resolution_mode, "resolution_mode"), (self.fit_mode, "fit_mode"), (self.rate_control, "rate_control")): self._select(combo, values[key])
        self.width.setValue(int(values["custom_width"])); self.height.setValue(int(values["custom_height"]))
        self.preserve_aspect.setChecked(bool(values["preserve_aspect"])); self.add_borders.setChecked(bool(values["add_borders"]))
        aspect = str(values["aspect_ratio"]); index = self.aspect.findData(aspect)
        if index >= 0: self.aspect.setCurrentIndex(index)
        else: self.aspect.setEditText(aspect.replace("/", ":"))
        self.quality.setValue(int(values["quality"])); self.bitrate.setValue(float(values["bitrate_mbps"])); self.max_bitrate.setValue(float(values["max_bitrate_mbps"]))
        self.loading = False; self.update_controls()

    def values(self) -> dict:
        return {"video_codec": self.video_codec.currentData() or "h264", "resolution": self.resolution.currentData() or "hd_720", "resolution_mode": self.resolution_mode.currentData() or "width", "custom_width": self.width.value(), "custom_height": self.height.value(), "preserve_aspect": self.preserve_aspect.isChecked(), "aspect_ratio": self.aspect.currentData() or self.aspect.currentText().strip().replace(":", "/") or "original", "fit_mode": self.fit_mode.currentData() or "crop", "add_borders": self.add_borders.isChecked(), "rate_control": self.rate_control.currentData() or "quality", "quality": self.quality.value(), "bitrate_mbps": self.bitrate.value(), "max_bitrate_mbps": self.max_bitrate.value()}

    def set_context(self, enabled: bool, copying: bool = False) -> None:
        self.setEnabled(enabled); self.copying = copying; self.update_controls()

    def update_controls(self) -> None:
        enabled = self.isEnabled(); copying = getattr(self, "copying", False); original = self.resolution.currentData() == "original"; custom = self.resolution.currentData() == "custom"; standard = self.resolution_mode.currentData() == "standard"; preserving = self.preserve_aspect.isChecked(); rate = self.rate_control.currentData()
        self.form.setRowVisible(self.size_widget, enabled and custom and not copying)
        for widget in (self.video_codec, self.resolution, self.rate_control): widget.setEnabled(enabled and not copying)
        self.resolution_mode.setEnabled(enabled and not copying and not original); self.height.setEnabled(enabled and not copying and custom and standard)
        self.width.setEnabled(enabled and not copying and custom); self.preserve_aspect.setEnabled(enabled and not copying and not original and standard)
        self.aspect.setEnabled(enabled and not copying and not original and standard and not preserving); self.fit_mode.setEnabled(enabled and not copying and not original and standard and not preserving); self.add_borders.setEnabled(enabled and not copying and not original and standard)
        self.quality.setEnabled(enabled and not copying and rate == "quality"); self.bitrate.setEnabled(enabled and not copying and rate != "quality"); self.max_bitrate.setEnabled(enabled and not copying and rate == "vbr")

    def _control_changed(self, *_args) -> None:
        self.update_controls()
        if not self.loading: self.changed.emit()

    def _ratio(self) -> float | None:
        return self.source_aspect_ratio() if self.source_aspect_ratio else None

    def _width_changed(self, width: int) -> None:
        if not self.loading and self.resolution.currentData() == "custom" and self.resolution_mode.currentData() == "standard" and self.preserve_aspect.isChecked():
            ratio = self._ratio()
            if ratio: self.height.blockSignals(True); self.height.setValue(max(2, round(width / ratio / 2) * 2)); self.height.blockSignals(False)
        self._control_changed()

    def _height_changed(self, height: int) -> None:
        if not self.loading and self.resolution.currentData() == "custom" and self.resolution_mode.currentData() == "standard" and self.preserve_aspect.isChecked():
            ratio = self._ratio()
            if ratio: self.width.blockSignals(True); self.width.setValue(max(2, round(height * ratio / 2) * 2)); self.width.blockSignals(False)
        self._control_changed()

    def _normalize_dimensions(self) -> None:
        if self.loading or self.resolution.currentData() != "custom": return
        alignment = required_dimension_alignment(self.video_codec.currentData() or "h264"); self.loading = True
        self.width.setValue(aligned_dimension(self.width.value(), alignment)); self.height.setValue(aligned_dimension(self.height.value(), alignment)); self.loading = False; self.changed.emit()


class AudioSettingsWidget(QWidget):
    changed = Signal()

    def __init__(self, translate) -> None:
        super().__init__(); self.t = translate; self.loading = False
        self.codec = QComboBox()
        for codec in ("copy", "aac", "ac3", "mp3", "opus", "flac"): self.codec.addItem("" if codec == "copy" else codec.upper(), codec)
        self.normalize = QCheckBox()
        self.form = QFormLayout(self); self.form.setContentsMargins(0, 0, 0, 0); self.codec_label, self.normalize_label = QLabel(), QLabel()
        self.form.addRow(self.codec_label, self.codec); self.form.addRow(self.normalize_label, self.normalize)
        self.codec.currentIndexChanged.connect(self._control_changed); self.normalize.toggled.connect(self._control_changed)
        self.retranslate(); self.load_values(AUDIO_DEFAULTS)

    def retranslate(self) -> None:
        self.codec_label.setText(self.t("audio_codec")); self.normalize_label.setText(self.t("normalize"))
        index = self.codec.findData("copy")
        if index >= 0: self.codec.setItemText(index, self.t("copy_original"))

    def load_values(self, values: dict) -> None:
        self.loading = True; index = self.codec.findData(values.get("audio_codec", "mp3"))
        self.codec.setCurrentIndex(max(0, index)); self.normalize.setChecked(bool(values.get("normalize", True)) and self.codec.currentData() != "copy")
        self.loading = False; self.update_controls()

    def values(self) -> dict:
        codec = self.codec.currentData() or "copy"
        return {"audio_codec": codec, "normalize": self.normalize.isChecked() and codec != "copy"}

    def set_context(self, enabled: bool) -> None:
        self.setEnabled(enabled); self.update_controls()

    def update_controls(self) -> None:
        copying = self.codec.currentData() == "copy"
        if copying and self.normalize.isChecked():
            self.normalize.blockSignals(True); self.normalize.setChecked(False); self.normalize.blockSignals(False)
        self.normalize.setEnabled(self.isEnabled() and not copying)

    def _control_changed(self, *_args) -> None:
        self.update_controls()
        if not self.loading: self.changed.emit()


class TrackPanel(QWidget):
    changed = Signal()

    def __init__(self, kind: str, owner: "MainWindow") -> None:
        super().__init__()
        self.kind, self.owner, self.loading_editor = kind, owner, False
        self.list = QListWidget()
        self.list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.currentItemChanged.connect(self.load_editor)
        self.list.model().rowsMoved.connect(lambda: self.changed.emit())
        self.add_button, self.toggle_button = QPushButton(), QPushButton()
        self.up_button, self.down_button = QPushButton(), QPushButton()
        self.add_button.clicked.connect(self.add_external)
        self.toggle_button.clicked.connect(self.toggle_current)
        self.up_button.clicked.connect(lambda: self.move_current(-1))
        self.down_button.clicked.connect(lambda: self.move_current(1))
        set_button_role(self.toggle_button, danger=False)
        controls = QHBoxLayout()
        for button in (self.add_button, self.toggle_button, self.up_button, self.down_button):
            controls.addWidget(button)

        self.info = QPlainTextEdit(); self.info.setReadOnly(True)
        if kind == "video":
            self.info.setMinimumHeight(self.info.sizeHint().height())
        self.title_edit, self.language_edit = QLineEdit(), QLineEdit()
        self.default_check, self.forced_check = QCheckBox(), QCheckBox()
        self.copy_video_check = QCheckBox()
        self.video_settings = VideoSettingsWidget(owner.t, self.source_aspect_ratio) if kind == "video" else None
        self.audio_settings = AudioSettingsWidget(owner.t) if kind == "audio" else None
        self.title_edit.editingFinished.connect(self.save_editor)
        self.language_edit.editingFinished.connect(self.save_editor)
        for editor in (self.default_check, self.forced_check):
            editor.toggled.connect(self.save_editor)
        self.copy_video_check.toggled.connect(self.save_editor)
        if self.video_settings: self.video_settings.changed.connect(self.save_editor)
        if self.audio_settings: self.audio_settings.changed.connect(self.save_editor)

        self.form = QFormLayout()
        self.form.addRow(QLabel(), self.info)
        self.form.addRow(QLabel(), self.title_edit)
        self.form.addRow(QLabel(), self.language_edit)
        if kind == "video": self.form.addRow(QLabel(), self.copy_video_check)
        self.form.addRow(QLabel(), self.default_check)
        if kind == "subtitle": self.form.addRow(QLabel(), self.forced_check)
        if self.audio_settings: self.form.addRow(self.audio_settings)
        if self.video_settings: self.form.addRow(self.video_settings)
        editor_widget = QWidget(); editor_widget.setLayout(self.form)
        editor_scroll = QScrollArea(); editor_scroll.setWidgetResizable(True); editor_scroll.setWidget(editor_widget)
        left = QWidget(); left_layout = QVBoxLayout(left); left_layout.addWidget(self.list); left_layout.addLayout(controls)
        splitter = QSplitter(); splitter.addWidget(left); splitter.addWidget(editor_scroll); splitter.setSizes([390, 310])
        layout = QVBoxLayout(self); layout.addWidget(splitter)
        self.retranslate(); self.set_editor_enabled(False)

    def retranslate(self) -> None:
        t = self.owner.t
        for button, key in ((self.add_button, "add"), (self.toggle_button, "remove"), (self.up_button, "up"), (self.down_button, "down")):
            button.setText(t(key))
        keys = ["track_info", "description", "track_language"]
        if self.kind == "video": keys.append("copy_video")
        keys.append("default")
        if self.kind == "subtitle": keys.append("forced")
        for row, key in enumerate(keys):
            item = self.form.itemAt(row, QFormLayout.ItemRole.LabelRole)
            if item and item.widget():
                item.widget().setText(t(key))
                tooltip_key = f"{key}_tooltip"
                tooltip = t(tooltip_key) if key in {"quality_value", "bitrate", "max_bitrate"} else ""
                item.widget().setToolTip(tooltip)
                field = self.form.itemAt(row, QFormLayout.ItemRole.FieldRole)
                if field and field.widget(): field.widget().setToolTip(tooltip)
        for index in range(self.list.count()): self.refresh_item(self.list.item(index))
        if self.video_settings: self.video_settings.retranslate()
        if self.audio_settings: self.audio_settings.retranslate()

    def set_tracks(self, tracks: tuple[MediaTrack, ...]) -> None:
        self.list.clear()
        for track in tracks: self.append_config(TrackConfig(track))
        if self.list.count(): self.list.setCurrentRow(0)

    def append_config(self, config: TrackConfig) -> None:
        self.owner.apply_encoding_preferences(config)
        item = QListWidgetItem(); item.setData(Qt.ItemDataRole.UserRole, config); self.list.addItem(item); self.refresh_item(item)

    def configs(self) -> list[TrackConfig]:
        return [self.list.item(index).data(Qt.ItemDataRole.UserRole) for index in range(self.list.count())]

    def refresh_item(self, item: QListWidgetItem) -> None:
        config: TrackConfig = item.data(Qt.ItemDataRole.UserRole)
        name, language = config.title or config.track.title or self.owner.t("track_stream_name").format(index=config.track.index), config.language or "—"
        codec = config.track.codec or self.owner.t("unknown")
        prefix = f"[{self.owner.t('deleted')}] " if not config.included else ""
        item.setText(f"{prefix}{name} · {language} · {codec} · {config.track.source.name}")
        font = QFont(item.font()); font.setStrikeOut(not config.included); item.setFont(font)
        item.setForeground(QBrush(QColor("#888888")) if not config.included else QBrush())

    def load_editor(self, current: QListWidgetItem | None) -> None:
        self.loading_editor = True; self.set_editor_enabled(current is not None)
        if current:
            config: TrackConfig = current.data(Qt.ItemDataRole.UserRole); track = config.track
            details = [self.owner.t("track_info_file").format(value=track.source), self.owner.t("track_info_stream").format(value=track.index), self.owner.t("track_info_codec").format(value=track.codec or self.owner.t("unknown"))]
            if self.kind == "video": details += [self.owner.t("track_info_resolution").format(width=track.width, height=track.height), self.owner.t("track_info_fps").format(value=track.frame_rate), self.owner.t("track_info_pixels").format(value=track.pixel_format or "—")]
            elif self.kind == "audio": details += [self.owner.t("track_info_channels").format(channels=track.channels, layout=track.layout or "—"), self.owner.t("track_info_frequency").format(value=track.sample_rate or "—"), self.owner.t("track_info_bitrate").format(value=track.bitrate or "—")]
            else: details += [self.owner.t("track_info_forced").format(value=self.owner.t("yes") if track.disposition_forced else self.owner.t("no"))]
            self.info.setPlainText("\n".join(details)); self.title_edit.setText(config.title); self.language_edit.setText(config.language)
            self.copy_video_check.setChecked(config.copy_video); self.default_check.setChecked(config.default); self.forced_check.setChecked(config.forced)
            if self.video_settings: self.video_settings.load_values({field: getattr(config, field) for field in VIDEO_DEFAULTS})
            if self.audio_settings: self.audio_settings.load_values({field: getattr(config, field) for field in AUDIO_DEFAULTS})
        self.loading_editor = False
        set_button_role(self.toggle_button, danger=bool(current and current.data(Qt.ItemDataRole.UserRole).included))
        self.update_video_controls()
        self.update_audio_controls()

    def save_editor(self) -> None:
        if self.loading_editor or not self.list.currentItem(): return
        config: TrackConfig = self.list.currentItem().data(Qt.ItemDataRole.UserRole)
        config.title, config.language = self.title_edit.text().strip(), self.language_edit.text().strip()
        config.copy_video = self.copy_video_check.isChecked()
        config.forced = self.forced_check.isChecked()
        if self.video_settings:
            for field, value in self.video_settings.values().items(): setattr(config, field, value)
        if self.audio_settings:
            for field, value in self.audio_settings.values().items(): setattr(config, field, value)
        if self.default_check.isChecked() and not config.default:
            for other in self.configs(): other.default = False
        config.default = self.default_check.isChecked()
        self.refresh_item(self.list.currentItem()); self.update_video_controls(); self.update_audio_controls(); self.changed.emit()

    def source_aspect_ratio(self) -> float | None:
        item = self.list.currentItem()
        if not item:
            return None
        track = item.data(Qt.ItemDataRole.UserRole).track
        if track.width > 0 and track.height > 0:
            return track.width / track.height
        if self.video_settings and self.video_settings.width.value() > 0 and self.video_settings.height.value() > 0:
            return self.video_settings.width.value() / self.video_settings.height.value()
        return None

    def update_video_controls(self) -> None:
        if self.kind != "video": return
        has_track = self.list.currentItem() is not None
        copying = self.copy_video_check.isChecked()
        self.default_check.setEnabled(has_track and not copying)
        if self.video_settings: self.video_settings.set_context(has_track, copying)

    def update_audio_controls(self) -> None:
        if self.kind != "audio": return
        has_track = self.list.currentItem() is not None
        if self.audio_settings: self.audio_settings.set_context(has_track)

    def set_editor_enabled(self, enabled: bool) -> None:
        for widget in (self.info, self.title_edit, self.language_edit, self.copy_video_check, self.default_check, self.forced_check):
            widget.setEnabled(enabled)
        if self.video_settings: self.video_settings.set_context(enabled, self.copy_video_check.isChecked())
        if self.audio_settings: self.audio_settings.set_context(enabled)

    def toggle_current(self) -> None:
        item = self.list.currentItem()
        if item:
            config: TrackConfig = item.data(Qt.ItemDataRole.UserRole); config.included = not config.included
            self.refresh_item(item); set_button_role(self.toggle_button, danger=config.included); self.changed.emit()

    def move_current(self, offset: int) -> None:
        row, target = self.list.currentRow(), self.list.currentRow() + offset
        if row < 0 or target < 0 or target >= self.list.count(): return
        item = self.list.takeItem(row); self.list.insertItem(target, item); self.list.setCurrentRow(target); self.changed.emit()

    def add_external(self) -> None:
        filters = {"video": self.owner.t("video_file_filter"), "audio": self.owner.t("audio_file_filter"), "subtitle": self.owner.t("subtitle_file_filter")}
        filename, _ = QFileDialog.getOpenFileName(self, self.owner.t("add"), "", filters[self.kind])
        if not filename: return
        try: tracks = probe_external_tracks(Path(filename), self.kind, self.owner.t)
        except MediaError as exc:
            QMessageBox.critical(self, self.owner.t("error"), str(exc)); return
        for track in tracks: self.append_config(TrackConfig(track))
        self.list.setCurrentRow(self.list.count() - len(tracks)); self.changed.emit()


class LanguageFilterWidget(QWidget):
    def __init__(self, owner: "MainWindow", kind: str) -> None:
        super().__init__(); self.owner, self.kind = owner, kind
        self.enabled_check = QCheckBox(owner.t("filter_track_languages"))
        self.list = QListWidget()
        self.list.setMinimumHeight(140); self.list.setMaximumHeight(180)
        for language in owner.track_languages:
            item = QListWidgetItem(language.name); item.setData(Qt.ItemDataRole.UserRole, language.identifier)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable); item.setCheckState(Qt.CheckState.Unchecked); self.list.addItem(item)
        self.all_button, self.none_button = QPushButton(owner.t("select_all")), QPushButton(owner.t("clear_all"))
        self.all_button.clicked.connect(lambda: self._set_all(Qt.CheckState.Checked)); self.none_button.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))
        controls = QHBoxLayout(); controls.addWidget(self.all_button); controls.addWidget(self.none_button); controls.addStretch()
        self.keep_unknown = QCheckBox(owner.t("keep_unknown_languages")); self.keep_unknown.setChecked(True)
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 6, 0, 0); layout.addWidget(self.enabled_check); layout.addWidget(self.list); layout.addLayout(controls); layout.addWidget(self.keep_unknown)
        self.enabled_check.toggled.connect(self._update_enabled); self._update_enabled(False)

    def _set_all(self, state: Qt.CheckState) -> None:
        for index in range(self.list.count()): self.list.item(index).setCheckState(state)

    def _update_enabled(self, enabled: bool) -> None:
        for widget in (self.list, self.all_button, self.none_button, self.keep_unknown): widget.setEnabled(enabled)

    def set_value(self, value: dict) -> None:
        selected = set(value.get("language_ids", [])); self.enabled_check.setChecked(bool(value.get("enabled", False)))
        self.keep_unknown.setChecked(bool(value.get("keep_unknown", True)))
        for index in range(self.list.count()):
            item = self.list.item(index); item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in selected else Qt.CheckState.Unchecked)

    def value(self) -> dict:
        selected = [self.list.item(index).data(Qt.ItemDataRole.UserRole) for index in range(self.list.count()) if self.list.item(index).checkState() == Qt.CheckState.Checked]
        return {"enabled": self.enabled_check.isChecked(), "language_ids": selected, "keep_unknown": self.keep_unknown.isChecked()}


class PresetEditorDialog(QDialog):
    def __init__(self, owner: "MainWindow", preset: Preset | None, existing_names: set[str]) -> None:
        super().__init__(owner)
        self.owner, self.original = owner, preset
        self.existing_names = existing_names
        self.setWindowTitle(owner.t("edit_preset") if preset else owner.t("create_preset"))
        self.setWindowIcon(QIcon(str(ICON_PATH))); self.setModal(True); self.resize(620, 560)

        self.name_edit = QLineEdit(preset.name if preset else "")
        top = QFormLayout(); top.addRow(owner.t("preset_name"), self.name_edit)
        self.tabs = QTabWidget()
        self.language_filters: dict[str, LanguageFilterWidget] = {}
        self.video_tab, self.audio_tab, self.subtitle_tab = QWidget(), QWidget(), QWidget()
        self.video_scroll = QScrollArea(); self.video_scroll.setWidgetResizable(True); self.video_scroll.setWidget(self.video_tab)
        self.tabs.addTab(self.video_scroll, owner.t("video_tracks"))
        self.tabs.addTab(self.audio_tab, owner.t("audio_tracks"))
        self.tabs.addTab(self.subtitle_tab, owner.t("subtitle_tracks"))
        self._build_video_tab(); self._build_audio_tab(); self._build_subtitle_tab()
        self._load_values(preset or Preset("new"))

        save_button = QPushButton(owner.t("save_preset")); cancel_button = QPushButton(owner.t("cancel"))
        set_button_role(save_button, success=True)
        save_button.clicked.connect(self.accept); cancel_button.clicked.connect(self.reject)
        buttons = QHBoxLayout(); buttons.addStretch(); buttons.addWidget(save_button); buttons.addWidget(cancel_button)
        layout = QVBoxLayout(self); layout.addLayout(top); layout.addWidget(self.tabs); layout.addLayout(buttons)

    def _build_video_tab(self) -> None:
        self.copy_video = QCheckBox(self.owner.t("copy_video"))
        self.only_default_video_track = QCheckBox(self.owner.t("only_default_video_track"))
        self.video_settings = VideoSettingsWidget(self.owner.t)
        self.copy_video.toggled.connect(lambda checked: self.video_settings.set_context(True, checked))
        layout = QVBoxLayout(self.video_tab); layout.addWidget(self.copy_video); layout.addWidget(self.only_default_video_track); layout.addWidget(self.video_settings)
        self._add_language_filter("video", layout)

    def _build_audio_tab(self) -> None:
        self.audio_settings = AudioSettingsWidget(self.owner.t)
        layout = QVBoxLayout(self.audio_tab); layout.addWidget(self.audio_settings)
        self._add_language_filter("audio", layout)

    def _build_subtitle_tab(self) -> None:
        self.keep_subtitles = QCheckBox()
        form = QFormLayout(self.subtitle_tab); form.addRow(self.owner.t("keep_subtitles"), self.keep_subtitles)
        self._add_language_filter("subtitle", form)
        self.keep_subtitles.toggled.connect(self.language_filters["subtitle"].setEnabled)
        self.language_filters["subtitle"].setEnabled(self.keep_subtitles.isChecked())

    def _add_language_filter(self, kind: str, layout) -> None:
        language_filter = LanguageFilterWidget(self.owner, kind)
        self.language_filters[kind] = language_filter
        if isinstance(layout, QFormLayout): layout.addRow(language_filter)
        else: layout.addWidget(language_filter)

    def _load_values(self, preset: Preset) -> None:
        video, audio = preset.video, preset.audio
        self.copy_video.setChecked(bool(video.get("copy_video", False))); self.video_settings.load_values(video)
        self.only_default_video_track.setChecked(preset.only_default_video_track)
        self.video_settings.set_context(True, self.copy_video.isChecked())
        self.audio_settings.load_values(audio)
        self.keep_subtitles.setChecked(preset.keep_subtitles)
        for kind, language_filter in self.language_filters.items():
            language_filter.set_value(preset.track_languages[kind])

    def result_preset(self) -> Preset:
        video = self.video_settings.values(); video["copy_video"] = self.copy_video.isChecked()
        filters = {kind: language_filter.value() for kind, language_filter in self.language_filters.items()}
        return Preset(
            self.name_edit.text().strip(), video, self.audio_settings.values(),
            self.keep_subtitles.isChecked(), filters, self.only_default_video_track.isChecked(),
        )

    def accept(self) -> None:
        name = self.name_edit.text().strip(); key = normalized_name(name)
        if not key:
            QMessageBox.warning(self, self.owner.t("error"), self.owner.t("preset_name_required")); return
        if key in self.existing_names:
            QMessageBox.warning(self, self.owner.t("error"), self.owner.t("preset_name_exists")); return
        self.name_edit.setText(name); super().accept()


class PresetManagerDialog(QDialog):
    def __init__(self, owner: "MainWindow", presets: list[Preset], path: Path, selected_name: str) -> None:
        super().__init__(owner)
        self.owner, self.presets, self.path, self.selected_name = owner, list(presets), path, selected_name
        self.setWindowTitle(owner.t("presets")); self.setWindowIcon(QIcon(str(ICON_PATH))); self.setModal(True); self.resize(520, 380)
        self.list = QListWidget(); self.list.itemDoubleClicked.connect(lambda: self.edit_preset())
        self.create_button, self.edit_button = QPushButton(owner.t("create")), QPushButton(owner.t("edit"))
        self.duplicate_button, self.delete_button = QPushButton(owner.t("duplicate")), QPushButton(owner.t("delete"))
        set_button_role(self.delete_button, danger=True)
        self.create_button.clicked.connect(self.create_preset); self.edit_button.clicked.connect(self.edit_preset)
        self.duplicate_button.clicked.connect(self.duplicate_preset); self.delete_button.clicked.connect(self.delete_preset)
        self.list.currentRowChanged.connect(self._update_buttons)
        controls = QHBoxLayout(); controls.addWidget(self.create_button); controls.addWidget(self.edit_button); controls.addWidget(self.duplicate_button); controls.addWidget(self.delete_button); controls.addStretch()
        close_button = QPushButton(owner.t("close")); close_button.clicked.connect(self.accept)
        bottom = QHBoxLayout(); bottom.addStretch(); bottom.addWidget(close_button)
        layout = QVBoxLayout(self); layout.addWidget(self.list); layout.addLayout(controls); layout.addLayout(bottom)
        self._refresh()

    def _refresh(self, selected: str = "") -> None:
        self.list.clear()
        for preset in self.presets: self.list.addItem(preset.name)
        target = next((index for index, preset in enumerate(self.presets) if normalized_name(preset.name) == normalized_name(selected)), -1)
        if target >= 0: self.list.setCurrentRow(target)
        self._update_buttons()

    def _update_buttons(self) -> None:
        enabled = self.list.currentRow() >= 0
        self.edit_button.setEnabled(enabled); self.duplicate_button.setEnabled(enabled); self.delete_button.setEnabled(enabled)

    def _names_except(self, index: int = -1) -> set[str]:
        return {normalized_name(preset.name) for position, preset in enumerate(self.presets) if position != index}

    def _save(self) -> bool:
        try: save_presets(self.path, self.presets); return True
        except OSError as error:
            QMessageBox.critical(self, self.owner.t("error"), self.owner.t("preset_save_error").format(error=error)); return False

    def create_preset(self) -> None:
        editor = PresetEditorDialog(self.owner, None, self._names_except())
        if editor.exec() == QDialog.DialogCode.Accepted:
            preset = editor.result_preset(); self.presets.append(preset)
            if self._save(): self._refresh(preset.name)

    def edit_preset(self) -> None:
        index = self.list.currentRow()
        if index < 0: return
        old_name = self.presets[index].name
        editor = PresetEditorDialog(self.owner, self.presets[index], self._names_except(index))
        if editor.exec() == QDialog.DialogCode.Accepted:
            preset = editor.result_preset(); self.presets[index] = preset
            if normalized_name(self.selected_name) == normalized_name(old_name): self.selected_name = preset.name
            if self._save(): self._refresh(preset.name)

    def duplicate_preset(self) -> None:
        index = self.list.currentRow()
        if index < 0: return
        source = self.presets[index]
        existing_names = self._names_except()
        while True:
            name_dialog = QInputDialog(self)
            name_dialog.setWindowTitle(self.owner.t("duplicate_preset"))
            name_dialog.setLabelText(self.owner.t("duplicate_preset_name").format(name=source.name))
            def style_apply_button() -> None:
                button_box = name_dialog.findChild(QDialogButtonBox)
                if button_box:
                    apply_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
                    if apply_button: set_button_role(apply_button, success=True)
            QTimer.singleShot(0, style_apply_button)
            if name_dialog.exec() != QDialog.DialogCode.Accepted: return
            name = name_dialog.textValue()
            name = name.strip(); key = normalized_name(name)
            if not key:
                QMessageBox.warning(self, self.owner.t("error"), self.owner.t("preset_name_required")); continue
            if key in existing_names:
                QMessageBox.warning(self, self.owner.t("error"), self.owner.t("preset_name_exists")); continue
            duplicate = Preset.from_dict(source.to_dict()); duplicate.name = name
            self.presets.append(duplicate)
            if self._save(): self._refresh(duplicate.name)
            return

    def delete_preset(self) -> None:
        index = self.list.currentRow()
        if index < 0: return
        preset = self.presets[index]
        if not ask_yes_no(self, self.owner.t("delete_preset"), self.owner.t("delete_preset_confirm").format(name=preset.name), self.owner.t): return
        self.presets.pop(index)
        if normalized_name(self.selected_name) == normalized_name(preset.name): self.selected_name = ""
        if self._save(): self._refresh()


class TrackLanguageEditorDialog(QDialog):
    def __init__(self, owner: "MainWindow", language: TrackLanguage | None, existing_names: set[str], empty_alias_in_use: bool = False) -> None:
        super().__init__(owner); self.owner, self.language, self.existing_names, self.empty_alias_in_use = owner, language, existing_names, empty_alias_in_use
        self.setWindowTitle(owner.t("edit_track_language") if language else owner.t("create_track_language")); self.setModal(True)
        self.name_edit = QLineEdit(language.name if language else "")
        self.aliases_edit = QPlainTextEdit("\n".join(language.aliases) if language else "")
        self.aliases_edit.setPlaceholderText(owner.t("track_language_aliases_hint"))
        form = QFormLayout(); form.addRow(owner.t("track_language_name"), self.name_edit); form.addRow(owner.t("track_language_aliases"), self.aliases_edit)
        save_button, cancel_button = QPushButton(owner.t("save_preset")), QPushButton(owner.t("cancel"))
        set_button_role(save_button, success=True)
        save_button.clicked.connect(self.accept); cancel_button.clicked.connect(self.reject)
        buttons = QHBoxLayout(); buttons.addStretch(); buttons.addWidget(save_button); buttons.addWidget(cancel_button)
        layout = QVBoxLayout(self); layout.addLayout(form); layout.addLayout(buttons); self.resize(520, 360)

    def result_language(self) -> TrackLanguage:
        aliases = [value.strip() for line in self.aliases_edit.toPlainText().splitlines() for value in line.split(",") if value.strip()]
        if self.language: return TrackLanguage(self.language.identifier, self.name_edit.text().strip(), list(dict.fromkeys(aliases)))
        return new_language(self.name_edit.text().strip(), list(dict.fromkeys(aliases)))

    def accept(self) -> None:
        name = self.name_edit.text().strip(); aliases = [value.strip() for line in self.aliases_edit.toPlainText().splitlines() for value in line.split(",") if value.strip()]
        if not name or not aliases:
            QMessageBox.warning(self, self.owner.t("error"), self.owner.t("track_language_required")); return
        if normalize(name) in self.existing_names:
            QMessageBox.warning(self, self.owner.t("error"), self.owner.t("track_language_exists")); return
        if self.empty_alias_in_use and any(value.casefold() == EMPTY_ALIAS for value in aliases):
            QMessageBox.warning(self, self.owner.t("error"), self.owner.t("track_language_empty_alias_exists")); return
        super().accept()


class TrackLanguageManagerDialog(QDialog):
    def __init__(self, owner: "MainWindow") -> None:
        super().__init__(owner); self.owner = owner; self.languages = list(owner.track_languages); self.deleted_ids: set[str] = set()
        self.setWindowTitle(owner.t("manage_track_languages")); self.setModal(True); self.resize(620, 520)
        self.list = QListWidget(); self.list.itemDoubleClicked.connect(lambda: self.edit_language())
        self.create_button, self.edit_button, self.delete_button = QPushButton(owner.t("create")), QPushButton(owner.t("edit")), QPushButton(owner.t("delete"))
        self.restore_button = QPushButton(owner.t("restore_track_languages"))
        set_button_role(self.delete_button, danger=True); set_button_role(self.restore_button, danger=True)
        self.create_button.clicked.connect(self.create_language); self.edit_button.clicked.connect(self.edit_language); self.delete_button.clicked.connect(self.delete_language)
        self.restore_button.clicked.connect(self.restore_languages)
        self.list.currentRowChanged.connect(self._update_buttons)
        controls = QHBoxLayout(); controls.addWidget(self.create_button); controls.addWidget(self.edit_button); controls.addWidget(self.delete_button); controls.addStretch(); controls.addWidget(self.restore_button)
        close_button = QPushButton(owner.t("close")); close_button.clicked.connect(self.accept)
        bottom = QHBoxLayout(); bottom.addStretch(); bottom.addWidget(close_button)
        layout = QVBoxLayout(self); layout.addWidget(self.list); layout.addLayout(controls); layout.addLayout(bottom); self._refresh()

    def _refresh(self, identifier: str = "") -> None:
        self.languages.sort(key=lambda language: normalize(language.name)); self.list.clear()
        for language in self.languages:
            item = QListWidgetItem(language.name); item.setData(Qt.ItemDataRole.UserRole, language.identifier); self.list.addItem(item)
            if language.identifier == identifier: self.list.setCurrentItem(item)
        self._update_buttons()

    def _update_buttons(self) -> None:
        enabled = self.list.currentRow() >= 0; self.edit_button.setEnabled(enabled); self.delete_button.setEnabled(enabled)

    def _names_except(self, index: int = -1) -> set[str]:
        return {normalize(language.name) for position, language in enumerate(self.languages) if position != index}

    def _empty_alias_in_use_except(self, index: int = -1) -> bool:
        return any(
            any(alias.casefold() == EMPTY_ALIAS for alias in language.aliases)
            for position, language in enumerate(self.languages) if position != index
        )

    def _save(self) -> bool:
        try: save_languages(self.owner.track_languages_path, self.languages); return True
        except OSError as error:
            QMessageBox.critical(self, self.owner.t("error"), self.owner.t("track_language_save_error").format(error=error)); return False

    def create_language(self) -> None:
        editor = TrackLanguageEditorDialog(self.owner, None, self._names_except(), self._empty_alias_in_use_except())
        if editor.exec() == QDialog.DialogCode.Accepted:
            language = editor.result_language(); self.languages.append(language)
            if self._save(): self._refresh(language.identifier)

    def edit_language(self) -> None:
        index = self.list.currentRow()
        if index < 0: return
        editor = TrackLanguageEditorDialog(self.owner, self.languages[index], self._names_except(index), self._empty_alias_in_use_except(index))
        if editor.exec() == QDialog.DialogCode.Accepted:
            language = editor.result_language(); self.languages[index] = language
            if self._save(): self._refresh(language.identifier)

    def delete_language(self) -> None:
        index = self.list.currentRow()
        if index < 0: return
        language = self.languages[index]
        if not ask_yes_no(self, self.owner.t("delete_track_language"), self.owner.t("delete_track_language_confirm").format(name=language.name), self.owner.t): return
        self.languages.pop(index); self.deleted_ids.add(language.identifier)
        if self._save(): self._refresh()

    def restore_languages(self) -> None:
        if not ask_yes_no(self, self.owner.t("restore_track_languages"), self.owner.t("restore_track_languages_confirm"), self.owner.t): return
        previous_ids = {language.identifier for language in self.languages}
        try:
            restore_user_catalog(self.owner.track_languages_path)
            self.languages = load_languages(self.owner.track_languages_path)
        except OSError as error:
            QMessageBox.critical(self, self.owner.t("error"), self.owner.t("track_language_save_error").format(error=error)); return
        restored_ids = {language.identifier for language in self.languages}
        self.deleted_ids.update(previous_ids - restored_ids); self._refresh()


class BatchWidget(QWidget):
    STATUS_KEYS = {
        PENDING: "batch_pending", CHECKING: "batch_checking", VALID: "batch_valid",
        ERROR: "batch_error", PROCESSING: "batch_processing", COMPLETED: "batch_completed",
        CANCELLED: "batch_cancelled",
    }

    def __init__(self, owner: "MainWindow") -> None:
        super().__init__(); self.owner = owner
        self.items: list[BatchItem] = []
        self.process: QProcess | None = None; self.busy = False
        self.test_process: QProcess | None = None; self.testing = False
        self.test_queue: list[BatchItem] = []; self.test_reserved: set[Path] = set()
        self.test_current: BatchItem | None = None; self.test_done = 0; self.test_total = 0
        self.test_timed_out = False
        self.test_timer = QTimer(self); self.test_timer.setSingleShot(True); self.test_timer.timeout.connect(self._test_timeout)
        self.current_item: BatchItem | None = None
        self.current_media = None; self.current_output: Path | None = None
        self.queue: list[BatchItem] = []; self.queue_reserved: set[Path] = set()
        self.queue_total = 0; self.queue_finished = 0
        self.cancel_requested = False; self.error_dialogs: list[QDialog] = []
        self.row_controls: dict[QWidget, BatchItem] = {}

        self.default_preset = QComboBox()
        self.apply_preset_to_all_button = QPushButton(); set_button_role(self.apply_preset_to_all_button, success=True)
        self.default_preset.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.apply_preset_to_all_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.same_source_directory = QCheckBox()
        self.same_source_directory.setChecked(True)
        self.output_directory = QLineEdit(); self.output_directory_button = QPushButton()
        self.output_format = QComboBox()
        for extension in (".mkv", ".mp4", ".avi"): self.output_format.addItem("", extension)
        self.hardware = QCheckBox(); self.hardware.setChecked(owner.hardware_check.isChecked())
        self.default_preset_label, self.output_directory_label, self.output_format_label, self.engine_label = QLabel(), QLabel(), QLabel(), QLabel()
        preset_row = QHBoxLayout(); preset_row.addWidget(self.default_preset); preset_row.addWidget(self.apply_preset_to_all_button)
        output_row = QHBoxLayout(); output_row.addWidget(self.output_directory); output_row.addWidget(self.output_directory_button)
        form = QFormLayout(); form.addRow(self.default_preset_label, preset_row); form.addRow(self.same_source_directory)
        form.addRow(self.output_directory_label, output_row); form.addRow(self.output_format_label, self.output_format); form.addRow(self.engine_label, self.hardware)

        self.table = QTableWidget(0, 4)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader(); header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents); header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed); header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._update_selection_buttons)

        self.select_files_button, self.load_button, self.save_button = QPushButton(), QPushButton(), QPushButton()
        self.remove_button, self.up_button, self.down_button, self.retry_button = QPushButton(), QPushButton(), QPushButton(), QPushButton()
        self.source_folder_button, self.destination_folder_button = QPushButton(), QPushButton()
        self.up_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp))
        self.down_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown))
        self.test_button, self.process_button = QPushButton(), QPushButton()
        set_button_role(self.save_button, success=True); set_button_role(self.remove_button, danger=True)
        set_button_role(self.test_button); set_button_role(self.process_button, execution=True)
        self.select_files_button.clicked.connect(self.select_files); self.load_button.clicked.connect(self.load_job); self.save_button.clicked.connect(self.save_job)
        self.apply_preset_to_all_button.clicked.connect(self.apply_preset_to_all)
        self.source_folder_button.clicked.connect(self.open_source_folder); self.destination_folder_button.clicked.connect(self.open_destination_folder)
        self.remove_button.clicked.connect(self.remove_selected); self.up_button.clicked.connect(lambda: self.move_selected(-1)); self.down_button.clicked.connect(lambda: self.move_selected(1)); self.retry_button.clicked.connect(self.retry_selected)
        self.test_button.clicked.connect(self.test_items); self.process_button.clicked.connect(self.toggle_processing)
        list_controls = QHBoxLayout()
        for button in (self.select_files_button, self.remove_button, self.retry_button): list_controls.addWidget(button)
        list_controls.addStretch(); list_controls.addWidget(self.source_folder_button); list_controls.addWidget(self.destination_folder_button)
        list_controls.addStretch(); list_controls.addWidget(self.load_button); list_controls.addWidget(self.save_button)
        arrow_controls = QVBoxLayout(); arrow_controls.addStretch(); arrow_controls.addWidget(self.up_button); arrow_controls.addWidget(self.down_button); arrow_controls.addStretch()
        table_row = QHBoxLayout(); table_row.addWidget(self.table); table_row.addLayout(arrow_controls)
        action_controls = QHBoxLayout(); action_controls.addStretch(); action_controls.addWidget(self.test_button); action_controls.addWidget(self.process_button)
        self.file_progress = QProgressBar(); self.file_progress.setValue(0); self.file_progress.setFormat("%p%")
        self.total_progress = QProgressBar(); self.total_progress.setProperty("scope", "total"); self.total_progress.setValue(0); self.total_progress.setFormat("%p%")
        self.file_progress_label, self.total_progress_label = QLabel(), QLabel()
        progress_form = QFormLayout(); progress_form.addRow(self.file_progress_label, self.file_progress); progress_form.addRow(self.total_progress_label, self.total_progress)
        self.summary = QLabel()
        layout = QVBoxLayout(self); layout.addLayout(form); layout.addLayout(table_row); layout.addLayout(list_controls); layout.addLayout(progress_form); layout.addWidget(self.summary); layout.addLayout(action_controls)

        self.same_source_directory.toggled.connect(self._output_mode_changed)
        self.default_preset.currentIndexChanged.connect(self._update_apply_button)
        self.output_directory_button.clicked.connect(self.choose_output_directory)
        self.output_directory.editingFinished.connect(self.options_changed)
        self.output_format.currentIndexChanged.connect(self.options_changed)
        self.hardware.toggled.connect(self._hardware_changed)
        self.refresh_presets(); self._output_mode_changed(True); self.retranslate(); self._update_selection_buttons(); self.update_summary()

    def retranslate(self) -> None:
        t = self.owner.t
        self.default_preset_label.setText(t("batch_default_preset")); self.same_source_directory.setText(t("batch_same_source_directory"))
        self.apply_preset_to_all_button.setText(t("batch_apply_to_all"))
        self.output_directory_label.setText(t("output_dir")); self.output_directory_button.setText(t("browse")); self.output_format_label.setText(t("output_format")); self.engine_label.setText(t("engine")); self.hardware.setText(t("use_hardware"))
        self.select_files_button.setText(t("batch_select_files")); self.load_button.setText(t("batch_load_job")); self.save_button.setText(t("batch_save_job"))
        self.remove_button.setText(t("batch_remove_files")); self.up_button.setToolTip(t("up")); self.down_button.setToolTip(t("down")); self.retry_button.setText(t("batch_retry"))
        self.source_folder_button.setText(t("batch_source_folder")); self.destination_folder_button.setText(t("batch_destination_folder"))
        self.test_button.setText(t("cancel") if self.testing else t("batch_test")); self.process_button.setText(t("stop") if self.busy and not self.testing else t("batch_process"))
        self.file_progress_label.setText(t("batch_file_progress")); self.total_progress_label.setText(t("batch_total_progress"))
        self.table.setHorizontalHeaderLabels((t("batch_source_file"), t("preset"), t("batch_status"), t("batch_details")))
        status_texts = [t("batch_status"), *(t(key) for key in self.STATUS_KEYS.values())]
        status_width = max(self.table.fontMetrics().horizontalAdvance(value) for value in status_texts) + 32
        self.table.horizontalHeader().resizeSection(2, status_width)
        for value, key in ((".mkv", "format_mkv"), (".mp4", "format_mp4"), (".avi", "format_avi")):
            self.output_format.setItemText(self.output_format.findData(value), t(key))
        self.refresh_presets(); self.refresh_table(); self.update_summary()

    def settings_value(self) -> BatchSettings:
        return BatchSettings(
            default_preset=str(self.default_preset.currentData() or ""),
            same_source_directory=self.same_source_directory.isChecked(),
            output_directory=self.output_directory.text().strip(),
            output_format=str(self.output_format.currentData() or ".mkv"),
            use_hardware=self.hardware.isChecked(),
        )

    def load_settings(self, settings: BatchSettings) -> None:
        self.same_source_directory.blockSignals(True); self.same_source_directory.setChecked(settings.same_source_directory); self.same_source_directory.blockSignals(False)
        self.output_directory.setText(settings.output_directory)
        self.output_format.blockSignals(True); index = self.output_format.findData(settings.output_format); self.output_format.setCurrentIndex(max(0, index)); self.output_format.blockSignals(False)
        self.hardware.blockSignals(True); self.hardware.setChecked(settings.use_hardware); self.hardware.blockSignals(False)
        self.owner.hardware_check.setChecked(settings.use_hardware)
        self.refresh_presets(settings.default_preset); self._output_mode_changed(settings.same_source_directory, reset=False)

    def refresh_presets(self, selected: str | None = None) -> None:
        if selected is None: selected = str(self.default_preset.currentData() or "")
        self.default_preset.blockSignals(True); self.default_preset.clear()
        if selected and find_preset(self.owner.presets, selected) is None:
            self.default_preset.addItem(self.owner.t("batch_missing_preset").format(name=selected), selected)
        for preset in self.owner.presets: self.default_preset.addItem(preset.name, preset.name)
        index = self.default_preset.findData(selected); self.default_preset.setCurrentIndex(index if index >= 0 else (0 if self.default_preset.count() else -1)); self.default_preset.blockSignals(False)
        self._update_apply_button()
        if hasattr(self, "table"): self.refresh_table()

    def _preset_combo(self, item: BatchItem) -> QComboBox:
        combo = QComboBox(); preset = find_preset(self.owner.presets, item.preset_name)
        if preset is None and item.preset_name:
            combo.addItem(self.owner.t("batch_missing_preset").format(name=item.preset_name), "")
        for available in self.owner.presets: combo.addItem(available.name, available.name)
        index = combo.findData(item.preset_name); combo.setCurrentIndex(index if index >= 0 else 0)
        combo.currentIndexChanged.connect(lambda _index, selected=item, editor=combo: self._row_preset_changed(selected, editor))
        combo.setEnabled(not self.busy)
        self.row_controls[combo] = item; combo.installEventFilter(self)
        return combo

    def refresh_table(self) -> None:
        selected_items = {id(self.items[row]) for row in self.selected_rows() if row < len(self.items)} if self.table.rowCount() else set()
        self.row_controls.clear()
        self.table.blockSignals(True); self.table.setRowCount(len(self.items))
        theme = self.owner.themes.get(getattr(self.owner, "theme", "default"))
        processing_color = QColor(theme.colors.get("processing_row", "#dce8f6")) if theme else QColor("#dce8f6")
        for row, item in enumerate(self.items):
            processing = item.status == PROCESSING
            source_item = QTableWidgetItem(Path(item.source).name); source_item.setToolTip(item.source); self.table.setItem(row, 0, source_item)
            preset_combo = self._preset_combo(item); preset_combo.setProperty("batchProcessing", processing); self.table.setCellWidget(row, 1, preset_combo)
            status_item = QTableWidgetItem(self.owner.t(self.STATUS_KEYS[item.status])); self.table.setItem(row, 2, status_item)
            if processing:
                source_item.setBackground(QBrush(processing_color)); status_item.setBackground(QBrush(processing_color))
            details = QPushButton(self.owner.t("batch_view_details")); details.setEnabled(bool(item.error or item.output_path)); details.clicked.connect(lambda _checked=False, selected=item: self.show_details(selected)); self.table.setCellWidget(row, 3, details)
            self.row_controls[details] = item; details.installEventFilter(self)
            if id(item) in selected_items:
                self.table.selectionModel().select(self.table.model().index(row, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        self.table.blockSignals(False); self._update_selection_buttons(); self._update_apply_button(); self.update_summary()

    def eventFilter(self, watched, event) -> bool:
        item = self.row_controls.get(watched)
        if item is not None and event.type() in {QEvent.Type.MouseButtonPress, QEvent.Type.FocusIn}:
            self._select_item(item)
        return super().eventFilter(watched, event)

    def _select_item(self, item: BatchItem) -> None:
        try: row = next(index for index, candidate in enumerate(self.items) if candidate is item)
        except StopIteration: return
        if row not in self.selected_rows():
            self.table.clearSelection()
            self.table.selectionModel().select(self.table.model().index(row, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)

    def _update_apply_button(self, *_args) -> None:
        preset = find_preset(self.owner.presets, str(self.default_preset.currentData() or ""))
        self.apply_preset_to_all_button.setEnabled(bool(self.items) and preset is not None and not self.busy)

    def selected_rows(self) -> list[int]:
        return sorted({index.row() for index in self.table.selectionModel().selectedRows()})

    def _update_selection_buttons(self) -> None:
        rows = self.selected_rows(); enabled = bool(rows) and not self.busy
        self.remove_button.setEnabled(enabled); self.retry_button.setEnabled(enabled)
        single = len(rows) == 1
        self.source_folder_button.setEnabled(single); self.destination_folder_button.setEnabled(single)
        self.up_button.setEnabled(enabled and min(rows, default=0) > 0)
        self.down_button.setEnabled(enabled and max(rows, default=-1) < len(self.items) - 1)

    def _require_presets(self) -> bool:
        if self.owner.presets: return True
        QMessageBox.warning(self, self.owner.t("error"), self.owner.t("batch_no_presets")); return False

    def select_files(self) -> None:
        if not self._require_presets(): return
        filenames, _ = QFileDialog.getOpenFileNames(self, self.owner.t("batch_select_files"), "", self.owner.t("file_filter"))
        if not filenames: return
        preset = find_preset(self.owner.presets, str(self.default_preset.currentData() or ""))
        if preset is None:
            QMessageBox.warning(self, self.owner.t("error"), self.owner.t("batch_select_preset")); return
        existing = {str(Path(item.source).resolve()) for item in self.items}
        for filename in filenames:
            source = str(Path(filename).resolve())
            if source not in existing:
                self.items.append(BatchItem(source, preset.name)); existing.add(source)
        self.refresh_table()

    def _row_preset_changed(self, item: BatchItem, combo: QComboBox) -> None:
        name = str(combo.currentData() or ""); preset = find_preset(self.owner.presets, name)
        if preset is None: return
        item.preset_name = preset.name
        item.status = PENDING; item.error = ""; item.output_path = ""; self.refresh_table()

    def apply_preset_to_all(self) -> None:
        preset = find_preset(self.owner.presets, str(self.default_preset.currentData() or ""))
        if preset is None:
            QMessageBox.warning(self, self.owner.t("error"), self.owner.t("batch_select_preset")); return
        for item in self.items:
            item.preset_name = preset.name
            item.status = PENDING; item.error = ""; item.output_path = ""
        self.refresh_table()

    def choose_output_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, self.owner.t("output_dir"), self.output_directory.text())
        if directory: self.output_directory.setText(directory); self.options_changed()

    def _output_mode_changed(self, checked: bool, reset: bool = True) -> None:
        self.output_directory.setEnabled(not checked); self.output_directory_button.setEnabled(not checked)
        if reset: self.options_changed()

    def _hardware_changed(self, checked: bool) -> None:
        if self.owner.hardware_check.isChecked() != checked: self.owner.hardware_check.setChecked(checked)
        self.options_changed()

    def set_hardware(self, checked: bool) -> None:
        changed = self.hardware.isChecked() != checked
        self.hardware.blockSignals(True); self.hardware.setChecked(checked); self.hardware.blockSignals(False)
        if changed: self.options_changed()

    def options_changed(self) -> None:
        if self.busy: return
        for item in self.items:
            if item.status != COMPLETED:
                item.status = PENDING; item.error = ""; item.output_path = ""
        self.refresh_table()

    def remove_selected(self) -> None:
        rows = self.selected_rows()
        if not rows or not ask_yes_no(self, self.owner.t("batch_remove_files"), self.owner.t("batch_remove_confirm").format(count=len(rows)), self.owner.t): return
        self.table.clearSelection()
        for row in reversed(rows): self.items.pop(row)
        self.refresh_table()

    def move_selected(self, direction: int) -> None:
        rows = self.selected_rows()
        if not rows: return
        selected = set(rows); order = rows if direction < 0 else list(reversed(rows))
        for row in order:
            target = row + direction
            if 0 <= target < len(self.items) and target not in selected:
                self.items[row], self.items[target] = self.items[target], self.items[row]
                selected.remove(row); selected.add(target)
        self.refresh_table(); self.table.clearSelection()
        for row in sorted(selected):
            self.table.selectionModel().select(self.table.model().index(row, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)

    def retry_selected(self) -> None:
        for row in self.selected_rows():
            item = self.items[row]; item.status = PENDING; item.error = ""; item.output_path = ""
        self.refresh_table()

    def _selected_item(self) -> BatchItem | None:
        rows = self.selected_rows()
        return self.items[rows[0]] if len(rows) == 1 and rows[0] < len(self.items) else None

    def _open_directory(self, directory: Path) -> None:
        directory = directory.expanduser().resolve()
        if not directory.is_dir():
            QMessageBox.warning(self, self.owner.t("error"), self.owner.t("batch_folder_unavailable").format(directory=directory)); return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory))):
            QMessageBox.warning(self, self.owner.t("error"), self.owner.t("batch_folder_open_error").format(directory=directory))

    def open_source_folder(self) -> None:
        item = self._selected_item()
        if item: self._open_directory(Path(item.source).parent)

    def open_destination_folder(self) -> None:
        item = self._selected_item()
        if not item: return
        if item.output_path:
            directory = Path(item.output_path).parent
        elif self.same_source_directory.isChecked():
            directory = Path(item.source).parent
        elif self.output_directory.text().strip():
            directory = Path(self.output_directory.text().strip())
        else:
            QMessageBox.warning(self, self.owner.t("error"), self.owner.t("batch_validation_no_output")); return
        self._open_directory(directory)

    def save_job(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(self, self.owner.t("batch_save_job"), "", self.owner.t("batch_job_filter"))
        if not filename: return
        path = Path(filename)
        if not path.name.lower().endswith(".vgbatch.json"): path = path.with_name(path.name + ".vgbatch.json")
        try: save_batch_job(path, self.settings_value(), self.items)
        except OSError as error: QMessageBox.critical(self, self.owner.t("error"), self.owner.t("batch_save_error").format(error=error))

    def load_job(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, self.owner.t("batch_load_job"), "", self.owner.t("batch_job_filter"))
        if not filename: return
        if self.items and not ask_yes_no(self, self.owner.t("batch_load_job"), self.owner.t("batch_replace_confirm"), self.owner.t): return
        try: settings, items = load_batch_job(Path(filename), self.owner.t)
        except (OSError, TypeError, ValueError, KeyError) as error:
            QMessageBox.critical(self, self.owner.t("error"), self.owner.t("batch_load_error").format(error=error)); return
        self.items = items; self.load_settings(settings); self.refresh_table()

    def test_items(self) -> None:
        if self.testing:
            self.cancel_testing(); return
        if not self.items: QMessageBox.warning(self, self.owner.t("error"), self.owner.t("batch_empty")); return
        if not self._require_presets(): return
        self.testing = True
        self.set_busy(True, can_stop=False)
        self.test_button.setText(self.owner.t("cancel")); self.test_button.setEnabled(True)
        set_button_role(self.test_button, danger=True)
        self.test_queue = [item for item in self.items if item.status != COMPLETED]
        self.test_reserved = {Path(item.output_path) for item in self.items if item.status == COMPLETED and item.output_path}
        self.test_total = len(self.test_queue); self.test_done = 0
        self.total_progress.setValue(0); self.total_progress.setFormat("%p%"); self._start_next_test()

    def _update_item_row(self, item: BatchItem) -> None:
        try: row = next(index for index, candidate in enumerate(self.items) if candidate is item)
        except StopIteration: return
        status = self.table.item(row, 2)
        if status: status.setText(self.owner.t(self.STATUS_KEYS[item.status]))
        details = self.table.cellWidget(row, 3)
        if details: details.setEnabled(bool(item.error or item.output_path))
        self.update_summary()

    def _start_next_test(self) -> None:
        if not self.testing: return
        if not self.test_queue:
            self._finish_testing(); return
        item = self.test_queue.pop(0); self.test_current = item
        item.status = CHECKING; item.error = ""; item.output_path = ""; self._update_item_row(item)
        path = Path(item.source).expanduser().resolve()
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            self._complete_test_error(self.owner.t("media_unsupported_format")); return
        if not path.is_file():
            self._complete_test_error(self.owner.t("media_file_missing").format(path=path)); return
        process = QProcess(self); self.test_process = process; self.test_timed_out = False
        process.setProgram("ffprobe")
        process.setArguments(["-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)])
        process.finished.connect(self._test_finished); process.errorOccurred.connect(self._test_process_error)
        process.start(); self.test_timer.start(PROBE_TIMEOUT_SECONDS * 1000)

    def _test_timeout(self) -> None:
        if self.test_process:
            self.test_timed_out = True; self.test_process.kill()

    def _test_process_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self.test_timer.stop(); self._complete_test_error(self.owner.t("media_ffprobe_missing"))

    def _test_finished(self, exit_code: int, _exit_status=QProcess.ExitStatus.NormalExit) -> None:
        if not self.testing or not self.test_current: return
        self.test_timer.stop(); process = self.test_process; self.test_process = None
        if self.test_timed_out:
            detail = f"timeout ({PROBE_TIMEOUT_SECONDS} s)"
            self._complete_test_error(self.owner.t("media_probe_failed").format(detail=detail)); return
        stderr = bytes(process.readAllStandardError()).decode(errors="replace").strip() if process else ""
        if exit_code != 0:
            self._complete_test_error(self.owner.t("media_probe_failed").format(detail=stderr or f"ffprobe: {exit_code}")); return
        try:
            output = bytes(process.readAllStandardOutput()).decode(errors="replace") if process else ""
            media = media_from_probe_output(Path(self.test_current.source), output, self.owner.t)
            _media, _configs, destination = validate_batch_media(
                self.test_current, media, self.owner.presets, self.owner.track_languages,
                self.settings_value(), self.test_reserved, self.owner.t,
            )
            self.test_current.status = VALID; self.test_current.output_path = str(destination); self.test_reserved.add(destination)
        except Exception as error:
            self.test_current.status = ERROR; self.test_current.error = str(error)
        self._complete_test_item()

    def _complete_test_error(self, message: str) -> None:
        if not self.testing or not self.test_current: return
        self.test_current.status = ERROR; self.test_current.error = message; self._complete_test_item()

    def _complete_test_item(self) -> None:
        if self.test_current: self._update_item_row(self.test_current)
        self.test_done += 1
        self.total_progress.setValue(round(self.test_done / self.test_total * 100) if self.test_total else 100)
        self.test_current = None; QTimer.singleShot(0, self._start_next_test)

    def cancel_testing(self) -> None:
        if not self.testing: return
        self.testing = False; self.test_timer.stop()
        if self.test_current and self.test_current.status == CHECKING:
            self.test_current.status = PENDING; self._update_item_row(self.test_current)
        if self.test_process: self.test_process.kill(); self.test_process = None
        self.test_queue.clear(); self._finish_testing(cancelled=True)

    def _finish_testing(self, cancelled: bool = False) -> None:
        self.testing = False; self.test_process = None; self.test_current = None
        self.set_busy(False); self.test_button.setText(self.owner.t("batch_test")); set_button_role(self.test_button)
        self.update_summary()
        if not cancelled and any(item.status == ERROR for item in self.items):
            QMessageBox.warning(self, self.owner.t("batch_test_errors_title"), self.owner.t("batch_test_errors_message"))

    def start_processing(self) -> None:
        if not self.items: QMessageBox.warning(self, self.owner.t("error"), self.owner.t("batch_empty")); return
        if not self._require_presets(): return
        eligible = [item for item in self.items if item.status in {PENDING, VALID, CANCELLED}]
        if not eligible: return
        self.set_busy(True, can_stop=False)
        self.file_progress.setValue(0); self.file_progress.setFormat("%p%")
        self.total_progress.setValue(0); self.total_progress.setFormat("%p%")
        self.queue = eligible
        self.queue_reserved = {Path(item.output_path) for item in self.items if item.status == COMPLETED and item.output_path}
        self.queue_total = len(self.queue); self.queue_finished = 0
        self.cancel_requested = False; self._start_next()

    def _start_next(self) -> None:
        if not self.queue:
            self.process = None; self.current_item = None; self.current_media = None; self.current_output = None
            self.set_busy(False); self.file_progress.setValue(100); self.total_progress.setValue(100); self.refresh_table(); self.update_summary()
            QMessageBox.information(self, self.owner.t("processing_complete"), self.owner.t("processing_complete")); return
        item = self.queue.pop(0)
        try:
            media, configs, output = validate_batch_item(
                item, self.owner.presets, self.owner.track_languages,
                self.settings_value(), self.queue_reserved, self.owner.t,
            )
            self.queue_reserved.add(output)
        except Exception as error:
            item.status = ERROR; item.error = str(error); item.output_path = ""
            self.queue_finished += 1; self.refresh_table(); self.update_summary()
            QTimer.singleShot(0, self._start_next); return
        item.status = PROCESSING; item.error = ""; self.current_item, self.current_media, self.current_output = item, media, output
        command = build_project_command(media.path, output, configs, EncodingOptions(hardware="nvidia" if self.hardware.isChecked() else "cpu"))
        self.process = QProcess(self); self.process.setProgram(command[0]); self.process.setArguments(command[1:]); self.process.setProperty("last_error", "")
        self.process.readyReadStandardOutput.connect(self._read_progress); self.process.readyReadStandardError.connect(self._read_error); self.process.finished.connect(self._process_finished)
        self.process.errorOccurred.connect(self._process_error)
        self.file_progress.setValue(0); self.file_progress.setFormat("%p% · --"); self._update_total_progress(0)
        self.process_button.setEnabled(True); self.refresh_table(); self.process.start()

    def _read_progress(self) -> None:
        if not self.process or not self.current_media or self.current_media.duration <= 0: return
        buffer = str(self.process.property("progress_buffer") or "") + bytes(self.process.readAllStandardOutput()).decode(errors="replace")
        lines = buffer.split("\n"); self.process.setProperty("progress_buffer", lines.pop())
        speed = str(self.process.property("speed") or "--")
        for line in lines:
            if line.startswith("out_time_us="):
                percent = min(100, round(int(line.partition("=")[2] or 0) / 1_000_000 / self.current_media.duration * 100))
                self.file_progress.setValue(percent); self._update_total_progress(percent)
            elif line.startswith("speed=") and line.partition("=")[2].strip() not in {"", "N/A"}: speed = line.partition("=")[2].strip()
        self.process.setProperty("speed", speed); self.file_progress.setFormat(f"%p% · {speed}")

    def _update_total_progress(self, current_percent: int) -> None:
        if self.queue_total:
            total = round((self.queue_finished + current_percent / 100) / self.queue_total * 100)
            self.total_progress.setValue(min(100, total))
            self.total_progress.setFormat(self.owner.t("batch_total_progress_format").format(done=self.queue_finished, total=self.queue_total, percent="%p%"))

    def _read_error(self) -> None:
        if self.process: self.process.setProperty("last_error", str(self.process.property("last_error") or "") + bytes(self.process.readAllStandardError()).decode(errors="replace"))

    def _process_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart and self.process:
            process = self.process
            QTimer.singleShot(0, lambda: self._process_finished(-1) if self.process is process else None)

    def _process_finished(self, exit_code: int) -> None:
        if not self.current_item: return
        error = str(self.process.property("last_error") or "") if self.process else ""
        if self.cancel_requested:
            if self.current_output: self.current_output.unlink(missing_ok=True)
            self.current_item.status = CANCELLED; self.current_item.error = self.owner.t("batch_cancelled_detail"); self.current_item.output_path = ""
            self.file_progress.setValue(0); self.file_progress.setFormat("%p%")
            self._update_total_progress(0)
            self.queue.clear(); self.process = None; self.set_busy(False)
        elif exit_code == 0:
            self.current_item.status = COMPLETED; self.current_item.output_path = str(self.current_output or ""); self.queue_finished += 1; self.process = None; self._start_next()
        else:
            if self.current_output: self.current_output.unlink(missing_ok=True)
            self.current_item.status = ERROR; self.current_item.error = error or self.owner.t("batch_ffmpeg_error").format(code=exit_code); self.current_item.output_path = ""; self.queue_finished += 1
            self.process = None; self._start_next()
        self.refresh_table()

    def stop_processing(self) -> None:
        if not self.process or not ask_yes_no(self, self.owner.t("stop_title"), self.owner.t("batch_stop_confirm"), self.owner.t): return
        self.cancel_requested = True; self.process_button.setEnabled(False); self.process.kill()

    def toggle_processing(self) -> None:
        if self.busy: self.stop_processing()
        else: self.start_processing()

    def show_details(self, item: BatchItem) -> None:
        dialog = QDialog(self); dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose); dialog.setWindowTitle(self.owner.t("batch_details")); dialog.resize(620, 320)
        details = QPlainTextEdit(); details.setReadOnly(True)
        values = [f"{self.owner.t('batch_source_file')}: {item.source}", f"{self.owner.t('preset')}: {item.preset_name}", f"{self.owner.t('batch_status')}: {self.owner.t(self.STATUS_KEYS[item.status])}"]
        if item.output_path: values.append(f"{self.owner.t('batch_output_file')}: {item.output_path}")
        if item.error: values += ["", item.error]
        details.setPlainText("\n".join(values)); close = QPushButton(self.owner.t("close")); close.clicked.connect(dialog.close)
        buttons = QHBoxLayout(); buttons.addStretch(); buttons.addWidget(close); layout = QVBoxLayout(dialog); layout.addWidget(details); layout.addLayout(buttons)
        self.error_dialogs.append(dialog); dialog.destroyed.connect(lambda: self.error_dialogs.remove(dialog) if dialog in self.error_dialogs else None); dialog.show()

    def update_summary(self) -> None:
        counts = {status: sum(item.status == status for item in self.items) for status in self.STATUS_KEYS}
        parts = [f"{self.owner.t(self.STATUS_KEYS[status])}: {count}" for status, count in counts.items() if count]
        self.summary.setText(" · ".join(parts) if parts else self.owner.t("batch_empty_summary"))

    def set_busy(self, busy: bool, can_stop: bool = False) -> None:
        self.busy = busy
        for widget in (self.default_preset, self.apply_preset_to_all_button, self.same_source_directory, self.output_directory, self.output_directory_button, self.output_format, self.hardware, self.select_files_button, self.load_button, self.save_button, self.remove_button, self.up_button, self.down_button, self.retry_button, self.test_button):
            widget.setEnabled(not busy)
        for row in range(self.table.rowCount()):
            editor = self.table.cellWidget(row, 1)
            if editor: editor.setEnabled(not busy)
        self.process_button.setText(self.owner.t("stop") if busy else self.owner.t("batch_process"))
        self.process_button.setEnabled(not busy or can_stop)
        set_button_role(self.process_button, danger=busy, execution=not busy)
        self._update_selection_buttons()
        if not busy: self._update_apply_button()
        self.owner.mode_tabs.setTabEnabled(0, not busy); self.owner.application_menu.setEnabled(not busy)
        if not busy: self._output_mode_changed(self.same_source_directory.isChecked(), reset=False)

    def is_processing(self) -> bool:
        return self.busy


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__(); self.settings = QSettings("VideoGUI", "VideoGUI")
        self.presets_path = Path(self.settings.fileName()).parent / "presets.json"
        self.track_languages_path = Path(self.settings.fileName()).parent / "track_languages.json"
        self.track_languages = load_languages(self.track_languages_path)
        self.presets = load_presets(self.presets_path)
        self.selected_preset_name = str(self.settings.value("selected_preset", ""))
        self.languages, self.themes = discover_languages(), discover_themes()
        saved_language = str(self.settings.value("language", "es"))
        self.language = saved_language if saved_language in self.languages else "es" if "es" in self.languages else next(iter(self.languages), "")
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.media, self.process, self.output_path, self.progress_buffer = None, None, None, ""
        self.source_edit = QLineEdit(); self.source_edit.setReadOnly(True); self.open_button = QPushButton()
        self.output_dir_edit = QLineEdit(str(self.settings.value("output_directory", ""))); self.output_dir_button = QPushButton(); self.output_name_edit = QLineEdit()
        self.output_format_combo = QComboBox()
        for extension in (".mkv", ".mp4", ".avi"): self.output_format_combo.addItem("", extension)
        saved_format = str(self.settings.value("output_format", ".mkv")); self.output_format_combo.setCurrentIndex(max(0, self.output_format_combo.findData(saved_format)))
        self.hardware_check = QCheckBox()
        self.defaults_button, self.convert_button = QPushButton(), QPushButton()
        set_button_role(self.convert_button, execution=True)
        self.progress, self.status = QProgressBar(), QLabel()
        self.video_panel, self.audio_panel, self.subtitle_panel = TrackPanel("video", self), TrackPanel("audio", self), TrackPanel("subtitle", self)
        self.video_panel.changed.connect(lambda: self.save_panel_encoding_preferences(self.video_panel))
        self.audio_panel.changed.connect(lambda: self.save_panel_encoding_preferences(self.audio_panel))
        for panel in (self.video_panel, self.audio_panel, self.subtitle_panel): panel.changed.connect(self.update_preset_selection_from_tracks)
        self.track_tabs = QTabWidget(); self.track_tabs.addTab(self.video_panel, ""); self.track_tabs.addTab(self.audio_panel, ""); self.track_tabs.addTab(self.subtitle_panel, "")
        form = QFormLayout(); self.preset_combo = QComboBox(); self.refresh_preset_combo(self.selected_preset_name)
        self.preset_combo.currentIndexChanged.connect(self.preset_selected)
        source_row = QHBoxLayout(); source_row.addWidget(self.source_edit); source_row.addWidget(self.open_button)
        output_row = QHBoxLayout(); output_row.addWidget(self.output_dir_edit); output_row.addWidget(self.output_dir_button)
        self.preset_label, self.source_label, self.output_dir_label, self.output_format_label, self.output_name_label = QLabel(), QLabel(), QLabel(), QLabel(), QLabel()
        self.engine_label = QLabel()
        form.addRow(self.preset_label, self.preset_combo); form.addRow(self.source_label, source_row); form.addRow(self.output_dir_label, output_row); form.addRow(self.output_format_label, self.output_format_combo); form.addRow(self.output_name_label, self.output_name_edit); form.addRow(self.engine_label, self.hardware_check)
        buttons = QHBoxLayout(); buttons.addWidget(self.defaults_button); buttons.addStretch(); buttons.addWidget(self.convert_button)
        single = QWidget(); layout = QVBoxLayout(single); layout.addLayout(form); layout.addWidget(self.track_tabs); layout.addWidget(self.progress); layout.addWidget(self.status); layout.addLayout(buttons)
        self.batch_widget = BatchWidget(self)
        self.mode_tabs = QTabWidget(); self.mode_tabs.addTab(single, ""); self.mode_tabs.addTab(self.batch_widget, "")
        saved_mode = self.settings.value("window/active_mode", 0, type=int)
        self.mode_tabs.setCurrentIndex(saved_mode if 0 <= saved_mode < self.mode_tabs.count() else 0)
        self.mode_tabs.currentChanged.connect(self.mode_changed)
        central = QWidget(); central_layout = QVBoxLayout(central); central_layout.addWidget(self.mode_tabs); self.setCentralWidget(central)
        self.open_button.clicked.connect(self.open_file); self.output_dir_button.clicked.connect(self.choose_output_directory); self.output_dir_edit.editingFinished.connect(self.remember_output_directory)
        self.output_format_combo.currentIndexChanged.connect(self.output_format_changed); self.output_name_edit.editingFinished.connect(self.output_name_finished)
        self.defaults_button.clicked.connect(self.restore_defaults); self.convert_button.clicked.connect(self.toggle_conversion)
        self.build_menus()
        self.convert_button.setEnabled(False); self.resize(980, 720)
        self.set_language(str(self.language)); self.set_theme(str(self.settings.value("theme", "default")))
        saved_hardware = self.settings.value("encoding/use_hardware", None)
        if saved_hardware is None:
            saved_hardware = self.settings.value("encoding/engine", "nvidia") == "nvidia"
        self.hardware_check.setChecked(bool(saved_hardware) if isinstance(saved_hardware, bool) else str(saved_hardware).lower() == "true")
        self.batch_widget.set_hardware(self.hardware_check.isChecked())
        self.hardware_check.toggled.connect(self.save_hardware_preference)
        self.restore_window_settings()

    def t(self, key: str) -> str: return text(self.languages, self.language, key)

    def retranslate(self) -> None:
        self.setWindowTitle(self.t("title")); self.open_button.setText(self.t("open")); self.output_dir_button.setText(self.t("browse")); self.defaults_button.setText(self.t("defaults")); self.convert_button.setText(self.t("stop") if self.process else self.t("convert")); self.hardware_check.setText(self.t("use_hardware"))
        for label, key in ((self.preset_label, "preset"), (self.source_label, "source"), (self.output_dir_label, "output_dir"), (self.output_format_label, "output_format"), (self.output_name_label, "output_name"), (self.engine_label, "engine")): label.setText(self.t(key))
        self.mode_tabs.setTabText(0, self.t("single")); self.mode_tabs.setTabText(1, self.t("batch")); self.batch_widget.retranslate()
        for value, key in ((".mkv", "format_mkv"), (".mp4", "format_mp4"), (".avi", "format_avi")):
            self.output_format_combo.setItemText(self.output_format_combo.findData(value), self.t(key))
        for index, key in enumerate(("video_tracks", "audio_tracks", "subtitle_tracks")): self.track_tabs.setTabText(index, self.t(key))
        if not self.status.text(): self.status.setText(self.t("ready"))
        self.application_menu.setTitle(self.t("application_menu")); self.preferences_menu.setTitle(self.t("preferences_menu"))
        self.themes_menu.setTitle(self.t("themes_menu")); self.languages_menu.setTitle(self.t("languages_menu"))
        self.manage_track_languages_action.setText(self.t("manage_track_languages"))
        self.presets_action.setText(self.t("presets")); self.about_action.setText(self.t("about")); self.exit_action.setText(self.t("exit"))
        self.refresh_preset_combo(self.selected_preset_name)
        for identifier, action in self.theme_actions.items(): action.setText(self.themes[identifier].display_name(self.language))
        for code, action in self.language_actions.items(): action.setText(self.languages[code].name)
        for panel in (self.video_panel, self.audio_panel, self.subtitle_panel): panel.retranslate()

    def build_menus(self) -> None:
        self.application_menu = self.menuBar().addMenu("")
        self.preferences_menu = self.application_menu.addMenu("")
        self.languages_menu = self.preferences_menu.addMenu("")
        self.themes_menu = self.preferences_menu.addMenu("")
        self.preferences_menu.addSeparator()
        self.manage_track_languages_action = QAction(self); self.manage_track_languages_action.triggered.connect(self.show_track_languages)
        self.preferences_menu.addAction(self.manage_track_languages_action)
        self.presets_action = QAction(self); self.presets_action.triggered.connect(self.show_presets)
        self.application_menu.addAction(self.presets_action)
        self.application_menu.addSeparator()
        self.about_action = QAction(self); self.about_action.triggered.connect(self.show_about)
        self.application_menu.addAction(self.about_action)
        self.application_menu.addSeparator()
        self.exit_action = QAction(self); self.exit_action.triggered.connect(self.close)
        self.application_menu.addAction(self.exit_action)
        self.theme_group = QActionGroup(self); self.theme_group.setExclusive(True)
        self.theme_actions: dict[str, QAction] = {}
        for identifier, theme in self.themes.items():
            action = QAction(theme.display_name(self.language), self); action.setCheckable(True); action.setData(identifier)
            self.theme_group.addAction(action); self.themes_menu.addAction(action)
            action.triggered.connect(lambda checked=False, selected=action: self.set_theme(selected.data()))
            self.theme_actions[identifier] = action
        self.language_group = QActionGroup(self); self.language_group.setExclusive(True)
        self.language_actions: dict[str, QAction] = {}
        for code, language in self.languages.items():
            action = QAction(language.name, self); action.setCheckable(True); action.setData(code)
            self.language_group.addAction(action); self.languages_menu.addAction(action)
            action.triggered.connect(lambda checked=False, selected=action: self.set_language(selected.data()))
            self.language_actions[code] = action

    def show_about(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(self.t("about"))
        dialog.setWindowIcon(QIcon(str(ICON_PATH)))
        dialog.setModal(True)

        icon_label = QLabel()
        icon_label.setPixmap(QPixmap(str(ICON_PATH)).scaled(
            96, 96, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
        ))
        information = QLabel(
            f"<p><b>{self.t('developed_by')}</b> M.A Software</p>"
            f"<p><b>{self.t('web')}:</b> <a href='https://masoftware.es'>https://masoftware.es</a></p>"
            f"<p><b>{self.t('email')}:</b> <a href='mailto:info@masoftware.es'>info@masoftware.es</a></p>"
        )
        information.setTextFormat(Qt.TextFormat.RichText)
        information.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        information.setOpenExternalLinks(True)

        content = QHBoxLayout(); content.addWidget(icon_label); content.addWidget(information)
        close_button = QPushButton(self.t("close")); close_button.clicked.connect(dialog.accept)
        buttons = QHBoxLayout(); buttons.addStretch(); buttons.addWidget(close_button)
        layout = QVBoxLayout(dialog); layout.addLayout(content); layout.addLayout(buttons)
        dialog.exec()

    def set_language(self, language: str) -> None:
        if language not in self.languages:
            language = "es" if "es" in self.languages else next(iter(self.languages), "")
        self.language = language; self.settings.setValue("language", language)
        for code, action in self.language_actions.items(): action.setChecked(code == language)
        self.retranslate()

    def set_theme(self, theme: str) -> None:
        if theme not in self.themes:
            theme = "default" if "default" in self.themes else next(iter(self.themes), "")
        self.theme = theme
        QApplication.instance().setStyleSheet(self.themes[theme].stylesheet if theme else ""); self.settings.setValue("theme", theme)
        for identifier, action in self.theme_actions.items(): action.setChecked(identifier == theme)
        if hasattr(self, "batch_widget"): self.batch_widget.refresh_table()

    def preset_by_name(self, name: str) -> Preset | None:
        key = normalized_name(name)
        return next((preset for preset in self.presets if normalized_name(preset.name) == key), None)

    def refresh_preset_combo(self, selected_name: str = "") -> None:
        if not hasattr(self, "preset_combo"): return
        self.preset_combo.blockSignals(True); self.preset_combo.clear()
        self.preset_combo.addItem(self.t("custom_preset"), "")
        for preset in self.presets: self.preset_combo.addItem(preset.name, preset.name)
        preset = self.preset_by_name(selected_name)
        self.selected_preset_name = preset.name if preset else ""
        index = self.preset_combo.findData(self.selected_preset_name)
        self.preset_combo.setCurrentIndex(max(0, index)); self.preset_combo.blockSignals(False)

    def preset_selected(self) -> None:
        name = str(self.preset_combo.currentData() or "")
        self.selected_preset_name = name; self.settings.setValue("selected_preset", name)
        preset = self.preset_by_name(name)
        if preset: self.apply_preset(preset)

    def apply_preset(self, preset: Preset) -> None:
        self._apply_preset(preset, False)

    def _included_by_language_filter(self, config: TrackConfig, preset: Preset) -> tuple[bool, bool]:
        rule = preset.track_languages[config.track.kind]
        if not rule["enabled"]: return True, True
        recognized = recognize_language(config.track.language, config.track.title, self.track_languages)
        if recognized is None: return bool(rule["keep_unknown"]), False
        return recognized.identifier in set(rule["language_ids"]), True

    def _apply_preset(self, preset: Preset, warn_unknown: bool) -> None:
        unknown: list[TrackConfig] = []
        for config in self.video_panel.configs():
            config.copy_video = False
            for field, value in preset.video.items(): setattr(config, field, value)
            config.included, recognized = self._included_by_language_filter(config, preset)
            if preset.only_default_video_track:
                config.included = config.included and config.track.disposition_default
            if not recognized: unknown.append(config)
            self.save_encoding_preferences(config)
        for config in self.audio_panel.configs():
            for field, value in preset.audio.items(): setattr(config, field, value)
            config.included, recognized = self._included_by_language_filter(config, preset)
            if not recognized: unknown.append(config)
            self.save_encoding_preferences(config)
        for config in self.subtitle_panel.configs():
            included, recognized = self._included_by_language_filter(config, preset)
            config.included = preset.keep_subtitles and included
            if preset.keep_subtitles and not recognized: unknown.append(config)
        for panel in (self.video_panel, self.audio_panel, self.subtitle_panel):
            for index in range(panel.list.count()): panel.refresh_item(panel.list.item(index))
            panel.load_editor(panel.list.currentItem())
        self.selected_preset_name = preset.name; self.settings.setValue("selected_preset", preset.name)
        self.refresh_preset_combo(preset.name)
        if warn_unknown and unknown:
            labels = {"video": self.t("video_tracks"), "audio": self.t("audio_tracks"), "subtitle": self.t("subtitle_tracks")}
            details = "\n".join(f"{labels[config.track.kind]} · {config.track.index} · {config.track.language or '—'} · {config.track.title or '—'}" for config in unknown)
            QMessageBox.information(self, self.t("unknown_track_languages"), self.t("unknown_track_languages_message").format(details=details))

    def update_preset_selection_from_tracks(self) -> None:
        preset = self.preset_by_name(self.selected_preset_name)
        if not preset: return
        matches_video = all(
            all(getattr(config, field) == value for field, value in preset.video.items())
            and config.included == (
                self._included_by_language_filter(config, preset)[0]
                and (not preset.only_default_video_track or config.track.disposition_default)
            )
            for config in self.video_panel.configs()
        )
        matches_audio = all(all(getattr(config, field) == value for field, value in preset.audio.items()) and config.included == self._included_by_language_filter(config, preset)[0] for config in self.audio_panel.configs())
        matches_subtitles = all(config.included == (preset.keep_subtitles and self._included_by_language_filter(config, preset)[0]) for config in self.subtitle_panel.configs())
        if not (matches_video and matches_audio and matches_subtitles):
            self.selected_preset_name = ""; self.settings.setValue("selected_preset", ""); self.refresh_preset_combo()

    def show_presets(self) -> None:
        dialog = PresetManagerDialog(self, self.presets, self.presets_path, self.selected_preset_name)
        dialog.exec(); self.presets = dialog.presets
        self.selected_preset_name = dialog.selected_name
        self.settings.setValue("selected_preset", self.selected_preset_name)
        self.refresh_preset_combo(self.selected_preset_name)
        self.batch_widget.refresh_presets()
        preset = self.preset_by_name(self.selected_preset_name)
        if preset: self.apply_preset(preset)

    def show_track_languages(self) -> None:
        dialog = TrackLanguageManagerDialog(self); dialog.exec(); self.track_languages = dialog.languages
        if dialog.deleted_ids:
            for preset in self.presets:
                for rule in preset.track_languages.values():
                    rule["language_ids"] = [identifier for identifier in rule["language_ids"] if identifier not in dialog.deleted_ids]
            try: save_presets(self.presets_path, self.presets)
            except OSError as error: QMessageBox.critical(self, self.t("error"), self.t("preset_save_error").format(error=error))
        preset = self.preset_by_name(self.selected_preset_name)
        if preset: self.apply_preset(preset)

    def save_hardware_preference(self, enabled: bool) -> None:
        self.settings.setValue("encoding/use_hardware", enabled)
        if hasattr(self, "batch_widget"): self.batch_widget.set_hardware(enabled)

    def mode_changed(self, index: int) -> None:
        self.settings.setValue("window/active_mode", index)
        if index == 1 and not self.presets:
            QMessageBox.information(self, self.t("batch"), self.t("batch_no_presets"))

    def apply_encoding_preferences(self, config: TrackConfig) -> None:
        defaults = VIDEO_PREFERENCE_DEFAULTS if config.track.kind == "video" else AUDIO_PREFERENCE_DEFAULTS if config.track.kind == "audio" else {}
        for field, default in defaults.items():
            value_type = bool if isinstance(default, bool) else int if isinstance(default, int) else float if isinstance(default, float) else str
            value = self.settings.value(f"encoding/{config.track.kind}/{field}", default, type=value_type)
            setattr(config, field, value)
        if config.track.kind == "video" and config.resolution == "script_1280":
            config.resolution, config.resolution_mode = "hd_720", "width"
        if config.track.kind == "video" and config.video_codec == "copy":
            config.copy_video, config.video_codec = True, "h264"
        preset = self.preset_by_name(self.selected_preset_name)
        if preset and config.track.kind == "video":
            config.copy_video = False
            for field, value in preset.video.items(): setattr(config, field, value)
        elif preset and config.track.kind == "audio":
            for field, value in preset.audio.items(): setattr(config, field, value)
        elif preset and config.track.kind == "subtitle":
            config.included = preset.keep_subtitles
        if preset:
            included, _ = self._included_by_language_filter(config, preset)
            if config.track.kind == "video" and preset.only_default_video_track:
                included = included and config.track.disposition_default
            config.included = (preset.keep_subtitles and included) if config.track.kind == "subtitle" else included

    def save_encoding_preferences(self, config: TrackConfig) -> None:
        fields = VIDEO_PREFERENCE_DEFAULTS if config.track.kind == "video" else AUDIO_PREFERENCE_DEFAULTS if config.track.kind == "audio" else {}
        for field in fields:
            self.settings.setValue(f"encoding/{config.track.kind}/{field}", getattr(config, field))

    def save_panel_encoding_preferences(self, panel: TrackPanel) -> None:
        item = panel.list.currentItem()
        if item:
            self.save_encoding_preferences(item.data(Qt.ItemDataRole.UserRole))

    def restore_window_settings(self) -> None:
        geometry = self.settings.value("window/geometry")
        restored = geometry is not None and self.restoreGeometry(geometry)
        if not restored:
            self.center_on_screen()
        if self.settings.value("window/maximized", False, type=bool):
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)

    def center_on_screen(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        frame = self.frameGeometry()
        frame.moveCenter(screen.availableGeometry().center())
        self.move(frame.topLeft())

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.batch_widget.testing:
            self.batch_widget.cancel_testing()
        if self.batch_widget.is_processing():
            self.batch_widget.stop_processing(); event.ignore(); return
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/maximized", self.isMaximized())
        self.settings.setValue("window/active_mode", self.mode_tabs.currentIndex())
        self.settings.sync()
        super().closeEvent(event)

    def open_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, self.t("open"), "", self.t("file_filter"))
        if not filename: return
        self.status.setText(self.t("probing")); QApplication.processEvents()
        try: self.media = probe_media(Path(filename), self.t)
        except MediaError as exc: QMessageBox.critical(self, self.t("error"), str(exc)); self.status.setText(self.t("ready")); return
        self.source_edit.setText(str(self.media.path))
        if not self.output_dir_edit.text().strip(): self.output_dir_edit.setText(str(self.media.path.parent))
        extension = str(self.output_format_combo.currentData() or ".mkv")
        self.output_name_edit.setText(f"{self.media.path.stem}_compressed{extension}"); self.video_panel.set_tracks(self.media.video_tracks)
        audio_tracks = tuple(MediaTrack(
            t.index, "audio", t.codec, t.language, t.title, self.media.path,
            channels=t.channels, layout=t.layout, sample_rate=t.sample_rate,
            bitrate=t.bitrate, disposition_default=t.disposition_default,
        ) for t in self.media.audio_tracks)
        self.audio_panel.set_tracks(audio_tracks); self.subtitle_panel.set_tracks(self.media.subtitle_tracks)
        preset = self.preset_by_name(self.selected_preset_name)
        if preset: self._apply_preset(preset, True)
        self.convert_button.setEnabled(True); self.status.setText(self.t("ready"))

    def choose_output_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, self.t("output_dir"), self.output_dir_edit.text())
        if directory: self.output_dir_edit.setText(directory); self.remember_output_directory()

    def remember_output_directory(self) -> None:
        if self.output_dir_edit.text().strip(): self.settings.setValue("output_directory", self.output_dir_edit.text().strip())

    def output_format_changed(self) -> None:
        extension = str(self.output_format_combo.currentData() or ".mkv")
        self.settings.setValue("output_format", extension)
        name = self.output_name_edit.text().strip()
        if name: self.output_name_edit.setText(str(Path(name).with_suffix(extension)))

    def output_name_finished(self) -> None:
        extension = Path(self.output_name_edit.text().strip()).suffix.lower()
        index = self.output_format_combo.findData(extension)
        if index >= 0:
            self.output_format_combo.blockSignals(True); self.output_format_combo.setCurrentIndex(index); self.output_format_combo.blockSignals(False)
            self.settings.setValue("output_format", extension)

    def all_configs(self) -> list[TrackConfig]: return self.video_panel.configs() + self.audio_panel.configs() + self.subtitle_panel.configs()

    def restore_defaults(self) -> None:
        for panel in (self.video_panel, self.audio_panel):
            panel.save_editor()
            for config in panel.configs():
                config.reset_encoding_defaults()
            for index in range(panel.list.count()): panel.refresh_item(panel.list.item(index))
            panel.load_editor(panel.list.currentItem())
        for kind, defaults in (("video", VIDEO_PREFERENCE_DEFAULTS), ("audio", AUDIO_PREFERENCE_DEFAULTS)):
            for field, value in defaults.items(): self.settings.setValue(f"encoding/{kind}/{field}", value)
        self.hardware_check.setChecked(True)
        self.save_hardware_preference(True); self.settings.sync()
        self.update_preset_selection_from_tracks()
        self.status.setText(self.t("defaults_restored"))

    def start_conversion(self) -> None:
        if not self.media: return
        for panel in (self.video_panel, self.audio_panel, self.subtitle_panel): panel.save_editor()
        configs = self.all_configs()
        if not any(c.included for c in self.video_panel.configs()): QMessageBox.warning(self, self.t("error"), self.t("no_video")); return
        output = Path(self.output_dir_edit.text()).expanduser() / self.output_name_edit.text().strip()
        if output.suffix.lower() not in {".mkv", ".mp4", ".avi"}:
            output = output.with_suffix(str(self.output_format_combo.currentData() or ".mkv")); self.output_name_edit.setText(output.name)
        warnings = container_warnings(configs, output.suffix, self.t)
        if warnings: QMessageBox.warning(self, self.t("error"), self.t("container_warning").format(details="\n".join(warnings))); return
        output.parent.mkdir(parents=True, exist_ok=True); self.remember_output_directory()
        if output.exists() and not ask_yes_no(self, self.t("overwrite_title"), self.t("overwrite"), self.t): return
        command = build_project_command(self.media.path, output, configs, EncodingOptions(hardware="nvidia" if self.hardware_check.isChecked() else "cpu"))
        self.output_path = output; self.process = QProcess(self); self.process.setProgram(command[0]); self.process.setArguments(command[1:])
        self.conversion_cancelled = False; self.current_speed = "--"
        self.process.readyReadStandardOutput.connect(self.read_progress); self.process.readyReadStandardError.connect(self.read_error); self.process.finished.connect(self.conversion_finished)
        self.progress.setValue(0); self.progress.setFormat("%p% · --"); self.progress_buffer = ""; self.set_busy(True); self.status.setText(self.t("converting")); self.process.start()

    def read_progress(self) -> None:
        if not self.process or not self.media or self.media.duration <= 0: return
        self.progress_buffer += bytes(self.process.readAllStandardOutput()).decode(errors="replace"); lines = self.progress_buffer.split("\n"); self.progress_buffer = lines.pop()
        for line in lines:
            if line.startswith("out_time_us="): self.progress.setValue(min(100, round(int(line.partition("=")[2] or 0) / 1_000_000 / self.media.duration * 100)))
            elif line.startswith("speed="):
                speed = line.partition("=")[2].strip()
                if speed and speed != "N/A": self.current_speed = speed
        self.progress.setFormat(f"%p% · {self.current_speed}")

    def read_error(self) -> None:
        if self.process: self.process.setProperty("last_error", (self.process.property("last_error") or "") + bytes(self.process.readAllStandardError()).decode(errors="replace"))

    def conversion_finished(self, exit_code: int) -> None:
        error = self.process.property("last_error") if self.process else ""; self.set_busy(False)
        if self.conversion_cancelled:
            if self.output_path: self.output_path.unlink(missing_ok=True)
            self.progress.setValue(0); self.progress.setFormat("%p%")
            self.status.setText(self.t("cancelled"))
        elif exit_code == 0:
            self.progress.setValue(100); self.status.setText(self.t("done"))
            QMessageBox.information(self, self.t("processing_complete"), self.t("processing_complete"))
        else:
            if self.output_path: self.output_path.unlink(missing_ok=True)
            self.status.setText(self.t("error")); QMessageBox.critical(self, self.t("error"), error or self.t("ffmpeg_exit_error").format(code=exit_code))
        self.process = None; self.output_path = None

    def cancel_conversion(self) -> None:
        if not self.process:
            return
        if not ask_yes_no(self, self.t("stop_title"), self.t("stop_confirm"), self.t):
            return
        self.conversion_cancelled = True
        self.status.setText(self.t("stopping"))
        self.convert_button.setEnabled(False)
        self.process.kill()

    def toggle_conversion(self) -> None:
        if self.process:
            self.cancel_conversion()
        else:
            self.start_conversion()

    def set_busy(self, busy: bool) -> None:
        for widget in (self.open_button, self.output_dir_button, self.output_dir_edit, self.output_name_edit,
                       self.output_format_combo, self.hardware_check, self.defaults_button, self.preset_combo, self.track_tabs):
            widget.setEnabled(not busy)
        self.mode_tabs.setTabEnabled(1, not busy)
        self.application_menu.setEnabled(not busy)
        self.convert_button.setEnabled(busy or self.media is not None)
        self.convert_button.setText(self.t("stop") if busy else self.t("convert"))
        set_button_role(self.convert_button, danger=busy, execution=not busy)


def main() -> int:
    app = QApplication(sys.argv); app.setApplicationName("VideoGUI"); app.setOrganizationName("VideoGUI")
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    app.dialog_sound = DialogSound(app); app.installEventFilter(app.dialog_sound)
    window = MainWindow(); window.show(); return app.exec()
