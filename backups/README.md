# Recovery snapshots

`2026-09-12-output.zip` is a Git LFS snapshot of the generated `output/` directory
at the user's commit-and-push checkpoint. `2026-09-12-output.manifest.json`
records each source path, size and SHA-256 plus the archive SHA-256. Every archived
file was read back and checked against its source hash before committing.

Run `git lfs pull` after checkout to download the archive. Extract into an empty
directory and review its `output/README.md` before using restoration material.
These are historical evidence and recovery products, not a declaration that every
candidate passed acceptance. Source code and the roadmap are versioned normally.

Checkpoint validation: 136 workflow tests, 5 offshore tests and 48 Unreal-adapter
tests passed (189 Python checks in total). Native build and vehicle verification
remain the previously recorded results; no new engine build or whole-map
acceptance is claimed by this backup commit.
