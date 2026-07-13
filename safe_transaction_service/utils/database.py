# SPDX-License-Identifier: FSL-1.1-MIT


def close_unusable_or_obsolete_connections() -> None:
    """
    Return obsolete DB connections of the current execution context to the pool.

    Mirrors Django's per-request cleanup for contexts that have no
    ``request_finished`` lifecycle hook, such as Celery tasks (see
    ``config.celery_app.close_db_connections``). With ``CONN_MAX_AGE=0`` every
    connection is eligible for closure, returning the psycopg3 pool slot
    immediately.

    Connections inside an atomic block are skipped: closing them would break the
    surrounding transaction (and test isolation, as ``TestCase`` wraps each test
    in one). ``close_if_unusable_or_obsolete`` is a no-op when no connection was
    opened, so calling this is always cheap.

    ``django.db`` is imported lazily so importing this module (and, transitively,
    ``config.celery_app``) does not pull ``django.db`` into ``sys.modules`` before
    Django is set up.

    :return:
    """
    from django.db import connections

    for conn in connections.all(initialized_only=True):
        if not conn.in_atomic_block:
            conn.close_if_unusable_or_obsolete()
