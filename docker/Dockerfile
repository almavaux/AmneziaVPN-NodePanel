FROM python:3.12-slim

WORKDIR /service

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client sshpass \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY docker/ ./docker/
COPY scripts/install_project.sh ./scripts/install_project.sh
COPY scripts/install_node_remote.sh ./scripts/install_node_remote.sh
COPY .env.example ./
RUN chmod +x ./scripts/install_project.sh ./scripts/install_node_remote.sh

# Non-root user for principle of least privilege,
# but docker.sock access still needs group docker or root.
# If you run as non-root, add the user to the docker group on the host.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000
EXPOSE 50051

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--access-log"]
