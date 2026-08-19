
import numpy as np
import soundfile as sf
import librosa
import os
import sys
import traceback
import time
import subprocess
import argparse
import logging
from pathlib import Path

# Import from the psychoacoustic utilities
# Assuming psyac_utils_v3.py is in the same directory or Python path
try:
    from psyac_utils_v3 import (
        hz2bark, bark2hz, spreadingfunctionmat_v3,
        mapping2barkmat_v3, mapping2bark_v3, mappingfrombarkmat_v3, mappingfrombark_v3,
        maskingThreshold_v3
    )
except ImportError:
    print("Error: Could not import psyac_utils_v3. Ensure psyac_utils_v3.py is in the same directory or Python path.")
    sys.exit(1)

# Setup logging
logger = logging.getLogger("protect_audio")
logger.setLevel(logging.INFO) # Default level
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

def generate_adversarial_noise_psyac_chunk_v3(audio_chunk_channel, sr, strength, nfft, hop_length, nfilts, alpha, W, W_inv, spreadingfuncmatrix):
    """Applies psychoacoustically shaped adversarial noise to a single channel audio chunk.
    Version 3: Focus on minimal audible impact, adds noise below threshold.
    """
    if np.all(np.abs(audio_chunk_channel) < 1e-7): # Use a slightly higher threshold for silence detection
        # logger.debug("Skipping silent chunk.")
        return audio_chunk_channel # Return original silent chunk

    try:
        # 1. Calculate Short-Time Fourier Transform (STFT)
        stft_chunk = librosa.stft(audio_chunk_channel, n_fft=nfft, hop_length=hop_length, center=True)
        magnitude, phase = librosa.magphase(stft_chunk)
        n_frames = magnitude.shape[1]
        n_freq_bins = magnitude.shape[0] # nfft // 2 + 1

        # Initialize array for the noise STFT
        noise_stft = np.zeros_like(stft_chunk, dtype=complex)

        # 2. Process each time frame individually
        for frame_idx in range(n_frames):
            mX_frame = magnitude[:, frame_idx]

            # 3. Calculate masking threshold in linear frequency scale (amplitude)
            mT_frame = maskingThreshold_v3(mX_frame, sr, nfft, nfilts, alpha, W, W_inv, spreadingfuncmatrix)

            # Ensure mT_frame has the correct length (nfft // 2 + 1)
            if len(mT_frame) != n_freq_bins:
                 logger.warning(f"Masking threshold length mismatch ({len(mT_frame)} vs {n_freq_bins}). Resizing.")
                 mT_frame_resized = np.zeros(n_freq_bins)
                 min_len = min(len(mT_frame), n_freq_bins)
                 mT_frame_resized[:min_len] = mT_frame[:min_len]
                 if n_freq_bins > len(mT_frame):
                     mT_frame_resized[len(mT_frame):] = np.min(mT_frame) if len(mT_frame) > 0 else 1e-12
                 mT_frame = mT_frame_resized

            # 4. Generate noise shaped by the masking threshold
            noise_complex = (np.random.randn(n_freq_bins) + 1j * np.random.randn(n_freq_bins)) * (1 / np.sqrt(2))

            # Scale noise amplitude to be proportional to the masking threshold
            mT_frame_safe = np.maximum(mT_frame, 1e-12)
            shaped_noise_complex = noise_complex * mT_frame_safe * strength

            # Store the generated noise for this frame
            noise_stft[:, frame_idx] = shaped_noise_complex

        # 5. Inverse STFT of the noise component ONLY
        noise_audio_channel = librosa.istft(noise_stft, n_fft=nfft, hop_length=hop_length, center=True, length=len(audio_chunk_channel))

        # 6. Add the generated noise to the ORIGINAL audio chunk
        perturbed_audio_channel = audio_chunk_channel + noise_audio_channel

        return perturbed_audio_channel

    except Exception as e:
        logger.error(f"Error during psychoacoustic noise generation for chunk: {e}", exc_info=True)
        return audio_chunk_channel

def apply_adversarial_encoding_v4(input_file, output_file, strength=0.4, block_duration_sec=5, nfft=2048, nfilts=64, alpha=0.6):
    """
    Apply psychoacoustically refined adversarial encoding chunk by chunk (Version 4).
    Saves output directly to output_file.

    Args:
        input_file (str): Path to the input audio file.
        output_file (str): Path to save the output audio file.
        strength (float, optional): Controls the level of noise relative to the masking threshold. Defaults to 0.4.
        block_duration_sec (int, optional): Duration of audio chunks to process in seconds. Defaults to 5.
        nfft (int, optional): FFT size for STFT. Defaults to 2048.
        nfilts (int, optional): Number of filters for the Bark scale analysis. Defaults to 64.
        alpha (float, optional): Exponent for non-linear superposition in masking calculation. Defaults to 0.6.

    Returns:
        tuple: (output_file_path, processing_time) or (None, 0) if an error occurred.
    """
    start_time = time.time()
    try:
        logger.info(f"Processing file: {input_file}")
        if not os.path.isfile(input_file):
            logger.error(f"Input file not found at {input_file}")
            return None, 0

        # Ensure output directory exists
        output_dir_for_file = os.path.dirname(output_file)
        if not os.path.exists(output_dir_for_file):
            logger.info(f"Creating directory for output file: {output_dir_for_file}")
            os.makedirs(output_dir_for_file, exist_ok=True)

        # Get original audio info using soundfile
        try:
            info = sf.info(input_file)
            original_samplerate = info.samplerate
            original_channels = info.channels
            original_subtype = info.subtype
            original_format = info.format
            total_frames = info.frames
            logger.info(f"Input Info: SR={original_samplerate}, Channels={original_channels}, Subtype={original_subtype}, Format={original_format}, Frames={total_frames}")
        except Exception as e:
            logger.error(f"Error reading audio info: {e}", exc_info=True)
            return None, 0

        # --- Precompute psychoacoustic model components ---
        logger.info("Precomputing psychoacoustic model components...")
        maxfreq = original_samplerate / 2.0
        W = mapping2barkmat_v3(original_samplerate, nfilts, nfft)
        W_inv = mappingfrombarkmat_v3(W)
        spreadingfuncmatrix = spreadingfunctionmat_v3(nfilts, alpha)
        logger.info(f"Using NFFT={nfft}, Bark Filters={nfilts}, Alpha={alpha}")

        # Calculate block size and hop length
        blocksize_sec = block_duration_sec
        blocksize_frames = int(original_samplerate * blocksize_sec)
        if blocksize_frames == 0:
            logger.error("Block duration too short or sample rate zero.")
            return None, 0
        hop_length = nfft // 4
        sf_overlap = nfft
        if blocksize_frames <= sf_overlap:
             logger.warning(f"Block size ({blocksize_frames}) <= STFT overlap ({sf_overlap}). Increasing block size.")
             blocksize_frames = sf_overlap + hop_length
             blocksize_sec = blocksize_frames / original_samplerate
             logger.info(f"Adjusted block duration: {blocksize_sec:.2f} seconds")

        logger.info(f"Processing in chunks of {blocksize_sec:.2f} seconds ({blocksize_frames} frames) with sf_overlap {sf_overlap} frames...")

        # --- Process and Write Chunk by Chunk ---
        processed_frames_count = 0
        with sf.SoundFile(input_file, 'r') as infile, sf.SoundFile(output_file, 'w', original_samplerate, original_channels, subtype=original_subtype, format=original_format) as outfile:
            for block_index, block in enumerate(infile.blocks(blocksize=blocksize_frames, dtype='float32', always_2d=True, overlap=sf_overlap, fill_value=0)):
                current_block_frames = block.shape[0]
                if current_block_frames == 0: continue

                write_start_idx = sf_overlap // 2 if block_index > 0 else 0
                frames_in_this_pass = current_block_frames - sf_overlap if block_index > 0 else current_block_frames - sf_overlap // 2

                is_last_block = (processed_frames_count + frames_in_this_pass >= total_frames)
                if is_last_block:
                    frames_in_this_pass = total_frames - processed_frames_count

                write_end_idx = write_start_idx + frames_in_this_pass

                if frames_in_this_pass <= 0: continue

                # Use logger.info for progress, avoid spamming stdout directly
                if block_index % 10 == 0: # Log progress every 10 blocks
                     logger.info(f"Processing frames {processed_frames_count} to {processed_frames_count + frames_in_this_pass - 1} / {total_frames}")

                block_t = block.T
                processed_block_channels = []

                for i in range(original_channels):
                    processed_channel = generate_adversarial_noise_psyac_chunk_v3(
                        block_t[i], original_samplerate, strength, nfft, hop_length, nfilts, alpha, W, W_inv, spreadingfuncmatrix
                    )
                    if len(processed_channel) != current_block_frames:
                        processed_channel = np.resize(processed_channel, current_block_frames)
                    processed_block_channels.append(processed_channel)

                processed_block = np.vstack(processed_block_channels).T

                # Clipping
                if np.issubdtype(processed_block.dtype, np.floating):
                    max_val = 1.0
                    min_val = -1.0
                    clipped_samples = np.sum(np.abs(processed_block) > max_val)
                    if clipped_samples > 0:
                         logger.debug(f"Clipping {clipped_samples} samples in block starting near frame {processed_frames_count}")
                         processed_block = np.clip(processed_block, min_val, max_val)

                # Write valid part
                write_data = processed_block[write_start_idx:write_end_idx, :]

                if write_data.shape[0] > 0:
                    outfile.write(write_data)
                    processed_frames_count += write_data.shape[0]

        logger.info(f"Processed {processed_frames_count} frames.")
        logger.info(f"Final protected audio saved to: {output_file}")
        end_time = time.time()
        processing_time = end_time - start_time
        logger.info(f"Processing took {processing_time:.2f} seconds.")
        return output_file, processing_time

    except Exception as e:
        logger.error(f"An unexpected error occurred during encoding: {e}", exc_info=True)
        return None, 0

def run_frequency_analyzer(input_file, protected_file, output_dir, report_file):
    """Run the frequency content analyzer and generate HTML report."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    possible_analyzer_names = [
        "audio-frequency-content-analyzer-v4.py",
        "audio-frequency-content-analyzer.py"
    ]
    analyzer_script = None
    for script_name in possible_analyzer_names:
        path = os.path.join(script_dir, script_name)
        if os.path.exists(path):
            analyzer_script = path
            break

    if not analyzer_script:
        logger.error(f"Analyzer script not found in {script_dir}")
        return False, "Analyzer script not found"

    logger.info("--- Running Frequency Content Analyzer --- ")
    analysis_log_content = ""
    try:
        input_data = f"{input_file}\ny\n{protected_file}\n"
        process = subprocess.run(
            ["python3", analyzer_script],
            input=input_data,
            text=True,
            capture_output=True,
            check=True
        )
        analysis_log_content = process.stdout
        logger.info("Analyzer script finished.")
        # Save analyzer output to a log file (can be the main log or a separate one)
        # The bash script handles the main logging, but we can save the raw output here if needed.
        analysis_log_path = os.path.join(output_dir, os.path.splitext(os.path.basename(protected_file))[0] + "_analysis.log")
        try:
            with open(analysis_log_path, "w") as log_f:
                log_f.write(analysis_log_content)
            logger.info(f"Analyzer output saved to {analysis_log_path}")
        except Exception as log_e:
            logger.warning(f"Could not save separate analysis log: {log_e}")

        # Generate HTML report using the analysis content
        try:
            with open(report_file, "w") as rf:
                # Basic HTML structure
                rf.write("<!DOCTYPE html><html><head><title>Protection Analysis Report</title>")
                rf.write("<style>body { font-family: sans-serif; } pre { background-color: #f0f0f0; padding: 10px; border-radius: 5px; } </style>")
                rf.write("</head><body><h1>Protection Analysis Report</h1>")
                rf.write(f"<p>Comparison between original ({os.path.basename(input_file)}) and protected ({os.path.basename(protected_file)}).</p>")
                rf.write("<h2>Analyzer Output:</h2><pre>")
                # Basic HTML escaping
                escaped_content = analysis_log_content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                rf.write(escaped_content)
                rf.write("</pre></body></html>")
            logger.info(f"HTML analysis report saved to: {report_file}")
            return True, analysis_log_content
        except Exception as report_e:
            logger.error(f"Could not create HTML report: {report_e}", exc_info=True)
            return False, analysis_log_content # Return true for analysis, but report failed

    except subprocess.CalledProcessError as e:
        logger.error(f"Error running analyzer script: {e}")
        logger.error(f"STDOUT: {e.stdout}")
        logger.error(f"STDERR: {e.stderr}")
        return False, e.stderr
    except Exception as e:
        logger.error(f"Error during analysis: {e}", exc_info=True)
        return False, str(e)

# --- Main Execution ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apply psychoacoustic adversarial protection to an audio file.")
    parser.add_argument("input_file", help="Path to the input audio file.")
    parser.add_argument("--output_file", required=True, help="Path to save the protected audio file.")
    parser.add_argument("--strength", type=float, default=0.4, help="Perturbation strength (0.01-1.0). Default: 0.4")
    parser.add_argument("--output_dir", required=True, help="Directory to save logs and reports.")
    parser.add_argument("--report_file", required=True, help="Path to save the HTML analysis report.")
    parser.add_argument("--log_file", help="Path to append processing logs.")
    parser.add_argument("--nfft", type=int, default=2048, help="FFT size. Default: 2048")
    parser.add_argument("--nfilts", type=int, default=64, help="Number of Bark filters. Default: 64")
    parser.add_argument("--alpha", type=float, default=0.6, help="Masking curve exponent. Default: 0.6")
    parser.add_argument("--block_duration", type=float, default=5.0, help="Processing block duration in seconds. Default: 5.0")

    args = parser.parse_args()

    # Configure logging to file if specified
    if args.log_file:
        # Remove existing stream handler to avoid duplicate console logs
        logger.removeHandler(handler)
        # Add file handler (append mode)
        file_handler = logging.FileHandler(args.log_file, mode='a')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        # Optionally add back a stream handler if console output is still desired
        # logger.addHandler(handler)

    logger.info("Audio Adversarial Perturbation Tool (Version 4.1 - Integrated Workflow)")
    logger.info("---------------------------------------------------------------------")

    # Validate strength
    if args.strength < 0.01:
        logger.warning(f"Strength ({args.strength}) is very low. Setting to 0.01.")
        args.strength = 0.01
    elif args.strength > 1.0:
        logger.warning(f"Strength ({args.strength}) is high, may cause artifacts.")

    logger.info(f"Using Parameters: Strength={args.strength}, NFFT={args.nfft}, BarkFilters={args.nfilts}, Alpha={args.alpha}, BlockSec={args.block_duration}")

    # Call the encoding function
    output_path, proc_time = apply_adversarial_encoding_v4(
        args.input_file,
        args.output_file,
        strength=args.strength,
        block_duration_sec=args.block_duration,
        nfft=args.nfft,
        nfilts=args.nfilts,
        alpha=args.alpha
    )

    if output_path:
        logger.info(f"Protection processing finished successfully in {proc_time:.2f} seconds.")
        # Run analyzer and generate report
        analysis_success, analysis_output = run_frequency_analyzer(
            args.input_file,
            args.output_file,
            args.output_dir, # Directory for saving _analysis.log
            args.report_file # Full path for HTML report
        )
        if not analysis_success:
            logger.error("Frequency analysis or report generation failed.")
            # Still exit 0 as protection succeeded, but log indicates analysis failure
            sys.exit(0)
        else:
             logger.info("Frequency analysis and report generation completed.")
             sys.exit(0)
    else:
        logger.error("Protection processing failed.")
        sys.exit(1)
