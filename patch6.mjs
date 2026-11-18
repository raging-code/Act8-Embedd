#!/usr/bin/env node
/**
 * patch6.mjs - fixes the real cause of the ~1 second dead-air / "gibberish"
 * gap right between the Tagalog and English chunks.
 *
 * I checked the actual downloaded .wav file with a spectrogram: the gap
 * itself is genuine near-silence (not noise), and the speech on either side
 * is clean, well-formed audio with no clicks or discontinuities. So nothing
 * was actually corrupted -- the model was generating an abnormally LONG
 * silent pause as part of its own output.
 *
 * Why: VITS/MMS models (facebook/mms-tts-*) predict each phoneme's DURATION
 * stochastically -- that's what config.noise_scale_duration controls
 * (default 0.8, which is not small). The code was calling
 * torch.manual_seed(555) with the SAME fixed seed before every single
 * synthesize() call. That makes output reproducible, but it also means: for
 * one particular piece of text, seed 555 can draw an unlucky, abnormally
 * long duration for one phoneme, and that outlier pause gets permanently
 * baked into the waveform for that exact text, every single time, forever.
 * That is 100% reproducible (same spot, every run) and looks exactly like a
 * code bug, but it was actually a property of the model's own stochastic
 * duration prediction landing on a bad draw for this specific sentence under
 * this specific seed -- not a cache issue, not a sample-rate issue, not a
 * pronunciation issue. No amount of patching render_audio() or the text
 * pipeline could ever have fixed this, because the bug lived inside what the
 * model itself generated for that one fixed seed + that one piece of text.
 *
 * Fix (two parts, both applied):
 *   1. Seed from a hash of the TEXT instead of a constant. Keeps results
 *      reproducible per phrase (same text -> same audio, so caching still
 *      makes sense) without pinning every single phrase in the whole app to
 *      whatever duration-noise seed 555 happens to sample.
 *   2. Lower model.noise_scale_duration from its default (0.8) to 0.3. This
 *      narrows how extreme an outlier duration draw can be in the first
 *      place -- defense in depth, independent of the seed change.
 *
 * Run from your project root (the folder with app.py):
 *   node patch6.mjs
 * Then clear the cache (same reason as before -- old audio for this exact
 * text is cached under the OLD seed's output):
 *   Remove-Item outputs\tts_*.wav, outputs\tts_*.json
 * Then stop the server (Ctrl+C), run python app.py again, and test:
 *   "Ang bilis ng internet ngayon, 100 percent stable."
 * Expect: a short, natural pause between the two languages (well under half
 * a second), not the ~1 second dead patch from before.
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
  const bak = path + ".bak6";
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
    "add hashlib import",
    `import os
import threading
import time`,
    `import hashlib
import os
import threading
import time`,
  ],
  [
    "dampen noise_scale_duration right after the model loads",
    `            model.eval()
            lang_sr = int(model.config.sampling_rate)`,
    `            model.eval()
            # Reduce stochastic-duration variance (default noise_scale_duration
            # is 0.8, which is high enough to occasionally sample a very long
            # pause for a short phrase -- this is what produced the ~1 second
            # of dead air you were hearing as "gibberish" mid-sentence). This
            # does not disable randomness, just narrows how extreme an outlier
            # duration draw can be.
            model.noise_scale_duration = 0.3
            lang_sr = int(model.config.sampling_rate)`,
  ],
  [
    "seed from the text's hash instead of a constant",
    `            model.speaking_rate = float(rate)
            torch.manual_seed(555)  # same text -> same voice every time
            with torch.inference_mode():`,
    `            model.speaking_rate = float(rate)
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
            with torch.inference_mode():`,
  ],
]);

if (anyMissed) {
  console.log("\nSome anchors were not found (see above) -- paste me minibot/engine.py and I'll give you a matching patch.");
} else {
  console.log("\nDone. Old version saved as minibot/engine.py.bak6 (delete or .gitignore it).");
}
console.log("\nIMPORTANT: clear old cached audio for this text (it was cached under the old seed):");
console.log("  Remove-Item outputs\\tts_*.wav, outputs\\tts_*.json");
console.log("\nThen stop the server (Ctrl+C), run python app.py again, and test:");
console.log('  "Ang bilis ng internet ngayon, 100 percent stable."');
