"""Text-to-speech engines.

MMSEngine  - Meta MMS-TTS (VITS) models, fully offline once downloaded:
               English -> facebook/mms-tts-eng
               Tagalog -> facebook/mms-tts-tgl
MockEngine - generates simple tones; lets you test the web app without torch/models.
"""
import os
import threading
import time
from pathlib import Path

import numpy as np

from .textnorm import has_letters, normalize, split_long

MODELS = {"en": "facebook/mms-tts-eng", "tl": "facebook/mms-tts-tgl"}

# "Voices": each is a pitch factor.  The model's speaking-rate is compensated so
# the speed slider still means the same thing for every voice.
VOICES = {"standard": 1.0, "deep": 0.86, "bright": 1.16}

GAP_SENTENCE = 0.30   # seconds of silence after a sentence
GAP_SWITCH = 0.06     # seconds between language runs inside a sentence


class BaseEngine:
    name = "base"
    sample_rate = 16000

    def __init__(self):
        self.state = "loading"      # loading | ready | error
        self.error = None
        self.loaded = []

    def warmup(self):
        raise NotImplementedError

    def synthesize(self, lang, text, rate):
        raise NotImplementedError

    def info(self):
        return {"name": self.name, "state": self.state, "error": self.error,
                "loaded": list(self.loaded), "sample_rate": self.sample_rate}

    def start_warmup(self):
        def run():
            try:
                self.warmup()
                self.state = "ready"
            except Exception as exc:  # noqa: BLE001 - shown on the dashboard
                self.state = "error"
                self.error = f"{type(exc).__name__}: {exc}"
                print("[engine] warm-up failed:", self.error, flush=True)
        threading.Thread(target=run, daemon=True, name="tts-warmup").start()


class MMSEngine(BaseEngine):
    name = "MMS-TTS (offline)"
    sample_rate = 16000

    def __init__(self, cache_dir):
        super().__init__()
        self.cache_dir = str(cache_dir)
        self._models = {}
        self._lock = threading.RLock()

    def _get(self, lang):
        with self._lock:
            if lang in self._models:
                return self._models[lang]
            import torch  # noqa: WPS433 - heavy import, keep lazy
            from transformers import AutoTokenizer, VitsModel

            name = MODELS[lang]
            kw = {"cache_dir": self.cache_dir}
            try:
                tok = AutoTokenizer.from_pretrained(name, local_files_only=True, **kw)
                model = VitsModel.from_pretrained(name, local_files_only=True, **kw)
            except OSError:
                print(f"[engine] {name} not cached yet - downloading (one time, ~140 MB)...", flush=True)
                tok = AutoTokenizer.from_pretrained(name, **kw)
                model = VitsModel.from_pretrained(name, **kw)
            model.eval()
            self.sample_rate = int(model.config.sampling_rate)
            self._models[lang] = (tok, model, torch)
            self.loaded = sorted(self._models)
            print(f"[engine] loaded {name}", flush=True)
            return self._models[lang]

    def warmup(self):
        for lang in MODELS:
            self._get(lang)

    def synthesize(self, lang, text, rate):
        with self._lock:
            tok, model, torch = self._get(lang)
            inputs = tok(text, return_tensors="pt")
            if inputs["input_ids"].shape[-1] == 0:
                return np.zeros(0, dtype=np.float32)
            model.speaking_rate = float(rate)
            torch.manual_seed(555)  # same text -> same voice every time
            with torch.inference_mode():
                wave_t = model(**inputs).waveform[0]
            return wave_t.cpu().numpy().astype(np.float32)


class MockEngine(BaseEngine):
    """Tone generator for testing the UI/API without any models."""
    name = "Mock (tones only)"
    sample_rate = 16000

    def warmup(self):
        time.sleep(0.3)
        self.loaded = ["en", "tl"]

    def synthesize(self, lang, text, rate):
        dur = max(0.15, 0.065 * len(text) / max(rate, 0.1))
        t = np.linspace(0, dur, int(self.sample_rate * dur), endpoint=False)
        freq = 220.0 if lang == "en" else 330.0
        wave_a = np.sin(2 * np.pi * freq * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 6 * t))
        env = np.minimum(1, np.minimum(t, dur - t) / 0.02)
        return (wave_a * env * 0.6).astype(np.float32)


def create_engine(kind, cache_dir):
    if kind == "mock":
        return MockEngine()
    return MMSEngine(cache_dir)


def _pitch_shift(wav, factor):
    if abs(factor - 1.0) < 1e-3 or len(wav) < 2:
        return wav
    n = max(2, int(len(wav) / factor))
    return np.interp(np.linspace(0, len(wav) - 1, n), np.arange(len(wav)), wav).astype(np.float32)


def render_audio(engine, segments, voice="standard", rate=1.0, volume=1.0):
    """Synthesise all segments -> (float32 audio, sample_rate, timeline).

    timeline = [{text, lang, t0, t1}] so the UI can highlight what is being spoken.
    """
    pitch = VOICES.get(voice, 1.0)
    model_rate = float(np.clip(rate / pitch, 0.3, 2.5))
    chunks, timeline, t = [], [], 0.0
    for seg in segments:
        text = normalize(seg["text"], seg["lang"])
        parts = [engine.synthesize(seg["lang"], p, model_rate)
                 for p in split_long(text) if has_letters(p)]
        parts = [p for p in parts if len(p)]
        if not parts:
            continue
        sr = engine.sample_rate
        wav = _pitch_shift(np.concatenate(parts), pitch)
        pad = np.zeros(int(sr * (GAP_SENTENCE if seg["sentence_end"] else GAP_SWITCH)), dtype=np.float32)
        dur = len(wav) / sr
        timeline.append({"text": seg["text"], "lang": seg["lang"], "t0": round(t, 3), "t1": round(t + dur, 3)})
        chunks += [wav, pad]
        t += dur + len(pad) / sr
    if not chunks:
        raise ValueError("Nothing speakable in the text (only symbols or unsupported characters).")
    audio = np.concatenate(chunks)
    peak = float(np.abs(audio).max())
    if peak > 0:
        audio = audio / peak * 0.9
    audio = np.clip(audio * float(volume), -1.0, 1.0)
    return audio, engine.sample_rate, timeline


def write_wav(path, audio, sample_rate):
    import wave
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sample_rate))
        w.writeframes(pcm.tobytes())
