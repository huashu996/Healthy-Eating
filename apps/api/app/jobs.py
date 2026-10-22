from . import db
TERMINAL = {"succeeded", "partial", "failed", "cancelled"}

def event(con, identifier, kind, payload=None):
    sequence = con.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM job_events WHERE job_id=?", (identifier,)).fetchone()[0]
    con.execute("INSERT INTO job_events VALUES(?,?,?,?,?)", (identifier, sequence, kind, db.encode(payload or {}), db.now()))
