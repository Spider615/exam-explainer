#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
store.py —— 存储层：Postgres（元数据）+ 资产后端（本地目录 / MinIO）

    python pipeline/store.py init          建表
    python pipeline/store.py stat          看库里有什么

为什么要有这一层
----------------
在这之前是「拿文件系统当数据库」，踩到了两个真问题：

  · **两棵树静默漂移** —— work/ 和 work/_batch/ 是同一批卷子的两份副本。
    改完管线只重跑一棵，audit 全绿，但 Web 上读的还是旧数据，没有任何机制能发现。
  · **并发写竞争** —— 两个进程同时写一份 questions.json。json.dump 不是原子的。

所以：`work/<卷名>/` 降级成**构建产物目录**，库是**发布后的唯一真相源**，
API 只读库。哪棵工作目录新都无所谓 —— 没 publish 就不算数。

资产后端的抽象
--------------
`assets` 表记着每份文件在哪（storage=local|minio）。对外 URL 一律由 api.py 代理，
所以从本地目录切到 MinIO **不改前端任何一个 URL**，只换 `read_asset` 的实现。

管线脚本不经过这里
------------------
ingest / segment / mathvlm / verify 继续读写本地目录。它们是靠目录串起来的，
harness 那套无头 Chrome 门禁也要本地文件。让它们改说 SQL 只会把一条能跑的
管线搅乱，收益却只是少一步 publish。
"""
import hashlib, json, mimetypes, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "work")

# .env 是唯一的配置来源；凭证不进代码、不进前端
for _line in open(os.path.join(ROOT, ".env"), encoding="utf-8").read().splitlines() \
        if os.path.exists(os.path.join(ROOT, ".env")) else []:
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        k, v = _line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

DSN = os.environ.get("DATABASE_URL", "postgresql:///exam_explainer")
STORAGE = os.environ.get("EXAM_ASSET_STORAGE", "local")
BUCKET = os.environ.get("MINIO_BUCKET", "exam")

# 资产的种类 → 卷内目录。_hires/_cache 不在其中：纯中间产物，裁完就没用了，
# 33 MB/20卷 全是可以几秒重算的东西，不该占对象存储。
ASSET_DIRS = {"page": "page", "img": "img", "mathimg": "mathimg"}


# ---------------------------------------------------------------- 连接
def connect():
    import psycopg
    return psycopg.connect(DSN, autocommit=False)


_s3 = None


def s3():
    global _s3
    if _s3 is None:
        import boto3
        _s3 = boto3.client(
            "s3", endpoint_url=os.environ.get("MINIO_ENDPOINT", "http://127.0.0.1:9000"),
            aws_access_key_id=os.environ.get("MINIO_ACCESS_KEY", "minioadmin"),
            aws_secret_access_key=os.environ.get("MINIO_SECRET_KEY", "minioadmin"),
            region_name="us-east-1")
    return _s3


def ensure_bucket():
    import botocore
    try:
        s3().head_bucket(Bucket=BUCKET)
    except botocore.exceptions.ClientError:
        s3().create_bucket(Bucket=BUCKET)


def init_schema():
    sql = open(os.path.join(ROOT, "pipeline", "schema.sql"), encoding="utf-8").read()
    with connect() as c:
        c.execute(sql)
        c.commit()


# ---------------------------------------------------------------- 资产
def object_key(sha, rel_path):
    """
    桶内 key 按**内容哈希**分片，不按卷名。

    两卷共用同一张图（同一份 PDF 处理两遍就是这种情况）时天然去重，
    而且卷名里的中文和空格不会跑进 key 里。
    """
    ext = os.path.splitext(rel_path)[1].lower()[:12]
    return "papers/%s/%s%s" % (sha[:2], sha, ext)


def put_asset(local_path, rel_path):
    """把一份文件放进资产存储，返回入库要用的那一行（不含 paper_id）。"""
    data = open(local_path, "rb").read()
    sha = hashlib.sha256(data).hexdigest()
    ct = mimetypes.guess_type(rel_path)[0] or "application/octet-stream"
    key = None
    if STORAGE == "minio":
        key = object_key(sha, rel_path)
        # 内容寻址：key 一样就是同一份字节，不必重传
        try:
            s3().head_object(Bucket=BUCKET, Key=key)
        except Exception:
            s3().put_object(Bucket=BUCKET, Key=key, Body=data, ContentType=ct)
    return {"kind": rel_path.split("/")[0], "rel_path": rel_path, "sha256": sha,
            "bytes": len(data), "content_type": ct,
            "storage": STORAGE, "object_key": key}


def read_asset(row, paper_name):
    """取回一份资产的字节。前端不知道也不需要知道它在哪。"""
    if row["storage"] == "minio" and row["object_key"]:
        return s3().get_object(Bucket=BUCKET, Key=row["object_key"])["Body"].read()
    p = os.path.join(WORK, paper_name, row["rel_path"])
    if not os.path.exists(p):
        return None
    return open(p, "rb").read()


def drop_objects(keys):
    """
    删桶里的对象。**只删没有别人引用的**。

    key 按内容哈希，两卷共用同一张图时 key 相同；删了 A 卷就把 B 卷的图删没，
    是这种设计最容易踩的坑。所以调用方必须先在库里确认没有其他引用。
    """
    if STORAGE != "minio" or not keys:
        return 0
    n = 0
    for i in range(0, len(keys), 1000):
        batch = [{"Key": k} for k in keys[i:i + 1000] if k]
        if batch:
            s3().delete_objects(Bucket=BUCKET, Delete={"Objects": batch})
            n += len(batch)
    return n


# ---------------------------------------------------------------- 发布
def publish(workdir, name=None, conn=None):
    """
    把一卷的构建产物导进库。**整卷替换**，在一个事务里。

    重跑 segment.py 会重写整份 questions.json，所以这里也是整卷替换语义：
    删掉旧的 questions（级联清掉 options/tables），重新插。
    papers 那一行保留 —— 它的 id 被 assets 引用，而且 created_at 有意义。
    """
    name = name or os.path.basename(os.path.abspath(workdir))
    qp = os.path.join(workdir, "questions.json")
    data = json.load(open(qp, encoding="utf-8"))

    own = conn is None
    c = conn or connect()
    try:
        cur = c.cursor()
        cur.execute("""
            INSERT INTO papers (name, source_pdf, n_questions, sections, warnings,
                                dropped_boilerplate, updated_at, run_started_at)
            VALUES (%s,%s,%s,%s,%s,%s, now(), now())
            ON CONFLICT (name) DO UPDATE SET
              source_pdf=EXCLUDED.source_pdf, n_questions=EXCLUDED.n_questions,
              sections=EXCLUDED.sections, warnings=EXCLUDED.warnings,
              dropped_boilerplate=EXCLUDED.dropped_boilerplate, updated_at=now(),
              -- 每次发布就是一轮新的处理，起点在这里重置
              run_started_at=now()
            RETURNING id""",
            (name, data.get("source"), len(data["questions"]),
             json.dumps(data.get("sections", []), ensure_ascii=False),
             json.dumps(data.get("warnings", []), ensure_ascii=False),
             json.dumps(data.get("dropped_boilerplate", []), ensure_ascii=False)))
        pid = cur.fetchone()[0]

        # **不能整卷 DELETE 再重插。** questions 的主键被 solutions / specs 以
        # ON DELETE CASCADE 引用着，删一次就把阶段③④ 的全部产出连根拔掉，
        # 而且重插后 id 变了，想接也接不回去 —— 实测重新发布一卷就丢了两题的解法。
        # 改成按 (paper_id, n) upsert：id 稳定，下游产出跟着题走。
        cur.execute("DELETE FROM questions WHERE paper_id=%s AND n <> ALL(%s)",
                    (pid, [q["n"] for q in data["questions"]]))
        for q in data["questions"]:
            layout = {k: q.get(k) for k in
                      ("y_bounds", "y_range", "fig_marks", "figures", "option_figures")}
            cur.execute("""
                INSERT INTO questions (paper_id, n, type, points, section, stem,
                    stem_latex, stem_low_conf, stem_image, option_image,
                    text_quality, quality_reason, n_chars, pages,
                    stem_math, flattened, layout)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (paper_id, n) DO UPDATE SET
                  type=EXCLUDED.type, points=EXCLUDED.points, section=EXCLUDED.section,
                  stem=EXCLUDED.stem, stem_latex=EXCLUDED.stem_latex,
                  stem_low_conf=EXCLUDED.stem_low_conf, stem_image=EXCLUDED.stem_image,
                  option_image=EXCLUDED.option_image, text_quality=EXCLUDED.text_quality,
                  quality_reason=EXCLUDED.quality_reason, n_chars=EXCLUDED.n_chars,
                  pages=EXCLUDED.pages, stem_math=EXCLUDED.stem_math,
                  flattened=EXCLUDED.flattened, layout=EXCLUDED.layout
                RETURNING id""",
                (pid, q["n"], q.get("type"), q.get("points"), q.get("section"),
                 q.get("stem", ""), q.get("stem_latex"), q.get("stem_low_conf"),
                 q.get("stem_image"), q.get("option_image"),
                 q.get("text_quality"), q.get("quality_reason"), q.get("n_chars"),
                 q.get("pages"),
                 json.dumps(q.get("stem_math", []), ensure_ascii=False),
                 json.dumps(q.get("flattened", []), ensure_ascii=False),
                 json.dumps(layout, ensure_ascii=False)))
            qid = cur.fetchone()[0]

            # 选项和表格没有下游依赖，整题替换最省事
            cur.execute("DELETE FROM q_options WHERE question_id=%s", (qid,))
            cur.execute("DELETE FROM q_tables WHERE question_id=%s", (qid,))
            for i, o in enumerate(q.get("options", [])):
                cur.execute("""INSERT INTO q_options
                    (question_id, ord, okey, otext, latex, math, figure)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (qid, i, o["key"], o.get("text", ""), o.get("latex"),
                     json.dumps(o.get("math", []), ensure_ascii=False), o.get("figure")))

            for t in q.get("tables", []):
                cur.execute("""INSERT INTO q_tables
                    (question_id, tid, page, caption, cells, box, cont_of, image)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (qid, t["id"], t.get("page"), t.get("caption", ""),
                     json.dumps(t.get("rows", []), ensure_ascii=False),
                     json.dumps(t.get("box"), ensure_ascii=False),
                     t.get("cont_of"), t.get("image")))

        # ---- 资产 ----
        n_asset = 0
        for kind, sub in ASSET_DIRS.items():
            d = os.path.join(workdir, sub)
            if not os.path.isdir(d):
                continue
            for fn in sorted(os.listdir(d)):
                fp = os.path.join(d, fn)
                if not os.path.isfile(fp):
                    continue
                row = put_asset(fp, "%s/%s" % (sub, fn))
                cur.execute("""
                    INSERT INTO assets (paper_id, kind, rel_path, sha256, bytes,
                                        content_type, storage, object_key)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (paper_id, rel_path) DO UPDATE SET
                      sha256=EXCLUDED.sha256, bytes=EXCLUDED.bytes,
                      content_type=EXCLUDED.content_type,
                      storage=EXCLUDED.storage, object_key=EXCLUDED.object_key""",
                    (pid, kind, row["rel_path"], row["sha256"], row["bytes"],
                     row["content_type"], row["storage"], row["object_key"]))
                n_asset += 1

        if own:
            c.commit()
        return {"paper_id": pid, "questions": len(data["questions"]), "assets": n_asset}
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


# ---------------------------------------------------------------- 删除
def delete_papers(names):
    """
    删卷。库里一个事务删干净，然后清掉没人再引用的对象。

    **vlm_cache 一律不动** —— 它按图片内容哈希存，跟卷子无关。
    删卷级联到它，等于每删一卷就把下次重跑的成本从 20 次模型调用推回 300 次。
    """
    if not names:
        return {"deleted": [], "missing": [], "objects": 0}
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT name FROM papers WHERE name = ANY(%s)", (list(names),))
        found = [r[0] for r in cur.fetchall()]
        missing = [n for n in names if n not in found]
        if not found:
            return {"deleted": [], "missing": missing, "objects": 0}

        # 待删卷引用到的对象里，**只有其他卷不再引用的**才能真删
        cur.execute("""
            SELECT DISTINCT a.object_key FROM assets a
             WHERE a.paper_id IN (SELECT id FROM papers WHERE name = ANY(%s))
               AND a.object_key IS NOT NULL
               AND NOT EXISTS (
                     SELECT 1 FROM assets b
                      WHERE b.object_key = a.object_key
                        AND b.paper_id NOT IN
                            (SELECT id FROM papers WHERE name = ANY(%s)))""",
            (found, found))
        keys = [r[0] for r in cur.fetchall()]

        cur.execute("DELETE FROM papers WHERE name = ANY(%s)", (found,))
        c.commit()

    # 对象在库提交之后再删：先删对象后回滚，会留下指向不存在对象的记录
    n = drop_objects(keys)
    return {"deleted": found, "missing": missing, "objects": n}


# ---------------------------------------------------------------- 读取
def list_papers():
    with connect() as c:
        cur = c.cursor()
        cur.execute("""
            SELECT p.name, p.n_questions, jsonb_array_length(p.warnings),
                   p.updated_at,
                   (SELECT count(*) FROM assets a
                     WHERE a.paper_id=p.id AND a.kind IN ('img','mathimg'))
              FROM papers p ORDER BY p.updated_at DESC""")
        return [{"name": r[0], "n": r[1], "warnings": r[2],
                 "mtime": r[3].timestamp(), "figures": r[4]} for r in cur.fetchall()]


def get_paper(name):
    """整卷读回，形状与旧的 questions.json 一致，好让上层不必改。"""
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT id, source_pdf, sections, warnings FROM papers WHERE name=%s",
                    (name,))
        row = cur.fetchone()
        if not row:
            return None
        pid, src, sections, warnings = row
        cur.execute("""SELECT id, n, type, points, section, stem, stem_latex,
                              stem_low_conf, stem_image, option_image, text_quality,
                              quality_reason, n_chars, pages, label,
                              anim_worth, anim_why,
                              stem_math, flattened, layout
                         FROM questions WHERE paper_id=%s ORDER BY n""", (pid,))
        cols = [d[0] for d in cur.description]
        qs = [dict(zip(cols, r)) for r in cur.fetchall()]
        by_id = {q["id"]: q for q in qs}
        for q in qs:
            q.update(q.pop("layout") or {})
            q["options"], q["tables"] = [], []
        if qs:
            ids = list(by_id)
            cur.execute("""SELECT question_id, okey, otext, latex, math, figure
                             FROM q_options WHERE question_id = ANY(%s) ORDER BY ord""",
                        (ids,))
            for qid, k, t, tex, math, fig in cur.fetchall():
                by_id[qid]["options"].append({"key": k, "text": t, "latex": tex,
                                              "math": math, "figure": fig})
            cur.execute("""SELECT question_id, tid, page, caption, cells, box, cont_of, image
                             FROM q_tables WHERE question_id = ANY(%s) ORDER BY tid""",
                        (ids,))
            for qid, tid, pg, cap, cells, box, cont, img in cur.fetchall():
                by_id[qid]["tables"].append({"id": tid, "page": pg, "caption": cap,
                                             "rows": cells, "box": box,
                                             "cont_of": cont, "image": img})
        return {"name": name, "source": src, "sections": sections,
                "warnings": warnings, "questions": qs}


def paper_scenes(name):
    """{题号: 场景 id}。只给**门禁判定通过**的 —— passed 由 verify.py 末行决定。"""
    with connect() as c:
        cur = c.cursor()
        cur.execute("""SELECT q.n, sc.scene_id FROM scenes sc
                         JOIN questions q ON q.id = sc.question_id
                         JOIN papers p ON p.id = q.paper_id
                        WHERE p.name = %s AND sc.passed""", (name,))
        return {r[0]: r[1] for r in cur.fetchall()}


def put_outline(qid, label, short):
    """
    阶段③b 的产出：题目的短标题、解法的短答案。

    分写两张表 —— label 描述题目本身（没解出来也该有），short_answer 是解法的
    压缩形式。写在一个函数里只是因为它们同一次调用出来的，别把它当成一张表。
    没解过的题 solutions 里没有行，UPDATE 影响 0 行，不报错也不插空行。
    """
    with connect() as c:
        if label:
            c.execute("UPDATE questions SET label=%s WHERE id=%s", (label, qid))
        if short:
            c.execute("UPDATE solutions SET short_answer=%s WHERE question_id=%s",
                      (short, qid))
        c.commit()


def outline_missing(name):
    """还差多少题没有短标题/短答案。③b 靠它决定要不要跑，以及跑完对不对得上。"""
    with connect() as c:
        cur = c.cursor()
        cur.execute("""SELECT count(*) FROM questions q
                         JOIN papers p ON p.id = q.paper_id
                         LEFT JOIN solutions s ON s.question_id = q.id
                        WHERE p.name = %s
                          AND (q.label IS NULL OR
                               (s.question_id IS NOT NULL AND s.short_answer IS NULL))""",
                    (name,))
        return cur.fetchone()[0]


def progress(name):
    """
    一份卷子的进度，**全部从库里算**。

    以前进度只存在 api.py 进程内的 `JOBS` 字典里，于是两种情况都看不见：
    命令行跑的（根本不进 JOBS）、服务重启过的（内存清空）。用户的原话是
    「为啥我在页面上根本都没有看到任何在跑的等待效果」—— 当时后台确实在跑。

    库里本来就有全部事实：每解完一题写一行 solutions，每写完一份 spec 写一行
    specs，每过一个门禁写一行 scenes，而且都带 created_at。所以「跑到哪了」
    是可以算出来的，不需要谁来上报。

    `busy` 用「最近有没有新东西落库」判定，而不是去查进程 —— 进程可能在别的
    机器上、可能是命令行起的，但只要它在干活，库里就会有新行。
    """
    with connect() as c:
        cur = c.cursor()
        cur.execute("""
            SELECT p.id, p.n_questions, p.assembled_at, p.run_started_at,
                   (SELECT count(*) FROM questions q WHERE q.paper_id=p.id),
                   (SELECT count(*) FROM questions q WHERE q.paper_id=p.id AND q.label IS NOT NULL),
                   (SELECT count(*) FROM solutions s JOIN questions q ON q.id=s.question_id
                     WHERE q.paper_id=p.id),
                   (SELECT count(*) FROM specs sp JOIN questions q ON q.id=sp.question_id
                     WHERE q.paper_id=p.id),
                   (SELECT count(*) FROM specs sp JOIN questions q ON q.id=sp.question_id
                     WHERE q.paper_id=p.id AND sp.status='approved'),
                   (SELECT count(*) FROM questions q
                     WHERE q.paper_id=p.id AND q.anim_worth IS NOT NULL),
                   (SELECT count(*) FROM questions q
                     WHERE q.paper_id=p.id AND q.anim_worth),
                   (SELECT count(*) FROM scenes sc JOIN questions q ON q.id=sc.question_id
                     WHERE q.paper_id=p.id AND sc.passed),
                   GREATEST(p.updated_at,
                     COALESCE((SELECT max(s.created_at) FROM solutions s
                                 JOIN questions q ON q.id=s.question_id
                                WHERE q.paper_id=p.id), p.updated_at),
                     COALESCE((SELECT max(sp.created_at) FROM specs sp
                                 JOIN questions q ON q.id=sp.question_id
                                WHERE q.paper_id=p.id), p.updated_at),
                     COALESCE((SELECT max(sc.created_at) FROM scenes sc
                                 JOIN questions q ON q.id=sc.question_id
                                WHERE q.paper_id=p.id), p.updated_at)),
                   now()
              FROM papers p WHERE p.name=%s""", (name,))
        r = cur.fetchone()
    if not r:
        return None
    (_pid, _nq, asm_at, started, n_q, n_label, n_sol, n_spec, n_appr, n_judged,
     n_worth, n_scene, last, now) = r
    idle = (now - last).total_seconds()
    # 总时长：跑完了就是 起点→装配完成，还在跑就是 起点→现在
    elapsed = ((asm_at or now) - started).total_seconds() if started else None
    return {"questions": n_q, "labels": n_label, "solutions": n_sol,
            "startedAt": started.timestamp() if started else None,
            "elapsedSeconds": elapsed,
            "specs": n_spec, "approved": n_appr, "judged": n_judged,
            "worth": n_worth, "scenes": n_scene,
            "assembled": bool(asm_at),
            "lastChange": last.timestamp(), "idleSeconds": idle,
            # 三分钟没有新东西落库就当它停了。⑤ 一道题要跑几分钟，阈值不能太小；
            # 但也不能太大，否则跑完了还一直显示「进行中」
            "busy": idle < 180}


def mark_assembled(name, path):
    """阶段⑦ 跑完在这里留痕。页面上的「⑦ 呈现」读它，不再硬编码 true。"""
    with connect() as c:
        cur = c.cursor()
        cur.execute("UPDATE papers SET assembled_at=now(), assembled_path=%s WHERE name=%s",
                    (path, name))
        n = cur.rowcount
        c.commit()
    return n > 0


def assembled(name):
    """
    ⑦ 的真实状态：装没装过、产物在哪、**是不是比库里的数据旧**。

    只报「装过」不够。out.html 是一次性的离线快照，而 ③④⑤ 都会往库里追加东西 ——
    解完题不重装，页面上「⑦ 呈现」亮着绿灯，手里那份 HTML 却还是一道解法都没有的版本。
    这正是 work/ 与库漂移那次事故的同一个形状，所以这里把「旧了」和「没装过」
    一样对待：fresh=False。

    fresh 的基准取本卷最后一次数据变动 —— publish（updated_at）、解题、写 spec、
    出场景，四者取最晚。
    """
    with connect() as c:
        cur = c.cursor()
        cur.execute("""
            SELECT p.assembled_at, p.assembled_path, GREATEST(
                     p.updated_at,
                     COALESCE((SELECT max(s.created_at) FROM solutions s
                                 JOIN questions q ON q.id = s.question_id
                                WHERE q.paper_id = p.id), p.updated_at),
                     COALESCE((SELECT max(sp.created_at) FROM specs sp
                                 JOIN questions q ON q.id = sp.question_id
                                WHERE q.paper_id = p.id), p.updated_at),
                     COALESCE((SELECT max(sc.created_at) FROM scenes sc
                                 JOIN questions q ON q.id = sc.question_id
                                WHERE q.paper_id = p.id), p.updated_at))
              FROM papers p WHERE p.name = %s""", (name,))
        r = cur.fetchone()
        if not r:
            return {"at": None, "path": None, "data_at": None, "fresh": False}
        at, path, data_at = r
        return {"at": at.timestamp() if at else None, "path": path,
                "data_at": data_at.timestamp() if data_at else None,
                "fresh": bool(at) and at >= data_at}


def paper_stems(name):
    """{题号: 题干}。场景绑定要拿它核对——题号不是全局唯一键，绑错过卷。"""
    with connect() as c:
        cur = c.cursor()
        cur.execute("""SELECT q.n, q.stem FROM questions q JOIN papers p ON p.id=q.paper_id
                        WHERE p.name=%s""", (name,))
        return {r[0]: r[1] for r in cur.fetchall()}


def find_page(name, n):
    """
    第 n 页的整页渲染图。

    文件名不能猜：pdftoppm 按**总页数**决定补零位数 —— 9 页的卷子是 `p-1.png`，
    10 页以上才是 `p-01.png`。端点里写死 `p-%02d.png` 的后果是所有 9 页以内的
    卷子整页图全部 404，而这条路径正是「对照原卷」的依据。所以按记录查，不按格式拼。
    """
    with connect() as c:
        cur = c.cursor()
        cur.execute("""SELECT a.rel_path, a.content_type, a.storage, a.object_key
                         FROM assets a JOIN papers p ON p.id=a.paper_id
                        WHERE p.name=%s AND a.kind='page'
                          AND a.rel_path ~ ('^page/p-0*' || %s || '\\.[a-z]+$')""",
                    (name, str(int(n))))
        r = cur.fetchone()
        return None if not r else {"rel_path": r[0], "content_type": r[1],
                                   "storage": r[2], "object_key": r[3]}


def find_asset(name, rel_path):
    with connect() as c:
        cur = c.cursor()
        cur.execute("""SELECT a.rel_path, a.content_type, a.storage, a.object_key
                         FROM assets a JOIN papers p ON p.id=a.paper_id
                        WHERE p.name=%s AND a.rel_path=%s""", (name, rel_path))
        r = cur.fetchone()
        return None if not r else {"rel_path": r[0], "content_type": r[1],
                                   "storage": r[2], "object_key": r[3]}


# ---------------------------------------------------------------- 视觉模型缓存
# ---------------------------------------------------------------- 解题与 spec
def solution_fresh(qid, sha):
    """这道题的解还对得上现在的题面吗。对得上就不必重解。"""
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT 1 FROM solutions WHERE question_id=%s AND src_sha256=%s",
                    (qid, sha))
        return cur.fetchone() is not None


def put_solution(qid, d, sha, model):
    with connect() as c:
        c.execute("""
            INSERT INTO solutions (question_id, answer, steps, key_facts, assumptions,
                                   confidence, src_sha256, model)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (question_id) DO UPDATE SET
              answer=EXCLUDED.answer, steps=EXCLUDED.steps,
              key_facts=EXCLUDED.key_facts, assumptions=EXCLUDED.assumptions,
              confidence=EXCLUDED.confidence, src_sha256=EXCLUDED.src_sha256,
              model=EXCLUDED.model, created_at=now()""",
            (qid, d["answer"],
             json.dumps(d["steps"], ensure_ascii=False),
             json.dumps(d["key_facts"], ensure_ascii=False),
             json.dumps(d["assumptions"], ensure_ascii=False),
             d["confidence"], sha, model))
        c.commit()


def get_solution(qid):
    with connect() as c:
        cur = c.cursor()
        cur.execute("""SELECT answer, steps, key_facts, assumptions, confidence, src_sha256
                         FROM solutions WHERE question_id=%s""", (qid,))
        r = cur.fetchone()
        if not r:
            return None
        return dict(zip(("answer", "steps", "key_facts", "assumptions",
                         "confidence", "src_sha256"), r))


def paper_solutions(name):
    """
    整卷的解题结果，{题号: {...}}。一次查完 —— 逐题查会变成 N+1。

    连 spec 的状态一起带出来：页面上要能看出「这题有没有断言、过没过人审」，
    否则读者无从判断眼前这段讲解是被检验过的还是刚生成的。
    """
    with connect() as c:
        cur = c.cursor()
        cur.execute("""
            SELECT q.n, s.answer, s.steps, s.assumptions, s.confidence, s.model,
                   sp.animatable, sp.n_invariants, sp.status, sp.why_not,
                   sc.passed, sc.rounds, s.short_answer, q.anim_worth, q.anim_why
              FROM questions q
              JOIN papers p ON p.id = q.paper_id
              JOIN solutions s ON s.question_id = q.id
              LEFT JOIN specs sp ON sp.question_id = q.id
              LEFT JOIN scenes sc ON sc.question_id = q.id
             WHERE p.name = %s""", (name,))
        return {r[0]: {"answer": r[1], "steps": r[2], "assumptions": r[3],
                       "confidence": r[4], "model": r[5],
                       "animatable": r[6], "n_invariants": r[7] or 0,
                       "spec_status": r[8], "why_not": r[9],
                       "scene_passed": r[10], "scene_rounds": r[11],
                       "short_answer": r[12], "worth": r[13], "worth_why": r[14]}
                for r in cur.fetchall()}


def spec_fresh(qid, sha):
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT 1 FROM specs WHERE question_id=%s AND src_sha256=%s", (qid, sha))
        return cur.fetchone() is not None


def put_spec(qid, spec, animatable, why_not, sha, model):
    with connect() as c:
        c.execute("""
            INSERT INTO specs (question_id, spec, animatable, why_not, n_invariants,
                               status, src_sha256, model)
            VALUES (%s,%s,%s,%s,%s,'draft',%s,%s)
            ON CONFLICT (question_id) DO UPDATE SET
              spec=EXCLUDED.spec, animatable=EXCLUDED.animatable,
              why_not=EXCLUDED.why_not, n_invariants=EXCLUDED.n_invariants,
              status='draft',            -- spec 变了就得重新过人审
              src_sha256=EXCLUDED.src_sha256, model=EXCLUDED.model, created_at=now()""",
            (qid, json.dumps(spec, ensure_ascii=False), animatable, why_not,
             len(spec.get("invariants") or []), sha, model))
        c.commit()


def get_spec(qid):
    with connect() as c:
        cur = c.cursor()
        cur.execute("""SELECT sp.spec, sp.animatable, sp.why_not, sp.n_invariants,
                              sp.status, q.anim_worth, q.anim_why
                         FROM specs sp JOIN questions q ON q.id=sp.question_id
                        WHERE sp.question_id=%s""", (qid,))
        r = cur.fetchone()
        if not r:
            return None
        return dict(zip(("spec", "animatable", "why_not", "n_invariants", "status",
                         "worth", "worth_why"), r))


def put_worth(qid, worth, why):
    """
    阶段④c 的裁决：这道题值不值得花几十分钟做成动画。

    写在 questions 上而不是 specs 上 —— ④c 现在跑在 ④ 之前，那时候
    specs 这一行还不存在。
    """
    with connect() as c:
        c.execute("UPDATE questions SET anim_worth=%s, anim_why=%s WHERE id=%s",
                  (worth, why, qid))
        c.commit()


def picked(name):
    """④c 选中要做动画的题号集合。spec.py --picked 用它决定给谁写断言。"""
    with connect() as c:
        cur = c.cursor()
        cur.execute("""SELECT q.n FROM questions q JOIN papers p ON p.id=q.paper_id
                        WHERE p.name=%s AND q.anim_worth""", (name,))
        return {r[0] for r in cur.fetchall()}


def put_scene(qid, sid, rounds, passed):
    with connect() as c:
        c.execute("""INSERT INTO scenes (question_id, scene_id, rounds, passed)
                     VALUES (%s,%s,%s,%s)
                     ON CONFLICT (question_id) DO UPDATE SET
                       scene_id=EXCLUDED.scene_id, rounds=EXCLUDED.rounds,
                       passed=EXCLUDED.passed, created_at=now()""",
                  (qid, sid, rounds, passed))
        c.commit()


def approve_spec(qid, ok=True):
    """人审通过与否。阶段⑤ 默认只接受 approved 的 spec。"""
    with connect() as c:
        c.execute("UPDATE specs SET status=%s WHERE question_id=%s",
                  ("approved" if ok else "rejected", qid))
        c.commit()


def cache_get(sha):
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT payload FROM vlm_cache WHERE img_sha256=%s", (sha,))
        r = cur.fetchone()
        return r[0] if r else None


def cache_put(sha, kind, payload):
    with connect() as c:
        c.execute("""INSERT INTO vlm_cache (img_sha256, kind, payload) VALUES (%s,%s,%s)
                     ON CONFLICT (img_sha256) DO NOTHING""",
                  (sha, kind, json.dumps(payload, ensure_ascii=False)))
        c.commit()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stat"
    if cmd == "init":
        init_schema()
        if STORAGE == "minio":
            ensure_bucket()
        print("建表完成；资产后端 = %s" % STORAGE)
    elif cmd == "stat":
        with connect() as c:
            cur = c.cursor()
            for t in ("papers", "questions", "q_options", "q_tables",
                      "assets", "vlm_cache"):
                cur.execute("SELECT count(*) FROM " + t)
                print("  %-10s %d" % (t, cur.fetchone()[0]))
            cur.execute("SELECT storage, count(*), pg_size_pretty(sum(bytes)) "
                        "FROM assets GROUP BY storage")
            for s, n, sz in cur.fetchall():
                print("  资产 %s：%d 份，%s" % (s, n, sz))
    else:
        print("用法：store.py [init|stat]")


if __name__ == "__main__":
    main()
