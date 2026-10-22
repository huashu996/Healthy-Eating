import { useEffect, useRef } from 'react';
type Point = {date:string;value:number;recorded_at?:string};
export function BodyTrend({kind,points,onClose}:{kind:'weight'|'body_fat';points:Point[];onClose:()=>void}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(()=>{ const node=dialog.current; node?.showModal(); return()=>node?.close(); },[]);
  const weight=kind==='weight', title=weight?'体重趋势':'体脂趋势', unit=weight?'kg':'%';
  const rows=[...points].filter(p=>Number.isFinite(p.value)&&/^\d{4}-\d{2}-\d{2}$/.test(p.date)).sort((a,b)=>a.date.localeCompare(b.date)||(a.recorded_at||'').localeCompare(b.recorded_at||''));
  const times=rows.map(p=>Date.parse(p.date+'T00:00:00Z'));
  const lo=Math.min(...rows.map(p=>p.value)),hi=Math.max(...rows.map(p=>p.value)),pad=Math.max((hi-lo)*.2,weight?.2:.3);
  const low=lo-pad,high=hi+pad,first=times[0],last=times[times.length-1];
  const x=(i:number)=>first===last?180:52+(times[i]-first)/(last-first)*260;
  const y=(v:number)=>180-(v-low)/(high-low)*140;
  return <dialog ref={dialog} className="body-trend-dialog" aria-label={title} onCancel={onClose} onClick={e=>{if(e.target===e.currentTarget)onClose();}}>
    <div className="body-trend-head"><h2>{title}</h2><button onClick={onClose} aria-label="关闭趋势图">×</button></div>
    {rows.length ? <><p className="body-trend-value">{rows[rows.length-1].value} <span>{unit}</span></p>
    <svg viewBox="0 0 360 224" role="img" aria-label={`${title}，${rows.length}条日期记录，单位${unit}`}>
      {[0,.5,1].map(t=><g key={t}><line x1="52" x2="312" y1={40+t*140} y2={40+t*140} stroke="#E9EBEF"/><text x="46" y={44+t*140} textAnchor="end" fill="#5F6672" fontSize="12">{(high-t*(high-low)).toFixed(1)}</text></g>)}
      {rows.length>1&&<polyline points={rows.map((p,i)=>`${x(i)},${y(p.value)}`).join(' ')} fill="none" stroke={weight?'#709AD7':'#77A98F'} strokeWidth="2.5" strokeLinejoin="round"/>}
      {rows.map((p,i)=><circle key={`${p.date}-${p.recorded_at||i}`} cx={x(i)} cy={y(p.value)} r="4" fill={weight?'#709AD7':'#77A98F'}><title>{p.date}：{p.value} {unit}</title></circle>)}
      <text x={rows[0].date===rows[rows.length-1].date?180:52} y="209" textAnchor={rows[0].date===rows[rows.length-1].date?'middle':'start'} fontSize="12" fill="#5F6672">{rows[0].date.slice(5).replace('-','.')}</text>
      {rows[0].date!==rows[rows.length-1].date&&<text x="312" y="209" textAnchor="end" fontSize="12" fill="#5F6672">{rows[rows.length-1].date.slice(5).replace('-','.')}</text>}
    </svg><p className="body-trend-note">{rows.length===1?'已有1条记录，新增测量后显示连线。':'每天保留一个数值，未测日期不补值。'}</p>
    <details><summary>测量记录 · {rows.length}条</summary><ul className="body-trend-list">{rows.map((p,i)=><li key={`${p.date}-${p.recorded_at||i}`}><time dateTime={p.date}>{p.date}</time><span>{p.value} {unit}</span></li>)}</ul></details></> : <p>暂无有日期的记录</p>}
  </dialog>;
}
