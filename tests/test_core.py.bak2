"""Run:  python -m unittest discover -s tests -v     (no models or GPIO needed)"""
import os
import sys
import unittest
from pathlib import Path

os.environ["TTS_ENGINE"] = "mock"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from minibot.badwords import BadWordFilter  # noqa: E402
from minibot.langdetect import segment_text  # noqa: E402
from minibot.textnorm import normalize  # noqa: E402

BASE = Path(__file__).resolve().parent.parent


def runs(text, mode="auto"):
    return [(s["lang"], s["text"]) for s in segment_text(text, mode)]


class LangDetect(unittest.TestCase):
    def test_pure_tagalog(self):
        self.assertEqual(runs("Kumain na ako ng pizza"), [("tl", "Kumain na ako ng pizza")])

    def test_pure_english(self):
        self.assertEqual(runs("Hello, how are you today?"), [("en", "Hello, how are you today?")])

    def test_code_switch(self):
        self.assertEqual(runs("I love you mahal ko"), [("en", "I love you"), ("tl", "mahal ko")])

    def test_sentence_split(self):
        r = runs("Hello po. Kumusta ka na? I'm fine, salamat!")
        self.assertEqual([l for l, _ in r], ["en", "tl", "tl", "en", "tl"])

    def test_forced_language(self):
        self.assertEqual(runs("Hello mahal ko", "tl"), [("tl", "Hello mahal ko")])

    def test_english_words_inside_tagalog(self):
        self.assertEqual(runs("Ang bilis ng internet ngayon, 100 percent stable."),
                         [("tl", "Ang bilis ng internet ngayon, 100"), ("en", "percent stable.")])

    def test_unknown_inherits_previous(self):
        self.assertEqual(runs("Pumunta ako sa mall"), [("tl", "Pumunta ako sa mall")])


class Numbers(unittest.TestCase):
    def test_english(self):
        self.assertEqual(normalize("I have 21 apples", "en"), "I have twenty one apples")
        self.assertEqual(normalize("1,250", "en"), "one thousand two hundred fifty")
        self.assertEqual(normalize("3.14", "en"), "three point one four")
        self.assertEqual(normalize("100%", "en"), "one hundred percent")

    def test_tagalog(self):
        self.assertEqual(normalize("may 3 aso", "tl"), "may tatlo aso")
        self.assertEqual(normalize("100", "tl"), "isang daan")
        self.assertEqual(normalize("21", "tl"), "dalawampu at isa")
        self.assertEqual(normalize("2024", "tl"), "dalawang libo at dalawampu at apat")
        self.assertEqual(normalize("1,250", "tl"), "isang libo dalawang daan at limampu")
        self.assertEqual(normalize("15", "tl"), "labinlima")


class BadWords(unittest.TestCase):
    def setUp(self):
        self.f = BadWordFilter(BASE / "data" / "badwords.txt")

    def test_hits(self):
        self.assertIn("shit", self.f.find("that is shit"))
        self.assertTrue(self.f.find("Ang gago mo!"))
        self.assertTrue(self.f.find("putang ina"))
        self.assertTrue(self.f.find("f-u-c-k".replace("-", "")))
        self.assertTrue(self.f.find("sh1t"))

    def test_no_false_positives(self):
        for ok in ("The class passed the assignment", "Scunthorpe", "Magandang umaga po", "I assist you"):
            self.assertEqual(self.f.find(ok), [], ok)


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app as appmod
        cls.mod = appmod
        appmod.engine.warmup()
        appmod.engine.state = "ready"
        cls.c = appmod.app.test_client()

    def test_index_and_status(self):
        self.assertEqual(self.c.get("/").status_code, 200)
        s = self.c.get("/api/status").get_json()
        self.assertEqual(s["engine"]["state"], "ready")

    def test_speak_and_download(self):
        r = self.c.post("/api/speak", json={"text": "Kumusta, hello there 5 times", "rate": 1.2, "voice": "deep"}).get_json()
        self.assertTrue(r["ok"])
        self.assertEqual({t["lang"] for t in r["timeline"]}, {"tl", "en"})
        wav = self.c.get(r["url"])
        self.assertEqual(wav.status_code, 200)
        self.assertEqual(wav.data[:4], b"RIFF")
        self.assertIn("attachment", self.c.get(r["url"] + "?download=1").headers["Content-Disposition"])

    def test_buzzer_and_block(self):
        before = self.c.get("/api/status").get_json()["buzzer"]["alerts"]
        r = self.c.post("/api/speak", json={"text": "you are a gago", "block_flagged": True}).get_json()
        self.assertTrue(r["blocked"])
        after = self.c.get("/api/status").get_json()["buzzer"]["alerts"]
        self.assertEqual(after, before + 1)

    def test_validation(self):
        self.assertEqual(self.c.post("/api/speak", json={"text": "  "}).status_code, 400)
        self.assertEqual(self.c.post("/api/speak", json={"text": "x" * 9999}).status_code, 400)
        self.assertEqual(self.c.post("/api/speak", json={"text": "!!! ???"}).status_code, 422)
        self.assertEqual(self.c.get("/audio/../app.py").status_code, 404)


if __name__ == "__main__":
    unittest.main()
