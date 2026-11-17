from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QPushButton,
    QSpinBox,
)

from core.normal_map import NormalMapOptions
from ui.panels.base import GeneratePropertiesContainer


class NormalPanel(GeneratePropertiesContainer):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.note_label = QLabel(
            "No Height map yet, so the button below has nothing to work from "
            "(you can still import a Normal map directly instead)."
        )
        self.note_label.setWordWrap(True)
        self.note_label.setStyleSheet("color: #e5a50a;")  # warning yellow, readable in light and dark
        self.generate_page.add_wide(self.note_label)

        self.preset_combo = QComboBox()
        self.preset_combo.addItems([
            "Blender / OpenGL / Unity (+Y)",
            "Unreal Engine / DirectX (-Y)",
        ])
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        self.preset_combo.setToolTip("Game engines read the green channel differently (OpenGL vs DirectX). Pick the one you export to.")
        self.generate_page.add_param("Target engine", self.preset_combo, wide=True)

        self.multi_freq_cb = QCheckBox("Set detail sizes separately")
        self.multi_freq_cb.setToolTip("Decompose surface relief into 3 independent frequency octaves.")
        self.multi_freq_cb.stateChanged.connect(self.propertiesChanged.emit)
        self.generate_page.add_section("Detail Sizes", toggle=self.multi_freq_cb)

        self.macro_spin = QDoubleSpinBox()
        self.macro_spin.setRange(0.0, 3.0)
        self.macro_spin.setSingleStep(0.1)
        self.macro_spin.setValue(1.0)
        self.macro_spin.setToolTip("Large-scale structural silhouette relief.")
        self.macro_spin.valueChanged.connect(self.propertiesChanged.emit)
        self.generate_page.add_param("Large shapes", self.macro_spin)

        self.medium_spin = QDoubleSpinBox()
        self.medium_spin.setRange(0.0, 3.0)
        self.medium_spin.setSingleStep(0.1)
        self.medium_spin.setValue(1.0)
        self.medium_spin.setToolTip("Mid-frequency surface relief (grooves, stone patterns, cracks).")
        self.medium_spin.valueChanged.connect(self.propertiesChanged.emit)
        self.generate_page.add_param("Medium detail", self.medium_spin)

        self.micro_spin = QDoubleSpinBox()
        self.micro_spin.setRange(0.0, 3.0)
        self.micro_spin.setSingleStep(0.1)
        self.micro_spin.setValue(1.0)
        self.micro_spin.setToolTip("High-frequency fine pores, sandpaper grain, and subtle irregularities.")
        self.micro_spin.valueChanged.connect(self.propertiesChanged.emit)
        self.generate_page.add_param("Fine grain", self.micro_spin)

        self.inject_albedo_cb = QCheckBox("Add grain from photo")
        self.inject_albedo_cb.setToolTip("Extract micro pore/fiber grain from Albedo photo and blend into normal map.")
        self.inject_albedo_cb.stateChanged.connect(self.propertiesChanged.emit)
        self.generate_page.add_section("Photo Grain", toggle=self.inject_albedo_cb)

        self.albedo_strength_spin = QDoubleSpinBox()
        self.albedo_strength_spin.setRange(0.05, 2.0)
        self.albedo_strength_spin.setSingleStep(0.05)
        self.albedo_strength_spin.setValue(0.5)
        self.albedo_strength_spin.valueChanged.connect(self.propertiesChanged.emit)
        self.albedo_strength_spin.setToolTip("How much fine texture from the photo is added to the bumps.")
        self.generate_page.add_param("Photo grain amount", self.albedo_strength_spin)

        reset_gen_btn = QPushButton("Reset Generate Defaults")
        reset_gen_btn.clicked.connect(self.reset_generate_defaults)
        self.generate_page.end_section()
        self.generate_page.add_wide(reset_gen_btn)
        self.generate_page.add_stretch()

        page = self.properties_page
        self.strength_spin = QDoubleSpinBox()
        self.strength_spin.setRange(0.1, 10.0)
        self.strength_spin.setSingleStep(0.1)
        self.strength_spin.setValue(1.0)
        self.strength_spin.valueChanged.connect(self.propertiesChanged.emit)
        self.strength_spin.setToolTip("How strong the bumps look. Higher makes the surface look deeper.")
        page.add_param("Bump strength", self.strength_spin)

        self.pre_blur_spin = QSpinBox()
        self.pre_blur_spin.setRange(0, 25)
        self.pre_blur_spin.valueChanged.connect(self.propertiesChanged.emit)
        self.pre_blur_spin.setToolTip("Softens the Height map before the bumps are calculated, which removes noise and jagged edges.")
        page.add_param("Smooth height first (px)", self.pre_blur_spin)

        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self.reset_to_defaults)
        page.add_wide(reset_btn)
        page.add_stretch()

    def _on_preset_changed(self, idx: int) -> None:
        self.propertiesChanged.emit()

    def _invert_y(self) -> bool:
        return self.preset_combo.currentIndex() == 1

    def reset_generate_defaults(self) -> None:
        self.multi_freq_cb.setChecked(False)
        self.macro_spin.setValue(1.0)
        self.medium_spin.setValue(1.0)
        self.micro_spin.setValue(1.0)
        self.inject_albedo_cb.setChecked(False)
        self.albedo_strength_spin.setValue(0.5)
        self.propertiesChanged.emit()

    def reset_to_defaults(self) -> None:
        self.strength_spin.setValue(1.0)
        self.pre_blur_spin.setValue(0)
        self.reset_generate_defaults()
        self.propertiesChanged.emit()

    def set_has_height(self, has_height: bool) -> None:
        self.note_label.setVisible(not has_height)

    def current_options(self) -> NormalMapOptions:
        return NormalMapOptions(
            strength=self.strength_spin.value(),
            invert_y=self._invert_y(),
            pre_blur_radius=self.pre_blur_spin.value(),
            multi_frequency=self.multi_freq_cb.isChecked(),
            macro_strength=self.macro_spin.value(),
            medium_strength=self.medium_spin.value(),
            micro_strength=self.micro_spin.value(),
            inject_albedo=self.inject_albedo_cb.isChecked(),
            albedo_strength=self.albedo_strength_spin.value(),
        )

    def properties_to_dict(self) -> dict:
        return {
            "strength": self.strength_spin.value(),
            "invert_y": self._invert_y(),
            "pre_blur_radius": self.pre_blur_spin.value(),
            "multi_frequency": self.multi_freq_cb.isChecked(),
            "macro_strength": self.macro_spin.value(),
            "medium_strength": self.medium_spin.value(),
            "micro_strength": self.micro_spin.value(),
            "inject_albedo": self.inject_albedo_cb.isChecked(),
            "albedo_strength": self.albedo_strength_spin.value(),
        }

    def properties_apply_dict(self, data: dict) -> None:
        if not data:
            return
        self.strength_spin.setValue(data.get("strength", self.strength_spin.value()))
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(1 if data.get("invert_y", False) else 0)
        self.preset_combo.blockSignals(False)
        self.pre_blur_spin.setValue(data.get("pre_blur_radius", self.pre_blur_spin.value()))

        self.multi_freq_cb.setChecked(data.get("multi_frequency", False))
        self.macro_spin.setValue(data.get("macro_strength", 1.0))
        self.medium_spin.setValue(data.get("medium_strength", 1.0))
        self.micro_spin.setValue(data.get("micro_strength", 1.0))
        self.inject_albedo_cb.setChecked(data.get("inject_albedo", False))
        self.albedo_strength_spin.setValue(data.get("albedo_strength", 0.5))

    to_options_dict = properties_to_dict
    apply_options_dict = properties_apply_dict
