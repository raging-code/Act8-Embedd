"""Activity 8 - Multilingual Text-to-Speech Mini-Bot (Flask backend).

Run:   python app.py            -> http://localhost:5000
Mock:  TTS_ENGINE=mock python app.py   (no torch / models needed, plays tones)
"""
import collections
import hashlib
import json
import os
import platform
import threading
import time
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_from_directory

from minibot.badwords import BadWordFilter
from minibot.buzzer import Buzzer
from minibot.engine import VOICES, create_engine, render_audio, write_wav
from minibot.gibberish import find_gibberish
from minibot.langdetect import segment_text, word_counts
from minibot.player import DevicePlayer

BASE = Path(__file__).resolve().parent
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


_CODE_FINGERPRINT = _code_fingerprint()

MAX_CHARS = int(os.environ.get("MAX_CHARS", 600))
KEEP_FILES = 60

app = Flask(__name__)
engine = create_engine(os.environ.get("TTS_ENGINE", "mms").lower(), MODEL_DIR)
buzzer = Buzzer(int(os.environ.get("BUZZER_PIN", 18)))
player = DevicePlayer()
badwords = BadWordFilter(BASE / "data" / "badwords.txt")

_started = time.time()
_stats_lock = threading.Lock()
stats = {"requests": 0, "flagged": 0, "blocked": 0, "synth_ms": [], "words": {"en": 0, "tl": 0},
         "last_duration": 0.0}
history = collections.deque(maxlen=25)


def _device_model():
    try:
        return Path("/proc/device-tree/model").read_text().strip("\x00\n ")
    except OSError:
        return f"{platform.system()} {platform.machine()}"


def _clamp(value, lo, hi, default):
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return default


def _prune_outputs():
    files = sorted(OUT_DIR.glob("tts_*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[KEEP_FILES:]:
        try:
            old.unlink()
        except OSError:
            pass


@app.get("/")
def index():
    return render_template("index.html", max_chars=MAX_CHARS, voices=list(VOICES))


@app.post("/api/analyze")
def analyze():
    """Live preview while typing: language runs + flagged words (no audio)."""
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "")[:MAX_CHARS]
    mode = data.get("lang", "auto")
    segs = segment_text(text, mode if mode in ("en", "tl") else "auto")
    detected = segment_text(text, mode if mode in ("en", "tl") else "auto", smooth=False)
    flagged = badwords.find(text) + [f"{g} (gibberish)" for g in find_gibberish(text)]
    return jsonify(segments=segs, detected=detected, flagged=flagged, words=word_counts(segs))


@app.post("/api/speak")
def speak():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify(ok=False, error="Type something first."), 400
    if len(text) > MAX_CHARS:
        return jsonify(ok=False, error=f"Text too long (max {MAX_CHARS} characters)."), 400

    mode = data.get("lang", "auto")
    mode = mode if mode in ("en", "tl") else "auto"
    voice = data.get("voice") if data.get("voice") in VOICES else "standard"
    rate = _clamp(data.get("rate"), 0.5, 1.6, 1.0)
    volume = _clamp(data.get("volume"), 0.1, 1.0, 1.0)

    flagged = badwords.find(text) + [f"{g} (gibberish)" for g in find_gibberish(text)]
    if flagged:
        buzzer.alert()
    with _stats_lock:
        stats["requests"] += 1
        stats["flagged"] += 1 if flagged else 0

    segments = segment_text(text, mode)
    counts = word_counts(segments)

    if flagged and data.get("block_flagged"):
        with _stats_lock:
            stats["blocked"] += 1
            history.appendleft({"ts": time.strftime("%H:%M:%S"), "text": text, "words": counts,
                                "flagged": flagged, "blocked": True, "url": None})
        return jsonify(ok=True, blocked=True, flagged=flagged, segments=segments, words=counts)

    key = hashlib.sha1(json.dumps([segments, voice, rate, volume, engine.name, _CODE_FINGERPRINT]).encode()).hexdigest()[:16]
    name = f"tts_{key}.wav"
    path = OUT_DIR / name
    meta = OUT_DIR / f"tts_{key}.json"

    t0 = time.perf_counter()
    cached = path.exists() and meta.exists()
    try:
        if cached:
            info = json.loads(meta.read_text())
        else:
            audio, sr, timeline = render_audio(engine, segments, voice, rate, volume)
            write_wav(path, audio, sr)
            info = {"timeline": timeline, "duration": round(len(audio) / sr, 2)}
            meta.write_text(json.dumps(info))
            _prune_outputs()
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 422
    except Exception as exc:  # noqa: BLE001 - surface model/loading errors in the UI
        app.logger.exception("synthesis failed")
        return jsonify(ok=False, error=f"{type(exc).__name__}: {exc}"), 500
    synth_ms = int((time.perf_counter() - t0) * 1000)

    played = False
    if data.get("play_device"):
        played = player.play(path)

    with _stats_lock:
        if not cached:
            stats["synth_ms"].append(synth_ms)
            stats["synth_ms"] = stats["synth_ms"][-50:]
        stats["words"]["en"] += counts["en"]
        stats["words"]["tl"] += counts["tl"]
        stats["last_duration"] = info["duration"]
        history.appendleft({"ts": time.strftime("%H:%M:%S"), "text": text, "words": counts,
                            "flagged": flagged, "blocked": False, "url": f"/audio/{name}",
                            "duration": info["duration"]})

    return jsonify(ok=True, blocked=False, url=f"/audio/{name}", duration=info["duration"],
                   timeline=info["timeline"], flagged=flagged, words=counts,
                   synth_ms=synth_ms, cached=cached, played_on_device=played)


@app.get("/audio/<name>")
def audio(name):
    if not (name.startswith("tts_") and name.endswith(".wav")):
        abort(404)
    dl = request.args.get("download") == "1"
    return send_from_directory(OUT_DIR, name, mimetype="audio/wav", as_attachment=dl,
                               download_name="minibot-speech.wav" if dl else None)


@app.post("/api/stop")
def stop():
    player.stop()
    return jsonify(ok=True)


@app.post("/api/buzzer/test")
def buzzer_test():
    buzzer.alert(beeps=2)
    return jsonify(ok=True, buzzer=buzzer.info())


@app.post("/api/badwords/reload")
def badwords_reload():
    badwords.reload()
    return jsonify(ok=True, count=len(badwords.phrases))


@app.post("/api/history/clear")
def history_clear():
    with _stats_lock:
        history.clear()
    return jsonify(ok=True)


@app.get("/api/status")
def status():
    with _stats_lock:
        ms = stats["synth_ms"]
        payload = {
            "engine": engine.info(),
            "device": {"model": _device_model(), "python": platform.python_version()},
            "buzzer": buzzer.info(),
            "player": player.info(),
            "stats": {"requests": stats["requests"], "flagged": stats["flagged"],
                      "blocked": stats["blocked"], "avg_synth_ms": int(sum(ms) / len(ms)) if ms else None,
                      "words": dict(stats["words"]), "last_duration": stats["last_duration"]},
            "badwords": len(badwords.phrases),
            "uptime": int(time.time() - _started),
            "history": list(history),
        }
    return jsonify(payload)


if __name__ == "__main__":
    engine.start_warmup()
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  Mini-Bot ready ->  http://localhost:{port}   (engine: {engine.name}, buzzer: {buzzer.mode})\n")
    try:
        app.run(host=host, port=port, threaded=True, debug=False)
    finally:
        buzzer.close()
