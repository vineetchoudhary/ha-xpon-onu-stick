# XPON ONU Stick for Home Assistant

A local, read-only custom integration for XPON/GPON ONU SFP sticks. It reads the stick's Device Status and PON Status pages from the stick's own management web interface, independently of the router, switch, or media converter the stick is plugged into. Tested with an **ODI DFP-34X-2C2 GPON SFP stick on firmware V1.0-220923**.

## Supported devices

The integration doesn't detect the stick's chipset or model. It works with firmware that serves the stock Realtek status pages described in [Check an untested stick](#check-an-untested-stick).

### Compatible (tested)

| Device | Firmware | Result |
| --- | --- | --- |
| ODI DFP-34X-2C2 GPON SFP stick (Realtek RTL9601D, SC/UPC) | `V1.0-220923`, ODI's stock SFU firmware (`M110_sfp_ODI_220923.tar`) | All 16 readings and the login work on a real stick. The stick's Device Status, PON Status, and login pages match the page templates in the published firmware image. |

### Likely supported, not tested

These share the hardware, the firmware, or the Realtek web pages of the tested stick, but none has been tested with this integration. Run the [checks below](#check-an-untested-stick) before relying on one.

| Device | Why it should work | What to check |
| --- | --- | --- |
| ODI DFP-34X-2C3 | Same board and firmware as the DFP-34X-2C2, with an SC/APC connector. | Nothing extra if it runs `V1.0-220923`. |
| ODI DFP-34X-2C2 on other ODI SFU firmware: `V1.0-220304`, `V1.0-220414`, or `V1.0-220817` | Same firmware family as the tested build. | All fields are present. |
| ODI DFP-34X-2C2 on router (HGU), hybrid, newer, or community-modified firmware, such as `V1.0-210702`, `V1.0-220530`, or the `M114_sfp_ODI_hybrid_*` builds | Same web server, but these builds add or restyle pages. | Lower confidence. Check the fields and the login form. |
| ODI DFP-34G-2C2 (Realtek version) | Same chip and firmware platform as the DFP-34X-2C2. | Fields and login form. |
| HSGQ XPON stick (identifies as `HSGQ-XPON-Stick`) | Runs ODI-derived firmware with the same GPON status rows. | Fields and login form. |
| Luleey LL-XS2510 | Realtek RTL9601D stick whose login form and PON Status page match the stock Realtek pages. | CPU Usage and Memory Usage on the Device Status page. |
| V-SOL V2801F, T&W TWCGPON657 | Realtek RTL9601CI sticks with the same family of web pages. | Fields and login form. |

### Not supported

- ODI's older ZTE-chipset stick and Lantiq/MaxLinear-based sticks, such as the Huawei MA5671A, Nokia G-010S-P, FS GPON-ONU-34-20BI, and HALNy HL-GSFP. Their web interfaces are different or absent.
- Replacement firmware that removes the stock status pages, such as odi-oss.
- Any stick running in EPON mode, as explained below.

### Check an untested stick

The integration works when all of these are true:

- `GET /status.asp` shows Device Name, Uptime, Firmware Version, CPU Usage, Memory Usage, IP Address, Subnet Mask, and MAC Address.
- `GET /status_pon.asp` shows Temperature, Voltage, Tx Power, Rx Power, Bias Current, ONU State, ONU ID, and LOID Status.
- The web interface is in English, because field labels are matched as English text.
- The stick is in GPON mode. In EPON mode, the firmware replaces the ONU State, ONU ID, and LOID Status rows with an EPON table, so the integration reports missing fields.
- If the pages require a login, `/admin/login.asp` has a form that posts `username`, `password`, and `save` to `/boaform/admin/formLogin` with an empty challenge. Older Realtek firmware that names the password field `psd` isn't supported.

The quickest check is the [live test](#test-the-real-stick), which prints all 16 readings or the reason it can't read them.

References: [ODI DFP-34X-2C2 firmware notes](https://github.com/Anime4000/RTL960x/blob/main/Firmware/DFP-34X-2C2/README.md), [ODI firmware archive](https://www.tripleoxygen.net/files/devices/odi/dfp-34x-2c2/firmware/), and [DFP-34X-2C2 hardware reference](https://hack-gpon.org/ont-odi-realtek-dfp-34x-2c2/).

## Screenshots

The screenshots show one example installation.

<table>
  <tr>
    <th>Measurements and friendly statuses</th>
    <th>Device information and options</th>
  </tr>
  <tr>
    <td valign="top">
      <img src="docs/screenshots/home-assistant-sensors.png" alt="Home Assistant Sensors section with optical readings, friendly statuses, and the GPON connection state" width="380">
    </td>
    <td valign="top">
      <img src="docs/screenshots/home-assistant-diagnostics.png" alt="Home Assistant Diagnostic section with device, firmware, and network information" width="380">
      <br>
      <img src="docs/screenshots/integration-options.png" alt="ONU options menu with Refresh interval and Status limits" width="380">
      <br>
      <img src="docs/screenshots/refresh-interval.png" alt="Refresh interval form showing the default interval of 30 seconds" width="380">
    </td>
  </tr>
</table>

## Install

### HACS (recommended)

With [HACS installed and configured](https://www.hacs.xyz/docs/use/), open the repository directly:

[![Open XPON ONU Stick in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=vineetchoudhary&repository=ha-xpon-onu-stick&category=integration)

Select your Home Assistant instance if prompted, download **XPON ONU Stick**, and restart Home Assistant. Then add **XPON ONU Stick** from **Settings → Devices & services → Add integration** and enter your ONU's address and credentials.

Alternatively, add the custom repository manually:

1. Open **HACS** from the Home Assistant sidebar.
2. Open the **⋮** menu in the top-right corner and select **Custom repositories**.
3. Enter `https://github.com/vineetchoudhary/ha-xpon-onu-stick` as the repository URL.
4. Choose **Integration** as the type/category and click **Add**.
5. Search HACS for **XPON ONU Stick**, open it, and click **Download**.
6. Restart Home Assistant.
7. Open **Settings → Devices & services → Add integration**, and search for **XPON ONU Stick**.
8. Enter your ONU's management address (hostname, IP address, or HTTP(S) base URL) and the username/password you use on its login page. The address field starts blank. Leave credentials blank only if the status pages are accessible directly.

### Manual installation

1. Copy `custom_components/xpon_onu_stick` into Home Assistant's `/config/custom_components/` directory.
2. Restart Home Assistant.
3. Open **Settings → Devices & services → Add integration**, and search for **XPON ONU Stick**.
4. Enter your ONU's management address (hostname, IP address, or HTTP(S) base URL) and the username/password you use on its login page. The address field starts blank. Leave credentials blank only if the status pages are accessible directly.

Continue with the [configuration guide](docs/configuration.md) to review the readings and customize the integration's options.


## Sensors

| Page | Sensor | Unit / format |
| --- | --- | --- |
| Device Status | Device name | Text |
| Device Status | Uptime | Original firmware text, e.g. `1:21` or `3 days, 21:22` |
| Device Status | Firmware version | Text |
| Device Status | CPU usage | % |
| Device Status | Memory usage | % |
| Device Status | IP address | Text |
| Device Status | Subnet mask | Text |
| Device Status | MAC address | Original firmware text |
| PON Status | Temperature | °C |
| PON Status | Voltage | V |
| PON Status | Tx power | dBm |
| PON Status | Rx power | dBm |
| PON Status | Bias current | mA |
| GPON Status | ONU state | Text, e.g. `O5` |
| GPON Status | ONU ID | Integer, including `0` |
| GPON Status | LOID status | Text, e.g. `Initial Status` |

Numeric measurements retain the precision supplied by the stick and support history/statistics. Suggested display precision keeps the dashboard readable. ONU ID is an identifier, so it does not accumulate statistics. Uptime remains the firmware's original text rather than guessing its format.

Device name, firmware, and LAN information are diagnostic sensors. They are enabled and can still be added to dashboards.

### Friendly status sensors

| Sensor | Possible status labels |
| --- | --- |
| Rx power status | Good, Weak signal, Signal too weak, Strong signal, Signal too strong |
| Tx power status | Good, Low transmit power, High transmit power |
| Temperature status | Normal, Cold, Warm, Hot |
| Voltage status | Normal, Low voltage, High voltage |
| Bias current status | Normal, Low current, High current, Limits not set, Invalid reading |
| ONU registration status | Starting up, Waiting for registration, Exchanging serial number, Aligning link timing, Connected, Recovering connection, Disabled by provider, Unrecognized state |

Each status includes a description in its attributes. Measurement statuses also include the original reading and the limits used to classify it. Rx power status includes the margin to each configured limit in dB. Missing measurements become unknown. All sensors share the same two status-page requests.

### Default status limits

Open the integration's options and select **Status limits** to adjust the ranges for your module. Saving limits updates the status sensors in Home Assistant.

See [Adjust the status limits](docs/configuration.md#5-adjust-the-status-limits) to change limits and set or clear bias current limits.

| Measurement | Default classification |
| --- | --- |
| Rx power | Below −27 dBm is Signal too weak. From −27 to −25 dBm is Weak signal. Above −25 and below −10 dBm is Good. From −10 to −8 dBm is Strong signal. Above −8 dBm is Signal too strong. |
| Tx power | From +0.5 to +5 dBm is Good. Below this range is Low transmit power. Above it is High transmit power. |
| Temperature | Below 0 °C is Cold. From 0 to below 60 °C is Normal. From 60 to below 70 °C is Warm. At 70 °C or higher it is Hot. |
| Voltage | From 3.135 to 3.465 V is Normal. Below this range is Low voltage. Above it is High voltage. |
| Bias current | Limits not set until you provide both limits from your module's specification. Values within the configured range are Normal. Values outside it are Low current or High current. A negative reading is Invalid reading. |

The optical defaults use the GPON Class B+ ONU reference values in [ITU-T G.984.2, Table A.1](https://www.itu.int/rec/dologin_pub.asp?id=T-REC-G.984.2-201908-I!!PDF-E&lang=e&type=items). The integration does not detect the module's optical class. Change these limits for other classes or manufacturer specifications. The 2 dB receive warning margin is an advisory buffer chosen by this integration. Set it to 0 to disable the Weak signal and Strong signal warnings.

The temperature and voltage defaults are generic guidelines for a commercial 3.3 V SFP module, with a 60 °C warm warning chosen by this integration. For example, the [Fibrain GPON SFP datasheet](https://fibrain.pl/wp-content/uploads/2020/12/DSH_FTS-GPON-OLT-CMAX.pdf) specifies a 0 to 70 °C operating range and a 3.135 to 3.465 V supply range. Internal sensor temperature can differ from the specified ambient or case temperature, so use the limits recommended for your module's reported measurement.

These labels are advisory comparisons. The status pages do not provide the module's factory alarm thresholds, and the integration does not read them from the SFP interface. [SFF-8472, section 9.4](https://members.snia.org/document/dl/25916) defines manufacturer-specific alarm and warning limits, including bias current. There is no single default bias current range suitable for every module.

For example, an Rx reading of −26.38 dBm displays **Weak signal** with the default limits. It is inside the reference range but only about 0.62 dB above the lower limit. This label alone does not mean the connection has failed.

### ONU registration states

The original **ONU state** sensor keeps the firmware's code and gains a description attribute. **ONU registration status** shows its friendly label.

| ONU state | Friendly status | Meaning |
| --- | --- | --- |
| O1 | Starting up | The ONU is initializing and checking its GPON readiness. |
| O2 | Waiting for registration | The ONU receives and responds to the provider's optical signal. |
| O3 | Exchanging serial number | The ONU identifies itself to the provider using its GPON serial number. |
| O4 | Aligning link timing | The provider measures the link delay and adjusts transmission timing. |
| O5 | Connected | The GPON optical connection is established with the provider. |
| O6 | Recovering connection | The ONU is recovering after a loss of signal or framing. |
| O7 | Disabled by provider | Upstream transmission is disabled until the provider enables it. |

O1 to O5 follow the [Zyxel GPON registration guide](https://service-provider.zyxel.com/compact-help/AX-DX-EX-PX-WiFi6-Series/AX-DX-EX-PX_5-70/h_WebTutorials.html). O6 and O7 follow [ITU-T G.984.3, section 10.2.2](https://www.itu.int/rec/dologin_pub.asp?id=T-REC-G.984.3-201401-I!!PDF-E&lang=e&type=items). Connected describes GPON registration and does not test Internet access. Other codes display Unrecognized state, with the original code retained in the attributes.

## Refresh and connection settings

The default refresh interval is **30 seconds**. Each poll makes two sequential GET requests shared by all sensors. Open the integration's options and select **Refresh interval** to change it, between 10 and 3600 seconds. Changing the interval preserves your status limits.

The [configuration guide](docs/configuration.md#4-set-the-refresh-interval) shows the refresh interval form and how to apply changes.

Use **Reconfigure** to change the device address or credentials. Re-enter the password if authentication is enabled.

The stick's MAC address is its identity in Home Assistant. Changing the management address doesn't create new entities, and a different stick at the same address is rejected instead of overwriting the original device's readings. If you later clone a different MAC address onto the stick, Home Assistant treats it as a different stick, so remove the integration and add it again.

Home Assistant names the device after the firmware's Device Name and also shows that value as the device model. If the stick was set up with an ISP ONT's identity, the Device Name is the ONT's name, not the stick's hardware model.

## Read-only behavior

The integration reads the two status pages:

- `GET /status.asp`
- `GET /status_pon.asp`

When the stick requests authentication, it also uses `GET /admin/login.asp` and submits **only** the login form with `POST /boaform/admin/formLogin`. If you enter a username, every request also carries it as HTTP Basic credentials, for firmware that protects its pages that way. It does not submit the status pages' Refresh forms, follow redirects, read settings pages, or expose configuration/reboot controls. Adding or changing the integration's options changes only Home Assistant configuration.

Both pages must be valid before a snapshot is published. When either page is unreachable or invalid, the sensors become unavailable instead of displaying stale readings as current. Polling resumes after ordinary connection failures. Empty or `N/A` readings become unknown, rather than a fabricated zero.

## Dashboard

[`examples/dashboard.yaml`](examples/dashboard.yaml) contains built-in Home Assistant cards for both status pages, the friendly statuses, and a history graph. Paste it into a Manual dashboard card. Entity IDs start with the stick's Device Name, and the example uses `sensor.aot5222zy_*`. Replace `aot5222zy` with the prefix Home Assistant shows for your stick.

## Development and verification

Run commands from the repository directory. Use **Python 3.14.2 or newer in the 3.14 series** for the pinned Home Assistant test environment. For the first run:

```sh
./scripts/test.sh --setup
```

`--setup` creates `.venv` if needed and installs `requirements-dev.txt`. If Python has a different executable path, use `PYTHON=/path/to/python3.14 ./scripts/test.sh --setup`. A normal run reuses the environment:

```sh
./scripts/test.sh
```

The script checks HACS metadata, repository layout, translations, brand images, installed dependencies, lint, formatting, and the complete test suite. Tests cover status boundaries, ONU state descriptions, shared polling, options form display, and saving or clearing module-specific limits. It stops at the first failing check and returns a nonzero exit code. Full output is saved to `.test-results/test-*.log`, including failed runs.

### Test the real stick

To run all checks and then read current Device Status and PON Status values from this computer, pass your ONU management address with `--host`. There is no default address. Replace the example `http://onu.example` below with your device's address:

```sh
./scripts/test.sh --live --host http://onu.example
```

If the stick requires authentication:

```sh
./scripts/test.sh --live --host http://onu.example --username YOUR_USERNAME
```

The script prompts privately for the password, then prints all 16 readings as JSON. Passwords are not passed as command-line arguments or saved in the test log. The live readings themselves are included in the log. A connection, authentication, or parsing failure makes the script fail. Use `./scripts/test.sh --help` for all options.
