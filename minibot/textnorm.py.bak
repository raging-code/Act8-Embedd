"""Text clean-up before synthesis.

MMS tokenizers silently drop digits and symbols, so numbers would be skipped.
We spell them out (English words for 'en' runs, digit-by-digit Tagalog for 'tl').
"""
import re

_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
         "fifteen sixteen seventeen eighteen nineteen").split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_SCALES = ((10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand"))
_TL_DIGITS = ["sero", "isa", "dalawa", "tatlo", "apat", "lima", "anim", "pito", "walo", "siyam", "sampu"]

_NUM = re.compile(r"\d+(?:[.,]\d+)*%?")


def int_to_en(n):
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return _ONES[n // 100] + " hundred" + (" " + int_to_en(n % 100) if n % 100 else "")
    for size, name in _SCALES:
        if n >= size:
            rest = n % size
            return int_to_en(n // size) + " " + name + (" " + int_to_en(rest) if rest else "")
    return str(n)


def _speak_number(match, lang):
    raw = match.group(0)
    pct = raw.endswith("%")
    clean = raw.rstrip("%").replace(",", "")
    if not re.fullmatch(r"\d+(\.\d+)?", clean):
        words = [(_ONES[int(d)] if lang == "en" else _TL_DIGITS[int(d)]) for d in clean if d.isdigit()]
        out = " ".join(words)
    else:
        whole, _, frac = clean.partition(".")
        if lang == "en":
            out = int_to_en(int(whole)) if len(whole) <= 12 else " ".join(_ONES[int(d)] for d in whole)
            if frac:
                out += " point " + " ".join(_ONES[int(d)] for d in frac)
        else:
            if int(whole) <= 10:
                out = _TL_DIGITS[int(whole)]
            else:
                out = " ".join(_TL_DIGITS[int(d)] for d in whole)
            if frac:
                out += " punto " + " ".join(_TL_DIGITS[int(d)] for d in frac)
    if pct:
        out += " percent" if lang == "en" else " porsyento"
    return " " + out + " "


def normalize(text, lang):
    text = text.replace("&", " and " if lang == "en" else " at ")
    text = _NUM.sub(lambda m: _speak_number(m, lang), text)
    return re.sub(r"\s+", " ", text).strip()


def has_letters(text):
    return any(c.isalpha() for c in text)


def split_long(text, limit=200):
    """Break very long runs at punctuation/space so VITS stays fast and stable."""
    text = text.strip()
    if len(text) <= limit:
        return [text] if text else []
    parts, cur = [], ""
    for piece in re.split(r"(?<=[,;:])\s+|\s+", text):
        if cur and len(cur) + len(piece) + 1 > limit:
            parts.append(cur)
            cur = piece
        else:
            cur = (cur + " " + piece).strip()
    if cur:
        parts.append(cur)
    return parts
