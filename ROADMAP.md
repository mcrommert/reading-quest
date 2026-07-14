# Reading Bot — Extensibility Roadmap

Goals: (1) keep using it year over year past Summer 2026, and (2) eventually let
other families run it. This doc captures what to change and in what order. None
of it requires a rewrite — the valuable core is portable; the coupling is at the edges.

---

## What's already portable (the good part)
- **`scoring.py`** — pure functions (tiers, density, classic bonus, ppp). No I/O, fully reusable.
- **`books.json`** — ~3,200-book scored catalog. A genuine asset / selling point.
- **`bingo.py`** — line-detection + multi-card logic is generic; only the square *definitions* are name-coupled.
- **points / density / audiobook / dense-tier model** — the "intellectual property," and it generalizes fine.

## What blocks reuse (the coupling, all at the edges)
- **Identity is hardcoded to `alex` / `sam`:**
  - `scoring.py`: `ALEX_TIERS` / `SAM_TIERS` (per-name Lexile tier tables)
  - `bingo.py`: `W_*` / `M_*` square IDs, two hardcoded cards
  - `books.json`: `alex_ppp_override` / `sam_ppp_override` keys
  - `app.py`: `PLAYERS_CONFIG`, plus many string checks on `'alex'`/`'sam'`
- **Single season:** `SUMMER_START` / `SUMMER_END` env vars; sessions have no `season` column.
- **Platform coupling:** Mattermost slash commands + webhooks + team/token; only input path for logging.
- **Account-specific integrations:** Google/Skylight calendar (`gcal.py`), Alexa skill ID, MM tokens — all wired to one household.
- **Deploy:** Portainer archive-API + rebuild from a private repo; single SQLite DB, no multi-tenancy.

---

## Two decisions that drive everything (decide before building)

1. **Distribution model — self-host vs hosted.**
   Recommendation: **self-host first.** Others run the Docker image with their own
   config. ~80% less work than SaaS (no auth, billing, data isolation, support).
   Hosting for strangers can come later if there's demand.

2. **Interface — Mattermost vs neutral front-end.**
   MM means every user needs Mattermost (niche). Keep scoring/catalog as a backend
   and add a thin **web logging form** (the board already exists as the read-only face);
   MM becomes one optional input among several.

---

## Phase 1 — Cheap now, expensive later (do these first; they also help our own use)
These deepen with every feature added, so earlier is much cheaper.

- [ ] **Readers as config, not code.** One `readers` list — `[{key, name, age, grade, tier_table}]` —
      that `scoring`, `bingo`, overrides, and the board all read from. Removes every
      hardcoded `alex`/`sam` reference. *Highest-leverage single change.*
- [ ] **Season concept.** Add a `season` column to `sessions` (cheap now, painful to
      backfill later). Lets years roll over, archive cleanly, and compare across summers.
      Solves the "past this summer" need directly.
- [ ] **Config out of code → one `config.yaml`:** readers, current season, family name,
      goals/milestones, family goal, which integrations are enabled.
- [ ] **Make integrations optional / off by default.** gcal, Alexa, MM each configured
      per-deploy; the bot must run with none of them set.

## Phase 2 — Generalize for others
- [ ] **Onboarding / setup flow** so a parent defines kids + reading levels without
      understanding Lexile tiers. Provide sensible default tier tables by grade
      (the tier math is the hardest part for a layperson).
- [ ] **Catalog as shared base + per-family overlay.** Ship the 3,200-book catalog as
      the shared base; per-family additions/overrides live in a separate file so
      upgrades don't clobber customizations.
- [ ] **Data-driven bingo cards.** Move card layouts to config; families use the
      built-ins or author their own. Square IDs become `<reader>_<n>` style, not `W_`/`M_`.
- [ ] **Web logging form** (Phase 2 if not already started) as the universal input.

## Phase 3 — Packaging & sharing
- [ ] README, example `config.yaml`, clean `docker-compose.yml`, one-command bring-up.
- [ ] Migrations strategy (currently ad-hoc `ALTER TABLE` in `log_session`).
- [ ] Decide license + where to publish.

## Phase 4 — Only if going hosted (big lift; defer)
- [ ] Accounts/auth, per-family data isolation, multi-tenant DB, abuse handling, infra/support.

---

## Suggested order
Phase 1 (readers-as-config + season column first — foundation for everything and
helps us immediately) → rest of Phase 1 → Phase 2 → Phase 3. Phase 4 only if demand appears.

## Notes / context worth remembering
- Per-reader ppp overrides currently power illustrated-hybrid scoring (Captain Underpants
  0.40/0.12). In a readers-as-config world these stay per-book but key off reader `key`.
- Read-time (minutes) was intentionally excised from all displays (column kept for history).
- Audiobooks = ¼ points, excluded from bingo (`audiobook` flag on `/read`).
- Container rebuilds from git on update — any hotfix must be committed, not just archive-API'd.
