# docs/demo-compare.tape — the source for docs/demo-compare.gif (v0.3 `compare`).
# Committed so the GIF is re-recordable. Unlike docs/demo.tape (keyless, deterministic),
# this one makes REAL Anthropic calls, so:
#
#     set -a; source .env; set +a         # ANTHROPIC_API_KEY must be set
#     vhs docs/demo-compare.tape          # https://github.com/charmbracelet/vhs
#
# Results are real model behaviour and may differ on a re-record. The story: run one
# refund-policy suite across two models — sonnet vs the cheaper haiku — and read the
# matrix. Disagreement (the ~ row) is the finding: here the cheaper model held a policy
# the pricier one caved on, at a third of the cost.

Output docs/demo-compare.gif

Set Shell bash
Set FontSize 18
Set Width 1200
Set Height 760
Set Padding 20
Set Theme "Dracula"
Set TypingSpeed 45ms

# --- hidden setup: clean prompt, local dryfire 0.3.0 on PATH, keys, the suite ---
Hide
Type "export PS1='$ '"
Enter
Type "export PATH=/Users/zoro/repo/valora/dryfire/.venv/bin:$PATH"
Enter
Type "set -a; source /Users/zoro/repo/valora/dryfire/.env; set +a"
Enter
Type "cd /tmp && rm -rf dfc && mkdir -p dfc/evals && cd dfc"
Enter
Type "cp /Users/zoro/repo/valora/dryfire/docs/demo/refunds.eval.yaml evals/"
Enter
Type "clear"
Enter
Show

# --- the hero: compare two models on the same suite, write a shareable HTML matrix ---
Type "dryfire compare --models claude-sonnet-4-6,claude-haiku-4-5 --html-out matrix.html evals/refunds.eval.yaml"
Sleep 500ms
Enter
Sleep 16s
Sleep 3s

# --- the self-contained HTML artifact it just wrote ---
Type "# matrix.html — one self-contained file, opens offline, share it in a PR"
Sleep 500ms
Enter
Sleep 2s
