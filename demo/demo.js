// Static demo of IMT Pulse: one real day's generated content (demo/data.json), with a playable quiz.
// The live app (sign-in, leaderboards, daily generation) runs on AWS and is paused; see the README.
(function () {
  const TRACKS = {
    marketing: "Marketing", finance: "Finance", consulting: "Consulting / Strategy", ops: "Ops / Analytics", hr: "HR",
  };
  const CREDIT = `<p class="credit">IMT Pulse by Raj Srivastava · Created 21 Oct 2026</p>`;
  const $app = document.getElementById("app");
  let data = null, timerId = null;

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const render = (html) => { $app.innerHTML = html; window.scrollTo(0, 0); };
  const fmt = (d, o) => new Date(d).toLocaleDateString("en-IN", o);

  const banner = () => `<div class="note"><b>The live app is paused for updates.</b> This demo shows a real edition the AI pipeline
    generated on ${fmt(data.date, { day: "numeric", month: "long", year: "numeric" })} during the student pilot. Sign-in, leaderboards and streaks
    are part of the live app.</div>`;

  function companyCard(c) {
    if (!c) return "";
    const news = (c.recent_news || []).map((n) => `<li>${esc(n.point)} <a href="${esc(n.link)}" target="_blank" rel="noopener">${esc(n.source)}</a></li>`).join("");
    return `<section class="card company"><div class="eyebrow">Company of the Day</div>
      <h2 style="margin:4px 0 2px">${esc(c.name)}</h2><p>${esc(c.what_it_does)}</p>
      <details><summary>Business lines, news & talking points</summary>
        <h3>Main business lines</h3><ul class="tight">${(c.business_lines || []).map((b) => `<li>${esc(b)}</li>`).join("")}</ul>
        ${news ? `<h3>In the news</h3><ul class="tight">${news}</ul>` : ""}
        <h3>Likely interview talking points</h3><ol class="tight">${(c.talking_points || []).map((t) => `<li>${esc(t)}</li>`).join("")}</ol>
      </details>
      <p class="badge" style="margin-top:12px">AI-written brief: double-check facts before your interview</p></section>`;
  }

  function storyCard(s) {
    return `<article class="card story"><h3><a href="${esc(s.link)}" target="_blank" rel="noopener">${esc(s.headline)}</a></h3>
      <p>${esc(s.summary)}</p><p class="why"><b>Why it matters:</b> ${esc(s.why_it_matters)}</p>
      <div class="meta">${esc(s.source)} · <a href="${esc(s.link)}" target="_blank" rel="noopener">Read original ↗</a></div></article>`;
  }

  function viewBrief(track) {
    const t = data.tracks[track];
    const quizLen = t.quiz.length + (data.company ? data.company.quiz.length : 0);
    const chips = Object.keys(TRACKS).filter((k) => data.tracks[k]).map((k) => `<button class="chip ${k === track ? "on" : ""}" data-t="${k}">${TRACKS[k]}</button>`).join("");
    render(`${banner()}
      <p class="eyebrow" style="margin-top:16px">${fmt(data.date, { weekday: "long", day: "numeric", month: "long" })}</p>
      <h1>Good morning 👋</h1>
      <p class="muted">Every morning at 8:00: the 5 stories that matter for your placement track, a Company of the Day brief and a quick quiz. Pick a track:</p>
      <div class="chips">${chips}</div>
      <a class="cta" href="#/quiz?track=${track}"><div><strong>Today's quiz · ${quizLen} questions</strong>
        <span>${TRACKS[track]} + Company of the Day. Faster correct answers earn bonus points.</span></div><b class="go">Start</b></a>
      ${companyCard(data.company)}
      <h2>Today's ${TRACKS[track]} stories</h2>
      ${t.stories.map(storyCard).join("")}
      <p class="muted small center" style="padding:16px 16px 0">Summaries, "why it matters" lines, quizzes and the company brief were written by
        Claude on Amazon Bedrock from news headlines. Tap a headline to read the original article.</p>
      <a class="btn block ghost" href="https://github.com/rajsrivastavaaa/imt-pulse">How it's built (GitHub) ↗</a>${CREDIT}`);
    $app.querySelectorAll(".chip").forEach((b) => (b.onclick = () => (location.hash = `#/?track=${b.dataset.t}`)));
  }

  function viewQuiz(track) {
    const qs = [...data.tracks[track].quiz.map((q) => ({ ...q, kind: "" })),
      ...(data.company ? data.company.quiz.map((q) => ({ ...q, kind: "Company of the Day · " })) : [])];
    let i = 0, score = 0, correct = 0, totalSecs = 0;
    const next = () => {
      clearInterval(timerId);
      if (i >= qs.length) {
        return render(`<div class="result-card"><div class="eyebrow">IMT Pulse · ${fmt(data.date, { day: "numeric", month: "short", year: "numeric" })}</div>
          <div class="score">${score}</div><div class="sub">points · ${TRACKS[track]}</div>
          <div class="stats"><div><b>${correct}/${qs.length}</b><span>correct</span></div><div><b>${Math.round(totalSecs)}s</b><span>total time</span></div>
            <div><b>🔥 1</b><span>day streak</span></div></div>
          <div class="foot"><span>10 per correct + speed bonus</span><span>IMT Pulse by Raj Srivastava</span></div></div>
          <p class="muted small">In the live app, answers are checked on the server, scores feed daily and weekly leaderboards,
            and streaks multiply your score (1.1x at 3 days, 1.25x at 7).</p>
          <a class="btn block accent" href="#/?track=${track}">Back to the brief</a>${CREDIT}`);
      }
      const q = qs[i], started = Date.now();
      render(`<div class="qhead"><span>${q.kind}Question ${i + 1} of ${qs.length}</span><span class="timer" id="timer">0s</span></div>
        <div class="progress"><i style="width:${(i / qs.length) * 100}%"></i></div>
        <div class="question">${esc(q.question)}</div>
        <div>${q.options.map((o, j) => `<button class="opt" data-i="${j}"><b>${"ABCD"[j]}</b><span>${esc(o)}</span></button>`).join("")}</div>
        <div id="after"></div><p class="muted small" style="margin-top:16px">Score so far: ${score} · answer within 10s for the full speed bonus</p>`);
      const $t = document.getElementById("timer");
      timerId = setInterval(() => ($t.textContent = Math.floor((Date.now() - started) / 1000) + "s"), 250);
      const buttons = [...document.querySelectorAll(".opt")];
      buttons.forEach((b) => (b.onclick = () => {
        clearInterval(timerId);
        buttons.forEach((x) => (x.disabled = true));
        const secs = (Date.now() - started) / 1000, ok = Number(b.dataset.i) === q.answer_index;
        const bonus = secs <= 10 ? 3 : secs >= 40 ? 0 : Math.round((3 * (40 - secs)) / 30);
        totalSecs += secs;
        if (ok) { score += 10 + bonus; correct++; }
        buttons[q.answer_index].classList.add("right");
        if (!ok) b.classList.add("wrong");
        document.getElementById("after").innerHTML = `<div class="explain"><strong class="${ok ? "ok" : "bad"}">${ok ? `Correct · +${10 + bonus} points` : "Not quite"}</strong>
          <span class="muted small"> · ${secs.toFixed(1)}s</span><p style="margin:6px 0 0">${esc(q.explanation)}</p></div>
          <button class="btn block accent" id="next">${i + 1 < qs.length ? "Next question" : "See my results"}</button>`;
        document.getElementById("next").onclick = () => { i++; next(); };
      }));
    };
    next();
  }

  function route() {
    clearInterval(timerId);
    const [path, qs] = location.hash.replace(/^#/, "").split("?");
    const p = new URLSearchParams(qs || "");
    const track = data.tracks[p.get("track")] ? p.get("track") : "marketing";
    if (path === "/quiz") viewQuiz(track); else viewBrief(track);
  }

  fetch("data.json").then((r) => r.json()).then((d) => { data = d; route(); window.addEventListener("hashchange", route); })
    .catch(() => render(`<div class="card center"><h2>Couldn't load the demo</h2><p class="muted">Please refresh.</p></div>`));
})();
