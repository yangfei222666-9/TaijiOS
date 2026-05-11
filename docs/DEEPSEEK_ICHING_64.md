# DeepSeek I Ching 64 Runner

This runner processes all 64 I Ching hexagrams and writes auditable artifacts:

```text
runs/iching/deepseek_iching_64_YYYYMMDD_HHMMSS_mmmmmm_<pid>_<nonce>/summary.json
runs/iching/deepseek_iching_64_YYYYMMDD_HHMMSS_mmmmmm_<pid>_<nonce>/event_flow.jsonl
runs/iching/deepseek_iching_64_YYYYMMDD_HHMMSS_mmmmmm_<pid>_<nonce>/iching_64_report.md
runs/iching/deepseek_iching_64_YYYYMMDD_HHMMSS_mmmmmm_<pid>_<nonce>/hexagrams/*.json
runs/iching/latest_output_dir.txt
```

Dry-run mode does not call DeepSeek:

```bash
python examples/deepseek_iching_64.py
python examples/validate_deepseek_iching_64.py
```

Live mode requires `DEEPSEEK_API_KEY`:

```bash
python examples/deepseek_iching_64.py --live
python examples/validate_deepseek_iching_64.py
```

To avoid repeatedly pasting the key, store it locally with Windows DPAPI:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\save_deepseek_key_dpapi.ps1
powershell -ExecutionPolicy Bypass -File scripts\run_deepseek_iching_live.ps1
```

The encrypted key is written under `data/secrets/`, which is ignored by git and
can only be decrypted by the same Windows user on the same machine.
The live helper fails closed if the runner or validator exits with a non-zero
status, so it will not silently validate stale artifacts after a failed run.
By default it first looks for a completed live run and validates it instead of
starting another 64-call batch. Use `-Fresh` only when you intentionally want a
new live run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_deepseek_iching_live.ps1 -Fresh
```

By default each run writes to a unique timestamp, microseconds, pid and nonce
directory. The validator reads `runs/iching/latest_output_dir.txt` when no
output directory is provided. Pass `--output-dir` to intentionally resume or
validate a specific directory.

Resume is enabled by default. Completed per-hexagram JSON files are reused when
the cache key matches the model, mode, temperature, max tokens and prompt hash.

Useful options:

```bash
python examples/deepseek_iching_64.py --live --fresh
python examples/deepseek_iching_64.py --live --no-cache
python examples/deepseek_iching_64.py --live --retry-attempts 3 --retry-delay-s 2
python examples/deepseek_iching_64.py --print-full
```

The summary includes token totals, cache-hit count, API-attempt count, retry
count and estimated USD cost. Pricing is estimated only and can be overridden:

```bash
set DEEPSEEK_INPUT_CACHE_HIT_USD_PER_1M=0.0028
set DEEPSEEK_INPUT_CACHE_MISS_USD_PER_1M=0.14
set DEEPSEEK_OUTPUT_USD_PER_1M=0.28
```

Outputs are marked `learning_only=true` and include a disclaimer that they are
not divination, investment, medical or legal advice.
