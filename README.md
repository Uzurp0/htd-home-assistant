# Home Theater Direct Integration for Home Assistant

![HTD](logo-htd.png)

This integration adds support for the Home Theater Direct line of Whole House Audio to Home Assistant.

Currently, it supports the following models:
- MC/MCA-66
- Lync 6
- Lync 12

## Installation steps

### Via HACS (Home Assistant Community Store)

Easiest installation is via [HACS](https://hacs.xyz/):

Please click this button below to install the integration:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=hikirsch&repository=htd-home-assistant&category=integration)

After you add the repository for the integration, you will then be able to install it into Home Assistant.

### Manually

Download all the files from this repo and upload as `custom_components/htd` folder.

### Configuration

Go to **Configuration → Integrations → Add Integration → Home Theater Direct**.

If you wish to use a USB to Serial adapter, you will need to configure the integration manually in your `configuration.yaml` file:

```yaml
htd:
  - device_name: Lync 6 over Serial
    path: /dev/ttyUSB0

Friendly Names for Zones and Sources
You can provide friendly names for zones and sources in the integration options.
Mappings can be defined in JSON or comma‑separated format:
Zones mapping
- JSON: {"1":"Kitchen","2":"Patio"}
- Comma-separated: 1=Kitchen,2=Patio

Sources mapping
- JSON: {"1":"Spotify","2":"TV","3":"Unused"}
- Comma-separated: 1=Spotify,2=TV,3=Unused

Use "Unused" to hide a zone or source in the UI while still logging updates.
Debug Logging

To see detailed logs (raw values, friendly names, normalized volume), enable debug logging in configuration.yaml:
    logger:
      default: info
      logs:
        custom_components.htd: debug

Example log output:

Zone 3 (Kitchen) updated: power=True, volume=15 (normalized=0.38), source=2 (Spotify), mute=False

Zone 4 (Patio) updated: power=False, volume=0 (normalized=0.00), source=4 (Unused), mute=False

Device Info
All zones are grouped under the HTD device in Home Assistant’s UI.
The integration reports the device name and manufacturer, and may also include the specific controller model if available.

Code Credits
- https://github.com/dustinmcintire/htd-lync
- https://github.com/whitingj/mca66
- https://github.com/qguernsey/Lync12
- https://github.com/steve28/mca66
- http://www.brandonclaps.com/?p=173
- https://github.com/lounsbrough/htd-mca-66-api



