import os
import json
import time
import requests
import psycopg2
from kafka import KafkaConsumer

KAFKA_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka:9092')
PG_HOST = os.getenv('POSTGRES_HOST', 'postgres')
PG_DB = os.getenv('POSTGRES_DB', 'authz')
PG_USER = os.getenv('POSTGRES_USER', 'authz')
PG_PASS = os.getenv('POSTGRES_PASSWORD', 'authz123')
OPA_URL = os.getenv('OPA_URL', 'http://opa:8181')
PLATFORM = os.getenv('PLATFORM', 'mlops')

def get_db_connection():
    return psycopg2.connect(host=PG_HOST, database=PG_DB, user=PG_USER, password=PG_PASS)

def fetch_bundle():
    conn = get_db_connection()
    cur = conn.cursor()
    # cur.execute(f"SELECT authz.generate_opa_bundle('{PLATFORM}')")
    cur.execute(f"SET search_path TO authz, public; SELECT generate_opa_bundle('{PLATFORM}')")
    bundle = cur.fetchone()[0]
    cur.close()
    conn.close()
    return bundle

def push_to_opa(bundle):
    url = f"{OPA_URL}/v1/data/authz"
    headers = {"Content-Type": "application/json"}
    
    # Push RBAC
    requests.put(f"{OPA_URL}/v1/data/rbac", json=bundle.get('rbac', {}), headers=headers)
    
    # Push Users
    requests.put(f"{OPA_URL}/v1/data/users", json=bundle.get('users', {}), headers=headers)
    
    print(f"[SYNC] Pushed bundle to OPA")

def initial_sync():
    print("[SYNC] Performing initial sync...")
    bundle = fetch_bundle()
    push_to_opa(bundle)
    print("[SYNC] Initial sync complete")

def watch_changes():
    topics = [
        'authz.authz.mlops_orgs',
        'authz.authz.mlops_roles', 
        'authz.authz.mlops_perms',
        'authz.authz.mlops_users'
    ]
    
    print(f"[SYNC] Connecting to Kafka: {KAFKA_SERVERS}")
    
    consumer = KafkaConsumer(
        *topics,
        bootstrap_servers=KAFKA_SERVERS,
        auto_offset_reset='latest',
        enable_auto_commit=True,
        group_id='opa-sync-group',
        value_deserializer=lambda x: json.loads(x.decode('utf-8')) if x else None
    )
    
    print(f"[SYNC] Watching topics: {topics}")
    
    last_sync = time.time()
    debounce_seconds = 2
    pending_sync = False
    
    for message in consumer:
        print(f"[CDC] Change detected in {message.topic}")
        pending_sync = True
        
        # Debounce: wait for burst of changes to settle
        if time.time() - last_sync > debounce_seconds and pending_sync:
            bundle = fetch_bundle()
            push_to_opa(bundle)
            last_sync = time.time()
            pending_sync = False

if __name__ == "__main__":
    print("[SYNC] Starting sync worker...")
    
    # Wait for services
    time.sleep(10)
    
    # Initial sync
    initial_sync()
    
    # Watch for changes
    watch_changes()