# Configure XPON ONU Stick

## Before you start

- [Install the integration](installation.md) on Home Assistant **2026.9.0 or newer**.
- Make sure Home Assistant Core can reach the ONU on the management network.

## 1. Add the integration

1. Open **Settings → Devices & services → Add integration**.
2. Select **XPON ONU Stick**.
3. Choose **Stock firmware (Boa web interface)** or **ODI OSS (SSH)**.
4. For stock firmware, enter the ONU's hostname, IP address, or base URL without a page path. Enter its username and password when login is required.
5. For ODI OSS, follow the key setup below and submit the SSH connection details.

### ODI OSS over SSH

1. On a trusted machine, create a dedicated Ed25519 SSH key for Home Assistant. Choose an empty passphrase for unattended polling. For example, use `ssh-keygen -t ed25519 -f ./odi-ha`.
2. Enroll only the public key (`odi-ha.pub`) on the stick in **Admin → SSH keys**. [ODI OSS access guide](https://github.com/AndreZiviani/odi-oss/blob/main/docs/ACCESS.md)
3. Copy the private key (`odi-ha`) into `xpon_onu_stick/ssh/` inside the Home Assistant Core configuration directory (typically `/config`). Set permissions to `0600` and make the file readable by Core. Treat it as a root credential and keep it private, including in backups.
4. Get the stick's Ed25519 host fingerprint from a trusted SSH connection or a previously verified `known_hosts` entry. For a verified default-port entry, use `ssh-keygen -l -F onu.example` on that machine. For a custom port, use the bracketed form, such as `ssh-keygen -l -F '[onu.example]:2222'`. Copy the `SHA256:…` value for the ED25519 host key.
5. Enter the stick's hostname or IP, its SSH port (default **22**), the key filename (`odi-ha`), and the verified host fingerprint. Home Assistant polls over SSH after setup.

## 2. Check the readings

Stock GPON has **22 entities**. Stock EPON has **18 common entities plus one per LLID index** (20 with two LLIDs). ODI OSS exposes GPON readings and optical alarms and line counters. Measurements appear under **Sensors** and device details under **Diagnostic**. See [sensors](sensors.md).

## 3. Open the options

Open **Settings → Devices & services → XPON ONU Stick** and select the settings gear. Choose **Refresh interval** or **Status limits**. Stock firmware also offers **Session settings**.

## 4. Set the refresh interval

Enter **10 to 3600 seconds** and select **Submit**. The default is **30 seconds**.

<img src="screenshots/refresh-interval.png" alt="Refresh interval form" width="560">

## 5. Adjust the status limits

Use your module's specifications. Each maximum must exceed its minimum. For bias current, enter both limits or leave both blank.

See [default status limits](sensors.md#default-status-limits), then select **Submit** to save.

<img src="screenshots/status-limits.png" alt="Status limits form" width="440">

## 6. Change the address or login

Open the entry's menu and select **Reconfigure**. Choose the connection type and enter its connection details. This also lets you switch from stock firmware to ODI OSS. The management MAC must match the existing entry.

Changing the address or connection type preserves common entities for the same stick. Add a different stick separately.

## 7. Add a dashboard

Select **Add card → XPON ONU Stick** in a dashboard. See [card options](dashboard.md), or use the [built-in card example](../examples/dashboard.yaml).

## Session settings

**Log out after a successful poll** is disabled by default. Enable it to close the integration's own form-login session after reading both status pages. Connection validation never logs out.

Some firmware shares the login with browsers on the same IP, so enable this only when needed. See [session behavior](behavior.md#stock-web-requests).

## Troubleshooting

- **Integration missing:** check installation and restart Home Assistant.
- **Connection or login fails:** check the address, network access, and credentials.
- **Already logged in:** sign out of the other management session and retry. The integration does not force another session closed.
- **All sensors unavailable:** check the configured connection and the [device identity](behavior.md#device-identity).
- **SSH client key rejected:** enroll the matching public key, then complete reauthentication with the private key filename.
- **SSH host fingerprint mismatch:** verify the stick's host key through a trusted connection, then use **Reconfigure** to update the fingerprint.
- **Reading unknown:** check its `parse_error` attribute and **Settings → System → Logs**. Other valid readings keep updating.
- **Logout warning:** when logout is enabled, this is noncritical; readings still update and logout is retried after the next successful poll.
- **Card missing:** reload the browser page after updating the integration.

Use the [live check](development.md#test-the-real-stick) for stock firmware or check the SSH connection from the Home Assistant Core network for ODI OSS.

Still having trouble? Open a **Problem with a supported device** issue with the firmware version and sanitized errors. For stock web errors, attach the [relevant frame HTML](device-support.md).
