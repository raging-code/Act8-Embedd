#!/usr/bin/env node
/**
 * patch5.mjs - fixes two issues:
 *
 * 1) STALE CACHE serving old, pre-fix audio ("from cache" in the UI)
 *    app.py's /api/speak cache key was built only from the TEXT, voice,
 *    rate, volume and engine name -- nothing about the CODE VERSION. So a
 *    .wav file written by an old, buggy render_audio() hashes to the exact
 *    same key as a request made right now, after patching. The server then
 *    returns that old file straight off disk without ever re-synthesizing,
 *    and you keep hearing the same old bug forever, no matter how many times
 *    the code gets fixed. Fix: the cache key now also includes a short hash
 *    of minibot/engine.py + langdetect.py + textnorm.py, so any edit to
 *    those files invalidates every old cache entry automatically.
 *
 * 2) MockEngine.synthesize() returned a 3-tuple (wav, sr, sr) instead of a
 *    2-tuple (wav, sr) -- a bug introduced in patch4. This only affects
 *    TTS_ENGINE=mock / the automated tests, NOT the real MMS voices, but it
 *    breaks "python -m pytest" / "python -m unittest" with a confusing
 *    "too many values to unpack" error. Fixed to return the correct 2-tuple.
 *
 * Run from your project root (the folder with app.py):
 *   node patch5.mjs
 * Then DELETE OLD CACHED AUDIO (belt and suspenders -- the fingerprint fix
 * makes old entries unreachable, but clearing them keeps the folder tidy):
 *   Remove-Item outputs\tts_*.wav, outputs\tts_*.json   (PowerShell)
 * Then:
 *   Ctrl+C the server, run python app.py again, and test:
 *   "Ang bilis ng internet ngayon, 100 percent stable."
 *   It should now say "from cache" only on a genuine repeat after THIS code,
 *   never on the first request after a patch.
 */
import { readFileSync, writeFileSync, existsSync, copyFileSync } from "node:fs";

const files = ["app.py", "minibot/engine.py"];
for (const f of files) {
  if (!existsSync(f)) {
    console.error(`Missing ${f} -- run this from the project root (the folder with app.py).`);
    process.exit(1);
  }
}

function backup(path) {
  const bak = path + ".bak5";
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

// ---------------------------------------------------------------------
// app.py -- fold a code fingerprint into the cache key
// ---------------------------------------------------------------------
apply("app.py", [
  [
    "add _code_fingerprint() right after OUT_DIR is created",
    `BASE = Path(__file__).resolve().parent
OUT_DIR = BASE / "outputs"
MODEL_DIR = BASE / "models"
OUT_DIR.mkdir(exist_ok=True)`,
    `BASE = Path(__file__).resolve().parent
OUT_DIR = BASE / "outputs"
MODEL_DIR = BASE / "models"
OUT_DIR.mkdir(exist_ok=True)


def _code_fingerprint():
    """A short hash of the TTS-affecting source files.

    This is folded into the cache key below so that editing engine.py,
    langdetect.py or textnorm.py (fixing a pronunciation bug, say) invalidates
    every old cached .wav automatically. Without this, the cache key was built
    only from the TEXT + voice/rate/volume/engine-name -- none of which change
    when the code is patched. So a .wav file synthesized by an old, buggy
    version of the code would keep matching the same cache key forever, and
    the server would keep serving that stale, wrong audio off disk instead of
    ever re-synthesizing it -- even after the bug was fixed. ("from cache" in
    the UI was the tell.)
    """
    paths = [BASE / "minibot" / f for f in ("engine.py", "langdetect.py", "textnorm.py")]
    h = hashlib.sha1()
    for p in paths:
        try:
            h.update(p.read_bytes())
        except OSError:
            pass
    return h.hexdigest()[:10]


_CODE_FINGERPRINT = _code_fingerprint()`,
  ],
  [
    "cache key: include _CODE_FINGERPRINT",
    `    key = hashlib.sha1(json.dumps([segments, voice, rate, volume, engine.name]).encode()).hexdigest()[:16]`,
    `    key = hashlib.sha1(json.dumps([segments, voice, rate, volume, engine.name, _CODE_FINGERPRINT]).encode()).hexdigest()[:16]`,
  ],
]);

// ---------------------------------------------------------------------
// minibot/engine.py -- fix MockEngine's stray 3rd return value
// ---------------------------------------------------------------------
apply("minibot/engine.py", [
  [
    "MockEngine.synthesize: return exactly (wav, sample_rate)",
    `        return (wave_a * env * 0.6).astype(np.float32), self.sample_rate, self.sample_rate`,
    `        return (wave_a * env * 0.6).astype(np.float32), self.sample_rate`,
  ],
]);

if (anyMissed) {
  console.log("\nSome anchors were not found (see above) -- paste me the current file and I'll give you a matching patch.");
} else {
  console.log("\nDone. Old versions saved as *.bak5 (delete or .gitignore them).");
}
console.log("\nIMPORTANT: also clear old cached audio so nothing stale lingers:");
console.log("  Remove-Item outputs\\tts_*.wav, outputs\\tts_*.json");
console.log("\nThen stop the server (Ctrl+C), run python app.py again, and test:");
console.log('  "Ang bilis ng internet ngayon, 100 percent stable."');
