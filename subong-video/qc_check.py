#!/usr/bin/env python3
"""
쇼츠 QC 체크 — 수민 님 9대 규율 중 자동 검증 가능한 항목만 본다.

  · 해상도 720p 이상 & 9:16 인지
  · 상하/좌우 검은 바(재생바·부가문구 크롭 누락) 여부
  · 장면전환 간격 최대값 (규율: 5초당 1회 이상)
  · 음량 (YouTube/릴스 권장 -14 LUFS 근처)

사용:  python3 qc_check.py video.mp4 [--ffmpeg /path/to/ffmpeg] [--ffprobe ...] [--json]
"""
import argparse
import json
import re
import subprocess
import sys


def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def probe(ffprobe, path):
    r = sh([ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    d = json.loads(r.stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    num, den = (v["r_frame_rate"].split("/") + ["1"])[:2]
    fps = float(num) / float(den or 1)
    return {
        "width": v["width"], "height": v["height"], "fps": round(fps, 2),
        "vcodec": v["codec_name"], "duration": round(float(d["format"]["duration"]), 2),
        "audio": bool(a), "acodec": a["codec_name"] if a else None,
        "audio_ch": a.get("channels") if a else None,
    }


def crop_detect(ffmpeg, path, samples=40):
    r = sh([ffmpeg, "-hide_banner", "-i", path, "-vf",
            f"cropdetect=limit=24:round=2:reset=0", "-frames:v", str(samples), "-f", "null", "-"])
    found = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", r.stderr)
    if not found:
        return None
    w, h, x, y = map(int, found[-1])
    return {"w": w, "h": h, "x": x, "y": y}


def cuts(ffmpeg, path, threshold=8):
    r = sh([ffmpeg, "-hide_banner", "-i", path, "-vf", f"scdet=threshold={threshold}",
            "-f", "null", "-"])
    times = sorted({float(t) for t in re.findall(r"lavfi\.scd\.time:\s*([0-9.]+)", r.stderr)})
    return times


def loudness(ffmpeg, path):
    r = sh([ffmpeg, "-hide_banner", "-nostats", "-i", path, "-filter_complex",
            "ebur128=peak=true", "-f", "null", "-"])
    m = re.findall(r"I:\s*(-?[0-9.]+)\s*LUFS", r.stderr)
    return float(m[-1]) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("--ffprobe", default="ffprobe")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    info = probe(a.ffprobe, a.video)
    crop = crop_detect(a.ffmpeg, a.video)
    cuts_v = cuts(a.ffmpeg, a.video)
    lufs = loudness(a.ffmpeg, a.video) if info["audio"] else None

    bars = []
    if crop and (crop["w"] < info["width"] - 2 or crop["h"] < info["height"] - 2):
        bars = [crop["x"], crop["y"], info["width"] - crop["w"] - crop["x"], info["height"] - crop["h"] - crop["y"]]
    # 상하 좌우 여백 비율
    bar_ratio = 0.0
    if bars:
        bar_ratio = 1 - (crop["w"] * crop["h"]) / (info["width"] * info["height"])

    boundaries = [0.0] + cuts_v + [info["duration"]]
    gaps = [round(b - a2, 2) for a2, b in zip(boundaries, boundaries[1:])]
    max_gap = max(gaps) if gaps else info["duration"]
    aspect = round(info["width"] / info["height"], 3)

    checks = []
    checks.append(("해상도 720p+", info["height"] >= 1280 or min(info["width"], info["height"]) >= 720,
                   f'{info["width"]}x{info["height"]}'))
    checks.append(("9:16 세로", abs(aspect - 9 / 16) < 0.02, f"aspect {aspect}"))
    checks.append(("프레임레이트 30fps+", info["fps"] >= 29.5, f'{info["fps"]}fps'))
    checks.append(("검은 바 없음", bar_ratio < 0.02,
                   (f'{crop["w"]}x{crop["h"]}+{crop["x"]}+{crop["y"]} (여백 {bar_ratio*100:.1f}%)'
                    if crop else "cropdetect 실패")))
    checks.append(("5초당 1회 장면전환", max_gap <= 5.0,
                   f"컷 {len(cuts_v)}개 / 최대 간격 {max_gap}s"))
    if lufs is not None:
        checks.append(("음량 -14 LUFS ±3", abs(lufs + 14) <= 3, f"{lufs} LUFS"))

    if a.json:
        print(json.dumps({"info": info, "crop": crop, "cuts": cuts_v, "gaps": gaps,
                          "lufs": lufs, "checks": checks}, ensure_ascii=False, indent=1))
        return

    print(f'\n■ {a.video}')
    print(f'  {info["width"]}x{info["height"]} · {info["fps"]}fps · {info["duration"]}s · '
          f'{info["vcodec"]} · 오디오 {"있음" if info["audio"] else "없음"}')
    print(f'  컷 타임: {", ".join(str(c) for c in cuts_v) if cuts_v else "없음"}')
    for name, ok, detail in checks:
        print(f'  [{"PASS" if ok else "FAIL"}] {name:<16} {detail}')
    ng = sum(1 for _, ok, _ in checks if not ok)
    print(f'  → {"전항목 통과" if ng == 0 else str(ng) + "항목 확인 필요"}\n')


if __name__ == "__main__":
    main()
