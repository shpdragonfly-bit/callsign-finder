# 운항 도우미 개발 서버 (설치 필요 없음 · Windows PowerShell 기본 기능만 사용)
# 개발서버_시작.bat 으로 실행합니다. web 폴더를 http://localhost:8000 으로 띄우고 브라우저를 엽니다.
# - 파일을 고친 뒤 브라우저에서 새로고침하면 바로 반영 (캐시 안 함)
# - 기상(wx.json)·공항버스 시간표(bus.json)가 폴더에 없으면 실제 앱 주소에서 받아와 그대로 전달
# - localhost 에서는 앱이 사용 통계를 보내지 않음
param([int]$Port = 8000)
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
    $full = [IO.Path]::GetFullPath((Join-Path $Root $path))
    if (-not $full.StartsWith($Root)) { $res.StatusCode = 403; continue }
    $bytes = $null
    if (Test-Path -LiteralPath $full -PathType Leaf) { $bytes = [IO.File]::ReadAllBytes($full) }
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
