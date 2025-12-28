#!/bin/bash

echo "Waiting for services..."
sleep 30

echo "Registering Debezium connector..."
curl -X POST http://localhost:8083/connectors \
  -H "Content-Type: application/json" \
  -d @debezium-connector.json

echo "Connector registered!"