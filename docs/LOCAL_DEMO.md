# Offline tomato walkthrough

After installing the local Python environments, run from the repository root:

```bash
make demo-local
```

This terminal demo uses Pomona's actual deterministic pipeline and automation
rules for three simulated tomato-greenhouse cases:

1. Routine readings: no automation suggestion.
2. High EC and humidity: inspect/verify suggestions and safety restrictions.
3. Missing pH: missing-data labels and human-review requirements.

Each result shows sensor inputs, risk labels, the safety decision, and suggested
checks. These are simulated software results, not validated agronomic advice.
The command forces rules/stub backends, needs no GPU or running server, and
offers no approvals. Audit output uses an automatically removed temporary
directory; it does not modify the owner's database or create saved suggestions.

For the live local monitoring dashboard, follow [Quickstart](GETTING_STARTED.md).
For visitors who want a browser-only introduction without installing anything,
use the existing [static greenhouse demo](https://huggingface.co/spaces/Okyanus/pomona-greenhouse-demo).
That separate browser demo is not a live connection to your local device.
