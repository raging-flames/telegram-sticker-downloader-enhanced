[中文](README.md)

# Telegram Sticker Downloader (Enhanced)

This project is a rewrite and optimization based on [littlebear0729/telegram_sticker_downloader](https://github.com/littlebear0729/telegram_sticker_downloader), **combined with AI**.


### 1. Optimizations
*   **Concurrent Downloading**:
    *   **Static Stickers**: Default to 8 threads.
    *   **Dynamic Stickers**: Limited to 3 threads to avoid exhausting server resources.
*   **Smart Packaging Strategy**:
    *   Automatically splits large sticker sets into multiple Zip files.
    *   Each archive is strictly kept under 50MB (Telegram's upload limit) while maximizing space usage.
*   **Single Sticker Support**:
    *   **Format Conversion**: Automatically converts `.tgs` (Animated) and `.webm` (Video) to `.gif`, and `.webp` to `.png`.
    *   **Prevent MP4 Conversion**: Automatically appends a `.1` suffix when sending single dynamic stickers to prevent Telegram from forcibly converting them to MP4 video, ensuring users download the original GIF file.

### 2. Fixes
*   **Transparent Background Fix**: Solved the issue where WebM to GIF conversion resulted in black or white backgrounds, preserving the transparent channel.
*   **Smart Frame Rate Adaptation**:
    *   Automatically identifies the source file frame rate.
    *   Limits the maximum frame rate to **50fps**.
*   **Size Optimization**: Introduced **Bayer Dithering Algorithm**, reducing the size of high frame rate GIFs by 40%~60% while maintaining image quality.

### 3. Interaction
*   **Collection Mode**:
    *   New `/add` command allows users to continuously send multiple individual stickers.
    *   New `/pack` command packs and downloads the collected stickers in a batch.
    *   Supports automatic deduplication and timeout auto-termination.
*   **Real-time Progress Bar**:
    *   Real-time display of download/conversion progress, concurrency count, and upload status.

---

## 🚀 Deployment & Usage

### 1. Clone the Project
First, clone the repository to your local server:
```bash
git clone https://github.com/raging-flames/telegram-sticker-downloader-enhanced.git
cd telegram-sticker-downloader-enhanced
```

### 2. Configuration
Open `config.json` with text editor:

Fill in your Telegram Bot Token and Admin IDs:
```json
{
  "token": "YOUR_BOT_TOKEN_HERE",
  "admin": [123456789],       
  "whitelist": [],            
  "collection_limit": 200     
}
```

### 3. Run with Docker (Recommended)
This is the easiest and recommended way, as it avoids manual dependency installation (like FFmpeg).
```bash
# Build and start in detached mode
docker-compose up -d --build

# View logs
docker-compose logs -f
```

### 4. Manual Run (Alternative)
If you prefer not to use Docker, ensure your system has Python 3.11+ and `ffmpeg` (must support libvpx-vp9) installed.

**Install Dependencies (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install ffmpeg python3-pip
```

**Run the Bot:**
```bash
pip install -r requirements.txt
python main.py
```

## 📋 Command List

*   `/start` - Check bot status
*   `/add` - Enter **Collection Mode** to send multiple single stickers
*   `/pack` - Pack and download stickers from Collection Mode
*   **Send Sticker Set Link** - Download the entire sticker set
*   **Send Single Sticker** - Convert and download immediately (GIF/PNG)
