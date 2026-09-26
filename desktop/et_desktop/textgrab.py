# -*- coding: utf-8 -*-
"""屏幕取词：UIA（Windows 辅助功能）为主，视觉模型 OCR 为兜底。

实测（2026-09-23，Windows 11 + Python 3.14 + uiautomation 2.0.29）：
  · `TextPattern.RangeFromPoint(x, y)` + `ExpandToEnclosingUnit(TextUnit.Word)`
    能精确取到光标下那个英文单词，浏览器、记事本、Word、Electron 系应用都支持；
  · 词下方偏一点（约 6px）也能取到 —— 与浏览器扩展的行盒容差一致；
  · 取不到的情形（图片、游戏、自绘 UI）交给视觉模型 OCR 兜底；两者都没有则静默。
"""
from __future__ import annotations

import base64
import io
import json
import os
import time
import urllib.request

from PIL import Image, ImageDraw

from .lookup import extract_word_at, is_english_word, is_letter_like

try:
    import uiautomation as auto
except Exception:                     # 未装依赖时仍可只用 OCR 兜底
    auto = None

TEXTUNIT_WORD = 2                     # IUIAutomation TextUnit_Word


def word_at_point_uia(x: int, y: int):
    """落点 → (单词, 是否看到文字)。

    第二个返回值很关键：辅助功能说「这里有文字，但不是英文」时，
    必须就此静默（中文上不弹窗的产品铁律）；只有「根本没有文字」才轮到 OCR 兜底。
    """
    if auto is None:
        return None, False
    try:
        ctrl = auto.ControlFromPoint(int(x), int(y))
    except Exception:
        return None, False
    if ctrl is None:
        return None, False

    node = ctrl
    for _ in range(24):
        if node is None:
            break
        try:
            pattern = node.GetTextPattern()
        except Exception:
            pattern = None
        if pattern is not None:
            try:
                rng = pattern.RangeFromPoint(int(x), int(y))
                if rng is None:
                    return None, False
                rng.ExpandToEnclosingUnit(TEXTUNIT_WORD)
                got = (rng.GetText(64) or "").strip()
            except Exception:
                return None, False
            if not got:
                return None, False
            # 「点空白处不翻译」：ExpandToEnclosingUnit 会把落点扩展成邻近的词，
            # 光标在词间空白上时也会抓到旁边的词。校验词的边界矩形确实包含光标。
            try:
                rects = rng.GetBoundingRectangles()
                if rects:
                    inside = any(r.left - 4 <= x <= r.right + 4 and
                                 r.top - 4 <= y <= r.bottom + 4 for r in rects)
                    if not inside:
                        # 离得近（词间空白/词缝）→ 按产品铁律静默；
                        # 离得远（>120px）→ 这个控件的文字坐标映射不可信
                        #   （Electron/Chromium 带缩放变换、PDF 阅读器常见），
                        #   报「这里没文字」，交给 OCR 按像素读光标下的真实文字。
                        gap = min(max(max(r.left - x, x - r.right),
                                      max(r.top - y, y - r.bottom)) for r in rects)
                        if gap > 120:
                            return None, False
                        return None, True
            except Exception:
                pass
            # 取回来的可能是「词 + 尾随空格」甚至标点，统一过取词闸门
            found = extract_word_at(got, 0)
            if found["word"]:
                return found["word"], True
            for cand in _tokenize(got):
                if is_english_word(cand):
                    return cand, True
            for ch in got:                 # 希腊字母 / 花体·双线体等变体字母：内置表有读音
                if is_letter_like(ch):
                    return ch, True
            return None, True              # 有文字但不是英文 → 静默
        try:
            node = node.GetParentControl()
        except Exception:
            return None, False
    return None, False


def _tokenize(s: str):
    out, cur = [], []
    for ch in s or "":
        if ch.isalpha() or ch in "'-\u2019":
            cur.append(ch)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


def _grab_png(x: int, y: int, w: int = 220, h: int = 84) -> bytes | None:
    """截取光标附近一小块（要小：块大了会把邻行的英文也收进来，误判成\"指到的词\"）。"""
    try:
        from PIL import ImageGrab
    except Exception:
        return None
    try:
        img = ImageGrab.grab(bbox=(x - w // 2, y - h // 2, x + w // 2, y + h // 2), all_screens=True)
    except Exception:
        return None
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


_OCR_CACHE: dict = {}          # (12px 网格坐标) -> (ts, word或None)；成功缓存数秒、失败缓存 30 秒
# 游戏守护标记（可选，环境变量 ET_GAMING_FLAG 指定）：文件存在时不发起 OCR，
# 避免把本地视觉模型重新拉回显存（打游戏时抢显存会卡）。
GAMING_FLAG = os.environ.get("ET_GAMING_FLAG")


def word_at_point_ocr(x: int, y: int, cfg: dict):
    """视觉模型 OCR 兜底（本地 Ollama 之类）。识别不到英文一律返回 None。"""
    cfg = cfg or {}
    # 配置是嵌套的（model.baseUrl / model.visionModel，与扩展 settings-core 同构）；
    # 早期这里读的是扁平键，永远取不到 → OCR 兜底被静默短路。扁平键仅作兼容回退。
    m = cfg.get("model") or {}
    base = (m.get("baseUrl") or cfg.get("baseUrl") or "").rstrip("/")
    model = m.get("visionModel") or cfg.get("visionModel") or ""
    if not base or not model:
        return None
    if (cfg.get("imageOcr") or {}).get("enabled") is False:
        return None                      # 设置里关掉了图片取词
    if GAMING_FLAG and os.path.exists(GAMING_FLAG):
        return None                      # 游戏中：静默，不加载视觉模型抢显存
    # 缓存：驻留期间同一位置不重复打模型；识别不到/服务不可用也不狂拍（负缓存 30s）
    key = (int(x) // 12, int(y) // 12)
    now = time.time()
    hit = _OCR_CACHE.get(key)
    if hit is not None:
        ts, w = hit
        if w and now - ts < 2.5:
            return w
        if not w and now - ts < 30:
            return None
    png = _grab_png(x, y)
    if not png:
        return None
    # 关键：ImageGrab 不带鼠标光标，模型在多个词的截图里根本不知道指哪个词
    #（实测「hello world」指 world 会返回 hello）。在截图中心画一个红叉当鼠标锚点。
    try:
        img = Image.open(io.BytesIO(png)).convert("RGB")
        d = ImageDraw.Draw(img)
        cx, cy = img.width // 2, img.height // 2
        d.line([(cx - 6, cy - 6), (cx + 6, cy + 6)], fill=(255, 0, 0), width=2)
        d.line([(cx - 6, cy + 6), (cx + 6, cy - 6)], fill=(255, 0, 0), width=2)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png = buf.getvalue()
    except Exception:
        pass
    prompt = ("图中红叉位于某个字符上。按下面规则只输出一个 JSON，不要解释：\n"
              "- 红叉压在英文字母上 → 输出它所在的**完整英文单词**：{\"word\":\"word\"}\n"
              "- 若那里是一个孤立的单个字母（数学变量，如 F X n，也可能写成花体 ℱ ℒ 𝒩）"
              "→ 输出这个字母本身：{\"word\":\"F\"}\n"
              "- 红叉压在希腊字母上 → 原样输出该字母（如 Ω α λ β）：{\"word\":\"Ω\"}\n"
              "- 红叉压在花体/双线体/哥特体字母上（如 ℒ ℝ 𝔼 𝒩 𝔤 𝓛 ℱ）→ 原样输出该字符：{\"word\":\"ℒ\"}\n"
              "- 红叉压在中文/数字/标点/空白上 → {\"word\":null}")
    body = {
        "model": model, "temperature": 0, "max_tokens": 60,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}},
        ]}],
    }
    try:
        req = urllib.request.Request(
            base + "/chat/completions", data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + (cfg.get("apiKey") or "none")})
        # 冷启动 1–3 分钟：超时给足余量，否则「第一次永远查不到」（用户会以为功能坏了）。
        # 启动时另有 warmup_vision() 把模型预热进内存，正常路径只要几百毫秒。
        with urllib.request.urlopen(req, timeout=float(cfg.get("visionTimeoutSec") or 90.0)) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        content = raw["choices"][0]["message"]["content"]
    except Exception:
        _OCR_CACHE[key] = (now, None)      # 服务不可用也负缓存，避免狂拍
        return None
    from .lookup import normalize_model, extract_json
    obj = extract_json(content) if isinstance(content, str) else None
    if isinstance(obj, dict) and isinstance(obj.get("word"), str):
        w = obj["word"].strip().strip("`").strip()
        if w.lower() in ("null", "none", "nan", "无", "没有", "—", "-"):
            w = ""                       # 模型有时把 JSON null 写成字符串 "null"
        w = w if (is_english_word(w) or is_letter_like(w)
                  or (len(w) == 1 and w.isascii() and w.isalpha())) else None
        # 末尾那项：图片/PDF 里的孤立单字母（数学变量 F、X、n…）——文字取词那边单字母
        # 仍按产品规则不触发，这里只放开 OCR 路径（需要在图上停住才会走到）。
        _OCR_CACHE[key] = (now, w)
        return w
    _OCR_CACHE[key] = (now, None)
    return None


def word_at_point(x: int, y: int, cfg: dict):
    """屏幕落点 → 英文单词；什么都取不到就返回 None（调用方必须静默）。

    优先级与产品铁律：
      ① UIA 取到英文 → 用它；
      ② UIA 说这里有文字但不是英文 → **就此静默**（中文上绝不弹窗）；
      ③ 这里根本没有文字（图片、自绘 UI）→ 才用视觉模型 OCR 兜底。
    """
    word, saw_text = word_at_point_uia(x, y)
    if word:
        return word, "uia"
    if saw_text:
        return None, ""
    word = word_at_point_ocr(x, y, (cfg or {}).get("model") or {})
    if word:
        return word, "ocr"
    return None, ""
