# Copyright 2025 Alexey Baikov, Anton Karmanov

# Licensed under the Apache License, Version 2.0.
# See LICENSE.txt file in the project root for license information.

# This file is a part of Salt.Box system.

ARG BASE_IMAGE="registry.altlinux.org/alt/alt:p11"

# hadolint global ignore=DL3006
FROM "$BASE_IMAGE" AS base

# hadolint ignore=DL3015
RUN \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
<<EOF
set -e
mkdir --parents /var/cache/apt/archives/partial/ /var/lib/apt/lists/partial/
apt-get update
apt-get install --yes glibc-pthread=2.38.0.223.f053ff-alt1.p11.1 \
                      python3-module-pip=26.1.2-alt1 \
                      git=2.50.1-alt1
EOF

COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/

RUN mkdir --parents /var/lib/saltbox-gateway/

# hadolint global ignore=DL3064
ENV UVICORN_WORKERS=1
ENV TIMEOUT_GRACEFUL_SHUTDOWN=5
ENV KEYCLOAK_CLIENT_SECRET_FILE=/run/secrets/keycloak_client_saltbox_core_password

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
EXPOSE 8000


FROM base AS uv
# hadolint ignore=DL3015
RUN \
  --mount=type=cache,target=/var/cache/apt,sharing=locked,id=apt \
  --mount=type=cache,target=/var/lib/apt/lists,sharing=locked,id=apt-lists \
<<EOF
set -e
mkdir --parents /var/cache/apt/archives/partial/ /var/lib/apt/lists/partial/
apt-get update

apt-get install --yes uv=0.10.7-alt1
EOF


FROM uv AS venv
WORKDIR /srv/saltbox-gateway/
COPY . /srv/saltbox-gateway/
ARG UV_CACHE_DIR=/root/.cache/uv/
RUN --mount=type=cache,target="$UV_CACHE_DIR",id=uv \
  uv sync \
    --python=/usr/bin/python3 \
    --no-dev \
    --no-sources \
    --no-editable \
  ;


FROM base AS prod
ENV VENV_PATH='/srv/saltbox-gateway/.venv'
ENV PATH="${VENV_PATH}/bin:${PATH}"
COPY --from=venv /srv/saltbox-gateway/.venv "$VENV_PATH"


FROM uv AS dev
ENV GATEWAY_PATH='/mnt/saltbox-gateway/'
WORKDIR "$GATEWAY_PATH"
ENV DEV_MODE=1
#NOTE: User MUST mount respective repositories to run the image
VOLUME /mnt/saltbox-gateway/
VOLUME /mnt/saltbox-sdk/
ENV SALTBOX_SDK_SRC_PATH /mnt/saltbox-sdk/
RUN git config --global --add safe.directory '/mnt/*'
