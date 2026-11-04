# Repository guidance for coding agents

These instructions apply throughout this repository. Follow the user's requested scope and preserve unrelated work. Keep this file focused on durable project rules; use the linked documentation for detailed behavior and current compatibility information.

## Project and code map

XPON ONU Stick is a Home Assistant custom integration for monitoring ONU sticks through the stock GPON/EPON web interface or ODI OSS GPON SSH. ODI OSS can also synchronize its runtime clock. The domain is `xpon_onu_stick`.

Keep these architectural boundaries clear:

| Area | Starting points |
| --- | --- |
| Shared device code | [Client workflow](custom_components/xpon_onu_stick/api.py), [HTTP transport](custom_components/xpon_onu_stick/transport.py), and [status/capability types](custom_components/xpon_onu_stick/models.py). |
| Device differences | [Interface adapters](custom_components/xpon_onu_stick/devices/) own status/authentication formats. Boa uses stock pages and firmware profiles. ODI OSS uses a fixed SSH status batch and supports runtime clock synchronization. |
| Home Assistant integration | The [integration package](custom_components/xpon_onu_stick/) owns entry lifecycle, configuration, polling, entities, advisory statuses, and resource registration. |
| Dashboard | The [bundled card](custom_components/xpon_onu_stick/frontend/) uses Home Assistant data. [Preview tools](tools/card/) use sample readings. |
| Tests and developer tools | [Tests](tests/) cover captured firmware, simulator behavior, Home Assistant, and the browser. Follow the [development guide](docs/development.md) for commands. |

See [device adapters and firmware profiles](docs/device-adapters.md) for detailed module ownership and the process for adding devices. Existing parser imports from the shared client remain compatibility exports.

Before changing behavior, read [connection behavior](docs/behavior.md), [firmware values](docs/firmware-values.md), and the relevant tests.

## Working conventions

- Check `git status --short` before editing. Preserve existing staged, unstaged, and untracked work; do not reset, clean, or include unrelated changes.
- Keep changes within the requested scope. An inspection or planning request does not authorize implementation.
- Use the current code, metadata, and captured fixtures as evidence. Do not copy old domain names, versions, sensor counts, or compatibility claims from earlier notes without checking them.
- Follow the existing asynchronous Home Assistant patterns. Avoid blocking I/O in the event loop and reuse the integration's client/coordinator helpers.
- Python style is defined in `pyproject.toml`: Python 3.14, 100-character formatting, and the configured Ruff rules. Follow the existing JavaScript style; the dashboard has no package-manager build step.
- Prefer existing Home Assistant dependencies and project tools. Keep dependency or build-system changes tied to a concrete requirement.
- Do not commit, push, tag, publish a release, or modify a live installation unless the user has requested that action.

## Device access and session rules

The request boundary declared in the [Boa adapter](custom_components/xpon_onu_stick/devices/boa/__init__.py) and enforced by the [shared transport](custom_components/xpon_onu_stick/transport.py) is deliberate. Its verified paths come from the [integration constants](custom_components/xpon_onu_stick/const.py):

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/status.asp` | Device Status. |
| GET | `/status_pon.asp` | PON Status. |
| GET | `/admin/login.asp` | Supported login form. |
| POST | `/boaform/admin/formLogin` | Form authentication when needed. |
| POST | `/boaform/admin/formLogout` | Optional logout of the integration's own session. |

- Preserve the selected adapter's reviewed request allowlist. New endpoints require captured behavior and regression coverage. Do not submit Refresh/settings forms, probe configuration endpoints, reboot/reset devices, or change firmware or ISP credentials.
- Keep requests on the explicitly configured HTTP(S) origin. Validate login form targets before sending credentials. Do not follow redirects or execute page scripts; retain TLS certificate verification, request timeouts, and the response-size limit.
- The Boa adapter reads Device Status and PON Status sequentially. Preserve the shared per-origin lock so polling and connection validation cannot overlap against the same embedded server.
- Reuse validated clients across setup, polling, and reloads. Keep device cookies isolated from Home Assistant's shared HTTP session, and release cached credentials/cookies when a device is removed.
- Logout is disabled by default. Only log out after a successful poll when the option is enabled and the integration owns the form-login session. Never close a borrowed/browser session, force logout after a busy-login response, or log out during connection validation or a failed poll.
- A logout failure must preserve the successful readings and allow a later retry. Authentication failures must still reach Home Assistant's reauthentication flow.
- Default checks use fixtures and localhost simulators. Run a physical-device check only when requested, using an explicitly supplied address. Never infer a management address or reuse credentials found elsewhere.
- Use the existing private password prompt for live checks. Keep credentials, cookies, raw HAR files, and personal network details out of source files, command arguments, public logs, and agent configuration.
- Keep ODI OSS SSH polling on the configured endpoint with a pinned Ed25519 host fingerprint and dedicated key file. Preserve the fixed read-only command, endpoint lock, reply/deadline bounds, and filtering of identifying GPON fields on the stick. Treat new commands as request policy changes that require captured evidence and regression coverage.
- Limit ODI OSS clock synchronization to the runtime clock, after a successful status poll on the same SSH connection with the configured MAC and the option enabled. Only interpolate the Home Assistant Unix timestamp into the fixed clock command. Preserve valid readings when clock synchronization fails.

## Readings and Home Assistant identity

- Publish a snapshot only after the selected adapter's required pages and MAC identity have been validated. The Boa adapter requires both Device Status and PON Status. Connection, authentication, page-structure, or identity failures make the device's sensors unavailable.
- Isolate malformed individual readings: preserve other valid values, expose the affected field's `parse_error`, and recover automatically when valid data returns. Avoid repeating unchanged parse-error logs.
- Empty or documented unknown values remain unknown. Never convert missing, invalid, infinite, or NaN readings to zero; preserve valid zero and negative values where the measurement supports them. Follow [firmware value handling](docs/firmware-values.md) for accepted units and formats.
- Keep the raw GPON state separate from its friendly classification. EPON LLID values are raw nonnegative integer codes keyed by the reported index; do not translate them into GPON registration states or invent meanings without device evidence.
- Preserve bounds on response size, numeric text, and dynamic LLID sensor creation. Reject ambiguous PON modes and invalid/duplicate LLID indices rather than guessing which readings belong together.
- The MAC address is the device identity. An address change for the same MAC must preserve entities; a different MAC must not replace the existing device. Preserve duplicate-device detection and reconfiguration checks.
- Keep entity unique IDs, sensor keys, translation keys, and the integration domain stable. Treat changes to persisted identifiers or configuration schemas as migration work, with explicit regression coverage.
- Common entities survive GPON/EPON mode changes. Discover new LLID indices without duplicating entities; absent indices and entities for the inactive mode become unavailable.
- All sensors share the coordinator's poll. Preserve the interval limits in the [integration constants](custom_components/xpon_onu_stick/const.py) and existing options when updating one options form. Status thresholds are advisory and do not change the device.
- Keep [strings.json](custom_components/xpon_onu_stick/strings.json) and [translations/en.json](custom_components/xpon_onu_stick/translations/en.json) identical. Update translation labels and status choices alongside config-flow, sensor, or health-status changes.

## Device adapters and profiles

- Follow [device adapters and firmware profiles](docs/device-adapters.md). Organize code by the web-interface family. Use small, evidence-backed profiles for differences within that family instead of copying clients per device model or firmware version.
- Keep adapters, status types, and transport independent of Home Assistant APIs. All adapters must use the shared request function, policy enforcement, device lock, cookie handling, and session-ownership workflow.
- Match firmware exceptions only after validating page structure and detecting PON mode. Unknown firmware may use the generic supported schema. Do not use branding or firmware comments to infer hardware identity, try multiple login protocols, or silently choose among ambiguous matches.
- Distinguish supported-but-invalid readings, optional missing rows, and unsupported capabilities. Optional values that are present but corrupt still need field errors. MAC identity always remains required.
- Discover newly supported entities without changing existing IDs. Unsupported capabilities must also apply to related friendly statuses, and existing entities must become unavailable rather than being removed.
- New profiles need sanitized capture evidence and regression coverage. New interface families need an explicit or deterministic selection path, reviewed request endpoints, and shared contract tests. Update this code map when adding or moving modules.

## Dashboard card

- Keep the card as a bundled, dependency-free custom element unless the task specifically requires changing that architecture.
- Discover entities through Home Assistant's entity/device metadata and translation keys. Do not assume users retain default entity IDs or that there is only one stick.
- Read state and history through Home Assistant; the card must not contact the ONU directly.
- Escape firmware text, entity text, and user configuration when inserting HTML. Preserve safe rendering for unknown, unavailable, malformed, and missing states, including during mode/device changes.
- Preserve the persistent [Lovelace module registration](custom_components/xpon_onu_stick/frontend.py), duplicate-resource handling, and the cache version derived from the [integration manifest](custom_components/xpon_onu_stick/manifest.json). Keep YAML-managed resource instructions accurate.
- Exercise relevant preview scenarios and browser tests after card changes. Inspect light and dark themes and regenerate committed screenshots only when the displayed UI changes.
- `.claude/launch.json` is a shared shortcut for the same local preview. Keep its paths relative and free of personal settings or secrets.

## Setup and validation

Run commands from the repository root. The pinned Home Assistant test environment requires **Python 3.14.2 or newer within the 3.14 series**. Use the existing `.venv`; the setup script uses `python3.14` by default, with `PYTHON` available to select another executable when creating it.

```sh
# Create the environment if needed, install pinned dependencies, and run checks.
./scripts/test.sh --setup

# Run checks with an existing environment, without accessing a physical ONU.
./scripts/test.sh

# Run a focused regression file during development.
.venv/bin/python -m pytest -q tests/test_devices.py

# Preview or test the dashboard with sample data.
./scripts/card.sh debug --no-open
./scripts/card.sh test

# Regenerate the documented dashboard images after an intentional UI change.
./scripts/card.sh screenshots
```

`scripts/test.sh` checks shell syntax, repository metadata/assets, installed dependencies, Ruff lint/formatting, and the full pytest suite. Logs and browser failure artifacts go in `.test-results/`.

The dashboard tests need Chrome, Edge, Chromium, or Brave; `CHROME_PATH` selects the executable. Some pytest browser tests skip when no browser is available. Report skipped browser coverage explicitly rather than claiming the UI passed.

For authorized live checks, follow [the development guide](docs/development.md#test-the-real-stick). Keep them separate from the normal simulator checks.

### Choose coverage by the change

| Change | Relevant regression coverage |
| --- | --- |
| Parsing, values, or PON modes | `tests/test_api.py`, `tests/test_epon.py`, and `tests/test_device_captures.py`. |
| Interface adapters, firmware profiles, or capabilities | `tests/test_devices.py` and `tests/test_integration.py`. |
| Login, cookies, request boundaries, or logout | `tests/test_form_auth.py`, `tests/test_logout.py`, and `tests/test_device_captures.py`. |
| ODI OSS SSH, telemetry, or diagnostics | `tests/test_odi_oss.py`. |
| Setup, identity, polling, options, or recovery | `tests/test_integration.py`. |
| Thresholds or friendly statuses | `tests/test_health.py` and `tests/test_integration.py`. |
| Card registration or dashboard behavior | `tests/test_card.py`, `tests/test_card_ui.py`, and `tools/card/ui-tests.js`. |
| Developer commands or repository metadata | `tests/test_tools.py` and `tests/test_repository.py`. |

- Add regression coverage for behavior changes and bug fixes, including failure and recovery where relevant. Preserve the real Home Assistant/local-server tests rather than replacing them with mocks that bypass the affected behavior.
- Use focused tests while developing, then run `./scripts/test.sh` for code changes. For documentation-only work, check references, commands, factual accuracy, and the diff; a full integration/browser run is unnecessary unless the documentation change reveals a behavior issue.
- CI additionally runs hassfest, HACS validation, and a tag/manifest version check. Local tests do not prove these remote checks passed.
- Distinguish simulator/browser evidence from physical-device compatibility and acceptance in a running Home Assistant dashboard. State what was actually checked and what remains unverified.

## Captured firmware pages and compatibility

- Follow [fixture layout and provenance](tests/fixtures/README.md) and [device support requests](docs/device-support.md). Store captured HTML under `tests/fixtures/devices/<model>/<firmware>/`; use `default` for unknown firmware.
- Capture the status frame or actual response body, not just the outer frameset or browser View Source wrapper. Preserve labels, tables, units, form actions, unusual markup, and relevant response messages.
- Sanitize every capture, including comments, scripts, hidden fields, and URLs. Replace identifying addresses with documentation/test values while preserving the HTML structure; remove passwords, tokens, serial numbers, and LOID credentials.
- Keep sanitized captures and provenance intact. Retain older snapshots with `_baseline` filenames; simulate additional failures or values in tests instead of presenting edited data as a new capture.
- Use confirmed device/model names. Do not infer hardware identity from commented firmware metadata or turn likely compatibility into tested support.
- Update [compatibility](docs/compatibility.md) only with the evidence available. A related chipset or a passing fixture test alone does not establish physical-device support.

## Documentation, metadata, and delivery

- Keep `README.md` as the user-facing overview and put detailed instructions in the appropriate `docs/` page. Update behavior, configuration, sensor, dashboard, and compatibility documentation when the corresponding contract changes.
- The release version comes from `custom_components/xpon_onu_stick/manifest.json`. Change it only as part of requested version/release work; update documented resource URLs and release notes when applicable. CI expects numeric `major.minor.patch` tags matching the manifest exactly.
- Keep `hacs.json`'s minimum Home Assistant version aligned with the tested pin in `requirements-dev.txt` and the installation requirements in the docs.
- Preserve the single-integration HACS layout, Apache license and attribution, and bundled brand assets. `tools/validate_repository.py` checks metadata, translations, and required 256/512-pixel RGBA PNG icons. Local brand assets do not prove HACS listing artwork works.
- Keep `.venv/`, caches, `.test-results/`, `dist/`, unsanitized device exports, and machine-specific files out of version control. Do not overwrite existing changelog work as part of an unrelated change.
- Before handing off, review the diff for unrelated edits and sensitive data. Report the resulting behavior, checks actually run, failures/skips, and any remaining device or Home Assistant validation. Leave commit/push/release actions to the user's requested scope.

## Code Review Rules

- Flag any path that can send credentials outside the configured origin, execute captured page content, submit device settings, or end a session the integration does not own.
- Flag changes that turn unknown/invalid readings into plausible measurements, hide device-level failures behind stale available values, or change persisted entity identity without migration handling.
- Flag uncapped LLID/entity growth, overlapping device requests, and dashboard rendering that inserts unescaped device/user text.
- Flag compatibility or validation claims that exceed the recorded fixture, browser, live-device, or Home Assistant evidence. Leave routine formatting checks to the configured tools.
