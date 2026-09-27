# Offline evidence retrieval experiment

Status: local retrieval-only prototype, not a deployed RAG chatbot.

```bash
python3 scripts/local_advice_retrieval.py "pH EC calibration probe"
```

The script selects exact sections from four allowlisted Pomona operational
documents: calibration provenance, temporal checks, advice boundaries and twin
calibration. It returns section IDs, source paths, full-document and excerpt
SHA-256 hashes, and exact excerpts. Unknown queries return insufficient evidence.
Citation verification rejects unknown IDs, altered quotes, changed documents,
and path substitutions. Keyword matches do not prove relevance or entailment.

No model, network, embeddings, external corpus download, dose calculation or
actuator tools are involved. This is the reproducible citation mechanism inspired
by AgriIR/Miranda, not a reimplementation of those systems. The experiment is
deliberately not attached to the production advice endpoint or used to generate
new claims. Internal docs are not a validated agronomic knowledge base.

Next gate: select licensed, crop/system-specific authoritative hydroponic
references; manually review question/passage pairs, conflicts and abstentions.
Then compare retrieval-only, rules-only and retrieval-assisted explanations.
Keep observed sensor evidence separate from documentary guidance. An LLM must
not create observations, calibrations, citations, or control commands.

Optional language/notification work is deferred pending delivery-channel and
privacy choices. WhatsApp/cloud services are not required by this prototype.
