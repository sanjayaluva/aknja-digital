# Integration and Provider Register

For each provider record:
- provider/product/category and official docs URL;
- account owner and account reference;
- plan and eligibility evidence;
- free quota, reset, units and metric source;
- billing state/payment method/auto-upgrade behavior;
- region, latency, data residency and retention;
- data classification allowed;
- commercial-use and ToS status;
- capability contract and quality benchmark;
- secret reference (never raw secret);
- health, last verified timestamp and reviewer;
- fallback category and switch strategy.

Provider candidates such as OCI, GitHub, Google Cloud, AWS, Colab, Kaggle, Cloudflare, Neon, Upstash, Hugging Face and AI/speech APIs are not presumed available or free. Verify account-specific conditions before activation.

## Telegram Bot API — admin notification channel (integrated 2026-11-14)

- Provider/product: Telegram Bot API `sendMessage`; docs:
  https://core.telegram.org/bots/api#sendmessage
- Account owner: founder; account reference: bot created via @BotFather
- Plan: free, no quota tier (rate limits per chat/second apply)
- Secrets: env `TELEGRAM_BOT_TOKEN` (never raw in repo),
  `TELEGRAM_ADMIN_CHAT_ID` from the founder chat
- Data classification allowed: INTERNAL/PUBLIC only — the outbox never
  carries client production data or credentials
- Commercial use: yes (Bot API is free); ToS reviewed at integration
- Capability contract: durable idempotent outbox; 200+ok confirmed
  delivery; 429 retry_after backoff; 400/403 terminal; ref footer on
  every body for duplicate reconciliation (docs/39)
- Health/verification: `python -m app.cli send-test-notification` then
  `process-notifications`; last verified: not yet (token unset)
- Fallback: rows stay PENDING while unconfigured — no fallback channel;
  email outbox remains a separate mechanism
