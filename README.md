# Wealth Advisor Assistant — a lightweight multi-agent system

A small, framework-free multi-agent system that simulates a **Wealth Advisor
Assistant**. It ingests a client's financial data, enriches it from a (mock)
CRM and market-data API, runs deterministic financial analysis including
anomaly detection, optionally pauses for a human review of high-severity
findings, and produces a structured advisory report.

It is intentionally built from first principles (plain Python, no agent
framework) so the agent/tool abstractions, orchestration, and error handling
are fully visible rather than hidden behind a library.

> **Runs with zero setup and zero API keys.** The entire pipeline — including
> anomaly detection — is deterministic and offline. An LLM (Claude) is used
> *only* to phrase the final advisory narrative, and only if an API key is
> present; otherwise a templated narrative is produced instead.

---

## Quick start

```bash
# Python 3.10+ (developed on 3.11). No install step is required to run.
cd wealth-advisor-agents

# Run on a bundled sample client (headless, auto-approves the HITL checkpoint):
python run.py --client data/clients/client_002.json --yes

# List the bundled sample clients:
python run.py --list-clients

# Optional: install dev/optional deps (pytest + the optional LLM client):
pip install -r requirements.txt
python -m pytest -q
```

`python run.py ...` and `python -m wealth_advisor ...` are equivalent.

---

## Architecture design

The system is a **pipeline of specialized agents coordinated by a central
orchestrator**. Each agent reaches the outside world only through **tools**
resolved by name from a registry, so agents never depend on raw
implementations. A shared `SessionContext` (short-term memory + handoff slots)
is threaded through the run; a JSON-backed long-term memory persists summaries
across runs.

```
                         ┌───────────────────────────┐
   client JSON  ───────► │     OrchestratorAgent      │  run_id · routing · flow
                         │  plan → route → aggregate  │  degraded-mode · memory I/O
                         └───────────────────────────┘
                            │         │            │
            ┌───────────────┘         │            └──────────────────┐
            ▼                         ▼                               ▼
   ┌─────────────────┐      ┌──────────────────┐           ┌────────────────────┐
   │ DataFetcherAgent│      │  AnalyzerAgent   │           │   AdvisorAgent     │
   └─────────────────┘      └──────────────────┘           └────────────────────┘
            │ (tools only)            │ (tools only)                 │ (tools only)
            ▼                         ▼                              ▼
   financial_data           anomaly_detection              llm  (Claude, optional)
   crm_api (mock API)       + analytics.py metrics          └─► templated fallback
   market_data (mock API)
            │                         │                              │
            └──────── SessionContext (short-term memory + trace) ────┘
                                      │
                      LongTermMemory (JSON store, cross-run history)
                                      │
                   [ HITL checkpoint runs between Analyze → Advise ]
```

### Why this shape

- **A fixed, inspectable pipeline, not an LLM-planned one.** For a regulated,
  advice-giving workflow, predictable and auditable routing matters more than
  open-ended autonomy. The orchestrator runs a declared plan
  (`data_fetcher → analyzer → hitl_checkpoint → advisor`) and logs every step.
- **Separation of concerns.** Pure math (`analytics.py`), side-effecting
  integrations (`tools/`), decision logic (`agents/`), and presentation
  (`reporting.py`) are separate and independently testable.
- **Deterministic core + optional LLM.** Numbers and recommendations are always
  computed deterministically; the LLM only turns them into prose. This keeps
  results reproducible and prevents the model from inventing figures.

---

## Agent interactions and flow

1. **OrchestratorAgent** (`agents/orchestrator.py`) builds the plan, creates the
   `SessionContext`, and routes between agents, handling failures and degraded
   mode.
2. **DataFetcherAgent** loads + validates the client JSON (`financial_data`
   tool), enriches it with the CRM profile (`crm_api`) and market benchmarks
   (`market_data`), and emits a normalized `ClientProfile`. Enrichment failures
   are **non-fatal** → it continues in *degraded mode* and records warnings.
3. The orchestrator then injects the client's **most recent prior run** from
   long-term memory into the context.
4. **AnalyzerAgent** computes portfolio metrics (`analytics.compute_portfolio_metrics`)
   and runs the `anomaly_detection` tool, comparing against the prior run to mark
   **recurring** anomalies and AUM/trend changes. It emits an `AnalysisResult`.
5. **HITL checkpoint** (`hitl.py`) runs if there are HIGH-severity findings and
   the session is interactive; otherwise it auto-approves and records why.
6. **AdvisorAgent** maps findings → prioritized `Recommendation`s and an overall
   `risk_posture`, then generates the narrative (LLM if available, else
   template). It emits the final `AdvisoryReport`.
7. The orchestrator **persists** a run summary to long-term memory and returns
   the populated context; the CLI renders it and writes the JSON artifacts.

---

## Key components

### Tool usage abstraction (`tools/base.py`)
- Every tool subclasses `Tool` and implements `_execute`. The base `run()` adds
  timing, logging, and retries, and **never raises** — it returns a uniform
  `ToolResult{ok, data, error, meta}` envelope.
- Agents resolve tools by **name** via a `ToolRegistry`
  (`self.tools.get("crm_api")`), so no agent imports a concrete tool. Swapping
  the mock CRM for a real one is a one-line registry change.
- Tools: `financial_data`, `crm_api` (mock, retryable, failure-injectable),
  `market_data` (mock, retryable), `anomaly_detection`, `llm` (optional).

### Anomaly detection (`tools/anomaly_tool.py`) — explainable by design
Rule-based + statistical, so every finding carries concrete evidence and an
explanation (no black-box model, no training data needed):
- **Concentration risk** — any single holding over the configured % of AUM.
- **Allocation drift** — asset-class weight vs the client's target band.
- **Large transaction** — a single transaction large relative to AUM.
- **Statistical outlier** — plain z-score **and** a robust **MAD-based modified
  z-score**; on small samples a lone extreme value inflates the standard
  deviation (and even an IQR fence) and masks itself, whereas the median/MAD
  resist it.
- **Duplicate transaction** — same type/symbol/amount within a short window.
- **Negative cash**, **cash drag**, **above-average fees**.

All thresholds live in one place: `config.AnomalyThresholds`.

### Memory layer
- **Short-term** (`memory/short_term.py`): per-run working memory inside
  `SessionContext` — facts, notes, and a structured event trace.
- **Long-term** (`memory/long_term.py`): a JSON store keyed by `client_id`
  holding a compact summary of each run, used to detect recurring anomalies and
  AUM changes since the last review.

### Human-in-the-loop (`hitl.py`)
Between analysis and advice, a reviewer can **approve**, **dismiss** false
positives, **re-rate** severity, or **add a note** to HIGH-severity findings.
It **auto-skips** (recording the reason) when nothing is high-severity or the
run is non-interactive (`--yes` / no TTY), so it never blocks CI.

### Error handling
- Tools return `ToolResult` instead of raising; agents inspect `ok` and
  **degrade gracefully** (missing CRM → financial-only; missing fields →
  defaults + warnings; LLM down → templated narrative).
- "API" tools **retry with backoff**; set `WA_SIMULATE_CRM_FAILURE=1` to force a
  CRM outage and watch the retry → fallback path.
- Only a fatal input error (unreadable file, missing `client_id`) stops the run,
  surfaced as a clear message + non-zero exit (not a traceback).

### Logging / observability
- Structured logs (`logging_config.py`) carry the `run_id` and go to the console
  (stderr) **and** a per-run file under `outputs/logs/`.
- Every agent step, tool call (name, ok/err, latency, retries), routing
  decision, and HITL action is logged, and a machine-readable **run trace** is
  written to `outputs/<run_id>_trace.json`.

---

## Project structure

```
wealth-advisor-agents/
├── run.py                       # CLI entrypoint (== python -m wealth_advisor)
├── requirements.txt             # optional runtime deps + pytest
├── .env.example                 # optional config (API key, model, flags)
├── data/
│   ├── clients/                 # 3 sample clients (healthy / anomalous / edge)
│   ├── crm_db.json              # mock CRM backing store
│   └── market_data.json         # mock benchmarks / index returns / avg fees
├── outputs/                     # generated reports, traces, logs (gitignored)
│   └── samples/                 # committed example outputs (see below)
├── wealth_advisor/
│   ├── cli.py  config.py  logging_config.py  context.py  schemas.py
│   ├── analytics.py  errors.py  hitl.py  reporting.py
│   ├── agents/  base.py  orchestrator.py  data_fetcher.py  analyzer.py  advisor.py
│   ├── tools/   base.py  financial_data_tool.py  crm_tool.py  market_data_tool.py
│   │            anomaly_tool.py  llm_tool.py
│   └── memory/  short_term.py  long_term.py
└── tests/                       # pytest suite (offline, no LLM)
```

---

## CLI usage

```bash
python run.py [--client PATH] [--output DIR] [--yes|--no-hitl]
              [--format text|json] [--log-level LEVEL] [--list-clients]
```

| Flag | Meaning |
|---|---|
| `--client` | Client JSON to analyze (default: `data/clients/client_001.json`). |
| `--yes` / `--no-hitl` | Skip the interactive HITL prompt (auto-approve). |
| `--format` | Console output: `text` (default) or `json`. Files are always written. |
| `--output` | Directory for the report + trace artifacts (default `outputs/`). |
| `--log-level` | `DEBUG` / `INFO` / `WARNING` / `ERROR`. |
| `--list-clients` | List bundled sample clients and exit. |

---

## Sample input / output

Three bundled clients exercise the main paths:

| Client | File | Demonstrates |
|---|---|---|
| **Jane Chen** (C001) | `client_001.json` | Healthy, on-target portfolio → no anomalies, `stable` posture. |
| **Robert Alvarez** (C002) | `client_002.json` | Concentration, allocation drift, large & outlier & duplicate transactions, pending KYC → `high` posture, HITL. |
| **Sofia Minimal** (C003) | `client_003.json` | Missing CRM record, missing fields, empty transactions → **degraded mode**. |

Committed example outputs live in [`outputs/samples/`](outputs/samples/):
`client_00X_console.txt` (human-readable reports) plus
`client_002_report.json` and `client_002_trace.json` (structured report + run
trace).

**Input (excerpt of `client_002.json`):**
```json
{
  "client_id": "C002",
  "name": "Robert Alvarez",
  "target_allocation": { "equity": 0.60, "fixed_income": 0.30, "cash": 0.10 },
  "accounts": [{ "account_id": "A1", "type": "brokerage", "cash_balance": 25000,
    "holdings": [{ "symbol": "TSLA", "asset_class": "equity", "quantity": 1000, "price": 225 }] }],
  "transactions": [{ "date": "2026-10-05", "type": "buy", "symbol": "TSLA", "amount": 150000 }]
}
```

**Output (excerpt):** risk posture `HIGH`; anomalies include *Over-concentration
in TSLA (45%)*, *Allocation drift* (equity +25% / fixed income −20%), *Large buy
(30% of AUM)*, an *outlier sell*, and a *duplicate buy*; recommendations are
prioritized and a *Complete KYC* item is added from the CRM profile. See the
full report in `outputs/samples/client_002_console.txt`.

---

## Testing

```bash
pip install -r requirements.txt   # or just: pip install pytest
python -m pytest -q
```

The suite (30 tests, fully offline — the LLM tool is never registered in tests)
covers: each anomaly detector, the tool envelope/registry and failure/retry
paths, agent behavior and degraded mode, the full orchestrated pipeline,
long-term memory recall driving a second run, and the observability trace.

---

## Key decisions and trade-offs

- **Custom orchestration vs. a framework (LangGraph/CrewAI).** Chose plain
  Python so the agent/tool abstraction — the thing being evaluated — is explicit
  and dependency-light. Trade-off: no built-in graph/visual tooling; acceptable
  for a bounded pipeline.
- **Deterministic core + optional LLM narrative.** Prioritizes reproducibility,
  auditability, and zero-key runnability over an "all-LLM" design. Trade-off:
  less open-ended reasoning; mitigated by a clean seam (`llm` tool) to expand it.
- **`dataclasses` vs. pydantic.** No hard dependency and transparent
  (de)serialization, at the cost of hand-written validation in the constructors.
- **JSON-file long-term memory vs. a database.** Simple and dependency-free.
  Trade-off: no concurrency or rich querying — the `LongTermMemory` interface is
  deliberately small so a swap to SQLite / a vector store is localized.
- **Explainable rule+statistical anomaly detection vs. ML (e.g. IsolationForest).**
  Chosen for explainability and because there's no labeled training data. MAD is
  used for robustness on small samples.
- **Synchronous execution.** The pipeline is short and I/O is mocked; sync keeps
  it readable. An async upgrade would localize to the tool layer.

---

## Assumptions

- Input client data follows the shape in `data/clients/*.json`; `client_id` is
  the only strictly required field, and `market_value` is derived from
  `quantity × price` when omitted.
- The CRM and market-data "APIs" are mocked by local JSON files with simulated
  latency and injectable failure; swapping in real HTTP clients is a tool-level
  change.
- Anomaly thresholds (`config.AnomalyThresholds`) are reasonable defaults, not
  calibrated to a specific firm's policy.
- "Transactions" are cash-flow amounts; `amount` is treated by magnitude for
  outlier detection.
- The LLM narrative is advisory phrasing only and is not required for a complete,
  correct report.

---

## Possible extensions

- Swap mock tools for real CRM / market-data HTTP clients (registry change only).
- Move long-term memory to SQLite or a vector store for semantic recall of notes.
- Add an `IsolationForest` detector behind the same `anomaly_detection` tool
  interface (guarded optional dependency).
- Expose a FastAPI endpoint reusing `OrchestratorAgent` unchanged.
