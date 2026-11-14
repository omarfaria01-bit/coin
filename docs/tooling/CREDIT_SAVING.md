# Credit-saving playbook

Claude Pro session limits cannot be made infinite. The goal is to waste as few
Claude tokens as possible and move cheap or bulky work off the main Sonnet/Opus
session. Routing Claude Code itself through a third-party gateway is **optional**
and stays off until kiwi approves it in `coord/DECISIONS.md` (see
`docs/prompts/PROMPT_CLAUDE_CODE.md`). Never route secrets, security reviews, or
final merges.

## Do this first (no new keys)

1. **Haiku subagents** in `.claude/agents/`: `researcher`, `test-writer`,
   `reviewer-lite`, `data-puller`, `sim-runner`. Verbose output stays in the
   subagent context; only the summary returns. Subagent requests still count
   toward the same plan, but Haiku is much cheaper than Sonnet/Opus.
   Docs: https://code.claude.com/docs/en/sub-agents (Frontmatter reference lists `effort` and `omitClaudeMd`). `data-puller` does **not** set `omitClaudeMd`, because it has Bash + WebFetch and must load CLAUDE.md untrusted-content rules. `researcher` (read-only) may omit it.
2. **`/compact` while the cache is warm** (during a working session, not after a
   long idle gap). Warm compaction reuses the prompt cache. After a long pause
   the cache is cold and compaction is an expensive full re-read.
   Docs: https://code.claude.com/docs/en/prompt-caching and
   https://code.claude.com/docs/en/costs
3. **`/clear` between unrelated tasks.** `/compact` itself reads the whole
   conversation; if you do not need continuity, `/clear` costs nothing.
4. Keep `CLAUDE.md` short, disable unused MCP servers, and prefer `gh`/`rg`
   over always-on MCP tool lists.
5. Track usage with `ccusage` and Claude Code `/usage` **only where Claude Code actually runs** (kiwi's own sessions, not this bot computer). Grok's box may have the binary installed, but the usage that matters is kiwi's session.

## Offload to other CLIs (dedicated bot accounts only, no paid signup)

Do **not** sign in with kiwi's personal Google, OpenCode, or OpenRouter
account on the bot computer. That would put kiwi's Gmail/Drive (or equivalent)
session on a machine an agent drives, which is why Claude's login also stays
off this box (DECISIONS D6). If a login is needed, create a **dedicated account
for the bot only**: no payment method, no recovery email or phone tied to
kiwi's personal accounts.

- **Gemini CLI** (`gemini`): official Google CLI. Prefer an AI Studio API key
  in `GEMINI_API_KEY` (environment only, never the repo). A Google login is
  only acceptable on a dedicated bot Google account, never kiwi's personal
  one. Use it for research, drafts, and second opinions so those tokens never
  hit Claude. Models listed by `gemini --list-models` on 14 Nov 2026
  (Europe/Rome): `gemini-3.5-flash`, `gemini-3.1-flash-lite`, `gemini-2.5-pro`.
- **OpenCode** (`opencode`): free `opencode/*-free` models can run without
  login. If a provider login is required, use a dedicated bot account, not
  kiwi's.

**Free-tier privacy:** free-tier models (OpenRouter `:free`, free Gemini tier,
OpenCode free models) may log prompts and use them for training. Never send
them `.env` content, keys, unreleased launch details (pad, timing, wallet
addresses before they are public), or `coord/` strategy. They are fine for
public-docs research and generic code.

## Optional gateways (keys required, not enabled)

Templates (keys from env vars only):

- `docs/tooling/claude-code-router.config.example.json`
- `docs/tooling/litellm.config.example.yaml`
- Box copy of the CCR template: `~/.claude-code-router/config.example.json`

OpenRouter `:free` models used in the templates (checked via
https://openrouter.ai/api/v1/models on 14 Nov 2026, Europe/Rome):
`cohere/north-mini-code:free`, `recursive/flint-v1.0:free`,
`thinkingmachines/inkling-2-small:free`,
`nvidia/nemotron-3-ultra-550b-a55b:free`, `openrouter/free`.

Free-tier limits are typically 20 requests/minute and 50 requests/day unless
the OpenRouter account has purchased credits (then 1,000/day). Quality and
availability change; treat these as overflow, not as a replacement for Claude
on core money logic.

## What we did not enable or install

- Claude Code Router remains installed but **disabled** (no provider keys, no
  `ccr start`).
- LiteLLM is installed but **not running**.
- `BeehiveInnovations/pal-mcp-server` (formerly zen-mcp, 11.8k stars) was
  **not** installed: last commit 15 Dec 2025, so it fails the "active" bar.
- Qwen Code was **not** installed: the Qwen OAuth free tier ended 15 Apr 2026.

## Kiwi to-do (Italian)

Non usare il tuo account Google (o OpenCode/OpenRouter) personale sul
computer del bot. Se serve un login, crea un account dedicato solo per il
bot: niente metodo di pagamento, niente email o telefono di recupero
collegati ai tuoi account personali. Stessa regola di D6 per Claude.

1. **Gemini CLI (consigliato, piano gratuito)**
   - Preferisci una chiave di AI Studio in `GEMINI_API_KEY` (solo ambiente,
     mai nel repo): https://aistudio.google.com/apikey
   - Un login Google va fatto solo con un account Google **nuovo, del bot**.
   - Non serve una carta. Resta sul piano gratuito.
   - I modelli free possono registrare i prompt e usarli per l'addestramento:
     non inviare `.env`, chiavi, dettagli di lancio non pubblici o `coord/`.

2. **OpenCode (consigliato; i modelli `*-free` funzionano anche senza login)**
   - `cd ~/work/coin && opencode run -m opencode/deepseek-v4.1-flash-free -p "…"`
   - Se un login è richiesto, usa un account dedicato del bot, non il tuo.
   - Nessuna chiave va incollata in un file del repo.

3. **OpenRouter (solo se vuoi il routing verso modelli :free)**
   - Crea un account **del bot** su https://openrouter.ai (il piano free basta).
   - Crea una chiave su https://openrouter.ai/keys
   - Esportala come `OPENROUTER_API_KEY` nell'ambiente, non in git.
   - Non avviare `ccr` o LiteLLM e non puntare Claude Code al proxy finché
     non hai scritto `APPROVED` in `coord/DECISIONS.md` per il routing.
   - Limite tipico free: 20 richieste/minuto, 50/giorno.
   - Stesso avviso privacy dei modelli free: niente segreti né strategia.

4. **Non fare**
   - Non pagare abbonamenti extra.
   - Non accedere con i tuoi account personali su questa macchina.
   - Non incollare seed, chiavi wallet, o token in questi strumenti.
   - Non avviare CCR, LiteLLM, Gemini o OpenCode *sul repo* finché non
     decidi tu il routing in DECISIONS.md.
