# Dashboard card

The integration adds its dashboard resource automatically. Restart Home Assistant after updating, then reload the browser page.

Edit a dashboard, select **Add card**, and search for **XPON ONU Stick**.

```yaml
type: custom:xpon-onu-stick-card
```

## Options

| Option | Default | Use |
| --- | --- | --- |
| `device_id` | First stick found | Choose a stick when you have several. |
| `title` | Device name | Set the card title. |
| `show_history` | `true` | Show the 24-hour Rx power trend. |
| `show_system` | `true` | Show CPU and memory usage. |
| `show_details` | `true` | Show ONU and network details. |
| `hide_mac` | `false` | Hide the MAC address. |

Select a reading to open its details and history. The card uses Home Assistant data and does not contact the stick. Reload the browser page if the card is missing after an update.

See the [light and dark previews](screenshots.md#dashboard-card).

## Custom element not found

Open **Settings → Dashboards → ⋮ → Resources**. Check for this resource:

- URL: `/xpon_onu_stick/xpon-onu-stick-card.js?v=0.6.1`
- Type: **JavaScript module**

Add it if missing, then reload the browser page. Enable **Advanced mode** in your profile if Resources is hidden.

## Built-in cards

Paste [examples/dashboard.yaml](../examples/dashboard.yaml) into a **Manual** card. Replace the sample `sensor.aot5222zy_*` entity IDs with those shown for your stick.

EPON uses the same optical and system readings. The registration badge applies to GPON. Add the [raw LLID example](../examples/dashboard-epon.yaml) to see EPON codes, replacing the sample entity IDs with your device's indices.
