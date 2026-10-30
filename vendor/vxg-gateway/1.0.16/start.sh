#!/bin/bash
set -uo pipefail
# Function to set architecture
set_arch() {
    # Check if the provided argument matches known architectures
    if [[ "$1" == "arm64" ]]; then
        ARCH="arm64"
    elif [[ "$1" == "x64" ]]; then
        ARCH="x64"
    else
        echo "Unknown architecture. Please provide either 'arm64' or 'x64'."
        exit 1
    fi
}

echo "View full logs in gateway_logs.txt"
{
echo ""
# Get the machine architecture using uname -m
if [[ -n "${1:-}" ]]; then
    set_arch "$1"
else
      ARCH=$(uname -m)

      if [[ $ARCH == "arm"* ]]; then
            echo "Architecture detected: arm64"
            ARCH="arm64"
      elif [[ $ARCH == "aarch"* ]]; then
            echo "Architecture detected: arm64"
            ARCH="arm64"
      elif [[ $ARCH == "x86_64" ]]; then
            echo "Architecture detected: x64"
            ARCH="x64"
      else
            echo "Error detecting architecture."
            echo "$ARCH"
            echo "Please execute the script as follows: ./start.sh <ARCH>"
            echo "Ex. ./start.sh x64"
            echo "    ./start.sh arm64"
      fi
fi

export DOCKER_VERSION=$(docker version --format '{{.Server.Version}}' 2>/dev/null || true)
if [ -z "${DOCKER_VERSION}" ]; then
      echo "Docker engine is not installed, please install it first"
      echo "You can use docker_install.sh script or find installation instructions here https://docs.docker.com/install/linux/docker-ce/ubuntu/"
      exit 1
fi
echo "Docker version: ${DOCKER_VERSION}"
export DOCKER_PLATFORM=$(docker info -f "{{.OperatingSystem}}" 2>/dev/null || true)

export COMPOSE_VERSION=$(docker-compose version --short 2>/dev/null || true)
if [ -z "${COMPOSE_VERSION}" ]; then
      # If the first command fails, run the second command
      echo "docker-compose failed. Trying docker compose..."
      export PLUGIN_COMPOSE_VERSION=$(docker compose version --short 2>/dev/null || true)
      if [ -z "${PLUGIN_COMPOSE_VERSION}" ]; then
            echo "Docker compose is not installed, please install it first"
            echo "Find installation instructions here https://docs.docker.com/compose/install/"
            exit 1
      else
            export USE_DOCKER_COMPOSE_PLUGIN="1"
            echo "Compose Plugin version: ${PLUGIN_COMPOSE_VERSION}"
      fi
else
      export USE_DOCKER_COMPOSE_PLUGIN="0"
      echo "Compose version: ${COMPOSE_VERSION}"
fi

export WORK_DIR=$(dirname "$(readlink -f "$0")")
cd "${WORK_DIR}"
export CAMERA_AGENT_GATEWAY_VERSION=$(cat "${WORK_DIR}/camera_agent_gateway_${ARCH}.version")
# Run the update_env.sh script
"${WORK_DIR}/env_setup.sh"

set -a
. "${WORK_DIR}/.env"
set +a

if [ -z "${GITLAB_REGISTRY_HOST:-}" ] || [ -z "${GITLAB_REGISTRY_USER:-}" ] || [ -z "${GITLAB_REGISTRY_TOKEN:-}" ]; then
      echo "Registry credentials are missing. Set GITLAB_REGISTRY_HOST, GITLAB_REGISTRY_USER, and GITLAB_REGISTRY_TOKEN in ${WORK_DIR}/.env"
      exit 1
fi

# Run docker commands
echo "Logging into GitLab container registry..."
if ! printf '%s\n' "${GITLAB_REGISTRY_TOKEN}" | docker login "${GITLAB_REGISTRY_HOST}" -u "${GITLAB_REGISTRY_USER}" --password-stdin; then
      echo "Failed to login to the GitLab container registry."
      exit 1
fi
echo "Pulling Uplink Gateway images..."
if [ "${USE_DOCKER_COMPOSE_PLUGIN}" = "1" ]; then
      if ! docker compose -f "${WORK_DIR}/docker-compose.yml" -p camera_agent_gateway pull; then
            echo "Failed to pull images."
            exit 1
      fi
      echo "Starting Uplink Gateway..."
      docker compose -f "${WORK_DIR}/docker-compose.yml" -p camera_agent_gateway up -d
else
      if ! docker-compose -f "${WORK_DIR}/docker-compose.yml" -p camera_agent_gateway pull; then
            echo "Failed to pull images."
            exit 1
      fi
      echo "Starting Uplink Gateway..."
      docker-compose -f "${WORK_DIR}/docker-compose.yml" -p camera_agent_gateway up -d
fi
} | tee -a ./gateway_logs.txt
