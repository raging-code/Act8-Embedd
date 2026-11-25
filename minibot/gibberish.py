"""Gibberish detector: flags keyboard mashing like "askjdhkj ahsjkdhkjahsdah".

A word is only judged if it is NOT in the English/Tagalog word lists. Unknown words
are flagged when they have no vowels, a long run of consonants, a keyboard-row
sequence (asdf, qwert, hjkl ...) or very unlikely letter patterns (character-trigram
score built from data/en_words.txt + data/tl_words.txt).  Names such as "Carlo" or
"Raspberry" look like normal words to the trigram model, so they pass.
"""
import math
import re
from collections import Counter
from pathlib import Path

from .langdetect import EN_ONLY, TL_ONLY

TRIGRAM_LIMIT = -3.7      # lower = more tolerant. mash is about -4.3 or worse, real words about -3.2 or better
MIN_TRIGRAM_LEN = 5       # shorter unknown words are judged by the other rules only
_ALLOWED = {"hmm", "hmmm", "shh", "psst", "brr", "tsk", "pfft", "grr", "zzz", "mmm", "nth", "wifi", "tv", "ok", "okay"}
_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm")
_VOWELS = "aeiouy"
_WORD = re.compile(r"[a-zñ']+(?:-[a-zñ']+)*")


def _clean(path_name):
    path = Path(__file__).resolve().parent.parent / "data" / path_name
    try:
        return {w.strip().lower() for w in path.read_text(encoding="utf-8").splitlines()
                if w.strip() and not w.startswith("#")}
    except OSError:
        return set()


_KNOWN = set(EN_ONLY) | set(TL_ONLY) | _clean("en_words.txt") | _clean("tl_words.txt") | _ALLOWED
_TRI, _BI = Counter(), Counter()
for _w in _KNOWN:
    if re.fullmatch(r"[a-zñ]+", _w):
        _s = "^^" + _w + "$"
        for _i in range(len(_s) - 2):
            _TRI[_s[_i:_i + 3]] += 1
            _BI[_s[_i:_i + 2]] += 1


def _trigram_score(word):
    s = "^^" + word + "$"
    total = 0.0
    for i in range(len(s) - 2):
        total += math.log((_TRI[s[i:i + 3]] + 0.1) / (_BI[s[i:i + 2]] + 3.0))
    return total / (len(s) - 2)


def _keyboard_run(word, n=4):
    return any(word[i:i + n] in row or word[i:i + n][::-1] in row
               for row in _ROWS for i in range(len(word) - n + 1))


def _bad_piece(piece):
    piece = piece.strip("'")
    if len(piece) < 3 or piece in _KNOWN:
        return False
    letters = re.sub(r"[^a-zñ]", "", piece)
    if len(letters) < 3:
        return False
    if not any(c in _VOWELS for c in letters):
        return True
    if re.search(r"[^aeiouy]{5,}", letters):
        return True
    if _keyboard_run(letters):
        return True
    return len(letters) >= MIN_TRIGRAM_LEN and _trigram_score(letters) < TRIGRAM_LIMIT


def find_gibberish(text):
    """Return the unique gibberish words found in text (original spelling)."""
    out, seen = [], set()
    for m in _WORD.finditer((text or "").lower()):
        word = m.group(0)
        if word in seen:
            continue
        pieces = word.split("-")
        if word not in _KNOWN and any(_bad_piece(p) for p in pieces):
            seen.add(word)
            out.append(word)
    return out
