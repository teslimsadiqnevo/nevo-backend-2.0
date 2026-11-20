FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY alembic ./alembic
COPY src ./src

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir . \
    && python -m nevo.legal.prepare

# Which source the image was built from, baked in at build time so /health
# can be trusted on any host. Placed after the install so naming a commit
# does not invalidate the dependency layer. Passed in by the deploy:
# heroku container:push web --arg DEPLOY_COMMIT=$(git rev-parse --short HEAD)
ARG DEPLOY_COMMIT=""
ARG DEPLOY_BRANCH=""
ENV DEPLOY_COMMIT=$DEPLOY_COMMIT
ENV DEPLOY_BRANCH=$DEPLOY_BRANCH

EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn nevo.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

