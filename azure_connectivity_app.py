import streamlit as st
import os
import uuid
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from azure.storage.blob import BlobServiceClient
from azure.cosmos import CosmosClient, PartitionKey, exceptions as cosmos_exceptions
from azure.mgmt.containerregistry import ContainerRegistryManagementClient
from azure.mgmt.containerregistry.models import Registry
import pyodbc
import redis
import socket
import http.client

st.set_page_config(page_title="Azure Connectivity Tester", layout="wide")
st.title("🔗 Azure Connectivity Tester (Thao tác thực tế)")

# --- Helper functions ---
def show_result(step, ok, msg):
    if ok:
        st.success(f"{step}: {msg}")
    else:
        st.error(f"{step}: {msg}")

def test_key_vault_full(vault_url, credential):
    steps = []
    try:
        client = SecretClient(vault_url=f"https://{vault_url}/", credential=credential)
        secret_name = f"test-conn-{uuid.uuid4().hex[:8]}"
        secret_value = uuid.uuid4().hex
        # 1. Set secret
        client.set_secret(secret_name, secret_value)
        steps.append((True, f"Tạo secret '{secret_name}' thành công"))
        # 2. Get secret
        got = client.get_secret(secret_name)
        if got.value == secret_value:
            steps.append((True, f"Đọc secret thành công: {got.value}"))
        else:
            steps.append((False, "Giá trị secret không khớp!"))
        # 3. Delete secret
        poller = client.begin_delete_secret(secret_name)
        poller.wait()
        steps.append((True, "Xóa secret thành công"))
    except Exception as e:
        steps.append((False, str(e)))
    return steps

def test_azure_sql_full(server, database, username=None, password=None):
    steps = []
    table = "test_connectivity"
    try:
        if username and password:
            conn_str = (
                f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={server};DATABASE={database};"
                f"UID={username};PWD={password};Encrypt=yes;TrustServerCertificate=no;"
            )
        else:
            steps.append((False, "Vui lòng nhập username và password để sử dụng SQL Authentication."))
            return steps
        conn = pyodbc.connect(conn_str, timeout=5)
        cursor = conn.cursor()
        # 1. Create table
        try:
            cursor.execute(f"CREATE TABLE {table} (id INT PRIMARY KEY, val NVARCHAR(100))")
            conn.commit()
            steps.append((True, "Tạo bảng test thành công"))
        except Exception:
            steps.append((True, "Bảng test đã tồn tại"))
        # 2. Insert
        cursor.execute(f"INSERT INTO {table} (id, val) VALUES (?, ?)", (1, "hello"))
        conn.commit()
        steps.append((True, "Insert thành công"))
        # 3. Select
        cursor.execute(f"SELECT val FROM {table} WHERE id=1")
        row = cursor.fetchone()
        if row and row[0] == "hello":
            steps.append((True, f"Select thành công: {row[0]}"))
        else:
            steps.append((False, "Select thất bại!"))
        # 4. Delete row
        cursor.execute(f"DELETE FROM {table} WHERE id=1")
        conn.commit()
        steps.append((True, "Xóa dòng test thành công"))
        # 5. Drop table
        cursor.execute(f"DROP TABLE {table}")
        conn.commit()
        steps.append((True, "Xóa bảng test thành công"))
        conn.close()
    except Exception as e:
        steps.append((False, str(e)))
    return steps

def test_cosmosdb_full(endpoint, key):
    steps = []
    db_name = f"testdb{uuid.uuid4().hex[:6]}"
    container_name = f"testct{uuid.uuid4().hex[:6]}"
    try:
        client = CosmosClient(f"https://{endpoint}/", key)
        # 1. Create DB
        db = client.create_database(db_name)
        steps.append((True, f"Tạo database '{db_name}' thành công"))
        # 2. Create container
        container = db.create_container(id=container_name, partition_key=PartitionKey(path="/id"))
        steps.append((True, f"Tạo container '{container_name}' thành công"))
        # 3. Insert item
        item = {"id": "1", "val": "hello"}
        container.create_item(item)
        steps.append((True, "Insert item thành công"))
        # 4. Query item
        items = list(container.query_items(query="SELECT * FROM c WHERE c.id='1'", enable_cross_partition_query=True))
        if items and items[0]["val"] == "hello":
            steps.append((True, f"Query thành công: {items[0]['val']}"))
        else:
            steps.append((False, "Query thất bại!"))
        # 5. Delete item
        container.delete_item(item="1", partition_key="1")
        steps.append((True, "Xóa item thành công"))
        # 6. Delete container
        db.delete_container(container_name)
        steps.append((True, "Xóa container thành công"))
        # 7. Delete DB
        client.delete_database(db_name)
        steps.append((True, "Xóa database thành công"))
    except Exception as e:
        steps.append((False, str(e)))
    return steps

def test_blob_full(blob_url, credential):
    steps = []
    try:
        ip = socket.gethostbyname(blob_url)
        steps.append((True, f"DNS resolved {blob_url} to {ip}"))
    except Exception as e:
        steps.append((False, f"DNS resolution failed: {e}"))
    container_name = f"testct{uuid.uuid4().hex[:6]}"
    blob_name = "testfile.txt"
    data = b"hello azure blob"
    try:
        client = BlobServiceClient(account_url=f"https://{blob_url}/", credential=credential)
        # 1. Create container
        container = client.create_container(container_name)
        steps.append((True, f"Tạo container '{container_name}' thành công"))
        # 2. Upload blob
        container_client = client.get_container_client(container_name)
        container_client.upload_blob(blob_name, data)
        steps.append((True, "Upload blob thành công"))
        # 3. Download blob
        blob_data = container_client.download_blob(blob_name).readall()
        if blob_data == data:
            steps.append((True, "Download blob thành công"))
        else:
            steps.append((False, "Dữ liệu blob không khớp!"))
        # 4. Delete blob
        container_client.delete_blob(blob_name)
        steps.append((True, "Xóa blob thành công"))
        # 5. Delete container
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
        r = redis.from_url(redis_connection_string)
        # 1. Set
        r.set(key, value)
        steps.append((True, f"Set key '{key}' thành công"))
        # 2. Get
        val = r.get(key)
        if val and val.decode() == value:
            steps.append((True, "Get key thành công"))
        else:
            steps.append((False, "Giá trị key không khớp!"))
        # 3. Delete
        r.delete(key)
        steps.append((True, "Xóa key thành công"))
    except Exception as e:
        steps.append((False, str(e)))
    return steps

def test_acr_full(acr_name, subscription_id, resource_group, credential):
    steps = []
    try:
        acr_client = ContainerRegistryManagementClient(credential, subscription_id)
        registry: Registry = acr_client.registries.get(resource_group, acr_name)
        login_server = registry.login_server
        steps.append((True, f"Login server: {login_server}"))
        # Test quyền truy cập bằng cách gọi một API đơn giản, ví dụ: get properties
        try:
            props = acr_client.registries.get(resource_group, acr_name)
            steps.append((True, "Có thể truy cập registry properties"))
        except Exception as e:
            steps.append((False, f"Không thể truy cập registry properties: {e}"))
    except Exception as e:
        steps.append((False, str(e)))
    return steps

# --- UI ---
st.header("Key Vault")
if 'kv_step' not in st.session_state:
    st.session_state.kv_step = 0
if 'kv_results' not in st.session_state:
    st.session_state.kv_results = []
if 'kv_secret_name' not in st.session_state:
    st.session_state.kv_secret_name = ''
if 'kv_secret_value' not in st.session_state:
    st.session_state.kv_secret_value = ''

with st.form("keyvault_form"):
    keyvault_url = st.text_input("Key Vault URL (e.g. myvault.vault.azure.net)")
    submitted_kv = st.form_submit_button("Bắt đầu kiểm tra Key Vault")
    if submitted_kv:
        st.session_state.kv_step = 1
        st.session_state.kv_results = []
        st.session_state.kv_secret_name = f"test-conn-{uuid.uuid4().hex[:8]}"
        st.session_state.kv_secret_value = uuid.uuid4().hex

if st.session_state.kv_step > 0 and keyvault_url:
    credential = DefaultAzureCredential()
    client = SecretClient(vault_url=f"https://{keyvault_url}/", credential=credential)
    secret_name = st.session_state.kv_secret_name
    secret_value = st.session_state.kv_secret_value
    # Bước 1: Set secret
    if st.session_state.kv_step == 1:
        if st.button("Bước 1: Tạo secret"):
            try:
                client.set_secret(secret_name, secret_value)
                st.session_state.kv_results.append((True, f"Tạo secret '{secret_name}' thành công"))
                st.session_state.kv_step = 2
            except Exception as e:
                st.session_state.kv_results.append((False, str(e)))
                st.session_state.kv_step = 0
    # Bước 2: Get secret
    elif st.session_state.kv_step == 2:
        for ok, msg in st.session_state.kv_results:
            show_result("Bước trước", ok, msg)
        if st.button("Bước 2: Đọc secret"):
            try:
                got = client.get_secret(secret_name)
                if got.value == secret_value:
                    st.session_state.kv_results.append((True, f"Đọc secret thành công: {got.value}"))
                    st.session_state.kv_step = 3
                else:
                    st.session_state.kv_results.append((False, "Giá trị secret không khớp!"))
                    st.session_state.kv_step = 0
            except Exception as e:
                st.session_state.kv_results.append((False, str(e)))
                st.session_state.kv_step = 0
    # Bước 3: Delete secret
    elif st.session_state.kv_step == 3:
        for ok, msg in st.session_state.kv_results:
            show_result("Bước trước", ok, msg)
        if st.button("Bước 3: Xóa secret"):
            try:
                poller = client.begin_delete_secret(secret_name)
                poller.wait()
                st.session_state.kv_results.append((True, "Xóa secret thành công"))
                st.session_state.kv_step = 0
            except Exception as e:
                st.session_state.kv_results.append((False, str(e)))
                st.session_state.kv_step = 0
    # Hiển thị kết quả các bước đã thực hiện
    for i, (ok, msg) in enumerate(st.session_state.kv_results, 1):
        show_result(f"Bước {i}", ok, msg)

# Azure SQL Database
st.header("Azure SQL Database")
if 'sql_step' not in st.session_state:
    st.session_state.sql_step = 0
if 'sql_results' not in st.session_state:
    st.session_state.sql_results = []
if 'sql_conn' not in st.session_state:
    st.session_state.sql_conn = None
if 'sql_table' not in st.session_state:
    st.session_state.sql_table = f"test_connectivity_{uuid.uuid4().hex[:6]}"

with st.form("sql_form"):
    sql_server = st.text_input("SQL Server (e.g. myserver.database.windows.net)")
    sql_db = st.text_input("Database Name")
    sql_user = st.text_input("SQL Username")
    sql_pwd = st.text_input("SQL Password", type="password")
    submitted_sql = st.form_submit_button("Bắt đầu kiểm tra SQL")
    if submitted_sql:
        st.session_state.sql_step = 1
        st.session_state.sql_results = []
        st.session_state.sql_table = f"test_connectivity_{uuid.uuid4().hex[:6]}"
        try:
            conn_str = (
                f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={sql_server};DATABASE={sql_db};"
                f"UID={sql_user};PWD={sql_pwd};Encrypt=yes;TrustServerCertificate=no;"
            )
            st.session_state.sql_conn = pyodbc.connect(conn_str, timeout=5)
        except Exception as e:
            st.session_state.sql_results.append((False, f"Kết nối thất bại: {e}"))
            st.session_state.sql_step = 0

if st.session_state.sql_step > 0 and st.session_state.sql_conn:
    conn = st.session_state.sql_conn
    table = st.session_state.sql_table
    cursor = conn.cursor()
    # Bước 1: Create table
    if st.session_state.sql_step == 1:
        if st.button("Bước 1: Tạo bảng test"):
            try:
                cursor.execute(f"CREATE TABLE {table} (id INT PRIMARY KEY, val NVARCHAR(100))")
                conn.commit()
                st.session_state.sql_results.append((True, "Tạo bảng test thành công"))
            except Exception:
                st.session_state.sql_results.append((True, "Bảng test đã tồn tại"))
            st.session_state.sql_step = 2
    # Bước 2: Insert
    elif st.session_state.sql_step == 2:
        for ok, msg in st.session_state.sql_results:
            show_result("Bước trước", ok, msg)
        if st.button("Bước 2: Insert"):
            try:
                cursor.execute(f"INSERT INTO {table} (id, val) VALUES (?, ?)", (1, "hello"))
                conn.commit()
                st.session_state.sql_results.append((True, "Insert thành công"))
                st.session_state.sql_step = 3
            except Exception as e:
                st.session_state.sql_results.append((False, str(e)))
                st.session_state.sql_step = 0
    # Bước 3: Select
    elif st.session_state.sql_step == 3:
        for ok, msg in st.session_state.sql_results:
            show_result("Bước trước", ok, msg)
        if st.button("Bước 3: Select"):
            try:
                cursor.execute(f"SELECT val FROM {table} WHERE id=1")
                row = cursor.fetchone()
                if row and row[0] == "hello":
                    st.session_state.sql_results.append((True, f"Select thành công: {row[0]}"))
                    st.session_state.sql_step = 4
                else:
                    st.session_state.sql_results.append((False, "Select thất bại!"))
                    st.session_state.sql_step = 0
            except Exception as e:
                st.session_state.sql_results.append((False, str(e)))
                st.session_state.sql_step = 0
    # Bước 4: Delete row
    elif st.session_state.sql_step == 4:
        for ok, msg in st.session_state.sql_results:
            show_result("Bước trước", ok, msg)
        if st.button("Bước 4: Xóa dòng test"):
            try:
                cursor.execute(f"DELETE FROM {table} WHERE id=1")
                conn.commit()
                st.session_state.sql_results.append((True, "Xóa dòng test thành công"))
                st.session_state.sql_step = 5
            except Exception as e:
                st.session_state.sql_results.append((False, str(e)))
                st.session_state.sql_step = 0
    # Bước 5: Drop table
    elif st.session_state.sql_step == 5:
        for ok, msg in st.session_state.sql_results:
            show_result("Bước trước", ok, msg)
        if st.button("Bước 5: Xóa bảng test"):
            try:
                cursor.execute(f"DROP TABLE {table}")
                conn.commit()
                st.session_state.sql_results.append((True, "Xóa bảng test thành công"))
            except Exception as e:
                st.session_state.sql_results.append((False, str(e)))
            st.session_state.sql_conn.close()
            st.session_state.sql_step = 0
    for i, (ok, msg) in enumerate(st.session_state.sql_results, 1):
        show_result(f"Bước {i}", ok, msg)

# Cosmos DB
st.header("Cosmos DB")
if 'cosmos_step' not in st.session_state:
    st.session_state.cosmos_step = 0
if 'cosmos_results' not in st.session_state:
    st.session_state.cosmos_results = []
if 'cosmos_db_name' not in st.session_state:
    st.session_state.cosmos_db_name = ''
if 'cosmos_ct_name' not in st.session_state:
    st.session_state.cosmos_ct_name = ''
if 'cosmos_client' not in st.session_state:
    st.session_state.cosmos_client = None
if 'cosmos_db' not in st.session_state:
    st.session_state.cosmos_db = None
if 'cosmos_ct' not in st.session_state:
    st.session_state.cosmos_ct = None

with st.form("cosmos_form"):
    cosmos_endpoint = st.text_input("Cosmos Endpoint (e.g. mycosmos.documents.azure.com)")
    cosmos_key = st.text_input("Cosmos Key", type="password")
    submitted_cosmos = st.form_submit_button("Bắt đầu kiểm tra Cosmos DB")
    if submitted_cosmos:
        st.session_state.cosmos_step = 1
        st.session_state.cosmos_results = []
        st.session_state.cosmos_db_name = f"testdb{uuid.uuid4().hex[:6]}"
        st.session_state.cosmos_ct_name = f"testct{uuid.uuid4().hex[:6]}"
        try:
            st.session_state.cosmos_client = CosmosClient(f"https://{cosmos_endpoint}/", cosmos_key)
        except Exception as e:
            st.session_state.cosmos_results.append((False, f"Kết nối thất bại: {e}"))
            st.session_state.cosmos_step = 0

if st.session_state.cosmos_step > 0 and st.session_state.cosmos_client:
    client = st.session_state.cosmos_client
    db_name = st.session_state.cosmos_db_name
    ct_name = st.session_state.cosmos_ct_name
    # Bước 1: Create DB
    if st.session_state.cosmos_step == 1:
        if st.button("Bước 1: Tạo database"):
            try:
                db = client.create_database(db_name)
                st.session_state.cosmos_db = db
                st.session_state.cosmos_results.append((True, f"Tạo database '{db_name}' thành công"))
                st.session_state.cosmos_step = 2
            except Exception as e:
                st.session_state.cosmos_results.append((False, str(e)))
                st.session_state.cosmos_step = 0
    # Bước 2: Create container
    elif st.session_state.cosmos_step == 2:
        for ok, msg in st.session_state.cosmos_results:
            show_result("Bước trước", ok, msg)
        if st.button("Bước 2: Tạo container"):
            try:
                db = client.get_database_client(db_name)
                ct = db.create_container(id=ct_name, partition_key=PartitionKey(path="/id"))
                st.session_state.cosmos_ct = ct
                st.session_state.cosmos_results.append((True, f"Tạo container '{ct_name}' thành công"))
                st.session_state.cosmos_step = 3
            except Exception as e:
                st.session_state.cosmos_results.append((False, str(e)))
                st.session_state.cosmos_step = 0
    # Bước 3: Insert item
    elif st.session_state.cosmos_step == 3:
        for ok, msg in st.session_state.cosmos_results:
            show_result("Bước trước", ok, msg)
        if st.button("Bước 3: Insert item"):
            try:
                ct = client.get_database_client(db_name).get_container_client(ct_name)
                item = {"id": "1", "val": "hello"}
                ct.create_item(item)
                st.session_state.cosmos_results.append((True, "Insert item thành công"))
                st.session_state.cosmos_step = 4
            except Exception as e:
                st.session_state.cosmos_results.append((False, str(e)))
                st.session_state.cosmos_step = 0
    # Bước 4: Query item
    elif st.session_state.cosmos_step == 4:
        for ok, msg in st.session_state.cosmos_results:
            show_result("Bước trước", ok, msg)
        if st.button("Bước 4: Query item"):
            try:
                ct = client.get_database_client(db_name).get_container_client(ct_name)
                items = list(ct.query_items(query="SELECT * FROM c WHERE c.id='1'", enable_cross_partition_query=True))
                if items and items[0]["val"] == "hello":
                    st.session_state.cosmos_results.append((True, f"Query thành công: {items[0]['val']}"))
                    st.session_state.cosmos_step = 5
                else:
                    st.session_state.cosmos_results.append((False, "Query thất bại!"))
                    st.session_state.cosmos_step = 0
            except Exception as e:
                st.session_state.cosmos_results.append((False, str(e)))
                st.session_state.cosmos_step = 0
    # Bước 5: Delete item
    elif st.session_state.cosmos_step == 5:
        for ok, msg in st.session_state.cosmos_results:
            show_result("Bước trước", ok, msg)
        if st.button("Bước 5: Xóa item"):
            try:
                ct = client.get_database_client(db_name).get_container_client(ct_name)
                ct.delete_item(item="1", partition_key="1")
                st.session_state.cosmos_results.append((True, "Xóa item thành công"))
                st.session_state.cosmos_step = 6
            except Exception as e:
                st.session_state.cosmos_results.append((False, str(e)))
                st.session_state.cosmos_step = 0
    # Bước 6: Delete container
    elif st.session_state.cosmos_step == 6:
        for ok, msg in st.session_state.cosmos_results:
            show_result("Bước trước", ok, msg)
        if st.button("Bước 6: Xóa container"):
            try:
                db = client.get_database_client(db_name)
                db.delete_container(ct_name)
                st.session_state.cosmos_results.append((True, "Xóa container thành công"))
                st.session_state.cosmos_step = 7
            except Exception as e:
                st.session_state.cosmos_results.append((False, str(e)))
                st.session_state.cosmos_step = 0
    # Bước 7: Delete DB
    elif st.session_state.cosmos_step == 7:
        for ok, msg in st.session_state.cosmos_results:
            show_result("Bước trước", ok, msg)
        if st.button("Bước 7: Xóa database"):
            try:
                client.delete_database(db_name)
                st.session_state.cosmos_results.append((True, "Xóa database thành công"))
            except Exception as e:
                st.session_state.cosmos_results.append((False, str(e)))
            st.session_state.cosmos_step = 0
    for i, (ok, msg) in enumerate(st.session_state.cosmos_results, 1):
        show_result(f"Bước {i}", ok, msg)

# Blob Storage
st.header("Blob Storage")
if 'blob_step' not in st.session_state:
    st.session_state.blob_step = 0
if 'blob_results' not in st.session_state:
    st.session_state.blob_results = []
if 'blob_container' not in st.session_state:
    st.session_state.blob_container = ''
if 'blob_name' not in st.session_state:
    st.session_state.blob_name = 'testfile.txt'
if 'blob_data' not in st.session_state:
    st.session_state.blob_data = b"hello azure blob"
if 'blob_client' not in st.session_state:
    st.session_state.blob_client = None

with st.form("blob_form"):
    blob_url = st.text_input("Blob Storage URL (e.g. mystorage.blob.core.windows.net)")
    submitted_blob = st.form_submit_button("Bắt đầu kiểm tra Blob Storage")
    if submitted_blob:
        st.session_state.blob_step = 1
        st.session_state.blob_results = []
        st.session_state.blob_container = f"testct{uuid.uuid4().hex[:6]}"
        try:
            credential = DefaultAzureCredential()
            st.session_state.blob_client = BlobServiceClient(account_url=f"https://{blob_url}/", credential=credential)
        except Exception as e:
            st.session_state.blob_results.append((False, f"Kết nối thất bại: {e}"))
            st.session_state.blob_step = 0

if st.session_state.blob_step > 0 and st.session_state.blob_client:
    client = st.session_state.blob_client
    container_name = st.session_state.blob_container
    blob_name = st.session_state.blob_name
    data = st.session_state.blob_data
    # Bước 1: Create container
    if st.session_state.blob_step == 1:
        if st.button("Bước 1: Tạo container"):
            try:
                client.create_container(container_name)
                st.session_state.blob_results.append((True, f"Tạo container '{container_name}' thành công"))
                st.session_state.blob_step = 2
            except Exception as e:
                st.session_state.blob_results.append((False, str(e)))
                st.session_state.blob_step = 0
    # Bước 2: Upload blob
    elif st.session_state.blob_step == 2:
        for ok, msg in st.session_state.blob_results:
            show_result("Bước trước", ok, msg)
        if st.button("Bước 2: Upload blob"):
            try:
                container_client = client.get_container_client(container_name)
                container_client.upload_blob(blob_name, data)
                st.session_state.blob_results.append((True, "Upload blob thành công"))
                st.session_state.blob_step = 3
            except Exception as e:
                st.session_state.blob_results.append((False, str(e)))
                st.session_state.blob_step = 0
    # Bước 3: Download blob
    elif st.session_state.blob_step == 3:
        for ok, msg in st.session_state.blob_results:
            show_result("Bước trước", ok, msg)
        if st.button("Bước 3: Download blob"):
            try:
                container_client = client.get_container_client(container_name)
                blob_data = container_client.download_blob(blob_name).readall()
                if blob_data == data:
                    st.session_state.blob_results.append((True, "Download blob thành công"))
                    st.session_state.blob_step = 4
                else:
                    st.session_state.blob_results.append((False, "Dữ liệu blob không khớp!"))
                    st.session_state.blob_step = 0
            except Exception as e:
                st.session_state.blob_results.append((False, str(e)))
                st.session_state.blob_step = 0
    # Bước 4: Delete blob
    elif st.session_state.blob_step == 4:
        for ok, msg in st.session_state.blob_results:
            show_result("Bước trước", ok, msg)
        if st.button("Bước 4: Xóa blob"):
            try:
                container_client = client.get_container_client(container_name)
                container_client.delete_blob(blob_name)
                st.session_state.blob_results.append((True, "Xóa blob thành công"))
                st.session_state.blob_step = 5
            except Exception as e:
                st.session_state.blob_results.append((False, str(e)))
                st.session_state.blob_step = 0
    # Bước 5: Delete container
    elif st.session_state.blob_step == 5:
        for ok, msg in st.session_state.blob_results:
            show_result("Bước trước", ok, msg)
        if st.button("Bước 5: Xóa container"):
            try:
                client.delete_container(container_name)
                st.session_state.blob_results.append((True, "Xóa container thành công"))
            except Exception as e:
                st.session_state.blob_results.append((False, str(e)))
            st.session_state.blob_step = 0
    for i, (ok, msg) in enumerate(st.session_state.blob_results, 1):
        show_result(f"Bước {i}", ok, msg)

# Azure Container Registry (ACR)
st.header("Azure Container Registry (ACR)")
if 'acr_step' not in st.session_state:
    st.session_state.acr_step = 0
if 'acr_results' not in st.session_state:
    st.session_state.acr_results = []
if 'acr_client' not in st.session_state:
    st.session_state.acr_client = None
if 'acr_registry' not in st.session_state:
    st.session_state.acr_registry = None

with st.form("acr_form"):
    acr_name = st.text_input("ACR Name (e.g. myregistry)")
    acr_subscription = st.text_input("Subscription ID")
    acr_rg = st.text_input("Resource Group")
    submitted_acr = st.form_submit_button("Bắt đầu kiểm tra ACR")
    if submitted_acr:
        st.session_state.acr_step = 1
        st.session_state.acr_results = []
        try:
            credential = DefaultAzureCredential()
            acr_client = ContainerRegistryManagementClient(credential, acr_subscription)
            st.session_state.acr_client = acr_client
        except Exception as e:
            st.session_state.acr_results.append((False, f"Kết nối thất bại: {e}"))
            st.session_state.acr_step = 0

if st.session_state.acr_step > 0 and st.session_state.acr_client:
    acr_client = st.session_state.acr_client
    # Bước 1: Get registry
    if st.session_state.acr_step == 1:
        if st.button("Bước 1: Lấy thông tin registry"):
            try:
                registry = acr_client.registries.get(acr_rg, acr_name)
                st.session_state.acr_registry = registry
                st.session_state.acr_results.append((True, f"Login server: {registry.login_server}"))
                st.session_state.acr_step = 2
            except Exception as e:
                st.session_state.acr_results.append((False, str(e)))
                st.session_state.acr_step = 0
    # Bước 2: Get properties
    elif st.session_state.acr_step == 2:
        for ok, msg in st.session_state.acr_results:
            show_result("Bước trước", ok, msg)
        if st.button("Bước 2: Kiểm tra quyền truy cập properties"):
            try:
                props = acr_client.registries.get(acr_rg, acr_name)
                st.session_state.acr_results.append((True, "Có thể truy cập registry properties"))
            except Exception as e:
                st.session_state.acr_results.append((False, f"Không thể truy cập registry properties: {e}"))
            st.session_state.acr_step = 0
    for i, (ok, msg) in enumerate(st.session_state.acr_results, 1):
        show_result(f"Bước {i}", ok, msg)

# Azure Redis Cache
st.header("Azure Redis Cache")
if 'redis_step' not in st.session_state:
    st.session_state.redis_step = 0
if 'redis_results' not in st.session_state:
    st.session_state.redis_results = []
if 'redis_key' not in st.session_state:
    st.session_state.redis_key = ''
if 'redis_value' not in st.session_state:
    st.session_state.redis_value = ''
if 'redis_client' not in st.session_state:
    st.session_state.redis_client = None

with st.form("redis_form"):
    redis_conn = st.text_input("Redis Connection String (e.g. rediss://...)")
    submitted_redis = st.form_submit_button("Bắt đầu kiểm tra Redis")
    if submitted_redis:
        st.session_state.redis_step = 1
        st.session_state.redis_results = []
        st.session_state.redis_key = f"testkey:{uuid.uuid4().hex[:6]}"
        st.session_state.redis_value = uuid.uuid4().hex
        try:
            st.session_state.redis_client = redis.from_url(redis_conn)
        except Exception as e:
            st.session_state.redis_results.append((False, f"Kết nối thất bại: {e}"))
            st.session_state.redis_step = 0

if st.session_state.redis_step > 0 and st.session_state.redis_client:
    r = st.session_state.redis_client
    key = st.session_state.redis_key
    value = st.session_state.redis_value
    # Bước 1: Set
    if st.session_state.redis_step == 1:
        if st.button("Bước 1: Set key"):
            try:
                r.set(key, value)
                st.session_state.redis_results.append((True, f"Set key '{key}' thành công"))
                st.session_state.redis_step = 2
            except Exception as e:
                st.session_state.redis_results.append((False, str(e)))
                st.session_state.redis_step = 0
    # Bước 2: Get
    elif st.session_state.redis_step == 2:
        for ok, msg in st.session_state.redis_results:
            show_result("Bước trước", ok, msg)
        if st.button("Bước 2: Get key"):
            try:
                val = r.get(key)
                if val and val.decode() == value:
                    st.session_state.redis_results.append((True, "Get key thành công"))
                    st.session_state.redis_step = 3
                else:
                    st.session_state.redis_results.append((False, "Giá trị key không khớp!"))
                    st.session_state.redis_step = 0
            except Exception as e:
                st.session_state.redis_results.append((False, str(e)))
                st.session_state.redis_step = 0
    # Bước 3: Delete
    elif st.session_state.redis_step == 3:
        for ok, msg in st.session_state.redis_results:
            show_result("Bước trước", ok, msg)
        if st.button("Bước 3: Xóa key"):
            try:
                r.delete(key)
                st.session_state.redis_results.append((True, "Xóa key thành công"))
            except Exception as e:
                st.session_state.redis_results.append((False, str(e)))
            st.session_state.redis_step = 0
    for i, (ok, msg) in enumerate(st.session_state.redis_results, 1):
        show_result(f"Bước {i}", ok, msg) 