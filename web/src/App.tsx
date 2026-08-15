import { useCallback, useEffect, useRef, useState } from 'react'
import { deletePapers, getMe, getProgress, listPapers, logout, Unauthorized } from './api'
import AppShell from './components/AppShell'
import type { Mode } from './components/AppShell'
import Login from './components/Login'
import PageIntro from './components/PageIntro'
import PaperList from './components/PaperList'
import PaperView from './components/PaperView'
import SheetLanding from './components/SheetLanding'
import SheetList from './components/SheetList'
import SheetUpload from './components/SheetUpload'
import SheetView from './components/SheetView'
import SheetDetail from './components/SheetDetail'
import Upload, { clearSavedJob } from './components/Upload'
import type { PaperSummary } from './types'

interface Route {
  mode: Mode
  open: string | null
  sheet: number | null
  /** 明确要看卷子页（`#/sheet/<卷名>/paper`），不要被解析成诊断页 */
  paperPage: boolean
  legacy: boolean
}

/**
 * 从地址读「哪个模式、开着哪份卷子」。
 *
 * `#/paper/<卷名>` `#/sheet/<卷名>`；只有模式时不开卷子。
 * 答题卡模式多两层：
 *
 * · `#/sheet/<卷名>/s<卡号>` 打开某一份学生的答题卡。卡号带 `s` 前缀，
 *   免得和卷名里可能出现的数字段混起来。
 * · `#/sheet/<卷名>/paper` 打开**卷子页**（每题的标准答案、知识点、Ⓐ 的进度、
 *   再传一份的入口）。
 *
 * **`#/sheet/<卷名>` 的含义是「给我看这份卷子的诊断结果」**，不是卷子页 ——
 * 库里点卷名、上传卡上那个「去看这份卷子 →」、书签、刷新、老地址都落在它上面，
 * 由 `SheetLanding` 解析成某一份卡。卷子页因此需要自己的地址：**没有它的话，
 * 诊断页那个「← 回到这份卷子」会被解析器立刻弹回来，按钮变成死的**，
 * 而「再传一个学生」的入口正在卷子页上。
 *
 * **老地址 `#/p/<卷名>` 要继续能开** —— 直接失效是不可接受的，那些链接可能
 * 已经发出去了。命中时先当解析试卷开着，拿到整卷数据知道它真正的模式后
 * 再把地址换过去。
 */
function readHash(): Route {
  const h = window.location.hash
  let m = /^#\/sheet\/(.+)\/s(\d+)$/.exec(h)
  if (m) return { mode: 'sheet', open: decodeURIComponent(m[1]),
                  sheet: Number(m[2]), paperPage: false, legacy: false }
  // 卷名是 encodeURIComponent 编过的，里面不会有裸斜杠，所以这条不会误伤
  // 一份名字里带 “/paper” 的卷子
  m = /^#\/sheet\/(.+)\/paper$/.exec(h)
  if (m) return { mode: 'sheet', open: decodeURIComponent(m[1]),
                  sheet: null, paperPage: true, legacy: false }
  m = /^#\/(paper|sheet)(?:\/(.+))?$/.exec(h)
  if (m) return { mode: m[1] as Mode, open: m[2] ? decodeURIComponent(m[2]) : null,
                  sheet: null, paperPage: false, legacy: false }
  m = /^#\/p\/(.+)$/.exec(h)
  if (m) return { mode: 'paper', open: decodeURIComponent(m[1]), sheet: null,
                  paperPage: false, legacy: true }
  return { mode: 'paper', open: null, sheet: null, paperPage: false, legacy: false }
}

/**
 * 任务库的小标题，右边挂一句**可解释的**统计。
 *
 * 「12 份 · 2 份在跑」是数得出来的；「本周处理 37 页」不是 —— 后者要么现编，
 * 要么得为它加一个端点。这一屏不需要经营看板，需要的是「有没有还在跑的」。
 */
function LibHead({ title, rows }: { title: string; rows: PaperSummary[] }) {
  const running = rows.filter((r) => r.progress?.busy).length
  return (
    <div className="sec-hd">
      <h2>{title}</h2>
      {rows.length > 0 && (
        <span>{rows.length} 份{running > 0 && <> · <b>{running} 份在跑</b></>}</span>
      )}
    </div>
  )
}

export default function App() {
  const [rows, setRows] = useState<PaperSummary[]>([])
  const [route, setRoute] = useState(readHash)
  const { mode, open, sheet, paperPage } = route

  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  /** 列表拉不下来。**和「一份都没有」是两句话** */
  const [listErr, setListErr] = useState<string | null>(null)

  // `go` 和 hashchange 都要知道「换模式前是哪个模式」，但只有 `go` 能在
  // 同一次调用里同步拿到旧值——hashchange 触发时 `mode` 这个闭包变量可能是
  // 装载时那份旧的（effect 依赖是 []）。用一个跟着 `mode` 走的 ref，两条路径
  // 读同一份「当下真正的模式」，不用各自猜
  const modeRef = useRef(mode)
  useEffect(() => { modeRef.current = mode }, [mode])

  /**
   * 换模式要把上一屏的残留清掉。 不清的话，在解析试卷删完一份卷子再切到
   * 答题卡诊断，那句「已删除 1 份」会跟着挂在答题卡库上面 —— 而那一屏什么都
   * 没删过。`rows` 同理：`refresh` 是异步的，不清就有至少一帧拿上一个模式的
   * 卷子去渲染这一屏的表格（PDF 卷子出现在答题卡库里，带着两列空的「带解答 /
   * 挂知识点」）。「互相看不见对方的卷子」这句话得是真的，不能只写在注释里。
   *
   * **两条路径共用这一个函数，不许各写一份。** 以前这段清理只写在 `go` 里，
   * 只覆盖点击路径——从答题卡按浏览器后退回解析试卷，hashchange 处理器
   * 直接 `setRoute(readHash())`，什么都不清，会有至少一帧用答题卡的
   * `rows` 去渲染解析试卷的表格。「互相看不见」那句注释于是只写在注释里，
   * 这条路径上从没兑现过。
   *
   * 清空写在这里而不是 `setRoute` 的更新函数里：更新函数必须是纯的，
   * StrictMode 下会跑两遍，把副作用塞进去等于让它执行两次。
   */
  const clearModeResidue = useCallback(() => { setRows([]); setNote(null) }, [])

  const go = useCallback((next: Mode, name: string | null, replace = false) => {
    const h = name ? `/${next}/${encodeURIComponent(name)}` : `/${next}`
    if (replace) {
      window.history.replaceState(
        null, '', `${window.location.pathname}${window.location.search}#${h}`)
    } else {
      window.location.hash = h
    }
    if (next !== modeRef.current) clearModeResidue()
    setRoute({ mode: next, open: name, sheet: null, paperPage: false, legacy: false })
  }, [clearModeResidue])

  /**
   * 打开某一份答题卡。地址要跟着变，刷新和分享才回得到同一屏。
   *
   * `replace=true` 给解析器用（`#/sheet/<卷名>` → 某一份卡）：**那一跳不该
   * 在历史里留一格** —— 留了的话，老师按一次后退回到中转地址，又被解析走，
   * 后退键在两页之间来回蹦。`replaceState` 不触发 hashchange，而这里本来
   * 就自己 `setRoute`，所以是安全的。
   */
  const goSheet = useCallback((name: string, id: number | null, replace = false) => {
    const h = id
      ? `/sheet/${encodeURIComponent(name)}/s${id}`
      : `/sheet/${encodeURIComponent(name)}`
    if (replace) {
      window.history.replaceState(
        null, '', `${window.location.pathname}${window.location.search}#${h}`)
    } else {
      window.location.hash = h
    }
    setRoute({ mode: 'sheet', open: name, sheet: id, paperPage: false, legacy: false })
  }, [])

  /**
   * 打开**卷子页**（标准答案、知识点、Ⓐ 的进度、再传一份的入口）。
   *
   * 它有自己的地址，所以不会被 `SheetLanding` 解析走 —— 诊断页那个
   * 「← 回到这份卷子」按下去就真的停在卷子页上。
   */
  const goSheetPaper = useCallback((name: string, replace = false) => {
    const h = `/sheet/${encodeURIComponent(name)}/paper`
    if (replace) {
      window.history.replaceState(
        null, '', `${window.location.pathname}${window.location.search}#${h}`)
    } else {
      window.location.hash = h
    }
    setRoute({ mode: 'sheet', open: name, sheet: null, paperPage: true, legacy: false })
  }, [])

  /**
   * 登录态。三个值不能合并成一个布尔：`undefined` 是「还没问过后端」。
   * 把它当成「没登录」的话，每次刷新页面都会先闪一下登录框再跳回列表。
   */
  const [me, setMe] = useState<string | null | undefined>(undefined)

  const checkMe = useCallback(() => {
    getMe().then((u) => setMe(u.email)).catch(() => setMe(null))
  }, [])
  useEffect(checkMe, [checkMe])

  /**
   * 老地址 `#/p/<卷名>` 落地后，把它换到这份卷子真正属于的那个模式去。
   *
   * **不换的话，一份答案卷会用解析试卷那套页面打开** —— 答案速览、动画开关、
   * 「解题步骤与动画均由 AI 生成」的页脚，全是错的话。那正是这轮要消灭的
   * 「两套话术缠在一起」。
   *
   * 问的是 `/progress` 而不是整卷：它是那个轻量端点（只有计数），而且已经带着
   * `mode.code` —— 模式的判定留在后端，前端不再自己从 sourceKind 映射一遍。
   * 问不到（卷子不在了、会话过期）就留在解析试卷模式，让详情页自己把
   * 「打不开」说出来 —— 这里不该替它编一句话。
   *
   * **换址用 replace。** 用 push 的话老地址上的后退键是死的：退回 `#/p/<名>`
   * → 这个 effect 又判一次 → 又把人推到前面去。答题卡那条链上还会再多一层
   * （`SheetLanding` 接着解析），一次后退白跑两个请求。
   */
  useEffect(() => {
    if (!route.legacy || !route.open || !me) return
    let alive = true
    getProgress(route.open)
      .then((p) => {
        if (!alive) return
        const m = p.mode?.code === 'sheet' ? 'sheet' : 'paper'
        go(m, route.open, true)
      })
      .catch(() => { if (alive) setRoute((r) => ({ ...r, legacy: false })) })
    return () => { alive = false }
  }, [route.legacy, route.open, me, go])

  /**
   * 浏览器前进/后退也要走上面那段模式清理，不能只在 `go()` 里做一遍。
   *
   * **认不出来的 hash 不许改路由。** `readHash` 的兜底是「解析试卷库」，
   * 于是任何一个别处写进来的锚点（`#q13` 那种）都会把人从答题卡里踢出去 ——
   * 页面上的锚点已经改成 `scrollIntoView` 了，但浏览器和第三方扩展照样能
   * 往地址里写东西。**兜底只该用在首次落地上**，不该用在「已经在某一屏」时。
   */
  useEffect(() => {
    const h = () => {
      const raw = window.location.hash
      if (raw && !raw.startsWith('#/')) return    // 不是我们的路由，当没看见
      const next = readHash()
      if (next.mode !== modeRef.current) clearModeResidue()
      setRoute(next)
    }
    window.addEventListener('hashchange', h)
    return () => window.removeEventListener('hashchange', h)
  }, [clearModeResidue])

  // 任何一次请求撞上 401 都退回登录页（api.ts 里广播）。会话是 30 天，
  // 但它可能在一次长任务跑到一半时过期 —— 那时候页面正开着试卷页
  useEffect(() => {
    // 句柄跟着会话作废。过期和主动登出是同一件事 —— 不清的话，下一个在这台
    // 机器上登进来的人会拿着别人的任务 id 去问，只能得到一条 404 和一句
    // 关于他从没传过的卷子的说明
    const h = () => { clearSavedJob(); setMe(null) }
    window.addEventListener('auth:expired', h)
    return () => window.removeEventListener('auth:expired', h)
  }, [])

  const refresh = useCallback(() => {
    if (!me) return
    listPapers(mode).then((r) => { setRows(r); setListErr(null) }).catch((e) => {
      // 会话过期时不能只是清空列表——那看起来像「一份卷子都没有」。
      // 退回登录页，把「你得重新登录」这件事说出来
      if (e instanceof Unauthorized) { setMe(null); setRows([]); return }
      // **其余的失败不许清空。** 清了的话，一个手上有三十份卷子的老师会在后端
      // 重启的那几十秒里被告知「还没有传过参考答案」——而每一条降级路径
      // （打不开的诊断页、打不开的卷子页）的出口都是这一屏
      setListErr(e instanceof Error ? e.message : String(e))
    })
  }, [me, mode])
  useEffect(refresh, [refresh])

  /**
   * 列表每 8 秒自己刷一次。后台任务跑着的时候，退回试卷库也能看到它在推进——
   * 不刷新就只能看到一份「上次打开时」的快照。
   *
   * **回到库页要立刻拉一次，不能等那 8 秒。** 从卷子页传完一份新答题卡再退
   * 回来，那一行的「答题卡 N 份」和进度都还是进去之前的快照 —— 而老师刚做完
   * 的事恰恰就是让这个数变了。
   *
   * （「点进去落到哪一份卡」不靠这份列表：那一跳由 `SheetLanding` 现问一次
   * 端点，判据只有一处。列表旧几秒不会把人送进上一个学生的诊断页。）
   */
  useEffect(() => {
    if (open || !me) return              // 详情页有自己的轮询，别重复打
    refresh()
    const t = window.setInterval(refresh, 8000)
    return () => window.clearInterval(t)
  }, [open, me, refresh])

  const remove = useCallback((names: string[]) => {
    setBusy(true)
    setNote(null)
    deletePapers(names)
      .then((r) => {
        // 删掉的正好是当前打开的那份，就退回列表——否则详情页会 404
        if (open && r.deleted.includes(open)) go(mode, null)
        const bits = [`已删除 ${r.deleted.length} 份`]
        if (r.missing.length) bits.push(`${r.missing.length} 份本来就不在`)
        if (r.objects) bits.push(`清理 ${r.objects} 个对象`)
        setNote(bits.join('，'))
        refresh()
      })
      .catch((e) => setNote('删除失败：' + e.message))
      .finally(() => setBusy(false))
  }, [open, mode, refresh, go])

  const signOut = useCallback(() => {
    // 上传任务的句柄也要清 —— 它是上一个账号的，留着只会让下一个人看到一条 404
    clearSavedJob()
    logout().finally(() => { setMe(null); setRows([]); go(mode, null) })
  }, [mode, go])

  if (me === undefined) return <div className="wrap"><div className="empty">载入中…</div></div>
  // 登录页整页接管：没登录时页面上只该有一件事可做，套上「回到试卷库」那层
  // 壳只会给出一个点了没用的入口
  if (me === null) return <Login onDone={checkMe} />

  return (
    // 试卷页多一栏目录，960 放不下：正文会被挤到 750 出头，题干读起来就窄了
    <AppShell
      mode={mode} onMode={(m) => go(m, null)}
      me={me} onSignOut={signOut} onHome={() => go(mode, null)}
      wide={!!open}
      crumb={open ? {
        back: `回到${mode === 'sheet' ? '答题卡库' : '试卷库'}`,
        onBack: () => go(mode, null),
        here: open,
      } : null}
    >
      {open ? (
        mode === 'sheet' ? (
          sheet != null
            /* 「← 回到这份卷子」用 **replace**。它画的是 `←`、指向上一级，
               老师读它就是后退 —— 而 push 的话历史会长成
               `[库, 卷子页, 张三, 卷子页, 李四, 卷子页]`：刚主动离开李四，
               按一下浏览器后退，李四又回来了；看三个学生要按六次后退才回得到库。
               replace 让这条链收敛到 `[库, 卷子页]`。代价是刚看过的那份卡从
               历史里没了 —— 但它就列在卷子页上，一点就回去，没有东西不可达 */
            ? <SheetDetail id={sheet} paper={open}
                           onBack={() => goSheetPaper(open, true)}
                           onOpenSheet={(id) => goSheet(open, id)} />
            /* `#/sheet/<卷名>/paper` 是「我就要看卷子页」；
               光秃秃的 `#/sheet/<卷名>` 是「给我看这份卷子的诊断结果」，
               交给解析器换到某一份卡上（换址用 replace，不留历史格） */
            : paperPage
              ? <SheetView name={open} onOpenSheet={(id) => goSheet(open, id)} />
              /* `key` 不能省：换一份卷子（改地址栏、点第二个书签）走的是同
                 文档 hash 跳转，React 会**复用同一个实例**只换 name ——
                 于是上一份卷子「没有诊断结果」的结论会先把新卷子的卷子页画出来
                 （还顺带触发那个一两兆的整卷请求），闪一下再跳走。
                 而这一屏存在的全部意义就是不让人看见那一闪 */
              : <SheetLanding key={open} name={open}
                              onLand={(id) => goSheet(open, id, true)}
                              onNoLanding={() => goSheetPaper(open, true)}
                              onOpenPaper={() => goSheetPaper(open)} />
        ) : <PaperView name={open} />
      ) : mode === 'sheet' ? (
        <div className="rise">
          <PageIntro
            title="答题卡诊断"
            lede="传参考答案和学生已经批改过的答题卡，逐题给出对错、丢分，
                  以及这个知识点下一步该练什么。" />
          <SheetUpload onDone={(n, o) => { refresh(); if (o) go('sheet', n) }}
                       onOpenSheet={(n, id) => { refresh(); goSheet(n, id) }} />
          <LibHead title="答题卡库" rows={rows} />
          {note && <div className="toast">{note}</div>}
          {/* 列表拉不下来时**保留上一份**，只在上面加一条 ——
              清空的话页面会说「还没有传过」，那是撒谎 */}
          {listErr && (
            <div className="banner bad">
              <b>列表没刷新成</b>　{listErr}
              　下面显示的是上一次问到的，可能不是最新的。
            </div>
          )}
          {/* 点卷名**直接到诊断结果页**。这里只管把地址改成
              `#/sheet/<卷名>`（含义就是「给我看这份卷子的诊断结果」），
              该落到哪一份交给 `SheetLanding` —— 它手上有列表这份数据，
              知道卡号时那一跳是同步的、一次请求都不发。
              **判据只写一处**：列表这一行可能是几秒前的，而解析器会去问最新的 */}
          <SheetList rows={rows}
                     onOpen={(r) => go('sheet', r.name)}
                     onOpenPaper={goSheetPaper}
                     onDelete={remove} busy={busy} />
        </div>
      ) : (
        <div className="rise">
          <PageIntro
            title="解析试卷"
            lede="上传一份物理卷 PDF，自动跑完切题、解题、写物理断言、生成动画，
                  得到一份能直接拿去讲的卷子。" />
          <Upload onDone={(n, o) => { refresh(); if (o) go('paper', n) }} />
          <LibHead title="试卷库" rows={rows} />
          {note && <div className="toast">{note}</div>}
          {/* 列表拉不下来时**保留上一份**，只在上面加一条 ——
              清空的话页面会说「还没有传过」，那是撒谎 */}
          {listErr && (
            <div className="banner bad">
              <b>列表没刷新成</b>　{listErr}
              　下面显示的是上一次问到的，可能不是最新的。
            </div>
          )}
          <PaperList rows={rows} onOpen={(n) => go('paper', n)}
                     onDelete={remove} busy={busy} />
        </div>
      )}
    </AppShell>
  )
}
