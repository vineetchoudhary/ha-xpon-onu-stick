# Firmware values

## Accepted values

| Reading | Format |
| --- | --- |
| CPU and memory | Decimal number with optional `%`. |
| Temperature | Decimal number with optional `C` or `°C`. |
| Voltage | Decimal number with optional `V`. |
| Tx and Rx power | Decimal number with optional `dBm`. Negative and zero values are kept. |
| Bias current | Decimal number with optional `mA`. A negative reading has an invalid status. |
| ONU ID | Nonnegative whole number, including `0` and `255`. |
| EPON LLID status | Raw nonnegative integer code keyed by the reported index. No GPON state conversion. |
| ONU state | Original text. Friendly status recognizes `O1` to `O7` and labels such as `Operation State(O5)`. |
| Device details, LOID status, and uptime | Original firmware text. |

Measurement numbers accept explicit signs, extra whitespace, and case variations in units. Scientific notation and decimal commas are not supported. LLID indices and codes accept ASCII decimal digits only, up to 64 digits to bound corrupt input. Valid `0` readings are preserved.

## Unknown readings

Empty values, `-`, `--`, `N/A`, `NA`, `unknown`, and `not available` show as unknown.

Missing fields, wrong units, corrupt text, infinity, NaN, and numeric overflow show as unknown with a `parse_error` attribute and a system log entry. Only the affected reading and its related status are changed. Other readings keep updating.

An invalid EPON LLID status affects only that index. Invalid or duplicate indices, missing LLID tables, and ambiguous modes reject the whole PON page because its structure cannot identify readings reliably. Missing or invalid MAC identity also rejects the snapshot.

For example, Tx power `-inf dBm` shows as **Unknown** in Home Assistant and a dash in the dashboard card. It is not converted to zero.

See [connection behavior](behavior.md#missing-or-invalid-readings) for recovery and device-level failures.

## References

- [RTL960x firmware notes](https://github.com/Anime4000/RTL960x/blob/main/Firmware/DFP-34X-2C2/README.md).
- [ODI compatibility manual](https://ae01.alicdn.com/kf/Sb6d6eb6f38084922861fabb044133dfel.pdf).
- [Stock firmware telemetry example](https://github.com/marfillaster/gpon-telemetry#what-it-polls).
- [ITU-T G.984.3, GPON states and ONU IDs](https://www.itu.int/rec/dologin_pub.asp?id=T-REC-G.984.3-200803-S%21%21PDF-E&lang=e&type=items).
