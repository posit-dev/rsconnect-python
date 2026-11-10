# Groom: Content management, CLI output & shinyapps.io

Research for #963 (map #956). Each of the 27 open issues in this batch was checked against the code at `main` @ `2ea5fdd2` (rsconnect-python 1.33.2.dev1), git history, merged PRs, and `docs/CHANGELOG.md`. CLI behaviour was checked with `uv run rsconnect ... --help`. No live Connect, shinyapps.io, or Connect Cloud server was contacted.

File references (`file:line`) are to `2ea5fdd2`.

## Summary

| Verdict | Count | Issues |
| --- | --- | --- |
| Resolved | 3 | #462, #491, #547 |
| Obsolete | 2 | #357 (duplicate of #332), #474 |
| Still valid | 19 | #332, #430, #439, #481, #494, #505, #506, #507, #542, #543, #654, #663, #678, #683, #686, #703, #746, #756, #760 |
| Unclear | 3 | #455, #465, #523 |

Proposed for closing: 5 (#462, #491, #547 as `completed`; #474 as `not planned`; #357 as duplicate of #332).

## Duplicates and related issues

- **#357 duplicates #332.** Both ask to choose the content's URL at deploy time instead of discovering it after the first deploy. Keep **#332**: it names the concrete mechanism (vanity URL, matching `connectapi::set_vanity_url`), links the Connect API endpoint, and has maintainer discussion. #357's other pain point (needing `--app-id` to redeploy) is already handled by the local deployment record, which a redeploy from the same directory reuses.
- **#663, #756, #760, #678 are related but not duplicates.** #663 is "show logs automatically when verification fails", #756 is "a command to fetch a content item's logs", #760 is "machine-readable output for every command", and #678 is "print the content URL when the build fails". A `logs` command (#756) would make #663 easy to implement, but each asks for a different change. Keep all four open.
- **#505 and #506** are a pair (`kill`, then `restart` built on it). Not duplicates.
- **#462** was called "essentially the same as" #296 by a maintainer. #296 is already closed (not planned, 2025-12-06), so there's nothing to merge.

## Verdict table

| Issue | Verdict | Evidence | Proposed close reason |
| --- | --- | --- | --- |
| #332 [Question] Adding a custom URL to an app during deployment | Still valid | No vanity URL support anywhere in `rsconnect/` (`grep -i vanity rsconnect/*.py` returns no CLI option or API call). `deploy` options listed by `rsconnect deploy fastapi --help` have no URL/vanity flag. Feature request. | — |
| #357 rsconnect and predefined app name/url | Obsolete (duplicate) | Same request as #332 (pick the URL before deploying). The "must know the app id to redeploy" half is handled by deployment records: a deploy with no target reuses the directory's record (CHANGELOG 1.31.0), stored by `save_deployed_info` (`rsconnect/api.py:2461-2463`). | duplicate-of #332 |
| #430 support tags in rsconnect content search | Still valid | `rsconnect content search --help` offers `--published`, `--unpublished`, `--content-type`, `--r-version`, `--py-version`, `--title-contains`, `--order-by`. No tag filter. | — |
| #439 Raise an error if providing environment variables to shinyapps.io | Still valid | The shinyapps.io branch of `deploy_bundle` (`rsconnect/api.py:2333-2360`) never reads `self.env_vars`, and nothing in `validation.py` rejects `-E` for shinyapps.io. CHANGELOG 1.31.0: "Other Posit Connect deploy options remain accepted and ignored for shinyapps.io." | — |
| #455 Unable to Deploy Shiny for Python app to Shiny Apps IO | Unclear | The error is in a screenshot and the reporter never replied to the maintainer's request for details (2023-07). #453 (1.20.0) added shinyapps.io build-log output on failure, which was the suggested next step. A repro needs a live shinyapps.io account. Candidate for `needs-info` in a later pass. | — |
| #462 Need a flag to stop web browser opening a new tab after successful deployment to shinyapps.io | Resolved | #828 (1.31.0) added `--quiet` to all `deploy` subcommands. The shinyapps.io path only opens the browser `if not logger.quiet` (`rsconnect/api.py:2352-2354`). CHANGELOG 1.31.0: "for shinyapps.io deploys it also skips opening a browser." | completed |
| #465 Deployment to shinyapps.io with a shiny app fails with 599 status code | Unclear | The 599 is reported by shinyapps.io's build task ("Child Task ... Unhandled Exception: 599"), which points to a server-side failure, not this CLI. Intermittent, and needs a live shinyapps.io deploy to check. | — |
| #474 Set content_category on static outputs and revisions | Obsolete | This was a Posit Cloud API feature. #735 (1.28.2) removed Posit Cloud publishing: "Removed support for publishing to Posit Cloud. Posit Cloud no longer hosts deployed content." | not planned |
| #481 rsconnect deploy --help is wrong? (Suggests shinyapps.io supports non-shiny apps) | Still valid | `rsconnect deploy --help` still lists shinyapps.io for `streamlit`, `dash`, `bokeh`, `fastapi`, `flask`, `api`, `gradio`, `panel`, `html`. The short help is built with a hard-coded "or shinyapps.io." for every Python app type (`rsconnect/main.py:3535`). Only the long help adds "(if supported by the platform)" (`rsconnect/main.py:3541`). | — |
| #491 Suggestion: rename `rsconnect deploy api` command to `rsconnect deploy flask` | Resolved | #499 (merged 2023-10-23, 1.21.0) added `deploy flask` and `write-manifest flask`, keeping `api` for compatibility. CHANGELOG 1.21.0: "Added the `deploy flask` command." `rsconnect deploy flask --help` shows "Deploy a Flask API module…". | completed |
| #494 Content search function to return all non-scheduled content | Still valid | `content search` has no schedule filter (see #430 evidence). Feature request. | — |
| #505 `rsconnect kill <content_id> [<job_id>]` | Still valid | No `kill` command in `rsconnect --help`/`rsconnect content --help`. No client method calls the `v1/content/{guid}/jobs` API (`grep "/jobs" rsconnect/api.py` is empty). | — |
| #506 `rsconnect restart <content_id>` | Still valid | No `restart` command (as #505). | — |
| #507 `rsconnect clone <content_id>` | Still valid | Partly covered: `content download-bundle` downloads a bundle and `deploy bundle` (1.30.0) redeploys one. The request is a single command that downloads, untars, and writes a deployment record so the next `deploy` updates the original item. That does not exist. | — |
| #523 KeyError: 'id' when deploying jupyter notebook | Unclear | Reporter traced it to a saved server URL ending in `//`. That URL is still not normalized: `append_to_path('http://h.example.com//', '__api__')` returns `http://h.example.com//__api__` (`rsconnect/http_support.py:276-291`, run locally). A redirect is always re-sent as `GET` (`rsconnect/http_support.py:793-794`), so a redirected `POST v1/content` (`rsconnect/api.py:703`) could still come back as a content list. The likely cause is still present, but confirming it needs a live server. | — |
| #542 error when existing content gone | Still valid | Connect deploys still fail with "Try setting the --new flag…" when the recorded content is gone (`rsconnect/api.py:1127-1131`, `2843-2853`). Only Connect Cloud falls back to creating new content (`rsconnect/api.py:4015-4027`). | — |
| #543 quarto: default name should default to directory name when using index.qmd | Still valid | `deploy quarto` passes the file as `path` (`rsconnect/main.py:3207`). The default title is `_default_title(self.path)` (`rsconnect/api.py:1347`), the file's basename without extension (`rsconnect/bundle.py:1884-1896`), so `index.qmd` still gives "index". | — |
| #547 `RSConnectExecutor.server_settings` throws error if `self.client` is a `PositClient` object | Resolved | #567 "Type cleanup" (merged 2024-04-04, commit `407e6db6`, released in 1.24.0) made `server_settings` raise a clear `RSConnectException` for non-Connect clients (`rsconnect/api.py:2882-2886`). Callers on shared deploy paths check `isinstance(ce.client, RSConnectClient)` first (e.g. `rsconnect/main.py:3700`), so shinyapps.io deploys don't reach it. #545, which hit this, merged. | completed |
| #654 Add "applications" method to rsconnect-python (already exists on R version) | Still valid | No command lists shinyapps.io applications (`rsconnect --help`). Feature request. | — |
| #663 Fetch logs if verification fails | Still valid | `verify_deployment` (`rsconnect/api.py:2759-2770`) calls `access_content`, which on failure raises only a link to the logs page (`rsconnect/api.py:666-674`). No job logs are fetched. | — |
| #678 Should output the content URL during deployment failure | Still valid | When the build task fails, `wait_for_task` raises `Task exited with status N.` with no content or logs URL (`rsconnect/api.py:1210-1214`). The URLs are only printed on success (`rsconnect/api.py:2453-2457`). | — |
| #683 Drop the "Direct Content URL" in output of deploys | Still valid | Still printed: `log_callback.info("\t Direct content URL: %s", ...)` (`rsconnect/api.py:2457`). Product call. | — |
| #686 improve output of `rsconnect details` | Still valid | `details` still prints `APIs: allowed`, lists Python versions without deduplicating, and shows only Python (`rsconnect/main.py:1356-1368`, `rsconnect/api.py:2937-2946`). | — |
| #703 support setting access type | Still valid | No deploy or content option sets Connect `access_type`. It appears only in a response TypedDict (`rsconnect/models.py:478`). `--visibility` applies to shinyapps.io/Connect Cloud only. | — |
| #746 `rsconnect system delete caches` reports success even if it fails | Still valid | `delete_runtime_cache` waits with `raise_on_error=False` and ignores the task result (`rsconnect/api.py:2998`). `system_caches_delete` then exits 0 (`rsconnect/main.py:6044-6071`). | — |
| #756 Provide agent-friendly interface for accessing logs of content | Still valid | No `logs`/`log` command in `rsconnect --help` or `rsconnect content --help`. | — |
| #760 feat: `--json` or something to return structured output | Still valid | Only `token --format json`, `preflight`, and resumable `login` emit JSON (CHANGELOG 1.32.0, 1.33.0). `deploy` has `--quiet` (URL only), but `deploy`, `content`, `details`, and `system` have no structured output. | — |

## Draft closing comments

### #357 (duplicate of #332)

> 🤖 Closing this as a duplicate of #332, which tracks choosing the content URL (vanity URL) at deploy time and has the most discussion. On the redeploy half: rsconnect-python saves a deployment record in `.rsconnect-python/` after each deploy, and a later deploy from the same directory reuses it, so you don't need to pass `--app-id`/`--guid` to update existing content (see the 1.31.0 CHANGELOG). If this still affects you in a way #332 doesn't cover, please reopen and tell us what's missing.

### #462 (completed)

> 🤖 This is resolved. Since 1.31.0 (#828), every `rsconnect deploy` subcommand accepts `--quiet`, and for shinyapps.io deploys `--quiet` also skips opening a browser (`rsconnect/api.py`, the `if not logger.quiet` check before `webbrowser.open_new`). For CI, use `rsconnect deploy shiny ... --quiet`. It prints only the deployed URL, which you can capture with `URL=$(...)`. If you still see a browser open with `--quiet`, please reopen with your version and command.

### #474 (not planned)

> 🤖 Closing as no longer applicable. This asked for `content_category` on Posit Cloud static outputs. rsconnect-python 1.28.2 (#735) removed Posit Cloud publishing because Posit Cloud no longer hosts deployed content. Posit Connect Cloud is supported instead. If you need something similar for Connect Cloud, please reopen or open a new issue describing it.

### #491 (completed)

> 🤖 This is resolved. rsconnect-python 1.21.0 (#499) added `rsconnect deploy flask` and `rsconnect write-manifest flask`. `deploy api` still works for backwards compatibility. If the `flask` command doesn't cover your case, please reopen and let us know.

### #547 (completed)

> 🤖 This is resolved. In #567 (released in 1.24.0, commit `407e6db6`), `RSConnectExecutor.server_settings` began raising a clear `RSConnectException` ("To get server settings, client must be a RSConnectClient.") instead of an `AttributeError` when the client isn't a Connect client. Shared deploy code checks `isinstance(ce.client, RSConnectClient)` before calling it, so shinyapps.io deploys no longer reach it. If you still hit this, please reopen with the command and traceback.
