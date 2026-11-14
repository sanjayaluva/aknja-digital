# Production Capacity and Hosting Admission

Do not publish a fixed app count per OCI VM. Capacity is a function of workload shape, concurrency, DB connections, memory peaks, CPU, storage growth, network, backup and recovery reserve.

Admission test:
1. inventory host and current workloads;
2. define per-app CPU/RAM/PID/storage/connection budgets;
3. run representative load test;
4. measure p95 latency, error rate, CPU/RAM and disk;
5. test noisy-neighbor/resource exhaustion;
6. verify backup and restore;
7. reserve operational headroom;
8. approve, require separate host or reject.

Single-node managed hosting is best-effort and has a single point of failure. HA/SLA requires additional infrastructure, monitoring and tested failover; price it accordingly.
