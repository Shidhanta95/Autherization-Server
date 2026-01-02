#!/bin/bash

CONNECT_URL=${CONNECT_URL:-http://debezium:8083}
CONNECTOR_NAME="authz-connector"

echo "Waiting for Kafka Connect to be ready..."
until curl -s "$CONNECT_URL/connectors" > /dev/null 2>&1; do
    sleep 5
done

echo "Deleting existing connector if present..."
curl -X DELETE "$CONNECT_URL/connectors/$CONNECTOR_NAME" 2>/dev/null

echo "Registering new connector..."
curl -X POST "$CONNECT_URL/connectors" \
  -H "Content-Type: application/json" \
  -d '{
  "name": "authz-connector",
  "config": {
    "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
    "database.hostname": "postgres",
    "database.port": "5432",
    "database.user": "authz",
    "database.password": "authz123",
    "database.dbname": "authz",
    "database.server.name": "authz",
    "topic.prefix": "authz",
    "schema.include.list": "authz",
    "plugin.name": "pgoutput",
    "publication.name": "authz_pub",
    "publication.autocreate.mode": "all_tables",
    "slot.name": "authz_slot",
    "snapshot.mode": "initial",
    "transforms": "unwrap",
    "transforms.unwrap.type": "io.debezium.transforms.ExtractNewRecordState",
    "transforms.unwrap.drop.tombstones": "false",
    "transforms.unwrap.delete.handling.mode": "rewrite"
  }
}'

echo ""
echo "Waiting for connector to start..."
sleep 10

echo "Connector status:"
curl -s "$CONNECT_URL/connectors/$CONNECTOR_NAME/status"