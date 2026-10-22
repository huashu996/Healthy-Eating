import { useEffect, useState } from 'react';
import type { ModuleId } from './lib';

// Local-only distribution: no model, chat connector, or scheduled worker is bundled.
export function usePrivateAnalysis(refresh:()=>void) {
  const [notice,setNotice]=useState(false);
  async function prepare(...args:[ModuleId,string,any,string]){void args;setNotice(true);refresh();}
  const consent=notice&&<div className="note" role="status">附件已保存在本机。本项目不含自动分析服务，请自行核对并通过本地 API / CLI 提交结构化结果。<button className="text-button" onClick={()=>setNotice(false)}>知道了</button></div>;
  return {prepare,consent};
}
export function useJobRefresh(_jobs:any[],refresh:()=>void){useEffect(()=>{const t=setInterval(refresh,15000);return()=>clearInterval(t);},[refresh]);}
