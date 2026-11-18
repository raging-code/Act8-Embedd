#!/usr/bin/env node
/**
 * patch8.mjs - sends English loanwords such as "internet" to the ENGLISH voice.
 *
 * Diagnosis (your diagnose_tgl.py report): the 1.14s dead-air pause comes from the
 * Tagalog model reading the word "internet", identical for every seed and at
 * noise_scale_duration=0. Phrases without it were clean. "internet" is in neither
 * word list, so it was "neutral" and inherited Tagalog from the word before it, which
 * is why the bad audio always appears right after Tagalog words.
 * The Tagalog model was never trained on English words, so give those to the English one.
 *
 * Add more words to the list below any time you hear the same problem.
 * Run from project root:  node patch8.mjs
 * Then:  Remove-Item outputs\tts_*.wav, outputs\tts_*.json   and restart python app.py
 */
import { readFileSync, writeFileSync, existsSync, copyFileSync } from "node:fs";
const f = "minibot/langdetect.py";
if (!existsSync(f)) { console.error("Run from the project root (minibot/langdetect.py not found)."); process.exit(1); }
let s = readFileSync(f, "utf8");
if (s.includes("_EN_LOANWORDS")) { console.log("Already patched."); process.exit(0); }
copyFileSync(f, f + ".bak8");

const defn = `# English words Filipinos say as-is. The Tagalog MMS model garbles them (long silent
# gaps / gibberish), so they are always spoken by the English voice.
_EN_LOANWORDS = set("""
internet wifi wi-fi online offline laptop cellphone smartphone email website facebook
youtube messenger password download upload wifi router network software hardware
""".split())

`;
const a = "def _is_number_token(core):";
const b = "    if core in TL_ONLY:\n        return \"tl\"\n    if core in EN_ONLY:";
if (!s.includes(a) || !s.includes(b)) { console.error("Anchors not found; file differs from expected."); process.exit(1); }
s = s.replace(a, defn + a);
s = s.replace(b, "    if core in _EN_LOANWORDS:\n        return \"en\"\n" + b);
writeFileSync(f, s);
console.log("Patched minibot/langdetect.py (backup: langdetect.py.bak8).");
// Update the one test that encoded the old split (it expected "internet" inside the Tagalog run).
const tf = "tests/test_core.py";
if (existsSync(tf)) {
  let t = readFileSync(tf, "utf8");
  const oldExp = '[("tl", "Ang bilis ng internet ngayon,"), ("en", "100 percent stable.")]';
  const newExp = '[("tl", "Ang bilis ng"), ("en", "internet"), ("tl", "ngayon,"), ("en", "100 percent stable.")]';
  if (t.includes(oldExp)) { copyFileSync(tf, tf + ".bak8"); writeFileSync(tf, t.replace(oldExp, newExp)); console.log("Updated tests/test_core.py"); }
}

