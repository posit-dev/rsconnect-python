"""
Public API for administering content.
"""

from __future__ import annotations

import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Iterator, Literal, Optional, Sequence, cast

import semver

from .api import RSConnectClient, RSConnectServer, emit_task_log
from .exception import RSConnectException
from .log import logger
from .metadata import ContentBuildStore, ContentItemWithBuildState
from .models import (
    BuildStatus,
    ContentGuidWithBundle,
    ContentItemV1,
    VersionSearchFilter,
)

_content_build_store: ContentBuildStore | None = None


def content_build_store() -> ContentBuildStore:
    if _content_build_store is None:
        raise RSConnectException("_content_build_store has not been initialized.")
    return _content_build_store


def ensure_content_build_store(connect_server: RSConnectServer) -> ContentBuildStore:
    global _content_build_store
    if not _content_build_store:
        logger.info("Initializing ContentBuildStore for %s" % connect_server.url)
        _content_build_store = ContentBuildStore(connect_server)
    return _content_build_store


def build_add_content(
    connect_server: RSConnectServer,
    content_guids_with_bundle: Sequence[ContentGuidWithBundle],
):
    """
    :param content_guids_with_bundle: Union[tuple[models.ContentGuidWithBundle], list[models.ContentGuidWithBundle]]
    """
    build_store = ensure_content_build_store(connect_server)
    with RSConnectClient(connect_server) as client:
        if len(content_guids_with_bundle) == 1:
            all_content = [client.content_get(content_guids_with_bundle[0].guid)]
        else:
            # if bulk-adding then we just do client side filtering so that we
            # dont have to make so many requests to connect.
            all_content = client.search_content()

        # always filter just in case it's a bulk add
        guids_to_add = list(map(lambda x: x.guid, content_guids_with_bundle))
        content_to_add_list = list(filter(lambda x: x["guid"] in guids_to_add, all_content))

        # merge the provided bundle_ids if they were specified
        content_to_add = {c["guid"]: c for c in content_to_add_list}
        for c in content_guids_with_bundle:
            current_bundle_id = content_to_add[c.guid]["bundle_id"]
            content_to_add[c.guid]["bundle_id"] = c.bundle_id if c.bundle_id else current_bundle_id

        for content in content_to_add.values():
            if not content["bundle_id"]:
                raise RSConnectException(
                    "This content has never been published to this server. "
                    + "You must specify a bundle_id for the build. Content GUID: %s" % content["guid"]
                )
            build_store.add_content_item(content)
            build_store.set_content_item_build_status(content["guid"], BuildStatus.NEEDS_BUILD)


def _validate_build_rm_args(guid: Optional[str], all: bool, purge: bool):
    if guid and all:
        raise RSConnectException("You must specify only one of -g/--guid or --all, not both.")
    if not guid and not all:
        raise RSConnectException("You must specify one of -g/--guid or --all.")


def build_remove_content(
    connect_server: RSConnectServer,
    guid: Optional[str],
    all: bool,
    purge: bool,
) -> list[str]:
    """
    :return: A list of guids of the content items that were removed
    """

    # Make sure that either `guid` is a string or `all == True`, but not both.
    _validate_build_rm_args(guid, all, purge)

    build_store = ensure_content_build_store(connect_server)
    guids: list[str]
    if all:
        guids = [c["guid"] for c in build_store.get_content_items()]
    else:
        # If we got here, we know `guid` is not None.
        guids = [cast(str, guid)]
    for guid in guids:
        build_store.remove_content_item(guid, purge)
    return guids


def build_list_content(connect_server: RSConnectServer, guid: str, status: Optional[str]):
    build_store = ensure_content_build_store(connect_server)
    if guid:
        return [build_store.get_content_item(g) for g in guid]
    else:
        return build_store.get_content_items(status=status)


def build_history(connect_server: RSConnectServer, guid: str):
    return ensure_content_build_store(connect_server).get_build_history(guid)


def build_start(
    connect_server: RSConnectServer,
    parallelism: int,
    aborted: bool = False,
    error: bool = False,
    running: bool = False,
    retry: bool = False,
    all: bool = False,
    poll_wait: int = 1,
    debug: bool = False,
    force: bool = False,
):
    build_store = ensure_content_build_store(connect_server)
    if build_store.get_build_running() and not force:
        raise RSConnectException(
            "A content build operation targeting '%s' is still running, or exited abnormally. "
            "Use the '--force' option to override this check." % connect_server.url
        )

    # if we are re-building any already "tracked" content items, then re-add them to be safe
    if all:
        logger.info("Adding all content to build...")
        all_content = build_store.get_content_items()
        all_content = list(map(lambda x: ContentGuidWithBundle(x["guid"], x["bundle_id"]), all_content))
        build_add_content(connect_server, all_content)
    else:
        # --retry is shorthand for --aborted --error --running
        if retry:
            aborted = True
            error = True
            running = True

        aborted_content = []
        if aborted:
            logger.info("Adding ABORTED content to build...")
            aborted_content = build_store.get_content_items(status=BuildStatus.ABORTED)
            aborted_content = list(map(lambda x: ContentGuidWithBundle(x["guid"], x["bundle_id"]), aborted_content))
        error_content = []
        if error:
            logger.info("Adding ERROR content to build...")
            error_content = build_store.get_content_items(status=BuildStatus.ERROR)
            error_content = list(map(lambda x: ContentGuidWithBundle(x["guid"], x["bundle_id"]), error_content))
        running_content = []
        if running:
            logger.info("Adding RUNNING content to build...")
            running_content = build_store.get_content_items(status=BuildStatus.RUNNING)
            running_content = list(map(lambda x: ContentGuidWithBundle(x["guid"], x["bundle_id"]), running_content))

        if len(aborted_content + error_content + running_content) > 0:
            build_add_content(connect_server, aborted_content + error_content + running_content)

    content_items = build_store.get_content_items(status=BuildStatus.NEEDS_BUILD)
    if len(content_items) == 0:
        logger.info("Nothing to build...")
        logger.info("\tUse `rsconnect content build add` to mark content for build.")
        return

    build_monitor = None
    content_executor = None
    try:
        logger.info("Starting content build (%s)..." % connect_server.url)
        build_store.set_build_running(True)

        # spawn a single thread to monitor progress and report feedback to the user
        build_monitor = ThreadPoolExecutor(max_workers=1)
        summary_future = build_monitor.submit(_monitor_build, connect_server, content_items)

        # TODO: stagger concurrent builds so the first batch of builds don't start at the exact same time.
        #   this would help resolve a race condidition in the packrat cache.
        #   or we could just re-run the build...

        # https://docs.python.org/3/library/concurrent.futures.html#threadpoolexecutor-example
        #   spawn a pool of worker threads to perform the content builds
        content_executor = ThreadPoolExecutor(max_workers=parallelism)
        build_result_futures = {
            content_executor.submit(_build_content_item, connect_server, content, poll_wait): ContentGuidWithBundle(
                content["guid"], content["bundle_id"]
            )
            for content in content_items
        }
        for future in as_completed(build_result_futures):
            guid_with_bundle = build_result_futures[future]
            try:
                future.result()
            except Exception as exc:
                # catch any unexpected exceptions from the future thread
                build_store.set_content_item_build_status(guid_with_bundle.guid, BuildStatus.ERROR)
                logger.error("%s generated an exception: %s" % (guid_with_bundle, exc))
                if debug:
                    logger.error(traceback.format_exc())

        # all content builds are finished, mark the build as complete
        build_store.set_build_running(False)

        # wait for the build_monitor thread to resolve its future
        try:
            success = summary_future.result()
        except Exception as exc:
            logger.error(exc)
            success = False

        logger.info("Content build complete.")
        if not success:
            exit(1)
    except KeyboardInterrupt:
        ContentBuildStore._BUILD_ABORTED = True
        logger.info("Content build interrupted...")
        logger.info(
            "Content that was in the RUNNING state may still be building on the "
            + "Connect server. Server builds will not be interrupted."
        )
        logger.info(
            "To find content items that _may_ still be running on the server, "
            + "use: rsconnect content build ls --status RUNNING"
        )
        logger.info(
            "To retry the content build, including items that were interrupted "
            + "or failed, use: rsconnect content build run --retry"
        )
    finally:
        # make sure that we always mark the build as complete but note
        # there's no guarantee that the content_executor or build_monitor
        # were allowed to shut down gracefully, they may have been interrupted.
        build_store.set_build_running(False)
        if content_executor:
            content_executor.shutdown(wait=False)
        if build_monitor:
            build_monitor.shutdown()


def _monitor_build(connect_server: RSConnectServer, content_items: list[ContentItemWithBuildState]):
    """
    :return bool: True if the build completed without errors, False otherwise
    """
    build_store = ensure_content_build_store(connect_server)
    complete = []
    error = []
    start = datetime.now()
    while build_store.get_build_running() and not build_store.aborted():
        time.sleep(5)
        complete = [item for item in content_items if item["rsconnect_build_status"] == BuildStatus.COMPLETE]
        error = [item for item in content_items if item["rsconnect_build_status"] == BuildStatus.ERROR]
        running = [item for item in content_items if item["rsconnect_build_status"] == BuildStatus.RUNNING]
        pending = [item for item in content_items if item["rsconnect_build_status"] == BuildStatus.NEEDS_BUILD]
        logger.info(
            "Running = %d, Pending = %d, Success = %d, Error = %d"
            % (len(running), len(pending), len(complete), len(error))
        )

    if build_store.aborted():
        logger.warning("Build interrupted!")
        aborted_builds = [i["guid"] for i in content_items if i["rsconnect_build_status"] == BuildStatus.RUNNING]
        if len(aborted_builds) > 0:
            logger.warning("Marking %d builds as ABORTED..." % len(aborted_builds))
            for guid in aborted_builds:
                logger.warning("Build aborted: %s" % guid)
                build_store.set_content_item_build_status(guid, BuildStatus.ABORTED)
        return False

    # TODO: print summary as structured json object instead of a string when
    #   format = json so that it is easily parsed by log aggregators
    current = datetime.now()
    duration = current - start
    # construct a new delta w/o millis since timedelta doesn't allow strfmt
    rounded_duration = timedelta(seconds=duration.seconds)
    logger.info(
        "%d/%d content builds completed in %s" % (len(complete) + len(error), len(content_items), rounded_duration)
    )
    logger.info("Success = %d, Error = %d" % (len(complete), len(error)))
    if len(error) > 0:
        logger.error("There were %d failures during your build." % len(error))
        return False
    return True


def _build_content_item(connect_server: RSConnectServer, content: ContentItemWithBuildState, poll_wait: int):
    build_store = ensure_content_build_store(connect_server)
    with RSConnectClient(connect_server) as client:
        # Pending futures will still try to execute when ThreadPoolExecutor.shutdown() is called
        # so just exit immediately if the current build has been aborted.
        # ThreadPoolExecutor.shutdown(cancel_futures=) isnt available until py3.9
        if build_store.aborted():
            return

        guid = content["guid"]
        logger.info("Starting build: %s" % guid)
        build_store.update_content_item_last_build_time(guid)
        build_store.set_content_item_build_status(guid, BuildStatus.RUNNING)
        build_store.ensure_logs_dir(guid)
        try:
            task_result = client.content_build(guid, content.get("bundle_id"))
            task_id = task_result["task_id"]
        except RSConnectException:
            # if we can't submit the build to connect then there is no log file
            # created on disk. When this happens we need to set the last_build_log
            # to None so its clear that we submitted a build but it never started
            build_store.update_content_item_last_build_log(guid, None)
            raise
        log_file = build_store.get_build_log(guid, task_id)
        if log_file is None:
            raise RSConnectException("Log file not found for content: %s" % guid)
        with open(log_file, "w") as log:

            def write_log(line: str):
                log.write("%s\n" % line)

            _, _, task = emit_task_log(
                connect_server,
                guid,
                task_id,
                log_callback=write_log,
                abort_func=build_store.aborted,
                poll_wait=poll_wait,
                raise_on_error=False,
            )
        build_store.update_content_item_last_build_log(guid, log_file)

        if build_store.aborted():
            return

        build_store.set_content_item_last_build_task_result(guid, task)
        if task["code"] != 0:
            logger.error("Build failed: %s" % guid)
            build_store.set_content_item_build_status(guid, BuildStatus.ERROR)
        else:
            logger.info("Build succeeded: %s" % guid)
            build_store.set_content_item_build_status(guid, BuildStatus.COMPLETE)


def emit_build_log(
    connect_server: RSConnectServer,
    guid: str,
    format: str,
    task_id: Optional[str] = None,
):
    build_store = ensure_content_build_store(connect_server)
    log_file = build_store.get_build_log(guid, task_id)
    if log_file:
        with open(log_file, "r") as f:
            for line in f.readlines():
                if format == "json":
                    yield json.dumps({"message": line}) + "\n"
                else:
                    yield line
    else:
        raise RSConnectException("Log file not found for content: %s" % guid)


def download_bundle(connect_server: RSConnectServer, guid_with_bundle: ContentGuidWithBundle):
    """
    :param guid_with_bundle: models.ContentGuidWithBundle
    """
    with RSConnectClient(connect_server) as client:
        # bundle_id not provided so grab the latest
        if not guid_with_bundle.bundle_id:
            content = client.get_content(guid_with_bundle.guid)
            if "bundle_id" in content and content["bundle_id"]:
                guid_with_bundle.bundle_id = content["bundle_id"]
            else:
                raise RSConnectException(
                    "There is no current bundle available for this content: %s" % guid_with_bundle.guid
                )

        return client.download_bundle(guid_with_bundle.guid, guid_with_bundle.bundle_id)


def get_content(connect_server: RSConnectServer, guid: str | list[str]):
    """
    :param guid: a single guid as a string or list of guids.
    :return: a list of content items.
    """
    with RSConnectClient(connect_server) as client:
        if isinstance(guid, str):
            result = [client.get_content(guid)]
        else:
            result = [client.get_content(g) for g in guid]
        return result


def search_content(
    connect_server: RSConnectServer,
    published: bool,
    unpublished: bool,
    content_type: Sequence[str],
    r_version: Optional[VersionSearchFilter],
    py_version: Optional[VersionSearchFilter],
    title_contains: Optional[str],
    order_by: Optional[Literal["created", "last_deployed"]],
):
    with RSConnectClient(connect_server) as client:
        result = client.search_content()
        result = _apply_content_filters(
            result, published, unpublished, content_type, r_version, py_version, title_contains
        )
        return _order_content_results(result, order_by)


def _apply_content_filters(
    content_list: list[ContentItemV1],
    published: bool,
    unpublished: bool,
    content_type: Sequence[str],
    r_version: Optional[VersionSearchFilter],
    py_version: Optional[VersionSearchFilter],
    title_search: Optional[str],
) -> Iterator[ContentItemV1]:
    def content_is_published(item: ContentItemV1):
        return item.get("bundle_id") is not None

    def content_is_unpublished(item: ContentItemV1):
        return item.get("bundle_id") is None

    def title_contains(item: ContentItemV1):
        if title_search is None:
            return True
        return item["title"] is not None and title_search in item["title"]

    def apply_content_type_filter(item: ContentItemV1):
        return item["app_mode"] is not None and item["app_mode"] in content_type

    def apply_version_filter(items: Iterator[ContentItemV1], version_filter: VersionSearchFilter):
        def do_filter(item: ContentItemV1) -> bool:
            vers = None
            if version_filter.name not in item:
                return False
            else:
                vers = cast(str, item[version_filter.name])
            try:
                compare = cast(
                    Literal[-1, 0, 1],
                    semver.compare(vers, version_filter.vers),  # pyright: ignore[reportUnknownMemberType]
                )
            except (ValueError, TypeError):
                return False

            if version_filter.comp == ">":
                return compare == 1
            elif version_filter.comp == "<":
                return compare == -1
            elif version_filter.comp in ["=", "=="]:
                return compare == 0
            elif version_filter.comp == "<=":
                return compare <= 0
            elif version_filter.comp == ">=":
                return compare >= 0
            return False

        return filter(do_filter, items)

    result = iter(content_list)
    if published:
        result = filter(content_is_published, result)
    if unpublished:
        result = filter(content_is_unpublished, result)
    if content_type:
        result = filter(apply_content_type_filter, result)
    if title_search:
        result = filter(title_contains, result)
    if r_version:
        result = apply_version_filter(result, r_version)
    if py_version:
        result = apply_version_filter(result, py_version)
    return result


def _order_content_results(
    content_list: Iterator[ContentItemV1],
    order_by: Optional[Literal["created", "last_deployed"]],
) -> list[ContentItemV1]:
    result = content_list
    if order_by == "last_deployed":
        pass  # do nothing, content is ordered by last_deployed by default
    elif order_by == "created":
        result = sorted(result, key=lambda c: c["created_time"], reverse=True)

    return list(result)
