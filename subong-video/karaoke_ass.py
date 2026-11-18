#!/usr/bin/env python3
"""
whisper word-timestamps(JSON) -> ASS karaoke subtitle (word-level highlight).

지원 입력:
  - faster-whisper / openai-whisper JSON: {"segments":[{"words":[{"word","start","end"}], ...}]}
  - {"words":[{"word","start","end"}, ...]}  (플랫 리스트)

사용:
  python3 karaoke_ass.py --words korean.whisper.json --out out.ass \
      --font "Noto Sans KR" --fontsize 96 --max-chars 12 \
      --primary "&H00FFFFFF" --highlight "&H0000E5FF" --outline 10 --margin-v 300

FFmpeg로 굽기:
  ffmpeg -i in.mp4 -vf "ass=out.ass:fontsdir=/path/to/fonts" -c:v libx264 -crf 18 out.mp4
"""
import argparse
import json
import os


def load_words(path):
    data = json.load(open(path, encoding="utf-8"))
    words = []
    if "segments" in data:
        for seg in data["segments"]:
            for w in seg.get("words", []):
                text = (w.get("word") or "").strip()
                if text:
                    words.append({"w": text, "s": float(w["start"]), "e": float(w["end"])})
    elif "words" in data:
        for w in data["words"]:
            text = (w.get("word") or "").strip()
            if text:
                words.append({"w": text, "s": float(w["start"]), "e": float(w["end"])})
    else:
        raise SystemExit("segments[] 또는 words[] 가 있는 JSON이 필요합니다.")
    words.sort(key=lambda x: x["s"])
    return words


def chunk_words(words, max_chars, max_gap=0.55):
    """글자 수 기준으로 줄을 나누고, 긴 침묵에서는 강제로 끊는다."""
    lines, cur, cur_len, last_end = [], [], 0, None
    for w in words:
        add = len(w["w"]) + (1 if cur else 0)
        gap_break = last_end is not None and (w["s"] - last_end) > max_gap
        if cur and (cur_len + add > max_chars or gap_break):
            lines.append(cur)
            cur, cur_len = [], 0
            add = len(w["w"])
        cur.append(w)
        cur_len += add
        last_end = w["e"]
    if cur:
        lines.append(cur)
    return lines


def ass_time(t):
    if t < 0:
        t = 0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_ass(lines, args):
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {args.width}
PlayResY: {args.height}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,{args.font},{args.fontsize},{args.highlight},{args.primary},{args.outline_color},{args.back_color},-1,0,0,0,100,100,{args.spacing},0,1,{args.outline},{args.shadow},2,{args.margin_h},{args.margin_h},{args.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    pop = (r"{\fscx75\fscy75\blur2"
           r"\t(0,90,\fscx110\fscy110\blur0)"
           r"\t(90,160,\fscx100\fscy100)}")
    out = [head]
    for line in lines:
        start, end = line[0]["s"], line[-1]["e"]
        if end - start < 0.20:          # 너무 짧은 줄은 최소 노출시간 확보
            end = start + 0.20
        # \k 는 centisecond 단위, 줄 시작 기준 누적. 단어 사이 공백은 앞 단어에 흡수.
        parts, prev_end = [], start
        for i, w in enumerate(line):
            w_start = max(prev_end, w["s"])       # 겹침/역행 방지
            w_end = max(w_start + 0.02, w["e"])
            cs = max(1, int(round((w_end - w_start) * 100)))
            gap = max(0, int(round((w_start - prev_end) * 100)))
            if gap:
                parts.append(f"{{\\k{gap}}}")     # 묵음 구간
            parts.append(f"{{\\k{cs}}}{w['w']}")
            parts.append(" " if i < len(line) - 1 else "")
            prev_end = w_end
        text = "".join(parts)
        out.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Karaoke,,0,0,0,,"
                   f"{pop if args.pop else ''}{text}\n")
    return "".join(out)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--words", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--font", default="Noto Sans KR")
    p.add_argument("--fontsize", type=int, default=96)
    p.add_argument("--max-chars", type=int, default=12)
    p.add_argument("--max-gap", type=float, default=0.55, help="이 초 이상 쉬면 줄을 강제로 끊는다(문장 단위 끊기)")
    p.add_argument("--width", type=int, default=1080)
    p.add_argument("--height", type=int, default=1920)
    p.add_argument("--primary", default="&H00FFFFFF")     # 아직 안 읽은 단어(흰색, &HBBGGRR)
    p.add_argument("--highlight", default="&H0000E5FF")   # 읽는 중 단어(노랑)
    p.add_argument("--outline-color", default="&H00000000")
    p.add_argument("--back-color", default="&H80000000")
    p.add_argument("--outline", type=int, default=10)
    p.add_argument("--shadow", type=int, default=4)
    p.add_argument("--spacing", type=int, default=0)
    p.add_argument("--margin-h", type=int, default=60)
    p.add_argument("--margin-v", type=int, default=300)
    p.add_argument("--pop", action="store_true", help="줄 등장 시 1.1배 팝 애니메이션")
    args = p.parse_args()

    words = load_words(args.words)
    lines = chunk_words(words, args.max_chars, args.max_gap)
    ass = build_ass(lines, args)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    open(args.out, "w", encoding="utf-8").write(ass)
    print(f"{args.out}: {len(words)}단어 / {len(lines)}줄")


if __name__ == "__main__":
    main()
