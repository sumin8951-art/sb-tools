#!/usr/bin/env python3
"""파일럿 컨택트시트 v2: 얼굴 12컷(4x3) + 입 확대 8컷 + 큐 타임라인/파형."""
import argparse
import json
import os
import numpy as np
import wave
from PIL import Image, ImageDraw, ImageFont


def resolve_font(path):
    """--font 로 준 경로 → 없으면 흔한 위치에서 한국어 폰트 찾기 → 없으면 PIL 기본
    (한국어가 □로 나오면 폰트 문제이니 --font 로 굵은 한글 폰트를 지정하세요)"""
    if path and os.path.exists(path):
        return path


def font_at(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        print(f'[warn] 폰트를 열 수 없습니다: {path} → 기본 폰트로 대체(한글이 □로 나옴)')
        return ImageFont.load_default(size)
    for d in ('./fonts', 'assets', os.path.expanduser('~/.fonts'),
              '/usr/share/fonts/truetype/noto', '/usr/share/fonts/opentype/noto',
              '/Library/Fonts', 'C:/Windows/Fonts'):
        for n in ('NotoSansKR-Bold.ttf', 'NotoSansKR-Regular.ttf', 'Pretendard-Bold.otf',
                  'NanumGothicBold.ttf', 'malgunbd.ttf'):
            p = os.path.join(d, n)
            if os.path.exists(p):
                return p
    return path
SHOT_NAMES = {'A': '역지미소', 'B': '1초침묵', 'C': '카운트다운', 'D': '되묻기'}
SHAPE_KO = {'X': '휴지', 'A': '닫힘', 'B': '살짝벌림', 'C': '벌림', 'D': '크게벌림', 'E': '오므림', 'F': '우/오'}

# (x0,y0,x1,y1) 얼굴 크롭 - 종횡비 0.8 통일
CROPS = {
    'A': (220, 436, 780, 1136),
    'B': (270, 498, 650, 973),
    'C': (240, 341, 800, 1041),
    'D': (250, 505, 630, 980),
}
MOUTH = {'A': (486, 940), 'B': (470, 792), 'C': (499, 775), 'D': (495, 799)}
SHAPE_GRAY = {'X': 45, 'A': 70, 'B': 100, 'C': 140, 'D': 175, 'E': 150, 'F': 120}


def shot_of(t):
    return 'A' if t < 4.80 else ('B' if t < 8.50 else ('C' if t < 9.5667 else 'D'))


def main():
    ap = argparse.ArgumentParser(description='처세의 정석 립싱크 컨택트시트 생성')
    ap.add_argument('--cues', default='out/p1_cues.json', help='Rhubarb 큐 JSON')
    ap.add_argument('--frames', default='frames_out', help='립싱크 렌더된 프레임 폴더')
    ap.add_argument('--audio', default='src/p1_audio.wav', help='파형용 오디오(wav)')
    ap.add_argument('--out', default='contact_sheet.png', help='저장할 PNG 경로')
    ap.add_argument('--font', default=os.environ.get('FONT', ''), help='한국어 폰트 경로')
    ap.add_argument('--fps', type=int, default=30)
    ap.add_argument('--dur', type=float, default=10.80, help='클립 길이(초)')
    a = ap.parse_args()
    FONT = resolve_font(a.font)
    FR = a.frames

    cues = json.load(open(a.cues))['mouthCues']
    fps, n = a.fps, int(round(a.dur * a.fps))
    seq = []
    for i in range(n):
        t0, t1 = i / fps, (i + 1) / fps
        best, bo = 'X', -1
        for c in cues:
            ov = min(t1, c['end']) - max(t0, c['start'])
            if ov > bo + 1e-9:
                best, bo = c['value'], ov
        seq.append(best)

    W, M = 1080, 24
    f_title = font_at(FONT, 40)
    f_sub = font_at(FONT, 21)
    f_cap = font_at(FONT, 19)
    f_small = font_at(FONT, 16)

    times = [0.20, 0.87, 1.55, 2.60, 4.87, 5.35, 6.70, 9.00, 9.62, 9.75, 10.07, 10.30]
    cols, gap = 4, 12
    pw = (W - 2 * M - gap * (cols - 1)) // cols
    ph = int(pw / 0.8)
    rows = 3
    row_h = ph + 40
    zoom_items = [(0.87, 'A'), (0.20, 'A'), (2.60, 'A'), (1.55, 'A'),
                  (4.87, 'B'), (5.35, 'B'), (9.00, 'C'), (9.75, 'D')]
    zw = (W - 2 * M - 7 * 10) // 8
    zh = int(zw * 0.72)
    H = 150 + rows * row_h + 46 + (zh + 54) + 40 + 190 + 40
    sheet = Image.new('RGB', (W, H), 'white')
    d = ImageDraw.Draw(sheet)

    d.text((M, 22), '처세의 정석 · Rhubarb 자동 립싱크 파일럿', font=f_title, fill='black')
    d.text((M, 76), '원본 ep1 17.9~28.7s (10.8s) · Rhubarb Lip Sync 1.14.0 -r phonetic · 입모양 큐 58개 · 샷 4개',
           font=f_sub, fill=(70, 70, 70))
    d.text((M, 104), '아래 얼굴컷은 실제 렌더 프레임 그대로 (입만 큐에 맞춰 다시 그림)', font=f_sub, fill=(130, 130, 130))
    d.line((M, 136, W - M, 136), fill=(210, 210, 210), width=2)

    y0 = 150
    for k, t in enumerate(times):
        r, c = divmod(k, cols)
        i = int(round(t * fps))
        sh = shot_of(t)
        val = seq[min(i, n - 1)]
        im = Image.open(os.path.join(FR, f'{i+1:04d}.png')).crop(CROPS[sh])
        im = im.resize((pw, ph), Image.LANCZOS)
        x = M + c * (pw + gap)
        yy = y0 + r * row_h
        sheet.paste(im, (x, yy))
        d.rectangle((x, yy, x + pw, yy + ph), outline=(200, 200, 200))
        d.text((x + 1, yy + ph + 6), f'{t:.2f}s · {val} {SHAPE_KO.get(val, "")}', font=f_cap, fill=(20, 20, 20))
        d.text((x + 1, yy + ph + 24), f'{sh}컷 {SHOT_NAMES[sh]}', font=f_small, fill=(120, 120, 120))

    # 입 확대
    yb = y0 + rows * row_h + 20
    d.text((M, yb), '입 확대 (큐 8종 중 등장 5종 + 휴지 · 각 3배)', font=f_sub, fill='black')
    yb += 30
    for k, (t, sh) in enumerate(zoom_items):
        i = int(round(t * fps))
        val = seq[min(i, n - 1)]
        mx, my = MOUTH[sh]
        half = 34
        zi = Image.open(os.path.join(FR, f'{i+1:04d}.png')).crop((mx - half, my - 24, mx + half, my + 26))
        zi = zi.resize((zw, zh), Image.LANCZOS)
        x = M + k * (zw + 10)
        sheet.paste(zi, (x, yb))
        d.rectangle((x, yb, x + zw, yb + zh), outline=(195, 195, 195))
        d.text((x + 1, yb + zh + 4), f'{t:.2f}s {val}', font=f_cap, fill=(0, 0, 0))
        d.text((x + 1, yb + zh + 24), SHAPE_KO.get(val, ''), font=f_small, fill=(110, 110, 110))

    # 타임라인
    yc = yb + zh + 56
    d.text((M, yc), '큐 타임라인 (위: 음량 파형 · 아래: 입모양 큐)', font=f_sub, fill='black')
    yc += 30
    wv = wave.open(a.audio)
    x_audio = np.frombuffer(wv.readframes(wv.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    tw = W - 2 * M
    mid = yc + 30
    step = max(1, len(x_audio) // tw)
    for px in range(tw):
        seg = x_audio[px * step:(px + 1) * step]
        if len(seg) == 0:
            continue
        amp = float(np.abs(seg).max())
        d.line((M + px, mid - amp * 28, M + px, mid + amp * 28), fill=(185, 185, 185))
    yc2 = mid + 34
    total = a.dur
    for c in cues:
        x0 = M + int(c['start'] / total * tw)
        x1 = M + max(int(c['end'] / total * tw), x0 + 1)
        g = SHAPE_GRAY.get(c['value'], 120)
        d.rectangle((x0, yc2, x1, yc2 + 30), fill=(g, g, g))
        if x1 - x0 > 14:
            d.text((x0 + 3, yc2 + 4), c['value'], font=f_small, fill='white')
    for t in range(0, 11):
        xx = M + int(t / total * tw)
        d.line((xx, yc2 + 30, xx, yc2 + 36), fill=(120, 120, 120))
        d.text((xx - 6, yc2 + 38), f'{t}', font=f_small, fill=(90, 90, 90))
    d.text((M, yc2 + 58), '8.5~9.6s 무음 구간 = X(휴지) 단일 큐로 정확히 떨어짐', font=f_small, fill=(120, 120, 120))
    sheet.save(a.out)
    print('saved', a.out, sheet.size)


if __name__ == '__main__':
    main()
