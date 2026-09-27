"""Constants for the Thermosave integration."""

from datetime import timedelta

DOMAIN = "thermosave"

# Cognito app client IDs are public identifiers, not client secrets.
COGNITO_CLIENT_ID = "734cc326bf3e5oicp51lnkdqf8"
COGNITO_BASE_URL = "https://cognito-idp.us-west-1.amazonaws.com"
API_BASE_URL = "https://api.thermosave.com"

CONF_ACCESS_TOKEN = "access_token"  # noqa: S105
CONF_REFRESH_TOKEN = "refresh_token"  # noqa: S105
CONF_EXPIRES_AT = "expires_at"

UPDATE_INTERVAL = timedelta(seconds=30)
