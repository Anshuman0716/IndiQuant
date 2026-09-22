$sources = @(
    "nse_corporate_actions",
    "nse_fundamentals",
    "nse_index_membership"
)

foreach ($source in $sources) {
    Write-Host "Starting backfill for $source..."
    $env:Path = "C:\Users\anshu\.local\bin;$env:Path"
    uv run iq ingest backfill --from 2015-01-01 --to 2024-12-31 --source $source
    Write-Host "Finished backfill for $source."
}
