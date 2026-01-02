import os
import json
import time
import re
import requests
import psycopg2
from kafka import KafkaConsumer
from kafka.admin import KafkaAdminClient

KAFKA_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka:9092')
PG_HOST = os.getenv('POSTGRES_HOST', 'postgres')
PG_DB = os.getenv('POSTGRES_DB', 'authz')
PG_USER = os.getenv('POSTGRES_USER', 'authz')
PG_PASS = os.getenv('POSTGRES_PASSWORD', 'authz123')
OPA_URL = os.getenv('OPA_URL', 'http://opa:8181')
TOPIC_PREFIX = os.getenv('TOPIC_PREFIX', 'authz.authz')

def get_db_connection():
    return psycopg2.connect(
        host=PG_HOST, 
        database=PG_DB, 
        user=PG_USER, 
        password=PG_PASS
    )

def get_all_platforms():
    """Fetch all registered platforms from database"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SET search_path TO authz, public; SELECT prefix FROM platforms")
    platforms = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return platforms

def fetch_bundle(platform):
    """Fetch OPA bundle for a specific platform"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(f"SET search_path TO authz, public; SELECT generate_opa_bundle('{platform}')")
    bundle = cur.fetchone()[0]
    cur.close()
    conn.close()
    return bundle

def fetch_all_bundles():
    """Fetch bundles for all platforms"""
    platforms = get_all_platforms()
    all_data = {
        'rbac': {},
        'users': {
            'user_roles': {},
            'user_tenant': {},
            'user_ids': {},
            'org_admin_flag': {}
        },
        'platforms': platforms
    }
    
    for platform in platforms:
        try:
            bundle = fetch_bundle(platform)
            if bundle:
                # Merge RBAC data under platform key
                if bundle.get('rbac'):
                    all_data['rbac'][platform] = bundle['rbac']
                
                # Merge user data
                if bundle.get('users'):
                    for key in ['user_roles', 'user_tenant', 'user_ids', 'org_admin_flag']:
                        if bundle['users'].get(key):
                            all_data['users'][key].update(bundle['users'][key])
        except Exception as e:
            print(f"[SYNC] Error fetching bundle for {platform}: {e}")
    
    return all_data

def push_to_opa(bundle):
    """Push complete bundle to OPA"""
    headers = {"Content-Type": "application/json"}
    
    try:
        # Push RBAC (per platform)
        resp = requests.put(
            f"{OPA_URL}/v1/data/rbac", 
            json=bundle.get('rbac', {}), 
            headers=headers
        )
        print(f"[SYNC] Pushed RBAC: {resp.status_code}")
        
        # Push Users
        resp = requests.put(
            f"{OPA_URL}/v1/data/users", 
            json=bundle.get('users', {}), 
            headers=headers
        )
        print(f"[SYNC] Pushed Users: {resp.status_code}")
        
        # Push platforms list
        resp = requests.put(
            f"{OPA_URL}/v1/data/platforms", 
            json=bundle.get('platforms', []), 
            headers=headers
        )
        print(f"[SYNC] Pushed Platforms: {resp.status_code}")
        
        print(f"[SYNC] Bundle pushed successfully at {time.strftime('%Y-%m-%d %H:%M:%S')}")
        
    except Exception as e:
        print(f"[SYNC] Error pushing to OPA: {e}")

def discover_topics():
    """Discover all authz-related Kafka topics"""
    try:
        admin = KafkaAdminClient(bootstrap_servers=KAFKA_SERVERS)
        all_topics = admin.list_topics()
        
        # Filter topics that match our prefix pattern
        authz_topics = [t for t in all_topics if t.startswith(TOPIC_PREFIX)]
        
        admin.close()
        return authz_topics
    except Exception as e:
        print(f"[SYNC] Error discovering topics: {e}")
        return []

def get_platform_from_topic(topic):
    """Extract platform name from topic"""
    # Topic format: authz.authz.{platform}_{table}
    # e.g., authz.authz.mlops_orgs -> mlops
    match = re.match(r'authz\.authz\.([^_]+)_', topic)
    if match:
        return match.group(1)
    return None

def initial_sync():
    """Perform initial sync on startup"""
    print("[SYNC] Performing initial sync...")
    max_retries = 5
    
    for attempt in range(max_retries):
        try:
            bundle = fetch_all_bundles()
            push_to_opa(bundle)
            print("[SYNC] Initial sync complete")
            return
        except Exception as e:
            print(f"[SYNC] Initial sync attempt {attempt + 1} failed: {e}")
            time.sleep(5)
    
    print("[SYNC] Initial sync failed after all retries")

def watch_changes():
    """Watch Kafka topics for changes and sync to OPA"""
    print(f"[SYNC] Discovering topics with prefix: {TOPIC_PREFIX}")
    
    # Wait for topics to be created
    topics = []
    while not topics:
        topics = discover_topics()
        if not topics:
            print("[SYNC] No topics found, waiting...")
            time.sleep(5)
    
    print(f"[SYNC] Watching topics: {topics}")
    
    consumer = KafkaConsumer(
        *topics,
        bootstrap_servers=KAFKA_SERVERS,
        auto_offset_reset='latest',
        enable_auto_commit=True,
        group_id='opa-sync-group',
        value_deserializer=lambda x: json.loads(x.decode('utf-8')) if x else None,
        consumer_timeout_ms=1000  # Allow periodic topic refresh
    )
    
    last_sync = time.time()
    last_topic_refresh = time.time()
    debounce_seconds = 2
    topic_refresh_seconds = 60  # Check for new topics every minute
    pending_sync = False
    affected_platforms = set()
    
    while True:
        try:
            # Poll for messages
            messages = consumer.poll(timeout_ms=1000)
            
            for topic_partition, records in messages.items():
                for message in records:
                    topic = message.topic
                    platform = get_platform_from_topic(topic)
                    
                    print(f"[CDC] Change detected: {topic} (platform: {platform})")
                    pending_sync = True
                    if platform:
                        affected_platforms.add(platform)
            
            # Debounced sync
            current_time = time.time()
            if pending_sync and (current_time - last_sync > debounce_seconds):
                print(f"[SYNC] Syncing changes for platforms: {affected_platforms}")
                bundle = fetch_all_bundles()
                push_to_opa(bundle)
                last_sync = current_time
                pending_sync = False
                affected_platforms.clear()
            
            # Periodic topic refresh (for new platforms)
            if current_time - last_topic_refresh > topic_refresh_seconds:
                new_topics = discover_topics()
                if set(new_topics) != set(topics):
                    print(f"[SYNC] New topics discovered: {set(new_topics) - set(topics)}")
                    consumer.subscribe(new_topics)
                    topics = new_topics
                last_topic_refresh = current_time
                
        except Exception as e:
            print(f"[SYNC] Error in watch loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    print("[SYNC] Starting sync worker...")
    print(f"[SYNC] Kafka: {KAFKA_SERVERS}")
    print(f"[SYNC] PostgreSQL: {PG_HOST}/{PG_DB}")
    print(f"[SYNC] OPA: {OPA_URL}")
    
    # Wait for services to be ready
    time.sleep(15)
    
    # Initial sync
    initial_sync()
    
    # Watch for changes
    watch_changes()