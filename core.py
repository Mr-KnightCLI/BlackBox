import json
import os
import sqlite3
import threading
import time
from contextlib import asynccontextmanager, closing, contextmanager
from pathlib import Path
from html import escape
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import psutil
ROOT = Path(__file__).resolve().parent
DB = ROOT / "activity.sqlite"
PERIOD = max(4, int(os.getenv("BLACKBOX_PROCESS_SECONDS", "8")))

stop = threading.Event()
status = "Starting"

@contextmanager
def db():
    with closing(sqlite3.connect(DB, timeout=10)) as conn, conn:
        conn.row_factory = sqlite3.Row
        yield conn

def initialize():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS points(owner INTEGER,t REAL,data TEXT,PRIMARY KEY(owner,t));
        CREATE TABLE IF NOT EXISTS incidents(id INTEGER PRIMARY KEY,mark REAL,name TEXT,notes TEXT,state TEXT,events TEXT);
        CREATE TABLE IF NOT EXISTS detector(id INTEGER PRIMARY KEY, active INTEGER, last_mark REAL);
        INSERT OR IGNORE INTO detector VALUES(1,0,0);
        UPDATE incidents SET state='Incomplete' WHERE state='Capturing';
        """)

def prune(conn, now):
    conn.execute('DELETE FROM points WHERE owner=0 AND t<?',(now-900,))

def rate(a,b,seconds):
    if a is not None and b is not None and b>=a and seconds>0:
        return (b-a)/seconds

def processes(previous,now):
    current, rows, denied = {}, [], 0
    capacity = psutil.cpu_count() or 1
    for p in psutil.process_iter():
        try:
            key = (p.pid,p.create_time())
            cpu = p.cpu_times()
            try:
                io = p.io_counters()
                total = io.read_bytes+io.write_bytes
            except (psutil.AccessDenied,AttributeError):
                total = None
                denied += 1
            current[key] = (now,cpu.user+cpu.system,total)
            if key in previous and p.pid:
                t,secs,old = previous[key]
                use = rate(secs,current[key][1],now-t)
                if use is not None:
                    rows.append(dict(name=p.name(),pid=p.pid,cpu=round(100*use/capacity,2),io=rate(old,total,now-t)))
        except psutil.AccessDenied:
            denied += 1
        except psutil.NoSuchProcess:
            pass
    rows.sort(key=lambda r:r['cpu'],reverse=True)
    busiest = sorted(rows,key=lambda r:r['io'] or 0,reverse=True)[:8]
    return current,rows[:12]+[r for r in busiest if r not in rows[:12]],denied

def events(identity,start,end):
    result=[]
    for channel in ('Application','System'):
        def stamp(t):
            return datetime.fromtimestamp(t,timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        query=f"*[System[(Level=1 or Level=2 or Level=3) and TimeCreated[@SystemTime>='{stamp(start)}' and @SystemTime<='{stamp(end)}']]]"
        try:
            import xml.etree.ElementTree as ET
            raw=subprocess.run(['wevtutil','qe',channel,'/q:'+query,'/f:RenderedXml','/c:100','/rd:true','/uni:true'],capture_output=True,timeout=15,check=True)
            nodes=ET.fromstring('<root>'+raw.stdout.decode('utf-16-le').lstrip('\ufeff')+'</root>')
            for node in nodes:
                val=node.find('.//{*}TimeCreated').get('SystemTime')
                result.append(dict(channel=channel,t=datetime.fromisoformat(val.replace('Z','+00:00')).timestamp(),message=node.findtext('.//{*}Message') or 'Message unavailable'))
            if len(nodes)==100:
                result.append(dict(channel=channel,message='Newest 100 matching events shown'))
        except Exception as e:
            result.append(dict(channel=channel,message='Channel unavailable: '+type(e).__name__))
    with db() as c:
        c.execute('UPDATE incidents SET events=? WHERE id=?',(json.dumps(result),identity))

def collect(pool):
    global status
    detector=Detector()
    previous={}
    last_proc=last=0
    disk=None
    psutil.cpu_percent()
    due = time.monotonic() + 2
    while not stop.wait(max(0, due - time.monotonic())):
        due = max(due + 2, time.monotonic() + 0.1)
        try:
            now=time.monotonic()
            t=time.time()
            try:
                d=psutil.disk_io_counters()
            except (OSError,psutil.Error):
                d=None
            row=dict(cpu=psutil.cpu_percent(),memory=psutil.virtual_memory().percent,read=None,write=None)
            if d and disk:
                for name in ('read','write'):
                    attr=name+'_bytes'
                    row[name]=rate(getattr(disk,attr),getattr(d,attr),now-last)
            disk,last=d,now
            if now-last_proc>=PERIOD:
                previous,row['processes'],row['limited']=processes(previous,now)
                last_proc=now
            with db() as c:
                payload=json.dumps(row)
                c.execute('INSERT INTO points VALUES(0,?,?)',(t,payload))
                prune(c,t)
                for i,m in c.execute("SELECT id,mark FROM incidents WHERE state='Capturing'").fetchall():
                    if t<=m+30:
                        c.execute('INSERT INTO points VALUES(?,?,?)',(i,t,payload))
                    else:
                        c.execute("UPDATE incidents SET state='Saved' WHERE id=?",(i,))
                        pool.submit(events,i,m-120,m+30)
                detector.observe(c,t,row)
            status='Recording'
        except Exception as e:
            status='Collector error: '+type(e).__name__

@asynccontextmanager
async def lifespan(app):
    initialize()
    stop.clear()
    with ThreadPoolExecutor(max_workers=1) as pool:
        worker=threading.Thread(target=collect,args=(pool,))
        worker.start()
        try:
            yield
        finally:
            stop.set()
            worker.join()
            initialize()

def data(owner:int):
    with db() as c:
        incident=c.execute('SELECT * FROM incidents WHERE id=?',(owner,)).fetchone()
        if owner and not incident:
            raise KeyError('Incident unavailable')
        return dict(status=status,incident=dict(incident) if incident else None,points=[dict(t=t,**json.loads(p)) for t,p in c.execute('SELECT t,data FROM points WHERE owner=? ORDER BY t',(owner,))])

def incidents():
    with db() as c:
        return [dict(r) for r in c.execute('SELECT id,name,mark,state FROM incidents ORDER BY id DESC')]

def snapshot(c,t,name,notes=''):
    i=c.execute("INSERT INTO incidents(mark,name,notes,state) VALUES(?,?,?,'Capturing')",(t,name,notes)).lastrowid
    c.execute('INSERT INTO points SELECT ?,t,data FROM points WHERE owner=0 AND t BETWEEN ? AND ?',(i,t-120,t))
    return i

def mark():
    with db() as c:
        return snapshot(c,time.time(),'Untitled incident')

class Detector:
    def __init__(self):
        self.since={}
        self.previous=None

    def observe(self,c,t,row):
        if self.previous is None or not 0<t-self.previous<=6:
            self.since.clear()
        self.previous=t
        active,last=c.execute('SELECT active,last_mark FROM detector WHERE id=1').fetchone()
        states={'CPU':row['cpu']>=90,'memory':row['memory']>=92,
                'recovered':row['cpu']<80 and row['memory']<88}
        for key,on in states.items():
            if on: self.since.setdefault(key,t)
            else: self.since.pop(key,None)
        if active:
            if t-self.since.get('recovered',t)>=20:
                c.execute('UPDATE detector SET active=0 WHERE id=1')
            return
        for key,minimum in [('CPU',90),('memory',92)]:
            if t-self.since.get(key,t)>=10 and t-last>=120:
                snapshot(c,t,'Automatic incident - high '+key,
                         f'{key} stayed at or above {minimum}% for at least 10 seconds.')
                c.execute('UPDATE detector SET active=1,last_mark=? WHERE id=1',(t,))
                return

def edit(i:int,body:dict):
    with db() as c:
        c.execute('UPDATE incidents SET name=?,notes=? WHERE id=?',(str(body['name'])[:200],str(body['notes'])[:8000],i))
    return True

def delete(i:int):
    if i<=0: raise ValueError('Invalid incident')
    with db() as c:
        c.execute('DELETE FROM points WHERE owner=?',(i,))
        c.execute('DELETE FROM incidents WHERE id=?',(i,))
    return True

def clean(value):
    s=re.sub(r'(?i)(?:[a-z]:[\\/]|\\\\|/)[^\r\n]*','[path omitted]',str(value))
    for key in ('USERNAME','USERDOMAIN'):
        if os.getenv(key):
            s=re.sub(re.escape(os.environ[key]),'[redacted]',s,flags=re.I)
    return escape(s)

def report(i:int,notes:bool=False,processes:bool=False,messages:bool=False,download:bool=False):
    d=data(i)
    info=d['incident']
    if not info: raise KeyError('Incident unavailable')
    parts=['<!doctype html><meta charset=utf-8><title>BlackBox support report</title><style>body{font:16px system-ui;max-width:900px;margin:3em auto}td,th{padding:.4em;border-bottom:1px solid #ccc;text-align:left}</style><h1>BlackBox support report</h1>',f"<h2>{clean(info['name'])}</h2><p>{clean(info['state'])}</p>"]
    points=d['points']
    if points:
        peak=max(points,key=lambda p:p['cpu'])
        when=lambda t: datetime.fromtimestamp(t).isoformat(timespec='seconds')
        parts.append(f"<p>Observed {when(points[0]['t'])} through {when(points[-1]['t'])}. Highest observed system CPU: {peak['cpu']}% at {when(peak['t'])}.</p>")
        if processes:
            near=min((p for p in points if p.get('processes')),key=lambda p:abs(p['t']-peak['t']),default=None)
            if near and abs(near['t']-peak['t'])<=PERIOD:
                r=near['processes'][0]
                parts.append(f"<p>{clean(r['name'])} had the highest observed process CPU ({r['cpu']}%) in the interval ending {when(near['t'])}.</p>")
    if info['events'] is None: parts.append('<p>Event evidence pending or unavailable.</p>')
    elif not json.loads(info['events']): parts.append('<p>No matching warning, error or critical events.</p>')
    if notes: parts.append('<p>'+clean(info['notes'])+'</p>')
    parts.append('<table><tr><th>Local time<th>CPU %<th>Memory %<th>Read B/s<th>Write B/s')
    for p in d['points']:
        parts.append('<tr>'+''.join('<td>'+clean(v) for v in [datetime.fromtimestamp(p['t']).isoformat(timespec='seconds')]+[round(p[k],1) if p[k]!=None else 'Unavailable' for k in ('cpu','memory','read','write')]))
        if processes:
            for r in p.get('processes',[]):
                parts.append(f"<tr><td colspan=5>{clean(r['name'])} ; PID {r['pid']} ; CPU {r['cpu']}%")
    parts.append('</table>')
    for e in json.loads(info['events'] or '[]'):
        parts.append('<p>'+clean(e['channel'])+' '+clean(e.get('t',''))+' '+(clean(e['message']) if messages or 't' not in e else '')+'</p>')
    return ''.join(parts)
