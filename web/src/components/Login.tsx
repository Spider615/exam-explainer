import { useEffect, useRef, useState } from 'react'
import { requestCode, verifyCode } from '../api'

/**
 * 登录。邮箱 → 验证码 → 进去，**注册和登录是同一条路**：第一次用某个邮箱
 * 验证成功时账号就建好了，没有单独的注册表单要填。
 *
 * 版式上是**整页接管**，不套在试卷库那层壳里 —— 那层壳的「回到试卷库」在
 * 没登录时点了没有意义。左边一栏说清楚这是个什么东西，右边一栏是唯一的动作。
 * 窄屏下左栏收成一行标题，不跟表单抢空间。
 *
 * 两个地方是有意为之：
 *
 * · 后端对「这个邮箱注册过没有」一律给同一个回答，所以这里的文案也不能分出
 *   「欢迎回来 / 新账号」—— 那等于把后端捂住的信息从前端漏出去。
 * · 没配 SMTP 时后端会说「验证码打在服务端日志里」，这句话原样显示出来。
 *   不然人对着一个永远收不到信的输入框，只会以为是自己邮箱填错了。
 */

/**
 * 两条链各自摊开。
 *
 * 以前这里只列了解析试卷那一条 —— 而答题卡诊断早就是并列的第二个工作流。
 * 登录页是唯一一屏「还没进来的人」看得到的东西，少说一条等于这个功能不存在。
 */
const CHAINS: [string, string[]][] = [
  ['解析试卷', ['① 摄入', '② 切分', '③ 解题', '④ 断言', '⑤ 场景', '⑦ 呈现']],
  ['答题卡诊断', ['Ⓐ 读参考答案', 'Ⓢ 抠图', 'Ⓑ 读批改', 'Ⓒ 判定', 'Ⓓ 建议']],
]

export default function Login({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [step, setStep] = useState<'email' | 'code'>('email')
  const [hint, setHint] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [left, setLeft] = useState(0)          // 重发倒计时；后端是 60 秒冷却
  const codeBox = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (left <= 0) return
    const t = window.setTimeout(() => setLeft(left - 1), 1000)
    return () => window.clearTimeout(t)
  }, [left])

  const ask = async () => {
    setErr(null); setBusy(true)
    try {
      const r = await requestCode(email.trim())
      setStep('code'); setCode(''); setLeft(60); setHint(r.hint ?? null)
      window.setTimeout(() => codeBox.current?.focus(), 40)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const go = async (value = code) => {
    setErr(null); setBusy(true)
    try {
      await verifyCode(email.trim(), value.trim())
      onDone()
    } catch (e) {
      setErr((e as Error).message)
      setCode('')
      codeBox.current?.focus()
    } finally {
      setBusy(false)
    }
  }

  /** 填满 6 位就自己提交 —— 输完还要再点一下按钮是白让人多做一步 */
  const onCode = (raw: string) => {
    const v = raw.replace(/\D/g, '').slice(0, 6)
    setCode(v)
    if (v.length === 6 && !busy) go(v)
  }

  const back = () => { setStep('email'); setCode(''); setErr(null); setHint(null) }

  return (
    <div className="auth">
      <div className="auth-grid">
        <section className="auth-say">
          <div className="auth-brand">析题</div>
          <h1>把一份卷子<br />拆到能讲的程度</h1>
          <p>
            上传物理卷 PDF，自动跑完切题、解题、写物理断言、生成动画场景；
            上传参考答案和学生的答题卡，逐题给出对错、丢分和下一步该练什么。
          </p>
          {CHAINS.map(([title, stages]) => (
            <div className="auth-chain-g" key={title}>
              <h2>{title}</h2>
              <ol className="auth-chain">
                {stages.map((s) => <li key={s}>{s}</li>)}
              </ol>
            </div>
          ))}
          <p className="auth-fine">
            动画的准入靠的是计算，不是人审 —— 满足不了它自己的断言就不出动画。
            答题卡上的对错来自老师的批改，不是模型自己判的。
          </p>
        </section>

        <section className="auth-card">
          <header className="auth-hd">
            <h2>{step === 'email' ? '登录' : '输入验证码'}</h2>
            {step === 'email' ? (
              <p>邮箱收一个验证码就行，没有密码。第一次登录即注册。</p>
            ) : (
              <p>
                已发往 <b>{email.trim()}</b>
                <button type="button" className="auth-link" onClick={back}>改一下</button>
              </p>
            )}
          </header>

          {step === 'email' ? (
            <label className="auth-f">
              <span>邮箱</span>
              <input type="email" value={email} autoFocus autoComplete="email"
                     placeholder="you@example.com" spellCheck={false}
                     onChange={(e) => setEmail(e.target.value)}
                     onKeyDown={(e) => { if (e.key === 'Enter' && email.includes('@')) ask() }} />
            </label>
          ) : (
            <label className="auth-f">
              <span>6 位验证码</span>
              <input ref={codeBox} className="auth-code" value={code} inputMode="numeric"
                     autoComplete="one-time-code" placeholder="••••••" maxLength={6}
                     onChange={(e) => onCode(e.target.value)}
                     onKeyDown={(e) => { if (e.key === 'Enter' && code.length === 6) go() }} />
            </label>
          )}

          {/* 提示与报错固定占一格，出现时不会把按钮顶下去 */}
          <div className="auth-msg" aria-live="polite">
            {err ? <span className="auth-err">{err}</span>
              : hint ? <span className="auth-hint">{hint}</span>
                : null}
          </div>

          {step === 'email' ? (
            <button className="auth-go" disabled={busy || !email.includes('@')} onClick={ask}>
              {busy ? '发送中…' : '发送验证码'}
            </button>
          ) : (
            <>
              <button className="auth-go" disabled={busy || code.length < 6} onClick={() => go()}>
                {busy ? '核验中…' : '登录'}
              </button>
              <button type="button" className="auth-resend" disabled={busy || left > 0}
                      onClick={ask}>
                {left > 0 ? `没收到？${left} 秒后可重发` : '重新发送验证码'}
              </button>
            </>
          )}

          <footer className="auth-ft">
            每个账号只看得到自己传的试卷。跑完一份卷子要几十分钟的模型时间，
            所以上传在登录之后。
            <span className="auth-tech">exam-explainer</span>
          </footer>
        </section>
      </div>
    </div>
  )
}
