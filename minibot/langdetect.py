"""Tiny rule-based English/Tagalog language tagger for code-switched ("Taglish") text.

Each word is tagged 'tl', 'en' or None (unknown/neutral).  Neutral words (names,
numbers, loanwords such as "pizza") inherit the language of the word before
them, so a sentence is split into a few clean runs instead of a choppy mess.
The runs are then synthesised with the matching MMS voice.
"""
import re
from pathlib import Path

_TL = """
ang ng mga sa na ay ako ikaw ka siya kami tayo kayo sila ito iyan iyon yan yun yung eto ayan ayun
ba po ho opo oo hindi wala mayroon pero kasi dahil para kung kapag habang naman lang lamang din rin
pa nga daw raw ko mo niya namin natin ninyo nyo nila akin iyo kanya amin atin inyo kanila ating
aming inyong kanilang ano sino saan kailan bakit paano ilan alin magkano gaano sana siguro talaga
sobra sobrang masyado medyo kaya ngayon bukas kahapon mamaya kanina lagi palagi minsan madalas
bago pagkatapos tapos salamat maraming magandang maganda umaga hapon gabi tanghali kumusta kamusta
mabuti mabuhay paalam sige tara halika halina hali heto narito nandito nandoon doon dito diyan
riyan rito roon iyong nito niyan noon ngunit subalit upang tungkol mula hanggang bawat lahat iba
ibang ilang marami konti kaunti isa dalawa tatlo apat lima anim pito walo siyam sampu unang
bahay tao araw tubig pagkain kain kumain inom uminom tulog matulog gising gusto ayaw kailangan
puwede pwede huwag wag mahal mahalin kaibigan kapatid nanay tatay kuya lola lolo anak bata babae
lalaki guro estudyante paaralan eskwela trabaho pera bayad bili bumili benta mura malaki maliit
mabilis mabagal mainit malamig masaya malungkot galit takot pagod gutom busog antok sakit ganda
guwapo pogi bagong luma mabait masama mali tama totoo totoong sabi sinabi sabihin tingin tingnan
nakita nakikita alam gawa gumawa ginawa gagawin punta pumunta pupunta uwi umuwi dumating balik
bumalik tulong tulungan tumulong salita magsalita aral mag-aral buhay mundo bansa pilipinas
pilipino tagalog ulan init lamig kape kanin ulam almusal tanghalian hapunan pasensya patawad
pakiusap paki walang wala'y gaya tulad parang tila kahit sana muna agad naman nasaan nasa
gago gaga tanga bobo ulol tarantado putangina tangina punyeta leche lintik buwisit bwisit pakyu
sino-sino kanino ninyo ikaw'y ako'y siya'y tayo'y sila'y ewan hay naku ay-naku aba oy uy
""".split()

_EN = """
the a an is are was were be been am i you he she it we they me him her us them my your his its our
their this that these those what who where when why how which and or but if then so because of to
in on at by for with from up down out over under again further not no yes do does did done have has
had will would can could should may might must shall just only very too also than as about into
through during before after above below between each few more most other some such own same here
there all any both one two three hello hi hey please thank thanks okay ok good bad great nice happy
sad love like want need know think see look come go make get take give say tell ask use find work
call try feel leave put mean keep let begin seem help talk turn start show hear play run move live
believe bring happen write provide sit stand lose pay meet include continue set learn change lead
understand watch follow stop create speak read allow add spend grow open walk win offer remember
consider appear buy wait serve die send expect build stay fall cut reach kill remain text speech
voice word words sentence language english test testing today tomorrow yesterday morning afternoon
evening night day time year people way thing man woman child world life hand part place week case
point government company number group problem fact name friend home house school food water money
mother father brother sister family computer phone project class teacher student morning really
always never sometimes maybe because thanks sorry welcome goodbye bye yeah yep nope well now
""".split()

# Words that mean something in both languages stay neutral (they inherit context).
_BOTH = {"at", "no", "may", "man", "ate", "so", "ha", "ok", "o"}
TL_ONLY = set(_TL) - set(_EN) - _BOTH
EN_ONLY = set(_EN) - set(_TL) - _BOTH


def _load_list(name):
    path = Path(__file__).resolve().parent.parent / "data" / name
    try:
        return {w.strip() for w in path.read_text(encoding="utf-8").splitlines()
                if w.strip() and not w.startswith("#")}
    except OSError:
        return set()


# Big generated lists (data/*.txt). The hand-written lists above always win on conflicts.
_gen_en, _gen_tl = _load_list("en_words.txt"), _load_list("tl_words.txt")
EN_ONLY = EN_ONLY | (_gen_en - TL_ONLY - _BOTH)
TL_ONLY = TL_ONLY | (_gen_tl - EN_ONLY - _BOTH)

_EN_CONTRACTION = {"t", "s", "re", "ve", "ll", "d", "m"}
_TL_PREFIX = re.compile(r"^(mag|nag|pag|pang|nang|ipa|ipag|paki|maki|naka|maka|taga)[a-z]{3,}$")
_TL_PREFIX_EXCLUDE = {
    "magic", "magical", "magician", "magnet", "magnetic", "magnitude", "magnificent", "magazine",
    "magnify", "magma", "magenta", "magpie", "magnate", "magnolia", "pagan", "pageant", "pagoda",
    "pagination", "makara", "nagging", "pangolin",
}
_EN_SUFFIX = re.compile(r"(ing|tion|sion|ness|ment|ful|less|able|ible|ous|ive|ly|ed|ity|ize|ise)$")
_EN_CLUSTER = re.compile(r"(th|ck|sh|wh|ough|ph|tch|oo|ee)")
_HYPHEN_TL = re.compile(r"^(mag|nag|pag|pang|nang|ka|pa)-")

_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+")
_STRIP = re.compile(r"^[^\w]+|[^\w]+$")
_CONTR = re.compile(r"^(\w+)'(\w+)$")


# Words that signal "this number is being read out in this language" even
# though the number token itself has no letters to classify on its own.
_EN_UNIT_WORDS = {"percent", "percentage", "dollars", "dollar", "kilometers",
                   "kilometer", "km", "meters", "meter", "degrees", "degree"}
_TL_UNIT_WORDS = {"porsyento", "piso", "kilometro", "metro", "digri"}


# English words Filipinos say as-is. The Tagalog MMS model garbles them (long silent
# gaps / gibberish), so they are always spoken by the English voice.
_EN_LOANWORDS = set("""
internet wifi wi-fi online offline laptop cellphone smartphone email website facebook
youtube messenger password download upload wifi router network software hardware
""".split())

def _is_number_token(core):
    return bool(core) and re.fullmatch(r"\d+(?:[.,]\d+)*%?", core) is not None


def classify_word(token):
    """Return 'tl', 'en' or None for a single whitespace-delimited token."""
    core = _STRIP.sub("", token).lower().replace("’", "'")
    if _is_number_token(core):
        return None  # numbers have no language of their own; resolved by neighbors (see _tag_sentence)
    if not core or not any(c.isalpha() for c in core):
        return None
    if core in _EN_LOANWORDS:
        return "en"
    if core in TL_ONLY:
        return "tl"
    if core in EN_ONLY:
        return "en"
    if core in _BOTH:
        return None

    m = _CONTR.match(core)
    if m:
        if classify_word(m.group(1)) == "tl":      # iba't, kaya't, ako'y ... = Tagalog
            return "tl"
        if m.group(2) in _EN_CONTRACTION:
            return "en"
        if m.group(2) == "y":
            return "tl"
        return classify_word(m.group(1))

    if "-" in core:
        if _HYPHEN_TL.match(core):
            return "tl"
        votes = {classify_word(p) for p in core.split("-") if p}
        votes.discard(None)
        return votes.pop() if len(votes) == 1 else None

    if _TL_PREFIX.match(core) and core not in _TL_PREFIX_EXCLUDE and not core.endswith(("ing", "tion", "ed")):
        return "tl"
    if len(core) >= 5 and _EN_SUFFIX.search(core):
        return "en"
    if _EN_CLUSTER.search(core):
        return "en"
    return None


def _is_number(tok):
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


# A language run shorter than this many words is too little text for VITS: it gives
# odd rhythm, mispronunciations and an audible pause at every seam. Short English
# runs inside Tagalog are therefore folded into the neighbouring Tagalog run (the
# Tagalog model reads English spellings with a natural Filipino accent). Short
# Tagalog runs are kept, because the English model mangles Tagalog words.
# Set to 1 to turn smoothing off.
MIN_EN_RUN = 3


def _is_locked(token):
    """English loanwords that must always be spoken by the English voice."""
    return _STRIP.sub("", token).lower().replace("\u2019", "'") in _EN_LOANWORDS


def _smooth_tags(tokens, tags, min_en_run=MIN_EN_RUN):
    tags = list(tags)
    if min_en_run <= 1:
        return tags
    while True:
        runs, i = [], 0
        while i < len(tags):
            j = i
            while j < len(tags) and tags[j] == tags[i]:
                j += 1
            runs.append((i, j, tags[i]))
            i = j
        if len(runs) < 2:
            return tags
        cands = [k for k, (a, b, lang) in enumerate(runs)
                 if lang == "en" and b - a < min_en_run
                 and not any(_is_locked(t) for t in tokens[a:b])]
        if not cands:
            return tags
        k = min(cands, key=lambda c: runs[c][1] - runs[c][0])
        a, b, _ = runs[k]
        nbrs = [runs[x] for x in (k - 1, k + 1) if 0 <= x < len(runs)]
        target = max(nbrs, key=lambda r: r[1] - r[0])[2]   # neighbours are always 'tl'
        for x in range(a, b):
            tags[x] = target


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
    tags = [t or first for t in tags]     # leading unknowns take the first known tag
    return _smooth_tags(tokens, tags)


def segment_text(text, mode="auto"):
    """Split text into [{'text', 'lang', 'sentence_end'}] runs.

    mode: 'auto' (per-word detection), 'en' or 'tl' (force one language).
    """
    segments = []
    fallback = "en"
    for sentence in _SENT_SPLIT.split((text or "").strip()):
        tokens = sentence.split()
        if not tokens:
            continue
        tags = _tag_sentence(tokens, mode, fallback)
        fallback = tags[-1]
        run_words, run_lang = [tokens[0]], tags[0]
        sent_runs = []
        for tok, tag in zip(tokens[1:], tags[1:]):
            if tag == run_lang:
                run_words.append(tok)
            else:
                sent_runs.append((" ".join(run_words), run_lang))
                run_words, run_lang = [tok], tag
        sent_runs.append((" ".join(run_words), run_lang))
        for i, (t, lang) in enumerate(sent_runs):
            segments.append({"text": t, "lang": lang, "sentence_end": i == len(sent_runs) - 1})
    return segments


def word_counts(segments):
    counts = {"en": 0, "tl": 0}
    for s in segments:
        counts[s["lang"]] += len(s["text"].split())
    return counts