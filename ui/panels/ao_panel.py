from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QPushButton,
    QSpinBox,
)

from core.ao_map import AO_METHOD_CLASSIC, AO_METHOD_RAYTRACED, AOMapOptions
from ui.panels.base import GeneratePropertiesContainer


class AOPanel(GeneratePropertiesContainer):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.note_label = QLabel(
            "No Height map yet, so the button below has nothing to work from "
            "(you can still import an Ambient Occlusion map directly instead)."
        )
        self.note_label.setWordWrap(True)
        self.note_label.setProperty("role", "dim")
        self.generate_page.add_wide(self.note_label)

        self.method_combo = QComboBox()
        self.method_combo.addItem("Ray-traced", AO_METHOD_RAYTRACED)
        self.method_combo.addItem("Classic", AO_METHOD_CLASSIC)
        self.method_combo.setToolTip(
            "Ray-traced: treats the Height map as a real 3D surface at the real-world\n"
            "scale below and traces the sky visibility of every pixel — physically\n"
            "based contact shadows that look the same at any resolution.\n"
            "Classic: the original fast approximation (used by older projects)."
        )
        self.method_combo.currentIndexChanged.connect(self._on_method_changed)
        self.method_combo.currentIndexChanged.connect(self.propertiesChanged.emit)
        self.generate_page.add_param("Method", self.method_combo, wide=True)

        self.generate_page.add_section("Real-World Scale")

        self.surface_width_spin = QDoubleSpinBox()
        self.surface_width_spin.setRange(1.0, 2000.0)
        self.surface_width_spin.setDecimals(1)
        self.surface_width_spin.setSingleStep(5.0)
        self.surface_width_spin.setSuffix(" cm")
        self.surface_width_spin.setToolTip("How wide the surface in the texture is in reality (e.g. 50 cm of brick wall).")
        self.surface_width_spin.valueChanged.connect(self.propertiesChanged.emit)
        self.generate_page.add_param("Surface width", self.surface_width_spin)

        self.max_depth_spin = QDoubleSpinBox()
        self.max_depth_spin.setRange(0.1, 500.0)
        self.max_depth_spin.setDecimals(1)
        self.max_depth_spin.setSingleStep(1.0)
        self.max_depth_spin.setSuffix(" mm")
        self.max_depth_spin.setToolTip("Real height difference between the lowest (black) and highest (white) point.")
        self.max_depth_spin.valueChanged.connect(self.propertiesChanged.emit)
        self.generate_page.add_param("Max depth", self.max_depth_spin)

        self.search_percent_spin = QDoubleSpinBox()
        self.search_percent_spin.setRange(0.5, 20.0)
        self.search_percent_spin.setDecimals(1)
        self.search_percent_spin.setSingleStep(0.5)
        self.search_percent_spin.setSuffix(" %")
        self.search_percent_spin.setToolTip("How far away (as % of the texture width) relief can still cast occlusion.")
        self.search_percent_spin.valueChanged.connect(self.propertiesChanged.emit)
        self.generate_page.add_param("Search distance", self.search_percent_spin)

        self.generate_page.add_section("Horizon Ray Sampling")

        self.samples_combo = QComboBox()
        self.samples_combo.addItems(["Fast", "Balanced", "High", "Ultra"])
        self.samples_combo.setCurrentIndex(1)
        self.samples_combo.currentIndexChanged.connect(self.propertiesChanged.emit)
        self.samples_combo.setToolTip("Fast: 4 directions, Balanced: 8, High: 12, Ultra: 16. More directions give smoother shadows but take longer.")
        self.generate_page.add_param("Quality", self.samples_combo)

        self.radius_spin = QSpinBox()
        self.radius_spin.setRange(2, 64)
        self.radius_spin.setValue(16)
        self.radius_spin.setToolTip("Classic method: search distance in pixels for neighboring occluding structures.")
        self.radius_spin.valueChanged.connect(self.propertiesChanged.emit)
        self.radius_spin.setToolTip("How far away a bump can still darken its surroundings, in pixels.")
        self._radius_field = self.generate_page.add_param("Shadow reach (px)", self.radius_spin)

        self.blur_spin = QSpinBox()
        self.blur_spin.setRange(0, 10)
        self.blur_spin.setValue(1)
        self.blur_spin.setToolTip("Gentle post-softening to eliminate stepped sampling artifacts.")
        self.blur_spin.valueChanged.connect(self.propertiesChanged.emit)
        self.blur_spin.setToolTip("Blurs the result slightly to hide banding.")
        self.generate_page.add_param("Softening (px)", self.blur_spin)

        reset_gen_btn = QPushButton("Reset Generate Defaults")
        reset_gen_btn.clicked.connect(self.reset_generate_defaults)
        self.generate_page.end_section()
        self.generate_page.add_wide(reset_gen_btn)
        self.generate_page.add_stretch()

        page = self.properties_page
        page.add_section("Intensity & Curve")

        self.strength_spin = QDoubleSpinBox()
        self.strength_spin.setRange(0.1, 5.0)
        self.strength_spin.setSingleStep(0.1)
        self.strength_spin.setValue(1.0)
        self.strength_spin.setToolTip("Multiplier for contact shadow darkness in crevices.")
        self.strength_spin.valueChanged.connect(self.propertiesChanged.emit)
        self.strength_spin.setToolTip("How dark the shadows in cracks and corners get.")
        page.add_param("Darkness", self.strength_spin)

        self.contrast_spin = QDoubleSpinBox()
        self.contrast_spin.setRange(0.2, 4.0)
        self.contrast_spin.setSingleStep(0.1)
        self.contrast_spin.setValue(1.5)
        self.contrast_spin.setToolTip("Occlusion gamma power: >1.0 deepens cracks while keeping flat areas bright.")
        self.contrast_spin.valueChanged.connect(self.propertiesChanged.emit)
        self.contrast_spin.setToolTip("Above 1 keeps flat areas bright while cracks get darker.")
        page.add_param("Contrast", self.contrast_spin)

        self.invert_checkbox = QCheckBox("Invert")
        self.invert_checkbox.stateChanged.connect(self.propertiesChanged.emit)
        self.invert_checkbox.setToolTip("Swap dark and light, for engines that expect white in the cracks.")
        page.add_param("Direction", self.invert_checkbox)

        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self.reset_to_defaults)
        page.end_section()
        page.add_wide(reset_btn)
        page.add_stretch()

        self.reset_to_defaults()

    def set_has_height(self, has_height: bool) -> None:
        self.note_label.setVisible(not has_height)

    def _get_samples_count(self) -> int:
        idx = self.samples_combo.currentIndex()
        return [4, 8, 12, 16][idx] if 0 <= idx < 4 else 8

    def _on_method_changed(self, *_args) -> None:
        raytraced = self.current_method() == AO_METHOD_RAYTRACED
        for w in (self.surface_width_spin, self.max_depth_spin, self.search_percent_spin):
            w.setEnabled(raytraced)
        self.radius_spin.setEnabled(not raytraced)
        sections = self.generate_page.sections
        if "Real-World Scale" in sections:
            for widget in sections["Real-World Scale"]:
                if widget is sections["Real-World Scale"][0] or not raytraced:
                    widget.setVisible(raytraced)
                elif sections["Real-World Scale"][0].is_expanded():
                    widget.setVisible(True)
        if hasattr(self, "_radius_field"):
            self._radius_field.setVisible(not raytraced)

    def current_method(self) -> str:
        return self.method_combo.currentData() or AO_METHOD_RAYTRACED

    def _set_method(self, method: str) -> None:
        index = self.method_combo.findData(method)
        self.method_combo.setCurrentIndex(index if index >= 0 else 0)
        self._on_method_changed()

    def reset_generate_defaults(self) -> None:
        defaults = AOMapOptions()
        self._set_method(AO_METHOD_RAYTRACED)
        self.surface_width_spin.setValue(defaults.surface_width_cm)
        self.max_depth_spin.setValue(defaults.max_depth_mm)
        self.search_percent_spin.setValue(defaults.search_percent)
        self.samples_combo.setCurrentIndex(1)
        self.radius_spin.setValue(16)
        self.blur_spin.setValue(1)
        self.propertiesChanged.emit()

    def reset_to_defaults(self) -> None:
        self.strength_spin.setValue(1.0)
        self.contrast_spin.setValue(1.5)
        self.invert_checkbox.setChecked(False)
        self.reset_generate_defaults()
        self.propertiesChanged.emit()

    def current_options(self) -> AOMapOptions:
        bit_depth = 16
        return AOMapOptions(
            strength=self.strength_spin.value(),
            radius=self.radius_spin.value(),
            samples=self._get_samples_count(),
            contrast=self.contrast_spin.value(),
            blur_radius=self.blur_spin.value(),
            invert=self.invert_checkbox.isChecked(),
            bit_depth=bit_depth,
            method=self.current_method(),
            surface_width_cm=self.surface_width_spin.value(),
            max_depth_mm=self.max_depth_spin.value(),
            search_percent=self.search_percent_spin.value(),
        )

    def properties_to_dict(self) -> dict:
        return {
            "strength": self.strength_spin.value(),
            "radius": self.radius_spin.value(),
            "samples_idx": self.samples_combo.currentIndex(),
            "contrast": self.contrast_spin.value(),
            "blur_radius": self.blur_spin.value(),
            "invert": self.invert_checkbox.isChecked(),
            "method": self.current_method(),
            "surface_width_cm": self.surface_width_spin.value(),
            "max_depth_mm": self.max_depth_spin.value(),
            "search_percent": self.search_percent_spin.value(),
        }

    def properties_apply_dict(self, data: dict) -> None:
        if not data:
            return
        self.strength_spin.setValue(data.get("strength", 1.0))
        self.radius_spin.setValue(data.get("radius", 16))
        self.samples_combo.setCurrentIndex(data.get("samples_idx", 1))
        self.contrast_spin.setValue(data.get("contrast", 1.5))
        self.blur_spin.setValue(data.get("blur_radius", 1))
        self.invert_checkbox.setChecked(data.get("invert", False))
        defaults = AOMapOptions()
        self._set_method(data.get("method", AO_METHOD_CLASSIC))
        self.surface_width_spin.setValue(data.get("surface_width_cm", defaults.surface_width_cm))
        self.max_depth_spin.setValue(data.get("max_depth_mm", defaults.max_depth_mm))
        self.search_percent_spin.setValue(data.get("search_percent", defaults.search_percent))

    to_options_dict = properties_to_dict
    apply_options_dict = properties_apply_dict
