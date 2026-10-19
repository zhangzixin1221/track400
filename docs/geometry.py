import math, sys
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, "src")

W, H = 1000, 780
S = 3.0
CX, CY = 480, 420
STRAIGHT = 84.39
R1, R2, R8 = 36.80, 37.92, 46.26

def font(size):
    for p in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\simhei.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()

F_TITLE, F_TXT, F_SMALL = font(34), font(20), font(16)
BG = (248, 250, 252)
TRACK = (226, 168, 152)
INFIELD = (206, 232, 200)
LANE2 = (220, 38, 38)
DIM = (71, 85, 105)

im = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(im)

def oval_points(r, cx=CX, cy=CY, n=720):
    L = STRAIGHT / 2
    pts = []
    for k in range(n):
        s = k / n * (2 * STRAIGHT + 2 * math.pi * r)
        if s < STRAIGHT:
            x, y = r, -L + s
        elif s < STRAIGHT + math.pi * r:
            th = (s - STRAIGHT) / r
            x, y = r * math.cos(th), L + r * math.sin(th)
        elif s < 2 * STRAIGHT + math.pi * r:
            x, y = -r, L - (s - STRAIGHT - math.pi * r)
        else:
            th = math.pi + (s - 2 * STRAIGHT - math.pi * r) / r
            x, y = r * math.cos(th), -L + r * math.sin(th)
        pts.append((cx + x * S, cy - y * S))
    return pts

d.polygon(oval_points(R8), fill=TRACK)
d.polygon(oval_points(36.5), fill=INFIELD)

def dashed(pts, fill, width=3, dash=10, gap=7):
    x0, y0 = pts[0]
    on = True
    acc = 0.0
    for x1, y1 in pts[1:]:
        seg = math.hypot(x1 - x0, y1 - y0)
        t = 0.0
        while t < seg:
            step = (dash if on else gap) - acc
            if t + step > seg:
                acc += seg - t
                t = seg
                break
            t2 = t + step
            if on:
                d.line([(x0 + (x1-x0)*t/seg, y0 + (y1-y0)*t/seg),
                        (x0 + (x1-x0)*t2/seg, y0 + (y1-y0)*t2/seg)], fill=fill, width=width)
            t, acc = t2, 0.0
            on = not on
        x0, y0 = x1, y1

dashed(oval_points(R2), LANE2, width=4)

# 起点
sx, sy = CX + R2 * S, CY + (STRAIGHT/2) * S
d.ellipse([sx-10, sy-10, sx+10, sy+10], fill=(16, 185, 129), outline=(15, 23, 42), width=2)
d.text((sx + 18, sy - 10), "起点（东直道南端）", font=F_SMALL, fill=(15, 23, 42))

# 方向箭头
ax, ay = CX + R2 * S, CY - 40
d.line([(ax, ay + 55), (ax, ay - 55)], fill=(15, 23, 42), width=3)
d.polygon([(ax, ay - 70), (ax - 9, ay - 50), (ax + 9, ay - 50)], fill=(15, 23, 42))
d.text((ax + 12, ay - 40), "跑进方向（北）", font=F_SMALL, fill=(15, 23, 42))

# 半径标注
d.line([(CX, CY), (CX + R2 * S, CY)], fill=DIM, width=2)
d.text((CX + 30, CY - 26), "R(2) = 37.92 m", font=F_SMALL, fill=DIM)
d.ellipse([CX-4, CY-4, CX+4, CY+4], fill=DIM)

# 直道标注（东侧）
x_line = CX + R8 * S + 46
d.line([(x_line, CY - (STRAIGHT/2) * S), (x_line, CY + (STRAIGHT/2) * S)], fill=DIM, width=2)
d.line([(x_line-8, CY - (STRAIGHT/2) * S), (x_line+8, CY - (STRAIGHT/2) * S)], fill=DIM, width=2)
d.line([(x_line-8, CY + (STRAIGHT/2) * S), (x_line+8, CY + (STRAIGHT/2) * S)], fill=DIM, width=2)
d.text((x_line + 12, CY - 10), "直道 84.39 m", font=F_SMALL, fill=DIM)

# 标题与说明
d.text((40, 30), "标准 400m 田径场 · 第 2 道", font=F_TITLE, fill=(15, 23, 42))
lines = [
    "圈长 P(2) = 2×84.39 + 2π×37.92 = 407.04 m",
    "道宽 1.22 m；丈量线外移：第 1 道 0.30 m，其余 0.20 m",
    "跑进方向：逆时针；直道沿南北向，起点在第 2 道东直道南端",
]
for i, t in enumerate(lines):
    d.text((40, 90 + i * 30), t, font=F_TXT, fill=(51, 65, 85))

d.text((40, H - 46), "俯视示意，非按比例精确制图 · 生成脚本见 docs/geometry.py", font=F_SMALL, fill=(148, 163, 184))

im.save("docs/track400_geometry.png")
print("saved docs/track400_geometry.png")
