"""SQLite job/outbox crash drill. Python standard library only."""
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

KEY = "tenant-A/agent-A/task-7/step-5"

def open_db(path):
    db = sqlite3.connect(path, isolation_level=None, timeout=5)
    db.execute("PRAGMA journal_mode=WAL")
    return db

def init(db):
    db.executescript("""
    CREATE TABLE task(id TEXT PRIMARY KEY, owner TEXT, state TEXT);
    CREATE TABLE job(task_id TEXT PRIMARY KEY, owner TEXT, state TEXT,
        lease_owner TEXT, lease_until INTEGER, claim_epoch INTEGER, checkpoint INTEGER);
    CREATE TABLE provider(key TEXT PRIMARY KEY, result TEXT);
    CREATE TABLE outbox(event_id TEXT PRIMARY KEY, task_id TEXT, sent INTEGER DEFAULT 0);
    CREATE TABLE deliveries(event_id TEXT PRIMARY KEY);
    INSERT INTO task VALUES ('task-7','tenant-A/agent-A','SUBMITTED');
    INSERT INTO job VALUES ('task-7','tenant-A/agent-A','READY',NULL,NULL,0,0);
    """)

def claim(db, worker, now):
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute("""UPDATE job SET state='RUNNING', lease_owner=?,
            lease_until=?, claim_epoch=claim_epoch+1
            WHERE task_id='task-7' AND (state='READY' OR
              (state='RUNNING' AND lease_until < ?))
            RETURNING claim_epoch,checkpoint""", (worker, now+60, now)).fetchone()
        db.execute("COMMIT")
        return row
    except BaseException:
        db.execute("ROLLBACK")
        raise

def checkpoint(db, worker, epoch, now, step):
    db.execute("BEGIN IMMEDIATE")
    try:
        changed = db.execute("""UPDATE job SET checkpoint=? WHERE task_id='task-7'
          AND lease_owner=? AND claim_epoch=? AND lease_until>?""",
          (step,worker,epoch,now)).rowcount
        if changed != 1:
            db.execute("ROLLBACK")
            return False
        db.execute("UPDATE task SET state='WORKING' WHERE id='task-7'")
        db.execute("COMMIT")
        return True
    except BaseException:
        db.execute("ROLLBACK")
        raise

def provider_call(db):
    db.execute("INSERT OR IGNORE INTO provider VALUES (?,?)", (KEY,"invoice-posted"))
    return db.execute("SELECT result FROM provider WHERE key=?", (KEY,)).fetchone()[0]

def finish(db, worker, epoch, now):
    db.execute("BEGIN IMMEDIATE")
    try:
        changed = db.execute("""UPDATE job SET state='COMPLETED',checkpoint=5
          WHERE task_id='task-7' AND lease_owner=? AND claim_epoch=?
            AND lease_until>? AND state='RUNNING'""",(worker,epoch,now)).rowcount
        if changed != 1:
            db.execute("ROLLBACK")
            return False
        db.execute("UPDATE task SET state='COMPLETED' WHERE id='task-7'")
        db.execute("INSERT OR IGNORE INTO outbox(event_id,task_id) VALUES ('task-7/completed','task-7')")
        db.execute("COMMIT")
        return True
    except BaseException:
        db.execute("ROLLBACK")
        raise

def dispatch(db):
    # Local receiver deduplication stands in for a webhook/broker acknowledgement.
    for (event_id,) in db.execute("SELECT event_id FROM outbox WHERE sent=0"):
        db.execute("INSERT OR IGNORE INTO deliveries VALUES (?)", (event_id,))
        db.execute("UPDATE outbox SET sent=1 WHERE event_id=?", (event_id,))

if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "worker-a":
    db = open_db(sys.argv[2])
    assert claim(db,"A",0) == (1,0)
    assert checkpoint(db,"A",1,1,4)
    assert provider_call(db) == "invoice-posted"
    db.close()
    os._exit(7)  # a hard process exit after provider success, before completion

if __name__ == "__main__" and len(sys.argv) == 1:
    with tempfile.TemporaryDirectory() as folder:
        path = str(Path(folder)/"jobs.sqlite")
        db = open_db(path)
        init(db)
        a = subprocess.run([sys.executable,__file__,"worker-a",path],check=False)
        assert a.returncode == 7
        print("worker A killed after provider call; checkpoint=4")
        assert claim(db,"B",40) is None
        print("t=40: B denied while lease current")
        assert claim(db,"B",61) == (2,4)
        print("t=61: B reclaimed epoch=2, checkpoint=4")
        assert not finish(db,"A",1,62)
        print("stale A epoch=1 completion denied")
        assert provider_call(db) == "invoice-posted"
        assert finish(db,"B",2,62)
        dispatch(db)
        dispatch(db)
        assert db.execute("SELECT state FROM task").fetchone() == ("COMPLETED",)
        assert db.execute("SELECT COUNT(*) FROM provider").fetchone() == (1,)
        assert db.execute("SELECT COUNT(*) FROM outbox").fetchone() == (1,)
        assert db.execute("SELECT COUNT(*) FROM deliveries").fetchone() == (1,)
        print("terminal task=COMPLETED; provider=1, outbox=1, delivery=1")
        db.close()
