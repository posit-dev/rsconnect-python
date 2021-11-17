"""
Public API for administering content.
"""
import contextlib
import json
import time
import sys

# This probably breaks python2, can we remove python2.7 support from setup and/or can we require >3 for only the admin tool?
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
#from multiprocessing.pool import ThreadPool

import click
import semver

from rsconnect import api
from .models import RebuildStatus
from .metadata import ContentRebuildStore

content_rebuild_store = ContentRebuildStore()

def rebuild_add_content(connect_server, guid, bundle_id):
    content = api.do_content_get(connect_server, guid)
    if not bundle_id and not content['bundle_id']:
        raise api.RSConnectException("This content has never been published to this server. You must specify a bundle_id for the rebuild. Content GUID: %s" % guid)
    else:
        bundle_id = bundle_id if bundle_id else content['bundle_id']

    if content_rebuild_store.get_rebuild_running(connect_server):
        raise api.RSConnectException("There is already a rebuild running on this server, please wait for it to finish before adding new content.")

    # TODO: should add_content_item should merge with existing items?
    content_rebuild_store.add_content_item(connect_server, content, bundle_id)
    content_rebuild_store.set_content_item_rebuild_status(connect_server, content['guid'], RebuildStatus.NEEDS_REBUILD)


def rebuild_remove_content(connect_server, guid, purge=False):
    if content_rebuild_store.get_rebuild_running(connect_server):
        raise api.RSConnectException("There is a rebuild running on this server, please wait for it to finish before removing content.")
    content_rebuild_store.remove_content_item(connect_server, guid, purge)


def rebuild_list_content(connect_server, status):
    return content_rebuild_store.get_content_items(connect_server, status=status)


def rebuild_history(connect_server, guid):
    return content_rebuild_store.get_rebuild_history(connect_server, guid)


def rebuild_start(connect_server, parallelism, resume=False, debug=False):
    if content_rebuild_store.get_rebuild_running(connect_server):
        raise api.RSConnectException("There is already a rebuild running on this server: %s" % connect_server.url)

    content_items = content_rebuild_store.get_content_items(connect_server, status=RebuildStatus.NEEDS_REBUILD)
    if resume:
        content_items = content_items + content_rebuild_store.get_content_items(connect_server, status=RebuildStatus.ABORTED)

    if len(content_items) == 0:
        click.secho("Nothing to rebuild...")
        click.secho("\tUse `rsconnect-admin rebuild add` to mark content for rebuild.")
        return

    rebuild_monitor = None
    content_executor = None
    try:
        click.secho("Starting content rebuild (%s)..." % connect_server.url)
        content_rebuild_store.set_rebuild_running(connect_server, True)

        # spawn a single thread to monitor progress and report feedback to the user
        rebuild_monitor = ThreadPoolExecutor(max_workers=1)
        summary_future = rebuild_monitor.submit(_monitor_rebuild, connect_server, content_items)

        # https://docs.python.org/3/library/concurrent.futures.html#threadpoolexecutor-example
        # spawn a pool of worker threads to perform the content rebuilds
        content_executor = ThreadPoolExecutor(max_workers=parallelism)
        rebuild_result_futures = {content_executor.submit(_rebuild_content_item, connect_server, content): content['guid'] for content in content_items}
        for future in as_completed(rebuild_result_futures):
            guid = rebuild_result_futures[future]
            try:
                future.result()
            except Exception as exc:
                content_rebuild_store.set_content_item_rebuild_status(connect_server, guid, RebuildStatus.ERROR)
                if debug: # TODO: should use logger.debug?
                    click.secho('%s generated an exception: %s' % (guid, exc), fg="red", err=True)

        # all content rebuilds are finished, mark the rebuild as complete
        content_rebuild_store.set_rebuild_running(connect_server, False)

        # wait for rebuild to complete
        try:
            success = summary_future.result()
        except Exception as exc:
            if debug: # TODO: should use logger.debug?
                click.secho(exc, fg="red")

        click.secho("\nContent rebuild complete.")
        if not success:
            exit(1)
    except KeyboardInterrupt:
        ContentRebuildStore._REBUILD_ABORTED = True
    finally:
        if content_executor:
            content_executor.shutdown(wait=False, cancel_futures=True)
        if rebuild_monitor:
            rebuild_monitor.shutdown()
        # make sure that we always mark the rebuild as complete once we finish our cleanup
        content_rebuild_store.set_rebuild_running(connect_server, False)


def _monitor_rebuild(connect_server, content_items):
    """
    :return bool: True if the rebuild completed without errors, False otherwise
    """
    click.secho()
    start = datetime.now()
    while content_rebuild_store.get_rebuild_running(connect_server) and not content_rebuild_store.aborted():
        current = datetime.now()
        duration = current - start
        # construct a new delta w/o millis since timedelta doesn't allow strfmt
        rounded_duration = timedelta(seconds=duration.seconds)
        time.sleep(0.5)
        complete = [item for item in content_items if item['rsconnect_rebuild_status'] == RebuildStatus.COMPLETE]
        error = [item for item in content_items if item['rsconnect_rebuild_status'] == RebuildStatus.ERROR]
        running = [item for item in content_items if item['rsconnect_rebuild_status'] == RebuildStatus.RUNNING]
        pending = [item for item in content_items if item['rsconnect_rebuild_status'] == RebuildStatus.NEEDS_REBUILD]
        click.secho("Content rebuild in progress... Running = %d, Pending = %d, Success = %d, Error = %d\t\t%s\r" %
            (len(running), len(pending), len(complete), len(error), rounded_duration), nl=False)

    if content_rebuild_store.aborted():
        click.secho()
        click.secho("Rebuild interrupted! Marking running rebuilds as ABORTED...")
        aborted_rebuilds = [i['guid'] for i in content_items if i['rsconnect_rebuild_status'] == RebuildStatus.RUNNING]
        if len(aborted_rebuilds) > 0:
            click.secho("\tUse `rsconnect-admin rebuild start --resume` to retry the aborted rebuilds.")
            click.secho("Aborted rebuilds:")
            for guid in aborted_rebuilds:
                click.secho("\t%s" % guid)
                content_rebuild_store.set_content_item_rebuild_status(connect_server, guid, RebuildStatus.ABORTED)
        return False

    click.secho()
    click.secho()
    click.secho("%d/%d content rebuilds completed in %s" % (len(complete) + len(error), len(content_items), rounded_duration))
    click.secho("Success = %d, Error = %d" % (len(complete), len(error)))
    if len(error) > 0:
        click.secho()
        click.secho("There were failures during your rebuild.")
        click.secho("\tUse `rsconnect-admin rebuild logs --guid` to check the rebuild logs.")
        click.secho()
        click.secho("Failed content:")
        for c in error:
            click.secho("\tContent Name: %s, GUID: %s" % (c['name'], c['guid']))
        return False
    return True


def _rebuild_content_item(connect_server, content, timeout=None):
    guid = content['guid']
    content_rebuild_store.ensure_logs_dir(connect_server, guid)
    content_rebuild_store.set_content_item_rebuild_status(connect_server, guid, RebuildStatus.RUNNING)
    task_result = api.do_start_content_rebuild(connect_server, guid, content.get('bundle_id'))
    task_id = task_result.json_data['task_id']
    log_file = content_rebuild_store.get_rebuild_log(connect_server, guid, task_id)
    with open(log_file, 'w') as log:
        # emit_task_log raises an exception if exit_code != 0
        api.emit_task_log(connect_server, guid, task_id,
            log_callback=lambda line: log.write("%s\n" % line), abort_func=content_rebuild_store.aborted)

    if content_rebuild_store.aborted():
        return

    # grab the updated content metadata from connect and update our store
    updated_content = api.do_content_get(connect_server, guid)
    content_rebuild_store.update_content_item(connect_server, guid, updated_content)
    content_rebuild_store.set_content_item_rebuild_status(connect_server, guid, RebuildStatus.COMPLETE)


def emit_rebuild_log(connect_server, guid, format, task_id=None):
    log_file = content_rebuild_store.get_rebuild_log(connect_server, guid, task_id)
    if log_file:
        with open(log_file, 'r') as f:
            for line in f.readlines():
                if format == "json":
                    yield json.dumps({"message": line}) + "\n"
                else:
                    yield line
    else:
        raise api.RSConnectException("Log file not found for content: %s" % guid)


def download_bundle(connect_server, guid, bundle_id):
    # bundle_id not provided so grab the latest
    if not bundle_id:
        content = api.do_content_get(connect_server, guid)
        if 'bundle_id' in content and content['bundle_id']:
            bundle_id = content['bundle_id']
        else:
            raise api.RSConnectException("There is no current bundle available for this content: %s" % guid)

    return api.do_bundle_download(connect_server, guid, bundle_id)


def get_content(connect_server, guid):
    """
    :param guid: a single guid as a string or list of guids.
    :return: a list of content items.
    """
    if isinstance(guid, str):
        result = [api.do_content_get(connect_server, guid)]
    else:
        result = [api.do_content_get(connect_server, g) for g in guid]
    return result


def search_content(connect_server, published, unpublished, content_type, r_version, py_version, title_contains, order_by):
    result = api.do_content_search(connect_server)
    result = _apply_content_filters(result, published, unpublished, content_type, r_version, py_version, title_contains)
    result = _order_content_results(result, order_by)
    return list(result)


def _apply_content_filters(content_list, published, unpublished, content_type, r_version, py_version, title_search):
    def content_is_published(item):
        return 'bundle_id' in item and item['bundle_id'] != None

    def content_is_unpublished(item):
        if 'bundle_id' not in item:
            return False
        else:
            return item['bundle_id'] == None

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


# https://stackoverflow.com/questions/17602878/how-to-handle-both-with-open-and-sys-stdout-nicely
@contextlib.contextmanager
def open_file_or_stdout(filename=None):
    if filename and filename != '-':
        fh = open(filename, 'w')
    else:
        fh = sys.stdout

    try:
        yield fh
    finally:
        if fh is not sys.stdout:
            fh.close()
