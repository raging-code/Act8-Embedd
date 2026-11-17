(() => {
  const $ = (s) => document.querySelector(s);
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };
  const LANG = { en: "EN", tl: "TL" };

  const ui = {
    text: $("#text"), count: $("#count"), preview: $("#preview"), voice: $("#voice"),
    rate: $("#rate"), volume: $("#volume"), msg: $("#msg"), speak: $("#speak"),
    download: $("#download"), now: $("#now"), audio: $("#player"), panel: $("#bot-panel"),
    mouth: $("#mouth"),
  };
  const state = { lang: "auto", timeline: [], alertUntil: 0 };

  async function api(path, body) {
    const res = await fetch(path, body === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    let data = {};
    try { data = await res.json(); } catch (_) { /* non-JSON error page */ }
    if (!res.ok && !data.error) data.error = `Server error (${res.status})`;
    return data;
  }
  function say(text, kind) { ui.msg.textContent = text; ui.msg.className = "msg " + (kind || ""); }

  /* ---------- inputs ---------- */
  document.querySelectorAll("#lang-seg button").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("#lang-seg button").forEach((x) => {
      x.classList.toggle("on", x === b); x.setAttribute("aria-checked", x === b);
    });
    state.lang = b.dataset.v; analyze();
  }));
  ui.rate.addEventListener("input", () => { $("#rate-o").textContent = Number(ui.rate.value).toFixed(2).replace(/0$/, "") + "×"; });
  ui.volume.addEventListener("input", () => { $("#vol-o").textContent = ui.volume.value + "%"; });
  document.querySelectorAll("[data-sample]").forEach((b) => b.addEventListener("click", () => {
    ui.text.value = b.dataset.sample; onType(); ui.text.focus();
  }));

  let timer;
  function onType() {
    ui.count.textContent = `${ui.text.value.length} / ${ui.text.maxLength}`;
    clearTimeout(timer); timer = setTimeout(analyze, 250);
  }
  ui.text.addEventListener("input", onType);
  ui.text.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") speak(); });

  async function analyze() {
    const text = ui.text.value;
    ui.preview.replaceChildren();
    if (!text.trim()) return;
    const d = await api("/api/analyze", { text, lang: state.lang });
    if (!d.segments) return;
    d.segments.forEach((s) => {
      const t = el("span", "tag " + s.lang);
      t.append(el("small", null, LANG[s.lang]), document.createTextNode(s.text));
      ui.preview.append(t);
    });
    if (d.flagged && d.flagged.length) {
      ui.preview.append(el("div", "warn", `⚠ ${d.flagged.length} flagged: ${d.flagged.join(", ")} — buzzer will sound`));
    }
  }

  /* ---------- speak ---------- */
  async function speak() {
    const text = ui.text.value.trim();
    if (!text) { say("Type something first.", "err"); return; }
    ensureAudioGraph();
    ui.speak.disabled = true; ui.speak.textContent = "Synthesizing…"; say("");
    ui.audio.pause();
    const d = await api("/api/speak", {
      text, lang: state.lang, voice: ui.voice.value,
      rate: ui.rate.value, volume: ui.volume.value / 100,
      play_device: $("#play-device").checked, block_flagged: $("#block").checked,
    }).catch((e) => ({ error: "Cannot reach the server: " + e.message }));
    ui.speak.disabled = false; ui.speak.textContent = "Speak ▸";

    if (d.flagged && d.flagged.length) triggerAlert();
    if (!d.ok) { say(d.error || "Something went wrong.", "err"); return; }
    if (d.blocked) { say(`Blocked — bad words found: ${d.flagged.join(", ")}`, "err"); refresh(); return; }

    state.timeline = d.timeline;
    renderNow(d.timeline);
    ui.download.href = d.url + "?download=1";
    ui.download.classList.remove("disabled"); ui.download.removeAttribute("aria-disabled");
    ui.audio.src = d.url;
    const bits = [`${d.duration}s of audio`, d.cached ? "from cache" : `synthesised in ${(d.synth_ms / 1000).toFixed(1)}s`];
    if (d.played_on_device) bits.push("playing on device speaker");
    say(bits.join(" · "), "ok");
    if ($("#play-browser").checked) { try { await ui.audio.play(); } catch (_) { say("Press play — the browser blocked autoplay.", "err"); } }
    refresh();
  }
  ui.speak.addEventListener("click", speak);
  $("#stop").addEventListener("click", () => { ui.audio.pause(); ui.audio.currentTime = 0; api("/api/stop", {}); });

  function renderNow(timeline) {
    ui.now.replaceChildren();
    timeline.forEach((s, i) => {
      const w = el("span", `seg-w ${s.lang}`, s.text); w.dataset.i = i;
      ui.now.append(w, document.createTextNode(" "));
    });
  }
  function highlight(t) {
    ui.now.querySelectorAll(".seg-w").forEach((w) => {
      const s = state.timeline[w.dataset.i];
      w.classList.toggle("active", s && t >= s.t0 - 0.02 && t <= s.t1 + 0.1);
    });
  }

  /* ---------- bot mouth (driven by the real audio level) ---------- */
  let actx, analyser, buf, amp = 0;
  function ensureAudioGraph() {
    if (actx) { if (actx.state === "suspended") actx.resume(); return; }
    try {
      actx = new (window.AudioContext || window.webkitAudioContext)();
      const src = actx.createMediaElementSource(ui.audio);
      analyser = actx.createAnalyser(); analyser.fftSize = 512;
      src.connect(analyser); analyser.connect(actx.destination);
      buf = new Uint8Array(analyser.fftSize);
    } catch (_) { actx = null; analyser = null; }
  }
  function frame() {
    const playing = !ui.audio.paused && !ui.audio.ended;
    let target = 0;
    if (playing) {
      if (analyser) {
        analyser.getByteTimeDomainData(buf);
        let s = 0; for (const v of buf) { const d = (v - 128) / 128; s += d * d; }
        target = Math.min(1, Math.sqrt(s / buf.length) * 4.5);
      } else target = 0.3 + 0.5 * Math.random();
      highlight(ui.audio.currentTime);
    }
    amp = amp * 0.55 + target * 0.45;
    ui.mouth.setAttribute("ry", (3 + amp * 20).toFixed(1));
    ui.mouth.setAttribute("rx", (24 - amp * 5).toFixed(1));
    ui.panel.classList.toggle("speaking", playing);
    ui.panel.classList.toggle("alert", performance.now() < state.alertUntil);
    requestAnimationFrame(frame);
  }
  ui.audio.addEventListener("ended", () => highlight(-1));
  requestAnimationFrame(frame);

  function triggerAlert() {
    state.alertUntil = performance.now() + 2500;
    const tile = $("#tile-buzz"); tile.classList.remove("alert"); void tile.offsetWidth; tile.classList.add("alert");
  }

  /* ---------- dashboard ---------- */
  function setLed(id, cls, text) { const n = $(id); n.className = "led " + cls; $(id + "-t").textContent = text; }

  function renderStatus(s) {
    const e = s.engine;
    if (e.state === "ready") setLed("#led-engine", "ok", "ready");
    else if (e.state === "error") setLed("#led-engine", "err", "error");
    else setLed("#led-engine", "wait", `loading (${e.loaded.length}/2)`);
    setLed("#led-buzzer", s.buzzer.mode === "gpio" ? "ok" : "sim", s.buzzer.mode === "gpio" ? `GPIO${s.buzzer.pin}` : "simulated");
    setLed("#led-speaker", s.player.backend ? "ok" : "sim", s.player.backend || "browser only");

    $("#t-req").textContent = s.stats.requests;
    $("#t-flag").textContent = s.stats.flagged;
    $("#t-ms").textContent = s.stats.avg_synth_ms == null ? "–" : (s.stats.avg_synth_ms / 1000).toFixed(1) + "s";
    $("#t-buzz").textContent = s.buzzer.alerts;
    if (s.buzzer.last_alert_age != null && s.buzzer.last_alert_age < 3) triggerAlert();

    const w = s.stats.words, tot = w.en + w.tl;
    $("#mix-en").style.width = tot ? (w.en / tot * 100) + "%" : "0";
    $("#mix-tl").style.width = tot ? (w.tl / tot * 100) + "%" : "0";
    $("#mix-t").textContent = tot ? `${w.en} EN · ${w.tl} TL` : "–";

    $("#s-dev").textContent = s.device.model;
    $("#s-eng").textContent = e.error ? `${e.name} — ${e.error}` : `${e.name} · ${e.sample_rate / 1000} kHz`;
    $("#s-buz").textContent = s.buzzer.mode === "gpio" ? `GPIO ${s.buzzer.pin} (active)` : "simulated (no GPIO)";
    $("#s-bw").textContent = `${s.badwords} entries`;

    const list = $("#hist"); list.replaceChildren();
    if (!s.history.length) { list.append(el("li", "empty", "Nothing spoken yet.")); return; }
    s.history.forEach((h) => {
      const li = el("li");
      li.append(el("span", "ts", h.ts));
      const tx = el("span", "tx", h.text); tx.title = h.text;
      if (h.flagged && h.flagged.length) tx.append(el("span", "bd", h.blocked ? "BLOCKED" : "FLAGGED"));
      li.append(tx);
      const ops = el("span", "ops");
      if (h.url) {
        const play = el("button", null, "▶"); play.type = "button"; play.title = "Replay"; play.setAttribute("aria-label", "Replay");
        play.addEventListener("click", () => { ensureAudioGraph(); state.timeline = []; ui.now.replaceChildren(el("span", "seg-w " + (h.words.tl > h.words.en ? "tl" : "en") + " active", h.text)); ui.audio.src = h.url; ui.audio.play(); });
        const dl = el("a", "btn", "⇩"); dl.href = h.url + "?download=1"; dl.title = "Download"; dl.setAttribute("aria-label", "Download");
        ops.append(play, dl);
      }
      li.append(ops); list.append(li);
    });
  }

  async function refresh() {
    try { renderStatus(await (await fetch("/api/status")).json()); }
    catch (_) { setLed("#led-engine", "err", "server offline"); }
  }
  $("#buzz-test").addEventListener("click", async () => { await api("/api/buzzer/test", {}); triggerAlert(); refresh(); });
  $("#clear-hist").addEventListener("click", async () => { await api("/api/history/clear", {}); refresh(); });

  refresh(); setInterval(refresh, 2000);
})();
