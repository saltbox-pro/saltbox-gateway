# Copyright 2025 Alexey Baikov, Anton Karmanov

# Licensed under the Apache License, Version 2.0.
# See LICENSE.txt file in the project root for license information.

# This file is a part of Salt.Box system.


FROM registry.altlinux.org/alt/alt:p11 AS base
LABEL version='0.2'
EXPOSE 8000

RUN \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
<<EOF
set -e
mkdir --parents /var/cache/apt/archives/partial/ /var/lib/apt/lists/partial/
apt-get update
apt-get install -y glibc-pthread python3-module-pip git
EOF

## Outer dependencies
## Install modules which are missing or have incompatible version in the dist repo
RUN \
  --mount=type=bind,source=requirements.txt,target=/mnt/requirements.txt\
  --mount=type=cache,target=/root/.cache/pip/ \
  pip3 install --requirement /mnt/requirements.txt

COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/

RUN mkdir --parents /var/lib/saltbox-gateway/

ENV TIMEOUT_GRACEFUL_SHUTDOWN=5
ENV KEYCLOAK_CLIENT_SECRET_FILE=/run/secrets/keycloak_client_saltbox_core_password

WORKDIR /
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]


################
## Dev image ##
################

## Mount gateway repository dir to /mnt/saltbox-gateway to serve with the container.

FROM base AS dev
LABEL name='saltbox-gateway-dev' version='0.2'
# Install gateway as editable package
RUN \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
<<EOF
set -e
mkdir --parents /var/cache/apt/archives/partial/ /var/lib/apt/lists/partial/
apt-get update
apt-get install -y ipython3
EOF
WORKDIR /mnt/saltbox-gateway/
ENV DEV_MODE=1
# User should mount respective repositories to run the image
VOLUME /mnt/saltbox-gateway/
VOLUME /mnt/saltbox-sdk/
ENV SALTBOX_SDK_SRC_PATH /mnt/saltbox-sdk/


################
## Main image ##
################

FROM base AS main
LABEL name='saltbox-gateway' version='0.2'
# Install gateway as usual package
RUN \
  --mount=type=bind,target=/mnt/saltbox-gateway/,readwrite \
  --mount=type=cache,target=/root/.cache/pip/ \
  pip3 install --no-deps /mnt/saltbox-gateway/
