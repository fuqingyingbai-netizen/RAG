param(
    [int]$Port = 8010,
    [switch]$Background,
    [switch]$ReuseVectorServices
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$runtimeRoot = Join-Path $projectRoot '.python\cpython-3.12.14-windows-x86_64-none'
$logRoot = Join-Path $projectRoot 'work\environment-recovery'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null

if (Test-Path -LiteralPath (Join-Path $runtimeRoot 'python.exe')) {
    $configPath = Join-Path $projectRoot '.venv\pyvenv.cfg'
    $config = [IO.File]::ReadAllText($configPath)
    $config = [regex]::Replace($config, '(?m)^home = .*$', ('home = ' + $runtimeRoot))
    [IO.File]::WriteAllText($configPath, $config, [Text.UTF8Encoding]::new($false))
}
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.env'))) {
    throw 'Create .env from .env.example and configure the model and database first.'
}
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Project Python is missing. Restore .venv before starting.'
}
& $pythonPath -c "import ssl, fastapi, uvicorn; print('Python runtime OK')"
if ($LASTEXITCODE -ne 0) { throw 'Project Python or dependencies are unavailable.' }

$dockerCommand = Get-Command docker -ErrorAction Stop
function Test-DockerServer {
    try {
        & docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}
if (-not (Test-DockerServer)) {
    $desktopRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $dockerCommand.Source))
    $desktopPath = Join-Path $desktopRoot 'Docker Desktop.exe'
    if (-not (Test-Path -LiteralPath $desktopPath)) { throw 'Start Docker Desktop, then retry.' }
    Start-Process -FilePath $desktopPath -WindowStyle Hidden
    Write-Host 'Waiting for Docker Desktop...'
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        Start-Sleep -Seconds 2
        if (Test-DockerServer) { break }
    }
    if (-not (Test-DockerServer)) { throw 'Docker Desktop did not become ready.' }
}

$vectorOwner = ''
$vectorContainer = & docker ps -a --filter 'name=^milvus-standalone$' --format '{{.Names}}'
if ($vectorContainer) {
    $vectorLabels = (& docker inspect milvus-standalone --format '{{json .Config.Labels}}') | ConvertFrom-Json
    $vectorOwner = $vectorLabels.'com.docker.compose.project.working_dir'
}
if ($vectorOwner -and ([IO.Path]::GetFullPath($vectorOwner) -ne $projectRoot)) {
    $ReuseVectorServices = $true
}
if ($ReuseVectorServices) {
    foreach ($container in @('milvus-etcd', 'milvus-minio', 'milvus-standalone')) {
        $health = & docker inspect $container --format '{{.State.Health.Status}}' 2>$null
        if ($LASTEXITCODE -ne 0 -or $health -ne 'healthy') {
            throw "Existing vector service $container is not healthy. Start its original Compose deployment first."
        }
    }
    Write-Host "Reusing healthy vector services from: $vectorOwner"
    & docker compose -p rag-local -f docker-compose.yml -f docker-compose.reuse.yml up -d --wait --wait-timeout 120 postgres redis
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL or Redis did not become healthy.' }
} else {
    $minioImageAvailable = $false
    try {
        & docker image inspect 'supermew-minio:RELEASE.2024-05-28T17-19-04Z' 2>$null | Out-Null
        $minioImageAvailable = $LASTEXITCODE -eq 0
    } catch { $minioImageAvailable = $false }
    if (-not $minioImageAvailable) {
        $archivePath = Join-Path $projectRoot 'docker\minio\minio-source.tar.gz'
        if (-not (Test-Path -LiteralPath $archivePath)) {
            Invoke-WebRequest -Uri 'https://codeload.github.com/minio/minio/tar.gz/refs/tags/RELEASE.2024-05-28T17-19-04Z' -OutFile $archivePath -TimeoutSec 120
        }
        $archiveHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash
        if ($archiveHash -ne '987C59F79100A8F7E30362C3ACD4D8601FDDBFC93558E4B05C3B6AD78A8E3EF0') {
            throw 'MinIO source archive checksum mismatch.'
        }
        & docker compose build minio
        if ($LASTEXITCODE -ne 0) { throw 'MinIO build failed.' }
    }
    & docker compose up -d --wait --wait-timeout 120
    if ($LASTEXITCODE -ne 0) { throw 'A required Docker service did not become healthy.' }
}

$baseUrl = "http://127.0.0.1:$Port"
try {
    $schema = Invoke-RestMethod -Uri "$baseUrl/openapi.json" -TimeoutSec 3
    if ($schema.paths.PSObject.Properties.Name -contains '/research/projects') {
        Write-Host "Backend is already running: $baseUrl"
        return
    }
    throw "Port $Port is occupied by another application."
} catch {
    if ($_.Exception.Message -like '*occupied by another application*') { throw }
}

$env:PYTHONUTF8 = '1'
$env:UV_CACHE_DIR = Join-Path $projectRoot '.uv-cache'
$backendArguments = @('-m', 'uvicorn', 'backend.app:app', '--host', '127.0.0.1', '--port', "$Port")
if ($Background) {
    $process = Start-Process -FilePath $pythonPath -ArgumentList $backendArguments -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logRoot 'backend.stdout.log') -RedirectStandardError (Join-Path $logRoot 'backend.stderr.log')
    $process.Id | Set-Content -LiteralPath (Join-Path $logRoot 'backend.pid')
    $ready = $false
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        if ($process.HasExited) { throw "Backend exited. Check $logRoot\backend.stderr.log" }
        try {
            $schema = Invoke-RestMethod -Uri "$baseUrl/openapi.json" -TimeoutSec 3
            if ($schema.paths.PSObject.Properties.Name -contains '/research/projects') {
                $ready = $true
                break
            }
        } catch { }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw "Backend is still starting. Check $logRoot\backend.stderr.log" }
    Write-Host "Backend started (PID $($process.Id)): $baseUrl"
    Write-Host "Logs: $logRoot"
} else {
    & $pythonPath @backendArguments
    exit $LASTEXITCODE
}
