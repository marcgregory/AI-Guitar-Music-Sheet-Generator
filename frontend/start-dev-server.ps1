$env:PATH = "C:\nvm4w\nodejs;C:\Program Files\cursor\resources\app\resources\helpers;$env:APPDATA\npm\node_modules\corepack\shims;$env:PATH"
Set-Location $PSScriptRoot
& "$env:APPDATA\npm\node_modules\corepack\shims\npm.cmd" run dev -- --host 127.0.0.1 --port 5173 *> "$PSScriptRoot\frontend.dev.log"
