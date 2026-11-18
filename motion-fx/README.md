# motion-fx — 2D 숏폼 모션 프리셋 (슈퍼샘플 켄번즈 · 임팩트 셰이크 · 파츠 오버레이)

> 저장소: https://github.com/sumin8951-art/sb-tools · 담당: 팅사원(처세 렌더링) · 에대리(수봉TV 렌더링) · 뮤팀장(1차 검수)
> FFmpeg + Pillow 만 있으면 됩니다. **GPU 0, Node 0, 유료 구독 0.**

## 무엇을 하는가

정지 PNG(또는 컷별 PNG 여러 장)에서 출발해, 숏폼에서 흔히 말하는 "카메라가 살아 있는 느낌"을 한 번에 굽습니다.

| 기능 | 명령 | 하는 일 |
|---|---|---|
| **Super-sampled Ken Burns** | `kenburns` / `make` | `zoom_in` `zoom_out` `pan_lr` `pan_rl` `pan_tb` `pan_bt` `static` — 4배 보드에서 **부동소수 크롭**으로 매 프레임을 다시 계산(누적 오차·정수 크롭 계단 없음) |
| **Impact Shake** | `make` 의 `shakes` | 펀치라인·돌발 순간에 0.3~0.5초 감쇠 진동 + 미세 회전 + 펀치줌 |
| **Parts Overlay** | `make` / `overlay` | 눈 깜빡임·식은땀·느낌표·스티커 PNG를 **지정 시각·좌표**에 얹기 (`space:"camera"` 면 카메라 무빙을 따라감) |
| **자동 검수** | `measure` | 코덱·fps·해상도 확인 + 프레임 간 이동/떨림(px) 측정 |
| **자체 시험** | `selftest` | 합성 소재로 전 기능을 돌려 PASS/FAIL 표를 뽑음 |

### 왜 만들었나 (실측)

같은 팬(1080×1920·30fps, 프레임당 약 3.9px)을 두 방식으로 렌더하고 `measure` 로 떨림을 쟀습니다 (2026-11-19, 이 환경 2코어).

| 방식 | 프레임당 떨림(이웃 중간값 대비 편차) | 판정 |
|---|---|---|
| FFmpeg `zoompan` (정수 크롭) | **1.237px** | FAIL (기준 0.2px) |
| **motion_fx (4배 보드 + 부동소수 크롭)** | **0.038px** | PASS |

`zoompan` 은 x/y 를 정수로 잘라 쓰기 때문에 서브픽셀 이동이 1px 단위로 툭툭 튑니다. 이 모듈은
① 원본을 ss배(기본 4배)로 키운 보드를 만들고 ② 매 프레임 크롭 좌표를 실수로 계산해 ③ 보드에서 BICUBIC 으로 다시 샘플링합니다.
그래서 이동이 연속적이고, 4배 보드가 에지의 서브픽셀 정보를 들고 있어 확대해도 선이 뭉개지지 않습니다.
프레임마다 위치를 누적하지 않고 **t 로부터 매번 다시 계산**하므로 프레임이 늘어도 드리프트가 없습니다.

---

## 준비

| 항목 | 요구 | 확인 |
|---|---|---|
| FFmpeg | x264 인코딩(`libx264`), `ffmpeg` 5+ | `ffmpeg -version` |
| ffprobe | 있으면 포맷 판독에 사용(없으면 `ffmpeg -i` 파싱으로 대체) | `ffprobe -version` |
| Python | 3.10+ | `python3 -V` |
| Pillow | 필수 | `python3 -c "import PIL; print(PIL.__version__)"` → `pip install pillow` |

ffmpeg 이 PATH 에 없으면 `--ffmpeg /경로/ffmpeg` 로 넘기면 됩니다(ffprobe 도 같은 폴더면 자동 인식).

```bash
mkdir -p art parts out
```

---

## 빠른 시작

### 1) 한 장으로 줌인 5초

```bash
python3 motion_fx.py kenburns art/cut01.png out/zoom.mp4 --preset zoom_in --dur 5 --zoom 1.18
```

### 2) 여러 컷 + 셰이크 + 파츠 (실무 기본형)

`job.json`:

```json
{
  "size": [1080, 1920], "fps": 30, "ss": 4,
  "shots": [
    {"image": "art/cut01.png", "preset": "zoom_in",  "dur": 1.9, "zoom": 1.16, "anchor": [0.5, 0.40]},
    {"image": "art/cut02.png", "preset": "pan_lr",   "dur": 1.5, "zoom": 1.16, "ease": "linear"},
    {"image": "art/cut03.png", "preset": "zoom_out", "dur": 1.6, "zoom": 1.12}
  ],
  "shakes": [{"at": 3.45, "amp": 16, "dur": 0.42, "freq": 10, "rot": 0.32}],
  "parts": [
    {"png": "parts/eyes_closed.png", "x": 500, "y": 767, "space": "camera", "shot": 0,
     "blink": {"every": [0.9, 1.15], "hold": 0.10, "phase": 0.45}},
    {"png": "parts/sweat.png", "x": 712, "y": 612, "scale": 0.45,
     "t0": 2.10, "t1": 3.15, "pop": 0.16, "fade": 0.12, "drift": [0, -16]},
    {"png": "parts/excl.png", "x": 884, "y": 486, "scale": 0.5,
     "t0": 3.45, "t1": 4.70, "pop": 0.12, "fade": 0.10, "wobble": {"amp": 4, "freq": 3.0}}
  ]
}
```

```bash
python3 motion_fx.py make job.json out/pilot.mp4
python3 motion_fx.py make job.json out/pilot.mp4 --frames-dir out/frames   # 프레임도 남기기(검수용)
```

### 3) 이미 렌더된 영상 위에 파츠만 얹기

```bash
python3 motion_fx.py overlay out/pilot.mp4 parts.json out/pilot_parts.mp4
# 오디오는 원본 그대로 copy, 영상만 재인코딩
```

`parts.json` 은 `{"parts": [...]}` 또는 파츠 배열만 있어도 됩니다.

### 4) 검수

```bash
python3 motion_fx.py measure out/pilot.mp4                  # 전체
python3 motion_fx.py measure out/pilot.mp4 --window 2.0 3.3 # 팬 구간만(권장)
python3 motion_fx.py measure out/pilot.mp4 --json           # 프레임별 이동량까지
```

### 5) 자체 시험 / 데모 파츠 생성

```bash
python3 motion_fx.py selftest                     # 합성 소재로 전 기능 PASS/FAIL
python3 motion_fx.py demo-parts parts             # 눈감김·식은땀·느낌표 PNG 생성
```

---

## 카메라 프리셋

| preset | 움직임 | 기본 zoom | 언제 |
|---|---|---|---|
| `zoom_in` | 중앙(또는 anchor) 고정, 서서히 당김 | 1.12 | 대사가 무게를 얻어야 할 때 |
| `zoom_out` | 당겨져 있다가 넓어짐 | 1.12 | 상황을 보여주며 마무리 |
| `pan_lr` / `pan_rl` | 좌→우 / 우→좌 횡이동 | 1.25 | 한 컷을 길게 쓰며 시선 유도 |
| `pan_tb` / `pan_bt` | 위→아래 / 아래→위 | 1.25 | 세로 아트의 위·아래 정보를 훑을 때 |
| `static` | 고정(셰이크만 얹거나 파츠만) | 1.00 | 자막·스티커 강조 컷 |

**권장 수치**
- `zoom` 1.10~1.20. 1.3 이상은 라인아트가 뭉개지고 "휙" 도는 느낌이 납니다.
- 숏폼 컷 길이 1.5~2.5초, `ease: "smooth"`(기본). 팬은 `"linear"` 가 카메라 같습니다.
- `anchor` 는 **얼굴·시선이 머무를 지점**. 세로 아트에서 얼굴이 위쪽이면 `[0.5, 0.40]`.
- 9대 규율의 "5초당 1회 장면전환"은 이 모듈이 만들어 주지 않습니다. 컷을 5초 안에 끊고, 컷 사이를 켄번즈로 채우세요.

---

## 임팩트 셰이크

```json
{"at": 3.45, "amp": 16, "dur": 0.42, "freq": 10, "rot": 0.32, "punch": 0.03, "decay": 0.14}
```

| 키 | 뜻 | 권장 |
|---|---|---|
| `at` | 시작 시각(초) | 펀치라인·자막이 튀는 순간 |
| `amp` | 최대 이동(px, 출력 기준) | 10~20 (짧은 컷일수록 크게) |
| `dur` | 지속(초) | 0.3~0.5 |
| `freq` | 진동(Hz) | 8~12 (30fps 에서 3~4프레임 주기) |
| `rot` | 회전(도) | 0.2~0.5 |
| `punch` | 펀치줌(배율) | 0.02~0.05 |
| `decay` | 감쇠 시간상수(초) | 생략 시 `dur/3` |

- 흔들림이 화면 밖으로 새지 않도록 필요한 만큼 자동으로 당겨서(줌인) 자릅니다. **여백이 생기지 않습니다.**
- 회전에도 같은 방식으로 여유를 확보합니다.

---

## 파츠 오버레이

좌표는 **최종 영상 픽셀**(1080×1920 기준)입니다 — `cheose-lipsync` 의 `SHOTS` 좌표와 같은 모델이라
립싱크 때 잰 입·눈 좌표를 그대로 씁니다. `"coord": "norm"` 을 주면 0~1 비율로도 쓸 수 있습니다.

| 키 | 뜻 |
|---|---|
| `png` | PNG(알파) 경로 — 필수 |
| `x`, `y` | 위치(px). 기본은 **중심** 좌표 |
| `anchor` | `topleft` `top` `topright` `left` `center` `right` `bottomleft` `bottom` `bottomright` |
| `scale` / `size` | 원본 대비 배율 / 직접 `[w,h]` |
| `t0`, `t1` | 노출 구간(초). `t1` 생략 시 영상 끝 |
| `space` | `screen`(기본, 화면 고정) / `camera`(카메라 무빙 따라감) |
| `shot` | 이 파츠를 붙일 컷 번호(0부터) 또는 컷 이름 |
| `fade` | 앞뒤 페이드(초) |
| `pop` | 등장 시 오버슈트 스케일(초) |
| `drift` | `[dx,dy]` 노출 동안 이동(px) |
| `wobble` | `{"amp":px,"freq":Hz}` 미세 흔들림 |
| `opacity` | 0~1 |
| `blink` | `{"every":[최소,최대],"hold":0.10,"phase":0.45,"seed":11}` — 감은 눈 PNG를 주기적으로 아주 짧게 |

### 눈 깜빡임 실무 요령 (실물 파일럿에서 얻은 것)

1. **감은 눈 PNG 는 "동공만 덮는" 크기**로. 눈 전체를 흰 타원으로 덮으면 아래 눈꺼풀선을 침범해
   회색 테두리(자국)가 남습니다. 채움의 가장자리는 **눈꺼풀선이 아니라 흰자 위**에 오게.
2. 좌우 눈을 **각각 다른 PNG·좌표**로 두는 게 정확합니다(얼굴이 살짝 기울어 있음).
3. `space: "camera"` + `shot` 을 지정해야 줌·팬을 해도 눈 위에 붙어 있습니다. 좌표는 **zoom 1(원본 프레임) 기준**.
4. `blink` 는 `every` 0.9~3.6초, `hold` 0.08~0.12초. 0.15초를 넘으면 "졸린 눈"으로 보입니다.
5. `pop` 0.12~0.18초면 "툭" 튀어나오는 느낌, `drift` 로 식은땀을 위로 흘려보냅니다.

---

## 검수(`measure`) 읽는 법

```
■ out/pilot.mp4
  1080x1920 · 30fps · 5s · h264
  이동 x: 평균 -3.828px/프레임 · 최대 3.850px
  떨림(이웃 중간값 대비 편차): 0.038px → PASS (기준 0.2px 미만, 컷/셰이크 제외 0프레임)
```

- **떨림** = 각 프레임 이동량이 이웃 7프레임 중간값에서 얼마나 튀는지의 RMS. 일정 속도 팬이나 부드러운 이징은 0에 가깝습니다.
- 컷·셰이크처럼 화면이 크게 바뀌는 프레임은 자동으로 제외합니다(제외 프레임 수 표시).
- **한계**: '전역 이동량' 하나로 재는 지표입니다. 아래 구간은 이동이 아니라 연출이라 값이 흔들립니다.
  · 셰이크 · 파츠(느낌표·식은땀)가 툭 튀어나오는 순간 · 컷 직후
  · 확대/축소 구간(특징점마다 이동량이 다름)
  → 판정은 **연출이 없는 구간만** `--window 시작 끝` 으로 지정하세요.

실물 파일럿(5초·3컷)을 구간별로 잰 예:

| 구간 | 내용 | 떨림 |
|---|---|---|
| 0~1.9s | 줌인 | **0.030px** |
| 1.9~3.4s | 팬(프레임당 3.8px) | **0.036px** |
| 3.4~5.0s | 줌아웃 + 셰이크 + 느낌표 등장 | 0.87px (연출 구간 — 판정 대상 아님) |
- `measure` 는 코덱·fps·해상도·길이도 같이 보여 주므로, 인코딩 사고(30fps 아님·해상도 틀림)를 먼저 잡습니다.

---

## 성능 (이 환경 2코어 CPU, GPU 0)

| 작업 | 실측 |
|---|---|
| 150프레임(5초·1080×1920·ss=4) 렌더 | **22.5초** (파츠 4개 포함) |
| selftest 전체(렌더 2회 + 측정 2회 + 파츠 검증) | 95초 |
| 출력 | 5초 · 1.3MB (CRF 18) |

실무 PC(6~12코어)는 대략 3~5배 빠릅니다. 32비트 파이프가 아니라 rawvideo 스트리밍이라 프레임을 디스크에 쓰지 않습니다
(`--frames-dir` 를 주면 남깁니다 — 검수용).

## 메모리

- ss=4 일 때 1080×1920 보드는 약 100MB 입니다(4320×7680 RGB). ss=2 로 낮추면 25MB, 대신 에지가 조금 부드러워집니다.
- 4K 보드를 쓰려면 `--size` 와 `ss` 를 함께 조정하세요(ss=4 + 4K = 약 400MB).

---

## 주의

- 이 저장소에는 **mp4·png 를 커밋하지 않습니다**(`.gitignore`). 파츠 PNG·아트는 각자 작업 폴더에서 관리하세요.
- `demo-parts` 로 만든 이미지는 **형태 확인용**입니다. 실제 편에는 그 편의 얼굴 좌표에 맞춰 다시 그려야 합니다.
- 카메라 무빙은 **컷 안에서만** 일어납니다. 컷 전환은 편집 단계(또는 `make` 의 다음 shot)에서 끊습니다.
- 고정사항(캐릭터·프레임·BGM·보이스 규격)은 이 모듈이 건드리지 않습니다. 모션만 얹습니다.

## 라이선스

- 이 폴더의 스크립트: SB Company Team 내부용
- FFmpeg: LGPL/GPL (각자 설치) · Pillow: HPND
