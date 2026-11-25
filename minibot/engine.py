"""Text-to-speech engines.

MMSEngine  - Meta MMS-TTS (VITS) models, fully offline once downloaded:
               English -> facebook/mms-tts-eng
               Tagalog -> facebook/mms-tts-tgl
MockEngine - generates simple tones; lets you test the web app without torch/models.
"""
import hashlib
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

# Every chunk is trimmed of the silence MMS/VITS puts at its start and end, so these
# gaps are the ONLY pauses between chunks (previously the model's own edge silence
# stacked on top of them, which is what sounded like long pauses at language switches).
GAP_SENTENCE = 0.30   # seconds of silence after a sentence
GAP_SWITCH = 0.04     # seconds between language runs inside a sentence
GAP_PART = 0.10       # seconds between pieces of one long run (split at commas)


def compress_gaps(wav, sr, max_gap=0.18, thresh_db=-40.0, win=0.01):
    """Shorten silences longer than max_gap (seconds) INSIDE a waveform to max_gap.
    MMS/VITS sometimes samples a ~1s pause at a word boundary; this removes it.
    Leading and trailing silence are left untouched."""
    if len(wav) < sr // 10:
        return wav
    h = max(1, int(sr * win))
    n = len(wav) // h
    if n < 3:
        return wav
    env = np.sqrt((wav[: n * h].reshape(n, h) ** 2).mean(axis=1))
    peak = float(env.max())
    if peak <= 0:
        return wav
    quiet = env < peak * (10 ** (thresh_db / 20.0))
    voiced = np.flatnonzero(~quiet)
    if len(voiced) == 0:
        return wav
    first, last = int(voiced[0]), int(voiced[-1])
    keep = int(max_gap / win)
    out, i = [wav[: first * h]], first
    while i <= last:
        j = i
        while j <= last and quiet[j] == quiet[i]:
            j += 1
        seg = wav[i * h : j * h]
        if quiet[i] and (j - i) > keep:
            half = keep * h // 2
            seg = np.concatenate([seg[:half], seg[-half:]])
        out.append(seg)
        i = j
    out.append(wav[(last + 1) * h :])
    return np.concatenate(out).astype(np.float32)



def trim_edges(wav, sr, thresh_db=-40.0, win=0.01, pad=0.02, fade=0.008):
    """Cut leading/trailing near-silence (keeping `pad` seconds) and add a tiny
    fade in/out so joined chunks don't click."""
    if len(wav) < sr // 20:
        return wav
    h = max(1, int(sr * win))
    n = len(wav) // h
    if n < 2:
        return wav
    env = np.sqrt((wav[: n * h].reshape(n, h) ** 2).mean(axis=1))
    peak = float(env.max())
    if peak <= 0:
        return wav
    voiced = np.flatnonzero(env >= peak * (10 ** (thresh_db / 20.0)))
    if len(voiced) == 0:
        return wav
    a = max(0, int(voiced[0]) * h - int(pad * sr))
    b = min(len(wav), (int(voiced[-1]) + 1) * h + int(pad * sr))
    out = wav[a:b].astype(np.float32).copy()
    f = min(int(fade * sr), len(out) // 2)
    if f > 1:
        ramp = np.linspace(0.0, 1.0, f, dtype=np.float32)
        out[:f] *= ramp
        out[-f:] *= ramp[::-1]
    return out


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
            # Reduce stochastic-duration variance (default noise_scale_duration
            # is 0.8, which is high enough to occasionally sample a very long
            # pause for a short phrase -- this is what produced the ~1 second
            # of dead air you were hearing as "gibberish" mid-sentence). This
            # does not disable randomness, just narrows how extreme an outlier
            # duration draw can be.
            model.noise_scale_duration = 0.1
            lang_sr = int(model.config.sampling_rate)
            # NOTE: self.sample_rate is only a "last loaded language" default
            # (used by warmup()/info() before anything has been synthesized).
            # It must NEVER be read inside render_audio() to interpret a
            # specific segment's waveform -- each language can have its own
            # native rate, and overwriting one shared attribute here caused
            # exactly that bug: whichever language's model loaded LAST would
            # silently decide the playback rate for EVERY segment, including
            # ones synthesized by the other language's model. That mismatch
            # is what produced the garbled audio right at the seam between
            # the Tagalog and English chunks.
            self.sample_rate = lang_sr
            self._models[lang] = (tok, model, torch, lang_sr)
            self.loaded = sorted(self._models)
            print(f"[engine] loaded {name} (sample_rate={lang_sr})", flush=True)
            return self._models[lang]

    def warmup(self):
        for lang in MODELS:
            self._get(lang)

    def synthesize(self, lang, text, rate):
        with self._lock:
            tok, model, torch, lang_sr = self._get(lang)
            inputs = tok(text, return_tensors="pt")
            if inputs["input_ids"].shape[-1] == 0:
                return np.zeros(0, dtype=np.float32), lang_sr
            model.speaking_rate = float(rate)
            # VITS/MMS predicts each phoneme's DURATION stochastically (that's
            # what config.noise_scale_duration controls, default 0.8 -- not a
            # small amount of randomness). A fixed seed makes output
            # reproducible, but it also means an unlucky seed can permanently
            # "lock in" an abnormally long sampled pause for one particular
            # piece of text -- every run of that exact text gets the exact
            # same outlier silence baked into the waveform, forever, no
            # matter what surrounding code changes. That looks exactly like a
            # code bug (100% reproducible, same spot every time) but isn't
            # one. Seeding from the text itself keeps results reproducible
            # per distinct phrase while no longer pinning EVERY phrase to
            # whatever duration-noise seed-555 happens to sample.
            seed = int(hashlib.sha1(text.encode()).hexdigest(), 16) % (2**31)
            torch.manual_seed(seed)
            with torch.inference_mode():
                wave_t = model(**inputs).waveform[0]
            wave_np = wave_t.cpu().numpy().astype(np.float32)
            return trim_edges(compress_gaps(wave_np, lang_sr), lang_sr), lang_sr


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
        return (wave_a * env * 0.6).astype(np.float32), self.sample_rate


def create_engine(kind, cache_dir):
    if kind == "mock":
        return MockEngine()
    return MMSEngine(cache_dir)


def _pitch_shift(wav, factor):
    if abs(factor - 1.0) < 1e-3 or len(wav) < 2:
        return wav
    n = max(2, int(len(wav) / factor))
    return np.interp(np.linspace(0, len(wav) - 1, n), np.arange(len(wav)), wav).astype(np.float32)


def _resample(wav, from_sr, to_sr):
    """Linear-interpolation resample. Cheap, but MMS output has no high-frequency
    content near Nyquist that would make that a problem for this use case."""
    if from_sr == to_sr or len(wav) < 2:
        return wav
    n = max(2, round(len(wav) * to_sr / from_sr))
    return np.interp(np.linspace(0, len(wav) - 1, n), np.arange(len(wav)), wav).astype(np.float32)


def render_audio(engine, segments, voice="standard", rate=1.0, volume=1.0):
    """Synthesise all segments -> (float32 audio, sample_rate, timeline).

    timeline = [{text, lang, t0, t1}] so the UI can highlight what is being spoken.

    Each language's model can have its own native sample rate. Every segment's
    audio is resampled (if needed) to a single OUTPUT rate -- fixed as the
    first segment's rate -- before being concatenated. Previously the code
    read a single shared `engine.sample_rate` attribute *after all segments
    were already synthesized*, so it reflected whichever language's model
    happened to load last, and applied that one rate to the entire buffer
    regardless of what rate each chunk was actually recorded at. If the two
    models' rates ever differ, that mismatch is exactly what would produce a
    garbled-sounding discontinuity right at the seam between language runs.
    """
    pitch = VOICES.get(voice, 1.0)
    model_rate = float(np.clip(rate / pitch, 0.3, 2.5))
    chunks, timeline, t = [], [], 0.0
    out_sr = None
    for seg in segments:
        text = normalize(seg["text"], seg["lang"])
        synthesized = [engine.synthesize(seg["lang"], p, model_rate)
                       for p in split_long(text) if has_letters(p)]
        synthesized = [(w, sr) for w, sr in synthesized if len(w)]
        if not synthesized:
            continue
        if out_sr is None:
            out_sr = synthesized[0][1]  # fix the output rate from the first real chunk
        gap_part = np.zeros(int(out_sr * GAP_PART), dtype=np.float32)
        parts = []
        for k, (w, sr) in enumerate(synthesized):
            if k:
                parts.append(gap_part)
            parts.append(_resample(w, sr, out_sr))
        wav = _pitch_shift(np.concatenate(parts), pitch)
        pad = np.zeros(int(out_sr * (GAP_SENTENCE if seg["sentence_end"] else GAP_SWITCH)), dtype=np.float32)
        dur = len(wav) / out_sr
        timeline.append({"text": seg["text"], "lang": seg["lang"], "t0": round(t, 3), "t1": round(t + dur, 3)})
        chunks += [wav, pad]
        t += dur + len(pad) / out_sr
    if not chunks:
        raise ValueError("Nothing speakable in the text (only symbols or unsupported characters).")
    audio = np.concatenate(chunks)
    peak = float(np.abs(audio).max())
    if peak > 0:
        audio = audio / peak * 0.9
    audio = np.clip(audio * float(volume), -1.0, 1.0)
    return audio, out_sr, timeline


def write_wav(path, audio, sample_rate):
    import wave
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sample_rate))
        w.writeframes(pcm.tobytes())