<#
.SYNOPSIS
    Set sdlc settings as Windows USER environment variables (persist across terminals, never in a file).

.DESCRIPTION
    Prompts for each value. Secrets are read hidden and never echoed. Leave a prompt empty to keep the
    current value; type "-" to remove a variable. Open a new terminal afterwards (sdlc itself also reads
    the user scope directly, so it works in already-open terminals).

.EXAMPLE
    .\scripts\setup-env.ps1                  # walk through the common settings
    .\scripts\setup-env.ps1 -Name SDLC_ALERT_WEBHOOK
#>
param([string[]]$Name)

$settings = [ordered]@{
    SDLC_PROVIDER           = @{ Secret = $false; Help = 'mock | anthropic | openai' }
    SDLC_MODEL              = @{ Secret = $false; Help = 'model id (optional for anthropic)' }
    ANTHROPIC_API_KEY       = @{ Secret = $true;  Help = 'Claude API key' }
    OPENAI_API_KEY          = @{ Secret = $true;  Help = 'OpenAI / Azure OpenAI key' }
    SDLC_OPENAI_BASE_URL    = @{ Secret = $false; Help = 'OpenAI-compatible endpoint (Azure, Ollama)' }
    SDLC_ALERT_WEBHOOK      = @{ Secret = $true;  Help = 'Slack/Teams/Mattermost webhook URL for alerts' }
    SDLC_ALERT_MIN_SEVERITY = @{ Secret = $false; Help = 'info | warning | error | critical' }
    GITHUB_TOKEN            = @{ Secret = $true;  Help = 'token for real PRs (optional)' }
    SDLC_GITHUB_REPO        = @{ Secret = $false; Help = 'owner/name for real PRs (optional)' }
}
$names = if ($Name) { $Name } else { $settings.Keys }

foreach ($n in $names) {
    $meta = $settings[$n]
    if (-not $meta) { $meta = @{ Secret = ($n -match 'KEY|TOKEN|SECRET|PASSWORD|WEBHOOK'); Help = '' } }
    $current = [Environment]::GetEnvironmentVariable($n, 'User')
    $shown = if (-not $current) { 'not set' } elseif ($meta.Secret) { 'set' } else { $current }
    $prompt = "$n ($($meta.Help)) [current: $shown]"
    if ($meta.Secret) {
        $secure = Read-Host -Prompt $prompt -AsSecureString
        $value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
    } else {
        $value = Read-Host -Prompt $prompt
    }
    if ($value -eq '-') {
        [Environment]::SetEnvironmentVariable($n, $null, 'User'); Write-Host "  removed $n"
    } elseif ($value) {
        [Environment]::SetEnvironmentVariable($n, $value, 'User'); Write-Host "  saved $n (user scope)"
    }
    $value = $null
}
Write-Host "`nDone. Check with: sdlc config   and   sdlc doctor"
