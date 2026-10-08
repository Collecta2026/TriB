"""Code 128 (set B) barcodes as SVG, for SKU and asset labels. Any USB/Bluetooth scanner reads them."""
from html import escape

# Bar/space widths for symbol values 0-106 (106 = stop).
PATTERNS = [
    "212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212", "221213",
    "221312", "231212", "112232", "122132", "122231", "113222", "123122", "123221", "223211", "221132",
    "221231", "213212", "223112", "312131", "311222", "321122", "321221", "312212", "322112", "322211",
    "212123", "212321", "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
    "231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121", "313121", "211331",
    "231131", "213113", "213311", "213131", "311123", "311321", "331121", "312113", "312311", "332111",
    "314111", "221411", "431111", "111224", "111422", "121124", "121421", "141122", "141221", "112214",
    "112412", "122114", "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
    "111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112", "421211", "212141",
    "214121", "412121", "111143", "111341", "131141", "114113", "114311", "411113", "411311", "113141",
    "114131", "311141", "411131", "211412", "211214", "211232", "2331112",
]
START_B, STOP = 104, 106


def code128_values(text):
    values = [START_B]
    for ch in text:
        code = ord(ch)
        if code < 32 or code > 126:
            raise ValueError(f"Character not allowed in a barcode: {ch!r}")
        values.append(code - 32)
    checksum = (START_B + sum(v * i for i, v in enumerate(values[1:], start=1))) % 103
    return values + [checksum, STOP]


def svg(text, module=2, height=60, show_text=True):
    widths = "".join(PATTERNS[v] for v in code128_values(text))
    quiet = 10 * module
    x, bars = quiet, []
    for i, w in enumerate(widths):
        width = int(w) * module
        if i % 2 == 0:  # bars are on even positions, spaces on odd
            bars.append(f'<rect x="{x}" y="0" width="{width}" height="{height}"/>')
        x += width
    total = x + quiet
    label_h = 16 if show_text else 0
    label = (f'<text x="{total / 2}" y="{height + 13}" text-anchor="middle" font-family="monospace" font-size="12">'
             f"{escape(text)}</text>") if show_text else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {height + label_h}" '
            f'width="{total}" height="{height + label_h}" role="img" aria-label="{escape(text)}">'
            f'<rect width="{total}" height="{height + label_h}" fill="#fff"/><g fill="#000">{"".join(bars)}</g>{label}</svg>')
