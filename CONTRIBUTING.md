# Contributing

## Branches
- `main` — production. Protected. Merge via PR only.
- Feature branches: `feature/<name>` or `fix/<name>` or `phase-<n>/<scope>`

## PR template
- What changes
- Screenshots for UI changes
- Test plan checklist
- Linked issue / phase

## Local dev
See [README.md](README.md).

## Commit messages
Conventional Commits encouraged:
- `feat:` new feature
- `fix:` bug
- `chore:` non-functional
- `docs:` documentation
- `test:` tests
- `refactor:` code restructure, no behavior change

## Pre-commit
Install the secrets-scan hook:
```bash
cp scripts/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

## Code style
- Frontend: Prettier + ESLint (next/core-web-vitals). Tailwind class ordering via `prettier-plugin-tailwindcss`.
- Backend: ruff + mypy (strict on `app/`).
- Sql: lowercase keywords, snake_case identifiers, one statement per migration file.
