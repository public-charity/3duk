# Generated output and recovery material

The 2026-09-12 commit-and-push checkpoint preserves this directory in
`backups/2026-09-12-output.zip` using Git LFS. Its companion JSON manifest lists
every archived path, byte count and SHA-256. The archive includes the Manston
recovery packs and PDF, offshore review evidence/scripts, original offshore
landscape package backups, candidate rasters and native application records.

To restore, fetch the archive with Git LFS and extract it into a separate empty
directory first. Archive paths start with `output/`. Inspect the manifest and the
historical plans before using any candidate or rollback operation. Restoring a
backup is not approval to apply an old landscape over newer road or building work.

Subsequent generated contents of this directory are ignored by Git; create a new
dated archive when another recovery snapshot is needed. The existing repository
rules still exclude raw `data/`, generated Unreal `Content/`, `Saved/`, build
products and downloaded photo/geodata collections. This archive is not a full
disk backup and does not include those excluded directories.
