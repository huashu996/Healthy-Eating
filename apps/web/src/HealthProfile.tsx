import { useEffect, useRef, useState } from 'react';
import { Camera, Check, LoaderCircle, UserRound, X } from 'lucide-react';
import { api } from './lib';
import type { Row } from './lib';
import type { PageProps } from './App';
import { IconButton } from './components';
import { usePrivateAnalysis } from './PrivateAnalysis';
import { foodGroups, likeDraft, likeRule } from './dietDisplay';

const fields = [
  ['年龄', '岁', 'number'], ['生理性别', '', '男|女'], ['身高', 'cm', 'number'], ['体重', 'kg', 'number'], ['体脂率', '%', 'number'],
  ['活动量', '', 'textarea'], ['忌口', '', 'text'], ['特殊健康情况', '', 'text'],
];

export function HealthProfile(p: PageProps) {
  const facts: Row[] = p.data['diet/body-metrics']?.items || [], likes: Row | undefined = p.data['diet/preferences']?.items?.find((r: Row) => r.data.kind === 'like');
  const overview = p.data['diet/overview'] || {}, uploads: Row[] = overview.health_uploads || [], reports: any[] = overview.health_reports || [];
  const [open, setOpen] = useState(false), [values, setValues] = useState<Record<string, any>>({}), [busy, setBusy] = useState(false), [error, setError] = useState(''), [expanded, setExpanded] = useState(false);
  const [observedAt, setObservedAt] = useState(''), [reportSource, setReportSource] = useState('');
  const [reportKeys, setReportKeys] = useState<string[]>([]);
  const dialog = useRef<HTMLDialogElement>(null), file = useRef<HTMLInputElement>(null), analysis = usePrivateAnalysis(p.refresh);
  const draftPending = useRef(false);
  const initialValues = useRef<Record<string, any>>({});
  useEffect(() => { if (open) dialog.current?.showModal(); }, [open]);
  function show() {
    const latest: Record<string, any> = {};
    for (const f of facts) if (!(f.data.key in latest)) latest[f.data.key] = f.data.value;
    if (!draftPending.current) { initialValues.current = { ...latest, ...overview.current_metrics }; setValues({ ...initialValues.current, 目标: ['增肌', '减脂', '保持现状'].includes(String(initialValues.current['目标'])) ? initialValues.current['目标'] : overview.target?.goal?.direction || '', food_likes: likeDraft(likes?.data) }); setObservedAt(overview.today?.date || ''); setReportSource(''); setReportKeys([]); }
    setError(''); setExpanded(false); setOpen(true);
  }
  async function upload(chosen?: File) {
    if (!chosen) return; setBusy(true); setError('');
    try {
      const form = new FormData(); form.append('file', chosen); form.append('module', 'diet');
      const asset = await api('assets', 'POST', form);
      const row = await api('diet/uploads', 'POST', { data: { title: chosen.name.slice(0, 200), assets: [asset.id] } });
      await analyze(row); p.refresh();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); if (file.current) file.current.value = ''; }
  }
  async function analyze(row: Row) {
    draftPending.current = true;
    await analysis.prepare('diet', 'extract_health', { record_id: row.id, context_refs: [{ id: row.id, version: row.version }] }, '提取体测资料');
    setOpen(false);
  }
  async function save() {
    setBusy(true); setError('');
    try {
      const changedFacts = [...fields, ['目标', '', 'text']].some(([key]) => String(initialValues.current[key] ?? '') !== String(values[key] ?? ''));
      if ((changedFacts || reportKeys.length > 0) && (!observedAt || observedAt > overview.today?.date)) throw new Error('请填写实际资料/测量日期；旧报告不能默认记为今天。');
      for (const [key, unit] of [...fields, ['目标', '', 'text']]) {
        // Keep dated report imports as separate facts so an older report cannot erase a newer measurement.
        const imported = reportKeys.includes(key);
        const old = imported ? undefined : facts.find(f => f.data.key === key), value = values[key] ?? '';
        if (!imported && String(initialValues.current[key] ?? '') === String(value)) continue;
        await api('profile/facts' + (old ? '/' + old.id : ''), old ? 'PATCH' : 'POST', { version: old?.version, data: { category: 'health', key, value, unit, source: imported ? `体测报告：${reportSource}；用户核对确认` : '用户核对确认', observed_at: observedAt, sensitivity: 'sensitive' } });
      }
      const food_likes = values.food_likes || likeDraft(), rule = likeRule(food_likes);
      if (rule !== (likes?.data.rule || '') || JSON.stringify(food_likes) !== JSON.stringify(likes?.data.food_likes)) {
        if (rule) await api('diet/preferences' + (likes ? '/' + likes.id : ''), likes ? 'PATCH' : 'POST', { version: likes?.version, data: { rule, kind: 'like', confirmed: true, food_likes } });
        else if (likes) await api(`diet/preferences/${likes.id}?version=${likes.version}`, 'DELETE');
      }
      draftPending.current = false; p.refresh(); setOpen(false); p.notify('个人资料已保存在本机');
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <><button className="button secondary" onClick={show}><UserRound size={16}/>个人资料与喜好</button>
    {open && <dialog ref={dialog} className="dialog health-profile-dialog" aria-label="个人资料与喜好" onCancel={e => { if (busy) e.preventDefault(); else setOpen(false); }}><div className="dialog-head"><h2>个人资料与喜好</h2><IconButton label="关闭个人资料" onClick={() => { if (!busy) setOpen(false); }}><X size={20}/></IconButton></div><div className="form-body">
      <button className="health-photo-upload" disabled={busy} onClick={() => file.current?.click()}><Camera size={24}/><span><strong>上传体测报告 / 身体资料照片</strong><small>保存本地附件；本项目不含自动文字提取服务</small></span></button><input ref={file} type="file" className="sr-only" accept="image/png,image/jpeg,image/webp" aria-label="体测资料照片" onChange={e => void upload(e.target.files?.[0])}/>
      <label className="field"><span>本次资料 / 测量日期</span><input type="date" max={overview.today?.date} value={observedAt} onChange={e => setObservedAt(e.target.value)}/></label>
      {reportSource && <p role="status">已填入报告「{reportSource}」。请核对报告上的测量日期；日期不明时先不要保存为当前资料。</p>}
      <label className="field"><span>想达到什么目标</span><select value={values['目标'] || ''} onChange={e => setValues({ ...values, 目标: e.target.value })}><option value="" disabled>选择目标</option>{['增肌', '减脂', '保持现状'].map(goal => <option key={goal} value={goal}>{goal}</option>)}</select></label>
      <fieldset className="food-likes"><legend>喜欢吃什么</legend><div className="food-likes-grid">{foodGroups.map(group => <label className="field" key={group.key}><span>{group.label}</span><textarea rows={3} maxLength={200} value={values.food_likes?.[group.key] || ''} onChange={e => setValues({ ...values, food_likes: { ...values.food_likes, [group.key]: e.target.value } })} placeholder={group.placeholder}/></label>)}</div></fieldset>
      {values.food_likes?.previous && <details><summary>以前保存的喜好</summary><label className="field"><span>原有内容（可以分到上面四列）</span><textarea maxLength={1000} value={values.food_likes.previous} onChange={e => setValues({ ...values, food_likes: { ...values.food_likes, previous: e.target.value } })}/></label></details>}
      <details open={expanded} onToggle={e => setExpanded(e.currentTarget.open)}><summary>基本信息</summary><div className="profile-fields">{fields.map(([key, unit, type]) => <label className={`field ${type === 'textarea' ? 'activity-field' : ''}`} key={key}><span>{key === '活动量' ? '每周活动与运动安排' : key}{unit && ` · ${unit}`}</span>{type.includes('|') ? <select value={values[key] || ''} onChange={e => setValues({ ...values, [key]: e.target.value })}><option value="">暂未填写</option>{type.split('|').map(v => <option key={v}>{v}</option>)}</select> : type === 'textarea' ? <textarea rows={3} maxLength={2000} value={values[key] || ''} onChange={e => setValues({ ...values, [key]: e.target.value })} placeholder="例如：每周力量3次，每次60分钟；有氧2次，每次30分钟。"/> : <input type={type} step="any" value={values[key] ?? ''} onChange={e => setValues({ ...values, [key]: e.target.value })} placeholder={key === '特殊健康情况' ? '孕哺、疾病或医生要求；没有可留空' : key === '忌口' ? '不吃什么 / 过敏（如有请填写）' : ''}/>}</label>)}</div></details>
      {uploads.length > 0 && <details className="health-upload-history" open><summary>已上传的体测资料</summary>{uploads.map(row => { const report = reports.find(r => r.data.record_id === row.id && r.data.input_refs?.some((ref: any) => ref.id === row.id && ref.version === row.version)); const job = overview.jobs?.find((j: any) => j.input?.record_id === row.id), running = ['queued', 'running'].includes(job?.status); return <article key={row.id}><img src={'/api/v1/assets/' + row.data.assets[0]} alt={row.data.title}/><div><strong>{row.data.title}</strong>{report ? <><p>{report.data.summary}</p>{report.data.facts.map((f: any, i: number) => <p key={i}>{f.key}：{f.value} {f.unit}<small>原文：{f.evidence}</small></p>)}{report.data.facts.length > 0 && <button className="text-button" onClick={() => { const draft = { ...values }; for (const f of report.data.facts) draft[f.key] = f.value; setValues(draft); setObservedAt(''); setReportSource(row.data.title); setReportKeys(report.data.facts.map((f: any) => f.key)); setExpanded(true); p.notify('已填入草稿，请核对原报告日期后保存'); }}>填入上方，核对后保存</button>}</> : <p>{running ? '正在提取，请稍候…' : job?.status === 'failed' ? '本次提取未完成，可以重试。' : '已保存在本机'}</p>}<div className="row"><button className="text-button" disabled={busy || running} onClick={async () => { try { await analyze(row); } catch (e) { setError((e as Error).message); } }}>{report ? '重新提取' : '提取数据'}</button><button className="text-button danger-text" onClick={() => p.remove('diet/uploads', row)}>删除</button></div></div></article>; })}</details>}
      {error && <p className="error" role="alert">{error}</p>}
    </div><div className="dialog-foot"><button className="button secondary" disabled={busy} onClick={() => setOpen(false)}>关闭</button><button className="button" disabled={busy} onClick={save}>{busy ? <LoaderCircle className="spin" size={16}/> : <Check size={16}/>}保存到本机</button></div></dialog>}{analysis.consent}</>;
}
