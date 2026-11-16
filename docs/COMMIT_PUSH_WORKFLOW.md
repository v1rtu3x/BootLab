# Development and release workflow

BootLab development uses ordinary Git commits with their real author and
committer timestamps. Do not rewrite dates to alter contribution graphs, and do
not force-push shared history.

## Local development

1. Create a branch for work that will be shared through review. Direct commits
   to `main` are appropriate only when the repository owner has requested them.
2. Initialize submodules and apply BootLab's simulator patch with
   `git submodule update --init --recursive` and
   `./scripts/apply-mcuboot-patches.sh`.
3. Install dependencies and run `./scripts/reproduce.sh`.
4. Review the complete diff, stage explicit product paths, and commit with a
   conventional subject. Keep generated evidence, local keys, and build output
   out of commits.

## Review and release

Open a pull request for review unless the repository maintainers have chosen a
different process. Resolve review feedback in new commits. Merge through the
repository's configured process, then create a release from the reviewed
commit if maintainers choose to publish one. Push normally; if the remote has
diverged, fetch and reconcile the histories without force-pushing.

Record the tested BootLab and MCUboot revisions, tool versions, validation
commands, and known limitations in release notes. Signatures and timestamps
may make generated evidence differ between runs, so do not promise byte-for-byte
identical output.
