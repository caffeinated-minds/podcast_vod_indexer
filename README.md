# Podcast VOD Indexer

Podcast VOD Indexer is a personal, locally operated pipeline for finding where
episodes of The StandUp Podcast appear across YouTube livestream VODs and
full-length YouTube episodes.

The pipeline uses YouTube transcripts to match podcast episodes to their
original livestream timestamps, stores its state in SQLite, and generates a
static HTML index.

This project is not intended to be published as a reusable service or run on a
hosted CI worker. YouTube access depends on browser cookies and the local user
keyring, so indexing runs on the machine where those credentials are available.

## V1 MVP

The v1 MVP is complete. It provides a reliable local-to-public publishing
pipeline that can be triggered with one command:

```bash
indexer run --publish
```

```text
preflight
-> synchronize YouTube metadata and transcripts
-> calculate new matches
-> generate and validate the static HTML index
-> create a verified local SQLite backup
-> push changed public artifacts
-> GitHub Pages deploys the public site
```

The indexer remains local because YouTube access depends on browser credentials.
Only the generated static site is hosted. The public project site is:

<https://caffeinated-minds.github.io/podcast_vod_indexer/>

## Architecture Decisions

### Local Pipeline

The pipeline runs directly on the local machine so `yt-dlp` can access browser
cookies and the unlocked user keyring. Docker and hosted CI are not part of the
MVP because they would complicate access to these credentials.

The Python CLI owns the actual workflow, including stage ordering, durable
state, retries, and failure handling. The intended primary command is:

```bash
indexer run --publish
```

`indexer` is a local launcher script that enters the project directory, starts a
small Nix shell with CA certificates, sets `SSL_CERT_FILE`, and then invokes the
Python CLI. The launcher owns local runtime setup; the Python CLI owns pipeline
logic.

Deep VOD matching is intentionally explicit because it can be slow:

```bash
indexer run --deep-vod-match --publish
```

A Makefile may later provide memorable shortcuts such as `make run`,
`make test`, and `make publish`, but it will not contain the pipeline's business
logic.

Useful commands:

```bash
indexer run
indexer run --publish
indexer run --deep-vod-match
indexer run --deep-vod-match --publish
indexer validate-public-artifacts
indexer backup-db
indexer publish
```

`publish` means "commit and push changed files from `output/`." The GitHub Pages
workflow performs the actual hosted deployment after the push.

### Future Scheduling

After manual runs are reliable, a version-controlled `systemd --user` service
and timer will invoke the same pipeline command. Scheduled runs should occur
during a logged-in desktop session so the browser keyring is available.

### Artifact Separation

For the current MVP, this repository tracks the pipeline implementation and its
latest public generated state:

- `output/index.html` contains the latest generated public index.
- Future `output/*.csv` files will contain public data exports.

The working SQLite database remains local-only:

- `data/index.db` contains collected metadata, transcripts, and match state.
- It is ignored by Git and must not be committed.
- Successful local runs create timestamped backups under
  `~/gdrive/Archive/podcast-vod-indexer/`.
- Each backup is copied through SQLite's backup API, checked with
  `PRAGMA integrity_check`, and written with a SHA-256 checksum file.

Updating tracked public artifacts allows a push to trigger publication. Browser
cookies, API credentials, logs, and temporary database snapshots must remain
outside the repository.

GitHub Pages hosts only intentionally public outputs:

- The static HTML index.
- Future CSV exports for direct data access.

GitHub Actions deploys the contents of `output/` to GitHub Pages. A future CSV
export should be generated in the same completed run as the HTML so the public
artifacts remain consistent.

The GitHub Pages deployment must include only intended public outputs. The
working SQLite database must not be included in the static-site deployment.

Ignoring `data/index.db` prevents future commits from tracking the working
database. It does not remove database blobs from old Git history. Before making
the repository public, historical commits must be audited and cleaned if they
contain private SQLite state.

### Credentials

Credentials remain local and must never be committed:

- YouTube access through local browser cookies and the user keyring

Credentials for any future external integrations must follow the same rule.

### Future Publication State

SQLite is currently the source of truth for collected metadata, transcripts, and
matches. Publication and announcement state may be added later.

The pipeline should track forward-only states similar to:

```text
matched -> exported -> published -> announced
```

Publication and announcement records must make interrupted runs resumable and
prevent duplicate X posts.

## Current Status

The project currently:

- Collects metadata for YouTube VODs, short episodes, and full-length episodes.
- Fetches and stores YouTube automatic-caption transcripts.
- Matches short episodes to VOD transcript windows.
- Matches short episodes to full-length YouTube episodes.
- Ignores and prunes VODs older than the VOD matched to the first episode.
- Skips accepted matches and scopes uncertain-match retries to new evidence.
- Preserves stronger existing matches when new candidates score lower.
- Backs up the local SQLite database to `~/gdrive/Archive/podcast-vod-indexer/`
  after successful runs.
- Generates a static Bootstrap HTML index.
- Includes a GitHub Pages workflow for publishing only files from `output/`.
- Provides `run --publish` to validate, commit, and push changed public
  artifacts after a successful local run.
- Publishes the generated index at
  <https://caffeinated-minds.github.io/podcast_vod_indexer/>.
- Passes the automated test suite, Ruff checks, and public-artifact validation.

It does not yet provide CSV exports, public-page verification, X announcements,
or scheduled execution. Those are post-MVP improvements rather than blockers for
the completed v1 workflow.

## V1 Acceptance

- [x] One local command synchronizes, matches, exports, backs up, and publishes.
- [x] The command can rebuild and publish from the existing local SQLite state.
- [x] Deep VOD matching remains an explicit opt-in operation.
- [x] Generated public artifacts are validated before publication.
- [x] Successful runs create integrity-checked SQLite backups with checksums.
- [x] The working SQLite database and credentials are excluded from Git.
- [x] Only files under `output/` are deployed publicly.
- [x] GitHub Pages deploys automatically after changed output is pushed.
- [x] The public project site is reachable.
- [x] Automated tests, lint checks, and artifact validation pass.

## Post-MVP Roadmap

### Reliability

- [ ] Test restoring a backup into a separate local path.
- [ ] Define backup retention and cleanup rules.
- [ ] Add an offline end-to-end test using fixtures.
- [ ] Add clearer handling for YouTube rate limits and locked-keyring failures.
- [ ] Add a fuller preflight check for credentials, tools, paths, and Git state.
- [ ] Print a concise final run summary.
- [ ] Verify the deployed page automatically after publication.

### Public Data

- [ ] Define and generate stable CSV exports alongside the HTML.
- [ ] Validate CSV row counts against SQLite before publication.
- [ ] Add stable HTML anchors for individual episodes.

### Automation

- [ ] Add a version-controlled `systemd --user` service and timer.
- [ ] Confirm scheduled runs can access browser cookies and the unlocked
      keyring.
- [ ] Make scheduled failures visible without publishing incomplete output.

### Optional Announcements

- [ ] Decide whether X announcements still provide enough value to implement.
- [ ] If retained, store credentials locally and never commit them.
- [ ] Announce only newly successful matches after deployment verification.
- [ ] Record post IDs and failures so retries cannot create duplicates.
