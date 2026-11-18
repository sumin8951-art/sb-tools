#!/bin/bash
# 두 버그 수정 재검증 — 다른 PC 에서도 같은 방식으로 확인할 수 있게 남겨 둔다.
#   실행: bash tests/test_bugfixes.sh            (ffmpeg 필요, ffprobe 는 있으면 더 정확)
#   결과: PASS/FAIL 표, 하나라도 실패하면 exit 1
set -uo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
FF="${FF:-ffmpeg}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0

ok()   { echo "  [PASS] $1"; PASS=$((PASS+1)); }
bad()  { echo "  [FAIL] $1"; FAIL=$((FAIL+1)); }

echo "■ 준비: 테스트 소재"
"$FF" -hide_banner -loglevel error -y -f lavfi -i "testsrc2=size=240x180:rate=30:duration=1" \
      -c:v libx264 -pix_fmt yuv420p "$TMP/small_240.mp4" || { echo "ffmpeg 실패"; exit 2; }

echo "■ 버그 1: cropdetect 가 아무 결과도 못 낼 때 qc_check 가 PASS 로 흘리지 않는지"
# cropdetect 를 부르면 아무 출력도 내지 않는 ffmpeg 래퍼
cat > "$TMP/ffmpeg_nocrop" <<EOF
#!/bin/bash
for a in "\$@"; do
  case "\$a" in *cropdetect*) exec "$(command -v "$FF")" "\$@" 2>/dev/null ;; esac
done
exec "$(command -v "$FF")" "\$@"
EOF
chmod +x "$TMP/ffmpeg_nocrop"
"$FF" -hide_banner -loglevel error -y -f lavfi -i "testsrc2=size=1080x1920:rate=30:duration=1" \
      -c:v libx264 -pix_fmt yuv420p "$TMP/full.mp4"
OUT="$(python3 "$HERE/subong-video/qc_check.py" "$TMP/full.mp4" --ffmpeg "$TMP/ffmpeg_nocrop" --ffprobe "${FFPROBE:-ffprobe}" 2>&1)"
if echo "$OUT" | grep -q "\[FAIL\] 검은 바 자동검출 실패 (수동 확인 필요)"; then
  ok "자동검출 실패 → [FAIL] + 수동 확인 문구"
else
  bad "자동검출 실패 문구가 없음"; echo "$OUT" | sed 's/^/        /'
fi
if echo "$OUT" | grep -q "항목 확인 필요"; then ok "요약에 '항목 확인 필요' 로 집계"; else bad "요약 집계 어긋남"; fi
# 정상 영상에서는 예전처럼 PASS
OUT2="$(python3 "$HERE/subong-video/qc_check.py" "$TMP/full.mp4" --ffprobe "${FFPROBE:-ffprobe}" 2>&1)"
if echo "$OUT2" | grep -q "\[PASS\] 검은 바 없음"; then ok "정상 영상은 종전대로 PASS (회귀 없음)"; else bad "정상 영상 회귀"; fi

echo "■ 버그 2: --no-crop --up xbr (--xbr-n 없음) 에서 작은 원본이 렌더 실패하지 않는지"
LOG="$TMP/pack.log"
FF="$FF" bash "$HERE/subong-video/vertical_pack.sh" "$TMP/small_240.mp4" "$TMP/packed.mp4" \
     --no-crop --up xbr --fps 30 > "$LOG" 2>&1
if [ -s "$TMP/packed.mp4" ]; then ok "240x180 입력 렌더 성공"; else bad "렌더 실패"; sed 's/^/        /' "$LOG" | tail -5; fi
if grep -q "flags=xbr" "$LOG"; then bad "여전히 flags=xbr 로 떨어짐"; else ok "flags=xbr 대체 경로 없음"; fi
if grep -q "xbr=4 + neighbor" "$LOG"; then ok "4배로 부족 → xbr=4 + neighbor 안내"; fi
SIZE="$("${FFPROBE:-ffprobe}" -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0:s=x "$TMP/packed.mp4" 2>/dev/null)"
case "$SIZE" in 1080x1920*) ok "출력 1080x1920";; *) bad "출력 해상도 $SIZE";; esac
# 잘못된 --xbr-n 은 조용히 넘어가지 않고 멈춰야 한다
FF="$FF" bash "$HERE/subong-video/vertical_pack.sh" "$TMP/small_240.mp4" "$TMP/x.mp4" \
     --no-crop --up xbr --xbr-n 5 > "$TMP/n5.log" 2>&1
if grep -q "2, 3, 4" "$TMP/n5.log"; then ok "--xbr-n 5 → 명확한 안내 후 중단"; else bad "--xbr-n 검증 없음"; fi

echo
echo "■ 결과: PASS $PASS · FAIL $FAIL"
[ "$FAIL" -eq 0 ] || exit 1
