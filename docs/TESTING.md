# Testing paperhound

Three layers — pick the right one for the change you're shipping:

| Layer | Where | When | Network |
|---|---|---|---|
| **Unit** | `tests/unit/` | Every commit (`make check`) | Mocked (`respx`) — no network |
| **Integration** | `tests/integration/` | `make test-integration`, CI on demand | Live arXiv / OpenAlex / DBLP / Crossref / HF |
| **Live smoke** | This document | After every PyPI publish | Live — exercises the published CLI + agent skill end-to-end |

`make check` is the gate. CI runs the same gate. The live smoke pass is a
post-release rite — it tests the *published* artifact, not the editable repo.

## Unit tests — non-negotiables

- One file per module under `tests/unit/test_<module>.py`.
- Mock all HTTP with `respx`. Never depend on real network.
- Cover happy path, every documented edge case, one negative path (invalid
  input → typed error from `paperhound.errors`), one regression seed if a fix
  motivated the test.
- Parametrize edge cases instead of copy-pasting.
- For CLI commands: `typer.testing.CliRunner` + monkeypatched aggregator /
  downloader. Assert exit code and stdout/stderr separately.

## Integration tests

- Live API calls only. `tests/integration/test_<provider>_live.py`.
- Keep them tiny — one real query per provider, assert *shape* not contents
  (titles change, counts drift). Never assert on a specific paper unless you
  use a stable arXiv id.
- Add a new file only when the feature touches a new external surface.

## Live smoke — standardized procedure

Run **after** the `Publish to PyPI` workflow finishes for the release you want
to validate. Goal: make sure the published wheel + the published skill work
end-to-end against live providers, before users hit any breakage.

The whole pass is ~3 minutes warm, ~5 minutes cold (first run downloads the
docling OCR model). One operator, one terminal, copy-pasteable.

### 0. Pre-flight — install the latest published bits

Always start from a clean scratch dir; never run smoke from inside the repo.

```bash
# Clean scratch
rm -rf /tmp/ph-smoke && mkdir -p /tmp/ph-smoke && cd /tmp/ph-smoke

# 0.1 — latest CLI from PyPI
uv tool upgrade paperhound      # or: pipx upgrade paperhound
INSTALLED=$(paperhound version)
EXPECTED=$(curl -fsS https://pypi.org/pypi/paperhound/json | python3 -c 'import json,sys;print(json.load(sys.stdin)["info"]["version"])')
echo "installed=$INSTALLED expected=$EXPECTED"
test "$INSTALLED" = "$EXPECTED" || { echo "FAIL: stale binary"; exit 1; }

# 0.2 — latest agent skill from GitHub (skills.sh installs to <cwd>/.agents/skills/)
npx -y skills add alexfdez1010/paperhound -y
SKILL_MD=./.agents/skills/paperhound/SKILL.md
test -f "$SKILL_MD" || { echo "FAIL: skill not installed"; exit 1; }
grep -q "^name: paperhound" "$SKILL_MD" \
  || { echo "FAIL: skill frontmatter"; exit 1; }

# 0.3 — sanity: which binary, which Python
which paperhound
paperhound --help > /dev/null
```

Pre-flight pass criteria:
- `paperhound version` prints the same version as PyPI's `info.version`.
- `./.agents/skills/paperhound/SKILL.md` exists with a `name: paperhound`
  frontmatter line (skills.sh installs project-scoped, into the current dir).
- `paperhound --help` exits 0 and lists the six commands (`version`, `search`,
  `show`, `download`, `convert`, `get`).

### 1. Smoke matrix — what to run, what to check

Run each step in order. Each step has an explicit pass criterion. Keep a
running tally — every step must pass before declaring the release green.

| # | Command | Pass criteria | Cold time |
|---|---|---|---|
| 1 | `paperhound search "retrieval augmented generation" -n 5` | exit 0; ≥ 3 distinct values in `Sources` column; no `&amp;`/`&lt;` in any title; wall time < 5 s | ~3 s |
| 2 | `paperhound search "vision transformers" -n 3 -s arxiv --json \| jq '.[0].title'` | exit 0; non-empty title; arxiv id matches `^[0-9]{4}\.[0-9]{4,5}$` in `.[0].identifiers.arxiv_id` | ~1 s |
| 3 | `paperhound search "graph neural networks" -n 3 -s openalex` | exit 0; 3 rows; `Sources` column = `openalex` for every row | ~1 s |
| 4 | `paperhound search "" -n 3` | exit ≠ 0; stderr contains `empty`; **no** results table printed | <0.1 s |
| 5 | `paperhound show 2401.12345` | exit 0; stdout contains the title `Distributionally Robust Receive Combining`, an `arXiv:` line, and an `Abstract` section | ~1 s |
| 6 | `paperhound show 10.48550/arXiv.2401.12345 --json \| jq -e '.title \| length > 0'` | exit 0 (jq returns truthy); JSON parses | ~1 s |
| 7 | `paperhound download 2401.12345 -o ./papers/` | exit 0; `papers/2401.12345.pdf` exists; `file` reports `PDF document` | ~1 s |
| 8 | `paperhound download 2401.12345 -o ./fresh-dir` (no slash, missing) | exit 0; `fresh-dir` is a **directory** (`test -d fresh-dir`); contains `2401.12345.pdf` | ~1 s |
| 9 | `paperhound convert papers/2401.12345.pdf -o paper.md` | exit 0; `paper.md` ≥ 5 KB; first non-blank line starts with `## ` (a heading) | 10–15 s |
| 10 | `paperhound get 2005.11401 -o rag.md` | exit 0; `rag.md` first heading is `## Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks`; ≥ 300 lines | 70 s cold / 10 s warm |
| 11 | `paperhound show invalid-id-zzz` | exit code 1; stderr contains `Not found` | <1 s |
| 12 | `paperhound search "rare-string-zzzzzzzzzzz12345" -n 3 -s arxiv` | exit 0; stderr contains `No results` | ~1 s |
| 13 | Skill smoke: `grep -cE "paperhound (search\|show\|download\|convert\|get)" ./.agents/skills/paperhound/SKILL.md` | ≥ 5 matches (every command documented) | <0.1 s |

### 2. Copy-paste runner

A single block that runs the matrix above and exits non-zero on the first
failure. Suitable for an agent or a CI shell step.

```bash
set -euo pipefail
cd /tmp/ph-smoke

step() { echo "── step $1 ──"; }

step 1
out=$(paperhound search "retrieval augmented generation" -n 5)
echo "$out"
distinct=$(echo "$out" | grep -oE "(arxiv|openalex|dblp|crossref|huggingface)" | sort -u | wc -l)
test "$distinct" -ge 3 || { echo "FAIL: only $distinct distinct sources"; exit 1; }
echo "$out" | grep -q "&amp;" && { echo "FAIL: HTML entity leak"; exit 1; } || true

step 2
paperhound search "vision transformers" -n 3 -s arxiv --json \
  | jq -e '.[0].identifiers.arxiv_id | test("^[0-9]{4}\\.[0-9]{4,5}$")' >/dev/null

step 3
paperhound search "graph neural networks" -n 3 -s openalex | grep -q openalex

step 4
if paperhound search "" -n 3 2>err.log; then echo "FAIL: empty query accepted"; exit 1; fi
grep -qi empty err.log || { echo "FAIL: empty-query message missing"; exit 1; }

step 5
paperhound show 2401.12345 | tee show.log | grep -q "Distributionally Robust"
grep -q "arXiv:" show.log
grep -qi "abstract" show.log

step 6
paperhound show 10.48550/arXiv.2401.12345 --json | jq -e '.title | length > 0' >/dev/null

step 7
rm -rf papers && paperhound download 2401.12345 -o ./papers/
file papers/2401.12345.pdf | grep -q "PDF document"

step 8
rm -rf fresh-dir && paperhound download 2401.12345 -o ./fresh-dir
test -d fresh-dir
test -f fresh-dir/2401.12345.pdf

step 9
paperhound convert papers/2401.12345.pdf -o paper.md
test "$(wc -c < paper.md)" -ge 5000
head -n 5 paper.md | grep -qE '^## '

step 10
paperhound get 2005.11401 -o rag.md
head -n 1 rag.md | grep -q "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks"
test "$(wc -l < rag.md)" -ge 300

step 11
if paperhound show invalid-id-zzz 2>err.log; then echo "FAIL: bad id accepted"; exit 1; fi
grep -qi "not found" err.log

step 12
paperhound search "rare-string-zzzzzzzzzzz12345" -n 3 -s arxiv 2>err.log
grep -qi "no results" err.log

step 13
matches=$(grep -cE "paperhound (search|show|download|convert|get)" ./.agents/skills/paperhound/SKILL.md)
test "$matches" -ge 5

echo "── ALL SMOKE STEPS PASSED ──"
```

### 3. What to record

When a step fails, capture the failing command + output and open an issue.
Don't commit per-release smoke reports to the repo — they go stale fast and
the procedure above is the canonical artifact.

## When smoke fails

1. Reproduce the failure in a unit test under `tests/unit/`.
2. Fix the code.
3. Add the regression seed to the unit test so it runs on every `make check`.
4. Bump the version (`pyproject.toml`), commit, push to `main` → PyPI publish.
5. Re-run the live smoke pass against the freshly published version.
