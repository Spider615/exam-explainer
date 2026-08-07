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

-- 一道题历次做出来的**能用的**场景。scenes 那张表只记「现在用哪个」，
-- 一行一题；重跑一次就把它盖掉，于是上一个版本在库里再也找不回来 ——
-- 而磁盘上 `runs/<id>/` 明明还在。实测重跑会变差（标签被甩离对象、
-- 几何重画得更糟），那时候人要的是「把原来那个换回来」，不是再赌一次。
--
-- 只记通过门禁的：没过门禁的场景不是一个可选项，列出来只会让人误点。
-- append-only，UNIQUE 挡住同一个 scene_id 重复入账。
CREATE TABLE IF NOT EXISTS scene_versions (
  id          bigserial PRIMARY KEY,
  question_id bigint NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  scene_id    text   NOT NULL,
  rounds      int    NOT NULL DEFAULT 0,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (question_id, scene_id)
);
CREATE INDEX IF NOT EXISTS scene_versions_q_idx ON scene_versions (question_id);

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
