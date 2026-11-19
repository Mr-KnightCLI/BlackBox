import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader
import core

app = FastAPI(lifespan=core.lifespan)
templates = Environment(loader=FileSystemLoader(core.ROOT), autoescape=True)
@app.get('/', response_class=HTMLResponse)
def home():
    return templates.get_template('dashboard.html').render()

@app.get('/lunar-background.png')
def lunar_background():
    from fastapi.responses import FileResponse
    return FileResponse(core.ROOT/'lunar-background.png', media_type='image/png')

@app.get('/moon.jpg')
def lunar_texture():
    from fastapi.responses import FileResponse
    return FileResponse(core.ROOT/'moon.jpg', media_type='image/jpeg')

app.get('/data/{owner}')(core.data)
app.get('/incidents')(core.incidents)
app.post('/mark')(core.mark)
app.post('/edit/{i}')(core.edit)
app.delete('/incident/{i}')(core.delete)

@app.get('/report/{i}')
def report(i:int, notes:bool=False, processes:bool=False, messages:bool=False, download:bool=False):
    return HTMLResponse(core.report(i, notes, processes, messages),headers={'Content-Disposition':'attachment; filename=blackbox-report.html'} if download else {})

if __name__=='__main__':
    uvicorn.run(app,host='127.0.0.1',port=8765)
