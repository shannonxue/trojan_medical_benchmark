# V3 experiment metadata status

## Confirmed routes and source dates

- Retraction dataset retrieval date: `2025-12-31`.
- OpenAlex citation-count retrieval date: `2025-12-31`.
- Human-RCT designation: inherited from the existing Xu/VITALITY source dataset cited in the manuscript; the present study did not independently re-adjudicate RCT design.
- Kaggle Benchmarks: nine tested models; task calls used `llm.prompt(prompt)` under pinned implementation `ab291417d9a4c731ccfbfb03ac0b8316cb843683`.
- Kimi K2.6: APIHub relay to Azure endpoint `https://target-vector.services.ai.azure.com`, deployment `Kimi K2.6`.
- DeepSeek-V4 Pro: APIHub relay to Azure endpoint `https://target-vector.services.ai.azure.com`, deployment `DeepSeek-V4 Pro`.
- MiniMax M2.7: NVIDIA hosted inference endpoint `https://integrate.api.nvidia.com/v1/chat/completions`.
- GLM-5.1: Zhipu BigModel coding endpoint.
- Baichuan-M3: APIHub relay at `https://APIHUB.sci.mom` to a Baichuan-M3 service or deployment; the exact upstream provider endpoint and immutable backend snapshot are not recoverable from the archived request artifacts.

## Model version provenance: DeepSeek-V4 family

Both DeepSeek-V4 models were evaluated in the **2026-04-24 preview open-weight release**. The later official builds were not evaluated:

| Model | Release evaluated | Later official build not evaluated |
|---|---|---|
| DeepSeek-V4 Flash | 2026-04-24 preview | `DeepSeek-V4-Flash-0731`, 2026-07-31 |
| DeepSeek-V4 Pro | 2026-04-24 preview | `DeepSeek-V4-Pro-0813`, general availability 2026-08-13 |

The provider repointed the unversioned model names `deepseek-v4-flash` and `deepseek-v4-pro` to those later builds without changing the calling identifier, so neither recorded identifier is an immutable snapshot.

Evidence level differs by route and must not be merged into one statement:

- **DeepSeek-V4 Flash (Kaggle, slug `deepseek-v4-flash`):** the archived source artifact mtime is `2026-06-21T13:25:43Z`, which precedes the 2026-07-31 build, so the preview attribution is supported by artifact timing plus the code/route record. The immutable backend snapshot remains unknown.
- **DeepSeek-V4 Pro (APIHub relay to Azure deployment `DeepSeek-V4 Pro`):** artifact mtimes are 2026-08-12 15:48 and 17:05 CST, which precede the 2026-08-13 general-availability build but follow the Flash official build. The author supplied the Azure deployment record on 2026-09-10: **deployment created 2026-04-28, model version `0423`**. That version string precedes the 2026-04-24 public preview announcement by one day, matching the provider's checkpoint-naming pattern, and corresponds to neither the `0731` nor the `0813` build. Evidence level: **provider-recorded deployment metadata, author-transmitted**. It is a deployment-level attribute, not a per-request field, so it establishes the version pinned to the deployment rather than independently confirming the version that served each of the 200 requests; the deployment's version-update policy is not documented in the archived artifacts.

Still outstanding: per-request model-version echo for the 200 DeepSeek-V4 Pro calls, which the archived artifacts do not contain.

## Parameter interpretation

For the pinned Kaggle Benchmarks implementation, `prompt()` defines defaults `seed=0` and `temperature=0`, but the Kaggle Model Proxy disables forwarding of the temperature parameter and removes seed for unsupported backends. The benchmark calls did not supply a max-token limit, custom system prompt or tool definitions. This does not prove that provider-side hidden instructions or built-in retrieval capabilities were disabled.

Documented direct-generation code requested temperature 0 and seed 123 for Kimi K2.6, DeepSeek-V4 Pro and GLM-5.1 with max tokens omitted. For Baichuan-M3 baseline and safety runs, the author confirmed on 2026-09-08 that `max_tokens` was left empty/unset: no explicit output cap was set. Whether the request omitted the field or serialized JSON `null` remains unverified. Provider defaults and limits still apply; this does not mean unlimited output, and actual token usage is unavailable. Baichuan-M3 temperature 0 and seed 123 remain prior code-audit evidence, not newly author-verified settings. The previous code-based output-cap attribution is superseded as a run-setting claim; historical provenance is retained in the dated correction in the metadata code audit. MiniMax M2.7 run-level decoding settings are not recoverable from the supplied archive.

Consequently, the effective decoding settings are not fully comparable across access routes: direct routes requested temperature 0 where documented, whereas the Kaggle Model Proxy did not forward that parameter and the MiniMax run-level value is unknown. Only one response per model--item--condition was analysed, so variability under repeated production sampling was not characterised.

## Still unavailable

- Exact historical query start/end times for most canonical model responses.
- Immutable backend snapshots behind aliases or deployment names where the provider did not record one in the archived artifacts.
- Provider-internal system prompts and provider-side built-in web/retrieval/tool state.
- An archived DOI for the released materials (the repository itself is now public).
