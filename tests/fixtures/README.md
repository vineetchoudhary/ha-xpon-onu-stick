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

Include only pages actually captured for that device. Use the reported firmware
version as the directory name. If it is unknown, use `default`, for example
`devices/odi-dfp-34x-2c2/default/`. `default` means the capture's firmware is
unknown, not that its pages apply to every firmware version.

Use the confirmed device model, rather than a cloned name or commented vendor
field from the web page. For issue #1 the exact BDCOM model is still unconfirmed,
so its record uses `bdcom-unknown-model`. `Twowing` and `GN25L95` are source-page
metadata and are not treated as the full device model.

Keep all pages directly in the firmware directory. Preserve older snapshots
with descriptive filenames, such as `device_status_baseline.html`. Record their
source and any sanitization below. Do not overwrite a capture with pages from a
different firmware version.

## Current records

| Device record | Firmware | Pages and provenance |
| --- | --- | --- |
| [ODI DFP-34X-2C2](devices/odi-dfp-34x-2c2/V1.0-220923/) | `V1.0-220923` | Device Status, PON Status, login, logout form, and logout acknowledgement supplied on 22 October 2026. Original status and login snapshots are retained with `_baseline` filenames. |
| [Reported BDCOM ONU, model unconfirmed](devices/bdcom-unknown-model/V2.11.00P3T1/) | `V2.11.00P3T1` | Issue #1 Device Status, PON Status, login, already-logged-in response, and logout acknowledgement. |

Both current records identify their firmware version, so neither uses `default`.

## ODI captures

The 22 October 2026 files were saved through the browser's View Source page.
Only the decoded source-line contents were extracted from its rendered wrapper.
The status snapshot has ONU state O5, Rx power -26.575773 dBm, and uptime
`2 days, 19:12`. The original snapshots are `device_status_baseline.html`,
`pon_status_baseline.html`, and `login_baseline.html` in the same directory.

## Issue #1 captures

The Device Status and PON Status files were supplied from firmware
`V2.11.00P3T1` in EPON mode. Their structure is preserved, including the
commented-out Device Name and the LLID table's unclosed rows. The original issue
status files supplied on 22 October 2026 match these fixtures apart from
whitespace, so duplicate copies are not stored.

The observed LLID rows are index 0 / status 1 and index 1 / status 0. The capture
does not establish what these numeric codes mean. Tests that change codes,
indices, or table structure simulate other readings and failure cases. They are
not additional device captures.

`login.html` and `login_busy.html` were also supplied on 22 October 2026. The
saved login page contains an absolute form action. Tests replace its
documentation origin with the localhost simulator's origin. The error response
contains the firmware's exact already-logged-in wording.

`logout_success.html` contains only the acknowledgement from the supplied HAR
for this firmware. The observed request was `POST /boaform/admin/formLogout`,
with URL-encoded fields `save=Logout` and `submit-url=/admin/logout.asp`, and
Referer path `/admin/logout.asp`. The response was HTTP 200. No cookies were
present in this exchange. The complete HAR and browser headers are not stored.

## Sanitization and limits

These files are test data, not scripts or instructions to execute. IP and MAC
addresses were replaced with documentation/test values. Browser save comments
containing the original address were removed. No passwords, session cookies,
tokens, or raw browser exports are included. External asset references remain
inert HTML and are never fetched. A capture verifies page structure and values,
not live authentication or session lifetime.
