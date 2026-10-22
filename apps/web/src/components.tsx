import { useEffect, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { ArrowUpRight, Check, ChevronRight, FileText, LoaderCircle, Plus, X } from 'lucide-react';
import { api, fmtDate, safeUrl, statuses } from './lib';
import type { ModuleId, Row } from './lib';

export function IconButton({ label, children, onClick }: { label: string; children: ReactNode; onClick: () => void }) { return <button type="button" className="icon-button" aria-label={label} title={label} onClick={onClick}>{children}</button>; }
export function Badge({ value, children }: { value?: string; children?: ReactNode }) { return <span className={`badge ${value || ''}`}>{children || statuses[value || ''] || value}</span>; }
export function Empty({ title, detail, action }: { title: string; detail: string; action?: ReactNode }) { return <div className="empty"><div className="empty-symbol"><Plus size={24}/></div><h3>{title}</h3><p>{detail}</p>{action}</div>; }
export function Panel({ title, subtitle, action, children, className = '' }: { title?: string; subtitle?: string; action?: ReactNode; children: ReactNode; className?: string }) { return <section className={`panel ${className}`}>{title && <div className="panel-head"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</div>}{children}</section>; }
export function Stat({ label, value, detail }: { label: string; value: ReactNode; detail: string }) { return <div className="stat"><p>{label}</p><strong>{value}</strong><small>{detail}</small></div>; }
export function Link({ href, children }: { href: string; children: ReactNode }) { return <a className="source-link" href={safeUrl(href)} target="_blank" rel="noreferrer">{children}<ArrowUpRight size={14}/></a>; }
export function Report({ report }: { report: any }) {
  const d = report.data || report;
  return <article className="report"><div className="row between"><h3>{d.title || '任务结果'}</h3><Badge value={report.status || d.status}/></div>{report.business_date && <p className="meta">{report.business_date} · {report.timezone} · 第 {report.version} 版 · {fmtDate(report.created_at)}</p>}<p>{d.summary}</p>
    {d.items?.map((item: string, i: number) => <p key={i} className="report-item"><Check size={15}/>{item}</p>)}
    {d.advice?.map((advice: any, i: number) => <div className="advice" key={i}><p>{advice.text}</p><small>{advice.reason}</small><Link href={advice.evidence.url}>{advice.evidence.title} · {advice.evidence.year}</Link><details><summary>证据与不确定性</summary><p>{advice.evidence.type} · {advice.evidence.publisher}</p><p>{advice.evidence.population}</p><p>{advice.evidence.grading}</p><p>{advice.uncertainty}</p><p>核验：{advice.evidence.checked_at}</p></details></div>)}
    {d.sections && <dl className="brief-sections">{Object.entries(d.sections).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{Array.isArray(value) ? value.length ? value.join('；') : '暂无已确认偏好' : String(value)}</dd></div>)}</dl>}
    {d.citations?.map((citation: any, i: number) => <blockquote key={i}><p>{citation.text}</p><footer>{citation.title} · v{citation.version} · {citation.locator}</footer></blockquote>)}
    {d.observations?.map((o: any, i: number) => <p key={i}>{o.price} {o.currency} · {o.as_of} · {o.source}</p>)}
    {d.input_refs?.length > 0 && <details><summary>引用了 {d.input_refs.length} 条资料版本</summary>{d.input_refs.map((r: any, i: number) => <p className="meta" key={i}>{r.id.slice(0, 8)} · v{r.version}</p>)}</details>}
    {d.limitations?.length > 0 && <div className="note">{d.limitations.map((l: string, i: number) => <p key={i}>{l}</p>)}</div>}
  </article>;
}

export type Field = { key: string; label: string; type?: 'text' | 'textarea' | 'number' | 'date' | 'datetime-local' | 'select' | 'check' | 'tags' | 'numbers' | 'dates'; required?: boolean; options?: { value: string; label: string }[]; placeholder?: string; help?: string; min?: number; max?: number };
export function Editor({ title, fields, initial, onSave, onClose, module, photoKey, projectId }: { title: string; fields: Field[]; initial: any; onSave: (data: any) => Promise<void>; onClose: () => void; module?: ModuleId; photoKey?: string; projectId?: string }) {
  const [data, setData] = useState<any>({ ...initial }); const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [files, setFiles] = useState<File[]>([]); const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { const el = dialog.current!; el.showModal(); return () => el.close(); }, []);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const result = { ...data };
      for (const field of fields) {
        const value = result[field.key];
        if (field.type === 'number') result[field.key] = value === '' || value == null ? null : Number(value);
        if (['tags', 'numbers', 'dates'].includes(field.type || '')) { const values = Array.isArray(value) ? value : String(value || '').split(/[,，\n]+/).map(s => s.trim()).filter(Boolean); result[field.key] = field.type === 'numbers' ? values.map(Number) : values; }
        if (field.type === 'date' && !value) result[field.key] = null;
        if (field.type === 'datetime-local' && value) result[field.key] = new Date(value).toISOString();
      }
      if (photoKey && module && files.length) {
        const ids: string[] = [];
        for (const file of files) { const form = new FormData(); form.append('file', file); form.append('module', module); if (projectId) form.append('project_id', projectId); ids.push((await api('assets', 'POST', form)).id); }
        result[photoKey] = photoKey === 'assets' ? [...(result[photoKey] || []), ...ids] : ids[0];
      }
      await onSave(result); onClose();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <dialog ref={dialog} className="dialog" onCancel={onClose}><form onSubmit={submit}><div className="dialog-head"><h2>{title}</h2><IconButton label="关闭" onClick={onClose}><X size={20}/></IconButton></div><div className="form-body">{fields.map(field => {
    let value = data[field.key] ?? '';
    if (field.type === 'datetime-local' && /(Z|[+-][0-9]{2}:[0-9]{2})$/.test(value)) { const date = new Date(value); value = new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16); }
    const props = { id: `field-${field.key}`, name: field.key, required: field.required, placeholder: field.placeholder, value: Array.isArray(value) ? value.join(', ') : value, onChange: (event: any) => setData({ ...data, [field.key]: event.target.value }) };
    return <label className={field.type === 'check' ? 'check-field' : 'field'} key={field.key} htmlFor={props.id}>{field.type === 'check' ? <><input id={props.id} type="checkbox" checked={Boolean(value)} onChange={e => setData({ ...data, [field.key]: e.target.checked })}/><span>{field.label}</span></> : <><span>{field.label}{field.required && <em> *</em>}</span>{field.type === 'textarea' || ['numbers', 'dates'].includes(field.type || '') ? <textarea {...props} rows={3}/> : field.type === 'select' ? <select {...props}><option value="">请选择</option>{field.options?.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select> : <input {...props} type={['number', 'date', 'datetime-local'].includes(field.type || '') ? field.type : 'text'} step={field.type === 'number' ? 'any' : undefined} min={field.min} max={field.max}/>}</>}{field.help && <small>{field.help}</small>}</label>;
  })}{photoKey && <label className="upload-field"><Plus size={24}/><span>添加照片</span><small>JPG / PNG / WebP，单张不超过 12MB；导入时移除 EXIF 位置信息</small><input type="file" accept="image/jpeg,image/png,image/webp" multiple={photoKey === 'assets'} onChange={e => setFiles(Array.from(e.target.files || []))}/>{files.length > 0 && <b>{files.length} 张待保存</b>}</label>}{error && <p className="error" role="alert">{error}</p>}</div><div className="dialog-foot"><button type="button" className="button secondary" onClick={onClose}>取消</button><button className="button" disabled={busy}>{busy ? <LoaderCircle className="spin" size={17}/> : <Check size={17}/>}保存到本机</button></div></form></dialog>;
}

export function RecordActions({ row, edit, remove }: { row: Row; edit: () => void; remove: () => void }) { return <div className="record-actions"><span className="meta">v{row.version} · {fmtDate(row.updated_at)}</span><button className="text-button" onClick={edit}>编辑</button><button className="text-button danger-text" onClick={remove}>删除</button></div>; }
export function SectionLink({ children, onClick }: { children: ReactNode; onClick: () => void }) { return <button className="section-link" onClick={onClick}><FileText size={16}/>{children}<ChevronRight size={16}/></button>; }


