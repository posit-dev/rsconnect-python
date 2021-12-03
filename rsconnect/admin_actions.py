"""
Public API for administering content.
"""
import json
import time
import traceback

# This probably breaks python2, can we remove python2.7 support
# from setup and/or can we require >3 for only the admin tool?
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
#from multiprocessing.pool import ThreadPool

import click
import semver

from .api import (
    RSConnect,
    RSConnectException,
    emit_task_log
)
from .log import logger
from .models import BuildStatus
from .metadata import ContentBuildStore

content_build_store = ContentBuildStore()

def build_add_content(connect_server, guid, bundle_id=None):
    with RSConnect(connect_server, timeout=120) as client:
        content = client.content_get(guid)
        if not bundle_id and not content['bundle_id']:
            raise RSConnectException("This content has never been published to this server. " +
                "You must specify a bundle_id for the build. Content GUID: %s" % guid)
        else:
            bundle_id = bundle_id if bundle_id else content['bundle_id']

        if content_build_store.get_build_running(connect_server):
            raise RSConnectException("There is already a build running on this server, " +
                "please wait for it to finish before adding new content.")

        content_build_store.add_content_item(connect_server, content, bundle_id)
        content_build_store.set_content_item_build_status(connect_server, content['guid'], BuildStatus.NEEDS_BUILD)


def build_remove_content(connect_server, guid, all=False, purge=False):
    if content_build_store.get_build_running(connect_server):
        raise RSConnectException("There is a build running on this server, " +
            "please wait for it to finish before removing content.")
    guids = [guid]
    if all:
        guids = [c['guid'] for c in content_build_store.get_content_items(connect_server)]
    for guid in guids:
        content_build_store.remove_content_item(connect_server, guid, purge)


def build_list_content(connect_server, guid, status):
    if guid:
        return [content_build_store.get_content_item(connect_server, g) for g in guid]
    else:
        return content_build_store.get_content_items(connect_server, status=status)


def build_history(connect_server, guid):
    return content_build_store.get_build_history(connect_server, guid)


def build_start(connect_server, parallelism, aborted=False, error=False, all=False, debug=False):
    if content_build_store.get_build_running(connect_server):
        raise RSConnectException("There is already a build running on this server: %s" % connect_server.url)

    # if we are re-building any already "tracked" content items, then re-add them to be safe
    if all:
        click.secho("Adding all content to build...", err=True)
        # only re-add content that is not already marked NEEDS_BUILD
        items = content_build_store.get_content_items(connect_server)
        items = list(filter(lambda x: x['rsconnect_build_status'] != BuildStatus.NEEDS_BUILD, items))
        for content_item in items:
            build_add_content(connect_server, content_item['guid'], content_item['bundle_id'])
    else:
        if aborted:
            click.secho("Adding ABORTED content to build...", err=True)
            for content_item in content_build_store.get_content_items(connect_server, status=BuildStatus.ABORTED):
                build_add_content(connect_server, content_item['guid'], content_item['bundle_id'])
        if error:
            click.secho("Adding ERROR content to build...", err=True)
            for content_item in content_build_store.get_content_items(connect_server, status=BuildStatus.ERROR):
                build_add_content(connect_server, content_item['guid'], content_item['bundle_id'])

    content_items = content_build_store.get_content_items(connect_server, status=BuildStatus.NEEDS_BUILD)
    if len(content_items) == 0:
        click.secho("Nothing to build...")
        click.secho("\tUse `rsconnect-admin build add` to mark content for build.")
        return

    build_monitor = None
    content_executor = None
    try:
        click.secho("Starting content build (%s)..." % connect_server.url)
        content_build_store.set_build_running(connect_server, True)

        # spawn a single thread to monitor progress and report feedback to the user
        build_monitor = ThreadPoolExecutor(max_workers=1)
        summary_future = build_monitor.submit(_monitor_build, connect_server, content_items)

        # https://docs.python.org/3/library/concurrent.futures.html#threadpoolexecutor-example
        # spawn a pool of worker threads to perform the content builds
        content_executor = ThreadPoolExecutor(max_workers=parallelism)
        build_result_futures = {content_executor.submit(_build_content_item, connect_server, content): content['guid'] for content in content_items}
        for future in as_completed(build_result_futures):
            guid = build_result_futures[future]
            try:
                future.result()
            except Exception as exc:
                # this exception is logged and re-raised from future thread
                content_build_store.set_content_item_build_status(connect_server, guid, BuildStatus.ERROR)
                if debug:
                    logger.error('%s generated an exception: %s' % (guid, exc))
                    logger.error(traceback.format_exc())

        # all content builds are finished, mark the build as complete
        content_build_store.set_build_running(connect_server, False)

        # wait for build to complete
        try:
            success = summary_future.result()
        except Exception as exc:
            logger.error(exc)

        click.secho("\nContent build complete.")
        if not success:
            exit(1)
    except KeyboardInterrupt:
        ContentBuildStore._BUILD_ABORTED = True
    finally:
        if content_executor:
            content_executor.shutdown(wait=False)
        if build_monitor:
            build_monitor.shutdown()
        # make sure that we always mark the build as complete once we finish our cleanup
        content_build_store.set_build_running(connect_server, False)


def _monitor_build(connect_server, content_items):
    """
    :return bool: True if the build completed without errors, False otherwise
    """
    click.secho()
    start = datetime.now()
    while content_build_store.get_build_running(connect_server) and not content_build_store.aborted():
        current = datetime.now()
        duration = current - start
        # construct a new delta w/o millis since timedelta doesn't allow strfmt
        rounded_duration = timedelta(seconds=duration.seconds)
        time.sleep(0.5)
        complete = [item for item in content_items if item['rsconnect_build_status'] == BuildStatus.COMPLETE]
        error = [item for item in content_items if item['rsconnect_build_status'] == BuildStatus.ERROR]
        running = [item for item in content_items if item['rsconnect_build_status'] == BuildStatus.RUNNING]
        pending = [item for item in content_items if item['rsconnect_build_status'] == BuildStatus.NEEDS_BUILD]
        click.secho("\033[KContent build in progress... (%s) Running = %d, Pending = %d, Success = %d, Error = %d\r" %
            (rounded_duration, len(running), len(pending), len(complete), len(error)), nl=False)

    # https://stackoverflow.com/questions/2388090/how-to-delete-and-replace-last-line-in-the-terminal-using-bash
    click.secho('\033[K')
    if content_build_store.aborted():
        click.secho("Build interrupted! Marking running builds as ABORTED...")
        aborted_builds = [i['guid'] for i in content_items if i['rsconnect_build_status'] == BuildStatus.RUNNING]
        if len(aborted_builds) > 0:
            click.secho("\tUse `rsconnect-admin build run --aborted` to retry the aborted builds.")
            click.secho("Aborted builds:")
            for guid in aborted_builds:
                click.secho("\t%s" % guid)
                content_build_store.set_content_item_build_status(connect_server, guid, BuildStatus.ABORTED)
        return False

    click.secho()
    click.secho("%d/%d content builds completed in %s" % (len(complete) + len(error), len(content_items), rounded_duration))
    click.secho("Success = %d, Error = %d" % (len(complete), len(error)))
    if len(error) > 0:
        click.secho()
        click.secho("There were failures during your build.")
        click.secho("\tUse `rsconnect-admin build ls --status=ERROR` to list the failed content.")
        click.secho("\tUse `rsconnect-admin build logs --guid` to check the build logs of a specific content build.")
        # click.secho()
        # click.secho("Failed content:")
        # for c in error:
        #     click.secho("\tName: %s, GUID: %s" % (c['name'], c['guid']))
        return False
    return True


def _build_content_item(connect_server, content):
    with RSConnect(connect_server, timeout=120) as client:
        # Pending futures will still try to execute when ThreadPoolExecutor.shutdown() is called
        # so just exit immediately if the current build has been aborted.
        # ThreadPoolExecutor.shutdown(cancel_futures=) isnt available until py3.9
        if content_build_store.aborted():
                return

        guid = content['guid']
        content_build_store.ensure_logs_dir(connect_server, guid)
        content_build_store.set_content_item_build_status(connect_server, guid, BuildStatus.RUNNING)
        task_result = client.content_build(guid, content.get('bundle_id'))
        task_id = task_result['task_id']
        log_file = content_build_store.get_build_log(connect_server, guid, task_id)
        with open(log_file, 'w') as log:
            # emit_task_log raises an exception if exit_code != 0
            emit_task_log(connect_server, guid, task_id,
                log_callback=lambda line: log.write("%s\n" % line), abort_func=content_build_store.aborted)

        if content_build_store.aborted():
            return

        # grab the updated content metadata from connect and update our store
        updated_content = client.get_content(guid)
        content_build_store.update_content_item(connect_server, guid, updated_content)
        content_build_store.set_content_item_build_status(connect_server, guid, BuildStatus.COMPLETE)


def emit_build_log(connect_server, guid, format, task_id=None):
    log_file = content_build_store.get_build_log(connect_server, guid, task_id)
    if log_file:
        with open(log_file, 'r') as f:
            for line in f.readlines():
                if format == "json":
                    yield json.dumps({"message": line}) + "\n"
                else:
                    yield line
    else:
        raise RSConnectException("Log file not found for content: %s" % guid)


def download_bundle(connect_server, guid, bundle_id):
    with RSConnect(connect_server, timeout=120) as client:
        # bundle_id not provided so grab the latest
        if not bundle_id:
            content = client.get_content(guid)
            if 'bundle_id' in content and content['bundle_id']:
                bundle_id = content['bundle_id']
            else:
                raise RSConnectException("There is no current bundle available for this content: %s" % guid)

        return client.download_bundle(guid, bundle_id)


def get_content(connect_server, guid):
    """
    :param guid: a single guid as a string or list of guids.
    :return: a list of content items.
    """
    with RSConnect(connect_server, timeout=120) as client:
        if isinstance(guid, str):
            result = [client.get_content(guid)]
        else:
            result = [client.get_content(g) for g in guid]
        return result


def search_content(connect_server, published, unpublished, content_type, r_version, py_version, title_contains, order_by):
    with RSConnect(connect_server, timeout=120) as client:
        result = client.search_content()
        result = _apply_content_filters(result, published, unpublished, content_type, r_version, py_version, title_contains)
        result = _order_content_results(result, order_by)
        return list(result)


def _apply_content_filters(content_list, published, unpublished, content_type, r_version, py_version, title_search):
    def content_is_published(item):
        return item.get('bundle_id') is not None

    def content_is_unpublished(item):
        return item.get('bundle_id') is None

    def title_contains(item):
        return item['title'] is not None and title_search in item['title']

    def apply_content_type_filter(item):
        return item['app_mode'] is not None and item['app_mode'] in content_type

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
            elif version_filter.comp == "==":
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
        result = sorted(result, key=lambda c: c['last_deployed_time'])
    elif order_by == "created":
        result = sorted(result, key=lambda c: c['created_time'])

    return result
