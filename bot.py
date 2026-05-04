#!/usr/bin/env python3
"""
magicpin AI Challenge — Vera Bot
=================================
FastAPI server exposing all 5 required endpoints.
Uses Google Gemini API for message composition.

HOW TO RUN:
  1. pip install fastapi uvicorn google-generativeai
  2. Set GEMINI_API_KEY in this file (or as env variable)
  3. uvicorn bot:app --host 0.0.0.0 --port 8080

ENDPOINTS:
  GET  /v1/healthz
  GET  /v1/metadata
  POST /v1/context
  POST /v1/tick
  POST /v1/reply
"""

import os
import time
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ─────────────────────────────────────────────────────────────────
# CONFIGURATION — Edit these
# ─────────────────────────────────────────────────────────────────

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")   # <-- paste your key or set env var
GEMINI_MODEL   = "gemini-2.0-flash"                      # fast + smart + free
TEAM_NAME      = "Smith's Bot"
TEAM_MEMBERS   = ["Patel Smith Shaileshbhai"]
CONTACT_EMAIL  = "smithsp5177@gmail.com"

# ─────────────────────────────────────────────────────────────────
# APP SETUP
# ─────────────────────────────────────────────────────────────────

app   = FastAPI(title="Vera Bot", version="1.0.0")
START = time.time()

# In-memory stores
contexts:      dict[tuple, dict] = {}   # (scope, context_id) -> {version, payload}
conversations: dict[str, list]   = {}   # conversation_id -> [turns]
suppressed:    set[str]          = set() # suppression keys already sent
ended_convs:   set[str]          = set() # conversation_ids that were ended

# ─────────────────────────────────────────────────────────────────
# GEMINI CLIENT
# ─────────────────────────────────────────────────────────────────

def call_gemini(prompt: str, system: str = "") -> str:
    """Call Gemini API and return the text response."""
    import time
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    
    # Try up to 3 times to handle 429 Rate Limits
    for attempt in range(3):
        try:
            model = genai.GenerativeModel(
                model_name=GEMINI_MODEL,
                system_instruction=system if system else None,
                generation_config={"temperature": 0.0, "max_output_tokens": 1024, "response_mime_type": "application/json"}
            )
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            if "429" in str(e) and attempt < 2:
                time.sleep(4 * (attempt + 1))
                continue
            return f'{{"error": "{e}"}}'
    return "{}"


def call_gemini_json(prompt: str, system: str = "") -> dict:
    """Call Gemini and parse JSON from response."""
    raw = call_gemini(prompt, system)
    # Strip markdown code fences if present
    raw = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try extracting JSON object
        match = re.search(r'\{[\s\S]*\}', raw)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
        return {}

# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────

def get_context(scope: str, context_id: str) -> Optional[dict]:
    entry = contexts.get((scope, context_id))
    return entry["payload"] if entry else None


def get_merchant(merchant_id: str) -> Optional[dict]:
    return get_context("merchant", merchant_id)


def get_category(slug: str) -> Optional[dict]:
    return get_context("category", slug)


def get_customer(customer_id: str) -> Optional[dict]:
    return get_context("customer", customer_id) if customer_id else None


def get_trigger_payload(trigger_id: str) -> Optional[dict]:
    return get_context("trigger", trigger_id)


def is_auto_reply(message: str) -> bool:
    """Detect WhatsApp Business canned auto-replies."""
    patterns = [
        r"thank you for contact",
        r"our team will (respond|get back|reply)",
        r"we have received your (message|query|request)",
        r"automated (message|response|reply)",
        r"this is an auto",
        r"aapki jaankari ke liye.*shukriya",
        r"main ek automated assistant",
        r"hum jald.*sampark karenge",
        r"we will get back to you",
        r"office hours.*back to you",
    ]
    msg_lower = message.lower()
    return any(re.search(p, msg_lower) for p in patterns)


def is_explicit_intent(message: str) -> bool:
    """Detect when merchant commits to action."""
    patterns = [
        r"\b(yes|haan|ha|ok|okay)\b.*\b(do it|karo|chalte|let'?s go|proceed|confirm|sure|bilkul|zaroor)\b",
        r"\b(let'?s do it|kar do|go ahead|start karo|shuru karo|aage badho)\b",
        r"\b(ok let'?s|ok lets)\b",
        r"\bwhat'?s next\b",
        r"\bproceed\b",
        r"\bconfirm\b",
    ]
    msg_lower = message.lower()
    return any(re.search(p, msg_lower) for p in patterns)


def is_hostile_or_opt_out(message: str) -> bool:
    """Detect hard opt-outs and hostile messages."""
    patterns = [
        r"\b(stop|unsubscribe|opt.?out|remove me|don'?t (message|contact|bother|send))\b",
        r"\b(not interested|koi zaroorat nahi|mujhe nahi chahiye|mat karo|band karo)\b",
        r"\b(spam|useless|bakwaas|bekar|irritating|annoying)\b",
        r"stop messaging",
        r"leave me alone",
        r"never contact",
    ]
    msg_lower = message.lower()
    return any(re.search(p, msg_lower) for p in patterns)


def build_languages_hint(merchant: dict) -> str:
    langs = merchant.get("identity", {}).get("languages", ["en"])
    if "hi" in langs and "en" in langs:
        return "Use natural Hindi-English code-mix (Hinglish). Mix freely like 'Dr. Meera, JIDA ka latest research aaya hai...'"
    elif "ta" in langs:
        return "Use English primarily, occasional Tamil words of greeting are fine."
    elif "te" in langs:
        return "Use English primarily, occasional Telugu words of greeting are fine."
    elif "mr" in langs:
        return "Use English primarily, occasional Marathi words are fine."
    return "Use clear, professional English."


# ─────────────────────────────────────────────────────────────────
# COMPOSER
# ─────────────────────────────────────────────────────────────────

COMPOSER_SYSTEM = """You are Vera, magicpin's AI merchant assistant. You compose WhatsApp messages for Indian merchants.

RULES (follow strictly):
1. Be SPECIFIC — use real numbers, dates, names from the context. Never invent data.
2. Keep it SHORT — max 3-4 sentences. WhatsApp is not email.
3. ONE CTA only — binary YES/STOP or one open question at the end.
4. NO preambles — don't start with "I hope you're doing well" or "I'm Vera".
5. NO fake data — only use facts from the provided context.
6. VOICE match — dentists: peer/clinical tone. Salons: warm/friendly. Restaurants: operator-to-operator. Gyms: coaching. Pharmacies: trustworthy.
7. CTA at the END — the ask should be the last sentence.
8. Respond in JSON only with keys: body, cta, send_as, suppression_key, rationale

CTA values: "open_ended" | "binary_yes_no" | "binary_confirm_cancel" | "multi_choice_slot" | "none"
send_as values: "vera" (merchant-facing) | "merchant_on_behalf" (customer-facing)"""


def compose_message(category: dict, merchant: dict, trigger: dict, customer: Optional[dict] = None) -> dict:
    """Main LLM composer — calls Gemini to compose the WhatsApp message."""

    merchant_name = merchant.get("identity", {}).get("name", "Merchant")
    owner_name    = merchant.get("identity", {}).get("owner_first_name", "")
    trigger_kind  = trigger.get("kind", "unknown")
    lang_hint     = build_languages_hint(merchant)

    # Build focused context summary
    perf     = merchant.get("performance", {})
    signals  = merchant.get("signals", [])
    offers   = [o["title"] for o in merchant.get("offers", []) if o.get("status") == "active"]
    cat_slug = category.get("slug", "")
    peer_ctr = category.get("peer_stats", {}).get("avg_ctr", 0)

    # Digest item lookup
    digest_item = {}
    trg_payload = trigger.get("payload", {})
    top_item_id = trg_payload.get("top_item_id", "")
    if top_item_id:
        for d in category.get("digest", []):
            if d.get("id") == top_item_id:
                digest_item = d
                break
    if not digest_item and category.get("digest"):
        digest_item = category["digest"][0]

    # Conversation history (last 2 turns)
    history = merchant.get("conversation_history", [])[-2:]
    history_str = ""
    for h in history:
        role = "Vera" if h.get("from") == "vera" else "Merchant"
        history_str += f"{role}: {h.get('body', '')[:100]}\n"

    customer_str = ""
    if customer:
        cust_id   = customer.get("identity", {})
        cust_rel  = customer.get("relationship", {})
        cust_state = customer.get("state", "")
        customer_str = f"""
CUSTOMER CONTEXT:
- Name: {cust_id.get('name', '')}
- Language: {cust_id.get('language_pref', 'en')}
- State: {cust_state}
- Last visit: {cust_rel.get('last_visit', '')}
- Visits total: {cust_rel.get('visits_total', 0)}
- Services: {cust_rel.get('services_received', [])}
- Preference: {customer.get('preferences', {}).get('preferred_slots', '')}
"""

    prompt = f"""Compose the next WhatsApp message for this merchant.

TRIGGER (WHY NOW):
- Kind: {trigger_kind}
- Source: {trigger.get('source', '')}
- Urgency: {trigger.get('urgency', 2)}
- Payload: {json.dumps(trg_payload)}

MERCHANT:
- Business: {merchant_name} ({owner_name})
- Category: {cat_slug}
- City/Area: {merchant.get('identity', {}).get('locality', '')}, {merchant.get('identity', {}).get('city', '')}
- Subscription: {merchant.get('subscription', {}).get('status', '')} ({merchant.get('subscription', {}).get('plan', '')})
- Days remaining: {merchant.get('subscription', {}).get('days_remaining', 'N/A')}
- Performance (30d): views={perf.get('views')}, calls={perf.get('calls')}, CTR={perf.get('ctr')} (peer median={peer_ctr})
- 7d delta: views {perf.get('delta_7d', {}).get('views_pct', 0):+.0%}, calls {perf.get('delta_7d', {}).get('calls_pct', 0):+.0%}
- Active offers: {offers if offers else 'None'}
- Signals: {signals}
- Customer aggregate: {merchant.get('customer_aggregate', {})}
- Recent conversation:
{history_str or '(No history)'}

CATEGORY ({cat_slug.upper()}):
- Voice: {category.get('voice', {}).get('tone', '')} — {lang_hint}
- Taboos (never use): {category.get('voice', {}).get('vocab_taboo', [])}
- Peer stats: avg CTR={peer_ctr}, avg rating={category.get('peer_stats', {}).get('avg_rating', '')}
- Relevant digest item: {json.dumps(digest_item) if digest_item else 'None'}
- Active offers available: {[o['title'] for o in category.get('offer_catalog', [])[:3]]}
- Seasonal beat: {category.get('seasonal_beats', [{}])[0].get('note', '') if category.get('seasonal_beats') else ''}
{customer_str}

TASK: Write ONE WhatsApp message. Use a compulsion lever: specificity, loss aversion, social proof, curiosity, or reciprocity.
{f"This is a CUSTOMER-FACING message (send_as=merchant_on_behalf) — write from merchant's perspective." if customer else "This is MERCHANT-FACING (send_as=vera)."}

Return JSON only:
{{
  "body": "<the message text, max 4 sentences>",
  "cta": "<open_ended|binary_yes_no|binary_confirm_cancel|multi_choice_slot|none>",
  "send_as": "<vera|merchant_on_behalf>",
  "suppression_key": "<unique key like 'trigger_kind:merchant_id:YYYY-WNN'>",
  "rationale": "<1-2 sentence explanation of why this message, what lever used>"
}}"""

    result = call_gemini_json(prompt, COMPOSER_SYSTEM)

    # Fallback defaults if LLM fails
    if not result.get("body"):
        result = {
            "body": f"Hi {owner_name or merchant_name}, checking in on your magicpin profile. Want me to review what's working best for you this week?",
            "cta": "binary_yes_no",
            "send_as": "vera",
            "suppression_key": f"fallback:{merchant.get('merchant_id', 'unknown')}:{datetime.now().strftime('%Y-W%V')}",
            "rationale": "Fallback message — LLM composition failed."
        }

    # Ensure suppression key exists
    if not result.get("suppression_key"):
        result["suppression_key"] = f"{trigger_kind}:{merchant.get('merchant_id', 'x')}:{datetime.now().strftime('%Y-W%V')}"

    return result


def compose_reply(conversation_id: str, merchant_id: str, message: str, turn_number: int, from_role: str = "merchant", customer_id: Optional[str] = None) -> dict:
    """Compose a reply to a message in an ongoing conversation."""

    history = conversations.get(conversation_id, [])

    # If message is from a customer, act as the merchant on behalf
    if from_role == "customer":
        customer = get_customer(customer_id) if customer_id else None
        cust_name = customer.get("identity", {}).get("name", "Customer") if customer else "Customer"
        merchant = get_merchant(merchant_id)
        owner_name = merchant.get("identity", {}).get("owner_first_name", "Merchant") if merchant else "Merchant"
        
        prompt = f"""You are {owner_name}, the business owner. A customer ({cust_name}) just replied: "{message}".
Previous conversation: {json.dumps(history[-3:] if len(history) >= 3 else history)}

Reply naturally to the customer, confirming their request or answering their question.
Keep it extremely brief (1-2 sentences). You are acting as the merchant.

Return JSON only: {{"body": "...", "cta": "none", "rationale": "Replying to customer request."}}"""
        result = call_gemini_json(prompt, COMPOSER_SYSTEM)
        return {
            "action": "send",
            "body": result.get("body", "Confirmed! See you then."),
            "cta": result.get("cta", "none"),
            "rationale": result.get("rationale", "Replied on behalf of merchant to customer.")
        }

    # Merchant reply handling
    if is_auto_reply(message):
        auto_count = sum(1 for t in history if t.get("from") == "merchant" and is_auto_reply(t.get("msg", "")))
        if auto_count >= 2:
            return {
                "action": "end",
                "rationale": f"Auto-reply detected {auto_count + 1} times in a row. No real engagement signal. Closing conversation."
            }
        elif auto_count == 1:
            return {
                "action": "wait",
                "wait_seconds": 86400,
                "rationale": "Auto-reply seen twice. Owner likely not at phone. Backing off 24h."
            }
        else:
            return {
                "action": "send",
                "body": "Looks like an automated reply 😊 When you get a chance, just reply YES to continue — I'll handle the rest.",
                "cta": "binary_yes_no",
                "rationale": "Detected likely auto-reply. One prompt to flag it for the owner, then wait."
            }

    if is_hostile_or_opt_out(message):
        return {
            "action": "end",
            "rationale": "Merchant explicitly opted out or expressed strong disinterest. Closing conversation respectfully."
        }

    if is_explicit_intent(message) and turn_number <= 4:
        merchant = get_merchant(merchant_id)
        owner    = merchant.get("identity", {}).get("owner_first_name", "there") if merchant else "there"
        cat_slug = merchant.get("category_slug", "") if merchant else ""
        category = get_category(cat_slug) if cat_slug else {}
        offers   = [o["title"] for o in (merchant or {}).get("offers", []) if o.get("status") == "active"] if merchant else []

        prompt = f"""Merchant just committed: "{message}"
Previous conversation: {json.dumps(history[-3:] if len(history) >= 3 else history)}
Merchant: {owner}, Category: {cat_slug}, Active offers: {offers}

They said YES / committed. Switch immediately to ACTION mode. DO NOT ask any more qualifying questions.
Tell them exactly what you're doing next. Be concrete, specific, brief (2-3 sentences).
End with ONE binary CTA (CONFIRM / OK / YES).

Return JSON: {{"body": "...", "cta": "binary_confirm_cancel", "rationale": "..."}}"""

        result = call_gemini_json(prompt, COMPOSER_SYSTEM)
        return {
            "action": "send",
            "body": result.get("body", f"Perfect {owner}! Starting right now — I'll draft that for you. Reply CONFIRM and I'll send it over."),
            "cta": result.get("cta", "binary_confirm_cancel"),
            "rationale": result.get("rationale", "Merchant committed — switched to action mode.")
        }

    merchant = get_merchant(merchant_id)
    cat_slug = merchant.get("category_slug", "") if merchant else ""
    category = get_category(cat_slug) if cat_slug else {}

    lang_hint = build_languages_hint(merchant) if merchant else "Use English."

    prompt = f"""You are Vera (magicpin AI assistant). Continue this WhatsApp conversation.

Merchant message (turn {turn_number}): "{message}"
Conversation so far: {json.dumps(history[-4:] if len(history) >= 4 else history)}
Merchant: {merchant.get('identity', {}).get('name', '') if merchant else 'Unknown'}
Category: {cat_slug}
Language hint: {lang_hint}
Active offers: {[o['title'] for o in (merchant or {}).get('offers', []) if o.get('status') == 'active'] if merchant else []}

Reply naturally. Be brief (2-3 sentences). ONE clear next step at the end.
If merchant asked a question, answer it specifically.
If merchant said something off-topic, politely redirect.

Return JSON: {{"body": "...", "cta": "open_ended|binary_yes_no|none", "rationale": "..."}}"""

    result = call_gemini_json(prompt, COMPOSER_SYSTEM)
    return {
        "action": "send",
        "body": result.get("body", "Got it! Let me check that for you and get back shortly."),
        "cta": result.get("cta", "open_ended"),
        "rationale": result.get("rationale", "General reply.")
    }


# ─────────────────────────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────────────────────────

@app.get("/v1/healthz")
async def healthz():
    counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
    for (scope, _) in contexts:
        if scope in counts:
            counts[scope] += 1
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - START),
        "contexts_loaded": counts
    }


@app.get("/v1/metadata")
async def metadata():
    return {
        "team_name": TEAM_NAME,
        "team_members": TEAM_MEMBERS,
        "model": GEMINI_MODEL,
        "approach": "4-context composer with trigger-kind dispatch, auto-reply detection, intent routing, Hindi-English code-mix support",
        "contact_email": CONTACT_EMAIL,
        "version": "1.0.0",
        "submitted_at": datetime.now(timezone.utc).isoformat()
    }


class ContextBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: dict[str, Any]
    delivered_at: str

@app.post("/v1/context")
async def push_context(body: ContextBody):
    if body.scope not in ("category", "merchant", "customer", "trigger"):
        return JSONResponse(status_code=400, content={
            "accepted": False,
            "reason": "invalid_scope",
            "details": f"scope must be one of: category, merchant, customer, trigger. Got: {body.scope}"
        })

    key = (body.scope, body.context_id)
    existing = contexts.get(key)

    if existing and existing["version"] >= body.version:
        return JSONResponse(status_code=409, content={
            "accepted": False,
            "reason": "stale_version",
            "current_version": existing["version"]
        })

    contexts[key] = {"version": body.version, "payload": body.payload}
    return {
        "accepted": True,
        "ack_id": f"ack_{body.context_id}_v{body.version}",
        "stored_at": datetime.now(timezone.utc).isoformat()
    }


class TickBody(BaseModel):
    now: str
    available_triggers: list[str] = []

@app.post("/v1/tick")
async def tick(body: TickBody):
    actions = []

    for trg_id in body.available_triggers:
        trg = get_trigger_payload(trg_id)
        if not trg:
            continue

        suppression_key = trg.get("suppression_key", trg_id)
        if suppression_key in suppressed:
            continue

        # Check expiry
        expires_at = trg.get("expires_at", "")
        if expires_at:
            try:
                exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                sim_now = datetime.fromisoformat(body.now.replace("Z", "+00:00"))
                if sim_now > exp:
                    continue
            except:
                pass

        merchant_id = trg.get("merchant_id", "")
        customer_id = trg.get("customer_id")

        merchant = get_merchant(merchant_id)
        if not merchant:
            continue

        cat_slug = merchant.get("category_slug", "")
        category = get_category(cat_slug)
        if not category:
            continue

        customer = get_customer(customer_id) if customer_id else None

        # Compose the message
        composed = compose_message(category, merchant, trg, customer)

        if not composed.get("body"):
            continue

        conv_id = f"conv_{merchant_id}_{trg_id}_{uuid.uuid4().hex[:6]}"

        # Build template params (first 3 meaningful words from body)
        owner = merchant.get("identity", {}).get("owner_first_name", merchant.get("identity", {}).get("name", ""))
        body_text = composed.get("body", "")
        # Simple 3-param template
        sentences = body_text.split(".")
        p2 = sentences[0].strip() if len(sentences) > 0 else body_text[:80]
        p3 = sentences[1].strip() if len(sentences) > 1 else ""

        action_obj = {
            "conversation_id": conv_id,
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "send_as": composed.get("send_as", "vera"),
            "trigger_id": trg_id,
            "template_name": f"vera_{trg.get('kind', 'generic')}_v1",
            "template_params": [owner, p2[:60], p3[:60]],
            "body": body_text,
            "cta": composed.get("cta", "open_ended"),
            "suppression_key": composed.get("suppression_key", suppression_key),
            "rationale": composed.get("rationale", "Composed from 4-context framework.")
        }

        actions.append(action_obj)
        suppressed.add(suppression_key)

        # Store initial turn
        conversations[conv_id] = [{"from": "vera", "msg": body_text}]

        # Cap at 10 actions per tick (well within 20 limit)
        if len(actions) >= 10:
            break

    return {"actions": actions}


class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str
    message: str
    received_at: str
    turn_number: int

@app.post("/v1/reply")
async def reply(body: ReplyBody):
    conv_id = body.conversation_id

    # Don't respond to ended conversations
    if conv_id in ended_convs:
        return {"action": "end", "rationale": "Conversation already ended."}

    # Store the incoming turn
    conversations.setdefault(conv_id, []).append({
        "from": body.from_role,
        "msg": body.message
    })

    merchant_id = body.merchant_id or ""
    customer_id = body.customer_id
    result = compose_reply(conv_id, merchant_id, body.message, body.turn_number, body.from_role, customer_id)

    if result.get("action") == "end":
        ended_convs.add(conv_id)

    if result.get("action") == "send":
        conversations[conv_id].append({"from": "vera", "msg": result.get("body", "")})

    return result


# Optional teardown endpoint (magicpin may call this)
@app.post("/v1/teardown")
async def teardown():
    contexts.clear()
    conversations.clear()
    suppressed.clear()
    ended_convs.clear()
    return {"status": "wiped"}


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("  Vera Bot starting...")
    print(f"  Model: {GEMINI_MODEL}")
    print(f"  API Key set: {'YES' if GEMINI_API_KEY else 'NO — set GEMINI_API_KEY!'}")
    print("  Endpoints: /v1/healthz /v1/metadata /v1/context /v1/tick /v1/reply")
    print("=" * 60)
    uvicorn.run("bot:app", host="0.0.0.0", port=8080, reload=False)
