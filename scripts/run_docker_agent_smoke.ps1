param(
  [int]$Port = 8766,
  [string]$Token = "ebook-test-20260531",
  [string]$ReportDir = "",
  [int]$ContainerIterations = 2,
  [switch]$KeepTestFiles
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$WorkspaceRoot = Split-Path $ProjectRoot -Parent
$TestRoot = Join-Path $ProjectRoot "agent-test"
$InputDir = Join-Path $TestRoot "inputs"
$OutputDir = Join-Path $TestRoot "outputs"
$ServerOut = Join-Path $TestRoot "http-bridge.out.log"
$ServerErr = Join-Path $TestRoot "http-bridge.err.log"
$Python = (Get-Command python).Source
$Formats = @()
$PSNativeCommandUseErrorActionPreference = $false

if ([string]::IsNullOrWhiteSpace($ReportDir)) {
  $ReportDir = Join-Path $ProjectRoot "benchmarks\runs\docker-agent-smoke-current"
}

function Assert-UnderProject {
  param([string]$Path)
  $resolvedProject = [System.IO.Path]::GetFullPath($ProjectRoot)
  $resolvedPath = [System.IO.Path]::GetFullPath($Path)
  if (-not $resolvedPath.StartsWith($resolvedProject, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to modify path outside project: $resolvedPath"
  }
}

function Invoke-Json {
  param(
    [string]$Uri,
    [string]$Method = "GET",
    [object]$Body = $null
  )
  $headers = @{ Authorization = "Bearer $Token" }
  if ($null -eq $Body) {
    return Invoke-RestMethod -Uri $Uri -Method $Method -Headers $headers -TimeoutSec 30
  }
  return Invoke-RestMethod -Uri $Uri -Method $Method -Headers $headers -ContentType "application/json; charset=utf-8" -Body ($Body | ConvertTo-Json -Depth 8) -TimeoutSec 30
}

function Add-Fixture {
  param([string]$Name)
  $script:Formats += $Name
}

function Invoke-DockerTool {
  param(
    [string]$Container,
    [string]$Name,
    [object]$Arguments,
    [string]$PayloadName
  )
  $safeContainer = $Container -replace "[^A-Za-z0-9_.-]", "-"
  $safePayload = $PayloadName -replace "[^A-Za-z0-9_.-]", "-"
  $payload = @{
    name = $Name
    arguments = $Arguments
  } | ConvertTo-Json -Compress -Depth 12
  $payloadFile = Join-Path $TestRoot "$safePayload-$safeContainer.json"
  [System.IO.File]::WriteAllText($payloadFile, $payload, [System.Text.UTF8Encoding]::new($false))
  docker cp $payloadFile "${Container}:/tmp/ebook-tool-payload.json" | Out-Null
  $cmd = "curl -sS -H 'Authorization: Bearer $Token' -H 'Content-Type: application/json' --data-binary @/tmp/ebook-tool-payload.json http://host.docker.internal:$Port/call"
  $text = docker exec $Container sh -lc $cmd 2>&1
  $exitCode = $LASTEXITCODE
  $json = $null
  if ($exitCode -eq 0) {
    try {
      $json = ($text -join "`n") | ConvertFrom-Json
    } catch {
      $json = $null
    }
  }
  return [pscustomobject]@{
    exit = $exitCode
    text = $text
    json = $json
  }
}

function Unwrap-ToolResult {
  param([object]$Response)
  if ($null -eq $Response) {
    return $null
  }
  if ($null -ne $Response.result) {
    return $Response.result
  }
  return $Response
}

Assert-UnderProject $TestRoot
if (Test-Path -LiteralPath $TestRoot) {
  Remove-Item -LiteralPath $TestRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $InputDir, $OutputDir | Out-Null

$Pandoc = (& $Python -c "import sys; sys.path.insert(0, r'$WorkspaceRoot'); from ebook_markdown_pipeline.batch_convert_books import suggested_command_value; print(suggested_command_value('pandoc'))").Trim()
$Calibre = (& $Python -c "import sys; sys.path.insert(0, r'$WorkspaceRoot'); from ebook_markdown_pipeline.batch_convert_books import suggested_command_value; print(suggested_command_value('ebook-convert'))").Trim()

$Markdown = @"
# Agent Smoke Test

## Chapter One

This is a tiny ebook conversion smoke test.

## Chapter Two

It checks format routing and output generation.
"@

$MarkdownPath = Join-Path $InputDir "sample.md"
Set-Content -LiteralPath $MarkdownPath -Value $Markdown -Encoding UTF8

Set-Content -LiteralPath (Join-Path $InputDir "sample.txt") -Value $Markdown -Encoding UTF8
Add-Fixture "txt"

$Fb2 = @"
<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
  <description><title-info><book-title>Agent Smoke Test</book-title></title-info></description>
  <body><section><title><p>Chapter One</p></title><p>FB2 body text.</p></section></body>
</FictionBook>
"@
Set-Content -LiteralPath (Join-Path $InputDir "sample.fb2") -Value $Fb2 -Encoding UTF8
Add-Fixture "fb2"

$Rtf = "{\rtf1\ansi\b Agent Smoke Test\b0\par Chapter One\par RTF body text.\par}"
Set-Content -LiteralPath (Join-Path $InputDir "sample.rtf") -Value $Rtf -Encoding ASCII
Add-Fixture "rtf"

if ($Pandoc -and (Test-Path -LiteralPath $Pandoc)) {
  & $Pandoc $MarkdownPath -o (Join-Path $InputDir "sample.epub")
  Add-Fixture "epub"
  & $Pandoc $MarkdownPath -o (Join-Path $InputDir "sample.odt")
  Add-Fixture "odt"
}

if ($Calibre -and (Test-Path -LiteralPath $Calibre) -and (Test-Path -LiteralPath (Join-Path $InputDir "sample.epub"))) {
  & $Calibre (Join-Path $InputDir "sample.epub") (Join-Path $InputDir "sample.azw3") | Out-Null
  Add-Fixture "azw3"
  & $Calibre (Join-Path $InputDir "sample.epub") (Join-Path $InputDir "sample.mobi") | Out-Null
  Add-Fixture "mobi"
  Copy-Item -LiteralPath (Join-Path $InputDir "sample.azw3") -Destination (Join-Path $InputDir "sample.azw")
  Add-Fixture "azw"
}

& $Python -c "from pathlib import Path; import fitz; p=Path(r'$InputDir')/'sample.pdf'; d=fitz.open(); page=d.new_page(); page.insert_text((72,72), 'Agent Smoke Test PDF\nChapter One\nPDF body text.'); d.save(p)"
Add-Fixture "pdf"

$Process = $null
try {
  New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null

  $Process = Start-Process -FilePath $Python `
    -ArgumentList @("-B", "-m", "ebook_markdown_pipeline.ebook_converter_http", "--host", "127.0.0.1", "--port", "$Port", "--token", $Token) `
    -WorkingDirectory $WorkspaceRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $ServerOut `
    -RedirectStandardError $ServerErr `
    -PassThru

  $BaseUrl = "http://127.0.0.1:$Port"
  $ready = $false
  for ($i = 0; $i -lt 30; $i++) {
    try {
      $health = Invoke-Json -Uri "$BaseUrl/health"
      if ($health.ok) {
        $ready = $true
        break
      }
    } catch {
      Start-Sleep -Milliseconds 500
    }
  }
  if (-not $ready) {
    throw "HTTP bridge did not become ready. stdout=$(Get-Content -LiteralPath $ServerOut -Raw -ErrorAction SilentlyContinue) stderr=$(Get-Content -LiteralPath $ServerErr -Raw -ErrorAction SilentlyContinue)"
  }

  $scan = Invoke-Json -Uri "$BaseUrl/call" -Method "POST" -Body @{
    name = "scan_books"
    arguments = @{
      input = $InputDir
      output = $OutputDir
      recursive = $true
      pdf_pipeline_mode = "pymupdf4llm"
    }
  }

  $start = Invoke-Json -Uri "$BaseUrl/call" -Method "POST" -Body @{
    name = "start_conversion"
    arguments = @{
      input = $InputDir
      output = $OutputDir
      recursive = $true
      resume = $false
      pdf_pipeline_mode = "pymupdf4llm"
    }
  }

  $jobId = $start.job_id
  $final = $null
  for ($i = 0; $i -lt 120; $i++) {
    $status = Invoke-Json -Uri "$BaseUrl/call" -Method "POST" -Body @{
      name = "get_job_status"
      arguments = @{ job_id = $jobId }
    }
    if ($status.status -ne "running") {
      $final = $status
      break
    }
    Start-Sleep -Seconds 1
  }
  if ($null -eq $final) {
    throw "Timed out waiting for conversion job $jobId"
  }

  $dockerResults = @()
  foreach ($container in @("openclaw-openclaw-gateway-1", "hermes-agent")) {
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $healthCmd = "curl -sS -H 'Authorization: Bearer $Token' http://host.docker.internal:$Port/health"
    $healthText = docker exec $container sh -lc $healthCmd 2>&1
    $healthExit = $LASTEXITCODE
    $scanPayload = @{
      name = "scan_books"
      arguments = @{
        input = $InputDir
        output = $OutputDir
        recursive = $true
        pdf_pipeline_mode = "pymupdf4llm"
      }
    } | ConvertTo-Json -Compress -Depth 8
    $payloadFile = Join-Path $TestRoot "scan-payload-$container.json"
    [System.IO.File]::WriteAllText($payloadFile, $scanPayload, [System.Text.UTF8Encoding]::new($false))
    docker cp $payloadFile "${container}:/tmp/ebook-scan-payload.json" | Out-Null
    $scanCmd = "curl -sS -H 'Authorization: Bearer $Token' -H 'Content-Type: application/json' --data-binary @/tmp/ebook-scan-payload.json http://host.docker.internal:$Port/call"
    $scanText = docker exec $container sh -lc $scanCmd 2>&1
    $scanExit = $LASTEXITCODE
    $jobRuns = @()
    for ($iter = 1; $iter -le $ContainerIterations; $iter++) {
      $safeContainer = $container -replace "[^A-Za-z0-9_.-]", "-"
      $containerOutput = Join-Path $OutputDir ("docker-$safeContainer-$iter")
      New-Item -ItemType Directory -Force -Path $containerOutput | Out-Null
      $startCall = Invoke-DockerTool -Container $container -Name "start_conversion" -PayloadName "start-$iter" -Arguments @{
        input = $InputDir
        output = $containerOutput
        recursive = $true
        resume = $false
        overwrite = $true
        pdf_pipeline_mode = "pymupdf4llm"
      }
      $startResult = Unwrap-ToolResult $startCall.json
      $jobId = $null
      if ($null -ne $startResult) {
        $jobId = $startResult.job_id
      }
      $finalJob = $null
      $pollExit = $null
      if ($jobId) {
        for ($poll = 0; $poll -lt 90; $poll++) {
          $statusCall = Invoke-DockerTool -Container $container -Name "get_job_status" -PayloadName "status-$iter-$poll" -Arguments @{ job_id = $jobId }
          $pollExit = $statusCall.exit
          $statusResult = Unwrap-ToolResult $statusCall.json
          if ($null -ne $statusResult -and $statusResult.status -ne "running") {
            $finalJob = $statusResult
            break
          }
          Start-Sleep -Seconds 1
        }
      }
      $artifactRead = $null
      $artifactPath = $null
      if ($null -ne $finalJob -and $finalJob.results -and $finalJob.results.Count -gt 0) {
        $artifactPath = $finalJob.results[0].output
      }
      if ($artifactPath) {
        $artifactCall = Invoke-DockerTool -Container $container -Name "read_artifact" -PayloadName "artifact-$iter" -Arguments @{
          path = $artifactPath
          artifact_type = "markdown"
          max_chars = 1000
          max_lines = 40
        }
        $artifactRead = [pscustomobject]@{
          exit = $artifactCall.exit
          ok = ($artifactCall.exit -eq 0 -and $null -ne (Unwrap-ToolResult $artifactCall.json))
          path = $artifactPath
        }
      }
      $jobRuns += [pscustomobject]@{
        iteration = $iter
        start_exit = $startCall.exit
        job_id = $jobId
        poll_exit = $pollExit
        final_status = if ($null -ne $finalJob) { $finalJob.status } else { "missing" }
        completed = if ($null -ne $finalJob) { $finalJob.completed } else { $null }
        total = if ($null -ne $finalJob) { $finalJob.total } else { $null }
        artifact_read = $artifactRead
      }
    }
    $ErrorActionPreference = $previousErrorActionPreference
    $dockerResults += [pscustomobject]@{
      container = $container
      health_exit = $healthExit
      health = $healthText
      scan_exit = $scanExit
      scan = $scanText
      job_runs = $jobRuns
    }
  }

  $outputs = Get-ChildItem -LiteralPath $OutputDir -File -Recurse | Select-Object -ExpandProperty FullName
  $report = [pscustomobject]@{
    schema_version = "docker-agent-smoke-v1"
    created_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    port = $Port
    server_pid = $Process.Id
    generated_formats = $Formats
    scan_count = $scan.count
    conversion_status = $final.status
    completed = $final.completed
    total = $final.total
    result_statuses = @($final.results | ForEach-Object { $_.status })
    result_outputs = @($final.results | ForEach-Object { $_.output })
    outputs = $outputs
    docker = $dockerResults
  }

  $reportPath = Join-Path $ReportDir "docker-agent-smoke.json"
  $summaryPath = Join-Path $ReportDir "docker-agent-smoke.md"
  $report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $reportPath -Encoding UTF8

  $containerRows = @()
  foreach ($item in $dockerResults) {
    $containerRows += "| $($item.container) | $($item.health_exit) | $($item.scan_exit) |"
  }
  $formatList = ($Formats | ForEach-Object { "``$($_)``" }) -join ", "
  $statusList = (@($final.results | ForEach-Object { $_.status }) | Group-Object | ForEach-Object { "$($_.Name): $($_.Count)" }) -join ", "
  $summary = @"
# Docker Agent Smoke

- Created: $($report.created_at)
- HTTP bridge: `http://127.0.0.1:$Port`
- Generated formats: $formatList
- Scan count: $($scan.count)
- Conversion status: $($final.status)
- Completed: $($final.completed) / $($final.total)
- Result statuses: $statusList
- Container iterations: $ContainerIterations

| Container | Health exit | Scan exit | Job runs ok | Artifact reads ok |
| --- | ---: | ---: | ---: | ---: |
$(
  ($dockerResults | ForEach-Object {
    $okJobs = @($_.job_runs | Where-Object { $_.final_status -eq "done" }).Count
    $okArtifacts = @($_.job_runs | Where-Object { $_.artifact_read -and $_.artifact_read.ok }).Count
    "| $($_.container) | $($_.health_exit) | $($_.scan_exit) | $okJobs / $ContainerIterations | $okArtifacts / $ContainerIterations |"
  }) -join "`n"
)

Evidence:

- `docker-agent-smoke.json`: full machine-readable response, including `/health`, `/call scan_books`, repeated `/call start_conversion`, `/call get_job_status`, and `/call read_artifact` output from each Docker container.
- This smoke verifies host-to-container access through `host.docker.internal` for OpenClaw and Hermes. It does not prove that their LLM planners autonomously selected the tool; it proves the stable callable HTTP surface that those agents can use.
"@
  $summary | Set-Content -LiteralPath $summaryPath -Encoding UTF8

  $report
} finally {
  if ($Process -and -not $Process.HasExited) {
    Stop-Process -Id $Process.Id -Force
  }
  if (-not $KeepTestFiles -and (Test-Path -LiteralPath $TestRoot)) {
    Remove-Item -LiteralPath $TestRoot -Recurse -Force
  }
}
