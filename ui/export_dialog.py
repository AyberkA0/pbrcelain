from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

_HEIGHT_CHOICES = (("8-bit PNG", 8), ("16-bit PNG", 16), ("32-bit OpenEXR", 32))
_AO_CHOICES = (("8-bit PNG", 8), ("16-bit PNG", 16))
_KEY = "export/"


@dataclass
class ExportOptions:
    height_bit_depth: int = 16
    ao_bit_depth: int = 8
    curvature: bool = True


def _load() -> ExportOptions:
    s = QSettings()
    return ExportOptions(
        height_bit_depth=int(s.value(_KEY + "heightBitDepth", 16)),
        ao_bit_depth=int(s.value(_KEY + "aoBitDepth", 8)),
        curvature=s.value(_KEY + "curvature", True, type=bool),
    )


def _save(options: ExportOptions) -> None:
    s = QSettings()
    s.setValue(_KEY + "heightBitDepth", options.height_bit_depth)
    s.setValue(_KEY + "aoBitDepth", options.ao_bit_depth)
    s.setValue(_KEY + "curvature", options.curvature)


def _combo(choices, current: int) -> QComboBox:
    combo = QComboBox()
    for label, depth in choices:
        combo.addItem(label, depth)
    index = combo.findData(current)
    combo.setCurrentIndex(index if index >= 0 else 0)
    return combo


class ExportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Maps")
        options = _load()

        layout = QVBoxLayout(self)
        intro = QLabel("All generated and imported maps are written to the folder you pick next.")
        intro.setWordWrap(True)
        intro.setProperty("role", "dim")
        layout.addWidget(intro)

        form = QFormLayout()
        self.height_combo = _combo(_HEIGHT_CHOICES, options.height_bit_depth)
        self.height_combo.setToolTip("16-bit is plenty for displacement in most engines; EXR for film/offline renderers.")
        self.ao_combo = _combo(_AO_CHOICES, options.ao_bit_depth)
        self.curvature_checkbox = QCheckBox("Also export Curvature map")
        self.curvature_checkbox.setChecked(options.curvature)
        self.curvature_checkbox.setToolTip(
            "Writes curvature.png, derived from the Height map:\n"
            "mid-grey = flat, brighter = edges/ridges (wear), darker = cavities (dirt)."
        )
        form.addRow("Height:", self.height_combo)
        form.addRow("Ambient Occlusion:", self.ao_combo)
        form.addRow("", self.curvature_checkbox)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        export_btn = buttons.addButton("Choose Folder…", QDialogButtonBox.ButtonRole.AcceptRole)
        export_btn.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def options(self) -> ExportOptions:
        options = ExportOptions(
            height_bit_depth=int(self.height_combo.currentData()),
            ao_bit_depth=int(self.ao_combo.currentData()),
            curvature=self.curvature_checkbox.isChecked(),
        )
        _save(options)
        return options
