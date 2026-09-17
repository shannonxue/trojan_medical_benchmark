# V3 experiment-metadata audit from archived generation code

**Audit scope:** code and artifacts under `provenance://project-source/data/v2/trojan sensitivity dataset/answer_generation`, canonical answer provenance, selective Kaggle rerun manifests, and archived Kaggle task files. Code evidence is not silently upgraded to run-log evidence.

## Recoverable facts

### Shared prompt behavior

- Baseline and safety user-prompt templates in `reference.py`, `generate_local.py`, the selective-rerun notebook and stored answer JSONs match the released templates.
- The archived generation code passes only a user message; it does not define a custom user-supplied system prompt.
- No archived generation function calls a web-search, retrieval or external-tool API. Kaggle notebook metadata has `enable_internet=true`, so notebook-network availability must not be described as proof that model-side browsing/tools were disabled.
- One item is generated per isolated conversation in the Kaggle task code.
- Kaggle tasks called `llm.prompt(prompt)` under pinned implementation `ab291417d9a4c731ccfbfb03ac0b8316cb843683`. Its Python signature defaults to seed 0 and temperature 0, but the Kaggle Model Proxy disables forwarding of the temperature parameter and removes seed for unsupported backends. No max-token limit or tool definitions were supplied by the benchmark call.

### Full local/API replacements used by the canonical layer

| Canonical model | Conditions | Evidence-backed route/settings | Time evidence |
|---|---|---|---|
| Kimi-K2.6 | baseline, safety | APIHub OpenAI-compatible relay to Azure endpoint `https://target-vector.services.ai.azure.com`, deployment `Kimi K2.6`; temperature 0; seed 123; `max_tokens` omitted; user message only; response extraction prefers `content`, then `reasoning_content` | output artifact mtimes 2026-08-12 13:29 and 14:59 CST; no request-level timestamps |
| DeepSeek-V4 Pro | baseline, safety | APIHub OpenAI-compatible relay to Azure endpoint `https://target-vector.services.ai.azure.com`, deployment `DeepSeek-V4 Pro`; temperature 0; seed 123; `max_tokens` omitted; user message only; response extraction prefers `content`, then `reasoning_content` | output artifact mtimes 2026-08-12 15:48 and 17:05 CST; no request-level timestamps |
| GLM-5.1 | baseline, safety | Zhipu BigModel coding endpoint; API model `glm-5.1`; temperature 0; seed 123; `max_tokens` omitted; user message only; response extraction prefers `content`, then `reasoning_content` | baseline artifact mtime 2026-08-12 20:51 CST; safety artifact finalized 2026-08-13 21:29 CST after item-33 repair; no complete request-level timestamps |
| Baichuan-M3 | baseline, safety | Local Python $\rightarrow$ APIHub OpenAI-compatible relay at `https://APIHUB.sci.mom` $\rightarrow$ a Baichuan-M3 service or deployment; relay endpoint author-confirmed; exact upstream provider endpoint and immutable backend snapshot are not recoverable; author-confirmed 2026-09-08: `max_tokens` left empty/unset, no explicit output cap; prior code-audit evidence: temperature 0, seed 123 and streaming; see correction below for serialization and provenance limits | exact query timestamps not logged; local artifact copy time is not treated as query time |

**Baichuan-M3 corrections — 2026-09-08:** The author confirmed that the client called the APIHub relay at `https://APIHUB.sci.mom`, not the official Baichuan endpoint directly. The exact relay-to-provider endpoint or deployment mapping is absent from the archived request/run artifacts and is therefore recorded as unknown rather than inferred. The author's confirmation of empty/unset `max_tokens` for baseline and safety supersedes the previous output-cap attribution as a run-setting claim. The prior audit's `max_tokens=8192` and conditional `max_tokens=4096` follow-up path are retained as historical code provenance, not executed settings or proof that a follow-up occurred; original source references remain unchanged. Unset does not establish an omitted request field or JSON `null`: serialization is unverified without a historical HTTP/run log. Provider defaults and limits still apply, so output is not unlimited; actual token usage is unavailable. Temperature 0 and seed 123 remain prior code-audit evidence, not newly author-verified settings.

### Other repaired/original cases

- DeepSeek-R1-0528 canonical files are cleaned copies with `<think>`/`<thinking>` content removed. The cleaning manifest preserves this transformation, but the original generation route/settings are not present in the supplied answer-generation code.
- MiniMax M2.7 canonical response texts match the archived answer-generation files after whitespace normalization. The author confirmed NVIDIA endpoint `https://integrate.api.nvidia.com`; a complete original full-run decoding configuration log remains absent.
- DeepSeek-V4 Flash canonical responses match archived answer-generation files, but no model-specific generation script or request log in the supplied directory proves its original decoding settings.

### Model version provenance (DeepSeek-V4 family)

Both DeepSeek-V4 models were evaluated in the 2026-04-24 preview open-weight release. The later official builds — `DeepSeek-V4-Flash-0731` (2026-07-31) and `DeepSeek-V4-Pro-0813` (general availability 2026-08-13) — were not evaluated. The provider repointed the unversioned names `deepseek-v4-flash` and `deepseek-v4-pro` to those later builds without changing the calling identifier, so neither recorded identifier is an immutable snapshot.

| Model | Route/identifier | Preview attribution evidence | Evidence level |
|---|---|---|---|
| DeepSeek-V4 Flash | Kaggle slug `deepseek-v4-flash` | Source artifact mtime `2026-06-21T13:25:43Z` precedes the 2026-07-31 build | Artifact timing + code/route record; immutable snapshot unknown |
| DeepSeek-V4 Pro | APIHub relay to Azure deployment `DeepSeek-V4 Pro`, model version `0423` | Author-supplied Azure deployment record (2026-09-10): deployment created 2026-04-28, model version `0423`; that string precedes the 2026-04-24 preview announcement by one day and matches neither the `0731` nor the `0813` build. Artifact mtimes 2026-08-12 15:48 / 17:05 CST | Provider-recorded deployment metadata, author-transmitted |

**DeepSeek-V4 Pro deployment record — 2026-09-10:** The deployment creation date and model version are deployment-level attributes obtained from the Azure deployment view, not fields echoed in the archived request or response artifacts. They establish the version pinned to the deployment; they do not independently confirm the version that served each of the 200 requests, and the deployment's version-update policy is not documented in the supplied directory. The per-request model-version echo remains absent and is recorded as outstanding rather than inferred.

### Selective Kaggle answer reruns

These exact run-level UTC timestamps are recoverable:

| Canonical condition | Repaired IDs | Kaggle model slug | Start UTC | End UTC |
|---|---:|---|---|---|
| Claude Opus 4.7 baseline | 12, 18, 84, 94 | `anthropic/claude-opus-4-7@default` | 2026-08-12T14:50:43.855516Z | 2026-08-12T14:51:35.766489Z |
| GPT-5.4 safety | 99 | `openai/gpt-5.4-2026-03-05` | 2026-08-12T14:48:24.347119Z | 2026-08-12T14:48:46.715310Z |
| Gemini 3.1 Pro baseline | 96 | `google/gemini-3.1-pro-preview` | 2026-08-12T14:46:03.222573Z | 2026-08-12T14:46:11.968752Z |

The selective task invokes `llm.prompt(prompt_text)` without explicit temperature, seed or output limit, so those values remain provider/Kaggle defaults for these repaired items.

### Judge runs

- All repaired judge task sources explicitly pass `temperature=0` and `seed=123` to `judge_llm.prompt(..., schema=JudgeResult, ...)`.
- Judge model slugs are `openai/gpt-5.5-2026-04-23`, `anthropic/claude-opus-4-7@default`, and `google/gemini-3.1-pro-preview`.
- Exact judge-run start/end UTC timestamps are preserved in the archived `.run.json` files; these are judgment dates, not tested-model answer-generation dates.

## Not recoverable from the supplied code directory

- Exact original query date/time for most canonical model responses.
- Immutable provider snapshot behind aliases such as `Baichuan-M3`, `Kimi-K2.6`, `deepseek-v4-flash`, and `minimaxai/minimax-m2.7`.
- Complete original endpoint/configuration for DeepSeek-R1-0528 and the original Kaggle-generated answer files.
- Provider-internal system prompts.
- Model-side browsing/retrieval/tool availability. The code shows no explicit tool invocation, but Kaggle notebook internet was enabled.
- Exact query time for model generation remains unavailable for most responses, but the author confirmed that the retraction dataset and OpenAlex citation counts were retrieved on 2025-12-31.

## Author-confirmed dataset provenance

- Retraction dataset retrieval date: 2025-12-31.
- OpenAlex citation-count retrieval date: 2025-12-31.
- Human-RCT designation came from the existing dataset supplied by the cited Xu/VITALITY reference; the present project did not independently re-adjudicate RCT study design.

## Reporting rule

Use `unknown` for unrecoverable historical fields. File creation/modification times are recorded only as artifact timestamps, not silently relabelled as query timestamps.
