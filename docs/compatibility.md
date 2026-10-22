# Device compatibility

## Compatible (tested)

| Device | Firmware |
| --- | --- |
| ODI DFP-34X-2C2, Realtek RTL9601D | `V1.0-220923`, stock SFU build `M110_sfp_ODI_220923.tar` |

## EPON capture coverage

EPON support is verified against sanitized Device Status and PON Status captures from firmware `V2.11.00P3T1`, plus local simulator tests. It has not been verified against a live EPON ONU. The captured page contains an **EPON LLID Status** table with indices `0` and `1`; status codes are exposed unchanged without interpreting them as GPON registration states.

## Likely supported, not tested

These use related hardware or web pages. Run the [compatibility checks](#check-an-untested-stick) before relying on them.

| Device or firmware | Check |
| --- | --- |
| ODI DFP-34X-2C3 | Same firmware and pages as the tested stick. |
| Other ODI SFU builds, including `220304`, `220414`, and `220817` | Status fields. |
| ODI HGU, hybrid, newer, or community builds | Status fields and login form. Compatibility is less certain. |
| ODI DFP-34G-2C2, Realtek version | Status fields and login form. |
| HSGQ XPON stick | Status fields and login form. |
| Luleey LL-XS2510 | CPU and memory fields on Device Status. |
| V-SOL V2801F and T&W TWCGPON657 | Status fields and login form. |

## Not supported

- Older ZTE-based ODI sticks and Lantiq/MaxLinear sticks with different web interfaces.
- Replacement firmware that removes the stock status pages, such as odi-oss.
- EPON web layouts without the recognized LLID table structure.

## Check an untested stick

- Both `/status.asp` and `/status_pon.asp` must be reachable and use English field labels.
- Check the expected [sensors](sensors.md) and a valid MAC address.
- GPON registration monitoring and EPON LLID status readings are selected automatically from the PON page.
- Login must use HTTP Basic authentication or the supported `/boaform/admin/formLogin` form. Forms using a `psd` password field are not supported.

Run the [live check](development.md#test-the-real-stick) to confirm readings. Missing or invalid fields are handled as described in [firmware values](firmware-values.md).

References: [firmware notes](https://github.com/Anime4000/RTL960x/blob/main/Firmware/DFP-34X-2C2/README.md), [firmware archive](https://www.tripleoxygen.net/files/devices/odi/dfp-34x-2c2/firmware/), and [hardware reference](https://hack-gpon.org/ont-odi-realtek-dfp-34x-2c2/).
