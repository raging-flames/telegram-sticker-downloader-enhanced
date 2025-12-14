# Telegram Sticker Downloader (Enhanced)

本项目基于 [littlebear0729/telegram_sticker_downloader](https://github.com/littlebear0729/telegram_sticker_downloader) 结合AI进行了重写与优化。


### 1. 优化
*   **多线程并发下载**：
    *   **静态贴纸**：默认 8 线程并发。
    *   **动态贴纸**：限制 3 线程，避免服务器资源耗尽。
*   **智能打包策略**：
    *   自动将大贴纸包分割为多个 Zip 文件。
    *   每个压缩包严格控制在 50MB 以内（Telegram 上传限制），同时最大化利用空间。
*   **单张贴纸支持**：
    *   **格式转换**：自动将 `.tgs` (动画) 和 `.webm` (视频) 转换为 `.gif`，将 `.webp` 转换为 `.png`。
    *   **防 MP4 转码**：单张动态贴纸发送时自动添加 `.1` 后缀，防止 Telegram 强制将其转为 MP4 视频，确保用户下载到原始 GIF 文件。

### 2. 修复
*   **透明背景修复**：解决了 WebM 转 GIF 时背景变黑或变白的问题，保留透明通道。
*   **智能帧率自适应**：
    *   自动识别源文件帧率。
    *   将最高帧率限制为 **50fps**。
*   **体积优化**：引入 **Bayer 抖动算法**，在保证画质的前提下，将高帧率 GIF 的体积减少 40%~60%。

### 3. 交互
*   **收集模式**：
    *   新增 `/add` 指令，允许用户连续发送多张零散贴纸。
    *   新增 `/pack` 指令，将收集到的贴纸打包批量下载。
    *   支持自动去重和超时自动结束。
*   **实时进度条**：
    *   实时显示下载/转换进度、并发数以及上传状态。

---

## 🚀 部署与使用

### 1. 配置
编辑 `config.json` 填入你的信息：
```json
{
  "token": "YOUR_BOT_TOKEN",
  "admin": [],       
  "whitelist": [],            
  "collection_limit": 200     
}
```

### 2. Docker 启动 (推荐)
```bash
# 构建并启动
docker-compose up -d --build
```

### 3. 手动运行
需要安装 `ffmpeg` (必须支持 libvpx-vp9) 和 Python 3.11+。
```bash
pip install -r requirements.txt
python main.py
```

## 📋 指令列表

*   `/start` - 检查机器人状态
*   `/add` - 进入**收集模式**，发送多张单张贴纸
*   `/pack` - 打包下载收集模式中的贴纸
*   **直接发送贴纸包链接** - 下载整套贴纸
*   **直接发送单张贴纸** - 立即转换并下载（GIF/PNG）
