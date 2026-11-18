# cheose-lipsync — 처세의 정석 자동 립싱크 (Rhubarb)

> 저장소: https://github.com/sumin8951-art/sb-tools · 담당: 팅사원(렌더링) · 에대리(파일럿 원본) · 뮤팀장(1차 검수)
> 대표·뮤팀장 파일럿 **합격**(2026-11-19). 기존 방식(프레임마다 `fi % 6 < 3`로 입을 여닫던 것)을 대체합니다.

## 무엇을 하는가

1. **Rhubarb Lip Sync**가 나레이션 오디오를 분석해 **입모양 큐**(시작·끝·모양)를 JSON으로 뽑는다.
2. `render_pilot.py`가 원본 프레임에서 캐릭터 **입만 지우고**, 큐에 맞는 입모양을 이정석 라인아트 톤으로 다시 그려 넣는다.
3. `make_contact_sheet.py`가 결과를 **검수용 컨택트시트**(얼굴 12컷 + 입 확대 8컷 + 큐 타임라인/파형)로 뽑는다.
4. 오디오는 **원본 그대로 copy** — 소리·비트가 바뀌지 않는다.

---

## ⚠️ 반드시 지킬 것 ①: `-r phonetic`

```bash
rhubarb -r phonetic --exportFormat json -o out/cues.json src/audio.wav
```

Rhubarb 기본 인식기(`pocketSphinx`)는 **영어 전용**입니다. 한국어 나레이션에 기본값을 쓰면 큐가 거의 안 나오거나 엉뚱하게 나옵니다.
`phonetic`은 언어와 무관하게 소리(발음) 기준으로 분석하므로 **한국어 TTS 나레이션에 이걸 씁니다.**
파일럿 실측: 10.81초 오디오 → 큐 58개 (처리 3.55초, 2코어 CPU·GPU 0).

## ⚠️ 반드시 지킬 것 ②: 입모양 8종 매핑

Rhubarb가 주는 값은 아래 8종입니다. `render_pilot.py`의 `SHAPES` 표에 비율이 들어 있습니다(CL = 그 샷의 가로 입폭 기준).

| 큐 | 뜻 | 이 캐릭터에서 |
|---|---|---|
| **X** | 휴지(무음) | **닫힘** — 무음 구간은 반드시 X 하나로 떨어져야 정상 |
| **A** | 닫힘 (M·B·P) | 닫힘 |
| **B** | 살짝 벌림 | 살짝 벌림 |
| **C** | 벌림 | 벌림 |
| **D** | 크게 벌림 | 크게 벌림 |
| **E** | 오므림 | 오므림 |
| **F** | 우/오 (작게 오므림) | 작게 오므림 |
| G · H | (거의 안 나옴) | 표에 값은 있음 |

파일럿 큐 분포: **B 21 · C 14 · F 10 · A 6 · E 4 · X 3** (D·G·H 없음).
→ `X`·`A`만 나오고 B~F가 안 나오면 `-r phonetic`을 안 준 것이고, `D`만 잔뜩 나오면 입폭(CL)을 잘못 잰 것입니다.

---

## 준비

```bash
# 1) Rhubarb v1.14.0 (MIT, 87MB) — 저장소에 바이너리는 넣지 않았습니다
#    https://github.com/DanielSWolf/rhubarb-lip-sync/releases/tag/v1.14.0
#    Rhubarb-Lip-Sync-1.14.0-Windows.zip / -macOS.zip / -Linux.zip  → 풀면 rhubarb 실행 파일

# 2) 파이썬 패키지
pip install pillow numpy

# 3) 폴더
mkdir -p src frames_src frames_out out
```

## 재현 명령 (파일럿 그대로)

```bash
FF=ffmpeg   # 또는 FF=/경로/ffmpeg
RB=./Rhubarb-Lip-Sync-1.14.0-Linux/rhubarb

# 1) 마스터 클립(정확 컷) + 오디오 + 프레임
$FF -ss 17.9 -t 10.8 -i master.mp4 -c:v libx264 -crf 16 -pix_fmt yuv420p -r 30 -c:a aac -b:a 192k src/p1_master.mp4
$FF -i src/p1_master.mp4 -vn -ac 1 -ar 48000 -c:a pcm_s16le src/p1_audio.wav
$FF -i src/p1_master.mp4 -vsync 0 frames_src/%04d.png

# 2) 한국어 입모양 큐  ← -r phonetic 필수
$RB -r phonetic --exportFormat json -o out/p1_cues.json src/p1_audio.wav

# 3) 입 지우고 다시 그리기 (샷별 좌표는 render_pilot.py 의 SHOTS)
python3 render_pilot.py frames_src frames_out out/p1_cues.json

# 4) 인코딩 — 오디오는 copy로 원본 유지
$FF -framerate 30 -i frames_out/%04d.png -i src/p1_master.mp4 \
    -map 0:v -map 1:a -c:v libx264 -crf 18 -pix_fmt yuv420p -c:a copy \
    -movflags +faststart -shortest out/p1_lipsync.mp4

# 5) 검수 컨택트시트
python3 make_contact_sheet.py --cues out/p1_cues.json --frames frames_out \
    --audio src/p1_audio.wav --font /경로/NotoSansKR-Bold.ttf --out out/contact_sheet.png
```

`make_contact_sheet.py` 옵션: `--cues` `--frames` `--audio` `--out` `--font` `--fps` `--dur`.
폰트를 지정하지 않으면 흔한 위치(`./fonts`, `assets`, `C:/Windows/Fonts` 등)에서 한글 폰트를 찾고, 없으면 기본 폰트로 그립니다(한글이 □로 보이면 `--font`를 주세요).

## 편마다 바꿔야 하는 것 — `render_pilot.py`의 `SHOTS`

| 항목 | 뜻 |
|---|---|
| `start` / `end` | 그 샷(카메라 컷)의 구간(초). **샷이 4개면 4행** |
| `cx`, `cy` | 그 샷에서 입 중심의 픽셀 좌표(1080×1920 기준) |
| `CL` | 그 샷에서의 가로 입폭(px). 작게 잡으면 입이 크게 벌어져 보임 |
| `rect` | 원본 입을 지울 사각형 `(x0, y0, x1, y1)` — 입 **주변만** 덮게 |
| `name` | 로그에 찍히는 샷 이름 |

파일럿 실측값(참고·그대로 쓰지 말 것):

| 샷 | 구간(s) | 내용 | 중심 | CL | 지우개 사각형 |
|---|---|---|---|---|---|
| A | 0.00–4.80 | 역지 미소 클로즈업 | 486, 938 | 58 | 454,922–532,954 |
| B | 4.80–8.50 | 1초 침묵(팔짱) | 470, 790 | 33 | 446,777–498,803 |
| C | 8.50–9.57 | 카운트다운 클로즈업 | 499, 773 | 52 | 466,762–535,786 |
| D | 9.57–10.80 | 되묻기(지적) | 495, 797 | 33 | 472,781–520,817 |

**지우개 사각형이 얼굴 경계선·턱선을 넘으면 그 자국이 남습니다** — 뮤팀장 최종검수 반려 사유 1순위(2026-11-18 처세 4화). rect는 입 주변 최소 크기로.

## 검수 기준 (뮤팀장)

- 무음 구간 → **X 하나**로 떨어지는지 (파일럿: 8.49~9.54s 무음이 X 단일 큐)
- 말하는 컷 **직접 재생**해서 입모양·얼굴 경계선 확인 (스틸컷만으로 통과 금지)
- 컨택트시트상 얼굴 경계에 회색/흰 테두리 자국이 없는지
- 오디오 파형이 원본과 동일한지(재인코딩 시 `-c:a copy`)

## 성능 (2코어 CPU 기준, 팀 PC는 보통 5~10배 빠름)

| 단계 | 파일럿 실측 |
|---|---|
| Rhubarb 분석 | 10.81s 오디오 → 3.55s |
| 프레임 324장 재드로잉(Pillow 1080×1920) | 36.6s |
| 인코딩 | 5.4s |

## 라이선스

- Rhubarb Lip Sync: **MIT** © Daniel S. Wolf — 사내 사용·수정 자유, 바이너리 재배포만 라이선스 고지 동봉 필요
- 이 폴더의 스크립트: SB Company Team 내부용
