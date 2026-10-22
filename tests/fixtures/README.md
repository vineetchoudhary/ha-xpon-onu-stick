# Device page fixtures

Store sanitized HTML by device model and firmware version:

```text
devices/<model>/<firmware>/
  device_status.html
  pon_status.html
  login.html
  logout.html
  logout_success.html
  login_busy.html
```

Include only captured pages. Use `default` when the firmware version is unknown.
Keep all HTML directly in the firmware directory, with `_baseline` filenames for
older snapshots. Do not mix firmware versions.

Use confirmed model names. Issue #1 uses `bdcom-unknown-model` because the exact
model is unconfirmed. `Twowing` and `GN25L95` are commented source metadata.

## Current records

| Device record | Firmware | Pages and provenance |
| --- | --- | --- |
| [ODI DFP-34X-2C2](devices/odi-dfp-34x-2c2/V1.0-220923/) | `V1.0-220923` | Device Status, PON Status, login, logout form, and logout acknowledgement supplied on 22 October 2026. Original status and login snapshots are retained with `_baseline` filenames. |
| [Reported BDCOM ONU, model unconfirmed](devices/bdcom-unknown-model/V2.11.00P3T1/) | `V2.11.00P3T1` | Issue #1 Device Status, PON Status, login, already-logged-in response, and logout acknowledgement. |

## Provenance

- **ODI:** supplied on 22 October 2026. Source lines were decoded from the
  browser's View Source wrapper. Original status and login fixtures are retained
  as `device_status_baseline.html`, `pon_status_baseline.html`, and
  `login_baseline.html`.
- **BDCOM:** supplied through issue #1. Commented fields and unclosed table rows
  are preserved. LLID rows report index 0 / status 1 and index 1 / status 0.
  The login page and already-logged-in response were supplied on 22 October 2026.
  Tests replace the absolute login action's origin with the local simulator.
- **BDCOM logout:** the supplied HAR records a successful
  `POST /boaform/admin/formLogout` with `save=Logout`,
  `submit-url=/admin/logout.asp`, and Referer path `/admin/logout.asp`.
  Only the response acknowledgement is stored.

Tests simulate other LLID values and failures without changing these records.

## Sanitization and limits

IP and MAC addresses use documentation/test values. Original browser URL comments,
passwords, cookies, tokens, and raw browser exports are excluded. HTML scripts and
external assets are never executed or fetched.
