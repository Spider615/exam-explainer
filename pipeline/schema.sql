-- exam-explainer 的库结构
--
-- 分界线在这里：**产品数据进列，管线中间量进 jsonb**。
-- `stem`/`options`/`tables` 前端要渲染、要查；而 y_bounds / y_range / box / fig_marks
-- 只有 mathvlm.py 自己读回去用来裁图，拆成列没有任何人会去查它。
--
-- 另一条线：`work/<卷名>/` 是构建产物目录，这里是发布后的唯一真相源。
-- API 只读库。这样两份工作目录谁新谁旧都不影响线上——没 publish 就不算数。

CREATE TABLE IF NOT EXISTS papers (
  id                  bigserial PRIMARY KEY,
  name                text        NOT NULL UNIQUE,
  source_pdf          text,
  n_questions         int         NOT NULL DEFAULT 0,
  sections            jsonb       NOT NULL DEFAULT '[]',
  warnings            jsonb       NOT NULL DEFAULT '[]',
  dropped_boilerplate jsonb       NOT NULL DEFAULT '[]',
  -- 阶段⑦ 的落点。以前页面上的「⑦ 呈现」是硬编码 true，装没装过都亮绿 ——
  -- 而网页上传那条链根本就没跑过 ⑦。现在以这两列为准，没跑过就是灭的。
  -- 只记「跑过」还不够：out.html 是离线快照，③④⑤ 之后没重装它就是旧的，
  -- 所以要拿 assembled_at 和本卷最后一次数据变动比（见 store.assembled）。
  assembled_at        timestamptz,
  assembled_path      text,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);
-- 老库补列：上面的 CREATE TABLE IF NOT EXISTS 对已经存在的表不生效。
-- 下面几条同理（questions.label / solutions.short_answer 在各自建表语句里也写了一份）。
ALTER TABLE papers ADD COLUMN IF NOT EXISTS assembled_at   timestamptz;
-- 这一轮处理的起点。每次 publish（即每次上传）重置，配合 assembled_at
-- 就能算出「这份卷子从头到尾跑了多久」——以前这个数字根本无从得知。
ALTER TABLE papers ADD COLUMN IF NOT EXISTS run_started_at timestamptz;
ALTER TABLE papers ADD COLUMN IF NOT EXISTS assembled_path text;

CREATE TABLE IF NOT EXISTS questions (
  id             bigserial PRIMARY KEY,
  paper_id       bigint NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  n              int    NOT NULL,
  type           text,
  points         int,
  section        text,
  stem           text   NOT NULL DEFAULT '',
  -- 视觉模型逐块转写的题干，含 $...$ 行内公式。没转写过就是 NULL
  stem_latex     text,
  -- 转写可信度不足时的提示语，页面上必须显式标出来
  stem_low_conf  text,
  stem_image     text,
  option_image   text,
  text_quality   text,
  quality_reason text,
  n_chars        int,
  pages          int[],
  -- 阶段③b 给的 2-5 字短标题（「火星车」「简谐横波」），目录和速览用。
  -- 挂在 questions 上而不是 solutions 上：它描述的是题目本身，没解出来也该有。
  -- publish 的 upsert 不碰这一列，所以重新发布不会把它冲掉。
  label          text,
  stem_math      jsonb  NOT NULL DEFAULT '[]',
  flattened      jsonb  NOT NULL DEFAULT '[]',
  -- y_bounds / y_range / fig_marks / figures / option_figures
  layout         jsonb  NOT NULL DEFAULT '{}',
  UNIQUE (paper_id, n)
);
CREATE INDEX IF NOT EXISTS questions_paper_idx ON questions (paper_id);

CREATE TABLE IF NOT EXISTS q_options (
  id          bigserial PRIMARY KEY,
  question_id bigint NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  ord         int    NOT NULL,
  okey        text   NOT NULL,
  otext       text   NOT NULL DEFAULT '',
  latex       text,
  math        jsonb  NOT NULL DEFAULT '[]',
  figure      text,
  UNIQUE (question_id, okey)
);

CREATE TABLE IF NOT EXISTS q_tables (
  id          bigserial PRIMARY KEY,
  question_id bigint NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  -- 卷内检出序号，题干里的 〔表N〕 指的就是它
  tid         int    NOT NULL,
  page        int,
  caption     text   NOT NULL DEFAULT '',
  cells       jsonb  NOT NULL DEFAULT '[]',
  box         jsonb,
  -- 跨页续表：指向同一道题里上半张的 tid。合并在读取时做，不落库
  cont_of     int,
  image       text,
  UNIQUE (question_id, tid)
);

-- 资产：这一张就是存储层的抽象。
-- storage='local' 时文件留在 work/<卷名>/<rel_path>；='minio' 时在桶里。
-- 对外 URL 一律由 api.py 代理，所以换后端**不影响前端任何一个 URL**。
CREATE TABLE IF NOT EXISTS assets (
  id           bigserial PRIMARY KEY,
  paper_id     bigint NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  kind         text   NOT NULL,          -- pdf | page | img | mathimg
  rel_path     text   NOT NULL,          -- 卷内相对路径，questions 里引用的就是它
  sha256       text   NOT NULL,
  bytes        bigint NOT NULL,
  content_type text   NOT NULL DEFAULT 'application/octet-stream',
  storage      text   NOT NULL,
  object_key   text,
  UNIQUE (paper_id, rel_path)
);
CREATE INDEX IF NOT EXISTS assets_sha_idx ON assets (sha256);

-- 视觉模型转写缓存，按**图片内容哈希**存。
--
-- 它跟卷子无关，所以删卷时绝对不能跟着删 —— 实测一次全量重跑靠它只花 20 次
-- 模型调用而不是 300 次。删卷级联到这张表就等于每次删卷都在烧钱。
-- 这也是它不挂 paper_id 外键的原因：没有可级联的路径，就不会被误删。
-- 阶段③ 解题。
--
-- `src_sha256` 是题面内容的哈希（题干 + 选项 + 插图字节）。题没变就不重算 ——
-- 和 vlm_cache 一个道理，只是这里的成本单位是「一次带图推理」。
--
-- `assumptions` 是题面没给、解题时自己补上的东西。它必须显式列出来：
-- 阶段④ 的断言就架在这些假设上，假设错了断言会「错得自洽」，
-- 门禁全绿而物理是错的 —— 人审时要盯的正是这一栏。
CREATE TABLE IF NOT EXISTS solutions (
  question_id bigint PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
  answer      text,
  -- 阶段③b 压出来的速览用短答案：选择题就是选项字母，多空题用 / 隔开，
  -- 解答题取最终表达式。`answer` 那一栏是给人读的完整版（第15题是一长串三问），
  -- 塞进目录和速览表里会把版面撑爆。两栏并存，谁也别替谁。
  short_answer text,
  steps       jsonb       NOT NULL DEFAULT '[]',
  key_facts   jsonb       NOT NULL DEFAULT '[]',
  assumptions jsonb       NOT NULL DEFAULT '[]',
  confidence  text,
  src_sha256  text        NOT NULL,
  model       text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS solution_failures (
  question_id bigint PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
  kind        text NOT NULL,
  reason      text NOT NULL,
  attempts    int NOT NULL,
  stage       text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

-- 阶段④ 写 spec 与断言。
--
-- `status` 默认 draft：**断言是整条链上唯一没有下游检查的环节**。
-- 解法错了断言能抓、实现错了断言能抓，断言自己错了没有任何东西能抓，
-- 所以它必须过人审才能被阶段⑤ 当作依据。
--
-- `animatable=false` 是一个诚实阀门：纯概念题、纯读图题写不出数值断言，
-- 与其编几条永远成立的假断言，不如明说它不适合做成动画。
CREATE TABLE IF NOT EXISTS specs (
  question_id   bigint PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
  spec          jsonb       NOT NULL,
  animatable    boolean     NOT NULL DEFAULT true,
  why_not       text,
  n_invariants  int         NOT NULL DEFAULT 0,
  status        text        NOT NULL DEFAULT 'draft',
  src_sha256    text        NOT NULL,
  model         text,
  created_at    timestamptz NOT NULL DEFAULT now()
);

-- 阶段⑤ 生成场景。
--
-- `passed` 记的是**门禁的裁决**，不是 agent 自己说的 —— 它可能没跑门禁、
-- 跑错了目录、或者看错了末行。这里的值一律由 verify.py 的末行决定。
--
-- 而 passed=true 也只意味着「实现与 spec 一致」，不代表解法正确：
-- spec 写错了门禁照样全绿。所以 specs.status 的人审是这条链的必经关口。
CREATE TABLE IF NOT EXISTS scenes (
  question_id bigint PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
  scene_id    text        NOT NULL,
  rounds      int         NOT NULL DEFAULT 0,
  passed      boolean     NOT NULL DEFAULT false,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS vlm_cache (
  img_sha256 text PRIMARY KEY,
  kind       text,
  payload    jsonb       NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- 老库补列（阶段③b）。放在最后是因为 ALTER 得等对应的 CREATE TABLE 先跑过。
ALTER TABLE questions ADD COLUMN IF NOT EXISTS label        text;
ALTER TABLE solutions ADD COLUMN IF NOT EXISTS short_answer text;

-- 阶段④c 动画选题。和 `animatable` 是**两件事**，不能合并：
--   animatable=false  写不出数值断言，做不了
--   worth=false       做得了，但动画对理解没有实质增量（两个力求合力、平均电动势）
-- ⑤ 一题几分钟到几十分钟，全做等于把时间花在增量最低的题上。
-- worth_why 要落库：页面上「这道题为什么没有动画」得答得出来。
-- 选题结果挂在 questions 上，不在 specs 上。原因是顺序变了：
-- ④c 现在跑在 ④ **之前**（判「值不值得做动画」只要一次调用 28 秒，
-- 而写断言一道 6 分钟——把便宜的筛子排在贵的前面才对）。
-- 那时候 specs 这一行还不存在，挂在它上面写不进去。
ALTER TABLE questions ADD COLUMN IF NOT EXISTS anim_worth boolean;
ALTER TABLE questions ADD COLUMN IF NOT EXISTS anim_why   text;
-- specs 上那两列留着只为兼容老数据，新代码不再写
ALTER TABLE specs ADD COLUMN IF NOT EXISTS worth     boolean;
ALTER TABLE specs ADD COLUMN IF NOT EXISTS worth_why text;

-- ---------------------------------------------------------------- 账号
-- 邮箱验证码登录，**没有密码**。没有密码就没有密码泄露、没有撞库、没有
-- 「忘记密码」那一整套流程；代价是每次新设备登录要收一封信。
-- 对这样一个每份卷子要烧掉几十分钟模型时间的东西来说，这个代价可以接受。
CREATE TABLE IF NOT EXISTS users (
  id            bigserial PRIMARY KEY,
  email         text        NOT NULL UNIQUE,   -- 一律存小写去空格后的规范形式
  created_at    timestamptz NOT NULL DEFAULT now(),
  last_login_at timestamptz
);

-- 登录验证码。存的是 sha256(邮箱 + ':' + 验证码)，不是明文。
-- 6 位数字只有一百万种，**哈希本身挡不住手里有库的人**，连邮箱一起哈希只是
-- 让彩虹表不能一次算好通吃所有账号；真正管用的是有效期、试错上限、一码一用。
-- 一个邮箱同时只有一个有效验证码：重新要码就覆盖上一个，旧的立刻作废。
CREATE TABLE IF NOT EXISTS login_codes (
  email       text PRIMARY KEY,
  code_sha256 text        NOT NULL,
  expires_at  timestamptz NOT NULL,
  -- 试错次数。6 位数字只有一百万种，不限次数的话在有效期内是可以穷举的
  tries       int         NOT NULL DEFAULT 0,
  sent_at     timestamptz NOT NULL DEFAULT now()
);

-- 会话。同样只存 token 的哈希，理由同上。
CREATE TABLE IF NOT EXISTS sessions (
  token_sha256 text PRIMARY KEY,
  user_id      bigint      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at   timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,
  last_seen_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id);

-- 试卷归属。**NULL = 无主**，不是「大家的」：命令行跑的卷子没有登录态，
-- 落库时就是无主的。它们归第一个注册的账号（见 store.create_user），
-- 之后想改用 `store.py claim <邮箱>`，或在 .env 里设 EXAM_OWNER_EMAIL
-- 让命令行那条链直接落到某个账号名下。
--
-- name 仍然全局唯一，没有按人分命名空间：`work/<卷名>/` 是按卷名建目录的，
-- 两个账号传同名卷子会写进同一个构建目录。所以重名在**上传时**就避开
-- （自动加后缀），而不是让两份数据在磁盘上打架。
--
-- 删账号是 **SET NULL 而不是 CASCADE**：一份卷子是几十分钟的模型时间换来的，
-- 删一个账号顺手把它的卷子全删掉，是那种「一条命令下去，重跑三个小时」的
-- 不可逆操作。归属没了就退回无主，重新 claim 就能拿回来。
ALTER TABLE papers ADD COLUMN IF NOT EXISTS owner_id bigint REFERENCES users(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS papers_owner_idx ON papers (owner_id);

-- ---------------------------------------------------------------- 期一：知识点与标准答案
-- kps 用 jsonb 存 [{code, why}] 而不是关联表：范围是单人单卷十几道题，
-- 聚合在应用层做就够。代价是 code 没有外键保护，所以 ③c 写入时要拿
-- 词表校一遍（见 kpmark.keep），挂不上的明说挂不上。
ALTER TABLE questions ADD COLUMN IF NOT EXISTS kps jsonb NOT NULL DEFAULT '[]';
-- 卷子上的标准答案。ref_answer_src 三个值：
--   paper        从题目那份文件里抽出来的
--   answer_file  老师另传的答案文件（期三）
--   none         抽不到。**这一列不许留 NULL** —— 「没抽到」和「还没跑过 ②c」
--                是两件事，页面上要分得出来
ALTER TABLE questions ADD COLUMN IF NOT EXISTS ref_answer     text;
ALTER TABLE questions ADD COLUMN IF NOT EXISTS ref_answer_src text;

-- ---------------------------------------------------------------- 期二：答题卡
-- 一份答题卡 = 一个学生的一次作答。
-- **不建 students 表**：范围定死单人、不做班级，学生就是老师随手填的一个标识。
-- 建了表就要配增删改查和「同一学生的历次考试」，那是另一个功能。
CREATE TABLE IF NOT EXISTS answer_sheets (
  id            bigserial PRIMARY KEY,
  paper_id      bigint NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  owner_id      bigint REFERENCES users(id) ON DELETE SET NULL,
  student_label text,
  n_pages       int NOT NULL DEFAULT 0,
  created_at    timestamptz NOT NULL DEFAULT now(),
  -- 老师改判会 touch 它。诊断过没过期，拿它跟 diagnoses.created_at 比 ——
  -- 跟 papers.assembled_at 判 out.html 旧没旧是同一个套路
  updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sheets_paper_idx ON answer_sheets (paper_id);

CREATE TABLE IF NOT EXISTS sheet_answers (
  id          bigserial PRIMARY KEY,
  sheet_id    bigint NOT NULL REFERENCES answer_sheets(id) ON DELETE CASCADE,
  -- **可空**：认出了题号但卷子里没这道题（串号、学生多写一道）。
  -- 挂不上就是挂不上，页面明说，不许猜一个最近的题号安上去。
  -- 实测这真会发生：答题卡第 13 题印的小问编号是 (1)(2)(4)(5)，参考答案是 (1)(2)(3)(4)。
  --
  -- **ON DELETE SET NULL，不是 CASCADE。** 既然「挂不上」是设计内的正常状态，
  -- 删掉一道题就该是**解绑**、不是把这一行连根删掉 —— 行里装着学生的作答、
  -- 原图切片和老师的改判，那些东西不可再生（参考答案能重读，那张已批改的
  -- 答题卡老师未必还留着，上传的原件跑完就清了）
  question_id bigint REFERENCES questions(id) ON DELETE SET NULL,
  n           int  NOT NULL,
  raw_text    text,        -- 模型认出的最终作答，**原样**，不加工
  norm        text,        -- 归一化后的形式，判定拿它比
  crop_rel    text,        -- 原图切片的 assets.rel_path
  box         jsonb,
  page        int,
  read_conf   text,        -- 模型自称的把握 high/medium/low
  reread      boolean NOT NULL DEFAULT false,
  reread_raw  text,        -- 复读认出来的东西。两次都留着，页面标「复读后改判」

  -- **verdict_by 才是红绿灯** —— 同一个「错」，代码判的和模型判的
  -- 可信度差一个量级，页面必须分得出来
  verdict         text,    -- right | wrong | blank | unsure
  verdict_by      text,    -- code | model
  verdict_why     text,

  -- 老师改判**单独一列，不覆盖系统原判**。留着原判才看得出系统错在哪，
  -- 也才撤得回来。读取一律走 store.sheet_answers 里那一个 COALESCE，
  -- 不让每个调用点各写一份 —— api.ts 那次 401 广播就是这个教训
  teacher_verdict text,

  UNIQUE (sheet_id, n)
);
CREATE INDEX IF NOT EXISTS sheet_answers_sheet_idx ON sheet_answers (sheet_id);

-- ---------------------------------------------------------------- 只有参考答案的卷子
-- pdf          走 ①②③ 的完整试卷
-- answers_only 老师传的是参考答案 + 题目图，不进 ③④⑤⑦
--
-- **stage_of 必须按它分支**：answers_only 的卷子 solutions/specs/scenes 恒为 0，
-- 不分支的话进度带永远转、done 永远是 false。期一加 ③c 那一格踩过一次一样的坑
ALTER TABLE papers ADD COLUMN IF NOT EXISTS source_kind text NOT NULL DEFAULT 'pdf';

-- 参考答案里的解答过程。ref_answer 是最终答案，这一列是过程。
-- 分两列而不是一列：判对错拿前者，「怎么提升」展示后者，混在一起两边都不好用。
-- 实测：参考答案只有大题有详解，选择填空这一列多半是 NULL，那是常态不是缺陷
ALTER TABLE questions ADD COLUMN IF NOT EXISTS ref_solution text;

-- 这个场景是哪套流程产的：
--   agent    模型自己写 figure.html + js（含物理）
--   codegen  物理与读数面板由 pipeline/scenegen.py 生成，模型只写 draw.js
-- 两套并存期间出了问题要分得清是谁的锅
ALTER TABLE scenes ADD COLUMN IF NOT EXISTS gen text NOT NULL DEFAULT 'agent';

-- ③c **判过**这道题的时间。和 kps 是两件事：kps 空只说明「没挂上标签」，
-- 说不出到底是「还没判过」还是「判过了但判不出来」。
--
-- 少了这一列，`stage_of` 只能拿「挂上几道」当分子 —— 而参考答案那条链上，
-- 只有一个字母答案（`D`/`BC`）的题**永远挂不上**，于是那份卷子永远到不了
-- 「已完成」，页面上永远写着「已停止」。用户两次问「为啥停止了」。
--
-- 这正是 stage_of 注释里记过的同一个教训：「⑤ 的分子必须是『试过几道』
-- 而不是『绿灯几道』—— 有一道怎么都过不了门禁的话，按绿灯数算就永远
-- 差一个，永远显示在跑」。
ALTER TABLE questions ADD COLUMN IF NOT EXISTS kps_at timestamptz;

-- 回填：③c 已经跑过的卷子，整卷标成判过。
--
-- **不回填的话，已经跑完的卷子会集体退回「未完成」** —— STATUS 的「踩过的坑」
-- 第 1 条就是这个（`stage_of` 加一格必须同时改分支/回填，踩过两次）。
--
-- 判据是「这份卷子里有任何一道挂上了知识点」：③c 是整卷一次调用，有一道挂上
-- 就说明它在这份卷子上跑过，那么同一份里没挂上的那些也是判过的。一道都没挂上
-- 的卷子留空 —— 那种情况分不出「跑过但全军覆没」和「压根没跑」，宁可当成没跑
-- （代价是多跑一次 ③c，几秒钟；反过来会把没跑过的说成跑完了）。
UPDATE questions q SET kps_at = now()
 WHERE q.kps_at IS NULL
   AND EXISTS (SELECT 1 FROM questions x
                WHERE x.paper_id = q.paper_id AND jsonb_array_length(x.kps) > 0);

-- ---------------------------------------------------------------- 老库补：解绑而不是删行
-- `sheet_answers.question_id` 的外键从 ON DELETE CASCADE 改成 ON DELETE SET NULL。
-- 上面 CREATE TABLE 里已经是新的了，但 `IF NOT EXISTS` 对已经存在的表不生效，
-- 老库还挂着旧约束，所以这里显式换一次。
--
-- 为什么改：「挂不上题」是这个设计里的**正常状态**，不是异常 —— 实测答题卡
-- 第 13 题印的小问编号是 (1)(2)(4)(5)，参考答案是 (1)(2)(3)(4)。既然挂不上正常，
-- 删掉一道题就该是解绑；CASCADE 会把整行连根删掉，而行里装着学生的作答、
-- 原图切片和老师的改判。那三样**不可再生**：参考答案能重读，那张已批改的
-- 答题卡老师未必还留着，上传的原件跑完就从 _uploads 清了。
--
-- 触发路径是现成的：refread.py 读完参考答案时，日志里直接教人跑
-- `store.drop_questions` 去收拾读错的题号。
ALTER TABLE sheet_answers DROP CONSTRAINT IF EXISTS sheet_answers_question_id_fkey;
ALTER TABLE sheet_answers ADD CONSTRAINT sheet_answers_question_id_fkey
  FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE SET NULL;

-- ---------------------------------------------------------------- 步二：分数
-- 卷子上**印着**的分数。系统一分不算，只是把它转写下来（见设计文档「非目标」）。
--
-- **numeric 不是 int**：实测有「7.5分(满分12分)」、总分 58.5。
-- 存整数会静默截断成 7 和 58，而薄弱知识点是按丢分率排的 —— 分母错了整个榜单都错。
ALTER TABLE sheet_answers ADD COLUMN IF NOT EXISTS score_got   numeric;
ALTER TABLE sheet_answers ADD COLUMN IF NOT EXISTS score_full  numeric;
-- 模型读到的批改符号原文。判定用的是归一化后的 verdict，这一列留原文好对账
ALTER TABLE sheet_answers ADD COLUMN IF NOT EXISTS mark_raw    text;
-- 老师用红笔**写在旁边**的正确答案（实测题 6 写了 BC、题 8 写了 AC）。
-- 白捡的第三份对照：它跟参考答案对不上，说明 Ⓐ 那一栏抽错了。只报，不改数据
ALTER TABLE sheet_answers ADD COLUMN IF NOT EXISTS teacher_red text;

-- Ⓑb **判过这一行**的时间。和 score_got 是两件事：score_got 为空只说明
-- 「这一行没有分数」，说不出到底是「还没跑过 Ⓑb」还是「跑过了，卷子上就没印」。
-- 与 questions.kps_at 完全同构 —— 那一列不加的时候，答案卷永远到不了「已完成」，
-- 用户两次问「为啥停止了」。
ALTER TABLE sheet_answers ADD COLUMN IF NOT EXISTS scored_at   timestamptz;

-- 卷子上印的总分（实测 58.5）。Ⓑc 单独一次调用、单独一块裁图读它，
-- 用来对 Σscore_got。**必须和逐题得分不同源**，同源的话这条校验就是自证。
ALTER TABLE answer_sheets ADD COLUMN IF NOT EXISTS total_score numeric;

-- 回填：已经有分数的行，整卡标成判过。
--
-- **不回填的话已经跑完的卡会退回「没判过」** —— 和 kps_at 那次一样的道理
-- （STATUS「踩过的坑」第 1 条：加一格必须同时改分支和回填，踩过两次）。
--
-- 判据是「这份答题卡里有任何一行有分数」：Ⓑb 是整卡跑的，有一行有分就说明它在
-- 这份卡上跑过，那么同一份里没分的那些也是判过的（卷子上就没印）。一行分数都
-- 没有的卡留空 —— 那种情况分不出「跑过但全没印分」和「压根没跑」，宁可当成没跑
-- （代价是多跑一次；反过来会把没跑过的说成跑完了）。
UPDATE sheet_answers a SET scored_at = now()
 WHERE a.scored_at IS NULL
   AND EXISTS (SELECT 1 FROM sheet_answers x
                WHERE x.sheet_id = a.sheet_id AND x.score_got IS NOT NULL);

-- 这份答题卡上，Ⓑ 的每一次子调用跑成什么样：
--   [{"page":1,"pass":"Ⓑa","ok":true,"seconds":235,"rows":18,"err":null}, ...]
-- 外加这一次的对总分结果、两遍之间的冲突、题号对不上的整题告警。
--
-- **不落这一行的话，「Ⓑb 第 2 页整遍失败」和「这几道题本来就读不出」
-- 在库里和页面上完全同形** —— 前者该让人重传，后者该让人去看原图，
-- 而页面分不出来就只能都说成「这道题没读出来」。
ALTER TABLE answer_sheets ADD COLUMN IF NOT EXISTS reads jsonb NOT NULL DEFAULT '{}';
