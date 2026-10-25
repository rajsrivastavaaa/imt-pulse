// Admin screens (admin Cognito group only; the API enforces this too).
(function () {
  const TRACK_NAMES = { marketing: "Marketing", finance: "Finance", consulting: "Consulting / Strategy", ops: "Ops / Analytics", hr: "HR" };
  let U;   // helpers passed in from app.js

  function istToday() {
    return new Date(Date.now() + 5.5 * 3600e3).toISOString().slice(0, 10);
  }

  async function view(params, helpers) {
    U = helpers;
    U.chrome(true, "admin");
    const tab = params.get("tab") || "review";
    const tabs = [["review", "Review"], ["schedule", "Companies"], ["stats", "Stats"]]
      .map(([k, n]) => `<a class="btn small ${k === tab ? "" : "ghost"}" href="#/admin?tab=${k}">${n}</a>`).join("");
    U.render(`<h1>Admin</h1><div class="admin-tabs">${tabs}</div><div id="pane"><div class="skeleton"></div></div>`);
    const pane = document.getElementById("pane");
    try {
      if (tab === "schedule") await schedule(pane);
      else if (tab === "stats") await stats(pane);
      else await review(pane, params.get("date") || istToday());
    } catch (e) { pane.innerHTML = `<div class="error">${U.esc(e.message)}</div>`; }
  }

  // ---------- review ----------
  function statusBadges(sec) {
    const b = [];
    if (sec.error) b.push(`<span class="badge bad">Failed: ${U.esc(sec.error).slice(0, 160)}</span>`);
    if (sec.warning) b.push(`<span class="badge">${U.esc(sec.warning)}</span>`);
    b.push(sec.status === "approved" ? `<span class="badge ok">Approved</span>` : `<span class="badge plain">Draft</span>`);
    if (sec.edited) b.push(`<span class="badge plain">Edited by you</span>`);
    return b.join(" ");
  }

  function quizEditor(quiz, prefix) {
    return (quiz || []).map((q, n) => `<div class="qedit" data-q="${n}">
      <label style="margin-top:0">Q${n + 1}</label><textarea data-f="question">${U.esc(q.question)}</textarea>
      ${q.options.map((o, i) => `<div class="optrow"><input type="radio" name="${prefix}-a${n}" value="${i}" ${i === Number(q.answer_index) ? "checked" : ""} aria-label="Correct answer ${"ABCD"[i]}">
        <input type="text" data-o="${i}" value="${U.esc(o)}"></div>`).join("")}
      <label>Explanation</label><textarea data-f="explanation">${U.esc(q.explanation)}</textarea></div>`).join("");
  }

  function readQuiz(card, prefix) {
    return [...card.querySelectorAll(".qedit")].map((el) => {
      const n = el.dataset.q;
      const checked = el.querySelector(`input[name="${prefix}-a${n}"]:checked`);
      return {
        question: el.querySelector('[data-f="question"]').value.trim(),
        options: [...el.querySelectorAll("[data-o]")].map((i) => i.value.trim()),
        answer_index: checked ? Number(checked.value) : 0,
        explanation: el.querySelector('[data-f="explanation"]').value.trim(),
      };
    });
  }

  function trackCard(sk, sec) {
    const track = sk.split("#")[1];
    const stories = (sec.stories || []).map((s, n) => `<div class="storyedit" data-s="${n}">
      <a href="${U.esc(s.link)}" target="_blank" rel="noopener"><b>${U.esc(s.headline)}</b></a> <span class="muted small">${U.esc(s.source)}</span>
      <label>Summary</label><textarea data-f="summary">${U.esc(s.summary)}</textarea>
      <label>Why it matters</label><textarea data-f="why_it_matters">${U.esc(s.why_it_matters)}</textarea>
      <label class="small" style="font-weight:400"><input type="checkbox" data-f="remove"> Remove this story</label></div>`).join("");
    return `<section class="card" data-sk="${sk}"><h2 style="margin-top:0">${TRACK_NAMES[track]}</h2>${statusBadges(sec)}
      <details><summary>${(sec.stories || []).length} stories</summary>${stories}</details>
      <details><summary>Quiz (${(sec.quiz || []).length} questions)</summary>${quizEditor(sec.quiz, sk)}</details>
      ${(sec.dropped || []).length ? `<details><summary class="muted">Left out by the pipeline (${sec.dropped.length})</summary><ul class="tight small">${sec.dropped.map((d) => `<li>${U.esc(d.headline)} <span class="muted">(${U.esc(d.reason)})</span></li>`).join("")}</ul></details>` : ""}
      <div class="toolbar"><button class="btn small ghost" data-act="save">Save edits</button><button class="btn small" data-act="approve">Save & approve</button></div></section>`;
  }

  function companyCardEdit(sec) {
    if (sec.error) return `<section class="card company" data-sk="COMPANY"><h2 style="margin-top:0">Company: ${U.esc(sec.name)}</h2>${statusBadges(sec)}</section>`;
    return `<section class="card company" data-sk="COMPANY"><h2 style="margin-top:0">Company: ${U.esc(sec.name)}</h2>${statusBadges(sec)}
      <label>What it does</label><textarea data-f="what_it_does">${U.esc(sec.what_it_does)}</textarea>
      <label>Business lines (one per line)</label><textarea data-f="business_lines">${U.esc((sec.business_lines || []).join("\n"))}</textarea>
      <label>Talking points (one per line)</label><textarea data-f="talking_points">${U.esc((sec.talking_points || []).join("\n"))}</textarea>
      ${(sec.recent_news || []).length ? `<p class="small muted">News items: ${sec.recent_news.map((n) => U.esc(n.point)).join(" · ")}</p>` : ""}
      <details><summary>Quiz (${(sec.quiz || []).length} questions)</summary>${quizEditor(sec.quiz, "COMPANY")}</details>
      <div class="toolbar"><button class="btn small ghost" data-act="save">Save edits</button><button class="btn small" data-act="approve">Save & approve</button></div></section>`;
  }

  async function review(pane, date) {
    const d = await U.api("GET", "/admin/day?date=" + date);
    const secs = d.sections || {};
    const meta = secs.META;
    const tracks = Object.keys(TRACK_NAMES).map((t) => `TRACK#${t}`).filter((k) => secs[k]);
    pane.innerHTML = `<div class="card"><div class="toolbar" style="margin-top:0">
        <input type="date" id="date" value="${date}" style="max-width:180px"><button class="btn small ghost" id="load">Open</button></div>
      <p class="small muted" style="margin-bottom:0">${meta ? `Generated ${new Date(meta.generated_at).toLocaleString("en-IN")} from ${meta.feed_items} feed items.` : "Nothing generated for this date yet."}
        ${d.published ? "Live for students (auto-published at 08:00 IST)." : "Not live yet: auto-publishes at 08:00 IST on this date."}
        ${d.schedule ? `Company: <b>${U.esc(d.schedule.name)}</b>.` : "No company scheduled for this date."}</p>
      <div class="toolbar"><button class="btn small accent" id="gen">Generate now</button>
        <label class="small" style="margin:0;font-weight:400"><input type="checkbox" id="force"> also replace sections I edited/approved</label></div></div>
      ${secs.COMPANY ? companyCardEdit(secs.COMPANY) : ""}${tracks.map((k) => trackCard(k, secs[k])).join("")}`;
    document.getElementById("load").onclick = () => U.go("admin?tab=review&date=" + document.getElementById("date").value);
    document.getElementById("gen").onclick = async (ev) => {
      ev.target.disabled = true;
      try {
        const r = await U.api("POST", "/admin/generate", { date: document.getElementById("date").value, force: document.getElementById("force").checked });
        U.toast(r.note);
      } catch (e) { U.toast(e.message); ev.target.disabled = false; }
    };
    pane.querySelectorAll("[data-act]").forEach((btn) => (btn.onclick = async () => {
      const card = btn.closest("[data-sk]"), sk = card.dataset.sk;
      const body = { date, sk, approve: btn.dataset.act === "approve" };
      if (sk === "COMPANY") {
        const lines = (f) => card.querySelector(`[data-f="${f}"]`).value.split("\n").map((s) => s.trim()).filter(Boolean);
        body.what_it_does = card.querySelector('[data-f="what_it_does"]').value.trim();
        body.business_lines = lines("business_lines");
        body.talking_points = lines("talking_points");
      } else {
        const orig = secs[sk].stories || [];
        body.stories = [...card.querySelectorAll(".storyedit")].filter((el) => !el.querySelector('[data-f="remove"]').checked)
          .map((el) => ({ ...orig[el.dataset.s], summary: el.querySelector('[data-f="summary"]').value.trim(),
            why_it_matters: el.querySelector('[data-f="why_it_matters"]').value.trim() }));
      }
      if (card.querySelector(".qedit")) body.quiz = readQuiz(card, sk);
      btn.disabled = true;
      try { await U.api("PUT", "/admin/section", body); U.toast(body.approve ? "Saved and approved" : "Saved"); review(pane, date); }
      catch (e) { U.toast(e.message); btn.disabled = false; }
    }));
  }

  // ---------- company schedule ----------
  async function schedule(pane) {
    const d = await U.api("GET", "/admin/schedule");
    const items = d.items.sort((a, b) => a.feature_date.localeCompare(b.feature_date));
    const rows = items.map((i) => `<tr><td>${U.esc(i.feature_date)}</td><td>${U.esc(i.name)}${i.aliases ? `<div class="muted small">aka ${U.esc(i.aliases)}</div>` : ""}</td>
      <td>${U.esc(i.process_date)}</td><td><button class="btn small ghost" data-del="${U.esc(i.feature_date)}">Remove</button></td></tr>`).join("");
    pane.innerHTML = `<form class="card" id="f"><h2 style="margin-top:0">Schedule a company</h2>
        <label>Company name</label><input name="name" required placeholder="Hindustan Unilever">
        <label>Also known as (comma-separated, used to find news)</label><input name="aliases" placeholder="HUL">
        <label>Feature it on (Company of the Day date)</label><input type="date" name="feature_date" required>
        <label>Placement process date</label><input type="date" name="process_date">
        <label>Verified notes (optional, the AI treats these as facts)</label>
        <textarea name="notes" placeholder="e.g. Segments: Home Care, Beauty & Wellbeing, Personal Care, Foods. Hiring for sales & marketing."></textarea>
        <button class="btn block">Save</button></form>
      <div class="card scroll-x"><h2 style="margin-top:0">Upcoming</h2>
        ${rows ? `<table class="stats"><tr><th>Feature date</th><th style="text-align:left">Company</th><th>Process</th><th></th></tr>${rows}</table>` : `<p class="muted">Nothing scheduled.</p>`}
        <p class="muted small">Generation runs at 05:30 IST. To regenerate a day after changing its company, use Review → Generate now.</p></div>`;
    const f = document.getElementById("f");
    f.onsubmit = async (ev) => {
      ev.preventDefault();
      try { await U.api("PUT", "/admin/schedule", Object.fromEntries(new FormData(f).entries())); U.toast("Saved"); schedule(pane); }
      catch (e) { U.toast(e.message); }
    };
    pane.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
      if (!confirm(`Remove the company scheduled for ${b.dataset.del}?`)) return;
      try { await U.api("DELETE", "/admin/schedule?feature_date=" + b.dataset.del); schedule(pane); } catch (e) { U.toast(e.message); }
    }));
  }

  // ---------- stats ----------
  async function stats(pane) {
    const d = await U.api("GET", "/admin/stats?days=14");
    const r = d.day7_return;
    const rows = d.days.slice().reverse().map((x) => `<tr><td>${x.date.slice(5)}</td><td>${x.dau}</td><td>${x.quizzes_completed}</td>
      <td>${x.quizzes_started}</td><td>${x.stories_opened}</td><td>${x.shares}</td><td>${x.signups}</td></tr>`).join("");
    pane.innerHTML = `<div class="statgrid"><div class="stat"><b>${d.users}</b><span>users</span></div>
        <div class="stat"><b>${d.days[d.days.length - 1].dau}</b><span>active today</span></div>
        <div class="stat"><b>${r.rate == null ? "–" : r.rate + "%"}</b><span>day-7 return (${r.returned}/${r.cohort})</span></div></div>
      <div class="card scroll-x"><table class="stats"><tr><th>Date</th><th>Active</th><th>Quizzes done</th><th>Started</th><th>Stories opened</th><th>Shares</th><th>Sign-ups</th></tr>${rows}</table>
      <p class="muted small">Active = opened the app or did anything that day. Day-7 return = of users whose first day was at least a week ago, the share who came back exactly 7 days later.</p></div>`;
  }

  window.PulseAdmin = { view };
})();
