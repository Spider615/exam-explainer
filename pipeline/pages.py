#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pages.py —— 一批文件（图片或 PDF）→ 规范化页面图

    python pipeline/pages.py -o <输出目录> <图1> [图2 ...|某.pdf]

三条链共用：试卷图、答案图、答题卡图，前半段完全一样 —— EXIF 转正、
按文件名自然排序、两档分辨率、按内容哈希。写三遍必然写歪。

两档分辨率
----------
`hires` 供裁块复读（这时才需要看清笔画），`web` 是它的一半，供整页读
（认出短答案和位置足够，token 省一半）。`mathvlm.py` 就是这个配比。

页序不靠拖拽靠对账
------------------
`IMG_001…` 通常就是拍摄顺序，先按文件名自然排。**排错了不会静默** ——
答题卡上认出的题号会乱序，Ⓑ 那一步报得出来。拖拽只是让老师**能**改，
对账才让老师**知道要**改；后者更值钱，先做后者。

为什么不在这里判「这张图是什么」
------------------------------
它只负责把一批文件变成规范的页面图，不认题、不认答案。谁来读、读成什么，
是 `imgdoc.py`（试卷）和 `sheet.py`（答题卡）各自的事。
"""
import argparse, hashlib, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ingest        # pdftoppm 的探测路径只写一份

HIRES_DPI = 300
WEB_SCALE = 0.5      # web 档是 hires 的一半

_NUM = re.compile(r"(\d+)")
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")


def sort_key(name):
    """
    自然排序：`IMG_2` 排在 `IMG_10` 前面。

    按字典序排的话 `IMG_10` 会跑到 `IMG_2` 前面、页序错乱，而拍照的人
    绝对想不到是这个原因。只看文件名不看目录 —— 老师从相册里选的图，
    路径前缀可能各不相同。
    """
    base = os.path.basename(str(name))
    return tuple((int(t), "") if t.isdigit() else (0, t.lower())
                 for t in _NUM.split(base) if t != "")


def exif_rotate(im):
    """按 EXIF Orientation 转正。横过来的照片模型认不出题号。"""
    from PIL import ImageOps
    return ImageOps.exif_transpose(im) or im


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _pdf_pages(pdf, outdir):
    """
    PDF → 逐页 PNG（hires）。找不到 pdftoppm 就明说，不静默少几页。

    先清掉上一次的中间产物：同一个目录跑第二次的话，残留的 `_pdf-*.png`
    会被当成这一次的页一起收进来 —— 页数凭空变多，而且看不出是为什么。
    """
    exe = ingest.pdftoppm_exe()
    if not exe:
        raise RuntimeError("找不到 pdftoppm（brew install poppler），PDF 展不开")
    for f in os.listdir(outdir):
        if f.startswith("_pdf") and f.endswith(".png"):
            os.remove(os.path.join(outdir, f))
    stem = os.path.join(outdir, "_pdf")
    subprocess.run([exe, "-r", str(HIRES_DPI), "-png", pdf, stem],
                   capture_output=True, check=True)
    got = sorted((os.path.join(outdir, f) for f in os.listdir(outdir)
                  if f.startswith("_pdf") and f.endswith(".png")), key=sort_key)
    if not got:
        raise RuntimeError("pdftoppm 一页都没渲出来：%s" % pdf)
    return got


def normalize(paths, outdir, prefix="p"):
    """
    一批文件 → `[{"page", "src", "hires", "web", "sha256"}]`，按页序。

    `paths` 里可以混着图片和 PDF：PDF 展开成多页，图片一张一页。
    `src` 记的是这一页来自哪个原始文件 —— 出问题时要答得出「是哪张拍歪了」。
    """
    from PIL import Image
    if not paths:
        raise ValueError("一个文件都没有，没什么可规范化的")
    os.makedirs(outdir, exist_ok=True)

    expanded = []
    for p in sorted(paths, key=sort_key):
        if str(p).lower().endswith(".pdf"):
            expanded += [(q, p) for q in _pdf_pages(p, outdir)]
        elif str(p).lower().endswith(IMG_EXT):
            expanded.append((p, p))
        else:
            raise ValueError("不认识的文件类型：%s（只收图片和 PDF）" % os.path.basename(p))

    out = []
    for i, (src, origin) in enumerate(expanded, 1):
        hi = os.path.join(outdir, "%s%02d.png" % (prefix, i))
        web = os.path.join(outdir, "%s%02d_web.png" % (prefix, i))
        with Image.open(src) as im0:
            im = exif_rotate(im0).convert("RGB")
            im.save(hi)
            im.resize((max(1, int(im.width * WEB_SCALE)),
                       max(1, int(im.height * WEB_SCALE))), Image.LANCZOS).save(web)
        out.append({"page": i, "src": origin, "hires": hi, "web": web,
                    "sha256": sha256_of(hi)})

    # 中间产物收掉。它们是 p01.png 的副本，留着白占一份磁盘，
    # 更要紧的是下一次跑会把它们当成新的一页收进来
    for f in os.listdir(outdir):
        if f.startswith("_pdf") and f.endswith(".png"):
            os.remove(os.path.join(outdir, f))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--prefix", default="p")
    a = ap.parse_args()
    for r in normalize(a.files, a.out, a.prefix):
        print("第%2d页  %s  ← %s" % (r["page"], os.path.basename(r["hires"]),
                                    os.path.basename(r["src"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
