from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QWidget,
)

from core.depth_models import LEGACY_VARIANTS, MODEL_CATALOG
from core.height_map import (
    DEFAULT_BOWL_CURVE,
    DETREND_HIGHPASS,
    DETREND_NONE,
    DETREND_PLANE,
    DETREND_QUADRATIC,
    HeightMapOptions,
)
from ui.curve_editor import CurveEditorDialog
from ui.panels.base import GeneratePropertiesContainer
import sys

from ui.value_controls import Knob

def _build_device_map() -> dict[str, str]:
    if sys.platform == "darwin":
        return {
            "Auto": "auto",
            "Apple Silicon (MPS)": "mps",
            "CPU": "cpu",
        }
    return {
        "Auto": "auto",
        "GPU (CUDA)": "cuda",
        "CPU": "cpu",
    }


DEVICE_MAP = _build_device_map()

DETREND_MAP = {
    "Remove bowl/dome (recommended)": DETREND_QUADRATIC,
    "Remove tilt (plane)": DETREND_PLANE,
    "High-pass (subtract blur)": DETREND_HIGHPASS,
    "None (raw model depth)": DETREND_NONE,
}


class HeightPanel(GeneratePropertiesContainer):
    modelSettingsChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bowl_curve_x: list[tuple[float, float]] = list(DEFAULT_BOWL_CURVE)
        self._bowl_curve_y: list[tuple[float, float]] = list(DEFAULT_BOWL_CURVE)
        self._bowl_curve: list[tuple[float, float]] = self._bowl_curve_x
        self._raw_source_provider = None

        self.note_label = QLabel(
            "No Albedo source yet, so the button below has nothing to work from "
            "(you can still import a Height image directly instead)."
        )
        self.note_label.setWordWrap(True)
        self.note_label.setStyleSheet("color: #e5a50a;")  # warning yellow, readable in light and dark
        self.generate_page.add_wide(self.note_label)

        self._build_model_group()
        self._build_chunk_group()
        self._build_seamless_gen_group()
        self.generate_page.add_stretch()

        self._build_settings_group()
        self.properties_page.add_stretch()

    def set_has_albedo(self, has_albedo: bool) -> None:
        self.note_label.setVisible(not has_albedo)

    def set_raw_source_provider(self, provider) -> None:
        self._raw_source_provider = provider

    def _build_model_group(self) -> None:
        page = self.generate_page
        page.add_section("Depth Model", expanded=True)

        self.family_combo = QComboBox()
        self.family_combo.addItems(list(MODEL_CATALOG.keys()))
        self.family_combo.currentTextChanged.connect(self._on_family_changed)
        self.family_combo.setToolTip("Which AI depth model estimates the relief.")
        page.add_param("Model", self.family_combo, wide=True)

        self.variant_combo = QComboBox()
        self.variant_combo.currentTextChanged.connect(self.modelSettingsChanged.emit)
        self.variant_combo.setToolTip(
            "Larger models give more detail but are slower and need more memory.\n"
            "Depth Anything V2 Base and Large may only be used for non-commercial work (CC BY-NC 4.0)."
        )

        self.device_combo = QComboBox()
        self.device_combo.addItems(list(DEVICE_MAP.keys()))
        self.device_combo.currentTextChanged.connect(self.modelSettingsChanged.emit)
        self.device_combo.setToolTip("Where the model runs. GPU is much faster when available.")
        page.add_pair(("Size", self.variant_combo), ("Run on", self.device_combo))


        self._on_family_changed(self.family_combo.currentText())

    def _on_family_changed(self, family: str) -> None:
        self.variant_combo.blockSignals(True)
        self.variant_combo.clear()
        self.variant_combo.addItems(list(MODEL_CATALOG[family].keys()))
        self.variant_combo.blockSignals(False)

        if hasattr(self, "chunk_checkbox") and hasattr(self, "chunk_batch_spin"):
            if "Marigold" in family:
                self.chunk_batch_spin.setMaximum(4)
                self.chunk_checkbox.setToolTip(
                    "Marigold produces diffusion-grade micro-relief even in single-pass mode.\n"
                    "Chunk estimation will tile 768x768 crops for extreme high-res detail."
                )
            else:
                self.chunk_batch_spin.setMaximum(16)
                self.chunk_checkbox.setToolTip(
                    "Runs one full-image reference pass, then re-runs the model on\n"
                    "overlapping crops at its native resolution for sharp micro-details.\n"
                    "Higher quality, but requires more computation."
                )

        self.modelSettingsChanged.emit()

    def selected_device(self) -> str:
        return DEVICE_MAP.get(self.device_combo.currentText(), "auto")

    def selected_family_variant(self) -> tuple[str, str]:
        return self.family_combo.currentText(), self.variant_combo.currentText()

    def set_model_status(self, text: str) -> None:
        pass

    def set_model_controls_enabled(self, enabled: bool) -> None:
        for w in (self.family_combo, self.variant_combo, self.device_combo):
            w.setEnabled(enabled)

    def _build_chunk_group(self) -> None:
        page = self.generate_page
        self.chunk_checkbox = QCheckBox("Process in tiles (sharper at high resolution)")
        self.chunk_checkbox.setToolTip(
            "Runs one full-image reference pass, then re-runs the model on\n"
            "overlapping crops at its native resolution for sharp micro-details.\n"
            "Higher quality, but requires more computation."
        )
        self.chunk_checkbox.stateChanged.connect(self._on_chunk_toggled)
        page.add_section("Full Resolution with Chunk Estimation", toggle=self.chunk_checkbox)

        self.chunk_batch_spin = QSpinBox()
        self.chunk_batch_spin.setRange(1, 16)
        self.chunk_batch_spin.setValue(1)
        self.chunk_batch_spin.setToolTip(
            "How many chunks the model works on at the same time. Higher is faster but needs more GPU memory.\n"
            "Graphics card with 8 GB or more: 2 to 4. Smaller cards: 1 or 2. On the CPU: 1."
        )
        # Kept for code that enables/disables it alongside the spin box; the label's tooltip replaces the icon.
        self.batch_info_label = QLabel()
        self.batch_info_label.hide()

        page.add_param("Batch size", self.chunk_batch_spin, plain=True)

        self.effort_combo = QComboBox()
        self.effort_combo.addItems(["ultra", "high", "medium", "low"])
        self.effort_combo.setCurrentText("high")
        self.effort_combo.setToolTip(
            "Effort (Chunk Resolution Multiplier):\n\n"
            "• ultra (0.5x tile size): Smaller chunks, highest density and micro-detail (longest time).\n"
            "• high (1.0x tile size): Native model resolution per chunk (recommended default).\n"
            "• medium (1.5x tile size): Larger chunks, faster processing.\n"
            "• low (2.0x tile size): Maximum chunk size, fastest estimation."
        )
        self.effort_combo.setToolTip("Higher quality takes longer.")
        page.add_param("Quality", self.effort_combo)

        self._on_chunk_toggled()

    def _on_chunk_toggled(self, *_args) -> None:
        enabled = self.chunk_checkbox.isChecked()
        self.chunk_batch_spin.setEnabled(enabled)
        self.batch_info_label.setEnabled(enabled)
        self.effort_combo.setEnabled(enabled)

    def is_chunked(self) -> bool:
        return self.chunk_checkbox.isChecked()

    def chunk_params(self) -> tuple[int, float, int]:
        family, _ = self.selected_family_variant()
        if "Marigold" in family:
            base_resolution = 768
        else:
            base_resolution = 518

        effort_multipliers = {
            "ultra": 0.5,
            "high": 1.0,
            "medium": 1.5,
            "low": 2.0,
        }
        effort = self.effort_combo.currentText().lower()
        multiplier = effort_multipliers.get(effort, 1.0)
        tile_size = int(round(base_resolution * multiplier))

        overlap_pct = 50.0
        batch_size = self.chunk_batch_spin.value()
        return tile_size, overlap_pct, batch_size

    def set_chunk_controls_enabled(self, enabled: bool) -> None:
        self.chunk_checkbox.setEnabled(enabled)
        if enabled:
            self._on_chunk_toggled()
        else:
            self.chunk_batch_spin.setEnabled(False)
            self.batch_info_label.setEnabled(False)
            self.effort_combo.setEnabled(False)

    def _build_seamless_gen_group(self) -> None:
        page = self.generate_page
        self.seamless_gen_checkbox = QCheckBox("Seamless")
        self.seamless_gen_checkbox.toggled.connect(self._on_seamless_gen_toggled)

        tooltip_text = (
            "Seamless Tiling (>99.8%):\n\n"
            "• Provides over 99.8% seamless continuity across borders by 3x3 tiled padding.\n"
            "• Please note: It is not 100% mathematically perfect; minor residual flaws or micro-steps\n"
            "  may still be visible upon close inspection in the extreme corner junctions."
        )
        self.seamless_gen_checkbox.setToolTip(tooltip_text)

        page.add_section("Seamless Tiling", toggle=self.seamless_gen_checkbox)

        self.force_seamless_blur_checkbox = QCheckBox("Force seamless with blur")
        self.force_seamless_blur_checkbox.setEnabled(False)
        self.force_seamless_blur_checkbox.setToolTip(
            "Force seamless with blur:\n\n"
            "• Applies a smooth band blur (edge length × 3%) along the top and left frame\n"
            "  boundary lines of the extended tile until sharp step discontinuities disappear.\n"
            "• Eliminates boundary seam artifacts before the depth model runs."
        )
        page.add_wide(self.force_seamless_blur_checkbox)
        page.end_section()

    def _on_seamless_gen_toggled(self, checked: bool) -> None:
        self.force_seamless_blur_checkbox.setEnabled(checked)
        if not checked:
            self.force_seamless_blur_checkbox.setChecked(False)

    def is_seamless_generation(self) -> bool:
        return self.seamless_gen_checkbox.isChecked()

    def is_force_seamless_blur(self) -> bool:
        return self.seamless_gen_checkbox.isChecked() and self.force_seamless_blur_checkbox.isChecked()

    def _build_settings_group(self) -> None:
        page = self.properties_page
        page.add_section("Overall Shape")

        self.detrend_combo = QComboBox()
        self.detrend_combo.addItems(list(DETREND_MAP.keys()))
        self.detrend_combo.setCurrentText("Remove bowl/dome (recommended)")
        self.detrend_combo.currentTextChanged.connect(self._on_detrend_mode_changed)
        self.detrend_combo.currentTextChanged.connect(self.propertiesChanged.emit)
        self.detrend_combo.setToolTip("Photos often make a flat surface look bowed or tilted. This flattens it.")
        page.add_param("Remove bending", self.detrend_combo)

        self.detrend_radius_spin = QDoubleSpinBox()
        self.detrend_radius_spin.setRange(1.0, 50.0)
        self.detrend_radius_spin.setValue(8.0)
        self.detrend_radius_spin.setSuffix(" %")
        self.detrend_radius_spin.valueChanged.connect(self.propertiesChanged.emit)
        self.detrend_radius_spin.setToolTip("Size of the shapes treated as unwanted bending, in % of the image. Smaller flattens more.")
        self._detrend_radius_field = page.add_param("Flatten size", self.detrend_radius_spin)

        self.edit_curve_btn = QPushButton("Edit Curve…")
        self.edit_curve_btn.clicked.connect(self._open_curve_editor)
        self.edit_curve_btn.setToolTip("Draw how much bending to remove from the center to the edges.")
        self._edit_curve_field = page.add_param("Correction curve", self.edit_curve_btn, share_cell=True)

        self.invert_checkbox = QCheckBox("Invert")
        self.invert_checkbox.setToolTip("Swap near and far: raised areas become recessed and vice versa.")
        self.invert_checkbox.stateChanged.connect(self.propertiesChanged.emit)
        page.add_param("Direction", self.invert_checkbox)

        self.gamma_spin = QDoubleSpinBox()
        self.gamma_spin.setRange(0.10, 4.00)
        self.gamma_spin.setSingleStep(0.05)
        self.gamma_spin.setValue(1.0)
        self.gamma_spin.valueChanged.connect(self.propertiesChanged.emit)
        self.gamma_spin.setToolTip("Below 1 raises the middle heights, above 1 lowers them. Highest and lowest points stay put.")
        page.add_param("Midtones", self.gamma_spin)

        page.add_section("Gaps & Cracks")

        self.local_eq_spin = QDoubleSpinBox()
        self.local_eq_spin.setRange(0.0, 1.0)
        self.local_eq_spin.setSingleStep(0.05)
        self.local_eq_spin.setValue(0.0)
        self.local_eq_spin.setToolTip(
            "Local Contrast Normalization / Baseline Leveling:\n"
            "Evens out wide macro-tilt and lighting differences across the texture,\n"
            "forcing all brick reliefs onto the same horizontal plane."
        )
        self.local_eq_spin.valueChanged.connect(self.propertiesChanged.emit)
        self.local_eq_spin.setToolTip("Puts all bumps on the same level, removing large slopes and lighting differences.")
        page.add_param("Level out", self.local_eq_spin)

        self.crevice_spin = QDoubleSpinBox()
        self.crevice_spin.setRange(-2.0, 3.0)
        self.crevice_spin.setSingleStep(0.1)
        self.crevice_spin.setValue(0.0)
        self.crevice_spin.setToolTip(
            "Morphological Joint & Crevice Depth Correction:\n"
            "> 0 pushes inverted or bright mortar lines down into deep recesses and elevates brick tops.\n"
            "< 0 softens joint depth."
        )
        self.crevice_spin.valueChanged.connect(self.propertiesChanged.emit)
        self.crevice_spin.setToolTip("Above 0 pushes gaps (like mortar between bricks) deeper. Below 0 makes them shallower.")
        page.add_param("Deepen cracks", self.crevice_spin)

        self.albedo_guidance_spin = QDoubleSpinBox()
        self.albedo_guidance_spin.setRange(0.0, 1.0)
        self.albedo_guidance_spin.setSingleStep(0.05)
        self.albedo_guidance_spin.setValue(0.0)
        self.albedo_guidance_spin.setToolTip(
            "Albedo Contrast Guidance:\n"
            "Uses color boundaries and contrast from the source Albedo image\n"
            "to clamp joint lines to the bottom floor."
        )
        self.albedo_guidance_spin.valueChanged.connect(self.propertiesChanged.emit)
        self.albedo_guidance_spin.setToolTip("Uses color edges in the photo to keep gaps at the bottom. Helps with bricks and tiles.")
        page.add_param("Use photo edges", self.albedo_guidance_spin)

        page.add_section("Tone & Smoothing")

        self.blur_spin = QSpinBox()
        self.blur_spin.setRange(0, 25)
        self.blur_spin.valueChanged.connect(self.propertiesChanged.emit)
        self.blur_spin.setToolTip("Blurs the height map to remove noise.")
        page.add_param("Smoothing (px)", self.blur_spin)

        self.low_pct_spin = QDoubleSpinBox()
        self.low_pct_spin.setRange(0.0, 49.0)
        self.low_pct_spin.setSingleStep(0.5)
        self.low_pct_spin.setValue(1.0)
        self.low_pct_spin.valueChanged.connect(self.propertiesChanged.emit)
        self.low_pct_spin.setSuffix(" %")
        self.low_pct_spin.setToolTip("Darkest share of the surface (in %) that becomes the lowest point. Raises contrast.")
        page.add_param("Clip low", Knob(self.low_pct_spin, default=1.0))

        self.high_pct_spin = QDoubleSpinBox()
        self.high_pct_spin.setRange(51.0, 100.0)
        self.high_pct_spin.setSingleStep(0.5)
        self.high_pct_spin.setValue(99.0)
        self.high_pct_spin.valueChanged.connect(self.propertiesChanged.emit)
        self.high_pct_spin.setSuffix(" %")
        self.high_pct_spin.setToolTip("Brightest share of the surface (in %) that becomes the highest point. Raises contrast.")
        page.add_param("Clip high", Knob(self.high_pct_spin, default=99.0))

        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self.reset_to_defaults)
        page.end_section()
        page.add_wide(reset_btn)

        self._on_detrend_mode_changed(self.detrend_combo.currentText())

    def reset_to_defaults(self) -> None:
        self.detrend_combo.setCurrentText("Remove bowl/dome (recommended)")
        self.detrend_radius_spin.setValue(8.0)
        self._bowl_curve_x = list(DEFAULT_BOWL_CURVE)
        self._bowl_curve_y = list(DEFAULT_BOWL_CURVE)
        self._bowl_curve = self._bowl_curve_x
        self.invert_checkbox.setChecked(False)
        self.gamma_spin.setValue(1.0)
        self.local_eq_spin.setValue(0.0)
        self.crevice_spin.setValue(0.0)
        self.albedo_guidance_spin.setValue(0.0)
        self.blur_spin.setValue(0)
        self.low_pct_spin.setValue(1.0)
        self.high_pct_spin.setValue(99.0)
        self.propertiesChanged.emit()

    def _on_detrend_mode_changed(self, text: str) -> None:
        mode = DETREND_MAP.get(text)
        self.detrend_radius_spin.setEnabled(mode == DETREND_HIGHPASS)
        self.edit_curve_btn.setEnabled(mode == DETREND_QUADRATIC)
        if hasattr(self, "_detrend_radius_field"):
            self._detrend_radius_field.setVisible(mode == DETREND_HIGHPASS)
        if hasattr(self, "_edit_curve_field"):
            self._edit_curve_field.setVisible(mode == DETREND_QUADRATIC)

    def _open_curve_editor(self) -> None:
        raw_depth = None
        if self._raw_source_provider is not None:
            raw_depth, _ = self._raw_source_provider()

        dialog = CurveEditorDialog(
            curve_x=self._bowl_curve_x,
            curve_y=self._bowl_curve_y,
            depth=raw_depth,
            options=self.current_options(),
            parent=self.window(),
        )

        initial_x = list(self._bowl_curve_x)
        initial_y = list(self._bowl_curve_y)

        def _on_live_curves_changed(cx, cy):
            self._bowl_curve_x = cx
            self._bowl_curve_y = cy
            self._bowl_curve = cx
            self.propertiesChanged.emit()

        dialog.liveCurvesChanged.connect(_on_live_curves_changed)

        if dialog.exec() == CurveEditorDialog.DialogCode.Accepted:
            self._bowl_curve_x, self._bowl_curve_y = dialog.result_curves()
            self._bowl_curve = self._bowl_curve_x
            self.propertiesChanged.emit()
        else:
            self._bowl_curve_x = initial_x
            self._bowl_curve_y = initial_y
            self._bowl_curve = initial_x
            self.propertiesChanged.emit()

    def current_options(self) -> HeightMapOptions:
        bit_depth = 16
        return HeightMapOptions(
            invert=self.invert_checkbox.isChecked(),
            low_percentile=self.low_pct_spin.value(),
            high_percentile=self.high_pct_spin.value(),
            gamma=self.gamma_spin.value(),
            blur_radius=self.blur_spin.value(),
            bit_depth=bit_depth,
            detrend_mode=DETREND_MAP[self.detrend_combo.currentText()],
            detrend_radius_pct=self.detrend_radius_spin.value(),
            bowl_curve_x=list(self._bowl_curve_x),
            bowl_curve_y=list(self._bowl_curve_y),
            bowl_curve=list(self._bowl_curve_x),
            local_equalization=self.local_eq_spin.value(),
            crevice_suppression=self.crevice_spin.value(),
            albedo_guidance=self.albedo_guidance_spin.value(),
        )

    def bowl_curve_x(self) -> list[tuple[float, float]]:
        return list(self._bowl_curve_x)

    def bowl_curve_y(self) -> list[tuple[float, float]]:
        return list(self._bowl_curve_y)

    def set_bowl_curves(
        self,
        curve_x: list[tuple[float, float]],
        curve_y: list[tuple[float, float]],
    ) -> None:
        self._bowl_curve_x = list(curve_x)
        self._bowl_curve_y = list(curve_y)
        self._bowl_curve = self._bowl_curve_x

    def bowl_curve(self) -> list[tuple[float, float]]:
        return list(self._bowl_curve_x)

    def set_bowl_curve(self, curve: list[tuple[float, float]]) -> None:
        self._bowl_curve_x = list(curve)
        self._bowl_curve_y = list(curve)
        self._bowl_curve = self._bowl_curve_x

    def generate_to_dict(self) -> dict:
        family, variant = self.selected_family_variant()
        return {
            "family": family,
            "variant": variant,
            "device": self.device_combo.currentText(),
            "chunked": self.chunk_checkbox.isChecked(),
            "chunk_batch": self.chunk_batch_spin.value(),
            "effort": self.effort_combo.currentText(),
            "seamless_generation": self.seamless_gen_checkbox.isChecked(),
            "force_seamless_blur": self.force_seamless_blur_checkbox.isChecked(),
        }

    def generate_apply_dict(self, data: dict) -> None:
        if not data:
            return
        target_dev = data.get("device", self.device_combo.currentText())
        idx = self.device_combo.findText(target_dev)
        if idx >= 0:
            self.device_combo.setCurrentIndex(idx)
        else:
            self.device_combo.setCurrentIndex(0)
        self.family_combo.setCurrentText(data.get("family", self.family_combo.currentText()))
        variant = data.get("variant", self.variant_combo.currentText())
        self.variant_combo.setCurrentText(LEGACY_VARIANTS.get(variant, variant))
        self.chunk_checkbox.setChecked(data.get("chunked", False))
        self.chunk_batch_spin.setValue(data.get("chunk_batch", self.chunk_batch_spin.value()))
        self.effort_combo.setCurrentText(data.get("effort", "high"))
        self.seamless_gen_checkbox.setChecked(data.get("seamless_generation", False))
        self.force_seamless_blur_checkbox.setChecked(data.get("force_seamless_blur", False))

    def properties_to_dict(self) -> dict:
        return {
            "detrend": self.detrend_combo.currentText(),
            "detrend_radius": self.detrend_radius_spin.value(),
            "bowl_curve_x": list(self._bowl_curve_x),
            "bowl_curve_y": list(self._bowl_curve_y),
            "bowl_curve": list(self._bowl_curve_x),
            "invert": self.invert_checkbox.isChecked(),
            "gamma": self.gamma_spin.value(),
            "local_equalization": self.local_eq_spin.value(),
            "crevice_suppression": self.crevice_spin.value(),
            "albedo_guidance": self.albedo_guidance_spin.value(),
            "blur": self.blur_spin.value(),
            "low_pct": self.low_pct_spin.value(),
            "high_pct": self.high_pct_spin.value(),
        }

    def properties_apply_dict(self, data: dict) -> None:
        if not data:
            return
        self.detrend_combo.setCurrentText(data.get("detrend", self.detrend_combo.currentText()))
        self.detrend_radius_spin.setValue(data.get("detrend_radius", self.detrend_radius_spin.value()))
        legacy_curve = data.get("bowl_curve", self._bowl_curve_x)
        self._bowl_curve_x = data.get("bowl_curve_x", legacy_curve)
        self._bowl_curve_y = data.get("bowl_curve_y", legacy_curve)
        self._bowl_curve = self._bowl_curve_x
        self.invert_checkbox.setChecked(data.get("invert", False))
        self.gamma_spin.setValue(data.get("gamma", self.gamma_spin.value()))
        self.local_eq_spin.setValue(data.get("local_equalization", self.local_eq_spin.value()))
        self.crevice_spin.setValue(data.get("crevice_suppression", self.crevice_spin.value()))
        self.albedo_guidance_spin.setValue(data.get("albedo_guidance", self.albedo_guidance_spin.value()))
        self.blur_spin.setValue(data.get("blur", self.blur_spin.value()))
        self.low_pct_spin.setValue(data.get("low_pct", self.low_pct_spin.value()))
        self.high_pct_spin.setValue(data.get("high_pct", self.high_pct_spin.value()))


    def to_options_dict(self) -> dict:
        return {**self.generate_to_dict(), **self.properties_to_dict()}

    def apply_options_dict(self, data: dict) -> None:
        self.generate_apply_dict(data)
        self.properties_apply_dict(data)
