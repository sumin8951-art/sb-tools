# subong-video — 수봉TV 쇼츠 제작용 FFmpeg 파이프라인 (검증 완료)

> 저장소: https://github.com/sumin8951-art/sb-tools · 담당: 에대리(렌더링) · 뮤팀장(1차 검수)
> 이 폴더에는 `vertical_pack.sh` · `karaoke_ass.py` · `qc_check.py` 세 개만 있습니다. 영상·자막 샘플은 용량 때문에 넣지 않았습니다.

## 요구 사항
- **FFmpeg 7 이상** 권장 (8.x 확인). libass 필수(자막), `xbr`/`hqx`/`cropdetect`/`scdet`/`zoompan` 내장 필터 사용.
  - 확인: `ffmpeg -filters | grep -Ew "ass|xbr|hqx|cropdetect|scdet|zoompan"`
- **ffprobe** (`qc_check.py` 사용 시)
- 한국어 폰트 (예: Noto Sans KR, Pretendard). 자막 굴 때 `--fonts` 로 폰트 폴더를 지정.
  - ⚠ 폰트 파일의 내부 패밀리명이 실제 이름과 다르면(예: `NotoSansKR-Black.ttf` 의 패밀리명이 "Noto Sans KR Thin") libass가 엉뚱한 굵기로 그린다. 폰트 이름을 먼저 확인하고, 애매하면 패밀리명을 직접 정한 사본을 만들어 쓸 것.
- GPU 불필요. Node/Python 패키지 설치 불필요(qc_check는 표준 라이브러리만 사용).

## 1) vertical_pack.sh — 크롭 → 업스케일 → 세로 합성 → 자막

```bash
chmod +x vertical_pack.sh   # 처음 한 번 (git clone 후 실행 권한이 없을 수 있음)
```
```bash
# 기본 (검은 바 자동 크롭 + xbr 픽셀아트 업스케일 + 60fps)
./vertical_pack.sh raw_capture.mp4 out.mp4 --ass subs.ass --fonts /path/to/fonts

# 크롭 없이, 라인아트(비픽셀) 소스
./vertical_pack.sh lineart.mp4 out.mp4 --up lanczos --fps 30 --ass subs.ass

# xbr 배율 고정 (기본은 320→1080 이면 자동으로 xbr=4)
./vertical_pack.sh raw.mp4 out.mp4 --up xbr --xbr-n 3 --fps 30
```
- 옵션: `--up xbr|hqx|neighbor|lanczos` · `--xbr-n 2|3|4` · `--fps 30|60` · `--crf 18`
  · `--crop W:H:X:Y` / `--no-crop` · `--out-size 1080x1920` · `--blur 24` · `--ass subs.ass` · `--fonts 폴더`
- `FF=/path/to/ffmpeg` 환경변수로 ffmpeg 바이너리 지정 가능 (ffprobe는 같은 폴더에서 찾음).
- 검증 결과(2026-11-19, 2코어 CPU): 320×240 원본 11초·30fps → 1080×1920 xbr3 출력 **22.8초**(약 0.5배 실시간). xbr4는 26.6초.
- `--up neighbor` 는 각진 픽셀을 그대로 살린다(픽셀아트 고증 취향). `lanczos` 는 부드럽게.

> 무거운 부분은 배경 블러(`boxblur`)임. 배경이 고정이면 블러 이미지를 1장 만들어 `-loop 1`로 재사용하면 크게 빨라진다.

## 2) karaoke_ass.py — whisper 단어 타임스탬프 → ASS 한국어 워드 하이라이트
```bash
# 입력 JSON: faster-whisper의 word_timestamps 결과(segments[].words[]) 그대로 사용 가능
python3 karaoke_ass.py --words words.json --out subs.ass \
  --font "SubongCaption" --fontsize 104 --max-chars 18 --max-gap 0.4 --margin-v 300 --pop

ffmpeg -i in.mp4 -vf "ass=subs.ass:fontsdir=/path/to/fonts" -c:v libx264 -crf 18 out.mp4
```
- `--primary` 미읽은 단어 색(&HBBGGRR), `--highlight` 읽는 중~읽은 단어 색(기본 노랑)
- `--max-chars` 로 9:16 한 줄 길이 제어. **WrapStyle=2(줄바꿈 없음)** 이라 길면 화면 밖으로 잘린다.
  → 폰트 크기와 함께 실측할 것. 1080×1920 기준 `--fontsize 104` + `--max-chars 18` 이면 최대 폭 992px(안전).
- `--max-gap` (기본 0.55초): 이 시간 이상 쉬면 줄을 강제로 끊어 **문장 단위 자막**에 가깝게 만든다. 0.4 권장.
- 하이라이트는 누적형(읽은 단어가 노랑으로 남음)이다. "지금 읽는 단어 하나만" 강조하려면 단어별 이벤트 분리가 필요(미구현).

## 3) qc_check.py — 납품 전 자동 검수
```bash
python3 qc_check.py out.mp4 --ffprobe /path/to/ffprobe --ffmpeg /path/to/ffmpeg
```
판정 항목: 720p+, 9:16, 30fps+, 검은 바 여백<2%, 최대 컷 간격 ≤5초, 음량 -14 LUFS ±3.
주의: 검은 바 판정은 어두운 배경 디자인에서 오탐할 수 있음 → FAIL이면 눈으로 확인.

## 4) 2026-11-19 수봉TV 파일럿에서 고친 것 (이 버전부터 적용)
| 파일 | 증상 | 조치 |
|---|---|---|
| `karaoke_ass.py` | 단어 하이라이트 색이 **반대**로 나옴 — 안 읽은 단어가 노랑, 읽은 단어가 흰색 | 스타일의 Primary/Secondary 자리를 맞바꿈 |
| `karaoke_ass.py` | 줄 끊기가 글자 수만 봐서 문장 중간에서 잘림 | `--max-gap` 옵션 추가 |
| `vertical_pack.sh` | `--ass` 로 자막을 넣어도 번들 폰트를 못 찾아 대체 폰트로 렌더 | `--fonts` 옵션 추가(`fontsdir=`) |
| `vertical_pack.sh` | `--up neighbor`/`lanczos` 를 줘도 둘 다 lanczos 로 렌더 | 지정 필터를 그대로 쓰도록 수정 |
| `vertical_pack.sh` | xbr 배율이 자동(320→1080 = xbr4)이라 3배 고정 불가 | `--xbr-n` 옵션 추가 |

원본 백업: `karaoke_ass.py.bak-before-colorfix`

### faster-whisper 주의 (단어 타임스탬프 만들 때)
- `av` 패키지 버전에 따라 `transcribe("file.wav")` 가 `TypeError: unexpected keyword argument 'metadata_errors'` 로 죽는다.
  → ffmpeg로 16kHz 모노 wav를 뽑아 **numpy 배열로 넘기면** 회피된다.
- 결과 JSON은 `{"words":[{"word","start","end"}]}` 또는 `{"segments":[{"words":[...]}]}` 둘 다 지원.
- 실제 적용 예(수봉TV 6탄 파일럿): 단어 타임스탬프 96개 → ASS 1개, `--fontsize 104`·`--max-chars 18`·`--max-gap 0.4`에서 최대 폭 992px(1080 안전).
