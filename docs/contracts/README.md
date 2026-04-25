# Contracts

Contracts are the highest-precedence ComfyGit truth layer. They describe the
behavioral guarantees and ownership boundaries that implementation work should
preserve.

Start with the smallest surface that matters:

- `core/CONTRACT.md` - core library, manifest, sync, dependency, and portability
  guarantees.

Package architecture docs and public documentation may expand on these contracts,
but they should not contradict them.
