# Connection and read-only behavior

The integration reads the stick's web interface, independently of the router or switch hosting it.

## Polling

All sensors share two status reads every **30 seconds**. Set an interval from **10 to 3600 seconds** in [configuration](configuration.md#4-set-the-refresh-interval).

## Requests

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

## PON mode

Mode is detected from GPON status fields or the **EPON LLID Status** table. EPON codes are reported unchanged.

Common entities keep their identity across mode changes. New LLID indices add sensors automatically. Sensors for a previous mode or missing index become unavailable until reported again.

## Device identity

The MAC address identifies the stick. Changing its IP preserves existing entities. A different MAC requires a separate integration.

The display name comes from firmware and may differ from the physical model. If absent, the integration uses a MAC-based name.

## Missing or invalid readings

- Empty or `N/A` values show as unknown.
- A bad field, such as `-inf dBm`, affects only that reading and its related status.
- The sensor includes a `parse_error` attribute. Details appear in **Settings → System → Logs**.
- Readings recover automatically, without repeated logs for unchanged errors.
- Connection, authentication, page, or MAC identity failures make all sensors unavailable.
