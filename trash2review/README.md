# trash2review — holding pen, not a deletion

Files here were moved by the cleanup pipeline because they looked redundant,
dead, or superseded. **Nothing has been deleted.** Review at your leisure and
empty this folder when satisfied.

## Restore a file

```bash
git mv trash2review/backend/app/old_module.py backend/app/old_module.py
```

(Paths are mirrored from their original location under the repo root. Then
commit the restore. If the pipeline branch has since been merged or rebased,
restoring onto the branch it came from is easiest.)
