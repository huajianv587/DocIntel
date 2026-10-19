# Demo configuration guide

The support service reads `DOCINTEL_INDEX_PATH` at startup. If the path is missing, the service can start in health-only mode but it must return an abstention for document questions. Configuration changes require rebuilding the index when source files change; a restart alone does not reload an old in-memory index.
