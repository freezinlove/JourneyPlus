# Web 构建阶段：Node.js 与前端源码不会进入最终运行镜像。
FROM node:22-bookworm-slim AS web-build
WORKDIR /web
COPY clients/web/package.json clients/web/package-lock.json ./
RUN npm ci
COPY clients/web/ ./
RUN npm run build

# 按锁文件安装后端依赖；保留源码布局供现有迁移入口定位。
FROM ghcr.io/astral-sh/uv:0.11.26 AS uv
FROM python:3.12-slim-bookworm AS app
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    JOURNEYPLUS_WEB_DIST="/app/clients/web/dist"

COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
COPY alembic.ini ./
COPY migrations/ ./migrations/
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
RUN uv sync --frozen --no-dev && uv cache clean \
    && playwright install --with-deps chromium \
    && apt-get update && apt-get install -y --no-install-recommends xvfb \
    && rm -rf /var/lib/apt/lists/*
COPY --from=web-build /web/dist/ ./clients/web/dist/

# 密码、授权文件和数据库由运行配置提供，不写入镜像。
EXPOSE 8000
CMD ["journeyplus", "product-api", "--host", "0.0.0.0", "--port", "8000"]
