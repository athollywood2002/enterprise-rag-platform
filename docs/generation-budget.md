# Optional generation token budget

`OLLAMA_NUM_PREDICT` is optional and unset by default. When unset, the outgoing
Ollama chat request is unchanged: `model`, `stream: false` and `messages`, with
no `options` key. When configured, the only added option is
`options: {"num_predict": <configured integer>}`. Embedding requests are unchanged.
No temperature, seed, thinking control or retry is added.

Configuration accepts a positive Python integer or a decimal integer string from
the environment or `.env`. Zero, negative sentinels, booleans, floats (including
`1.0`), fractional/malformed strings, whitespace, signs and empty values are
rejected. Unset means absent, not an empty string. The maximum accepted value is
2,147,483,647, the signed 32-bit range used by the reviewed backend; larger values
are rejected rather than risking an ineffective overflowed limit. No live cap
value is selected by this change.

## Completion evidence and evaluation

For an actual chat response, `RagEngine.ask` retains `answer` and `sources` and
adds a `generation` object. `/ask` passes that object through without changing
HTTP success semantics. This is an additive response change, even when the cap
is unset; clients requiring an exact two-key response must adapt. The prompt,
model choice and default outgoing generation request remain unchanged.

The object records `status`, `done`, `done_reason`, `eval_count`, configured
`num_predict`, and `visible_empty`. Missing or malformed termination/count fields
become null, not invented evidence. Unknown string reasons are retained.
`message.thinking` is never copied into the engine result or evaluation receipt.

| Status | Meaning |
| --- | --- |
| `limit` | Server reports `done_reason: "length"`; may be an output or other runtime limit. |
| `budget_reached` | Reported generated count reaches/exceeds the configured cap; review even if the server also reports a natural stop. This alone does not prove truncation. |
| `empty` | Visible content is empty/whitespace, without the preceding limit/budget evidence. |
| `complete` | Nonempty content, `done` exactly true, reason exactly `stop`, and no preceding limit/budget evidence. Protocol completion only. |
| `unknown` | Other, absent or inconsistent termination evidence; completion is not established. |

`visible_empty` remains available for limit/budget results too. `eval_count` is
accepted only as a nonnegative integer, never a boolean, string or fraction.
An absent count does not negate an explicit natural stop, but also does not prove
that the server honored the token budget. No-sources fallback responses dispatch
no chat and keep their existing shape; absent generation metadata is not proof
of a completed model answer.

`evaluation.generation.is_completed_generation(result)` is the fail-closed gate
before semantic review. It rejects limited/budget-reached, empty and unknown
results, including results without generation metadata. The offline HTTP smoke
uses it for its two scripted chat results. It does not assign quality credit:
even `complete` still needs factual/citation/negative-answer review. A 200 HTTP
response alone is neither completion evidence nor semantic success. Historical
receipts are not rewritten; older receipts without metadata need separate review.

## Thinking and official compatibility evidence

Thinking models can generate reasoning before visible answer content. A token
budget can therefore be consumed before any answer appears, or truncate an
answer. Counting visible words or choosing a cap from one observed maximum is
not a safe general budget. This implementation neither disables thinking nor
returns the separate thinking trace. Limited and empty results must be reviewed,
not silently counted as successful answers.

Official references reviewed:

- [Ollama chat API](https://docs.ollama.com/api/chat): `options.num_predict` is the
  maximum generated tokens; response includes `done`, `done_reason`, `eval_count`
  and separate `message.content` / `message.thinking`.
- [Thinking documentation](https://docs.ollama.com/capabilities/thinking): thinking
  precedes final content and is returned separately. These documentation pages
  are current generic documentation, not pinned deployment evidence.
- Official **v0.40.14** tag resolves to
  [`9a3e8177767245acc62b735eba7d5d8a553606d0`](https://github.com/ollama/ollama/tree/9a3e8177767245acc62b735eba7d5d8a553606d0).
  [`api/types.go`](https://github.com/ollama/ollama/blob/9a3e8177767245acc62b735eba7d5d8a553606d0/api/types.go)
  defines `ChatRequest.Options`, `Options.NumPredict` and chat termination metrics.
- At that commit,
  [`llm/llama_server.go`](https://github.com/ollama/ollama/blob/9a3e8177767245acc62b735eba7d5d8a553606d0/llm/llama_server.go)
  forwards `NumPredict` as backend `n_predict`, bounds open-ended/oversized requests
  relative to context, and maps backend stop type `limit` to `DoneReasonLength`.
  [`llm/server.go`](https://github.com/ollama/ollama/blob/9a3e8177767245acc62b735eba7d5d8a553606d0/llm/server.go)
  maps that reason to `length`.
- The same version's
  [`server/routes.go`](https://github.com/ollama/ollama/blob/9a3e8177767245acc62b735eba7d5d8a553606d0/server/routes.go)
  parses thinking/content from generated completion text and forwards final reason
  and token metrics. The limit applies to generated tokens before that split,
  not a fresh budget for visible content.
- Its [`LLAMA_CPP_VERSION`](https://github.com/ollama/ollama/blob/9a3e8177767245acc62b735eba7d5d8a553606d0/LLAMA_CPP_VERSION)
  pins backend `b11963`.
  [`tools/server/server-context.cpp`](https://github.com/ggml-org/llama.cpp/blob/b11963/tools/server/server-context.cpp)
  subtracts total `stats.n_gen` from `n_predict_max`, increments that generated
  count for sampled tokens, and stops at the limit. There is no separate visible
  answer allowance: generated thinking also uses this budget on this source path.

This establishes source-level support and accounting for the reviewed version
and backend path. It is not binary-build verification or a live compatibility
test. Other backends, versions or model configurations need their own validation.
No inference, database service or operational machine was contacted for this PR.

## What this does not enforce

This is request-level token budgeting only. It supplies no hard wall time, global
call allowance, GPU/RAM limit or in-flight cancellation. HTTP timeouts do not
reliably stop server-side generation. A separately approved live test still needs
dedicated owned services and an independently reviewed supervisor that can stop
only those services. An existing non-test-owned daemon is never a safe stop target.

The merged real-HTTP plan pins an earlier commit without this option. Using this
change in a future packet requires a separately reviewed code pin and explicit
approval; opening or merging this PR does not authorize a live test.
