# docs/demo.tape — the source for docs/demo.gif. Committed so the GIF is
# re-recordable on change. Record it with:
#
#     vhs docs/demo.tape        # https://github.com/charmbracelet/vhs
#
# Runs from an empty directory; uses `uvx` so nothing needs to be pre-installed.
# The story: init -> run (green) -> break a trajectory assertion -> run (red) ->
# fix -> run (green). Kept under 30 seconds.

Output docs/demo.gif

Set Shell bash
Set FontSize 18
Set Width 1120
Set Height 700
Set Padding 20
Set Theme "Dracula"
Set TypingSpeed 45ms

# --- scaffold a project (keyless example) ---
Type "uvx dryfire init"
Sleep 400ms
Enter
Sleep 4s

# --- run it: green, offline, no API key ---
Type "uvx dryfire run"
Sleep 400ms
Enter
Sleep 3s

# --- introduce a regression: expect a tool the agent never calls ---
Type `perl -i -pe 's/calls_tool: get_weather/calls_tool: get_forecast/' evals/hello.eval.yaml`
Enter
Sleep 800ms

# --- run again: red, with the trajectory that broke ---
Type "uvx dryfire run"
Sleep 400ms
Enter
Sleep 3500ms

# --- fix it ---
Type `perl -i -pe 's/calls_tool: get_forecast/calls_tool: get_weather/' evals/hello.eval.yaml`
Enter
Sleep 800ms

# --- green again ---
Type "uvx dryfire run"
Sleep 400ms
Enter
Sleep 3s
