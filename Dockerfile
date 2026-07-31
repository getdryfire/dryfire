# Development image. There is deliberately NO production image: agentcheck ships
# to PyPI as a package (SPEC §1.4 — no server, no service). Docker exists here to
# provide a reproducible Linux toolchain and a local CI matrix (docker-compose.yml).
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim

COPY --from=ghcr.io/astral-sh/uv:0.10.10 /uv /uvx /bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The venv lives OUTSIDE /app so the bind mount of the source tree
# (docker-compose.yml) cannot shadow it with the host's macOS .venv.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_FROZEN=1

# Layer-cache third-party deps separately from the project itself.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --all-extras --no-install-project

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --all-extras

CMD ["make", "check"]
