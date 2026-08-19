
import os
import random
import numpy as np
import subprocess
from PIL import Image, ImageDraw, ImageChops
import warnings
import argparse
import logging
import sys

# Try importing glitch_this, handle if missing
try:
    from glitch_this import ImageGlitcher
except ImportError:
    print("Error: Could not import glitch_this. Please install it (")
    print("pip install glitch-this")
    sys.exit(1)

# Setup logging
logger = logging.getLogger("canvas_generator")
logger.setLevel(logging.INFO) # Default level
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

warnings.filterwarnings("ignore", category=Image.DecompressionBombWarning)

# Constants
TARGET_WIDTH = 720  # Spotify Canvas minimum width
TARGET_HEIGHT = 1280  # Spotify Canvas minimum height (9:16 ratio)
CANVAS_DURATION = 8  # Spotify requires exactly 8 seconds

def check_ffmpeg():
    """Check if FFmpeg is installed"""
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
        if result.returncode == 0:
            logger.info("FFmpeg found.")
            return True
        else:
            logger.error("FFmpeg command failed.")
            return False
    except FileNotFoundError:
        logger.error("FFmpeg is not installed or not in PATH. MP4 conversion will fail.")
        return False
    except Exception as e:
        logger.error(f"Error checking FFmpeg: {e}")
        return False

def apply_smearing(image, strength=20):
    """Apply a digital smearing effect to the image"""
    try:
        img_array = np.array(image)
        height, width = img_array.shape[:2]
        for x in range(width):
            if random.random() < 0.1:  # 10% chance of smearing each column
                streak_height = random.randint(10, strength)
                y_start = random.randint(0, height - streak_height)
                for y in range(y_start, min(y_start + streak_height, height)):
                    if y > 0:
                        alpha = 1.0 - ((y - y_start) / streak_height)
                        # Ensure integer arithmetic for colors
                        img_array[y] = (img_array[y].astype(float) * alpha + img_array[y-1].astype(float) * (1-alpha)).astype(img_array.dtype)
        return Image.fromarray(img_array)
    except Exception as e:
        logger.warning(f"Error applying smearing: {e}")
        return image # Return original if smearing fails

def blend_images(img1, img2, alpha):
    """Blend two images with given alpha value"""
    try:
        # Ensure images are in RGB format for blending
        img1_rgb = img1.convert("RGB")
        img2_rgb = img2.convert("RGB")
        return Image.blend(img1_rgb, img2_rgb, alpha)
    except Exception as e:
        logger.warning(f"Error blending images: {e}")
        return img1 # Return first image if blending fails

def create_crossfade_frames(glitch_frames, num_transition_frames=5):
    """Create smooth transitions between glitch frames with smearing"""
    logger.info("Applying crossfade and smearing effects...")
    smoothed_frames = []
    num_glitch_frames = len(glitch_frames)
    if num_glitch_frames == 0:
        logger.warning("No glitch frames provided for crossfade.")
        return []

    for i in range(num_glitch_frames):
        current_frame = glitch_frames[i]
        next_frame = glitch_frames[(i + 1) % num_glitch_frames]

        # Apply smearing (handle potential errors)
        current_frame_smeared = apply_smearing(current_frame, strength=40)
        next_frame_smeared = apply_smearing(next_frame, strength=40)

        smoothed_frames.append(current_frame_smeared)

        for j in range(num_transition_frames):
            alpha = (j + 1) / (num_transition_frames + 1)
            transition_frame = blend_images(current_frame_smeared, next_frame_smeared, alpha)
            # Apply smearing to transition frame
            transition_frame_smeared = apply_smearing(transition_frame, strength=30)
            smoothed_frames.append(transition_frame_smeared)

    logger.info(f"Generated {len(smoothed_frames)} frames after crossfade.")
    return smoothed_frames

def convert_gif_to_mp4(gif_path, output_path):
    """Convert GIF to MP4 with proper Spotify Canvas settings"""
    logger.info("Converting GIF to MP4 format...")
    if not check_ffmpeg():
        return False
    try:
        cmd = [
            "ffmpeg",
            "-i", gif_path,
            "-movflags", "+faststart",
            "-pix_fmt", "yuv420p",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", # Ensure dimensions are even
            "-r", "30", # Frame rate
            "-t", str(CANVAS_DURATION), # Exact duration
            "-an", # No audio
            "-y", # Overwrite output file
            output_path
        ]
        logger.debug(f"FFmpeg command: {' '.join(cmd)}")
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.info("MP4 conversion successful.")
        logger.debug(f"FFmpeg output:\n{result.stderr}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Error converting GIF to MP4: {e}")
        logger.error(f"FFmpeg stderr:\n{e.stderr}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during MP4 conversion: {e}", exc_info=True)
        return False

def create_spotify_canvas(input_image_path, output_dir):
    """Generates Spotify Canvas assets (static PNG, GIF, MP4) in the specified output directory."""
    logger.info(f"Starting Spotify Canvas generation for: {input_image_path}")
    try:
        if not os.path.isfile(input_image_path):
            logger.error(f"Input image file not found: {input_image_path}")
            return None

        base_name = os.path.splitext(os.path.basename(input_image_path))[0]
        # Remove potential _artwork suffix if present from previous step
        if base_name.endswith("_artwork"):
            base_name = base_name[:-len("_artwork")]

        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"Output directory: {output_dir}")

        glitcher = ImageGlitcher()

        # Calculate frame duration for GIF to achieve ~8 seconds total
        # Total frames = FRAMES * (1 + TRANSITION_FRAMES)
        FRAMES = 24 # Number of base glitch frames
        TRANSITION_FRAMES = 3 # Number of frames between each glitch frame
        total_frames_in_loop = FRAMES * (1 + TRANSITION_FRAMES)
        # Duration per frame in milliseconds
        DURATION_MS = max(10, int(CANVAS_DURATION * 1000 / total_frames_in_loop))
        logger.info(f"Generating {FRAMES} base glitch frames with {TRANSITION_FRAMES} transition frames each.")
        logger.info(f"Targeting {DURATION_MS}ms per frame for GIF.")

        logger.info("Opening and processing image...")
        image = Image.open(input_image_path).convert("RGBA")

        if image.size[0] < TARGET_WIDTH or image.size[1] < TARGET_HEIGHT:
            logger.warning(f"Input image resolution ({image.size[0]}x{image.size[1]}) is lower than target ({TARGET_WIDTH}x{TARGET_HEIGHT}).")

        # Calculate cropping needed to achieve 9:16 aspect ratio
        original_aspect = image.size[0] / image.size[1]
        canvas_aspect = TARGET_WIDTH / TARGET_HEIGHT

        if abs(original_aspect - canvas_aspect) < 0.01: # Already correct aspect ratio (approx)
            new_width, new_height = TARGET_WIDTH, TARGET_HEIGHT
            resized_image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            cropped_image = resized_image
            logger.info(f"Image already has ~9:16 aspect ratio. Resizing to {TARGET_WIDTH}x{TARGET_HEIGHT}.")
        elif original_aspect > canvas_aspect: # Wider than 9:16, crop sides
            scale_factor = TARGET_HEIGHT / image.size[1]
            new_width = int(image.size[0] * scale_factor)
            new_height = TARGET_HEIGHT
            resized_image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            left = (new_width - TARGET_WIDTH) // 2
            right = left + TARGET_WIDTH
            top = 0
            bottom = TARGET_HEIGHT
            cropped_image = resized_image.crop((left, top, right, bottom))
            logger.info(f"Image is wider than 9:16. Resizing and cropping sides to {TARGET_WIDTH}x{TARGET_HEIGHT}.")
        else: # Taller than 9:16, crop top/bottom
            scale_factor = TARGET_WIDTH / image.size[0]
            new_width = TARGET_WIDTH
            new_height = int(image.size[1] * scale_factor)
            resized_image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            left = 0
            right = TARGET_WIDTH
            top = (new_height - TARGET_HEIGHT) // 2
            bottom = top + TARGET_HEIGHT
            cropped_image = resized_image.crop((left, top, right, bottom))
            logger.info(f"Image is taller than 9:16. Resizing and cropping top/bottom to {TARGET_WIDTH}x{TARGET_HEIGHT}.")

        # Ensure final image is RGB for glitching and saving
        if cropped_image.mode != "RGB":
            cropped_image = cropped_image.convert("RGB")

        logger.info("Generating glitch effects...")
        glitch_imgs = glitcher.glitch_image(
            cropped_image,
            3.0,  # Glitch intensity
            color_offset=True,
            scan_lines=True,
            gif=True,
            frames=FRAMES
        )

        if not glitch_imgs:
             logger.error("Failed to generate glitch frames.")
             return None

        smoothed_frames = create_crossfade_frames(glitch_imgs, TRANSITION_FRAMES)
        if not smoothed_frames:
             logger.error("Failed to create crossfade frames.")
             return None

        logger.info("Saving output files...")
        static_path = os.path.join(output_dir, f"{base_name}_canvas_static.png")
        gif_path = os.path.join(output_dir, f"{base_name}_canvas.gif")
        mp4_path = os.path.join(output_dir, f"{base_name}_canvas.mp4")

        # Save static image
        cropped_image.save(static_path)
        logger.info(f"Static canvas saved: {static_path}")

        # Save GIF
        smoothed_frames[0].save(
            gif_path,
            format="GIF",
            append_images=smoothed_frames[1:],
            save_all=True,
            duration=DURATION_MS,
            loop=0 # Loop indefinitely
        )
        logger.info(f"GIF canvas saved: {gif_path}")

        # Convert GIF to MP4
        mp4_success = convert_gif_to_mp4(gif_path, mp4_path)
        if mp4_success:
            logger.info(f"MP4 canvas saved: {mp4_path}")
            return static_path, gif_path, mp4_path
        else:
            logger.warning("MP4 conversion failed. Only static and GIF files were saved.")
            return static_path, gif_path, None # Indicate MP4 failure

    except FileNotFoundError as e:
        logger.error(f"File not found error during canvas generation: {e}")
        return None
    except Exception as e:
        logger.error(f"Error processing image for canvas: {e}", exc_info=True)
        return None

def main():
    parser = argparse.ArgumentParser(description="Generate Spotify Canvas assets (static, GIF, MP4) from an image.")
    parser.add_argument("input_image", help="Path to the input artwork image file.")
    parser.add_argument("--output_dir", required=True, help="Directory to save the generated canvas files.")
    parser.add_argument("--log_file", help="Path to append processing logs.")

    args = parser.parse_args()

    # Configure logging to file if specified
    if args.log_file:
        logger.removeHandler(handler) # Avoid duplicate console logs
        file_handler = logging.FileHandler(args.log_file, mode="a")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        # Optionally add back a stream handler
        # logger.addHandler(handler)

    logger.info("Spotify Canvas Generator (Integrated Workflow)")
    logger.info("---------------------------------------------")

    result = create_spotify_canvas(args.input_image, args.output_dir)

    if result:
        logger.info("Canvas generation finished.")
        if result[2] is None: # Check if MP4 path is None
            logger.warning("MP4 conversion failed or was skipped.")
            sys.exit(0) # Exit successfully, but indicate MP4 issue
        else:
            sys.exit(0)
    else:
        logger.error("Canvas generation failed.")
        sys.exit(1)

if __name__ == "__main__":
    main()
