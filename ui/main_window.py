from __future__ import annotations

import os
from dataclasses import replace
from typing import Optional

import numpy as np
from PIL import Image
from PyQt6.QtCore import QEvent, QSettings, QSize, QTimer, Qt
from PyQt6.QtGui import QAction, QColor, QKeySequence, QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QSizePolicy,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QMenu,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.depth_models import DepthResult
from core.depth_process import RemoteDepthEstimator
from core.height_map import (
    apply_force_seamless_blur,
    apply_seamless_linear_mask,
    build_height_map,
    build_seamless_extended_tile,
    downsample_for_preview,
)
from core.height_map import to_image as height_map_to_image
from core.maps import MAP_TYPE_LABELS, MAP_TYPE_ORDER, MapType
from core.normal_map import generate_normal_map
from core.normal_map import to_image as normal_map_to_image
from core.project import PROJECT_EXTENSION, PROJECT_FILE_FILTER, MapSlotData, ProjectData, is_project_path
from core.roughness_map import generate_roughness_map
from core.roughness_map import to_image as roughness_map_to_image
from core.ao_map import generate_ao_map
from core.curvature_map import generate_curvature_map
from core.curvature_map import to_image as curvature_map_to_image
from core.ao_map import to_image as ao_map_to_image
from core.albedo_adjust import apply_albedo_adjustments
from ui.panels.albedo_panel import AlbedoPanel
from ui.panels.height_panel import HeightPanel
from ui.panels.normal_panel import NormalPanel
from ui.panels.roughness_panel import RoughnessPanel
from ui.panels.ao_panel import AOPanel
from ui.preview_3d import Preview3DWidget
from ui.preview_properties_panel import PreviewPropertiesPanel
from ui.progress_dialog import OperationProgressDialog
from ui import mac_window, window_layout
from ui.theme import IS_MAC, IS_WINDOWS, PLATFORM_THEME, legacy_style, pick, theme_changed
from ui.tiled_preview_dialog import TiledPreviewDialog
from ui.export_dialog import ExportDialog
from ui.history import History, Snapshot
from ui.icons import overlay_icon, slot_icon, subtle_icon, themed_icon
from ui.widgets import IMAGE_EXTENSIONS, ImageLabel, PulseGlow, SlotButton, ToggleHeading
from ui.workers import (
    AIRuntimeInstallWorker,
    ExportWorker,
    InferenceWorker,
    ModelLoadWorker,
    ProjectLoadWorker,
    ProjectSaveWorker,
    PropertiesPreviewWorker,
    SingleImageSaveWorker,
)


def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    if img.mode == "RGB":
        data = img.tobytes("raw", "RGB")
        qimg = QImage(data, img.width, img.height, img.width * 3, QImage.Format.Format_RGB888)
    elif img.mode in ("I;16", "I"):
        arr = (np.asarray(img, dtype=np.float32) / 256.0).clip(0, 255).astype(np.uint8)
        data = arr.tobytes()
        qimg = QImage(data, img.width, img.height, img.width, QImage.Format.Format_Grayscale8)
    elif img.mode == "F":
        arr = (np.asarray(img, dtype=np.float32) * 255.0).clip(0, 255).astype(np.uint8)
        data = arr.tobytes()
        qimg = QImage(data, img.width, img.height, img.width, QImage.Format.Format_Grayscale8)
    else:
        img = img.convert("L")
        data = img.tobytes("raw", "L")
        qimg = QImage(data, img.width, img.height, img.width, QImage.Format.Format_Grayscale8)
    return QPixmap.fromImage(qimg.copy())


def _image_to_height_array(image: Image.Image) -> np.ndarray:
    if image.mode in ("I;16", "I"):
        return np.asarray(image, dtype=np.float32) / 65535.0
    if image.mode == "F":
        return np.asarray(image, dtype=np.float32).clip(0.0, 1.0)
    return np.asarray(image.convert("L"), dtype=np.float32) / 255.0


def _image_to_normal_array(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0


class _StatusLabel(QLabel):
    """Status line whose messages fade out once they are old news. While a job
    runs its progress text stays put."""

    HOLD_MS = 6000

    def __init__(self, is_busy, parent=None):
        super().__init__("", parent)
        self._is_busy = is_busy
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.HOLD_MS)
        self._timer.timeout.connect(self._expire)

    def setText(self, text: str) -> None:
        super().setText(text)
        if text:
            self._timer.start()

    def _expire(self) -> None:
        if self._is_busy():
            self._timer.start()
        else:
            super().setText("")

    def clear_if_idle(self) -> None:
        if not self._is_busy():
            self._timer.stop()
            super().setText("")


# The main button does something different on every map, so it says what.
_GENERATE_LABELS = {
    MapType.ALBEDO: ("Apply to Albedo", "Writes the white balance, color shift and seamless settings into the Albedo map."),
    MapType.HEIGHT: ("Generate Height", "An AI depth model estimates the surface relief from the Albedo photo."),
    MapType.NORMAL: ("Generate Normal", "Calculates surface direction from the Height map. Quick, no AI."),
    MapType.ROUGHNESS: ("Generate Roughness", "Estimates how matte or shiny each spot is from the Normal map and the photo."),
    MapType.AO: ("Generate Ambient Occlusion", "Calculates the soft contact shadows in cracks and corners from the Height map."),
}

# The map each Generate button works from; without it the button is disabled.
_GENERATE_SOURCE = {
    MapType.HEIGHT: MapType.ALBEDO,
    MapType.NORMAL: MapType.HEIGHT,
    MapType.ROUGHNESS: MapType.NORMAL,
    MapType.AO: MapType.HEIGHT,
}

SIDEBAR_START_WIDTH = 370
MAP_WELL_HEIGHT = 150

RECENT_PROJECTS_KEY = "recentProjects"
MAX_RECENT_PROJECTS = 8


def _heading(text: str) -> str:
    return text if PLATFORM_THEME == "legacy" else text.title()


_VIEW_OPTIONS_EXPANDED_KEY = "window/viewOptionsExpanded"
_VIEW_OPTIONS_MARGIN = 12
_MATERIAL_THUMB = 38
_VIEW_OPTIONS_HEIGHT = 300
_VIEW_OPTIONS_WIDTH = 684
_VIEW_OPTIONS_MAX_WIDTH = 684


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1440, 860)
        if IS_MAC:
            mac_window.hide_title_bar(self)
        self._initial_layout_done = False
        self._taskbar_progress = None
        self.setAcceptDrops(True)

        self.project = ProjectData.new()
        self.project_path: Optional[str] = None
        self.dirty = False

        self.source_images: dict[MapType, Image.Image] = {}
        self.generated_images: dict[MapType, Image.Image] = {}

        self.estimator: Optional[RemoteDepthEstimator] = None
        self.model_thread: Optional[ModelLoadWorker] = None
        self.infer_thread: Optional[InferenceWorker] = None
        self._height_depth_result: Optional[DepthResult] = None
        self._generating_all = False
        self._infer_is_seamless: bool = False
        self._infer_orig_albedo_size: Optional[tuple[int, int]] = None
        self._height_before_infer: Optional[Image.Image] = None

        self.current_map_type: MapType = MapType.ALBEDO
        self._bottom_bar_mode = "generate"
        self._properties_snapshot: dict[MapType, dict] = {}
        self._draft_images: dict[MapType, Image.Image] = {}
        self.properties_preview_thread: Optional[PropertiesPreviewWorker] = None
        self._properties_preview_revision = 0
        self._properties_preview_pending = False

        self._properties_debounce = QTimer(self)
        self._properties_debounce.setSingleShot(True)
        self._properties_debounce.setInterval(180)
        self._properties_debounce.timeout.connect(self._refresh_properties_draft)

        self._slot_buttons: dict[MapType, QPushButton] = {}

        self._history = History(self._capture_state, self._restore_state, self)
        self._build_toolbar()
        self._build_history_actions()
        self._build_ui()
        self._update_window_title()
        self._reset_properties_snapshots()
        self._select_map_type(MapType.ALBEDO)
        for panel in self._panels_by_type.values():
            panel.propertiesChanged.connect(self._history.touch)
        self._history.reset()

    def _build_history_actions(self) -> None:
        self.undo_action = QAction("Undo", self)
        self.undo_action.setShortcuts([QKeySequence(QKeySequence.StandardKey.Undo)])
        self.undo_action.triggered.connect(self._undo)
        self.redo_action = QAction("Redo", self)
        self.redo_action.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence(QKeySequence.StandardKey.Redo)])
        self.redo_action.triggered.connect(self._redo)
        for action in (self.undo_action, self.redo_action):
            action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            self.addAction(action)
        if PLATFORM_THEME == "mac":
            edit_menu = self.menuBar().addMenu("Edit")
            edit_menu.addAction(self.undo_action)
            edit_menu.addAction(self.redo_action)
        self._history.changed.connect(self._update_history_actions)
        self._update_history_actions()

    def _update_history_actions(self) -> None:
        self.undo_action.setEnabled(self._history.can_undo())
        self.redo_action.setEnabled(self._history.can_redo())
        if hasattr(self, "_title_back_btn"):
            self._title_back_btn.setEnabled(self._history.can_undo())
            self._title_forward_btn.setEnabled(self._history.can_redo())

    def _refresh_title_icons(self) -> None:
        for btn, icon in getattr(self, "_title_buttons", []):
            btn.setIcon(subtle_icon(icon))

    def _toggle_sidebar(self) -> None:
        """Hide the sidebar completely, or bring it back at its previous width.
        While it is hidden the title bar (window buttons, sidebar, back and
        forward) floats over the 3D view with a transparent background."""
        splitter = self._main_splitter
        sidebar = splitter.widget(0)
        title = getattr(self, "_title_space", None)
        total = sum(splitter.sizes())
        if sidebar.isVisible():
            self._sidebar_width_before_hide = sidebar.width()
            sidebar.hide()
            if title is not None:
                self._project_section_layout.removeWidget(title)
                title.setParent(self.centralWidget())
                title.setStyleSheet("#TitleBarSpace { background: transparent; border: none; }")
                title.setGeometry(0, 0, title.sizeHint().width(), title.height())
                title.show()
                title.raise_()
        else:
            if title is not None:
                title.setStyleSheet("")
                self._project_section_layout.insertWidget(0, title)
            sidebar.show()
            width = getattr(self, "_sidebar_width_before_hide", SIDEBAR_START_WIDTH)
            splitter.setSizes([width, max(0, total - width)])

    def _is_busy(self) -> bool:
        return any(
            t is not None and t.isRunning()
            for t in (self.infer_thread, self.model_thread)
        )

    def _capture_state(self) -> Optional[Snapshot]:
        if self._is_busy():
            return None
        return Snapshot(
            source_images=dict(self.source_images),
            generated_images=dict(self.generated_images),
            height_depth=self._height_depth_result,
            panels={mt: panel.to_options_dict() for mt, panel in self._panels_by_type.items()},
            saved={mt: dict(v) for mt, v in self._properties_snapshot.items()},
            current_map=self.current_map_type,
            view=self.preview_properties_panel.get_settings(),
        )

    def _restore_state(self, snap: Snapshot) -> None:
        self._invalidate_properties_preview()
        self.source_images = dict(snap.source_images)
        self.generated_images = dict(snap.generated_images)
        self._draft_images.clear()
        self._height_depth_result = snap.height_depth
        for mt, panel in self._panels_by_type.items():
            panel.apply_options_dict(snap.panels.get(mt, {}))
        self._properties_snapshot = {mt: dict(v) for mt, v in snap.saved.items()}
        if snap.view:
            self.preview_properties_panel.apply_settings(snap.view)
            self.preview_3d.set_preview_settings(self.preview_properties_panel.get_settings())
        self._invalidate_properties_preview()
        self._mark_dirty()
        self._select_map_type(self.current_map_type)
        self._push_textures_to_preview()
        self._update_save_revert_enabled()
        panel = self._panels_by_type[self.current_map_type]
        if panel.properties_to_dict() != self._properties_snapshot.get(self.current_map_type, {}):
            self._schedule_properties_preview()

    def _undo(self) -> None:
        if self._is_busy():
            self.status_label.setText("Wait for the current job to finish before undoing.")
            return
        if self._history.undo():
            self.status_label.setText("Undone.")

    def _redo(self) -> None:
        if self._is_busy():
            return
        if self._history.redo():
            self.status_label.setText("Redone.")

    def _build_toolbar(self) -> None:
        if PLATFORM_THEME == "mac":
            self._build_mac_menu()
            return
        if PLATFORM_THEME == "windows":
            self._build_windows_commands()
            return

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        def add(text: str, handler, shortcut: Optional[str] = None) -> QAction:
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(shortcut)
            action.triggered.connect(handler)
            toolbar.addAction(action)
            return action

        add("New Project", self._new_project, "Ctrl+N")
        add("Open Project", self._open_project, "Ctrl+O")
        add("Save", self._save_project, "Ctrl+S")
        add("Save As", self._save_project_as, "Ctrl+Shift+S")
        toolbar.addSeparator()
        add("Export Maps", self._export_maps, "Ctrl+E")
        toolbar.addSeparator()
        add("Exit", self.close)

    def _build_mac_menu(self) -> None:
        file_menu = self.menuBar().addMenu("File")

        def add(text: str, handler, shortcut: str) -> None:
            action = QAction(text, self)
            action.setShortcut(shortcut)
            action.triggered.connect(handler)
            file_menu.addAction(action)

        add("New Project", self._new_project, "Ctrl+N")
        add("Open Project…", self._open_project, "Ctrl+O")
        file_menu.addSeparator()
        add("Save", self._save_project, "Ctrl+S")
        add("Save As…", self._save_project_as, "Ctrl+Shift+S")
        file_menu.addSeparator()
        add("Export Maps…", self._export_maps, "Ctrl+E")
        file_menu.insertMenu(file_menu.actions()[2], self._build_recent_menu())

        quit_action = QAction("Quit PBRCELAIN", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    def _build_windows_commands(self) -> None:
        from ui import windows_theme

        toolbar = QToolBar("Commands")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(toolbar)
        iconed: list[tuple[QAction, str]] = []

        def add(label: str, tooltip: str, handler, shortcut: str, icon: str) -> QAction:
            action = QAction(label, self)
            action.setShortcut(shortcut)
            action.setToolTip(f"{tooltip} ({action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)})")
            action.triggered.connect(handler)
            toolbar.addAction(action)
            iconed.append((action, icon))
            return action

        add("New", "New Project", self._new_project, "Ctrl+N", "new")
        open_action = add("Open", "Open Project", self._open_project, "Ctrl+O", "open")
        open_button = toolbar.widgetForAction(open_action)
        if isinstance(open_button, QToolButton):
            open_button.setMenu(self._build_recent_menu())
            open_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        toolbar.addSeparator()
        add("Save", "Save Project", self._save_project, "Ctrl+S", "save")
        add("Save As", "Save Project As", self._save_project_as, "Ctrl+Shift+S", "save_as")
        toolbar.addSeparator()
        add("Export Maps", "Export Maps", self._export_maps, "Ctrl+E", "export")

        def refresh_icons() -> None:
            for action, name in iconed:
                action.setIcon(windows_theme.themed_icon(name))

        refresh_icons()
        theme_changed.connect(refresh_icons)

    def _build_recent_menu(self) -> QMenu:
        menu = QMenu("Open &Recent", self)

        def populate() -> None:
            menu.clear()
            paths = [p for p in self._recent_projects() if os.path.isfile(p)]
            for path in paths:
                action = menu.addAction(os.path.basename(path))
                action.setToolTip(path)
                action.triggered.connect(lambda _checked=False, p=path: self._handle_dropped_project(p))
            if not paths:
                menu.addAction("No Recent Projects").setEnabled(False)
            else:
                menu.addSeparator()
                menu.addAction("Clear Menu").triggered.connect(lambda: QSettings().remove(RECENT_PROJECTS_KEY))

        menu.aboutToShow.connect(populate)
        return menu

    @staticmethod
    def _recent_projects() -> list[str]:
        value = QSettings().value(RECENT_PROJECTS_KEY, [])
        if isinstance(value, str):
            value = [value]
        return [str(p) for p in (value or [])]

    def _add_recent_project(self, path: str) -> None:
        path = os.path.abspath(path)
        paths = [p for p in self._recent_projects() if os.path.normcase(p) != os.path.normcase(path)]
        QSettings().setValue(RECENT_PROJECTS_KEY, [path, *paths][:MAX_RECENT_PROJECTS])

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(splitter)
        self._main_splitter = splitter

        splitter.addWidget(self._build_project_section())
        splitter.addWidget(self._build_preview_section())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        if PLATFORM_THEME == "legacy":
            splitter.setSizes([400, 1040])
        else:
            splitter.setChildrenCollapsible(False)
            splitter.widget(0).setMinimumWidth(pick(mac=340, windows=340))
            # Wider than this the settings just spread out; the 3D view gets the room
            # instead. The limit follows the screen (see _apply_sidebar_max).
            splitter.widget(0).setMaximumWidth(self._sidebar_max_width())
            splitter.setSizes([520, 920])

    def _build_project_section(self) -> QWidget:
        section = QWidget()
        section.setObjectName("ProjectSection")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        selector = self._build_map_selector()

        if IS_MAC:
            title_space = QWidget()
            title_space.setObjectName("TitleBarSpace")
            title_space.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            title_space.setFixedHeight(mac_window.TITLE_BAR_HEIGHT)
            mac_window.install_drag_area(title_space)
            title_row = QHBoxLayout(title_space)
            title_row.setContentsMargins(78, 0, 14, 1)
            title_row.setSpacing(4)
            self._title_buttons = []
            for icon, tip, slot in (
                ("sidebar", "Show or hide the sidebar", self._toggle_sidebar),
                ("back", "Undo", self._undo),
                ("forward", "Redo", self._redo),
            ):
                btn = QToolButton()
                btn.setAutoRaise(True)
                btn.setToolTip(tip)
                btn.setAccessibleName(tip)
                btn.setIconSize(QSize(18, 18))
                btn.setFixedSize(28, 24)
                btn.setStyleSheet(
                    "QToolButton { border: none; border-radius: 5px; background: transparent; }"
                    " QToolButton:hover { background-color: rgba(127, 127, 127, 0.22); }"
                )
                btn.clicked.connect(slot)
                title_row.addWidget(btn)
                self._title_buttons.append((btn, icon))
            if len(self._title_buttons) == 3:
                self._title_back_btn = self._title_buttons[1][0]
                self._title_forward_btn = self._title_buttons[2][0]
            title_row.addStretch(1)
            self._refresh_title_icons()
            theme_changed.connect(self._refresh_title_icons)
            layout.addWidget(title_space)
            self._title_space = title_space
            self._project_section_layout = layout

        strip = QFrame()
        strip.setObjectName("SlotStrip")
        strip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        strip_layout = QVBoxLayout(strip)
        strip_layout.setContentsMargins(0, 0, 0, 0)
        strip_layout.setSpacing(0)
        strip_layout.addWidget(self._build_material_header())
        slots_host = QWidget()
        slots_host.setLayout(self._slots_bar_layout)
        self._slots_bar_layout.setContentsMargins(*pick(mac=(14, 4, 14, 12), windows=(16, 4, 16, 12), legacy=(10, 4, 10, 10)))
        strip_layout.addWidget(slots_host)
        self._slot_strip = strip
        self._style_slot_strip()
        theme_changed.connect(self._style_slot_strip)
        layout.addWidget(strip)

        inspector = QWidget()
        inspector.setObjectName("MapInspector")
        inspector_layout = QVBoxLayout(inspector)
        inspector_layout.setContentsMargins(*pick(mac=(14, 16, 14, 16), windows=(16, 16, 16, 16), legacy=(10, 10, 10, 10)))
        inspector_layout.addLayout(selector)
        layout.addWidget(inspector)

        layout.addWidget(self._build_dynamic_panel_host(), 1)

        controls = QWidget()
        controls.setObjectName("MapInspector")
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(*pick(mac=(14, 10, 14, 12), windows=(16, 10, 16, 14), legacy=(10, 8, 10, 10)))
        controls_layout.addLayout(self._build_generate_controls())
        layout.addWidget(controls)
        return section

    def _build_map_selector(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(8)

        slots_bar = QHBoxLayout()
        slots_bar.setSpacing(4)
        for map_type in MAP_TYPE_ORDER:
            btn = SlotButton()
            btn.setProperty("role", "slot-btn")
            btn.setCheckable(True)
            btn.setAccessibleName(MAP_TYPE_LABELS[map_type])
            btn.setIconSize(QSize(20, 20))
            btn.clicked.connect(lambda _checked=False, mt=map_type: self._select_map_type(mt))
            btn.doubleClicked.connect(lambda mt=map_type: (self._select_map_type(mt), self._open_tiled_preview(mt)))
            self._slot_buttons[map_type] = btn
            slots_bar.addWidget(btn)
        self._slots_bar_layout = slots_bar

        # The map image spans the panel; its name and state sit on a translucent
        # strip in the bottom-left corner and the actions in the top-right one.
        self.selected_map_preview = ImageLabel("No map selected")
        self.selected_map_preview.setObjectName("MapWell")
        self.selected_map_preview.set_checker_background()
        self.selected_map_preview.setWordWrap(True)
        self.selected_map_preview.setMinimumWidth(48)
        self.selected_map_preview.setFixedHeight(MAP_WELL_HEIGHT)
        self.selected_map_preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.selected_map_preview.imageDropped.connect(self._on_preview_image_dropped)
        self.selected_map_preview.fileDropped.connect(self._on_other_file_dropped)
        self.selected_map_preview.doubleClicked.connect(self._open_tiled_preview)
        self.selected_map_preview.installEventFilter(self)

        self._map_caption = QWidget(self.selected_map_preview)
        self._map_caption.setObjectName("MapCaption")
        self._map_caption.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._map_caption.setStyleSheet(
            "#MapCaption { background-color: rgba(0, 0, 0, 0.55); border-radius: 6px; }"
            " QLabel { background: transparent; color: #ffffff; }"
        )
        caption_row = QHBoxLayout(self._map_caption)
        caption_row.setContentsMargins(8, 3, 8, 3)
        caption_row.setSpacing(6)
        self.active_slot_label = QLabel(MAP_TYPE_LABELS[MapType.ALBEDO])
        self.active_slot_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        self.slot_info_label = QLabel("")
        self.slot_info_label.setStyleSheet("font-size: 12px; color: rgba(255, 255, 255, 0.75);")
        caption_row.addWidget(self.active_slot_label)
        caption_row.addWidget(self.slot_info_label)

        self.upload_btn = QPushButton()
        self.upload_btn.clicked.connect(self._upload_image)
        self.save_as_btn = QPushButton()
        self.save_as_btn.clicked.connect(self._save_current_map_as)
        self.remove_btn = QPushButton()
        self.remove_btn.clicked.connect(self._remove_image)

        self._slot_action_buttons = (
            (self.upload_btn, "import", "Import", "Import an image file into the selected slot."),
            (self.save_as_btn, "export", "Export", "Save the selected map as an image file."),
            (self.remove_btn, "remove", "Remove", "Clear the selected slot's image."),
        )
        self._map_actions = QWidget(self.selected_map_preview)
        self._map_actions.setObjectName("MapActions")
        self._map_actions.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._map_actions.setStyleSheet(
            "#MapActions { background-color: rgba(0, 0, 0, 0.55); border-radius: 7px; }"
            " QPushButton { background: transparent; border: none; border-radius: 5px; padding: 0px; }"
            " QPushButton:hover { background-color: rgba(255, 255, 255, 0.18); }"
            " QPushButton:pressed { background-color: rgba(255, 255, 255, 0.28); }"
        )
        actions_row = QHBoxLayout(self._map_actions)
        actions_row.setContentsMargins(3, 3, 3, 3)
        actions_row.setSpacing(2)
        for btn, icon, name, description in self._slot_action_buttons:
            btn.setToolTip(f"<b>{name}</b><br>{description}")
            btn.setAccessibleName(name)
            btn.setIcon(overlay_icon(icon))
            btn.setIconSize(QSize(16, 16))
            btn.setFixedSize(26, 24)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            actions_row.addWidget(btn)
        theme_changed.connect(self._refresh_material_slots_bar)

        col.addWidget(self.selected_map_preview)
        return col

    def _place_map_overlays(self) -> None:
        well = self.selected_map_preview
        inset = 8
        for widget in (self._map_caption, self._map_actions):
            widget.adjustSize()
        caption = self._map_caption
        caption_width = min(caption.sizeHint().width(), well.width() - 2 * inset)
        caption.setGeometry(inset, well.height() - caption.sizeHint().height() - inset, caption_width, caption.sizeHint().height())
        actions = self._map_actions
        actions.move(well.width() - actions.width() - inset, inset)
        caption.raise_()
        actions.raise_()

    def _style_slot_strip(self) -> None:
        if PLATFORM_THEME == "mac":
            from ui import mac_theme

            dark = mac_theme.is_dark()
        elif PLATFORM_THEME == "windows":
            from ui import windows_theme

            dark = windows_theme.is_dark()
        else:
            dark = True
        tint = "rgba(0, 0, 0, 0.08)" if dark else "rgba(0, 0, 0, 0.02)"
        line = "rgba(255, 255, 255, 0.10)" if dark else "rgba(0, 0, 0, 0.12)"
        self._slot_strip.setStyleSheet(
            f"QFrame#SlotStrip {{ background-color: {tint}; border: none; border-bottom: 1px solid {line}; }}"
        )

    def _refresh_slot_info(self) -> None:
        map_type = self.current_map_type
        image = self._active_display_image(map_type)
        if image is None:
            self.slot_info_label.setText("Empty")
            self._place_map_overlays()
            return
        if map_type in self._draft_images:
            state = "Draft"
        elif map_type in self.generated_images:
            state = "Generated"
        else:
            state = "Loaded"
        self.slot_info_label.setText(f"{state} \u00b7 {image.width} \u00d7 {image.height}")
        self._place_map_overlays()

    def _build_material_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("MaterialHeader")
        row = QHBoxLayout(header)
        row.setContentsMargins(*pick(mac=(14, 10, 10, 8), windows=(16, 10, 12, 8), legacy=(10, 8, 8, 6)))
        row.setSpacing(10)

        self.material_thumb = QLabel()
        self.material_thumb.setFixedSize(_MATERIAL_THUMB, _MATERIAL_THUMB)
        row.addWidget(self.material_thumb)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        self.material_name_label = QLabel("")
        self.material_name_label.setProperty("role", "slot-title")
        self.material_info_label = QLabel("")
        self.material_info_label.setProperty("role", "dim")
        text_col.addStretch(1)
        text_col.addWidget(self.material_name_label)
        text_col.addWidget(self.material_info_label)
        text_col.addStretch(1)
        row.addLayout(text_col, 1)

        menu = QMenu(self)
        for text, handler in (
            ("New Project", self._new_project),
            ("Open Project…", self._open_project),
            (None, None),
            ("Save", self._save_project),
            ("Save As…", self._save_project_as),
            (None, None),
            ("Export Maps…", self._export_maps),
        ):
            if text is None:
                menu.addSeparator()
            else:
                menu.addAction(text, handler)
        self.material_menu_btn = QToolButton()
        self.material_menu_btn.setToolTip("Project actions")
        self.material_menu_btn.setAutoRaise(True)
        self.material_menu_btn.setIconSize(QSize(16, 16))
        self.material_menu_btn.setMenu(menu)
        self.material_menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.material_menu_btn.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0px; }")
        self.material_menu_btn.setIcon(themed_icon("more"))
        theme_changed.connect(lambda: self.material_menu_btn.setIcon(themed_icon("more")))
        row.addWidget(self.material_menu_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        return header

    def _update_next_step_pulse(self) -> None:
        """An empty project points at the map to create first: the Albedo slot
        breathes softly until an albedo image is imported."""
        btn = self._slot_buttons.get(MapType.ALBEDO)
        if btn is None:
            return
        if getattr(self, "_next_step_pulse", None) is None:
            self._next_step_pulse = PulseGlow(btn, self._accent_qcolor(), host=self._slot_strip)
            theme_changed.connect(lambda: self._next_step_pulse.set_color(self._accent_qcolor()))
        if MapType.ALBEDO in self.source_images or self.generated_images:
            self._next_step_pulse.stop()
        else:
            self._next_step_pulse.start()

    def _accent_qcolor(self):
        from PyQt6.QtGui import QColor

        if PLATFORM_THEME == "mac":
            from ui import mac_theme

            return mac_theme.accent_color()
        from ui.theme import ACCENT

        return QColor(ACCENT)

    def _refresh_material_header(self) -> None:
        if not hasattr(self, "material_name_label"):
            return
        if getattr(self, "_bottom_bar_mode", None) == "generate" and hasattr(self, "generate_btn"):
            self._update_generate_bar_mode("generate")
        name = os.path.splitext(os.path.basename(self.project_path))[0] if self.project_path else "Untitled"
        self.material_name_label.setText(f"{name}*" if self.dirty else name)
        maps = [mt for mt in MAP_TYPE_ORDER if self._active_display_image(mt) is not None]
        info = f"{len(maps)} of {len(MAP_TYPE_ORDER)} maps"
        albedo = self._active_display_image(MapType.ALBEDO)
        if albedo is not None:
            info += f" \u00b7 {albedo.width} \u00d7 {albedo.height}"
        self.material_info_label.setText(info)
        self.material_thumb.setPixmap(self._material_thumb_pixmap(albedo))

    def _material_thumb_pixmap(self, albedo: Optional[Image.Image]) -> QPixmap:
        from PyQt6.QtGui import QBrush, QColor, QPainter, QPainterPath

        ratio = self.devicePixelRatioF()
        size = int(_MATERIAL_THUMB * ratio)
        out = QPixmap(size, size)
        out.fill(Qt.GlobalColor.transparent)
        painter = QPainter(out)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addEllipse(1, 1, size - 2, size - 2)
        if albedo is not None:
            thumb = albedo.convert("RGB").copy()
            thumb.thumbnail((size * 2, size * 2))
            pix = pil_to_qpixmap(thumb).scaled(
                size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation
            )
            painter.setClipPath(path)
            painter.drawPixmap(0, 0, pix)
            painter.setClipping(False)
        else:
            color = self.palette().color(self.foregroundRole())
            color.setAlphaF(0.12)
            painter.fillPath(path, QBrush(color))
        edge = self.palette().color(self.foregroundRole())
        edge.setAlphaF(0.18)
        painter.setPen(edge)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.end()
        out.setDevicePixelRatio(ratio)
        return out

    def _refresh_material_slots_bar(self) -> None:
        self._refresh_material_header()
        self._update_next_step_pulse()
        for map_type, btn in self._slot_buttons.items():
            btn.setChecked(map_type == self.current_map_type)
            if map_type in self._draft_images:
                state, color, filled = "Draft (unsaved adjustment)", "#f5a524", True
            elif map_type in self.generated_images:
                state, color, filled = "Generated", "#30a46c", True
            elif map_type in self.source_images:
                state, color, filled = "Loaded", "#4a72d9", True
            else:
                state, color, filled = "Empty", "#8e8e93", False
            btn.setIcon(slot_icon(f"map-{map_type.value}", color, filled))
            btn.setToolTip(
                f"<b>{MAP_TYPE_LABELS[map_type]}</b> \u2014 {state}<br>"
                "Click to select, double-click to open the 2x2 tiled preview."
            )

    def _build_dynamic_panel_host(self) -> QWidget:
        host = QWidget()
        host.setObjectName("DynamicPanelHost")
        layout = QVBoxLayout(host)

        self.stacked_panels = QStackedWidget()
        self.height_panel = HeightPanel()
        self.albedo_panel = AlbedoPanel()
        self.normal_panel = NormalPanel()
        self.roughness_panel = RoughnessPanel()
        self.ao_panel = AOPanel()

        self._panels_by_type = {
            MapType.ALBEDO: self.albedo_panel,
            MapType.HEIGHT: self.height_panel,
            MapType.NORMAL: self.normal_panel,
            MapType.ROUGHNESS: self.roughness_panel,
            MapType.AO: self.ao_panel,
        }
        for map_type in MAP_TYPE_ORDER:
            self._panels_by_type[map_type].sync_knob_defaults()
            self.stacked_panels.addWidget(self._panels_by_type[map_type])
        layout.addWidget(self.stacked_panels)

        self.height_panel.set_raw_source_provider(self._height_raw_source)
        self.roughness_panel.set_underlay_provider(self._roughness_underlays)
        self.height_panel.modelSettingsChanged.connect(self._on_model_settings_changed)
        for map_type in MAP_TYPE_ORDER:
            self._panels_by_type[map_type].pageChanged.connect(self._on_panel_page_changed)
            self._panels_by_type[map_type].propertiesChanged.connect(self._schedule_properties_preview)
            self._panels_by_type[map_type].propertiesChanged.connect(self._update_save_revert_enabled)
        return host

    def _build_generate_controls(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(6)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.generate_btn = QPushButton(_GENERATE_LABELS[MapType.ALBEDO][0])
        self.generate_btn.setProperty("role", "generate")
        self.generate_btn.clicked.connect(self._on_primary_btn_clicked)

        self.kill_btn = QPushButton("Stop")
        self.kill_btn.setProperty("role", "generate")
        self.kill_btn.setEnabled(False)
        self.kill_btn.setVisible(False)
        self.kill_btn.clicked.connect(self._on_secondary_btn_clicked)

        btn_row.addWidget(self.generate_btn)
        btn_row.addWidget(self.kill_btn)
        col.addLayout(btn_row)

        status_row = QHBoxLayout()
        self.status_label = _StatusLabel(self._is_busy)
        self.status_label.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(0)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self.progress_bar)
        col.addLayout(status_row)
        return col

    def _build_preview_section(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setObjectName("PreviewSection")
        splitter.setChildrenCollapsible(False)

        top_pane = QWidget()
        top_layout = QVBoxLayout(top_pane)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)


        self.preview_3d = Preview3DWidget()
        self.preview_3d.setMinimumHeight(160)
        viewport = QWidget()
        viewport.setObjectName("ViewportFrame")
        viewport_layout = QVBoxLayout(viewport)
        viewport_layout.setContentsMargins(0, 0, 0, 0)
        viewport_layout.addWidget(self.preview_3d)
        top_layout.addWidget(viewport, 1)

        panel = QFrame(viewport)
        panel.setObjectName("FloatingViewOptions")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)
        self._view_options_panel = panel
        self._viewport_frame = viewport

        # The title bar strip over the viewport is invisible but still drags
        # the window, like the strip above the material slots.
        self._viewport_title_drag = None
        if IS_MAC:
            drag = QWidget(viewport)
            drag.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
            drag.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            drag.setFixedHeight(mac_window.TITLE_BAR_HEIGHT)
            mac_window.install_drag_area(drag)
            self._viewport_title_drag = drag

        preview_heading = ToggleHeading(_heading("VIEW OPTIONS"))
        preview_heading.setProperty("role", "panel-heading")
        preview_heading.setToolTip("Click to show or hide the view options")
        preview_heading.toggled.connect(self._set_view_options_expanded)
        self._view_options_heading = preview_heading
        panel_layout.addWidget(preview_heading)

        self.preview_properties_panel = PreviewPropertiesPanel()
        self.preview_properties_panel.settingsChanged.connect(self._on_preview_settings_changed)
        self.preview_properties_panel.tabChanged.connect(self._layout_view_options_panel)

        self.preview_3d.distanceChanged.connect(self.preview_properties_panel.set_distance_value)
        self.preview_3d.lightChanged.connect(self.preview_properties_panel.set_light_values)
        self.preview_3d.autoRotateToggled.connect(self.preview_properties_panel.set_auto_rotate)
        self.preview_3d.pivotChanged.connect(self.preview_properties_panel.set_pivot_values)

        self.preview_3d.set_preview_settings(self.preview_properties_panel.get_settings())
        panel_layout.addWidget(self.preview_properties_panel, 1)

        self._style_view_options_panel()
        theme_changed.connect(self._style_view_options_panel)
        viewport.installEventFilter(self)
        panel.raise_()

        splitter.addWidget(top_pane)
        self._preview_splitter = splitter
        return splitter

    def _style_view_options_panel(self) -> None:
        if PLATFORM_THEME == "mac":
            from ui import mac_theme

            base, dark = mac_theme.tokens()["window"], mac_theme.is_dark()
        elif PLATFORM_THEME == "windows":
            from ui import windows_theme

            base, dark = windows_theme.tokens()["window"], windows_theme.is_dark()
        else:
            base, dark = "#2b2b2b", True
        color = QColor(base)
        edge = "rgba(255, 255, 255, 0.14)" if dark else "rgba(0, 0, 0, 0.16)"
        self._view_options_panel.setStyleSheet(
            "QFrame#FloatingViewOptions {"
            f" background-color: rgba({color.red()}, {color.green()}, {color.blue()}, 0.93);"
            f" border: 1px solid {edge}; border-radius: 10px; }}"
            " QFrame#FloatingViewOptions QScrollArea, QFrame#FloatingViewOptions QScrollArea > QWidget > QWidget"
            " { background: transparent; }"
            ' QFrame#FloatingViewOptions QLabel[role="panel-heading"] { padding: 8px 12px 8px 12px; }'
        )

    def _layout_view_options_panel(self) -> None:
        panel, viewport = self._view_options_panel, self._viewport_frame
        if self._viewport_title_drag is not None:
            self._viewport_title_drag.setGeometry(0, 0, viewport.width(), mac_window.TITLE_BAR_HEIGHT)
            self._viewport_title_drag.raise_()
        margin = _VIEW_OPTIONS_MARGIN
        max_width = max(120, viewport.width() - 2 * margin)
        max_height = max(40, viewport.height() - 2 * margin)
        heading_height = self._view_options_heading.sizeHint().height()
        if self._view_options_heading.is_expanded():
            width = min(_VIEW_OPTIONS_WIDTH, _VIEW_OPTIONS_MAX_WIDTH, max_width)
            content = heading_height + self.preview_properties_panel.content_height()
            height = min(content, _VIEW_OPTIONS_HEIGHT, max_height)
        else:
            width = min(self._view_options_heading.sizeHint().width() + 4, max_width)
            height = min(heading_height, max_height)
        panel.setGeometry(margin, viewport.height() - margin - height, width, height)
        panel.raise_()

    def eventFilter(self, obj, event) -> bool:
        if obj is getattr(self, "selected_map_preview", None) and event.type() == QEvent.Type.Resize:
            self._place_map_overlays()
        if obj is getattr(self, "_viewport_frame", None) and event.type() == QEvent.Type.Resize:
            self._layout_view_options_panel()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_view_options_panel"):
            self._layout_view_options_panel()

    def _set_view_options_expanded(self, expanded: bool) -> None:
        self.preview_properties_panel.setVisible(expanded)
        self._layout_view_options_panel()
        QSettings().setValue(_VIEW_OPTIONS_EXPANDED_KEY, expanded)

    def _sidebar_max_width(self) -> int:
        """A quarter of the screen the window is on, plus 100 px."""
        screen = self.screen() or QApplication.primaryScreen()
        return screen.availableGeometry().width() // 4 + 100

    def _apply_sidebar_max(self, *_args) -> None:
        if PLATFORM_THEME == "legacy" or not hasattr(self, "_main_splitter"):
            return
        splitter = self._main_splitter
        limit = self._sidebar_max_width()
        splitter.widget(0).setMaximumWidth(limit)
        # setSizes() (e.g. restoring a saved layout) can hand the sidebar more
        # than its maximum, which would leave an empty strip; give it to the 3D view.
        sizes = splitter.sizes()
        if len(sizes) == 2 and sizes[0] > limit:
            splitter.setSizes([limit, sizes[0] + sizes[1] - limit])

    def showEvent(self, event) -> None:
        super().showEvent(event)
        handle = self.windowHandle()
        if handle is not None and not getattr(self, "_screen_watch", False):
            self._screen_watch = True
            handle.screenChanged.connect(self._apply_sidebar_max)
        self._apply_sidebar_max()
        if self._initial_layout_done or PLATFORM_THEME == "legacy":
            return
        self._initial_layout_done = True
        if not window_layout.restore(self, self._main_splitter, self._preview_splitter):
            window_layout.fit_to_screen(
                self, self._main_splitter, self._preview_splitter,
                sidebar_ratio=pick(mac=0.34, windows=0.32), sidebar_min=pick(mac=380, windows=380), sidebar_max=self._sidebar_max_width(),
            )
        # The sidebar always opens narrow so the 3D view gets the room.
        splitter = self._main_splitter
        total = sum(splitter.sizes())
        start = max(splitter.widget(0).minimumWidth(), min(SIDEBAR_START_WIDTH, self._sidebar_max_width()))
        splitter.setSizes([start, max(0, total - start)])
        self._apply_sidebar_max()
        if QSettings().value(_VIEW_OPTIONS_EXPANDED_KEY, True, type=bool) is False:
            self._view_options_heading.set_expanded(False)
        if IS_WINDOWS:
            from ui.win_window import TaskbarProgress

            self._taskbar_progress = TaskbarProgress(self)

    def _select_map_type(self, map_type: MapType) -> None:
        self._invalidate_properties_preview()
        self.current_map_type = map_type
        if map_type != getattr(self, "_status_map_type", map_type):
            self.status_label.clear_if_idle()
        self._status_map_type = map_type
        self.active_slot_label.setText(MAP_TYPE_LABELS[map_type])
        self._place_map_overlays()
        panel = self._panels_by_type[map_type]
        self.stacked_panels.setCurrentWidget(panel)
        self._refresh_selected_map_preview()
        self._refresh_material_slots_bar()
        self._update_generate_bar_mode(panel.current_page())
        self._restore_pending_draft()

    def _update_map_controls_enabled(self) -> None:
        map_type = self.current_map_type
        self.upload_btn.setEnabled(True)
        has_content = (
            map_type in self.source_images
            or map_type in self.generated_images
            or map_type in self._draft_images
        )
        self.remove_btn.setEnabled(has_content)
        self.save_as_btn.setEnabled(has_content)

    def _active_display_image(self, map_type: MapType) -> Optional[Image.Image]:
        return (
            self._draft_images.get(map_type)
            or self.generated_images.get(map_type)
            or self.source_images.get(map_type)
        )

    def _refresh_selected_map_preview(self) -> None:
        image = self._active_display_image(self.current_map_type)
        self.selected_map_preview.set_pixmap_source(pil_to_qpixmap(image) if image is not None else None)
        if image is not None:
            self.selected_map_preview.setToolTip(
                f"Double-click to open 2x2 Tiled Preview ({MAP_TYPE_LABELS.get(self.current_map_type, 'Map')})"
            )
        self.height_panel.set_has_albedo(MapType.ALBEDO in self.source_images)
        self.normal_panel.set_has_height(self._active_display_image(MapType.HEIGHT) is not None)
        self.roughness_panel.set_has_normal(self._active_display_image(MapType.NORMAL) is not None)
        self.ao_panel.set_has_height(self._active_display_image(MapType.HEIGHT) is not None)
        self._update_map_controls_enabled()
        self._refresh_material_slots_bar()
        self._refresh_slot_info()

    def _open_tiled_preview(self, target_map_type: Optional[MapType] = None) -> None:
        map_type = target_map_type or self.current_map_type
        image = (
            self.generated_images.get(map_type)
            or self._draft_images.get(map_type)
            or self.source_images.get(map_type)
        )
        if image is None:
            return
        map_name = MAP_TYPE_LABELS.get(map_type, "Active Map")
        dlg = TiledPreviewDialog(image, map_name=map_name, parent=self)
        dlg.exec()

    def _on_preview_image_dropped(self, path: str) -> None:
        self._load_source_image(self.current_map_type, path)

    def _on_other_file_dropped(self, path: str) -> None:
        if is_project_path(path):
            self._handle_dropped_project(path)

    def _upload_image(self) -> None:
        filt = "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)"
        path, _ = QFileDialog.getOpenFileName(self, "Select Image", "", filt)
        if path:
            self._load_source_image(self.current_map_type, path)

    def _get_dependent_downstream_maps(self, map_type: MapType) -> list[MapType]:
        if map_type == MapType.ALBEDO:
            candidates = (MapType.HEIGHT, MapType.NORMAL, MapType.ROUGHNESS, MapType.AO)
        elif map_type == MapType.HEIGHT:
            candidates = (MapType.NORMAL, MapType.ROUGHNESS, MapType.AO)
        elif map_type == MapType.NORMAL:
            candidates = (MapType.ROUGHNESS,)
        else:
            candidates = ()
        return [m for m in candidates if (m in self.generated_images or m in self.source_images)]

    def _load_source_image(self, map_type: MapType, path: str) -> None:
        if not path.lower().endswith(IMAGE_EXTENSIONS):
            return
        try:
            image = Image.open(path)
            image.load()
            if map_type in (MapType.HEIGHT, MapType.ROUGHNESS) and image.mode in ("I;16", "I", "L"):
                pass
            else:
                image = image.convert("RGB")
        except Exception as exc:
            QMessageBox.critical(self, "Failed to load image", str(exc))
            return

        affected = self._get_dependent_downstream_maps(map_type)

        self.source_images[map_type] = image
        self.generated_images.pop(map_type, None)
        self._draft_images.pop(map_type, None)
        if map_type == MapType.HEIGHT:
            self._height_depth_result = None

        self._mark_dirty()
        if self.current_map_type == map_type:
            self._refresh_selected_map_preview()
        else:
            self._refresh_material_slots_bar()
        self._push_textures_to_preview()

        if affected:
            affected_names = ", ".join(MAP_TYPE_LABELS[m] for m in affected)
            self.status_label.setText(f"{affected_names} maps may be out of sync with your changes.")
        else:
            self.status_label.setText(f"{MAP_TYPE_LABELS[map_type]} loaded.")

    def _remove_image(self) -> None:
        map_type = self.current_map_type
        has_content = (
            map_type in self.source_images
            or map_type in self.generated_images
            or map_type in self._draft_images
        )
        if not has_content:
            return

        reply = QMessageBox.question(
            self,
            f"Remove {MAP_TYPE_LABELS[map_type]} Map?",
            f"Are you sure you want to remove the {MAP_TYPE_LABELS[map_type]} map?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        affected = self._get_dependent_downstream_maps(map_type)

        self.source_images.pop(map_type, None)
        self.generated_images.pop(map_type, None)
        self._draft_images.pop(map_type, None)
        if map_type == MapType.HEIGHT:
            self._height_depth_result = None

        self._mark_dirty()
        self._refresh_selected_map_preview()
        self._refresh_material_slots_bar()
        self._push_textures_to_preview()

        if affected:
            affected_names = ", ".join(MAP_TYPE_LABELS[m] for m in affected)
            msg = f"{affected_names} maps may be out of sync with your changes."
            QMessageBox.information(self, "Warning", msg)
            self.status_label.setText(f"{affected_names} maps may be out of sync with your changes.")
        else:
            self.status_label.setText(f"{MAP_TYPE_LABELS[map_type]} removed.")

    def _save_current_map_as(self) -> None:
        map_type = self.current_map_type
        image = self._active_display_image(map_type)
        if image is None:
            QMessageBox.information(self, "Nothing to save", "This map has no image yet.")
            return

        is_32bit = (image.mode == "F")
        if is_32bit:
            default_name = f"{map_type.value}.exr"
            filter_str = "OpenEXR (*.exr);;TIFF Image (*.tif *.tiff);;All Files (*.*)"
        elif image.mode in ("I;16", "I"):
            default_name = f"{map_type.value}.png"
            filter_str = "PNG Image (*.png);;TIFF Image (*.tif *.tiff);;OpenEXR (*.exr);;All Files (*.*)"
        else:
            default_name = f"{map_type.value}.png"
            filter_str = "PNG Image (*.png);;JPEG Image (*.jpg *.jpeg);;TIFF Image (*.tif *.tiff);;OpenEXR (*.exr);;All Files (*.*)"

        path, _ = QFileDialog.getSaveFileName(self, "Save Map As", default_name, filter_str)
        if not path:
            return
        if is_32bit and not (path.lower().endswith((".exr", ".tif", ".tiff"))):
            path += ".exr"
        elif not is_32bit and not path.lower().endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr")):
            path += ".png"
        dialog = OperationProgressDialog("Saving Map", f"Writing {os.path.basename(path)}…", parent=self)
        worker = SingleImageSaveWorker(image, path, parent=self)

        saved = [False]
        def on_done(_p):
            saved[0] = True
            dialog.accept()

        def on_err(err):
            dialog.reject()
            QMessageBox.critical(self, "Failed to save image", str(err))

        worker.finished_ok.connect(on_done)
        worker.failed.connect(on_err)
        worker.start()
        dialog.exec()

        if saved[0]:
            self.status_label.setText(f"Saved {MAP_TYPE_LABELS[map_type]} map to {path}")

    def _is_model_ready_and_matched(self) -> bool:
        if self.estimator is None or not self.estimator.is_loaded():
            return False
        family, variant = self.height_panel.selected_family_variant()
        device = self.height_panel.selected_device()
        device_matches = (
            device == getattr(self.estimator, "requested_device", None)
            or device == self.estimator.device
            or (device == "auto" and getattr(self.estimator, "requested_device", None) == "auto")
        )
        return (
            self.estimator.family == family
            and self.estimator.variant == variant
            and device_matches
        )

    def _replace_estimator(self, family: str, variant: str, device: str) -> None:
        if self.estimator is not None:
            self.estimator.unload()
        # Runs in its own process so Stop can kill it outright (see core/depth_process).
        self.estimator = RemoteDepthEstimator(family, variant, device)

    def _on_model_settings_changed(self) -> None:
        family, variant = self.height_panel.selected_family_variant()
        device = self.height_panel.selected_device()

        if self.estimator is not None and self.estimator.is_loaded():
            if self._is_model_ready_and_matched():
                self.height_panel.set_model_status(
                    f"Loaded: {self.estimator.family} / {self.estimator.variant} on {self.estimator.device.upper()}"
                )
            else:
                self.height_panel.set_model_status(
                    f"Loaded: {self.estimator.family} / {self.estimator.variant} on {self.estimator.device.upper()} "
                    f"— selected: {family} / {variant} on {device.upper()} (loads on the next generate)"
                )
        else:
            self.height_panel.set_model_status("No model loaded yet — it loads when you generate.")

    def _on_model_loaded(self) -> None:
        self.height_panel.set_model_controls_enabled(True)
        self.generate_btn.setEnabled(True)
        if self.estimator is None or not self.estimator.is_loaded():
            self.height_panel.set_model_status("No model loaded yet — it loads when you generate.")
            return
        self.height_panel.set_model_status(
            f"Loaded: {self.estimator.family} / {self.estimator.variant} on {self.estimator.device.upper()}"
        )

    def _on_model_loaded_for_generate_all(self) -> None:
        self._on_model_loaded()
        if self._generating_all:
            self._start_height_inference()

    def _on_model_loaded_for_generate_height(self) -> None:
        self._on_model_loaded()
        self._start_height_inference()

    def _on_model_load_failed(self, msg: str) -> None:
        self._generating_all = False
        self.height_panel.set_model_controls_enabled(True)
        self.height_panel.set_model_status("Failed to load model.")
        self._set_busy(False)
        if self.estimator is not None:
            self.estimator.unload()
        self.estimator = None
        QMessageBox.critical(self, "Model load failed", msg)

    def _height_raw_source(self) -> tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        if self._height_depth_result is not None:
            return self._height_depth_result.depth, self._height_depth_result.guide
        src = self.source_images.get(MapType.HEIGHT)
        if src is not None:
            return _image_to_height_array(src), None
        return None, None

    def _roughness_underlays(self) -> tuple[Optional[Image.Image], Optional[Image.Image], Optional[Image.Image]]:
        return (
            self._active_display_image(MapType.ALBEDO),
            self._active_display_image(MapType.NORMAL),
            self._active_display_image(MapType.ROUGHNESS),
        )

    def _height_seamless_orig_size(self) -> Optional[tuple[int, int]]:
        if self._height_depth_result is None:
            return None
        return self._height_depth_result.seamless_orig_size

    def _apply_height_result(self, depth: np.ndarray, guide: Optional[np.ndarray]) -> np.ndarray:
        options = self.height_panel.current_options()
        height_normed = build_height_map(depth, options, guide=guide)

        seamless_size = self._height_seamless_orig_size()
        if seamless_size is not None:
            ehm, raw1, mask_map = apply_seamless_linear_mask(
                height_normed,
                orig_size=seamless_size,
                padding_pct=0.10,
            )
            height_normed = raw1

        height_img = height_map_to_image(height_normed, bit_depth=options.bit_depth)
        self.generated_images[MapType.HEIGHT] = height_img
        self._draft_images.pop(MapType.HEIGHT, None)

        if MapType.NORMAL in self.generated_images:
            self._generate_normal_from_height(height_normed, seamless=True, saved=True)
        if MapType.AO in self.generated_images:
            self._generate_ao_from_height(height_normed, commit=True, saved=True)

        if self.current_map_type in (MapType.HEIGHT, MapType.NORMAL, MapType.AO):
            self._refresh_selected_map_preview()
        self._refresh_material_slots_bar()
        self._push_textures_to_preview()
        return height_normed

    def _saved_options(self, map_type: MapType):
        """The map's options as last saved on its Adjustment page. Used when a
        map is rebuilt only because the map it is made from changed: its own
        unsaved adjustments must stay a draft, so Revert still matches the image."""
        panel = self._panels_by_type[map_type]
        current = panel.properties_to_dict()
        saved = self._properties_snapshot.get(map_type)
        if not saved or saved == current:
            return panel.current_options()
        panel.blockSignals(True)
        try:
            panel.properties_apply_dict(saved)
            options = panel.current_options()
            panel.properties_apply_dict(current)
        finally:
            panel.blockSignals(False)
        return options

    def _generate_normal_from_height(
        self, height_normed: np.ndarray, seamless: bool = True, commit: bool = True, saved: bool = False
    ) -> None:
        base = self._saved_options(MapType.NORMAL) if saved else self.normal_panel.current_options()
        normal_options = replace(base, seamless=seamless)
        albedo_src = self._active_display_image(MapType.ALBEDO)
        if albedo_src is not None:
            normal_options.albedo_source = albedo_src
        normal_arr = generate_normal_map(height_normed, normal_options)
        img = normal_map_to_image(normal_arr)
        if commit:
            self.generated_images[MapType.NORMAL] = img
            self._draft_images.pop(MapType.NORMAL, None)
            if MapType.ROUGHNESS in self.generated_images:
                self._generate_roughness_from_normal(normal_arr, commit=True, saved=True)
        else:
            self._draft_images[MapType.NORMAL] = img
            if MapType.ROUGHNESS in self.generated_images or MapType.ROUGHNESS in self._draft_images:
                self._generate_roughness_from_normal(normal_arr, commit=False)

    def _generate_roughness_from_normal(self, normal_arr: np.ndarray, commit: bool = True, saved: bool = False) -> None:
        roughness_options = self._saved_options(MapType.ROUGHNESS) if saved else self.roughness_panel.current_options()
        height_img = self._active_display_image(MapType.HEIGHT)
        if height_img is not None:
            roughness_options.height_source = _image_to_height_array(height_img)
        albedo_img = self._active_display_image(MapType.ALBEDO)
        if albedo_img is not None:
            roughness_options.albedo_source = albedo_img
        roughness_arr = generate_roughness_map(normal_arr, roughness_options)
        img = roughness_map_to_image(roughness_arr)
        if commit:
            self.generated_images[MapType.ROUGHNESS] = img
            self._draft_images.pop(MapType.ROUGHNESS, None)
        else:
            self._draft_images[MapType.ROUGHNESS] = img

    def _generate_ao_from_height(self, height_normed: np.ndarray, commit: bool = True, saved: bool = False) -> None:
        ao_options = self._saved_options(MapType.AO) if saved else self.ao_panel.current_options()
        ao_arr = generate_ao_map(height_normed, ao_options)
        img = ao_map_to_image(ao_arr, bit_depth=ao_options.bit_depth)
        if commit:
            self.generated_images[MapType.AO] = img
            self._draft_images.pop(MapType.AO, None)
        else:
            self._draft_images[MapType.AO] = img

    def _schedule_properties_preview(self) -> None:
        panel = self._panels_by_type[self.current_map_type]
        if panel.current_page() != "properties":
            return
        self._properties_preview_revision += 1
        self._properties_preview_pending = True
        self._properties_debounce.start()

    def _refresh_properties_draft(self) -> None:
        if not self._properties_preview_pending:
            return
        if self.properties_preview_thread is not None and self.properties_preview_thread.isRunning():
            return

        self._properties_preview_pending = False
        revision = self._properties_preview_revision
        map_type = self.current_map_type
        has_normal = MapType.NORMAL in self.generated_images or MapType.NORMAL in self._draft_images
        has_roughness = MapType.ROUGHNESS in self.generated_images or MapType.ROUGHNESS in self._draft_images
        has_ao = MapType.AO in self.generated_images or MapType.AO in self._draft_images

        if map_type == MapType.HEIGHT:
            depth, guide = self._height_raw_source()
            if depth is None:
                return
            worker = PropertiesPreviewWorker(
                revision, map_type.value,
                height_depth=depth,
                height_guide=guide,
                height_seamless_orig_size=self._height_seamless_orig_size(),
                height_options=self.height_panel.current_options(),
                normal_options=replace(self.normal_panel.current_options(), seamless=True),
                roughness_options=self.roughness_panel.current_options(),
                ao_options=self.ao_panel.current_options(),
                make_normal=has_normal,
                make_roughness=has_normal and has_roughness,
                make_ao=has_ao,
            )
        elif map_type == MapType.NORMAL:
            height_image = self._active_display_image(MapType.HEIGHT)
            if height_image is None:
                return
            normal_opts = replace(self.normal_panel.current_options(), seamless=True)
            normal_opts.albedo_source = self._active_display_image(MapType.ALBEDO)
            worker = PropertiesPreviewWorker(
                revision, map_type.value,
                height_image=height_image,
                normal_options=normal_opts,
                roughness_options=self.roughness_panel.current_options(),
                make_roughness=has_roughness,
            )
        elif map_type == MapType.ROUGHNESS:
            normal_image = self._active_display_image(MapType.NORMAL)
            if normal_image is None:
                return
            rough_opts = self.roughness_panel.current_options()
            height_img = self._active_display_image(MapType.HEIGHT)
            if height_img is not None:
                rough_opts.height_source = _image_to_height_array(height_img)
            rough_opts.albedo_source = self._active_display_image(MapType.ALBEDO)
            worker = PropertiesPreviewWorker(
                revision, map_type.value,
                normal_image=normal_image,
                roughness_options=rough_opts,
                make_roughness=True,
            )
        elif map_type == MapType.AO:
            height_image = self._active_display_image(MapType.HEIGHT)
            if height_image is None:
                return
            worker = PropertiesPreviewWorker(
                revision, map_type.value,
                height_image=height_image,
                ao_options=self.ao_panel.current_options(),
            )
        elif map_type == MapType.ALBEDO:
            albedo_src = self.source_images.get(MapType.ALBEDO)
            if albedo_src is None:
                return
            worker = PropertiesPreviewWorker(
                revision, map_type.value,
                albedo_image=albedo_src,
                albedo_shift_rules=self.albedo_panel.current_shift_rules(),
                albedo_options=self.albedo_panel.current_adjust_options(),
            )
        else:
            return

        self.properties_preview_thread = worker
        worker.result_ready.connect(self._on_properties_preview_ready)
        worker.failed.connect(self._on_properties_preview_failed)
        worker.finished.connect(lambda: self._on_properties_preview_finished(worker))
        worker.start()

    def _on_properties_preview_ready(self, revision: int, map_type: str, images: dict[str, Image.Image]) -> None:
        if revision != self._properties_preview_revision or map_type != self.current_map_type.value:
            return
        for name, image in images.items():
            self._draft_images[MapType(name)] = image
        self._refresh_selected_map_preview()
        self._push_textures_to_preview()

    def _on_properties_preview_failed(self, revision: int, message: str) -> None:
        if revision == self._properties_preview_revision:
            self.status_label.setText(f"Preview update failed: {message}")

    def _on_properties_preview_finished(self, worker: PropertiesPreviewWorker) -> None:
        if self.properties_preview_thread is worker:
            self.properties_preview_thread = None
        worker.deleteLater()
        if self._properties_preview_pending:
            self._properties_debounce.start(0)

    def _invalidate_properties_preview(self) -> None:
        self._properties_preview_revision += 1
        self._properties_preview_pending = False
        self._properties_debounce.stop()

    def _ensure_ai_runtime(self, then) -> bool:
        """True when the depth models can run now. Otherwise offers to download
        the AI components (packaged app only) and calls `then` once they are in."""
        from core import ai_runtime

        if not ai_runtime.needs_download():
            if ai_runtime.is_frozen() and not ai_runtime.activate():
                QMessageBox.critical(self, "AI components missing", "This build cannot load the depth models.")
                return False
            return True
        size_mb = ai_runtime.download_size() / 1e6
        answer = QMessageBox.question(
            self,
            "Download AI components?",
            "Generating maps needs the depth-estimation components (PyTorch and the model runtime), "
            f"which are downloaded once: about {size_mb:.0f} MB.\n\n"
            "The depth model itself is downloaded separately the first time you use it.\n\nDownload now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False

        dialog = OperationProgressDialog(
            "Downloading AI Components", "Connecting…", parent=self, cancellable=True
        )
        worker = AIRuntimeInstallWorker(self)
        state = {"ok": False, "error": None}

        def on_progress(done: int, total: int, message: str) -> None:
            dialog.set_status(f"{message} {done / 1e6:.0f} / {total / 1e6:.0f} MB" if total else message)
            dialog.set_progress(done // 1024, max(1, total // 1024) if total else 0)

        def on_ok() -> None:
            state["ok"] = True
            dialog.accept()

        def on_failed(message: str) -> None:
            state["error"] = message
            dialog.reject()

        worker.progress.connect(on_progress)
        worker.finished_ok.connect(on_ok)
        worker.failed.connect(on_failed)
        worker.start()
        if dialog.exec() != dialog.DialogCode.Accepted and worker.isRunning():
            worker.requestInterruption()
        worker.wait()
        if state["ok"]:
            self.status_label.setText("AI components installed.")
            QTimer.singleShot(0, then)
        elif state["error"]:
            QMessageBox.critical(self, "Download failed", state["error"])
        else:
            self.status_label.setText("Download cancelled.")
        return False

    def _generate_all_maps(self) -> None:
        albedo_source = self.source_images.get(MapType.ALBEDO)
        if albedo_source is None:
            QMessageBox.warning(
                self,
                "Albedo required",
                "Please import an Albedo image first before generating maps.",
            )
            return
        if self.infer_thread is not None and self.infer_thread.isRunning():
            QMessageBox.information(self, "Busy", "Generation already running, please wait.")
            return
        if not self._ensure_ai_runtime(self._generate_all_maps):
            return

        self._generating_all = True

        if not self._is_model_ready_and_matched():
            self.status_label.setText("Loading depth model for generation…")
            self._set_busy(True)
            family, variant = self.height_panel.selected_family_variant()
            device = self.height_panel.selected_device()
            self._replace_estimator(family, variant, device)

            self.height_panel.set_model_controls_enabled(False)
            dialog = OperationProgressDialog(
                "Loading Depth Model",
                f"Initializing {family} ({variant}) on {device.upper()}…",
                parent=self,
                cancellable=True,
            )
            self.model_thread = ModelLoadWorker(self.estimator, parent=self)
            self.model_thread.progress.connect(lambda msg: (dialog.set_status(msg), self.height_panel.set_model_status(msg)))

            def on_loaded():
                dialog.accept()
                self._on_model_loaded_for_generate_all()

            def on_failed(err):
                dialog.reject()
                self._on_model_load_failed(err)

            self.model_thread.finished_ok.connect(on_loaded)
            self.model_thread.failed.connect(on_failed)
            self.model_thread.cancelled.connect(self._on_model_load_cancelled)
            self.model_thread.start()
            if dialog.exec() != OperationProgressDialog.DialogCode.Accepted and self.model_thread.isRunning():
                self._kill_process()
            return

        self._start_height_inference()

    def _generate_current_map(self) -> None:
        map_type = self.current_map_type
        if map_type == MapType.ALBEDO:
            self._generate_albedo_map_only()
            return
        if map_type == MapType.ROUGHNESS:
            self._generate_roughness_map_only()
            return
        if map_type == MapType.NORMAL:
            self._generate_normal_map_only()
            return
        if map_type == MapType.AO:
            self._generate_ao_map_only()
            return
        self._generate_height_map()

    def _generate_albedo_map_only(self) -> None:
        albedo_src = self.source_images.get(MapType.ALBEDO)
        if albedo_src is None:
            QMessageBox.information(
                self,
                "Albedo required",
                "Import an Albedo base texture first.",
            )
            return
        opts = self.albedo_panel.current_adjust_options()
        rules = self.albedo_panel.current_shift_rules()
        result_img = apply_albedo_adjustments(albedo_src, options=opts, rules=rules)
        self.generated_images[MapType.ALBEDO] = result_img
        self._draft_images.pop(MapType.ALBEDO, None)
        self._refresh_selected_map_preview()
        self._push_textures_to_preview()
        self._mark_dirty()
        self.status_label.setText("Albedo map updated with seamless & color adjustments.")

    def _generate_ao_map_only(self) -> None:
        height_image = self._active_display_image(MapType.HEIGHT)
        if height_image is None:
            QMessageBox.information(
                self,
                "Height required",
                "Import or generate a Height map first — Ambient Occlusion is derived from it.",
            )
            return
        height_arr = _image_to_height_array(height_image)
        self._generate_ao_from_height(height_arr, commit=True)
        self._refresh_selected_map_preview()
        self._push_textures_to_preview()
        self._properties_snapshot[MapType.AO] = self.ao_panel.properties_to_dict()
        self._mark_dirty()
        self.status_label.setText("Ambient Occlusion map generated from Height.")

    def _generate_roughness_map_only(self) -> None:
        normal_image = self._active_display_image(MapType.NORMAL)
        if normal_image is None:
            QMessageBox.information(
                self,
                "Normal required",
                "Import or generate a Normal map first — Roughness is derived from it.",
            )
            return
        self._generate_roughness_from_normal(_image_to_normal_array(normal_image))
        self._refresh_selected_map_preview()
        self._push_textures_to_preview()
        self._properties_snapshot[MapType.ROUGHNESS] = self.roughness_panel.properties_to_dict()
        self._mark_dirty()
        self.status_label.setText("Roughness map generated from Normal.")

    def _generate_normal_map_only(self) -> None:
        height_image = self._active_display_image(MapType.HEIGHT)
        if height_image is None:
            QMessageBox.information(
                self,
                "Height required",
                "Import or generate a Height map first — Normal is derived from it.",
            )
            return
        height_arr = _image_to_height_array(height_image)
        self._generate_normal_from_height(height_arr, seamless=True)
        self._refresh_selected_map_preview()
        self._push_textures_to_preview()
        self._properties_snapshot[MapType.NORMAL] = self.normal_panel.properties_to_dict()
        self._mark_dirty()
        self.status_label.setText("Normal map generated from Height.")

    def _generate_height_map(self) -> None:
        albedo_source = self.source_images.get(MapType.ALBEDO)
        if albedo_source is None:
            QMessageBox.information(
                self,
                "Nothing to generate",
                "Height is generated from the Albedo source image — switch to "
                "the Albedo tab and import an image first.",
            )
            return
        if not self._ensure_ai_runtime(self._generate_height_map):
            return
        if not self._is_model_ready_and_matched():
            if self.model_thread is not None and self.model_thread.isRunning():
                QMessageBox.information(self, "Busy", "Model is loading, please wait.")
                return
            self.status_label.setText("Loading depth model for generation…")
            self._set_busy(True)
            family, variant = self.height_panel.selected_family_variant()
            device = self.height_panel.selected_device()
            self._replace_estimator(family, variant, device)

            self.height_panel.set_model_controls_enabled(False)
            dialog = OperationProgressDialog(
                "Loading Depth Model",
                f"Initializing {family} ({variant}) on {device.upper()}…",
                parent=self,
                cancellable=True,
            )
            self.model_thread = ModelLoadWorker(self.estimator, parent=self)
            self.model_thread.progress.connect(lambda msg: (dialog.set_status(msg), self.height_panel.set_model_status(msg)))

            def on_loaded():
                dialog.accept()
                self._on_model_loaded_for_generate_height()

            def on_failed(err):
                dialog.reject()
                self._on_model_load_failed(err)

            self.model_thread.finished_ok.connect(on_loaded)
            self.model_thread.failed.connect(on_failed)
            self.model_thread.cancelled.connect(self._on_model_load_cancelled)
            self.model_thread.start()
            if dialog.exec() != OperationProgressDialog.DialogCode.Accepted and self.model_thread.isRunning():
                self._kill_process()
            return
        if self.infer_thread is not None and self.infer_thread.isRunning():
            QMessageBox.information(self, "Busy", "Already generating, please wait.")
            return

        self._start_height_inference()

    def _start_height_inference(self) -> None:
        albedo_source = self.source_images.get(MapType.ALBEDO)
        if albedo_source is None:
            return

        is_seamless = self.height_panel.is_seamless_generation()
        self._infer_is_seamless = is_seamless
        self._infer_orig_albedo_size = albedo_source.size

        infer_source = albedo_source
        if is_seamless:
            try:
                extended, tile_box = build_seamless_extended_tile(albedo_source, padding_pct=0.10)
                if self.height_panel.is_force_seamless_blur():
                    extended = apply_force_seamless_blur(extended, tile_box, blur_pct=0.03)
                infer_source = extended
            except Exception as exc:
                print(f"[Seamless] Failed to build extended tile: {exc}")
                infer_source = albedo_source
                self._infer_is_seamless = False

        tiled = self.height_panel.is_chunked()
        if tiled:
            reply = QMessageBox.question(
                self,
                "Chunk estimation enabled",
                "Chunk estimation runs the model many times (1 full-image pass + "
                "one pass per chunk) and can take significantly longer, especially "
                "on CPU. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                self._generating_all = False
                self._set_busy(False)
                return

        self._set_busy(True)
        self.status_label.setText("Running depth estimation…")
        self._height_before_infer = self.generated_images.get(MapType.HEIGHT)

        tile_size, overlap_pct, batch_size = self.height_panel.chunk_params()
        self.infer_thread = InferenceWorker(
            self.estimator,
            infer_source,
            tiled=tiled,
            tile_size=tile_size,
            overlap_pct=overlap_pct,
            batch_size=batch_size,
        )
        self.infer_thread.tile_progress.connect(self.status_label.setText)
        self.infer_thread.tile_preview.connect(self._on_tile_preview)
        self.infer_thread.result_ready.connect(self._on_depth_ready)
        self.infer_thread.failed.connect(self._on_infer_failed)
        self.infer_thread.finished_ok.connect(self._on_infer_finished)
        self.infer_thread.cancelled.connect(self._on_infer_cancelled)
        self.infer_thread.start()

    def _on_tile_preview(self, depth: object, guide: object) -> None:
        options = self.height_panel.current_options()
        preview_depth = downsample_for_preview(depth)
        normed = build_height_map(preview_depth, options, guide=guide)
        img = height_map_to_image(normed, bit_depth=8)
        self.generated_images[MapType.HEIGHT] = img
        if self.current_map_type == MapType.HEIGHT:
            self.selected_map_preview.set_pixmap_source(pil_to_qpixmap(img))
        self._refresh_material_slots_bar()

    def _on_depth_ready(self, result: DepthResult) -> None:
        self._height_before_infer = None
        if self._infer_is_seamless and self._infer_orig_albedo_size is not None:
            result.seamless_orig_size = self._infer_orig_albedo_size
        self._height_depth_result = result
        height_normed = self._apply_height_result(result.depth, result.guide)
        self._properties_snapshot[MapType.HEIGHT] = self.height_panel.properties_to_dict()

        if self._generating_all:
            if MapType.NORMAL not in self.source_images:
                self._generate_normal_from_height(height_normed, seamless=True, commit=True)
                self._properties_snapshot[MapType.NORMAL] = self.normal_panel.properties_to_dict()
            if MapType.ROUGHNESS not in self.source_images and MapType.NORMAL in self.generated_images:
                normal_img = self.generated_images[MapType.NORMAL]
                self._generate_roughness_from_normal(_image_to_normal_array(normal_img), commit=True)
                self._properties_snapshot[MapType.ROUGHNESS] = self.roughness_panel.properties_to_dict()
            if MapType.AO not in self.source_images:
                self._generate_ao_from_height(height_normed, commit=True)
                self._properties_snapshot[MapType.AO] = self.ao_panel.properties_to_dict()

        self._mark_dirty()
        self._refresh_selected_map_preview()
        self._refresh_material_slots_bar()
        self._push_textures_to_preview()

    def _restore_height_before_infer(self) -> None:
        previous = self._height_before_infer
        self._height_before_infer = None
        if previous is not None:
            self.generated_images[MapType.HEIGHT] = previous
        else:
            self.generated_images.pop(MapType.HEIGHT, None)
        self._refresh_selected_map_preview()
        self._push_textures_to_preview()

    def _on_infer_failed(self, msg: str) -> None:
        self._generating_all = False
        self._restore_height_before_infer()
        self._set_busy(False)
        self.status_label.setText(f"Failed: {msg}")
        QMessageBox.critical(self, "Generation failed", msg)

    def _on_infer_finished(self) -> None:
        self._set_busy(False)
        if self._generating_all:
            self._generating_all = False
            self.status_label.setText("All maps generated successfully.")
        else:
            self.status_label.setText("Height map generated.")

    def _on_infer_cancelled(self) -> None:
        self._generating_all = False
        self._restore_height_before_infer()
        self._set_busy(False)
        self.status_label.setText("Cancelled.")

    def _kill_process(self) -> None:
        """Stop the depth model immediately: its process is killed, not asked."""
        self._generating_all = False
        running = (self.infer_thread is not None and self.infer_thread.isRunning()) or (
            self.model_thread is not None and self.model_thread.isRunning()
        )
        if running and self.estimator is not None:
            self.status_label.setText("Stopping…")
            self.estimator.kill()

    def _on_model_load_cancelled(self) -> None:
        self._generating_all = False
        self._set_busy(False)
        self.height_panel.set_model_controls_enabled(True)
        self.status_label.setText("Cancelled.")

    def _on_panel_page_changed(self, page: str) -> None:
        self._update_generate_bar_mode(page)
        self._restore_pending_draft()

    def _restore_pending_draft(self) -> None:
        """Unsaved adjustments whose draft was dropped (e.g. the map they come
        from was rebuilt meanwhile) get their preview back."""
        map_type = self.current_map_type
        panel = self._panels_by_type[map_type]
        if map_type in self._draft_images:
            return
        if self._properties_snapshot.get(map_type) not in (None, panel.properties_to_dict()):
            self._schedule_properties_preview()

    def _reset_properties_snapshots(self) -> None:
        self._properties_snapshot = {
            map_type: self._panels_by_type[map_type].properties_to_dict() for map_type in MAP_TYPE_ORDER
        }

    def _update_generate_bar_mode(self, mode: str) -> None:
        self._bottom_bar_mode = mode
        if mode == "properties":
            self.generate_btn.setText("Save")
            self.kill_btn.setText("Revert")
            self.kill_btn.setVisible(True)
            self._update_save_revert_enabled()
        else:
            text, tip = _GENERATE_LABELS[self.current_map_type]
            if self.current_map_type in self.generated_images and self.current_map_type != MapType.ALBEDO:
                text = text.replace("Generate", "Regenerate", 1)
            self.generate_btn.setText(text)
            self.generate_btn.setToolTip(tip)
            self.kill_btn.setText("Stop")
            busy = (
                (self.infer_thread is not None and self.infer_thread.isRunning())
                or (self.model_thread is not None and self.model_thread.isRunning())
            )
            self.generate_btn.setEnabled(not busy and self._has_generate_source())
            self.kill_btn.setEnabled(busy)
            self.kill_btn.setVisible(busy)

    def _has_generate_source(self) -> bool:
        source = _GENERATE_SOURCE.get(self.current_map_type)
        return source is None or self._active_display_image(source) is not None

    def _update_save_revert_enabled(self) -> None:
        if self._bottom_bar_mode != "properties":
            return
        map_type = self.current_map_type
        panel = self._panels_by_type[map_type]
        changed = panel.properties_to_dict() != self._properties_snapshot.get(map_type, {})
        self.generate_btn.setEnabled(changed)
        self.kill_btn.setEnabled(changed)

    def _on_primary_btn_clicked(self) -> None:
        if self._bottom_bar_mode == "properties":
            self._save_current_properties()
        else:
            self._generate_current_map()

    def _on_secondary_btn_clicked(self) -> None:
        if self._bottom_bar_mode == "properties":
            self._revert_current_properties()
        else:
            self._kill_process()

    def _bake_all_pending_properties(self) -> None:
        self._invalidate_properties_preview()

        # Albedo first: Normal and Roughness read it, so it must be current before they are rebuilt.
        albedo_panel_dict = self.albedo_panel.properties_to_dict()
        if albedo_panel_dict != self._properties_snapshot.get(MapType.ALBEDO, {}) or MapType.ALBEDO in self._draft_images:
            albedo_src = self.source_images.get(MapType.ALBEDO)
            if albedo_src is not None:
                shifted = apply_albedo_adjustments(
                    albedo_src,
                    options=self.albedo_panel.current_adjust_options(),
                    rules=self.albedo_panel.current_shift_rules(),
                )
                self.generated_images[MapType.ALBEDO] = shifted
                self._draft_images.pop(MapType.ALBEDO, None)
                self._properties_snapshot[MapType.ALBEDO] = albedo_panel_dict

        height_panel_dict = self.height_panel.properties_to_dict()
        if height_panel_dict != self._properties_snapshot.get(MapType.HEIGHT, {}) or MapType.HEIGHT in self._draft_images:
            depth, guide = self._height_raw_source()
            if depth is not None:
                self._apply_height_result(depth, guide)
                self._draft_images.pop(MapType.HEIGHT, None)
                self._properties_snapshot[MapType.HEIGHT] = height_panel_dict

        normal_panel_dict = self.normal_panel.properties_to_dict()
        if normal_panel_dict != self._properties_snapshot.get(MapType.NORMAL, {}) or MapType.NORMAL in self._draft_images:
            height_image = self._active_display_image(MapType.HEIGHT)
            if height_image is not None:
                self._generate_normal_from_height(_image_to_height_array(height_image), seamless=True, commit=True)
                self._draft_images.pop(MapType.NORMAL, None)
                self._properties_snapshot[MapType.NORMAL] = normal_panel_dict

        roughness_panel_dict = self.roughness_panel.properties_to_dict()
        if roughness_panel_dict != self._properties_snapshot.get(MapType.ROUGHNESS, {}) or MapType.ROUGHNESS in self._draft_images:
            normal_image = self._active_display_image(MapType.NORMAL)
            if normal_image is not None:
                self._generate_roughness_from_normal(_image_to_normal_array(normal_image), commit=True)
                self._draft_images.pop(MapType.ROUGHNESS, None)
                self._properties_snapshot[MapType.ROUGHNESS] = roughness_panel_dict

        ao_panel_dict = self.ao_panel.properties_to_dict()
        if ao_panel_dict != self._properties_snapshot.get(MapType.AO, {}) or MapType.AO in self._draft_images:
            height_image = self._active_display_image(MapType.HEIGHT)
            if height_image is not None:
                self._generate_ao_from_height(_image_to_height_array(height_image), commit=True)
                self._draft_images.pop(MapType.AO, None)
                self._properties_snapshot[MapType.AO] = ao_panel_dict

        self._refresh_material_slots_bar()
        # Same follow-up as the Adjustment page's Save button, so after Ctrl+S
        # the Save/Revert buttons, the map thumbnail and the 3D view all agree.
        self._refresh_selected_map_preview()
        self._push_textures_to_preview()
        self._update_save_revert_enabled()

    def _save_current_properties(self) -> None:
        self._invalidate_properties_preview()
        map_type = self.current_map_type
        if map_type == MapType.HEIGHT:
            depth, guide = self._height_raw_source()
            if depth is not None:
                self._apply_height_result(depth, guide)
                self._draft_images.pop(MapType.HEIGHT, None)
                self._refresh_selected_map_preview()
        elif map_type == MapType.NORMAL:
            height_image = self._active_display_image(MapType.HEIGHT)
            if height_image is not None:
                self._generate_normal_from_height(_image_to_height_array(height_image), seamless=True, commit=True)
                self._refresh_selected_map_preview()
                self._push_textures_to_preview()
        elif map_type == MapType.ROUGHNESS:
            normal_image = self._active_display_image(MapType.NORMAL)
            if normal_image is not None:
                self._generate_roughness_from_normal(_image_to_normal_array(normal_image), commit=True)
                self._refresh_selected_map_preview()
                self._push_textures_to_preview()
        elif map_type == MapType.AO:
            height_image = self._active_display_image(MapType.HEIGHT)
            if height_image is not None:
                self._generate_ao_from_height(_image_to_height_array(height_image), commit=True)
                self._refresh_selected_map_preview()
                self._push_textures_to_preview()
        elif map_type == MapType.ALBEDO:
            albedo_src = self.source_images.get(MapType.ALBEDO)
            if albedo_src is not None:
                shifted = apply_albedo_adjustments(
                    albedo_src,
                    options=self.albedo_panel.current_adjust_options(),
                    rules=self.albedo_panel.current_shift_rules(),
                )
                self.generated_images[MapType.ALBEDO] = shifted
                self._draft_images.pop(MapType.ALBEDO, None)
                self._refresh_selected_map_preview()
                self._push_textures_to_preview()

        panel = self._panels_by_type[map_type]
        self._properties_snapshot[map_type] = panel.properties_to_dict()
        self._update_save_revert_enabled()
        self._refresh_material_slots_bar()
        self._mark_dirty()
        self.status_label.setText(f"Saved {MAP_TYPE_LABELS[map_type]} properties.")

    def _revert_current_properties(self) -> None:
        self._invalidate_properties_preview()
        map_type = self.current_map_type
        panel = self._panels_by_type[map_type]
        snapshot = self._properties_snapshot.get(map_type, {})
        panel.properties_apply_dict(snapshot)
        self._draft_images.pop(map_type, None)
        if map_type == MapType.HEIGHT:
            self._draft_images.pop(MapType.NORMAL, None)
            self._draft_images.pop(MapType.ROUGHNESS, None)
            self._draft_images.pop(MapType.AO, None)
        elif map_type == MapType.NORMAL:
            self._draft_images.pop(MapType.ROUGHNESS, None)
        self._refresh_selected_map_preview()
        self._refresh_material_slots_bar()
        self._push_textures_to_preview()
        self._update_save_revert_enabled()
        self.status_label.setText(f"Reverted {MAP_TYPE_LABELS[map_type]} properties.")

    def _set_busy(self, busy: bool) -> None:
        if self._bottom_bar_mode == "generate":
            self.generate_btn.setEnabled(not busy and self._has_generate_source())
            self.kill_btn.setEnabled(busy)
            self.kill_btn.setVisible(busy)
        self.height_panel.set_model_controls_enabled(not busy)
        self.height_panel.set_chunk_controls_enabled(not busy)
        self.progress_bar.setVisible(busy)
        if self._taskbar_progress is not None:
            self._taskbar_progress.set_busy(busy)
        if not busy and not self.isActiveWindow():
            QApplication.alert(self)

    def _on_preview_settings_changed(self, settings: dict) -> None:
        self.preview_3d.set_preview_settings(settings)
        self._mark_dirty()

    def _push_textures_to_preview(self) -> None:
        albedo = self._active_display_image(MapType.ALBEDO)
        height = self._active_display_image(MapType.HEIGHT)
        normal = self._active_display_image(MapType.NORMAL)
        roughness = self._active_display_image(MapType.ROUGHNESS)
        ao = self._active_display_image(MapType.AO)
        self.preview_3d.set_textures(albedo, normal, roughness, height=height, ao=ao)

    def _mark_dirty(self) -> None:
        self.dirty = True
        self._update_window_title()
        if hasattr(self, "_history"):
            self._history.touch()

    def _update_window_title(self) -> None:
        self._refresh_material_header()
        if IS_MAC:
            self.setWindowTitle("[*]")
            self.setWindowModified(self.dirty)
            return
        name = os.path.basename(self.project_path) if self.project_path else "Untitled"
        star = "*" if self.dirty else ""
        self.setWindowTitle(f"PBRCELAIN — {name}{star}")

    def _confirm_discard_if_dirty(self) -> bool:
        if not self.dirty:
            return True
        reply = QMessageBox.question(
            self,
            "Unsaved changes",
            "You have unsaved changes. Save before continuing?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Save:
            return self._save_project()
        return reply == QMessageBox.StandardButton.Discard

    def _new_project(self) -> None:
        if not self._confirm_discard_if_dirty():
            return
        self.project = ProjectData.new()
        self.project_path = None
        self.source_images.clear()
        self.generated_images.clear()
        self._draft_images.clear()
        self._height_depth_result = None
        self.dirty = False
        for panel in (self.height_panel, self.normal_panel, self.albedo_panel, self.roughness_panel, self.ao_panel):
            panel.reset_to_defaults()
        self.preview_properties_panel.apply_settings({})
        self.preview_3d.set_preview_settings(self.preview_properties_panel.get_settings())
        self._reset_properties_snapshots()
        self._select_map_type(MapType.ALBEDO)
        self._push_textures_to_preview()
        self._update_window_title()
        self._history.reset()

    def _open_project(self) -> None:
        if not self._confirm_discard_if_dirty():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open Project", "", PROJECT_FILE_FILTER)
        if not path:
            return
        self._load_project_from_path(path)

    def _handle_dropped_project(self, path: str) -> None:
        if not self._confirm_discard_if_dirty():
            return
        self._load_project_from_path(path)

    def _load_project_from_path(self, path: str) -> None:
        fname = os.path.basename(path)
        dialog = OperationProgressDialog("Loading Project", f"Opening {fname}…", parent=self)
        worker = ProjectLoadWorker(path, parent=self)
        worker.progress.connect(dialog.set_status)

        loaded_result = []

        def on_loaded(project, source_images, cache_images, height_raw):
            loaded_result.append((project, source_images, cache_images, height_raw))
            dialog.accept()

        def on_failed(err):
            dialog.reject()
            QMessageBox.critical(self, "Failed to open project", str(err))

        worker.finished_ok.connect(on_loaded)
        worker.failed.connect(on_failed)
        worker.start()
        dialog.exec()

        if not loaded_result:
            return

        project, source_images, cache_images, height_raw = loaded_result[0]
        self.project = project
        self.project_path = path
        self._add_recent_project(path)
        self.source_images = source_images
        self.generated_images = cache_images
        self._draft_images.clear()
        self._height_depth_result = height_raw
        self.dirty = False

        self.height_panel.apply_options_dict(project.map_slots.get(MapType.HEIGHT.value, MapSlotData()).options)
        self.normal_panel.apply_options_dict(project.map_slots.get(MapType.NORMAL.value, MapSlotData()).options)
        self.albedo_panel.apply_options_dict(project.map_slots.get(MapType.ALBEDO.value, MapSlotData()).options)
        self.roughness_panel.apply_options_dict(project.map_slots.get(MapType.ROUGHNESS.value, MapSlotData()).options)
        self.ao_panel.apply_options_dict(project.map_slots.get(MapType.AO.value, MapSlotData()).options)
        self.preview_properties_panel.apply_settings(project.preview_settings)
        self.preview_3d.set_preview_settings(self.preview_properties_panel.get_settings())
        self._reset_properties_snapshots()

        self._select_map_type(MapType.ALBEDO)
        self._push_textures_to_preview()
        self._update_window_title()
        self._history.reset()
        self.status_label.setText(f"Project loaded from {fname}")

    def _collect_project_data(self) -> ProjectData:
        return ProjectData(
            map_slots={
                MapType.ALBEDO.value: MapSlotData(
                    has_source=MapType.ALBEDO in self.source_images,
                    has_cache=MapType.ALBEDO in self.generated_images,
                    options=self.albedo_panel.to_options_dict(),
                ),
                MapType.HEIGHT.value: MapSlotData(
                    has_source=MapType.HEIGHT in self.source_images,
                    has_cache=MapType.HEIGHT in self.generated_images,
                    options=self.height_panel.to_options_dict(),
                ),
                MapType.NORMAL.value: MapSlotData(
                    has_source=MapType.NORMAL in self.source_images,
                    has_cache=MapType.NORMAL in self.generated_images,
                    options=self.normal_panel.to_options_dict(),
                ),
                MapType.ROUGHNESS.value: MapSlotData(
                    has_source=MapType.ROUGHNESS in self.source_images,
                    has_cache=MapType.ROUGHNESS in self.generated_images,
                    options=self.roughness_panel.to_options_dict(),
                ),
                MapType.AO.value: MapSlotData(
                    has_source=MapType.AO in self.source_images,
                    has_cache=MapType.AO in self.generated_images,
                    options=self.ao_panel.to_options_dict(),
                ),
            },
            preview_settings=self.preview_properties_panel.get_settings(),
        )

    def _save_project(self) -> bool:
        if self.project_path is None:
            return self._save_project_as()
        return self._write_project(self.project_path)

    def _save_project_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(self, "Save Project As", "", f"PBRCELAIN Project (*{PROJECT_EXTENSION})")
        if not path:
            return False
        if not path.lower().endswith(PROJECT_EXTENSION):
            path += PROJECT_EXTENSION
        return self._write_project(path)

    def _write_project(self, path: str) -> bool:
        self._bake_all_pending_properties()
        project = self._collect_project_data()

        fname = os.path.basename(path)
        dialog = OperationProgressDialog("Saving Project", f"Packaging {fname}…", parent=self)
        worker = ProjectSaveWorker(
            path,
            project,
            self.source_images,
            self.generated_images,
            height_raw=self._height_depth_result,
            parent=self,
        )
        worker.progress.connect(dialog.set_status)

        saved = [False]

        def on_saved():
            saved[0] = True
            dialog.accept()

        def on_failed(err):
            dialog.reject()
            QMessageBox.critical(self, "Failed to save project", str(err))

        worker.finished_ok.connect(on_saved)
        worker.failed.connect(on_failed)
        worker.start()
        dialog.exec()

        if saved[0]:
            self.project = project
            self.project_path = path
            self._add_recent_project(path)
            self.dirty = False
            self._update_window_title()
            self.status_label.setText(f"Project saved to {fname}")
        return saved[0]

    def _export_maps(self) -> None:
        self._bake_all_pending_properties()

        export_dialog = ExportDialog(self)
        if export_dialog.exec() != ExportDialog.DialogCode.Accepted:
            return
        export_options = export_dialog.options()

        out_dir = QFileDialog.getExistingDirectory(self, "Select Export Folder")
        if not out_dir:
            return

        items = []
        for mt in MAP_TYPE_ORDER:
            img = self.generated_images.get(mt) or self.source_images.get(mt)
            if img is not None:
                if mt == MapType.HEIGHT:
                    img = height_map_to_image(_image_to_height_array(img), bit_depth=export_options.height_bit_depth)
                elif mt == MapType.AO:
                    img = ao_map_to_image(_image_to_height_array(img), bit_depth=export_options.ao_bit_depth)
                ext = ".exr" if getattr(img, "mode", None) == "F" else ".png"
                fname = f"{mt.value}{ext}"
                items.append((MAP_TYPE_LABELS[mt], img, fname))

        height_img = self.generated_images.get(MapType.HEIGHT) or self.source_images.get(MapType.HEIGHT)
        if height_img is not None and export_options.curvature:
            curvature = generate_curvature_map(_image_to_height_array(height_img))
            items.append(("Curvature", curvature_map_to_image(curvature), "curvature.png"))

        if not items:
            QMessageBox.information(self, "Nothing to export", "No maps have been generated or imported yet.")
            return

        dialog = OperationProgressDialog("Exporting Maps", "Preparing export…", parent=self)
        dialog.set_progress(0, len(items))

        worker = ExportWorker(out_dir, items, parent=self)
        worker.progress.connect(lambda cur, total, msg: (dialog.set_progress(cur, total), dialog.set_status(msg)))

        export_res = []

        def on_exported(exported):
            export_res.extend(exported)
            dialog.accept()

        def on_failed(err):
            dialog.reject()
            QMessageBox.critical(self, "Export Failed", str(err))

        worker.finished_ok.connect(on_exported)
        worker.failed.connect(on_failed)
        worker.start()
        dialog.exec()

        if export_res:
            exported_list = "\n".join(f"• {item}" for item in export_res)
            self.status_label.setText(f"Exported {len(export_res)} map(s) to {out_dir}")
            QMessageBox.information(
                self,
                "Export Complete",
                f"Successfully exported {len(export_res)} map(s) to:\n{out_dir}\n\n{exported_list}",
            )

    def dragEnterEvent(self, event) -> None:
        for url in event.mimeData().urls():
            if is_project_path(url.toLocalFile()):
                event.acceptProposedAction()
                return
        super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if is_project_path(path):
                event.acceptProposedAction()
                self._handle_dropped_project(path)
                return
        super().dropEvent(event)

    def closeEvent(self, event) -> None:
        if not self._confirm_discard_if_dirty():
            event.ignore()
            return
        if self.infer_thread is not None and self.infer_thread.isRunning():
            self.infer_thread.requestInterruption()
        for thread in (self.model_thread, self.infer_thread, self.properties_preview_thread):
            if thread is not None and thread.isRunning():
                thread.requestInterruption()
                thread.quit()
                thread.wait(5000)
        if PLATFORM_THEME != "legacy":
            window_layout.save(self, self._main_splitter, self._preview_splitter)
        super().closeEvent(event)
