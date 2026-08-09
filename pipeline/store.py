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
from contextlib import contextmanager

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
def readonly_from(env):
    return (env.get("EXAM_READONLY") or "").strip().lower() not in ("", "0", "false", "no")


# `EXAM_READONLY=1`：这一次运行不许改库。
#
# 反复踩的坑是「**本意只是看看，结果动了真东西**」：想看看 ⑤ 的清单，它把一道题
# 真跑了；想冒烟试试 ④c 通不通，它把整卷的选题判定重写了。两次都不是不知道会
# 写库，是顺手拿生产命令当查看工具。
#
# 「下次注意」不是修复，所以做成结构上做不到：开着它时会话是
# `TRANSACTION READ ONLY`，**由 Postgres 拒绝**任何写 —— 不依赖哪个脚本记得
# 支持 `--dry-run`，也不依赖人记得加。查东西时一律：
#
#     EXAM_READONLY=1 .venv/bin/python pipeline/<某一步>.py <卷名>
#
# 严格 opt-in：不设这个变量时行为一个字都不变。
READONLY = readonly_from(os.environ)


def connect():
    import psycopg
    c = psycopg.connect(DSN, autocommit=False)
    if READONLY:
        # 必须 autocommit 才设得进去：会话级只读是给「下一个事务」定的，
        # 已经开着的事务里改不了
        c.autocommit = True
        c.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        c.autocommit = False
    return c


@contextmanager
def question_generation_lock(qid):
    """Serialize complete solve generations for one question across processes."""
    with connect() as c:
        c.execute("SELECT pg_advisory_lock(%s)", (qid,))
        c.commit()
        try:
            yield
        finally:
            c.execute("SELECT pg_advisory_unlock(%s)", (qid,))
            c.commit()


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
def publish(workdir, name=None, conn=None, owner_id=None):
    """
    把一卷的构建产物导进库。**整卷替换**，在一个事务里。

    重跑 segment.py 会重写整份 questions.json，所以这里也是整卷替换语义：
    删掉旧的 questions（级联清掉 options/tables），重新插。
    papers 那一行保留 —— 它的 id 被 assets 引用，而且 created_at 有意义。

    `owner_id` 只在这一行**还没有主**的时候才写进去。重新发布一份已有的卷子
    不该改变它归谁 —— 否则谁最后重跑一遍谁就成了它的主人。命令行那条链
    传不进 owner_id（没有登录态），落库就是无主的，见 schema.sql 的说明。
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
                                dropped_boilerplate, updated_at, run_started_at,
                                owner_id)
            VALUES (%s,%s,%s,%s,%s,%s, now(), now(), %s)
            ON CONFLICT (name) DO UPDATE SET
              source_pdf=EXCLUDED.source_pdf, n_questions=EXCLUDED.n_questions,
              sections=EXCLUDED.sections, warnings=EXCLUDED.warnings,
              dropped_boilerplate=EXCLUDED.dropped_boilerplate, updated_at=now(),
              -- 每次发布就是一轮新的处理，起点在这里重置
              run_started_at=now(),
              -- 已经有主的不改主。谁最后重跑一遍谁就成主人是不对的
              owner_id=COALESCE(papers.owner_id, EXCLUDED.owner_id)
            RETURNING id""",
            (name, data.get("source"), len(data["questions"]),
             json.dumps(data.get("sections", []), ensure_ascii=False),
             json.dumps(data.get("warnings", []), ensure_ascii=False),
             json.dumps(data.get("dropped_boilerplate", []), ensure_ascii=False),
             owner_id))
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
def delete_papers(names, owner_id=None):
    """
    删卷。库里一个事务删干净，然后清掉没人再引用的对象。

    **vlm_cache 一律不动** —— 它按图片内容哈希存，跟卷子无关。
    删卷级联到它，等于每删一卷就把下次重跑的成本从 20 次模型调用推回 300 次。

    `owner_id` 的过滤写在 SQL 里，不是在调用方检查一遍就算数：这是批量接口，
    一次几十个卷名，漏掉一个的代价是删掉别人的东西。不是自己的卷子会被算进
    `missing` —— 和「本来就不存在」一样对待，不告诉调用方它其实存在。
    """
    if not names:
        return {"deleted": [], "missing": [], "objects": 0}
    with connect() as c:
        cur = c.cursor()
        cur.execute("""SELECT name FROM papers
                        WHERE name = ANY(%s) AND (%s::bigint IS NULL OR owner_id = %s)""",
                    (list(names), owner_id, owner_id))
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
def list_papers(owner_id=None):
    """
    试卷列表。给了 owner_id 就**只给这个账号的** —— 试卷是按人隔离的。

    owner_id=None 是给命令行和运维用的「全都要」，API 那条路一律带 owner_id。
    """
    with connect() as c:
        cur = c.cursor()
        cur.execute("""
            SELECT p.name, p.n_questions, jsonb_array_length(p.warnings),
                   p.updated_at,
                   (SELECT count(*) FROM assets a
                     WHERE a.paper_id=p.id AND a.kind IN ('img','mathimg')),
                   p.source_kind,
                   -- 答题卡那一列：有官方解答过程的题数。参考答案的版式就是只有
                   -- 大题给详解，所以这个数天生小于题数，不是缺陷
                   (SELECT count(*) FROM questions q
                     WHERE q.paper_id=p.id AND q.ref_solution IS NOT NULL),
                   (SELECT count(*) FROM questions q
                     WHERE q.paper_id=p.id AND jsonb_array_length(q.kps) > 0)
              FROM papers p
             WHERE %s::bigint IS NULL OR p.owner_id = %s
             ORDER BY p.updated_at DESC""", (owner_id, owner_id))
        return [{"name": r[0], "n": r[1], "warnings": r[2],
                 "mtime": r[3].timestamp(), "figures": r[4],
                 "sourceKind": r[5], "withSolution": r[6], "kps": r[7]}
                for r in cur.fetchall()]


def paper_owner(name):
    """
    这份卷子归谁。返回 (存在吗, owner_id)。

    分成两个值是有意的：**「不存在」和「存在但不是你的」在 API 那边要给出
    同一个 404** —— 不然拿一堆卷名去试，就能问出别人库里有什么。
    但存储层不该替上层做这个决定，所以这里如实回报。
    """
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT owner_id FROM papers WHERE name=%s", (name,))
        r = cur.fetchone()
        return (False, None) if not r else (True, r[0])


def free_name(base, also_taken=()):
    """
    挑一个还没被占用的卷名。

    卷名全局唯一，因为 `work/<卷名>/` 是按它建目录的 —— 两个账号传同名卷子，
    在磁盘上会写进同一个构建目录，两条管线互相覆盖。所以重名在上传时就避开：
    `2023年高考福建卷物理真题` → `2023年高考福建卷物理真题 (2)`。

    **不告诉后来的人「这个名字被谁占了」**，只是换一个名字继续 ——
    否则卷名就成了一个能探测别人库存的接口。

    `also_taken` 是库外的占用：卷子要跑完 ①②②b 才 publish，这几分钟里它在库里
    还不存在，只有 api.py 的 CLAIMS 知道这个名字已经被人开跑了。不带上它的话，
    两个账号在这个窗口里会各自算出同一个「(2)」。
    """
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT name FROM papers WHERE name = %s OR name LIKE %s",
                    (base, base.replace("\\", "\\\\").replace("%", "\\%")
                             .replace("_", "\\_") + " (%)"))
        taken = {r[0] for r in cur.fetchall()} | set(also_taken)
    if base not in taken:
        return base
    k = 2
    while "%s (%d)" % (base, k) in taken:
        k += 1
    return "%s (%d)" % (base, k)


def get_paper(name):
    """整卷读回，形状与旧的 questions.json 一致，好让上层不必改。"""
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT id, source_pdf, sections, warnings, source_kind "
                    "FROM papers WHERE name=%s", (name,))
        row = cur.fetchone()
        if not row:
            return None
        pid, src, sections, warnings, src_kind = row
        cur.execute("""SELECT id, n, type, points, section, stem, stem_latex,
                              stem_low_conf, stem_image, option_image, text_quality,
                              quality_reason, n_chars, pages, label,
                              anim_worth, anim_why,
                              kps, ref_answer, ref_answer_src, ref_solution,
                              stem_math, flattened, layout
                         FROM questions WHERE paper_id=%s ORDER BY n""", (pid,))
        cols = [d[0] for d in cur.description]
        qs = [dict(zip(cols, r)) for r in cur.fetchall()]
        by_id = {q["id"]: q for q in qs}
        # `layout` 是版面信息（插图、图在正文里的落位、选项区截图……），
        # 由 ②切分 写进去。**答案卷这一列是空对象 `{}`**（schema.sql 里
        # `layout jsonb NOT NULL DEFAULT '{}'`，而答案卷走的 put_answer_question
        # 的 INSERT 列表里没有 layout，所以拿到的是默认值，不是 NULL）——
        # 它那条链根本不过 ②，所以这里要把缺的键补成空的。
        #
        # 不补的话，缺的不是「值是 None」而是「键根本不存在」，
        # 而下游 `api.paper` 那句 `x["figures"]` 是硬取 —— 整个端点 500，
        # 答案卷的详情页从来就打不开。这个函数的契约是「形状与旧的
        # questions.json 一致」，那就得对两条链都一致。
        for q in qs:
            q.update(q.pop("layout") or {})
            q.setdefault("figures", [])
            q.setdefault("fig_marks", [])
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
        # sourceKind 页面要用来分开「解析试卷」和「答题卡诊断」两个功能。
        # 建库早于这一列的卷子是 NULL，按普通试卷算 —— 不能让它掉进判卷那条分支
        return {"name": name, "source": src, "sections": sections,
                "sourceKind": src_kind or "pdf",
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


def put_kps(qid, kps):
    """
    阶段③c 的产出：这道题的知识点标签，形如 `[{"code": ..., "why": ...}]`。

    整体替换而不是追加：③c 是整卷一次调用，每次都给出这道题的完整清单，
    追加会让重跑一次就变成两倍标签。
    """
    with connect() as c:
        c.execute("UPDATE questions SET kps=%s WHERE id=%s",
                  (json.dumps(kps, ensure_ascii=False), qid))
        c.commit()


def put_ref_answer(qid, text, src):
    """
    阶段②c 的产出：卷子上的标准答案。`src` 必须是 paper / answer_file / none 之一。

    抽不到也要写一行（text=None, src='none'）—— 「抽不到」和「还没跑过 ②c」
    在页面上是两句不同的话，靠这一列区分。src 写野了当场抛：这一列的值
    会决定页面上说哪句话，混进第四个值会让页面静静地什么都不说。
    """
    if src not in ("paper", "answer_file", "none"):
        raise ValueError("ref_answer_src 只能是 paper/answer_file/none，给的是 %r" % src)
    with connect() as c:
        c.execute("UPDATE questions SET ref_answer=%s, ref_answer_src=%s WHERE id=%s",
                  (text, src, qid))
        c.commit()


# ------------------------------------------------- 只有参考答案 + 题目图的卷子
def create_answers_paper(name, owner_id=None):
    """
    建一份「参考答案 + 题目图」的卷子。没有 questions.json，所以**不走 publish**。

    题目由 Ⓐ（refread）一条条写进去，题干由 Ⓔ（stemread）按题号填。
    两步分工写死，谁都不许碰对方那一列 —— 见 put_answer_question / put_stem。

    **撞上一份解析试卷就抛，不许就地转模式。** 原来这条 upsert 无条件
    `source_kind='answers_only'`，于是填一个和某份高考真题重名的卷名，
    那份跑了一小时的卷子会当场变成答题卡卷子：进度改走两格链，解法和动画
    还在库里却一格都不显示，**而且一句提示都没有**。
    调用方（API）该在挑卷名时就用 free_name 避开，走到这里抛已经是最后一道闸。
    """
    with connect() as c:
        cur = c.cursor()
        cur.execute("""
            INSERT INTO papers (name, n_questions, source_kind, updated_at,
                                run_started_at, owner_id)
            VALUES (%s, 0, 'answers_only', now(), now(), %s)
            ON CONFLICT (name) DO UPDATE SET
              updated_at=now(), run_started_at=now(),
              owner_id=COALESCE(papers.owner_id, EXCLUDED.owner_id)
            WHERE papers.source_kind = 'answers_only'
            RETURNING id""", (name, owner_id))
        row = cur.fetchone()
        if not row:
            # DO UPDATE 的 WHERE 没通过：这个名字被一份解析试卷占着
            c.rollback()
            raise ValueError(
                "「%s」已经是一份解析试卷，不能把它改成答题卡卷子 —— 换个卷名" % name)
        c.commit()
        return row[0]


def source_kind_of(name):
    """`pdf` / `answers_only`；卷子不存在回 None。"""
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT source_kind FROM papers WHERE name=%s", (name,))
        r = cur.fetchone()
        return r[0] if r else None


def _bump_qcount(cur, paper_name):
    cur.execute("""UPDATE papers SET
                     n_questions=(SELECT count(*) FROM questions q
                                   WHERE q.paper_id=papers.id),
                     updated_at=now()
                   WHERE name=%s""", (paper_name,))


def put_answer_question(paper_name, n, ref_answer, ref_solution):
    """
    Ⓐ 的产出：一道题的标准答案与官方解答过程。返回 question_id。

    **只更新这三列。** `stem` 是 Ⓔ 的、`kps` 是 ③c 的 —— 列进 DO UPDATE SET
    就会在重跑 Ⓐ 时把它们冲没了。期一 publish 那次就是这个坑。
    """
    with connect() as c:
        cur = c.cursor()
        cur.execute("""
            INSERT INTO questions (paper_id, n, stem, ref_answer, ref_solution,
                                   ref_answer_src)
            SELECT p.id, %s, '', %s, %s, 'answer_file' FROM papers p WHERE p.name=%s
            ON CONFLICT (paper_id, n) DO UPDATE SET
              ref_answer=EXCLUDED.ref_answer,
              ref_solution=EXCLUDED.ref_solution,
              ref_answer_src=EXCLUDED.ref_answer_src
            RETURNING id""", (n, ref_answer, ref_solution, paper_name))
        row = cur.fetchone()
        if not row:
            raise ValueError("库里没有「%s」" % paper_name)
        _bump_qcount(cur, paper_name)
        c.commit()
        return row[0]


def put_stem(paper_name, n, stem):
    """
    Ⓔ 的产出：一道题的题干。

    **只更新 stem 一列。** 答案、解答过程、知识点都不许碰 —— 同上。
    题号必须已经由 Ⓐ 写进来过（参考答案上的题号是权威的），没有就抛。
    """
    with connect() as c:
        cur = c.cursor()
        cur.execute("""UPDATE questions q SET stem=%s
                        FROM papers p
                       WHERE p.id=q.paper_id AND p.name=%s AND q.n=%s
                       RETURNING q.id""", (stem, paper_name, n))
        if not cur.fetchone():
            raise ValueError("「%s」里没有第 %s 题 —— 题号清单以参考答案为准"
                             % (paper_name, n))
        c.commit()


def drop_questions(paper_name, ns):
    """
    删掉指定题号的题。**给人手动收拾读错的题号用，管线自己不调。**

    不让 refread 自动删的两个理由：这一次可能有页失败，删就会误伤；
    而且 sheet_answers 以 ON DELETE CASCADE 挂在 questions 上，
    删一道题会连学生的作答一起删掉。
    """
    with connect() as c:
        cur = c.cursor()
        cur.execute("""DELETE FROM questions q USING papers p
                        WHERE p.id=q.paper_id AND p.name=%s AND q.n = ANY(%s)""",
                    (paper_name, list(ns)))
        n = cur.rowcount
        _bump_qcount(cur, paper_name)
        c.commit()
        return n


def put_page_asset(paper_name, local_path, rel_path):
    """把一页原图挂到卷子上。资产行的形状与 publish 里那段一致。"""
    row = put_asset(local_path, rel_path)
    with connect() as c:
        c.execute("""
            INSERT INTO assets (paper_id, kind, rel_path, sha256, bytes,
                                content_type, storage, object_key)
            SELECT p.id, %s,%s,%s,%s,%s,%s,%s FROM papers p WHERE p.name=%s
            ON CONFLICT (paper_id, rel_path) DO UPDATE SET
              sha256=EXCLUDED.sha256, bytes=EXCLUDED.bytes,
              content_type=EXCLUDED.content_type,
              storage=EXCLUDED.storage, object_key=EXCLUDED.object_key""",
            (row["kind"], row["rel_path"], row["sha256"], row["bytes"],
             row["content_type"], row["storage"], row["object_key"], paper_name))
        c.commit()


# ---------------------------------------------------------------- 答题卡
# 允许写进 sheet_answers 的列。**白名单，不是 kwargs 直通** ——
# 拼错一个列名会静默写不进去，而阅卷结果错了页面上看不出来
_SHEET_COLS = ("question_id", "raw_text", "norm", "crop_rel", "box", "page",
               "read_conf", "reread", "reread_raw",
               "verdict", "verdict_by", "verdict_why")

_VERDICTS = ("right", "wrong", "blank", "unsure")


def create_sheet(paper_name, student_label, owner_id, n_pages=0):
    """新建一份答题卡，返回 id。卷子不存在就当场抛。"""
    with connect() as c:
        cur = c.cursor()
        cur.execute("""INSERT INTO answer_sheets (paper_id, owner_id, student_label, n_pages)
                       SELECT p.id, %s, %s, %s FROM papers p WHERE p.name=%s
                       RETURNING id""",
                    (owner_id, student_label, n_pages, paper_name))
        row = cur.fetchone()
        if not row:
            raise ValueError("库里没有「%s」" % paper_name)
        c.commit()
        return row[0]


def set_sheet_pages(sheet_id, n):
    with connect() as c:
        c.execute("UPDATE answer_sheets SET n_pages=%s WHERE id=%s", (n, sheet_id))
        c.commit()


def put_sheet_answer(sheet_id, n, **fields):
    """
    写一题的作答与判定。**按 (sheet_id, n) 覆盖，不追加** —— 复读会把同一题
    再写一次，追加的话页面上会出现两行。

    **只更新这次给了的列。** 复读那一步只写 reread_raw 和 verdict，不该顺手
    把 crop_rel 抹成 NULL —— 原图切片没了，这个功能唯一的红绿灯就废了。
    """
    bad = set(fields) - set(_SHEET_COLS)
    if bad:
        raise ValueError("不认识的列：%s" % ", ".join(sorted(bad)))
    cols = [k for k in _SHEET_COLS if k in fields]
    vals = [json.dumps(fields[k], ensure_ascii=False) if k == "box" else fields[k]
            for k in cols]
    sets = ", ".join("%s=EXCLUDED.%s" % (k, k) for k in cols) or "n=EXCLUDED.n"
    sql = ("INSERT INTO sheet_answers (sheet_id, n%s) VALUES (%%s, %%s%s) "
           "ON CONFLICT (sheet_id, n) DO UPDATE SET %s"
           % ("".join(", " + k for k in cols), ", %s" * len(cols), sets))
    with connect() as c:
        c.execute(sql, [sheet_id, n] + vals)
        c.commit()


def sheet_answers(sheet_id):
    """
    一份答题卡的全部作答，按题号。

    **`final_verdict` 只在这里算一次。** 老师改判存在单独一列，对外读到的
    必须是改判后的结果 —— 让每个调用点各写一份 COALESCE，总会漏掉一个，
    漏掉的那个表现为「老师改了判，某个地方还显示旧结果」。
    """
    with connect() as c:
        cur = c.cursor()
        cur.execute("""SELECT id, question_id, n, raw_text, norm, crop_rel, box, page,
                              read_conf, reread, reread_raw,
                              verdict, verdict_by, verdict_why, teacher_verdict,
                              COALESCE(teacher_verdict, verdict) AS final_verdict
                         FROM sheet_answers WHERE sheet_id=%s ORDER BY n""",
                    (sheet_id,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def set_teacher_verdict(sheet_id, n, verdict):
    """
    老师改判。`verdict=None` 表示撤回改判，退回系统原判。

    **不碰 verdict 那一列。** 留着原判才看得出系统错在哪，也才撤得回来。
    """
    if verdict is not None and verdict not in _VERDICTS:
        raise ValueError("verdict 只能是 right/wrong/blank/unsure 或 None，"
                         "给的是 %r" % verdict)
    with connect() as c:
        c.execute("UPDATE sheet_answers SET teacher_verdict=%s WHERE sheet_id=%s AND n=%s",
                  (verdict, sheet_id, n))
        # 诊断过没过期靠它判，所以改判必须 touch
        c.execute("UPDATE answer_sheets SET updated_at=now() WHERE id=%s", (sheet_id,))
        c.commit()


def list_sheets(paper_name):
    """这份卷子下面的所有答题卡，新的在前。错题数按**改判后**的算。"""
    with connect() as c:
        cur = c.cursor()
        cur.execute("""SELECT s.id, s.student_label, s.n_pages, s.created_at, s.updated_at,
                              (SELECT count(*) FROM sheet_answers a WHERE a.sheet_id=s.id),
                              (SELECT count(*) FROM sheet_answers a WHERE a.sheet_id=s.id
                                AND COALESCE(a.teacher_verdict, a.verdict)='wrong')
                         FROM answer_sheets s JOIN papers p ON p.id=s.paper_id
                        WHERE p.name=%s ORDER BY s.created_at DESC""", (paper_name,))
        return [{"id": r[0], "student": r[1], "nPages": r[2],
                 "created_at": r[3], "updated_at": r[4],
                 "answers": r[5], "wrong": r[6]} for r in cur.fetchall()]


def sheet_owner(sheet_id):
    """这份答题卡属于哪份卷子、归谁。返回 (卷名, owner_id) 或 (None, None)。"""
    with connect() as c:
        cur = c.cursor()
        cur.execute("""SELECT p.name, p.owner_id FROM answer_sheets s
                         JOIN papers p ON p.id = s.paper_id WHERE s.id=%s""", (sheet_id,))
        r = cur.fetchone()
        return (r[0], r[1]) if r else (None, None)


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

    **计数要跟着管线口径走，不能只数「有几行」。** ④ 现在只给 ④c 选中的题写
    断言，所以「specs 少于 solutions」是常态而不是没跑完 —— 按旧口径算，
    一份跑完的卷子会永远停在「④ 写断言 6/16」。所以这里多给四个数，
    每个都对着管线里真正的那道闸门：
      labels      已成功解出的题里有几道生成了目录标题（失败题即使残留标题也不算）
      specsWorth  选中的题里写了几份 spec        （④ 的分母是 worth，不是题数）
      drafts      还没过 ④b 自检的 spec          （animatable=false 的不算，
                                                  speccheck 根本不看它们）
      ready       ⑤ 真正会做的题（自检通过 + 选中）
      sceneTried  这些题里已经试过的（**不管过没过门禁** —— 试过就是做完了，
                  一直数「绿灯几个」的话，有一道怎么都过不了就永远显示在跑）
    """
    with connect() as c:
        cur = c.cursor()
        cur.execute("""
            SELECT p.id, p.n_questions, p.assembled_at, p.run_started_at, p.source_kind,
                   (SELECT count(*) FROM questions q WHERE q.paper_id=p.id),
                   -- ③c 的分母是**题数**，不是解出来的题数：没解出来的题也该有
                   -- 知识点（只看题干就判得出个大概），诊断报告要拿它做聚合
                   (SELECT count(*) FROM questions q
                     WHERE q.paper_id=p.id AND jsonb_array_length(q.kps) > 0),
                   -- ③b 的分母只数**已经有解法**的题。否则一道终态失败的题留下的
                   -- 标题会冒充成进度，而它永远等不到解法
                   (SELECT count(*) FROM solutions s JOIN questions q ON q.id=s.question_id
                     WHERE q.paper_id=p.id AND q.label IS NOT NULL),
                   (SELECT count(*) FROM solutions s JOIN questions q ON q.id=s.question_id
                     WHERE q.paper_id=p.id),
                   (SELECT count(*) FROM solution_failures f JOIN questions q ON q.id=f.question_id
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
                   (SELECT count(*) FROM specs sp JOIN questions q ON q.id=sp.question_id
                     WHERE q.paper_id=p.id AND q.anim_worth),
                   (SELECT count(*) FROM specs sp JOIN questions q ON q.id=sp.question_id
                     WHERE q.paper_id=p.id AND sp.animatable AND sp.status='draft'),
                   (SELECT count(*) FROM specs sp JOIN questions q ON q.id=sp.question_id
                     WHERE q.paper_id=p.id AND sp.animatable AND sp.status='approved'
                       AND q.anim_worth),
                   (SELECT count(*) FROM specs sp JOIN questions q ON q.id=sp.question_id
                      JOIN scenes sc ON sc.question_id = q.id
                     WHERE q.paper_id=p.id AND sp.animatable AND sp.status='approved'
                       AND q.anim_worth),
                   GREATEST(p.updated_at,
                     COALESCE((SELECT max(s.created_at) FROM solutions s
                                 JOIN questions q ON q.id=s.question_id
                                WHERE q.paper_id=p.id), p.updated_at),
                     COALESCE((SELECT max(f.updated_at) FROM solution_failures f
                                 JOIN questions q ON q.id=f.question_id
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
    (_pid, _nq, asm_at, started, src_kind,
     n_q, n_kps, n_label, n_sol, n_failure, n_spec, n_appr, n_judged,
     n_worth, n_scene, n_spec_worth, n_draft, n_ready, n_scene_try, last, now) = r
    idle = (now - last).total_seconds()
    # 总时长：跑完了就是 起点→装配完成，还在跑就是 起点→现在
    elapsed = ((asm_at or now) - started).total_seconds() if started else None
    return {"sourceKind": src_kind,
            "questions": n_q, "labels": n_label, "kps": n_kps, "solutions": n_sol,
            "solutionFailures": n_failure,
            "startedAt": started.timestamp() if started else None,
            "elapsedSeconds": elapsed,
            "specs": n_spec, "approved": n_appr, "judged": n_judged,
            "worth": n_worth, "scenes": n_scene,
            "specsWorth": n_spec_worth, "drafts": n_draft,
            "ready": n_ready, "sceneTried": n_scene_try,
            "assembled": bool(asm_at),
            # 装过 ≠ 装的是现在这份数据。解完题不重装的话，out.html 还是零解法的
            # 那一版 —— 那不叫「完成」，所以「完成」判定要用这个，不是 assembled
            "assembledFresh": bool(asm_at) and asm_at >= last,
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
                     COALESCE((SELECT max(f.updated_at) FROM solution_failures f
                                 JOIN questions q ON q.id = f.question_id
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
        c.execute("SELECT id FROM questions WHERE id=%s FOR UPDATE", (qid,))
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
        c.execute("DELETE FROM solution_failures WHERE question_id=%s", (qid,))
        c.commit()


def clear_solution_failure(qid):
    with connect() as c:
        cur = c.cursor()
        cur.execute("""SELECT p.id FROM papers p
                         JOIN questions q ON q.paper_id=p.id
                        WHERE q.id=%s
                        FOR UPDATE OF p""", (qid,))
        cur.execute("SELECT id FROM questions WHERE id=%s FOR UPDATE", (qid,))
        cur.execute("DELETE FROM solution_failures WHERE question_id=%s RETURNING question_id", (qid,))
        if cur.fetchone() is not None:
            cur.execute("""UPDATE papers SET updated_at=clock_timestamp()
                           WHERE id=(SELECT paper_id FROM questions WHERE id=%s)""", (qid,))
        c.commit()


def put_solution_failure(qid, kind, reason, attempts, stage):
    """Persist the terminal solve result, replacing any successful solution."""
    with connect() as c:
        c.execute("SELECT id FROM questions WHERE id=%s FOR UPDATE", (qid,))
        c.execute("DELETE FROM solutions WHERE question_id=%s", (qid,))
        c.execute("""INSERT INTO solution_failures (question_id, kind, reason, attempts, stage)
                     VALUES (%s,%s,%s,%s,%s)
                     ON CONFLICT (question_id) DO UPDATE SET
                       kind=EXCLUDED.kind, reason=EXCLUDED.reason,
                       attempts=EXCLUDED.attempts, stage=EXCLUDED.stage,
                       updated_at=now()""",
                  (qid, kind, str(reason)[:240], attempts, stage))
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


def paper_solution_failures(name):
    """Terminal solve failures for one paper, fetched in one query."""
    with connect() as c:
        cur = c.cursor()
        cur.execute("""SELECT q.n, f.kind, f.reason, f.attempts, f.stage, f.updated_at
                         FROM questions q
                         JOIN papers p ON p.id=q.paper_id
                         JOIN solution_failures f ON f.question_id=q.id
                        WHERE p.name=%s
                        ORDER BY q.n""", (name,))
        return {r[0]: {"kind": r[1], "reason": r[2], "attempts": r[3],
                       "stage": r[4], "updated_at": (r[5].isoformat()
                                                        if hasattr(r[5], "isoformat") else str(r[5]))}
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


def put_scene(qid, sid, rounds, passed, gen="agent"):
    """
    ⑤ 的产出。**失败不许覆盖成功** —— 这是 WHERE 那一行的全部意义。

    没有它的话，重跑一道已经有动画的题、而这次跑满轮数没过，就会把库里那行
    `passed=true` 改成 `false`；`paper_scenes` 只取 passed 的，于是页面上那道题的
    动画**凭空消失**了 —— 用户只是想让它更好看一点，结果连原来的都没了。
    磁盘上的旧场景文件还在，但库是唯一真相源，没人会去捞。

    三种情形，一条 WHERE 说清：
      新的过了            → 覆盖（不管旧的什么样）
      新旧都没过          → 覆盖（刷新这条尝试记录，sceneTried 才数得对）
      新的没过、旧的过了  → **跳过**

    这跟下面 put_scene_attempt 的 DO NOTHING 是同一个直觉，只是那条管的是
    「⑤ 抛异常」，这条管的是「跑满轮数仍未通过」—— 两条路都能抹掉好结果。

    `gen` 记这个场景是哪套流程产的（agent / codegen）。两套并存期间出了问题
    要分得清是谁的锅 —— 默认 'agent'，不传时老行为一个字不变。

    **被换下来的那个不记在库里。** 试过记一列 `prev_scene_id` 做「换回上一个」，
    但它只存一级、连跑两次就被覆盖，而真正兜底的是 `runs/<id>/` 里的文件和
    git —— 那两样删不掉。为一个够不着的退路留一列和一堆代码不划算。
    """
    with connect() as c:
        c.execute("""INSERT INTO scenes (question_id, scene_id, rounds, passed, gen)
                     VALUES (%s,%s,%s,%s,%s)
                     ON CONFLICT (question_id) DO UPDATE SET
                       scene_id=EXCLUDED.scene_id, rounds=EXCLUDED.rounds,
                       passed=EXCLUDED.passed, gen=EXCLUDED.gen, created_at=now()
                     WHERE EXCLUDED.passed OR NOT scenes.passed""",
                  (qid, sid, rounds, passed, gen))
        c.commit()






def put_scene_attempt(qid, sid):
    """
    这道题**试过了但没试成**（⑤ 那边直接抛了异常，连门禁都没跑到）。

    非记不可：进度里的 `sceneTried` 数的是「有没有 scenes 行」，抛异常那条路
    一行都不写，于是 `sceneTried < ready` 永远成立 —— ⑤ 那一步永远显示在跑，
    卷子早就停了也一样。这正是 sceneTried 当初不数「绿灯几个」要避开的坑，
    只是从另一头漏了出去。

    `DO NOTHING` 不是 `DO UPDATE`：这道题上一轮可能已经绿灯了，这一轮只是重跑时
    崩了一下，不能拿一条异常把那次通过抹掉。
    """
    with connect() as c:
        c.execute("""INSERT INTO scenes (question_id, scene_id, rounds, passed)
                     VALUES (%s,%s,0,false)
                     ON CONFLICT (question_id) DO NOTHING""", (qid, sid))
        c.commit()


def approve_spec(qid, ok=True):
    """人审通过与否。阶段⑤ 默认只接受 approved 的 spec。"""
    with connect() as c:
        c.execute("UPDATE specs SET status=%s WHERE question_id=%s",
                  ("approved" if ok else "rejected", qid))
        c.commit()


# ---------------------------------------------------------------- 账号与会话
def norm_email(email):
    """规范化：去空格 + 转小写。`Jerry@X.com` 和 `jerry@x.com ` 必须是同一个人。"""
    return (email or "").strip().lower()


def get_user_by_email(email):
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT id, email, created_at FROM users WHERE email=%s",
                    (norm_email(email),))
        r = cur.fetchone()
        return None if not r else {"id": r[0], "email": r[1], "createdAt": r[2].timestamp()}


def create_user(email):
    """
    建账号。返回 (账号, 是不是新建的)。

    **第一个账号会把所有无主试卷认领走**。库里现存的卷子都是加登录之前跑的，
    owner_id 是 NULL；不认领的话它们对谁都不可见 —— 数据还在，人却打不开，
    这比「归属可能不对」糟得多。之后再有无主卷子（命令行跑的），
    用 `store.py claim <邮箱>` 手动收。
    """
    email = norm_email(email)
    with connect() as c:
        cur = c.cursor()
        cur.execute("""INSERT INTO users (email) VALUES (%s)
                       ON CONFLICT (email) DO NOTHING RETURNING id""", (email,))
        r = cur.fetchone()
        fresh = r is not None
        if fresh:
            uid = r[0]
            cur.execute("SELECT count(*) FROM users")
            if cur.fetchone()[0] == 1:
                cur.execute("UPDATE papers SET owner_id=%s WHERE owner_id IS NULL", (uid,))
        else:
            cur.execute("SELECT id FROM users WHERE email=%s", (email,))
            uid = cur.fetchone()[0]
        cur.execute("UPDATE users SET last_login_at=now() WHERE id=%s", (uid,))
        c.commit()
    return {"id": uid, "email": email}, fresh


def claim_orphans(email):
    """把所有无主试卷收到某个账号名下。命令行跑的卷子靠它进到某个人的库里。"""
    u = get_user_by_email(email)
    if not u:
        return -1
    with connect() as c:
        cur = c.cursor()
        cur.execute("UPDATE papers SET owner_id=%s WHERE owner_id IS NULL", (u["id"],))
        n = cur.rowcount
        c.commit()
    return n


def put_login_code(email, code_hash, ttl_min):
    """
    写下这个邮箱当前的验证码。一个邮箱同时只有一个 —— 重新要码就覆盖，
    上一个立刻作废。返回 False 表示**要得太频繁**，这一次不该发信。
    """
    email = norm_email(email)
    with connect() as c:
        cur = c.cursor()
        cur.execute("""SELECT sent_at > now() - interval '60 seconds'
                         FROM login_codes WHERE email=%s""", (email,))
        r = cur.fetchone()
        if r and r[0]:
            return False
        cur.execute("""
            INSERT INTO login_codes (email, code_sha256, expires_at, tries, sent_at)
            VALUES (%s, %s, now() + make_interval(mins => %s), 0, now())
            ON CONFLICT (email) DO UPDATE SET
              code_sha256=EXCLUDED.code_sha256, expires_at=EXCLUDED.expires_at,
              tries=0, sent_at=now()""", (email, code_hash, ttl_min))
        c.commit()
    return True


MAX_TRIES = 5


def check_login_code(email, code_hash):
    """
    核验验证码。返回 (通过吗, 说明)。通过就把这个码销掉 —— 一码一用。

    试错次数写在库里而不是内存里：6 位数字只有一百万种，进程重启一次就把
    计数清零的话，慢慢试是能试出来的。
    """
    email = norm_email(email)
    with connect() as c:
        cur = c.cursor()
        cur.execute("""SELECT code_sha256, expires_at < now(), tries
                         FROM login_codes WHERE email=%s FOR UPDATE""", (email,))
        r = cur.fetchone()
        if not r:
            return False, "还没给这个邮箱发过验证码"
        want, expired, tries = r
        if expired:
            cur.execute("DELETE FROM login_codes WHERE email=%s", (email,))
            c.commit()
            return False, "验证码已过期，重新获取一个"
        if tries >= MAX_TRIES:
            cur.execute("DELETE FROM login_codes WHERE email=%s", (email,))
            c.commit()
            return False, "错太多次了，这个验证码已作废，重新获取一个"
        if code_hash != want:
            cur.execute("UPDATE login_codes SET tries=tries+1 WHERE email=%s", (email,))
            c.commit()
            return False, "验证码不对（还可以试 %d 次）" % (MAX_TRIES - tries - 1)
        cur.execute("DELETE FROM login_codes WHERE email=%s", (email,))
        c.commit()
    return True, ""


def create_session(user_id, token_hash, days=30):
    with connect() as c:
        c.execute("""INSERT INTO sessions (token_sha256, user_id, expires_at)
                     VALUES (%s, %s, now() + make_interval(days => %s))""",
                  (token_hash, user_id, days))
        c.commit()


def session_user(token_hash):
    """
    拿会话换账号。过期的当不存在，顺手删掉。

    `last_seen_at` 每次都写 —— 一次 UPDATE 换来的是「这个会话还活着吗」
    可查，对一个能烧模型额度的系统来说值这一次写。
    """
    if not token_hash:
        return None
    with connect() as c:
        cur = c.cursor()
        cur.execute("""SELECT u.id, u.email, s.expires_at < now()
                         FROM sessions s JOIN users u ON u.id = s.user_id
                        WHERE s.token_sha256=%s""", (token_hash,))
        r = cur.fetchone()
        if not r:
            return None
        if r[2]:
            cur.execute("DELETE FROM sessions WHERE token_sha256=%s", (token_hash,))
            c.commit()
            return None
        cur.execute("UPDATE sessions SET last_seen_at=now() WHERE token_sha256=%s",
                    (token_hash,))
        c.commit()
        return {"id": r[0], "email": r[1]}


def drop_session(token_hash):
    with connect() as c:
        c.execute("DELETE FROM sessions WHERE token_sha256=%s", (token_hash,))
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
    elif cmd == "claim":
        # 命令行跑的卷子落库时是无主的（没有登录态）。用这个把它们收进某个账号
        if len(sys.argv) < 3:
            print("用法：store.py claim <邮箱>")
            return
        n = claim_orphans(sys.argv[2])
        print("没有这个账号（先在页面上登录一次）" if n < 0
              else "%d 份无主试卷已归到 %s 名下" % (n, sys.argv[2]))
    elif cmd == "stat":
        with connect() as c:
            cur = c.cursor()
            cur.execute("SELECT count(*) FROM papers WHERE owner_id IS NULL")
            orphan = cur.fetchone()[0]
            if orphan:
                print("  ⚠ %d 份试卷无主，页面上谁都看不到（store.py claim <邮箱> 可以收）"
                      % orphan)
            for t in ("papers", "questions", "q_options", "q_tables",
                      "assets", "users", "sessions", "vlm_cache"):
                cur.execute("SELECT count(*) FROM " + t)
                print("  %-10s %d" % (t, cur.fetchone()[0]))
            cur.execute("SELECT storage, count(*), pg_size_pretty(sum(bytes)) "
                        "FROM assets GROUP BY storage")
            for s, n, sz in cur.fetchall():
                print("  资产 %s：%d 份，%s" % (s, n, sz))
    else:
        print("用法：store.py [init|stat|claim <邮箱>]")


if __name__ == "__main__":
    main()
