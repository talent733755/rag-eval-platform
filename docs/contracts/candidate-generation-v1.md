# Candidate Generation v1 Contract

`candidate-generation-v1` is a provider-neutral contract for turning an
explicit parsed document-version snapshot into reviewable candidate items.
The request contains a fixed `document_version_id` and chunk content hashes;
providers cannot silently read the latest document version.

The public Python models are in `rag_eval_api.candidates.protocol`. Every
result item contains a question, question type, reference answer, confidence,
automatic checks, source-version provenance, and at least one evidence link.
Evidence must point to the same source version as the item. Provider output
that violates the schema is rejected as `invalid_provider_output`.

Provider configuration is opt-in. When no configured provider is available,
the API returns `provider_not_configured` and creates no candidate data. The
`FakeCandidateGenerator` is test-only and is never selected by production
configuration.

`capability_version`, `prompt_version`, parser/check versions, seed,
randomness, chunk hashes, provider/model name, usage and environment metadata
are stored as an immutable generation snapshot. Compatible additions require a
new schema field with a safe default; incompatible changes require a new
capability version and migration notes.
