FROM python:3.10.9-slim

WORKDIR /app

# Cài đặt các thư viện hệ thống cần thiết cho ODBC, Cosmos, Blob, Redis, Flask, Azure SDK
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        dnsutils \
        curl \
        unixodbc \
        unixodbc-dev \
        odbcinst \
        gnupg \
        gcc \
        g++ \
        python3-dev \
        openssh-client && \
    curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor \
        -o /usr/share/keyrings/microsoft-prod.gpg && \
    curl https://packages.microsoft.com/config/debian/12/prod.list \
        > /etc/apt/sources.list.d/mssql-release.list && \
    apt-get update && \
    ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy requirements và cài đặt Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ mã nguồn
COPY . .

# Nhận build args từ GitHub Actions
ARG KEYVAULT_URL
ARG SQL_CONNECTION_STRING
ARG COSMOS_CONNECTION_STRING
ARG BLOB_CONNECTION_STRING
ARG ACR_NAME
ARG ACR_SUBSCRIPTION
ARG ACR_RG
ARG REDIS_CONNECTION_STRING

# Set environment variables
ENV KEYVAULT_URL=$KEYVAULT_URL
ENV SQL_CONNECTION_STRING=$SQL_CONNECTION_STRING
ENV COSMOS_CONNECTION_STRING=$COSMOS_CONNECTION_STRING
ENV BLOB_CONNECTION_STRING=$BLOB_CONNECTION_STRING
ENV ACR_NAME=$ACR_NAME
ENV ACR_SUBSCRIPTION=$ACR_SUBSCRIPTION
ENV ACR_RG=$ACR_RG
ENV REDIS_CONNECTION_STRING=$REDIS_CONNECTION_STRING

# Thiết lập biến môi trường cho Flask
ENV FLASK_APP=app.py
ENV FLASK_RUN_HOST=0.0.0.0
EXPOSE 5000

# Chạy Flask app
CMD ["python", "-m", "flask", "run"]