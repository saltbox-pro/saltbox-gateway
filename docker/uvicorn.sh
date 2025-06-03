#! /bin/sh
# shellcheck source=./shell_init.sh
. /etc/shell_init.sh

extra_args=''

case $1 in
  start) ;;
  dev) extra_args='--reload' ;;
  *) echo "unknown command \"$1\"" && exit 1 ;;
esac

cmd='/usr/bin/uvicorn saltbox_gateway.main:app'
cmd="$cmd --host=0.0.0.0 --port=${GATEWAY_HTTP_PORT:-8000}"
cmd="$cmd --timeout-graceful-shutdown=${TIMEOUT_GRACEFUL_SHUTDOWN:-5}"
cmd="$cmd --workers=${UVICORN_WORKERS:-1}"
cmd="$cmd $extra_args"

echo "$ ${cmd}"
exec $cmd
