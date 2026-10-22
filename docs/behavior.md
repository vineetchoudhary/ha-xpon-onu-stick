# Connection and read-only behavior

The integration reads the stick's web interface, independently of the router or switch hosting it.

## Polling

All sensors share two status reads every **30 seconds**. Set an interval from **10 to 3600 seconds** in [configuration](configuration.md#4-set-the-refresh-interval).

## Requests

- `GET /status.asp` for device readings.
- `GET /status_pon.asp` for PON readings.
- When login is needed, `GET /admin/login.asp` and `POST /boaform/admin/formLogin`.
- Only when **Session settings → Log out after a successful poll** is enabled and the integration opened the session, `POST /boaform/admin/formLogout` with `save=Logout` and `submit-url=/admin/logout.asp` after successfully reading both pages.

HTTP Basic authentication is also supported. The integration does not change device settings or submit Refresh forms.

Logout is disabled by default (`logout_after_poll: false`), including for existing entries without this option. A validated client retains its own cookies and login state across setup, polling, and options reloads. Failed connection changes do not replace a working client. Retained login data is released when the integration is removed.

When enabled, logout closes only a form-login session established by this integration. Anonymous reads, HTTP Basic authentication, and a pre-existing session do not trigger logout. Partial field errors still count as a successful poll. Failed status reads do not trigger logout. Setup, reconfiguration, and reauthentication validation never log out. Coordinator polling honors the saved setting.

Login, status reads, and optional logout share a lock for the same normalized device address within the Home Assistant process. This prevents a validation request from closing a session during another poll. Other processes and alternate addresses for the same ONU are outside that lock. Firmware with one shared IP session may still let another browser join the integration's session, so enable logout only when needed.

The captured EPON firmware can return an already-logged-in error. The integration does not force that session closed. If it cannot read status, sign out of the other management session and retry.

The captured success response contains `OK: logout successfully!`. A failed or unconfirmed logout is noncritical: fresh readings remain available, a warning is logged, and no reauthentication prompt is raised. Session cookies are cleared after confirmed logout; otherwise they are retained for the next poll, which tries logout again after reading status.

## Authentication boundaries

Requests use only the configured HTTP(S) origin and the fixed status, login, and logout paths above. A login form may use the expected relative path or an absolute URL on that same origin. Forms targeting another origin, credentials in the URL, query strings, fragments, and other action paths are rejected. Redirects are not followed. Scripts and form actions from the pages are never executed. A dedicated transport with automatic cookies disabled keeps each client's login cookies separate from other devices and integrations.

Responses are limited to 256 KiB of decoded content. HTTPS uses normal certificate verification. Use HTTPS when the device supports it. HTTP sends authentication over the local network without encryption.

## PON mode

Each poll detects GPON from its status fields or heading, or EPON from an explicit **EPON LLID Status** table with `index` and `Status` columns. Missing GPON readings alone never imply EPON. Ambiguous modes and malformed LLID table structure reject the snapshot.

Common entities keep their identity across mode changes. Newly reported LLID indices are added automatically. Entities belonging to the previous mode or removed LLID indices become unavailable and can recover when reported again.

## Device identity

The MAC address identifies the stick. Changing its IP preserves existing entities. A different MAC requires a separate integration.

The device name and model come from the firmware's Device Name field, which may contain a cloned ONT name.

If Device Name is absent, the entry uses `XPON ONU Stick (<MAC>)` in GPON or `XPON ONU <MAC>` in EPON. The model remains unknown. The captured EPON firmware hides Device Name in a comment; that omission is expected and does not produce a parsing error.

## Missing or invalid readings

- Empty or `N/A` values show as unknown.
- A bad field, such as `-inf dBm`, affects only that reading and its related status.
- The sensor includes a `parse_error` attribute. Details appear in **Settings → System → Logs**.
- Unchanged errors are not logged on every poll. Readings recover automatically.
- Connection, authentication, page, or MAC identity failures make all sensors unavailable.
