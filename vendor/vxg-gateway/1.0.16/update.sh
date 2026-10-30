#!/bin/bash
set -euo pipefail

set_arch() {
    if [[ "$1" == "arm64" ]]; then
        ARCH="arm64"
    elif [[ "$1" == "x64" ]]; then
        ARCH="x64"
    else
        echo "Unknown architecture. Please provide either 'arm64' or 'x64'."
        exit 1
    fi
}

detect_arch() {
    local detected_arch
    detected_arch=$(uname -m)

    if [[ $detected_arch == "arm"* ]] || [[ $detected_arch == "aarch"* ]]; then
        echo "Architecture detected: arm64"
        ARCH="arm64"
    elif [[ $detected_arch == "x86_64" ]]; then
        echo "Architecture detected: x64"
        ARCH="x64"
    else
        echo "Error detecting architecture."
        echo "$detected_arch"
        echo "Usage: $0 -orig <original_directory> -dest <destination_directory> -arch <x64|arm64>"
        exit 1
    fi
}

resolve_compose_cmd() {
    if docker compose version >/dev/null 2>&1; then
        COMPOSE_CMD=(docker compose)
    elif docker-compose version >/dev/null 2>&1; then
        COMPOSE_CMD=(docker-compose)
    else
        echo "Docker compose is not installed, please install it first."
        exit 1
    fi
}

compose_in_dir() {
    local dir=$1
    shift
    (
        cd "$dir"
        if [[ -n "${VERSION_FILE:-}" ]] && [[ -f "$dir/$VERSION_FILE" ]]; then
            export CAMERA_AGENT_GATEWAY_VERSION
            CAMERA_AGENT_GATEWAY_VERSION=$(cat "$dir/$VERSION_FILE")
        fi
        "${COMPOSE_CMD[@]}" -f docker-compose.yml -p camera_agent_gateway "$@"
    )
}

get_service_container_id() {
    local dir=$1
    local service=$2
    local include_stopped=${3:-0}

    if [[ "$include_stopped" == "1" ]]; then
        compose_in_dir "$dir" ps -a -q "$service" 2>/dev/null | tail -n 1 || true
    else
        compose_in_dir "$dir" ps -q "$service" 2>/dev/null | tail -n 1 || true
    fi
}

wait_for_container() {
    local dir=$1
    local service=$2
    local attempts=30
    local container_id=""

    while (( attempts > 0 )); do
        container_id=$(get_service_container_id "$dir" "$service" 1)
        if [[ -n "$container_id" ]]; then
            echo "$container_id"
            return 0
        fi
        attempts=$((attempts - 1))
        sleep 1
    done

    echo "Timed out waiting for service '$service' container in $dir."
    exit 1
}

ensure_file_exists() {
    local path=$1
    if [[ ! -f "$path" ]]; then
        echo "Required file not found: $path"
        exit 1
    fi
}

ensure_dir_exists() {
    local path=$1
    if [[ ! -d "$path" ]]; then
        echo "Required directory not found: $path"
        exit 1
    fi
}

ensure_registry_login() {
    local dir=$1

    if [[ -x "$dir/env_setup.sh" ]]; then
        (
            cd "$dir"
            ./env_setup.sh >/dev/null
        )
    fi

    ensure_file_exists "$dir/.env"

    set -a
    # shellcheck disable=SC1090
    . "$dir/.env"
    set +a

    if [[ -z "${GITLAB_REGISTRY_HOST:-}" ]] || [[ -z "${GITLAB_REGISTRY_USER:-}" ]] || [[ -z "${GITLAB_REGISTRY_TOKEN:-}" ]]; then
        echo "Registry credentials are missing in $dir/.env"
        exit 1
    fi

    printf '%s\n' "${GITLAB_REGISTRY_TOKEN}" | docker login "${GITLAB_REGISTRY_HOST}" -u "${GITLAB_REGISTRY_USER}" --password-stdin >/dev/null
}

main() {
    local orig_dir=""
    local dest_dir=""
    local orig_version=""
    local dest_version=""
    local orig_container_id=""
    local dest_container_id=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            -orig)
                orig_dir=$2
                shift 2
                ;;
            -dest)
                dest_dir=$2
                shift 2
                ;;
            -arch)
                set_arch "$2"
                shift 2
                ;;
            *)
                echo "Unknown option: $1"
                echo "Usage: $0 -orig <original_directory> -dest <destination_directory> -arch <x64|arm64>"
                exit 1
                ;;
        esac
    done

    if [[ -z "${ARCH:-}" ]]; then
        detect_arch
    fi

    if [[ -z "$orig_dir" ]] || [[ -z "$dest_dir" ]]; then
        echo "Usage: $0 -orig <original_directory> -dest <destination_directory> -arch <x64|arm64>"
        exit 1
    fi

    ensure_dir_exists "$orig_dir"
    ensure_dir_exists "$dest_dir"
    resolve_compose_cmd

    VERSION_FILE="camera_agent_gateway_${ARCH}.version"
    ensure_file_exists "$orig_dir/$VERSION_FILE"
    ensure_file_exists "$dest_dir/$VERSION_FILE"

    orig_version=$(cat "$orig_dir/$VERSION_FILE")
    dest_version=$(cat "$dest_dir/$VERSION_FILE")

    DB_TMP=$(mktemp)
    trap 'rm -f "${DB_TMP:-}"' EXIT

    orig_container_id=$(get_service_container_id "$orig_dir" app)
    if [[ -z "$orig_container_id" ]]; then
        echo "Could not find a running app container in $orig_dir. Start the original package before running update.sh."
        exit 1
    fi

    legacy_copy_needed=false
    if docker exec "$orig_container_id" test -s /vol/data/db.sqlite3 2>/dev/null; then
        echo "Database is already on the persistent Docker volume; it will be reused after the upgrade."
    else
        echo "Checking for a legacy database at /code/server/db.sqlite3 (one-time migration to volume)..."
        if docker cp "${orig_container_id}:/code/server/db.sqlite3" "$DB_TMP" 2>/dev/null && [[ -s "$DB_TMP" ]]; then
            legacy_copy_needed=true
        else
            echo "No legacy database found; a new database will be created on first start if the volume is empty."
        fi
    fi

    echo "Stopping existing deployment..."
    compose_in_dir "$orig_dir" down >/dev/null 2>&1 || true

    echo "Logging into registry and pulling destination images..."
    ensure_registry_login "$dest_dir"
    compose_in_dir "$dest_dir" pull

    echo "Creating destination containers without starting them..."
    compose_in_dir "$dest_dir" up -d --no-start
    dest_container_id=$(wait_for_container "$dest_dir" app)

    if [[ "$legacy_copy_needed" == "true" ]]; then
        echo "Copying migrated database into destination volume for version: $dest_version"
        docker cp "$DB_TMP" "${dest_container_id}:/vol/data/db.sqlite3"
    fi

    echo "Starting destination deployment..."
    compose_in_dir "$dest_dir" up -d

    echo "Script execution completed successfully."
}

main "$@"
