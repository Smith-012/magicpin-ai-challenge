# Vera Bot — magicpin AI Challenge Submission

## Approach

**Model**: Google Gemini 2.0 Flash (temperature=0 for determinism)

**Architecture**: Single-prompt LLM composer with trigger-kind dispatch, built on FastAPI.

### How it works

1. **Context Store** — all 4 context types (category, merchant, trigger, customer) are stored in-memory with version tracking. Higher version replaces atomically; same version is a no-op (idempotent).

2. **Tick Handler** — on each `/v1/tick`, the bot inspects all `available_triggers`, looks up the associated merchant + category + optional customer, checks suppression keys, and calls the LLM composer for each eligible trigger.

3. **Composer** — a single Gemini prompt receives all 4 context layers and returns: `body`, `cta`, `send_as`, `suppression_key`, `rationale`. The prompt is structured to enforce:
   - Specificity (real numbers from context)
   - Category voice (clinical for dentists, warm for salons, etc.)
   - Hindi-English code-mix when merchant language includes `hi`
   - Single CTA at the end of message

4. **Reply Handler** — on `/v1/reply`:
   - **Auto-reply detection**: regex patterns match canned WA Business replies → escalates: send (first) → wait 24h (second) → end (third+)
   - **Intent transition**: detects "ok let's do it / confirm / go ahead" → switches immediately to action mode (no more qualifying questions)
   - **Hostile/opt-out**: detects "stop / spam / not interested" → graceful `end`
   - **General replies**: Gemini continues the conversation in-context

5. **Suppression**: Each trigger has a `suppression_key` — once sent, it's tracked in-memory and won't fire again on the same test run.

### Tradeoffs

- **In-memory state**: Suitable for the 60-minute test window. Would use Redis for production.
- **Single prompt**: Simpler than multi-step chain, but means the prompt must handle all trigger kinds. A routing layer by `trigger.kind` would improve quality further.
- **Gemini 2.0 Flash**: Chosen for speed (<5s per call) and free API access. GPT-4o or Claude would score marginally better on nuance.

### What additional context would help most

1. **Real open slot data** for customer-facing recall messages (we currently ask the merchant to confirm slots)
2. **Actual conversation history** from previous sessions (current context only has last 2 turns)
3. **Merchant language detection per-turn** (language can switch mid-conversation)
4. **Peer stats scoped to exact locality** (current data is city-level)

## Running locally

```bash
pip install -r requirements.txt
set GEMINI_API_KEY=your_key_here      # Windows
python bot.py
```

Then test:
```bash
python judge_simulator.py
```

## Deployment

Deployed on Render (free tier) — permanent public URL, no PC required.
