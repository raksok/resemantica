# Retired Task: Packet Integration Redirect

## Goal

Do not claim this as a standalone implementation task; graph integration belongs to Task 08, Chapter Packets with Graph Integration (M8).

## Scope

In:

- redirect agents to the merged packet scope

Out:

- standalone packet-integration implementation
- separate packet-retrofit milestone
- new owned modules

## Owned Files Or Modules

- none

## Interfaces To Satisfy

- task brief: `task-08-packets.md`
- LLD: `../20-lld/lld-08-packets.md`
- retired LLD note: `../20-lld/retired-packet-integration.md`

## Tests Or Smoke Checks

- none for this redirect

## Done Criteria

- no agent treats packet integration as separate claimable work
- graph-to-packet behavior is implemented only through Task 08
- Task 08 remains the active packet implementation brief for M8
