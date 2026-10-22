# Request device support

For a new model or firmware, open a **New device support** issue with the files below. For an existing device, choose **Problem with a supported device** and attach pages relevant to the problem.

## Files to collect

| File | Page or response | When needed |
| --- | --- | --- |
| `device-status.html` | Device Status, usually `/status.asp` or `/admin/status.asp` | Always |
| `pon-status.html` | PON Status, usually `/status_pon.asp` | Always |
| `login.html` | Login form, usually `/admin/login.asp` | Web form login |
| `login-result.html` | Response to submitting login, often `POST /boaform/admin/formLogin` | Web form login |
| `logout.html` | Logout page/form, usually `/admin/logout.asp` | If the interface has one |
| `logout-result.html` | Response to logging out, often `POST /boaform/admin/formLogout` | If the interface supports logout |

Use the actual paths on your firmware. If a page is unavailable, explain why. For HTTP Basic authentication (a browser login popup), say so in the issue. There may be no login form to save.

## Save the frame source

Many ONU interfaces show a menu and a separate content frame. **Save the source of the frame containing the readings.** The root page source may contain only the frame layout.

1. Open the ONU web interface and sign in if needed.
2. Select **Device Status**. Right-click inside the readings area, away from links and buttons.
3. Choose **View frame source** if available. In Firefox, look under **This Frame → View Frame Source**. If the option is missing, use the [Network method](#use-the-network-panel) below.
4. Check the source: it should contain the Device Status labels and values. A source containing only `<frame>`, `<iframe>`, or navigation links is the wrong page.
5. Copy the HTML into a plain-text editor and save it as `device-status.html`, using UTF-8. Use Notepad, VS Code, or TextEdit with **Format → Make Plain Text**.
6. Repeat for **PON Status**, saving `pon-status.html`. Save the login and logout forms the same way when present.

Copy the HTML text from the source view. The browser's **Save page as** command on a `view-source:` tab can save the browser's source-view wrapper instead. Screenshots and the root page alone do not include the source needed for parsing.

## Use the Network panel

This also works for frames and captures the login/logout responses.

1. Open browser developer tools: **F12** or **Ctrl+Shift+I** on Windows/Linux, **⌘+Option+I** on macOS. Select **Network** and enable **Preserve log**.
2. Open the relevant status page, or use the interface's normal **Login** or **Logout** action. Capture logout only when you are ready to end the browser session. Avoid settings, reboot, or reset controls.
3. Select the matching request. Check **Response** for the HTML and **Headers** for its path, request method, and status code.
4. In Chrome/Edge, right-click the request and choose **Copy → Copy response**. Paste the response body into a plain-text `.html` file using the names above.
5. In the issue's page notes, record any different paths, errors, or redirects. If a redirect has no response body, record its method, status, and destination path instead, then save the destination page's HTML.

Capture POST responses from the normal login/logout action. Opening a form action URL in the address bar sends a GET request and can produce a different result. Include an already-logged-in error page if you encounter it.

Share response HTML and short request notes. Do not upload a full HAR, request payload, cookies, authorization headers, or a copied cURL command. [Chrome Network reference](https://developer.chrome.com/docs/devtools/network/reference/).

## Remove sensitive details

Before uploading, open every file in a text editor, including comments, scripts, and hidden fields:

- Remove passwords, session cookies, tokens, serial numbers, and LOID credentials. Keep field names and whether a challenge was empty or populated.
- Replace IP addresses with `192.0.2.1` and MAC addresses with `02:00:00:00:00:01`. Remove personal hostnames and identifying details from URLs and notes.
- Keep firmware versions, table structure, labels, readings, units, and form action paths intact. Replace sensitive values rather than deleting the surrounding HTML.

## Attach the files

1. Put the reviewed HTML files into one folder named for the model and firmware. Use `default` when the firmware is unknown. Compress it as a `.zip`.
2. Open the [issue chooser](https://github.com/vineetchoudhary/ha-xpon-onu-stick/issues/new/choose), select the appropriate form, and upload the ZIP. Mention missing files or empty responses in **Page paths and missing files**.
3. Include the manufacturer/model, full firmware version, PON mode, and Home Assistant/integration versions. Add relevant logs or screenshots if there is an error.

Issue attachments are public. Review files before uploading. [GitHub attachment help](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/attaching-files).
