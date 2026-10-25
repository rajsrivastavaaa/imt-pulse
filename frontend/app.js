// IMT Pulse PWA: hash router + screens. No build step, no framework.
(function () {
  const C = window.PULSE_CONFIG;
  const $app = document.getElementById("app");
  const TRACKS = {
    marketing: { name: "Marketing", blurb: "Brands, FMCG, retail, D2C, media" },
    finance: { name: "Finance", blurb: "Markets, banking, IPOs, deals, RBI" },
    consulting: { name: "Consulting / Strategy", blurb: "Strategy, policy, economy, deals" },
    ops: { name: "Ops / Analytics", blurb: "Supply chain, manufacturing, tech, AI" },
  };
  const state = { me: null, lastResult: null };

  // ---------- helpers ----------
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const render = (html) => { $app.innerHTML = html; window.scrollTo(0, 0); };
  const go = (route) => { if (location.hash !== "#/" + route) location.hash = "#/" + route; else route_(); };
  const form = (el) => Object.fromEntries(new FormData(el).entries());

  function toast(msg) {
    const t = document.getElementById("toast");
    t.textContent = msg; t.hidden = false;
    clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 2600);
  }

  function ago(iso) {
    const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (m < 60) return `${Math.max(m, 1)}m ago`;
    const h = Math.round(m / 60);
    return h < 24 ? `${h}h ago` : `${Math.round(h / 24)}d ago`;
  }

  function busy(btn, on, label) {
    if (!btn) return;
    if (on) { btn.dataset.label = btn.textContent; btn.textContent = label || "Please wait…"; btn.disabled = true; }
    else { btn.textContent = btn.dataset.label || btn.textContent; btn.disabled = false; }
  }

  function showError(container, err) {
    let box = container.querySelector(".error");
    if (!box) { box = document.createElement("div"); box.className = "error"; container.appendChild(box); }
    box.textContent = err.message || String(err);
  }

  async function api(method, path, body, retried) {
    let token;
    try { token = await Auth.idToken(retried); }
    catch (e) { Auth.clear(); go("login"); throw new Error("Please sign in again."); }
    const r = await fetch(C.apiUrl + path, {
      method, headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (r.status === 401 && !retried) return api(method, path, body, true);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(data.error || data.message || `Request failed (${r.status})`); e.status = r.status; throw e; }
    return data;
  }
  window.PulseAPI = api;

  function logEvent(type, meta) { api("POST", "/events", { type, meta }).catch(() => {}); }

  function chrome(show, tab) {
    document.getElementById("topbar").hidden = !show;
    document.getElementById("tabbar").hidden = !show;
    document.body.style.paddingBottom = show ? "" : "0";
    document.querySelectorAll(".tabbar a").forEach((a) => a.classList.toggle("active", a.dataset.tab === tab));
    document.getElementById("adminTab").hidden = !(state.me && state.me.is_admin);
    const chip = document.getElementById("streakChip");
    const s = state.me ? state.me.streak : 0;
    chip.hidden = !s; chip.textContent = `🔥 ${s} day${s === 1 ? "" : "s"}`;
  }

  async function loadMe() { state.me = await api("GET", "/me"); return state.me; }

  // ---------- auth screens ----------
  function authShell(title, sub, inner) {
    chrome(false);
    render(`<div class="auth"><img class="logo" src="icons/icon-192.png" alt="">
      <h1>${title}</h1>${sub ? `<p class="muted">${sub}</p>` : ""}${inner}</div>`);
  }

  function viewLogin() {
    authShell("IMT Pulse", "Your 5-minute morning business brief and quiz for placement season.", `
      <form id="f"><label for="email">IMT email</label>
        <input id="email" name="email" type="email" autocomplete="username" placeholder="pgp25yourname@imt.ac.in" required>
        <label for="pw">Password</label>
        <input id="pw" name="password" type="password" autocomplete="current-password" required>
        <button class="btn block" type="submit">Sign in</button></form>
      <div class="links"><a href="#/signup">Create account</a><a href="#/forgot">Forgot password?</a></div>`);
    const f = document.getElementById("f");
    const saved = sessionStorage.getItem("pulse.email");
    if (saved) f.email.value = saved;
    f.onsubmit = async (ev) => {
      ev.preventDefault();
      const v = form(f), btn = f.querySelector("button");
      busy(btn, true, "Signing in…");
      try { await Auth.signIn(v.email, v.password); state.me = null; logEvent("app_open"); go("home"); }
      catch (e) {
        if (e.code === "UserNotConfirmedException") {
          sessionStorage.setItem("pulse.email", v.email.trim().toLowerCase());
          await Auth.resend(v.email).catch(() => {});
          return go("verify");
        }
        showError(f, e);
      } finally { busy(btn, false); }
    };
  }

  function viewSignup() {
    authShell("Create your account", "Only @imt.ac.in emails can join. We'll email you a code to confirm it's yours.", `
      <form id="f">
        <label for="first">First name</label><input id="first" name="first" autocomplete="given-name" required>
        <label for="last">Last name</label><input id="last" name="last" autocomplete="family-name" required>
        <label for="email">IMT email</label>
        <input id="email" name="email" type="email" autocomplete="username" placeholder="pgp25yourname@imt.ac.in" required>
        <label for="pw">Password</label>
        <input id="pw" name="password" type="password" autocomplete="new-password" minlength="8" required>
        <p class="muted small">At least 8 characters, including a number.</p>
        <button class="btn block" type="submit">Sign up</button></form>
      <div class="links"><a href="#/login">I already have an account</a></div>`);
    const f = document.getElementById("f");
    f.onsubmit = async (ev) => {
      ev.preventDefault();
      const v = form(f), btn = f.querySelector("button");
      if (!v.email.trim().toLowerCase().endsWith("@imt.ac.in")) return showError(f, new Error("Please use your @imt.ac.in email."));
      busy(btn, true, "Creating account…");
      try {
        await Auth.signUp(v.email, v.password, v.first, v.last);
        sessionStorage.setItem("pulse.email", v.email.trim().toLowerCase());
        sessionStorage.setItem("pulse.pw", v.password);   // only for auto sign-in right after verifying
        go("verify");
      } catch (e) { showError(f, e); } finally { busy(btn, false); }
    };
  }

  function viewVerify() {
    const email = sessionStorage.getItem("pulse.email");
    if (!email) return go("login");
    authShell("Check your email", `We sent a 6-digit code to <b>${esc(email)}</b>. It can take a minute, and Outlook often puts it in <b>Junk</b>.`, `
      <form id="f"><label for="code">Verification code</label>
        <input id="code" name="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" required>
        <button class="btn block" type="submit">Verify</button></form>
      <div class="links"><a href="#" id="resend">Resend code</a><a href="#/login">Back to sign in</a></div>`);
    const f = document.getElementById("f");
    document.getElementById("resend").onclick = async (ev) => {
      ev.preventDefault();
      try { await Auth.resend(email); toast("New code sent. Check Junk too."); } catch (e) { showError(f, e); }
    };
    f.onsubmit = async (ev) => {
      ev.preventDefault();
      const btn = f.querySelector("button");
      busy(btn, true, "Verifying…");
      try {
        await Auth.confirm(email, f.code.value);
        const pw = sessionStorage.getItem("pulse.pw");
        sessionStorage.removeItem("pulse.pw");
        if (pw) { await Auth.signIn(email, pw); state.me = null; logEvent("app_open"); return go("home"); }
        toast("Email verified. Please sign in."); go("login");
      } catch (e) { showError(f, e); } finally { busy(btn, false); }
    };
  }

  function viewForgot() {
    authShell("Reset password", "We'll email you a code (check Junk).", `
      <form id="f1"><label for="email">IMT email</label><input id="email" name="email" type="email" required>
        <button class="btn block" type="submit">Send code</button></form>
      <form id="f2" hidden><label for="code">Code</label><input id="code" name="code" inputmode="numeric" required>
        <label for="pw">New password</label><input id="pw" name="password" type="password" minlength="8" autocomplete="new-password" required>
        <button class="btn block" type="submit">Set new password</button></form>
      <div class="links"><a href="#/login">Back to sign in</a></div>`);
    const f1 = document.getElementById("f1"), f2 = document.getElementById("f2");
    f1.onsubmit = async (ev) => {
      ev.preventDefault(); const btn = f1.querySelector("button"); busy(btn, true);
      try { await Auth.forgot(f1.email.value); f1.hidden = true; f2.hidden = false; }
      catch (e) { showError(f1, e); } finally { busy(btn, false); }
    };
    f2.onsubmit = async (ev) => {
      ev.preventDefault(); const btn = f2.querySelector("button"); busy(btn, true);
      try { await Auth.resetPassword(f1.email.value, f2.code.value, f2.password.value); toast("Password updated. Sign in."); go("login"); }
      catch (e) { showError(f2, e); } finally { busy(btn, false); }
    };
  }

  // ---------- onboarding ----------
  function trackPicker(selected) {
    return `<div class="tracks">${Object.entries(TRACKS).map(([k, t]) =>
      `<button type="button" class="track ${k === selected ? "on" : ""}" data-track="${k}"><strong>${t.name}</strong><span>${t.blurb}</span></button>`).join("")}</div>`;
  }

  function viewOnboarding() {
    chrome(false);
    let pick = state.me.track;
    render(`<div class="auth"><h1>Welcome, ${esc(state.me.first)} 👋</h1>
      <p class="muted">Pick the track you're preparing for. You'll get 8–10 stories and a 5-question quiz for it every morning at 8:00. You can change it later.</p>
      <form id="f">${trackPicker(pick)}
        <label for="dn">Name on the leaderboard</label>
        <input id="dn" name="display_name" maxlength="30" value="${esc(state.me.display_name)}" required>
        <p class="muted small">First name + last initial by default. You can hide yourself from the leaderboard in your profile.</p>
        <button class="btn block accent" type="submit">Let's go</button></form></div>`);
    const f = document.getElementById("f");
    f.querySelectorAll(".track").forEach((b) => (b.onclick = () => {
      pick = b.dataset.track; f.querySelectorAll(".track").forEach((x) => x.classList.toggle("on", x === b));
    }));
    f.onsubmit = async (ev) => {
      ev.preventDefault();
      if (!pick) return showError(f, new Error("Pick a track first."));
      const btn = f.querySelector("button[type=submit]"); busy(btn, true);
      try { state.me = await api("PUT", "/me", { track: pick, display_name: f.display_name.value, onboarded: true }); go("home"); }
      catch (e) { showError(f, e); } finally { busy(btn, false); }
    };
  }

  // ---------- home ----------
  function quizCta(q) {
    if (!q) return "";
    const map = {
      not_started: [`Today's quiz · ${q.total} questions`, "About 2 minutes. Faster correct answers earn bonus points.", "Start"],
      in_progress: ["Finish today's quiz", `${q.answered} of ${q.total} answered`, "Resume"],
      done: [`You scored ${q.score} today`, `${q.correct}/${q.total} correct · see your rank`, "Results"],
      closed: ["Quiz closed", "Today's quiz runs 08:00–23:59 IST.", ""],
      unavailable: ["No quiz today", "Today's questions aren't ready yet.", ""],
    }[q.state];
    if (!map) return "";
    const href = q.state === "done" ? "#/results" : "#/quiz";
    return map[2] ? `<a class="cta" href="${href}"><div><strong>${map[0]}</strong><span>${map[1]}</span></div><b class="go">${map[2]}</b></a>`
      : `<div class="cta"><div><strong>${map[0]}</strong><span>${map[1]}</span></div></div>`;
  }

  function companyCard(c) {
    if (!c) return "";
    const news = (c.recent_news || []).map((n) => `<li>${esc(n.point)} <a href="${esc(n.link)}" target="_blank" rel="noopener">${esc(n.source)}</a></li>`).join("");
    return `<section class="card company"><div class="eyebrow">Company of the Day</div>
      <h2 style="margin:4px 0 2px">${esc(c.name)}</h2>
      ${c.process_date ? `<div class="muted small">On campus ${esc(new Date(c.process_date).toLocaleDateString("en-IN", { day: "numeric", month: "short" }))}</div>` : ""}
      <p>${esc(c.what_it_does)}</p>
      <details><summary>Business lines, news & talking points</summary>
        <h3>Main business lines</h3><ul class="tight">${(c.business_lines || []).map((b) => `<li>${esc(b)}</li>`).join("")}</ul>
        ${news ? `<h3>In the news</h3><ul class="tight">${news}</ul>` : ""}
        <h3>Likely interview talking points</h3><ol class="tight">${(c.talking_points || []).map((t) => `<li>${esc(t)}</li>`).join("")}</ol>
      </details>
      <p class="badge" style="margin-top:12px">AI-written brief: double-check facts before your interview</p></section>`;
  }

  function storyCard(s) {
    return `<article class="card story"><h3><a href="${esc(s.link)}" target="_blank" rel="noopener" data-story="${esc(s.id)}">${esc(s.headline)}</a></h3>
      <p>${esc(s.summary)}</p><p class="why"><b>Why it matters:</b> ${esc(s.why_it_matters)}</p>
      <div class="meta">${esc(s.source)} · ${ago(s.published)} · <a href="${esc(s.link)}" target="_blank" rel="noopener" data-story="${esc(s.id)}">Read original ↗</a></div></article>`;
  }

  async function viewHome(params) {
    chrome(true, "home");
    render(`<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>`);
    const track = params.get("track");
    const d = await api("GET", "/today" + (track ? `?track=${encodeURIComponent(track)}` : ""));
    const hour = new Date().getHours();
    const hello = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
    const dateStr = new Date(d.date).toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" });
    if (!d.published && !d.preview) {
      return render(`<p class="eyebrow">${dateStr}</p><h1>${hello}, ${esc(state.me.first)}</h1>
        <div class="card center"><h2>Today's brief lands at 8:00 AM IST</h2><p class="muted">Stories and the quiz open together. See you then!</p></div>`);
    }
    const mine = state.me.track;
    const chips = Object.entries(TRACKS).map(([k, t]) =>
      `<button class="chip ${k === d.track ? "on" : ""}" data-t="${k}">${t.name}${k === mine ? " ★" : ""}</button>`).join("");
    render(`<p class="eyebrow">${dateStr}</p><h1>${hello}, ${esc(state.me.first)}</h1>
      ${d.preview ? `<div class="note">Admin preview: students see this from 08:00 IST.</div>` : ""}
      ${quizCta(d.quiz)}
      ${companyCard(d.company)}
      <h2>Today's stories</h2><div class="chips">${chips}</div>
      ${d.track !== mine ? `<p class="muted small">Peeking at ${TRACKS[d.track].name}. Your quiz is on ${TRACKS[mine].name}.</p>` : ""}
      ${(d.stories || []).map(storyCard).join("") || `<div class="card muted">No stories for this track today.</div>`}
      <p class="muted small center" style="padding:16px">Summaries are AI-written from headlines. Tap a headline to read the original article.</p>`);
    $app.querySelectorAll(".chip").forEach((b) => (b.onclick = () => go(b.dataset.t === mine ? "home" : `home?track=${b.dataset.t}`)));
    $app.querySelectorAll("[data-story]").forEach((a) => a.addEventListener("click", () => logEvent("story_open", { id: a.dataset.story, track: d.track })));
  }

  // ---------- quiz ----------
  let timerId = null;
  function stopTimer() { clearInterval(timerId); timerId = null; }

  async function viewQuiz() {
    chrome(true, "quiz");
    stopTimer();
    render(`<div class="skeleton"></div><div class="skeleton" style="height:240px"></div>`);
    let r;
    try { r = await api("POST", "/quiz/start"); }
    catch (e) { return render(`<h1>Today's quiz</h1><div class="card"><p>${esc(e.message)}</p><a class="btn" href="#/home">Back to today</a></div>`); }
    if (r.finished) { state.lastResult = r.result; return go("results"); }
    showQuestion(r.question, r.score_so_far);
  }

  function showQuestion(q, scoreSoFar) {
    const started = Date.now();
    render(`<div class="qhead"><span>${q.kind === "company" ? "Company of the Day · " : ""}Question ${q.index + 1} of ${q.total}</span>
        <span class="timer" id="timer">0s</span></div>
      <div class="progress"><i style="width:${(q.index / q.total) * 100}%"></i></div>
      <div class="question">${esc(q.question)}</div>
      <div id="opts">${q.options.map((o, i) => `<button class="opt" data-i="${i}"><b>${"ABCD"[i]}</b><span>${esc(o)}</span></button>`).join("")}</div>
      <div id="after"></div>
      <p class="muted small" style="margin-top:16px">Score so far: ${scoreSoFar || 0} · answer within 10s for the full speed bonus</p>`);
    const $t = document.getElementById("timer");
    timerId = setInterval(() => ($t.textContent = Math.floor((Date.now() - started) / 1000) + "s"), 250);
    const buttons = [...document.querySelectorAll(".opt")];
    buttons.forEach((b) => (b.onclick = async () => {
      buttons.forEach((x) => (x.disabled = true));
      b.style.borderColor = "var(--accent)";
      stopTimer();
      let res;
      try { res = await api("POST", "/quiz/answer", { qid: q.qid, choice: Number(b.dataset.i) }); }
      catch (e) {
        if (e.status === 409) return viewQuiz();   // already answered or out of sync: resume from server state
        buttons.forEach((x) => (x.disabled = false)); return toast(e.message);
      }
      b.style.borderColor = "";
      buttons[res.answer_index].classList.add("right");
      if (!res.correct) b.classList.add("wrong");
      const after = document.getElementById("after");
      after.innerHTML = `<div class="explain"><strong class="${res.correct ? "ok" : "bad"}">${res.correct ? `Correct · +${res.points} points` : "Not quite"}</strong>
        <span class="muted small"> · ${res.secs}s</span><p style="margin:6px 0 0">${esc(res.explanation)}</p></div>
        <button class="btn block accent" id="next">${res.result ? "See my results" : "Next question"}</button>`;
      document.getElementById("next").onclick = () => {
        if (res.result) { state.lastResult = res.result; state.me = null; go("results"); }
        else viewQuiz();
      };
      document.getElementById("next").focus();
    }));
  }

  // ---------- results ----------
  async function viewResults() {
    chrome(true, "quiz");
    let r = state.lastResult;
    if (!r) {
      render(`<div class="skeleton" style="height:320px"></div>`);
      try { r = await api("GET", "/quiz/result"); }
      catch (e) { return render(`<h1>Results</h1><div class="card"><p>You haven't finished today's quiz yet.</p><a class="btn" href="#/quiz">Take the quiz</a></div>`); }
    }
    if (!state.me) await loadMe();
    chrome(true, "quiz");
    const dateStr = new Date(r.date).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
    const bonus = r.multiplier > 1 ? ` · ${r.multiplier}x streak bonus` : "";
    render(`<div class="result-card" id="card"><div class="eyebrow">IMT Pulse · ${dateStr}</div>
        <div class="score">${r.score}</div><div class="sub">points · ${esc(r.display_name)} · ${TRACKS[r.track].name}</div>
        <div class="stats"><div><b>${r.correct}/${r.total}</b><span>correct</span></div>
          <div><b>${r.rank ? "#" + r.rank : "–"}</b><span>of ${r.players} today</span></div>
          <div><b>🔥 ${r.streak}</b><span>day streak</span></div></div>
        <div class="foot"><span>${r.base} base${bonus}</span><span>${Math.round(r.total_secs)}s total</span></div></div>
      <button class="btn block accent" id="share">Share on WhatsApp</button>
      <a class="btn block ghost" href="#/leaderboard">See the leaderboard</a>
      <p class="muted small center" style="padding:12px">Tip: screenshot the card above to share it as an image.</p>`);
    document.getElementById("share").onclick = async () => {
      const text = `I scored ${r.score} on today's IMT Pulse quiz (${r.correct}/${r.total} correct${r.rank ? `, #${r.rank} of ${r.players}` : ""}, 🔥 ${r.streak}-day streak). Can you beat that?`;
      const url = location.origin;
      logEvent("results_shared", { score: r.score });
      if (navigator.share) { try { await navigator.share({ title: "IMT Pulse", text, url }); } catch (e) {} }
      else { location.href = "https://wa.me/?text=" + encodeURIComponent(text + " " + url); }
    };
  }

  // ---------- leaderboard ----------
  async function viewLeaderboard(params) {
    chrome(true, "leaderboard");
    const period = params.get("p") === "week" ? "week" : "today";
    render(`<h1>Leaderboard</h1><div class="tabs"><button data-p="today" class="${period === "today" ? "on" : ""}">Today</button>
      <button data-p="week" class="${period === "week" ? "on" : ""}">This week</button></div><div id="lb"><div class="skeleton" style="height:300px"></div></div>`);
    $app.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => go(b.dataset.p === "week" ? "leaderboard?p=week" : "leaderboard")));
    const d = await api("GET", "/leaderboard?period=" + period);
    const fmt = (s) => new Date(s).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
    const sub = period === "week" ? `Mon ${fmt(d.week[0])} – Sun ${fmt(d.week[1])}` : "Resets at midnight IST";
    const rows = d.rows.map((r) => `<li class="${r.you ? "you" : ""}"><span class="rank">${r.rank <= 3 ? ["🥇", "🥈", "🥉"][r.rank - 1] : r.rank}</span>
      <span>${esc(r.name)}${r.you ? " (you)" : ""} <span class="muted small">${esc(r.batch)}${period === "week" ? ` · ${r.quizzes} quiz${r.quizzes === 1 ? "" : "zes"}` : ""}</span></span>
      <span class="pts">${r.score}</span></li>`).join("");
    document.getElementById("lb").innerHTML = `<p class="muted small">${sub} · ${d.players} player${d.players === 1 ? "" : "s"}</p>
      ${rows ? `<ol class="lb">${rows}</ol>` : `<div class="card center muted">No scores yet. Be the first!</div>`}
      ${d.me && d.me.hidden ? `<p class="muted small">You're hidden from others. Only you see your row.</p>` : ""}
      ${!d.me && period === "today" ? `<a class="btn block accent" href="#/quiz">Take today's quiz to get on the board</a>` : ""}`;
  }

  // ---------- profile ----------
  async function viewProfile() {
    chrome(true, "profile");
    const me = await loadMe();
    chrome(true, "profile");
    render(`<h1>${esc(me.first)} ${esc(me.last)}</h1><p class="muted" style="margin-top:-8px">${esc(me.email)}${me.batch ? " · " + esc(me.batch.toUpperCase()) : ""}</p>
      <div class="statgrid"><div class="stat"><b>🔥 ${me.streak}</b><span>streak (best ${me.best_streak})</span></div>
        <div class="stat"><b>${me.total_score}</b><span>total points</span></div><div class="stat"><b>${me.quizzes}</b><span>quizzes</span></div></div>
      <h2>Your track</h2>${trackPicker(me.track)}
      <p class="muted small">Changing your track applies from your next quiz.</p>
      <h2>Leaderboard</h2>
      <form id="dnf" class="card"><label for="dn" style="margin-top:0">Display name</label>
        <div style="display:flex;gap:8px"><input id="dn" name="display_name" maxlength="30" value="${esc(me.display_name)}"><button class="btn small">Save</button></div>
        <div class="row" style="margin-top:12px"><div><b>Hide me from the leaderboard</b><div class="muted small">You'll still see your own rank.</div></div>
          <label class="switch"><input type="checkbox" id="hidden" ${me.hidden ? "checked" : ""}><i></i></label></div></form>
      <p class="muted small">Scoring: 10 points per correct answer, plus up to 3 for speed. Streaks multiply your daily score: 1.1x at 3+ days, 1.25x at 7+ days.</p>
      <button class="btn block ghost" id="logout">Log out</button>`);
    $app.querySelectorAll(".track").forEach((b) => (b.onclick = async () => {
      try { state.me = await api("PUT", "/me", { track: b.dataset.track });
        $app.querySelectorAll(".track").forEach((x) => x.classList.toggle("on", x === b)); toast(`Track set to ${TRACKS[b.dataset.track].name}`); }
      catch (e) { toast(e.message); }
    }));
    document.getElementById("dnf").onsubmit = async (ev) => {
      ev.preventDefault();
      try { state.me = await api("PUT", "/me", { display_name: document.getElementById("dn").value }); toast("Saved"); }
      catch (e) { toast(e.message); }
    };
    document.getElementById("hidden").onchange = async (ev) => {
      try { state.me = await api("PUT", "/me", { hidden: ev.target.checked }); toast(ev.target.checked ? "Hidden from leaderboard" : "Visible on leaderboard"); }
      catch (e) { ev.target.checked = !ev.target.checked; toast(e.message); }
    };
    document.getElementById("logout").onclick = async () => { await Auth.signOut(); state.me = null; go("login"); };
  }

  // ---------- router ----------
  const PUBLIC = { login: viewLogin, signup: viewSignup, verify: viewVerify, forgot: viewForgot };
  const PRIVATE = { home: viewHome, quiz: viewQuiz, results: viewResults, leaderboard: viewLeaderboard, profile: viewProfile,
    onboarding: viewOnboarding, admin: (p) => window.PulseAdmin.view(p, { chrome, render, esc, toast, api, go }) };

  async function route_() {
    stopTimer();
    const [name, qs] = (location.hash.replace(/^#\/?/, "") || "home").split("?");
    const params = new URLSearchParams(qs || "");
    if (PUBLIC[name]) {
      if (Auth.signedIn() && name !== "verify") return go("home");
      return PUBLIC[name](params);
    }
    if (!Auth.signedIn()) return go("login");
    try {
      if (!state.me) await loadMe();
      if (!state.me.onboarded && name !== "onboarding") return go("onboarding");
      const view = PRIVATE[name] || viewHome;
      await view(params);
    } catch (e) {
      if (!Auth.signedIn()) return go("login");
      chrome(true);
      render(`<div class="card center"><h2>Couldn't load</h2><p class="muted">${esc(e.message)}</p><button class="btn" onclick="location.reload()">Try again</button></div>`);
    }
  }

  window.addEventListener("hashchange", route_);
  route_();
  if (Auth.signedIn()) logEvent("app_open");
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
})();
