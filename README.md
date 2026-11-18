# 🧰 sb-tools — SB Company Team 숏폼 제작·검수 툴킷

수봉TV와 처세의 정석을 실제로 렌더링하면서 **버그를 잡고 검증을 끝낸** 스크립트만 모은 저장소입니다.
대표 승인 완료(2026-11-19). 대상: **에대리**(수봉TV 렌더링) · **팅사원**(처세 렌더링·카피) · **뮤팀장**(1차 검수·조율).

- 저장소: **https://github.com/sumin8951-art/sb-tools** (Public)
- **깃허브 로그인 필요 없습니다.** `git clone` 하거나 페이지에서 ZIP으로 받으면 바로 씁니다.

```bash
git clone https://github.com/sumin8951-art/sb-tools.git
cd sb-tools
```

---

## 폴더 구성

| 경로 | 내용 | 쓰는 사람 |
|---|---|---|
| `subong-video/` | 수봉TV 파이프라인 — 검은 바 크롭 → 픽셀아트 업스케일 → 9:16 합성 → 한국어 워드 하이라이트 자막 / 자동 QC | 에대리 |
| `cheose-lipsync/` | 처세의 정석 파이프라인 — Rhubarb 한국어 자동 립싱크(입모양 재드로잉) / 컨택트시트 검수 | 팅사원 |
| `REPORT.md` | 툴 선정 근거와 실측 수치(벤치마크 요약). 왜 이 도구인지 확인할 때 | 전원 |

---

## 공통 요구 사항

| 항목 | 요구 | 확인 명령 |
|---|---|---|
| **FFmpeg 7+** | libass 포함(`ass` 필터), `xbr`·`hqx`·`cropdetect`·`scdet` 필터 필요 | `ffmpeg -filters \| grep -Ew "ass\|xbr\|hqx\|cropdetect\|scdet"` |
| **ffprobe** | `qc_check.py` 사용 시 (ffmpeg와 같은 폴더에 있으면 자동 인식) | `ffprobe -version` |
| **python3** | 3.10 이상. `qc_check.py`는 표준 라이브러리만 사용 | `python3 -V` |
| **Rhubarb Lip Sync v1.14.0** | 처세 립싱크 전용 (MIT). 저장소에는 용량(87MB) 때문에 **바이너리를 넣지 않았습니다** — 아래 링크에서 받으세요 | `rhubarb --version` |
| Python 패키지 | `cheose-lipsync`만 Pillow(+`make_contact_sheet.py`는 numpy) 필요: `pip install pillow numpy` | — |
| 한국어 폰트 | Noto Sans KR / Pretendard 등. `--fonts`로 폴더 지정 | — |

**Rhubarb 다운로드 (v1.14.0, OS별 zip 87MB, MIT)**
https://github.com/DanielSWolf/rhubarb-lip-sync/releases/tag/v1.14.0
→ `Rhubarb-Lip-Sync-1.14.0-Windows.zip` / `-macOS.zip` / `-Linux.zip` 중 자기 OS 것을 풀면 `rhubarb` 실행 파일이 나옵니다.

GPU는 필요 없습니다. Node 패키지도 필요 없습니다.

---

## 빠른 시작 ① — 수봉TV (에대리)

```bash
cd subong-video

# 1) 9:16 패키징: 크롭 → xbr 업스케일 → 세로 합성 → 자막 (한 줄로 끝)
./vertical_pack.sh raw_capture.mp4 out.mp4 --up xbr --xbr-n 3 --fps 60 --ass subs.ass --fonts ./fonts

# 2) 자막 만들기: whisper 단어 타임스탬프 JSON → ASS 워드 하이라이트
python3 karaoke_ass.py --words words.json --out subs.ass \
  --font "SubongCaption" --fontsize 104 --max-chars 18 --max-gap 0.4 --margin-v 300 --pop

# 3) 납품 전 자동 검수 (720p+/9:16/30fps+/검은 바/5초 컷/음량)
python3 qc_check.py out.mp4
```

- 크롭 없이 라인아트 소스를 쓸 때: `--no-crop --up lanczos --fps 30`
- ffmpeg이 PATH에 없으면: `FF=/경로/ffmpeg ./vertical_pack.sh ...`
- 자세한 옵션·주의사항: **[`subong-video/README.md`](subong-video/README.md)**

## 빠른 시작 ② — 처세의 정석 (팅사원)

```bash
cd cheose-lipsync
RB=./Rhubarb-Lip-Sync-1.14.0-Linux/rhubarb   # 받은 파일 경로

# 1) 마스터 클립 + 오디오 + 프레임
ffmpeg -i master.mp4 -c:v libx264 -crf 16 -pix_fmt yuv420p -r 30 -c:a aac -b:a 192k src/master.mp4
ffmpeg -i src/master.mp4 -vn -ac 1 -ar 48000 -c:a pcm_s16le src/audio.wav
ffmpeg -i src/master.mp4 -vsync 0 frames_src/%04d.png

# 2) 한국어 입모양 큐 — 반드시 -r phonetic
$RB -r phonetic --exportFormat json -o out/cues.json src/audio.wav

# 3) 입만 지우고 큐에 맞춰 다시 그리기
python3 render_pilot.py frames_src frames_out out/cues.json

# 4) 인코딩 (오디오는 copy로 원본 유지)
ffmpeg -framerate 30 -i frames_out/%04d.png -i src/master.mp4 \
  -map 0:v -map 1:a -c:v libx264 -crf 18 -pix_fmt yuv420p -c:a copy \
  -movflags +faststart -shortest out/lipsync.mp4

# 5) 검수용 컨택트시트
python3 make_contact_sheet.py --out contact_sheet.png --font /경로/NotoSansKR-Bold.ttf
```

- **`-r phonetic`이 핵심입니다.** 기본 인식기(`pocketSphinx`)는 영어 전용이라 한국어에서 큐가 엉망이 됩니다.
- 큐 8종: **X**(휴지) **A**(닫힘) **B**(살짝 벌림) **C**(벌림) **D**(크게 벌림) **E**(오므림) **F**(우/오) + G·H.
- `render_pilot.py`의 `SHOTS`(샷별 입 좌표·지우개 사각형)는 **편마다 다시 재야 합니다.** 상세: **[`cheose-lipsync/README.md`](cheose-lipsync/README.md)**

---

## 이 버전에서 고친 버그 (2026-11-19 파일럿)

| 파일 | 증상 | 조치 |
|---|---|---|
| `karaoke_ass.py` | 단어 하이라이트 색이 **반대** — 안 읽은 단어가 노랑, 읽은 단어가 흰색 | 스타일 Primary/Secondary 자리 교체 |
| `karaoke_ass.py` | 글자 수만 보고 줄을 끊어 문장 중간에서 잘림 | `--max-gap` 옵션 추가(0.4초 권장) |
| `vertical_pack.sh` | `--ass`로 자막을 넣어도 폰트를 못 찾아 대체 폰트로 렌더 | `--fonts` 옵션 추가(`fontsdir=`) |
| `vertical_pack.sh` | `--up neighbor`/`lanczos`를 줘도 둘 다 lanczos로 렌더 | 지정 필터를 그대로 쓰도록 수정 |
| `vertical_pack.sh` | xbr 배율이 자동(320→1080이면 xbr4)이라 3배 고정 불가 | `--xbr-n` 옵션 추가 |

---

## 검수 원칙 (전원 공통)

1. `qc_check.py`는 **자동으로 잡을 수 있는 것만** 봅니다. PASS여도 직접 재생 확인은 필수입니다(내규: 최종검수 직접재생).
2. `qc_check.py`의 "검은 바" 판정은 어두운 배경 디자인에서 오탐이 납니다 → FAIL이면 눈으로 확인.
3. 입모양·얼굴 경계선은 **말하는 컷을 직접 재생**해서 봅니다(스틸컷만으로 통과 금지).
4. 이 저장소는 스크립트만 있습니다. 영상 소스·완성본은 드라이브 인계 폴더를 쓰세요.

## 라이선스 / 출처

- 이 저장소의 스크립트: SB Company Team 내부용.
- Rhubarb Lip Sync: MIT © Daniel S. Wolf (바이너리는 각자 다운로드).
- FFmpeg: LGPL/GPL (각자 설치).
- 벤치마크 출처·실측 수치: [`REPORT.md`](REPORT.md)
