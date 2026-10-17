# Model Stack and Costing

Pricing and model behavior were checked against Google's Gemini API docs on 2026-09-29. Rates and quotas change; verify them in [AI Studio rate limits](https://aistudio.google.com/rate-limit) and [current pricing](https://ai.google.dev/gemini-api/docs/pricing) before each production batch.

## Recommended one-key stack

| Stage | Model ID | Use | Price assumption |
|---|---|---|---|
| Storyboard, metadata, sampled-frame QA | `gemini-3.5-flash-lite` | JSON generation and image understanding | Free-tier usage is quota-limited; paid list price is $0.30 / 1M input tokens and $2.50 / 1M output tokens. |
| Narration | `gemini-3.8-flash-lite-tts` | Friendly speech using the `Kore` voice | Free-tier access is limited; paid output is about $0.00015/audio-second, plus text input. |
| Video | `veo-3.1-lite-generate-preview` | Text-to-video, native audio, 8-second 720p clips | $0.05 / generated second at 720p. 1080p is listed at $0.08 / second; default stays at 720p and upscales during assembly. |
| Optional keyframes | `gemini-3.1-flash-lite-image` | Image-to-video mode only | About $0.0336 per 1K image; image output has no free-tier price in the current table. |
| Optional music | `lyria-3.5` | One original instrumental song per video | About $0.08 per song; not listed as free-tier. |

All these Gemini-family services use the same `GEMINI_API_KEY`, but they have **separate model quotas and prices**. YouTube OAuth is a separate credential, not another generative-model key. The YouTube Data API has quota limits rather than a per-upload model fee; unverified API projects may be restricted to private uploads.

## 60-second example

Veo Lite generates 8 seconds per request. A typical 60-second storyboard needs about 8 clips: 64 billed seconds, or **$3.20 for one pass**. A worst-shaped storyboard may reach the prompt's 15-scene limit: 120 billed seconds, or **$6.00 for one pass**.

The cost guard reserves one complete QA regeneration and one generation attempt per scene. At the 15-scene upper bound:

- Veo: $6.00 initial pass + $6.00 full QA regeneration = $12.00
- Optional 15 keyframes: approximately $0.50
- Lyria full song: approximately $0.08
- One minute of TTS: approximately $0.01 on paid output pricing
- Storyboard/vision QA plus one JSON-repair reserve for each call: $0.60
- **Estimated upper bound: approximately $13.19**, below the configured $15 daily cap

A typical 8-clip run with one full QA regeneration is approximately **$7.09**, including music, TTS and the LLM reserve. Text-to-video mode skips keyframe costs. Actual story scene counts, retries, model availability, taxes, tier, and rates change the result.

The cap is a local estimate, **not a provider-enforced spending limit**. It uses the configured list-price assumptions and reserves the configured retries/QA regeneration before media generation. Keep `video.max_attempts: 1` unless you raise the cap. Failed or policy-blocked jobs, provider retry semantics, and pricing changes can make actual charges differ; monitor usage in AI Studio.

## Free-tier and privacy caveats

- Gemini Flash-Lite and TTS may be available on a free tier, but rate limits are per model and project-specific. The free tier is not a production SLA and can return 429/503 errors.
- Veo video, generated image output, and Lyria music are billed services; do not expect a free Gemini API key to make the full pipeline free.
- Free-tier Gemini prompts may be used to improve Google's products under the applicable terms. Do not include children's personal information or other sensitive data in scripts/prompts.
- Use original characters and melodies. AI music can still receive false Content ID claims; retain source and generation records for disputes.
- Current defaults upload privately for approval, enforce the QA hold, and send success/failure email alerts. No recurring scheduler starts unless `python -m kidtube serve` is run.

## Official references

- [Gemini model catalog](https://ai.google.dev/gemini-api/docs/models)
- [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Veo API guide and duration limits](https://ai.google.dev/gemini-api/docs/veo)
- [Nano Banana image generation](https://ai.google.dev/gemini-api/docs/image-generation)
- [Gemini TTS guide](https://ai.google.dev/gemini-api/docs/speech-generation)
- [Lyria music generation](https://ai.google.dev/gemini-api/docs/music-generation)
- [Rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)
