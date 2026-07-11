## Summary

<!-- What does this PR do? Link related issue if any. -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Documentation
- [ ] Refactor / chore

## How to test

```bash
cp .env.example .env
./scripts/up.sh
make test
```

<!-- Add any extra steps -->

## Checklist

- [ ] `make test` passes
- [ ] No secrets or large files committed (`.env`, weights, private assets)
- [ ] Updated docs if behavior changed
- [ ] Follows [architecture.md](../docs/architecture.md) rules (LLM does not control actuators)

## Screenshots (if UI)

<!-- Optional -->
