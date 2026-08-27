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

## MVP

The MVP is a reliable local-to-public publishing pipeline that can be triggered
with one command.

```text
preflight
-> synchronize YouTube metadata and transcripts
-> calculate new matches
-> detect newly successful episode matches
-> generate and validate the static HTML index and CSV exports
-> create a verified local SQLite backup
-> push changed HTML and CSV artifacts
-> GitHub Pages deploys the public site
-> verify the public page
-> announce newly published matches on X
-> record results and print a run summary
```

An X announcement must only be created when:

- An episode receives a successful match for the first time.
- The match meets the configured confidence threshold.
- The generated HTML contains a stable link to the episode.
- Publishing and public-page verification succeed.
- The match has not previously been announced.

Failed publication must prevent announcements. Failed X announcements must be
recorded and safely retryable without creating duplicate posts.

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

A Makefile may later provide memorable shortcuts such as `make run`, `make
test`, and `make publish`, but it will not contain the pipeline's business
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

`publish` means "commit and push changed files from `output/`." The GitHub
Pages workflow performs the actual hosted deployment after the push.

### Scheduling

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
- CSV exports for direct data access.

The HTML and CSV exports are generated from the same completed run so they
remain consistent. GitHub Actions deploys them to GitHub Pages and the local
pipeline should verify the public site before allowing X announcements.

The GitHub Pages deployment must include only intended public outputs. The
working SQLite database must not be included in the static-site deployment.

Ignoring `data/index.db` prevents future commits from tracking the working
database. It does not remove database blobs from old Git history. Before making
the repository public, historical commits must be audited and cleaned if they
contain private SQLite state.

### Credentials

Credentials remain local and must never be committed:

- YouTube access through local browser cookies and the user keyring
- X API credentials

An `.env.example` file will document required environment variables without
containing secrets.

### Durable State

SQLite is the source of truth for collected metadata, transcripts, matches,
publication state, and announcement state.

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
- Backs up the local SQLite database to
  `~/gdrive/Archive/podcast-vod-indexer/` after successful runs.
- Generates a static Bootstrap HTML index.
- Includes a GitHub Pages workflow for publishing only files from `output/`.
- Provides `run --publish` to validate, commit, and push changed public
  artifacts after a successful local run.

It does not yet provide CSV exports, public-page verification, X announcements,
or comprehensive automated test coverage.

## MVP Roadmap

### 1. Establish Safe Repository Boundaries

- [x] Track the latest generated HTML in the repository.
- [x] Keep the working SQLite database local and ignored by Git.
- [x] Keep browser cookies and API credentials out of the repository.
- [x] Ensure deployment publishes files from `output/` only, never SQLite.
- [x] Add a GitHub Pages project-site deployment workflow.
- [ ] Enable GitHub Pages with GitHub Actions as the source in repository
      settings.
- [x] Add verified local SQLite backups under
      `~/gdrive/Archive/podcast-vod-indexer/`.
- [ ] Add `.env.example` with placeholder X and publishing settings.
- [ ] Document how local state is backed up and restored.

### 2. Define Match Success

- [ ] Define separate confidence thresholds for VOD and full-episode matches.
- [ ] Distinguish successful, uncertain, and unmatched results.
- [x] Prevent weaker reruns from replacing stronger existing matches.
- [x] Skip repeated matching work unless relevant new transcript evidence is
      available.
- [ ] Add a durable record of when an episode first becomes successfully
      matched.
- [ ] Add stable HTML anchors for individual episodes.
- [ ] Manually evaluate a representative sample and document acceptable
      accuracy.

### 3. Build the Pipeline CLI

- [ ] Add explicit `sync`, `match`, `export`, and `announce`
      commands.
- [x] Add a `run --publish` command that orchestrates through publication.
- [x] Keep deep VOD matching explicit with `run --deep-vod-match`.
- [ ] Add a `run --publish --announce` command once X support exists.
- [x] Add a launcher script for NixOS/local runtime setup.
- [x] Add publish safety checks for branch, remote, ignored DB state, and
      non-output working tree changes.
- [ ] Add a fuller preflight stage that validates credentials, tools, paths, and
      repositories.
- [ ] Make interrupted runs resumable and reruns idempotent.
- [x] Return nonzero exit codes for fatal validation and publication failures.
- [ ] Print a final summary of discovered, matched, published, and announced
      episodes.
- [ ] Add a dry-run mode that performs no publication or X posting.

### 4. Back Up SQLite Locally

- [x] Create a consistent full SQLite snapshot without copying an active write.
- [x] Validate SQLite integrity before accepting the backup.
- [x] Write a checksum next to each SQLite backup.
- [x] Store backups in `~/gdrive/Archive/podcast-vod-indexer/`.
- [ ] Define backup naming, retention, and cleanup rules.
- [ ] Record the backup path and result in SQLite.
- [ ] Test restoring a backup into a separate local path.

### 5. Publish Static HTML and CSV

- [x] Add a GitHub Pages deployment workflow.
- [ ] Enable GitHub Pages deployment from GitHub Actions in repository
      settings.
- [ ] Validate generated HTML before deployment.
- [ ] Define useful CSV datasets, such as episodes, successful matches, and
      unmatched episodes.
- [ ] Generate CSV files from the same completed run as the HTML.
- [ ] Use stable CSV columns and document their meanings.
- [ ] Validate CSV row counts against the working SQLite database.
- [x] Deploy only intended files from `output/`.
- [x] Publish only when generated artifacts changed.
- [ ] Record the deployed revision and publication result in SQLite.
- [ ] Verify the public page is reachable before allowing announcements.
- [ ] Ensure failed or incomplete indexing runs cannot publish broken output.

### 6. Announce New Matches on X

- [ ] Configure X API credentials locally.
- [ ] Add an announcement table with unique constraints preventing duplicates.
- [ ] Detect newly successful, published, and unannounced matches.
- [ ] Generate posts containing the episode title and stable public index link.
- [ ] Post only after successful publication and public-page verification.
- [ ] Store returned X post IDs and timestamps.
- [ ] Record failures and safely retry them on later runs.
- [ ] Confirm dry-run output clearly shows proposed posts.

### 7. Add Reliability Coverage

- [ ] Add tests for title, transcript, date, and duration similarity.
- [ ] Add tests for match selection and confidence thresholds.
- [ ] Add tests for database upserts, migrations, and announcement uniqueness.
- [ ] Add tests confirming static deployment contains only intended HTML and CSV
      files.
- [ ] Add tests for consistent SQLite backup creation and integrity validation.
- [ ] Add tests for HTML escaping, links, and stable anchors.
- [ ] Add an offline end-to-end test using fixtures.
- [ ] Back up SQLite before schema migrations or risky operations.
- [ ] Handle YouTube rate limits and locked-keyring failures explicitly.

### 8. Add Local Automation

- [ ] Add a Makefile containing convenience commands only.
- [ ] Add a version-controlled `systemd --user` service.
- [ ] Add a version-controlled `systemd --user` timer.
- [ ] Confirm scheduled runs can access browser cookies and the unlocked
      keyring.
- [ ] Confirm failures are visible through logs and do not publish or announce.

### 9. MVP Acceptance

- [ ] A single local command completes sync, matching, export, publication, and
      announcement.
- [ ] The command can rebuild and publish from the existing local SQLite state.
- [ ] Every publication includes matching HTML and CSV exports from the same
      run.
- [ ] Full SQLite snapshots are stored locally and can be restored
      successfully.
- [ ] GitHub Pages contains no SQLite database or private operational data.
- [ ] Reruns are idempotent and never duplicate X announcements.
- [ ] New successful matches are published before they are announced.
- [ ] Failed indexing never publishes or posts.
- [ ] Failed publication prevents posting.
- [ ] Failed X posts are recorded and retry successfully.
- [ ] Published episode links resolve to the intended rows.
- [ ] Several manual and scheduled runs complete without intervention.

When every acceptance item is checked, the local publishing and announcement
workflow is considered the finished MVP.
