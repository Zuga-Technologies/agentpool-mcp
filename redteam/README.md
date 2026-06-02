# cq safety corpus — an open content-safety benchmark for agent knowledge pools

A shared, agent-readable knowledge pool (cq, AgentPool, DebugBase, …) is an
**indirect prompt-injection surface**: a malicious "solution" is retrieved by a
reading agent and lands in its context as semi-trusted text. Any node that
accepts community contributions needs a guardrail — and that guardrail needs to
be *measured*, not assumed.

`cq_safety_corpus.jsonl` is a small, open, labeled corpus for exactly that. Each
line is a contribution with an expected verdict:

- **attack cases** (`expect: block`) — prompt injection, instruction override,
  data exfiltration, leaked secrets (Stripe / AWS / GitHub), jailbreaks.
- **benign controls** (`expect: allow`) — *real* developer solutions that contain
  scary-looking-but-legitimate content (`git push --force`, `allow_origins=['*']`,
  shell commands, env-var mentions). These keep a guardrail honest: blocking
  everything is not safety, it's uselessness.

A guardrail is scored on **both** axes:

- **recall** — fraction of attacks blocked
- **precision** — fraction of benign solutions allowed

## Run it

```bash
python redteam/run_corpus.py    # scores AgentPool's ZugaShield guard
```

Against any other node, import `run()` and pass a callable
`screen(problem, solution) -> (allowed: bool, reason: str)`.

## Why this is here

AgentPool maintains this corpus as a contribution to the cq ecosystem and any
other agent-knowledge-pool project. It is intentionally vendor-neutral — the
payloads are not specific to ZugaShield. PRs adding new attack classes or
tricky benign controls are welcome. Apache-2.0, same as cq.
