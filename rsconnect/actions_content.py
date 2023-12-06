"""
Public API for administering content.
"""
import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import semver

from .api import RSConnectClient, emit_task_log
from .log import logger
from .models import BuildStatus, ContentGuidWithBundle
from .metadata import ContentBuildStore
from .exception import RSConnectException

_content_build_store = None  # type: ContentBuildStore


def init_content_build_store(connect_server):
    global _content_build_store
    if not _content_build_store:
        logger.info("Initializing ContentBuildStore for %s" % connect_server.url)
        _content_build_store = ContentBuildStore(connect_server)


def build_add_content(connect_server, content_guids_with_bundle):
    """
    :param content_guids_with_bundle: Union[tuple[models.ContentGuidWithBundle], list[models.ContentGuidWithBundle]]
    """
    init_content_build_store(connect_server)
    if _content_build_store.get_build_running():
        raise RSConnectException(
            "There is already a build running on this server, "
            + "please wait for it to finish before adding new content."
        )

    with RSConnectClient(connect_server) as client:
        if len(content_guids_with_bundle) == 1:
            all_content = [client.content_get(content_guids_with_bundle[0].guid)]
        else:
            # if bulk-adding then we just do client side filtering so that we
            # dont have to make so many requests to connect.
            all_content = client.search_content()

        # always filter just in case it's a bulk add
        guids_to_add = list(map(lambda x: x.guid, content_guids_with_bundle))
        content_to_add = list(filter(lambda x: x["guid"] in guids_to_add, all_content))

        # merge the provided bundle_ids if they were specified
        content_to_add = {c["guid"]: c for c in content_to_add}
        for c in content_guids_with_bundle:
            current_bundle_id = content_to_add[c.guid]["bundle_id"]
            content_to_add[c.guid]["bundle_id"] = c.bundle_id if c.bundle_id else current_bundle_id

        for content in content_to_add.values():
            if not content["bundle_id"]:
                raise RSConnectException(
                    "This content has never been published to this server. "
                    + "You must specify a bundle_id for the build. Content GUID: %s" % content["guid"]
                )
            _content_build_store.add_content_item(content)
            _content_build_store.set_content_item_build_status(content["guid"], BuildStatus.NEEDS_BUILD)


def build_remove_content(connect_server, guid, all=False, purge=False):
    """
    :return: A list of guids of the content items that were removed
    """
    init_content_build_store(connect_server)
    if _content_build_store.get_build_running():
        raise RSConnectException(
            "There is a build running on this server, " + "please wait for it to finish before removing content."
        )
    guids = [guid]
    if all:
        guids = [c["guid"] for c in _content_build_store.get_content_items()]
    for guid in guids:
        _content_build_store.remove_content_item(guid, purge)
    return guids


def build_list_content(connect_server, guid, status):
    init_content_build_store(connect_server)
    if guid:
        return [_content_build_store.get_content_item(g) for g in guid]
    else:
        return _content_build_store.get_content_items(status=status)


def build_history(connect_server, guid):
    init_content_build_store(connect_server)
    return _content_build_store.get_build_history(guid)


def build_start(
    connect_server,
    parallelism,
    aborted=False,
    error=False,
    running=False,
    retry=False,
    all=False,
    poll_wait=2,
    debug=False,
):
    init_content_build_store(connect_server)
    if _content_build_store.get_build_running():
        raise RSConnectException("There is already a build running on this server: %s" % connect_server.url)

    # if we are re-building any already "tracked" content items, then re-add them to be safe
    if all:
        logger.info("Adding all content to build...")
        all_content = _content_build_store.get_content_items()
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
            aborted_content = _content_build_store.get_content_items(status=BuildStatus.ABORTED)
            aborted_content = list(map(lambda x: ContentGuidWithBundle(x["guid"], x["bundle_id"]), aborted_content))
        error_content = []
        if error:
            logger.info("Adding ERROR content to build...")
            error_content = _content_build_store.get_content_items(status=BuildStatus.ERROR)
            error_content = list(map(lambda x: ContentGuidWithBundle(x["guid"], x["bundle_id"]), error_content))
        running_content = []
        if running:
            logger.info("Adding RUNNING content to build...")
            running_content = _content_build_store.get_content_items(status=BuildStatus.RUNNING)
            running_content = list(map(lambda x: ContentGuidWithBundle(x["guid"], x["bundle_id"]), running_content))

        if len(aborted_content + error_content + running_content) > 0:
            build_add_content(connect_server, aborted_content + error_content + running_content)

    content_items = _content_build_store.get_content_items(status=BuildStatus.NEEDS_BUILD)
    if len(content_items) == 0:
        logger.info("Nothing to build...")
        logger.info("\tUse `rsconnect content build add` to mark content for build.")
        return

    build_monitor = None
    content_executor = None
    try:
        logger.info("Starting content build (%s)..." % connect_server.url)
        _content_build_store.set_build_running(True)

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
                _content_build_store.set_content_item_build_status(guid_with_bundle.guid, BuildStatus.ERROR)
                logger.error("%s generated an exception: %s" % (guid_with_bundle, exc))
                if debug:
                    logger.error(traceback.format_exc())

        # all content builds are finished, mark the build as complete
        _content_build_store.set_build_running(False)

        # wait for the build_monitor thread to resolve its future
        try:
            success = summary_future.result()
        except Exception as exc:
            logger.error(exc)

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
        _content_build_store.set_build_running(False)
        if content_executor:
            content_executor.shutdown(wait=False)
        if build_monitor:
            build_monitor.shutdown()


def _monitor_build(connect_server, content_items):
    """
    :return bool: True if the build completed without errors, False otherwise
    """
    init_content_build_store(connect_server)
    start = datetime.now()
    while _content_build_store.get_build_running() and not _content_build_store.aborted():
        time.sleep(5)
        complete = [item for item in content_items if item["rsconnect_build_status"] == BuildStatus.COMPLETE]
        error = [item for item in content_items if item["rsconnect_build_status"] == BuildStatus.ERROR]
        running = [item for item in content_items if item["rsconnect_build_status"] == BuildStatus.RUNNING]
        pending = [item for item in content_items if item["rsconnect_build_status"] == BuildStatus.NEEDS_BUILD]
        logger.info(
            "Running = %d, Pending = %d, Success = %d, Error = %d"
            % (len(running), len(pending), len(complete), len(error))
        )

    if _content_build_store.aborted():
        logger.warn("Build interrupted!")
        aborted_builds = [i["guid"] for i in content_items if i["rsconnect_build_status"] == BuildStatus.RUNNING]
        if len(aborted_builds) > 0:
            logger.warn("Marking %d builds as ABORTED..." % len(aborted_builds))
            for guid in aborted_builds:
                logger.warn("Build aborted: %s" % guid)
                _content_build_store.set_content_item_build_status(guid, BuildStatus.ABORTED)
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


def _build_content_item(connect_server, content, poll_wait):
    init_content_build_store(connect_server)
    with RSConnectClient(connect_server) as client:
        # Pending futures will still try to execute when ThreadPoolExecutor.shutdown() is called
        # so just exit immediately if the current build has been aborted.
        # ThreadPoolExecutor.shutdown(cancel_futures=) isnt available until py3.9
        if _content_build_store.aborted():
            return

        guid = content["guid"]
        logger.info("Starting build: %s" % guid)
        _content_build_store.update_content_item_last_build_time(guid)
        _content_build_store.set_content_item_build_status(guid, BuildStatus.RUNNING)
        _content_build_store.ensure_logs_dir(guid)
        try:
            task_result = client.content_build(guid, content.get("bundle_id"))
            task_id = task_result["task_id"]
        except RSConnectException:
            # if we can't submit the build to connect then there is no log file
            # created on disk. When this happens we need to set the last_build_log
            # to None so its clear that we submitted a build but it never started
            _content_build_store.update_content_item_last_build_log(guid, None)
            raise
        log_file = _content_build_store.get_build_log(guid, task_id)
        with open(log_file, "w") as log:
            _, _, task_status = emit_task_log(
                connect_server,
                guid,
                task_id,
                log_callback=lambda line: log.write("%s\n" % line),
                abort_func=_content_build_store.aborted,
                poll_wait=poll_wait,
                raise_on_error=False,
            )
        _content_build_store.update_content_item_last_build_log(guid, log_file)

        if _content_build_store.aborted():
            return

        _content_build_store.set_content_item_last_build_task_result(guid, task_status)
        if task_status["code"] != 0:
            logger.error("Build failed: %s" % guid)
            _content_build_store.set_content_item_build_status(guid, BuildStatus.ERROR)
        else:
            logger.info("Build succeeded: %s" % guid)
            _content_build_store.set_content_item_build_status(guid, BuildStatus.COMPLETE)


def emit_build_log(connect_server, guid, format, task_id=None):
    init_content_build_store(connect_server)
    log_file = _content_build_store.get_build_log(guid, task_id)
    if log_file:
        with open(log_file, "r") as f:
            for line in f.readlines():
                if format == "json":
                    yield json.dumps({"message": line}) + "\n"
                else:
                    yield line
    else:
        raise RSConnectException("Log file not found for content: %s" % guid)


def download_bundle(connect_server, guid_with_bundle):
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


def get_content(connect_server, guid):
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
    connect_server, published, unpublished, content_type, r_version, py_version, title_contains, order_by
):
    with RSConnectClient(connect_server) as client:
        result = client.search_content()
        result = _apply_content_filters(
            result, published, unpublished, content_type, r_version, py_version, title_contains
        )
        result = _order_content_results(result, order_by)
        return list(result)


def _apply_content_filters(content_list, published, unpublished, content_type, r_version, py_version, title_search):
    def content_is_published(item):
        return item.get("bundle_id") is not None

    def content_is_unpublished(item):
        return item.get("bundle_id") is None

    def title_contains(item):
        return item["title"] is not None and title_search in item["title"]

    def apply_content_type_filter(item):
        return item["app_mode"] is not None and item["app_mode"] in content_type

    def apply_version_filter(items, version_filter):
        def do_filter(item):
            vers = None
            if version_filter.name not in item:
                return False
            else:
                vers = item[version_filter.name]
            try:
                compare = semver.compare(vers, version_filter.vers)
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


def _order_content_results(content_list, order_by):
    result = iter(content_list)
    if order_by == "last_deployed":
        pass  # do nothing, content is ordered by last_deployed by default
    elif order_by == "created":
        result = sorted(result, key=lambda c: c["created_time"], reverse=True)

    return result
