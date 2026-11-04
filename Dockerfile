# syntax=docker/dockerfile:1
# Required immutable python:3.12-slim-bookworm digest, resolved before build.
ARG PYTHON_IMAGE
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements-node.txt requirements-documents.txt ./
RUN pip install --no-cache-dir -r requirements-documents.txt
COPY blockchain/ blockchain/
COPY node/ node/
COPY documents/ documents/
COPY webconsole/ webconsole/
COPY deployment/ deployment/
RUN mkdir -p /data && chown 10001:10001 /data
USER 10001:10001
EXPOSE 19980
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:19980/healthz',timeout=2).read()"]
ENTRYPOINT ["python", "-B", "-m", "deployment.cluster"]
