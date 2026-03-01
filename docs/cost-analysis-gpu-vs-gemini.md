# Cost Analysis: Self-Hosted GPU Model vs Gemini API for Enrichment

**Date:** 2026-02-28
**Status:** Recommendation — Stick with Gemini 2.5 Flash API

## Context

The enrichment pipeline (`backend/processing/enricher.py`) sends ~2,500 input tokens (mostly fixed prompt) and receives ~200 output tokens (structured JSON with summary, tags, scores) per article. This analysis evaluates whether self-hosting a lightweight model (Llama 3.1 8B / Mistral 7B) on GCP GPU instances is cost-effective vs the current Gemini 2.5 Flash API at 1,000–5,000 calls/month.

---

## Option 1: Gemini 2.5 Flash API (Current)

**Pricing (paid tier):**
- Input: $0.30 / 1M tokens
- Output: $2.50 / 1M tokens

**Per-call cost:**
- Input: 2,500 tokens × $0.30/1M = $0.00075
- Output: 200 tokens × $2.50/1M = $0.00050
- **Total: ~$0.00125 per call**

| Volume | Monthly Cost |
|--------|-------------|
| 1,000 calls | **$1.25** |
| 2,500 calls | **$3.13** |
| 5,000 calls | **$6.25** |

**Free tier note:** Gemini 2.5 Flash has a free tier (15 RPM limit). At 1,000 calls/month (~33/day), the free tier is viable if you can tolerate the rate limit.

---

## Option 2: Self-Hosted on GCP L4 GPU (On-Demand)

**Instance: g2-standard-4** (1× NVIDIA L4, 24GB VRAM, 4 vCPU, 16GB RAM)
- On-demand: **$0.71/hour**

**Model:** Llama 3.1 8B Instruct (FP16, ~16GB VRAM)
- Estimated throughput on L4: ~30–50 output tokens/sec (single request), higher with batching
- Per-article processing: ~8–10 sec (prompt ingestion + generation)
- Model load time: ~2–3 min cold start

**Estimated processing time (on-demand, spin up and tear down):**

| Volume | Compute Time | Overhead (startup/shutdown) | Total Hours | Monthly Cost |
|--------|-------------|----------------------------|-------------|-------------|
| 1,000 calls | ~2 hrs | +0.5 hr | ~2.5 hrs | **$1.78** |
| 2,500 calls | ~5 hrs | +0.5 hr | ~5.5 hrs | **$3.91** |
| 5,000 calls | ~10 hrs | +0.5 hr | ~10.5 hrs | **$7.46** |

**Always-on (24/7): $0.71 × 730 hrs = ~$518/month** — not viable at this volume.

---

## Option 3: Self-Hosted on GCP T4 GPU (On-Demand)

**Instance: n1-standard-4 + 1× T4** (16GB VRAM, 4 vCPU, 15GB RAM)
- On-demand: **~$0.54/hour** (VM $0.19 + GPU $0.35)

**Model:** Llama 3.1 8B (INT8 quantized to fit 16GB VRAM)
- Estimated throughput on T4: ~15–25 output tokens/sec (older architecture, no FP8)
- Per-article processing: ~15–20 sec
- Model load time: ~3–5 min

| Volume | Compute Time | Overhead | Total Hours | Monthly Cost |
|--------|-------------|----------|-------------|-------------|
| 1,000 calls | ~5 hrs | +0.5 hr | ~5.5 hrs | **$2.97** |
| 2,500 calls | ~12 hrs | +0.5 hr | ~12.5 hrs | **$6.75** |
| 5,000 calls | ~25 hrs | +0.5 hr | ~25.5 hrs | **$13.77** |

---

## Side-by-Side Comparison

| | Gemini API | Self-Host L4 | Self-Host T4 |
|---|---|---|---|
| **1,000 calls/mo** | **$1.25** | $1.78 | $2.97 |
| **2,500 calls/mo** | **$3.13** | $3.91 | $6.75 |
| **5,000 calls/mo** | **$6.25** | $7.46 | $13.77 |
| Setup effort | Zero | High | High |
| Maintenance | Zero | Ongoing | Ongoing |
| Latency/call | ~2–3s | ~8–10s | ~15–20s |
| Output quality | Excellent (SOTA) | Good (8B model) | Good (quantized) |
| JSON reliability | Native JSON mode | Needs prompt engineering | Needs prompt engineering |
| Availability | 99.9%+ SLA | You manage | You manage |

---

## Hidden Costs of Self-Hosting (Not in the Numbers Above)

1. **Engineering time**: Setting up vLLM/TGI, container image, startup/shutdown automation, health checks — easily 2–5 days of work
2. **Orchestration**: Need Cloud Scheduler or Cloud Functions to spin up/down the GPU VM on demand (to avoid paying 24/7)
3. **Reliability**: Handling GPU quota limits, preemption (if using spot), OOM errors, model version management
4. **Quality gap**: An 8B model will produce noticeably worse structured JSON output than Gemini 2.5 Flash. More hallucinations, worse instruction following, especially for the audience_scores and nuanced summaries
5. **Disk costs**: ~$5–10/month for persistent disk to store model weights (~16GB)
6. **Networking**: Egress costs if serving externally (minimal for internal use)

---

## Break-Even Analysis

Self-hosting on L4 becomes cheaper than Gemini API only at roughly **20,000–30,000+ calls/month**, where:
- Gemini: ~$25–37/month
- L4 on-demand: ~$20–25/month (with efficient batching)

Even then, engineering/maintenance overhead likely negates the savings unless you have other GPU workloads to amortize the infrastructure investment.

---

## Recommendation

**Stick with Gemini 2.5 Flash API.** At 1,000–5,000 calls/month:

- It's the cheapest option ($1.25–$6.25/month)
- Zero infrastructure to manage
- Best output quality (structured JSON mode, instruction following)
- The free tier alone may cover the 1,000 call/month scenario
- Faster per-request latency

Self-hosting only makes sense if you need: (a) data privacy (no external API calls), (b) 50K+ calls/month, or (c) you already have GPU infrastructure for other workloads.
