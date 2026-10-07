# Isolated discovery validation

The six implementation files are copied byte-for-byte from the reviewed A6
candidate. No new dependency, migration, permission grant or route mounting is
introduced. List/dictionary source remains opt-in until app composition is tested.

The PostgreSQL workflow runs, in order:
1. Existing 24 command cases, populated-schema identity-fix proof and 33 role cases
2. All 13 discovery author PostgreSQL cases, with no skip accepted
3. Seven unchanged independent probes, assembled against this backend and migration
   004 in a disposable copy, with frozen source/probe hashes checked first
4. All 13 author discovery cases again through an actual restricted login; owner
   connections are used only for fixtures, and restarted services also use runtime
   connections
5. Aggregate checks with PostgreSQL configured

The temporary review assembly adds current migrations to the originally reviewed
001/002 snapshot. It preserves the seven probe bytes and their real PostgreSQL
lock-wait observation. This tests the integrated hardening rather than an older
unprotected schema; it is not a replacement of reviewed runtime source.

Dictionary policy is explicit: representative lowest-number active order, and
only the explicit queued state counted in queue_count. A representative does not
imply exclusive assignment. Lists are live keyset sweeps, not repeatable snapshots;
clients must restart/drain them as agreed to discover old newly reassigned work.
Network/TLS/device timing and final auth/router composition remain separate gates.
