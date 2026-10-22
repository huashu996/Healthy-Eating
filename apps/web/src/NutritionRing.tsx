import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { ringEase } from './ringAnimation';
import { Flame, Beef, Droplet, Wheat } from 'lucide-react';
import { nutrientPoint, nutrientProgress, nutrientAmountLabel } from './dietDisplay';
import type { NutrientRange } from './dietDisplay';

export function NutritionRing({ name, unit, value, target, color, coverage, meals, labels, finished }: { name: string; unit: string; value: NutrientRange; target?: number; color: string; coverage?: number; meals: number; labels?: number; finished: boolean }) {
  const Icon = name === '热量' ? Flame : name === '蛋白质' ? Beef : name === '脂肪' ? Droplet : Wheat;
  const amount = nutrientPoint(value), percent = nutrientProgress(amount, target);
  const shown = useAnimatedPercent(percent ?? 0);
  const formatted = amount === null ? '—' : nutrientAmountLabel(value);
  const targetFormatted = target && Number.isFinite(target) && target > 0 ? target.toLocaleString('zh-CN', { useGrouping: false }) : '—';
  const incomplete = amount !== null && ((coverage || 0) < meals || !finished);
  const status = amount === null ? (meals ? '待分析' : '待记录') : `${labels === coverage ? '标签记录' : '估算记录'}${incomplete ? ' · 部分记录' : ''}`;
  return <article className="nutrition-ring" style={{ '--ring-color': color } as CSSProperties} aria-label={`${name}：已记录${formatted}${unit}，${targetFormatted !== '—' ? `参考目标${targetFormatted}${unit}` : '参考目标待完善'}${percent === null ? '' : `，${percent}%`}，${status}`}>
    <div className="ring-visual">
      <svg viewBox="0 0 160 160" aria-hidden="true"><circle className="ring-track" cx="80" cy="80" r="68"/>{percent !== null && percent > 0 && <circle className="ring-fill" cx="80" cy="80" r="68" pathLength="100" strokeDasharray={`${Math.min(100, shown)} 100`}/>}</svg>
      <div className="ring-value"><strong>{percent === null ? '—' : `${Math.round(shown)}%`}</strong></div>
    </div><h3 className="nutrient-label"><Icon aria-hidden="true"/>{name}</h3><p className="ring-caption">已摄入 {formatted} / 推荐 {targetFormatted} {unit === '大卡' ? 'kcal' : unit}</p>
    <p className="ring-percent sr-only"><span>{percent !== null && percent > 100 ? `${status} · 超过参考目标` : status}</span></p>
  </article>;
}

function useAnimatedPercent(target: number) {
  const [shown,setShown]=useState(target), current=useRef(0);
  useEffect(()=>{
    const media=window.matchMedia('(prefers-reduced-motion: reduce)');let frame=0;
    const from=current.current,start=performance.now();
    const tick=(now:number)=>{const p=media.matches?1:Math.min(1,(now-start)/800);current.current=from+(target-from)*ringEase(p);setShown(current.current);if(p<1)frame=requestAnimationFrame(tick);};
    frame=requestAnimationFrame(tick);
    return()=>cancelAnimationFrame(frame);
  },[target]);
  return shown;
}
