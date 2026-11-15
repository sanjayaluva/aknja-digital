# Aknja translation worker (instance-2)

Self-hosted IndicTrans2-dist-200M translation service (docs/34 §3 decision,
T-023). Two AI4Bharat models (MIT licence, HF gated:auto — access granted to
the founder account 2026-11-15) behind an OpenAI-compatible shim:

- `en -> {ml, hi, ta}`: ai4bharat/IndicTrans2-en-indic-dist-200M
- `{ml, hi, ta} -> en`: ai4bharat/IndicTrans2-indic-en-dist-200M

## Layout on instance-2

- `/home/ubuntu/aknja-translate/{app.py,requirements.txt}` (from this repo)
- `/home/ubuntu/aknja-translate/venv` — own venv (torch stack, NOT the app venv)
- `/home/ubuntu/aknja-translate.env` — `AKNJA_WORKER_KEY=<bearer>`,
  `HF_TOKEN=<founder full-access token>` (model download; gated repos),
  optional `AKNJA_WORKER_BEAMS=5` (chmod 600)
- `aknja-translate.service` — uvicorn 127.0.0.1:8001 (models load at startup,
  then brand-stem calibration; ~2 min on 1 OCPU)
- `aknja-translate-tunnel.service` — reverse SSH tunnel to instance-1 so the
  production app reaches the worker at `http://127.0.0.1:8001` without any
  OCI security-list change. Dedicated key `~/.ssh/tunnel_to_inst1` (ed25519,
  generated ON instance-2); its public key is installed on instance-1 with
  `restrict,port-forwarding` — no shell, forwarding only.

## Translation behaviour (validated 8/8 vs the app benchmark evaluator)

- IndicTrans2 unifies Indic scripts to Devanagari: outputs are converted to
  the target script, `->en` sources are converted in.
- Brand terms (BRAND_TERMS in app.py) are preserved verbatim in Latin:
  `->en` injects the Latin brand via glossary; `en->` restores it over the
  model's own transliteration (startup-calibrated, fuzzy/prefix tolerant).
- Non-translation prompts → HTTP 400; the app's task-scoped routing
  (`capability_contract["tasks"] = ["translation"]`) never sends them.

## Ops

- health: `curl -s http://127.0.0.1:8001/healthz` (on instance-2)
- from instance-1 through the tunnel: `curl -s http://127.0.0.1:8001/healthz`
- logs: `journalctl -u aknja-translate -u aknja-translate-tunnel -f`
- model cache: `~/.cache/huggingface` (~2.3 GB for both dist-200M models)
- upgrade: `cd /home/ubuntu/aknja-digital && git pull && \
  cp infra/oci/worker/*.py infra/oci/worker/requirements.txt ~/aknja-translate/ && \
  ~/aknja-translate/venv/bin/pip install -r ~/aknja-translate/requirements.txt && \
  sudo systemctl restart aknja-translate`
- benchmark: on the app host — `python -m app.cli run-llm-benchmark \
  --provider indictrans2 --tasks translation` (floor 1.0)
