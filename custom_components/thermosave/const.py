"""Constants for the ThermoSave integration."""

from datetime import timedelta

DOMAIN = "thermosave"

# Cognito app client IDs are public identifiers, not client secrets.
COGNITO_CLIENT_ID = "1ce8jd3ujc5alanbtqds8d6hpn"
COGNITO_BASE_URL = "https://cognito-idp.us-west-1.amazonaws.com"
API_BASE_URL = "https://api.thermosave.com"

CONF_ACCESS_TOKEN = "access_token"  # noqa: S105
CONF_REFRESH_TOKEN = "refresh_token"  # noqa: S105
CONF_EXPIRES_AT = "expires_at"

STATUS_UPDATE_INTERVAL = timedelta(minutes=5)
CONFIG_UPDATE_INTERVAL = timedelta(hours=1)
DEVICES_UPDATE_INTERVAL = timedelta(hours=1)
