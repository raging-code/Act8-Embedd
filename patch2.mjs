#!/usr/bin/env node
/**
 * patch2.mjs - fixes the "100 percent stable" (and similar) mis-pronunciations.
 *
 * Root cause: numbers were assigned a language by "forward fill" alone --
 * whatever language the word immediately BEFORE the number happened to be.
 * In "Ang bilis ng internet ngayon, 100 percent stable.", that put "100" in
 * the Tagalog run (because of "ngayon,") even though it's actually part of
 * the English phrase "100 percent stable.". That split the number from its
 * unit word across two different-language audio chunks.
 *
 * Fix: a number now looks at the word that follows it. If that word is a
 * known unit word ("percent"/"porsyento", "dollars", etc.) the number joins
 * THAT word's language. Otherwise it falls back to the next word's language,
 * then the previous word's language. This also fixes the corresponding unit
 * test, which had encoded the buggy behaviour as the "expected" result --
 * that's why the first patch's test suite passed while the audio was wrong.
 *
 * Run from your project root (the folder with app.py):
 *   node patch2.mjs
 * Then:
 *   Ctrl+C the server if running, then: python app.py  (or python3 on mac/linux)
 *   Test: "Ang bilis ng internet ngayon, 100 percent stable."
 */
import { readFileSync, writeFileSync, existsSync, copyFileSync } from "node:fs";

const files = ["minibot/langdetect.py", "tests/test_core.py"];
for (const f of files) {
  if (!existsSync(f)) {
    console.error(`Missing ${f} -- run this from the project root (the folder with app.py).`);
    process.exit(1);
  }
}

function backup(path) {
  const bak = path + ".bak2";
  if (!existsSync(bak)) copyFileSync(path, bak);
}

function apply(path, edits) {
  backup(path);
  let src = readFileSync(path, "utf8");
  for (const [label, from, to] of edits) {
    if (!src.includes(from)) {
      console.error(`[${path}] could not find anchor for "${label}" -- file may already be patched, or differs from what this patch expects.`);
      continue;
    }
    src = src.replace(from, to);
  }
  writeFileSync(path, src);
  console.log(`patched ${path}`);
}

// ---------------------------------------------------------------------
// minibot/langdetect.py
// ---------------------------------------------------------------------
apply("minibot/langdetect.py", [
  [
    "classify_word: recognize digit tokens as language-neutral",
    `def classify_word(token):
    """Return 'tl', 'en' or None for a single whitespace-delimited token."""
    core = _STRIP.sub("", token).lower().replace("\u2019", "'")
    if not core or not any(c.isalpha() for c in core):
        return None
    if core in TL_ONLY:`,
    `# Words that signal "this number is being read out in this language" even
# though the number token itself has no letters to classify on its own.
_EN_UNIT_WORDS = {"percent", "percentage", "dollars", "dollar", "kilometers",
                   "kilometer", "km", "meters", "meter", "degrees", "degree"}
_TL_UNIT_WORDS = {"porsyento", "piso", "kilometro", "metro", "digri"}


def _is_number_token(core):
    return bool(core) and re.fullmatch(r"\\d+(?:[.,]\\d+)*%?", core) is not None


def classify_word(token):
    """Return 'tl', 'en' or None for a single whitespace-delimited token."""
    core = _STRIP.sub("", token).lower().replace("\u2019", "'")
    if _is_number_token(core):
        return None  # numbers have no language of their own; resolved by neighbors (see _tag_sentence)
    if not core or not any(c.isalpha() for c in core):
        return None
    if core in TL_ONLY:`,
  ],
  [
    "_tag_sentence: resolve numbers from neighboring unit words before forward-fill",
    `def _tag_sentence(tokens, mode, fallback):
    if mode in ("en", "tl"):
        return [mode] * len(tokens)
    tags = [classify_word(t) for t in tokens]
    last = None
    for i, t in enumerate(tags):          # forward fill
        if t is None:
            tags[i] = last
        else:
            last = t
    first = next((t for t in tags if t), None) or fallback
    return [t or first for t in tags]     # leading unknowns take the first known tag`,
    `def _is_number(tok):
    core = _STRIP.sub("", tok).lower()
    return _is_number_token(core)


def _resolve_numbers(tokens, tags):
    """Numbers inherit from the side whose language they actually belong to.

    Preference order: (1) a unit word immediately following the number (e.g.
    "100 percent" -> 'en', "100 porsyento" -> 'tl') always wins, since that's
    the strongest signal of what the number is describing; (2) otherwise the
    tag of the next known word; (3) otherwise the tag of the previous known
    word. This avoids numbers getting stranded on the wrong side of a comma
    just because of forward-fill from an unrelated earlier word.
    """
    n = len(tokens)
    for i, tok in enumerate(tokens):
        if not _is_number(tok):
            continue
        nxt_core = _STRIP.sub("", tokens[i + 1]).lower() if i + 1 < n else ""
        if nxt_core in _EN_UNIT_WORDS:
            tags[i] = "en"
            continue
        if nxt_core in _TL_UNIT_WORDS:
            tags[i] = "tl"
            continue
        nxt_tag = tags[i + 1] if i + 1 < n else None
        prev_tag = tags[i - 1] if i > 0 else None
        tags[i] = nxt_tag or prev_tag  # may still be None; filled below
    return tags


def _tag_sentence(tokens, mode, fallback):
    if mode in ("en", "tl"):
        return [mode] * len(tokens)
    tags = [classify_word(t) for t in tokens]
    tags = _resolve_numbers(tokens, tags)
    last = None
    for i, t in enumerate(tags):          # forward fill whatever's still unknown
        if t is None:
            tags[i] = last
        else:
            last = t
    first = next((t for t in tags if t), None) or fallback
    return [t or first for t in tags]     # leading unknowns take the first known tag`,
  ],
]);

// ---------------------------------------------------------------------
// tests/test_core.py -- the old test encoded the bug as "expected"
// ---------------------------------------------------------------------
apply("tests/test_core.py", [
  [
    "test_english_words_inside_tagalog: correct expectation + two new tests",
    `    def test_english_words_inside_tagalog(self):
        self.assertEqual(runs("Ang bilis ng internet ngayon, 100 percent stable."),
                         [("tl", "Ang bilis ng internet ngayon, 100"), ("en", "percent stable.")])`,
    `    def test_english_words_inside_tagalog(self):
        # "100" describes "percent stable" (English), so the whole number+unit
        # phrase must stay in the English run -- it must NOT get stranded with
        # the Tagalog run just because it's adjacent to "ngayon,".
        self.assertEqual(runs("Ang bilis ng internet ngayon, 100 percent stable."),
                         [("tl", "Ang bilis ng internet ngayon,"), ("en", "100 percent stable.")])

    def test_number_with_tagalog_unit_word(self):
        self.assertEqual(runs("May 100 porsyentong tiyaga siya."),
                         [("tl", "May 100 porsyentong tiyaga siya.")])

    def test_number_between_tagalog_words_with_no_unit(self):
        # No unit word to arbitrate -> falls back to the next word's language.
        self.assertEqual(runs("May 50 estudyante sa classroom."),
                         [("tl", "May 50 estudyante sa"), ("en", "classroom.")])`,
  ],
]);

console.log("\nDone. Old versions saved as *.bak2 (delete or .gitignore them).");
console.log("Next: stop the server (Ctrl+C), run python app.py again, and test:");
console.log('  "Ang bilis ng internet ngayon, 100 percent stable."');
console.log("Expect ONE clean English chunk: \"100 percent stable.\" (not split across languages).");
