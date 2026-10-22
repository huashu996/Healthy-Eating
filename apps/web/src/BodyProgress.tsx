import { useEffect, useRef, useState } from 'react';
import { LoaderCircle, Scale, X } from 'lucide-react';
import type { PageProps } from './App';
import { api } from './lib';
import { IconButton } from './components';

export function BodyProgress(p: PageProps) {
  const overview = p.data['diet/overview'] || {}, progress = overview.body_progress || {};
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [weight, setWeight] = useState(''), [fat, setFat] = useState(''), [day, setDay] = useState(''), [review, setReview] = useState<any>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { if (open) dialog.current?.showModal(); }, [open]);
  function show() { setWeight(String(progress.current?.weight_kg || '')); setFat(''); setDay(new Intl.DateTimeFormat('sv-SE', {timeZone:'Asia/Shanghai'}).format(new Date())); setReview(null); setError(''); setOpen(true); }
  async function save() {
    setBusy(true); setError('');
    try {
      await api('diet/checkins', 'POST', { data: { measured_on: day, weight_kg: Number(weight), body_fat_pct: fat === '' ? null : Number(fat) } });
      const updated = await api('diet/overview'); setReview(updated.body_progress.review); p.refresh();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <><button className="button secondary" onClick={show}><Scale size={16}/>更新体重 / 体脂</button>
    {open && <dialog ref={dialog} className="dialog body-checkin-dialog" aria-label="更新体重与体脂" onCancel={e => { if (busy) e.preventDefault(); else setOpen(false); }}>
      <div className="dialog-head"><h2>{review ? '本次测量与回顾' : '更新体重与体脂'}</h2><IconButton label="关闭体重更新" onClick={() => { if (!busy) setOpen(false); }}><X size={20}/></IconButton></div>
      <div className="form-body">{review ? <div className="checkin-review"><p>{review.summary}</p>{review.target && <div className="updated-targets">{[['kcal', '热量', '大卡'], ['protein_g', '蛋白质', 'g'], ['fat_g', '脂肪', 'g'], ['carbs_g', '碳水', 'g']].map(([key, name, unit]) => <div key={key}><span>{name}</span><strong>{review.target[key]}<small>{unit}</small></strong></div>)}</div>}<ul>{review.suggestions.map((s: string) => <li key={s}>{s}</li>)}</ul></div> : <>
        <label className="field"><span>测量日期</span><input type="date" max={new Intl.DateTimeFormat('sv-SE', {timeZone:'Asia/Shanghai'}).format(new Date())} value={day} onChange={e => setDay(e.target.value)}/></label>
        <div className="profile-fields"><label className="field"><span>体重 · kg</span><input type="number" min="10" max="500" step="0.1" value={weight} onChange={e => setWeight(e.target.value)}/></label><label className="field"><span>体脂率 · %（可选）</span><input type="number" min="1" max="75" step="0.1" value={fat} onChange={e => setFat(e.target.value)}/></label></div>
      </>}{error && <p className="error" role="alert">{error}</p>}</div>
      <div className="dialog-foot">{review ? <button className="button" onClick={() => setOpen(false)}>完成</button> : <button className="button" disabled={busy || !weight || !day} onClick={save}>{busy && <LoaderCircle className="spin" size={16}/>}保存测量</button>}</div>
    </dialog>}</>;
}
