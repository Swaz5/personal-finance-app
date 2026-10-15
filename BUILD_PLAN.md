# Personal Finance OS — Build Plan

Local-only. Single user. Three jobs: **where is my money going**, **am I on track**, **can I afford this**.

Drop this at the repo root so Claude Code can read it as context.

---

## 0. Scope lock

**In scope**
- Ingest transactions and balances from all accounts
- Categorize spending, detect recurring bills and subscriptions
- Cash flow: income, fixed vs. discretionary, trailing baselines
- Savings rate and net worth over time
- Retirement pacing as a scenario tool
- Affordability verdict for a specific purchase

**Explicitly out of scope** (say no now or it'll creep in)
- Portfolio allocation / drift / rebalancing analysis — you didn't ask for it
- Security recommendations — the app should never tell you what to buy
- Budgeting envelopes — different philosophy, different app, don't bolt it on
- Multi-user, auth, deployment — it runs on localhost, that's the point

**What it is:** a decision-support instrument. It surfaces numbers that make a decision obvious. It is not an advisor and shouldn't write like one.

---

## 1. Architecture

```
finance-os/
├── api/                     FastAPI
│   ├── main.py
│   ├── models.py            SQLModel tables
│   ├── db.py
│   ├── importers/
│   │   ├── base.py          Importer protocol — everything conforms
│   │   ├── csv_import.py    Phase 1
│   │   ├── simplefin.py     Phase 8
│   │   └── snaptrade.py     Phase 5
│   ├── engine/
│   │   ├── categorize.py    Rules → LLM fallback → manual override
│   │   ├── transfers.py     Transfer pair detection
│   │   ├── cashflow.py      Income, spend, baselines
│   │   ├── recurring.py     Subscription/bill detection
│   │   ├── projection.py    90-day forward cash
│   │   ├── affordability.py The payoff feature
│   │   └── retirement.py    Scenario projector
│   └── llm/
│       └── narrate.py       Explains numbers. Never computes them.
├── web/                     Vite + React + Tailwind
├── data/
│   ├── finance.db           gitignored
│   └── statements/          gitignored — raw CSVs
├── config/
│   └── mappings/            One YAML per institution's CSV format
└── .env                     gitignored
```

**Stack rationale:** FastAPI + SQLite because it's a familiar, well-supported shape. SQLModel over raw SQLAlchemy for less boilerplate. React over Streamlit because "professional looking" rules Streamlit out.

Lower-effort alternative if you want to move faster: FastAPI + HTMX + Tailwind, no build step, no separate frontend server. Real option — costs you portfolio value, saves you maybe 30% of the UI work.

---

## 2. Data model

This is the part that determines whether the app works. Get it wrong and every downstream number is quietly incorrect.

### Tables

**`institutions`** — id, name, kind (`bank` | `brokerage` | `card` | `loan`)

**`accounts`** — id, institution_id, name, type (`checking` | `savings` | `credit` | `brokerage` | `retirement` | `loan`), currency, external_id, is_active, include_in_net_worth

**`balances`** — id, account_id, as_of (date), current_cents, available_cents
> Time series, **not** a column on `accounts`. Without snapshot history you can never chart net worth, and net worth over time is half the value of this app.

**`transactions`** — id, account_id, posted_at, amount_cents, description_raw, merchant_normalized, category_id, is_transfer, transfer_pair_id, external_id, import_batch_id, content_hash

**`categories`** — id, name, parent_id, kind (`income` | `fixed` | `variable` | `discretionary` | `transfer`)

**`rules`** — id, match_pattern, match_type (`contains` | `regex`), set_category_id, priority

**`holdings`** — id, account_id, as_of, symbol, quantity, cost_basis_cents, market_value_cents
> Also a time series.

**`securities`** — symbol, name, asset_class

**`recurring`** — id, merchant_normalized, expected_amount_cents, cadence_days, last_seen, next_expected, confidence

**`goals`** — id, name, target_amount_cents, target_date, kind

**`import_batches`** — id, source, imported_at, file_name, row_count

**`settings`** — emergency_floor_cents, target_retirement_date, assumed_real_return, etc.

### Six rules you don't get to break

1. **Money is `int` cents. Never float.** `0.1 + 0.2 != 0.3` and you will not notice the drift until your net worth is off by $340.

2. **One sign convention, enforced at the importer boundary.** Recommended: from the account's perspective, outflow negative, inflow positive. Credit card purchase = negative, payment to the card = positive. Write it in a docstring. Every importer normalizes to it before anything touches the DB.

3. **Transfers are not spending.** Paying $2,000 from checking to your credit card is not $2,000 of spending — it's the same dollars moving. Naive finance apps show you spending 2–3x your real number and you stop trusting the app. Detection: opposite-signed, near-equal amounts across two of your accounts within ±3 days. Match them, set `transfer_pair_id`, exclude from all spend math.

4. **Imports are idempotent via content hash.** `sha256(account_id | posted_at | amount_cents | description_raw)`. CSVs overlap when you re-download, and duplicate transactions poison every average. API sources give you stable IDs; use those when available and fall back to the hash.

5. **Baselines use median, not mean.** One Costco run or one annual insurance payment shouldn't move your "normal" for that category. Trailing 6-month median per category.

6. **15–20 categories, max.** Sixty categories feels rigorous and guarantees you never look at the app again. Coarse categories you actually maintain beat fine ones you abandon.

---

## 3. Ingestion — the importer contract

Everything conforms to one interface so the source is swappable:

```python
class Importer(Protocol):
    def fetch(self, since: date) -> list[RawTransaction]: ...
    def balances(self) -> list[RawBalance]: ...
```

**Phase 1 — CSV.** One YAML mapping per institution: column names, date format, sign convention, amount column(s). Some banks use separate debit/credit columns instead of a signed amount — handle both.

**Phase 5 — SnapTrade Personal (free).** Personal API key, holdings-level positions. Signed requests — use their SDK rather than rolling it.

**Phase 8 — SimpleFIN ($15/yr).** Setup token → one-time exchange for a long-lived access URL. **The setup token is consumed on first use** — store the access URL immediately or you're re-doing the handshake. Respect the ~24 requests/day quota; exceeding it gets tokens disabled. Max 90-day window per request, so backfill in chunks.

---

## 4. The three engines

### Cash flow
- Monthly income = recurring inflows, transfers excluded
- Spend split into fixed / variable / discretionary via `category.kind`
- Trailing 3/6/12-month median per category
- **Recurring detection:** group by normalized merchant, look for ≥3 occurrences with stable amount (±10%) and consistent gap (±4 days). Assign a confidence score. This feeds the projection engine, so it's load-bearing — not a nice-to-have.

### Savings rate & pacing
- Savings rate = `(income − spending) / income`. Compute a second version that adds employer 401k match and pre-tax contributions, because the first number will look worse than reality.
- Net worth series = balance snapshots + holdings market value, per date.
- **Retirement pacing is a scenario tool, not a prediction.** Use *real* (inflation-adjusted) returns — 4%/5%/6% — not 10% nominal. Output three scenarios, never one number. A single point estimate on a 30-year projection is false precision, and the UI should show the assumptions on the same screen as the result.
- Worth computing: your Coast FI number — the amount that, untouched, reaches your target at your assumed return. It's a more actionable number than "you need $2.1M."

### Affordability — the reason to build this

A good affordability check is not "is there enough in checking." Four factors:

1. **Post-purchase cash vs. emergency floor.** Floor = N months of *fixed* expenses (you set N).
2. **Effect on the 90-day cash trough.** Project forward from known recurring bills and find the lowest point the account will hit. A $4k purchase today that's fine on paper isn't fine if your insurance premium and property tax both land in six weeks.
3. **Recurring vs. one-time.** A $30k car at $550/month is not a $30k decision — it's a permanent cut to your savings rate. Compute the new savings rate and show it next to the old one.
4. **Opportunity cost.** What that amount compounds to at your assumed real return over 10/20/30 years. Not to guilt you — to price the decision honestly.

Return a **green / yellow / red verdict with the actual numbers attached**, never a vibe. Yellow is the most useful outcome and most apps don't have it.

---

## 5. The LLM layer

**The hard rule: deterministic Python computes every number. The LLM only narrates numbers it was handed.**

LLMs get arithmetic subtly wrong in ways that look right. This is your actual money and you will not catch it. Non-negotiable.

**Good uses**
- Batch-categorize transactions the rules engine missed. Send description strings only, get back JSON `{id: category}`. Manual corrections write back a new rule, so the LLM's job shrinks every month.
- Normalize merchant strings (`SQ *BLUE BOTTLE #4471` → `Blue Bottle`).
- Write the explanation around a computed verdict.
- Answer freeform questions by calling tools against your own data.

**Privacy note:** using the Anthropic API means your transaction descriptions leave your machine. That's a normal tradeoff, but it contradicts "local-only" if you meant it strictly. Ollama with a small local model handles categorization fine and keeps everything on-device. Build the categorizer behind an interface so you can swap.

**Never:** recommend specific securities, or state a financial conclusion the deterministic engine didn't produce. The app surfaces facts; you make the call.

---

## 6. Security for a local app

- **Write `.gitignore` before you write any code.** `data/`, `*.db`, `.env`, `config/mappings/*.local.yaml`. Committing a finance DB to a public repo is a bad day.
- Encrypt access tokens at rest — `cryptography.Fernet`, key from a passphrase or Windows DPAPI. Not the whole DB; just the tokens.
- Bind the API to `127.0.0.1` explicitly. Not `0.0.0.0`.
- BitLocker on the drive. Free, and it's the actual protection for a local DB.
- Never log a full account number. Mask to last 4 at the importer boundary and store only the mask.

---

## 7. Design direction

**The reference is not a fintech marketing site.** Those are built to sell to strangers. This has one user who already trusts it, which means it can be far denser and more instrument-like than Mint or YNAB is allowed to be. Think aircraft panel, not landing page.

**Palette** — color is semantic only, never decorative:

```
--ground     #0F151E   deep navy-slate
--panel      #17202C   raised surface
--line       #28323F   hairlines
--ink        #E7EDF3   primary text
--ink-dim    #8393A5   labels, axes, secondary
--positive   #4FB286   inflow, on-track
--negative   #CC5F5F   outflow, off-track
--flag       #E0A458   caution — the yellow verdict
```

**Type** — IBM Plex Sans for UI, IBM Plex Mono for every number. Plex was designed for data-dense interfaces and the mono has proper tabular figures, so columns of numbers align. That's functional, not stylistic — misaligned decimal points in a finance app are a real defect.

**Signature element: the trough chart.** Your primary view isn't a balance line or a spending pie. It's a 90-day forward cash projection with the emergency floor drawn as a hard horizontal rule, and the lowest projected point called out. When you enter a purchase amount, the trough drops in real time toward the floor. That single interaction is the whole app. Build the dashboard around it.

**No pie charts.** They're the default answer and they're bad at the actual job. Use horizontal bars per category with a ghost marker at the trailing 6-month median — so you see *this month vs. your normal* at a glance, which is the only comparison that matters.

**Copy:** plain, active, specific. "You'd dip $340 below your floor on March 12" beats "This purchase may impact your financial health." Errors and empty states explain what to do next.

---

## 8. Build order

Each phase has a checkpoint. Don't advance until it passes.

**Phase 0 — Skeleton.** `.gitignore` first. venv, FastAPI, SQLite, SQLModel, one health endpoint, Vite+React+Tailwind shell hitting it.
*Checkpoint: `npm run dev` shows data from `uvicorn`.*

**Phase 1 — Model + CSV ingestion.** All tables. CSV importer with per-institution YAML mappings. Content-hash dedup. Transfer detection. Backfill 12 months from every account.
*Checkpoint: a transaction table where signs are right, transfers are flagged, and net worth matches what you'd get with a calculator. This is the phase that decides if the project works. Don't rush it.*

**Phase 2 — Categorization.** Category tree, rules engine, manual override in the UI that writes back a rule. LLM fallback only for what rules miss.
*Checkpoint: >90% of 12 months categorized and you agree with the categories.*

**Phase 3 — Cash flow engine.** Income, fixed/variable/discretionary, trailing medians, recurring detection.
*Checkpoint: it finds every subscription you actually have. If it misses one, the projection engine will lie to you later.*

**Phase 4 — Trough + affordability.** Forward projection, emergency floor setting, the four-factor verdict endpoint.
*Checkpoint: enter a real purchase you're actually considering. If the verdict disagrees with your gut, one of you is wrong — figure out which. That's the app earning its keep.*

**Phase 5 — Holdings + net worth.** SnapTrade Personal, or manual entry plus price refresh from a public market-data endpoint.
*Checkpoint: 12-month net worth chart.*

**Phase 6 — Retirement pacing.** Three-scenario projector with assumptions visible on screen.

**Phase 7 — Design pass.** Only now. Design against real data or you'll build for fake numbers and it'll break on contact with your actual finances.

**Phase 8 — Optional sync.** SimpleFIN behind the Phase 1 importer interface. A day's work if Phase 1 was built right.

---

## 9. Plugging into the business backbone

You want expenses and income feeding the wider ecosystem eventually. Two things to get right now so you don't have to unwind them:

- **Separate DBs, shared schema.** Personal ledger and business ledger stay in different SQLite files. Merging them feels efficient and is genuinely painful at tax time.
- **Expose this as a local read-only API.** `GET /api/summary`, `GET /api/cashflow`. The backbone queries it over localhost. Later, wrapping those endpoints as an MCP server is a small step — and SnapTrade already ships an MCP server for Personal accounts, so there's a working pattern to copy.

---

## 10. Traps

1. Floats for money.
2. Not detecting transfers — spending looks 2–3x real and you stop trusting the app.
3. Building sync first. It's the most fragile, least valuable part, and it's where this project dies.
4. Letting the LLM compute a number that appears in a decision.
5. Designing before real data is loaded.
6. Nominal returns in projections instead of real. 10% nominal is how you lie to yourself politely.
7. Mean instead of median for baselines.
8. Sixty categories.
9. Committing the DB or `.env`. Write the `.gitignore` in the first five minutes.
10. Building a "recommendations" feature before the affordability engine works. The recommendation *is* the affordability engine — everything else is narration.
