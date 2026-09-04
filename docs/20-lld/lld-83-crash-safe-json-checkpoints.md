# LLD 83: Crash-Safe JSON Checkpoints

## Summary

Run artifacts written through the shared JSON helper use same-directory temporary files and atomic replacement. Translation passes treat an unreadable compatible checkpoint artifact as a cache miss so an interrupted write cannot become a sticky retry failure.

## Persistence Contract

For each shared JSON artifact write:

1. Serialize the complete payload before touching the destination.
2. Create a unique temporary file beside the destination.
3. Write UTF-8 JSON, flush the file, and synchronize its contents to storage.
4. Atomically replace the destination with the completed temporary file.
5. Remove the temporary file after an ordinary failure.

If serialization, writing, synchronization, or replacement fails, an existing destination remains unchanged. If the destination does not yet exist, interruption before replacement leaves it missing rather than exposing a partial artifact. Concurrent writers receive distinct temporary paths; existing stage ownership rules still determine which completed write is authoritative.

## Translation Cache Recovery

Pass 1, Pass 2, and Pass 3 validate that a compatible checkpoint artifact can be read as a JSON object before reuse. Invalid UTF-8, malformed JSON, non-object JSON, and operating-system read failures produce an operator warning plus a `translate-chapter.passN.cache_invalid` event, then become a cache miss. The event records the pass, artifact path, and parse reason. The affected pass regenerates normally without requiring `--force`, and its next durable write replaces the unreadable artifact.

Required upstream artifacts remain strict inputs. Pass 2 does not continue from an unreadable Pass 1 artifact, and Pass 3 does not continue from an unreadable Pass 2 artifact; the upstream pass must recover first.

Semantically malformed Pass 2 block mappings retain their existing hard-failure behavior because the intended source mapping cannot be inferred safely. Valid partial Pass 1 and Pass 2 artifacts retain their existing block-level reuse behavior.

## Interfaces

No CLI flags, configuration fields, database schemas, checkpoint identities, prompt versions, generic event schema, or JSON artifact shapes change. Translation adds the `pass1.cache_invalid`, `pass2.cache_invalid`, and `pass3.cache_invalid` event types under the existing `translate-chapter` namespace.

## Tests

- Atomic replacement produces valid UTF-8 JSON and leaves no temporary file.
- Serialization and replacement failures preserve an existing artifact.
- NUL-filled Pass 1, Pass 2, and Pass 3 cache artifacts are regenerated without force.
- Valid cache reuse, targeted Pass 2 repair, and strict upstream reads remain unchanged.
