# Configure XPON ONU Stick

## Before you start

- [Install the integration](installation.md) on Home Assistant **2026.9.0 or newer**.
- Make sure Home Assistant can reach the ONU's web interface.

## 1. Add the integration

1. Open **Settings → Devices & services → Add integration**.
2. Select **XPON ONU Stick**.
3. Enter the ONU's hostname, IP address, or base URL without a page path.
4. Enter its username and password. Leave both blank if login is not required.
5. Select **Submit**.

## 2. Check the readings

Mode is detected automatically. GPON has **22 entities**. EPON has **18 common entities plus one per LLID index** (20 with two LLIDs). Measurements appear under **Sensors** and device details under **Diagnostic**. See the [screenshots](screenshots.md).

## 3. Open the options

Open **Settings → Devices & services → XPON ONU Stick** and select the settings gear. Choose **Refresh interval**, **Status limits**, or **Session settings**.

## 4. Set the refresh interval

Enter **10 to 3600 seconds** and select **Submit**. The default is **30 seconds**.

<img src="screenshots/refresh-interval.png" alt="Refresh interval form" width="560">

## 5. Adjust the status limits

Use your module's specifications. Each maximum must exceed its minimum. For bias current, enter both limits or leave both blank.

See [default status limits](sensors.md#default-status-limits), then select **Submit** to save.

<img src="screenshots/status-limits.png" alt="Status limits form" width="440">

## 6. Change the address or login

Open the entry's menu and select **Reconfigure**. Enter the new address and credentials, including the password when login is required.

Changing the address preserves entities for the same stick. Add a different stick separately.

## 7. Add a dashboard

Select **Add card → XPON ONU Stick** in a dashboard. See [card options](dashboard.md), or use the [built-in card example](../examples/dashboard.yaml).

## Session settings

**Log out after a successful poll** is disabled by default. Enable it to close the integration's own form-login session after reading both status pages. Connection validation never logs out.

Some firmware shares the login with browsers on the same IP, so enable this only when needed. See [session behavior](behavior.md#requests).

## Troubleshooting

- **Integration missing:** check installation and restart Home Assistant.
- **Connection or login fails:** check the address, network access, and credentials.
- **Already logged in:** sign out of the other management session and retry. The integration does not force another session closed.
- **All sensors unavailable:** check both status pages and the [device identity](behavior.md#device-identity).
- **Reading unknown:** check its `parse_error` attribute and **Settings → System → Logs**. Other valid readings keep updating.
- **Logout warning:** when logout is enabled, this is noncritical; readings still update and logout is retried after the next successful poll.
- **Card missing:** reload the browser page after updating the integration.

Use the [live check](development.md#test-the-real-stick) to read the stick directly.
