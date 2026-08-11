# syntax=docker/dockerfile:1
# BARSAN R35.2.3 — audited Railway production image
FROM python:3.12-slim-bookworm

ARG APP_VERSION=35.2.3
LABEL org.opencontainers.image.title="Barsan AI Chatbot"
LABEL org.opencontainers.image.version="${APP_VERSION}"
LABEL barsan.build.marker="BARSAN_R35_2_3_BUILD"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    DATA_DIR=/data \
    BARSAN_RUN_UID=10001 \
    BARSAN_RUN_GID=10001

WORKDIR /app

# pyproject.toml is intentionally not a Docker input. Runtime dependencies have
# one source of truth, and every COPY source below is validated by tests.
COPY ./requirements.lock.txt ./requirements.lock.txt
RUN python -m pip install --no-cache-dir --prefer-binary --only-binary=:all: --timeout 180 --retries 12 -r ./requirements.lock.txt \
    && python -m pip check

COPY ./main.py ./ui_templates.py ./rag_engine.py ./deep_rag.py ./release_info.py ./source_quality.py ./provider_runtime.py ./runtime_guards.py ./ops_runtime.py ./ui_components.py ./barsan_cargo.py ./barsan_location.py ./railway_start.py ./install_builtin_sources.py ./FAQ_TEMPLATE.csv ./thinking_loader.mp4 ./
COPY ./builtin_sources.bundle.part01 ./builtin_sources.bundle.part02 ./builtin_sources.bundle.part03 ./builtin_sources.bundle.part04 ./builtin_sources.bundle.part05 ./builtin_sources.bundle.part06 ./builtin_sources.bundle.part07 ./builtin_sources.bundle.part08 ./builtin_sources.bundle.part09 ./

RUN python /app/install_builtin_sources.py /app/builtin_sources /app/builtin_sources.bundle.part01 /app/builtin_sources.bundle.part02 /app/builtin_sources.bundle.part03 /app/builtin_sources.bundle.part04 /app/builtin_sources.bundle.part05 /app/builtin_sources.bundle.part06 /app/builtin_sources.bundle.part07 /app/builtin_sources.bundle.part08 /app/builtin_sources.bundle.part09 \
    && rm /app/builtin_sources.bundle.part01 /app/builtin_sources.bundle.part02 /app/builtin_sources.bundle.part03 /app/builtin_sources.bundle.part04 /app/builtin_sources.bundle.part05 /app/builtin_sources.bundle.part06 /app/builtin_sources.bundle.part07 /app/builtin_sources.bundle.part08 /app/builtin_sources.bundle.part09 \
    && python -Werror -m py_compile /app/main.py /app/ui_templates.py /app/rag_engine.py /app/deep_rag.py /app/release_info.py /app/source_quality.py /app/provider_runtime.py /app/runtime_guards.py /app/ops_runtime.py /app/ui_components.py /app/barsan_cargo.py /app/barsan_location.py /app/railway_start.py /app/install_builtin_sources.py \
    && mkdir -p /data/uploads /data/upload-sessions /data/backups \
    && chown -R 10001:10001 /app /data \
    && chmod 0700 /data /data/uploads /data/upload-sessions /data/backups \
    && echo "=== BARSAN_R35_BUILD_OK ===" \
    && echo "=== BARSAN_R35_2_3_BUILD_OK ==="

EXPOSE 8080
ENTRYPOINT ["python", "/app/railway_start.py"]
