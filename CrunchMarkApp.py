#!/usr/bin/env python3
import sys, os, subprocess, json, argparse, tempfile
from fractions import Fraction

INSTAGRAM_VIDEO_FLAGS = [
    '-profile:v', 'high', '-level', '4.0',
    '-pix_fmt', 'yuv420p',
    '-movflags', '+faststart',
    '-maxrate', '3500k', '-bufsize', '7000k',
]

EXPORT_TIPS = """
╔══════════════════════════════════════════════════════════════════════════════╗
║              CrunchMark — Optimal Export Settings for Instagram             ║
╚══════════════════════════════════════════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ADOBE LIGHTROOM CLASSIC — Photo Export Settings
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Format: JPEG · Quality: 100 · Color Space: sRGB (CRITICAL) · File Size Limit: OFF
  Sizing: Long Edge 1080px  |  Portrait 1080×1350  |  Stories 1080×1920  |  72 PPI
  Sharpening: Screen / Standard  |  Metadata: Copyright Only
  Tips: Edit in Rec.709/sRGB · +10–15 Clarity pre-export · avoid heavy NR

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  DAVINCI RESOLVE — Video Deliver Settings (Reels / Feed)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Format: MP4 · Codec: H.264 High 4.0 · Pixel Format: YUV 4:2:0 (CRITICAL)
  Reels/Stories: 1080×1920  |  Feed Portrait: 1080×1350  |  Square: 1080×1080
  Frame Rate: match source, cap at 30fps for Reels
  Bitrate: 10–15 Mbps target / 20 Mbps max · Keyframe: every 1 sec
  Audio: AAC-LC · 48000 Hz · Stereo · 320 kbps
  Color: Rec.709 / Gamma 2.4 · HDR OFF · Data levels: Video (16–235)
  Fast Start: ON · Burn in captions (IG strips embedded subs)
  Tips: always export from original camera file · normalize audio to -14 LUFS
        Reels: keep under 90 sec / 1 GB · 60fps → render at source, let IG downconvert
"""


def get_video_info(path):
    cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json',
           '-select_streams', 'v:0', '-count_packets',
           '-show_entries', 'stream=width,height,r_frame_rate,duration', path]
    info = json.loads(subprocess.run(cmd, capture_output=True, text=True).stdout)
    s = info['streams'][0]
    try:
        fps = float(Fraction(s.get('r_frame_rate', '0')))
    except Exception:
        fps = 0.0
    return {'width': s['width'], 'height': s['height'],
            'framerate': f"{fps:.2f}", 'duration': float(s.get('duration', 0.0))}


def simulate_instagram_photo(input_path, output_path=None):
    try:
        from PIL import Image, ImageCms
    except ImportError:
        sys.exit("[CrunchMark] Install Pillow first: pip install Pillow")

    if output_path is None:
        base, _ = os.path.splitext(input_path)
        output_path = f"{base}_instagram_sim.jpg"

    img = Image.open(input_path)
    srgb = ImageCms.createProfile("sRGB")
    try:
        if img.info.get("icc_profile"):
            src = ImageCms.ImageCmsProfile(__import__('io').BytesIO(img.info["icc_profile"]))
            img = ImageCms.profileToProfile(img, src, srgb, outputMode="RGB")
        else:
            img = img.convert("RGB")
    except Exception:
        img = img.convert("RGB")

    w, h = img.size
    if max(w, h) > 1080:
        scale = 1080 / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        print(f"  Resized: {w}x{h} -> {img.size[0]}x{img.size[1]}")

    img.save(output_path, "JPEG", quality=75, subsampling=2, optimize=True)

    orig, sim = os.path.getsize(input_path), os.path.getsize(output_path)
    print(f"  Original: {orig/1024:.1f} KB  ->  Simulated: {sim/1024:.1f} KB  "
          f"({(1 - sim/orig)*100:.1f}% reduction)")

    try:
        import numpy as np
        from skimage.metrics import structural_similarity as ssim
        a = np.array(Image.open(input_path).convert("RGB").resize(img.size, Image.LANCZOS), dtype=np.float32) / 255
        b = np.array(Image.open(output_path).convert("RGB"), dtype=np.float32) / 255
        print(f"  SSIM: {ssim(a, b, channel_axis=2, data_range=1.0):.4f}  (1.0 = identical)")
    except ImportError:
        print("  (pip install scikit-image numpy for SSIM scoring)")

    print(f"[CrunchMark] Photo simulation -> {output_path}")


def process_videos(vid1, vid2, output, args):
    label_1 = args.label1 or os.path.basename(vid1)
    label_2 = args.label2 or os.path.basename(vid2)
    info = get_video_info(vid1)
    w, h, duration = info['width'], info['height'], info['duration']
    freq = args.sweep_speed / 60.0

    if args.vertical:
        blend   = f'if(gte(Y,H*(0.5+0.5*sin(2*PI*{freq}*T))),A,B)'
        overlay = f'0:(H-{args.divider_width})*(0.5+0.5*sin(2*PI*{freq}*t))'
        dsize   = f'{w}x{args.divider_width}'
    else:
        blend   = f'if(gte(X,W*(0.5+0.5*sin(2*PI*{freq}*T))),A,B)'
        overlay = f'(W-{args.divider_width})*(0.5+0.5*sin(2*PI*{freq}*t)):0'
        dsize   = f'{args.divider_width}x{h}'

    dt = f"drawtext=fontfile={args.font}:fontsize={args.fontsize}:fontcolor=white@0.8:box=1:boxcolor=black@0.5:boxborderw=5"
    fc = (
        f"[0:v][1:v]scale2ref[v0][v1];"
        f"[v0]{dt}:x=10:y=10:text='{label_1}',{dt}:x=10:y=h-th-10:text='{label_1}'[v0l];"
        f"[v1]{dt}:x=w-tw-10:y=10:text='{label_2}',{dt}:x=w-tw-10:y=h-th-10:text='{label_2}'[v1l];"
        f"[v0l][v1l]blend=all_expr='{blend}':shortest=1[blended];"
        f"color=white:s={dsize}[bar];[blended][bar]overlay='{overlay}'"
    )

    ig_flags = INSTAGRAM_VIDEO_FLAGS if args.instagram else ['-pix_fmt', 'yuv420p']

    cmd = (
        ['ffmpeg', '-y', '-i', vid1, '-i', vid2,
         '-filter_complex', fc, '-map', '0:a?',
         '-c:a', 'aac', '-b:a', '128k', '-ar', '48000',
         '-c:v', 'libx264', '-preset', args.preset, '-crf', str(args.crf)]
        + ig_flags
        + ['-t', str(duration), output]
    )

    print(f"\n[CrunchMark] Rendering -> {output}")
    subprocess.run(cmd, check=True)
    if args.instagram:
        print("[CrunchMark] Instagram flags: H.264 High 4.0 · yuv420p · 3.5 Mbps · faststart · AAC 128k/48kHz")
    print(f"[CrunchMark] Done -> {output}")


def main():
    p = argparse.ArgumentParser(prog="crunchmark",
        description="CrunchMark -- Instagram Compression Simulator & Export Optimizer")
    p.add_argument("input_video_1", nargs="?")
    p.add_argument("input_video_2", nargs="?")
    p.add_argument("output_video",  nargs="?")
    p.add_argument("--label1");  p.add_argument("--label2")
    p.add_argument("--sweep-speed",   type=float, default=20)
    p.add_argument("--divider-width", type=int,   default=8)
    p.add_argument("--font",    default="/Library/Fonts/Arial.ttf")
    p.add_argument("--fontsize", type=int, default=28)
    p.add_argument("--preset",  default="slow")
    p.add_argument("--crf",     type=int, default=18)
    p.add_argument("--vertical",    action="store_true")
    p.add_argument("--instagram",   action="store_true")
    p.add_argument("--photo",       metavar="IMAGE_PATH")
    p.add_argument("--photo-out",   metavar="OUTPUT_PATH")
    p.add_argument("--export-tips", action="store_true")
    args = p.parse_args()

    if args.export_tips:
        print(EXPORT_TIPS); sys.exit(0)

    if args.photo:
        if not os.path.isfile(args.photo):
            sys.exit(f"Error: '{args.photo}' not found.")
        simulate_instagram_photo(args.photo, args.photo_out)
        sys.exit(0)

    if not all([args.input_video_1, args.input_video_2, args.output_video]):
        p.print_help(); sys.exit(1)

    for f in [args.input_video_1, args.input_video_2]:
        if not os.path.isfile(f) or not os.access(f, os.R_OK):
            sys.exit(f"Error: '{f}' not found or unreadable.")

    if args.instagram and args.input_video_1 == args.input_video_2:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            print(f"\n[CrunchMark] Generating Instagram simulation of {args.input_video_1}")
            subprocess.run(
                ['ffmpeg', '-y', '-i', args.input_video_1,
                 '-c:v', 'libx264', '-preset', 'slow', '-crf', '23',
                 '-c:a', 'aac', '-b:a', '128k', '-ar', '48000']
                + INSTAGRAM_VIDEO_FLAGS + [tmp_path],
                check=True
            )
            args.label1 = args.label1 or "Original"
            args.label2 = args.label2 or "Instagram Sim"
            process_videos(args.input_video_1, tmp_path, args.output_video, args)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    else:
        process_videos(args.input_video_1, args.input_video_2, args.output_video, args)


if __name__ == "__main__":
    main()
