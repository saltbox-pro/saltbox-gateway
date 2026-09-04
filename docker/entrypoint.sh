#! /bin/sh

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

if [ "$DEV_MODE" = 1 ]; then
    # typing_extensions is installed via apt (no RECORD file), pip can't upgrade it in place
    pip3 install --ignore-installed typing_extensions
    pip3 install --editable .[reload]
    pip3 install --editable "${SALTBOX_SDK_SRC_PATH}[mongo]"
fi

cmd_uvicorn() {
  cmd='/usr/bin/uvicorn saltbox_gateway.main:app'
  cmd="${cmd} --host=0.0.0.0 --port=${GATEWAY_HTTP_PORT:-8000}"
  cmd="${cmd} --timeout-graceful-shutdown=${TIMEOUT_GRACEFUL_SHUTDOWN:-5}"
  cmd="${cmd} --workers=${UVICORN_WORKERS:-1}"
  if [ "$DEV_MODE" = 1 ]; then
    cmd="$cmd --reload"
  fi
}

cmd_shell() {
  shift
  cmd="$*"
}

wrong_cmd() {
  warn "Unknown command \"${*}\""
  err "Try \"shell ${*}\" for arbitrary command"
}

case $1 in
  uvicorn) cmd_uvicorn ;;
  shell) cmd_shell "$@" ;;
  *) wrong_cmd "$@" ;;
esac

echo "$ ${cmd}"
exec $cmd
