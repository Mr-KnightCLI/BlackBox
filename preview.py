import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
import core

class Handler(BaseHTTPRequestHandler):
    def dispatch(self):
        u=urlsplit(self.path)
        parts=u.path.strip('/').split('/')
        act=parts[0]
        try:
            i=int(parts[1]) if len(parts)>1 else 0
            html=False
            attachment=False
            if self.command=='GET' and u.path in ('/moon.jpg','/lunar-background.png'):
                image=(core.ROOT/u.path[1:]).read_bytes()
                self.send_response(200)
                self.send_header('Content-Type','image/png' if u.path.endswith('.png') else 'image/jpeg')
                self.send_header('Content-Length',str(len(image)))
                self.end_headers()
                self.wfile.write(image)
                return
            if self.command=='GET':
                if not act:
                    value=(core.ROOT/'dashboard.html').read_text(encoding='utf-8-sig')
                    html=True
                elif act=='incidents': value=core.incidents()
                elif act=='data': value=core.data(i)
                elif act=='report':
                    q=parse_qs(u.query)
                    value=core.report(i,*(q.get(k)==['true'] for k in ('notes','processes','messages')))
                    html=True
                    attachment=q.get('download')==['true']
                else: raise KeyError()
            elif self.command=='POST' and act=='mark': value=core.mark()
            elif self.command=='POST' and act=='edit':
                value=core.edit(i,json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            elif self.command=='DELETE' and act=='incident': value=core.delete(i)
            else: raise KeyError()
            payload=(value if html else json.dumps(value)).encode()
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8' if html else 'application/json')
            if attachment: self.send_header('Content-Disposition','attachment; filename=blackbox-report.html')
            self.send_header('Content-Length',str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (ValueError,KeyError): self.send_error(404)
    do_GET=do_POST=do_DELETE=dispatch

async def main():
    with ThreadingHTTPServer(('127.0.0.1',8765),Handler) as server:
        async with core.lifespan(None):
            server.serve_forever()

if __name__=='__main__':
    try: asyncio.run(main())
    except KeyboardInterrupt: pass
