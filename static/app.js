(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const log = $("#log"), form = $("#composer"), input = $("#msg"), sendBtn = $("#send");
  const starters = $("#starters"), board = $("#board"), poster = $("#poster");
  let sessionId = null, busy = false, currentPlan = null;

  // ---------- helpers ----------
  function el(tag, attrs = {}, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else n.setAttribute(k, v);
    }
    for (const k of kids) if (k != null) n.append(k);
    return n;
  }

  // Model text is never inserted as HTML. Only **bold** is turned into <b>.
  function richText(text) {
    const frag = document.createDocumentFragment();
    String(text).split(/(\*\*[^*]+\*\*)/g).forEach((part) => {
      if (/^\*\*[^*]+\*\*$/.test(part)) frag.append(el("b", { text: part.slice(2, -2) }));
      else if (part) frag.append(document.createTextNode(part));
    });
    return frag;
  }

  const money = (n, cur) => {
    try { return new Intl.NumberFormat(undefined, { style: "currency", currency: cur, maximumFractionDigits: 0 }).format(n); }
    catch { return `${Math.round(n).toLocaleString()} ${cur}`; }
  };

  async function api(path, body) {
    const res = await fetch(path, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    let data = {};
    try { data = await res.json(); } catch { /* non-JSON error */ }
    if (!res.ok) { const e = new Error(data.error || "Something went wrong. Try again."); e.status = res.status; throw e; }
    return data;
  }

  function addMessage(role, text, opts = {}) {
    const m = el("div", { class: `msg ${role}` }, richText(text));
    if (opts.planLink) {
      const b = el("button", { class: "see-plan", type: "button", text: "See your plan" });
      b.addEventListener("click", () => board.scrollIntoView({ behavior: "smooth" }));
      m.append(el("br"), b);
    }
    log.append(m);
    log.scrollTop = log.scrollHeight;
    return m;
  }

  function showThinking() {
    const t = el("div", { class: "msg assistant thinking" }, el("i"), el("span", { text: "Thinking" }));
    log.append(t); log.scrollTop = log.scrollHeight;
    const timer = setTimeout(() => { t.lastChild.textContent = "Building your itinerary. This can take up to a minute."; }, 5000);
    return () => { clearTimeout(timer); t.remove(); };
  }

  function updateMeter(usage) {
    if (!usage) return;
    const eur = usage.cost_eur || 0;
    const txt = `AI usage in this chat: ${usage.input_tokens.toLocaleString()} tokens in, ` +
      `${usage.output_tokens.toLocaleString()} out, about €${eur < 0.01 ? eur.toFixed(4) : eur.toFixed(2)}`;
    $("#meter").textContent = txt;
    $("#meter").title = Object.entries(usage.by_model || {})
      .map(([m, v]) => `${m}: ${v.calls} calls, $${v.cost_usd.toFixed(4)}`).join("\n");
  }

  // ---------- session ----------
  async function startSession() {
    log.replaceChildren();
    currentPlan = null;
    $("#plan").hidden = true; $("#empty").hidden = false; board.classList.remove("has-plan");
    starters.hidden = false;
    $("#meter").textContent = "No AI usage yet in this chat.";
    try {
      const data = await api("/api/session");
      sessionId = data.session_id;
      addMessage("assistant", data.greeting);
    } catch (e) {
      addMessage("assistant error", e.message);
    }
  }

  async function send(text) {
    text = text.trim();
    if (!text || busy) return;
    if (!sessionId) await startSession();
    busy = true; sendBtn.disabled = true; starters.hidden = true;
    addMessage("user", text);
    input.value = ""; autosize();
    const stop = showThinking();
    try {
      const data = await api("/api/chat", { session_id: sessionId, message: text });
      stop();
      addMessage("assistant", data.reply, { planLink: !!data.plan });
      updateMeter(data.usage);
      if (data.plan) renderPlan(data.plan);
    } catch (e) {
      stop();
      if (e.status === 404) { addMessage("assistant error", e.message); sessionId = null; }
      else addMessage("assistant error", e.message);
    } finally {
      busy = false; sendBtn.disabled = false; input.focus();
    }
  }

  // ---------- the poster ----------
  const ICONS = {
    sun: '<circle cx="12" cy="12" r="4.5"/><path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8"/>',
    cloud: '<path d="M7 18h10a4 4 0 0 0 .4-8A6 6 0 0 0 6 9.5 4.3 4.3 0 0 0 7 18z"/>',
    rain: '<path d="M7 15h10a4 4 0 0 0 .4-8A6 6 0 0 0 6 6.5 4.3 4.3 0 0 0 7 15z"/><path d="M8 18l-1 3M12 18l-1 3M16 18l-1 3"/>',
    snow: '<path d="M7 15h10a4 4 0 0 0 .4-8A6 6 0 0 0 6 6.5 4.3 4.3 0 0 0 7 15z"/><path d="M8 19h.01M12 20h.01M16 19h.01"/>',
    storm: '<path d="M7 15h10a4 4 0 0 0 .4-8A6 6 0 0 0 6 6.5 4.3 4.3 0 0 0 7 15z"/><path d="M12 15l-2 4h4l-2 4"/>',
  };
  function icon(cond) {
    const c = (cond || "").toLowerCase();
    const k = /thunder/.test(c) ? "storm" : /snow/.test(c) ? "snow" : /rain|drizzle|shower/.test(c) ? "rain"
      : /cloud|overcast|fog/.test(c) ? "cloud" : "sun";
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true");
    svg.innerHTML = ICONS[k];   // constant markup only
    return svg;
  }

  function renderPlan(plan) {
    currentPlan = plan;
    const cur = plan.budget.currency;
    poster.replaceChildren();

    // hero
    const hero = el("header", { class: "hero" });
    const heroText = el("div", { class: "hero-text" },
      el("h2", { text: plan.title }),
      el("p", { text: `${plan.destination}, ${plan.duration_days} ${plan.duration_days === 1 ? "day" : "days"}` }));
    if (plan.image) {
      hero.append(el("img", { src: plan.image, alt: `Illustration of ${plan.destination}` }));
    } else {
      hero.classList.add("pending");
      hero.append(el("span", { class: "pending-note", text: "Painting your trip" }));
      illustrate(plan.id);
    }
    hero.append(heroText);
    poster.append(hero);

    const body = el("div", { class: "poster-body" });
    body.append(el("p", { class: "summary", text: plan.summary }));

    // weather
    if (plan.weather && plan.weather.days && plan.weather.days.length) {
      body.append(el("h3", { class: "section-title", text: "Weather" }));
      const grid = el("div", { class: "weather" });
      plan.weather.days.forEach((w) => {
        const d = new Date(w.date + "T12:00:00");
        const label = d.toLocaleDateString(undefined, { weekday: "short", day: "numeric" });
        const rain = w.rain_chance_pct != null ? `${w.rain_chance_pct}% rain`
          : w.rain_mm != null ? `${w.rain_mm} mm rain` : "";
        grid.append(el("div", { class: "wx", title: w.conditions },
          el("b", { text: label }), icon(w.conditions),
          el("div", { class: "temp", text: `${Math.round(w.high_c)}° / ${Math.round(w.low_c)}°` }),
          el("div", { text: rain })));
      });
      body.append(grid);
      body.append(el("p", { class: "wx-note", text: plan.weather.kind === "forecast"
        ? "Forecast from Open-Meteo." : "Typical weather: what these dates looked like last year." }));
    }

    // route
    body.append(el("h3", { class: "section-title", text: "Day by day" }));
    const route = el("ol", { class: "route" });
    plan.days.forEach((d) => {
      const acts = el("ul", { class: "acts" });
      d.activities.forEach((a) => {
        acts.append(el("li", { class: "act" },
          el("span", { class: "when", text: a.time_of_day[0].toUpperCase() + a.time_of_day.slice(1) }),
          el("span", { class: "what" }, el("b", { text: a.name }), el("span", { text: a.description })),
          el("span", { class: "cost", text: a.est_cost ? `~${money(a.est_cost, cur)}` : "Free" })));
      });
      route.append(el("li", { class: "stop" },
        el("span", { class: "marker", "aria-label": `Day ${d.day}`, text: String(d.day) }),
        el("h3", { text: d.theme }), el("p", { class: "area", text: d.area }), acts));
    });
    body.append(route);

    // budget
    body.append(el("h3", { class: "section-title", text: "Estimated budget" }));
    const max = Math.max(...plan.budget.items.map((i) => i.amount), 1);
    const budget = el("div", { class: "budget", role: "table", "aria-label": "Budget by category" });
    plan.budget.items.forEach((i) => {
      const bar = el("div", { class: "bar", title: `${i.category}: ${money(i.amount, cur)}. ${i.note}` });
      bar.style.width = `${(i.amount / max) * 100}%`;
      budget.append(el("div", { class: "bar-row", role: "row" },
        el("span", { class: "cat", role: "cell", text: i.category }),
        el("div", { class: "bar-track", role: "cell" }, bar),
        el("span", { class: "amt", role: "cell", text: money(i.amount, cur) })));
    });
    budget.append(el("div", { class: "total" }, el("span", { text: "Total" }),
      el("strong", { text: money(plan.budget.total, cur) })));
    body.append(budget, el("p", { class: "basis", text: `${plan.budget.basis}. All prices are estimates.` }));

    // tips
    body.append(el("h3", { class: "section-title", text: "Good to know" }));
    const tips = el("ul", { class: "tips" });
    plan.tips.forEach((t) => tips.append(el("li", {}, richText(t))));
    body.append(tips);
    body.append(el("p", { class: "footnote", text: "Planned with Atlas. Check opening hours and prices before you go." }));
    poster.append(body);

    $("#saveMd").href = `/api/plan/${encodeURIComponent(sessionId)}/${encodeURIComponent(plan.id)}.md`;
    $("#empty").hidden = true; $("#plan").hidden = false; board.classList.add("has-plan");
    board.scrollTop = 0;
  }

  async function illustrate(planId) {
    try {
      const data = await api("/api/illustrate", { session_id: sessionId, plan_id: planId });
      updateMeter(data.usage);
      if (!currentPlan || currentPlan.id !== planId) return;
      currentPlan.image = data.image;
      const hero = poster.querySelector(".hero");
      const img = el("img", { src: data.image, alt: `Illustration of ${currentPlan.destination}` });
      img.addEventListener("load", () => { hero.classList.remove("pending"); hero.querySelector(".pending-note")?.remove(); });
      hero.prepend(img);
    } catch (e) {
      const note = poster.querySelector(".pending-note");
      if (note) note.textContent = "Illustration unavailable";
      poster.querySelector(".hero")?.classList.remove("pending");
    }
  }

  async function savePng() {
    if (!window.htmlToImage || !currentPlan) return;
    const btn = $("#savePng"); btn.disabled = true; btn.textContent = "Saving";
    try {
      const bg = getComputedStyle(document.body).backgroundColor;
      const url = await window.htmlToImage.toPng(poster, { pixelRatio: 2, backgroundColor: bg, cacheBust: false });
      const a = el("a", { href: url, download: (currentPlan.title || "trip").replace(/[^\w]+/g, "-").toLowerCase() + ".png" });
      document.body.append(a); a.click(); a.remove();
      btn.textContent = "Saved";
    } catch {
      btn.textContent = "Couldn't save image";
    } finally {
      setTimeout(() => { btn.textContent = "Save as image"; btn.disabled = false; }, 1800);
    }
  }

  // ---------- wiring ----------
  function autosize() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 160) + "px"; }
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input.value); }
  });
  form.addEventListener("submit", (e) => { e.preventDefault(); send(input.value); });
  starters.addEventListener("click", (e) => { if (e.target.tagName === "BUTTON") send(e.target.textContent); });
  $("#newTrip").addEventListener("click", () => { if (!busy) startSession(); });
  $("#savePng").addEventListener("click", savePng);
  startSession();
})();
