from moviepy import AudioFileClip
import os

INPUT_AUDIO = r"D:\files\fangtan.m4a"
OUTPUT_DIR = r"D:\files\chunks"

os.makedirs(OUTPUT_DIR, exist_ok=True)

TARGET_MB = 10
BITRATE = "96k"

def split_fixed():
    audio = AudioFileClip(INPUT_AUDIO)
    duration = audio.duration

    # 估算 96k ≈ 0.75MB/min
    mb_per_sec = 0.75 / 60

    max_seconds = TARGET_MB / mb_per_sec

    print(f"单段最大时长: {max_seconds/60:.2f} 分钟")

    start = 0
    idx = 0

    while start < duration:
        end = min(start + max_seconds, duration)

        chunk = audio.subclipped(start, end)

        out_path = os.path.join(
            OUTPUT_DIR,
            f"chunk_{idx:02d}.mp3"
        )

        chunk.write_audiofile(
            out_path,
            bitrate=BITRATE,
            logger=None
        )

        real_size = os.path.getsize(out_path) / (1024*1024)
        print(f"生成: {out_path} | {real_size:.2f} MB")

        start = end
        idx += 1

    audio.close()

if __name__ == "__main__":
    split_fixed()