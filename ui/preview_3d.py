from __future__ import annotations

import ctypes
import math
from typing import Optional

import numpy as np
from OpenGL import GL as gl
from PIL import Image
from PyQt6.QtCore import QEasingCurve, QPointF, QTimer, QVariantAnimation, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF, QSurfaceFormat
from PyQt6.QtOpenGLWidgets import QOpenGLWidget

from core.image_modes import to_gray8 as _to_gray8
from ui import trackpad

SKY_GLSL = """
const vec3 SKY_ZENITH = vec3(0.17, 0.24, 0.42);
const vec3 SKY_UPPER = vec3(0.42, 0.50, 0.66);
const vec3 SKY_HORIZON = vec3(0.90, 0.87, 0.82);
const vec3 GROUND_HORIZON = vec3(0.50, 0.51, 0.55);
const vec3 GROUND_NADIR = vec3(0.15, 0.16, 0.19);
const vec3 SKY_GROUND = vec3(0.30, 0.31, 0.35);
const vec3 SUN_COLOR = vec3(1.0, 0.90, 0.76);

vec3 proceduralSky(vec3 d, vec3 sunDir, bool backdrop) {
    float y = clamp(d.y, -1.0, 1.0);
    vec3 c;
    if (y >= 0.0) {
        float t = pow(y, 0.45);
        c = mix(SKY_HORIZON, SKY_UPPER, smoothstep(0.0, 0.35, t));
        c = mix(c, SKY_ZENITH, smoothstep(0.30, 1.0, t));
    } else {
        c = mix(GROUND_HORIZON, GROUND_NADIR, pow(-y, 0.6));
        if (backdrop) {
            vec2 p = d.xz / max(-y, 1e-3) * 0.5;
            vec2 f = abs(fract(p) - 0.5);
            vec2 w = max(fwidth(p), vec2(1e-4));
            vec2 lineDist = (0.5 - f) / w;
            float line = 1.0 - clamp(min(lineDist.x, lineDist.y), 0.0, 1.0);
            float fade = exp(-length(p) * 0.18) * smoothstep(0.0, 0.10, -y);
            c += vec3(0.62, 0.72, 0.92) * line * fade * 0.12;
        }
    }
    c = mix(c, SKY_HORIZON, exp(-abs(y) * (y >= 0.0 ? 9.0 : 14.0)) * (y >= 0.0 ? 0.55 : 1.0));
    float s = max(dot(d, sunDir), 0.0);
    c += SUN_COLOR * (pow(s, 24.0) * 0.18 + pow(s, 160.0) * 0.35);
    if (backdrop && y > -0.02) {
        c += vec3(1.0, 0.96, 0.90) * smoothstep(0.99955, 0.9998, s) * 1.6;
    }
    return c;
}
"""

VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec3 inPosition;
layout(location = 1) in vec3 inNormal;
layout(location = 2) in vec2 inUV;
layout(location = 3) in vec3 inTangent;

uniform mat4 uModel;
uniform mat4 uView;
uniform mat4 uProj;
uniform float uUVScale;

out vec3 vWorldPos;
out vec3 vNormal;
out vec2 vUV;
out vec3 vTangent;

void main() {
    vec4 world = uModel * vec4(inPosition, 1.0);
    vWorldPos = world.xyz;
    vNormal = mat3(uModel) * inNormal;
    vTangent = mat3(uModel) * inTangent;
    vUV = inUV * uUVScale;
    gl_Position = uProj * uView * world;
}
"""

FRAGMENT_SHADER = """
#version 330 core
in vec3 vWorldPos;
in vec3 vNormal;
in vec2 vUV;
in vec3 vTangent;
out vec4 outColor;

uniform vec3 uCamPos;
uniform vec3 uLightDir;
uniform float uLightIntensity;
uniform float uEnvIntensity;
uniform float uExposure;
uniform vec3 uAmbientColor;

uniform sampler2D uAlbedoTex;
uniform bool uHasAlbedo;
uniform sampler2D uNormalTex;
uniform bool uHasNormal;
uniform sampler2D uRoughnessTex;
uniform bool uHasRoughnessTex;
uniform float uRoughnessValue;
uniform sampler2D uHeightTex;
uniform bool uHasHeight;
uniform sampler2D uAOTex;
uniform bool uHasAO;
uniform bool uPOMEnabled;
uniform float uPOMHeightScale;
uniform float uPOMRefHeight;
uniform int uPOMMaxLayers;
uniform bool uSkyAmbient;

const float PI = 3.14159265359;
""" + SKY_GLSL + """
vec3 skyIrradiance(vec3 n, vec3 sunDir) {
    vec3 skyAvg = pow(mix(SKY_HORIZON, SKY_UPPER, 0.6), vec3(2.2));
    vec3 ground = pow(SKY_GROUND, vec3(2.2));
    vec3 c = mix(ground, skyAvg, clamp(n.y * 0.5 + 0.5, 0.0, 1.0));
    return c + SUN_COLOR * 0.08 * max(dot(n, sunDir), 0.0);
}

vec2 parallaxOcclusionMapping(vec2 texCoords, vec3 viewDirTS) {
    float maxLayers = float(max(uPOMMaxLayers, 4));
    float minLayers = max(4.0, maxLayers * 0.25);
    float layerCount = mix(maxLayers, minLayers, abs(viewDirTS.z));
    float layerDepth = 1.0 / layerCount;
    vec2 deltaUV = (viewDirTS.xy / max(viewDirTS.z, 0.15))
        * (uPOMHeightScale / layerCount);

    float currentLayerDepth = 0.0;
    vec2 currentUV = texCoords + deltaUV * layerCount * (1.0 - uPOMRefHeight);
    float sampledDepth = 1.0 - texture(uHeightTex, currentUV).r;
    if (sampledDepth <= 0.0) {
        return currentUV;
    }
    for (int i = 0; i < 64; ++i) {
        if (float(i) >= layerCount || currentLayerDepth >= sampledDepth) {
            break;
        }
        currentUV -= deltaUV;
        sampledDepth = 1.0 - texture(uHeightTex, currentUV).r;
        currentLayerDepth += layerDepth;
    }

    vec2 previousUV = currentUV + deltaUV;
    float afterDepth = sampledDepth - currentLayerDepth;
    float beforeDepth = (1.0 - texture(uHeightTex, previousUV).r) - currentLayerDepth + layerDepth;
    float denominator = afterDepth - beforeDepth;
    float weight = abs(denominator) > 1e-5 ? afterDepth / denominator : 0.0;
    weight = clamp(weight, 0.0, 1.0);
    return previousUV * weight + currentUV * (1.0 - weight);
}

void main() {
    vec3 N = normalize(vNormal);
    vec3 rawT = vTangent - N * dot(vTangent, N);
    vec3 fallbackAxis = abs(N.z) > 0.9 ? vec3(1.0, 0.0, 0.0) : vec3(0.0, 0.0, 1.0);
    vec3 T = length(rawT) > 1e-4 ? normalize(rawT) : normalize(cross(fallbackAxis, N));
    vec3 B = cross(N, T);

    vec2 uv = vUV;
    vec3 V = normalize(uCamPos - vWorldPos);
    if (uPOMEnabled && uHasHeight && uPOMHeightScale > 0.0) {
        vec3 viewDirTS = vec3(dot(V, T), dot(V, B), dot(V, N));
        uv = parallaxOcclusionMapping(uv, viewDirTS);
    }

    vec3 albedo = uHasAlbedo ? texture(uAlbedoTex, uv).rgb : vec3(0.75);
    albedo = pow(albedo, vec3(2.2));
    float roughness = uHasRoughnessTex ? texture(uRoughnessTex, uv).r : uRoughnessValue;
    roughness = clamp(roughness, 0.05, 1.0);

    if (uHasNormal) {
        vec3 tex = texture(uNormalTex, uv).rgb * 2.0 - 1.0;
        mat3 TBN = mat3(T, B, N);
        N = normalize(TBN * tex);
    }

    vec3 L = normalize(-uLightDir);
    vec3 H = normalize(V + L);

    float NdotL = max(dot(N, L), 0.0);
    float NdotV = max(dot(N, V), 0.0001);
    float NdotH = max(dot(N, H), 0.0);
    float VdotH = max(dot(V, H), 0.0);

    float alpha = roughness * roughness;
    float alpha2 = alpha * alpha;
    float denom = (NdotH * NdotH * (alpha2 - 1.0) + 1.0);
    float D = alpha2 / (PI * denom * denom + 1e-6);

    float k = (roughness + 1.0);
    k = (k * k) / 8.0;
    float G1V = NdotV / (NdotV * (1.0 - k) + k);
    float G1L = NdotL / (NdotL * (1.0 - k) + k);
    float G = G1V * G1L;

    vec3 F0 = vec3(0.04);
    vec3 F = F0 + (1.0 - F0) * pow(1.0 - VdotH, 5.0);

    vec3 specular = (D * G * F) / (4.0 * NdotV * NdotL + 1e-4);
    vec3 kd = (1.0 - F);
    vec3 diffuse = kd * albedo / PI;

    float ao = uHasAO ? texture(uAOTex, uv).r : 1.0;
    vec3 color = (diffuse + specular) * uLightIntensity * NdotL;
    if (uSkyAmbient) {
        vec3 Fenv = F0 + (max(vec3(1.0 - roughness), F0) - F0) * pow(1.0 - NdotV, 5.0);
        vec3 R = reflect(-V, N);
        vec3 reflected = pow(proceduralSky(R, L, false), vec3(2.2));
        vec3 envSpec = mix(reflected, skyIrradiance(R, L), roughness);
        vec3 envDiffuse = (1.0 - Fenv) * albedo * skyIrradiance(N, L);
        float gloss = pow(1.0 - roughness, 4.0);
        color += (envDiffuse + envSpec * Fenv * gloss) * uEnvIntensity * ao;
    } else {
        color += albedo * uAmbientColor * uEnvIntensity * ao;
    }
    color *= uExposure;

    color = color / (color + vec3(1.0));
    color = pow(color, vec3(1.0 / 2.2));
    outColor = vec4(color, 1.0);
}
"""

GRID_VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec3 inPosition;
uniform mat4 uView;
uniform mat4 uProj;
void main() { gl_Position = uProj * uView * vec4(inPosition, 1.0); }
"""

GRID_FRAGMENT_SHADER = """
#version 330 core
out vec4 outColor;
uniform vec3 uColor;
void main() { outColor = vec4(uColor, 1.0); }
"""

BACKGROUND_VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec2 inClipPos;
out vec2 vClip;
void main() {
    vClip = inClipPos;
    gl_Position = vec4(inClipPos, 0.9999, 1.0);
}
"""

BACKGROUND_FRAGMENT_SHADER = """
#version 330 core
in vec2 vClip;
out vec4 outColor;

uniform vec3 uCamForward;
uniform vec3 uCamRight;
uniform vec3 uCamUp;
uniform float uTanHalfFov;
uniform float uAspect;
uniform sampler2D uHdriTex;
uniform bool uHasHdri;
uniform vec3 uFlatColor;
uniform float uBrightness;
uniform vec3 uSunDir;

const float PI = 3.14159265359;
""" + SKY_GLSL + """

void main() {
    vec3 color;
    if (uHasHdri) {
        vec3 dir = normalize(
            uCamForward
            + vClip.x * uAspect * uTanHalfFov * uCamRight
            + vClip.y * uTanHalfFov * uCamUp
        );
        float u = 0.5 + atan(dir.z, dir.x) / (2.0 * PI);
        float v = 0.5 - asin(clamp(dir.y, -1.0, 1.0)) / PI;
        color = texture(uHdriTex, vec2(u, v)).rgb;
    } else {
        vec3 dir = normalize(
            uCamForward
            + vClip.x * uAspect * uTanHalfFov * uCamRight
            + vClip.y * uTanHalfFov * uCamUp
        );
        color = proceduralSky(dir, uSunDir, true);
    }
    outColor = vec4(color * uBrightness, 1.0);
}
"""


def configure_surface_format() -> None:
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    fmt.setDepthBufferSize(24)
    fmt.setSamples(4)
    QSurfaceFormat.setDefaultFormat(fmt)


def _build_uv_sphere(rings: int = 40, segments: int = 64) -> tuple[np.ndarray, np.ndarray]:
    verts = []
    for r in range(rings + 1):
        theta = r * math.pi / rings
        for s in range(segments + 1):
            phi = s * 2.0 * math.pi / segments
            x = math.sin(theta) * math.cos(phi)
            y = math.cos(theta)
            z = math.sin(theta) * math.sin(phi)
            u = s / segments
            v = r / rings
            tx = -math.sin(phi)
            ty = 0.0
            tz = math.cos(phi)
            verts.extend([x, y, z, x, y, z, u, v, tx, ty, tz])

    indices = []
    stride = segments + 1
    for r in range(rings):
        for s in range(segments):
            i0 = r * stride + s
            i1 = i0 + stride
            indices.extend([i0, i1, i0 + 1, i0 + 1, i1, i1 + 1])

    return np.array(verts, dtype=np.float32), np.array(indices, dtype=np.uint32)


def _build_cube(half_extent: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    s = half_extent
    faces = [
        ((1, 0, 0), (0, 0, -1), [(s, -s, s), (s, -s, -s), (s, s, -s), (s, s, s)]),
        ((-1, 0, 0), (0, 0, 1), [(-s, -s, -s), (-s, -s, s), (-s, s, s), (-s, s, -s)]),
        ((0, 1, 0), (1, 0, 0), [(-s, s, s), (s, s, s), (s, s, -s), (-s, s, -s)]),
        ((0, -1, 0), (1, 0, 0), [(-s, -s, -s), (s, -s, -s), (s, -s, s), (-s, -s, s)]),
        ((0, 0, 1), (1, 0, 0), [(-s, -s, s), (s, -s, s), (s, s, s), (-s, s, s)]),
        ((0, 0, -1), (-1, 0, 0), [(s, -s, -s), (-s, -s, -s), (-s, s, -s), (s, s, -s)]),
    ]
    uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]

    verts: list[float] = []
    indices: list[int] = []
    base = 0
    for normal, tangent, corners in faces:
        for corner, uv in zip(corners, uvs):
            verts.extend([*corner, *normal, *uv, *tangent])
        indices.extend([base, base + 1, base + 2, base, base + 2, base + 3])
        base += 4

    return np.array(verts, dtype=np.float32), np.array(indices, dtype=np.uint32)


def _build_plane(half_extent: float = 1.4) -> tuple[np.ndarray, np.ndarray]:
    s = half_extent
    normal = (0.0, 1.0, 0.0)
    tangent = (1.0, 0.0, 0.0)
    corners = [(-s, 0.0, s), (s, 0.0, s), (s, 0.0, -s), (-s, 0.0, -s)]
    uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]

    verts: list[float] = []
    for corner, uv in zip(corners, uvs):
        verts.extend([*corner, *normal, *uv, *tangent])
    indices = [0, 1, 2, 0, 2, 3]

    return np.array(verts, dtype=np.float32), np.array(indices, dtype=np.uint32)


def _build_grid(size: float = 4.0, divisions: int = 8) -> np.ndarray:
    y = -0.001
    lines = []
    step = (2 * size) / divisions
    for i in range(divisions + 1):
        c = -size + i * step
        lines.extend([c, y, -size, c, y, size])
        lines.extend([-size, y, c, size, y, c])
    return np.array(lines, dtype=np.float32)


def _build_fullscreen_triangle() -> np.ndarray:
    return np.array([-1.0, -1.0, 3.0, -1.0, -1.0, 3.0], dtype=np.float32)


# Degrees the auto-rotating model turns per frame at a speed setting of 1.
ROTATION_STEP = 0.2

class Preview3DWidget(QOpenGLWidget):
    distanceChanged = pyqtSignal(float)
    lightChanged = pyqtSignal(float, float)
    autoRotateToggled = pyqtSignal(bool)
    pivotChanged = pyqtSignal(float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFormat(QSurfaceFormat.defaultFormat())
        self.setMinimumHeight(260)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._azimuth = 35.0
        self._elevation = 20.0
        self._last_mouse_pos = None
        self._is_dragging = False

        # Pivot gizmo: arrows to move the pivot like an object's position.
        self._gizmo_visible = False
        self._gizmo_hover: Optional[int] = None     # axis under the pointer
        self._gizmo_axis: Optional[int] = None      # handle being dragged (0-2 axes, 3-5 planes)
        self._gizmo_hit0: Optional[np.ndarray] = None
        self._gizmo_pos: Optional[np.ndarray] = None  # where it is drawn while dragged
        self._gizmo_drag_start: Optional[np.ndarray] = None
        self._gizmo_drag_t0 = 0.0
        self._gizmo_camera = None                   # camera frozen during a drag
        self._pivot_anim: Optional[QVariantAnimation] = None

        self._settings = {
            "mesh": "plane",
            "fov": 75.0,
            "distance": 3.5,
            "auto_rotate_speed": 1.0,
            "pivot_x": 0.0,
            "pivot_y": 0.0,
            "pivot_z": 0.0,
            "light_intensity": 1.2,
            "env_intensity": 1.0,
            "exposure": 1.0,
            "show_grid": False,
            "auto_rotate": True,
            "wireframe": False,
            "pom_enabled": True,
            "pom_height_scale": 0.04,
            "pom_max_layers": 32,
            "background_brightness": 1.0,
            "light_azimuth": 45.0,
            "light_elevation": 50.0,
            "uv_tiling": 1.0,
        }
        self._ambient_color = (0.05, 0.05, 0.06)
        self._background_color = (0.05, 0.05, 0.06)

        self._albedo_image: Optional[Image.Image] = None
        self._normal_image: Optional[Image.Image] = None
        self._roughness_image: Optional[Image.Image] = None
        self._height_image: Optional[Image.Image] = None
        self._ao_image: Optional[Image.Image] = None
        self._albedo_source: Optional[Image.Image] = None
        self._normal_source: Optional[Image.Image] = None
        self._roughness_source: Optional[Image.Image] = None
        self._height_source: Optional[Image.Image] = None
        self._height_ref: float = 1.0
        self._ao_source: Optional[Image.Image] = None
        self._texture_upload_needed: set[str] = set()
        self._roughness_value = 0.5
        self._hdri_image: Optional[Image.Image] = None
        self._hdri_pending_upload = False

        self._gl_ready = False
        self._pending_texture_upload = False

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()

    def set_textures(
        self,
        albedo: Optional[Image.Image],
        normal: Optional[Image.Image],
        roughness: Optional[Image.Image] = None,
        height: Optional[Image.Image] = None,
        ao: Optional[Image.Image] = None,
    ) -> None:
        changed: set[str] = set()
        if albedo is not self._albedo_source:
            self._albedo_source = albedo
            self._albedo_image = albedo.convert("RGB") if albedo is not None else None
            changed.add("albedo")
        if normal is not self._normal_source:
            self._normal_source = normal
            self._normal_image = normal.convert("RGB") if normal is not None else None
            changed.add("normal")
        if roughness is not self._roughness_source:
            self._roughness_source = roughness
            self._roughness_image = _to_gray8(roughness) if roughness is not None else None
            changed.add("roughness")
        if height is not self._height_source:
            self._height_source = height
            if height is not None:
                self._height_image = _to_gray8(height)
                self._height_ref = float(np.asarray(self._height_image, dtype=np.float32).mean() / 255.0)
            else:
                self._height_image = None
                self._height_ref = 1.0
            changed.add("height")
        if ao is not self._ao_source:
            self._ao_source = ao
            # A saved AO map is 16-bit (the panel's bit depth) while drafts are 8-bit; a plain
            # convert("L") clips 16-bit values to white, which made AO vanish from the view after Save.
            self._ao_image = _to_gray8(ao) if ao is not None else None
            changed.add("ao")

        self._texture_upload_needed.update(changed)
        if self._gl_ready and changed:
            self._upload_textures()
        elif changed:
            self._pending_texture_upload = True
        self.update()

    def set_preview_settings(self, data: dict) -> None:
        self._settings.update(data)
        hdri_path = data.get("hdri_path")
        if hdri_path != getattr(self, "_hdri_path_loaded", None):
            self._hdri_path_loaded = hdri_path
            self._update_environment_color(hdri_path)
        self.update()

    def _update_environment_color(self, hdri_path: Optional[str]) -> None:
        if not hdri_path:
            self._ambient_color = (0.05, 0.05, 0.06)
            self._background_color = (0.05, 0.05, 0.06)
            self._hdri_image = None
            self._queue_hdri_upload()
            return
        try:
            with Image.open(hdri_path) as raw:
                rgb = raw.convert("RGB")
                rgb.thumbnail((2048, 1024))
                self._hdri_image = rgb.copy()
                img_small = rgb.resize((32, 16))
            arr = np.asarray(img_small, dtype=np.float32) / 255.0
            avg = arr.reshape(-1, 3).mean(axis=0)
            self._ambient_color = tuple(float(c) for c in avg)
            self._background_color = tuple(float(c) for c in avg)
        except Exception:
            self._ambient_color = (0.05, 0.05, 0.06)
            self._background_color = (0.05, 0.05, 0.06)
            self._hdri_image = None
        self._queue_hdri_upload()

    def _queue_hdri_upload(self) -> None:
        if self._gl_ready:
            self._upload_hdri_texture()
        else:
            self._hdri_pending_upload = True

    def initializeGL(self) -> None:
        drained = 0
        while gl.glGetError() != gl.GL_NO_ERROR and drained < 500:
            drained += 1
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glEnable(gl.GL_MULTISAMPLE)

        self._program = self._build_program(VERTEX_SHADER, FRAGMENT_SHADER)
        self._grid_program = self._build_program(GRID_VERTEX_SHADER, GRID_FRAGMENT_SHADER)
        self._uniforms = self._cache_uniform_locations(self._program, [
            "uModel", "uView", "uProj", "uCamPos", "uLightDir", "uLightIntensity",
            "uEnvIntensity", "uExposure", "uAmbientColor", "uRoughnessValue",
            "uHasAlbedo", "uHasNormal", "uHasRoughnessTex",
            "uHasHeight", "uPOMEnabled", "uPOMHeightScale", "uPOMRefHeight", "uPOMMaxLayers",
            "uAlbedoTex", "uNormalTex", "uRoughnessTex", "uHeightTex", "uUVScale",
            "uAOTex", "uHasAO", "uSkyAmbient",
        ])
        self._grid_uniforms = self._cache_uniform_locations(self._grid_program, ["uView", "uProj", "uColor"])

        self._bg_program = self._build_program(BACKGROUND_VERTEX_SHADER, BACKGROUND_FRAGMENT_SHADER)
        self._bg_uniforms = self._cache_uniform_locations(self._bg_program, [
            "uCamForward", "uCamRight", "uCamUp", "uTanHalfFov", "uAspect",
            "uHdriTex", "uHasHdri", "uFlatColor", "uBrightness", "uSunDir",
        ])
        bg_verts = _build_fullscreen_triangle()
        self._bg_vao = gl.glGenVertexArrays(1)
        gl.glBindVertexArray(self._bg_vao)
        bg_vbo = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, bg_vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, bg_verts.nbytes, bg_verts, gl.GL_STATIC_DRAW)
        gl.glVertexAttribPointer(0, 2, gl.GL_FLOAT, gl.GL_FALSE, 2 * 4, ctypes.c_void_p(0))
        gl.glEnableVertexAttribArray(0)
        gl.glBindVertexArray(0)

        self._meshes = {
            "sphere": self._upload_mesh(*_build_uv_sphere()),
            "cube": self._upload_mesh(*_build_cube()),
            "plane": self._upload_mesh(*_build_plane()),
        }

        grid_verts = _build_grid()
        self._grid_vertex_count = len(grid_verts) // 3
        self._grid_vao = gl.glGenVertexArrays(1)
        gl.glBindVertexArray(self._grid_vao)
        grid_vbo = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, grid_vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, grid_verts.nbytes, grid_verts, gl.GL_STATIC_DRAW)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 3 * 4, ctypes.c_void_p(0))
        gl.glEnableVertexAttribArray(0)
        gl.glBindVertexArray(0)

        self._albedo_tex = self._make_placeholder_texture((191, 191, 191))
        self._normal_tex = self._make_placeholder_texture((128, 128, 255))
        self._roughness_tex = self._make_placeholder_texture((128, 128, 128))
        self._height_tex = self._make_placeholder_texture((0, 0, 0))
        self._ao_tex = self._make_placeholder_texture((255, 255, 255))
        self._hdri_tex = self._make_placeholder_texture((13, 13, 15))

        self._gl_ready = True
        if self._pending_texture_upload:
            self._upload_textures()
            self._pending_texture_upload = False
        if self._hdri_pending_upload:
            self._upload_hdri_texture()
            self._hdri_pending_upload = False

    def _build_program(self, vs_src: str, fs_src: str) -> int:
        vs = gl.glCreateShader(gl.GL_VERTEX_SHADER)
        gl.glShaderSource(vs, vs_src)
        gl.glCompileShader(vs)
        if not gl.glGetShaderiv(vs, gl.GL_COMPILE_STATUS):
            raise RuntimeError(gl.glGetShaderInfoLog(vs).decode())

        fs = gl.glCreateShader(gl.GL_FRAGMENT_SHADER)
        gl.glShaderSource(fs, fs_src)
        gl.glCompileShader(fs)
        if not gl.glGetShaderiv(fs, gl.GL_COMPILE_STATUS):
            raise RuntimeError(gl.glGetShaderInfoLog(fs).decode())

        program = gl.glCreateProgram()
        gl.glAttachShader(program, vs)
        gl.glAttachShader(program, fs)
        gl.glLinkProgram(program)
        if not gl.glGetProgramiv(program, gl.GL_LINK_STATUS):
            raise RuntimeError(gl.glGetProgramInfoLog(program).decode())
        gl.glDeleteShader(vs)
        gl.glDeleteShader(fs)
        return program

    @staticmethod
    def _cache_uniform_locations(program: int, names: list[str]) -> dict[str, int]:
        return {name: gl.glGetUniformLocation(program, name) for name in names}

    @staticmethod
    def _upload_mesh(verts: np.ndarray, indices: np.ndarray) -> tuple[int, int]:
        vao = gl.glGenVertexArrays(1)
        gl.glBindVertexArray(vao)
        vbo = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, verts.nbytes, verts, gl.GL_STATIC_DRAW)
        ebo = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, ebo)
        gl.glBufferData(gl.GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, gl.GL_STATIC_DRAW)

        stride = 11 * 4
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, stride, ctypes.c_void_p(0))
        gl.glEnableVertexAttribArray(0)
        gl.glVertexAttribPointer(1, 3, gl.GL_FLOAT, gl.GL_FALSE, stride, ctypes.c_void_p(3 * 4))
        gl.glEnableVertexAttribArray(1)
        gl.glVertexAttribPointer(2, 2, gl.GL_FLOAT, gl.GL_FALSE, stride, ctypes.c_void_p(6 * 4))
        gl.glEnableVertexAttribArray(2)
        gl.glVertexAttribPointer(3, 3, gl.GL_FLOAT, gl.GL_FALSE, stride, ctypes.c_void_p(8 * 4))
        gl.glEnableVertexAttribArray(3)
        gl.glBindVertexArray(0)
        return vao, len(indices)

    def _make_placeholder_texture(self, rgb: tuple[int, int, int]) -> int:
        tex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
        data = bytes(rgb) * 4
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGB, 2, 2, 0, gl.GL_RGB, gl.GL_UNSIGNED_BYTE, data)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT)
        return tex

    def _upload_image_texture(self, tex: int, image: Image.Image) -> None:
        arr = np.asarray(image)
        h, w = arr.shape[0], arr.shape[1]
        fmt = gl.GL_RGB if arr.ndim == 3 and arr.shape[2] == 3 else gl.GL_RED
        gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGB if fmt == gl.GL_RGB else gl.GL_RED,
                         w, h, 0, fmt, gl.GL_UNSIGNED_BYTE, np.ascontiguousarray(arr))
        gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT)

    def _upload_textures(self) -> None:
        pending = self._texture_upload_needed.copy()
        if not pending:
            return
        self.makeCurrent()
        if "albedo" in pending and self._albedo_image is not None:
            self._upload_image_texture(self._albedo_tex, self._albedo_image)
        if "normal" in pending and self._normal_image is not None:
            self._upload_image_texture(self._normal_tex, self._normal_image)
        if "roughness" in pending and self._roughness_image is not None:
            self._upload_image_texture(self._roughness_tex, self._roughness_image)
        if "height" in pending and self._height_image is not None:
            self._upload_image_texture(self._height_tex, self._height_image)
        if "ao" in pending and self._ao_image is not None:
            self._upload_image_texture(self._ao_tex, self._ao_image)
        self.doneCurrent()
        self._texture_upload_needed.difference_update(pending)

    def _upload_hdri_texture(self) -> None:
        self.makeCurrent()
        if self._hdri_image is not None:
            self._upload_image_texture(self._hdri_tex, self._hdri_image)
        self.doneCurrent()

    def resizeGL(self, w: int, h: int) -> None:
        dpr = self.devicePixelRatio()
        gl.glViewport(0, 0, max(1, int(round(w * dpr))), max(1, int(round(h * dpr))))

    def _on_tick(self) -> None:
        if self._settings.get("auto_rotate") and not self._is_dragging:
            self._azimuth = (self._azimuth + self._settings.get("auto_rotate_speed", 1.0) * ROTATION_STEP) % 360.0
            self.update()

    # -- camera ---------------------------------------------------------------

    def _pivot(self) -> np.ndarray:
        return np.array([
            self._settings.get("pivot_x", 0.0),
            self._settings.get("pivot_y", 0.0),
            self._settings.get("pivot_z", 0.0),
        ], dtype=np.float64)

    def _camera(self) -> dict:
        """Camera position and row-major view/projection matrices."""
        aspect = max(self.width(), 1) / max(self.height(), 1)
        fov = self._settings.get("fov", 45.0)
        distance = self._settings.get("distance", 3.5)
        az = math.radians(self._azimuth)
        el = math.radians(self._elevation)
        offset = np.array([
            distance * math.cos(el) * math.sin(az),
            distance * math.sin(el),
            distance * math.cos(el) * math.cos(az),
        ])
        pivot = self._pivot()
        cam_pos = pivot + offset
        view = _look_at(cam_pos.astype(np.float32), pivot.astype(np.float32), np.array([0.0, 1.0, 0.0], dtype=np.float32)).T
        proj = _perspective(fov, aspect, 0.01, 100.0).T
        return {"cam_pos": cam_pos, "view": view.astype(np.float64), "proj": proj.astype(np.float64), "fov": fov}

    def _project(self, cam: dict, point: np.ndarray) -> Optional[QPointF]:
        clip = cam["proj"] @ cam["view"] @ np.append(point, 1.0)
        if clip[3] <= 1e-6:
            return None
        ndc = clip[:3] / clip[3]
        return QPointF((ndc[0] + 1.0) * 0.5 * self.width(), (1.0 - ndc[1]) * 0.5 * self.height())

    def _mouse_ray(self, cam: dict, pos: QPointF) -> tuple[np.ndarray, np.ndarray]:
        x = 2.0 * pos.x() / max(self.width(), 1) - 1.0
        y = 1.0 - 2.0 * pos.y() / max(self.height(), 1)
        inverse = np.linalg.inv(cam["proj"] @ cam["view"])
        near = inverse @ np.array([x, y, -1.0, 1.0])
        far = inverse @ np.array([x, y, 1.0, 1.0])
        near, far = near[:3] / near[3], far[:3] / far[3]
        direction = far - near
        return near, direction / max(np.linalg.norm(direction), 1e-12)

    # -- pivot gizmo ----------------------------------------------------------

    GIZMO_ARROW_PX = 78.0
    GIZMO_PICK_PX = 9.0
    # Plane squares: from this far along both axes, this big (share of the arrow).
    GIZMO_PLANE_OFFSET = 0.16
    GIZMO_PLANE_SIZE = 0.24
    _GIZMO_AXES = (np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0]), np.array([0.0, 0.0, 1.0]))
    _GIZMO_COLORS = ("#e5484d", "#46a758", "#3e7bfa")
    _GIZMO_ACTIVE = "#ffc53d"
    # Handles 0-2 are the axis arrows; 3-5 the plane squares, each given as its
    # two axes. A square takes the colour of the axis it is perpendicular to.
    _GIZMO_PLANES = ((0, 1), (1, 2), (0, 2))   # XY, YZ, XZ
    _GIZMO_PLANE_NORMAL = (2, 0, 1)
    # Handle 6 is the dot in the middle: double-clicking it puts the pivot
    # back at the origin.
    _GIZMO_CENTER = 6
    GIZMO_CENTER_PX = 7.0

    def set_pivot_gizmo_visible(self, visible: bool) -> None:
        """Show or hide the arrows that move the camera pivot."""
        self._gizmo_visible = bool(visible)
        self._gizmo_hover = None
        self.setMouseTracking(self._gizmo_visible)
        self.update()

    def is_pivot_gizmo_visible(self) -> bool:
        return self._gizmo_visible

    def _gizmo_origin(self) -> np.ndarray:
        return self._gizmo_pos if self._gizmo_pos is not None else self._pivot()

    def _gizmo_geometry(self, cam: dict):
        """Screen shapes of the gizmo, sized to stay the same on screen at any
        distance: the origin, each arrow's tip, and each plane square's corners.
        Arrows and squares point to the side of each axis that faces the camera."""
        origin = self._gizmo_origin()
        o = self._project(cam, origin)
        if o is None:
            return None
        forward = -cam["view"][2, :3]
        depth = max(float(np.dot(origin - cam["cam_pos"], forward)), 1e-3)
        world_per_px = 2.0 * math.tan(math.radians(cam["fov"]) / 2.0) * depth / max(self.height(), 1)
        length = self.GIZMO_ARROW_PX * world_per_px
        directions = self._gizmo_directions(cam, origin)
        tips = [self._project(cam, origin + axis * length) for axis in directions]
        planes = []
        for a, b in self._GIZMO_PLANES:
            ua, ub = directions[a], directions[b]
            lo, hi = self.GIZMO_PLANE_OFFSET * length, (self.GIZMO_PLANE_OFFSET + self.GIZMO_PLANE_SIZE) * length
            corners = [origin + ua * i + ub * j for i, j in ((lo, lo), (hi, lo), (hi, hi), (lo, hi))]
            points = [self._project(cam, c) for c in corners]
            planes.append(None if any(pt is None for pt in points) else QPolygonF(points))
        return o, tips, planes

    def _gizmo_directions(self, cam: dict, origin: np.ndarray) -> list[np.ndarray]:
        """Each axis, flipped to point toward the camera's side."""
        to_camera = cam["cam_pos"] - origin
        return [axis * (1.0 if axis @ to_camera >= 0 else -1.0) for axis in self._GIZMO_AXES]

    @staticmethod
    def _polygon_area(poly: QPolygonF) -> float:
        pts = [poly[i] for i in range(poly.count())]
        return abs(sum(pts[i].x() * pts[i - 1].y() - pts[i - 1].x() * pts[i].y() for i in range(len(pts)))) / 2.0

    def _gizmo_pick(self, pos: QPointF) -> Optional[int]:
        cam = self._gizmo_camera or self._camera()
        geometry = self._gizmo_geometry(cam)
        if geometry is None:
            return None
        o, tips, planes = geometry
        if math.hypot(pos.x() - o.x(), pos.y() - o.y()) <= self.GIZMO_CENTER_PX:
            return self._GIZMO_CENTER
        # Plane squares first: they are small and sit between the arrows.
        for index, poly in enumerate(planes):
            if poly is not None and self._polygon_area(poly) > 40.0 and poly.containsPoint(pos, Qt.FillRule.OddEvenFill):
                return 3 + index
        best, best_dist = None, self.GIZMO_PICK_PX
        for index, tip in enumerate(tips):
            if tip is None:
                continue
            seg = np.array([tip.x() - o.x(), tip.y() - o.y()])
            seg_len2 = float(seg @ seg)
            if seg_len2 < 100.0:  # pointing at the camera: too short to grab
                continue
            rel = np.array([pos.x() - o.x(), pos.y() - o.y()])
            t = max(0.0, min(1.0, float(rel @ seg) / seg_len2))
            dist = float(np.linalg.norm(rel - seg * t))
            if dist < best_dist:
                best, best_dist = index, dist
        return best

    def _axis_param(self, cam: dict, pos: QPointF, origin: np.ndarray, axis: np.ndarray) -> Optional[float]:
        """Where along the axis line through `origin` the mouse ray passes closest."""
        ray_origin, ray_dir = self._mouse_ray(cam, pos)
        w0 = origin - ray_origin
        b = float(axis @ ray_dir)
        denom = 1.0 - b * b
        if denom < 1e-4:  # axis almost along the view ray
            return None
        d = float(axis @ w0)
        e = float(ray_dir @ w0)
        return (b * e - d) / denom

    def _plane_hit(self, cam: dict, pos: QPointF, origin: np.ndarray, normal: np.ndarray) -> Optional[np.ndarray]:
        """Where the mouse ray meets the plane through `origin`."""
        ray_origin, ray_dir = self._mouse_ray(cam, pos)
        facing = float(ray_dir @ normal)
        if abs(facing) < 1e-3:  # plane seen edge-on
            return None
        t = float((origin - ray_origin) @ normal) / facing
        if t <= 0.0:
            return None
        return ray_origin + ray_dir * t

    def _handle_active(self, index: int) -> bool:
        if self._gizmo_axis is not None:
            return index == self._gizmo_axis
        return index == self._gizmo_hover

    def _paint_gizmo(self) -> None:
        cam = self._gizmo_camera or self._camera()
        geometry = self._gizmo_geometry(cam)
        if geometry is None:
            return
        o, tips, planes = geometry
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for index, poly in enumerate(planes):
            if poly is None:
                continue
            handle = 3 + index
            base = QColor(self._GIZMO_ACTIVE if self._handle_active(handle) else self._GIZMO_COLORS[self._GIZMO_PLANE_NORMAL[index]])
            edge_on = self._polygon_area(poly) <= 40.0
            fill, line = QColor(base), QColor(base)
            fill.setAlphaF(0.12 if edge_on else (0.45 if self._handle_active(handle) else 0.28))
            line.setAlphaF(0.3 if edge_on else 0.95)
            painter.setPen(QPen(line, 1.25))
            painter.setBrush(fill)
            painter.drawPolygon(poly)
        # Farther arrows first, so the nearer ones draw over them.
        forward = -cam["view"][2, :3]
        directions = self._gizmo_directions(cam, self._gizmo_origin())
        order = sorted(range(3), key=lambda i: -float(directions[i] @ forward))
        for index in order:
            tip = tips[index]
            if tip is None:
                continue
            dx, dy = tip.x() - o.x(), tip.y() - o.y()
            length = math.hypot(dx, dy)
            color = QColor(self._GIZMO_ACTIVE if self._handle_active(index) else self._GIZMO_COLORS[index])
            if length < 10.0:
                color.setAlphaF(0.35)
            if length < 1.0:
                continue
            ux, uy = dx / length, dy / length
            head = 11.0
            base = QPointF(tip.x() - ux * head, tip.y() - uy * head)
            pen = QPen(color, 2.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(o, base)
            path = QPainterPath(tip)
            path.lineTo(base.x() - uy * 4.5, base.y() + ux * 4.5)
            path.lineTo(base.x() + uy * 4.5, base.y() - ux * 4.5)
            path.closeSubpath()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawPath(path)
        center_active = self._gizmo_hover == self._GIZMO_CENTER and self._gizmo_axis is None
        painter.setPen(QPen(QColor(0, 0, 0, 140), 1.0))
        painter.setBrush(QColor(self._GIZMO_ACTIVE if center_active else "#f2f2f2"))
        radius = 4.5 if center_active else 3.5
        painter.drawEllipse(o, radius, radius)
        painter.end()

    def _move_pivot_keeping_camera(self, target: np.ndarray) -> None:
        """Make `target` the pivot without moving the camera: it stays where it
        is and turns to face the new pivot over a short animation."""
        cam_pos = self._camera()["cam_pos"]
        start = self._pivot()
        if self._pivot_anim is not None:
            self._pivot_anim.stop()

        def apply(t) -> None:
            pivot = start + (target - start) * float(t)
            offset = cam_pos - pivot
            distance = float(np.linalg.norm(offset))
            if distance < 1e-4:
                return
            self._settings["pivot_x"], self._settings["pivot_y"], self._settings["pivot_z"] = (
                round(float(c), 3) for c in pivot
            )
            self._settings["distance"] = max(0.01, min(20.0, distance))
            self._elevation = max(-85.0, min(85.0, math.degrees(math.asin(max(-1.0, min(1.0, offset[1] / distance))))))
            self._azimuth = math.degrees(math.atan2(offset[0], offset[2])) % 360.0
            self.update()

        def finished() -> None:
            self._gizmo_pos = None
            self.pivotChanged.emit(self._settings["pivot_x"], self._settings["pivot_y"], self._settings["pivot_z"])
            self.distanceChanged.emit(self._settings["distance"])
            self.update()

        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(300)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(apply)
        anim.finished.connect(finished)
        self._pivot_anim = anim
        anim.start()

    def paintGL(self) -> None:
        # QPainter (the pivot gizmo) leaves its own GL state behind.
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_BLEND)
        gl.glDisable(gl.GL_SCISSOR_TEST)
        gl.glDisable(gl.GL_STENCIL_TEST)
        dpr = self.devicePixelRatio()
        gl.glViewport(0, 0, max(1, int(round(self.width() * dpr))), max(1, int(round(self.height() * dpr))))
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)

        aspect = max(self.width(), 1) / max(self.height(), 1)
        fov = self._settings.get("fov", 45.0)
        proj = _perspective(fov, aspect, 0.01, 100.0)

        distance = self._settings.get("distance", 3.5)
        az = math.radians(self._azimuth)
        el = math.radians(self._elevation)
        orbit_offset = np.array([
            distance * math.cos(el) * math.sin(az),
            distance * math.sin(el),
            distance * math.cos(el) * math.cos(az),
        ], dtype=np.float32)

        pivot = np.array([
            self._settings.get("pivot_x", 0.0),
            self._settings.get("pivot_y", 0.0),
            self._settings.get("pivot_z", 0.0),
        ], dtype=np.float32)

        cam_pos = pivot + orbit_offset
        world_up = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        view = _look_at(cam_pos, pivot, world_up)
        model = np.identity(4, dtype=np.float32)

        cam_forward = -orbit_offset / max(np.linalg.norm(orbit_offset), 1e-6)
        cam_right = np.cross(cam_forward, world_up)
        cam_right = cam_right / max(np.linalg.norm(cam_right), 1e-6)
        cam_up = np.cross(cam_right, cam_forward)

        light_az = math.radians(self._settings.get("light_azimuth", 45.0))
        light_el = math.radians(self._settings.get("light_elevation", 50.0))
        light_source_dir = (
            math.cos(light_el) * math.sin(light_az),
            math.sin(light_el),
            math.cos(light_el) * math.cos(light_az),
        )
        light_dir = tuple(-c for c in light_source_dir)

        bg_brightness = self._settings.get("background_brightness", 1.0)
        bu = self._bg_uniforms
        gl.glDepthMask(gl.GL_FALSE)
        gl.glUseProgram(self._bg_program)
        gl.glUniform3f(bu["uCamForward"], *cam_forward.tolist())
        gl.glUniform3f(bu["uCamRight"], *cam_right.tolist())
        gl.glUniform3f(bu["uCamUp"], *cam_up.tolist())
        gl.glUniform1f(bu["uTanHalfFov"], math.tan(math.radians(fov) / 2.0))
        gl.glUniform1f(bu["uAspect"], aspect)
        gl.glUniform1i(bu["uHasHdri"], 1 if self._hdri_image is not None else 0)
        gl.glUniform3f(bu["uFlatColor"], *self._background_color)
        gl.glUniform1f(bu["uBrightness"], bg_brightness)
        gl.glUniform3f(bu["uSunDir"], *light_source_dir)
        gl.glActiveTexture(gl.GL_TEXTURE4)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._hdri_tex)
        gl.glUniform1i(bu["uHdriTex"], 4)
        gl.glBindVertexArray(self._bg_vao)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)
        gl.glBindVertexArray(0)
        gl.glDepthMask(gl.GL_TRUE)

        u = self._uniforms
        gl.glUseProgram(self._program)
        self._set_mat4(u["uModel"], model)
        self._set_mat4(u["uView"], view)
        self._set_mat4(u["uProj"], proj)
        gl.glUniform3f(u["uCamPos"], *cam_pos.tolist())
        gl.glUniform3f(u["uLightDir"], *light_dir)
        gl.glUniform1f(u["uLightIntensity"], self._settings.get("light_intensity", 1.2))
        gl.glUniform1f(u["uEnvIntensity"], self._settings.get("env_intensity", 1.0))
        gl.glUniform1f(u["uExposure"], self._settings.get("exposure", 1.0))
        gl.glUniform3f(u["uAmbientColor"], *self._ambient_color)
        gl.glUniform1i(u["uSkyAmbient"], 1 if self._hdri_image is None else 0)
        gl.glUniform1f(u["uRoughnessValue"], self._roughness_value)
        gl.glUniform1i(u["uHasAlbedo"], 1 if self._albedo_image is not None else 0)
        gl.glUniform1i(u["uHasNormal"], 1 if self._normal_image is not None else 0)
        gl.glUniform1i(u["uHasRoughnessTex"], 1 if self._roughness_image is not None else 0)
        gl.glUniform1i(u["uHasHeight"], 1 if self._height_image is not None else 0)
        gl.glUniform1i(u["uHasAO"], 1 if self._ao_image is not None else 0)
        gl.glUniform1i(u["uPOMEnabled"], 1 if self._settings.get("pom_enabled", True) else 0)
        gl.glUniform1f(u["uPOMHeightScale"], self._settings.get("pom_height_scale", 0.04))
        gl.glUniform1f(u["uPOMRefHeight"], self._height_ref)
        gl.glUniform1i(u["uPOMMaxLayers"], self._settings.get("pom_max_layers", 32))
        gl.glUniform1f(u["uUVScale"], float(self._settings.get("uv_tiling", 1.0)))

        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._albedo_tex)
        gl.glUniform1i(u["uAlbedoTex"], 0)
        gl.glActiveTexture(gl.GL_TEXTURE1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._normal_tex)
        gl.glUniform1i(u["uNormalTex"], 1)
        gl.glActiveTexture(gl.GL_TEXTURE2)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._roughness_tex)
        gl.glUniform1i(u["uRoughnessTex"], 2)
        gl.glActiveTexture(gl.GL_TEXTURE3)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._height_tex)
        gl.glUniform1i(u["uHeightTex"], 3)
        gl.glActiveTexture(gl.GL_TEXTURE5)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._ao_tex)
        gl.glUniform1i(u["uAOTex"], 5)

        mesh_vao, mesh_index_count = self._meshes.get(self._settings.get("mesh", "plane"), self._meshes["plane"])
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_LINE if self._settings.get("wireframe") else gl.GL_FILL)
        gl.glBindVertexArray(mesh_vao)
        gl.glDrawElements(gl.GL_TRIANGLES, mesh_index_count, gl.GL_UNSIGNED_INT, None)
        gl.glBindVertexArray(0)
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)

        if self._settings.get("show_grid"):
            gu = self._grid_uniforms
            gl.glUseProgram(self._grid_program)
            self._set_mat4(gu["uView"], view)
            self._set_mat4(gu["uProj"], proj)
            gl.glUniform3f(gu["uColor"], 0.35, 0.35, 0.38)
            gl.glBindVertexArray(self._grid_vao)
            gl.glDrawArrays(gl.GL_LINES, 0, self._grid_vertex_count)
            gl.glBindVertexArray(0)

        if self._gizmo_visible:
            gl.glUseProgram(0)
            self._paint_gizmo()

    @staticmethod
    def _set_mat4(location: int, mat: np.ndarray) -> None:
        gl.glUniformMatrix4fv(location, 1, gl.GL_FALSE, mat)

    def mousePressEvent(self, event) -> None:
        self._last_mouse_pos = event.position()
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._is_dragging = True
            if self._gizmo_visible and self._start_gizmo_drag(event.position()):
                return

    def _start_gizmo_drag(self, pos: QPointF) -> bool:
        if self._pivot_anim is not None and self._pivot_anim.state() == QVariantAnimation.State.Running:
            return False
        handle = self._gizmo_pick(pos)
        if handle is None:
            return False
        if handle == self._GIZMO_CENTER:
            # Taken, so it does not turn the camera; a double-click resets it.
            self._gizmo_center_pressed = True
            return True
        cam = self._camera()
        origin = self._pivot()
        if handle < 3:
            t0 = self._axis_param(cam, pos, origin, self._GIZMO_AXES[handle])
            if t0 is None:
                return False
        else:
            normal = self._GIZMO_AXES[self._GIZMO_PLANE_NORMAL[handle - 3]]
            self._gizmo_hit0 = self._plane_hit(cam, pos, origin, normal)
            if self._gizmo_hit0 is None:
                return False
            t0 = 0.0
        self._gizmo_axis = handle
        self._gizmo_camera = cam  # the camera holds still while the pivot moves
        self._gizmo_drag_start = origin
        self._gizmo_drag_t0 = t0
        self._gizmo_pos = origin.copy()
        self.update()
        return True

    def mouseDoubleClickEvent(self, event) -> None:
        if (
            self._gizmo_visible
            and event.button() == Qt.MouseButton.LeftButton
            and self._gizmo_pick(event.position()) == self._GIZMO_CENTER
        ):
            self._gizmo_center_pressed = True
            if float(np.linalg.norm(self._pivot())) > 1e-6:
                self._move_pivot_keeping_camera(np.zeros(3))
            return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if getattr(self, "_gizmo_center_pressed", False) and event.buttons() & Qt.MouseButton.LeftButton:
            return
        if self._gizmo_axis is not None:
            handle = self._gizmo_axis
            if handle < 3:
                axis = self._GIZMO_AXES[handle]
                t = self._axis_param(self._gizmo_camera, event.position(), self._gizmo_drag_start, axis)
                if t is not None:
                    self._gizmo_pos = np.round(self._gizmo_drag_start + axis * (t - self._gizmo_drag_t0), 3)
            else:
                normal = self._GIZMO_AXES[self._GIZMO_PLANE_NORMAL[handle - 3]]
                hit = self._plane_hit(self._gizmo_camera, event.position(), self._gizmo_drag_start, normal)
                if hit is not None:
                    delta = hit - self._gizmo_hit0
                    delta -= normal * float(delta @ normal)  # stay exactly in the plane
                    # Near the horizon a small mouse move would throw the point far away.
                    reach = float(np.linalg.norm(delta))
                    if reach > 10.0:
                        delta *= 10.0 / reach
                    self._gizmo_pos = np.round(self._gizmo_drag_start + delta, 3)
            self.update()
            return
        if self._gizmo_visible and not (event.buttons() & Qt.MouseButton.LeftButton):
            hover = self._gizmo_pick(event.position())
            if hover != self._gizmo_hover:
                self._gizmo_hover = hover
                self.update()
            return
        if self._last_mouse_pos is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        pos = event.position()
        dx = pos.x() - self._last_mouse_pos.x()
        dy = pos.y() - self._last_mouse_pos.y()
        self._last_mouse_pos = pos
        self._apply_drag(dx, dy, event.modifiers())

    def _apply_drag(self, dx: float, dy: float, modifiers) -> None:
        is_pan = bool(modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier))

        if is_pan:
            distance = self._settings.get("distance", 3.5)
            az = math.radians(self._azimuth)
            el = math.radians(self._elevation)
            cam_forward = np.array([
                -math.cos(el) * math.sin(az),
                -math.sin(el),
                -math.cos(el) * math.cos(az),
            ], dtype=np.float32)
            world_up = np.array([0.0, 1.0, 0.0], dtype=np.float32)
            cam_right = np.cross(cam_forward, world_up)
            norm_r = np.linalg.norm(cam_right)
            if norm_r > 1e-6:
                cam_right /= norm_r
            cam_up = np.cross(cam_right, cam_forward)
            norm_u = np.linalg.norm(cam_up)
            if norm_u > 1e-6:
                cam_up /= norm_u

            pan_speed = max(0.001, distance * 0.002)
            dx_pan = -dx * pan_speed
            dy_pan = dy * pan_speed

            delta_pivot = cam_right * dx_pan + cam_up * dy_pan
            new_px = round(float(self._settings.get("pivot_x", 0.0) + delta_pivot[0]), 3)
            new_py = round(float(self._settings.get("pivot_y", 0.0) + delta_pivot[1]), 3)
            new_pz = round(float(self._settings.get("pivot_z", 0.0) + delta_pivot[2]), 3)

            self._settings["pivot_x"] = new_px
            self._settings["pivot_y"] = new_py
            self._settings["pivot_z"] = new_pz
            self.pivotChanged.emit(new_px, new_py, new_pz)
            self.update()
        elif modifiers & Qt.KeyboardModifier.ShiftModifier:
            new_az = (self._settings.get("light_azimuth", 45.0) + dx * 0.5) % 360.0
            new_el = max(-90.0, min(90.0, self._settings.get("light_elevation", 50.0) - dy * 0.5))
            self._settings["light_azimuth"] = new_az
            self._settings["light_elevation"] = new_el
            self.lightChanged.emit(new_az, new_el)
            self.update()
        else:
            self._azimuth = (self._azimuth - dx * 0.4) % 360.0
            self._elevation = max(-85.0, min(85.0, self._elevation + dy * 0.4))
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._last_mouse_pos = None
        self._is_dragging = False
        self._gizmo_center_pressed = False
        if self._gizmo_axis is not None:
            target = self._gizmo_pos
            self._gizmo_axis = None
            self._gizmo_camera = None
            self._gizmo_hover = self._gizmo_pick(event.position())
            if target is not None and float(np.linalg.norm(target - self._pivot())) > 1e-6:
                self._move_pivot_keeping_camera(target)
            else:
                self._gizmo_pos = None
                self.update()

    def leaveEvent(self, event) -> None:
        if self._gizmo_hover is not None:
            self._gizmo_hover = None
            self.update()
        super().leaveEvent(event)

    def wheelEvent(self, event) -> None:
        if trackpad.is_trackpad_scroll(event):
            d = trackpad.scroll_delta(event)
            self._apply_drag(d.x(), d.y(), event.modifiers())
            return
        delta = event.angleDelta().y() / 120.0
        current_distance = self._settings.get("distance", 3.5)
        step = 0.05 if current_distance <= 1.0 else 0.2
        self._set_distance(current_distance - delta * step)

    def _set_distance(self, distance: float) -> None:
        new_distance = max(0.01, min(20.0, distance))
        self._settings["distance"] = new_distance
        self.distanceChanged.emit(new_distance)
        self.update()

    def event(self, event) -> bool:
        factor = trackpad.pinch_factor(event)
        if factor is not None:
            self._set_distance(self._settings.get("distance", 3.5) / factor)
            return True
        if trackpad.is_smart_zoom(event):
            self.reset_camera()
            return True
        return super().event(event)

    def reset_camera(self) -> None:
        self._azimuth = 35.0
        self._elevation = 20.0
        self._settings["distance"] = 3.5
        self._settings["pivot_x"] = 0.0
        self._settings["pivot_y"] = 0.0
        self._settings["pivot_z"] = 0.0
        self.distanceChanged.emit(3.5)
        self.pivotChanged.emit(0.0, 0.0, 0.0)
        self.update()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_F:
            self.reset_camera()
        elif event.key() == Qt.Key.Key_Space:
            auto = not self._settings.get("auto_rotate", True)
            self._settings["auto_rotate"] = auto
            self.autoRotateToggled.emit(auto)
            self.update()
        else:
            super().keyPressEvent(event)


def _perspective(fov_deg: float, aspect: float, near: float, far: float) -> np.ndarray:
    f = 1.0 / math.tan(math.radians(fov_deg) / 2.0)
    m = np.zeros((4, 4), dtype=np.float32)
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = (2 * far * near) / (near - far)
    m[3, 2] = -1.0
    return m.T.copy()


def _look_at(eye: np.ndarray, center: np.ndarray, up: np.ndarray) -> np.ndarray:
    f = center - eye
    f = f / np.linalg.norm(f)
    s = np.cross(f, up)
    s = s / np.linalg.norm(s)
    u = np.cross(s, f)
    m = np.identity(4, dtype=np.float32)
    m[0, 0:3] = s
    m[1, 0:3] = u
    m[2, 0:3] = -f
    m[0, 3] = -np.dot(s, eye)
    m[1, 3] = -np.dot(u, eye)
    m[2, 3] = np.dot(f, eye)
    return m.T.copy()
