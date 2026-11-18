#!/usr/bin/env node
/**
 * patch7.mjs - removes the long mid-sentence dead-air pause that MMS-TTS (Tagalog)
 * puts inside ONE synthesize() call, e.g. "ang bilis ng internet ngayon".
 *
 * Measured from your two WAVs (test 1 and test 2): speech 0-1.70s, silence
 * 1.70-2.88s (1.17s), speech 2.88-3.98s. Both files are identical, there is one
 * model call, no language switch and no number. So it is the model's own
 * stochastic duration predictor drawing a huge pause for one word boundary, and
 * the text-hash seed makes that same draw repeat every time for that text.
 *
 * Fix (both applied):
 *   1. noise_scale_duration 0.3 -> 0.1 (far less room for an outlier pause).
 *   2. compress_gaps(): after each model call, any silence INSIDE the audio
 *      longer than 0.18s is cut down to 0.18s. Leading/trailing silence is kept.
 *      This is a guarantee, not a probability, so it works for any sentence.
 *      Tested on your two WAVs: 4.27s -> 3.31s, the 1.17s gap becomes ~0.18s.
 *
 * Run from project root (folder with app.py):   node patch7.mjs
 * Then clear cache:  Remove-Item outputs\tts_*.wav, outputs\tts_*.json
 * Restart python app.py and test "Ang bilis ng internet ngayon."
 */
import { readFileSync, writeFileSync, existsSync, copyFileSync } from "node:fs";

const f = "minibot/engine.py";
if (!existsSync(f)) { console.error("Run this from the project root (minibot/engine.py not found)."); process.exit(1); }
let s = readFileSync(f, "utf8");
if (s.includes("def compress_gaps")) { console.log("Already patched."); process.exit(0); }
copyFileSync(f, f + ".bak7");

const fn = `
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

`;
const anchor = "class BaseEngine:";
if (!s.includes(anchor)) { console.error("Anchor not found."); process.exit(1); }
s = s.replace(anchor, fn.trimStart() + "\n\n" + anchor);

const a = "model.noise_scale_duration = 0.3";
if (!s.includes(a)) { console.error("noise_scale_duration line not found."); process.exit(1); }
s = s.replace(a, "model.noise_scale_duration = 0.1");

const b = "return wave_t.cpu().numpy().astype(np.float32), lang_sr";
if (!s.includes(b)) { console.error("return line not found."); process.exit(1); }
s = s.replace(b, "wave_np = wave_t.cpu().numpy().astype(np.float32)\n            return compress_gaps(wave_np, lang_sr), lang_sr");

writeFileSync(f, s);
console.log("Patched minibot/engine.py (backup: engine.py.bak7). Clear outputs cache and restart.");
