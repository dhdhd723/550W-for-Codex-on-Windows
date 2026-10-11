"""Generate a local launcher icon from the reference-inspired 550W outline."""
from pathlib import Path
import re
import struct

from PySide6.QtCore import QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

root = Path(__file__).resolve().parents[1]
html = (root / "web" / "index.html").read_text(encoding="utf-8")
paths = re.search(r'<g id="double-u">([\s\S]*?)</g>', html).group(1)
glyph_renderer = QSvgRenderer(('<svg xmlns="http://www.w3.org/2000/svg"><g id="glyph">' + paths + '</g></svg>').encode())
offset_x = 115 - glyph_renderer.boundsOnElement('glyph').center().x()
svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 230 230">'
       '<rect width="230" height="230" rx="24" fill="#050403"/>'
       '<rect x="10" y="10" width="210" height="210" rx="16" stroke="#805820" fill="none"/>'
       f'<g transform="translate({offset_x:g},0)" fill="#e8a020">' + paths + '</g></svg>')
assets = root / "assets"
assets.mkdir(exist_ok=True)
(assets / "launcher.svg").write_text(svg, encoding="utf-8")
renderer = QSvgRenderer(svg.encode())
pngs = []
sizes = (16, 24, 32, 48, 64, 128, 256)
for size in sizes:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    pngs.append(bytes(buffer.data()))
    if size == 256:
        image.save(str(assets / "launcher.png"))
offset = 6 + 16 * len(sizes)
entries = []
for size, png in zip(sizes, pngs):
    entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), offset))
    offset += len(png)
(assets / "launcher.ico").write_bytes(struct.pack("<HHH", 0, 1, len(sizes)) + b"".join(entries) + b"".join(pngs))
print("Generated launcher.ico from the adapted 550W outline")
