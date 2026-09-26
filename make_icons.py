"""Draws icon.png and icon.ico (blue app icon). Run automatically by the build."""
import os
from PIL import Image, ImageDraw


def main(folder=None):
    folder = folder or os.path.dirname(os.path.abspath(__file__))
    S = 1024
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    top, bot = (0x5b, 0x95, 0xf5), (0x2f, 0x68, 0xd8)
    for y in range(S):
        t = y / (S - 1)
        gd.line([(0, y), (S, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bot)) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((24, 24, S - 24, S - 24), radius=230, fill=255)
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    im.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(im)
    w = 92

    def dot(x, y):
        d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill="white")
    pts = [(215, 700), (420, 460), (590, 590), (815, 330)]
    d.line(pts, fill="white", width=w, joint="curve")
    d.line([(610, 330), (815, 330)], fill="white", width=w)
    d.line([(815, 330), (815, 535)], fill="white", width=w)
    for x, y in (pts[0], pts[-1], (610, 330), (815, 535)):
        dot(x, y)
    im.resize((256, 256), Image.LANCZOS).save(os.path.join(folder, "icon.png"))
    im.save(os.path.join(folder, "icon.ico"),
            sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    main()
