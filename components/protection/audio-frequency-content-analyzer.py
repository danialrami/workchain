import librosa
import numpy as np
import os
import matplotlib.pyplot as plt
from tabulate import tabulate  # For nice text table output
import argparse
import sys

def analyze_frequency_content(audio_file, n_time_frames=10, n_bands=5):
    """Analyze frequency content of an audio file over time."""
    print(f"\nAnalyzing: {os.path.basename(audio_file)}")

    # Load audio file
    try:
        y, sr = librosa.load(audio_file)
        duration = librosa.get_duration(y=y, sr=sr)
        print(f"Duration: {duration:.2f} seconds, Sample rate: {sr} Hz")
    except Exception as e:
        print(f"Error loading audio file: {e}")
        return None

    # Compute spectrogram
    S = np.abs(librosa.stft(y))

    # Convert to log scale (dB)
    S_db = librosa.amplitude_to_db(S, ref=np.max)

    # Define frequency bands with names
    freq_bands = [
        {"name": "Sub",      "range": (20, 60)},
        {"name": "Bass",     "range": (60, 250)},
        {"name": "Low-Mid",  "range": (250, 500)},
        {"name": "Mid",      "range": (500, 2000)},
        {"name": "High-Mid", "range": (2000, 5000)},
        {"name": "High",     "range": (5000, 20000)}
    ]

    # Get frequency values for each bin - make sure to use the same n_fft as the STFT
    n_fft = 2 * (S.shape[0] - 1)  # Calculate n_fft from the size of S
    freq_bins = librosa.fft_frequencies(sr=sr, n_fft=n_fft)

    # Divide signal into time frames
    times = librosa.times_like(S_db, sr=sr)
    time_indices = np.linspace(0, len(times)-1, n_time_frames+1).astype(int)

    # Store results
    results = []
    time_labels = []

    # Process each time frame
    for i in range(len(time_indices)-1):
        start_idx = time_indices[i]
        end_idx = time_indices[i+1]

        # Get time frame label
        start_time = times[start_idx]
        end_time = times[end_idx] if end_idx < len(times) else duration
        time_label = f"{start_time:.1f}-{end_time:.1f}s"
        time_labels.append(time_label)

        frame_results = {}

        # Process each frequency band
        for band in freq_bands:
            band_name = band["name"]
            low_freq, high_freq = band["range"]

            # Find bins in this frequency range
            band_mask = (freq_bins >= low_freq) & (freq_bins <= high_freq)
            if not np.any(band_mask):
                continue

            # Extract energy in this band for this time frame
            band_energy = np.mean(S_db[band_mask, start_idx:end_idx])
            frame_results[band_name] = band_energy

        results.append(frame_results)

    return {
        "time_labels": time_labels,
        "band_results": results,
        "freq_bands": freq_bands
    }

def print_analysis_results(analysis_results):
    """Print analysis results in a readable text format."""
    if not analysis_results:
        return

    time_labels = analysis_results["time_labels"]
    band_results = analysis_results["band_results"]
    freq_bands = analysis_results["freq_bands"]

    # Prepare data for tabulation
    headers = ["Time"] + [band["name"] for band in freq_bands]
    table_data = []

    for i, time_label in enumerate(time_labels):
        row = [time_label]
        for band in freq_bands:
            band_name = band["name"]
            energy = band_results[i].get(band_name, float('nan'))
            # Convert to simplified representation (0-9 scale)
            if np.isnan(energy):
                row.append("-")
            else:
                # Normalize to 0-9 scale (assuming dB values roughly from -80 to 0)
                normalized = int(((energy + 80) / 80) * 9)
                normalized = max(0, min(9, normalized))  # Clamp to 0-9
                row.append(str(normalized))
        table_data.append(row)

    # Print the table
    print("\nFrequency Content Analysis (0=silent, 9=loudest):")
    print(tabulate(table_data, headers=headers, tablefmt="grid"))

    # Add a legend explaining the frequency ranges
    print("\nFrequency Bands:")
    for band in freq_bands:
        print(f"  {band['name']}: {band['range'][0]}-{band['range'][1]} Hz")

def compare_analyses(analysis1, analysis2):
    """Compare two analysis results and show differences."""
    if not analysis1 or not analysis2:
        return

    time_labels1 = analysis1["time_labels"]
    time_labels2 = analysis2["time_labels"]
    band_results1 = analysis1["band_results"]
    band_results2 = analysis2["band_results"]
    freq_bands = analysis1["freq_bands"]  # Assuming same bands

    # Handle different time frames by using the shorter one
    min_time_frames = min(len(time_labels1), len(time_labels2))
    time_labels = time_labels1[:min_time_frames]

    # Prepare data for tabulation
    headers = ["Time"] + [f"{band['name']} Diff" for band in freq_bands]
    table_data = []

    for i in range(min_time_frames):
        row = [time_labels[i]]
        for band in freq_bands:
            band_name = band["name"]
            energy1 = band_results1[i].get(band_name, float('nan'))
            energy2 = band_results2[i].get(band_name, float('nan'))

            if np.isnan(energy1) or np.isnan(energy2):
                row.append("-")
            else:
                # Calculate difference (positive means second file has more energy)
                diff = energy2 - energy1

                # Format with sign and scaled to reflect magnitude
                if abs(diff) < 3:  # Small difference
                    row.append("≈")
                elif diff > 0:
                    strength = min(3, int(diff / 5))
                    row.append("+" * strength)
                else:
                    strength = min(3, int(abs(diff) / 5))
                    row.append("-" * strength)

        table_data.append(row)

    # Print comparison table
    print("\nFrequency Content Comparison:")
    print(tabulate(table_data, headers=headers, tablefmt="grid"))
    print("\nLegend: +++ (much louder), ++ (louder), + (slightly louder), ")
    print("        --- (much quieter), -- (quieter), - (slightly quieter), ≈ (similar)")

def get_file_path_with_fallback(input_text="Enter path to audio file: ", default_path=None):
    """Get file path from user input with error handling and fallback"""
    while True:
        try:
            file_path = input(input_text).strip()

            # Handle empty input with default
            if not file_path and default_path:
                print(f"Using default: {default_path}")
                file_path = default_path

            # Clean the path (remove quotes)
            if file_path.startswith(("\"", "'")) and file_path.endswith(("\"", "'")):
                file_path = file_path[1:-1]

            # Check if file exists
            if os.path.exists(file_path):
                return file_path
            else:
                print(f"Error: File not found: {file_path}")
                if not default_path:  # Only ask again if there's no default
                    continue
                return None
        except (EOFError, KeyboardInterrupt):
            print("\nInput interrupted. Exiting.")
            sys.exit(1)

def main(file1=None, file2=None, n_frames=8):
    """
    Main function for frequency content analysis.

    Args:
        file1: Path to first audio file (optional)
        file2: Path to second audio file for comparison (optional)
        n_frames: Number of time frames to divide the audio into
    """
    print("\n=== Audio Frequency Content Analyzer v4 ===\n")

    # Get first audio file path if not provided
    if file1 is None:
        file_path1 = get_file_path_with_fallback()
        if not file_path1:
            return
    else:
        file_path1 = file1
        print(f"Analyzing file: {file_path1}")

    # Analyze first file
    analysis1 = analyze_frequency_content(file_path1, n_time_frames=n_frames)
    if analysis1:
        print_analysis_results(analysis1)

    # If second file is provided or user wants to compare
    if file2:
        file_path2 = file2
        do_compare = True
    else:
        # Ask if user wants to compare with another file
        compare = input("\nCompare with another file? (y/n): ").strip().lower()
        do_compare = compare.startswith('y')

        if do_compare:
            file_path2 = get_file_path_with_fallback("Enter path to second audio file: ")
            if not file_path2:
                return

    # Analyze second file and compare if needed
    if do_compare:
        analysis2 = analyze_frequency_content(file_path2, n_time_frames=n_frames)
        if analysis2:
            print_analysis_results(analysis2)

        # Compare the analyses
        if analysis1 and analysis2:
            compare_analyses(analysis1, analysis2)

    print("\nAnalysis complete!")

if __name__ == "__main__":
    # Set up argument parser
    parser = argparse.ArgumentParser(description="Analyze and compare frequency content of audio files")
    parser.add_argument("--file1", help="Path to first audio file")
    parser.add_argument("--file2", help="Path to second audio file (for comparison)")
    parser.add_argument("--frames", type=int, default=8, help="Number of time frames to analyze")

    # Parse arguments
    args = parser.parse_args()

    # Run main function with provided arguments
    main(args.file1, args.file2, args.frames)
