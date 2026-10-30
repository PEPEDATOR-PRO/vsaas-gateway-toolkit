#!/bin/bash
set -euo pipefail

ENV_FILE=".env"

# Ensure env file exists and is locked down
if [ ! -f "$ENV_FILE" ]; then
  touch "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"

# Update or add KEY=VALUE
upsert_env() {
  local key="$1"
  local value="$2"

  if grep -qE "^${key}=" "$ENV_FILE"; then
    # replace whole line (| delimiter avoids escaping / in values)
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    echo "${key}=${value}" >> "$ENV_FILE"
  fi
}

# Check if KEY exists (even if empty)
has_key() {
  local key="$1"
  grep -qE "^${key}=" "$ENV_FILE"
}

# Get value of KEY (last occurrence)
get_val() {
  local key="$1"
  sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1
}

# Generate a safe secret (letters+digits only) of requested length
gen_secret() {
  local len="${1:-64}"

  if command -v openssl >/dev/null 2>&1; then
    # openssl is common; filter to alnum to be .env-safe
    # Use enough bytes so filtering doesn't shorten too much, then cut.
    openssl rand -base64 96 2>/dev/null | tr -dc 'A-Za-z0-9' | head -c "$len"
    echo
    return
  fi

  # /dev/urandom fallback (very portable)
  # Note: this relies on tr/head being available (standard on almost all Linux)
  tr -dc 'A-Za-z0-9' < /dev/urandom | head -c "$len"
  echo
}

# HOST_IP detection
HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
if [ -z "${HOST_IP}" ]; then
  # fallback for systems without hostname -I
  HOST_IP="$(ip route get 1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}' || true)"
fi
upsert_env "HOST_IP" "$HOST_IP"

# Ensure Django secret(s) exist (generate once)
if ! has_key "DJANGO_SECRET_KEY"; then
  upsert_env "DJANGO_SECRET_KEY" "$(gen_secret 64)"
fi

# Keep SECRET_KEY present as well if your app expects it
if ! has_key "SECRET_KEY"; then
  upsert_env "SECRET_KEY" "$(get_val DJANGO_SECRET_KEY)"
else
  cur="$(get_val SECRET_KEY || true)"
  if [ -z "${cur}" ]; then
    upsert_env "SECRET_KEY" "$(get_val DJANGO_SECRET_KEY)"
  fi
fi

# Superuser defaults (non-secret)
if ! has_key "DJANGO_SUPERUSER_USERNAME"; then
  upsert_env "DJANGO_SUPERUSER_USERNAME" "admin"
fi

if ! has_key "DJANGO_SUPERUSER_EMAIL"; then
  upsert_env "DJANGO_SUPERUSER_EMAIL" ""
fi

if ! has_key "DJANGO_SUPERUSER_PASSWORD"; then
  upsert_env "DJANGO_SUPERUSER_PASSWORD" "admin"
fi

if ! has_key "GITLAB_REGISTRY_HOST"; then
  upsert_env "GITLAB_REGISTRY_HOST" "gitlab.vxg.io:5050"
fi

if ! has_key "GITLAB_REGISTRY_USER"; then
  upsert_env "GITLAB_REGISTRY_USER" ""
fi

if ! has_key "GITLAB_REGISTRY_TOKEN"; then
  upsert_env "GITLAB_REGISTRY_TOKEN" ""
fi

if ! has_key "UPLINK_GATEWAY_IMAGE_REPOSITORY"; then
  upsert_env "UPLINK_GATEWAY_IMAGE_REPOSITORY" "gitlab.vxg.io:5050/vxg/cvp/onvif-uplink/camera-agent-web-server/uplink-gateway"
fi

if ! has_key "UPLINK_GATEWAY_NGINX_IMAGE_REPOSITORY"; then
  upsert_env "UPLINK_GATEWAY_NGINX_IMAGE_REPOSITORY" "gitlab.vxg.io:5050/vxg/cvp/onvif-uplink/camera-agent-web-server/uplink-gateway-nginx"
fi

# Don’t print secrets
echo "Updated $ENV_FILE (HOST_IP=$HOST_IP). Secrets ensured (not printed)."
