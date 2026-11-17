"""Bad-word detector (English + Tagalog) used to trigger the buzzer."""
import re
from pathlib import Path

_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "@": "a", "$": "s", "!": "i"})


class BadWordFilter:
    def __init__(self, path):
        self.path = Path(path)
        self.phrases = []
        self._regex = None
        self.reload()

    def reload(self):
        phrases = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip().lower()
                if line and not line.startswith("#"):
                    phrases.append(line)
        self.phrases = sorted(set(phrases), key=len, reverse=True)
        if not self.phrases:
            self._regex = None
            return
        alts = []
        for p in self.phrases:
            words = [re.escape(w) for w in p.split()]
            alts.append(r"[\s\-_.]*".join(words))
        # optional common endings so "fucking", "shits", "gagong" are caught
        self._regex = re.compile(r"(?<![a-z])(?:" + "|".join(alts) + r")(?:s|es|ed|ing|er|ers|y|ng)?(?![a-z])")

    @staticmethod
    def _normalise(text):
        return re.sub(r"(?<=[a-z])([0-9@$!])(?=[a-z])", lambda m: m.group(1).translate(_LEET), text.lower())

    def find(self, text):
        """Return a de-duplicated list of flagged words/phrases found in text."""
        if not self._regex or not text:
            return []
        norm = self._normalise(text)
        seen, out = set(), []
        for m in self._regex.finditer(norm):
            w = re.sub(r"\s+", " ", m.group(0)).strip()
            if w not in seen:
                seen.add(w)
                out.append(w)
        return out
