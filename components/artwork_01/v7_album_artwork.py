
import subprocess
import hashlib
import os
import time
import numpy as np
from PIL import Image, ImageEnhance
import librosa
import librosa.display
import matplotlib.pyplot as plt
import io
import argparse
import logging
import sys

# Setup logging
logger = logging.getLogger("album_artwork")
logger.setLevel(logging.INFO) # Default level
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

def hash_audio_file(file_path):
    """Generate a hash from an audio file."""
    logger.info("Analyzing audio fingerprint...")
    sha256 = hashlib.sha256()
    try:
        with open(file_path, 'rb') as f:
            while True:
                data = f.read(65536)
                if not data:
                    break
                sha256.update(data)
        hash_value = sha256.hexdigest()
        logger.info(f"Audio hash: {hash_value[:8]}...{hash_value[-8:]}")
        return hash_value
    except FileNotFoundError:
        logger.error(f"Audio file not found for hashing: {file_path}")
        return None
    except Exception as e:
        logger.error(f"Error hashing audio file: {e}", exc_info=True)
        return None

def create_identicon(hash_value, output_dir, size=5000):
    """Create an identicon from a hash value with timeout protection."""
    logger.info("Generating identicon...")
    identicon_path = os.path.join(output_dir, 'identicon.png')

    # Try portable approaches in order of preference. Never bake a developer's absolute checkout
    # path into a component: the engine is designed to move between machines and hosted runners.
    component_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(component_dir, "../.."))
    local_jdenticon = os.path.join(repo_root, "node_modules", ".bin", "jdenticon")
    jdenticon_commands = []
    if os.path.isfile(local_jdenticon):
        jdenticon_commands.append([local_jdenticon, hash_value, "--size", str(size), "--output", identicon_path])
    jdenticon_commands.extend([
        # Use an already-installed package only; do not make a render download dependencies.
        ["npx", "--no-install", "jdenticon", hash_value, "--size", str(size), "--output", identicon_path],
        # Try a global installation last; the deterministic Pillow fallback below remains valid.
        ["jdenticon", hash_value, "--size", str(size), "--output", identicon_path],
    ])

    for i, cmd in enumerate(jdenticon_commands):
        try:
            logger.info(f"Trying jdenticon approach {i+1}: {' '.join(cmd[:2])}")

            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,  # Reduced timeout to 30 seconds
                env=os.environ.copy()
            )

            logger.info("Identicon created successfully.")
            return Image.open(identicon_path).convert('RGBA')

        except subprocess.TimeoutExpired:
            logger.warning(f"jdenticon approach {i+1} timed out after 30 seconds")
            continue
        except FileNotFoundError:
            logger.warning(f"jdenticon approach {i+1} - command not found")
            continue
        except subprocess.CalledProcessError as e:
            logger.warning(f"jdenticon approach {i+1} failed: {e}")
            continue
        except Exception as e:
            logger.warning(f"jdenticon approach {i+1} error: {e}")
            continue

    # If all approaches failed, create a simple fallback
    logger.error("All jdenticon approaches failed. Creating simple fallback identicon.")
    try:
        # Create a simple geometric pattern based on the hash
        from PIL import ImageDraw
        import random

        # Seed random with hash for consistent patterns
        random.seed(int(hash_value[:8], 16))

        img = Image.new('RGBA', (size, size), (0, 0, 0, 255))
        draw = ImageDraw.Draw(img)

        # Generate colors from hash
        colors = []
        for i in range(0, min(24, len(hash_value)), 8):
            r = int(hash_value[i:i+2], 16) if i+2 <= len(hash_value) else 128
            g = int(hash_value[i+2:i+4], 16) if i+4 <= len(hash_value) else 128
            b = int(hash_value[i+4:i+6], 16) if i+6 <= len(hash_value) else 128
            colors.append((r, g, b, 255))

        if not colors:
            colors = [(128, 128, 128, 255)]

        # Draw simple geometric pattern
        grid_size = 8
        cell_size = size // grid_size

        for row in range(grid_size):
            for col in range(grid_size//2):  # Only half for symmetry
                if random.random() > 0.5:
                    color = random.choice(colors)
                    # Draw on both sides for symmetry
                    x1 = col * cell_size
                    y1 = row * cell_size
                    x2 = (col + 1) * cell_size
                    y2 = (row + 1) * cell_size
                    draw.rectangle([x1, y1, x2, y2], fill=color)

                    # Mirror on the right side
                    mirror_col = grid_size - 1 - col
                    mx1 = mirror_col * cell_size
                    mx2 = (mirror_col + 1) * cell_size
                    draw.rectangle([mx1, y1, mx2, y2], fill=color)

        img.save(identicon_path, optimize=True)
        logger.info(f"Fallback identicon created: {identicon_path}")
        return img

    except Exception as e:
        logger.error(f"Failed to create fallback identicon: {e}")
        return None

def create_improved_spectrogram(audio_file_path, components_dir, saturation_level=0.5):
    """Create an ultra-high-resolution spectrogram, save components, and return a 5000x5000 square section."""
    logger.info("Generating ultra-high-resolution spectrogram...")
    try:
        y, sr = librosa.load(audio_file_path)
        duration = len(y) / sr

        # Calculate dimensions to target a ~20000×5000px image
        target_width = 20000
        target_height = 5000

        # Work backwards to determine figure size and DPI
        # For a 4:1 aspect ratio at ultra-high resolution
        dpi = 400  # Significantly increased DPI

        # Calculate figure dimensions needed to reach target pixels
        width = target_width / dpi
        height = target_height / dpi

        logger.info(f"Using figure dimensions: {width:.1f}x{height:.1f} inches at {dpi} DPI")
        logger.info(f"Target pixel dimensions: {target_width}x{target_height}")

        # Use significantly more mel bands for vertical resolution
        S = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=512)  # Increased from 256
        S_dB = librosa.power_to_db(S, ref=np.max)

        # Create the figure at massive size
        plt.figure(figsize=(width, height), dpi=dpi)
        librosa.display.specshow(S_dB, x_axis='time', y_axis='mel', sr=sr, fmax=8000)
        plt.axis('off')
        plt.tight_layout(pad=0)

        # Save with maximum resolution (removed quality parameter since not supported)
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', pad_inches=0, dpi=dpi)
        buf.seek(0)
        plt.close()

        # Open the image and ensure RGBA mode for processing
        spec_img = Image.open(buf).convert('RGBA')
        logger.info(f"Raw spectrogram dimensions: {spec_img.size[0]}x{spec_img.size[1]} pixels")

        # Check if we have enough width for our target
        img_width, img_height = spec_img.size
        logger.info(f"Initial dimensions: {img_width}x{img_height} pixels")

        # Always ensure we have at least a 4:1 aspect ratio
        if img_width < img_height * 4:
            logger.warning("Spectrogram not wide enough. Forcing 4:1 aspect ratio...")
            target_width = img_height * 4
            new_img = Image.new('RGBA', (target_width, img_height), (0, 0, 0, 0))
            # Stretch the image to fill the width
            resized_img = spec_img.resize((target_width, img_height), Image.LANCZOS)
            new_img.paste(resized_img, (0, 0))
            spec_img = new_img
            logger.info(f"Forced aspect ratio to 4:1: {spec_img.size[0]}x{spec_img.size[1]} pixels")

        # Apply saturation adjustment
        if saturation_level != 1.0:
            logger.info(f"Adjusting saturation to {saturation_level}...")
            enhancer = ImageEnhance.Color(spec_img)
            spec_img = enhancer.enhance(saturation_level)

        # Get updated dimensions
        img_width, img_height = spec_img.size

        # Save the full rectangular spectrogram - use optimize=True instead of quality
        rectangle_filename = "rectangle_spectrogram.png"
        full_rect_path = os.path.join(components_dir, rectangle_filename)
        spec_img.save(full_rect_path, optimize=True)
        logger.info(f"Saved full rectangular spectrogram to: {full_rect_path}")

        # Determine target square size - we want a 5000x5000 square
        target_square_size = 5000

        # If the height is less than target_square_size, we need to resize before cropping
        if img_height < target_square_size:
            scale_factor = target_square_size / img_height
            new_width = int(img_width * scale_factor)
            new_height = target_square_size
            logger.info(f"Resizing to {new_width}x{new_height} to get {target_square_size}x{target_square_size} crop")
            spec_img = spec_img.resize((new_width, new_height), Image.LANCZOS)
            img_width, img_height = new_width, new_height

        # Now we should have a height of at least target_square_size
        # Take a square from the middle that's target_square_size x target_square_size
        left = (img_width - target_square_size) // 2
        right = left + target_square_size
        top = 0
        bottom = target_square_size

        # Ensure we don't go out of bounds
        if left < 0:
            left = 0
            right = min(target_square_size, img_width)
        if right > img_width:
            right = img_width
            left = max(0, img_width - target_square_size)

        # Crop the 5000x5000 square from the middle width-wise
        square_spec_img = spec_img.crop((left, top, right, bottom))

        # Check the dimensions of the square crop
        sq_width, sq_height = square_spec_img.size
        logger.info(f"Square crop dimensions: {sq_width}x{sq_height}")

        # If we didn't get a 5000x5000 square (e.g., if the image wasn't big enough),
        # resize it to exactly 5000x5000
        if sq_width != 5000 or sq_height != 5000:
            logger.warning(f"Square crop not 5000x5000. Resizing to exact dimensions...")
            square_spec_img = square_spec_img.resize((5000, 5000), Image.LANCZOS)
            logger.info("Resized square crop to exactly 5000x5000")

        # Save the square spectrogram to components_dir - use optimize=True instead of quality
        square_filename = "spectrogram.png"
        square_spec_path = os.path.join(components_dir, square_filename)
        square_spec_img.save(square_spec_path, optimize=True)
        logger.info(f"Saved 5000x5000 square spectrogram to: {square_spec_path}")

        # Calculate the audio time range represented by the square section
        time_position = (left / img_width) * duration
        time_end = (right / img_width) * duration
        logger.info(f"Spectrogram segment covers audio from {time_position:.2f}s to {time_end:.2f}s")

        return square_spec_img

    except FileNotFoundError:
        logger.error(f"Audio file not found for spectrogram: {audio_file_path}")
        return None
    except Exception as e:
        logger.error(f"Error creating spectrogram: {e}", exc_info=True)
        return None

def set_image_alpha(image, alpha_value):
    """Set the alpha channel for the entire image."""
    if image.mode != 'RGBA':
        image = image.convert('RGBA')
    r, g, b, a = image.split()
    new_alpha = Image.new('L', image.size, color=alpha_value)
    image.putalpha(new_alpha)
    return image

def resize_identicon(identicon, scale=0.4):
    """Resize the identicon by a scale factor."""
    width, height = identicon.size
    new_size = (int(width * scale), int(height * scale))
    return identicon.resize(new_size, Image.LANCZOS)  # Added LANCZOS for high quality

def create_album_artwork_v7(audio_file_path, output_dir, components_dir, output_name, saturation_level=0.5):
    """Create album artwork using v7 logic with ultra-high resolution components."""
    logger.info("Starting the v7 Ultra-High Resolution Album Artwork Generator")

    # Ensure output directories exist
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(components_dir, exist_ok=True)
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Components directory: {components_dir}")

    hash_value = hash_audio_file(audio_file_path)
    if not hash_value:
        return None # Error handled in hash_audio_file

    # Create identicon (saved in components_dir) at 5000x5000
    identicon = create_identicon(hash_value, components_dir)
    if not identicon:
        return None # Error handled in create_identicon

    # Create ultra-high resolution spectrogram
    # The function now directly returns a 5000x5000 square crop
    spectrogram = create_improved_spectrogram(audio_file_path, components_dir, saturation_level)
    if not spectrogram:
        return None # Error handled in create_improved_spectrogram

    # Check and confirm dimensions
    spec_width, spec_height = spectrogram.size
    icon_width, icon_height = identicon.size
    logger.info(f"Working with spectrogram: {spec_width}x{spec_height}, identicon: {icon_width}x{icon_height}")

    # Both images should now be exactly 5000x5000
    composite_size = (5000, 5000)

    # If either isn't 5000x5000 for some reason, resize it (shouldn't happen, but just in case)
    if spec_width != 5000 or spec_height != 5000:
        logger.warning(f"Spectrogram not exactly 5000x5000, resizing...")
        spectrogram = spectrogram.resize(composite_size, Image.LANCZOS)

    # Boost saturation to compensate for transparency
    # logger.info("Boosting spectrogram saturation to compensate for transparency...")
    # enhancer = ImageEnhance.Color(spectrogram)
    # spectrogram = enhancer.enhance(1.8)  # Boost saturation by 80%

    # Also boost contrast slightly to make features more visible
    logger.info("Enhancing spectrogram contrast...")
    contrast_enhancer = ImageEnhance.Contrast(spectrogram)
    spectrogram = contrast_enhancer.enhance(1.1)  # Boost contrast by 10%

    # Make spectrogram semi-transparent
    # logger.info("Adjusting spectrogram transparency...")
    # spectrogram = set_image_alpha(spectrogram, 127) # opacity at 50%

    # Resize identicon for overlay
    logger.info("Resizing identicon for overlay...")
    identicon_resized = resize_identicon(identicon) # Default scale 0.4
    identicon_resized.putalpha(255) # Full opacity

    # Create final composite image with black background
    logger.info("Creating final composite image...")
    final_image = Image.new('RGBA', composite_size, (0, 0, 0, 255))

    # Composite spectrogram first (background)
    final_image.alpha_composite(spectrogram)

    # Center the resized identicon (foreground)
    position = (
        (composite_size[0] - identicon_resized.size[0]) // 2,
        (composite_size[1] - identicon_resized.size[1]) // 2
    )
    final_image.alpha_composite(identicon_resized, position)

    # Convert final image to RGB before saving
    final_image_rgb = final_image.convert('RGB')

    # Save the final artwork with optimization
    output_path = os.path.join(output_dir, f'{output_name}.png')
    try:
        final_image_rgb.save(output_path, optimize=True)
        logger.info(f"Album artwork generated successfully: {output_path}")
        return output_path
    except Exception as e:
        logger.error(f"Error saving final artwork: {e}", exc_info=True)
        return None

def main():
    parser = argparse.ArgumentParser(description="Generate ultra-high-resolution album artwork v7 from an audio file.")
    parser.add_argument("input_file", help="Path to the input audio file.")
    parser.add_argument("--output_dir", help="Directory to save the final artwork PNG.", default=".")
    parser.add_argument("--components_dir", help="Directory to save component files (identicon, spectrograms).", default="./components")
    parser.add_argument("--output_name", help="Base name for the output artwork file (without extension).", default=None)
    parser.add_argument("--saturation", type=float, default=0.5, help="Spectrogram saturation level (0.0-2.0). Default: 0.5")
    parser.add_argument("--log_file", help="Path to append processing logs.")

    args = parser.parse_args()

    # Configure logging to file if specified
    if args.log_file:
        logger.removeHandler(handler) # Avoid duplicate console logs if appending
        file_handler = logging.FileHandler(args.log_file, mode='a')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        # Optionally add back a stream handler if console output is still desired
        # logger.addHandler(handler)

    logger.info("Ultra-High Resolution Album Artwork Generator v7 (5000x5000 Edition)")
    logger.info("-------------------------------------------------")

    # Validate saturation
    args.saturation = max(0.0, min(2.0, args.saturation))
    logger.info(f"Using saturation level: {args.saturation}")

    # If output_name not provided, use the base name of the input file
    if not args.output_name:
        args.output_name = os.path.splitext(os.path.basename(args.input_file))[0]
        logger.info(f"Using default output name: {args.output_name}")

    # Run the artwork creation process
    logger.info(f"Processing audio file: {args.input_file}")
    logger.info(f"Output will be saved as: {os.path.join(args.output_dir, f'{args.output_name}.png')}")
    logger.info(f"Component files will be saved in: {args.components_dir}")

    try:
        artwork_path = create_album_artwork_v7(
            args.input_file,
            args.output_dir,
            args.components_dir,
            args.output_name,
            args.saturation
        )

        if artwork_path:
            logger.info(f"Ultra-high resolution (5000x5000) artwork generation finished successfully.")
            logger.info(f"Final artwork saved at: {artwork_path}")
            sys.exit(0)
        else:
            logger.error("Artwork generation failed. Check logs for details.")
            sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error during execution: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
