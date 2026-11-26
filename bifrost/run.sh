#!/usr/bin/with-contenv sh
# with-contenv passes the Supervisor environment (SUPERVISOR_TOKEN) to the app
set -e
exec python3 -m bifrost_app
