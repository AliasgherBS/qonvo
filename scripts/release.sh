#!/bin/bash
# Cut a Qonvo release: dev → main, tagged, with the changelog as the tag message.
#
#   ./scripts/release.sh 0.10.0
#
# Deliberately does NOT push. Pushing a tag is how work becomes "released" for
# everyone, so it stays an explicit act by a person. The commands are printed.
#
# See CONTRIBUTING.md for when to cut one and which number to bump.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

VERSION="${1:-}"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "usage: $0 X.Y.Z    (got '${VERSION:-nothing}')" >&2
  exit 1
fi
TAG="v$VERSION"

# --- refuse to release from the wrong place -------------------------------- #
branch=$(git rev-parse --abbrev-ref HEAD)
[[ "$branch" == "dev" ]] || { echo "Release from 'dev', not '$branch'." >&2; exit 1; }

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree is dirty. Commit or stash first:" >&2
  git status --short >&2
  exit 1
fi

if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  echo "Tag $TAG already exists." >&2
  exit 1
fi

if ! grep -q "^## \[Unreleased\]" CHANGELOG.md; then
  echo "CHANGELOG.md has no '## [Unreleased]' section to promote." >&2
  exit 1
fi

# An empty Unreleased section means there is nothing to release, which is
# usually a sign the changelog was not updated rather than that nothing changed.
unreleased_body=$(awk '/^## \[Unreleased\]/{f=1;next} /^## \[/{f=0} f' CHANGELOG.md | tr -d '[:space:]')
if [[ -z "$unreleased_body" ]]; then
  echo "CHANGELOG.md's Unreleased section is empty — write the entries first." >&2
  exit 1
fi

# --- gates ------------------------------------------------------------------ #
echo "→ backend tests"
(cd backend && uv run pytest -q >/dev/null && uv run ruff check >/dev/null)
echo "  ✓ green"

echo "→ dashboard typecheck, lint and brand gates"
(
  cd dashboard
  export NVM_DIR="$HOME/.nvm"
  # shellcheck disable=SC1091
  [[ -s "$NVM_DIR/nvm.sh" ]] && . "$NVM_DIR/nvm.sh"
  npx tsc --noEmit && npm run lint --silent && npm run verify:brand --silent
) >/dev/null
echo "  ✓ green"

# --- changelog: promote Unreleased to this version -------------------------- #
TODAY=$(date +%F)
python3 - "$VERSION" "$TODAY" <<'PY'
import pathlib, re, sys
version, today = sys.argv[1], sys.argv[2]
p = pathlib.Path("CHANGELOG.md")
s = p.read_text()
s = s.replace("## [Unreleased]\n", f"## [Unreleased]\n\n## [{version}] - {today}\n", 1)
# Keep the link refs at the bottom honest.
s = re.sub(r"\[Unreleased\]: (\S+)/compare/v[0-9.]+\.\.\.dev",
           rf"[Unreleased]: \1/compare/v{version}...dev", s, count=1)
if f"[{version}]:" not in s:
    s = s.rstrip("\n") + (
        f"\n[{version}]: https://github.com/AliasgherBS/qonvo/releases/tag/v{version}\n"
    )
p.write_text(s)
PY

sed -i -E "0,/^version = \"[0-9]+\.[0-9]+\.[0-9]+\"/s//version = \"$VERSION\"/" backend/pyproject.toml
sed -i -E "0,/\"version\": \"[0-9]+\.[0-9]+\.[0-9]+\"/s//\"version\": \"$VERSION\"/" dashboard/package.json
echo "→ bumped to $VERSION and promoted the changelog"

# --- the release notes are that version's changelog section ----------------- #
NOTES=$(awk -v v="## [$VERSION]" 'index($0,v)==1{f=1;next} /^## \[/{f=0} f' CHANGELOG.md)

git add CHANGELOG.md backend/pyproject.toml dashboard/package.json
git commit -q -m "chore(release): $TAG"

git switch -q main
git merge --no-ff -q dev -m "release: $TAG"
git tag -a "$TAG" -m "$TAG

$NOTES"

echo
echo "✓ $TAG merged to main and tagged."
echo
echo "Review it:   git show $TAG --stat | head -40"
echo "Publish it:  git push origin main dev && git push origin $TAG"
echo "Undo it:     git tag -d $TAG && git switch main && git reset --hard HEAD~1"
