# -*- coding: utf-8 -*-
from PIL import Image
import pages


def test_自然排序不按字典序():
    names = ["IMG_10.jpg", "IMG_2.jpg", "IMG_1.jpg"]
    assert sorted(names, key=pages.sort_key) == ["IMG_1.jpg", "IMG_2.jpg", "IMG_10.jpg"]


def test_同名不同扩展名也稳定():
    names = ["a2.png", "a10.png", "a1.png"]
    assert sorted(names, key=pages.sort_key) == ["a1.png", "a2.png", "a10.png"]


def test_没有数字的按名字排():
    assert sorted(["b.jpg", "a.jpg"], key=pages.sort_key) == ["a.jpg", "b.jpg"]


def test_排序只看文件名不看目录():
    """老师从相册里选的图，路径前缀可能各不相同"""
    names = ["/x/9/IMG_2.jpg", "/y/1/IMG_10.jpg"]
    assert sorted(names, key=pages.sort_key)[0].endswith("IMG_2.jpg")


def _make(tmp_path, name, size=(1200, 1600), orientation=None, color=(240, 240, 240)):
    p = tmp_path / name
    im = Image.new("RGB", size, color)
    if orientation:
        ex = im.getexif()
        ex[274] = orientation          # 274 = Orientation
        im.save(p, exif=ex)
    else:
        im.save(p)
    return str(p)


def test_横过来的照片被转正(tmp_path):
    # orientation=6：顺时针转 90 度才是正的。不转正的话模型认不出题号
    src = _make(tmp_path, "x.jpg", size=(1600, 1200), orientation=6)
    got = pages.normalize([src], str(tmp_path / "out"))
    with Image.open(got[0]["hires"]) as im:
        assert im.height > im.width, "EXIF 转正没生效"


def test_没有exif的原样不动(tmp_path):
    src = _make(tmp_path, "x.jpg", size=(1600, 1200))
    got = pages.normalize([src], str(tmp_path / "out"))
    with Image.open(got[0]["hires"]) as im:
        assert (im.width, im.height) == (1600, 1200)


def test_页序按文件名而不是传入顺序(tmp_path):
    a = _make(tmp_path, "IMG_10.jpg", color=(10, 10, 10))
    b = _make(tmp_path, "IMG_2.jpg", color=(20, 20, 20))
    got = pages.normalize([a, b], str(tmp_path / "out"))
    assert [g["page"] for g in got] == [1, 2]
    assert "IMG_2" in got[0]["src"] and "IMG_10" in got[1]["src"]


def test_出两档分辨率(tmp_path):
    src = _make(tmp_path, "a.jpg", size=(2400, 3200))
    got = pages.normalize([src], str(tmp_path / "out"))[0]
    with Image.open(got["hires"]) as hi, Image.open(got["web"]) as lo:
        assert lo.width < hi.width, "web 档更小：整页读用它，裁块复读用 hires"
        assert abs(lo.width / hi.width - pages.WEB_SCALE) < 0.01


def test_内容一样哈希就一样(tmp_path):
    a = _make(tmp_path, "a.jpg")
    b = _make(tmp_path, "b.jpg")          # 内容相同、名字不同
    g = pages.normalize([a, b], str(tmp_path / "out"))
    assert g[0]["sha256"] == g[1]["sha256"], "按内容哈希，重传同一张不该重复烧钱"


def test_内容不同哈希就不同(tmp_path):
    a = _make(tmp_path, "a.jpg", color=(1, 2, 3))
    b = _make(tmp_path, "b.jpg", color=(9, 9, 9))
    g = pages.normalize([a, b], str(tmp_path / "out"))
    assert g[0]["sha256"] != g[1]["sha256"]


def test_一张都没有就明说(tmp_path):
    try:
        pages.normalize([], str(tmp_path / "out"))
    except ValueError as e:
        assert "一个文件" in str(e)
    else:
        raise AssertionError("空输入应该当场抛，不该回一个空列表让下游去猜")


def test_同一目录跑两次页数不会涨(tmp_path):
    """PDF 展开的中间产物如果留着，第二次跑会把它们当成新的一页收进来。
    页数凭空变多，而且看不出是为什么"""
    a = _make(tmp_path, "IMG_1.jpg")
    out = str(tmp_path / "out")
    n1 = len(pages.normalize([a], out))
    n2 = len(pages.normalize([a], out))
    assert n1 == n2 == 1
    import os
    assert not [f for f in os.listdir(out) if f.startswith("_pdf")], "中间产物没收干净"
