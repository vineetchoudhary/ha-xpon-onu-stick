# Connection and read-only behavior

The integration reads the stock web interface or connects to ODI OSS over SSH, independently of the router or switch hosting the stick.

## Polling

All sensors share one poll every **30 seconds**. Set an interval from **10 to 3600 seconds** in [configuration](configuration.md#4-set-the-refresh-interval).

## Stock web requests

- `GET /status.asp` for device readings.
- `GET /status_pon.asp` for PON readings.
- When login is needed, `GET /admin/login.asp` and `POST /boaform/admin/formLogin`.
- Optional logout: `POST /boaform/admin/formLogout` after both pages are read.

HTTP Basic authentication is also supported. The integration does not change device settings or submit Refresh forms.

Sessions are reused across setup, polling, and reloads. Login cookies are kept separate for each device and released when the integration is removed.

Logout is disabled by default. When enabled, it closes only a form-login session opened by the integration. Anonymous reads, HTTP Basic authentication, pre-existing sessions, connection validation, and failed polls do not trigger logout.

Requests to the same device address run in sequence. Firmware with shared IP sessions may also close a browser using the integration's login.

If another management session blocks login, sign out of it and retry. Failed logout leaves readings available and is retried after the next successful poll.

## Authentication boundaries

Requests use only the configured HTTP(S) origin and fixed paths above. Login forms must target that origin's login path. Redirects are not followed, and page scripts are never executed. Cookies are isolated from other integrations.

Responses are limited to 256 KiB. HTTPS verifies certificates. HTTP sends authentication without encryption.

## ODI OSS over SSH

Home Assistant authenticates as `root` with the configured Ed25519 key after verifying the stick's pinned host fingerprint. A poll runs one fixed batch of read-only status commands and reuses the SSH connection while it is healthy. Validation and polling for the same SSH endpoint are serialized. A failed transport closes the connection so the next poll can reconnect.

The batch reads the management MAC, firmware, system data, optical diagnostics and accumulated GPON driver counters. It filters the GPON status on the stick to omit the serial number and provisioning details. The poll has a 10-second deadline and a 256 KiB reply limit.

## PON mode

On stock firmware, mode is detected from GPON status fields or the **EPON LLID Status** table. EPON codes are reported unchanged. ODI OSS reports GPON status.

Common entities keep their identity across mode changes. New LLID indices add sensors automatically. Sensors for a previous mode or missing index become unavailable until reported again.

## Device identity

The MAC address identifies the stick. Changing its IP preserves existing entities. A different MAC requires a separate integration.

The display name comes from firmware and may differ from the physical model. If absent, the integration uses a MAC-based name.

## Missing or invalid readings

- Empty or `N/A` values show as unknown.
- A bad field, such as `-inf dBm`, affects only that reading and its related status.
- The sensor includes a `parse_error` attribute. Details appear in **Settings → System → Logs**.
- Readings recover automatically, without repeated logs for unchanged errors.
- Connection, authentication, status structure, or MAC identity failures make all sensors unavailable.

Field expectations can vary by a verified firmware profile. A known optional row may be absent without a parsing error. Missing or unknown firmware uses the generic interface profile, so it does not silently inherit another firmware's exceptions. See [device adapters and firmware profiles](device-adapters.md).
