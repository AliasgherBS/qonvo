# Working on Qonvo

## Branches

| Branch | Means | Rule |
|---|---|---|
| `main` | **production** | Only ever receives a tested release, and every arrival is tagged `vX.Y.Z`. Never commit to it directly. |
| `dev` | integration | Where features accumulate between releases. Never commit to it directly either. |
| `feat/…` `fix/…` `docs/…` `chore/…` | one change | Where all work happens. |

```
feat/billing ─┐
fix/pacing  ──┼──▶ dev ──(release, tagged)──▶ main
docs/readme ──┘
```

The point of the split: `main` answers "what is live?" and its tags answer "since
when?". If work went straight onto a long-lived branch, neither question has an answer.

## Making a change

```bash
git switch dev && git pull
git switch -c feat/short-name

# ... work, with tests ...
cd backend && uv run pytest -q && uv run ruff check
cd dashboard && npx tsc --noEmit && npm run lint && npm run verify:brand
```

Commit subjects follow the convention already in this history:
`type(scope): imperative summary` — e.g. `fix(billing): honour the grace window`.
Types: `feat` `fix` `docs` `test` `chore` `perf` `refactor`.

Then merge to `dev` keeping the feature visible as a unit:

```bash
git switch dev
git merge --no-ff feat/short-name
git branch -d feat/short-name
```

Never commit a secret. `.env*` files are gitignored except the `*.example` templates.

## Cutting a release

Releases **batch several changes** — do not tag every merge. Cut one when a meaningful
set has accumulated and been tested.

```bash
./scripts/release.sh 0.10.0
```

That script does the whole sequence, refusing to proceed if anything is off:

1. Checks you are on `dev` with a clean tree and that tests pass.
2. Moves `CHANGELOG.md`'s `Unreleased` entries under the new version and today's date.
3. Bumps the version in `backend/pyproject.toml` and `dashboard/package.json`.
4. Commits the bump, merges `dev` into `main` with `--no-ff`, and creates an annotated
   `vX.Y.Z` tag whose message is that version's changelog section.
5. Prints the push commands. **It never pushes for you** — that stays a deliberate act.

### Which number to bump

- **patch** (`0.9.1`) — fixes only, nothing an owner would notice as new.
- **minor** (`0.10.0`) — new capability, or a behaviour change tenants will feel.
- **major** (`1.0.0`) — reserved for the first release sold to a paying customer who
  is not the owner.

## Before releasing, by hand

The automated gates cannot cover these; see [docs/TESTING.md](docs/TESTING.md) §5:

- The integration suite against **staging**, not production (`./qonvo-staging.sh`).
- A live WhatsApp round trip: a grounded answer, an unanswerable question that hands
  off, and the flood guard.
- Migrations applied on a **fresh** database, not only on the box that already has the
  columns. This is exactly how the `0007` fresh-database failure went unnoticed.
