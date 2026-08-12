#!/bin/bash
# Frequency band energy distribution analysis
# Adapted from audio-benchmarks/audio_spectral.sh for LUFS workchain

# Usage: run_spectral_check <input_file>
# Outputs JSON result to stdout, logs to stderr
run_spectral_check() {
    local FILE="$1"
    local STATUS="pass"
    
    echo "Analyzing spectral balance..." >&2
    
    # Use python3 to run ffmpeg and construct JSON (FILE via env — quoted heredoc,
    # robust to apostrophes/spaces in the audio path).
    __WC_FILE="$FILE" python3 << 'EOF'
import subprocess
import re
import json
import sys
import os

bands = [
    ("Sub", 20, 80),
    ("Low Mids", 80, 250),
    ("Mids", 250, 4000),
    ("High Mids", 4000, 8000),
    ("Presence", 8000, 12000),
    ("Air", 12000, 20000)
]

results = {}
for name, lo, hi in bands:
    freq = (lo + hi) // 2
    width = hi - lo
    ffmpeg_cmd = [
        'ffmpeg', '-i', os.environ['__WC_FILE'], '-af',
        f'bandpass=f={freq}:width_type=h:w={width},astats=metadata=1',
        '-f', 'null', '-'
    ]
    try:
        proc = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=30)
        output = proc.stderr
        
        # Extract RMS level (last occurrence)
        rms_matches = re.findall(r'RMS level dB:\s*([-\d.]+)', output)
        if rms_matches:
            rms = float(rms_matches[-1])
            results[name] = rms
            print(f"  {name}: {rms} dB", file=sys.stderr, flush=True)
        else:
            results[name] = None
    except Exception as e:
        results[name] = None

print(json.dumps(results))
EOF
    
    return 0
}
