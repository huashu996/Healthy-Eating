import { useCallback, useEffect, useState } from 'react';
import { api, initSession } from './lib';
import type { ModuleId, Row } from './lib';
import { Editor } from './components';
import type { Field } from './components';
import { DietPage } from './DietPage';
import { DietHistory } from './DietHistory';

type EditState = { title: string; path: string; fields: Field[]; row?: Row; initial: any; module?: ModuleId; photoKey?: string; customSave?: (data: any) => Promise<void> };
export type PageProps = { data: Record<string, any>; refreshing?: boolean; edit: (state: EditState) => void; remove: (path: string, row: Row) => void; run: (module: ModuleId, operation: string, input?: any) => Promise<void>; navigate: (path: string) => void; notify: (text: string) => void; refresh: () => void };
export function App() {
  const [path, setPath] = useState(() => location.pathname + location.search);
  const [phoneView, setPhoneView] = useState(() => localStorage.getItem('diet-view') !== 'wide');
  const navigate = useCallback((next: string) => { history.pushState(null, '', next); setPath(next); window.scrollTo(0, 0); }, []);
  useEffect(() => { const update = () => setPath(location.pathname + location.search); window.addEventListener('popstate', update); return () => window.removeEventListener('popstate', update); }, []);
  useEffect(() => { document.title = path.startsWith('/diet/history') ? '历史记录 · 饮食健康' : '饮食健康 · 专用面板'; }, [path]);

  const [data,setData]=useState<Record<string,any>>({}),[ready,setReady]=useState(false),[error,setError]=useState(''),[toast,setToast]=useState(''),[revision,setRevision]=useState(0),[loadedRevision,setLoadedRevision]=useState(-1),[editor,setEditor]=useState<EditState|null>(null);
  const refresh=useCallback(()=>setRevision(v=>v+1),[]);
  useEffect(()=>{initSession().then(()=>setReady(true)).catch(e=>setError(e.message));},[]);
  useEffect(()=>{if(!ready)return;let active=true;Promise.all(['diet/overview','diet/preferences','diet/body-metrics'].map(async p=>[p,await api(p)])).then(r=>{if(active){setData(Object.fromEntries(r));setLoadedRevision(revision);}}).catch(e=>{if(active){setError(e.message);setLoadedRevision(revision);}});return()=>{active=false;};},[ready,revision]);
  useEffect(()=>{if(!toast)return;const t=setTimeout(()=>setToast(''),6000);return()=>clearTimeout(t);},[toast]);
  const props:PageProps={data,refreshing:loadedRevision!==revision,edit:setEditor,refresh,notify:setToast,navigate,run:async()=>setToast('本项目不含图片分析服务；请通过本地 API / CLI 导入已核对的结构化结果'),remove:async(path,row)=>{if(!confirm('删除此记录？'))return;try{await api(`${path}/${row.id}?version=${row.version}`,'DELETE');refresh();}catch(e){setError((e as Error).message);}}};
  return <div className={"app simplified-page" + (phoneView ? " diet-phone-view" : "")}><div className="workspace"><main id="main" className="main simple-main">{error&&<div role="alert" className="error">{error}</div>}{data['diet/overview']?(path.startsWith('/diet/history') ? <DietHistory path={path} today={data['diet/overview'].today.date} navigate={navigate}/> : <DietPage {...props}/>):<p>正在读取…</p>}<div className="health-window-actions"><button className="text-button" onClick={() => { const next = !phoneView; setPhoneView(next); localStorage.setItem('diet-view', next ? 'phone' : 'wide'); }}>{phoneView ? '展开页面' : '手机竖屏'}</button><button className="text-button" onClick={() => { const panel = window.open('/diet/health', 'diet-health-panel', 'popup=yes,width=500,height=844,resizable=yes,scrollbars=yes'); if (!panel) setToast('独立窗口被浏览器拦截，可继续使用当前专用页面。'); else panel.focus(); }}>独立窗口</button></div><details className="diet-usage-note"><summary>本地记录 · 07:00 饮食日分界</summary><p>本机保存记录；图片分析结果需自行提供并校验。07:00是饮食日分界，不代表内置自动任务；结算由操作者手动触发。</p></details></main></div>{toast&&<div role="status" className="toast">{toast}</div>}{editor&&<Editor {...editor} onClose={()=>setEditor(null)} onSave={async values=>{if(editor.customSave)await editor.customSave(values);else await api(editor.path+(editor.row?'/'+editor.row.id:''),editor.row?'PATCH':'POST',{version:editor.row?.version,data:values});refresh();}}/>}</div>;
}
