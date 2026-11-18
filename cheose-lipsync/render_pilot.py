#!/usr/bin/env python3
"""처세의 정석 Rhubarb 자동 립싱크 파일럿 렌더러.

원본 영상 프레임(1080x1920)에서 캐릭터 입만 지우고,
Rhubarb Lip Sync(phonetic) 큐에 맞춰 이정석 라인아트 스타일의
입모양(테두리 타원/렌즈형)을 다시 그려 넣는다.

사용:
  python3 render_pilot.py <frames_src> <frames_out> <cues.json>
  (기본값: frames_src frames_out out/p1_cues.json)

  큐는 반드시 한국어용으로 뽑짐: rhubarb -r phonetic --exportFormat json -o out/cues.json audio.wav

주의:
  아래 SHOTS 의 cx/cy(입 중심) · CL(가로 입폭) · rect(지우는 사각형)는
  **이 파일럿 클립(ep1 17.9~28.7s)의 4개 샷 실측 좌표다.** 다른 편에 쓰려면
  샷 경계(start/end)와 좌표를 그 편 기준으로 다시 재야 한다.
"""
import json, glob, os, sys
from PIL import Image, ImageDraw

SS = 4  # supersample

# 큐 -> 입모양 파라미터 (CL = 그 샷의 가로 입폭 기준 비율)
#  w: 가로 / u: 윗입술 들림 / d: 아랫입술 내림
SHAPES = {
    'X': dict(w=0.93, u=0.010, d=0.016, fill=True),   # 휴지(닫힘)
    'A': dict(w=0.97, u=0.012, d=0.022, fill=True),   # 닫힘(M/B/P)
    'B': dict(w=0.86, u=0.075, d=0.115, fill=False),  # 살짝 벌림
    'C': dict(w=0.84, u=0.130, d=0.240, fill=False),  # 벌림
    'D': dict(w=0.78, u=0.200, d=0.340, fill=False),  # 크게 벌림
    'E': dict(w=0.58, u=0.170, d=0.210, fill=False),  # 오므림
    'F': dict(w=0.38, u=0.120, d=0.140, fill=False),  # 우/오 (작게 오므림)
    'G': dict(w=0.70, u=0.090, d=0.150, fill=False),
    'H': dict(w=0.72, u=0.140, d=0.260, fill=False),
}

# 샷별 입 위치(중심)와 가로 입폭, 지우는 사각형  ← 편마다 재측정 필요
SHOTS = [
    # start, end, cx, cy, CL, erase rect
    dict(start=0.0,    end=4.80,    cx=486, cy=938, CL=58, rect=(454, 922, 532, 954), name='A_역지미소_클로즈업'),
    dict(start=4.80,   end=8.50,    cx=470, cy=790, CL=33, rect=(446, 777, 498, 803), name='B_1초침묵_팔짱'),
    dict(start=8.50,   end=9.5667,  cx=499, cy=773, CL=52, rect=(466, 762, 535, 786), name='C_카운트다운_클로즈업'),
    dict(start=9.5667, end=99.0,    cx=495, cy=797, CL=33, rect=(472, 781, 520, 817), name='D_되묻기_지적'),
]


def bez(p0, p1, p2, n=40):
    out = []
    for i in range(n + 1):
        t = i / n
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]
        out.append((x, y))
    return out


def lens(CL, cx, cy, w, u, dn, n=48):
    """좌우 코너를 고정하고 위/아래로 벌어지는 렌즈형 입 외곽선 포인트."""
    lx, rx = cx - w / 2, cx + w / 2
    top = bez((lx, cy), (cx, cy - u), (rx, cy), n)
    bot = bez((rx, cy), (cx, cy + dn), (lx, cy), n)
    return top + bot


def mouth_tile(shape, CL, size, cx_local, cy_local):
    """흰 바탕 타일에 입모양을 그려 반환(SS배 슈퍼샘플 후 축소는 호출측)."""
    W, H = size
    tile = Image.new('RGB', (W * SS, H * SS), 'white')
    d = ImageDraw.Draw(tile)
    p = SHAPES[shape]
    w = p['w'] * CL
    u = p['u'] * CL
    dn = p['d'] * CL
    if p['fill'] or max(u, dn) < 0.05 * CL:
        d.polygon([(x * SS, y * SS) for x, y in lens(CL, cx_local, cy_local, w, max(u, 0.8), max(dn, 0.8))], fill='black')
        return tile
    t = max(2.6, min(4.0, 0.062 * CL))   # 외곽선 두께(px) - 라인아트와 동일 톤
    outer = lens(CL, cx_local, cy_local, w, u + t / 2, dn + t / 2)
    d.polygon([(x * SS, y * SS) for x, y in outer], fill='black')
    iu, idn = max(u - t / 2, 0.6), max(dn - t / 2, 0.6)
    inner = lens(CL, cx_local, cy_local, max(w - t * 1.6, 2), iu, idn)
    d.polygon([(x * SS, y * SS) for x, y in inner], fill='white')
    return tile


def main():
    src_dir = sys.argv[1] if len(sys.argv) > 1 else 'frames_src'
    out_dir = sys.argv[2] if len(sys.argv) > 2 else 'frames_out'
    cues_path = sys.argv[3] if len(sys.argv) > 3 else 'out/p1_cues.json'
    fps = 30
    cues = json.load(open(cues_path))['mouthCues']
    os.makedirs(out_dir, exist_ok=True)
    frames = sorted(glob.glob(os.path.join(src_dir, '*.png')))

    for idx, fp in enumerate(frames):
        t0, t1 = idx / fps, (idx + 1) / fps
        shot = next(s for s in SHOTS if s['start'] <= t0 < s['end'])
        # 프레임 구간과 가장 많이 겹치는 큐 선택 (짧은 큐 플리커 완화)
        best, best_ov = 'X', -1.0
        for c in cues:
            ov = min(t1, c['end']) - max(t0, c['start'])
            if ov > best_ov + 1e-9:
                best, best_ov = c['value'], ov
        x0, y0, x1, y1 = shot['rect']
        w, h = x1 - x0, y1 - y0
        tile = mouth_tile(best, shot['CL'], (w, h), shot['cx'] - x0, shot['cy'] - y0)
        tile = tile.resize((w, h), Image.LANCZOS)
        im = Image.open(fp).convert('RGB')
        im.paste(tile, (x0, y0))
        im.save(os.path.join(out_dir, os.path.basename(fp)), optimize=False)
        if idx % 60 == 0:
            print(f'frame {idx}/{len(frames)} t={t0:.2f}s shot={shot["name"]} shape={best}', flush=True)
    print('done', len(frames))


if __name__ == '__main__':
    main()
