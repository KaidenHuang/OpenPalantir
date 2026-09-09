#!/bin/bash
NEO4J_HOME=/mnt/f/Code/OpenPalantir/dependencies/neo4j/extracted/neo4j-community-2026.07.1
NEO4J_DATA=/mnt/f/Code/OpenPalantir/backend/data/neo4j/data

echo "Stopping Neo4j..."
$NEO4J_HOME/bin/neo4j stop 2>/dev/null
sleep 3
# Force kill if still running
pkill -9 -f "org.neo4j.server" 2>/dev/null
sleep 2
echo "Neo4j stopped"

echo "Clearing data at $NEO4J_DATA..."
rm -rf $NEO4J_DATA/databases/*
rm -rf $NEO4J_DATA/transactions/*
echo "Data cleared"

echo "Starting Neo4j..."
setsid $NEO4J_HOME/bin/neo4j console > /mnt/f/Code/OpenPalantir/logs/neo4j-console.log 2>&1 &
disown

echo "Waiting for Neo4j..."
for i in $(seq 1 45); do
  if $NEO4J_HOME/bin/cypher-shell -u neo4j -p '1234qwer' 'RETURN 1 AS test' 2>/dev/null; then
    echo "Neo4j is ready!"
    $NEO4J_HOME/bin/cypher-shell -u neo4j -p '1234qwer' 'MATCH (n) RETURN count(n) AS total'
    exit 0
  fi
  sleep 2
done
echo "Timeout"
exit 1
