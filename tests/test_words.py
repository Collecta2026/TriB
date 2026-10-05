from decimal import Decimal

from core.amount_words import amount_in_words, arabic_number, english_number


def test_arabic_numbers():
    assert arabic_number(1250) == "ألف ومائتان وخمسون"
    assert arabic_number(2000) == "ألفان"
    assert arabic_number(3000) == "ثلاثة آلاف"
    assert arabic_number(11000) == "أحد عشر ألف"
    assert arabic_number(200000) == "مائتا ألف"
    assert arabic_number(1000000) == "مليون"
    assert arabic_number(25) == "خمسة وعشرون"


def test_arabic_voucher_words():
    assert amount_in_words(Decimal("1250.50"), "EGP", "ar") == "فقط ألف ومائتان وخمسون جنيه مصري وخمسون قرش لا غير"


def test_english_voucher_words():
    assert english_number(312480) == "three hundred and twelve thousand four hundred and eighty"
    assert amount_in_words(Decimal("42500"), "USD", "en") == "Forty-two thousand five hundred US dollars only"
