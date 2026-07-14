// board.js — shared renderer for the Summer Reading game board.
// Reads JSON (shape documented at bottom of this file) and patches the
// existing HTML markup in-place. Falls back to embedded MOCK when the
// /board.json endpoint isn't reachable (e.g. file:// preview, dev).

(function () {
  'use strict';

  // ----- embedded mock for offline preview -------------------------------
  const MOCK = {
    today: { iso: "2026-07-01", label: "Wed, Jul 1" },
    summer: {
      day: 22, total: 70, left: 48,
      start_label: "Jun 10", end_label: "Aug 19", pct: 0.32
    },
    family_goal: {
      current: 4180, target: 10000, pct: 0.418,
      alex: 1740, sam: 2440
    },
    daily_goal_min: 60,
    milestones: [
      { pts: 1500, label: "Small reward" },
      { pts: 3000, label: "Medium reward" },
      { pts: 4500, label: "Big reward" }
    ],
    players: [
      {
        key: "alex", name: "Alex", monogram: "A",
        age: 7, grade: "2nd grade",
        total_pts: 1740,
        books_finished: 3,
        tier_label: "Stretch", tier_ppp: "1.5",
        today: { pages: 35, pts: 52, sessions: 1 },
        week: {
          pts: 210, pages: 280, days_read: 5,
          by_day: [
            { name: "Mon", pages: 56, sessions: 1, is_today: false, is_future: false },
            { name: "Tue", pages: 64, sessions: 2, is_today: false, is_future: false },
            { name: "Wed", pages:  0, sessions: 0, is_today: false, is_future: false },
            { name: "Thu", pages: 48, sessions: 1, is_today: false, is_future: false },
            { name: "Fri", pages: 35, sessions: 1, is_today: false, is_future: false },
            { name: "Sat", pages: 42, sessions: 1, is_today: false, is_future: false },
            { name: "Sun", pages: 35, sessions: 1, is_today: true,  is_future: false }
          ]
        },
        milestones: {
          cleared_indices: [0],
          next_index: 1,
          next_to_go: 1260,
          progress_overall: 0.387
        },
        bingo: {
          squares_checked: [0, 4, 6, 12, 16, 19, 22],
          lines: [],
          lines_count: 0,
          pts_bonus: 0,
          grid_size: 5
        },
        recent: [
          { title: "The Boxcar Children",
            when_label: "Today", when_time: "5:42p",
            pages: 42, points: 52,
            detail_meta: "490L · Comfort × Modern" },
          { title: "Magic Tree House: Dinosaurs Before Dark",
            when_label: "Sat", when_time: "2:10p",
            pages: 64, points: 32,
            detail_meta: "240L · Easy" },
          { title: "Dog Man: Mothering Heights",
            when_label: "Fri", when_time: "7:50p",
            pages: 56, points: 11,
            detail_meta: "Graphic novel" }
        ]
      },
      {
        key: "sam", name: "Sam", monogram: "S",
        age: 10, grade: "6th grade",
        total_pts: 2440,
        books_finished: 7,
        tier_label: "Comfort", tier_ppp: "1.0",
        today: { pages: 48, pts: 72, sessions: 1 },
        week: {
          pts: 410, pages: 412, days_read: 6,
          by_day: [
            { name: "Mon", pages: 70, sessions: 2, is_today: false, is_future: false },
            { name: "Tue", pages: 65, sessions: 1, is_today: false, is_future: false },
            { name: "Wed", pages: 72, sessions: 2, is_today: false, is_future: false },
            { name: "Thu", pages: 45, sessions: 1, is_today: false, is_future: false },
            { name: "Fri", pages: 68, sessions: 1, is_today: false, is_future: false },
            { name: "Sat", pages:  0, sessions: 0, is_today: false, is_future: false },
            { name: "Sun", pages: 48, sessions: 1, is_today: true,  is_future: false }
          ]
        },
        milestones: {
          cleared_indices: [0],
          next_index: 1,
          next_to_go: 560,
          progress_overall: 0.542
        },
        bingo: {
          squares_checked: [0, 3, 7, 11, 12, 15, 17, 19, 22, 24],
          lines: [4],          // Row 5 cleared
          lines_count: 1,
          pts_bonus: 25,
          grid_size: 5
        },
        recent: [
          { title: "The Hobbit",
            when_label: "Today", when_time: "4:15p",
            pages: 48, points: 72,
            detail_meta: "1000L · Comfort × Masterpiece" },
          { title: "Percy Jackson: The Lightning Thief",
            when_label: "Fri", when_time: "8:05p",
            pages: 54, points: 27,
            detail_meta: "740L · Easy" },
          { title: "Harry Potter and the Goblet of Fire",
            when_label: "Wed", when_time: "6:30p",
            pages: 60, points: 60,
            detail_meta: "880L · Comfort" }
        ]
      }
    ]
  };

  const MILESTONE_REWARD_LABELS = ['Small reward', 'Medium reward', 'Big reward'];

  // Per-reader accent palette, assigned by index. First two match the
  // original two-reader board (amber / blue); the rest extend it for more.
  const PALETTE = [
    { accent: 'var(--sun)', deep: 'var(--sun-deep)', stroke: '#a3691f', grad: '#FFF7E0', ink: '' },
    { accent: 'var(--sea)', deep: 'var(--sea-deep)', stroke: '#2c4a6e', grad: '#E6F0F7', ink: 'var(--paper)' },
    { accent: '#3aa76d', deep: '#1f6e45', stroke: '#1f6e45', grad: '#E6F4EC', ink: 'var(--paper)' },
    { accent: '#8a63c4', deep: '#553a86', stroke: '#553a86', grad: '#F1E9F8', ink: 'var(--paper)' },
    { accent: '#e07a5f', deep: '#a24a34', stroke: '#a24a34', grad: '#FBEAE4', ink: 'var(--paper)' },
    { accent: '#2f9bb5', deep: '#1c6577', stroke: '#1c6577', grad: '#E4F2F6', ink: 'var(--paper)' }
  ];
  const familyStripe = (pal) =>
    `repeating-linear-gradient(45deg, ${pal.accent} 0 5px, ${pal.deep} 5px 10px)`;
  function applyAccent(el, i) {
    const pal = PALETTE[i % PALETTE.length];
    el.style.setProperty('--accent', pal.accent);
    el.style.setProperty('--accent-deep', pal.deep);
    el.style.setProperty('--accent-stroke', pal.stroke);
    el.style.setProperty('--accent-grad', pal.grad);
    if (pal.ink) el.style.setProperty('--accent-ink', pal.ink);
  }

  // ----- helpers ---------------------------------------------------------
  const fmt   = (n) => Number(n).toLocaleString();
  const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));
  const setText = (root, sel, val) => {
    const el = root.querySelector(sel);
    if (el != null) el.textContent = val;
  };
  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));

  // ----- header / season / family-goal -----------------------------------
  function renderHeader(d) {
    const root = document;
    setText(root, '[data-day-of-summer]', String(d.summer.day));
    setText(root, '[data-summer-total]',  String(d.summer.total));
    setText(root, '[data-days-left]',     d.summer.left + ' days left');
    setText(root, '[data-summer-start]',  d.summer.start_label);
    setText(root, '[data-summer-end]',    d.summer.end_label);
    setText(root, '[data-daily-goal]',    'Daily reading');
    setText(root, '[data-today-label]',   d.today.label);

    const fill   = root.querySelector('[data-season-fill]');
    const marker = root.querySelector('[data-season-marker]');
    if (fill)   fill.style.width = (d.summer.pct * 100).toFixed(1) + '%';
    if (marker) marker.style.left = (d.summer.pct * 100).toFixed(1) + '%';

    // Family goal
    if (d.family_goal) {
      const pct = clamp(d.family_goal.pct, 0, 1);
      const fgFill = root.querySelector('[data-family-fill]');
      if (fgFill) fgFill.style.width = (pct * 100).toFixed(1) + '%';

      // per-reader split segments inside the fill
      const splits = root.querySelector('[data-family-splits]');
      if (splits) {
        splits.innerHTML = '';
        let acc = 0;
        (d.players || []).forEach((p, i) => {
          const val = Number(d.family_goal[p.key] || 0);
          const w = clamp(val / d.family_goal.target, 0, 1);
          const seg = document.createElement('div');
          seg.className = 'fill-seg';
          seg.style.left = (acc * 100).toFixed(1) + '%';
          seg.style.width = (w * 100).toFixed(1) + '%';
          seg.style.background = familyStripe(PALETTE[i % PALETTE.length]);
          splits.appendChild(seg);
          acc += w;
        });
      }

      setText(root, '[data-family-current]', fmt(Math.round(d.family_goal.current)));
      setText(root, '[data-family-target]',  fmt(d.family_goal.target));
      setText(root, '[data-family-pct]',     Math.round(pct * 100) + '%');
    }
  }

  // ----- quest track (SVG path + milestones + pawn) ----------------------
  function renderQuestTrack(playerEl, p, milestonePts) {
    const svg = playerEl.querySelector('[data-quest-svg]');
    if (!svg) return;
    const bg = svg.querySelector('[data-quest-bg-path]');
    const fg = svg.querySelector('[data-quest-fg-path]');
    if (!bg || !fg) return;

    const len = bg.getTotalLength();
    fg.setAttribute('stroke-dasharray', len);
    fg.setAttribute('stroke-dashoffset',
      len * (1 - clamp(p.milestones.progress_overall, 0, 1)));

    const maxPts = milestonePts[milestonePts.length - 1];
    const milestoneEls = svg.querySelectorAll('[data-milestone]');
    milestoneEls.forEach((el) => {
      const idx = Number(el.getAttribute('data-milestone'));
      const pts = milestonePts[idx];
      const pct = clamp(pts / maxPts, 0, 1);
      const pt  = bg.getPointAtLength(len * pct);
      const yOff = (idx === 1) ? 12 : -10;
      el.setAttribute('transform', `translate(${pt.x.toFixed(1)} ${(pt.y + yOff).toFixed(1)})`);

      el.classList.remove('cleared', 'next', 'locked');
      if (p.milestones.cleared_indices.includes(idx)) el.classList.add('cleared');
      else if (idx === p.milestones.next_index)        el.classList.add('next');
      else                                              el.classList.add('locked');

      // Update label text
      const lbl = el.querySelector('.num-label');
      if (lbl) lbl.textContent = fmt(pts);
    });

    const pawn = svg.querySelector('[data-quest-pawn]');
    if (pawn) {
      const pct = clamp(p.milestones.progress_overall, 0.005, 0.995);
      const pt = bg.getPointAtLength(len * pct);
      pawn.setAttribute('transform',
        `translate(${pt.x.toFixed(1)} ${(pt.y - 16).toFixed(1)})`);
    }
  }

  // ----- quest legend stones --------------------------------------------
  function renderQuestLegend(playerEl, p, milestonePts) {
    const stones = playerEl.querySelectorAll('[data-stone]');
    stones.forEach((stone) => {
      const idx = Number(stone.getAttribute('data-stone'));
      stone.classList.remove('done', 'next', 'locked');
      const headline = stone.querySelector('[data-stone-headline]');
      if (p.milestones.cleared_indices.includes(idx)) {
        stone.classList.add('done');
        if (headline) headline.innerHTML =
          '<span class="check"></span>' + fmt(milestonePts[idx]) + ' pts';
      } else if (idx === p.milestones.next_index) {
        stone.classList.add('next');
        if (headline) headline.textContent = fmt(p.milestones.next_to_go) + ' to go';
      } else {
        stone.classList.add('locked');
        const togo = Math.max(0, milestonePts[idx] - p.total_pts);
        if (headline) headline.textContent = fmt(togo) + ' to go';
      }
    });
  }

  // ----- today ring -----------------------------------------------------
  // Ring is binary: filled when they’ve read today, empty when they haven’t.
  // No minute goal anymore — just pages logged.
  function renderToday(playerEl, p) {
    const fill = playerEl.querySelector('[data-today-fill]');
    if (fill) {
      const r = parseFloat(fill.getAttribute('r'));
      const circ = 2 * Math.PI * r;
      fill.setAttribute('stroke-dasharray', circ.toFixed(1));
      fill.setAttribute('stroke-dashoffset',
        (p.today.sessions > 0 ? 0 : circ).toFixed(1));
    }
    const pages = p.today.pages || 0;
    setText(playerEl, '[data-today-mins]', String(pages));
    setText(playerEl, '[data-today-goal]', pages === 1 ? 'page' : 'pages');

    const status = playerEl.querySelector('[data-today-status]');
    if (status) {
      status.classList.remove('met');
      if (p.today.sessions > 0) {
        status.textContent = 'Read today ✓';
        status.classList.add('met');
      } else {
        status.textContent = 'Not yet today';
      }
    }
  }

  // ----- week strip -----------------------------------------------------
  // Each day cell shows pages (when they read) or a hollow zero state.
  // “met” state is whether they read at all that day (sessions > 0).
  function renderWeek(playerEl, p) {
    const days = playerEl.querySelectorAll('[data-week-day]');
    p.week.by_day.forEach((d, i) => {
      const cell = days[i];
      if (!cell) return;
      const nameEl = cell.querySelector('[data-day-name]');
      const minEl  = cell.querySelector('[data-day-mins]');
      const read   = (d.sessions || 0) > 0;
      if (nameEl) nameEl.textContent = d.name;
      if (minEl)  minEl.textContent  = read ? d.pages : '—';
      cell.classList.remove('met', 'zero', 'today', 'future');
      if (d.is_future)     cell.classList.add('future');
      else if (d.is_today) cell.classList.add('today');
      if (read)            cell.classList.add('met');
      else if (!d.is_future) cell.classList.add('zero');
    });

    const summary = playerEl.querySelector('[data-week-summary]');
    if (summary) {
      summary.innerHTML =
        '<b>+' + fmt(Math.round(p.week.pts)) + '</b> pts · ' +
        fmt(p.week.pages || 0) + ' pp · ' + p.week.days_read + ' days';
    }
  }

  // ----- recent sessions ------------------------------------------------
  function renderRecent(playerEl, p) {
    const list = playerEl.querySelector('[data-recent]');
    if (!list) return;
    if (!p.recent || p.recent.length === 0) {
      list.innerHTML =
        '<div class="recent-empty">No sessions logged yet — use ' +
        '<code>/read</code> in Mattermost</div>';
      return;
    }
    list.innerHTML = p.recent.map(s => `
      <div class="session">
        <div class="when">${escapeHtml(s.when_label)}<br>${escapeHtml(s.when_time)}</div>
        <div class="book">
          <em>${escapeHtml(s.title)}</em>
          <span class="detail">${s.pages} pp · ${escapeHtml(s.detail_meta)}</span>
        </div>
        <div class="gain"><span class="plus">+</span>${Math.round(s.points)}</div>
      </div>
    `).join('');
  }

  // ----- bingo mini-grid ------------------------------------------------
  function renderBingo(playerEl, p) {
    const grid = playerEl.querySelector('[data-bingo-grid]');
    if (grid && p.bingo) {
      const checked = new Set(p.bingo.squares_checked || []);
      // Which positions are part of an awarded line?
      const LINES = [
        [0,1,2,3,4], [5,6,7,8,9], [10,11,12,13,14],
        [15,16,17,18,19], [20,21,22,23,24],
        [0,5,10,15,20], [1,6,11,16,21], [2,7,12,17,22],
        [3,8,13,18,23], [4,9,14,19,24],
        [0,6,12,18,24], [4,8,12,16,20]
      ];
      const inLine = new Set();
      (p.bingo.lines || []).forEach(li => LINES[li].forEach(i => inLine.add(i)));

      let html = '';
      for (let i = 0; i < 25; i++) {
        const cls =
          (checked.has(i) ? ' checked' : '') +
          (inLine.has(i)  ? ' line'    : '') +
          (i === 12       ? ' free'    : '');
        html += `<span class="bingo-cell${cls}"></span>`;
      }
      grid.innerHTML = html;
    }

    const summary = playerEl.querySelector('[data-bingo-summary]');
    if (summary && p.bingo) {
      const n = p.bingo.lines_count || 0;
      const pts = p.bingo.pts_bonus || 0;
      const sq  = (p.bingo.squares_checked || []).length;
      if (n > 0) {
        summary.innerHTML =
          '<b>' + n + ' line' + (n > 1 ? 's' : '') + '</b> · +' + pts + ' pts';
      } else {
        summary.innerHTML = sq + ' / 25 squares';
      }
    }
  }

  // ----- player header + score -----------------------------------------
  function renderPlayerHeader(playerEl, p) {
    setText(playerEl, '[data-name]',         p.name);
    setText(playerEl, '[data-monogram]',     p.monogram);
    setText(playerEl, '[data-grade]',        'Age ' + p.age + ' · ' + p.grade);
    setText(playerEl, '[data-tier-label]',   p.tier_label);
    setText(playerEl, '[data-tier-ppp]',     p.tier_ppp + ' pts/pg');
    setText(playerEl, '[data-total-pts]',    fmt(Math.round(p.total_pts)));
    setText(playerEl, '[data-books-finished]', String(p.books_finished ?? 0));

    const toGo = playerEl.querySelector('[data-pts-to-go]');
    if (toGo) {
      if (p.milestones.next_to_go != null && p.milestones.next_index != null) {
        const label = MILESTONE_REWARD_LABELS[p.milestones.next_index] || 'Reward';
        toGo.innerHTML =
          fmt(Math.round(p.milestones.next_to_go)) + ' to <em>' + escapeHtml(label) + '</em>';
      } else {
        toGo.innerHTML = '<em>All milestones cleared</em>';
      }
    }
  }

  // ----- main render ----------------------------------------------------
  function render(data) {
    const milestonePts = (data.milestones || []).map(m => m.pts);
    renderHeader(data);
    const container = document.querySelector('.players');
    const tpl = document.getElementById('player-tpl');
    if (container && tpl) {
      container.querySelectorAll('.player').forEach(n => n.remove());
      (data.players || []).forEach((p, i) => {
        const root = tpl.content.firstElementChild.cloneNode(true);
        root.setAttribute('data-player', p.key);
        applyAccent(root, i);
        const link = root.querySelector('[data-bingo-link]');
        if (link) link.textContent = '/bingo show ' + p.key;
        const pawn = root.querySelector('.pawn-letter');
        if (pawn) pawn.textContent = p.monogram;
        container.appendChild(root);
        renderPlayerHeader(root, p);
        renderQuestTrack(root, p, milestonePts);
        renderQuestLegend(root, p, milestonePts);
        renderToday(root, p);
        renderWeek(root, p);
        renderBingo(root, p);
        renderRecent(root, p);
      });
    }
    document.body.classList.add('board-ready');
    window.__boardRenderedAt = Date.now();
  }

  // ----- fetch + auto-refresh ------------------------------------------
  let __lastHash = null;

  async function fetchAndRender() {
    try {
      const resp = await fetch('/board.json', { cache: 'no-store' });
      if (!resp.ok) throw new Error('http ' + resp.status);
      const data = await resp.json();
      window.__boardSource = 'live';
      const h = JSON.stringify(data);
      if (h === __lastHash) return data;   // unchanged — skip DOM rebuild
      __lastHash = h;
      render(data);
      return data;
    } catch (e) {
      console.warn('[board] live fetch failed (' + e.message +
                   ') — using embedded mock data');
      const mock = window.__boardMock || MOCK;
      window.__boardSource = 'mock';
      const h = JSON.stringify(mock);
      if (h === __lastHash) return null;
      __lastHash = h;
      render(mock);
      return null;
    }
  }

  window.Board = { render, fetchAndRender, MOCK };
})();

/* ------------------------------------------------------------------
JSON contract for /board.json:
{
  "today":          { "iso": "YYYY-MM-DD", "label": "Wed, Jul 1" },
  "summer":         { "day": 22, "total": 70, "left": 48,
                      "start_label": "Jun 10", "end_label": "Aug 19",
                      "pct": 0.32 },
  "family_goal":    { "current": 1920, "target": 5000, "pct": 0.384,
                      "alex": 740, "sam": 1180 },
  "daily_goal_min": 60,    // unused on board, kept for back-compat
  "milestones":     [ {"pts": 500, "label": "Small reward"}, ... ],
  "players": [
    {
      "key": "alex", "name": "Alex", "monogram": "A",
      "age": 7, "grade": "2nd grade",
      "total_pts": 740, "books_finished": 3,
      "tier_label": "Stretch", "tier_ppp": 1.5,
      "today":      { "pages": 35, "pts": 52, "sessions": 1 },
      "week":       { "pts": 210, "pages": 280, "days_read": 5,
                      "by_day": [{"name":"Mon","pages":56,"sessions":1,...}, ...x7] },
      "milestones": { "cleared_indices": [0],
                      "next_index": 1, "next_to_go": 260,
                      "progress_overall": 0.296 },
      "bingo":      { "squares_checked": [0,4,...],
                      "lines": [4],
                      "lines_count": 1, "pts_bonus": 25,
                      "grid_size": 5 },
      "recent":     [ { "title": "...", "when_label": "Today",
                        "when_time": "5:42p",
                        "pages": 42, "points": 52,
                        "detail_meta": "490L · Comfort × Modern" }, ... ]
    }
  ]
}

Note on “today” boundary: the server is expected to compute `today` in the
family’s local timezone (TZ_LOCAL env var, e.g. America/New_York). If left
unset, the container defaults to UTC and the day rolls over at the wrong time.
------------------------------------------------------------------ */
