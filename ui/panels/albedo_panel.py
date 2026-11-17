from __future__ import annotations

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QPushButton,
)

from core.albedo_adjust import AlbedoAdjustOptions, ColorShiftRule
from ui.panels.base import GeneratePropertiesContainer


class AlbedoPanel(GeneratePropertiesContainer):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Albedo is imported, never generated, so it only has the Adjustment page.
        self.set_single_page()

        self.wb_cb = QCheckBox("Remove color cast")
        self.wb_cb.setToolTip("Neutralize undesirable yellow/blue color cast using gray-world normalization.")
        self.wb_cb.stateChanged.connect(self.propertiesChanged.emit)
        self.properties_page.add_section("White Balance", toggle=self.wb_cb)

        self.wb_strength_spin = QDoubleSpinBox()
        self.wb_strength_spin.setRange(0.1, 1.0)
        self.wb_strength_spin.setSingleStep(0.05)
        self.wb_strength_spin.setValue(0.70)
        self.wb_strength_spin.valueChanged.connect(self.propertiesChanged.emit)
        self.wb_strength_spin.setToolTip("How much of the color cast is removed. 1 removes it fully.")
        self.properties_page.add_param("Correction strength", self.wb_strength_spin)

        self.shift_enabled_cb = QCheckBox("Change a color")
        self.shift_enabled_cb.stateChanged.connect(self._on_shift_toggled)
        self.shift_enabled_cb.stateChanged.connect(self.propertiesChanged.emit)
        self.properties_page.add_section("Change a Color", toggle=self.shift_enabled_cb)

        self.source_color = QColor(200, 200, 200)
        self.src_color_btn = QPushButton()
        self.src_color_btn.setFixedHeight(28)
        self.src_color_btn.setMinimumWidth(56)
        self._update_btn_color(self.src_color_btn, self.source_color)
        self.src_color_btn.clicked.connect(self._pick_source_color)
        self.src_color_btn.setToolTip("Pick the color in the photo you want to replace.")
        self.properties_page.add_param("Color to change", self.src_color_btn)

        self.target_color = QColor(120, 120, 120)
        self.dst_color_btn = QPushButton()
        self.dst_color_btn.setFixedHeight(28)
        self.dst_color_btn.setMinimumWidth(56)
        self._update_btn_color(self.dst_color_btn, self.target_color)
        self.dst_color_btn.clicked.connect(self._pick_target_color)
        self.dst_color_btn.setToolTip("The color the picked color becomes.")
        self.properties_page.add_param("Change it to", self.dst_color_btn)
        self.properties_page.new_row()

        self.tolerance_spin = QDoubleSpinBox()
        self.tolerance_spin.setRange(1.0, 255.0)
        self.tolerance_spin.setSingleStep(2.0)
        self.tolerance_spin.setValue(40.0)
        self.tolerance_spin.setToolTip(
            "Color Distance Range (Tolerance):\n"
            "Colors within this Euclidean distance in RGB will shift towards the target color.\n"
            "The closer a pixel is to the source color, the more it shifts."
        )
        self.tolerance_spin.valueChanged.connect(self.propertiesChanged.emit)
        self.properties_page.add_param("Color range", self.tolerance_spin)

        self.falloff_spin = QDoubleSpinBox()
        self.falloff_spin.setRange(0.2, 3.0)
        self.falloff_spin.setSingleStep(0.1)
        self.falloff_spin.setValue(1.0)
        self.falloff_spin.setToolTip(
            "Falloff Curve:\n"
            "1.0 = linear proximity falloff.\n"
            "> 1.0 = sharper falloff (only very close colors shift strongly).\n"
            "< 1.0 = broader, softer transition across the range."
        )
        self.falloff_spin.valueChanged.connect(self.propertiesChanged.emit)
        self.properties_page.add_param("Soft falloff", self.falloff_spin)

        self.seamless_cb = QCheckBox("Make seamless (tileable)")
        self.seamless_cb.setToolTip("Blends opposing boundary strips to produce matching edges for infinite repeats.")
        self.seamless_cb.stateChanged.connect(self.propertiesChanged.emit)
        self.properties_page.add_section("Make Seamless", toggle=self.seamless_cb)

        self.seamless_overlap_spin = QDoubleSpinBox()
        self.seamless_overlap_spin.setRange(2.0, 30.0)
        self.seamless_overlap_spin.setSingleStep(1.0)
        self.seamless_overlap_spin.setValue(10.0)
        self.seamless_overlap_spin.setToolTip("Percentage of the border width used for smooth cross-fading.")
        self.seamless_overlap_spin.valueChanged.connect(self.propertiesChanged.emit)
        self.properties_page.add_param("Blend width (%)", self.seamless_overlap_spin)

        self.properties_page.end_section()

        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self.reset_to_defaults)
        self.properties_page.add_wide(reset_btn)
        self.properties_page.add_stretch()

        self._on_shift_toggled()

    def _update_btn_color(self, btn: QPushButton, color: QColor) -> None:
        btn.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #555; border-radius: 4px;")
        btn.setText(color.name().upper())

    def _pick_source_color(self) -> None:
        col = QColorDialog.getColor(self.source_color, self, "Select Source Color to Shift")
        if col.isValid():
            self.source_color = col
            self._update_btn_color(self.src_color_btn, col)
            self.propertiesChanged.emit()

    def _pick_target_color(self) -> None:
        col = QColorDialog.getColor(self.target_color, self, "Select Target Replacement Color")
        if col.isValid():
            self.target_color = col
            self._update_btn_color(self.dst_color_btn, col)
            self.propertiesChanged.emit()

    def _on_shift_toggled(self, *_args) -> None:
        enabled = self.shift_enabled_cb.isChecked()
        self.src_color_btn.setEnabled(enabled)
        self.dst_color_btn.setEnabled(enabled)
        self.tolerance_spin.setEnabled(enabled)
        self.falloff_spin.setEnabled(enabled)

    def current_shift_rules(self) -> list[ColorShiftRule]:
        rule = ColorShiftRule(
            enabled=self.shift_enabled_cb.isChecked(),
            source_rgb=(self.source_color.red(), self.source_color.green(), self.source_color.blue()),
            target_rgb=(self.target_color.red(), self.target_color.green(), self.target_color.blue()),
            tolerance=self.tolerance_spin.value(),
            falloff=self.falloff_spin.value(),
        )
        return [rule]

    def current_adjust_options(self) -> AlbedoAdjustOptions:
        return AlbedoAdjustOptions(
            white_balance_enabled=self.wb_cb.isChecked(),
            white_balance_strength=self.wb_strength_spin.value(),
            seamless_enabled=self.seamless_cb.isChecked(),
            seamless_overlap_pct=self.seamless_overlap_spin.value(),
        )

    current_options = current_adjust_options
    current_generate_options = current_adjust_options

    def reset_to_defaults(self) -> None:
        self.wb_cb.setChecked(False)
        self.wb_strength_spin.setValue(0.70)
        self.shift_enabled_cb.setChecked(False)
        self.source_color = QColor(200, 200, 200)
        self.target_color = QColor(120, 120, 120)
        self._update_btn_color(self.src_color_btn, self.source_color)
        self._update_btn_color(self.dst_color_btn, self.target_color)
        self.tolerance_spin.setValue(40.0)
        self.falloff_spin.setValue(1.0)
        self.seamless_cb.setChecked(False)
        self.seamless_overlap_spin.setValue(10.0)
        self.propertiesChanged.emit()

    def properties_to_dict(self) -> dict:
        return {
            "shift_enabled": self.shift_enabled_cb.isChecked(),
            "source_rgb": [self.source_color.red(), self.source_color.green(), self.source_color.blue()],
            "target_rgb": [self.target_color.red(), self.target_color.green(), self.target_color.blue()],
            "tolerance": self.tolerance_spin.value(),
            "falloff": self.falloff_spin.value(),
            "seamless_enabled": self.seamless_cb.isChecked(),
            "seamless_overlap_pct": self.seamless_overlap_spin.value(),
            "white_balance_enabled": self.wb_cb.isChecked(),
            "white_balance_strength": self.wb_strength_spin.value(),
        }

    def properties_apply_dict(self, data: dict) -> None:
        if not data:
            return
        self.shift_enabled_cb.setChecked(data.get("shift_enabled", False))
        if "source_rgb" in data:
            r, g, b = data["source_rgb"]
            self.source_color = QColor(r, g, b)
            self._update_btn_color(self.src_color_btn, self.source_color)
        if "target_rgb" in data:
            r, g, b = data["target_rgb"]
            self.target_color = QColor(r, g, b)
            self._update_btn_color(self.dst_color_btn, self.target_color)
        self.tolerance_spin.setValue(data.get("tolerance", self.tolerance_spin.value()))
        self.falloff_spin.setValue(data.get("falloff", self.falloff_spin.value()))
        self.seamless_cb.setChecked(data.get("seamless_enabled", False))
        self.seamless_overlap_spin.setValue(data.get("seamless_overlap_pct", 10.0))
        self.wb_cb.setChecked(data.get("white_balance_enabled", False))
        self.wb_strength_spin.setValue(data.get("white_balance_strength", 0.70))

    to_options_dict = properties_to_dict
    apply_options_dict = properties_apply_dict
