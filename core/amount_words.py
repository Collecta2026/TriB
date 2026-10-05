"""Amounts in words for vouchers and cheques (تفقيط), in Arabic and English.

Arabic follows the common Egyptian voucher style: "فقط ألف ومائتان وخمسون جنيه مصري وخمسون قرش لا غير".
"""
from decimal import ROUND_HALF_UP, Decimal

from .reference import CURRENCY_WORDS

# ---------- Arabic ----------
AR_ONES = ["", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة"]
AR_TEENS = ["عشرة", "أحد عشر", "اثنا عشر", "ثلاثة عشر", "أربعة عشر", "خمسة عشر", "ستة عشر", "سبعة عشر", "ثمانية عشر", "تسعة عشر"]
AR_TENS = ["", "", "عشرون", "ثلاثون", "أربعون", "خمسون", "ستون", "سبعون", "ثمانون", "تسعون"]
AR_HUNDREDS = ["", "مائة", "مائتان", "ثلاثمائة", "أربعمائة", "خمسمائة", "ستمائة", "سبعمائة", "ثمانمائة", "تسعمائة"]
# (singular, dual, plural 3-10, singular-after-11+)
AR_SCALES = [
    ("", "", "", ""),
    ("ألف", "ألفان", "آلاف", "ألف"),
    ("مليون", "مليونان", "ملايين", "مليون"),
    ("مليار", "ملياران", "مليارات", "مليار"),
]


def _ar_below_1000(n):
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(AR_HUNDREDS[hundreds])
    if rest:
        if rest < 10:
            parts.append(AR_ONES[rest])
        elif rest < 20:
            parts.append(AR_TEENS[rest - 10])
        else:
            ones, tens = rest % 10, rest // 10
            parts.append(f"{AR_ONES[ones]} و{AR_TENS[tens]}" if ones else AR_TENS[tens])
    return " و".join(parts)


def arabic_number(n):
    n = int(n)
    if n == 0:
        return "صفر"
    groups = []
    scale = 0
    while n:
        n, chunk = divmod(n, 1000)
        if chunk:
            if scale == 0:
                words = _ar_below_1000(chunk)
            else:
                single, dual, plural, many = AR_SCALES[scale]
                if chunk == 1:
                    words = single
                elif chunk == 2:
                    words = dual
                else:
                    count = _ar_below_1000(chunk)
                    if count.endswith("مائتان"):
                        count = count[: -len("مائتان")] + "مائتا"
                    words = f"{count} {plural if 3 <= chunk % 100 <= 10 else many}"
            groups.append(words)
        scale += 1
    return " و".join(reversed(groups))


# ---------- English ----------
EN_ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
           "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
EN_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
EN_SCALES = ["", "thousand", "million", "billion"]


def _en_below_1000(n):
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(f"{EN_ONES[hundreds]} hundred")
    if rest:
        if rest < 20:
            words = EN_ONES[rest]
        else:
            words = EN_TENS[rest // 10] + (f"-{EN_ONES[rest % 10]}" if rest % 10 else "")
        parts.append(("and " if hundreds else "") + words)
    return " ".join(parts)


def english_number(n):
    n = int(n)
    if n == 0:
        return "zero"
    groups = []
    scale = 0
    while n:
        n, chunk = divmod(n, 1000)
        if chunk:
            groups.append(_en_below_1000(chunk) + (f" {EN_SCALES[scale]}" if scale else ""))
        scale += 1
    return " ".join(reversed(groups))


def _split(amount, decimals):
    q = Decimal(1).scaleb(-decimals) if decimals else Decimal(1)
    amount = Decimal(amount).quantize(q, rounding=ROUND_HALF_UP)
    whole = int(amount)
    minor = int(((amount - whole) * (10 ** decimals)).to_integral_value()) if decimals else 0
    return whole, minor


def amount_in_words(amount, currency_code, lang="en", decimals=2):
    unit_en, minor_en, unit_ar, minor_ar = CURRENCY_WORDS.get(
        currency_code, (currency_code, "", currency_code, "")
    )
    whole, minor = _split(amount, decimals)
    if lang == "ar":
        text = f"فقط {arabic_number(whole)} {unit_ar}"
        if minor and minor_ar:
            text += f" و{arabic_number(minor)} {minor_ar}"
        return text + " لا غير"
    text = f"{english_number(whole)} {unit_en}"
    if minor and minor_en:
        text += f" and {english_number(minor)} {minor_en}"
    text += " only"
    return text[0].upper() + text[1:]
