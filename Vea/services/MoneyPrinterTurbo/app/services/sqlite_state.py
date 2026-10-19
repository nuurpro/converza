"""Durable approved-render receipts for the single-process renderer.

Use the persistent storage volume. On process startup, unfinished local threads
cannot resume: their receipts become definitive failures. Completed outputs and
immutable bindings remain readable so Converza can reconcile without a new POST.
"""
from contextlib import contextmanager, closing
import json
import os
from pathlib import Path
import sqlite3


class SQLiteState:
    def __init__(self, filename):
        self.filename = str(filename)
        self._runtime_lock = None
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, data TEXT NOT NULL)')

    def start_runtime(self):
        """Called once by ASGI startup, never by ordinary state clients."""
        if self._runtime_lock is not None:
            return
        handle = open(self.filename + '.lock', 'a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                if handle.tell() == 0:
                    handle.write(b'0');handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise RuntimeError('Only one approved renderer process may use this task storage volume') from exc
        self._runtime_lock = handle
        try:
            self._recover_interrupted()
        except BaseException:
            self.stop_runtime()
            raise

    def stop_runtime(self):
        if self._runtime_lock is not None:
            self._runtime_lock.close()
            self._runtime_lock = None

    def _recover_interrupted(self):
        with self._transaction() as connection:
            for task_id, raw in connection.execute('SELECT id,data FROM tasks').fetchall():
                task = json.loads(raw)
                if task.get('state') not in (-1, 1):
                    task.update(state=-1, error_code='renderer_restarted')
                    connection.execute('UPDATE tasks SET data=? WHERE id=?', (json.dumps(task, ensure_ascii=False), task_id))

    @contextmanager
    def _transaction(self):
        with closing(sqlite3.connect(self.filename, timeout=30)) as connection:
            connection.execute('PRAGMA busy_timeout=30000')
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('BEGIN IMMEDIATE')
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def update_task(self, task_id, state=4, progress=0, **kwargs):
        with self._transaction() as connection:
            previous = connection.execute('SELECT data FROM tasks WHERE id=?', (task_id,)).fetchone()
            task = json.loads(previous[0]) if previous else {}
            binding = task.get('milo_binding')
            if binding is not None and 'milo_binding' in kwargs and kwargs['milo_binding'] != binding:
                raise ValueError('Approved task binding is immutable')
            task.update(kwargs)
            task.update(task_id=task_id, state=state, progress=max(0, min(int(progress), 100)))
            connection.execute('INSERT INTO tasks(id,data) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                               (task_id, json.dumps(task, ensure_ascii=False)))

    def get_task(self, task_id):
        with closing(sqlite3.connect(self.filename, timeout=30)) as connection:
            row = connection.execute('SELECT data FROM tasks WHERE id=?', (task_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def get_all_tasks(self, page, page_size):
        with closing(sqlite3.connect(self.filename, timeout=30)) as connection:
            count = connection.execute('SELECT count(*) FROM tasks').fetchone()[0]
            rows = connection.execute('SELECT data FROM tasks ORDER BY rowid LIMIT ? OFFSET ?',
                                      (page_size, (page - 1) * page_size)).fetchall()
        return [json.loads(row[0]) for row in rows], count

    def delete_task(self, task_id):
        with self._transaction() as connection:
            connection.execute('DELETE FROM tasks WHERE id=?', (task_id,))
