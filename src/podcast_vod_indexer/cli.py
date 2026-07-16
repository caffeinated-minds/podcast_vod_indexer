from podcast_vod_indexer.db import (
    LONG_EPISODE_DURATION_TOLERANCE_SECONDS,
    init_db,
    get_connection,
    insert_video,
    insert_segments,
    get_video_id_by_youtube_id,
    get_videos_without_segments_by_kind,
    get_videos_with_segments_by_kind,
    get_videos_with_segments_by_kind_and_date,
    get_segments_for_video,
    get_match_confidence_for_episode,
    get_episode_long_match_for_episode,
    get_excluded_long_episode_ids,
    get_first_episode_matched_vod_date,
    get_excluded_long_episode_match_ids,
    get_matched_long_episode_ids,
    prune_vods_before_date,
    remove_non_distinct_long_episode_matches,
    upsert_match,
    upsert_episode_long_match,
)
from podcast_vod_indexer.youtube import (
    get_latest_videos,
    get_video_info,
    get_transcript_segments,
    TranscriptRateLimitError,
)
from podcast_vod_indexer.matching import (
    find_best_window_match,
    find_best_window_pair_match,
    find_long_episode_transcript_match,
    refine_low_confidence_window_match,
    token_overlap_score,
    transcript_tokens,
)
from podcast_vod_indexer.export import export_matches_html

import argparse
from collections.abc import Callable
from dataclasses import dataclass, field
import select
import sys
import time


MATCH_CONFIDENCE_CUTOFF = 0.15
MATCH_SKIP_CONFIDENCE_CUTOFF = 0.15
SHORT_EPISODE_MATCH_SECONDS = 15 * 60
LONG_EPISODE_SEARCH_SECONDS = 45 * 60
LONG_EPISODE_WINDOW_SECONDS = 15 * 60
LONG_EPISODE_STEP_SECONDS = 2 * 60
LONG_EPISODE_MATCH_METHOD = "transcript_short15m_long45m_window15m"
DEEP_VOD_EPISODE_STEP_SECONDS = 5 * 60
DEEP_VOD_STEP_SECONDS = 60
DEEP_VOD_TOP_CANDIDATES = 5
DEEP_VOD_PROMPT_TIMEOUT_SECONDS = 30


@dataclass
class TranscriptFetchResults:
    episode_ids: set[int] = field(default_factory=set)
    long_episode_ids: set[int] = field(default_factory=set)
    vod_ids: set[int] = field(default_factory=set)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--deep-vod-match",
        "--deep-vod-matching",
        action="store_true",
        dest="deep_vod_match",
        help=(
            "Re-run deeper VOD matching for missing or low-confidence "
            "episode matches without fetching new data."
        ),
    )
    return parser.parse_args(argv)


def confirm_continue_deep_vod_search(
    episode_title: str,
    remaining_count: int,
) -> bool:
    if remaining_count <= 0:
        return False

    prompt = (
        "[deep-vod-match] No accepted match found in the top "
        f"{DEEP_VOD_TOP_CANDIDATES} ranked VODs for "
        f"'{episode_title}'. Check the remaining {remaining_count} VOD(s)? "
        f"[y/N, timeout {DEEP_VOD_PROMPT_TIMEOUT_SECONDS}s] "
    )
    print(prompt, end="", flush=True)

    try:
        ready, _, _ = select.select(
            [sys.stdin],
            [],
            [],
            DEEP_VOD_PROMPT_TIMEOUT_SECONDS,
        )
    except (OSError, ValueError):
        print("[deep-vod-match] No input available, skipping remaining VODs")
        return False

    if not ready:
        print()
        print(
            "[deep-vod-match] No response before timeout, "
            "skipping remaining VODs"
        )
        return False

    answer = sys.stdin.readline()
    if not answer:
        print("[deep-vod-match] No input available, skipping remaining VODs")
        return False

    return answer.strip().lower() in {"y", "yes"}


def process_source(
        conn,
        source_url: str,
        kind: str,
        limit: int | None = None,
        min_upload_date: str | None = None,
        ) -> None:
    if limit is None:
        videos = get_latest_videos(source_url)
    else:
        videos = get_latest_videos(source_url, limit=limit)

    for v in videos:
        video_url = v["webpage_url"]
        youtube_id = v["youtube_id"]

        print(f"[{kind}] Processing metadata: {video_url}")

        existing_id = get_video_id_by_youtube_id(conn, youtube_id)
        if existing_id:
            print("  -> already known, skipping metadata")
            continue

        video = get_video_info(video_url, kind=kind)

        if (
            min_upload_date is not None
            and video.get("upload_date") is not None
            and video["upload_date"] < min_upload_date
        ):
            print(
                f"  -> reached VOD cutoff {min_upload_date}, "
                "stopping metadata collection"
            )
            break

        insert_video(conn, video)

    conn.commit()


def fetch_transcripts_for_videos(
    conn,
    kind: str,
    videos: list,
    limit: int,
) -> tuple[bool, set[int]]:
    successes = 0
    fetched_video_ids: set[int] = set()

    for video_id, _, video_url in videos:
        if successes >= limit:
            return True, fetched_video_ids

        print(f"[{kind}] Fetching transcript: {video_url}")

        try:
            segments = get_transcript_segments(video_url)

            if not segments:
                print("  -> no transcript, skipping")
                continue

            insert_segments(conn, video_id, segments)
            conn.commit()
            time.sleep(5)
            successes += 1
            fetched_video_ids.add(video_id)

        except TranscriptRateLimitError:
            print(
                " -> transcript rate limit hit, stopping"
                " transcript fetches for this run"
            )
            conn.commit()
            return False, fetched_video_ids

        except Exception as e:
            print(f"  -> transcript fetch failed, skipping: {e}")
            conn.commit()
            time.sleep(20)

    return True, fetched_video_ids


def fetch_missing_transcripts_with_budget(
    conn,
    vod_limit: int,
    episode_limit: int,
    long_episode_limit: int,
    vod_min_upload_date: str | None = None,
) -> TranscriptFetchResults:
    results = TranscriptFetchResults()
    episode_videos = get_videos_without_segments_by_kind(
        conn,
        kind="episode",
        limit=50,
    )

    long_episode_videos = get_videos_without_segments_by_kind(
        conn,
        kind="episode_long",
        limit=100,
    )

    vod_videos = get_videos_without_segments_by_kind(
        conn,
        kind="vod",
        limit=200,
        min_upload_date=vod_min_upload_date,
    )

    episode_fetch_completed, results.episode_ids = fetch_transcripts_for_videos(
        conn,
        kind="episode",
        videos=episode_videos,
        limit=episode_limit,
    )
    if not episode_fetch_completed:
        return results

    (
        long_episode_fetch_completed,
        results.long_episode_ids,
    ) = fetch_transcripts_for_videos(
        conn,
        kind="episode_long",
        videos=long_episode_videos,
        limit=long_episode_limit,
    )
    if not long_episode_fetch_completed:
        return results

    (
        vod_fetch_completed,
        results.vod_ids,
    ) = fetch_transcripts_for_videos(
        conn,
        kind="vod",
        videos=vod_videos,
        limit=vod_limit,
    )
    if not vod_fetch_completed:
        return results

    return results


def run_matching(
    conn,
    *,
    new_vod_transcript_ids: set[int] | None = None,
    newly_long_matched_episode_ids: set[int] | None = None,
    vod_min_upload_date: str | None = None,
) -> None:
    new_vod_transcript_ids = new_vod_transcript_ids or set()
    newly_long_matched_episode_ids = newly_long_matched_episode_ids or set()
    episodes = get_videos_with_segments_by_kind(conn, "episode")
    vods = None

    for episode_id, _, episode_title in episodes:
        existing_confidence = get_match_confidence_for_episode(
            conn, episode_id
        )

        if (
            existing_confidence is not None
            and existing_confidence >= MATCH_SKIP_CONFIDENCE_CUTOFF
        ):
            print(
                f"[match] Skipping: {episode_title} "
                f"({existing_confidence * 100:.2f}%)"
            )
            continue

        if (
            existing_confidence is not None
            and not new_vod_transcript_ids
            and episode_id not in newly_long_matched_episode_ids
        ):
            print(
                f"[match] Skipping low-confidence candidate: "
                f"{episode_title} "
                f"({existing_confidence * 100:.2f}%, no new evidence)"
            )
            continue

        if existing_confidence is not None:
            retry_reasons = []
            if new_vod_transcript_ids:
                retry_reasons.append(
                    f"{len(new_vod_transcript_ids)} new VOD transcript(s)"
                )
            if episode_id in newly_long_matched_episode_ids:
                retry_reasons.append("newly accepted long-episode match")

            print(
                f"[match] Retrying low-confidence candidate: "
                f"{episode_title} ({', '.join(retry_reasons)})"
            )

        if vods is None:
            vods = get_videos_with_segments_by_kind(
                conn,
                "vod",
                min_upload_date=vod_min_upload_date,
            )

        vods_to_search = vods
        if (
            existing_confidence is not None
            and new_vod_transcript_ids
            and episode_id not in newly_long_matched_episode_ids
        ):
            vods_to_search = [
                vod for vod in vods if vod[0] in new_vod_transcript_ids
            ]

        episode_segments = get_segments_for_video(conn, episode_id)

        best_vod_id = None
        best_vod_segments = None
        best_score = -1.0
        best_window_start = None

        print(f"[match] Episode: {episode_title}")

        for vod_id, _, vod_title in vods_to_search:
            vod_segments = get_segments_for_video(conn, vod_id)

            match = find_best_window_match(
                episode_segments,
                vod_segments,
                window_seconds=900.0,
                step_seconds=300.0,
            )

            if match is None:
                continue

            if match["score"] > best_score:
                best_score = match["score"]
                best_vod_id = vod_id
                best_vod_segments = vod_segments
                best_window_start = match["start"]

        if (
            best_vod_id is not None
            and best_vod_segments is not None
            and best_window_start is not None
            and best_score < MATCH_CONFIDENCE_CUTOFF
        ):
            refined_match = refine_low_confidence_window_match(
                episode_segments,
                best_vod_segments,
                coarse_start_seconds=best_window_start,
                window_seconds=900.0,
                search_radius_seconds=300.0,
                step_seconds=60.0,
            )

            if refined_match is not None and refined_match["score"] > best_score:
                best_score = refined_match["score"]
                best_window_start = refined_match["start"]
                print(
                    f"  -> refined low-confidence match "
                    f"({best_score * 100:.2f}%)"
                )

        if (
            existing_confidence is not None
            and best_score <= existing_confidence
        ):
            print(
                f"  -> kept stronger existing candidate "
                f"({existing_confidence * 100:.2f}%)"
            )
        elif best_vod_id is not None and best_window_start is not None:
            upsert_match(
                conn,
                episode_video_id=episode_id,
                vod_video_id=best_vod_id,
                matched_start_seconds=best_window_start,
                confidence=best_score,
            )
            conn.commit()

            if best_score >= MATCH_CONFIDENCE_CUTOFF:
                print(f"  -> stored match ({best_score * 100:.2f}%)")
            else:
                print(
                    f"  -> stored low-confidence candidate "
                    f"({best_score * 100:.2f}%)"
                )
        else:
            print("  -> no candidate found")


def run_deep_vod_matching(
    conn,
    *,
    vod_min_upload_date: str | None = None,
    confirm_continue: Callable[[str, int], bool] = (
        confirm_continue_deep_vod_search
    ),
) -> dict[str, int]:
    episodes = get_videos_with_segments_by_kind_and_date(conn, "episode")
    vods = get_videos_with_segments_by_kind_and_date(
        conn,
        "vod",
        min_upload_date=vod_min_upload_date,
    )
    summary = {
        "checked": 0,
        "improved": 0,
        "unchanged": 0,
        "no_candidate": 0,
    }

    for episode_id, _, episode_title, episode_upload_date in episodes:
        existing_confidence = get_match_confidence_for_episode(
            conn,
            episode_id,
        )
        if (
            existing_confidence is not None
            and existing_confidence >= MATCH_CONFIDENCE_CUTOFF
        ):
            continue

        candidate_vods = [
            vod
            for vod in vods
            if episode_upload_date is not None
            and vod[3] is not None
            and vod[3] <= episode_upload_date
        ]
        if not candidate_vods:
            summary["no_candidate"] += 1
            continue

        summary["checked"] += 1
        episode_segments = get_segments_for_video(conn, episode_id)
        episode_tokens = transcript_tokens(episode_segments)
        ranked_candidates = []

        print(f"[deep-vod-match] Episode: {episode_title}")
        print(
            f"  -> ranking {len(candidate_vods)} candidate VOD(s) "
            "by token overlap"
        )

        for vod in candidate_vods:
            vod_id = vod[0]
            vod_segments = get_segments_for_video(conn, vod_id)
            ranked_candidates.append(
                {
                    "vod": vod,
                    "segments": vod_segments,
                    "rank_score": token_overlap_score(
                        episode_tokens,
                        transcript_tokens(vod_segments),
                    ),
                }
            )

        ranked_candidates.sort(
            key=lambda candidate: candidate["rank_score"],
            reverse=True,
        )

        best_vod_id = None
        best_window_start = None
        best_score = -1.0
        accepted_match_found = False

        def search_candidates(candidates: list[dict]) -> bool:
            nonlocal best_vod_id, best_window_start, best_score

            for candidate in candidates:
                vod_id, _, vod_title, _ = candidate["vod"]
                match = find_best_window_pair_match(
                    episode_segments,
                    candidate["segments"],
                    window_seconds=900.0,
                    episode_step_seconds=DEEP_VOD_EPISODE_STEP_SECONDS,
                    vod_step_seconds=DEEP_VOD_STEP_SECONDS,
                )
                if match is None:
                    continue

                if match["score"] > best_score:
                    best_vod_id = vod_id
                    best_window_start = match["start"]
                    best_score = match["score"]
                    print(
                        f"  -> best so far: {vod_title} "
                        f"({best_score * 100:.2f}%, "
                        f"token rank {candidate['rank_score'] * 100:.2f}%)"
                    )
                    if best_score >= MATCH_CONFIDENCE_CUTOFF:
                        print("  -> accepted match found, moving on")
                        return True

            return False

        top_candidates = ranked_candidates[:DEEP_VOD_TOP_CANDIDATES]
        remaining_candidates = ranked_candidates[DEEP_VOD_TOP_CANDIDATES:]

        accepted_match_found = search_candidates(top_candidates)
        if not accepted_match_found and remaining_candidates:
            if confirm_continue(episode_title, len(remaining_candidates)):
                accepted_match_found = search_candidates(remaining_candidates)
            else:
                print("  -> skipped remaining ranked VOD candidates")

        if (
            not accepted_match_found
            or best_vod_id is None
            or best_window_start is None
        ):
            if existing_confidence is None:
                summary["no_candidate"] += 1
                print("  -> no accepted candidate found")
            else:
                summary["unchanged"] += 1
                print(
                    f"  -> kept existing candidate "
                    f"({existing_confidence * 100:.2f}%)"
                )
            continue

        if (
            existing_confidence is not None
            and best_score <= existing_confidence
        ):
            summary["unchanged"] += 1
            print(
                f"  -> kept existing candidate "
                f"({existing_confidence * 100:.2f}%)"
            )
            continue

        upsert_match(
            conn,
            episode_video_id=episode_id,
            vod_video_id=best_vod_id,
            matched_start_seconds=best_window_start,
            confidence=best_score,
        )
        conn.commit()
        summary["improved"] += 1
        print(f"  -> stored improved match ({best_score * 100:.2f}%)")

    print(
        "[deep-vod-match] Summary: "
        f"{summary['checked']} checked, "
        f"{summary['improved']} improved, "
        f"{summary['unchanged']} unchanged, "
        f"{summary['no_candidate']} without candidates"
    )
    return summary


def run_long_episode_matching(
    conn,
    *,
    new_episode_transcript_ids: set[int] | None = None,
    new_long_episode_transcript_ids: set[int] | None = None,
) -> set[int]:
    new_episode_transcript_ids = new_episode_transcript_ids or set()
    new_long_episode_transcript_ids = new_long_episode_transcript_ids or set()

    short_episodes = get_videos_with_segments_by_kind(conn, "episode")
    long_episodes = get_videos_with_segments_by_kind(conn, "episode_long")

    if not long_episodes:
        print("[long-episode-match] No long episodes with transcripts found")
        return set()

    matched_long_episode_ids = get_matched_long_episode_ids(conn)
    excluded_short_episode_ids = get_excluded_long_episode_match_ids(conn)
    excluded_long_episode_ids = get_excluded_long_episode_ids(conn)
    candidates = []
    existing_matches = {}
    attempted_short_episode_ids = set()

    for episode_id, _, episode_title in short_episodes:
        if episode_id in excluded_short_episode_ids:
            print(
                f"[long-episode-match] Skipping equivalent upload: "
                f"{episode_title}"
            )
            continue

        existing_match = get_episode_long_match_for_episode(conn, episode_id)
        existing_matches[episode_id] = existing_match

        if (
            existing_match is not None
            and existing_match[0] >= MATCH_CONFIDENCE_CUTOFF
        ):
            print(
                f"[long-episode-match] Skipping: {episode_title} "
                f"({existing_match[0] * 100:.2f}%)"
            )
            continue

        if (
            existing_match is not None
            and episode_id not in new_episode_transcript_ids
            and not new_long_episode_transcript_ids
        ):
            continue

        if (
            existing_match is None
            or episode_id in new_episode_transcript_ids
        ):
            candidate_long_episodes = [
                long_episode
                for long_episode in long_episodes
                if long_episode[0] not in matched_long_episode_ids
                and long_episode[0] not in excluded_long_episode_ids
            ]
        else:
            candidate_long_episodes = [
                long_episode
                for long_episode in long_episodes
                if long_episode[0] in new_long_episode_transcript_ids
                and long_episode[0] not in matched_long_episode_ids
                and long_episode[0] not in excluded_long_episode_ids
            ]

        if not candidate_long_episodes:
            continue

        attempted_short_episode_ids.add(episode_id)
        episode_segments = get_segments_for_video(conn, episode_id)

        print(f"[long-episode-match] Episode: {episode_title}")

        for long_episode_id, _, long_episode_title in candidate_long_episodes:
            long_episode_segments = get_segments_for_video(
                conn, long_episode_id
            )

            match = find_long_episode_transcript_match(
                episode_segments,
                long_episode_segments,
                max_episode_seconds=SHORT_EPISODE_MATCH_SECONDS,
                max_long_episode_seconds=LONG_EPISODE_SEARCH_SECONDS,
                window_seconds=LONG_EPISODE_WINDOW_SECONDS,
                step_seconds=LONG_EPISODE_STEP_SECONDS,
            )

            if match is None:
                continue

            candidates.append(
                {
                    "short_episode_id": episode_id,
                    "short_episode_title": episode_title,
                    "long_episode_id": long_episode_id,
                    "long_episode_title": long_episode_title,
                    "score": match["score"],
                }
            )

    candidates.sort(key=lambda candidate: candidate["score"], reverse=True)

    matched_short_episode_ids = set()
    newly_accepted_short_episode_ids = set()

    for candidate in candidates:
        short_episode_id = candidate["short_episode_id"]
        long_episode_id = candidate["long_episode_id"]

        if (
            short_episode_id in matched_short_episode_ids
            or long_episode_id in matched_long_episode_ids
        ):
            continue

        existing_match = existing_matches[short_episode_id]

        if (
            existing_match is not None
            and candidate["score"] <= existing_match[0]
        ):
            continue

        upsert_episode_long_match(
            conn,
            short_episode_video_id=short_episode_id,
            long_episode_video_id=long_episode_id,
            confidence=candidate["score"],
            match_method=LONG_EPISODE_MATCH_METHOD,
        )
        conn.commit()

        matched_short_episode_ids.add(short_episode_id)
        matched_long_episode_ids.add(long_episode_id)

        if candidate["score"] >= MATCH_CONFIDENCE_CUTOFF:
            if (
                existing_match is None
                or existing_match[0] < MATCH_CONFIDENCE_CUTOFF
            ):
                newly_accepted_short_episode_ids.add(short_episode_id)

            print(
                f"[long-episode-match] Stored: "
                f"{candidate['short_episode_title']} -> "
                f"{candidate['long_episode_title']} "
                f"({candidate['score'] * 100:.2f}%)"
            )
        else:
            print(
                f"[long-episode-match] Stored low-confidence candidate: "
                f"{candidate['short_episode_title']} -> "
                f"{candidate['long_episode_title']} "
                f"({candidate['score'] * 100:.2f}%)"
            )

    unmatched_short_episodes = [
        episode_title
        for episode_id, _, episode_title in short_episodes
        if episode_id in attempted_short_episode_ids
        and episode_id not in matched_short_episode_ids
    ]

    for episode_title in unmatched_short_episodes:
        print(f"[long-episode-match] No improved candidate: {episode_title}")

    return newly_accepted_short_episode_ids


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    vod_source_url = "https://www.youtube.com/@ThePrimeTimeagen/streams"
    episode_source_url = (
        "https://www.youtube.com/playlist?"
        "list=PL2Fq-K0QdOQiJpufsnhEd1z3xOv2JMHuk"
    )
    long_episode_source_url = (
        "https://www.youtube.com/playlist?"
        "list=PLnO2sUspiA2b-gmVb-khiLa2NoQ7mHzZ-"
    )

    init_db()

    with get_connection() as conn:
        vod_min_upload_date = get_first_episode_matched_vod_date(
            conn,
            MATCH_CONFIDENCE_CUTOFF,
        )

        if args.deep_vod_match:
            run_deep_vod_matching(
                conn,
                vod_min_upload_date=vod_min_upload_date,
            )
            export_matches_html(conn)
            conn.commit()
            print("Done")
            return

        removed_non_distinct_matches = (
            remove_non_distinct_long_episode_matches(conn)
        )
        if removed_non_distinct_matches:
            print(
                "[long-episode-match] Removed "
                f"{removed_non_distinct_matches} match(es) where the long "
                "episode was not more than "
                f"{LONG_EPISODE_DURATION_TOLERANCE_SECONDS} seconds longer"
            )
            conn.commit()

        if vod_min_upload_date is not None:
            pruned_vods, pruned_segments = prune_vods_before_date(
                conn,
                vod_min_upload_date,
            )
            if pruned_vods:
                print(
                    f"[vod] Pruned {pruned_vods} VOD(s) and "
                    f"{pruned_segments} transcript segment(s) before "
                    f"{vod_min_upload_date}"
                )
            conn.commit()

        process_source(
            conn,
            vod_source_url,
            kind="vod",
            min_upload_date=vod_min_upload_date,
        )
        process_source(conn, episode_source_url, kind="episode")
        process_source(conn, long_episode_source_url, kind="episode_long")

        transcript_fetches = fetch_missing_transcripts_with_budget(
            conn,
            vod_limit=2,
            episode_limit=2,
            long_episode_limit=2,
            vod_min_upload_date=vod_min_upload_date,
        )

        newly_long_matched_episode_ids = run_long_episode_matching(
            conn,
            new_episode_transcript_ids=transcript_fetches.episode_ids,
            new_long_episode_transcript_ids=transcript_fetches.long_episode_ids,
        )
        removed_non_distinct_matches = (
            remove_non_distinct_long_episode_matches(conn)
        )
        if removed_non_distinct_matches:
            print(
                "[long-episode-match] Marked "
                f"{removed_non_distinct_matches} equivalent upload(s) "
                "as not needed"
            )
            conn.commit()
            newly_long_matched_episode_ids -= (
                get_excluded_long_episode_match_ids(conn)
            )

        run_matching(
            conn,
            new_vod_transcript_ids=transcript_fetches.vod_ids,
            newly_long_matched_episode_ids=newly_long_matched_episode_ids,
            vod_min_upload_date=vod_min_upload_date,
        )
        export_matches_html(conn)

        conn.commit()

    print("Done")
