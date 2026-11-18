"""Text clean-up before synthesis.

MMS tokenizers silently drop digits and symbols, so numbers would be skipped.
We spell them out: English words for 'en' runs, proper Tagalog number words for 'tl' runs.
"""
import re

_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
         "fifteen sixteen seventeen eighteen nineteen").split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_SCALES = ((10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand"))

# ---- Tagalog ----
_TL_DIGITS = ["sero", "isa", "dalawa", "tatlo", "apat", "lima", "anim", "pito", "walo", "siyam", "sampu"]
_TL_TEENS = {11: "labing isa", 12: "labindalawa", 13: "labintatlo", 14: "labing apat", 15: "labinlima",
             16: "labing anim", 17: "labimpito", 18: "labingwalo", 19: "labinsiyam"}
_TL_TENS = {2: "dalawampu", 3: "tatlumpu", 4: "apatnapu", 5: "limampu", 6: "animnapu",
            7: "pitumpu", 8: "walumpu", 9: "siyamnapu"}
# number + linker used before "daan / libo / milyon / bilyon"
_TL_LINK = {1: "isang", 2: "dalawang", 3: "tatlong", 4: "apat na", 5: "limang", 6: "anim na",
            7: "pitong", 8: "walong", 9: "siyam na"}
_TL_SCALES = ((10 ** 9, "bilyon"), (10 ** 6, "milyon"), (1000, "libo"))

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


def _tl_below_100(n):
    if n <= 10:
        return _TL_DIGITS[n]
    if n < 20:
        return _TL_TEENS[n]
    tens, ones = divmod(n, 10)
    return _TL_TENS[tens] + (" at " + _TL_DIGITS[ones] if ones else "")


def _tl_multiplier(n):
    """Count before daan/libo/milyon: 'isang', 'dalawang', 'apat na' ... ('dalawampung' for 20)."""
    if n < 10:
        return _TL_LINK[n]
    if n == 10:
        return "sampung"
    return int_to_tl(n)


def int_to_tl(n):
    if n < 100:
        return _tl_below_100(n)
    if n < 1000:
        h, rest = divmod(n, 100)
        out = _TL_LINK[h] + (" raan" if h in (4, 6, 9) else " daan")
        return out + (" at " + _tl_below_100(rest) if rest else "")
    for size, name in _TL_SCALES:
        if n >= size:
            q, rest = divmod(n, size)
            out = _tl_multiplier(q) + " " + name
            if rest:
                out += " " + int_to_tl(rest) if rest >= 100 else " at " + int_to_tl(rest)
            return out
    return str(n)


def _speak_number(match, lang):
    raw = match.group(0)
    pct = raw.endswith("%")
    clean = raw.rstrip("%").replace(",", "")
    digit_words = _ONES if lang == "en" else _TL_DIGITS
    if not re.fullmatch(r"\d+(\.\d+)?", clean):
        out = " ".join(digit_words[int(d)] for d in clean if d.isdigit())
    else:
        whole, _, frac = clean.partition(".")
        spoken = lang == "en" and int_to_en or int_to_tl
        out = spoken(int(whole)) if len(whole) <= 12 else " ".join(digit_words[int(d)] for d in whole)
        if frac:
            out += (" point " if lang == "en" else " punto ") + " ".join(digit_words[int(d)] for d in frac)
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
