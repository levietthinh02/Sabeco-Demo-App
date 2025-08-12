"""
Module kiểm tra kết nối và thao tác cơ bản với các dịch vụ Azure.
"""
import os
import socket
import subprocess
import time
from datetime import datetime
import http.client

# Azure SDK imports
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from azure.storage.blob import BlobServiceClient
from azure.cosmos import CosmosClient
from azure.mgmt.containerregistry import ContainerRegistryManagementClient
from azure.mgmt.containerregistry.models import Registry
import pyodbc
import redis

def check_nslookup(host):
    """Kiểm tra DNS lookup cho host."""
    try:
        output = subprocess.check_output(["nslookup", host], stderr=subprocess.STDOUT, text=True)
        return True, output
    except Exception as e:
        return False, str(e)

def check_port(host, port):
    """Kiểm tra kết nối TCP tới host:port."""
    try:
        with socket.create_connection((host, int(port)), timeout=5):
            return True, "SUCCESS"
    except Exception as e:
        return False, str(e)

def check_http(host, port=443, path="/"):
    """Kiểm tra HTTP GET tới host:port/path."""
    conn = None
    try:
        conn = http.client.HTTPSConnection(host, port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        return True, f"HTTP {resp.status} {resp.reason}"
    except Exception as e:
        return False, str(e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

def log_change(service, check_type, status, detail):
    """Ghi log khi trạng thái kiểm tra thay đổi."""
    print(f"[{datetime.now().isoformat()}] {service} {check_type}: {status} - {detail}", flush=True)

# Azure credential dùng chung
credential = DefaultAzureCredential()

def test_key_vault(vault_url):
    """Kiểm tra truy cập Key Vault và liệt kê secrets."""
    try:
        client = SecretClient(vault_url=f"https://{vault_url}/", credential=credential)
        secrets = list(client.list_properties_of_secrets())
        return True, f"Num secrets: {len(secrets)}"
    except Exception as e:
        return False, str(e)

def test_azure_sql(server, database):
    """Kiểm tra truy vấn đơn giản tới Azure SQL Database."""
    try:
        conn_str = (
            f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={server};DATABASE={database};Encrypt=yes;TrustServerCertificate=no;"
            f"Authentication=ActiveDirectoryMsi;"
        )
        conn = pyodbc.connect(conn_str, timeout=5)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        row = cursor.fetchone()
        conn.close()
        return True, f"SQL SELECT 1: {row[0]}"
    except Exception as e:
        return False, str(e)

def test_cosmos_db(endpoint, key, database_name):
    """Kiểm tra truy cập Cosmos DB và liệt kê databases."""
    try:
        client = CosmosClient(f"https://{endpoint}/", key)
        dbs = list(client.list_databases())
        return True, f"Num DBs: {len(dbs)}"
    except Exception as e:
        return False, str(e)

def test_blob_storage(blob_url):
    """Kiểm tra truy cập Blob Storage và liệt kê containers."""
    try:
        client = BlobServiceClient(account_url=f"https://{blob_url}/", credential=credential)
        containers = list(client.list_containers())
        return True, f"Num containers: {len(containers)}"
    except Exception as e:
        return False, str(e)

def test_container_registry(acr_name, subscription_id, resource_group):
    """Kiểm tra truy cập Azure Container Registry."""
    try:
        acr_client = ContainerRegistryManagementClient(credential, subscription_id)
        registry: Registry = acr_client.registries.get(resource_group, acr_name)
        login_server = registry.login_server
        return True, f"Login server: {login_server}"
    except Exception as e:
        return False, str(e)

def test_redis_cache(redis_connection_string):
    """Kiểm tra kết nối Redis Cache."""
    try:
        r = redis.from_url(redis_connection_string)
        pong = r.ping()
        return True, f"PING: {pong}"
    except Exception as e:
        return False, str(e)

def get_services_from_env():
    """Lấy danh sách dịch vụ và thông tin host/port từ biến môi trường."""
    return [
        ("KeyVault", os.environ.get("KEY_VAULT_URL", "").replace("https://", "").replace("/", ""), 443),
        ("SQL", os.environ.get("SQL_SERVER", "").replace("https://", "").replace("/", ""), 1433),
        ("CosmosDB", os.environ.get("COSMOS_ENDPOINT", "").replace("https://", "").replace(":443/", "").replace("/", ""), 443),
        ("Blob", os.environ.get("BLOB_URL", "").replace("https://", "").replace("/", ""), 443),
        ("ACR", os.environ.get("ACR_NAME", "") + ".azurecr.io", 443),
        ("Redis", os.environ.get("REDIS_HOST", ""), 6380),
    ]

def main():
    """Vòng lặp kiểm tra trạng thái các dịch vụ Azure."""
    services = get_services_from_env()
    print("Service list:", services, flush=True)
    prev_status = {}
    while True:
        for name, host, port in services:
            # HTTP check (chỉ cho các dịch vụ không phải Redis, ACR)
            if name not in ("Redis", "ACR"):
                http_status, http_detail = check_http(host, port)
                if prev_status.get((name, "http")) != http_status:
                    log_change(name, "HTTP", "OK" if http_status else "FAIL", http_detail)
                prev_status[(name, "http")] = http_status

            # NSLOOKUP check
            nslookup_status, nslookup_detail = check_nslookup(host)
            if prev_status.get((name, "nslookup")) != nslookup_status:
                log_change(name, "NSLOOKUP", "OK" if nslookup_status else "FAIL", nslookup_detail)
            prev_status[(name, "nslookup")] = nslookup_status

            # TELNET check
            telnet_status, telnet_detail = check_port(host, port)
            if prev_status.get((name, "telnet")) != telnet_status:
                log_change(name, "TELNET", "OK" if telnet_status else "FAIL", telnet_detail)
            prev_status[(name, "telnet")] = telnet_status

            # AZURE SDK/API check cho KeyVault, SQL, CosmosDB
            if name == "KeyVault":
                kv_status, kv_detail = test_key_vault(os.environ.get("KEY_VAULT_URL", ""))
                if prev_status.get((name, "azure")) != kv_status:
                    log_change(name, "AZURE", "OK" if kv_status else "FAIL", kv_detail)
                    prev_status[(name, "azure")] = kv_status
            elif name == "SQL":
                sql_status, sql_detail = test_azure_sql(host, os.environ.get("SQL_DATABASE", ""))
                if prev_status.get((name, "azure")) != sql_status:
                    log_change(name, "AZURE", "OK" if sql_status else "FAIL", sql_detail)
                    prev_status[(name, "azure")] = sql_status
            elif name == "CosmosDB":
                cosmos_status, cosmos_detail = test_cosmos_db(host, os.environ.get("COSMOS_KEY", ""), os.environ.get("COSMOS_DATABASE_NAME", ""))
                if prev_status.get((name, "azure")) != cosmos_status:
                    log_change(name, "AZURE", "OK" if cosmos_status else "FAIL", cosmos_detail)
                    prev_status[(name, "azure")] = cosmos_status
            # Bỏ qua AZURE check cho Blob, ACR, Redis
        time.sleep(5)

if __name__ == "__main__":
    main()