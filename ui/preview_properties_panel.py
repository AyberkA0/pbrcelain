from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui.theme import IS_MAC

MESH_LABELS = {"sphere": "Sphere", "cube": "Cube", "plane": "Plane"}
MESH_VALUES = {v: k for k, v in MESH_LABELS.items()}
DEFAULT_MESH = "plane"


class PreviewPropertiesPanel(QWidget):
    settingsChanged = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PreviewPropertiesPanel")
        self._hdri_path: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        tabs_row = QHBoxLayout()
        tabs_row.setContentsMargins(6, 2, 6, 4)
        tabs_row.setSpacing(2)
        tab_host_layout = tabs_row
        if IS_MAC:
            tabs_row.setContentsMargins(14, 2, 14, 4)
            segment = QWidget()
            segment.setObjectName("SubtabBar")
            segment.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            tab_host_layout = QHBoxLayout(segment)
            tab_host_layout.setContentsMargins(2, 2, 2, 2)
            tab_host_layout.setSpacing(2)
            tabs_row.addWidget(segment, 1)

        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)
        self._stack = QStackedWidget()
        pages = (
            ("Geometry", self._build_geometry_group),
            ("Display", self._build_display_group),
            ("Camera", self._build_camera_group),
            ("Lighting", self._build_lighting_group),
            ("Parallax", self._build_parallax_group),
            ("Environment", self._build_environment_group),
        )
        for index, (title, build) in enumerate(pages):
            btn = QPushButton(title)
            btn.setCheckable(True)
            btn.setProperty("role", "subtab")
            btn.setStyleSheet("padding-left: 2px; padding-right: 2px;")
            btn.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            btn.setMinimumWidth(0)
            self._tab_group.addButton(btn, index)
            tab_host_layout.addWidget(btn, btn.fontMetrics().horizontalAdvance(title) + 16)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(8, 4, 8, 8)
            page_layout.addWidget(build())
            page_layout.addStretch(1)
            scroll.setWidget(page)
            self._stack.addWidget(scroll)
        if not IS_MAC:
            tabs_row.addStretch(1)

        self._tab_group.button(0).setChecked(True)
        self._tab_group.idClicked.connect(self._on_tab_clicked)

        outer.addLayout(tabs_row)
        outer.addWidget(self._stack, 1)

    tabChanged = pyqtSignal()

    def _on_tab_clicked(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self.tabChanged.emit()

    def content_height(self) -> int:
        """Height needed to show the current tab without scrolling."""
        page = self._stack.currentWidget().widget()
        tabs = self.layout().itemAt(0).sizeHint().height()
        return tabs + page.sizeHint().height() + 4

    def _build_geometry_group(self) -> QWidget:
        group = QWidget()
        layout = QFormLayout(group)

        self.mesh_combo = QComboBox()
        self.mesh_combo.addItems([MESH_LABELS["plane"], MESH_LABELS["sphere"], MESH_LABELS["cube"]])
        self.mesh_combo.currentTextChanged.connect(self._emit_changed)

        layout.addRow("Mesh:", self.mesh_combo)
        return group

    def _build_camera_group(self) -> QWidget:
        group = QWidget()
        layout = QFormLayout(group)

        self.fov_spin = QDoubleSpinBox()
        self.fov_spin.setRange(20.0, 100.0)
        self.fov_spin.setValue(75.0)
        self.fov_spin.setSuffix("°")
        self.fov_spin.valueChanged.connect(self._emit_changed)

        self.distance_spin = QDoubleSpinBox()
        self.distance_spin.setRange(0.01, 20.0)
        self.distance_spin.setSingleStep(0.1)
        self.distance_spin.setDecimals(2)
        self.distance_spin.setValue(3.5)
        self.distance_spin.valueChanged.connect(self._emit_changed)

        self.rotation_speed_spin = QDoubleSpinBox()
        self.rotation_speed_spin.setRange(0.0, 5.0)
        self.rotation_speed_spin.setSingleStep(0.1)
        self.rotation_speed_spin.setValue(0.5)
        self.rotation_speed_spin.valueChanged.connect(self._emit_changed)

        self.pivot_x_spin = QDoubleSpinBox()
        self.pivot_x_spin.setRange(-50.0, 50.0)
        self.pivot_x_spin.setSingleStep(0.1)
        self.pivot_x_spin.setDecimals(2)
        self.pivot_x_spin.setValue(0.0)
        self.pivot_x_spin.valueChanged.connect(self._emit_changed)

        self.pivot_y_spin = QDoubleSpinBox()
        self.pivot_y_spin.setRange(-50.0, 50.0)
        self.pivot_y_spin.setSingleStep(0.1)
        self.pivot_y_spin.setDecimals(2)
        self.pivot_y_spin.setValue(0.0)
        self.pivot_y_spin.valueChanged.connect(self._emit_changed)

        self.pivot_z_spin = QDoubleSpinBox()
        self.pivot_z_spin.setRange(-50.0, 50.0)
        self.pivot_z_spin.setSingleStep(0.1)
        self.pivot_z_spin.setDecimals(2)
        self.pivot_z_spin.setValue(0.0)
        self.pivot_z_spin.valueChanged.connect(self._emit_changed)

        layout.addRow("FOV:", self.fov_spin)
        layout.addRow("Distance:", self.distance_spin)
        layout.addRow("Rotation Speed:", self.rotation_speed_spin)
        layout.addRow("Pivot X:", self.pivot_x_spin)
        layout.addRow("Pivot Y:", self.pivot_y_spin)
        layout.addRow("Pivot Z:", self.pivot_z_spin)

        reset_pivot_btn = QPushButton("Reset Pivot")
        reset_pivot_btn.setToolTip("Reset camera target pivot point back to (0, 0, 0)")
        reset_pivot_btn.clicked.connect(self._reset_pivot)
        layout.addRow("", reset_pivot_btn)
        return group

    def _build_lighting_group(self) -> QWidget:
        group = QWidget()
        layout = QFormLayout(group)

        self.light_intensity_spin = QDoubleSpinBox()
        self.light_intensity_spin.setRange(0.0, 5.0)
        self.light_intensity_spin.setSingleStep(0.1)
        self.light_intensity_spin.setValue(1.2)
        self.light_intensity_spin.valueChanged.connect(self._emit_changed)

        self.env_intensity_spin = QDoubleSpinBox()
        self.env_intensity_spin.setRange(0.0, 5.0)
        self.env_intensity_spin.setSingleStep(0.1)
        self.env_intensity_spin.setValue(1.0)
        self.env_intensity_spin.valueChanged.connect(self._emit_changed)

        self.exposure_spin = QDoubleSpinBox()
        self.exposure_spin.setRange(0.1, 4.0)
        self.exposure_spin.setSingleStep(0.1)
        self.exposure_spin.setValue(1.0)
        self.exposure_spin.valueChanged.connect(self._emit_changed)

        self.light_azimuth_spin = QDoubleSpinBox()
        self.light_azimuth_spin.setRange(0.0, 360.0)
        self.light_azimuth_spin.setSingleStep(5.0)
        self.light_azimuth_spin.setValue(45.0)
        self.light_azimuth_spin.setSuffix("°")
        self.light_azimuth_spin.setToolTip("Compass direction the light comes from, around the vertical axis.")
        self.light_azimuth_spin.valueChanged.connect(self._emit_changed)

        self.light_elevation_spin = QDoubleSpinBox()
        self.light_elevation_spin.setRange(-90.0, 90.0)
        self.light_elevation_spin.setSingleStep(5.0)
        self.light_elevation_spin.setValue(50.0)
        self.light_elevation_spin.setSuffix("°")
        self.light_elevation_spin.setToolTip("Height of the light above (positive) or below (negative) the horizon.")
        self.light_elevation_spin.valueChanged.connect(self._emit_changed)

        layout.addRow("Light Intensity:", self.light_intensity_spin)
        layout.addRow("Environment Intensity:", self.env_intensity_spin)
        layout.addRow("Exposure:", self.exposure_spin)
        layout.addRow("Light Azimuth:", self.light_azimuth_spin)
        layout.addRow("Light Elevation:", self.light_elevation_spin)
        return group

    def _build_display_group(self) -> QWidget:
        group = QWidget()
        layout = QFormLayout(group)

        self.show_grid_checkbox = QCheckBox()
        self.show_grid_checkbox.stateChanged.connect(self._emit_changed)

        self.auto_rotate_checkbox = QCheckBox()
        self.auto_rotate_checkbox.setChecked(True)
        self.auto_rotate_checkbox.stateChanged.connect(self._emit_changed)

        self.wireframe_checkbox = QCheckBox()
        self.wireframe_checkbox.stateChanged.connect(self._emit_changed)

        self.uv_tiling_spin = QDoubleSpinBox()
        self.uv_tiling_spin.setRange(1.0, 5.0)
        self.uv_tiling_spin.setSingleStep(0.5)
        self.uv_tiling_spin.setValue(1.0)
        self.uv_tiling_spin.setSuffix("x")
        self.uv_tiling_spin.setToolTip("Tile the texture across the surface to test seamless wrapping.")
        self.uv_tiling_spin.valueChanged.connect(self._emit_changed)

        layout.addRow("Show Grid:", self.show_grid_checkbox)
        layout.addRow("Auto Rotate:", self.auto_rotate_checkbox)
        layout.addRow("Wireframe Mode:", self.wireframe_checkbox)
        layout.addRow("UV Tiling:", self.uv_tiling_spin)
        return group

    def _build_parallax_group(self) -> QWidget:
        group = QWidget()
        layout = QFormLayout(group)

        self.pom_enabled_checkbox = QCheckBox()
        self.pom_enabled_checkbox.setChecked(True)
        self.pom_enabled_checkbox.setToolTip("Uses the Height map to add view-dependent surface depth in the viewport.")
        self.pom_enabled_checkbox.stateChanged.connect(self._emit_changed)

        self.pom_depth_spin = QDoubleSpinBox()
        self.pom_depth_spin.setRange(0.0, 0.20)
        self.pom_depth_spin.setSingleStep(0.005)
        self.pom_depth_spin.setDecimals(3)
        self.pom_depth_spin.setValue(0.04)
        self.pom_depth_spin.setToolTip("UV-space parallax depth. Keep low to avoid stretched detail at grazing angles.")
        self.pom_depth_spin.valueChanged.connect(self._emit_changed)

        self.pom_quality_spin = QSpinBox()
        self.pom_quality_spin.setRange(8, 64)
        self.pom_quality_spin.setSingleStep(4)
        self.pom_quality_spin.setValue(32)
        self.pom_quality_spin.setToolTip("Maximum ray-march layers. Higher improves grazing angles but costs GPU time.")
        self.pom_quality_spin.valueChanged.connect(self._emit_changed)

        layout.addRow("Enable POM:", self.pom_enabled_checkbox)
        layout.addRow("Depth:", self.pom_depth_spin)
        layout.addRow("Quality:", self.pom_quality_spin)
        return group

    def _build_environment_group(self) -> QWidget:
        group = QWidget()
        layout = QFormLayout(group)

        hdri_row = QHBoxLayout()
        self.hdri_edit = QLineEdit()
        self.hdri_edit.setReadOnly(True)
        self.hdri_edit.setPlaceholderText("None")
        hdri_browse_btn = QPushButton("Browse…")
        hdri_browse_btn.clicked.connect(self._browse_hdri)
        hdri_clear_btn = QPushButton("Clear")
        hdri_clear_btn.clicked.connect(self._clear_hdri)
        hdri_row.addWidget(self.hdri_edit, 1)
        hdri_row.addWidget(hdri_browse_btn)
        hdri_row.addWidget(hdri_clear_btn)

        self.background_brightness_spin = QDoubleSpinBox()
        self.background_brightness_spin.setRange(0.0, 3.0)
        self.background_brightness_spin.setSingleStep(0.1)
        self.background_brightness_spin.setValue(1.0)
        self.background_brightness_spin.valueChanged.connect(self._emit_changed)

        layout.addRow("HDRI Selection:", hdri_row)
        layout.addRow("Background Brightness:", self.background_brightness_spin)
        return group

    def _browse_hdri(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select HDRI / Environment Image", "", "Images (*.png *.jpg *.jpeg)")
        if path:
            self._hdri_path = path
            self.hdri_edit.setText(path)
            self._emit_changed()

    def _clear_hdri(self) -> None:
        self._hdri_path = None
        self.hdri_edit.clear()
        self._emit_changed()

    def _emit_changed(self, *_args) -> None:
        self.settingsChanged.emit(self.get_settings())

    def _reset_pivot(self) -> None:
        self.pivot_x_spin.setValue(0.0)
        self.pivot_y_spin.setValue(0.0)
        self.pivot_z_spin.setValue(0.0)

    def get_settings(self) -> dict:
        return {
            "mesh": MESH_VALUES.get(self.mesh_combo.currentText(), DEFAULT_MESH),
            "fov": self.fov_spin.value(),
            "distance": self.distance_spin.value(),
            "rotation_speed": self.rotation_speed_spin.value(),
            "pivot_x": self.pivot_x_spin.value(),
            "pivot_y": self.pivot_y_spin.value(),
            "pivot_z": self.pivot_z_spin.value(),
            "light_intensity": self.light_intensity_spin.value(),
            "env_intensity": self.env_intensity_spin.value(),
            "exposure": self.exposure_spin.value(),
            "light_azimuth": self.light_azimuth_spin.value(),
            "light_elevation": self.light_elevation_spin.value(),
            "show_grid": self.show_grid_checkbox.isChecked(),
            "auto_rotate": self.auto_rotate_checkbox.isChecked(),
            "wireframe": self.wireframe_checkbox.isChecked(),
            "uv_tiling": self.uv_tiling_spin.value(),
            "pom_enabled": self.pom_enabled_checkbox.isChecked(),
            "pom_height_scale": self.pom_depth_spin.value(),
            "pom_max_layers": self.pom_quality_spin.value(),
            "hdri_path": self._hdri_path,
            "background_brightness": self.background_brightness_spin.value(),
        }

    def apply_settings(self, data: dict) -> None:
        if not data:
            return
        self.mesh_combo.setCurrentText(MESH_LABELS.get(data.get("mesh", DEFAULT_MESH), MESH_LABELS[DEFAULT_MESH]))
        self.fov_spin.setValue(data.get("fov", self.fov_spin.value()))
        self.distance_spin.setValue(data.get("distance", self.distance_spin.value()))
        self.rotation_speed_spin.setValue(data.get("rotation_speed", self.rotation_speed_spin.value()))
        self.pivot_x_spin.setValue(data.get("pivot_x", self.pivot_x_spin.value()))
        self.pivot_y_spin.setValue(data.get("pivot_y", self.pivot_y_spin.value()))
        self.pivot_z_spin.setValue(data.get("pivot_z", self.pivot_z_spin.value()))
        self.light_intensity_spin.setValue(data.get("light_intensity", self.light_intensity_spin.value()))
        self.env_intensity_spin.setValue(data.get("env_intensity", self.env_intensity_spin.value()))
        self.exposure_spin.setValue(data.get("exposure", self.exposure_spin.value()))
        self.light_azimuth_spin.setValue(data.get("light_azimuth", self.light_azimuth_spin.value()))
        self.light_elevation_spin.setValue(data.get("light_elevation", self.light_elevation_spin.value()))
        self.show_grid_checkbox.setChecked(data.get("show_grid", False))
        self.auto_rotate_checkbox.setChecked(data.get("auto_rotate", True))
        self.wireframe_checkbox.setChecked(data.get("wireframe", False))
        self.uv_tiling_spin.setValue(data.get("uv_tiling", self.uv_tiling_spin.value()))
        self.pom_enabled_checkbox.setChecked(data.get("pom_enabled", True))
        self.pom_depth_spin.setValue(data.get("pom_height_scale", self.pom_depth_spin.value()))
        self.pom_quality_spin.setValue(data.get("pom_max_layers", self.pom_quality_spin.value()))
        self._hdri_path = data.get("hdri_path")
        self.hdri_edit.setText(self._hdri_path or "")
        self.background_brightness_spin.setValue(data.get("background_brightness", self.background_brightness_spin.value()))

    def set_distance_value(self, val: float) -> None:
        self.distance_spin.blockSignals(True)
        self.distance_spin.setValue(val)
        self.distance_spin.blockSignals(False)

    def set_pivot_values(self, x: float, y: float, z: float) -> None:
        self.pivot_x_spin.blockSignals(True)
        self.pivot_y_spin.blockSignals(True)
        self.pivot_z_spin.blockSignals(True)
        self.pivot_x_spin.setValue(x)
        self.pivot_y_spin.setValue(y)
        self.pivot_z_spin.setValue(z)
        self.pivot_x_spin.blockSignals(False)
        self.pivot_y_spin.blockSignals(False)
        self.pivot_z_spin.blockSignals(False)

    def set_light_values(self, az: float, el: float) -> None:
        self.light_azimuth_spin.blockSignals(True)
        self.light_elevation_spin.blockSignals(True)
        self.light_azimuth_spin.setValue(az)
        self.light_elevation_spin.setValue(el)
        self.light_azimuth_spin.blockSignals(False)
        self.light_elevation_spin.blockSignals(False)

    def set_auto_rotate(self, val: bool) -> None:
        self.auto_rotate_checkbox.blockSignals(True)
        self.auto_rotate_checkbox.setChecked(val)
        self.auto_rotate_checkbox.blockSignals(False)
