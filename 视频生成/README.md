# 视频生成工作台

读取相邻 `../提示词生成/storage/results/` 与 `../提示词生成/storage/history/` 中的脚本结果，选择各脚本变体的分段提示词，提交 OpenProxy / Seedance 异步视频生成任务。

## 启动

```bash
cd /Users/zyb/Desktop/AI图书自动化/视频生成
python3 -m pip install -r requirements.txt
python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

浏览器打开 <http://127.0.0.1:8000>，点击页面右上方 **API 设置**，填写并安全保存 `SEEDANCE_API_KEY`。密钥只会写入当前电脑项目根目录的 `.env`（owner read/write 权限），保存后立即生效，不会返回给浏览器、写入任务记录或浏览器本地存储。也可以先执行 `cp .env.example .env` 后手动编辑。

> 此工具未配置登录认证；务必仅监听 `127.0.0.1`，不要绑定 `0.0.0.0` 或暴露到局域网/公网。

## 当前能力

- 浏览提示词生成工作台保存的结果、脚本变体和分段提示词。
- 默认使用 `jimeng_prompt`，可逐段切换为 `kling_prompt` 或手动编辑最终提交文案。
- 可选择成片时长、画面比例、清晰度和每分段生成数量；生成数量会展开成多个独立远端任务，可能分别计费，单批最多 5 个任务。
- 可手动选择模型：`Seedance 1.0 Pro` 不保证原生音频；要请求原生音频，请选择支持音频的模型并开启“同步生成原生音频”。下载后若系统可用 `ffprobe`，页面会检测 MP4 是否含音轨。
- 支持上游规范 ID `doubao-seedance-2-0-fast-260128`，页面标注为“Seedance 2.0 Fast（VIP 账户可用时）”。VIP 是账户授权/套餐前提，不是模型 ID 后缀；该模型目前仅开放文生视频、支持音频、4–15 秒或自动时长、480p/720p（不支持 1080p）。当前 OpenProxy 对该模型的账户可用性仍需以一次实际提交结果为准。
- `duration`、`ratio`、`resolution` 会直接作为候选字段提交给当前 OpenProxy；具体支持的取值仍取决于模型与账户，如被拒绝，页面会显示 Provider 的安全错误信息且不会自动重复创建任务。页面会在下载后显示“请求参数”和“实测成片规格”，不再只假设 Provider 已遵从配置。
- 如需自动检测成品的实际时长、宽高比例与音轨，可安装 FFmpeg：macOS 运行 `brew install ffmpeg`；也可在 `.env` 设置 `VIDEO_FFPROBE_PATH=/绝对路径/ffprobe`。检测工具不可用时视频仍可播放，只会显示“无法检测实际规格”。
- 将远端 task ID、本地状态、最终提示词、请求参数、进度和成品视频保存到本地 `storage/`；服务重启后可继续查询未完成任务。
- 成功后下载 MP4 至 `storage/videos/`，在网页中播放和下载。
- 图生视频 UI 与校验入口已准备好，但图片 content 的精确 Provider 契约尚未由截图证实。因此图生提交会安全终止，不会创建远端任务或产生费用。拿到官方/代理的图片请求示例后，在 `backend/seedance_provider.py` 的 `_payload()` 中补齐该分支和测试 fixture。

## API 约定

文生提交以截图信息为依据：

```json
{
  "model": "doubao-seedance-1-0-pro-250528",
  "content": [{"type": "text", "text": "最终视频提示词"}],
  "generate_audio": true
}
```

请求地址为 `POST /openproxy/rp/doubao/v3/contents/generations/tasks`，创建响应读取 `id`，后续使用 `GET /.../tasks/{id}` 轮询。API Key 仅在后端的 `SEEDANCE_API_KEY` 环境变量中使用，绝不会发送到浏览器。

## 测试

```bash
python3 -m pytest -q
```
