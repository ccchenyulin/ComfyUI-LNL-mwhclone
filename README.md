# LNL Frame Selector V3 for ComfyUI

[English](#english) | [中文](#中文)

---

## English

The Late Night Labs (LNL) Frame Selector node enhances video interaction inside ComfyUI. It lets you upload, preview, scrub, and set In/Out points directly in the node UI, then outputs frames (and audio) for downstream processing.

### Features
- Video upload & playback (Play/Pause, step, in/out, jump).
- Timeline scrubber with In/Out markers and current frame indicator.
- Outputs for frame ranges, frame counts, current frame (abs/rel), and frame rate.
- Optional audio output for the selected range.
- Optional workflow pause to confirm trim before continuing.
- Progress overlay with step messaging while media is prepared (image sequence/audio alignment).

### Structure
The project is structured into two main components: the web directory, containing front-end JavaScript and CSS files, and the modules directory, containing back-end Python scripts.

#### Web Directory
- `eventHandlers.js`: Manages event handling for video playback and editing features.
- `nodes.js`: Defines the Frame Selector node structure and integration within ComfyUI.
- `utils.js`: Utility functions for video processing and manipulation.
- `styles.js`: Dynamic styling of the video node elements.
- `VideoPlayer/videoPlayer.js`: Main UI logic for preview, timeline, and controls.
- `css/lnlNodes.css`: Styling for the Frame Selector node components.
- `images/`: Contains icons used for playback and editing controls.

#### Modules Directory
- `server.py`: Back-end server implementation for handling video upload and processing.
- `utils.py`: Back-end utility functions supporting video editing features.
- `nodes.py`: Defines the server-side representation of the Frame Selector node.

### Installation
1. Ensure you have ComfyUI and its dependencies installed.
2. Clone this repo into `custom_nodes`:
   ```bash
   cd ComfyUI/custom_nodes
   git clone https://github.com/你的用户名/你的仓库名.git
   ```
3. Install dependencies if not downloaded from the ComfyUI Manager:
   ```bash
   cd 你的仓库名
   pip install -r requirements.txt
   ```

### Troubleshooting
- Make sure `ffmpeg`/`ffprobe` are available in your PATH.
- If numeric outputs appear as `0`, ensure the Frame Selector is connected (directly or indirectly) to an output node in the graph.

### Usage
#### Inputs
1. **Choose Video to Upload**: Select a video file for processing.
2. **Optional Image Batch**: Connect an IMAGE batch to use as the source instead of a file-based video.
3. **Optional Audio**: Connect an AUDIO input to override/externalize audio for the selected range.

> Note: When an Image Batch input is connected, the video library selector and upload button are hidden. Audio inputs are aligned to the video timeline (start at 0:0), padded/cropped to match duration, then trimmed by In/Out.

#### Outputs
1. **Current image**: Current frame being viewed.
2. **Image Batch (in/out)**: Range of frames between In/Out points.
3. **Frame in**: In point (absolute).
4. **Frame out**: Out point (absolute).
5. **Filename**: Selected video filename.
6. **Frame count (rel)**: Count of frames between In/Out.
7. **Frame count (abs)**: Total frames in the video.
8. **Current frame (rel)**: Current frame relative to In point.
9. **Current frame (abs)**: Current frame in full video.
10. **Frame rate (INT)**: FPS rounded to int.
11. **Frame rate (FLOAT)**: FPS as float.
12. **Audio**: Audio for the selected range.

> Note: Value outputs only compute when the node is connected to a downstream output node (ComfyUI execution behavior).

#### Playback Controls
![Playback controls](https://github.com/latenightlabs/ComfyUI-LNL/assets/157748925/42f2987e-b4a5-433b-a2d1-0fd33eed03ed)

##### Timeline Scrubber
- Shows the current frame number out of the total number of frames.
- **In Point** (green marker)
- **Out Point** (red marker)
- In/Out points can be set with the playback controls or directly in the input fields.

##### Media Controls (left to right)
1. Go to very first frame.
2. Set in-point.
3. Go to in-point.
4. Step backward one frame.
5. Play/Pause.
6. Step forward one frame.
7. Go to out-point.
8. Set out-point.
9. Go to last frame.

##### Numeric Input Fields
- `current_frame`: Jump to a specific frame.
- `in_point` / `out_point`: Set start/end of range.
- `select_every_nth_frame`: Step pattern for frame selection.

### Credits
This project uses code and ideas from:
- [ComfyUI-Custom-Scripts](https://github.com/pythongosssss/ComfyUI-Custom-Scripts)
- [ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite)

Player control icons are provided by [Icons8](https://icons8.com).

---

## 中文

### 简介
LNL Frame Selector（Late Night Labs 帧选择器）是一个 ComfyUI 自定义节点，可在节点界面内直接上传、预览、拖动时间轴并设置入点/出点，然后将选定帧（及音频）输出到下游处理。

### 功能
- 视频上传与播放（播放/暂停、步进、设置入/出点、跳转）
- 带出入点标记和当前帧指示器的时间轴拖动条
- 输出帧范围、帧数、当前帧（绝对/相对）、帧率
- 可选输出选定范围的音频
- 可选的工作流暂停功能，在继续执行前确认裁剪范围
- 准备媒体（图像序列/音频对齐）时显示进度信息

### 项目结构
- `web/` – 前端 JavaScript 与 CSS
- `modules/` – 后端 Python 脚本

### 安装
1. 确保已安装 ComfyUI 及其依赖。
2. 将仓库克隆到 `custom_nodes` 目录：
   ```bash
   cd ComfyUI/custom_nodes
   git clone https://github.com/你的用户名/你的仓库名.git
   ```
3. 安装额外依赖（如果未通过 ComfyUI Manager 安装）：
   ```bash
   cd 你的仓库名
   pip install -r requirements.txt
   ```

### 故障排除
- 确认 `ffmpeg`/`ffprobe` 在系统 PATH 中可用。
- 若数值输出显示为 `0`，请确保帧选择器节点直接或间接连接到了输出节点。

### 使用方法
#### 输入
- **视频文件**：点击上传按钮选择视频。
- **可选的图像批次**：连接 IMAGE 类型的输入以替代视频文件。
- **可选的音频**：连接 AUDIO 类型的输入，覆盖或提供外部音频。

#### 输出
与英文版输出说明一致，共 12 个输出端口。

#### 播放控件
- 时间轴显示当前帧和出入点。
- 媒体控制按钮：跳转到开头/结尾、设置/跳转入/出点、逐帧进退、播放/暂停。
- 数字输入框可精确设置帧位置和选择步长。

### 致谢
- [ComfyUI-Custom-Scripts](https://github.com/pythongosssss/ComfyUI-Custom-Scripts)
- [ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite)
- 播放器图标来自 [Icons8](https://icons8.com)

---

## License 许可证

This project is licensed under the **GNU General Public License v3.0 (GPL-3.0)**.  
本项目采用 **GNU General Public License v3.0 (GPL-3.0)** 许可证。

Portions of the codebase incorporate code from [ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite), which is also distributed under GPL-3.0. The original copyright notices are retained in the respective source files.  
部分代码改编自 [ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite)，该项目同样采用 GPL-3.0 协议。原始版权声明保留在相应源文件中。

Icons provided by Icons8 are used under their [license terms](https://icons8.com/license).  
Icons8 提供的图标根据其[许可条款](https://icons8.com/license)使用。

---

## Contributing 贡献
Contributions are welcome! Please open a pull request with a short description and screenshots when UI changes are involved.  
欢迎贡献！提交 PR 时请附上简短说明，若涉及 UI 改动请提供截图。
