
## PaddleOCR 安装与版本注意事项

### 版本兼容性（关键）
- **PaddleOCR 3.4.0** 需要搭配 **PaddlePaddle 3.2.2**
- **不要使用 PaddlePaddle 3.3.0**：存在 oneDNN 推理 bug，会报错：
  ```
  NotImplementedError: ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<pir::DoubleAttribute>]
  ```
  这是 PaddlePaddle 3.3.0 在 Windows CPU 推理时的已知问题（见 https://github.com/PaddlePaddle/Paddle/issues/77340）
- 已验证可用组合: `paddlepaddle==3.2.2` + `paddleocr==3.4.0`

### Windows 长路径问题
- `modelscope` 包含超长路径文件，在 Windows 上可能安装失败
- 错误信息: `OSError: [Errno 2] No such file or directory` + 提示启用 Long Path Support
- 解决方案：使用虚拟环境（venv）安装，路径较短，可以避免此问题
- 或者启用 Windows 长路径支持: `reg add "HKLM\SYSTEM\CurrentControlSet\Control\FileSystem" /v LongPathsEnabled /t REG_DWORD /d 1 /f`

### 安装命令
```bash
python -m venv venv
source venv/Scripts/activate  # Windows Git Bash
pip install paddlepaddle==3.2.2 paddleocr opencv-python numpy
```

### PaddleOCR 2.x vs 3.x API 差异（关键）
PaddleOCR 3.x 对 API 做了大幅改动，2.x 的代码不能直接用于 3.x。

#### 构造函数变化
```python
# 2.x 旧参数 → 3.x 新参数
use_angle_cls  → use_textline_orientation
det_db_thresh  → text_det_thresh
det_db_box_thresh → text_det_box_thresh
use_gpu=False  → (已移除，默认 CPU)
show_log=False → (已移除，改用新日志系统)
```

#### 3.x 构造函数
```python
from paddleocr import PaddleOCR
ocr = PaddleOCR(
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
    lang="ch",
    text_det_thresh=0.3,
    text_det_box_thresh=0.5,
    # 可选参数:
    # text_detection_model_name="PP-OCRv5_server_det",
    # text_recognition_model_name="PP-OCRv5_server_rec",
    # device="cpu",  # 或 "gpu:0"
    # ocr_version="PP-OCRv5",  # 或 PP-OCRv4, PP-OCRv3
)
```

#### 调用方法变化
```python
# 2.x
results = ocr.ocr(image_path, cls=True)
# results[0] 是 [box, (text, score)] 的列表

# 3.x
results = ocr.predict(image_path)  # ocr.ocr() 已废弃
for res in results:
    data = res.json
    texts = data["res"]["rec_texts"]      # 文字列表
    scores = data["res"]["rec_scores"]    # 置信度列表
    polys = data["res"]["dt_polys"]       # 检测多边形 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
    boxes = data["res"]["rec_boxes"]      # 矩形框 [x_min, y_min, x_max, y_max]
    # 可视化
    res.save_to_img("output_dir")
    res.save_to_json("output_dir")
```
### 模型缓存位置
- 模型自动下载到 `C:\Users\<user>\.paddlex\official_models\`
- 默认使用 PP-OCRv5_server_det 和 PP-OCRv5_server_rec