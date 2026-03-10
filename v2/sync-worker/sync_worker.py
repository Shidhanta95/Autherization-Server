"""
Sync Worker - Synchronizes PostgreSQL RBAC data to OPA via CDC (Debezium/Kafka)

Features:
- Initial sync on startup (data + policy)
- CDC-based incremental sync via Kafka
- Policy file watching for hot-reload
- Debounced updates to reduce OPA load
"""

import os
import json
import time
import re
import threading
import requests
import psycopg2
from pathlib import Path
from kafka import KafkaConsumer
from kafka.admin import KafkaAdminClient
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ============================================================
# CONFIGURATION
# ============================================================
KAFKA_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
PG_HOST = os.getenv("POSTGRES_HOST", "postgres")
PG_DB = os.getenv("POSTGRES_DB", "authz")
PG_USER = os.getenv("POSTGRES_USER", "authz")
PG_PASS = os.getenv("POSTGRES_PASSWORD", "authz123")
OPA_URL = os.getenv("OPA_URL", "http://opa:8181")
TOPIC_PREFIX = os.getenv("TOPIC_PREFIX", "authz.authz")
POLICY_FILE = os.getenv("POLICY_FILE", "/policy/policy.rego")


# ============================================================
# DATABASE FUNCTIONS
# ============================================================
def get_db_connection():
    """Create a new database connection"""
    return psycopg2.connect(
        host=PG_HOST, database=PG_DB, user=PG_USER, password=PG_PASS
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
    cur.execute(
        f"SET search_path TO authz, public; SELECT generate_opa_bundle('{platform}')"
    )
    bundle = cur.fetchone()[0]
    cur.close()
    conn.close()
    return bundle


def fetch_all_bundles():
    """Fetch bundles for all platforms"""
    platforms = get_all_platforms()
    all_data = {
        "rbac": {},
        "users": {
            "user_roles": {},
            "user_tenant": {},
            "user_ids": {},
            "org_admin_flag": {},
        },
        "platforms": platforms,
    }

    for platform in platforms:
        try:
            bundle = fetch_bundle(platform)
            if bundle:
                # Merge RBAC data under platform key
                if bundle.get("rbac"):
                    all_data["rbac"][platform] = bundle["rbac"]

                # Merge user data
                if bundle.get("users"):
                    for key in [
                        "user_roles",
                        "user_tenant",
                        "user_ids",
                        "org_admin_flag",
                    ]:
                        if bundle["users"].get(key):
                            all_data["users"][key].update(bundle["users"][key])
        except Exception as e:
            print(f"[SYNC] Error fetching bundle for {platform}: {e}")

    return all_data


# ============================================================
# OPA SYNC FUNCTIONS
# ============================================================
def push_data_to_opa(bundle):
    """Push complete data bundle to OPA"""
    headers = {"Content-Type": "application/json"}

    try:
        # Push RBAC (per platform)
        resp = requests.put(
            f"{OPA_URL}/v1/data/rbac", json=bundle.get("rbac", {}), headers=headers
        )
        print(f"[SYNC] Pushed RBAC: {resp.status_code}")

        # Push Users
        resp = requests.put(
            f"{OPA_URL}/v1/data/users", json=bundle.get("users", {}), headers=headers
        )
        print(f"[SYNC] Pushed Users: {resp.status_code}")

        # Push platforms list
        resp = requests.put(
            f"{OPA_URL}/v1/data/platforms",
            json=bundle.get("platforms", []),
            headers=headers,
        )
        print(f"[SYNC] Pushed Platforms: {resp.status_code}")

        print(
            f"[SYNC] Data bundle pushed successfully at {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )

    except Exception as e:
        print(f"[SYNC] Error pushing data to OPA: {e}")


def push_policy_to_opa():
    """Push policy.rego to OPA via REST API"""
    try:
        policy_path = Path(POLICY_FILE)
        if not policy_path.exists():
            print(f"[POLICY] Policy file not found: {POLICY_FILE}")
            return False

        policy_content = policy_path.read_text()

        resp = requests.put(
            f"{OPA_URL}/v1/policies/authz",
            data=policy_content,
            headers={"Content-Type": "text/plain"},
        )

        if resp.status_code == 200:
            print(
                f"[POLICY] Policy pushed successfully at {time.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            return True
        else:
            print(f"[POLICY] Failed to push policy: {resp.status_code} - {resp.text}")
            return False

    except Exception as e:
        print(f"[POLICY] Error pushing policy to OPA: {e}")
        return False


# ============================================================
# POLICY FILE WATCHER
# ============================================================
class PolicyFileHandler(FileSystemEventHandler):
    """Watches for changes to policy.rego and pushes updates to OPA"""

    def __init__(self):
        self.last_push = 0
        self.debounce_seconds = 2

    def on_modified(self, event):
        if event.is_directory:
            return

        # Check if it's our policy file
        if event.src_path.endswith("policy.rego"):
            current_time = time.time()

            # Debounce rapid changes
            if current_time - self.last_push > self.debounce_seconds:
                print(f"[POLICY] Detected change in {event.src_path}")
                time.sleep(0.5)  # Small delay to ensure file write is complete
                push_policy_to_opa()
                self.last_push = current_time


def start_policy_watcher():
    """Start watching the policy directory for changes"""
    policy_path = Path(POLICY_FILE)
    policy_dir = policy_path.parent

    if not policy_dir.exists():
        print(f"[POLICY] Policy directory not found: {policy_dir}")
        return None

    event_handler = PolicyFileHandler()
    observer = Observer()
    observer.schedule(event_handler, str(policy_dir), recursive=False)
    observer.start()

    print(f"[POLICY] Watching for changes in: {policy_dir}")
    return observer


# ============================================================
# KAFKA FUNCTIONS
# ============================================================
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
    match = re.match(r"authz\.authz\.([^_]+)_", topic)
    if match:
        return match.group(1)
    return None


# ============================================================
# SYNC OPERATIONS
# ============================================================
def initial_sync():
    """Perform initial sync on startup"""
    print("[SYNC] Performing initial sync...")
    max_retries = 5

    # Push policy first
    for attempt in range(max_retries):
        if push_policy_to_opa():
            break
        print(f"[POLICY] Retry {attempt + 1}/{max_retries}...")
        time.sleep(5)

    # Then push data
    for attempt in range(max_retries):
        try:
            bundle = fetch_all_bundles()
            push_data_to_opa(bundle)
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
        auto_offset_reset="latest",
        enable_auto_commit=True,
        group_id="opa-sync-group",
        value_deserializer=lambda x: json.loads(x.decode("utf-8")) if x else None,
        consumer_timeout_ms=1000,  # Allow periodic topic refresh
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
                push_data_to_opa(bundle)
                last_sync = current_time
                pending_sync = False
                affected_platforms.clear()

            # Periodic topic refresh (for new platforms)
            if current_time - last_topic_refresh > topic_refresh_seconds:
                new_topics = discover_topics()
                if set(new_topics) != set(topics):
                    print(
                        f"[SYNC] New topics discovered: {set(new_topics) - set(topics)}"
                    )
                    consumer.subscribe(new_topics)
                    topics = new_topics
                last_topic_refresh = current_time

        except Exception as e:
            print(f"[SYNC] Error in watch loop: {e}")
            time.sleep(5)


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    print("[SYNC] Starting sync worker...")
    print(f"[SYNC] Kafka: {KAFKA_SERVERS}")
    print(f"[SYNC] PostgreSQL: {PG_HOST}/{PG_DB}")
    print(f"[SYNC] OPA: {OPA_URL}")
    print(f"[SYNC] Policy file: {POLICY_FILE}")

    # Wait for services to be ready
    time.sleep(15)

    # Start policy file watcher in background
    policy_observer = start_policy_watcher()

    # Initial sync (policy + data)
    initial_sync()

    # Watch for data changes via Kafka
    try:
        watch_changes()
    except KeyboardInterrupt:
        print("[SYNC] Shutting down...")
        if policy_observer:
            policy_observer.stop()
            policy_observer.join()
