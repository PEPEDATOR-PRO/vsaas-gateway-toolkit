#!/bin/bash

echo "View full logs in gateway_logs.txt"
{
echo ""
export DOCKER_VERSION=`docker version --format {{.Server.Version}}`
if [[ ! $? -eq 0 ]]; then
      echo "Docker engine is not installed, please install it first"
      echo "You can use docker_install.sh script or find installation instructions here https://docs.docker.com/install/linux/docker-ce/ubuntu/"
      exit 1
fi
echo "Docker version: ${DOCKER_VERSION}"
export DOCKER_PLATFORM=`docker info -f "{{.OperatingSystem}}"`

export COMPOSE_VERSION=`docker-compose version --short`
if [[ ! $? -eq 0 ]]; then
      # If the first command fails, run the second command
      echo "docker-compose failed. Trying docker compose..."
      export PLUGIN_COMPOSE_VERSION=$(docker compose version --short)
      if [[ ! $? -eq 0 ]]; then
            echo "Docker compose is not installed, please install it first"
            echo "Find installation instructions here https://docs.docker.com/compose/install/"
            exit 1
      else
            echo "Compose Plugin version: ${PLUGIN_COMPOSE_VERSION}"
      fi
else
      echo "Compose version: ${COMPOSE_VERSION}"
fi

echo "Stopping camera-agent-gateway module..."
export WORK_DIR=$(dirname $(readlink -f $0))
docker-compose -f ${WORK_DIR}/docker-compose.yml -p camera_agent_gateway stop
if [ $? -ne 0 ]; then
    echo "docker-compose failed. Trying docker compose..."
    docker compose -f ${WORK_DIR}/docker-compose.yml -p camera_agent_gateway stop
fi
} | tee -a ./gateway_logs.txt
