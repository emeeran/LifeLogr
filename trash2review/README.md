# trash2review — holding pen, not a deletion

Files moved here by the cleanup pipeline were relocated with `git mv`, so
history is preserved and nothing was destroyed. This folder exists so a human
can review each relocation before it becomes a real deletion.

## Restore a file to its original location

    git mv trash2review/<same-relative-path> <original-path>

Each moved file keeps its original relative path beneath this folder, so the
original location is always recoverable from the path itself. Reasons for each
move are logged in `.pipeline/purge-plan.md`.
