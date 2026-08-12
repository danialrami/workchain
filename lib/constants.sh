#!/bin/bash

# Constants for audio workchain v2

# Get the directory where this file is located
LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKCHAIN_ROOT="$(cd "$LIB_DIR/.." && pwd)"

ENGINE_DIR="$WORKCHAIN_ROOT/engine"
COMPONENTS_DIR="$WORKCHAIN_ROOT/components"
CHAINS_DIR="$WORKCHAIN_ROOT/chains"

# (is_audio_file) rejects anything not listed here, so a scanner-supported format that is
# missing from this list fails every file with "Input file is not a supported audio format".
SUPPORTED_AUDIO_EXTENSIONS=("wav" "mp3" "aiff" "aif" "flac" "m4a" "ogg" "caf" "aifc" "oga" "opus" "aac" "wv" "alac")

DEFAULT_LUFS_TARGET=-11
DEFAULT_PROTECTION_STRENGTH=0.4
DEFAULT_SATURATION=0.5
