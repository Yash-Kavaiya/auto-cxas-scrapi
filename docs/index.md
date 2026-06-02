# auto-cxas-scrapi Documentation

`auto-cxas-scrapi` is an autonomous optimization loop for Google Cloud
[CX Agent Studio (CXAS)](https://cloud.google.com/customer-engagement-ai).
It proposes targeted mutations to your agent configuration, evaluates them
against 54 golden tests across 5 eval dimensions, keeps improvements, and
discards regressions — all without human intervention.

## Pages

| Page | What it covers |
|---|---|
| [Architecture](architecture.md) | Component breakdown, data-flow, convergence, mutation diversity |
| [Configuration](configuration.md) | All environment variables with types, defaults, and examples |
| [Eval Types](eval-types.md) | All 5 eval types, their columns, and golden-test mapping |
| [Deployment](deployment.md) | Local, Docker, and Cloud Run Job deployment guides |
| [Adapters](adapters.md) | Every CXAS adapter with methods and retry policy |
| [Development](development.md) | Local dev setup, testing, adding new mutation types |

---

## How the loop works

```
┌─────────────────────────────────────────────────────────────────┐
│  1. RANK   MultiObjectivePlanner identifies the worst-scoring   │
│           eval dimension (task_success, latency, etc.)          │
│                                                                 │
│  2. PLAN   LLMPlanner generates a targeted mutation for that    │
│           dimension using Gemini / OpenAI / Anthropic.          │
│           Mutation diversity is enforced via mutation_history.  │
│                                                                 │
│  3. PATCH  agent_config.py is patched in-place and committed.   │
│                                                                 │
│  4. EVAL   evaluate.py runs all 5 eval types in parallel via    │
│           ThreadPoolExecutor and returns a 0-1 eval_score.      │
│                                                                 │
│  5. DECIDE If score > baseline + min_delta -> KEEP (EMA update).│
│           Otherwise -> DISCARD (git reset --soft HEAD~1).       │
│                                                                 │
│  6. CHECK  If the last N scores all fall within convergence_    │
│           threshold -> stop. Otherwise go to step 1.            │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key files

| File | Role | AI may edit? |
|---|---|---|
| `agent_config.py` | Agent configuration — the only mutation target | Yes |
| `evaluate.py` | Eval harness — fixed reference point | Never |
| `auto_loop.py` | Loop orchestration | Never |
| `golden_tests.yaml` | 54 built-in test cases | Never |
| `results.tsv` | Append-only experiment journal | Never |
| `program.md` | Human-readable loop strategy | Read-only reference |

---

## Score formula (v2)

```
eval_score = task_success        x 0.35
           + turn_pass_rate      x 0.20
           + tool_pass_rate      x 0.20
           + latency_score       x 0.15
           + guardrail_pass_rate x 0.07
           + callback_pass_rate  x 0.03
```

All weights sum to 1.0 and are enforced in CI.

-> See [Eval Types](eval-types.md) for how each dimension is measured.
