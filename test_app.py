import os
import tempfile
import unittest
from pathlib import Path
import core

class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old=core.DB
        self.addCleanup(setattr,core,'DB',self.old)
        core.DB=Path(self.tmp.name)/'test.sqlite'
        core.initialize()

    def test_rates(self):
        self.assertEqual(core.rate(20,50,2),15)
        for args in [(20,0,2),(None,0,2),(0,1,0)]:
            self.assertIsNone(core.rate(*args))

    def test_snapshot_and_restart(self):
        import time
        with core.db() as c:
            for age in (1000,10):
                c.execute('INSERT INTO points VALUES(0,?,?)',(time.time()-age,'{}'))
        i=core.mark()
        with core.db() as c:
            c.execute('DELETE FROM points WHERE owner=0')
        core.initialize()
        saved=core.data(i)
        self.assertEqual(len(saved['points']),1)
        self.assertEqual(saved['incident']['state'],'Incomplete')

    def test_retention(self):
        with core.db() as c:
            for owner,t in [(0,99),(0,100),(1,99)]:
                c.execute("INSERT INTO points VALUES(?,?,'{}')",(owner,t))
            core.prune(c,1000)
            self.assertEqual([tuple(r) for r in c.execute("SELECT owner,t FROM points ORDER BY owner")],[(0,100),(1,99)])

    def test_report(self):
        i=core.mark()
        core.edit(i,dict(name='<script>alert(1)</script>',notes=r'C:\Users\Private\secret.txt'))
        report=core.report(i,notes=True)
        self.assertIn('&lt;script&gt;',report)
        self.assertNotIn('secret.txt',report)
        self.assertIn('[path omitted]',report)
        self.assertNotIn('[path omitted]</p></table>',core.report(i))
    def test_automatic_capture(self):
        detector=core.Detector()
        with core.db() as c:
            for t in [200,202,220,222,224,226,228]:
                detector.observe(c,t,dict(cpu=96,memory=72))
            self.assertEqual(c.execute('select count(*) from incidents').fetchone()[0],0)
            for t in range(230,401,2):
                detector.observe(c,t,dict(cpu=96,memory=72))
            self.assertEqual(c.execute('select count(*) from incidents').fetchone()[0],1)
            for t in range(402,426,2):
                detector.observe(c,t,dict(cpu=40,memory=72))
            for t in range(426,440,2):
                detector.observe(c,t,dict(cpu=40,memory=95))
            self.assertEqual(c.execute('select count(*) from incidents').fetchone()[0],2)
