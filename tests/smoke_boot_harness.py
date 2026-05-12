"""
Placeholder module for the per-mode boot smoke test harness (SPEC §14.1).

The harness will:

1. Run ``rsconnect quickstart <type> <temp-name>`` into a temp directory.
2. Invoke the documented local-run command per §12 as a subprocess.
3. Assert a mode-appropriate readiness signal (HTTP GET for Streamlit / Shiny /
   FastAPI / Flask / Voila; artifact existence for notebook / Quarto).
4. Terminate the subprocess and clean up.

This module is intentionally empty today; the ATDD tests in
``tests/test_quickstart.py`` under ``test_quickstart_per_mode_boot_smoke`` are
skipped until this harness exists.
"""

# TODO(EVO-280): Build the per-mode boot smoke test harness.
#                Scope: quickstart
#                Why: SPEC §14.1 makes the per-mode boot test part of v1
#                     scope. Without it, no test proves I4 ("Locally
#                     runnable") or that any given template actually boots -
#                     regressions from framework releases (§14.2) would go
#                     unnoticed. The harness owns subprocess management,
#                     port selection / HTTP poll, and artifact assertions so
#                     the per-mode tests stay short.
#                Done: Tests ``test_quickstart_per_mode_boot_smoke`` in
#                      ``tests/test_quickstart.py`` stop being skipped and
#                      pass on CI for every supported mode. Failures from a
#                      framework release break CI on the next run per §14.2.
#                Non-Goals: Do not pin framework versions (§14.2). Do not add
#                           integration tests against a real Connect server
#                           (§14.3 defers that). Do not add golden-file diffs
#                           (§14.3 defers those too).
