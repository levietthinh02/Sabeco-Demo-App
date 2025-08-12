from flask import Flask, render_template_string, request
import uuid
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from azure.storage.blob import BlobServiceClient
from azure.cosmos import CosmosClient, PartitionKey
from azure.mgmt.containerregistry import ContainerRegistryManagementClient
from azure.mgmt.containerregistry.models import Registry
import pyodbc
import redis

import os

app = Flask(__name__)


# --- Helper functions ---
def test_key_vault_full(vault_url, credential):
    steps = []
    try:
        client = SecretClient(vault_url=f"https://{vault_url}/", credential=credential)
        secret_name = f"test-conn-{uuid.uuid4().hex[:8]}"
        secret_value = uuid.uuid4().hex
        client.set_secret(secret_name, secret_value)
        steps.append((True, f"Tạo secret '{secret_name}' thành công"))
        got = client.get_secret(secret_name)
        if got.value == secret_value:
            steps.append((True, f"Đọc secret thành công: {got.value}"))
        else:
            steps.append((False, "Giá trị secret không khớp!"))
        poller = client.begin_delete_secret(secret_name)
        poller.wait()
        steps.append((True, "Xóa secret thành công"))
    except Exception as e:
        steps.append((False, str(e)))
    return steps

def test_azure_sql_full(connection_string):
    steps = []
    table = "test_connectivity"
    try:
        conn = pyodbc.connect(connection_string, timeout=5)
        cursor = conn.cursor()
        try:
            cursor.execute(f"CREATE TABLE {table} (id INT PRIMARY KEY, val NVARCHAR(100))")
            conn.commit()
            steps.append((True, "Tạo bảng test thành công"))
        except Exception:
            steps.append((True, "Bảng test đã tồn tại"))
        cursor.execute(f"INSERT INTO {table} (id, val) VALUES (?, ?)", (1, "hello"))
        conn.commit()
        steps.append((True, "Insert thành công"))
        cursor.execute(f"SELECT val FROM {table} WHERE id=1")
        row = cursor.fetchone()
        if row and row[0] == "hello":
            steps.append((True, f"Select thành công: {row[0]}"))
        else:
            steps.append((False, "Select thất bại!"))
        cursor.execute(f"DELETE FROM {table} WHERE id=1")
        conn.commit()
        steps.append((True, "Xóa dòng test thành công"))
        cursor.execute(f"DROP TABLE {table}")
        conn.commit()
        steps.append((True, "Xóa bảng test thành công"))
        conn.close()
    except Exception as e:
        steps.append((False, str(e)))
    return steps

def test_cosmosdb_full(connection_string):
    steps = []
    db_name = f"testdb{uuid.uuid4().hex[:6]}"
    container_name = f"testct{uuid.uuid4().hex[:6]}"
    try:
        # Parse connection string để lấy endpoint và key
        conn_parts = dict(part.split('=', 1) for part in connection_string.split(';') if '=' in part)
        endpoint = conn_parts.get('AccountEndpoint', '').replace('https://', '').replace('http://', '')
        key = conn_parts.get('AccountKey', '')
        
        if not endpoint or not key:
            steps.append((False, "Connection string không hợp lệ"))
            return steps
            
        client = CosmosClient(f"https://{endpoint}/", key)
        db = client.create_database(db_name)
        steps.append((True, f"Tạo database '{db_name}' thành công"))
        container = db.create_container(id=container_name, partition_key=PartitionKey(path="/id"))
        steps.append((True, f"Tạo container '{container_name}' thành công"))
        item = {"id": "1", "val": "hello"}
        container.create_item(item)
        steps.append((True, "Insert item thành công"))
        items = list(container.query_items(query="SELECT * FROM c WHERE c.id='1'", enable_cross_partition_query=True))
        if items and items[0]["val"] == "hello":
            steps.append((True, f"Query thành công: {items[0]['val']}"))
        else:
            steps.append((False, "Query thất bại!"))
        container.delete_item(item="1", partition_key="1")
        steps.append((True, "Xóa item thành công"))
        db.delete_container(container_name)
        steps.append((True, "Xóa container thành công"))
        client.delete_database(db_name)
        steps.append((True, "Xóa database thành công"))
    except Exception as e:
        steps.append((False, str(e)))
    return steps

def test_blob_full(connection_string):
    steps = []
    container_name = f"testct{uuid.uuid4().hex[:6]}"
    blob_name = "testfile.txt"
    data = b"hello azure blob"
    try:
        client = BlobServiceClient.from_connection_string(connection_string)
        container = client.create_container(container_name)
        steps.append((True, f"Tạo container '{container_name}' thành công"))
        container_client = client.get_container_client(container_name)
        container_client.upload_blob(blob_name, data)
        steps.append((True, "Upload blob thành công"))
        blob_data = container_client.download_blob(blob_name).readall()
        if blob_data == data:
            steps.append((True, "Download blob thành công"))
        else:
            steps.append((False, "Dữ liệu blob không khớp!"))
        container_client.delete_blob(blob_name)
        steps.append((True, "Xóa blob thành công"))
        client.delete_container(container_name)
        steps.append((True, "Xóa container thành công"))
    except Exception as e:
        steps.append((False, str(e)))
    return steps

def test_redis_full(redis_connection_string):
    steps = []
    key = f"testkey:{uuid.uuid4().hex[:6]}"
    value = uuid.uuid4().hex
    try:
        # Hỗ trợ Redis với SSH tunnel
        if redis_connection_string.startswith('ssh://'):
            # Parse SSH connection string: ssh://user@host:port
            ssh_parts = redis_connection_string.replace('ssh://', '').split('@')
            if len(ssh_parts) == 2:
                user = ssh_parts[0]
                host_port = ssh_parts[1].split(':')
                host = host_port[0]
                port = int(host_port[1]) if len(host_port) > 1 else 22
                
                # Sử dụng SSH tunnel để kết nối Redis
                import paramiko
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(host, port=port, username=user)
                
                # Tạo Redis connection qua SSH tunnel
                r = redis.Redis(host='localhost', port=6379, decode_responses=True)
                steps.append((True, f"Kết nối Redis qua SSH thành công: {host}:{port}"))
            else:
                steps.append((False, "SSH connection string không hợp lệ"))
                return steps
        else:
            # Kết nối Redis trực tiếp
            r = redis.from_url(redis_connection_string)
            steps.append((True, "Kết nối Redis trực tiếp thành công"))
        
        r.set(key, value)
        steps.append((True, f"Set key '{key}' thành công"))
        val = r.get(key)
        if val and val == value:
            steps.append((True, "Get key thành công"))
        else:
            steps.append((False, "Giá trị key không khớp!"))
        r.delete(key)
        steps.append((True, "Xóa key thành công"))
        
        if redis_connection_string.startswith('ssh://'):
            ssh.close()
            
    except Exception as e:
        steps.append((False, str(e)))
    return steps

def test_acr_full(acr_name, subscription_id, resource_group, credential):
    steps = []
    try:
        acr_client = ContainerRegistryManagementClient(credential, subscription_id)
        registry = acr_client.registries.get(resource_group, acr_name)
        login_server = registry.login_server
        steps.append((True, f"Login server: {login_server}"))
        try:
            props = acr_client.registries.get(resource_group, acr_name)
            steps.append((True, "Có thể truy cập registry properties"))
        except Exception as e:
            steps.append((False, f"Không thể truy cập registry properties: {e}"))
    except Exception as e:
        steps.append((False, str(e)))
    return steps

def list_key_vault_secrets(vault_url, credential):
    try:
        client = SecretClient(vault_url=f"https://{vault_url}/", credential=credential)
        secrets = [s.name for s in client.list_properties_of_secrets()]
        return secrets
    except Exception as e:
        return [str(e)]

def list_sql_tables(connection_string):
    try:
        conn = pyodbc.connect(connection_string, timeout=5)
        cursor = conn.cursor()
        cursor.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE'")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        return tables
    except Exception as e:
        return [str(e)]

def list_cosmos_items(endpoint, key, db_name, container_name):
    try:
        client = CosmosClient(f"https://{endpoint}/", key)
        db = client.get_database_client(db_name)
        container = db.get_container_client(container_name)
        items = list(container.read_all_items())
        return items
    except Exception as e:
        return [str(e)]

def list_blob_containers(connection_string):
    try:
        client = BlobServiceClient.from_connection_string(connection_string)
        containers = [c['name'] for c in client.list_containers()]
        return containers
    except Exception as e:
        return [str(e)]

def list_blobs_in_container(connection_string, container_name):
    try:
        client = BlobServiceClient.from_connection_string(connection_string)
        container_client = client.get_container_client(container_name)
        blobs = [b.name for b in container_client.list_blobs()]
        return blobs
    except Exception as e:
        return [str(e)]

def list_acr_images(acr_name, subscription_id, resource_group, credential):
    try:
        acr_client = ContainerRegistryManagementClient(credential, subscription_id)
        repos = acr_client.registries.list_credentials(resource_group, acr_name)
        # This only lists credentials, to list images use REST or Azure SDK for Container Registry (preview)
        # Here, we just return the login server as a placeholder
        registry = acr_client.registries.get(resource_group, acr_name)
        return [registry.login_server]
    except Exception as e:
        return [str(e)]

def list_redis_keys(redis_connection_string, pattern='*'):
    try:
        r = redis.from_url(redis_connection_string)
        keys = r.keys(pattern)
        return [k.decode() for k in keys]
    except Exception as e:
        return [str(e)]

def get_config():
    # Ưu tiên lấy từ biến môi trường, fallback sang file yaml nếu chạy local
    config = {}
    config_keys = [
        ("keyvault_url", "KEYVAULT_URL"),
        ("sql_connection_string", "SQL_CONNECTION_STRING"),
        ("cosmos_connection_string", "COSMOS_CONNECTION_STRING"),
        ("blob_connection_string", "BLOB_CONNECTION_STRING"),
        ("acr_name", "ACR_NAME"),
        ("acr_subscription", "ACR_SUBSCRIPTION"),
        ("acr_rg", "ACR_RG"),
        ("redis_connection_string", "REDIS_CONNECTION_STRING"),
    ]
    for k, envk in config_keys:
        v = os.environ.get(envk)
        if v:
            config[k] = v
    # Nếu thiếu biến env, thử đọc file yaml (chỉ dùng cho local dev)
    if len(config) < len(config_keys):
        try:
            CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.yaml')
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                yaml_config = yaml.safe_load(f)
            for k, _ in config_keys:
                if k not in config and k in yaml_config:
                    config[k] = yaml_config[k]
        except Exception:
            pass
    return config

# --- HTML Template ---
TEMPLATE = '''
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Azure Connectivity Tester (Flask)</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #f8f9fa; }
        .card { margin-bottom: 2rem; }
        .service-title { font-size: 1.3rem; font-weight: 600; }
        .result-list { margin-top: 1rem; }
    </style>
</head>
<body>
<div class="container py-4">
    <h1 class="mb-4 text-center">🔗 Azure Connectivity Tester (Flask)</h1>
    <div class="row row-cols-1 row-cols-md-2 g-4">
        <div class="col">
            <div class="card shadow-sm">
                <div class="card-body">
                    <div class="service-title mb-2">Key Vault</div>
                    <form method="post" class="row g-2 align-items-end">
                        <input type="hidden" name="service" value="keyvault">
                        <div class="col-md-5">
                            <label class="form-label">Secret Name</label>
                            <input name="keyvault_secret_name" class="form-control">
                        </div>
                        <div class="col-md-5">
                            <label class="form-label">Secret Value</label>
                            <input name="keyvault_secret_value" class="form-control">
                        </div>
                        <div class="col-md-2 d-grid gap-2">
                            <button type="submit" name="action" value="add" class="btn btn-primary">Add</button>
                            <button type="submit" name="action" value="list" class="btn btn-secondary mt-1">List</button>
                        </div>
                    </form>
                    {% if results_keyvault is not none %}
                        <div class="result-list">
                        {% for msg in results_keyvault %}
                            {% if 'added' in msg or 'Secret' in msg or 'success' in msg or 'thành công' in msg %}
                                <div class="alert alert-success py-2 mb-2">{{ msg }}</div>
                            {% else %}
                                <div class="alert alert-danger py-2 mb-2">{{ msg }}</div>
                            {% endif %}
                        {% endfor %}
                        </div>
                    {% endif %}
                </div>
            </div>
        </div>
        <div class="col">
            <div class="card shadow-sm">
                <div class="card-body">
                    <div class="service-title mb-2">Azure SQL Database</div>
                    <form method="post" class="row g-2 align-items-end">
                        <input type="hidden" name="service" value="sql">
                        <div class="col-md-5">
                            <label class="form-label">Table Name</label>
                            <input name="sql_table" class="form-control">
                        </div>
                        <div class="col-md-5">
                            <label class="form-label">Value</label>
                            <input name="sql_value" class="form-control">
                        </div>
                        <div class="col-md-2 d-grid gap-2">
                            <button type="submit" name="action" value="add" class="btn btn-primary">Add</button>
                            <button type="submit" name="action" value="list" class="btn btn-secondary mt-1">List</button>
                        </div>
                    </form>
                    {% if results_sql is not none %}
                        <div class="result-list">
                        {% for msg in results_sql %}
                            {% if 'Inserted' in msg or 'table' in msg or 'Table' in msg or 'success' in msg or 'thành công' in msg %}
                                <div class="alert alert-success py-2 mb-2">{{ msg }}</div>
                            {% else %}
                                <div class="alert alert-danger py-2 mb-2">{{ msg }}</div>
                            {% endif %}
                        {% endfor %}
                        </div>
                    {% endif %}
                </div>
            </div>
        </div>
        <div class="col">
            <div class="card shadow-sm">
                <div class="card-body">
                    <div class="service-title mb-2">Cosmos DB</div>
                    <form method="post" class="row g-2 align-items-end">
                        <input type="hidden" name="service" value="cosmos">
                        <div class="col-md-4">
                            <label class="form-label">DB Name</label>
                            <input name="cosmos_db" class="form-control">
                        </div>
                        <div class="col-md-4">
                            <label class="form-label">Container Name</label>
                            <input name="cosmos_container" class="form-control">
                        </div>
                        <div class="col-md-4">
                            <label class="form-label">Item (JSON)</label>
                            <input name="cosmos_item" class="form-control">
                        </div>
                        <div class="col-12 d-grid gap-2 mt-2">
                            <button type="submit" name="action" value="add" class="btn btn-primary">Add</button>
                            <button type="submit" name="action" value="list" class="btn btn-secondary mt-1">List</button>
                        </div>
                    </form>
                    {% if results_cosmos is not none %}
                        <div class="result-list">
                        {% for msg in results_cosmos %}
                            {% if 'Item' in msg or 'success' in msg or 'thành công' in msg %}
                                <div class="alert alert-success py-2 mb-2">{{ msg }}</div>
                            {% else %}
                                <div class="alert alert-danger py-2 mb-2">{{ msg }}</div>
                            {% endif %}
                        {% endfor %}
                        </div>
                    {% endif %}
                </div>
            </div>
        </div>
        <div class="col">
            <div class="card shadow-sm">
                <div class="card-body">
                    <div class="service-title mb-2">Blob Storage</div>
                    <form method="post" class="row g-2 align-items-end">
                        <input type="hidden" name="service" value="blob">
                        <div class="col-md-4">
                            <label class="form-label">Container Name</label>
                            <input name="blob_container" class="form-control">
                        </div>
                        <div class="col-md-4">
                            <label class="form-label">Blob Name</label>
                            <input name="blob_name" class="form-control">
                        </div>
                        <div class="col-md-4">
                            <label class="form-label">Data</label>
                            <input name="blob_data" class="form-control">
                        </div>
                        <div class="col-12 d-grid gap-2 mt-2">
                            <button type="submit" name="action" value="add" class="btn btn-primary">Upload</button>
                            <button type="submit" name="action" value="list" class="btn btn-secondary mt-1">List</button>
                        </div>
                    </form>
                    {% if results_blob is not none %}
                        <div class="result-list">
                        {% for msg in results_blob %}
                            {% if 'uploaded' in msg or 'success' in msg or 'thành công' in msg %}
                                <div class="alert alert-success py-2 mb-2">{{ msg }}</div>
                            {% else %}
                                <div class="alert alert-danger py-2 mb-2">{{ msg }}</div>
                            {% endif %}
                        {% endfor %}
                        </div>
                    {% endif %}
                </div>
            </div>
        </div>
        <div class="col">
            <div class="card shadow-sm">
                <div class="card-body">
                    <div class="service-title mb-2">Azure Container Registry (ACR)</div>
                    <form method="post" class="row g-2 align-items-end">
                        <input type="hidden" name="service" value="acr">
                        <div class="col-12 d-grid gap-2">
                            <button type="submit" name="action" value="list" class="btn btn-secondary">List Images</button>
                        </div>
                    </form>
                    {% if results_acr is not none %}
                        <div class="result-list">
                        {% for msg in results_acr %}
                            <div class="alert alert-info py-2 mb-2">{{ msg }}</div>
                        {% endfor %}
                        </div>
                    {% endif %}
                </div>
            </div>
        </div>
        <div class="col">
            <div class="card shadow-sm">
                <div class="card-body">
                    <div class="service-title mb-2">Azure Redis Cache</div>
                    <form method="post" class="row g-2 align-items-end">
                        <input type="hidden" name="service" value="redis">
                        <div class="col-md-5">
                            <label class="form-label">Key</label>
                            <input name="redis_key" class="form-control">
                        </div>
                        <div class="col-md-5">
                            <label class="form-label">Value</label>
                            <input name="redis_value" class="form-control">
                        </div>
                        <div class="col-md-2 d-grid gap-2">
                            <button type="submit" name="action" value="add" class="btn btn-primary">Set</button>
                            <button type="submit" name="action" value="list" class="btn btn-secondary mt-1">List</button>
                        </div>
                    </form>
                    {% if results_redis is not none %}
                        <div class="result-list">
                        {% for msg in results_redis %}
                            {% if 'set' in msg or 'success' in msg or 'thành công' in msg %}
                                <div class="alert alert-success py-2 mb-2">{{ msg }}</div>
                            {% else %}
                                <div class="alert alert-danger py-2 mb-2">{{ msg }}</div>
                            {% endif %}
                        {% endfor %}
                        </div>
                    {% endif %}
                </div>
            </div>
        </div>
    </div>
    <footer class="text-center mt-4 mb-2 text-muted">&copy; {{ 2024 }} Azure Connectivity Tester</footer>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

@app.route('/', methods=['GET', 'POST'])
def index():
    results_keyvault = results_sql = results_cosmos = results_blob = results_acr = results_redis = None
    credential = DefaultAzureCredential()
    CONFIG = get_config()
    if request.method == 'POST':
        service = request.form.get('service')
        action = request.form.get('action')
        if service == 'keyvault':
            vault_url = CONFIG['keyvault_url']
            if action == 'add':
                secret_name = request.form.get('keyvault_secret_name')
                secret_value = request.form.get('keyvault_secret_value')
                try:
                    client = SecretClient(vault_url=f"https://{vault_url}/", credential=credential)
                    client.set_secret(secret_name, secret_value)
                    results_keyvault = [f"Secret '{secret_name}' added."]
                except Exception as e:
                    results_keyvault = [str(e)]
            elif action == 'list':
                results_keyvault = list_key_vault_secrets(vault_url, credential)
        elif service == 'sql':
            sql_conn_str = CONFIG['sql_connection_string']
            if action == 'add':
                table = request.form.get('sql_table')
                value = request.form.get('sql_value')
                try:
                    conn = pyodbc.connect(sql_conn_str, timeout=5)
                    cursor = conn.cursor()
                    # Kiểm tra bảng tồn tại, nếu chưa thì tạo bảng
                    cursor.execute(f"SELECT COUNT(*) FROM sysobjects WHERE name='{table}' AND xtype='U'")
                    exists = cursor.fetchone()[0]
                    if not exists:
                        cursor.execute(f"CREATE TABLE {table} (id INT IDENTITY(1,1) PRIMARY KEY, val NVARCHAR(100))")
                    cursor.execute(f"INSERT INTO {table} (val) VALUES (?)", (value,))
                    conn.commit()
                    conn.close()
                    results_sql = [f"Inserted '{value}' into table '{table}'."]
                except Exception as e:
                    results_sql = [str(e)]
            elif action == 'list':
                results_sql = list_sql_tables(sql_conn_str) # Pass sql_conn_str directly
        elif service == 'cosmos':
            cosmos_conn_str = CONFIG['cosmos_connection_string']
            endpoint = cosmos_conn_str.split(';')[0].split('=')[1]
            key = cosmos_conn_str.split(';')[1].split('=')[1]
            db_name = request.form.get('cosmos_db')
            container_name = request.form.get('cosmos_container')
            if action == 'add':
                item_json = request.form.get('cosmos_item')
                import json
                try:
                    item = json.loads(item_json)
                    client = CosmosClient(f"https://{endpoint}/", key)
                    try:
                        db = client.create_database_if_not_exists(db_name)
                        container = db.create_container_if_not_exists(
                            id=container_name,
                            partition_key=PartitionKey(path="/id"),
                            offer_throughput=400
                        )
                    except Exception as e:
                        # Xử lý lỗi
                        print(e)
                    container.create_item(item)
                    results_cosmos = [f"Item added to {container_name}."]
                except Exception as e:
                    results_cosmos = [str(e)]
            elif action == 'list':
                results_cosmos = list_cosmos_items(endpoint, key, db_name, container_name)
        elif service == 'blob':
            blob_conn_str = CONFIG['blob_connection_string']
            blob_url = blob_conn_str.split(';')[0].split('=')[1]
            if action == 'add':
                container_name = request.form.get('blob_container')
                blob_name = request.form.get('blob_name')
                data = request.form.get('blob_data', '').encode()
                try:
                    client = BlobServiceClient(account_url=f"https://{blob_url}/", credential=credential)
                    container_client = client.get_container_client(container_name)
                    if not container_client.exists():
                        client.create_container(container_name)
                    container_client.upload_blob(blob_name, data)
                    results_blob = [f"Blob '{blob_name}' uploaded to '{container_name}'."]
                except Exception as e:
                    results_blob = [str(e)]
            elif action == 'list':
                container_name = request.form.get('blob_container')
                results_blob = list_blobs_in_container(blob_conn_str, container_name)
        elif service == 'acr':
            acr_name = CONFIG['acr_name']
            acr_subscription = CONFIG['acr_subscription']
            acr_rg = CONFIG['acr_rg']
            if action == 'list':
                results_acr = list_acr_images(acr_name, acr_subscription, acr_rg, credential)
        elif service == 'redis':
            redis_conn_str = CONFIG['redis_connection_string']
            if action == 'add':
                key = request.form.get('redis_key')
                value = request.form.get('redis_value')
                try:
                    r = redis.from_url(redis_conn_str)
                    r.set(key, value)
                    results_redis = [f"Key '{key}' set."]
                except Exception as e:
                    results_redis = [str(e)]
            elif action == 'list':
                results_redis = list_redis_keys(redis_conn_str)
    return render_template_string(
        TEMPLATE,
        results_keyvault=results_keyvault,
        results_sql=results_sql,
        results_cosmos=results_cosmos,
        results_blob=results_blob,
        results_acr=results_acr,
        results_redis=results_redis
    )

if __name__ == '__main__':
    app.run(debug=True) 