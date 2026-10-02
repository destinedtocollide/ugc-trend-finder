"""Draws icon.png, icon.ico and splash.png (startup image). Run automatically by the build."""
import os
from PIL import Image, ImageDraw, ImageFont


def _font(names, size):
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def splash(icon, folder):
    """The image the .exe shows the instant it's opened, before the window appears."""
    W, H, S = 520, 320, 2                        # drawn at 2x, then scaled down for smooth edges
    im = Image.new("RGB", (W * S, H * S), (15, 17, 21))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W * S - 1, H * S - 1), outline=(38, 42, 51), width=2 * S)
    size = 96 * S
    ic = icon.resize((size, size), Image.LANCZOS)
    im.paste(ic, ((W * S - size) // 2, 52 * S), ic)
    bold = _font(["segoeuib.ttf", "seguisb.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"], 26 * S)
    reg = _font(["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"], 14 * S)

    def center(text, y, font, fill):
        w = d.textlength(text, font=font)
        d.text(((W * S - w) / 2, y), text, font=font, fill=fill)
    center("UGC Trend Finder", 166 * S, bold, (232, 234, 238))
    center("Starting…", 204 * S, reg, (127, 135, 149))
    bx, by, bw, bh = (W - 240) // 2 * S, 244 * S, 240 * S, 6 * S
    d.rounded_rectangle((bx, by, bx + bw, by + bh), radius=bh // 2, fill=(35, 39, 49))
    d.rounded_rectangle((bx, by, bx + int(bw * .12), by + bh), radius=bh // 2, fill=(74, 134, 240))
    im.resize((W, H), Image.LANCZOS).save(os.path.join(folder, "splash.png"))


def draw_icon(top=(0x5b, 0x95, 0xf5), bottom=(0x2f, 0x68, 0xd8), fg=(255, 255, 255), size=1024):
    """The app icon: a rounded tile with a gradient and a rising arrow. The app also calls this
    to redraw the icon in the colors of the current theme."""
    S = 1024
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / (S - 1)
        gd.line([(0, y), (S, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((24, 24, S - 24, S - 24), radius=230, fill=255)
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    im.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(im)
    w = 92
    fg = tuple(fg)

    def dot(x, y):
        d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=fg)
    pts = [(215, 700), (420, 460), (590, 590), (815, 330)]
    d.line(pts, fill=fg, width=w, joint="curve")
    d.line([(610, 330), (815, 330)], fill=fg, width=w)
    d.line([(815, 330), (815, 535)], fill=fg, width=w)
    for x, y in (pts[0], pts[-1], (610, 330), (815, 535)):
        dot(x, y)
    return im if size == S else im.resize((size, size), Image.LANCZOS)


ICO_SIZES = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)]


def main(folder=None):
    folder = folder or os.path.dirname(os.path.abspath(__file__))
    im = draw_icon()
    im.resize((256, 256), Image.LANCZOS).save(os.path.join(folder, "icon.png"))
    im.save(os.path.join(folder, "icon.ico"), sizes=ICO_SIZES)
    splash(im, folder)


if __name__ == "__main__":
    main()
