# Demo streaming response guide

This fixture describes a small streaming endpoint used by the regression tests. A streaming response should yield chunks from the iterator and should not buffer the complete body before returning. When the client closes early, first check whether the generator raised an exception and whether the server is waiting on a blocking operation.

For a slow producer, use an explicit timeout and emit small chunks. A proxy may close an idle connection, so a heartbeat or a shorter flush interval is preferable to an unbounded blocking call. The application should log the request id and the last emitted chunk before retrying.
