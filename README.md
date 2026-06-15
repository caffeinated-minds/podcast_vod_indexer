# Podcast VOD Indexer

Podcast VOD Indexer is a personal, locally operated pipeline for finding where
episodes of The StandUp Podcast appear across YouTube livestream VODs,
full-length YouTube episodes, and Spotify.

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
-> synchronize Spotify episodes
-> calculate new matches
-> detect newly successful episode matches
-> create and upload a private SQLite backup
-> generate and validate the static HTML index and CSV exports
-> deploy changed HTML and CSV artifacts
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
uv run podcast-vod-indexer run --publish --announce
```

A Makefile may provide memorable shortcuts such as `make run`, `make test`, and
`make publish`, but it will not contain the pipeline's business logic.

### Scheduling

After manual runs are reliable, a version-controlled `systemd --user` service
and timer will invoke the same pipeline command. Scheduled runs should occur
during a logged-in desktop session so the browser keyring is available.

### Artifact Separation

This source repository contains the pipeline implementation, configuration,
tests, documentation, and deployment definitions.

Generated staging files and operational state are not source artifacts:

- Working SQLite database
- Generated staging output
- Logs and temporary database snapshots
- Browser cookies and API credentials

Azure Static Web Apps hosts only intentionally public outputs:

- The static HTML index.
- CSV exports for direct data access.

The HTML and CSV exports are generated from the same completed run so they
remain consistent. The local pipeline deploys them to Azure Static Web Apps and
verifies the public site before allowing X announcements.

The complete working SQLite database is never published publicly. The pipeline
creates a consistent full-database snapshot and uploads it as a private,
versioned Azure Artifacts Universal Package for remote backup and recovery.

### Credentials

Credentials remain local and must never be committed:

- YouTube access through local browser cookies and the user keyring
- `SPOTIFY_CLIENT_ID`
- `SPOTIFY_CLIENT_SECRET`
- X API credentials
- Azure Static Web Apps deployment credentials
- Azure DevOps credentials for private SQLite backups

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
- Generates a static Bootstrap HTML index.
- Contains an in-progress Spotify synchronization and matching implementation.

It does not yet provide the complete one-command pipeline, artifact publishing,
I public-page verification, X announcements, or automated tests.

## MVP Roadmap

### 1. Establish Safe Repository Boundaries

- [x] Stop tracking the mutable SQLite database in the source repository.
- [x] Stop tracking generated staging HTML in the source repository.
- [x] Add `data/`, `output/`, logs, and backups to `.gitignore`.
- [x] Create and configure an Azure Static Web Apps resource.
  - [Link](https://lively-flower-08252b703.7.azurestaticapps.net/)
- [x] Create a private Azure Artifacts feed for full SQLite backups.
- [ ] Add `.env.example` with placeholder Spotify, X, and publishing settings.
- [ ] Document how local state is backed up and restored.

### 2. Finish Spotify Integration

- [ ] Complete Spotify episode synchronization.
- [ ] Validate Spotify matching against real episodes.
- [ ] Define a Spotify-specific successful-match threshold.
- [ ] Prevent weak candidates from displacing stronger existing matches.
- [ ] Display successful Spotify links in the generated index.
- [ ] Confirm the pipeline still works when Spotify credentials are unavailable.

### 3. Define Match Success

- [ ] Define separate confidence thresholds for VOD, full-episode, and Spotify
      matches.
- [ ] Distinguish successful, uncertain, and unmatched results.
- [ ] Prevent weaker reruns from replacing stronger existing matches.
- [ ] Add a durable record of when an episode first becomes successfully
      matched.
- [ ] Add stable HTML anchors for individual episodes.
- [ ] Manually evaluate a representative sample and document acceptable
      accuracy.

### 4. Build the Pipeline CLI

- [ ] Add explicit `sync`, `match`, `export`, `publish`, and `announce`
      commands.
- [ ] Add a `run --publish --announce` command that orchestrates all stages.
- [ ] Add a preflight stage that validates credentials, tools, paths, and
      repositories.
- [ ] Make interrupted runs resumable and reruns idempotent.
- [ ] Return nonzero exit codes for fatal failures.
- [ ] Print a final summary of discovered, matched, published, and announced
      episodes.
- [ ] Add a dry-run mode that performs no publication or X posting.

### 5. Back Up SQLite Privately

- [ ] Configure access to a private Azure Artifacts feed.
- [ ] Create a consistent full SQLite snapshot without copying an active write.
- [ ] Validate SQLite integrity before uploading the backup.
- [ ] Upload each backup as a versioned Azure Artifacts Universal Package.
- [ ] Define backup naming, retention, and cleanup rules.
- [ ] Record the backup package version and result in SQLite.
- [ ] Test restoring a backup into a separate local path.

### 6. Publish Static HTML and CSV

- [ ] Configure Azure Static Web Apps and its local deployment credentials.
- [ ] Validate generated HTML before deployment.
- [ ] Define useful CSV datasets, such as episodes, successful matches, and
      unmatched episodes.
- [ ] Generate CSV files from the same completed run as the HTML.
- [ ] Use stable CSV columns and document their meanings.
- [ ] Validate CSV row counts against the working SQLite database.
- [ ] Deploy only intended HTML and CSV files to Azure Static Web Apps.
- [ ] Publish only when generated artifacts changed.
- [ ] Record the deployed revision and publication result in SQLite.
- [ ] Verify the public page is reachable before allowing announcements.
- [ ] Ensure failed or incomplete indexing runs cannot publish broken output.

### 7. Announce New Matches on X

- [ ] Configure X API credentials locally.
- [ ] Add an announcement table with unique constraints preventing duplicates.
- [ ] Detect newly successful, published, and unannounced matches.
- [ ] Generate posts containing the episode title and stable public index link.
- [ ] Post only after successful publication and public-page verification.
- [ ] Store returned X post IDs and timestamps.
- [ ] Record failures and safely retry them on later runs.
- [ ] Confirm dry-run output clearly shows proposed posts.

### 8. Add Reliability Coverage

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

### 9. Add Local Automation

- [ ] Add a Makefile containing convenience commands only.
- [ ] Add a version-controlled `systemd --user` service.
- [ ] Add a version-controlled `systemd --user` timer.
- [ ] Confirm scheduled runs can access browser cookies and the unlocked
      keyring.
- [ ] Confirm failures are visible through logs and do not publish or announce.

### 10. MVP Acceptance

- [ ] A single local command completes sync, matching, export, publication, and
      announcement.
- [ ] The command can rebuild and publish from the existing local SQLite state.
- [ ] Every publication includes matching HTML and CSV exports from the same
      run.
- [ ] Full SQLite snapshots are stored privately and can be restored
      successfully.
- [ ] Azure Static Web Apps contains no SQLite database or private operational
      data.
- [ ] Reruns are idempotent and never duplicate X announcements.
- [ ] New successful matches are published before they are announced.
- [ ] Failed indexing never publishes or posts.
- [ ] Failed publication prevents posting.
- [ ] Failed X posts are recorded and retry successfully.
- [ ] Published episode links resolve to the intended rows.
- [ ] Several manual and scheduled runs complete without intervention.

When every acceptance item is checked, the local publishing and announcement
workflow is considered the finished MVP.
