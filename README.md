# ThermoSave for Home Assistant

[![hacs][hacs-badge]][hacs]
[![Validate][validate-badge]][validate]

Custom integration that connects [ThermoSave](https://www.thermosave.com/)
devices to Home Assistant through the ThermoSave cloud (`api.thermosave.com`).

All devices claimed by your ThermoSave account are added automatically,
including devices claimed after the integration was set up.

> [!WARNING]
> This integration is experimental and may change or break between releases.
> It is not yet recommended for daily use.

## Entities

Each ThermoSave device gets:

| Platform      | Entity    | Description                                                           |
| ------------- | --------- | --------------------------------------------------------------------- |
| Water heater  | (device)  | Auto (follow the schedule), Heat now (forced on) or Away (forced off) |
| Sensor        | State     | Heating, Ready (tank full), Paused (schedule), Away (mode off), Offline |
| Sensor        | Power     | Current power draw (kW)                                               |
| Sensor        | Last seen | When the device last reported to the cloud                            |
| Sensor        | Timezone  | Timezone configured on the device                                     |
| Binary sensor | Online    | Whether the device is connected to the ThermoSave cloud               |
| Calendar      | Schedule  | Daily power-saving windows. Create, edit or delete events to change them |

Changing one occurrence of a Schedule event changes that window on every day,
because schedule windows repeat daily.

## Installation

### HACS (recommended)

Assumes that you have
[downloaded HACS](https://hacs.xyz/docs/use/download/prerequisites/) to your
Home Assistant installation.

1. Open HACS, go to the three-dot menu, then **Custom repositories**.
2. Add `https://github.com/thermosave/ha-thermosave` with the type **Integration**.
3. Search for **ThermoSave**, download it, and restart Home Assistant.

### Manual

Copy `custom_components/thermosave` into the `custom_components` folder of your
Home Assistant configuration directory and restart Home Assistant.

## Configuration

1. Go to **Settings → Devices & services → Add integration** and pick **ThermoSave**.
2. Enter the email address of your ThermoSave account.
3. Enter the one-time code that ThermoSave emails to you.

If the stored login stops working, Home Assistant asks you to reauthenticate,
and a new code is emailed to you.

## Removal

Go to **Settings → Devices & services → ThermoSave**, open the three-dot menu
and pick **Delete**. Then remove the repository from HACS (or delete
`custom_components/thermosave`) and restart Home Assistant.

## Report bugs using Github's [issues](../../issues)

GitHub issues are used to track public bugs.
Report a bug by [opening a new issue](../../issues/new/choose); it's that easy!

**Great Bug Reports** tend to have:

- A quick summary and/or background
- Steps to reproduce
  - Be specific!
  - Give sample code if you can.
- What you expected would happen
- What actually happens
- Notes (possibly including why you think this might be happening, or stuff you tried that didn't work)

People *love* thorough bug reports. I'm not even kidding.

## Data updates

The integration polls the ThermoSave cloud for device status every 5 minutes.
The device list and device configuration (mode, schedule and timezone) change
rarely and are refreshed every hour. Changes made from Home Assistant show up
right away.

## Cloud API client

The integration bundles its own client for the ThermoSave cloud API in
`custom_components/thermosave/pythermosave/`, so it installs no extra Python
packages.

## Contributions are welcome!

See the [contribution guidelines](CONTRIBUTING.md). For local development, run
`scripts/setup` and then `scripts/develop`. This starts Home Assistant with the
integration loaded, using `config/` as the configuration directory.

[hacs]: https://github.com/hacs/integration
[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[validate]: https://github.com/thermosave/ha-thermosave/actions/workflows/validate.yml
[validate-badge]: https://github.com/thermosave/ha-thermosave/actions/workflows/validate.yml/badge.svg
