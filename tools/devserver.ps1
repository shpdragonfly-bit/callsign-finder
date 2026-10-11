# 운항 도우미 개발 서버 (설치 필요 없음 · Windows PowerShell 기본 기능만 사용)
# 개발서버_시작.bat 으로 실행합니다. web 폴더를 http://localhost:8000 으로 띄우고 브라우저를 엽니다.
# - 파일을 고친 뒤 브라우저에서 새로고침하면 바로 반영 (캐시 안 함)
# - 기상(wx.json)·공항버스 시간표(bus.json)가 폴더에 없으면 실제 앱 주소에서 받아와 그대로 전달
# - localhost 에서는 앱이 사용 통계를 보내지 않음
# - /fpdata/… 는 이 PC 의 공항별 유의사항 내보내기 폴더(개인 AI 비서 봇이 씀)를 읽기 전용으로 전달 → '비행준비'·FLT 요약 PDF
#   (회사 내부 자료: 이 PC 밖으로 나가지 않음. GitHub·실제 앱 주소에는 없음)
param([int]$Port = 8000, [string]$FpDir = "")
# 비행준비 자료 폴더는 GitHub 에 올라가지 않는 PC 설정 파일에서 읽음: config\fpdata.local.env 의 FP_DIR=폴더경로
if (-not $FpDir) {
  $fpConf = Join-Path $PSScriptRoot "..\config\fpdata.local.env"
  if (Test-Path -LiteralPath $fpConf) {
    foreach ($ln in Get-Content -LiteralPath $fpConf) { if ($ln -match '^\s*FP_DIR\s*=\s*"?(.+?)"?\s*$') { $FpDir = $Matches[1] } }
  }
}
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\web")).Path
$Live = "https://shpdragonfly-bit.github.io/callsign-finder/"
$Types = @{ ".html" = "text/html; charset=utf-8"; ".js" = "text/javascript; charset=utf-8"; ".json" = "application/json; charset=utf-8";
  ".css" = "text/css; charset=utf-8"; ".png" = "image/png"; ".svg" = "image/svg+xml"; ".webmanifest" = "application/manifest+json";
  ".ico" = "image/x-icon"; ".pdf" = "application/pdf"; ".woff2" = "font/woff2"; ".ttf" = "font/ttf" }

$L = New-Object System.Net.HttpListener
$L.Prefixes.Add("http://localhost:$Port/")
try { $L.Start() } catch {
  Write-Host "포트 $Port 를 쓸 수 없습니다. 이미 개발 서버 창이 열려 있는지 확인하세요." -ForegroundColor Red
  exit 1
}
Write-Host ""
Write-Host "  운항 도우미 개발 서버 실행 중" -ForegroundColor Green
Write-Host "  주소: http://localhost:$Port/"
Write-Host "  폴더: $Root"
Write-Host "  끄기: 이 창을 닫거나 Ctrl+C"
Write-Host ""
Start-Process "http://localhost:$Port/"

while ($L.IsListening) {
  $ctx = $L.GetContext(); $req = $ctx.Request; $res = $ctx.Response
  try {
    $path = [Uri]::UnescapeDataString($req.Url.AbsolutePath.TrimStart("/"))
    if ($path -eq "") { $path = "index.html" }
    $bytes = $null
    if ($path.StartsWith("fpdata/")) {
      if (-not $FpDir) { $res.StatusCode = 404; continue }     # 설정 없으면 비행준비 자료 없음
      # 비행준비 자료: 읽기 전용, .json 만, 폴더 밖 경로 거부. ReadAllBytes 는 한 번에 읽고 바로 닫음(봇의 파일 교체를 막지 않음)
      $aroot = [IO.Path]::GetFullPath($FpDir).TrimEnd("\") + "\"
      $full = [IO.Path]::GetFullPath((Join-Path $aroot ($path.Substring(7).Replace("/", "\"))))
      if (-not $full.StartsWith($aroot, [StringComparison]::OrdinalIgnoreCase) -or [IO.Path]::GetExtension($full).ToLower() -ne ".json") { $res.StatusCode = 403; continue }
      if (Test-Path -LiteralPath $full -PathType Leaf) { try { $bytes = [IO.File]::ReadAllBytes($full) } catch { $res.StatusCode = 503; continue } }
    } else {
      $full = [IO.Path]::GetFullPath((Join-Path $Root $path))
      if (-not $full.StartsWith($Root)) { $res.StatusCode = 403; continue }
      if (Test-Path -LiteralPath $full -PathType Leaf) { $bytes = [IO.File]::ReadAllBytes($full) }
    }
    if ($null -ne $bytes) { }
    elseif ($path -eq "wx.json" -or $path -eq "bus.json") {
      try { $bytes = (New-Object Net.WebClient).DownloadData($Live + $path) } catch { }
    }
    if ($null -eq $bytes) { $res.StatusCode = 404; Write-Host ("404  " + $path) -ForegroundColor DarkYellow; continue }
    $ext = [IO.Path]::GetExtension($full).ToLower()
    $res.ContentType = $(if ($Types.ContainsKey($ext)) { $Types[$ext] } else { "application/octet-stream" })
    $res.Headers.Add("Cache-Control", "no-store")
    $res.ContentLength64 = $bytes.Length
    $res.OutputStream.Write($bytes, 0, $bytes.Length)
    Write-Host ("200  " + $path)
  } catch {
    try { $res.StatusCode = 500 } catch { }
    Write-Host ("500  " + $_.Exception.Message) -ForegroundColor Red
  } finally { try { $res.Close() } catch { } }
}
