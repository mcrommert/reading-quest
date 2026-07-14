# reading-bot

A summer-reading game for families. Log what your kids read, score it by
book difficulty (Lexile) relative to *each reader's* level, and show it all on
a live game board with per-reader progress, a family points goal, streaks, and
a bingo card. Optional Mattermost slash commands, an Alexa skill, and Google
Calendar sync.

It started as a two-kid household project and is built so **adding a reader is
a config edit, not a code change** — see [`reader_config_example.py`](reader_config_example.py).

## How scoring works

Every book has a Lexile measure. Each reader is assigned a **level** — a ladder
of Lexile boundaries (defined in [`readers.py`](readers.py), `LEVELS`) that maps a
book to a tier from *way&nbsp;below* to *big&nbsp;stretch*. Points per page scale
with the tier, so a book that's an easy read for an older reader is worth more
when a younger reader stretches into it. Format (graphic novel, easy reader,
chapter book…) and a per-book density factor adjust the rate further.

Seven levels ship by default (`emerging` → `advanced`); two readers can share
one, and you can tune the boundaries or add your own.

## Quick start

```bash
git clone <this repo>
cd reading-bot
cp reader_config_example.py reader_config.py   # then edit for your family
cp .env.example .env                            # optional integrations
cp docker-compose.example.yml docker-compose.yml
docker compose up -d
```

Open **http://localhost:8602/board/** for the board. Without Docker:

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8602
```

## Configuring readers

Copy the example and edit `reader_config.py` (gitignored, so your family's real
data never gets committed):

```python
READERS = [
    {"key": "alex", "name": "Alex", "monogram": "A", "age": 7,
     "grade": "2nd grade", "level": "developing", "aliases": ["a"]},
    {"key": "sam",  "name": "Sam",  "monogram": "S", "age": 10,
     "grade": "5th grade", "level": "capable", "aliases": ["s"],
     "warn_upper_grade": True},
]
```

Each reader gets scoring, name resolution (key / name / aliases), a bingo card,
board presence, and a share of the family goal automatically. Readers without a
hand-authored bingo card get one generated from a default template.

## Endpoints

| Path | Purpose |
|---|---|
| `/board/` | Desktop game board |
| `/board/ipad` | iPad kiosk view |
| `/library/` | Books-read library |
| `/board.json`, `/library.json` | Raw data |
| `/slash/read`, `/slash/reading`, `/slash/book`, `/slash/bingo` | Mattermost slash commands |
| `/alexa` | Alexa skill endpoint (set `ALEXA_SKILL_ID`) |

Log a session from Mattermost:

```
/read alex "Frog and Toad Are Friends" pages=30
```

## Configuration

All configuration is via environment variables — see [`.env.example`](.env.example).
Everything is optional; with nothing set, the bot runs standalone with no
external integrations. Data persists in a SQLite file at `DB_PATH`
(default `/data/reading.db`).

## Known limitations

- The board HTML ([`board/index.html`](board/index.html)) has one hand-built
  section per reader; adding a third reader currently needs an HTML edit even
  though the backend is fully config-driven. See [`ROADMAP.md`](ROADMAP.md).
- The bundled book catalog ([`books.json`](books.json)) is one family's list —
  useful as a starting point; add your own with `/book`.

## License

MIT — see [LICENSE](LICENSE).
