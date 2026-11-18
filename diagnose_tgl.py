"""Talks to facebook/mms-tts-tgl DIRECTLY (no Flask, no minibot code).
Run from the project root:   python diagnose_tgl.py
Writes diag_out/*.wav and prints a report. Send me the printed report + diag_out folder."""
import wave
from pathlib import Path
import numpy as np
import torch
from transformers import AutoTokenizer, VitsModel

NAME = "facebook/mms-tts-tgl"
CACHE = str(Path(__file__).resolve().parent / "models")
OUT = Path(__file__).resolve().parent / "diag_out"
OUT.mkdir(exist_ok=True)

tok = AutoTokenizer.from_pretrained(NAME, cache_dir=CACHE)
model = VitsModel.from_pretrained(NAME, cache_dir=CACHE).eval()
sr = int(model.config.sampling_rate)
print("sample rate:", sr, "| defaults: noise_scale", model.noise_scale,
      "noise_scale_duration", model.noise_scale_duration, "speaking_rate", model.speaking_rate)
print("tokenizer vocab chars:", "".join(sorted(k for k in tok.get_vocab() if len(k) == 1)))


def speech_spans(x, thr=0.01, win=0.02):
    h = int(sr * win)
    e = [np.abs(x[i:i + h]).mean() for i in range(0, len(x) - h, h)]
    spans, on = [], False
    for i, v in enumerate(e):
        if v > thr and not on:
            st, on = i, True
        if v <= thr and on:
            spans.append((round(st * win, 2), round(i * win, 2))); on = False
    if on:
        spans.append((round(st * win, 2), round(len(e) * win, 2)))
    return spans


def gaps(spans):
    return [round(b[0] - a[1], 2) for a, b in zip(spans, spans[1:])]


def run(label, text, nsd, seed, rate=1.0, noise=0.667):
    model.noise_scale_duration = nsd
    model.noise_scale = noise
    model.speaking_rate = rate
    inp = tok(text, return_tensors="pt")
    torch.manual_seed(seed)
    with torch.inference_mode():
        x = model(**inp).waveform[0].numpy().astype(np.float32)
    sp = speech_spans(x)
    longest = max(gaps(sp), default=0)
    print(f"{label:34s} dur={len(x)/sr:5.2f}s  longest_gap={longest:4.2f}s  ids={inp['input_ids'].shape[-1]}")
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(OUT / f"{label}.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm.tobytes())
    return longest


TEXT = "ang bilis ng internet ngayon"
print("\ntoken ids for", repr(TEXT), "->", tok(TEXT)["input_ids"])
print("\n== 1. same text, different seeds / noise_scale_duration (is the gap random?)")
for nsd in (0.8, 0.3, 0.1, 0.0):
    for seed in (1, 2, 3):
        run(f"nsd{nsd}_seed{seed}", TEXT, nsd, seed)

print("\n== 2. is it the word 'internet'? (tagalog spellings / other phrases)")
for i, t in enumerate(["ang bilis ng internet ngayon", "ang bilis ng internet ngayon",
                       "ang bilis ng ngayon", "ang bilis ng wifi ngayon",
                       "mabilis ang takbo ngayon", "kumain na ako ng pizza"]):
    run(f"phrase{i}", t, 0.1, 1)

print("\n== 3. is it the speaking rate?")
for r in (0.8, 1.0, 1.2):
    run(f"rate{r}", TEXT, 0.1, 1, rate=r)
print("\nDone. Files in", OUT)
