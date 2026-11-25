import os
import sys
import unittest
from pathlib import Path

os.environ["TTS_ENGINE"] = "mock"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from minibot.gibberish import find_gibberish  # noqa: E402


class Gibberish(unittest.TestCase):
    def test_mash_is_flagged(self):
        self.assertEqual(find_gibberish("askjdhkj ahsjkdhkjahsdah"), ["askjdhkj", "ahsjkdhkjahsdah"])
        for w in ("qwerty", "asdfgh", "hjkl", "kdjfhskdjf", "xzcvb"):
            self.assertEqual(find_gibberish(w), [w], w)

    def test_real_text_passes(self):
        for ok in ("Kahapon pumunta kami sa mall para mag-shopping, tapos nag-lunch kami sa isang restaurant.",
                   "Hello po, good morning. Pwede mo bang buksan ang door?",
                   "Ang ganda ng weather, punta tayo sa Baguio at Burnham Park.",
                   "Raspberry Pi, Mini-Bot, Carlo, hmm, shh, wifi 2026"):
            self.assertEqual(find_gibberish(ok), [], ok)


if __name__ == "__main__":
    unittest.main()
