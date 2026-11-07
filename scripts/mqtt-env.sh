# Sourced by other scripts (POSIX sh): helpers for the MQTT broker login. Never prints the password.
#
#   ensure_mqtt_password [env-file]   put a random MQTT_PASSWORD into .env when it is missing or blank
#   load_mqtt_credentials [env-file]  export MQTT_USERNAME / MQTT_PASSWORD from .env unless already set
#
# load_mqtt_credentials reads only those two keys (it does not source .env: .env says MQTT_HOST=mqtt,
# which is the Docker-network name and wrong for a client running on the host).

_mqtt_env_value() {  # _mqtt_env_value KEY FILE -> value of the last KEY= line, without quotes
  [ -f "$2" ] || return 0
  grep -E "^$1=" "$2" | tail -n 1 | cut -d= -f2- | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
    -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/" || true  # no match is fine under pipefail
}

ensure_mqtt_password() {
  _env_file="${1:-.env}"
  [ -f "$_env_file" ] || return 0
  if [ -n "${MQTT_PASSWORD:-}" ] || [ -n "$(_mqtt_env_value MQTT_PASSWORD "$_env_file")" ]; then
    return 0
  fi
  if command -v openssl >/dev/null 2>&1; then
    _pw="$(openssl rand -hex 16)"
  elif command -v python3 >/dev/null 2>&1; then
    _pw="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
  else
    echo "ERROR: need openssl or python3 to generate MQTT_PASSWORD; set it in $_env_file yourself." >&2
    return 1
  fi
  _tmp="$(mktemp "${_env_file}.XXXXXX")"
  if grep -qE '^MQTT_PASSWORD=' "$_env_file"; then
    awk -v pw="$_pw" '/^MQTT_PASSWORD=/ { print "MQTT_PASSWORD=" pw; next } { print }' "$_env_file" > "$_tmp"
  else
    { cat "$_env_file"; printf '\nMQTT_PASSWORD=%s\n' "$_pw"; } > "$_tmp"
  fi
  chmod 600 "$_tmp"
  mv "$_tmp" "$_env_file"
  echo "Generated a random MQTT_PASSWORD in $_env_file (the broker requires a login)."
  unset _pw _tmp
}

load_mqtt_credentials() {
  _env_file="${1:-.env}"
  if [ -z "${MQTT_USERNAME:-}" ]; then
    MQTT_USERNAME="$(_mqtt_env_value MQTT_USERNAME "$_env_file")"
  fi
  if [ -z "${MQTT_PASSWORD:-}" ]; then
    MQTT_PASSWORD="$(_mqtt_env_value MQTT_PASSWORD "$_env_file")"
  fi
  export MQTT_USERNAME MQTT_PASSWORD
}
