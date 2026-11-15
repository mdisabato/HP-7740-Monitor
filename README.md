# HP-7740-Monitor

A Node-RED flow that monitors an HP OfficeJet Pro 7740 for Home Assistant, replacing the HP printer integrations. It never reports the printer as "unavailable" just because it's off, and it ignores the nags you get for third-party cartridges and firmware.

## Why

The HP integrations lose track of the printer whenever it powers down (auto-off, a power schedule, or the power button) and often fail to notice it's back, leaving sensors stuck at `unknown` until the integration is reloaded. Worse, the 7740 has no Wake-on-LAN and powers its network card down when off, so polling it can't tell "off" from "broken".

This flow takes power from the switch instead: when the printer is off, the switch port it's wired to loses its link. That is reported by the switch (here over SNMP into Home Assistant), so it's reliable even when the printer isn't answering.

## How it works

- **Power**: a Home Assistant state node watches the switch port's link entity. Link down publishes `off` immediately and polling stops. Link up publishes `starting`, waits for the printer to boot (45 s by default), then polls.
- **Poll** (every 15 s while powered; the ink page every 4th poll):
  1. `http://<printer>/DevMgmt/ConsumableConfigDyn.xml`: ink percentages and each cartridge's measured level (`ok`, `low`, ...). This is plain HTTP, the same LEDM data HP's own tools read, and it reports third-party cartridges correctly. The printer's SNMP ink levels don't (it reported 0% black at 20%).
  2. `http://<printer>/DevMgmt/ProductStatusDyn.xml`: status categories and the alert table. Alerts for non-HP cartridges, firmware, web services and low ink (covered by the ink sensors) are dropped, as are empty-tray alerts for trays you list in `ignore_trays`.
  3. SNMP v2c (read-only): printer state (`hrPrinterStatus`, the fallback when the status page shows no known mode), uptime (`sysUpTime`, used for "powered on" time) and page count (`prtMarkerLifeCount`).
- **Publish**: two retained MQTT topics, `<base>/power` and `<base>/supplies`, with Home Assistant MQTT discovery. Ink and page counts keep their last values while the printer is off. The mode comes from the status page's categories (what the front panel shows: `inPowerSave`, `scanProcessing`, `copying`, ...), so scanning and copying show up, which SNMP can't report. Supplies are only republished when something changes. A failed poll while the link is up reports `not responding`.

## Entities

| Entity | Values |
|---|---|
| `binary_sensor.hp7740_power` | on / off |
| `sensor.hp7740_status` | off, starting, sleep (power save), ready, printing, scanning, copying, faxing, cancelling, warming up, busy, not responding |
| `sensor.hp7740_ink_cyan` / `_magenta` / `_yellow` / `_black` | % remaining |
| `sensor.hp7740_ink_low` | `none`, or e.g. `black low` (attribute `ink` has per-cartridge detail) |
| `sensor.hp7740_alert` | `none`, or the remaining alerts, e.g. `trayEmpty (Tray1)` (attributes `alerts`, `categories`) |
| `sensor.hp7740_pages` | total pages printed |
| `sensor.hp7740_powered_on` | timestamp of the last power-on |

Nothing in the flow checks for, reports or triggers firmware updates.

## Requirements

- Node-RED with `node-red-contrib-home-assistant-websocket` and `node-red-node-snmp`, and an MQTT broker config node.
- The printer wired to a switch whose port link state is in Home Assistant (for example the SNMP integration or a switch integration).
- SNMP v1/v2c read-only enabled on the printer (its web page: Network > Advanced Settings > SNMP).

## Build and install

```
cp settings.example.json settings.json   # fill in your printer, link entity and config-node ids
python3 build_flow.py                    # writes flow.json (and funcs.json for the tests)
node test.js                             # runs the flow's functions against samples/
```

Import `flow.json` in the Node-RED editor (Menu > Import), or POST it to the admin API's `/flow` endpoint. It adds one tab and doesn't touch your other flows.

The config-node ids are in your Node-RED flows export: the `server` node (Home Assistant) and the `mqtt-broker` node.

`samples/` holds the two status pages from a 7740 with third-party cartridges, serial numbers and dates removed.

## Licence
MIT
