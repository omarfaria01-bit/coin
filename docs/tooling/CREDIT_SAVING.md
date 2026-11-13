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
   Docs: https://code.claude.com/docs/en/sub-agents
2. **`/compact` while the cache is warm** (during a working session, not after a
   long idle gap). Warm compaction reuses the prompt cache. After a long pause
   the cache is cold and compaction is an expensive full re-read.
   Docs: https://code.claude.com/docs/en/prompt-caching and
   https://code.claude.com/docs/en/costs
3. **`/clear` between unrelated tasks.** `/compact` itself reads the whole
   conversation; if you do not need continuity, `/clear` costs nothing.
4. Keep `CLAUDE.md` short, disable unused MCP servers, and prefer `gh`/`rg`
   over always-on MCP tool lists.
5. Track usage with `ccusage` and Claude Code `/usage`.

## Offload to other CLIs (kiwi login, no paid signup)

- **Gemini CLI** (`gemini`): official Google CLI, free tier after Google login.
  Use it for research, drafts, and second opinions so those tokens never hit
  Claude. Models listed by `gemini --list-models` on 14 Nov 2026 (Europe/Rome):
  `gemini-3.5-flash`, `gemini-3.1-flash-lite`, `gemini-2.5-pro`.
- **OpenCode** (`opencode`): after kiwi signs in, Zen free models can do
  parallel coding work in a separate agent.

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

Vedi la fine di questa sezione.

1. **Gemini CLI (consigliato, gratis con il tuo account Google)**
   - Sul computer del bot, in un terminale: `cd ~/work/coin && gemini`
   - Quando chiede l'accesso, accedi con il tuo account Google.
   - Non serve una carta. Resta sul piano gratuito.
   - Opzionale, per il proxy: crea una chiave su https://aistudio.google.com/apikey
     e mettila solo in una variabile d'ambiente `GEMINI_API_KEY` (mai nel repo).

2. **OpenCode Zen (consigliato, modelli free dopo il login)**
   - `cd ~/work/coin && opencode auth`
   - Completa il login del provider free/Zen che ti propone.
   - Nessuna chiave va incollata in un file del repo.

3. **OpenRouter (solo se vuoi il routing verso modelli :free)**
   - Crea un account su https://openrouter.ai (il piano free basta).
   - Crea una chiave su https://openrouter.ai/keys
   - Esportala come `OPENROUTER_API_KEY` nell'ambiente, non in git.
   - Non avviare `ccr` o LiteLLM e non puntare Claude Code al proxy finché
     non hai scritto `APPROVED` in `coord/DECISIONS.md` per il routing.
   - Limite tipico free: 20 richieste/minuto, 50/giorno.

4. **Non fare**
   - Non pagare abbonamenti extra.
   - Non incollare seed, chiavi wallet, o token in questi strumenti.
