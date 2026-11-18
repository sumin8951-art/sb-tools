#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
motion_fx.py — 2D 숏폼 모션 프리셋 (FFmpeg + Pillow, GPU 0)

처세의 정석·수봉TV 같은 2D 라인아트 숏폼에 "카메라가 살아 있는 느낌"을 넣는 도구.
정지 PNG 한 장(또는 컷별 PNG 여러 장)에서 출발해 아래 3가지를 한 번에 굽는다.

  1) Super-sampled Ken Burns — zoom_in / zoom_out / pan_lr / pan_rl / pan_tb / pan_bt
     · 보드를 ss배(기본 4배)로 키우고, 매 프레임 **부동소수 크롭**으로 떠서 줄인다
     · 프레임마다 위치를 누적하지 않고 t로부터 다시 계산 → 누적 오차·떨림 없음
  2) Impact Shake — 펀치라인·돌발 순간에 프레임을 흔든다 (감쇠 진동 + 아주 작은 회전 + 펀치줌)
  3) Parts Overlay — 눈 깜빡임 / 식은땀 / 느낌표 PNG를 지정 시각·좌표에 얹는다
     · 좌표는 최종 영상 픽셀(1080x1920) 기준 — cheose-lipsync 와 같은 좌표 모델
     · space="camera" 로 두면 얼굴에 붙어 카메라 무빙을 따라간다

GPU·Node·유료 구독 없음. 필요한 것은 FFmpeg(x264) + ffprobe(선택) + Pillow 뿐.

────────────────────────────────────────────────────────────────────
빠른 시작
────────────────────────────────────────────────────────────────────
  # 1) 한 장에서 줌인 5초
  python3 motion_fx.py kenburns cut01.png out.mp4 --preset zoom_in --dur 5 --zoom 1.18

  # 2) 여러 컷 + 셰이크 + 파츠 (job.json)
  python3 motion_fx.py make job.json out.mp4

  # 3) 이미 렌더된 영상 위에 파츠만 얹기 (오디오 원본 유지)
  python3 motion_fx.py overlay base.mp4 parts.json out.mp4

  # 4) 떨림·포맷 자동 측정 / 자체 시험
  python3 motion_fx.py measure out.mp4
  python3 motion_fx.py selftest

────────────────────────────────────────────────────────────────────
job.json (make) — 모든 값 생략 가능
────────────────────────────────────────────────────────────────────
{
  "size": [1080, 1920],          // 출력 해상도
  "fps": 30,                     // 프레임레이트 (30 이상 권장)
  "ss": 4,                       // 슈퍼샘플 배율 (4 = 기본, 1 = 끔)
  "fit": "cover",                // cover(꽉 채움) | contain(여백)
  "bg": "#ffffff",               // contain 일 때 여백색
  "audio": "bgm.m4a",            // 선택 — 있으면 -shortest 로 붙임
  "shots": [
    {"image": "art/cut01.png", "preset": "zoom_in",  "dur": 2.2, "zoom": 1.18,
     "ease": "smooth", "anchor": [0.5, 0.42]},
    {"image": "art/cut02.png", "preset": "pan_lr",   "dur": 1.6, "zoom": 1.28},
    {"image": "art/cut03.png", "preset": "zoom_out", "dur": 1.2, "zoom": 1.15}
  ],
  "shakes": [
    {"at": 3.15, "amp": 18, "dur": 0.42, "freq": 11, "rot": 0.35, "punch": 0.03}
  ],
  "parts": [
    {"png": "parts/eyes_closed.png", "x": 500, "y": 690, "anchor": "center",
     "scale": 0.45, "space": "camera", "shot": 0,
     "blink": {"every": [2.4, 3.6], "hold": 0.10, "phase": 0.8}},
    {"png": "parts/sweat.png", "x": 640, "y": 560, "scale": 0.8,
     "t0": 2.3, "t1": 3.4, "pop": 0.18, "fade": 0.12, "drift": [0, -18]},
    {"png": "parts/excl.png", "x": 664, "y": 470, "scale": 1.0,
     "t0": 3.15, "t1": 4.2, "pop": 0.12, "fade": 0.10,
     "wobble": {"amp": 5, "freq": 3.2}}
  ]
}

parts 옵션 한눈에
  png      : PNG(알파) 경로 — 필수
  x, y     : 좌표 (space=screen 이면 최종 영상 픽셀, space=camera 이면 zoom1 프레임 픽셀)
             "coord":"norm" 이면 0~1 비율
  anchor   : topleft|top|topright|left|center|right|bottomleft|bottom|bottomright (기본 center)
  scale    : 원본 PNG 크기 대비 배율 (기본 1.0) · size:[w,h] 로 직접 지정 가능
  t0, t1   : 노출 구간(초). t1 생략 시 영상 끝까지
  space    : screen(기본) | camera(카메라 무빙 따라감, shot 으로 컷 지정)
  fade     : 앞뒤 페이드 길이(초)
  pop      : 등장 시 튀어나오는 시간(초) — 0이면 없음
  drift    : [dx, dy] 노출 구간 동안 이동(px)
  wobble   : {"amp": px, "freq": Hz} 미세 흔들림
  opacity  : 0~1
  blink    : {"every": [최소,최대]초, "hold": 표시시간, "phase": 시작지연, "seed": 난수시드}
             → 감은 눈 PNG를 주기적으로 아주 짧게 보여줄 때
"""
import argparse
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFilter

VERSION = "1.0"

SIZE_DEFAULT = (1080, 1920)
FPS_DEFAULT = 30
SS_DEFAULT = 4

PAN_PRESETS = {"pan_lr": (1, 0), "pan_rl": (-1, 0), "pan_tb": (0, 1), "pan_bt": (0, -1)}
ZOOM_PRESETS = {"zoom_in": "in", "zoomin": "in", "zoom_out": "out", "zoomout": "out"}
PRESETS = ["zoom_in", "zoom_out", "pan_lr", "pan_rl", "pan_tb", "pan_bt", "static"]

ANCHORS = {
    "topleft": (0.0, 0.0), "top": (0.5, 0.0), "topright": (1.0, 0.0),
    "left": (0.0, 0.5), "center": (0.5, 0.5), "right": (1.0, 0.5),
    "bottomleft": (0.0, 1.0), "bottom": (0.5, 1.0), "bottomright": (1.0, 1.0),
}

# ──────────────────────────────────────────────────────────── 기본 유틸
def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def ease(name, u):
    """u(0~1) → 카메라 진행도. smooth = ease-in-out(기본, 자연스러운 카메라)."""
    u = clamp(u, 0.0, 1.0)
    name = (name or "smooth").lower()
    if name in ("linear", "none"):
        return u
    if name in ("in", "ease_in"):
        return u * u
    if name in ("out", "ease_out"):
        return 1 - (1 - u) ** 2
    if name in ("smooth", "ease_in_out", "smoothstep"):
        return u * u * (3 - 2 * u)
    raise SystemExit(f"[ease] 알 수 없는 값: {name} (linear|in|out|smooth)")


def back_out(k, s=1.70158):
    """팝인용 오버슈트 이징: 0→1 을 살짝 넘겼다가 돌아온다."""
    k = clamp(k, 0.0, 1.0) - 1
    return k * k * ((s + 1) * k + s) + 1


def parse_size(v):
    if isinstance(v, (list, tuple)):
        return int(v[0]), int(v[1])
    m = re.fullmatch(r"(\d+)x(\d+)", str(v).strip())
    if not m:
        raise SystemExit(f"[size] '1080x1920' 형식이어야 합니다: {v}")
    return int(m.group(1)), int(m.group(2))


def parse_pair(v, default=None):
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return (float(v), float(v))
    if isinstance(v, (list, tuple)):
        return tuple(float(x) for x in v)
    parts = [p for p in re.split(r"[,\s]+", str(v).strip()) if p]
    vals = [float(p) for p in parts]
    if len(vals) == 1:
        return (vals[0], vals[0])
    return (vals[0], vals[1])


def hex_rgb(s):
    s = str(s).lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


# ──────────────────────────────────────────────────────────── 카메라(촌번즈)
class Shot:
    """한 컷 = 이미지 한 장 + 카메라 프리셋 + 길이."""

    def __init__(self, image, preset="zoom_in", dur=2.0, zoom=None, ease_name="smooth",
                 anchor=(0.5, 0.5), name=None, start=0.0):
        if preset not in PRESETS:
            raise SystemExit(f"[shot] 알 수 없는 preset: {preset} (가능: {', '.join(PRESETS)})")
        self.image = image
        self.preset = preset
        self.dur = float(dur)
        self.ease_name = ease_name
        self.anchor = tuple(anchor)
        self.name = name or os.path.basename(image)
        self.start = float(start)
        if zoom is None:
            zoom = 1.25 if preset in PAN_PRESETS else 1.12
        self.zoom = float(zoom)
        if self.zoom < 1.0:
            raise SystemExit("[shot] zoom 은 1.0 이상이어야 합니다 (1.0 = 원본 프레임 전체)")

    @property
    def end(self):
        return self.start + self.dur

    @classmethod
    def from_dict(cls, d, start=0.0):
        return cls(image=d["image"], preset=d.get("preset", "zoom_in"), dur=d.get("dur", 2.0),
                   zoom=d.get("zoom"), ease_name=d.get("ease", "smooth"),
                   anchor=parse_pair(d.get("anchor"), (0.5, 0.5)),
                   name=d.get("name"), start=start)


def shot_crop(shot, u, size):
    """진행도 u(0~1) 시점의 크롭 (cx, cy, cw, ch) — 출력 픽셀 기준."""
    W, H = size
    z = shot.zoom
    preset = shot.preset
    if preset in ZOOM_PRESETS:
        k = ease(shot.ease_name, u)
        z = (1 + (z - 1) * k) if ZOOM_PRESETS[preset] == "in" else (z - (z - 1) * k)
    elif preset == "static":
        z = 1.0
    cw, ch = W / z, H / z
    ax, ay = shot.anchor

    if preset in PAN_PRESETS:
        k = ease(shot.ease_name, u)
        dx_dir, dy_dir = PAN_PRESETS[preset]
        slack_x, slack_y = W - cw, H - ch
        cx = ax * W + (0.5 - ax) * cw
        cy = ay * H + (0.5 - ay) * ch
        if dx_dir:
            cx = cw / 2 + (k * slack_x if dx_dir > 0 else (1 - k) * slack_x)
        if dy_dir:
            cy = ch / 2 + (k * slack_y if dy_dir > 0 else (1 - k) * slack_y)
    else:
        # 줌: anchor 점이 화면의 같은 자리에 머무르도록 크롭 중심을 옮긴다
        cx = ax * W + (0.5 - ax) * cw
        cy = ay * H + (0.5 - ay) * ch

    cx = clamp(cx, cw / 2, W - cw / 2)
    cy = clamp(cy, ch / 2, H - ch / 2)
    return cx, cy, cw, ch


def shake_at(shakes, t):
    """t 시점의 흔들림 (dx, dy, rot, punch) — 초기화 없이 항상 t에서 직접 계산."""
    dx = dy = rot = 0.0
    punch = 1.0
    for s in shakes or []:
        at = float(s.get("at", 0.0))
        dur = float(s.get("dur", 0.45))
        if t < at or t > at + dur:
            continue
        lt = t - at
        decay = float(s.get("decay", max(0.05, dur / 3.0)))
        env = math.exp(-lt / decay)
        w = 2 * math.pi * float(s.get("freq", 11.0))
        amp = float(s.get("amp", 14.0))
        dx += amp * env * math.sin(w * lt)
        dy += amp * 0.6 * env * math.sin(w * lt * 1.17 + 1.9)
        rot += float(s.get("rot", 0.35)) * env * math.sin(w * lt * 0.83 + 0.7)
        punch = max(punch, 1.0 + float(s.get("punch", 0.02)) * env)
    return dx, dy, rot, punch


def camera_box(shot, u, size, ss, dx=0.0, dy=0.0, rot=0.0, punch=1.0):
    """흔들림·회전 여유까지 반영한 보드 좌표 크롭 박스 (x0, y0, w, h)."""
    W, H = size
    cx, cy, cw, ch = shot_crop(shot, u, size)
    if punch > 1.0:
        cw, ch = cw / punch, ch / punch
    need = max(2.0 * math.hypot(dx, dy), abs(math.radians(rot)) * max(W, H) * 0.8)
    if need > 0 and cw > 1 and ch > 1:
        k = 1.0 + need / min(cw, ch)
        cw, ch = cw / k, ch / k
    x0 = clamp(cx - cw / 2 + dx, 0.0, W - cw)
    y0 = clamp(cy - ch / 2 + dy, 0.0, H - ch)
    return x0 * ss, y0 * ss, cw * ss, ch * ss


def load_board(path, size, ss, fit="cover", bg="#ffffff", anchor=(0.5, 0.5)):
    """이미지를 (W*ss, H*ss) 보드로 준비한다. 화질은 LANCZOS 업스케일."""
    W, H = size
    bw, bh = int(W * ss), int(H * ss)
    src = Image.open(path)
    src = src.convert("RGB") if src.mode != "RGB" else src
    if fit == "contain":
        k = min(bw / src.width, bh / src.height)
        nw, nh = max(1, round(src.width * k)), max(1, round(src.height * k))
        board = Image.new("RGB", (bw, bh), hex_rgb(bg))
        board.paste(src.resize((nw, nh), Image.LANCZOS),
                    (round((bw - nw) * anchor[0]), round((bh - nh) * anchor[1])))
        return board
    k = max(bw / src.width, bh / src.height)
    nw, nh = max(bw, round(src.width * k)), max(bh, round(src.height * k))
    big = src.resize((nw, nh), Image.LANCZOS)
    left = round((nw - bw) * anchor[0])
    top = round((nh - bh) * anchor[1])
    return big.crop((left, top, left + bw, top + bh))


def sample(board, box, size, rot=0.0):
    """보드에서 크롭박스를 뽑아 출력 해상도로 샘플링(부동소수 좌표 → 서브픽셀 이동)."""
    W, H = size
    x0, y0, bw, bh = box
    sx, sy = bw / W, bh / H
    if abs(rot) < 1e-6:
        return board.transform((W, H), Image.AFFINE, (sx, 0, x0, 0, sy, y0),
                               resample=Image.BICUBIC)
    th = math.radians(rot)
    c, s = math.cos(th), math.sin(th)
    a, b = sx * c, -sy * s
    d, e = sx * s, sy * c
    cx, cy = x0 + bw / 2, y0 + bh / 2
    cc = cx - a * (W / 2) - b * (H / 2)
    ff = cy - d * (W / 2) - e * (H / 2)
    return board.transform((W, H), Image.AFFINE, (a, b, cc, d, e, ff), resample=Image.BICUBIC)


# ──────────────────────────────────────────────────────────── 파츠 오버레이
def _anchor_xy(name):
    if isinstance(name, (list, tuple)):
        return float(name[0]), float(name[1])
    return ANCHORS.get(str(name).lower(), ANCHORS["center"])


_img_cache = {}


def _scaled(path, w, h):
    """PNG 를 목표 크기로 캐시 변환(프레임마다 재리사이즈하지 않는다)."""
    key = (path, int(w), int(h))
    img = _img_cache.get(key)
    if img is None:
        base = Image.open(path).convert("RGBA")
        img = base.resize((max(1, int(w)), max(1, int(h))), Image.LANCZOS)
        if len(_img_cache) > 400:
            _img_cache.clear()
        _img_cache[key] = img
    return img


def _with_opacity(img, alpha):
    if alpha >= 0.999:
        return img
    out = img.copy()
    a = out.getchannel("A").point(lambda v: int(v * alpha))
    out.putalpha(a)
    return out


class Part:
    """오버레이 한 조각(눈 깜빡임·식은땀·느낌표·스티커)."""

    def __init__(self, d, total):
        if "png" not in d:
            raise SystemExit("[parts] 'png' 경로가 필요합니다")
        self.path = d["png"]
        if not os.path.exists(self.path):
            raise SystemExit(f"[parts] PNG 가 없습니다: {self.path}")
        self.x, self.y = float(d.get("x", 0)), float(d.get("y", 0))
        self.coord = d.get("coord", "px")
        self.anchor = _anchor_xy(d.get("anchor", "center"))
        self.scale = float(d.get("scale", 1.0))
        self.size = parse_size(d["size"]) if d.get("size") else None
        self.opacity = float(d.get("opacity", 1.0))
        self.fade = float(d.get("fade", 0.0))
        self.pop = float(d.get("pop", 0.0))
        self.t0 = float(d.get("t0", 0.0))
        self.t1 = float(d["t1"]) if d.get("t1") is not None else float(total)
        self.space = d.get("space", "screen")
        self.shot = d.get("shot")
        self.shot_index = None          # render_job 이 실제 컷 번호로 채운다
        self.drift = parse_pair(d.get("drift"), (0.0, 0.0))
        wob = d.get("wobble") or {}
        self.wob_amp = float(wob.get("amp", 0.0))
        self.wob_freq = float(wob.get("freq", 0.0))
        self.blinks = self._blink_windows(d)
        self._base_size = Image.open(self.path).size

    def _blink_windows(self, d):
        b = d.get("blink")
        if not b:
            return None
        every = b.get("every", [2.4, 3.6])
        lo, hi = parse_pair(every, (2.6, 3.6))
        if hi < lo:
            lo, hi = hi, lo
        hold = float(b.get("hold", 0.10))
        rnd = random.Random(int(b.get("seed", 7)))
        t = self.t0 + rnd.uniform(0.0, float(b.get("phase", 0.0)) or 0.0)
        wins = []
        while t < self.t1:
            wins.append((t, t + hold))
            t += rnd.uniform(lo, hi)
        return wins

    def _visible(self, t):
        if not (self.t0 <= t < self.t1):
            return False
        if self.blinks is not None:
            return any(a <= t < b for a, b in self.blinks)
        return True

    def _alpha(self, t):
        a = self.opacity
        if self.fade > 0:
            a *= clamp((t - self.t0) / self.fade, 0.0, 1.0)
            a *= clamp((self.t1 - t) / self.fade, 0.0, 1.0)
        return clamp(a, 0.0, 1.0)

    def evaluate(self, t, ctx):
        """(img, (x, y)) 또는 None. ctx 는 현재 프레임의 카메라 정보."""
        if not self._visible(t):
            return None
        W, H = ctx["size"]
        x, y = self.x, self.y
        if self.coord == "norm":
            x, y = x * W, y * H

        if self.shot_index is not None and ctx.get("shot_index") != self.shot_index:
            return None                          # 컷을 지정한 파츠는 그 컷에서만 보인다

        mult = 1.0
        if self.space == "camera":
            box = ctx["box"]
            sx = box[2] / W                      # 보드 px / 출력 px
            sy = box[3] / H
            if sx <= 0 or sy <= 0:
                return None
            z = ctx["ss"] / sx                   # 현재 확대 배율
            x = (x * ctx["ss"] - box[0]) / sx
            y = (y * ctx["ss"] - box[1]) / sy
            mult = z                             # 줌인하면 파츠도 같이 커진다

        w, h = self.size if self.size else (self._base_size[0] * self.scale,
                                            self._base_size[1] * self.scale)
        w, h = w * mult, h * mult

        lt = t - self.t0
        if self.pop > 0 and lt < self.pop:
            k = back_out(lt / self.pop)
            w, h = w * (0.55 + 0.45 * k), h * (0.55 + 0.45 * k)
        if self.drift != (0.0, 0.0):
            life = max(1e-6, self.t1 - self.t0)
            f = clamp(lt / life, 0.0, 1.0)
            x += self.drift[0] * f
            y += self.drift[1] * f
        if self.wob_amp:
            x += self.wob_amp * math.sin(2 * math.pi * self.wob_freq * lt)
            y += self.wob_amp * 0.6 * math.sin(2 * math.pi * self.wob_freq * lt * 1.3 + 1.1)

        px = round(x - w * self.anchor[0])
        py = round(y - h * self.anchor[1])
        img = _with_opacity(_scaled(self.path, round(w), round(h)), self._alpha(t))
        return img, (px, py)


def composite_parts(frame, parts, t, ctx):
    active = []
    for p in parts:
        r = p.evaluate(t, ctx)
        if r:
            active.append(r)
    if not active:
        return frame
    layer = frame.convert("RGBA")
    for img, pos in active:
        layer.alpha_composite(img, pos)
    return layer.convert("RGB")


# ──────────────────────────────────────────────────────────── 렌더러
class Writer:
    """프레임 → (ffmpeg rawvideo 파이프) 또는 PNG 폴더."""

    def __init__(self, out, size, fps, ffmpeg="ffmpeg", crf=18, audio=None,
                 frames_dir=None, total=None):
        self.out = out
        self.size = size
        self.fps = fps
        self.ffmpeg = ffmpeg
        self.crf = crf
        self.audio = audio
        self.frames_dir = frames_dir
        self.total = total
        self.n = 0
        self.proc = None
        if frames_dir:
            os.makedirs(frames_dir, exist_ok=True)
        else:
            W, H = size
            cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                   "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                   "-r", str(fps), "-i", "-"]
            if audio:
                cmd += ["-i", audio]
            cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
            if audio:
                cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
            cmd += [out]
            self.cmd = cmd
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    def write(self, img):
        if self.frames_dir:
            img.save(os.path.join(self.frames_dir, f"f_{self.n:05d}.png"))
        else:
            self.proc.stdin.write(img.tobytes())
        self.n += 1

    def close(self):
        if self.proc:
            self.proc.stdin.close()
            rc = self.proc.wait()
            if rc != 0:
                raise SystemExit(f"[ffmpeg] 인코딩 실패 (exit {rc}) — 명령: {' '.join(self.cmd)}")
        elif self.frames_dir and self.out:
            W, H = self.size
            cmd = [self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                   "-framerate", str(self.fps), "-i", os.path.join(self.frames_dir, "f_%05d.png")]
            if self.audio:
                cmd += ["-i", self.audio]
            cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(self.crf),
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
            if self.audio:
                cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
            cmd += [self.out]
            subprocess.run(cmd, check=True)
        return self.n


def shot_index_at(shots, t):
    for i, s in enumerate(shots):
        if t < s.end or i == len(shots) - 1:
            return i
    return len(shots) - 1


def render_job(job, out=None, ffmpeg="ffmpeg", crf=18, frames_dir=None, audio=None,
               trace_path=None, log=print):
    size = parse_size(job.get("size", SIZE_DEFAULT))
    fps = float(job.get("fps", FPS_DEFAULT))
    ss = float(job.get("ss", SS_DEFAULT))
    fit = job.get("fit", "cover")
    bg = job.get("bg", "#ffffff")

    raw_shots = job.get("shots")
    if not raw_shots:
        if "image" not in job:
            raise SystemExit("[job] 'shots' 또는 'image' 가 필요합니다")
        raw_shots = [dict(job)]
    shots, t0 = [], 0.0
    for d in raw_shots:
        s = Shot.from_dict(d, start=t0)
        shots.append(s)
        t0 = s.end
    total = shots[-1].end
    audio = audio or job.get("audio")

    log(f"[job] {len(shots)}컷 · {total:.2f}s · {size[0]}x{size[1]} · {fps:g}fps · ss={ss:g}")
    boards = []
    for s in shots:
        boards.append(load_board(s.image, size, ss, fit=fit, bg=bg))
        log(f"  · {s.name:<28} {s.preset:<9} {s.dur:.2f}s  zoom={s.zoom:g}")

    parts = [Part(d, total) for d in job.get("parts", [])]
    names = [s.name for s in shots]
    for p in parts:
        if isinstance(p.shot, int):
            p.shot_index = p.shot if 0 <= p.shot < len(shots) else None
        elif isinstance(p.shot, str):
            p.shot_index = names.index(p.shot) if p.shot in names else None
        elif p.space == "camera":
            p.shot_index = shot_index_at(shots, p.t0)   # 카메라 부착은 t0 의 컷에 붙인다
    shakes = job.get("shakes", [])

    if out:
        writer = Writer(out, size, fps, ffmpeg=ffmpeg, crf=crf, audio=audio,
                        frames_dir=frames_dir, total=total)
    else:
        writer = None
    n = int(round(total * fps))
    trace = []
    for i in range(n):
        t = i / fps
        si = shot_index_at(shots, t)
        shot = shots[si]
        u = (t - shot.start) / shot.dur if shot.dur > 0 else 0.0
        dx, dy, rot, punch = shake_at(shakes, t)
        box = camera_box(shot, u, size, ss, dx, dy, rot, punch)
        frame = sample(boards[si], box, size, rot)
        if parts:
            ctx = {"size": size, "box": box, "ss": ss, "shot_index": si,
                   "shot_name": shot.name, "t": t}
            frame = composite_parts(frame, parts, t, ctx)
        if writer:
            writer.write(frame)
        if trace_path:
            trace.append({"t": round(t, 4), "shot": si, "shot_name": shot.name,
                          "x0": round(box[0], 3), "y0": round(box[1], 3),
                          "w": round(box[2], 3), "h": round(box[3], 3),
                          "shake": [round(dx, 3), round(dy, 3), round(rot, 3)]})
        if i % max(1, int(fps * 2)) == 0 and out:
            log(f"  [render] {i + 1}/{n} frames")
    written = writer.close() if writer else n
    if trace_path and trace:
        with open(trace_path, "w", encoding="utf-8") as f:
            json.dump({"size": size, "fps": fps, "ss": ss, "frames": trace}, f)
    log(f"[done] {written} frames" + (f" → {out}" if out else ""))
    return {"frames": written, "duration": total, "shots": len(shots)}


# ──────────────────────────────────────────────────────────── 측정·검수
def probe_media(path, ffprobe=None, ffmpeg="ffmpeg"):
    """ffprobe 있으면 그걸로, 없으면 ffmpeg -i 헤더 파싱."""
    exe = ffprobe or shutil.which("ffprobe")
    if exe:
        r = subprocess.run([exe, "-v", "error", "-select_streams", "v:0",
                            "-show_entries",
                            "stream=width,height,r_frame_rate,codec_name:format=duration",
                            "-of", "json", path], capture_output=True, text=True)
        try:
            d = json.loads(r.stdout)
            st = d["streams"][0]
            num, den = (st["r_frame_rate"].split("/") + ["1"])[:2]
            return {"width": st["width"], "height": st["height"],
                    "fps": round(float(num) / float(den or 1), 3),
                    "codec": st.get("codec_name"),
                    "duration": round(float(d.get("format", {}).get("duration", 0) or 0), 3)}
        except Exception:
            pass
    err = subprocess.run([ffmpeg, "-hide_banner", "-i", path],
                         capture_output=True, text=True).stderr
    wh = re.search(r"\b(\d{2,5})x(\d{2,5})\b(?!.*kbits)", err)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    fps = re.search(r"([\d.]+) fps", err)
    codec = re.search(r"Video:\s*([A-Za-z0-9_\-]+)", err)
    return {"width": int(wh.group(1)) if wh else 0, "height": int(wh.group(2)) if wh else 0,
            "fps": float(fps.group(1)) if fps else 0.0,
            "codec": codec.group(1) if codec else None,
            "duration": (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))) if m else 0.0}


def _gray_profile(img, axis):
    """가로(axis=0 → 컬럼 평균) / 세로 프로파일. 이동량 추정용."""
    g = img.convert("L")
    if axis == 0:
        g = g.resize((g.width, 1), Image.BOX)
    else:
        g = g.resize((1, g.height), Image.BOX)
    return list(g.tobytes())


def _corr_at(a, b, lag, band, step):
    """a 의 가운데 밴드와 b 를 lag 만큼 이동한 값의 정규화 상관(NCC).

    · 비교 구간을 고정해야 lag 마다 표본 수가 달라지며 생기는 이동량 과대추정이 없다.
    · 두 신호를 각각의 평균으로 중심화·정규화해야 DC 성분이 만드는 편향이 없다.
    · 소수 lag 은 b 를 선형보간해 센다.
    """
    lo, hi = band
    av, bv = [], []
    n_b = len(b)
    for i in range(lo, hi, step):
        x = i + lag
        i0 = int(math.floor(x))
        f = x - i0
        j = i0 + 1 if i0 + 1 < n_b else i0
        av.append(a[i])
        bv.append(b[i0] * (1 - f) + b[j] * f)
    m = len(av)
    if m < 8:
        return -1e18
    am = sum(av) / m
    bm = sum(bv) / m
    sab = saa = sbb = 0.0
    for u, v in zip(av, bv):
        du, dv = u - am, v - bm
        sab += du * dv
        saa += du * du
        sbb += dv * dv
    if saa <= 1e-12 or sbb <= 1e-12:
        return -1e18
    return sab / (saa * sbb) ** 0.5


def _best_shift(a, b, radius=8):
    """a→b 이동량(서브픽셀). 정수 지연으로 대략 잡고 소수 지연으로 정밀화한다.

    정수 지연만 쓰고 포물선 보정만 하면, 1px 안쪽 위치에 따라 보정값이 주기적으로
    흔들려 떨림 측정이 0.2px 를 넘게 나온다(측정기 자체 오차). 그래서 상관함수를
    직접 소수 지연에서 계산한다.
    """
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    if n < 4 * radius:
        radius = max(1, n // 8)
    ma = sum(a) / n
    mb = sum(b) / n
    step = 1                      # 서브샘플하면 추정치가 계단처럼 흔들린다(실측)
    band = (radius + 2, n - radius - 2)
    coarse = [(lag, _corr_at(a, b, float(lag), band, step))
              for lag in range(-radius, radius + 1)]
    best_lag, best = max(coarse, key=lambda p: p[1])
    lo, hi = best_lag - 1.0, best_lag + 1.0
    fine = [(lo, _corr_at(a, b, lo, band, step))]
    k = lo + 0.05
    while k < hi - 1e-9:
        fine.append((k, _corr_at(a, b, k, band, step)))
        k += 0.05
    fine.append((hi, _corr_at(a, b, hi, band, step)))
    return max(fine, key=lambda p: p[1])[0]


def _frames_from(path, size=None, fps=None, ffmpeg="ffmpeg", limit=None):
    """mp4 → PIL 프레임 제너레이터 (ffmpeg rawvideo 파이프)."""
    info = probe_media(path, ffmpeg=ffmpeg)
    W = size[0] if size else info["width"]
    H = size[1] if size else info["height"]
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", path,
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    fsize = W * H * 3
    count = 0
    try:
        while True:
            buf = proc.stdout.read(fsize)
            if len(buf) < fsize:
                break
            yield Image.frombytes("RGB", (W, H), buf)
            count += 1
            if limit and count >= limit:
                break
    finally:
        proc.stdout.close()
        proc.kill()


def _motion_stats(steps, cut_set=None, cut_thresh=5.0):
    """
    프레임별 이동량 배열 → 떨림 추정.
    떨림 = 각 프레임 이동량이 이웃 7프레임 중간값에서 얼마나 튀는가의 RMS(px).
      · 일정 속도 팬 → 0
      · 가속하는 이징 줌 → 이웃과 비슷하게 변하므로 0에 가깝다(정상)
      · 정수 크롭·보간 오차로 툭툭 튀는 프레임 → 크게 나온다
    컷·셰이크처럼 의도된 큰 이동(|step| > cut_thresh, 기본 5px/프레임)은 연출로 보고 제외한다.
    (부드러운 팬은 30fps 에서 보통 1~4px/프레임이다. 5px 를 넘는 이동은 셰이크·컷이거나
     너무 빠른 이동이라 이 지표로 판정할 대상이 아니다.)
    """
    n = len(steps)
    if n < 8:
        return {"frames": n + 1, "mean_step": round(sum(steps) / n, 3) if n else 0.0,
                "max_step": round(max((abs(s) for s in steps), default=0.0), 3),
                "jitter": 0.0, "cut_frames": 0}
    cuts = {i for i, s in enumerate(steps) if abs(s) > cut_thresh}
    cuts |= set(cut_set or ())
    resid = []
    for i in range(n):
        if i in cuts or (i - 1) in cuts or (i + 1) in cuts:
            continue
        win = [steps[j] for j in range(max(0, i - 3), min(n, i + 4))
               if j not in cuts and abs(j - i) <= 3]
        if len(win) < 3:
            continue
        win.sort()
        med = win[len(win) // 2]
        resid.append(steps[i] - med)
    jit = (sum(r * r for r in resid) / len(resid)) ** 0.5 if resid else 0.0
    return {"frames": n + 1,
            "mean_step": round(sum(steps) / n, 3),
            "max_step": round(max(abs(s) for s in steps), 3),
            "jitter": round(jit, 3), "cut_frames": len(cuts)}


def measure(path, ffmpeg="ffmpeg", max_frames=400, quiet=False, window=None):
    """포맷 + 프레임 간 이동/떨림 측정. 떨림 판정 기준: 0.2px 미만.

    window=(t0, t1) 을 주면 그 구간만 본다(예: 셰이크가 없는 구간만 검사).
    """
    info = probe_media(path, ffmpeg=ffmpeg)
    fps = info["fps"] or 30.0
    prof_x, prof_y, thumbs = [], [], []
    for img in _frames_from(path, (info["width"], info["height"]), ffmpeg=ffmpeg, limit=max_frames):
        prof_x.append(_gray_profile(img, 0))
        prof_y.append(_gray_profile(img, 1))
        thumbs.append(img.convert("L").resize((64, 48), Image.BOX).tobytes())
    steps_x = [_best_shift(prof_x[i], prof_x[i + 1]) for i in range(len(prof_x) - 1)]
    steps_y = [_best_shift(prof_y[i], prof_y[i + 1]) for i in range(len(prof_y) - 1)]
    # 컷·세이크로 화면이 크게 바뀐 프레임은 '이동'이 아니라 연출이므로 떨림 계산에서 뺀다
    cut_set = set()
    for i in range(len(thumbs) - 1):
        a, b = thumbs[i], thumbs[i + 1]
        diff = sum(abs(x - y) for x, y in zip(a, b)) / len(a)
        if diff > 8:
            cut_set.add(i)
    note = ""
    if window:
        a, b = window
        i0 = max(0, int(round(a * fps)))
        i1 = min(len(steps_x), int(round(b * fps)))
        steps_x, steps_y = steps_x[i0:i1], steps_y[i0:i1]
        cut_set = {i - i0 for i in cut_set if i0 <= i < i1}
        note = f" (구간 {a:g}~{b:g}s)"

    out = {"path": path, "info": info, "x": _motion_stats(steps_x, cut_set),
           "y": _motion_stats(steps_y, cut_set), "window": note.strip() or None,
           "steps_x": [round(s, 3) for s in steps_x],
           "steps_y": [round(s, 3) for s in steps_y]}
    out["jitter"] = round(max(out["x"]["jitter"], out["y"]["jitter"]), 3)
    out["jitter_ok"] = out["jitter"] < 0.2
    if not quiet:
        print(f"\n■ {path}{note}")
        print(f"  {info['width']}x{info['height']} · {info['fps']:g}fps · "
              f"{info['duration']:g}s · {info['codec']}")
        print(f"  이동 x: 평균 {out['x']['mean_step']:+.3f}px/프레임 · 최대 {out['x']['max_step']:.3f}px")
        print(f"  이동 y: 평균 {out['y']['mean_step']:+.3f}px/프레임 · 최대 {out['y']['max_step']:.3f}px")
        print(f"  떨림(이웃 중간값 대비 편차): {out['jitter']:.3f}px "
              f"→ {'PASS' if out['jitter_ok'] else 'FAIL'} (기준 0.2px 미만, "
              f"컷/셰이크 제외 {out['x']['cut_frames'] + out['y']['cut_frames']}프레임)")
        if not out["jitter_ok"] and not window:
            print("  ※ 셰이크·파츠 등장·컷처럼 화면 내용이 바뀌는 구간은 '이동'이 아니라 연출이라")
            print("     이 지표가 흔들립니다. 판정은 연출이 없는 구간만 골라서:")
            print("     measure in.mp4 --window 2.0 3.3")
    return out


# ──────────────────────────────────────────────────────────── 데모 파츠 PNG
def make_demo_parts(outdir):
    """눈 감김·식은땀·느낌표 PN은 를 코드로 그려 준다(바이너리 자산 없이 바로 시험용).

    라인아트에 얹을 것이므로 **흰 채움의 가장자리를 3px 정도 부드럽게(feather)** 해야
    기존 선·머리를 칼로 자른 듯한 흰 사각형 자국이 남지 않는다.
    """
    os.makedirs(outdir, exist_ok=True)
    paths = {}

    # 눈 감은 모양 두 개 — 흰 채움으로 기존 눈을 덮고 그 위에 눈썹처럼 꺾인 호를 그린다
    w, h = 420, 130
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    for cx in (100, 320):
        md.ellipse([cx - 80, 18, cx + 80, 96], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(4))
    img.paste(Image.new("RGBA", (w, h), (255, 255, 255, 255)), (0, 0), mask)
    d = ImageDraw.Draw(img)
    for cx in (100, 320):
        d.arc([cx - 74, 22, cx + 74, 104], start=20, end=160, fill=(18, 18, 18, 255), width=7)
    p = os.path.join(outdir, "eyes_closed.png")
    img.save(p)
    paths["eyes_closed"] = p

    # 식은땀 방울 (옅은 물색 + 검은 외곽선)
    img = Image.new("RGBA", (160, 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon([(80, 6), (128, 96), (120, 152), (80, 186), (40, 152), (32, 96)],
              fill=(206, 232, 255, 255), outline=(25, 25, 25, 255))
    d.line([(80, 6), (128, 96), (120, 152), (80, 186), (40, 152), (32, 96), (80, 6)],
           fill=(25, 25, 25, 255), width=6)
    d.ellipse([54, 104, 76, 126], fill=(255, 255, 255, 255))
    p = os.path.join(outdir, "sweat.png")
    img.save(p)
    paths["sweat"] = p

    # 느낌표
    img = Image.new("RGBA", (120, 300), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([34, 8, 86, 196], radius=22, fill=(226, 30, 54, 255),
                        outline=(20, 20, 20, 255), width=7)
    d.ellipse([34, 226, 86, 278], fill=(226, 30, 54, 255), outline=(20, 20, 20, 255), width=7)
    p = os.path.join(outdir, "excl.png")
    img.save(p)
    paths["excl"] = p
    return paths


# ──────────────────────────────────────────────────────────── 자체 시험
def _demo_art(path, size=(1080, 1920)):
    """검증용 라인아트 한 장: 눈금 막대(이동 추적) + 대각선 + 얼굴 느낌의 도형.
    주기적인 격자는 이동량 추정을 흐리기 때문에 일부러 불규칙하게 배치한다."""
    W, H = size
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    # 이동 추적용 막대 — 위치·굵기를 서로 다르게(주기 없음)
    d.rectangle([120, 200, 132, 1720], fill=(10, 10, 10))
    d.rectangle([420, 150, 438, 1780], fill=(10, 10, 10))
    d.rectangle([900, 260, 907, 1500], fill=(10, 10, 10))
    d.rectangle([60, 300, 1000, 306], fill=(10, 10, 10))
    d.rectangle([40, 1420, 940, 1446], fill=(10, 10, 10))
    # 대각선(에일리어싱 관찰용)
    for i in range(9):
        d.line([(60 + i * 40, 1660), (300 + i * 90, 1300)], fill=(60, 60, 60), width=3)
    # 얼굴
    d.ellipse([300, 420, 780, 980], outline=(20, 20, 20), width=6)
    d.ellipse([400, 600, 500, 660], fill=(20, 20, 20))
    d.ellipse([580, 600, 680, 660], fill=(20, 20, 20))
    d.arc([430, 740, 650, 860], start=15, end=165, fill=(20, 20, 20), width=6)
    img.save(path)
    return path


def selftest(workdir=None, ffmpeg="ffmpeg"):
    tmp = workdir or tempfile.mkdtemp(prefix="motion_fx_selftest_")
    os.makedirs(tmp, exist_ok=True)
    art = os.path.join(tmp, "art.png")
    _demo_art(art)
    parts_dir = os.path.join(tmp, "parts")
    pp = make_demo_parts(parts_dir)

    job = {
        "size": [1080, 1920], "fps": 30, "ss": 4,
        "shots": [
            {"image": art, "preset": "zoom_in", "dur": 2.0, "zoom": 1.18, "name": "A_줌인"},
            {"image": art, "preset": "pan_lr", "dur": 1.5, "zoom": 1.18, "ease": "linear",
             "name": "B_팬"},
            {"image": art, "preset": "zoom_out", "dur": 1.5, "zoom": 1.15, "name": "C_줌아웃"},
        ],
        "shakes": [{"at": 3.7, "amp": 18, "dur": 0.42, "freq": 11, "rot": 0.35}],
        "parts": [
            {"png": pp["eyes_closed"], "x": 540, "y": 630, "scale": 0.9,
             "t0": 0.0, "blink": {"every": [1.2, 1.6], "hold": 0.10, "phase": 0.6, "seed": 3}},
            {"png": pp["sweat"], "x": 760, "y": 480, "scale": 0.9,
             "t0": 2.2, "t1": 3.6, "pop": 0.16, "fade": 0.12, "drift": [0, -20]},
            {"png": pp["excl"], "x": 780, "y": 380, "scale": 0.9,
             "t0": 3.1, "t1": 4.4, "pop": 0.12, "fade": 0.10,
             "wobble": {"amp": 5, "freq": 3.2}},
        ],
    }
    job_path = os.path.join(tmp, "job.json")
    with open(job_path, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=1)
    clip = os.path.join(tmp, "selftest.mp4")
    frames_dir = os.path.join(tmp, "frames")
    print(f"[selftest] 작업 폴더: {tmp}")
    res = render_job(job, clip, ffmpeg=ffmpeg, crf=18, frames_dir=frames_dir)

    ss1_job = json.loads(json.dumps(job))
    ss1_job["ss"] = 1
    ss1_job["parts"] = []
    ss1_job["shakes"] = []
    clip1 = os.path.join(tmp, "selftest_ss1.mp4")
    render_job(ss1_job, clip1, ffmpeg=ffmpeg, crf=18)

    # 떨림은 "순수 이동" 구간(팬, 등속)에서 잰다 — 확대 중에는 특징점마다 이동량이 달라
    # 전역 이동량 추정 자체가 흔들리므로 측정 지표로 부적합하다.
    m4 = measure(clip, ffmpeg=ffmpeg, window=(2.05, 3.45))
    m1 = measure(clip1, ffmpeg=ffmpeg, window=(2.05, 3.45))
    fall_shake = measure(clip, ffmpeg=ffmpeg, window=(3.65, 4.25), quiet=True)

    # 파츠 검증: 깜빡임 프레임 vs 직전 프레임의 픽셀 차이(박스 안에서만 변해야 한다)
    eyes = Part(job["parts"][0], 5.0)
    w0 = eyes.blinks[0][0]
    f_close = int(round((w0 + 0.02) * 30))
    f_open = f_close + 8
    fa = Image.open(os.path.join(frames_dir, f"f_{f_close:05d}.png")).convert("RGB")
    fb = Image.open(os.path.join(frames_dir, f"f_{f_open:05d}.png")).convert("RGB")
    # 합성 아트의 눈(검은 타원)은 감은눈 PNG의 흰 채움으로 덮인다
    #   → 깜빡임 프레임은 흰색, 뜬 프레임은 검은색이어야 파츠가 제 좌표에 그려진 것
    probe = (420, 600, 470, 630)
    blink_lum = sum(fa.crop(probe).convert("L").getdata()) / (probe[2] - probe[0]) / (probe[3] - probe[1])
    open_lum = sum(fb.crop(probe).convert("L").getdata()) / (probe[2] - probe[0]) / (probe[3] - probe[1])
    parts_ok = blink_lum > 200 and open_lum < 120

    checks = []
    info = m4["info"]
    checks.append(("H.264 인코딩", info["codec"] == "h264", str(info["codec"])))
    checks.append(("30fps", abs(info["fps"] - 30) < 0.05, f"{info['fps']:g}fps"))
    checks.append(("1080x1920", (info["width"], info["height"]) == (1080, 1920),
                   f"{info['width']}x{info['height']}"))
    checks.append(("5초 길이", abs(info["duration"] - 5.0) < 0.12, f"{info['duration']:g}s"))
    checks.append(("프레임 150장 렌더", res["frames"] == 150, f"{res['frames']}장"))
    shake_steps = [abs(s) for s in fall_shake["steps_x"]] + [abs(s) for s in fall_shake["steps_y"]]
    checks.append(("셰이크 동작(프레임 점프)", max(shake_steps) > 8 and shake_steps[-4:] and
                   sum(shake_steps[-4:]) / 4 < 4,
                   f"최대 {max(shake_steps):.1f}px → 감쇠 후 평균 "
                   f"{sum(shake_steps[-4:]) / 4:.1f}px"))
    checks.append(("떨림 < 0.2px (ss=4)", m4["jitter"] < 0.2, f"{m4['jitter']:.3f}px"))
    checks.append(("파츠가 지정 좌표에 그려짐", parts_ok,
                   f"깜빡임 프레임 휘도 {blink_lum:.0f} / 뜬 프레임 {open_lum:.0f}"))
    print("\n■ selftest 결과")
    for name, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:<22} {detail}")
    print(f"  (참고) ss=1 떨림 {m1['jitter']:.3f}px · ss=4 떨림 {m4['jitter']:.3f}px")
    ng = sum(1 for _, ok, _ in checks if not ok)
    print(f"  → {'전항목 통과' if ng == 0 else str(ng) + '항목 실패'}  (폴더: {tmp})")
    return 0 if ng == 0 else 1


# ──────────────────────────────────────────────────────────── CLI
def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="motion_fx.py",
        description="2D 숏폼 모션 프리셋 — 슈퍼샘플 켄번즈 / 임팩트 셰이크 / 파츠 오버레이")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--ffmpeg", default="ffmpeg", help="ffmpeg 경로(기본 ffmpeg)")
        p.add_argument("--ffprobe", default=None, help="ffprobe 경로(기본 자동)")
        p.add_argument("--crf", type=float, default=18, help="x264 CRF (기본 18)")

    p = sub.add_parser("kenburns", help="이미지 한 장 → 카메라 무빙 클립")
    p.add_argument("image")
    p.add_argument("out")
    p.add_argument("--preset", default="zoom_in", choices=PRESETS)
    p.add_argument("--dur", type=float, default=5.0)
    p.add_argument("--fps", type=float, default=FPS_DEFAULT)
    p.add_argument("--size", default="1080x1920")
    p.add_argument("--zoom", type=float, default=None)
    p.add_argument("--ease", default="smooth")
    p.add_argument("--anchor", default="0.5,0.5")
    p.add_argument("--ss", type=float, default=SS_DEFAULT)
    p.add_argument("--fit", default="cover", choices=["cover", "contain"])
    p.add_argument("--audio", default=None)
    p.add_argument("--frames-dir", default=None)
    p.add_argument("--trace", default=None)
    common(p)

    p = sub.add_parser("make", help="job.json(여러 컷 + 셰이크 + 파츠) → 클립")
    p.add_argument("job")
    p.add_argument("out")
    p.add_argument("--audio", default=None)
    p.add_argument("--frames-dir", default=None)
    p.add_argument("--trace", default=None)
    common(p)

    p = sub.add_parser("overlay", help="이미 렌더된 영상 위에 파츠만 얹기(오디오 유지)")
    p.add_argument("src")
    p.add_argument("parts")
    p.add_argument("out")
    p.add_argument("--size", default=None)
    p.add_argument("--fps", type=float, default=None)
    p.add_argument("--ss", type=float, default=SS_DEFAULT)
    common(p)

    p = sub.add_parser("measure", help="포맷 + 프레임 이동/떨림 측정")
    p.add_argument("path")
    p.add_argument("--json", action="store_true")
    common(p)

    p = sub.add_parser("selftest", help="합성 소재로 전 기능 자체 시험")
    p.add_argument("--workdir", default=None)
    common(p)

    p = sub.add_parser("demo-parts", help="눈감김·식은땀·느낌표 데모 PNG 생성")
    p.add_argument("outdir")
    common(p)

    a = ap.parse_args(argv)

    if a.cmd == "kenburns":
        job = {"size": a.size, "fps": a.fps, "ss": a.ss, "fit": a.fit,
               "shots": [{"image": a.image, "preset": a.preset, "dur": a.dur,
                          "zoom": a.zoom, "ease": a.ease, "anchor": a.anchor}]}
        render_job(job, a.out, ffmpeg=a.ffmpeg, crf=a.crf, frames_dir=a.frames_dir,
                   audio=a.audio, trace_path=a.trace)
    elif a.cmd == "make":
        with open(a.job, encoding="utf-8") as f:
            job = json.load(f)
        render_job(job, a.out, ffmpeg=a.ffmpeg, crf=a.crf, frames_dir=a.frames_dir,
                   audio=a.audio, trace_path=a.trace)
    elif a.cmd == "overlay":
        overlay_video(a.src, a.parts, a.out, ffmpeg=a.ffmpeg, ffprobe=a.ffprobe,
                      crf=a.crf, size=a.size, fps=a.fps)
    elif a.cmd == "measure":
        res = measure(a.path, ffmpeg=a.ffmpeg, quiet=a.json)
        if a.json:
            print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["jitter_ok"] else 1
    elif a.cmd == "selftest":
        return selftest(a.workdir, ffmpeg=a.ffmpeg)
    elif a.cmd == "demo-parts":
        for k, v in make_demo_parts(a.outdir).items():
            print(f"[parts] {k}: {v}")
    return 0


def overlay_video(src, parts_json, out, ffmpeg="ffmpeg", ffprobe=None, crf=18,
                  size=None, fps=None):
    """기존 영상에 파츠만 얹는다. 영상 스트림은 재인코딩, 오디오는 그대로 복사."""
    info = probe_media(src, ffprobe=ffprobe, ffmpeg=ffmpeg)
    W, H = parse_size(size) if size else (info["width"], info["height"])
    fr = fps or info["fps"]
    with open(parts_json, encoding="utf-8") as f:
        spec = json.load(f)
    specs = spec.get("parts", spec) if isinstance(spec, dict) else spec
    total = float(spec.get("duration", info["duration"])) if isinstance(spec, dict) else info["duration"]
    parts = [Part(d, total) for d in specs]

    cmd_in = [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", src,
              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    dec = subprocess.Popen(cmd_in, stdout=subprocess.PIPE)
    cmd_out = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fr),
               "-i", "-", "-i", src,
               "-map", "0:v", "-map", "1:a?", "-c:v", "libx264", "-preset", "medium",
               "-crf", str(crf), "-pix_fmt", "yuv420p", "-c:a", "copy",
               "-movflags", "+faststart", "-shortest", out]
    enc = subprocess.Popen(cmd_out, stdin=subprocess.PIPE)
    fsize = W * H * 3
    i = 0
    try:
        while True:
            buf = dec.stdout.read(fsize)
            if len(buf) < fsize:
                break
            img = Image.frombytes("RGB", (W, H), buf)
            t = i / fr
            ctx = {"size": (W, H), "box": (0, 0, W, H), "ss": 1, "shot_index": 0,
                   "shot_of": {}, "t": t}
            img = composite_parts(img, parts, t, ctx)
            enc.stdin.write(img.tobytes())
            i += 1
    finally:
        dec.stdout.close()
        dec.kill()
        enc.stdin.close()
        rc = enc.wait()
    print(f"[overlay] {i} frames → {out}" + ("" if rc == 0 else f" (ffmpeg exit {rc})"))


if __name__ == "__main__":
    sys.exit(main() or 0)
