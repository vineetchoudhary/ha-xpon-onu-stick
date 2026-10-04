"""Constants for XPON ONU Stick."""

DOMAIN = "xpon_onu_stick"
DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 10
MAX_SCAN_INTERVAL = 3600
REQUEST_TIMEOUT = 10

# Deliberately fixed: status reads and authentication only.
DEVICE_STATUS_PATH = "/status.asp"
PON_STATUS_PATH = "/status_pon.asp"
LOGIN_PAGE_PATH = "/admin/login.asp"
LOGIN_FORM_PATH = "/boaform/admin/formLogin"
