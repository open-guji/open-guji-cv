# s4: 倾斜/透视校正 (deskew)

## 概述

| 项目 | 说明 |
|------|------|
| 编号 | s4 |
| 文件夹 | `s4_deskew/` |
| 源文件 | `guji_preprocess/preprocessors/normalize.py` |
| 类名 | `NormalizePreprocessor` |
| 执行条件 | 始终执行 |
| 输入 | s3 输出（增强后的图片） |
| 输出 | 校正倾斜/透视后的图片 |

## 背景

古籍扫描/拍摄时会产生两类几何失真：

1. **整体旋转倾斜**：相机/扫描仪略有倾斜，整页统一偏转一个角度
2. **透视变形（梯形畸变）**：相机不完全平行于纸面，导致上下/左右边框角度不一致

单纯旋转只能校正第一类问题，透视变换可以同时解决两类。

## 算法：两阶段策略

### 阶段 1：透视校正（首选）

```
1. LSD 检测线段 → 分类水平/垂直
2. 共线性聚类（border_detect.cluster_lines）
3. 检测四条边框线：
   - 上/下边框：_find_border_pair(h_clusters, "min"/"max")
   - 左/右边框：_find_border_pair(v_clusters, "min"/"max")
4. 安全检查：
   - 需要全部 4 条边框
   - 每条边框覆盖率 >= 40%
   - slope < tan(5°)
   - 角点在图像范围内（±5% 容差）
   - 四边形面积 > 图像 20%
   - 最大 slope > tan(0.1°)（太小则不需要校正）
5. 计算四角交点 → cv2.getPerspectiveTransform → cv2.warpPerspective
6. 保持原图完整区域（锚定 tl 位置，计算变换后图像四角确定输出尺寸）
7. 验证：校正后用投影法测量残余角度，如果没有改善则放弃
```

### 阶段 2：投影法旋转（回退）

当透视校正失败（边框检测不完整）时回退到旋转：

```
1. Canny 边缘检测（缩放到 800px 加速）
2. 粗搜：±3° 范围，步长 0.1°
   - 对每个角度旋转边缘图
   - 计算水平投影（按行求和）的 sum of squares（尖锐度）
   - 尖锐度最大的角度 = 最佳角度
3. 精搜：粗搜最优值 ±0.2°，步长 0.02°
4. 安全范围：0.1° < |angle| < 5°
5. cv2.getRotationMatrix2D → cv2.warpAffine
```

### 内容保留设计

透视校正时，目标矩形以原始 tl 位置为锚点（不移到原点）：

```python
dst_pts = [[ox, oy], [ox+frame_w, oy], [ox+frame_w, oy+frame_h], [ox, oy+frame_h]]
```

然后计算变换后原图四角的位置，确保输出尺寸包含所有内容（不裁切边框外的版心等区域）。

## 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MAX_CORRECTION_ANGLE` | 5.0° | 最大校正角度 |
| `MIN_CORRECTION_ANGLE` | 0.1° | 最小校正角度（低于此不校正） |
| `_SEARCH_RANGE` | 3.0° | 投影法粗搜范围 |
| `_COARSE_STEP` | 0.1° | 粗搜步长 |
| `_FINE_RANGE` | 0.2° | 精搜范围 |
| `_FINE_STEP` | 0.02° | 精搜步长 |
| `_MIN_LINE_LENGTH` | 30 | LSD 最小线段长度 |
| `_ANGLE_TOL` | 10.0° | 水平/垂直判定角度容差 |

## 依赖

- `border_detect.py` → `cluster_lines()`, `_find_border_pair()`, `_intersect_hv()`
