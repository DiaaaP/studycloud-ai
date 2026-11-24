param(
    [Parameter(Mandatory = $true)]
    [string]$SecretArn,
    [string]$Profile = "project",
    [string]$Region = "ap-southeast-2"
)

$ErrorActionPreference = "Stop"
$SecretFile = Join-Path ([System.IO.Path]::GetTempPath()) ("studycloud-secret-" + [guid]::NewGuid().ToString("N") + ".json")
$jwtBytes = New-Object byte[] 48
[System.Security.Cryptography.RandomNumberGenerator]::Fill($jwtBytes)
$secret = @{ jwt_secret = [Convert]::ToBase64String($jwtBytes) }
$secureGeminiKey = Read-Host "Gemini API key (leave empty to use the built-in study-material fallback)" -AsSecureString
if ($secureGeminiKey.Length -gt 0) {
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureGeminiKey)
    try { $secret.gemini_api_key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}

try {
    $json = $secret | ConvertTo-Json -Compress
    [System.IO.File]::WriteAllText($SecretFile, $json, [System.Text.UTF8Encoding]::new($false))
    & aws secretsmanager put-secret-value --secret-id $SecretArn --secret-string ("file://" + $SecretFile) --profile $Profile --region $Region --output json | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "AWS Secrets Manager did not accept the runtime secret." }
    Write-Output "Runtime secret configured. The JWT key is generated locally and was not printed."
}
finally {
    Remove-Item -LiteralPath $SecretFile -Force -ErrorAction SilentlyContinue
    if ($jwtBytes) { [Array]::Clear($jwtBytes, 0, $jwtBytes.Length) }
    if ($secret) { $secret.Clear() }
}
