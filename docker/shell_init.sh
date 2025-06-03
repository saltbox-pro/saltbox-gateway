# This file is a part of Salt.Box Core Docker image.
#
# This file supposed to be sourced with a shell.
#

set -e

warn() {
  1>&2 echo "$@"
}

err() {
  warn "$@" && exit 1
}

REDIS_PASSWORD="$(cat /run/secrets/redis_salt_password)"
KEYCLOAK_CLIENT_SECRET="$(cat "$KEYCLOAK_CLIENT_SECRET_FILE")"


export REDIS_PASSWORD KEYCLOAK_CLIENT_SECRET
