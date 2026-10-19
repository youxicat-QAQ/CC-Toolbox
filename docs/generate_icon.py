"""CC-Toolbox 图标生成脚本（深空数据大屏主题）

设计说明（512×512 主画布绘制后缩放输出，纯 Pillow 几何绘制、不依赖任何字体文件）：
  - 底：圆角矩形（圆角半径约边长 22%），深空色 #0a0e17；
        外沿一圈青(#00f0ff)→紫(#7c3aed)对角线性渐变霓虹描边
  - 主体：居中几何化「工具箱」——
        · 箱体：宽约 52%、高约 34% 的圆角矩形，居中偏下，青→紫对角渐变填充（逐像素插值 + 圆角遮罩）
        · 提手：箱体上方 ∩ 拱形（粗描边半椭圆弧），同一渐变
        · 锁扣：箱体正中深空色挖空小竖矩形 + 两侧浅青(#a5f3fc)圆形铆钉
  - 氛围：箱体后方大而淡的青紫混合径向光晕（峰值约 18% 不透明度）；
        顶部一条低透明度扫描线（附一小段亮青高光）

输出（可重复运行，幂等覆盖）：
  static/icon.png      256×256 应用图标
  static/icon-64.png   64×64  网页小图标
  static/favicon.ico   内含 16/32/48 三档

运行方式（仅维护者需要；应用运行时与 requirements.txt 均不需要 Pillow）：
  python docs/generate_icon.py
  依赖安装：pip install pillow
"""

import os

from PIL import Image, ImageChops, ImageDraw

# ---------- 主题色 ----------
DEEP = (10, 14, 23)           # #0a0e17 深空底
CYAN = (0, 240, 255)          # #00f0ff 青
PURPLE = (124, 58, 237)       # #7c3aed 紫
LIGHT_CYAN = (165, 243, 252)  # #a5f3fc 铆钉浅青

# ---------- 画布几何（基于 512 主画布） ----------
S = 512                          # 主画布边长
MARGIN = 4                       # 描边外沿留白
STROKE = 6                       # 霓虹描边宽度
RADIUS = int(S * 0.22)           # 底板圆角半径（约 22%）

BOX_W = int(S * 0.52)            # 箱体宽约 52%
BOX_H = int(S * 0.34)            # 箱体高约 34%
BOX_CX = S // 2                  # 箱体水平居中
BOX_CY = S // 2 + int(S * 0.06)  # 箱体垂直居中偏下
BOX_R = 26                       # 箱体圆角

HANDLE_HW = 46                   # 提手拱形路径半宽
HANDLE_STROKE = 26               # 提手线宽
HANDLE_ARCH = 56                 # 拱高（路径椭圆半高）

LATCH_W = 24                     # 锁扣宽
LATCH_H = 48                     # 锁扣高
RIVET_DX = 38                    # 铆钉相对箱体中心的横向偏移
RIVET_R = 7                      # 铆钉半径

GLOW_RADIUS = int(S * 0.42)      # 光晕半径
GLOW_PEAK = 46                   # 光晕峰值 alpha（约 18% × 255）
SCAN_ALPHA = 36                  # 扫描线整体 alpha（低透明度）

# 脚本位于 docs/ 下，输出仍指向项目根的 static/（向上两级再拼 static）
OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static"
)


def diagonal_gradient(size, c0, c1):
    """左上 c0 → 右下 c1 的对角线性渐变（RGB，逐像素插值）"""
    img = Image.new("RGB", (size, size))
    span = 2 * (size - 1)
    data = []
    for y in range(size):
        for x in range(size):
            t = (x + y) / span
            data.append((
                int(c0[0] + (c1[0] - c0[0]) * t),
                int(c0[1] + (c1[1] - c0[1]) * t),
                int(c0[2] + (c1[2] - c0[2]) * t),
            ))
    img.putdata(data)
    return img


def radial_glow(size, center, radius, peak, c0, c1):
    """青紫混合径向光晕（RGBA，二次衰减，峰值透明度 peak/255）"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    cx, cy = center
    span = 2 * (size - 1)
    data = []
    for y in range(size):
        dy2 = (y - cy) ** 2
        for x in range(size):
            dist = ((x - cx) ** 2 + dy2) ** 0.5
            if dist >= radius:
                data.append((0, 0, 0, 0))
                continue
            u = 1 - dist / radius
            alpha = int(peak * u * u)
            t = (x + y) / span
            data.append((
                int(c0[0] + (c1[0] - c0[0]) * t),
                int(c0[1] + (c1[1] - c0[1]) * t),
                int(c0[2] + (c1[2] - c0[2]) * t),
                alpha,
            ))
    img.putdata(data)
    return img


def build_icon():
    """在 512×512 画布上绘制完整图标，返回 RGBA 主图"""
    # ---- 遮罩：底板外轮廓 / 内轮廓 / 描边带 ----
    outer_box = [MARGIN, MARGIN, S - 1 - MARGIN, S - 1 - MARGIN]
    inner_box = [MARGIN + STROKE, MARGIN + STROKE,
                 S - 1 - MARGIN - STROKE, S - 1 - MARGIN - STROKE]
    mask_outer = Image.new("L", (S, S), 0)
    mask_inner = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask_outer).rounded_rectangle(
        outer_box, radius=RADIUS, fill=255)
    ImageDraw.Draw(mask_inner).rounded_rectangle(
        inner_box, radius=RADIUS - STROKE, fill=255)
    # 描边带 = 外轮廓 − 内轮廓
    mask_stroke = ImageChops.subtract(mask_outer, mask_inner)

    # ---- 主渐变（整幅画布对角：左上青 → 右下紫，描边与箱体共用） ----
    grad = diagonal_gradient(S, CYAN, PURPLE)

    # ---- 画布：透明底，先铺深空底色 ----
    canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    canvas.paste(DEEP, (0, 0), mask_inner)

    # ---- 氛围 1：箱体后方径向光晕（裁剪在底板内） ----
    glow = radial_glow(S, (BOX_CX, BOX_CY), GLOW_RADIUS,
                       GLOW_PEAK, CYAN, PURPLE)
    glow.putalpha(ImageChops.multiply(glow.getchannel("A"), mask_inner))
    canvas = Image.alpha_composite(canvas, glow)

    # ---- 氛围 2：顶部扫描线（低透明度 + 一小段亮青高光） ----
    scan = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(scan)
    y = int(S * 0.13)
    x0, x1 = int(S * 0.10), int(S * 0.90)
    sdraw.line([(x0, y), (x1, y)], fill=CYAN + (255,), width=2)
    sdraw.line([(x0, y), (x0 + 88, y)], fill=LIGHT_CYAN + (255,), width=2)
    scan.putalpha(scan.getchannel("A").point(lambda a: a * SCAN_ALPHA // 255))
    scan.putalpha(ImageChops.multiply(scan.getchannel("A"), mask_inner))
    canvas = Image.alpha_composite(canvas, scan)

    # ---- 主体遮罩：提手拱弧 + 箱体，一次填充同一渐变（无接缝） ----
    mask_tool = Image.new("L", (S, S), 0)
    tdraw = ImageDraw.Draw(mask_tool)
    box_top = BOX_CY - BOX_H // 2
    # 提手：路径半椭圆（180°→360° 为上半弧），线宽粗描边，底端搭在箱体顶边上
    tdraw.arc(
        [BOX_CX - HANDLE_HW, box_top - HANDLE_ARCH,
         BOX_CX + HANDLE_HW, box_top + HANDLE_ARCH],
        start=180, end=360, fill=255, width=HANDLE_STROKE,
    )
    # 箱体
    tdraw.rounded_rectangle(
        [BOX_CX - BOX_W // 2, box_top,
         BOX_CX + BOX_W // 2, box_top + BOX_H],
        radius=BOX_R, fill=255,
    )
    canvas.paste(grad, (0, 0), mask_tool)

    # ---- 锁扣：箱体正中深空色挖空小竖矩形 ----
    tdraw = ImageDraw.Draw(canvas)
    tdraw.rounded_rectangle(
        [BOX_CX - LATCH_W // 2, BOX_CY - LATCH_H // 2,
         BOX_CX + LATCH_W // 2, BOX_CY + LATCH_H // 2],
        radius=6, fill=DEEP + (255,),
    )
    # ---- 铆钉：锁扣两侧浅青小圆点 ----
    for sign in (-1, 1):
        rx = BOX_CX + sign * RIVET_DX
        tdraw.ellipse(
            [rx - RIVET_R, BOX_CY - RIVET_R,
             rx + RIVET_R, BOX_CY + RIVET_R],
            fill=LIGHT_CYAN + (255,),
        )

    # ---- 霓虹描边：渐变略微提亮后压在外沿描边带上 ----
    stroke_rgb = Image.blend(
        grad, Image.new("RGB", (S, S), (255, 255, 255)), 0.15)
    canvas.paste(stroke_rgb, (0, 0), mask_stroke)

    return canvas


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    master = build_icon()  # 512×512 RGBA 主图

    # 256×256 应用图标
    png_path = os.path.join(OUT_DIR, "icon.png")
    master.resize((256, 256), Image.LANCZOS).save(png_path, format="PNG")
    print(f"[OK] PNG: {png_path} (256x256)")

    # 64×64 网页小图标
    png_64 = os.path.join(OUT_DIR, "icon-64.png")
    master.resize((64, 64), Image.LANCZOS).save(png_64, format="PNG")
    print(f"[OK] PNG-64: {png_64} (64x64)")

    # favicon.ico：从主图生成 16/32/48 三档
    ico_path = os.path.join(OUT_DIR, "favicon.ico")
    master.save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48)],
    )
    print(f"[OK] ICO: {ico_path} (16/32/48)")


if __name__ == "__main__":
    main()
