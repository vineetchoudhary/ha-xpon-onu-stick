# Sensors and status limits

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
| GPON Status | ONU state | Original firmware text, e.g. `O5` or `Operation State(O5)` |
| GPON Status | ONU ID | Integer, including `0` |
| GPON Status | LOID status | Text, e.g. `Initial Status` |
| EPON LLID Status | EPON LLID `<index>` status | Raw nonnegative integer code, one sensor per reported index |

Measurements support history and statistics. Uptime and device details keep the firmware's original text.

Every sensor includes a `pon_mode` attribute (`gpon` or `epon`). GPON exposes 22 entities. EPON exposes 18 common entities plus one per LLID index, without GPON ONU state, ONU ID, LOID status, or ONU registration status. LLID codes have no unit or measurement statistics and are not mapped to connected/disconnected states without firmware documentation.

Each integration entry can register up to 256 LLID sensors, including indices seen previously. This prevents corrupt, constantly changing indices from creating unlimited entities. Existing indices and common measurements continue updating when the limit is reached.

## Friendly status sensors

Five measurement statuses and, in GPON mode, one ONU registration status explain the readings. Their attributes include descriptions and limits. Rx status also shows the margin to each limit.

Missing readings and supported formats are covered in [firmware values](firmware-values.md).

## Default status limits

Change these in [Status limits](configuration.md#5-adjust-the-status-limits) using your module's specifications.

| Measurement | Default classification |
| --- | --- |
| Rx power | Below −27 dBm is Signal too weak. From −27 to −25 dBm is Weak signal. Above −25 and below −10 dBm is Good. From −10 to −8 dBm is Strong signal. Above −8 dBm is Signal too strong. |
| Tx power | From +0.5 to +5 dBm is Good. Below this range is Low transmit power. Above it is High transmit power. |
| Temperature | Below 0 °C is Cold. From 0 to below 60 °C is Normal. From 60 to below 70 °C is Warm. At 70 °C or higher it is Hot. |
| Voltage | From 3.135 to 3.465 V is Normal. Below this range is Low voltage. Above it is High voltage. |
| Bias current | Limits not set until you provide both limits from your module's specification. Values within the configured range are Normal. Values outside it are Low current or High current. A negative reading is Invalid reading. |

These limits are advisory, not factory alarms. Optical defaults use GPON Class B+ references. Temperature and voltage use generic SFP guidelines. Set both bias current limits from your module's specifications.

EPON retains the same defaults. Set optical limits to match your EPON module's specifications.

Set the Rx warning margin to `0` to disable weak and strong warnings. For example, `-26.38 dBm` is inside the default range but shows **Weak signal** because it is near the lower limit.

References: [ITU-T G.984.2](https://www.itu.int/rec/dologin_pub.asp?id=T-REC-G.984.2-201908-I!!PDF-E&lang=e&type=items), [SFP datasheet](https://fibrain.pl/wp-content/uploads/2020/12/DSH_FTS-GPON-OLT-CMAX.pdf), and [SFF-8472](https://members.snia.org/document/dl/25916).

## ONU registration states

The raw sensor preserves the firmware text. The status sensor shows a friendly label.

| ONU state | Friendly status | Meaning |
| --- | --- | --- |
| O1 | Starting up | The ONU is initializing and checking its GPON readiness. |
| O2 | Waiting for registration | The ONU receives and responds to the provider's optical signal. |
| O3 | Exchanging serial number | The ONU identifies itself to the provider using its GPON serial number. |
| O4 | Aligning link timing | The provider measures the link delay and adjusts transmission timing. |
| O5 | Connected | The GPON optical connection is established with the provider. |
| O6 | Recovering connection | The ONU is recovering after a loss of signal or framing. |
| O7 | Disabled by provider | Upstream transmission is disabled until the provider enables it. |

Connected means GPON registration is complete. It does not test Internet access. Other codes show **Unrecognized state**.

References: [GPON registration guide](https://service-provider.zyxel.com/compact-help/AX-DX-EX-PX-WiFi6-Series/AX-DX-EX-PX_5-70/h_WebTutorials.html) and [ITU-T G.984.3](https://www.itu.int/rec/dologin_pub.asp?id=T-REC-G.984.3-201401-I!!PDF-E&lang=e&type=items).
