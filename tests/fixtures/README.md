# Status page fixtures

`epon_device_status.html` and `epon_pon_status.html` were supplied from a device
running firmware `V2.11.00P3T1` in EPON mode. IP and MAC addresses have been
replaced with documentation/test addresses. The HTML structure is preserved,
including the commented-out Device Name and the LLID table's unclosed rows.

The observed LLID rows are index 0 / status 1 and index 1 / status 0. The capture
does not establish what these numeric status codes mean. Tests that change the
codes, indices, or table structure simulate other readings and failure cases;
they are not additional device captures.

`logout_success.html` contains only the logout acknowledgement from the supplied
HAR for firmware `V2.11.00P3T1`. The observed request was
`POST /boaform/admin/formLogout`, with URL-encoded fields `save=Logout` and
`submit-url=/admin/logout.asp`, and Referer path `/admin/logout.asp`. The response
was HTTP 200. No cookies were present in this exchange. The complete HAR, browser
headers, and other page contents are not included in the repository.
