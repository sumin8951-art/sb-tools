#!/bin/bash
# 9:16 쇼츠 패키징 — 크롭 → 픽셀아트 업스케일 → 세로 캔버스 합성 → 자막 굽기
#
# 사용 예:
#   ./vertical_pack.sh raw_capture.mp4 out.mp4 --ass subs.ass --up xbr --fps 60
#   ./vertical_pack.sh raw_capture.mp4 out.mp4 --no-crop --up lanczos
#
# --up: xbr | hqx | neighbor | lanczos  (xbr/hqx = 8/16비트 픽셀아트용, 2~4배 자동)
# 크롭: ffmpeg cropdetect 로 검은 바/부가 UI 여백을 자동 제거
set -euo pipefail

FF="${FF:-ffmpeg}"
FFPROBE="${FFPROBE:-${FF%ffmpeg}ffprobe}"   # FF=/경로/ffmpeg 면 같은 폴더의 ffprobe
IN="${1:?input}"; OUT="${2:?output}"; shift 2
ASS=""; UP="xbr"; FPS="60"; CRF="18"; CROP="auto"; W="1080"; H="1920"; BLUR="24"; FONTS=""; XBRN="auto"

while [ $# -gt 0 ]; do
  case "$1" in
    --ass) ASS="$2"; shift 2;;
    --fonts) FONTS="$2"; shift 2;;
    --up) UP="$2"; shift 2;;
    --fps) FPS="$2"; shift 2;;
    --crf) CRF="$2"; shift 2;;
    --no-crop) CROP="none"; shift;;
    --crop) CROP="$2"; shift 2;;
    --out-size) W="${2%x*}"; H="${2#*x}"; shift 2;;
    --blur) BLUR="$2"; shift 2;;
    --xbr-n) XBRN="$2"; shift 2;;
    *) echo "unknown opt $1"; exit 1;;
  esac
done

# 입력 해상도 읽기: ffprobe 우선, 없으면 ffmpeg -i 헤더에서 'WxH' 토큰만 골라낸다.
probe_wh() {  # $1=파일 → "W H" 한 줄 (실패 시 빈 줄)
  local wh
  wh=$( "$FFPROBE" -v error -select_streams v:0 -show_entries stream=width,height \
        -of csv=p=0:s=x "$1" 2>/dev/null | head -1 ) || wh=""
  case "$wh" in
    [0-9]*x[0-9]*) echo "${wh%x*} ${wh#*x}"; return 0;;
  esac
  wh=$( { "$FF" -hide_banner -i "$1" 2>&1 | grep -oE '[0-9]{2,5}x[0-9]{2,5}' | head -1; } || true )
  case "$wh" in
    [0-9]*x[0-9]*) echo "${wh%x*} ${wh#*x}"; return 0;;
  esac
  echo ""
}

# 1) 크롭 자동 감지
if [ "$CROP" = "auto" ]; then
  C=$( { "$FF" -hide_banner -i "$IN" -vf "cropdetect=limit=24:round=2:reset=0" -frames:v 40 -f null - 2>&1 \
        | grep -o 'crop=[0-9:]*' | tail -1 | cut -d= -f2; } || true )
  if [ -n "${C:-}" ]; then CROP="$C"; echo "[crop] $CROP"; else CROP="none"; echo "[crop] 감지 실패 → 원본 유지"; fi
fi

# 2) 픽셀아트 업스케일 배율 계산 (xbr/hqx 는 정수배만 가능)
if [ "$CROP" != "none" ]; then
  CW=$(echo "$CROP" | cut -d: -f1); CH=$(echo "$CROP" | cut -d: -f2)
  CX=$(echo "$CROP" | cut -d: -f3); CY=$(echo "$CROP" | cut -d: -f4)
  SRC="crop=${CW}:${CH}:${CX}:${CY}"
else
  SRC="null"
  WH=$(probe_wh "$IN")
  CW=""; CH=""
  [ -n "$WH" ] && { CW="${WH% *}"; CH="${WH#* }"; }
  case "${CW}:${CH}" in
    *[!0-9:]*|:*) echo "[size] 입력 해상도를 읽지 못했습니다 (ffprobe/ffmpeg 확인 필요): $IN" >&2; exit 1;;
  esac
  echo "[size] ${CW}x${CH}"
fi

if [ "$UP" = "xbr" ] || [ "$UP" = "hqx" ]; then
  if [ "$XBRN" != "auto" ]; then
    case "$XBRN" in
      2|3|4) UPSTEP="${UP}=${XBRN}";;
      *) echo "[up] --xbr-n 은 2, 3, 4 중 하나여야 합니다 (받은 값: $XBRN)" >&2; exit 1;;
    esac
  else
    UPSTEP=""
    for N in 4 3 2; do
      if [ $((CW * N)) -ge "$W" ]; then UPSTEP="${UP}=${N}"; break; fi
    done
    if [ -z "$UPSTEP" ]; then
      # 원본이 너무 작아 최대 배율(xbr4)로도 출력 폭에 못 미치는 경우.
      # 정수배 업스케일 뒤 남은 배율만 이웃보간으로 채워 픽셀 격자를 유지한다.
      # (예전에는 여기서 UPSTEP 이 비어 flags=xbr 이라는 없는 옵션으로 떨어져 렌더가 실패했다)
      UPSTEP="${UP}=4,scale=${W}:-2:flags=neighbor"
      echo "[up] ${CW}px × 4 = $((CW * 4))px < ${W}px → ${UP}=4 + neighbor 확대" >&2
    fi
  fi
fi
if [ -z "${UPSTEP:-}" ]; then
  # xbr/hqx 이외: 지정한 필터 그대로(neighbor = 픽셀아트 고유의 각진 맛 유지)
  UPSTEP="scale=${W}:-2:flags=${UP}"
fi
echo "[up] $UPSTEP"

# 3) 세로 캔버스 합성 (+자막)
SUB=""
[ -n "$ASS" ] && SUB=",ass='${ASS}'${FONTS:+:fontsdir=${FONTS}}"

FILTER="[0:v]split=2[a][b];
[a]${SRC},${UPSTEP},scale=${W}:-2:flags=lanczos[fg];
[b]${SRC},scale=${W}:${H}:force_original_aspect_ratio=increase,crop=${W}:${H},boxblur=${BLUR}:2,eq=brightness=-0.16:saturation=0.9[bg];
[bg][fg]overlay=(W-w)/2:(H-h)/2[comp];
[comp]fps=${FPS}${SUB}[v]"

echo "[run] $IN → $OUT"
"$FF" -hide_banner -loglevel warning -stats -i "$IN" -filter_complex "$FILTER" \
  -map "[v]" -map 0:a? -c:v libx264 -preset medium -crf "$CRF" -pix_fmt yuv420p \
  -c:a aac -b:a 192k -movflags +faststart "$OUT" -y

echo "[done] $OUT"
"$FFPROBE" -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate \
  -of default=nw=1 "$OUT" 2>/dev/null || true
