# BlackBox for Windows

From the project workspace, use PowerShell with Python 3.11 or newer installed.

```powershell
cd .\blackbox
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open http://127.0.0.1:8765. Keep this terminal open. Press Ctrl+C to stop. After setup, the last command starts both the collector and dashboard offline. Run one instance against the database.

## Capture and replay

1. Open Live Monitor. Allow two minutes for the rolling history to fill. Process rates require two process observations.
2. Reproduce the slowdown and click Mark incident. The slider immediately shows the available preceding history. Keep BlackBox running for another 30 seconds.
3. Use Jump to spike or focus the slider and use the arrow keys. Inspect CPU, memory, read/write rates and the timestamp of the latest process observation. Process CPU is a percentage of total logical CPU capacity.
4. Give the incident a name, enter support notes and click Save changes. Incidents survive restart in activity.sqlite beside the application. An interrupted capture is labeled Incomplete.
5. Choose which optional evidence to include. Click Preview report, inspect the text for sensitive information, and download the HTML. Open the downloaded file directly in your browser. Free-form text may contain identifiers beyond the automatic redaction rules.
6. Restart the app and use Incidents to reopen the snapshot. Delete incident removes it from the archive.

## Tests and collection settings

```powershell
.\.venv\Scripts\python.exe -m unittest -v
$env:BLACKBOX_PROCESS_SECONDS = '12'
.\.venv\Scripts\python.exe app.py
```

The default process observation interval is eight seconds. Live samples expire after 15 minutes. Windows Application and System warning, error and critical events are queried after capture. A restricted channel is recorded as unavailable. Missing disk readings are displayed as unavailable.

## Offline launch on this computer

With the installed Python and psutil, run **python preview.py** from the blackbox directory. This bundled standard-library HTTP server serves the same dashboard, collector, archive and reports on the same port. Stop the current server before switching launch commands.

Automatic capture runs inside the collector even with every browser tab closed. CPU at 90% or memory at 92% for 10 seconds starts a saved incident. One sustained episode produces one capture. Both metrics must recover below 80% CPU and 88% memory for 20 seconds to rearm, with at least two minutes between automatic captures. Keep the BlackBox server running. Manual capture is available for symptoms below these thresholds.

Lunar surface texture: three.js r160 examples/textures/planets/moon_1024.jpg, bundled locally.
