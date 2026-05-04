# 🤖 Vera: AI Merchant Assistant

Welcome to **Vera**! This is a stateful, context-aware AI conversational agent built for the [magicpin AI Challenge](https://magicpin.com/vera/ai-challenge). Vera acts as a smart WhatsApp assistant that communicates with local merchants (like dentists, salons, and restaurants) to boost their engagement and help them manage customer bookings.

## ✨ Key Features

- **🧠 Context-Aware AI**: Powered by Google's **Gemini 2.0 Flash**, Vera dynamically composes WhatsApp messages based on 4 layers of live context (Merchant data, Category trends, Customer history, and Trigger events).
- **⚡ High-Performance API**: Built on **FastAPI**, handling high-throughput asynchronous requests with instant JSON validation.
- **🔄 Stateful Memory**: Maintains conversation history in-memory to remember what the merchant or customer said 3 turns ago.
- **🎯 Intent Routing**: Smartly detects when a merchant commits to an action (e.g., "let's do it") and instantly switches from "sales mode" to "action mode".
- **🛡️ Auto-Reply & Spam Protection**: Detects WhatsApp Business automated replies and backs off to prevent spamming. Gracefully handles hostile messages or opt-outs.
- **🗣️ Dynamic Code-Switching**: Automatically analyzes merchant preferences to speak in clean English or natural Hindi-English code-mix (Hinglish).

---

## 🛠️ Tech Stack

- **Backend Framework**: FastAPI (Python)
- **Server**: Uvicorn
- **LLM Engine**: Google Gemini API (`gemini-2.0-flash`)
- **Data Validation**: Pydantic
- **Deployment**: Render

---

## 🚀 How It Works (The 5 Endpoints)

Vera strictly follows a 5-endpoint API contract to integrate seamlessly with external event systems:

1. `GET /v1/healthz` 🩺 — Returns the server's health status and how many contexts are currently loaded in memory.
2. `GET /v1/metadata` 📊 — Returns team details and the LLM approach being used.
3. `POST /v1/context` 📂 — Accepts real-time business data payloads (Merchant stats, Customer profiles) and stores them securely in memory.
4. `POST /v1/tick` ⏱️ — The "heartbeat". When a trigger fires (like a drop in views), Vera analyzes all contexts and uses Gemini to compose a highly personalized, compelling WhatsApp message to the merchant.
5. `POST /v1/reply` 💬 — Handles live 2-way conversations. Vera reads the message, identifies if it's from a customer or merchant, and uses the LLM to generate the perfect response.

---

## 💻 How to Run Locally

Want to spin up Vera on your own machine? It's super easy!

### 1. Install Dependencies
Make sure you have Python installed, then run:
```bash
pip install fastapi uvicorn google-generativeai pydantic
```

### 2. Set your Gemini API Key
Get a free API key from [Google AI Studio](https://aistudio.google.com/) and set it as an environment variable:

**Windows (PowerShell):**
```powershell
$env:GEMINI_API_KEY="your_api_key_here"
```
**Mac/Linux:**
```bash
export GEMINI_API_KEY="your_api_key_here"
```

### 3. Start the Server
Run the FastAPI server using Uvicorn:
```bash
python bot.py
```
*(The bot will start running on `http://localhost:8080`)*

---

## 📈 Challenge Learnings & Architecture Decisions

- **Single-Prompt vs. Chain**: I opted for a single, highly detailed master prompt to minimize latency and avoid API rate limits, ensuring responses always return within the strict <30s timeout window.
- **Exponential Backoff**: Implemented retry logic to gracefully handle free-tier API rate limits during heavy load testing.
- **In-Memory Store**: Used Python dictionaries for state management (suitable for the 60-minute simulation window). For a full production rollout, this would be replaced with Redis.

---
*Built with ❤️ by Patel Smith for the magicpin AI Challenge.*
