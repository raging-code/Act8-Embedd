#!/usr/bin/env node
/**
 * patch4.mjs - fixes a sample-rate mismatch at the seam between language
 * chunks (the "gibberish right at the Tagalog/English boundary" bug).
 *
 * Root cause: MMSEngine stored the sample rate as ONE shared attribute,
 * `self.sample_rate`, that got overwritten every time a language model was
 * loaded. render_audio() read that single attribute as if it applied to the
 * whole output buffer, when really each language's model can have its own
 * native sample rate. If facebook/mms-tts-eng and facebook/mms-tts-tgl don't
 * share exactly the same rate, whichever language's model happened to load
 * LAST silently decided the playback rate for the ENTIRE file -- including
 * chunks that were actually synthesized by the OTHER model, at a different
 * rate. Audio recorded at one rate but declared/played at another comes out
 * sped up or slowed down and pitch-shifted -- which is exactly what sounds
 * like unintelligible "gibberish," concentrated right where one language's
 * chunk meets the other's.
 *
 * Fix: synthesize() now returns (waveform, sample_rate) per call. render_audio()
 * fixes one output rate (from the first real chunk) and resamples every
 * other chunk to match it BEFORE concatenating, so every segment in the
 * final buffer is guaranteed to be internally consistent.
 *
 * Run from your project root (the folder with app.py):
 *   node patch4.mjs
 * Then:
 *   Ctrl+C the server, run python app.py again, and test:
 *   "Ang bilis ng internet ngayon, 100 percent stable."
 */
import { readFileSync, writeFileSync, existsSync, copyFileSync } from "node:fs";

const files = ["minibot/engine.py"];
for (const f of files) {
  if (!existsSync(f)) {
    console.error(`Missing ${f} -- run this from the project root (the folder with app.py).`);
    process.exit(1);
  }
}

function backup(path) {
  const bak = path + ".bak4";
  if (!existsSync(bak)) copyFileSync(path, bak);
}

let anyMissed = false;
function apply(path, edits) {
  backup(path);
  let src = readFileSync(path, "utf8");
  for (const [label, from, to] of edits) {
    if (!src.includes(from)) {
      console.error(`[${path}] could not find anchor for "${label}" -- file may already be patched, or differs from what this script expects. Paste me the file and I'll check.`);
      anyMissed = true;
      continue;
    }
    src = src.replace(from, to);
  }
  writeFileSync(path, src);
  console.log(`patched ${path}`);
}

apply("minibot/engine.py", [
  [
    "MMSEngine._get: return lang_sr alongside the model, don't rely on a shared attribute",
    `            model.eval()
            self.sample_rate = int(model.config.sampling_rate)
            self._models[lang] = (tok, model, torch)
            self.loaded = sorted(self._models)
            print(f"[engine] loaded {name}", flush=True)
            return self._models[lang]`,
    `            model.eval()
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
            return self._models[lang]`,
  ],
  [
    "MMSEngine.synthesize: return (wav, lang_sr)",
    `    def synthesize(self, lang, text, rate):
        with self._lock:
            tok, model, torch = self._get(lang)
            inputs = tok(text, return_tensors="pt")
            if inputs["input_ids"].shape[-1] == 0:
                return np.zeros(0, dtype=np.float32)
            model.speaking_rate = float(rate)
            torch.manual_seed(555)  # same text -> same voice every time
            with torch.inference_mode():
                wave_t = model(**inputs).waveform[0]
            return wave_t.cpu().numpy().astype(np.float32)`,
    `    def synthesize(self, lang, text, rate):
        with self._lock:
            tok, model, torch, lang_sr = self._get(lang)
            inputs = tok(text, return_tensors="pt")
            if inputs["input_ids"].shape[-1] == 0:
                return np.zeros(0, dtype=np.float32), lang_sr
            model.speaking_rate = float(rate)
            torch.manual_seed(555)  # same text -> same voice every time
            with torch.inference_mode():
                wave_t = model(**inputs).waveform[0]
            return wave_t.cpu().numpy().astype(np.float32), lang_sr`,
  ],
  [
    "MockEngine.synthesize: return (wav, sample_rate)",
    `    def synthesize(self, lang, text, rate):
        dur = max(0.15, 0.065 * len(text) / max(rate, 0.1))
        t = np.linspace(0, dur, int(self.sample_rate * dur), endpoint=False)
        freq = 220.0 if lang == "en" else 330.0
        wave_a = np.sin(2 * np.pi * freq * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 6 * t))
        env = np.minimum(1, np.minimum(t, dur - t) / 0.02)
        return (wave_a * env * 0.6).astype(np.float32)`,
    `    def synthesize(self, lang, text, rate):
        dur = max(0.15, 0.065 * len(text) / max(rate, 0.1))
        t = np.linspace(0, dur, int(self.sample_rate * dur), endpoint=False)
        freq = 220.0 if lang == "en" else 330.0
        wave_a = np.sin(2 * np.pi * freq * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 6 * t))
        env = np.minimum(1, np.minimum(t, dur - t) / 0.02)
        return (wave_a * env * 0.6).astype(np.float32), self.sample_rate`,
  ],
  [
    "render_audio: resample each segment to one consistent output rate before concatenating",
    `def render_audio(engine, segments, voice="standard", rate=1.0, volume=1.0):
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
    return audio, engine.sample_rate, timeline`,
    `def _resample(wav, from_sr, to_sr):
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
    read a single shared \`engine.sample_rate\` attribute *after all segments
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
        parts = [_resample(w, sr, out_sr) for w, sr in synthesized]
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
    return audio, out_sr, timeline`,
  ],
]);

if (anyMissed) {
  console.log("\nSome anchors were not found (see above) -- paste me minibot/engine.py and I'll give you a matching patch.");
} else {
  console.log("\nDone. Old version saved as minibot/engine.py.bak4 (delete or .gitignore it).");
}
console.log("Next: stop the server (Ctrl+C), run python app.py again, and test:");
console.log('  "Ang bilis ng internet ngayon, 100 percent stable."');
