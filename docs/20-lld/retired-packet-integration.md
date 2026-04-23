# Retired LLD: Packet Integration Redirect

Status: retired redirect.

Packet integration is not a standalone LLD or claimable implementation slice. Graph data is built before packets in M6 and M7, so graph integration happens in the M8 chapter packet build described in `lld-08-packets.md`.

Implementation agents should read:

- `lld-08-packets.md` for packet building and graph integration
- `lld-06-graph-mvp.md` for the graph foundation
- `lld-07-world-model.md` for M7 world-model enrichment
