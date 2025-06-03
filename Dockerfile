# Copyright 2025 Alexey Baikov, Anton Karmanov

# Licensed under the Apache License, Version 2.0.
# See LICENSE.txt file in the project root for license information.

# This file is a part of Salt.Box system.


FROM registry.altlinux.org/alt/alt:p11 AS base
LABEL version='0.1'
EXPOSE 8000

RUN \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
<<EOF
set -e
mkdir --parents /var/cache/apt/archives/partial/ /var/lib/apt/lists/partial/
apt-get update
apt-get install -y glibc-pthread python3-module-pip
EOF

## Outer dependencies
## Install modules which are missing or have incompatible version in the dist repo
RUN \
  --mount=type=bind,source=requirements.txt,target=/mnt/requirements.txt\
  --mount=type=cache,target=/root/.cache/pip/ \
  pip3 install --requirement /mnt/requirements.txt

COPY --chmod=644 docker/shell_init.sh /etc/
COPY --chmod=755 \
  docker/entrypoint.sh \
  docker/uvicorn.sh \
  /usr/local/bin/

RUN mkdir --parents /var/lib/saltbox-gateway/

ENV BASE_URL_ROOT_PATH=/
ENV TIMEOUT_GRACEFUL_SHUTDOWN=5
ENV KEYCLOAK_CLIENT_SECRET_FILE=/run/secrets/keycloak_client_saltbox_core_password

WORKDIR /
ENTRYPOINT ["/usr/local/bin/uvicorn.sh"]


################
## Dev image ##
################

## Mount gateway repository dir to /mnt/saltbox_gateway to serve with the container.

FROM base AS dev
LABEL name='saltbox-gateway-dev' version='0.1'
# Install gateway as editable package
WORKDIR /mnt/saltbox_gateway/
VOLUME /mnt/saltbox_gateway/
RUN \
  --mount=type=bind,target=/mnt/saltbox_gateway/,readwrite \
  pip3 install --no-deps --editable .[dev]
CMD ["dev"]


################
## Main image ##
################

FROM base AS main
LABEL name='saltbox-gateway' version='0.1'
# Install gateway as usual package
RUN \
  --mount=type=bind,target=/mnt/saltbox_gateway/,readwrite \
  --mount=type=cache,target=/root/.cache/pip/ \
  pip3 install --no-deps /mnt/saltbox_gateway/
CMD ["start"]
